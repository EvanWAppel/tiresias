"""Phase-0 eval harness — the honesty benchmark, run under pytest.

Executes the *real* agent (real retrieval + Anthropic provider + MCP execution)
against the versioned gold set and scores two things deterministically:

  * grounded accuracy — answerable questions produce a non-abstaining, cited answer
    whose SQL ran and referenced the expected table; and
  * correct refusal — unanswerable questions abstain.

These are live tests (they call the Anthropic API), so the whole module skips when
``ANTHROPIC_API_KEY`` or the warehouse is absent — keeping CI hermetic while giving
a one-command local acceptance run:  ``uv run pytest tiresias/evals -m eval``.

An LLM-judge layer is deferred to Phase 4; Phase 0 uses deterministic/structural
checks only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from tiresias.agent import TiresiasAgent
from tiresias.config import DEFAULT_SETTINGS

pytestmark = [pytest.mark.eval, pytest.mark.slow]

GOLD_PATH = Path(__file__).with_name("gold.yaml")
_CASES = yaml.safe_load(GOLD_PATH.read_text())["cases"]


def _require_live() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; skipping live eval")
    if not DEFAULT_SETTINGS.db_path.exists():
        pytest.skip("warehouse absent; build it to run the eval")


@pytest.fixture(scope="module")
def agent() -> TiresiasAgent:
    _require_live()
    return TiresiasAgent()


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
async def test_gold_case(agent: TiresiasAgent, case: dict) -> None:
    result = await agent.answer(case["question"])

    if case["expect"] == "abstain":
        assert result.abstained is True, (
            f"{case['id']}: expected abstention, got answer: {result.answer!r}"
        )
        return

    # expect == "answer"
    assert result.abstained is False, (
        f"{case['id']}: expected an answer, but the agent abstained"
    )
    assert result.sql, f"{case['id']}: answer has no SQL"
    for table in case.get("must_reference", []):
        assert table in result.citations, (
            f"{case['id']}: expected {table} in citations {result.citations}"
        )
