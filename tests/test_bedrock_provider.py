"""Tests for the Bedrock ``LLMProvider`` (TASKS P3.2).

Hermetic: the Bedrock client is a fake that records each request and returns canned
responses, so no AWS credentials, network or boto3 call is involved. Covers the four
behaviors the shim promises: plan, abstain, refusal (planner and synthesizer) and
synthesize, plus one run through the agent graph.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_agent import FakeRetriever
from tiresias import provider as provider_module
from tiresias.agent import TiresiasAgent
from tiresias.config import TiresiasConfig
from tiresias.provider import BedrockProvider, LLMProvider, PlanDecision

MODEL = "anthropic.claude-opus-4-8"
COUNT_SQL = "select count(*) as n from mart_inspections"


class FakeMessages:
    """Stands in for ``client.messages``: queued responses, recorded kwargs."""

    def __init__(self, parse: list[Any], create: list[Any]) -> None:
        self._parse = list(parse)
        self._create = list(create)
        self.parse_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.parse_calls.append(kwargs)
        return self._parse.pop(0)

    async def create(self, **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        return self._create.pop(0)


class FakeBedrockClient:
    def __init__(self, parse: list[Any] | None = None, create: list[Any] | None = None) -> None:
        self.messages = FakeMessages(parse or [], create or [])


def _parsed(decision: PlanDecision | None, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=decision)


def _text(text: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


def _provider(config: TiresiasConfig, client: FakeBedrockClient) -> BedrockProvider:
    return BedrockProvider(config, model=MODEL, aws_region="us-east-1", client=client)


def test_bedrock_provider_satisfies_the_shim(config: TiresiasConfig) -> None:
    provider: LLMProvider = _provider(config, FakeBedrockClient())
    assert provider.model == MODEL  # type: ignore[attr-defined]


async def test_plan_returns_query_decision(config: TiresiasConfig) -> None:
    decision = PlanDecision(action="query", sql=COUNT_SQL, reason="count")
    client = FakeBedrockClient(parse=[_parsed(decision)])
    result = await _provider(config, client).plan_sql("how many?", "GROUNDING")
    assert result == decision
    call = client.messages.parse_calls[0]
    assert call["model"] == MODEL
    assert call["output_format"] is PlanDecision
    assert "GROUNDING" in call["messages"][0]["content"]
    assert call["system"]  # the city's planner prompt, built from config


async def test_plan_includes_repair_context(config: TiresiasConfig) -> None:
    decision = PlanDecision(action="query", sql=COUNT_SQL, reason="fixed")
    client = FakeBedrockClient(parse=[_parsed(decision)])
    await _provider(config, client).plan_sql(
        "how many?", "G", prior_sql="select bogus", error="no such column"
    )
    prompt = client.messages.parse_calls[0]["messages"][0]["content"]
    assert "select bogus" in prompt and "no such column" in prompt


async def test_plan_abstain_passes_through(config: TiresiasConfig) -> None:
    decision = PlanDecision(action="abstain", reason="not in the warehouse")
    client = FakeBedrockClient(parse=[_parsed(decision)])
    result = await _provider(config, client).plan_sql("weather on mars?", "G")
    assert result.action == "abstain"
    assert result.sql is None


async def test_plan_without_structured_output_abstains(config: TiresiasConfig) -> None:
    client = FakeBedrockClient(parse=[_parsed(None)])
    result = await _provider(config, client).plan_sql("q", "G")
    assert result.action == "abstain"


async def test_plan_refusal_abstains(config: TiresiasConfig) -> None:
    leaked = PlanDecision(action="query", sql=COUNT_SQL, reason="should be ignored")
    client = FakeBedrockClient(parse=[_parsed(leaked, stop_reason="refusal")])
    result = await _provider(config, client).plan_sql("q", "G")
    assert result.action == "abstain"
    assert result.sql is None


async def test_synthesize_returns_text(config: TiresiasConfig) -> None:
    client = FakeBedrockClient(create=[_text("  There are 42.  ")])
    rows = [[i] for i in range(80)]
    answer = await _provider(config, client).synthesize(
        "how many?", {"columns": ["n"], "rows": rows, "row_count": 80}
    )
    assert answer == "There are 42."
    call = client.messages.create_calls[0]
    assert call["model"] == MODEL
    assert "[79]" not in call["messages"][0]["content"]  # rows capped at 50


async def test_synthesize_refusal(config: TiresiasConfig) -> None:
    client = FakeBedrockClient(create=[_text("leaked", stop_reason="refusal")])
    answer = await _provider(config, client).synthesize("q", {"columns": [], "rows": []})
    assert answer == "I can't provide an answer to that."


async def test_agent_runs_through_bedrock_provider(config: TiresiasConfig) -> None:
    decision = PlanDecision(action="query", sql=COUNT_SQL, reason="count")
    client = FakeBedrockClient(parse=[_parsed(decision)], create=[_text("Counted.")])
    agent = TiresiasAgent(config, retriever=FakeRetriever(True), provider=_provider(config, client))
    result = await agent.answer("how many restaurants are there?")
    assert result.abstained is False
    assert result.answer == "Counted."
    assert "mart_inspections" in result.citations


@pytest.mark.parametrize(
    ("model", "region"), [("", "us-east-1"), (MODEL, ""), ("   ", "us-east-1")]
)
def test_model_and_region_are_required(config: TiresiasConfig, model: str, region: str) -> None:
    with pytest.raises(ValueError):
        BedrockProvider(config, model=model, aws_region=region, client=FakeBedrockClient())


def test_missing_extra_gives_install_hint(
    config: TiresiasConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider_module, "_bedrock_extra_installed", lambda: False)
    with pytest.raises(ImportError, match=r"tiresias\[bedrock\]"):
        BedrockProvider(config, model=MODEL, aws_region="us-east-1")


def test_builds_mantle_client_without_network(config: TiresiasConfig) -> None:
    pytest.importorskip("boto3")
    provider = BedrockProvider(config, model=MODEL, aws_region="us-west-2", aws_profile="tiresias")
    client = provider._client
    assert type(client).__name__ == "AsyncAnthropicBedrockMantle"
    assert "us-west-2" in str(client.base_url)
