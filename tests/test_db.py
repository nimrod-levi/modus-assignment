"""SQL guard and read-only checks. The guard tests need no database;
the rest skip until `make db` has built data/jaffle.duckdb."""

import pytest

from agent import db
from agent.db import SQLRejected, check_sql

# --- guard (no database needed) ---------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "select 1",
        "  SELECT * FROM main.orders;  ",
        "with t as (select 1 as x) select x from t",
        "select ';' as semicolon_in_string",
        "select 1 -- trailing comment; with semicolon",
    ],
)
def test_allows_single_select(sql):
    assert check_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        ";",
        "drop table main.orders",
        "insert into main.orders values (1)",
        "attach 'other.duckdb'",
        "select 1; drop table main.orders",
        "copy (select 1) to 'out.csv'",
        "/* select */ delete from main.orders",
    ],
)
def test_rejects_everything_else(sql):
    with pytest.raises(SQLRejected):
        check_sql(sql)


def test_strips_trailing_semicolon():
    assert check_sql("select 1;") == "select 1"


# --- against the real warehouse ----------------------------------------------

needs_db = pytest.mark.skipif(not db.db_path().exists(), reason="run `make db` first")


@pytest.fixture(scope="module")
def con():
    c = db.connect()
    yield c
    c.close()


@needs_db
def test_runs_a_query(con):
    result = db.run_sql(con, "select count(*) as n from main.orders")
    assert result.error is None
    assert result.columns == ["n"]
    assert result.rows[0][0] > 0


@needs_db
def test_all_three_layers_exist(con):
    schema = db.describe_schema(con)
    for name in ("raw.raw_orders", "main.stg_orders", "main.orders"):
        assert name in schema


@needs_db
def test_row_cap(con):
    result = db.run_sql(con, "select * from range(1000)", max_rows=10)
    assert result.row_count == 10
    assert result.truncated


@needs_db
def test_connection_is_read_only(con):
    with pytest.raises(Exception):
        con.execute("create table main.should_fail as select 1")


@needs_db
def test_file_access_is_blocked(con):
    result = db.run_sql(con, "select * from read_csv('/etc/hosts')")
    assert result.error is not None


@needs_db
def test_timeout(con):
    result = db.run_sql(con, "select count(*) from range(100000000000)", timeout_s=1)
    assert result.error and "timed out" in result.error


def test_default_cap_is_five_rows(con):
    result = db.run_sql(con, "select * from range(1000)")
    assert db.MAX_ROWS == 5 and result.row_count == 5 and result.truncated
    assert "aggregate or filter in SQL" in result.to_text()


@needs_db
def test_schema_types_are_compact(con):
    schema = db.describe_schema(con)
    assert "VARCHAR" not in schema and "DECIMAL(" not in schema
