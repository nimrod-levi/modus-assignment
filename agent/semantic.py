"""Step 3: structural context, generated from dbt artifacts and the warehouse. Nothing here is hand-written knowledge.

Inputs
- dbt/target/manifest.json: model and column descriptions, `unique` tests (grain), `relationships` tests (join paths),
  `primary_key`.
- the DuckDB warehouse itself: column types, row counts, date ranges, values of low-cardinality columns, and how many
  parent rows have no children.

Output: one block per mart table (grain, keys, joins, columns with descriptions, edge-case findings from agent/edge_cases.py)
plus a join-risks section. Staging and raw tables stay as the compact one-line listing from step 0-2 (db.describe_schema).

Foreign keys: dbt only declares a few `relationships` tests. A column that has the same name as another table's key
is added as an *inferred* join, and labelled so.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb

from agent import db, edge_cases

MANIFEST_PATH = db.REPO_ROOT / "dbt" / "target" / "manifest.json"
MAX_DISTINCT = 6  # list the values of a text column only if it has at most this many distinct values
_REF = re.compile(r"ref\('([^']+)'\)")


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(Path(path).read_text())


def _is_mart(name: str) -> bool:
    return not name.startswith(("stg_", "raw_")) and name != "metricflow_time_spine"


def _models(manifest: dict) -> dict[str, dict]:
    return {n["name"]: n for n in manifest["nodes"].values() if n["resource_type"] == "model"}


def _tests(manifest: dict, kind: str):
    for node in manifest["nodes"].values():
        meta = node.get("test_metadata")
        if node["resource_type"] == "test" and meta and meta["name"] == kind and node.get("column_name"):
            yield node, meta["kwargs"]


def _unique_columns(manifest: dict) -> dict[str, set[str]]:
    """model name -> columns that are unique (declared by a unique test or by primary_key)."""
    out: dict[str, set[str]] = {n: set(m.get("primary_key") or []) for n, m in _models(manifest).items()}
    for node, _ in _tests(manifest, "unique"):
        out.setdefault(node["attached_node"].split(".")[-1], set()).add(node["column_name"])
    # A mart is a passthrough of its staging model, so it has the same keys even when only stg_* is tested.
    for name in list(out):
        if name.startswith("stg_"):
            out.setdefault(name[4:], set()).update(out[name])
    return out


def _resolve_mart(name: str, marts: set[str]) -> str:
    """The relationships tests point at stg_* models; the same keys exist on the mart with the same name without stg_."""
    return name[4:] if name.startswith("stg_") and name[4:] in marts else name


def find_joins(manifest: dict, columns: dict[str, list[str]]) -> list[dict]:
    """Child.column -> parent.column, with `source` = declared (dbt relationships test) or inferred (same key name)."""
    marts = set(columns)
    keys = _unique_columns(manifest)
    joins: dict[tuple, dict] = {}
    for node, kwargs in _tests(manifest, "relationships"):
        child = _resolve_mart(node["attached_node"].split(".")[-1], marts)
        parent = _resolve_mart(_REF.search(kwargs["to"]).group(1), marts)
        if child in marts and parent in marts:
            joins[(child, node["column_name"], parent)] = {
                "child": child, "column": node["column_name"], "parent": parent, "field": kwargs["field"], "source": "declared",
            }
    for child, cols in columns.items():
        for col in cols:
            for parent in marts - {child}:
                if col in keys.get(parent, set()) and col not in keys.get(child, set()) and col in columns[parent]:
                    joins.setdefault((child, col, parent), {
                        "child": child, "column": col, "parent": parent, "field": col, "source": "inferred",
                    })
    return sorted(joins.values(), key=lambda j: (j["child"], j["column"]))


def _table_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    rows = con.execute(
        "select column_name, data_type from information_schema.columns where table_schema = 'main' and table_name = ? "
        "order by ordinal_position", [table]).fetchall()
    return [(c, db._short_type(t)) for c, t in rows]


def _facts(con: duckdb.DuckDBPyConnection, table: str, cols: list[tuple[str, str]]) -> dict[str, str]:
    """Per-column facts read from the data: the values of a low-cardinality text column."""
    facts: dict[str, str] = {}
    for col, dtype in cols:
        q = f'"{col}"'
        if dtype == "text" and not col.endswith(("_id", "_uuid")):
            n = con.execute(f"select count(distinct {q}) from main.{table}").fetchone()[0]
            if 0 < n <= MAX_DISTINCT:
                vals = [r[0] for r in con.execute(f"select distinct {q} from main.{table} order by 1").fetchall()]
                facts[col] = "values: " + ", ".join(repr(v) for v in vals)
    return facts


def join_paths(joins: list[dict], tables: list[str]) -> list[str]:
    """For every pair of tables with no direct join, the shortest chain of joins between them (breadth-first search)."""
    edges: dict[str, list[tuple[str, str]]] = {t: [] for t in tables}
    for j in joins:
        edges[j["child"]].append((j["parent"], f"{j['child']}.{j['column']} = {j['parent']}.{j['field']}"))
        edges[j["parent"]].append((j["child"], f"{j['parent']}.{j['field']} = {j['child']}.{j['column']}"))
    out = []
    for i, a in enumerate(tables):
        paths, queue = {a: []}, [a]
        for node in queue:
            for nxt, step in edges[node]:
                if nxt not in paths:
                    paths[nxt] = paths[node] + [step]
                    queue.append(nxt)
        direct = {n for n, _ in edges[a]}
        out += [f"{a} <-> {b} (no direct join): " + "; ".join(paths[b])
                for b in tables[i + 1:] if b not in direct and b in paths]
    return out


def shared_columns(cols: dict[str, list[tuple[str, str]]], joins: list[dict], keys: dict[str, set[str]]) -> list[str]:
    """Non-key column names that exist in 2+ tables: same name, but each table has its own grain."""
    join_cols = {j["column"] for j in joins} | {j["field"] for j in joins}
    where: dict[str, list[str]] = {}
    for t, tcols in cols.items():
        for c, _ in tcols:
            if c not in join_cols:
                where.setdefault(c, []).append(t)
    return [
        f"{c} exists in " + " and ".join(f"{t} (one row per {', '.join(sorted(keys[t])) or '?'})" for t in ts)
        + ": same name, different grain, check which one you need."
        for c, ts in sorted(where.items()) if len(ts) > 1
    ]


def _orphans(con: duckdb.DuckDBPyConnection, j: dict) -> int:
    """Child rows whose key has no parent row."""
    return con.execute(
        f'select count(*) from main.{j["child"]} c where c."{j["column"]}" is not null and not exists '
        f'(select 1 from main.{j["parent"]} p where p."{j["field"]}" = c."{j["column"]}")').fetchone()[0]


def relationships(con: duckdb.DuckDBPyConnection, tables: list[str], cols: dict[str, list[tuple[str, str]]],
                  joins: list[dict], keys: dict[str, set[str]]) -> list[str]:
    """One section with the whole join graph: edges, multi-hop paths and same-name columns."""
    lines = ["Relationships (the join graph in one place):"]
    for j in joins:
        n = _orphans(con, j)
        lines.append(
            f"- {j['child']}.{j['column']} -> {j['parent']}.{j['field']} "
            f"(many-to-one, {j['source']}, {n} {j['child']} rows with no matching {j['parent']} row)")
    paths = join_paths(joins, tables)
    if paths:
        lines.append("Tables that connect only through other tables:")
        lines.extend("- " + p for p in paths)
    shared = shared_columns(cols, joins, keys)
    if shared:
        lines.append("Columns with the same name in several tables:")
        lines.extend("- " + s for s in shared)
    return lines


def describe(con: duckdb.DuckDBPyConnection, manifest: dict | None = None) -> str:
    manifest = manifest or load_manifest()
    models = _models(manifest)
    tables = [t for (t,) in con.execute(
        "select table_name from information_schema.tables where table_schema = 'main' order by 1").fetchall()
        if _is_mart(t)]
    cols = {t: _table_columns(con, t) for t in tables}
    keys = _unique_columns(manifest)
    joins = find_joins(manifest, {t: [c for c, _ in cols[t]] for t in tables})
    ctx = edge_cases.Ctx(
        con=con, cols=cols, joins=joins, keys={t: keys.get(t, set()) for t in tables},
        rows={t: con.execute(f"select count(*) from main.{t}").fetchone()[0] for t in tables})

    lines = []
    if joins:
        lines += relationships(con, tables, cols, joins, {t: keys.get(t, set()) for t in tables}) + [""]
    lines.append("Business tables (generated from the dbt project and the data):")
    for t in tables:
        node = models.get(t, {})
        n = con.execute(f"select count(*) from main.{t}").fetchone()[0]
        pk = sorted(keys.get(t, set()))
        grain = f"one row per {', '.join(pk)}" if pk else "grain not declared"
        desc = " ".join((node.get("description") or "").split())
        lines.append(f"\nmain.{t} ({n} rows, {grain})" + (f": {desc}" if desc else ""))
        fks = [j for j in joins if j["child"] == t]
        if fks:
            lines.append("  joins: " + "; ".join(
                f"{j['column']} -> {j['parent']}.{j['field']}" + (" (inferred)" if j["source"] == "inferred" else "")
                for j in fks))
        findings, clean = edge_cases.check_table(ctx, t)
        for finding in findings:
            lines.append(f"  NOTE: {finding}")
        if clean:
            lines.append("  Checked, nothing found: " + ", ".join(clean))
        facts = _facts(con, t, cols[t])
        col_docs = node.get("columns", {})
        for c, dtype in cols[t]:
            extra = [x for x in (" ".join((col_docs.get(c, {}).get("description") or "").split()), facts.get(c)) if x]
            lines.append(f"  {c} {dtype}" + (" - " + " | ".join(extra) if extra else ""))

    if joins:
        lines.append("\nJoin risks (from the keys above):")
        lines.extend("- " + risk for risk in edge_cases.join_risks(joins))

    other = [line for line in db.describe_schema(con).splitlines()
             if not any(line.startswith(f"main.{t} ") for t in tables)]
    lines.append("\nOther tables and views (staging and raw; names and types only):\n" + "\n".join(other))
    return "\n".join(lines)
