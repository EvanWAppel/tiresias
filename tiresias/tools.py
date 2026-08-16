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
