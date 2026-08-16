"""Governed metric registry — typed loader over ``metrics.yml``.

The registry is the semantic layer's Phase-0 form: canonical, grounded metric
definitions the agent is required to use instead of improvising arithmetic. It is
also surfaced as an MCP resource (see ``tiresias/mcp_server.py``).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel

from tiresias.config import METRICS_PATH

logger = logging.getLogger(__name__)


class Metric(BaseModel):
    """One canonical, grounded metric definition."""

    model_config = {"frozen": True}

    name: str
    label: str
    grain: str
    description: str
    unit: str
    source_table: str
    source_column: str
    # Canonical SQL expression, lifted verbatim from the dbt model.
    expression: str
    numerator: str | None = None
    denominator: str | None = None
    # Fully-qualified ``table.column`` references this metric is grounded in.
    references: tuple[str, ...] = ()


class MetricRegistry(BaseModel):
    """The full set of governed metrics."""

    model_config = {"frozen": True}

    version: int
    metrics: tuple[Metric, ...]

    def get(self, name: str) -> Metric:
        """Return the metric named ``name`` or raise ``KeyError`` with the known set."""
        for metric in self.metrics:
            if metric.name == name:
                return metric
        raise KeyError(
            f"No governed metric named {name!r}; known metrics: {list(self.names)}"
        )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(metric.name for metric in self.metrics)


def load_registry(path: Path = METRICS_PATH) -> MetricRegistry:
    """Parse and validate the metric registry YAML."""
    logger.debug("Loading metric registry from %s", path)
    data = yaml.safe_load(path.read_text())
    return MetricRegistry.model_validate(data)


def get_metric(name: str, path: Path = METRICS_PATH) -> Metric:
    """Convenience: load the registry and return one metric by name."""
    return load_registry(path).get(name)
