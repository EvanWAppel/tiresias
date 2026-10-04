"""End-to-end MCP tests: a client speaks the real protocol to the Tiresias server."""

from __future__ import annotations

from tiresias.mcp_client import warehouse_session


async def test_run_validated_sql_over_mcp(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        payload = await ware.run_sql("select count(*) as n from mart_restaurants")
    assert payload["ok"] is True
    assert payload["rows"][0]["n"] > 0
    # The tool echoes the exact hardened SQL (row cap included) for citation.
    assert "LIMIT 1000" in payload["sql"].upper()


async def test_guard_rejection_is_structured_over_mcp(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        payload = await ware.run_sql("drop table mart_restaurants")
    assert payload["ok"] is False
    assert "SELECT" in payload["error"] or "select" in payload["error"]


async def test_catalog_resource_over_mcp(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        catalog = await ware.read_catalog()
    assert "mart_restaurants" in catalog
    assert "failure_rate_pct" in catalog


async def test_metrics_resource_over_mcp(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        metrics = await ware.read_metrics()
    assert "restaurant_failure_rate" in metrics


async def test_list_tables_tool_over_mcp(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        payload = await ware.call_tool("list_tables", {})
    # MCP wraps a bare-list tool return under "result".
    names = {t["name"] for t in payload["result"]}
    assert {"mart_restaurants", "mart_top_violations"} <= names


async def test_profile_column_tool_over_mcp(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        payload = await ware.call_tool(
            "profile_column", {"table": "mart_restaurants", "column": "permit_number"}
        )
    assert payload["ok"] is True
    assert payload["row_count"] > 0
    # permit_number is the unique grain: distinct == rows, no nulls.
    assert payload["distinct_count"] == payload["row_count"]
    assert payload["null_count"] == 0


async def test_get_metric_tool_over_mcp(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        ok = await ware.call_tool("get_metric", {"name": "restaurant_failure_rate"})
        bad = await ware.call_tool("get_metric", {"name": "no_such_metric"})
    assert ok["ok"] is True and ok["source_column"] == "failure_rate_pct"
    assert bad["ok"] is False


async def test_profile_unknown_column_is_structured_error(_require_warehouse: None) -> None:
    async with warehouse_session() as ware:
        payload = await ware.call_tool(
            "profile_column", {"table": "mart_restaurants", "column": "nope"}
        )
    assert payload["ok"] is False


async def test_timeout_is_structured_over_mcp(
    _require_warehouse: None, monkeypatch
) -> None:
    from tiresias import tools

    def _slow(sql: str):
        raise tools.QueryTimeoutError("query timed out after 15.0s")

    monkeypatch.setattr(tools, "run_validated_sql", _slow)
    async with warehouse_session() as ware:
        payload = await ware.run_sql("select count(*) from mart_restaurants")
    assert payload["ok"] is False
    assert "timed out" in payload["error"]


async def test_oversized_result_is_structured_over_mcp(
    _require_warehouse: None, monkeypatch
) -> None:
    from tiresias import tools

    def _huge(sql: str):
        raise tools.ResultTooLargeError("result too large (999999 bytes > 256000)")

    monkeypatch.setattr(tools, "run_validated_sql", _huge)
    async with warehouse_session() as ware:
        payload = await ware.run_sql("select * from mart_parks")
    assert payload["ok"] is False
    assert "too large" in payload["error"]
