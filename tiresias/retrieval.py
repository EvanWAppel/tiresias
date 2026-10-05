"""Hybrid retrieval over a city's schema + metric corpus.

The corpus is deliberately small — the allowlisted tables, the governed metrics,
and the city's natural-language examples (from ``tiresias.yml``) — so an in-memory cosine index
is the honest, un-over-engineered choice at this corpus size.
Retrieval returns *schema and metric context*, not prose, so the agent drafts SQL
grounded in real columns and blessed metrics.

The embedder is behind a Protocol: production uses fastembed (ONNX, local), while
tests inject a deterministic fake so the retrieval logic is verified offline.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

import numpy as np
from pydantic import BaseModel
from rank_bm25 import BM25Okapi

from tiresias.catalog import Catalog, load_catalog
from tiresias.config import Example, TiresiasConfig
from tiresias.metrics import MetricRegistry, load_registry

logger = logging.getLogger(__name__)

# Reciprocal Rank Fusion constant. Dampens the contribution of lower ranks; 60 is
# the value from the original RRF paper and a common default.
RRF_K = 60


class Embedder(Protocol):
    """Anything that turns texts into fixed-width vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SupportsRetrieval(Protocol):
    """The retrieval surface the agent depends on (real or faked)."""

    def is_grounded(self, query: str) -> bool: ...

    def retrieve(self, query: str, k: int = ...) -> list[RetrievalHit]: ...


class FastEmbedEmbedder:
    """Default embedder: fastembed's ONNX models (local, no torch, no API key)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self.model_name = model_name
        self._model = None  # lazily constructed — model load is expensive

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            from fastembed import TextEmbedding

            logger.info("Loading fastembed model %s", self.model_name)
            self._model = TextEmbedding(model_name=self.model_name)
        return [vec.tolist() for vec in self._model.embed(list(texts))]


class RetrievedDoc(BaseModel):
    """One retrievable unit of grounding context."""

    model_config = {"frozen": True}

    doc_id: str
    kind: str  # "table" | "metric" | "exemplar"
    ref: str  # the table or metric name this doc grounds to
    text: str
    grounds: tuple[str, ...] = ()  # exact table/metric names this doc points at


class RetrievalHit(BaseModel):
    model_config = {"frozen": True}

    doc: RetrievedDoc
    score: float


def build_corpus(
    catalog: Catalog, registry: MetricRegistry, examples: Sequence[Example]
) -> tuple[RetrievedDoc, ...]:
    """Assemble the grounding corpus from the catalog, registry, and examples."""
    docs: list[RetrievedDoc] = []
    for table in catalog.tables:
        docs.append(
            RetrievedDoc(
                doc_id=f"table:{table.name}",
                kind="table",
                ref=table.name,
                text=table.to_prompt(),
                grounds=(table.name,),
            )
        )
    for metric in registry.metrics:
        docs.append(
            RetrievedDoc(
                doc_id=f"metric:{metric.name}",
                kind="metric",
                ref=metric.name,
                text=(
                    f"Metric {metric.name} ({metric.label}) — {metric.description} "
                    f"Grain: {metric.grain}. Expression: {metric.expression}. "
                    f"Grounded in: {', '.join(metric.references)}."
                ),
                grounds=(metric.name, metric.source_table),
            )
        )
    for i, example in enumerate(examples):
        docs.append(
            RetrievedDoc(
                doc_id=f"exemplar:{i}",
                kind="exemplar",
                ref=example.guidance,
                text=f"Q: {example.question}\nA: {example.guidance}",
                grounds=example.grounds,
            )
        )
    return tuple(docs)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens, splitting on non-letters so `violation_code` -> {violation, code}."""
    return re.findall(r"[a-z]+", text.lower())


class Retriever:
    """Hybrid retriever: dense embeddings + lexical BM25, fused by Reciprocal Rank
    Fusion.

    Dense catches semantic paraphrase ("fail inspection" ~ "non-compliant"); BM25
    catches exact column/table tokens the embedder may under-weight. The abstain
    gate (:meth:`is_grounded`) stays on the *dense* cosine, which is what the
    grounding threshold was calibrated against — hybrid improves the *ranking* of
    the context handed to the planner without changing the abstain decision.
    """

    def __init__(
        self, embedder: Embedder, corpus: Sequence[RetrievedDoc], threshold: float
    ) -> None:
        if not corpus:
            raise ValueError("retrieval corpus is empty")
        self.embedder = embedder
        self.corpus: tuple[RetrievedDoc, ...] = tuple(corpus)
        self.threshold = threshold
        vectors = np.asarray(self.embedder.embed([d.text for d in self.corpus]), dtype=float)
        self._matrix = _normalize(vectors)
        self._bm25 = BM25Okapi([_tokenize(d.text) for d in self.corpus])

    def _dense_scores(self, query: str) -> np.ndarray:
        query_vec = _normalize(np.asarray(self.embedder.embed([query]), dtype=float))
        return (self._matrix @ query_vec.T).ravel()

    def grounding_score(self, query: str) -> float:
        """Top-1 *dense* cosine — the signal the abstain threshold is calibrated on."""
        scores = self._dense_scores(query)
        return float(scores.max()) if scores.size else float("nan")

    def retrieve(self, query: str, k: int = 4) -> list[RetrievalHit]:
        """Return the top-k grounding docs, fusing dense + BM25 rankings via RRF.

        The returned score is the RRF fusion score (rank-based), not a cosine — use
        :meth:`grounding_score` for the calibrated dense signal.
        """
        dense_order = np.argsort(self._dense_scores(query))[::-1]
        lexical_order = np.argsort(self._bm25.get_scores(_tokenize(query)))[::-1]

        fused: dict[int, float] = defaultdict(float)
        for ranking in (dense_order, lexical_order):
            for rank, idx in enumerate(ranking):
                fused[int(idx)] += 1.0 / (RRF_K + rank)

        order = sorted(fused, key=lambda i: fused[i], reverse=True)[:k]
        hits = [RetrievalHit(doc=self.corpus[i], score=fused[i]) for i in order]
        logger.debug("Retrieved %d docs for %r (hybrid RRF)", len(hits), query)
        return hits

    def is_grounded(self, query: str) -> bool:
        """Whether the query is in-domain enough to attempt an answer (dense gate)."""
        return self.grounding_score(query) >= self.threshold

    @classmethod
    def from_config(cls, config: TiresiasConfig, embedder: Embedder | None = None) -> Retriever:
        """Build the retriever for one city: its catalog, metrics, and examples."""
        corpus = build_corpus(
            load_catalog(config), load_registry(config.metrics_path), config.examples
        )
        return cls(embedder or FastEmbedEmbedder(), corpus, config.grounding.threshold)
