"""Two configs for the same city in one process: each must get its own agent."""

import os
from pathlib import Path

import streamlit as st

from tiresias.agent import TiresiasAnswer
from tiresias.chat import render_chat
from tiresias.config import load_config


def factory(label: str):
    class Labelled:
        async def answer(self, question: str) -> TiresiasAnswer:
            return TiresiasAnswer(
                question=question,
                answer=f"agent {label}",
                sql=None,
                citations=(),
                abstained=False,
                trace=(),
            )

    return Labelled


config = load_config(Path(os.environ["TIRESIAS_TEST_CONFIG"]))
if st.session_state.get("use_b"):
    config = config.model_copy(update={"blurb": "a different scope"})
    render_chat(config, agent_factory=factory("B"))
else:
    render_chat(config, agent_factory=factory("A"))
