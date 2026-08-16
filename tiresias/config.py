"""Tiresias configuration — paths, read-only query caps, and Phase-0 domain scope.

These are read-only defaults; construct ``TiresiasSettings(...)`` to override in
tests (e.g. point ``db_path`` at a fixture warehouse). Nothing here talks to an
LLM — the model id and provider settings live in ``tiresias/provider.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Repo root = parent of the tiresias/ package. The warehouse and dbt artifacts are
# written here by build_warehouse.py + dbt build (both gitignored, rebuilt on deploy).
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "vegas.duckdb"
MANIFEST_PATH = REPO_ROOT / "target" / "manifest.json"
CATALOG_PATH = REPO_ROOT / "target" / "catalog.json"
METRICS_PATH = Path(__file__).resolve().parent / "metrics.yml"

# Phase-0 scope: restaurant-inspection marts only. The catalog, retrieval corpus,
# and the SQL allowlist are all bounded to these until later phases widen the domain.
PHASE0_TABLES: tuple[str, ...] = (
    "mart_restaurants",
    "mart_inspection_violations",
    "mart_top_violations",
    "mart_inspections_over_time",
)


class TiresiasSettings(BaseModel):
    """Read-only execution guardrails for the validated SQL tool.

    Frozen so a set of settings can be shared across the MCP server, agent, and
    eval harness without any component mutating another's caps mid-run.
    """

    model_config = {"frozen": True}

    db_path: Path = DB_PATH
    manifest_path: Path = MANIFEST_PATH
    catalog_path: Path = CATALOG_PATH
    metrics_path: Path = METRICS_PATH

    # dbt materializes marts into the `main` schema (profiles.yml). The guard rejects
    # any table reference outside these schemas.
    allowed_schemas: frozenset[str] = frozenset({"main"})
    # Phase-0 table allowlist; widen per phase as domains come online.
    allowed_tables: frozenset[str] = frozenset(PHASE0_TABLES)

    # Hard row cap injected into every executed query (defense against runaway scans).
    max_rows: int = 1000
    # Reserved cost cap (seconds). Not yet enforced in Phase 0 — the row cap,
    # read-only connection, and allowlist are the active guards; wire a real query
    # timeout in a later phase.
    statement_timeout_s: float = 15.0


DEFAULT_SETTINGS = TiresiasSettings()
