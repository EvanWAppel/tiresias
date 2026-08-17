"""Tests for the governed metric registry."""

from __future__ import annotations

import pytest

from tiresias.catalog import Catalog
from tiresias.metrics import Metric, MetricRegistry, get_metric


def test_registry_loads_and_is_versioned(registry: MetricRegistry) -> None:
    assert registry.version == 1
    assert "restaurant_failure_rate" in registry.names


def test_failure_rate_metric_is_grounded(registry: MetricRegistry) -> None:
    metric = registry.get("restaurant_failure_rate")
    assert isinstance(metric, Metric)
    assert metric.source_table == "mart_restaurants"
    assert metric.source_column == "failure_rate_pct"
    assert metric.unit == "percent"
    # Canonical arithmetic, not reinvented: numerator/denominator trace to real columns.
    assert metric.numerator == "failed_inspections"
    assert metric.denominator == "total_inspections"
    assert "failed_inspections" in metric.expression
    assert "total_inspections" in metric.expression
    assert "mart_restaurants.failure_rate_pct" in metric.references


def test_get_metric_convenience_matches_registry(registry: MetricRegistry) -> None:
    assert get_metric("restaurant_failure_rate") == registry.get("restaurant_failure_rate")


def test_unknown_metric_raises_with_known_names(registry: MetricRegistry) -> None:
    with pytest.raises(KeyError, match="restaurant_failure_rate"):
        registry.get("no_such_metric")


def test_every_metric_is_grounded_in_the_catalog(
    registry: MetricRegistry, catalog: Catalog
) -> None:
    """The semantic layer must trace to real columns — a metric that references a
    column the catalog doesn't have is a broken governed definition."""
    for metric in registry.metrics:
        table = catalog.get(metric.source_table)  # raises if the table is unknown
        assert metric.source_column in table.column_names, (
            f"{metric.name}: source_column {metric.source_column!r} "
            f"not in {metric.source_table}"
        )
        for ref in metric.references:
            ref_table, _, ref_column = ref.partition(".")
            assert ref_column in catalog.get(ref_table).column_names, (
                f"{metric.name}: reference {ref!r} does not resolve in the catalog"
            )

