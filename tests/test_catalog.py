"""Tests for the dbt-artifact-sourced catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiresias.catalog import Catalog, load_catalog
from tiresias.config import TiresiasConfig


def test_catalog_is_bounded_to_allowlist(config: TiresiasConfig, catalog: Catalog) -> None:
    assert set(catalog.table_names) == set(config.tables.allowed)


def test_excluded_and_staging_tables_are_not_in_catalog(catalog: Catalog) -> None:
    assert "mart_qa_audit" not in catalog.table_names
    assert "stg_service_calls" not in catalog.table_names


def test_columns_carry_warehouse_types(catalog: Catalog) -> None:
    table = catalog.get("mart_inspections")
    assert table.db_schema == "main"
    by_name = {col.name: col for col in table.columns}
    assert by_name["failure_rate_pct"].type == "DOUBLE"
    assert by_name["permit_number"].type == "VARCHAR"


def test_column_descriptions_flow_from_manifest(catalog: Catalog) -> None:
    by_name = {c.name: c for c in catalog.get("mart_inspections").columns}
    assert "downgrade" in by_name["failed_inspections"].description.lower()
    assert catalog.get("mart_inspections").description


def test_columns_keep_warehouse_order(catalog: Catalog) -> None:
    assert catalog.get("mart_inspections").column_names[0] == "permit_number"


def test_to_prompt_lists_columns(catalog: Catalog) -> None:
    prompt = catalog.get("mart_top_violations").to_prompt()
    assert "main.mart_top_violations" in prompt
    assert "violation_code" in prompt


def test_unknown_table_raises(catalog: Catalog) -> None:
    with pytest.raises(KeyError, match="mart_inspections"):
        catalog.get("mart_nonexistent")


def test_missing_artifacts_raise(config: TiresiasConfig, tmp_path: Path) -> None:
    broken = config.model_copy(update={"dbt_target": tmp_path})
    with pytest.raises(FileNotFoundError, match="dbt docs generate"):
        load_catalog(broken)


def test_allowlist_matching_nothing_raises(config: TiresiasConfig) -> None:
    scope = config.tables.model_copy(
        update={"allowed": frozenset({"mart_missing"}), "map_only_columns": {}}
    )
    with pytest.raises(ValueError, match="No allowed tables"):
        load_catalog(config.model_copy(update={"tables": scope}))


def test_docs_match_mixed_case_columns(config: TiresiasConfig, tmp_path: Path) -> None:
    # dbt lowercases unquoted column keys in manifest.json, while DuckDB's catalog
    # keeps the case the column was created with; identifiers are case-insensitive.
    import json

    target = tmp_path / "target"
    target.mkdir()
    catalog = json.loads(config.catalog_path.read_text())
    node = catalog["nodes"]["model.testville.mart_park_areas"]
    node["columns"]["Park_Name"] = node["columns"].pop("park_name") | {"name": "Park_Name"}
    (target / "catalog.json").write_text(json.dumps(catalog))
    (target / "manifest.json").write_text(config.manifest_path.read_text())

    table = load_catalog(config.model_copy(update={"dbt_target": target})).get("mart_park_areas")
    by_name = {c.name: c for c in table.columns}
    assert by_name["Park_Name"].description == "Park name."
