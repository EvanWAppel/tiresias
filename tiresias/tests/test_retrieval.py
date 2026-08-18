"""Tests for dense retrieval over the schema + metric corpus.

Most tests use the offline FakeEmbedder (deterministic, no network). One test
exercises the real fastembed backend end-to-end and skips if the model cannot be
fetched (e.g. no network in CI).
"""

from __future__ import annotations

import pytest

from tiresias.catalog import Catalog
from tiresias.metrics import MetricRegistry
from tiresias.retrieval import (
    FastEmbedEmbedder,
    Retriever,
    build_corpus,
)
from tiresias.tests.conftest import FakeEmbedder


@pytest.fixture
def corpus(catalog: Catalog, registry: MetricRegistry):
    return build_corpus(catalog=catalog, registry=registry)


@pytest.fixture
def retriever(fake_embedder: FakeEmbedder, corpus) -> Retriever:
    return Retriever(embedder=fake_embedder, corpus=corpus)


def test_corpus_covers_tables_metrics_and_exemplars(corpus) -> None:
    kinds = {doc.kind for doc in corpus}
    assert kinds == {"table", "metric", "exemplar"}
    refs = {doc.ref for doc in corpus if doc.kind == "table"}
    assert "mart_top_violations" in refs


def test_violations_query_retrieves_violations_table(retriever: Retriever) -> None:
    # A top hit should point at the violations table — via the table doc (ref == name)
    # or an exemplar whose answer names it.
    hits = retriever.retrieve("what are the most common violations", k=4)
    assert any("mart_top_violations" in h.doc.ref for h in hits)


def test_failure_rate_query_retrieves_metric(retriever: Retriever) -> None:
    hits = retriever.retrieve("restaurant inspection failure rate", k=4)
    assert any("restaurant_failure_rate" in h.doc.ref for h in hits)


def test_in_domain_outscores_out_of_domain(retriever: Retriever) -> None:
    # grounding_score is the calibrated dense signal (retrieve() now returns RRF
    # fusion scores, which are rank-based rather than relevance magnitudes).
    in_score = retriever.grounding_score("restaurant inspection violations")
    out_score = retriever.grounding_score("lake mead water elevation forecast")
    assert in_score > out_score


def test_out_of_domain_is_ungrounded(retriever: Retriever) -> None:
    # A query with no lexical overlap scores ~0, well under the threshold.
    assert retriever.is_grounded("bitcoin price tomorrow") is False


def test_retrieve_respects_k(retriever: Retriever) -> None:
    assert len(retriever.retrieve("inspections", k=2)) == 2


@pytest.mark.slow
def test_fastembed_backend_end_to_end(catalog: Catalog, registry: MetricRegistry) -> None:
    """Real dense retrieval with fastembed; skipped if the model can't be fetched."""
    try:
        retriever = Retriever(
            embedder=FastEmbedEmbedder(),
            corpus=build_corpus(catalog=catalog, registry=registry),
        )
    except Exception as exc:  # noqa: BLE001 — network / model-download failure in CI
        pytest.skip(f"fastembed model unavailable: {exc}")

    assert retriever.is_grounded("which restaurants fail inspection most often?") is True
    assert retriever.is_grounded("what is the weather forecast for Reno?") is False
    # Hybrid surfaces the violations context via the table doc, its metric, or the
    # matching exemplar — any top hit that points at mart_top_violations counts.
    hits = retriever.retrieve("most common health code violations", k=3)
    assert any("mart_top_violations" in h.doc.ref for h in hits)
