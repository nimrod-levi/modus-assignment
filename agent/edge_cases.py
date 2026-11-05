"""A fixed edge-case checklist, run on every table of the warehouse. Output feeds the agent's context (agent/semantic.py).

Why a checklist: steps 3b/3c added notes for the gaps that eval questions exposed (midnight timestamps, partial quarters, ...).
That finds only the gaps we happened to test. This module is the opposite: the list of checks is fixed in advance, comes from
the usual data-quality taxonomy, and runs on every table and column whether or not any question needs it.

Each check is a function (ctx, table) -> list[str] | None
  None  = the check does not apply to this table (e.g. no date column)
  []    = it applies and found nothing: reported as "checked, clean", so the agent knows the absence is real, not unknown
  [..]  = findings, one short sentence each, all read from the data

Checklist (id, title):
  time_range      min/max of every date column
  time_coverage   months present, missing months, partial first/last month, incomplete calendar quarters, no "today"
  time_granularity  date-only columns (every value at midnight)
  nulls           columns with nulls (columns that are null for the same rows are grouped)
  zeros           numeric columns equal to 0 in up to 5% of rows
  negatives       numeric columns with values below 0
  key_duplicates  declared key not unique, fully duplicated rows, or no key declared
  orphans         child keys with no parent row; parent rows with no children
  constants       columns with a single value
  placeholders    text values such as '', 'N/A', 'unknown', 'test'
  units           a column that exists twice, once scaled (x and x_cents)
Join-level risks (fan-out, many-to-many) are produced by join_risks() from the join graph.

Not covered, because the data cannot reveal it: concepts the schema does not represent (refunds, targets, labour cost), what the
business means by a metric, and the fiscal calendar. Those belong in the labelled glossary file, never in generated context.
Not covered yet: outliers, near-duplicate text, referential checks across non-key columns, cross-column consistency.

Run `python -m agent.edge_cases` (or `make checks`) to print the report for the whole warehouse.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable

import duckdb

PLACEHOLDERS = ("", "n/a", "na", "null", "none", "unknown", "tbd", "test", "-", "?")
ZERO_SHARE_MAX = 0.05  # report zeros only when they are rare enough to be exceptions, not a normal value
AXIS_MIN_ROWS = 1000  # a date column is a time axis (not a few opening dates) above this many rows
NUMERIC = ("int", "decimal", "double")


@dataclass
class Ctx:
    con: duckdb.DuckDBPyConnection
    cols: dict[str, list[tuple[str, str]]]  # table -> [(column, short type)]
    joins: list[dict]
    keys: dict[str, set[str]]
    rows: dict[str, int]


def _q(name: str) -> str:
    return '"' + name + '"'


def _scalar(ctx: Ctx, sql: str):
    return ctx.con.execute(sql).fetchone()[0]


def _group(by_count: dict[int, list[str]], n: int, template: str) -> list[str]:
    return [template.format(cols=", ".join(c), k=k, n=n, pct=100 * k / n) for k, c in by_count.items()]


def _date_cols(ctx: Ctx, t: str) -> list[str]:
    return [c for c, d in ctx.cols[t] if d in ("ts", "date")]


def _numeric_cols(ctx: Ctx, t: str) -> list[str]:
    return [c for c, d in ctx.cols[t] if d in NUMERIC and not c.endswith("_id")]


def time_range(ctx: Ctx, t: str):
    cols = _date_cols(ctx, t)
    if not cols:
        return None
    out = []
    for c in cols:
        lo, hi = ctx.con.execute(f"select min({_q(c)})::date, max({_q(c)})::date from main.{t}").fetchone()
        out.append(f"{c} covers {lo} to {hi}")
    return out


def time_coverage(ctx: Ctx, t: str):
    axes = [c for c in _date_cols(ctx, t) if ctx.rows[t] >= AXIS_MIN_ROWS]
    if not axes:
        return None
    out = []
    for c in axes:
        q = _q(c)
        lo, hi = ctx.con.execute(f"select min({q})::date, max({q})::date from main.{t}").fetchone()
        months = sorted(ctx.con.execute(
            f"select distinct year({q}), month({q}) from main.{t} where {q} is not null").fetchall())
        if len(months) < 2:
            continue
        expected = (hi.year - lo.year) * 12 + hi.month - lo.month + 1
        parts = [f"{len(months)} months"]
        if len(months) < expected:
            parts.append(f"{expected - len(months)} months in between have no rows")
        if lo.day != 1:
            parts.append(f"first month {lo:%Y-%m} starts on day {lo.day}")
        if (hi + dt.timedelta(days=1)).day != 1:
            parts.append(f"last month {hi:%Y-%m} ends on day {hi.day}")
        by_quarter: dict[tuple[int, int], list[int]] = {}
        for y, m in months:
            by_quarter.setdefault((y, (m - 1) // 3 + 1), []).append(m)
        names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for (y, qtr), ms in sorted(by_quarter.items()):
            if len(ms) < 3:
                parts.append(f"{y}-Q{qtr} has only {', '.join(names[m - 1] for m in ms)}")
        parts.append("no 'today' is stored: relative dates (last month, this quarter) are not defined by the data")
        out.append(f"{c}: " + "; ".join(parts))
    return out


def time_granularity(ctx: Ctx, t: str):
    cols = _date_cols(ctx, t)
    if not cols:
        return None
    clean = [c for c in cols if _scalar(ctx, f"select count(*) from main.{t} where {_q(c)}::time <> time '00:00:00'") > 0]
    midnight = [c for c in cols if c not in clean]
    return [f"{', '.join(midnight)}: date only, every value is midnight (no hour or minute exists)"] if midnight else []


def nulls(ctx: Ctx, t: str):
    n, by_count = ctx.rows[t], {}
    for c, _ in ctx.cols[t]:
        k = _scalar(ctx, f"select count(*) from main.{t} where {_q(c)} is null")
        if k:
            by_count.setdefault(k, []).append(c)
    return _group(by_count, n, "{cols} null in {k} of {n} rows")


def zeros(ctx: Ctx, t: str):
    cols = _numeric_cols(ctx, t)
    if not cols:
        return None
    n, by_count = ctx.rows[t], {}
    for c in cols:
        k = _scalar(ctx, f"select count(*) from main.{t} where {_q(c)} = 0")
        if 0 < k <= ZERO_SHARE_MAX * n:
            by_count.setdefault(k, []).append(c)
    return _group(by_count, n, "{cols} = 0 in {k} of {n} rows ({pct:.1f}%)")


def negatives(ctx: Ctx, t: str):
    cols = _numeric_cols(ctx, t)
    if not cols:
        return None
    n, by_count = ctx.rows[t], {}
    for c in cols:
        k = _scalar(ctx, f"select count(*) from main.{t} where {_q(c)} < 0")
        if k:
            by_count.setdefault(k, []).append(c)
    return _group(by_count, n, "{cols} < 0 in {k} of {n} rows")


def key_duplicates(ctx: Ctx, t: str):
    n, out = ctx.rows[t], []
    keys = sorted(ctx.keys.get(t, set()))
    if not keys:
        out.append("no unique key is declared, so the grain is unknown")
    for k in keys:
        dup = n - _scalar(ctx, f"select count(distinct {_q(k)}) from main.{t}")
        if dup:
            out.append(f"{k} is declared unique but {dup} of {n} rows repeat a value")
    full = n - _scalar(ctx, f"select count(*) from (select distinct * from main.{t})")
    if full:
        out.append(f"{full} of {n} rows are exact duplicates of another row")
    return out


def orphans(ctx: Ctx, t: str):
    out = []
    for j in ctx.joins:
        if j["child"] == t:
            k = _scalar(ctx, (
                f"select count(*) from main.{t} c where c.{_q(j['column'])} is not null and not exists "
                f"(select 1 from main.{j['parent']} p where p.{_q(j['field'])} = c.{_q(j['column'])})"))
            if k:
                out.append(f"{k} of {ctx.rows[t]} rows have a {j['column']} that does not exist in {j['parent']}")
        if j["parent"] == t:
            k = _scalar(ctx, (
                f"select count(*) from main.{t} p where not exists "
                f"(select 1 from main.{j['child']} c where c.{_q(j['column'])} = p.{_q(j['field'])})"))
            if k:
                out.append(f"{k} of {ctx.rows[t]} rows have no {j['child']} rows (via {j['child']}.{j['column']})")
    return out if ctx.joins and any(t in (j["child"], j["parent"]) for j in ctx.joins) else None


def constants(ctx: Ctx, t: str):
    if ctx.rows[t] < 2:
        return None
    const = []
    for c, _ in ctx.cols[t]:
        if _scalar(ctx, f"select count(distinct {_q(c)}) from main.{t}") == 1:
            const.append(c)
    return [f"{', '.join(const)}: a single value in every row"] if const else []


def placeholders(ctx: Ctx, t: str):
    cols = [c for c, d in ctx.cols[t] if d == "text"]
    if not cols:
        return None
    marks = ", ".join("'" + p + "'" for p in PLACEHOLDERS)
    out = []
    for c in cols:
        k = _scalar(ctx, f"select count(*) from main.{t} where lower(trim({_q(c)})) in ({marks})")
        if k:
            out.append(f"{c} holds a placeholder value ('', 'N/A', 'unknown', ...) in {k} rows")
    return out


def units(ctx: Ctx, t: str):
    names = {c for c, _ in ctx.cols[t]}
    pairs = [(c, c[: -len("_cents")]) for c in sorted(names) if c.endswith("_cents") and c[: -len("_cents")] in names]
    if not pairs:
        return None
    parts = []
    for scaled, base in pairs:
        ratio = _scalar(ctx, f"select sum({_q(scaled)}) / nullif(sum({_q(base)}), 0) from main.{t}")
        if ratio:
            parts.append(f"{scaled} = {base} x {ratio:.0f}")
    return ["scaled duplicate columns (cents): " + ", ".join(parts) + "; use the unscaled column for dollars"] if parts else []


CHECKLIST: list[tuple[str, str, Callable[[Ctx, str], list[str] | None]]] = [
    ("time_range", "date ranges", time_range),
    ("time_coverage", "time coverage", time_coverage),
    ("time_granularity", "time of day", time_granularity),
    ("nulls", "nulls", nulls),
    ("zeros", "zero values", zeros),
    ("negatives", "negative values", negatives),
    ("key_duplicates", "duplicate keys and rows", key_duplicates),
    ("orphans", "orphan and childless keys", orphans),
    ("constants", "constant columns", constants),
    ("placeholders", "placeholder values", placeholders),
    ("units", "scaled duplicate columns", units),
]


def check_table(ctx: Ctx, table: str) -> tuple[list[str], list[str]]:
    """(findings, titles of the checks that applied and found nothing)."""
    findings, clean = [], []
    for _, title, fn in CHECKLIST:
        result = fn(ctx, table)
        if result:
            findings.extend(result)
        elif result is not None:
            clean.append(title)
    return findings, clean


def join_risks(joins: list[dict], fanout: dict[tuple[str, str], float] | None = None) -> list[str]:
    """Fan-out for every join, and a many-to-many warning for tables that reference the same parent key.

    `fanout` (optional, measured from the data): (child, column) -> average child rows per parent row. When given, the
    warnings say how many times rows repeat, not only that they do."""
    fanout = fanout or {}

    def avg(j: dict) -> str:
        n = fanout.get((j["child"], j["column"]))
        return f" (measured: {n:g} {j['child']} rows per {j['parent']} row on average)" if n else ""

    out = [
        f"{j['parent']} 1-N {j['child']} on {j['column']}{avg(j)}: after joining, each {j['parent']} row appears once per "
        f"matching {j['child']} row, so summing or counting {j['parent']} columns over-counts."
        for j in joins
    ]
    by_parent: dict[tuple[str, str], list[dict]] = {}
    for j in joins:
        by_parent.setdefault((j["parent"], j["field"]), []).append(j)
    out += [
        f"{' and '.join(k['child'] for k in kids)} both reference {parent}.{field}: joining them to each other directly on "
        f"that key repeats rows (many-to-many)"
        + (f" (each {kids[0]['child']} row would repeat about {fanout[(kids[1]['child'], kids[1]['column'])]:g} times, "
           f"each {kids[1]['child']} row about {fanout[(kids[0]['child'], kids[0]['column'])]:g} times)"
           if len(kids) == 2 and all((k["child"], k["column"]) in fanout for k in kids) else "")
        + f", so sums over either table are inflated. Aggregate each to one row per {field} first."
        for (parent, field), kids in sorted(by_parent.items()) if len(kids) > 1
    ]
    return out


def main() -> None:
    from agent import db, semantic

    print(semantic.describe(db.connect()))


if __name__ == "__main__":
    main()
