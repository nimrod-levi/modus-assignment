"""Step 3 generator: output is derived from dbt/target/manifest.json and the warehouse (skipped if either is missing)."""

import pytest

from agent import db, semantic

pytestmark = pytest.mark.skipif(
    not (db.db_path().exists() and semantic.MANIFEST_PATH.exists()), reason="needs `make db`"
)


@pytest.fixture(scope="module")
def con():
    return db.connect()


@pytest.fixture(scope="module")
def text(con):
    return semantic.describe(con)


def test_declared_and_inferred_joins(con):
    manifest = semantic.load_manifest()
    cols = {t: [c for c, _ in semantic._table_columns(con, t)] for t in ("orders", "order_items", "products", "locations")}
    joins = {(j["child"], j["column"], j["parent"]): j["source"] for j in semantic.find_joins(manifest, cols)}
    assert joins[("order_items", "order_id", "orders")] == "declared"  # dbt relationships test
    assert joins[("orders", "location_id", "locations")] == "inferred"  # same key name, no test


def test_grain_comes_from_unique_tests(text):
    assert "main.orders (61948 rows, one row per order_id)" in text
    assert "main.locations (6 rows, one row per location_id)" in text  # only stg_locations is tested in dbt


def test_data_facts_are_read_from_the_warehouse(text):
    assert "ordered_at covers 2024-09-01 to 2025-08-31" in text and "ordered_at: 12 months" in text
    assert "4 of 6 rows have no orders rows" in text  # only 2 stores have orders
    assert "483 of 61948 rows have no order_items rows" in text


def test_notes_flag_partial_quarters_and_midnight_timestamps(text):
    assert "2025-Q3 has only Jul, Aug" in text
    assert "every value is midnight" in text
    assert "relative dates" in text


def test_notes_group_nulls_and_zeros(text):
    assert "order_total = 0 in 483 of 61948 rows" in text
    assert "null in 483 of 61948 rows" in text


def test_sibling_tables_are_flagged(text):
    assert "order_items and supplies both reference products.product_id" in text


def test_fanout_warning_and_descriptions(text):
    assert "orders 1-N order_items on order_id" in text and "over-counts" in text
    assert "including tax" in text  # order_total description from the dbt yml


def test_staging_and_raw_stay_compact(text):
    assert "raw.raw_orders (table):" in text and "main.stg_orders (view):" in text


# Step 5: relationship map. The pure functions run on tiny hand-made inputs, the section on the real warehouse.
def test_join_paths_finds_the_chain_between_unconnected_tables():
    joins = [
        {"child": "order_items", "column": "order_id", "parent": "orders", "field": "order_id", "source": "declared"},
        {"child": "order_items", "column": "product_id", "parent": "products", "field": "product_id", "source": "inferred"},
        {"child": "supplies", "column": "product_id", "parent": "products", "field": "product_id", "source": "inferred"},
    ]
    paths = semantic.join_paths(joins, ["order_items", "orders", "products", "supplies"])
    assert ("orders <-> supplies (no direct join): orders.order_id = order_items.order_id; "
            "order_items.product_id = products.product_id; products.product_id = supplies.product_id") in paths
    assert not any(p.startswith("order_items <-> orders") for p in paths)  # direct joins are not repeated


def test_join_paths_skips_tables_that_are_not_connected():
    assert semantic.join_paths([], ["a", "b"]) == []


def test_shared_columns_ignore_join_keys():
    cols = {"a": [("id", "text"), ("cost", "decimal")], "b": [("id", "text"), ("cost", "decimal")]}
    joins = [{"child": "a", "column": "id", "parent": "b", "field": "id", "source": "declared"}]
    out = semantic.shared_columns(cols, joins, {"a": {"x"}, "b": {"id"}})
    assert len(out) == 1 and out[0].startswith("cost exists in a (one row per x) and b (one row per id)")


def test_relationship_section_is_in_the_prompt(text):
    assert text.index("Relationships (the join graph") < text.index("Business tables")
    assert ("orders.customer_id -> customers.customer_id "
            "(many-to-one, declared, 0 orders rows with no matching customers row)") in text
    assert "orders <-> supplies (no direct join)" in text and "products.product_id = supplies.product_id" in text
    assert "supply_cost exists in order_items" in text and "and supplies" in text
