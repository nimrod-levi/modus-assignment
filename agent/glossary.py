"""Step 4: the customer glossary. Customer-provided knowledge the data and the dbt project cannot hold.

This is the only hand-written context in the agent, and it is kept apart from the generated context (agent/semantic.py):
what a business word means, which rows do not count, what "today" is. Concepts the warehouse lacks are deliberately not listed: the agent has to find that out itself.
The file is glossary/glossary.yaml. Each entry has an owner, a date and a status (confirmed | assumed).

`validate` checks a glossary against the warehouse, so a wrong entry fails when it is written (`make glossary-check`).
`render` turns entries into a labelled block for the agent's first message.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import yaml

from agent import db

GLOSSARY_PATH = db.REPO_ROOT / "glossary" / "glossary.yaml"
KINDS = ("definition", "rule", "reference")
STATUSES = ("confirmed", "assumed")
REQUIRED = ("id", "kind", "text", "status", "owner", "date")
_PLACEHOLDER = re.compile(r":[a-z_]+")


def load(path: Path = GLOSSARY_PATH) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return list(data.get("entries") or [])


def _warehouse_columns(con: duckdb.DuckDBPyConnection) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table, column in con.execute(
        "select table_name, column_name from information_schema.columns where table_schema = 'main'").fetchall():
        out.setdefault(table, set()).add(column)
    return out


def validate(entries: list[dict], con: duckdb.DuckDBPyConnection) -> list[str]:
    """Every problem found, one sentence each. An empty list means the glossary is usable."""
    errors: list[str] = []
    warehouse = _warehouse_columns(con)
    seen: set[str] = set()
    for i, e in enumerate(entries):
        name = e.get("id") or f"entry #{i + 1}"
        for key in REQUIRED:
            if not e.get(key):
                errors.append(f"{name}: missing '{key}'")
        if e.get("id") in seen:
            errors.append(f"{name}: duplicate id")
        seen.add(e.get("id"))
        if e.get("kind") and e["kind"] not in KINDS:
            errors.append(f"{name}: kind '{e['kind']}' is not one of {', '.join(KINDS)}")
        if e.get("status") and e["status"] not in STATUSES:
            errors.append(f"{name}: status '{e['status']}' is not one of {', '.join(STATUSES)}")
        for ref in e.get("applies_to") or []:
            table, _, column = str(ref).partition(".")
            if table not in warehouse:
                errors.append(f"{name}: applies_to '{ref}': no such table")
            elif column and column not in warehouse[table]:
                errors.append(f"{name}: applies_to '{ref}': no such column")
        if e.get("sql"):
            tables = [str(r).partition(".")[0] for r in e.get("applies_to") or []]
            if not tables or tables[0] not in warehouse:
                errors.append(f"{name}: 'sql' needs applies_to to start with an existing table")
                continue
            snippet = _PLACEHOLDER.sub("null", e["sql"])
            try:
                con.execute(f"explain select 1 from main.{tables[0]} where {snippet}")
            except duckdb.Error as exc:
                errors.append(f"{name}: sql does not compile: {str(exc).splitlines()[0]}")
    return errors


def render(entries: list[dict]) -> str:
    """The block sent with the question. Empty string when there is nothing relevant."""
    if not entries:
        return ""
    lines = ["Customer definitions (provided by the customer; they take precedence over anything inferred from the data. \"assumed\" = a draft the customer has not confirmed yet):"]
    for e in entries:
        line = f"- [{e['id']}] {' '.join(str(e['text']).split())}"
        if e.get("sql"):
            line += f" SQL: {e['sql']}"
        if e["status"] == "assumed":
            line += " (assumed)"
        lines.append(line)
    return "\n".join(lines)


def main() -> None:
    entries = load()
    errors = validate(entries, db.connect())
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    by_status = {s: sum(e["status"] == s for e in entries) for s in STATUSES}
    print(f"glossary ok: {len(entries)} entries ({by_status['confirmed']} confirmed, {by_status['assumed']} assumed)")
    print(render(entries))


if __name__ == "__main__":
    main()
