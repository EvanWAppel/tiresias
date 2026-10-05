"""The honesty benchmark: gold-set scoring, retrieval recall@k, and calibration.

Three harnesses, all driven by a city's own gold files (paths in ``tiresias.yml``):

  * ``run_gold`` runs the real agent over the answer gold set and scores it
    deterministically: answerable questions must produce a non-abstaining answer
    whose SQL ran and cited the expected tables; unanswerable ones must abstain.
  * ``retrieval_recall`` scores the retrieval layer alone (no LLM): for each query,
    one of the expected tables/metrics must be among the top-k grounding targets.
  * ``calibration_report`` lists the dense grounding score of every gold question,
    so a human can pick the retrieval threshold from measured bands.

All scoring is structural; there is no LLM judge.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from tiresias.agent import TiresiasAgent, TiresiasAnswer
from tiresias.config import TiresiasConfig
from tiresias.retrieval import Retriever

logger = logging.getLogger(__name__)


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldCase(_Strict):
    id: str
    question: str
    expect: Literal["answer", "abstain"]
    must_reference: tuple[str, ...] = ()
    sql_must_contain: tuple[str, ...] = ()


class _GoldFile(_Strict):
    version: int
    cases: tuple[GoldCase, ...]


class CaseResult(_Strict):
    id: str
    question: str
    passed: bool
    reason: str = ""


class RetrievalCase(_Strict):
    query: str
    expect_any: tuple[str, ...]


class RetrievalGold(_Strict):
    version: int
    k: int
    min_recall: float
    cases: tuple[RetrievalCase, ...]


class RecallReport(_Strict):
    k: int
    recall: float
    min_recall: float
    misses: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.recall >= self.min_recall


class QuestionScore(_Strict):
    question: str
    expect: Literal["answer", "abstain"]
    score: float


class CalibrationReport(_Strict):
    current_threshold: float
    scores: tuple[QuestionScore, ...]

    def _of(self, expect: str) -> list[float]:
        return [s.score for s in self.scores if s.expect == expect]

    @property
    def min_answerable(self) -> float | None:
        return min(self._of("answer"), default=None)

    @property
    def max_abstain(self) -> float | None:
        return max(self._of("abstain"), default=None)

    def _refused(self, s: QuestionScore) -> bool:
        return s.expect == "answer" and s.score < self.current_threshold

    @property
    def answerable_below_threshold(self) -> tuple[str, ...]:
        return tuple(s.question for s in self.scores if self._refused(s))

    def to_text(self) -> str:
        lines = [f"{'score':>6}  {'expect':<8} question"]
        for s in sorted(self.scores, key=lambda s: s.score):
            flag = "  <- below threshold" if self._refused(s) else ""
            lines.append(f"{s.score:6.3f}  {s.expect:<8} {s.question}{flag}")
        lines += [
            "",
            f"current threshold:     {self.current_threshold:.3f}",
            f"lowest answerable:     {_fmt(self.min_answerable)}",
            f"highest abstain:       {_fmt(self.max_abstain)}",
            "Answerable questions under the threshold are refused before planning.",
            "Abstain questions above it are left to the planner, which is the",
            "authoritative abstain decider; the threshold only screens clear misses.",
        ]
        return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def load_gold(path: Path) -> tuple[GoldCase, ...]:
    """Parse and validate an answer gold set."""
    return _GoldFile.model_validate(yaml.safe_load(Path(path).read_text())).cases


def load_retrieval_gold(path: Path) -> RetrievalGold:
    """Parse and validate a retrieval gold set."""
    return RetrievalGold.model_validate(yaml.safe_load(Path(path).read_text()))


def score_case(case: GoldCase, answer: TiresiasAnswer) -> CaseResult:
    """Score one agent answer against its gold expectation."""

    def result(passed: bool, reason: str = "") -> CaseResult:
        return CaseResult(id=case.id, question=case.question, passed=passed, reason=reason)

    if case.expect == "abstain":
        if answer.abstained:
            return result(True)
        return result(False, f"expected abstention, got answer: {answer.answer!r}")

    if answer.abstained:
        return result(False, "expected an answer, but the agent abstained")
    if not answer.sql:
        return result(False, "answer has no SQL")
    for table in case.must_reference:
        if table not in answer.citations:
            return result(False, f"expected {table} in citations {answer.citations}")
    for fragment in case.sql_must_contain:
        if fragment.lower() not in answer.sql.lower():
            return result(False, f"expected {fragment!r} in SQL {answer.sql!r}")
    return result(True)


async def run_gold(agent: TiresiasAgent, cases: Sequence[GoldCase]) -> list[CaseResult]:
    """Run the agent over every gold case, sequentially, and score each."""
    results = []
    for case in cases:
        answer = await agent.answer(case.question)
        scored = score_case(case, answer)
        logger.info("gold %s: %s %s", case.id, "PASS" if scored.passed else "FAIL", scored.reason)
        results.append(scored)
    return results


def retrieval_recall(retriever: Retriever, gold: RetrievalGold) -> RecallReport:
    """recall@k: the share of queries whose top-k grounding targets hit an expected ref.

    Exact match on each hit's structured ``grounds``, not substring search over
    prose, so an example that merely mentions a table does not count for it.
    """
    misses = []
    for case in gold.cases:
        grounds = {g for hit in retriever.retrieve(case.query, k=gold.k) for g in hit.doc.grounds}
        if not any(expected in grounds for expected in case.expect_any):
            misses.append(case.query)
    total = len(gold.cases)
    recall = (total - len(misses)) / total if total else 0.0
    return RecallReport(k=gold.k, recall=recall, min_recall=gold.min_recall, misses=tuple(misses))


def calibration_report(
    retriever: Retriever, cases: Sequence[GoldCase], config: TiresiasConfig
) -> CalibrationReport:
    """Dense grounding score of every gold question, for picking the threshold."""
    scores = tuple(
        QuestionScore(
            question=case.question,
            expect=case.expect,
            score=retriever.grounding_score(case.question),
        )
        for case in cases
    )
    return CalibrationReport(current_threshold=config.grounding.threshold, scores=scores)
