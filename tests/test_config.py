"""Tests for the per-city ``tiresias.yml`` config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tiresias.config import TiresiasConfig, load_config


def test_loads_city_identity(config: TiresiasConfig) -> None:
    assert config.city == "Testville"
    assert "service calls" in config.blurb


def test_paths_resolve_relative_to_the_yaml(config: TiresiasConfig, config_path: Path) -> None:
    root = config_path.parent
    assert config.db_path == root / "testville.duckdb"
    assert config.catalog_path == root / "target" / "catalog.json"
    assert config.manifest_path == root / "target" / "manifest.json"
    assert config.metrics_path == root / "metrics.yml"
    assert config.gold.answers == root / "evals" / "gold.yaml"
    assert config.gold.retrieval == root / "evals" / "retrieval_gold.yaml"


def test_table_scope(config: TiresiasConfig) -> None:
    assert "mart_inspections" in config.tables.allowed
    assert config.tables.excluded == frozenset({"mart_qa_audit"})
    assert config.tables.schemas == frozenset({"main"})
    assert dict(config.tables.map_only_columns) == {
        "mart_park_areas": frozenset({"geometry_json"}),
        "mart_events": frozenset({"path_json"}),
    }


def test_examples_limits_and_threshold(config: TiresiasConfig) -> None:
    assert config.examples[0].grounds == ("mart_inspections", "inspection_failure_rate")
    assert config.grounding.threshold == pytest.approx(0.30)
    assert config.limits.max_rows == 1000
    assert config.limits.statement_timeout_s == 15
    assert config.planner_notes


def test_config_is_frozen(config: TiresiasConfig) -> None:
    with pytest.raises(ValidationError):
        config.city = "Elsewhere"  # ty: ignore[invalid-assignment]


def test_with_limits_overrides_one_cap(config: TiresiasConfig) -> None:
    tighter = config.with_limits(max_rows=5)
    assert tighter.limits.max_rows == 5
    assert tighter.limits.statement_timeout_s == config.limits.statement_timeout_s
    assert config.limits.max_rows == 1000


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "tiresias.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def _minimal() -> dict:
    return {
        "city": "Nowhere",
        "blurb": "nothing much",
        "warehouse": "w.duckdb",
        "dbt_target": "target",
        "metrics": "metrics.yml",
        "tables": {"allowed": ["mart_a"]},
    }


def test_minimal_config_gets_default_limits(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, _minimal()))
    assert config.limits.max_rows == 1000
    assert config.tables.schemas == frozenset({"main"})
    assert config.gold.answers is None


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    # A typo in a security-relevant key (e.g. `alowed`) must not be silently ignored.
    data = _minimal() | {"tabels": {}}
    with pytest.raises(ValidationError, match="tabels"):
        load_config(_write(tmp_path, data))


def test_table_cannot_be_both_allowed_and_excluded(tmp_path: Path) -> None:
    data = _minimal()
    data["tables"] = {"allowed": ["mart_a"], "excluded": ["mart_a"]}
    with pytest.raises(ValidationError, match="mart_a"):
        load_config(_write(tmp_path, data))


def test_map_only_columns_must_name_an_allowed_table(tmp_path: Path) -> None:
    data = _minimal()
    data["tables"] = {"allowed": ["mart_a"], "map_only_columns": {"mart_b": ["geo"]}}
    with pytest.raises(ValidationError, match="mart_b"):
        load_config(_write(tmp_path, data))


def test_missing_config_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="tiresias.yml"):
        load_config(tmp_path / "tiresias.yml")


def test_map_only_columns_cannot_be_mutated(config: TiresiasConfig) -> None:
    # The map-only set is part of the security boundary shared by every component.
    with pytest.raises(TypeError):
        del config.tables.map_only_columns["mart_park_areas"]  # ty: ignore[not-subscriptable]


def test_with_limits_rejects_unknown_and_invalid_caps(config: TiresiasConfig) -> None:
    with pytest.raises(ValidationError, match="max_rowz"):
        config.with_limits(max_rowz=5)
    with pytest.raises(ValidationError):
        config.with_limits(max_rows=0)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("limits", "max_rows", 0),
        ("limits", "max_rows", -1),
        ("limits", "max_result_bytes", 0),
        ("limits", "statement_timeout_s", -1),
        ("limits", "max_per_day", 0),
        ("grounding", "threshold", -0.1),
        ("grounding", "threshold", 1.5),
        ("grounding", "threshold", float("nan")),
    ],
)
def test_out_of_range_values_are_rejected(
    tmp_path: Path, section: str, key: str, value: float
) -> None:
    data = _minimal() | {section: {key: value}}
    with pytest.raises(ValidationError, match=key):
        load_config(_write(tmp_path, data))


def test_home_relative_paths_expand(tmp_path: Path) -> None:
    data = _minimal() | {"warehouse": "~/w.duckdb"}
    assert load_config(_write(tmp_path, data)).db_path == Path.home() / "w.duckdb"


ELVIS = Path(__file__).resolve().parent.parent / "examples" / "elvis"


def test_elvis_reference_config_loads_and_grounds_to_its_scope() -> None:
    from tiresias.metrics import load_registry

    config = load_config(ELVIS / "tiresias.yml")
    known = config.tables.allowed | set(load_registry(config.metrics_path).names)
    for example in config.examples:
        assert set(example.grounds) <= known, example.question
    assert config.gold.answers is not None and config.gold.answers.exists()
    assert config.gold.retrieval is not None and config.gold.retrieval.exists()


def test_config_serializes_to_json(config: TiresiasConfig) -> None:
    assert '"mart_park_areas":["geometry_json"]' in config.model_dump_json()
