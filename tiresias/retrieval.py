"""Minimal dense retrieval over the Phase-0 schema + metric corpus.

The corpus is deliberately small — the four restaurant marts, the one governed
metric, and a handful of natural-language exemplars — so an in-memory cosine index
is the honest, un-over-engineered choice (see TIRESIAS-PRD "Open decisions" #1).
Retrieval returns *schema and metric context*, not prose, so the agent drafts SQL
grounded in real columns and blessed metrics.

The embedder is behind a Protocol: production uses fastembed (ONNX, local), while
tests inject a deterministic fake so the retrieval logic is verified offline.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

import numpy as np
from pydantic import BaseModel

from tiresias.catalog import Catalog, load_catalog
from tiresias.metrics import MetricRegistry, load_registry

logger = logging.getLogger(__name__)

# Below this top-1 cosine score, retrieval hard-abstains (clearly out-of-domain).
# This is a LENIENT pre-filter, not the final grounding decision: in-domain and
# subtle out-of-domain questions overlap (e.g. "average tip per waiter" scores like
# a real restaurant question because it mentions restaurants, but no such column
# exists), so borderline cases are passed through to the planner — which sees the
# full schema and is the authoritative abstain decider. Calibrated on the Phase-0
# gold set (default fastembed BAAI/bge-small-en-v1.5): clearly-OOD questions
# measured 0.45-0.54, answerable ones 0.59-0.80; 0.55 sits in that gap.
GROUNDING_THRESHOLD = 0.55

# NL question -> the tables/metric that answer it. These teach retrieval the mapping
# from how people ask to what actually holds the answer.
EXEMPLARS: tuple[tuple[str, str], ...] = (
    (
        "Which restaurants fail health inspections most often?",
        "Use mart_restaurants with the restaurant_failure_rate metric (failure_rate_pct).",
    ),
    (
        "What are the most common health code violations?",
        "Use mart_top_violations, ranked by occurrence_count.",
    ),
    (
        "How have restaurant inspection counts changed over time?",
        "Use mart_inspections_over_time, grouped by inspection_month.",
    ),
    (
        "What specific violations did a restaurant receive?",
        "Use mart_inspection_violations joined to mart_restaurants on permit_number.",
    ),
    (
        "What is the inspection failure rate for a restaurant?",
        "Use the restaurant_failure_rate metric on mart_restaurants.failure_rate_pct.",
    ),
)


class Embedder(Protocol):
    """Anything that turns texts into fixed-width vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SupportsRetrieval(Protocol):
    """The retrieval surface the agent depends on (real or faked)."""

    def is_grounded(self, query: str, threshold: float = ...) -> bool: ...

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


class RetrievalHit(BaseModel):
    model_config = {"frozen": True}

    doc: RetrievedDoc
    score: float


def build_corpus(
    catalog: Catalog | None = None,
    registry: MetricRegistry | None = None,
) -> tuple[RetrievedDoc, ...]:
    """Assemble the grounding corpus from the catalog, registry, and exemplars."""
    catalog = catalog or load_catalog()
    registry = registry or load_registry()

    docs: list[RetrievedDoc] = []
    for table in catalog.tables:
        docs.append(
            RetrievedDoc(
                doc_id=f"table:{table.name}",
                kind="table",
                ref=table.name,
                text=table.to_prompt(),
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
            )
        )
    for i, (question, answer) in enumerate(EXEMPLARS):
        docs.append(
            RetrievedDoc(
                doc_id=f"exemplar:{i}",
                kind="exemplar",
                ref=answer,
                text=f"Q: {question}\nA: {answer}",
            )
        )
    return tuple(docs)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


class Retriever:
    """In-memory dense retriever: embed the corpus once, cosine top-k per query."""

    def __init__(
        self,
        embedder: Embedder,
        corpus: Sequence[RetrievedDoc] | None = None,
    ) -> None:
        self.embedder = embedder
        self.corpus: tuple[RetrievedDoc, ...] = tuple(corpus) if corpus else build_corpus()
        vectors = np.asarray(self.embedder.embed([d.text for d in self.corpus]), dtype=float)
        self._matrix = _normalize(vectors)

    def retrieve(self, query: str, k: int = 4) -> list[RetrievalHit]:
        """Return the top-k grounding docs for ``query``, most similar first."""
        query_vec = _normalize(np.asarray(self.embedder.embed([query]), dtype=float))
        scores = (self._matrix @ query_vec.T).ravel()
        order = np.argsort(scores)[::-1][:k]
        hits = [
            RetrievalHit(doc=self.corpus[i], score=float(scores[i])) for i in order
        ]
        logger.debug(
            "Retrieved %d docs for %r; top score %.3f",
            len(hits), query, hits[0].score if hits else float("nan"),
        )
        return hits

    def is_grounded(self, query: str, threshold: float = GROUNDING_THRESHOLD) -> bool:
        """Whether any corpus doc is similar enough to treat the query as in-domain."""
        hits = self.retrieve(query, k=1)
        return bool(hits) and hits[0].score >= threshold
