"""Step 6a: the company's metric definitions, generated from the dbt semantic layer in dbt/target/manifest.json.

dbt (MetricFlow) already defines what "revenue", "order total" or "gross profit" mean here: a measure on one table
(aggregation + expression), optional filters, and metrics built from other metrics (ratio, derived, cumulative).
This module turns those definitions into one line per metric with the SQL they imply. Nothing is typed by hand:
change the dbt YAML, rebuild, and the prompt follows.
"""

from __future__ import annotations

import re

_REF = re.compile(r"ref\('([^']+)'\)")
_DIM = re.compile(r"\{\{\s*Dimension\('([^']+)'\)\s*\}\}")
_AGG = {"sum": "SUM({})", "count_distinct": "COUNT(DISTINCT {})", "average": "AVG({})", "median": "MEDIAN({})",
        "min": "MIN({})", "max": "MAX({})", "count": "COUNT({})"}


def _measures(manifest: dict) -> dict[str, dict]:
    """measure name -> {table, agg, expr, time} from every semantic model."""
    out = {}
    for sm in manifest.get("semantic_models", {}).values():
        table = _REF.search(sm["model"]).group(1)
        time = (sm.get("defaults") or {}).get("agg_time_dimension")
        for m in sm["measures"]:
            out[m["name"]] = {"table": table, "agg": m["agg"], "expr": m.get("expr") or m["name"], "time": time}
    return out


def _where(metric_filter: dict | None) -> str:
    """The filter as plain SQL: `{{ Dimension('order_id__customer_order_number') }} = 1` -> `customer_order_number = 1`."""
    if not metric_filter:
        return ""
    parts = [" ".join(_DIM.sub(lambda m: m.group(1).split("__")[-1], f["where_sql_template"]).split())
             for f in metric_filter.get("where_filters", [])]
    return " AND ".join(parts)


def _formula(metric: dict, measures: dict[str, dict]) -> str:
    p = metric["type_params"]
    kind = metric["type"]
    if kind in ("simple", "cumulative"):
        m = measures[p["measure"]["name"]]
        sql = _AGG[m["agg"]].format(m["expr"]) + f" over main.{m['table']}"
        where = _where(metric.get("filter"))
        if where:
            sql += f" where {where}"
        if m["time"]:
            sql += f" (by {m['time']})"
        return "running total of " + sql if kind == "cumulative" else sql
    if kind == "ratio":
        return f"{p['numerator']['name']} / {p['denominator']['name']}"
    if kind == "derived":
        names = []
        for ref in p["metrics"]:
            label = ref.get("alias") or ref["name"]
            off = ref.get("offset_window")
            if label != ref["name"] or off:  # `revenue = revenue` says nothing
                names.append(f"{label} = {ref['name']}" + (f" {off['count']} {off['granularity']} earlier" if off else ""))
        return p["expr"] + (", where " + "; ".join(names) if names else "")
    return kind


CLOSED = ("This is every metric the company has defined. A business metric that is neither on this list nor "
          "computable from the data columns has no company definition.")


def describe_metrics(manifest: dict, closed: bool = False) -> str:
    """One line per metric; empty string if the project defines none. `closed` (step 6a') adds that the list is complete."""
    metrics = sorted(manifest.get("metrics", {}).values(), key=lambda m: m["name"])
    if not metrics:
        return ""
    measures = _measures(manifest)
    lines = ["Company metrics (defined in the dbt semantic layer; a question that names one of these uses its definition):"]
    if closed:
        lines.append(CLOSED)
    for m in metrics:
        desc = " ".join((m.get("description") or "").split())
        lines.append(f"- {m['name']} ({m['type']}): {desc} | definition: {_formula(m, measures)}")
    return "\n".join(lines)
