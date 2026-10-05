"""The eval harness: gold-set scoring, retrieval recall@k, and calibration."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FakeEmbedder
from tests.test_agent import COUNT, FakeProvider, FakeRetriever
from tiresias.agent import TiresiasAgent, TiresiasAnswer
from tiresias.config import TiresiasConfig
from tiresias.evals import (
    GoldCase,
    calibration_report,
    load_gold,
    load_retrieval_gold,
    retrieval_recall,
    run_gold,
    score_case,
)
from tiresias.retrieval import Retriever

BASE_ANSWER = TiresiasAnswer(
    question="q",
    answer="a",
    sql="SELECT failure_rate_pct FROM mart_inspections LIMIT 1000",
    citations=("mart_inspections",),
    abstained=False,
    trace=(),
)


def _answer(**overrides: object) -> TiresiasAnswer:
    return BASE_ANSWER.model_copy(update=overrides)


ANSWER_CASE = GoldCase(
    id="c",
    question="q",
    expect="answer",
    must_reference=("mart_inspections",),
    sql_must_contain=("FAILURE_RATE_PCT",),
)
ABSTAIN_CASE = GoldCase(id="o", question="q", expect="abstain")


def test_load_gold_reads_the_city_set(config: TiresiasConfig) -> None:
    assert config.gold.answers is not None
    cases = load_gold(config.gold.answers)
    assert [c.id for c in cases] == ["count_restaurants", "worst_failure_rate", "off_topic"]
    assert cases[2].expect == "abstain"


def test_load_gold_rejects_unknown_expectation(tmp_path: Path) -> None:
    path = tmp_path / "gold.yaml"
    path.write_text("version: 1\ncases:\n  - {id: x, question: q, expect: maybe}\n")
    with pytest.raises(ValueError, match="expect"):
        load_gold(path)


def test_answer_case_passes_with_citation_and_sql_fragment() -> None:
    assert score_case(ANSWER_CASE, _answer()).passed is True


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (_answer(abstained=True, sql=None, citations=()), "abstained"),
        (_answer(sql=None), "no SQL"),
        (_answer(citations=("mart_other",)), "mart_inspections"),
        (_answer(sql="SELECT 1 FROM mart_inspections"), "FAILURE_RATE_PCT"),
    ],
)
def test_answer_case_failures_say_why(answer: TiresiasAnswer, reason: str) -> None:
    result = score_case(ANSWER_CASE, answer)
    assert result.passed is False
    assert reason in result.reason


def test_abstain_case() -> None:
    assert score_case(ABSTAIN_CASE, _answer(abstained=True, sql=None)).passed is True
    failed = score_case(ABSTAIN_CASE, _answer())
    assert failed.passed is False and "expected abstention" in failed.reason


async def test_run_gold_scores_every_case(config: TiresiasConfig) -> None:
    agent = TiresiasAgent(config, retriever=FakeRetriever(True), provider=FakeProvider([COUNT]))
    results = await run_gold(agent, [ANSWER_CASE.model_copy(update={"sql_must_contain": ()})])
    assert [r.passed for r in results] == [True]


def test_retrieval_recall_on_the_city_gold(
    config: TiresiasConfig, fake_embedder: FakeEmbedder
) -> None:
    assert config.gold.retrieval is not None
    gold = load_retrieval_gold(config.gold.retrieval)
    report = retrieval_recall(Retriever.from_config(config, embedder=fake_embedder), gold)
    assert report.k == gold.k
    assert report.recall == pytest.approx(1.0)
    assert report.passed is True
    assert report.misses == ()


def test_retrieval_recall_reports_misses(
    config: TiresiasConfig, fake_embedder: FakeEmbedder
) -> None:
    assert config.gold.retrieval is not None
    gold = load_retrieval_gold(config.gold.retrieval)
    impossible = gold.model_copy(
        update={"cases": (gold.cases[0].model_copy(update={"expect_any": ("nope",)}),)}
    )
    report = retrieval_recall(Retriever.from_config(config, embedder=fake_embedder), impossible)
    assert report.passed is False
    assert report.misses == (gold.cases[0].query,)


def test_calibration_report_separates_answerable_from_abstain(
    config: TiresiasConfig, fake_embedder: FakeEmbedder
) -> None:
    assert config.gold.answers is not None
    retriever = Retriever.from_config(config, embedder=fake_embedder)
    report = calibration_report(retriever, load_gold(config.gold.answers), config)
    assert {s.expect for s in report.scores} == {"answer", "abstain"}
    assert report.current_threshold == config.grounding.threshold
    assert report.min_answerable == min(s.score for s in report.scores if s.expect == "answer")
    # Answerable questions that score under the threshold would be wrongly refused.
    assert report.answerable_below_threshold == tuple(
        s.question
        for s in report.scores
        if s.expect == "answer" and s.score < config.grounding.threshold
    )
    assert "threshold" in report.to_text()


async def test_run_gold_records_a_crashing_case_and_keeps_going(config: TiresiasConfig) -> None:
    class Flaky:
        calls = 0

        async def answer(self, question: str) -> TiresiasAnswer:
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RuntimeError("API overloaded")
            return BASE_ANSWER.model_copy(update={"abstained": True, "sql": None})

    results = await run_gold(Flaky(), [ANSWER_CASE, ABSTAIN_CASE])
    assert [r.passed for r in results] == [False, True]
    assert "RuntimeError: API overloaded" in results[0].reason


@pytest.mark.parametrize(
    "body",
    [
        "version: 1\nk: 0\nmin_recall: 0.5\ncases: [{query: q, expect_any: [t]}]\n",
        "version: 1\nk: 3\nmin_recall: 1.5\ncases: [{query: q, expect_any: [t]}]\n",
        "version: 1\nk: 3\nmin_recall: 0.5\ncases: []\n",
    ],
)
def test_retrieval_gold_is_range_checked(tmp_path: Path, body: str) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(body)
    with pytest.raises(ValueError):
        load_retrieval_gold(path)


def test_gold_ids_must_be_unique(tmp_path: Path) -> None:
    path = tmp_path / "gold.yaml"
    path.write_text(
        "version: 1\ncases:\n"
        "  - {id: x, question: a, expect: abstain}\n"
        "  - {id: x, question: b, expect: abstain}\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_gold(path)
