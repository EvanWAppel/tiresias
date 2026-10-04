"""Hybrid retrieval over the Elvis schema + metric corpus.

The corpus is deliberately small — the allowlisted marts, the governed metrics,
and a set of natural-language exemplars per domain — so an in-memory cosine index
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
# subtle out-of-domain questions overlap (e.g. "weather forecast for Las Vegas" or
# "median home price in Las Vegas" score like real questions because they name
# the city and a nearby domain, but nothing in the warehouse answers them), so
# borderline cases are passed through to the planner — which sees the full schema
# and is the authoritative abstain decider. Recalibrated for the all-domains corpus
# (default fastembed BAAI/bge-small-en-v1.5): generic off-topic questions measured
# 0.43-0.555, answerable questions across every domain 0.598-0.83; 0.56 sits at
# the top of the off-topic band, keeping ~0.04 margin below the lowest answerable.
GROUNDING_THRESHOLD = 0.56

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
    (
        "How many restaurants have been closed by the health district?",
        "Use mart_restaurants (closures, failed_inspections). Road closures are a different domain (mart_road_construction).",
    ),
    (
        "How many police calls were there per month?",
        "Use mart_crime_monthly (incident_month, incident_count). These are LVMPD calls for service, not confirmed crimes.",
    ),
    (
        "What are the most common types of police calls?",
        "Use mart_crime_by_type, ranked by incident_count.",
    ),
    (
        "What hour of the day has the most police calls?",
        "Use mart_crime_by_hour_weekday, summing incident_count by hour_of_day.",
    ),
    (
        "How many building permits were issued and what were they worth?",
        "Use mart_permits_monthly or mart_permits_by_type (permit_count, total_valuation) for Las Vegas; mart_henderson_permits for Henderson.",
    ),
    (
        "How many visitors came to Las Vegas each month?",
        "Use mart_lvcva_indicators where metric ILIKE 'Visitor Volume'.",
    ),
    (
        "How has gaming revenue changed over time?",
        "Use mart_lvcva_indicators where metric ILIKE 'Gaming Revenue%'.",
    ),
    (
        "How many 110 degree days were there each year?",
        "Use mart_weather_extreme_days (days_110f_plus by observed_year).",
    ),
    (
        "What was the hottest month on record?",
        "Use mart_weather_monthly ordered by record_high_f or avg_high_f.",
    ),
    (
        "How bad is the air quality in Las Vegas?",
        "Use mart_air_quality_monthly or mart_air_quality_daily (AQI by parameter).",
    ),
    (
        "How low has Lake Mead's water level dropped?",
        "Use mart_lake_mead_monthly (min_elevation_ft, avg_elevation_ft by reading_month).",
    ),
    (
        "Which day of the year has the most weddings?",
        "Use mart_marriage_daily, summing license_count by month_of_year and day_of_month.",
    ),
    (
        "Where do couples who marry in Las Vegas come from?",
        "Use mart_marriage_by_origin ranked by license_count.",
    ),
    (
        "How many same-sex marriages are there each year?",
        "Use mart_marriage_by_gender_year where couple_type = 'Same-sex'.",
    ),
    (
        "How many short-term rentals (Airbnbs) are there in each city?",
        "Use mart_short_term_rentals grouped by jurisdiction.",
    ),
    (
        "Which roads have active construction or closures?",
        "Use mart_road_construction (road_name, status, start_date, end_date, is_full_closure).",
    ),
    (
        "Which parks are largest or have water features?",
        "Use mart_parks (acres, has_water, jurisdiction).",
    ),
    (
        "Which artists have the most public art pieces?",
        "Use mart_public_art_metro (Las Vegas + Henderson) grouped by artist.",
    ),
    (
        "Which apartment complexes have the most fire code violations?",
        "Use mart_fire_prevention_inspections ranked by total_violations.",
    ),
    (
        "Which census tracts have the most police calls per resident?",
        "Use mart_tract_metrics where topic = 'calls', ranked by rate_per_1000 (null unless coverage = 'available').",
    ),
    (
        "What kinds of business licenses does Henderson issue?",
        "Use mart_henderson_licenses_by_type (license_count, active_count).",
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
