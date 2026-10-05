"""Static checks of a city's config against its own dbt artifacts."""

from __future__ import annotations

import json

from tiresias.check import check_config
from tiresias.config import Example, TiresiasConfig


def _messages(config: TiresiasConfig, severity: str) -> list[str]:
    return [p.message for p in check_config(config) if p.severity == severity]


def test_fixture_city_is_clean(config: TiresiasConfig) -> None:
    assert check_config(config) == []


def test_allowed_table_missing_from_artifacts(config: TiresiasConfig) -> None:
    scope = config.tables.model_copy(update={"allowed": config.tables.allowed | {"mart_gone"}})
    errors = _messages(config.model_copy(update={"tables": scope}), "error")
    assert any("mart_gone" in m for m in errors)


def test_map_only_column_that_does_not_exist(config: TiresiasConfig) -> None:
    scope = config.tables.model_copy(
        update={"map_only_columns": {"mart_park_areas": frozenset({"no_such_col"})}}
    )
    errors = _messages(config.model_copy(update={"tables": scope}), "error")
    assert any("no_such_col" in m for m in errors)


def test_example_grounding_to_unknown_name(config: TiresiasConfig) -> None:
    bad = Example(question="q", guidance="g", grounds=("mart_imaginary",))
    errors = _messages(config.model_copy(update={"examples": (bad,)}), "error")
    assert any("mart_imaginary" in m for m in errors)


def test_metric_reference_that_does_not_resolve(config: TiresiasConfig, tmp_path) -> None:
    metrics = tmp_path / "metrics.yml"
    metrics.write_text(
        config.metrics_path.read_text().replace(
            "mart_inspections.total_inspections", "mart_inspections.total_visits"
        )
    )
    errors = _messages(config.model_copy(update={"metrics": metrics}), "error")
    assert any("total_visits" in m for m in errors)


def test_undocumented_columns_are_warnings(config: TiresiasConfig, tmp_path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "catalog.json").write_text(config.catalog_path.read_text())
    manifest = json.loads(config.manifest_path.read_text())
    manifest["nodes"]["model.testville.mart_inspections"]["columns"]["restaurant_name"] = {
        "description": ""
    }
    (target / "manifest.json").write_text(json.dumps(manifest))
    problems = check_config(config.model_copy(update={"dbt_target": target}))
    assert [p.severity for p in problems] == ["warning"]
    assert "mart_inspections.restaurant_name" in problems[0].message


def test_missing_gold_file_is_a_warning(config: TiresiasConfig, tmp_path) -> None:
    gold = config.gold.model_copy(update={"answers": tmp_path / "nope.yaml"})
    warnings = _messages(config.model_copy(update={"gold": gold}), "warning")
    assert any("nope.yaml" in m for m in warnings)


def test_tables_outside_the_configured_schemas_are_errors(config: TiresiasConfig) -> None:
    # dbt wrote the marts to `main`; a config that only allows `analytics` can't query them.
    scope = config.tables.model_copy(update={"schemas": frozenset({"analytics"})})
    errors = _messages(config.model_copy(update={"tables": scope}), "error")
    assert any("main.mart_inspections" in m and "analytics" in m for m in errors)
