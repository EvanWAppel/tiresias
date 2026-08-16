"""Tests for the dbt-artifact-sourced catalog."""

from __future__ import annotations

import pytest

from tiresias.catalog import Catalog
from tiresias.config import PHASE0_TABLES


def test_catalog_is_bounded_to_phase0_allowlist(catalog: Catalog) -> None:
    assert set(catalog.table_names) == set(PHASE0_TABLES)


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
