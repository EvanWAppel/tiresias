"""Core grounded-query tools — the single implementation behind both surfaces.

The MCP server (``tiresias.mcp_server``) and the LangGraph agent
(``tiresias.agent``) both call these functions, so "the agent builds the tools, the
human inspects the data" holds literally: one validated, read-only execution path,
two consumers.

Everything here is read-only. ``run_validated_sql`` is the only way agent-drafted
SQL should ever reach the warehouse — it guards, EXPLAIN-validates, executes under a
row cap, and returns JSON-safe rows plus the exact SQL that ran (for citation).
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from tiresias import db
from tiresias.catalog import load_catalog
from tiresias.config import DEFAULT_SETTINGS, TiresiasSettings
from tiresias.metrics import Metric, load_registry
from tiresias.sql_guard import guard_sql

logger = logging.getLogger(__name__)


class QueryResult(BaseModel):
    """The outcome of a validated, read-only query."""

    model_config = {"frozen": True}

    sql: str  # the exact hardened SQL that ran (row cap included) — cite this
    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    row_count: int
    tables: tuple[str, ...]
    truncated: bool


def run_validated_sql(
    sql: str, settings: TiresiasSettings = DEFAULT_SETTINGS
) -> QueryResult:
    """Guard, validate, and execute ``sql`` read-only; return JSON-safe rows.

    Raises ``tiresias.sql_guard.SqlGuardError`` if the SQL violates the policy or
    fails catalog validation — errors are never swallowed.
    """
    conn = db.get_connection(settings.db_path)
    safe = guard_sql(sql, settings=settings, connection=conn)

    frame = conn.cursor().execute(safe.sql).df()
    # to_json handles numpy/date coercion; round-trip to get JSON-safe Python values.
    # (to_json returns str when no path is given; `or "[]"` satisfies the typechecker.)
    records = tuple(json.loads(frame.to_json(orient="records", date_format="iso") or "[]"))
    row_count = len(frame)

    logger.info("run_validated_sql returned %d rows from %s", row_count, safe.tables)
    return QueryResult(
        sql=safe.sql,
        columns=tuple(frame.columns),
        rows=records,
        row_count=row_count,
        tables=safe.tables,
        truncated=row_count >= safe.row_cap,
    )


def catalog_text(settings: TiresiasSettings = DEFAULT_SETTINGS) -> str:
    """The in-scope table catalog as grounding text (an MCP resource body)."""
    catalog = load_catalog(settings)
    return "\n\n".join(table.to_prompt() for table in catalog.tables)


def metrics_text(settings: TiresiasSettings = DEFAULT_SETTINGS) -> str:
    """The governed metric registry as grounding text (an MCP resource body)."""
    registry = load_registry(settings.metrics_path)
    blocks = []
    for metric in registry.metrics:
        blocks.append(
            f"Metric: {metric.name} ({metric.label})\n"
            f"  Grain: {metric.grain}\n"
            f"  Definition: {metric.description}\n"
            f"  Canonical expression: {metric.expression}\n"
            f"  Grounded in: {', '.join(metric.references)}"
        )
    return "\n\n".join(blocks)


def get_metric(name: str, settings: TiresiasSettings = DEFAULT_SETTINGS) -> Metric:
    """Look up one governed metric by name (raises KeyError if unknown)."""
    return load_registry(settings.metrics_path).get(name)


def list_tables(settings: TiresiasSettings = DEFAULT_SETTINGS) -> list[dict]:
    """The in-scope tables with their columns and types (structured, for tools)."""
    catalog = load_catalog(settings)
    return [
        {
            "name": table.name,
            "schema": table.db_schema,
            "description": table.description,
            "columns": [{"name": c.name, "type": c.type} for c in table.columns],
        }
        for table in catalog.tables
    ]


def profile_column(
    table: str, column: str, settings: TiresiasSettings = DEFAULT_SETTINGS
) -> dict:
    """Read-only profile of one column of an allowed table.

    Both identifiers are validated against the catalog (so they must be known,
    allowlisted names) before the profiling query is built — this is a trusted,
    fixed-shape aggregate, not agent-drafted SQL.
    """
    catalog = load_catalog(settings)
    tbl = catalog.get(table)  # raises KeyError if the table is out of scope
    col = next((c for c in tbl.columns if c.name == column), None)
    if col is None:
        raise KeyError(
            f"column {column!r} not in {table}; columns: {list(tbl.column_names)}"
        )

    query = (
        f'select count(*) as row_count, '
        f'count("{column}") as non_null_count, '
        f'count(distinct "{column}") as distinct_count, '
        f'min("{column}")::varchar as min_value, '
        f'max("{column}")::varchar as max_value '
        f'from {tbl.db_schema}."{table}"'
    )
    row = db.query(query, settings.db_path).iloc[0]
    row_count = int(row["row_count"])
    non_null = int(row["non_null_count"])
    return {
        "table": table,
        "column": column,
        "type": col.type,
        "row_count": row_count,
        "non_null_count": non_null,
        "null_count": row_count - non_null,
        "distinct_count": int(row["distinct_count"]),
        "min": row["min_value"],
        "max": row["max_value"],
    }
