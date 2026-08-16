"""Tiresias — a grounded civic-intelligence agent over the restaurant marts.

Ask a natural-language question about Las Vegas restaurant inspections. Tiresias
plans SQL grounded in the real schema and the governed failure-rate metric,
executes it read-only through its MCP tool, and answers **with the SQL and
citations shown** — or **abstains** when it can't ground the answer in a real row.

This page is additive; it does not touch the other Elvis views. Heavy imports
(agent, embeddings, Anthropic SDK) live inside this module so they load only when
the page is opened.
"""

import asyncio
import os

import streamlit as st

st.title("🔮 Tiresias — ask the warehouse")
st.caption(
    "A grounded agent over the restaurant-inspection marts. It shows its SQL and "
    "citations, and **abstains** rather than guess when a question falls outside "
    "the data. Phase 0: restaurant inspections only."
)

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.info(
        "Tiresias needs an `ANTHROPIC_API_KEY` to run its reasoning model. "
        "Set it in the environment to enable the agent."
    )
    st.stop()


@st.cache_resource(show_spinner="Loading the Tiresias agent…")
def _get_agent():
    # Imported lazily so opening other pages doesn't pay these imports.
    from tiresias.agent import TiresiasAgent

    return TiresiasAgent()


agent = _get_agent()

st.markdown(
    "**Try:** *Which restaurants have the highest failure rate?* · "
    "*What are the most common violations?* · "
    "*How have inspection counts changed over time?*"
)

question = st.chat_input("Ask about Las Vegas restaurant inspections…")
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Grounding, planning, and querying…"):
            result = asyncio.run(agent.answer(question))

        if result.abstained:
            st.warning(result.answer)
        else:
            st.write(result.answer)
            if result.sql:
                st.code(result.sql, language="sql")
            if result.citations:
                st.caption("Cited sources: " + ", ".join(f"`{c}`" for c in result.citations))

        with st.expander("Trace (plan → execute → answer)"):
            for step in result.trace:
                st.text(step)
