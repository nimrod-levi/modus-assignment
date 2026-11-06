"""Read-only access to the jaffle-shop DuckDB warehouse.

Safety is layered:
1. The file is opened with read_only=True, so DuckDB itself refuses any write.
2. External access is switched off, so a SELECT can't read local files or URLs
   (e.g. read_csv('/etc/passwd')), and the setting is locked.
3. check_sql() allows one SELECT/WITH statement, so the model gets a clear error
   instead of a cryptic DuckDB one.
4. Each query has a row cap and a timeout.
"""

from __future__ import annotations

import datetime as dt
import decimal
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "jaffle.duckdb"

MAX_ROWS = 5  # default rows handed back to the model per query: results are re-sent on every later turn, so keep them tiny
MAX_ROWS_LIMIT = 200  # the most the model may ask for (run_sql's max_rows), when the rows themselves are the answer
QUERY_TIMEOUT_S = 20.0
MAX_CELL_CHARS = 60

_ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


class SQLRejected(ValueError):
    """The query was refused before it reached DuckDB."""


def db_path() -> Path:
    return Path(os.environ.get("JAFFLE_DB_PATH", DEFAULT_DB_PATH))


def connect(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    path = Path(path or db_path())
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Build it first with `make db`.")
    con = duckdb.connect(str(path), read_only=True)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def check_sql(sql: str) -> str:
    """Return the query ready to run, or raise SQLRejected.

    Checks run on a copy with string literals and comments removed, so a ';' or
    '--' inside a string doesn't trip them. The original text is what runs.
    """
    query = sql.strip().rstrip(";").strip()
    if not query:
        raise SQLRejected("Empty query.")
    scrubbed = _STRING_LITERAL.sub("''", query)
    scrubbed = _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", scrubbed))
    if ";" in scrubbed:
        raise SQLRejected("Only one statement per call.")
    if not _ALLOWED_START.match(scrubbed):
        raise SQLRejected("Only read-only SELECT or WITH queries are allowed.")
    return query


@dataclass
class QueryResult:
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    elapsed_ms: int = 0
    error: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_text(self) -> str:
        """Compact CSV-like text for the model."""
        if self.error:
            return f"ERROR: {self.error}"
        if not self.columns:
            return "Query ran and returned no columns."
        lines = [",".join(self.columns)]
        lines += [",".join(_fmt(v) for v in row) for row in self.rows]
        if not self.rows:
            lines.append("(0 rows)")
        elif self.truncated:
            lines.append(
                f"(showing first {len(self.rows)} rows; more exist: aggregate or filter in SQL, "
                f"or raise max_rows up to {MAX_ROWS_LIMIT} if you need the rows)"
            )
        return "\n".join(lines)


def run_sql(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    max_rows: int = MAX_ROWS,
    timeout_s: float = QUERY_TIMEOUT_S,
) -> QueryResult:
    started = time.perf_counter()
    try:
        query = check_sql(sql)
    except SQLRejected as exc:
        return QueryResult(sql=sql, error=str(exc))

    timed_out = threading.Event()

    def _interrupt() -> None:
        timed_out.set()
        con.interrupt()

    timer = threading.Timer(timeout_s, _interrupt)
    timer.start()
    try:
        con.execute(query)
        columns = [d[0] for d in con.description] if con.description else []
        rows = con.fetchmany(max_rows + 1) if columns else []
        truncated = len(rows) > max_rows
        result = QueryResult(sql=query, columns=columns, rows=rows[:max_rows], truncated=truncated)
    except duckdb.Error as exc:
        msg = f"Query timed out after {timeout_s:.0f}s." if timed_out.is_set() else str(exc)
        result = QueryResult(sql=query, error=msg)
    finally:
        timer.cancel()
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result


def describe_schema(con: duckdb.DuckDBPyConnection) -> str:
    """One line per table or view: schema.name (kind): column TYPE, ..."""
    kinds = dict(
        ((s, t), "view" if k == "VIEW" else "table")
        for s, t, k in con.execute(
            "select table_schema, table_name, table_type from information_schema.tables"
        ).fetchall()
    )
    rows = con.execute(
        """
        select table_schema, table_name, column_name, data_type
        from information_schema.columns
        where table_schema not in ('information_schema', 'pg_catalog')
        order by table_schema, table_name, ordinal_position
        """
    ).fetchall()
    tables: dict[tuple[str, str], list[str]] = {}
    for schema, table, column, dtype in rows:
        tables.setdefault((schema, table), []).append(f"{column} {_short_type(dtype)}")
    return "\n".join(
        f"{schema}.{table} ({kinds.get((schema, table), 'table')}): {', '.join(cols)}"
        for (schema, table), cols in tables.items()
    )


def _short_type(dtype: str) -> str:
    """Compact type for the prompt: the schema is re-sent every turn. DECIMAL(38,2) -> decimal, VARCHAR -> text."""
    base = dtype.split("(")[0].lower()
    return {"varchar": "text", "timestamp": "ts", "hugeint": "int", "bigint": "int", "integer": "int"}.get(base, base)


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dt.datetime, dt.date)):
        text = value.isoformat(sep=" ") if isinstance(value, dt.datetime) else value.isoformat()
    elif isinstance(value, decimal.Decimal):
        text = format(value, "f")
    else:
        text = str(value)
    if len(text) > MAX_CELL_CHARS:
        text = text[: MAX_CELL_CHARS - 3] + "..."
    if any(c in text for c in ',"\n'):
        text = '"' + text.replace('"', '""').replace("\n", " ") + '"'
    return text
