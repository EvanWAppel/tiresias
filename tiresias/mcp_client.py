"""In-memory MCP client for Tiresias's own agent.

The agent talks to the warehouse through the *real* MCP protocol — not a shortcut —
using an in-memory transport so there is no subprocess overhead. External clients
(e.g. Claude Code) reach the same server over stdio via ``python -m
tiresias.mcp_server``; this module is the internal consumer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client._memory import InMemoryTransport
from mcp.server import MCPServer
from mcp.types import TextContent, TextResourceContents

from tiresias.mcp_server import CATALOG_URI, METRICS_URI, build_server

logger = logging.getLogger(__name__)


def _resource_text(result) -> str:
    block = result.contents[0]
    if isinstance(block, TextResourceContents):
        return block.text
    raise TypeError(f"expected a text resource, got {type(block).__name__}")


def _tool_text(result) -> str:
    block = result.content[0]
    if isinstance(block, TextContent):
        return block.text
    raise TypeError(f"expected text tool content, got {type(block).__name__}")


class WarehouseSession:
    """A connected MCP session wrapping the catalog/metrics resources and the tool."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def read_catalog(self) -> str:
        return _resource_text(await self._session.read_resource(CATALOG_URI))

    async def read_metrics(self) -> str:
        return _resource_text(await self._session.read_resource(METRICS_URI))

    async def run_sql(self, sql: str) -> dict[str, Any]:
        """Call ``run_validated_sql`` and return its ``{ok, ...}`` payload.

        A guard/validation failure is a normal ``{ok: False, error}`` payload the
        caller inspects — not an exception.
        """
        result = await self._session.call_tool("run_validated_sql", {"sql": sql})
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(_tool_text(result))


@asynccontextmanager
async def warehouse_session(
    server: MCPServer | None = None,
) -> AsyncIterator[WarehouseSession]:
    """Open a real MCP session to the Tiresias server over an in-memory transport."""
    server = server or build_server()
    async with (
        InMemoryTransport(server, raise_exceptions=True) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        logger.debug("MCP warehouse session initialized")
        yield WarehouseSession(session)
