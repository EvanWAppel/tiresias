"""Retrieval-quality mini-eval — recall@k for hybrid retrieval.

Uses the real fastembed backend (marked ``slow``; skips if the model can't be
fetched). No LLM involved, so it proves the RAG layer on its own: for each labeled
query, at least one expected table/metric ref must land in the top-k. A retrieval
regression (a bad fusion tweak, a corpus change) turns this red deterministically.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tiresias.catalog import Catalog
from tiresias.metrics import MetricRegistry
from tiresias.retrieval import FastEmbedEmbedder, Retriever, build_corpus

GOLD = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "evals" / "retrieval_gold.yaml").read_text()
)


@pytest.mark.slow
def test_hybrid_retrieval_recall_at_k(
    catalog: Catalog, registry: MetricRegistry
) -> None:
    try:
        retriever = Retriever(
            FastEmbedEmbedder(),
            corpus=build_corpus(catalog=catalog, registry=registry),
        )
    except Exception as exc:  # noqa: BLE001 — model download failure in CI
        pytest.skip(f"fastembed model unavailable: {exc}")

    k = GOLD["k"]
    hits = []
    for case in GOLD["cases"]:
        refs = " ".join(h.doc.ref for h in retriever.retrieve(case["query"], k=k))
        ok = any(expected in refs for expected in case["expect_any"])
        hits.append(ok)
        if not ok:
            print(f"MISS: {case['query']!r} -> expected any of {case['expect_any']}")

    recall = sum(hits) / len(hits)
    print(f"hybrid retrieval recall@{k} = {recall:.2f} ({sum(hits)}/{len(hits)})")
    assert recall >= GOLD["min_recall"], (
        f"recall@{k} {recall:.2f} below floor {GOLD['min_recall']}"
    )
