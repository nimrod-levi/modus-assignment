"""Step 5a: is every number in the final answer one that a query returned?

The model sometimes answers with figures it never queried (q15 "$1,234,567.89", q16 in two runs). That is detectable without
a second model: collect the numbers in the successful run_sql results and check the answer against them.

Checked, only when status is "answered":
- at least one run_sql call succeeded;
- `numeric_value`, and every figure in `answer` that is not trivially small, matches a returned number after rounding
  to the decimals the answer states, or one simple derivation of two returned numbers (difference, sum, ratio, percent change).

Not checked (kept out on purpose, to avoid false rejections): integers below 100 ("top 5", "Q3"), years, numbers written
with a scale word or suffix ("$1.2M"), numbers already in the question, and the other fields (assumptions, definition_used).
This does not catch a real number used for the wrong thing (q19, tax as a cost): that is step 5b.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")  # answer text: "1,234.5" has a thousands separator
CSV_NUMBER = re.compile(r"\d+(?:\.\d+)?")  # query results are CSV: a comma separates two values
SCALE_AFTER = re.compile(r"\s?(?:k|m|mm|bn|b|thousand|million|billion)\b", re.IGNORECASE)
MAX_POOL = 200  # derived values are pairwise: cap the quadratic part


def numbers_in(text: str, *, csv: bool = False) -> list[tuple[float, int, bool]]:
    """(absolute value, decimals written, followed by a scale word) for each number in the text."""
    out = []
    for m in (CSV_NUMBER if csv else NUMBER).finditer(text):
        raw = m.group().rstrip(",")
        whole, _, frac = raw.replace(",", "").partition(".")
        out.append((float(f"{whole}.{frac}" if frac else whole), len(frac), bool(SCALE_AFTER.match(text, m.end()))))
    return out


def result_numbers(steps: list[dict]) -> list[float]:
    """Distinct numbers in the results of the queries that ran without an error."""
    seen: dict[float, None] = {}
    for step in steps:
        if step.get("type") == "sql" and step.get("error") is None:
            for value, _, _ in numbers_in(step.get("preview") or "", csv=True):
                seen[value] = None
    return list(seen)


def _derived(pool: list[float]) -> list[float]:
    pool = pool[:MAX_POOL]
    out = []
    for a in pool:
        for b in pool:
            out += [abs(a - b), a + b]
            if b:
                out += [a / b, a / b * 100, (a - b) / b * 100, abs(a - b) / b * 100]
    return out


def _matches(value: float, decimals: int, candidates) -> bool:
    return any(abs(round(c, decimals) - value) < 1e-9 for c in candidates)


def is_grounded(value: float, decimals: int, pool: list[float]) -> bool:
    """value (absolute) equals a pool number, the pool number as a percent, or one derivation of two, at that precision."""
    if _matches(value, decimals, pool) or _matches(value, decimals, [p * 100 for p in pool]):
        return True
    return _matches(value, decimals, _derived(pool))


def check(answer: dict, question: str, steps: list[dict]) -> list[str]:
    """Problems with an answered final answer, as short messages the model can act on. Empty when it is grounded."""
    if answer.get("status") != "answered":
        return []
    pool = result_numbers(steps)
    if not any(s.get("type") == "sql" and s.get("error") is None for s in steps):
        return ["you answered without a successful query, so no figure in the answer comes from the data"]
    in_question = {v for v, _, _ in numbers_in(question)}
    problems = []
    value = answer.get("numeric_value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = repr(float(value))
        decimals = len(text.partition(".")[2].rstrip("0")) if "e" not in text else 6
        if not is_grounded(abs(float(value)), decimals, pool):
            problems.append(f"numeric_value {value} is not in any query result")
    for number, decimals, scaled in numbers_in(str(answer.get("answer") or "")):
        trivial = decimals == 0 and (number < 100 or 1900 <= number <= 2100)
        if trivial or scaled or number in in_question:
            continue
        if not is_grounded(number, decimals, pool):
            problems.append(f"the figure {number:,.{decimals}f} in the answer is not in any query result")
    return problems
