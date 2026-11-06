"""Run the eval: python -m eval.run_eval --step step-00-baseline

For each question: compute the gold answer from gold_sql, run the agent --runs times,
grade each run deterministically, write eval/results/<step>_<timestamp>.json and (for a
full run) append one row to eval/scoreboard.csv.

Score = mean over questions of the credit per run. A passed run earns 1 - 0.1 per rejected tool call
(min 0); a failed run earns 0. raw_score is the plain pass rate.
pass^k = fraction of questions where ALL k runs passed (the reliability number).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import types
from collections import defaultdict
from pathlib import Path
from typing import Callable

import yaml

from agent import db
from agent.__main__ import load_dotenv
from agent.agent import AgentConfig, ask, make_client
from eval import grade as grading

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = EVAL_DIR / "questions.yaml"
RESULTS_DIR = EVAL_DIR / "results"
SCOREBOARD = EVAL_DIR / "scoreboard.csv"
SCOREBOARD_FIELDS = [
    "timestamp", "step", "suite", "git_sha", "dirty", "model", "system_prompt_sha",
    "questions", "runs", "score", "raw_score", "pass_all", "errors", "rejections", "tokens_per_run", "sql_calls_per_run",
]


MAX_WAIT_S = 120.0  # longest rate-limit wait we accept before giving up
RETRY_PENALTY = 0.1  # credit lost per rejected tool call


class ThrottledClient:
    """Wraps the model client: spaces calls out and retries on 429 (rate limit).

    The agent takes a `client=` argument, so the eval can add this without touching agent code.
    """

    def __init__(self, client, min_interval_s: float = 0.5, max_retries: int = 6, sleep=time.sleep,
                 max_wait_s: float = MAX_WAIT_S):
        self._client = client
        self._min_interval = min_interval_s
        self._max_retries = max_retries
        self._sleep = sleep
        self._max_wait = max_wait_s
        self._last_call = 0.0
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        for attempt in range(self._max_retries + 1):
            wait = self._last_call + self._min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            try:
                return self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                if getattr(exc, "status_code", None) != 429 or attempt == self._max_retries:
                    raise
                delay = _retry_delay_s(exc)
                if delay > self._max_wait:
                    # A daily token limit asks for many minutes. Do not sleep silently: fail with the reason.
                    raise RuntimeError(f"rate limit: provider asks to wait {delay:.0f}s (> {self._max_wait:.0f}s): {exc}") from exc
                print(f"  rate limited, waiting {delay:.0f}s", flush=True)
                self._sleep(delay)


def _retry_delay_s(exc: Exception) -> float:
    """Seconds the provider asks us to wait (Retry-After header, or 'try again in 7.66s'), else 30."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    if headers.get("retry-after"):
        return float(headers["retry-after"]) + 1
    match = re.search(r"try again in (?:(\d+)m)?([0-9.]+)s", str(exc))
    return int(match.group(1) or 0) * 60 + float(match.group(2)) + 1 if match else 30.0


def load_questions(path: Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    questions = data.get("questions") or []
    seen: set[str] = set()
    for q in questions:
        for key in ("id", "category", "question", "grader"):
            if not q.get(key):
                raise ValueError(f"{path}: question {q.get('id', '?')} is missing {key!r}")
        if q["id"] in seen:
            raise ValueError(f"{path}: duplicate id {q['id']!r}")
        seen.add(q["id"])
        kind = q["grader"].get("type")
        if kind not in grading.GRADER_TYPES:
            raise ValueError(f"{path}: {q['id']}: grader.type must be one of {grading.GRADER_TYPES}")
        if kind in ("number", "set", "table") and not q.get("gold_sql"):
            raise ValueError(f"{path}: {q['id']}: {kind} questions need gold_sql")
    return questions


def run_question(question: dict, gold, runs: int, ask_fn: Callable[[str], dict]) -> list[dict]:
    records = []
    for i in range(runs):
        record: dict = {"id": question["id"], "run": i, "error": None}
        try:
            trace = ask_fn(question["question"])
        except Exception as exc:  # API failure, not an agent failure: keep going, count separately
            record.update(passed=False, reason=f"agent error: {type(exc).__name__}: {exc}", error=True)
            records.append(record)
            continue
        g = grading.grade(question, gold, trace["answer"])
        rejections = trace.get("tool_rejections", 0)
        usage = trace["usage"]
        record.update(
            passed=g.passed,
            reason=g.reason,
            error=False,
            rejections=rejections,
            credit=max(0.0, 1 - RETRY_PENALTY * rejections) if g.passed else 0.0,
            end_reason=trace["end_reason"],
            answer=trace["answer"],
            model=trace["model"],
            provider=trace.get("provider"),
            system_prompt_sha=trace["system_prompt_sha"],
            glossary_sha=trace.get("glossary_sha"),
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            sql_calls=trace["sql_calls"],
            latency_ms=trace["latency_ms"],
            steps=trace["steps"],
        )
        records.append(record)
    return records


def summarize(questions: list[dict], records: list[dict], runs: int) -> dict:
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_q[r["id"]].append(r)
    per_q = {qid: sum(r.get("credit", float(r["passed"])) for r in rs) / len(rs) for qid, rs in by_q.items()}
    raw = {qid: sum(r["passed"] for r in rs) / len(rs) for qid, rs in by_q.items()}
    category = {q["id"]: q["category"] for q in questions}
    by_cat: dict[str, list[float]] = defaultdict(list)
    for qid, frac in per_q.items():
        by_cat[category[qid]].append(frac)
    ok = [r for r in records if not r["error"]]
    return {
        "questions": len(per_q),
        "runs": runs,
        "score": sum(per_q.values()) / len(per_q) if per_q else 0.0,
        "raw_score": sum(raw.values()) / len(raw) if raw else 0.0,
        "pass_all": sum(f == 1.0 for f in raw.values()) / len(raw) if raw else 0.0,
        "rejections": sum(r.get("rejections", 0) for r in records),
        "errors": sum(r["error"] for r in records),
        "tokens_per_run": sum(r["input_tokens"] + r["output_tokens"] for r in ok) / len(ok) if ok else 0,
        "sql_calls_per_run": sum(r["sql_calls"] for r in ok) / len(ok) if ok else 0,
        "per_question": per_q,
        "per_category": {c: sum(v) / len(v) for c, v in sorted(by_cat.items())},
    }


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=db.REPO_ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def append_scoreboard(meta: dict, summary: dict, path: Path = SCOREBOARD) -> None:
    row = {**meta, **{k: summary[k] for k in ("questions", "runs", "errors", "rejections")}}
    row["score"] = f"{summary['score']:.3f}"
    row["raw_score"] = f"{summary['raw_score']:.3f}"
    row["pass_all"] = f"{summary['pass_all']:.3f}"
    row["tokens_per_run"] = round(summary["tokens_per_run"])
    row["sql_calls_per_run"] = f"{summary['sql_calls_per_run']:.1f}"
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCOREBOARD_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.run_eval", description=__doc__)
    parser.add_argument("--step", required=True, help="Label for this run, e.g. step-00-baseline.")
    parser.add_argument("--file", type=Path, default=DEFAULT_QUESTIONS, help="Question file.")
    parser.add_argument("--only", help="Comma-separated question ids. A subset run is not added to the scoreboard.")
    parser.add_argument("--runs", type=int, default=1, help="Runs per question (default 1).")
    parser.add_argument("--min-interval", type=float, default=0.5,
                        help="Seconds between model calls (default 0.5).")
    args = parser.parse_args(argv)

    load_dotenv()
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        return 2

    questions = load_questions(args.file)
    if args.only:
        wanted = set(args.only.split(","))
        unknown = wanted - {q["id"] for q in questions}
        if unknown:
            print(f"Unknown question ids: {sorted(unknown)}", file=sys.stderr)
            return 2
        questions = [q for q in questions if q["id"] in wanted]
    if not questions:
        print(f"No questions in {args.file}.", file=sys.stderr)
        return 2

    con = db.connect()
    golds = {q["id"]: grading.compute_gold(con, q) for q in questions}  # fail fast on a bad gold_sql
    con.close()

    # Read the tree state before this run writes anything; the eval's own outputs do not count as changes.
    dirty = bool(_git("status", "--porcelain", "--", ".", ":!eval/results", ":!eval/scoreboard.csv"))
    config = AgentConfig()
    client = ThrottledClient(make_client(), args.min_interval)
    records: list[dict] = []
    started_at = dt.datetime.now(dt.timezone.utc)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{args.step}_{args.file.stem}_{started_at.strftime('%Y%m%d-%H%M%S')}.json"
    for q in questions:
        recs = run_question(q, golds[q["id"]], args.runs, lambda text: ask(text, client=client, config=config))
        for r in recs:
            r["category"] = q["category"]
            r["gold"] = golds[q["id"]]
        records += recs
        # Save after every question, so a stopped or crashed run keeps what it finished.
        out.write_text(json.dumps({"partial": True, "records": records}, indent=2, default=str))
        marks = "".join("E" if r["error"] else ("P" if r["passed"] else "F") for r in recs)
        print(f"{q['id']:<12} {q['category']:<18} {marks}  {recs[-1]['reason']}")

    summary = summarize(questions, records, args.runs)
    first_ok = next((r for r in records if not r["error"]), {})
    now = dt.datetime.now(dt.timezone.utc)
    meta = {
        "timestamp": now.isoformat(timespec="seconds"),
        "step": args.step,
        "suite": args.file.stem,
        "git_sha": _git("rev-parse", "--short", "HEAD"),
        "dirty": dirty,
        "model": first_ok.get("model", config.model),
        "system_prompt_sha": first_ok.get("system_prompt_sha", ""),
        "glossary_sha": first_ok.get("glossary_sha") or "",
    }
    out.write_text(json.dumps({"meta": meta, "summary": summary, "records": records}, indent=2, default=str))

    full_run = not args.only
    if summary["errors"]:
        full_run = False
        print(f"\n{summary['errors']} runs hit API errors: this run is NOT valid and was not added to the scoreboard.")
    if full_run:
        append_scoreboard(meta, summary)
    print(
        f"\nscore {summary['score']:.1%} · pass^{args.runs} {summary['pass_all']:.1%} · "
        f"{summary['errors']} errors · {summary['tokens_per_run']:,.0f} tokens/run · {out.relative_to(db.REPO_ROOT)}"
        + ("" if full_run else " · subset run, scoreboard not updated")
    )
    for cat, frac in summary["per_category"].items():
        print(f"  {cat:<18} {frac:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
