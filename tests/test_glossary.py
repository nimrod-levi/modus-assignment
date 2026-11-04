"""Customer glossary: the validator catches wrong entries (planted data), the real file is valid, and the block reaches the agent."""

import duckdb
import pytest

from agent import db, glossary


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("create table orders (order_id varchar, order_total double, ordered_at date)")
    return c


def _entry(**kw):
    base = {"id": "e1", "kind": "rule", "text": "t", "status": "assumed", "owner": "o", "date": "2026-11-04",
            "applies_to": ["orders.order_total"]}
    return {**base, **kw}


def test_valid_entry_has_no_errors(con):
    assert glossary.validate([_entry(sql="order_total > 0")], con) == []


def test_placeholders_in_sql_are_bound(con):
    assert glossary.validate([_entry(sql="ordered_at >= :start and ordered_at < :end")], con) == []


def test_validator_reports_each_kind_of_mistake(con):
    errors = glossary.validate([
        _entry(id="a", kind="opinion"),
        _entry(id="b", status="maybe"),
        _entry(id="c", applies_to=["nope.col"]),
        _entry(id="d", applies_to=["orders.nope"]),
        _entry(id="e", sql="order_total >>> 0"),
        _entry(id="e"),
        _entry(id="f", text=""),
    ], con)
    text = "\n".join(errors)
    for expected in ("a: kind 'opinion'", "b: status 'maybe'", "c: applies_to 'nope.col': no such table",
                     "d: applies_to 'orders.nope': no such column", "e: sql does not compile", "e: duplicate id",
                     "f: missing 'text'"):
        assert expected in text


def test_render_labels_assumed_entries_and_sql():
    block = glossary.render([_entry(id="x", text="a  b", sql="order_total > 0"), _entry(id="y", status="confirmed")])
    assert "[x] a b SQL: order_total > 0 (assumed)" in block
    assert "[y] t" in block and "[y] t (assumed)" not in block
    assert glossary.render([]) == ""


@pytest.mark.skipif(not db.db_path().exists(), reason="needs `make db`")
def test_the_real_glossary_is_valid():
    entries = glossary.load()
    assert entries and glossary.validate(entries, db.connect()) == []
