"""Tests for hybrid retrieval over the schema + metric + example corpus.

Most tests use the offline FakeEmbedder (deterministic, no network). One test
exercises the real fastembed backend end-to-end and skips if the model cannot be
fetched (e.g. no network in CI).
"""

from __future__ import annotations

import pytest

from tests.conftest import FakeEmbedder
from tiresias.catalog import Catalog
from tiresias.config import TiresiasConfig
from tiresias.metrics import MetricRegistry
from tiresias.retrieval import FastEmbedEmbedder, RetrievedDoc, Retriever, build_corpus


@pytest.fixture
def corpus(
    catalog: Catalog, registry: MetricRegistry, config: TiresiasConfig
) -> tuple[RetrievedDoc, ...]:
    return build_corpus(catalog, registry, config.examples)


@pytest.fixture
def retriever(fake_embedder: FakeEmbedder, corpus, config: TiresiasConfig) -> Retriever:
    return Retriever(fake_embedder, corpus, config.grounding.threshold)


def test_corpus_covers_tables_metrics_and_examples(corpus, config: TiresiasConfig) -> None:
    kinds = [doc.kind for doc in corpus]
    assert set(kinds) == {"table", "metric", "exemplar"}
    assert kinds.count("exemplar") == len(config.examples)
    assert "mart_top_violations" in {doc.ref for doc in corpus if doc.kind == "table"}


def test_violations_query_retrieves_violations_table(retriever: Retriever) -> None:
    hits = retriever.retrieve("what are the most common violations", k=4)
    assert any("mart_top_violations" in h.doc.grounds for h in hits)


def test_failure_rate_query_retrieves_metric(retriever: Retriever) -> None:
    hits = retriever.retrieve("restaurant inspection failure rate", k=4)
    assert any("inspection_failure_rate" in h.doc.grounds for h in hits)


def test_in_domain_outscores_out_of_domain(retriever: Retriever) -> None:
    in_score = retriever.grounding_score("restaurant inspection violations")
    out_score = retriever.grounding_score("weather forecast for the weekend")
    assert in_score > out_score


def test_out_of_domain_is_ungrounded(retriever: Retriever) -> None:
    # A query with no lexical overlap scores ~0, well under the threshold.
    assert retriever.is_grounded("bitcoin price tomorrow") is False


def test_threshold_comes_from_config(fake_embedder: FakeEmbedder, corpus) -> None:
    query = "restaurant inspection violations"
    assert Retriever(fake_embedder, corpus, threshold=0.0).is_grounded(query) is True
    assert Retriever(fake_embedder, corpus, threshold=1.01).is_grounded(query) is False


def test_retrieve_respects_k(retriever: Retriever) -> None:
    assert len(retriever.retrieve("inspections", k=2)) == 2


def test_empty_corpus_is_rejected(fake_embedder: FakeEmbedder) -> None:
    with pytest.raises(ValueError, match="empty"):
        Retriever(fake_embedder, (), threshold=0.5)


def test_from_config_builds_city_corpus(
    config: TiresiasConfig, fake_embedder: FakeEmbedder
) -> None:
    retriever = Retriever.from_config(config, embedder=fake_embedder)
    assert retriever.threshold == config.grounding.threshold
    assert any(doc.kind == "exemplar" for doc in retriever.corpus)


def test_example_grounds_name_real_tables(
    corpus, catalog: Catalog, registry: MetricRegistry
) -> None:
    known = set(catalog.table_names) | set(registry.names)
    for doc in corpus:
        assert doc.grounds, doc.doc_id
        assert set(doc.grounds) <= known, (doc.doc_id, doc.grounds)


@pytest.mark.slow
def test_fastembed_backend_end_to_end(corpus, config: TiresiasConfig) -> None:
    """Real dense retrieval with fastembed; skipped if the model can't be fetched."""
    try:
        retriever = Retriever(FastEmbedEmbedder(), corpus, config.grounding.threshold)
    except Exception as exc:  # noqa: BLE001 — network / model-download failure in CI
        pytest.skip(f"fastembed model unavailable: {exc}")
    hits = retriever.retrieve("most common health code violations", k=3)
    assert any("mart_top_violations" in h.doc.grounds for h in hits)
    assert retriever.grounding_score(
        "which restaurants fail inspection?"
    ) > retriever.grounding_score("what's the best laptop to buy?")
