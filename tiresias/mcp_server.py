"""Tiresias MCP server — the governed, read-only surface over the warehouse.

Exposes the Tiresias grounding surface as MCP:

  * Resources: the in-scope table catalog and the governed metric registry.
  * Tool: ``run_validated_sql`` — SELECT-only, allowlisted, row-capped, and
    EXPLAIN-validated against the live catalog before it runs.

The same server object drives two consumers (PRD Layer 3): the LangGraph agent
(in-memory transport, see ``tiresias.agent``) and an external client such as Claude
Code over stdio (``tiresias mcp --config tiresias.yml``). One server, two consumers.

Guard/validation failures are returned as structured ``{ok: false, error: ...}``
tool output so a consuming agent can read the reason and repair — that is the tool's
contract, not error-swallowing. Unexpected errors still propagate.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer

from tiresias import __version__, tools
from tiresias.config import TiresiasConfig
from tiresias.sql_guard import SqlGuardError

logger = logging.getLogger(__name__)

CATALOG_URI = "tiresias://catalog/tables"
METRICS_URI = "tiresias://metrics/registry"


def build_server(config: TiresiasConfig) -> MCPServer:
    """Construct the Tiresias MCP server for one city's warehouse."""
    server: MCPServer = MCPServer(
        name="tiresias-warehouse",
        version=__version__,
        instructions=(
            f"Read-only access to the {config.city} open-data warehouse "
            f"({config.blurb}). Read the catalog and metric resources to ground SQL "
            "in real columns and the governed metrics, then call run_validated_sql. "
            "Only the allowlisted tables are queryable; the tool is SELECT-only and "
            "row-capped."
        ),
    )

    @server.resource(
        CATALOG_URI,
        name="Table catalog",
        description="In-scope tables with columns, types, and dbt descriptions.",
        mime_type="text/plain",
    )
    def catalog_resource() -> str:
        return tools.catalog_text(config)

    @server.resource(
        METRICS_URI,
        name="Metric registry",
        description="Governed metric definitions the agent must use, not reinvent.",
        mime_type="text/plain",
    )
    def metrics_resource() -> str:
        return tools.metrics_text(config)

    @server.tool(
        description=(
            f"Execute a single read-only SELECT against the allowlisted {config.city} "
            "tables. The query is validated (SELECT-only, known tables, EXPLAIN-checked) "
            "and row-capped. Returns rows plus the exact SQL that ran (cite it). On a "
            "validation failure, returns {ok: false, error} so you can repair the SQL."
        )
    )
    def run_validated_sql(sql: str) -> dict[str, Any]:
        try:
            result = tools.run_validated_sql(sql, config)
        except (SqlGuardError, tools.QueryTimeoutError, tools.ResultTooLargeError) as exc:
            logger.info("run_validated_sql rejected a query: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **result.model_dump()}

    @server.tool(description="List the in-scope tables with their columns and types.")
    def list_tables() -> list[dict[str, Any]]:
        return tools.list_tables(config)

    @server.tool(
        description=(
            "Profile one column of an allowed table: row/null/distinct counts and "
            "min/max. Read-only. Returns {ok: false, error} for an unknown table/column."
        )
    )
    def profile_column(table: str, column: str) -> dict[str, Any]:
        try:
            return {"ok": True, **tools.profile_column(table, column, config)}
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}

    @server.tool(
        description=(
            "Get a governed metric definition by name (canonical expression + the "
            "columns it is grounded in). Returns {ok: false, error} if unknown."
        )
    )
    def get_metric(name: str) -> dict[str, Any]:
        try:
            return {"ok": True, **tools.get_metric(name, config).model_dump()}
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}

    return server


def serve_stdio(config: TiresiasConfig) -> None:
    """Run the server over stdio (for Claude Code and other MCP clients)."""
    build_server(config).run(transport="stdio")
