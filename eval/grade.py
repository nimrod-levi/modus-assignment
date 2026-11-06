"""Deterministic grading. No LLM involved.

Three grader types, set per question under `grader:` in the YAML:

  number  the agent's `numeric_value` must match the gold number within a tolerance,
          and `unit` must match (if the question names one).
  set     every gold item must appear in the agent's answer text (whole-word,
          case-insensitive). Optional `exclude_sql` lists items that must NOT appear.
          Limit: this can't catch extra, unlisted items.
  status  only the submitted `status` is checked (for ambiguous or unanswerable questions).
  table   the agent's `table` ({columns, rows}) must hold exactly the gold rows. Columns are matched by their
          values, not their names, so the agent may name and order them freely and add extra columns. Same row
          count, compared as a multiset (as a list with `ordered: true`). Cells: numbers rounded to `decimals`
          (default 2; "$14.00" counts as 14), text compared like the set grader (case, Unicode spaces, trimmed).

Every question also checks `status`: it must equal `grader.status` (default "answered"; a list
means any of those statuses is accepted).
Gold values come from running `gold_sql` against the warehouse, never from typed numbers.
"""

from __future__ import annotations

import decimal
import itertools
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from agent import db

GRADER_TYPES = ("number", "set", "status", "table")
GOLD_MAX_ROWS = 10_000
DEFAULT_REL_TOL = 0.001  # 0.1%
DEFAULT_ABS_TOL = 0.005  # half a cent
DEFAULT_DECIMALS = 2  # table cells: numbers are compared after rounding to this many decimals


@dataclass
class Grade:
    passed: bool
    reason: str


def _run_gold(con, question: dict, sql: str):
    result = db.run_sql(con, sql, max_rows=GOLD_MAX_ROWS)
    if result.error:
        raise ValueError(f"{question['id']}: gold SQL failed: {result.error}")
    if result.truncated:
        raise ValueError(f"{question['id']}: gold SQL returned more than {GOLD_MAX_ROWS} rows")
    return result


def compute_gold(con, question: dict) -> Any:
    """Run the question's gold_sql. number -> float; set -> {"items", "excluded"}; table -> {"columns", "rows"};
    status -> None."""
    kind = question["grader"]["type"]
    if kind == "status":
        return None
    result = _run_gold(con, question, question["gold_sql"])
    if kind == "table":
        if not result.rows:
            raise ValueError(f"{question['id']}: table gold_sql returned no rows")
        return {"columns": result.columns, "rows": [list(row) for row in result.rows]}
    if kind == "number":
        if result.row_count != 1 or len(result.columns) != 1 or result.rows[0][0] is None:
            raise ValueError(f"{question['id']}: number gold_sql must return exactly one non-null value")
        return float(result.rows[0][0])
    items = sorted({str(row[0]) for row in result.rows if row[0] is not None})
    if not items:
        raise ValueError(f"{question['id']}: set gold_sql returned no rows")
    excluded: list[str] = []
    if question["grader"].get("exclude_sql"):
        excl = _run_gold(con, question, question["grader"]["exclude_sql"])
        excluded = sorted({str(row[0]) for row in excl.rows if row[0] is not None})
    return {"items": items, "excluded": excluded}


def _normalize(text: str) -> str:
    """Lowercase, with Unicode look-alikes made plain: the model writes U+202F / U+00A0 between words and U+2011 in
    'pre-tax'. NFKC turns the odd spaces into ' '; dash variants become '-'; runs of whitespace become one space."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    return re.sub(r"\s+", " ", text).lower()


def _contains_word(text: str, item: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(_normalize(item))}(?![a-z0-9])", _normalize(text)) is not None


def _grade_number(spec: dict, gold: float, answer: dict) -> Grade:
    value = answer.get("numeric_value")
    if value is None:
        return Grade(False, "no numeric_value submitted")
    rel = spec.get("rel_tol", DEFAULT_REL_TOL)
    abs_tol = spec.get("abs_tol", DEFAULT_ABS_TOL)
    if abs(value - gold) > max(abs_tol, rel * abs(gold)):
        return Grade(False, f"numeric_value {value} != gold {gold}")
    if spec.get("unit"):
        accepted = [spec["unit"]] if isinstance(spec["unit"], str) else list(spec["unit"])
        unit = (answer.get("unit") or "").strip().lower()
        if unit not in {u.strip().lower() for u in accepted}:
            return Grade(False, f"unit {answer.get('unit')!r} not in {accepted}")
    return Grade(True, f"numeric_value {value} matches gold {gold}")


def _grade_set(gold: dict, answer: dict) -> Grade:
    text = answer.get("answer") or ""
    missing = [item for item in gold["items"] if not _contains_word(text, item)]
    if missing:
        return Grade(False, f"missing from answer: {missing}")
    present_excluded = [item for item in gold["excluded"] if _contains_word(text, item)]
    if present_excluded:
        return Grade(False, f"answer includes items that should not be there: {present_excluded}")
    return Grade(True, f"all {len(gold['items'])} gold items present")


def _cell(value: Any, decimals: int) -> Any:
    """One table cell, made comparable: numbers (also "$1,234.50" or "6%") rounded, text normalised and trimmed."""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float, decimal.Decimal)):
        return round(float(value), decimals)
    text = _normalize(str(value)).strip()
    try:
        return round(float(text.replace("$", "").replace(",", "").replace("%", "").strip()), decimals)
    except ValueError:
        return text


def _grade_table(spec: dict, gold: dict, answer: dict) -> Grade:
    table = answer.get("table")
    if not isinstance(table, dict):
        return Grade(False, "no table submitted")
    columns, rows = table.get("columns"), table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or any(
        not isinstance(row, list) or len(row) != len(columns) for row in rows
    ):
        return Grade(False, "malformed table: every row must be a list as long as columns")
    if len(rows) != len(gold["rows"]):
        return Grade(False, f"table has {len(rows)} rows, expected {len(gold['rows'])}")
    decimals = spec.get("decimals", DEFAULT_DECIMALS)
    want = [tuple(_cell(v, decimals) for v in row) for row in gold["rows"]]
    have = [[_cell(v, decimals) for v in row] for row in rows]
    k = len(gold["columns"])
    if len(columns) < k:
        return Grade(False, f"table has {len(columns)} columns, expected at least {k}")
    ordered = spec.get("ordered", False)
    # Try every way of picking k agent columns for the k gold columns (tables here have a handful of columns).
    for mapping in itertools.permutations(range(len(columns)), k):
        got = [tuple(row[i] for i in mapping) for row in have]
        if (got == want) if ordered else (Counter(got) == Counter(want)):
            return Grade(True, f"all {len(want)} rows match")
    best = max(  # the mapping that matches most rows, to name a missing one
        itertools.permutations(range(len(columns)), k),
        key=lambda m: sum((Counter(tuple(r[i] for i in m) for r in have) & Counter(want)).values()),
    )
    left = Counter(want) - Counter(tuple(r[i] for i in best) for r in have)
    if not left:
        return Grade(False, "all rows present but in the wrong order")
    return Grade(False, f"{sum(left.values())} gold rows missing, e.g. {next(iter(left))}")


def grade(question: dict, gold: Any, answer: dict | None) -> Grade:
    spec = question["grader"]
    if not answer:
        return Grade(False, "no answer submitted")
    expected = spec.get("status", "answered")
    accepted = [expected] if isinstance(expected, str) else list(expected)
    if answer.get("status") not in accepted:
        return Grade(False, f"status {answer.get('status')!r}, expected {expected!r}")
    kind = spec["type"]
    if kind == "status":
        return Grade(True, f"status is {expected!r}")
    if kind == "number":
        return _grade_number(spec, gold, answer)
    if kind == "set":
        return _grade_set(gold, answer)
    if kind == "table":
        return _grade_table(spec, gold, answer)
    raise ValueError(f"{question['id']}: unknown grader type {kind!r}")
