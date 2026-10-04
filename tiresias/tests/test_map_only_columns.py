"""Map-only geometry columns are invisible to and unselectable by the agent (S2)."""

from __future__ import annotations

import pytest

from tiresias import db, tools
from tiresias.catalog import Catalog
from tiresias.config import DEFAULT_SETTINGS, MAP_ONLY_COLUMNS
from tiresias.sql_guard import SqlGuardError, guard_sql
from tiresias.tools import ResultTooLargeError


def test_map_only_columns_are_declared() -> None:
    assert MAP_ONLY_COLUMNS == {
        "mart_tract_metrics": frozenset({"geometry_json"}),
        "mart_road_construction": frozenset({"path_json"}),
    }


def test_catalog_hides_map_only_columns(catalog: Catalog) -> None:
    for table, hidden in MAP_ONLY_COLUMNS.items():
        assert not hidden & set(catalog.get(table).column_names)
    # Neighbouring analytic columns are still there.
    assert "rate_per_1000" in catalog.get("mart_tract_metrics").column_names


@pytest.mark.parametrize(
    "sql",
    [
        "select geometry_json from mart_tract_metrics",
        "select GEOMETRY_JSON from mart_tract_metrics",
        'select "geometry_json" from mart_tract_metrics',
        "select t.geometry_json from mart_tract_metrics t",
        "select length(geometry_json) as n from mart_tract_metrics",
        "select path_json from mart_road_construction",
        "with x as (select path_json as p from mart_road_construction) select p from x",
        # DuckDB row-as-struct: a bare table name/alias selects the whole row.
        "select t from mart_tract_metrics t",
        "select to_json(t) as j from mart_tract_metrics t",
        "select mart_road_construction from mart_road_construction",
    ],
)
def test_guard_rejects_map_only_columns(sql: str) -> None:
    with pytest.raises(SqlGuardError, match="map-only"):
        guard_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "select * from mart_tract_metrics",
        "select t.* from mart_road_construction t",
        "select columns('.*json') from mart_tract_metrics",
    ],
)
def test_guard_rejects_star_expansion_of_map_only_columns(
    _require_warehouse: None, sql: str
) -> None:
    conn = db.get_connection(DEFAULT_SETTINGS.db_path)
    with pytest.raises(SqlGuardError, match="map-only"):
        guard_sql(sql, connection=conn)


def test_guard_allows_analytic_columns_of_those_tables(_require_warehouse: None) -> None:
    conn = db.get_connection(DEFAULT_SETTINGS.db_path)
    safe = guard_sql(
        "select topic, geoid, coverage, rate_per_1000 from mart_tract_metrics",
        connection=conn,
    )
    assert safe.tables == ("mart_tract_metrics",)
    safe = guard_sql("select * from mart_parks", connection=conn)
    assert safe.tables == ("mart_parks",)


def test_oversized_result_is_rejected(_require_warehouse: None) -> None:
    settings = DEFAULT_SETTINGS.model_copy(update={"max_result_bytes": 200})
    with pytest.raises(ResultTooLargeError, match="too large"):
        tools.run_validated_sql(
            "select park_name, address from mart_parks", settings=settings
        )
