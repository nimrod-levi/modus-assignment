"""Re-grade a saved results file with the current grader and question file: python -m eval.regrade <results.json>

Used after an eval fix (a grader or question change) to show its effect on an earlier run without calling the model
again. The stored answers are graded again; gold is recomputed from gold_sql. The original file is not changed: the
output goes to <name>_regraded.json, and each verdict that flipped is printed. No scoreboard row is added.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent import db
from eval import grade as grading
from eval.run_eval import EVAL_DIR, RETRY_PENALTY, load_questions, summarize


def regrade(path: Path) -> tuple[dict, list[str]]:
    data = json.loads(path.read_text())
    suite = data["meta"]["suite"]
    questions = {q["id"]: q for q in load_questions(EVAL_DIR / f"{suite}.yaml")}
    con = db.connect()
    golds = {qid: grading.compute_gold(con, q) for qid, q in questions.items()}
    con.close()
    flips = []
    for r in data["records"]:
        if r["error"] or r["id"] not in questions:
            continue
        g = grading.grade(questions[r["id"]], golds[r["id"]], r["answer"])
        if g.passed != r["passed"]:
            flips.append(f"{r['id']} run {r['run']}: {'P' if r['passed'] else 'F'} -> {'P' if g.passed else 'F'} ({g.reason})")
        r.update(passed=g.passed, reason=g.reason,
                 credit=max(0.0, 1 - RETRY_PENALTY * r.get("rejections", 0)) if g.passed else 0.0)
    runs = max(r["run"] for r in data["records"]) + 1
    data["summary"] = summarize([questions[i] for i in {r["id"] for r in data["records"]}], data["records"], runs)
    data["meta"]["regraded_from"] = path.name
    return data, flips


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.regrade", description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args(argv)
    data, flips = regrade(args.results)
    out = args.results.with_name(args.results.stem + "_regraded.json")
    out.write_text(json.dumps(data, indent=2, default=str))
    print("\n".join(flips) or "no verdict changed")
    print(f"score {data['summary']['score']:.1%} · pass_all {data['summary']['pass_all']:.1%} · {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
