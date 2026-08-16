"""LLM provider shim — one interface, Anthropic today, Bedrock later.

The agent depends only on the ``LLMProvider`` protocol, so the same LangGraph loop
can run against the Anthropic API now and Amazon Bedrock behind the same interface
in a later phase (PRD Layer 4). Claude is called via the official Anthropic SDK.

Two operations are all Phase 0 needs:
  * ``plan_sql`` — given grounding, draft a read-only SELECT *or* decide to abstain.
    Uses structured output (``messages.parse``) so the decision is a typed object.
  * ``synthesize`` — turn query results into a concise, grounded answer.

Grounding-first honesty guard: a safety ``refusal`` from the model is treated as an
abstention, never a guess.
"""

from __future__ import annotations

import logging
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Per the claude-api reference: default to Opus 4.8 (exact id, no date suffix).
DEFAULT_MODEL = "claude-opus-4-8"

Effort = Literal["low", "medium", "high", "xhigh", "max"]

_PLAN_SYSTEM = (
    "You are Tiresias, a grounded SQL analyst for the Elvis Las Vegas "
    "restaurant-inspection warehouse. You are given the exact schema (tables and "
    "columns) and the governed metric definitions. Draft exactly ONE read-only "
    "DuckDB SELECT that answers the user's question using ONLY the listed tables "
    "and columns, and prefer a governed metric's canonical expression over "
    "inventing arithmetic. Reference tables by their bare name (e.g. "
    "mart_restaurants). If the question cannot be answered from these tables and "
    "columns, or is not about restaurant inspections, do NOT guess — abstain. "
    "Return action='query' with the SQL, or action='abstain' with a brief reason. "
    "SELECT only; never DDL/DML."
)

_SYNTHESIZE_SYSTEM = (
    "You are Tiresias. Answer the user's question using ONLY the query results "
    "provided — never invent numbers that are not in the results. Be concise and "
    "factual. The SQL and its source tables are shown to the user separately, so "
    "do not repeat the SQL. If the results are empty, say so plainly."
)


class PlanDecision(BaseModel):
    """The planner's structured choice: draft SQL, or abstain."""

    action: Literal["query", "abstain"]
    sql: str | None = None
    reason: str


class LLMProvider(Protocol):
    async def plan_sql(
        self,
        question: str,
        grounding: str,
        *,
        prior_sql: str | None = None,
        error: str | None = None,
    ) -> PlanDecision: ...

    async def synthesize(self, question: str, result: dict) -> str: ...


class AnthropicProvider:
    """``LLMProvider`` backed by the Anthropic API (via the official SDK)."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: Effort = "medium") -> None:
        self.model = model
        self.effort = effort
        self._client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env

    async def plan_sql(
        self,
        question: str,
        grounding: str,
        *,
        prior_sql: str | None = None,
        error: str | None = None,
    ) -> PlanDecision:
        repair = ""
        if prior_sql and error:
            repair = (
                f"\n\nYour previous SQL failed validation:\n{prior_sql}\n"
                f"Error: {error}\nFix it, or abstain if it cannot be answered."
            )
        prompt = (
            f"Schema and governed metrics:\n{grounding}\n\n"
            f"Question: {question}{repair}"
        )
        response = await self._client.messages.parse(
            model=self.model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=_PLAN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=PlanDecision,
        )
        if response.stop_reason == "refusal":
            logger.info("Planner refused; abstaining")
            return PlanDecision(
                action="abstain", reason="the request was declined by a safety check"
            )
        parsed = response.parsed_output
        if parsed is None:
            logger.warning("Planner returned no structured output; abstaining")
            return PlanDecision(action="abstain", reason="could not plan a query")
        return parsed

    async def synthesize(self, question: str, result: dict) -> str:
        # Cap rows fed to the model to keep the prompt bounded; the full result set
        # is still what was executed and cited.
        rows = result.get("rows", [])
        shown = rows[:50]
        prompt = (
            f"Question: {question}\n\n"
            f"Columns: {result.get('columns')}\n"
            f"Rows (up to 50 of {result.get('row_count')}): {shown}"
        )
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=1500,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            system=_SYNTHESIZE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return "I can't provide an answer to that."
        return next(
            (block.text for block in response.content if block.type == "text"), ""
        ).strip()
