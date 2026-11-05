"""Step 6a: metric definitions come from the manifest (hand-made one here; the real one in the last test, skipped without `make db`)."""

import pytest

from agent import metrics, semantic

MANIFEST = {
    "semantic_models": {
        "sm.orders": {
            "model": "ref('orders')", "defaults": {"agg_time_dimension": "ordered_at"},
            "measures": [{"name": "order_count", "agg": "sum", "expr": "1"}, {"name": "cost", "agg": "sum"}],
        },
        "sm.items": {
            "model": "ref('order_items')", "defaults": {"agg_time_dimension": "ordered_at"},
            "measures": [{"name": "revenue", "agg": "sum", "expr": "product_price"}],
        },
    },
    "metrics": {
        "m.orders": {"name": "orders", "type": "simple", "description": "Count of orders.",
                     "type_params": {"measure": {"name": "order_count"}}},
        "m.new": {"name": "new_orders", "type": "simple", "description": "First orders.",
                  "filter": {"where_filters": [{"where_sql_template": "{{ Dimension('order_id__order_number') }} = 1\n"}]},
                  "type_params": {"measure": {"name": "order_count"}}},
        "m.revenue": {"name": "revenue", "type": "simple", "description": "Excludes tax.",
                      "type_params": {"measure": {"name": "revenue"}}},
        "m.profit": {"name": "profit", "type": "derived", "description": "Gross profit.",
                     "type_params": {"expr": "revenue - c", "metrics": [{"name": "revenue"}, {"name": "cost", "alias": "c"}]}},
        "m.pct": {"name": "share", "type": "ratio", "description": "Share.",
                  "type_params": {"numerator": {"name": "orders"}, "denominator": {"name": "revenue"}}},
        "m.prev": {"name": "growth", "type": "derived", "description": "Growth.",
                   "type_params": {"expr": "(a - b) / b", "metrics": [
                       {"name": "revenue", "alias": "a"}, {"name": "revenue", "alias": "b", "offset_window": {"count": 1, "granularity": "month"}}]}},
    },
}


def test_simple_metric_gets_its_table_aggregation_and_time_column():
    text = metrics.describe_metrics(MANIFEST)
    assert "- revenue (simple): Excludes tax. | definition: SUM(product_price) over main.order_items (by ordered_at)" in text


def test_filter_is_turned_into_plain_sql():
    assert "SUM(1) over main.orders where order_number = 1 (by ordered_at)" in metrics.describe_metrics(MANIFEST)


def test_derived_and_ratio_metrics_show_their_inputs_without_noise():
    text = metrics.describe_metrics(MANIFEST)
    assert "definition: revenue - c, where c = cost" in text  # `revenue = revenue` is not repeated
    assert "definition: orders / revenue" in text
    assert "(a - b) / b, where a = revenue; b = revenue 1 month earlier" in text


def test_closed_list_says_it_is_complete_only_when_asked():
    assert "This is every metric the company has defined" not in metrics.describe_metrics(MANIFEST)
    assert "This is every metric the company has defined" in metrics.describe_metrics(MANIFEST, closed=True)


def test_no_metrics_means_no_section():
    assert metrics.describe_metrics({"metrics": {}, "semantic_models": {}}) == ""


@pytest.mark.skipif(not semantic.MANIFEST_PATH.exists(), reason="needs `make db`")
def test_real_manifest_metrics():
    text = metrics.describe_metrics(semantic.load_manifest())
    assert "- revenue (simple): Sum of the product revenue for each order item. Excludes tax. | definition: SUM(product_price) over main.order_items" in text
    assert "order_gross_profit (derived)" in text and "revenue - cost, where cost = order_cost" in text
