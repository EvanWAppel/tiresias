"""Shared pytest fixtures: a hermetic, synthetic city ("Testville").

The static half of the city (``tiresias.yml``, metrics, gold sets) lives in
``tests/fixtures/testville``. The session fixture copies it to a temp dir, then
builds the rest the way a real city's pipeline would: a small DuckDB warehouse
plus minimal dbt ``target/catalog.json`` and ``target/manifest.json``. No real
warehouse, network, or API key is needed.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path

import duckdb
import pytest

from tiresias.catalog import Catalog, load_catalog
from tiresias.config import TiresiasConfig, load_config
from tiresias.metrics import MetricRegistry, load_registry

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "testville"

# Rows big enough that a 3-way self cross join of mart_events runs for minutes
# without the statement timeout (3000^3 rows), while each table builds instantly.
_WAREHOUSE_SQL = """
create table mart_inspections as
select
    'P' || lpad(i::varchar, 4, '0') as permit_number,
    'Restaurant ' || i as restaurant_name,
    10 + i % 7 as total_inspections,
    i % 4 as failed_inspections,
    round((i % 4) / (10 + i % 7) * 100, 1) as failure_rate_pct
from range(1, 51) t(i);

create table mart_top_violations as
select
    'V' || i as violation_code,
    'Violation number ' || i as violation_description,
    (100 - i * 3)::integer as occurrence_count,
    (i % 5 + 1)::integer as demerits
from range(1, 21) t(i);

create table mart_service_calls_monthly as
select
    (date '2024-01-01' + to_months(i::integer))::date as call_month,
    (500 + i * 11)::integer as call_count
from range(0, 24) t(i);

create table mart_park_areas as
select
    'Park ' || i as park_name,
    (i * 2.5)::double as acres,
    i || ' Main Street' as address,
    '{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}' as geometry_json
from range(1, 31) t(i);

create table mart_events as
select
    i::integer as event_id,
    'kind ' || (i % 9) as event_kind,
    '[[0,0],[1,1]]' as path_json
from range(1, 3001) t(i);

create table mart_qa_audit as
select i::integer as audit_id, 'ok' as status from range(1, 6) t(i);

create view stg_service_calls as select * from mart_service_calls_monthly;
"""

TABLE_DOCS: dict[str, str] = {
    "mart_inspections": "One row per restaurant permit with inspection outcomes.",
    "mart_top_violations": "Health-code violations ranked by how often they occur.",
    "mart_service_calls_monthly": "Monthly count of service calls.",
    "mart_park_areas": "City parks with their size and map shape.",
    "mart_events": "One row per logged event.",
    "mart_qa_audit": "Internal QA bookkeeping.",
}

COLUMN_DOCS: dict[str, str] = {
    "permit_number": "Restaurant permit id; the grain of mart_inspections.",
    "restaurant_name": "Restaurant name as registered.",
    "total_inspections": "Count of inspections on record.",
    "failed_inspections": "Count of inspections that were a downgrade or closure.",
    "failure_rate_pct": "Failed inspections as a percent of total inspections.",
    "violation_code": "Health-code violation code.",
    "violation_description": "Plain-language description of the violation.",
    "occurrence_count": "How many times the violation was cited.",
    "demerits": "Demerit points the violation carries.",
    "call_month": "First day of the month.",
    "call_count": "Service calls received that month.",
    "park_name": "Park name.",
    "acres": "Park area in acres.",
    "address": "Street address of the park entrance.",
    "geometry_json": "GeoJSON boundary for the map page.",
    "event_id": "Event id.",
    "event_kind": "Kind of event.",
    "path_json": "GeoJSON line for the map page.",
    "audit_id": "Audit row id.",
    "status": "Audit status.",
}


def build_city(root: Path) -> Path:
    """Materialize Testville under ``root``; return its ``tiresias.yml`` path."""
    shutil.copytree(FIXTURE_DIR, root, dirs_exist_ok=True)
    db_path = root / "testville.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(_WAREHOUSE_SQL)
        rows = conn.execute(
            "select table_name, column_name, data_type, ordinal_position "
            "from information_schema.columns where table_schema = 'main' "
            "order by table_name, ordinal_position"
        ).fetchall()

    catalog_nodes: dict[str, dict] = {}
    manifest_nodes: dict[str, dict] = {}
    for table, column, data_type, position in rows:
        uid = f"model.testville.{table}"
        node = catalog_nodes.setdefault(
            uid,
            {
                "metadata": {"name": table, "schema": "main", "database": "testville"},
                "columns": {},
            },
        )
        node["columns"][column] = {"name": column, "type": data_type, "index": position}
        doc = manifest_nodes.setdefault(
            uid, {"description": TABLE_DOCS.get(table, ""), "columns": {}}
        )
        doc["columns"][column] = {"description": COLUMN_DOCS.get(column, "")}

    target = root / "target"
    target.mkdir()
    (target / "catalog.json").write_text(json.dumps({"nodes": catalog_nodes}))
    (target / "manifest.json").write_text(json.dumps({"nodes": manifest_nodes}))
    return root / "tiresias.yml"


class FakeEmbedder:
    """Deterministic, offline embedder: stable-hashed bag-of-words vectors.

    Good enough to exercise cosine ranking and grounded/ungrounded separation
    without downloading a real model. Stable across runs (hashlib, not ``hash``).
    """

    dim = 256

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            # Split on non-letters so `violation_code` -> {violation, code}, giving
            # the fake lexical overlap on real column names.
            for token in re.findall(r"[a-z]+", text.lower()):
                idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim
                vec[idx] += 1.0
            vectors.append(vec)
        return vectors


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture(scope="session")
def config_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_city(tmp_path_factory.mktemp("testville"))


@pytest.fixture(scope="session")
def config(config_path: Path) -> TiresiasConfig:
    return load_config(config_path)


@pytest.fixture(scope="session")
def registry(config: TiresiasConfig) -> MetricRegistry:
    return load_registry(config.metrics_path)


@pytest.fixture(scope="session")
def catalog(config: TiresiasConfig) -> Catalog:
    return load_catalog(config)
