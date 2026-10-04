"""Tests for the dbt-artifact-sourced catalog."""

from __future__ import annotations

import json

import pytest

from tiresias.catalog import Catalog
from tiresias.config import ALLOWED_TABLES, EXCLUDED_TABLES, TiresiasSettings


def test_catalog_is_bounded_to_allowlist(catalog: Catalog) -> None:
    assert set(catalog.table_names) == set(ALLOWED_TABLES)


def test_catalog_spans_every_civic_domain(catalog: Catalog) -> None:
    names = set(catalog.table_names)
    for table in (
        "mart_restaurants",
        "mart_crime_monthly",
        "mart_permits_by_type",
        "mart_lvcva_indicators",
        "mart_weather_extreme_days",
        "mart_air_quality_monthly",
        "mart_marriage_by_origin",
        "mart_lake_mead_monthly",
        "mart_short_term_rentals",
        "mart_road_construction",
        "mart_parks",
        "mart_public_art_metro",
        "mart_fire_prevention_inspections",
        "mart_tract_metrics",
    ):
        assert table in names


def test_every_built_mart_is_classified(settings: TiresiasSettings, catalog: Catalog) -> None:
    # A new mart must be deliberately opted in or out: the built mart_* set has to
    # equal ALLOWED | EXCLUDED, and the two must not overlap.
    built = {
        node["metadata"]["name"]
        for node in json.loads(settings.catalog_path.read_text())["nodes"].values()
        if node["metadata"]["name"].startswith("mart_")
    }
    assert not set(ALLOWED_TABLES) & EXCLUDED_TABLES
    assert built == set(ALLOWED_TABLES) | EXCLUDED_TABLES


@pytest.mark.parametrize(
    "table", ["mart_tract_assignment_audit", "mart_crime_map_sample"]
)
def test_non_analytic_marts_are_not_queryable(catalog: Catalog, table: str) -> None:
    # Audit bookkeeping and the random map sample (~1% of calls) would mislead counts.
    assert table in EXCLUDED_TABLES
    assert table not in catalog.table_names


def test_every_column_is_documented(catalog: Catalog) -> None:
    # The planner grounds column meaning in these descriptions; an undocumented
    # column is a column the agent has to guess about.
    missing = [
        f"{t.name}.{c.name}" for t in catalog.tables for c in t.columns if not c.description
    ]
    assert missing == []


def test_restaurant_table_has_typed_failure_rate_column(catalog: Catalog) -> None:
    table = catalog.get("mart_restaurants")
    assert table.db_schema == "main"
    by_name = {col.name: col for col in table.columns}
    assert "failure_rate_pct" in by_name
    # Types come from the real warehouse introspection (catalog.json).
    assert by_name["failure_rate_pct"].type == "DOUBLE"
    assert by_name["permit_number"].type == "VARCHAR"


def test_column_descriptions_flow_from_manifest(catalog: Catalog) -> None:
    table = catalog.get("mart_restaurants")
    by_name = {col.name: col for col in table.columns}
    # failed_inspections is documented in the dbt schema.yml / model.
    assert "downgrade" in by_name["failed_inspections"].description.lower()


def test_to_prompt_lists_columns(catalog: Catalog) -> None:
    prompt = catalog.get("mart_top_violations").to_prompt()
    assert "mart_top_violations" in prompt
    assert "violation_code" in prompt


def test_unknown_table_raises(catalog: Catalog) -> None:
    with pytest.raises(KeyError, match="mart_restaurants"):
        catalog.get("mart_nonexistent")
