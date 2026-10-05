"""End-to-end MCP tests: a client speaks the real protocol to the Tiresias server."""

from __future__ import annotations

import pytest

from tiresias import tools
from tiresias.config import TiresiasConfig
from tiresias.mcp_client import warehouse_session
from tiresias.mcp_server import build_server


def test_server_instructions_name_the_city(config: TiresiasConfig) -> None:
    server = build_server(config)
    assert "Testville" in (server.instructions or "")


async def test_run_validated_sql_over_mcp(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        payload = await ware.run_sql("select count(*) as n from mart_inspections")
    assert payload["ok"] is True
    assert payload["rows"][0]["n"] == 50
    # The tool echoes the exact hardened SQL (row cap included) for citation.
    assert "LIMIT 1000" in payload["sql"].upper()


async def test_guard_rejection_is_structured_over_mcp(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        payload = await ware.run_sql("drop table mart_inspections")
    assert payload["ok"] is False
    assert "select" in payload["error"].lower()


async def test_catalog_resource_over_mcp(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        catalog = await ware.read_catalog()
    assert "mart_inspections" in catalog
    assert "failure_rate_pct" in catalog
    assert "geometry_json" not in catalog


async def test_metrics_resource_over_mcp(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        metrics = await ware.read_metrics()
    assert "inspection_failure_rate" in metrics


async def test_list_tables_tool_over_mcp(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        payload = await ware.call_tool("list_tables", {})
    # MCP wraps a bare-list tool return under "result".
    names = {t["name"] for t in payload["result"]}
    assert names == set(config.tables.allowed)


async def test_profile_column_tool_over_mcp(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        payload = await ware.call_tool(
            "profile_column", {"table": "mart_inspections", "column": "permit_number"}
        )
    assert payload["ok"] is True
    assert payload["row_count"] == 50
    assert payload["distinct_count"] == payload["row_count"]
    assert payload["null_count"] == 0


async def test_get_metric_tool_over_mcp(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        ok = await ware.call_tool("get_metric", {"name": "inspection_failure_rate"})
        bad = await ware.call_tool("get_metric", {"name": "no_such_metric"})
    assert ok["ok"] is True and ok["source_column"] == "failure_rate_pct"
    assert bad["ok"] is False


async def test_profile_unknown_column_is_structured_error(config: TiresiasConfig) -> None:
    async with warehouse_session(config) as ware:
        payload = await ware.call_tool(
            "profile_column", {"table": "mart_inspections", "column": "nope"}
        )
    assert payload["ok"] is False


@pytest.mark.parametrize(
    "error",
    [
        tools.QueryTimeoutError("query timed out after 15.0s"),
        tools.ResultTooLargeError("result too large (999999 bytes > 256000)"),
    ],
)
async def test_execution_limits_are_structured_over_mcp(
    config: TiresiasConfig, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def _fail(sql: str, config: TiresiasConfig):
        raise error

    monkeypatch.setattr(tools, "run_validated_sql", _fail)
    async with warehouse_session(config) as ware:
        payload = await ware.run_sql("select count(*) from mart_inspections")
    assert payload["ok"] is False
    assert str(error) in payload["error"]
