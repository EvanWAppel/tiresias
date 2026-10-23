"""LLM provider shim — one interface, Anthropic today, Bedrock later.

The agent depends only on the ``LLMProvider`` protocol, so the same LangGraph loop
can run against the Anthropic API now and Amazon Bedrock behind the same interface
in a later phase (PRD Layer 4). Claude is called via the official Anthropic SDK.

The agent needs two operations:
  * ``plan_sql`` — given grounding, draft a read-only SELECT *or* decide to abstain.
    Uses structured output (``messages.parse``) so the decision is a typed object.
  * ``synthesize`` — turn query results into a concise, grounded answer.

Grounding-first honesty guard: a safety ``refusal`` from the model is treated as an
abstention, never a guess.

``BedrockProvider`` runs the same requests through Amazon Bedrock (the SDK's Mantle
client, i.e. the Messages API on Bedrock). It needs the optional extra
``tiresias[bedrock]`` (boto3, for SigV4 signing) and takes its model id and region
explicitly: there is no default config.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any, Literal, Protocol

import anthropic
from pydantic import BaseModel

from tiresias.config import TiresiasConfig
from tiresias.prompts import SYNTHESIZE_SYSTEM, plan_system_prompt

logger = logging.getLogger(__name__)

# Per the claude-api reference: default to Opus 4.8 (exact id, no date suffix).
DEFAULT_MODEL = "claude-opus-4-8"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


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

    def __init__(
        self,
        config: TiresiasConfig,
        model: str = DEFAULT_MODEL,
        effort: Effort = "medium",
        *,
        client: Any | None = None,
    ) -> None:
        self.plan_system = plan_system_prompt(config)
        self.model = model
        self.effort = effort
        # Any client exposing the Messages API (``messages.parse`` / ``messages.create``).
        # The default reads ANTHROPIC_API_KEY from env.
        self._client: Any = client if client is not None else anthropic.AsyncAnthropic()

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
        prompt = f"Schema and governed metrics:\n{grounding}\n\nQuestion: {question}{repair}"
        response = await self._client.messages.parse(
            model=self.model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=self.plan_system,
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
            system=SYNTHESIZE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return "I can't provide an answer to that."
        return next((block.text for block in response.content if block.type == "text"), "").strip()


def _bedrock_extra_installed() -> bool:
    """True when boto3 (``tiresias[bedrock]``) is importable for SigV4 signing."""
    return importlib.util.find_spec("boto3") is not None


class BedrockProvider(AnthropicProvider):
    """``LLMProvider`` backed by Claude on Amazon Bedrock.

    Same requests, refusal handling and abstain-first behavior as ``AnthropicProvider``;
    only the client differs. ``model`` is a Bedrock model id (e.g. an ``anthropic.``-
    prefixed id) and ``aws_region`` is required. AWS credentials come from the standard
    boto3 chain (env, ``aws_profile``, instance/task role); Tiresias never takes keys
    as arguments. Pass ``client`` to inject a fake in tests.
    """

    def __init__(
        self,
        config: TiresiasConfig,
        *,
        model: str,
        aws_region: str,
        aws_profile: str | None = None,
        effort: Effort = "medium",
        client: Any | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("BedrockProvider needs an explicit Bedrock model id")
        if not aws_region.strip():
            raise ValueError("BedrockProvider needs an explicit aws_region")
        if client is None:
            if not _bedrock_extra_installed():
                raise ImportError(
                    "BedrockProvider needs the optional extra: pip install 'tiresias[bedrock]'"
                )
            client = anthropic.AsyncAnthropicBedrockMantle(
                aws_region=aws_region, aws_profile=aws_profile
            )
        super().__init__(config, model=model, effort=effort, client=client)
        self.aws_region = aws_region
