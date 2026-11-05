"""Quick profile of the warehouse: row counts, date range, revenue both ways.

Run with `make profile`. Use it to sanity-check gold answers, not as agent context.
"""

import sys
from pathlib import Path

# Running a file from scripts/ puts scripts/ on sys.path, not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import db  # noqa: E402

QUERIES = {
    "Row counts": """
        select schema_name || '.' || table_name as name, estimated_size as approx_rows
        from duckdb_tables() order by 1
    """,
    "Order date range": """
        select min(ordered_at) as first_order, max(ordered_at) as last_order, count(*) as orders
        from main.orders
    """,
    "Revenue: pre-tax vs incl. tax": """
        select sum(subtotal) as subtotal_pre_tax, sum(tax_paid) as tax, sum(order_total) as order_total_incl_tax
        from main.orders
    """,
    "Orders by store": """
        select l.location_name, count(o.order_id) as orders, sum(o.subtotal) as subtotal
        from main.locations l left join main.orders o using (location_id)
        group by 1 order by 2 desc
    """,
}


def main() -> None:
    con = db.connect()
    for title, sql in QUERIES.items():
        result = db.run_sql(con, sql, max_rows=1000)  # the agent's 5-row cap would cut these tables
        print(f"\n## {title}\n{result.to_text()}")


if __name__ == "__main__":
    main()
