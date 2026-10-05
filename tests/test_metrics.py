"""Tests for the governed metric registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiresias.catalog import Catalog
from tiresias.config import TiresiasConfig
from tiresias.metrics import Metric, MetricRegistry, get_metric, load_registry


def test_registry_loads_and_is_versioned(registry: MetricRegistry) -> None:
    assert registry.version == 1
    assert registry.names == ("inspection_failure_rate",)


def test_metric_is_grounded(registry: MetricRegistry) -> None:
    metric = registry.get("inspection_failure_rate")
    assert isinstance(metric, Metric)
    assert metric.source_table == "mart_inspections"
    assert metric.source_column == "failure_rate_pct"
    assert metric.numerator == "failed_inspections"
    assert "mart_inspections.failure_rate_pct" in metric.references


def test_get_metric_convenience_matches_registry(
    registry: MetricRegistry, config: TiresiasConfig
) -> None:
    assert get_metric("inspection_failure_rate", config.metrics_path) == registry.get(
        "inspection_failure_rate"
    )


def test_unknown_metric_raises_with_known_names(registry: MetricRegistry) -> None:
    with pytest.raises(KeyError, match="inspection_failure_rate"):
        registry.get("no_such_metric")


def test_missing_registry_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Metric registry"):
        load_registry(tmp_path / "metrics.yml")


def test_every_metric_is_grounded_in_the_catalog(
    registry: MetricRegistry, catalog: Catalog
) -> None:
    for metric in registry.metrics:
        table = catalog.get(metric.source_table)
        assert metric.source_column in table.column_names
        for ref in metric.references:
            ref_table, _, ref_column = ref.partition(".")
            assert ref_column in catalog.get(ref_table).column_names
