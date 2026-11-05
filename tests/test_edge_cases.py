"""Each check of the checklist must fire on planted data (so it is not tied to the jaffle-shop data) and stay silent on clean data."""

import duckdb
import pytest

from agent import edge_cases


def make_ctx(sql: str, table="t", keys=("id",), joins=None):
    con = duckdb.connect()
    con.execute(sql)
    cols = {
        table: [(c, _short(d)) for c, d in con.execute(
            "select column_name, data_type from information_schema.columns where table_name = ? order by ordinal_position",
            [table]).fetchall()]
    }
    n = con.execute(f"select count(*) from main.{table}").fetchone()[0]
    return edge_cases.Ctx(con=con, cols=cols, joins=joins or [], keys={table: set(keys)}, rows={table: n})


def _short(d):
    d = d.upper()
    return ("ts" if d.startswith("TIMESTAMP") else "date" if d == "DATE" else "text" if d == "VARCHAR"
            else "decimal" if d.startswith("DECIMAL") else "int" if "INT" in d else "double" if d == "DOUBLE" else d.lower())


def run(ctx, check):
    return dict((cid, fn) for cid, _, fn in edge_cases.CHECKLIST)[check](ctx, "t")


def test_nulls_zeros_negatives_are_found_and_grouped():
    ctx = make_ctx("create table t as select i as id, case when i < 3 then null else i end as a, "
                   "case when i < 3 then null else i end as b, case when i = 5 then 0 else 1 end as z, "
                   "case when i = 6 then -1 else 1 end as neg from range(1, 101) r(i)")
    assert run(ctx, "nulls") == ["a, b null in 2 of 100 rows"]
    assert run(ctx, "zeros") == ["z = 0 in 1 of 100 rows (1.0%)"]
    assert run(ctx, "negatives") == ["neg < 0 in 1 of 100 rows"]


def test_time_checks():
    ctx = make_ctx("create table t as select i as id, date '2024-01-15' + to_days(i) as d from range(0, 1500) r(i)")
    cov = run(ctx, "time_coverage")[0]
    assert "first month 2024-01 starts on day 15" in cov and "no 'today'" in cov
    assert "date only" in run(ctx, "time_granularity")[0]


def test_timestamps_with_a_time_of_day_are_not_flagged_as_date_only():
    ctx = make_ctx("create table t as select i as id, timestamp '2024-01-01 08:30:00' as ts from range(0, 5) r(i)")
    assert run(ctx, "time_granularity") == []


def test_duplicates_and_missing_key():
    ctx = make_ctx("create table t as select 1 as id, 'x' as v union all select 1, 'x'")
    out = run(ctx, "key_duplicates")
    assert any("declared unique but 1 of 2 rows repeat" in o for o in out) and any("exact duplicates" in o for o in out)
    assert run(make_ctx("create table t as select 1 as id", keys=()), "key_duplicates") == [
        "no unique key is declared, so the grain is unknown"]


def test_placeholders_constants_units():
    ctx = make_ctx("create table t as select i as id, case when i = 1 then 'N/A' else 'a' || i end as name, "
                   "7 as k, i * 100 as price_cents, i as price from range(1, 21) r(i)")
    assert "name holds a placeholder" in run(ctx, "placeholders")[0]
    assert run(ctx, "constants") == ["k: a single value in every row"]
    assert "price_cents = price x 100" in run(ctx, "units")[0]


def test_orphans_and_childless_parents():
    con = duckdb.connect()
    con.execute("create table p as select i as id from range(1, 4) r(i)")
    con.execute("create table t as select i as id, i as p_id from range(1, 6) r(i)")  # p_id 4, 5 do not exist in p
    ctx = edge_cases.Ctx(con=con, cols={"t": [("id", "int"), ("p_id", "int")], "p": [("id", "int")]},
                         joins=[{"child": "t", "column": "p_id", "parent": "p", "field": "id", "source": "declared"}],
                         keys={"t": {"id"}, "p": {"id"}}, rows={"t": 5, "p": 3})
    assert edge_cases.orphans(ctx, "t") == ["2 of 5 rows have a p_id that does not exist in p"]
    assert edge_cases.orphans(ctx, "p") == []


def test_clean_data_reports_nothing_and_inapplicable_checks_are_skipped():
    ctx = make_ctx("create table t as select i as id, 'a' || i as name from range(1, 21) r(i)")
    findings, clean = edge_cases.check_table(ctx, "t")
    assert findings == []
    assert "nulls" in clean and "date ranges" not in clean  # no date column: the check does not apply


def test_join_risks_flag_many_to_many():
    joins = [{"child": "a", "column": "k", "parent": "p", "field": "k", "source": "declared"},
             {"child": "b", "column": "k", "parent": "p", "field": "k", "source": "declared"}]
    risks = edge_cases.join_risks(joins)
    assert any("a and b both reference p.k" in r for r in risks)


def test_join_risks_with_measured_fanout():
    joins = [{"child": "a", "column": "k", "parent": "p", "field": "k", "source": "declared"},
             {"child": "b", "column": "k", "parent": "p", "field": "k", "source": "declared"}]
    risks = edge_cases.join_risks(joins, {("a", "k"): 3.0, ("b", "k"): 6.5})
    assert any("(measured: 6.5 b rows per p row on average)" in r for r in risks)
    assert any("each a row would repeat about 6.5 times, each b row about 3 times" in r for r in risks)
    assert edge_cases.join_risks(joins) == edge_cases.join_risks(joins, {})  # no measurement: the old text
