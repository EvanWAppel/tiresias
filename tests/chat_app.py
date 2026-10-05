"""Streamlit script for the chat tests: the real page over a fake agent."""

import os
from pathlib import Path

from tiresias.agent import TiresiasAnswer
from tiresias.chat import render_chat
from tiresias.config import load_config


class FakeAgent:
    async def answer(self, question: str) -> TiresiasAnswer:
        if "bitcoin" in question:
            return TiresiasAnswer(
                question=question,
                answer="I can't answer that.",
                sql=None,
                citations=(),
                abstained=True,
                trace=("abstain: ungrounded",),
            )
        return TiresiasAnswer(
            question=question,
            answer="There are 50 restaurants.",
            sql="SELECT count(*) FROM mart_inspections LIMIT 1000",
            citations=("mart_inspections",),
            abstained=False,
            trace=("plan: action=query",),
        )


render_chat(load_config(Path(os.environ["TIRESIAS_TEST_CONFIG"])), agent_factory=FakeAgent)
