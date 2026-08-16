"""The Tiresias agent — a LangGraph plan → execute → abstain loop.

The graph wires the layers together:

    retrieve → (grounded?) → plan → (query?) → execute → (ok?) → synthesize
                    │                  │                   │
                    └──────────────────┴───────────────────┴──▶ abstain

Abstention is a first-class terminal node reachable whenever the agent cannot
ground itself: retrieval finds nothing in-domain, the planner declines, or a
drafted query fails catalog validation and one repair attempt still fails. The
agent never emits an answer it cannot trace to real rows.

All SQL executes through the MCP ``run_validated_sql`` tool (see
``tiresias.mcp_client``); the schema/metric grounding is read from the MCP catalog
and metric resources. Retrieval provides the grounded/ungrounded gate.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from tiresias.config import DEFAULT_SETTINGS, TiresiasSettings
from tiresias.mcp_client import WarehouseSession, warehouse_session
from tiresias.provider import AnthropicProvider, LLMProvider
from tiresias.retrieval import FastEmbedEmbedder, Retriever, SupportsRetrieval

logger = logging.getLogger(__name__)

_ABSTAIN_MESSAGE = (
    "I can't answer that from the restaurant-inspection warehouse, so I'm not going "
    "to guess. Try a question about Las Vegas restaurant inspections — for example, "
    "failure rates, common violations, or inspection counts over time."
)


class TiresiasAnswer(BaseModel):
    """The agent's final, cited output."""

    model_config = {"frozen": True}

    question: str
    answer: str
    sql: str | None
    citations: tuple[str, ...]
    abstained: bool
    trace: tuple[str, ...]


class _State(TypedDict, total=False):
    question: str
    grounding: str
    grounded: bool
    sql: str | None
    result: dict | None
    error: str | None
    attempts: int
    answer: str
    citations: tuple[str, ...]
    abstained: bool
    abstain_reason: str
    trace: list[str]


class TiresiasAgent:
    """Grounded civic-intelligence agent over the restaurant-inspection domain."""

    def __init__(
        self,
        retriever: SupportsRetrieval | None = None,
        provider: LLMProvider | None = None,
        settings: TiresiasSettings = DEFAULT_SETTINGS,
        max_repairs: int = 1,
    ) -> None:
        # Constructing the default retriever loads the embedding model + corpus once.
        self.retriever = retriever or Retriever(FastEmbedEmbedder())
        self.provider = provider or AnthropicProvider()
        self.settings = settings
        self.max_repairs = max_repairs

    async def answer(self, question: str) -> TiresiasAnswer:
        """Run the graph for one question and return a cited answer or abstention."""
        async with warehouse_session() as session:
            graph = self._build_graph(session)
            final: _State = await graph.ainvoke(
                {"question": question, "attempts": 0, "trace": []}
            )
        return TiresiasAnswer(
            question=question,
            answer=final.get("answer", _ABSTAIN_MESSAGE),
            sql=final.get("sql") if not final.get("abstained") else None,
            citations=tuple(final.get("citations", ())),
            abstained=bool(final.get("abstained", False)),
            trace=tuple(final.get("trace", [])),
        )

    def _build_graph(self, session: WarehouseSession):
        """Compile the state machine, closing over the live MCP session."""

        async def retrieve(state: _State) -> _State:
            question = state["question"]
            grounded = self.retriever.is_grounded(question)
            hits = self.retriever.retrieve(question, k=3)
            # Authoritative schema + metrics come from the MCP resources; retrieval
            # supplies the grounded gate and a few relevant exemplars.
            catalog = await session.read_catalog()
            metrics = await session.read_metrics()
            exemplars = "\n\n".join(
                h.doc.text for h in hits if h.doc.kind == "exemplar"
            )
            grounding = f"{catalog}\n\n{metrics}\n\nRelevant examples:\n{exemplars}"
            trace = state["trace"] + [
                f"retrieve: grounded={grounded} (top score {hits[0].score:.2f})"
            ]
            return {"grounded": grounded, "grounding": grounding, "trace": trace}

        async def plan(state: _State) -> _State:
            decision = await self.provider.plan_sql(
                state["question"],
                state["grounding"],
                prior_sql=state.get("sql"),
                error=state.get("error"),
            )
            trace = state["trace"] + [f"plan: action={decision.action}"]
            if decision.action == "abstain":
                return {"abstain_reason": decision.reason, "trace": trace}
            return {"sql": decision.sql, "trace": trace}

        async def execute(state: _State) -> _State:
            payload = await session.run_sql(state["sql"] or "")
            if payload.get("ok"):
                trace = state["trace"] + [
                    f"execute: ok, {payload.get('row_count')} rows"
                ]
                return {"result": payload, "error": None, "trace": trace}
            error = payload.get("error", "unknown error")
            trace = state["trace"] + [f"execute: rejected — {error}"]
            return {
                "error": error,
                "attempts": state.get("attempts", 0) + 1,
                "trace": trace,
            }

        async def synthesize(state: _State) -> _State:
            result = state["result"] or {}
            answer = await self.provider.synthesize(state["question"], result)
            citations = tuple(result.get("tables", ())) + (result.get("sql", ""),)
            trace = state["trace"] + ["synthesize: answer produced"]
            return {
                "answer": answer,
                "sql": result.get("sql"),
                "citations": tuple(c for c in citations if c),
                "abstained": False,
                "trace": trace,
            }

        def abstain(state: _State) -> _State:
            reason = state.get("abstain_reason") or state.get("error") or "ungrounded"
            trace = state["trace"] + [f"abstain: {reason}"]
            return {
                "answer": _ABSTAIN_MESSAGE,
                "abstained": True,
                "citations": (),
                "trace": trace,
            }

        def after_retrieve(state: _State) -> str:
            return "plan" if state.get("grounded") else "abstain"

        def after_plan(state: _State) -> str:
            return "execute" if state.get("sql") else "abstain"

        def after_execute(state: _State) -> str:
            if state.get("result"):
                return "synthesize"
            if state.get("attempts", 0) <= self.max_repairs:
                return "plan"  # repair
            return "abstain"

        # langgraph's StateGraph generic bound doesn't accept a plain TypedDict class
        # in ty's view; the runtime contract is a state schema, which _State satisfies.
        builder: StateGraph = StateGraph(_State)  # ty: ignore[invalid-argument-type]
        builder.add_node("retrieve", retrieve)
        builder.add_node("plan", plan)
        builder.add_node("execute", execute)
        builder.add_node("synthesize", synthesize)
        builder.add_node("abstain", abstain)

        builder.add_edge(START, "retrieve")
        builder.add_conditional_edges("retrieve", after_retrieve, ["plan", "abstain"])
        builder.add_conditional_edges("plan", after_plan, ["execute", "abstain"])
        builder.add_conditional_edges(
            "execute", after_execute, ["synthesize", "plan", "abstain"]
        )
        builder.add_edge("synthesize", END)
        builder.add_edge("abstain", END)
        return builder.compile()
