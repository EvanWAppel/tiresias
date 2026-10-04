"""Tiresias configuration — paths, read-only query caps, and the queryable table scope.

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

# Query scope: every user-facing Elvis mart across all civic domains. Kept as an
# explicit list (not "every mart_*") because it is a security boundary — a new
# mart must be deliberately opted in. The catalog, retrieval corpus, and the SQL
# allowlist are all bounded to these.
ALLOWED_TABLES: tuple[str, ...] = (
    # Restaurant inspections (SNHD)
    "mart_restaurants",
    "mart_inspection_history",
    "mart_inspection_violations",
    "mart_top_violations",
    "mart_inspections_over_time",
    # Crime (LVMPD calls for service)
    "mart_crime_by_type",
    "mart_crime_by_hour_weekday",
    "mart_crime_monthly",
    # Building permits + business licenses
    "mart_permits_monthly",
    "mart_permits_by_type",
    "mart_henderson_permits",
    "mart_henderson_licenses_by_type",
    # Tourism, environment, civic life
    "mart_lvcva_indicators",
    "mart_weather_monthly",
    "mart_weather_extreme_days",
    "mart_air_quality_daily",
    "mart_air_quality_monthly",
    "mart_lake_mead_monthly",
    "mart_marriage_monthly",
    "mart_marriage_daily",
    "mart_marriage_by_origin",
    "mart_marriage_by_gender_year",
    # Places and inventories
    "mart_short_term_rentals",
    "mart_road_construction",
    "mart_parks",
    "mart_art_work_points",
    "mart_public_art_metro",
    "mart_fire_prevention_inspections",
    "mart_tract_metrics",
)

# Built marts deliberately kept out of scope (a test requires every built mart_*
# to be in exactly one of ALLOWED_TABLES / EXCLUDED_TABLES):
#   - mart_tract_assignment_audit: internal QA bookkeeping, not a civic dataset.
#   - mart_crime_map_sample: a random ~12k-row sample (~1% of calls) for the map;
#     any count or total from it would be a silent undercount.
EXCLUDED_TABLES: frozenset[str] = frozenset(
    {"mart_tract_assignment_audit", "mart_crime_map_sample"}
)

# Map-only geometry columns inside allowed tables: hidden from the agent's catalog
# and rejected by the SQL guard. They hold JSON shapes for the map pages (tract
# boundaries up to ~320 KB per row), carry no analytic meaning, and would bloat
# results and prompts. The Streamlit map pages read the warehouse directly and are
# unaffected.
MAP_ONLY_COLUMNS: dict[str, frozenset[str]] = {
    "mart_tract_metrics": frozenset({"geometry_json"}),
    "mart_road_construction": frozenset({"path_json"}),
}


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
    # Table allowlist (see ALLOWED_TABLES).
    allowed_tables: frozenset[str] = frozenset(ALLOWED_TABLES)

    # Hard row cap injected into every executed query (defense against runaway scans).
    max_rows: int = 1000
    # Backstop on the serialized result (bytes): catches oversized payloads from any
    # shape of query the guard's column checks don't anticipate.
    max_result_bytes: int = 256_000
    # Wall-clock cap (seconds) on executing a validated query; enforced in
    # tools.run_validated_sql by a watchdog that interrupts the DuckDB cursor.
    statement_timeout_s: float = 15.0


DEFAULT_SETTINGS = TiresiasSettings()
