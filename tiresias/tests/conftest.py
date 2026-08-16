"""Shared pytest fixtures for the Tiresias suite.

These rely on the locally-built warehouse (``vegas.duckdb``) and dbt artifacts
(``target/manifest.json``, ``target/catalog.json``). Tests that need them are
skipped with a clear message when they are absent, so a fresh checkout fails
loudly-but-legibly rather than with a cryptic error.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

import pytest

from tiresias.catalog import Catalog, load_catalog
from tiresias.config import DEFAULT_SETTINGS, TiresiasSettings
from tiresias.metrics import MetricRegistry, load_registry


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
def settings() -> TiresiasSettings:
    return DEFAULT_SETTINGS


@pytest.fixture(scope="session")
def _require_warehouse(settings: TiresiasSettings) -> None:
    if not settings.db_path.exists():
        pytest.skip(
            f"warehouse absent at {settings.db_path}; "
            "run build_warehouse.py + dbt build to enable warehouse tests"
        )


@pytest.fixture(scope="session")
def _require_artifacts(settings: TiresiasSettings) -> None:
    for path in (settings.catalog_path, settings.manifest_path):
        if not path.exists():
            pytest.skip(
                f"dbt artifact absent at {path}; run `dbt docs generate` to enable"
            )


@pytest.fixture(scope="session")
def registry() -> MetricRegistry:
    return load_registry()


@pytest.fixture(scope="session")
def catalog(_require_artifacts: None) -> Catalog:
    return load_catalog()
