"""Command line: python -m agent "What was our revenue last month?"

Prints the answer and saves the full trace to runs/<timestamp>_<slug>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from agent import db
from agent.agent import AgentConfig, ask, build_system_prompt

RUNS_DIR = db.REPO_ROOT / "runs"


def load_dotenv(path: Path = db.REPO_ROOT / ".env") -> None:
    """Tiny .env loader so we don't need python-dotenv. Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def save_trace(trace: dict) -> Path:
    RUNS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", trace["question"].lower()).strip("-")[:50]
    path = RUNS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug}.json"
    path.write_text(json.dumps(trace, indent=2, default=str))
    return path


def print_trace(trace: dict) -> None:
    for step in trace["steps"]:
        if step["type"] == "text":
            print(f"\n[turn {step['turn']}] {step['text']}")
        else:
            print(f"\n[turn {step['turn']}] SQL ({step['row_count']} rows, {step['elapsed_ms']} ms)")
            print(step["sql"])
            print(step["error"] or step["preview"][:600])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description=__doc__)
    parser.add_argument("question", nargs="?", help="The business question to answer.")
    parser.add_argument("--trace", action="store_true", help="Print every SQL step.")
    parser.add_argument("--schema", action="store_true", help="Print the system prompt and exit.")
    parser.add_argument("--model", help="Override AGENT_MODEL.")
    args = parser.parse_args(argv)

    load_dotenv()

    if args.schema:
        con = db.connect()
        print(build_system_prompt(con))
        return 0
    if not args.question:
        parser.error("give a question, or --schema")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        return 2

    config = AgentConfig(model=args.model) if args.model else AgentConfig()
    trace = ask(args.question, config=config)
    path = save_trace(trace)

    if args.trace:
        print_trace(trace)
    answer = trace["answer"] or {}
    print("\n=== Answer ===")
    print(answer.get("answer", f"(no answer: {trace['end_reason']})"))
    for key in ("status", "numeric_value", "unit", "definition_used", "assumptions"):
        if answer.get(key) not in (None, "", []):
            print(f"{key}: {answer[key]}")
    if answer.get("sql"):
        print(f"sql:\n{answer['sql']}")
    usage = trace["usage"]
    print(
        f"\n{trace['model']} · {trace['sql_calls']} SQL calls · "
        f"{usage['input_tokens']:,} in / {usage['output_tokens']:,} out tokens · "
        f"{trace['latency_ms'] / 1000:.1f}s · trace: {path.relative_to(db.REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
