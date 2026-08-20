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
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

import numpy as np
from pydantic import BaseModel
from rank_bm25 import BM25Okapi

from tiresias.catalog import Catalog, load_catalog
from tiresias.metrics import MetricRegistry, load_registry

logger = logging.getLogger(__name__)

# Reciprocal Rank Fusion constant. Dampens the contribution of lower ranks; 60 is
# the value from the original RRF paper and a common default.
RRF_K = 60

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
        self,
        embedder: Embedder,
        corpus: Sequence[RetrievedDoc] | None = None,
    ) -> None:
        self.embedder = embedder
        self.corpus: tuple[RetrievedDoc, ...] = tuple(corpus) if corpus else build_corpus()
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

    def is_grounded(self, query: str, threshold: float = GROUNDING_THRESHOLD) -> bool:
        """Whether the query is in-domain enough to attempt an answer (dense gate)."""
        return self.grounding_score(query) >= threshold
