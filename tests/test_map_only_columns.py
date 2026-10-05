"""Map-only columns are invisible to and unselectable by the agent (review S2)."""

from __future__ import annotations

import pytest

from tiresias import db, tools
from tiresias.catalog import Catalog
from tiresias.config import TiresiasConfig
from tiresias.sql_guard import SqlGuardError, guard_sql
from tiresias.tools import ResultTooLargeError


def test_catalog_hides_map_only_columns(config: TiresiasConfig, catalog: Catalog) -> None:
    for table, hidden in config.tables.map_only_columns.items():
        assert not hidden & set(catalog.get(table).column_names)
    # Neighbouring analytic columns are still there.
    assert "acres" in catalog.get("mart_park_areas").column_names


@pytest.mark.parametrize(
    "sql",
    [
        "select geometry_json from mart_park_areas",
        "select GEOMETRY_JSON from mart_park_areas",
        'select "geometry_json" from mart_park_areas',
        "select p.geometry_json from mart_park_areas p",
        "select length(geometry_json) as n from mart_park_areas",
        "with x as (select geometry_json as g from mart_park_areas) select g from x",
        # DuckDB row-as-struct: a bare table name/alias selects the whole row.
        "select p from mart_park_areas p",
        "select to_json(p) as j from mart_park_areas p",
        "select mart_park_areas from mart_park_areas",
        # A second map-only table, alone and joined to the first.
        "select path_json from mart_events",
        "select p.acres, e.path_json from mart_park_areas p join mart_events e on true",
        "select e from mart_events e",
    ],
)
def test_guard_rejects_map_only_columns(config: TiresiasConfig, sql: str) -> None:
    with pytest.raises(SqlGuardError, match="map-only"):
        guard_sql(sql, config)


@pytest.mark.parametrize(
    "sql",
    [
        "select * from mart_park_areas",
        "select p.* from mart_park_areas p",
        "select columns('.*json') from mart_park_areas",
        "select * from mart_events",
        "select p.park_name, e.* from mart_park_areas p join mart_events e on true",
    ],
)
def test_guard_rejects_star_expansion_of_map_only_columns(config: TiresiasConfig, sql: str) -> None:
    conn = db.get_connection(config.db_path)
    with pytest.raises(SqlGuardError, match="map-only"):
        guard_sql(sql, config, connection=conn)


def test_guard_allows_analytic_columns_and_other_tables(config: TiresiasConfig) -> None:
    conn = db.get_connection(config.db_path)
    safe = guard_sql("select park_name, acres from mart_park_areas", config, connection=conn)
    assert safe.tables == ("mart_park_areas",)
    safe = guard_sql("select * from mart_inspections", config, connection=conn)
    assert safe.tables == ("mart_inspections",)


def test_oversized_result_is_rejected(config: TiresiasConfig) -> None:
    with pytest.raises(ResultTooLargeError, match="too large"):
        tools.run_validated_sql(
            "select park_name, address from mart_park_areas",
            config.with_limits(max_result_bytes=200),
        )
