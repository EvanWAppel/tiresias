"""Static checks of a city's ``tiresias.yml`` against its own dbt artifacts.

Errors mean the config cannot work as written (a table or column it names does
not exist). Warnings mean it will run but less well: an undocumented column is a
column the planner has to guess about, and a missing gold file means no eval.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel

from tiresias.catalog import load_catalog
from tiresias.config import TiresiasConfig
from tiresias.metrics import load_registry

logger = logging.getLogger(__name__)


class Problem(BaseModel):
    model_config = {"frozen": True}

    severity: Literal["error", "warning"]
    message: str


def check_config(config: TiresiasConfig) -> list[Problem]:
    """Every problem found, errors first."""
    problems: list[Problem] = []

    def error(message: str) -> None:
        problems.append(Problem(severity="error", message=message))

    def warning(message: str) -> None:
        problems.append(Problem(severity="warning", message=message))

    catalog = load_catalog(config)
    registry = load_registry(config.metrics_path)
    tables = {t.name: t for t in catalog.tables}

    for name in sorted(config.tables.allowed - set(tables)):
        error(f"allowed table {name} is not in the dbt catalog")

    for table in catalog.tables:
        if table.db_schema not in config.tables.schemas:
            error(
                f"table {table.db_schema}.{table.name} is outside the allowed schemas "
                f"{sorted(config.tables.schemas)}"
            )

    # The catalog already hides map-only columns, so look them up in the raw artifact.
    raw_columns = _raw_columns(config)
    for table, columns in sorted(config.tables.map_only_columns.items()):
        for column in sorted(columns - raw_columns.get(table, set())):
            error(f"map-only column {table}.{column} does not exist")

    known = set(tables) | set(registry.names)
    for i, example in enumerate(config.examples):
        for name in example.grounds:
            if name not in known:
                error(f"example {i} ({example.question!r}) grounds to unknown {name}")

    for metric in registry.metrics:
        refs = (f"{metric.source_table}.{metric.source_column}", *metric.references)
        for ref in refs:
            table, _, column = ref.partition(".")
            if table not in tables or column not in tables[table].column_names:
                error(f"metric {metric.name} references {ref}, which does not resolve")

    for table in catalog.tables:
        for column in table.columns:
            if not column.description:
                warning(f"column {table.name}.{column.name} has no dbt description")

    for label, path in (("answer", config.gold.answers), ("retrieval", config.gold.retrieval)):
        if path is None:
            warning(f"no {label} gold set configured")
        elif not path.exists():
            warning(f"{label} gold set not found at {path}")

    problems.sort(key=lambda p: p.severity != "error")
    logger.debug("check_config found %d problems", len(problems))
    return problems


def _raw_columns(config: TiresiasConfig) -> dict[str, set[str]]:
    nodes = json.loads(config.catalog_path.read_text()).get("nodes", {})
    return {
        node["metadata"]["name"]: set(node["columns"])
        for node in nodes.values()
        if node["metadata"]["name"] in config.tables.allowed
    }
