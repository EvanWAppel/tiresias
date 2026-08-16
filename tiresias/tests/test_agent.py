"""Tests for the LangGraph agent's routing: answer, abstain, and repair.

The retriever and LLM provider are faked so the graph's control flow is tested
deterministically; SQL still executes for real through the in-memory MCP server,
so the guard/execute/abstain paths are exercised end-to-end.
"""

from __future__ import annotations

from tiresias.agent import TiresiasAgent
from tiresias.provider import PlanDecision
from tiresias.retrieval import RetrievalHit, RetrievedDoc


class FakeRetriever:
    """Deterministic retriever: grounded gate is a fixed boolean."""

    def __init__(self, grounded: bool) -> None:
        self._grounded = grounded

    def is_grounded(self, query: str, threshold: float = 0.0) -> bool:
        return self._grounded

    def retrieve(self, query: str, k: int = 3) -> list[RetrievalHit]:
        doc = RetrievedDoc(
            doc_id="exemplar:0",
            kind="exemplar",
            ref="Use mart_restaurants.",
            text="Q: failure rate? A: use mart_restaurants.failure_rate_pct",
        )
        return [RetrievalHit(doc=doc, score=0.9)]


class FakeProvider:
    """Returns a queued sequence of PlanDecisions; records calls."""

    def __init__(self, decisions: list[PlanDecision], answer: str = "A grounded answer.") -> None:
        self._decisions = decisions
        self._answer = answer
        self.plan_calls = 0
        self.synthesize_calls = 0

    async def plan_sql(self, question, grounding, *, prior_sql=None, error=None) -> PlanDecision:
        decision = self._decisions[min(self.plan_calls, len(self._decisions) - 1)]
        self.plan_calls += 1
        return decision

    async def synthesize(self, question, result) -> str:
        self.synthesize_calls += 1
        return self._answer


def _agent(grounded: bool, decisions: list[PlanDecision], **kwargs) -> tuple[TiresiasAgent, FakeProvider]:
    provider = FakeProvider(decisions)
    agent = TiresiasAgent(
        retriever=FakeRetriever(grounded), provider=provider, **kwargs
    )
    return agent, provider


async def test_grounded_question_produces_cited_answer(_require_warehouse: None) -> None:
    agent, provider = _agent(
        grounded=True,
        decisions=[PlanDecision(action="query", sql="select count(*) as n from mart_restaurants", reason="count")],
    )
    result = await agent.answer("how many restaurants are there?")
    assert result.abstained is False
    assert result.answer == "A grounded answer."
    assert "mart_restaurants" in result.citations
    assert result.sql is not None and "LIMIT" in result.sql.upper()
    assert provider.synthesize_calls == 1


async def test_out_of_domain_abstains_without_calling_planner(_require_warehouse: None) -> None:
    agent, provider = _agent(grounded=False, decisions=[])
    result = await agent.answer("what will bitcoin cost tomorrow?")
    assert result.abstained is True
    assert result.sql is None
    assert result.citations == ()
    assert provider.plan_calls == 0  # abstained before ever planning


async def test_planner_choice_to_abstain_is_honored(_require_warehouse: None) -> None:
    agent, _ = _agent(
        grounded=True,
        decisions=[PlanDecision(action="abstain", reason="no such column")],
    )
    result = await agent.answer("what is the average tip amount per waiter?")
    assert result.abstained is True
    assert result.sql is None


async def test_repair_after_validation_failure_then_succeeds(_require_warehouse: None) -> None:
    agent, provider = _agent(
        grounded=True,
        decisions=[
            # First draft references a hallucinated column → EXPLAIN rejects it.
            PlanDecision(action="query", sql="select bogus_col from mart_restaurants", reason="try"),
            # Repair draft is valid.
            PlanDecision(action="query", sql="select count(*) as n from mart_restaurants", reason="fixed"),
        ],
    )
    result = await agent.answer("how many restaurants?")
    assert result.abstained is False
    assert provider.plan_calls == 2  # planned, then repaired
    assert any("rejected" in step for step in result.trace)


async def test_repair_exhausted_abstains(_require_warehouse: None) -> None:
    agent, provider = _agent(
        grounded=True,
        decisions=[PlanDecision(action="query", sql="select bogus_col from mart_restaurants", reason="bad")],
        max_repairs=1,
    )
    result = await agent.answer("how many restaurants?")
    assert result.abstained is True
    # Initial attempt + one repair, both rejected.
    assert provider.plan_calls == 2
