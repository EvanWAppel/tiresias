"""Tiresias — a grounded civic-intelligence agent over the restaurant marts.

Ask a natural-language question about Las Vegas restaurant inspections. Tiresias
plans SQL grounded in the real schema and the governed failure-rate metric,
executes it read-only through its MCP tool, and answers **with the SQL and
citations shown** — or **abstains** when it can't ground the answer in a real row.

This is a public, unauthenticated endpoint where every question costs two model
calls, so it carries abuse guards: an input-length cap, a per-session cap, and a
process-wide daily circuit breaker. These sit *below* the hard backstop, which is
a spend limit on the Anthropic workspace/key. Limits are env-overridable so they
can be tuned on Railway without a redeploy.

This page is additive; it does not touch the other Elvis views. Heavy imports
(agent, embeddings, Anthropic SDK) live inside this module so they load only when
the page is opened.
"""

import asyncio
import datetime
import logging
import os
import threading

import streamlit as st

logger = logging.getLogger(__name__)

# --- Abuse guards (tune via Railway env vars) ---
MAX_QUESTION_CHARS = int(os.environ.get("TIRESIAS_MAX_QUESTION_CHARS", "500"))
MAX_PER_SESSION = int(os.environ.get("TIRESIAS_MAX_PER_SESSION", "15"))
MAX_PER_DAY = int(os.environ.get("TIRESIAS_MAX_PER_DAY", "200"))

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


@st.cache_resource
def _daily_limiter() -> dict:
    """Process-wide daily counter (shared across all sessions on this replica).

    Resets on a new day or a process restart. Assumes a single Railway replica;
    with multiple replicas each would keep its own count (still bounded per replica).
    """
    return {"lock": threading.Lock(), "day": None, "count": 0}


def _claim_daily_slot() -> bool:
    """Reserve one of today's global query slots; False if the day's cap is hit."""
    state = _daily_limiter()
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    with state["lock"]:
        if state["day"] != today:
            state["day"], state["count"] = today, 0
        if state["count"] >= MAX_PER_DAY:
            return False
        state["count"] += 1
        return True


agent = _get_agent()

st.markdown(
    "**Try:** *Which restaurants have the highest failure rate?* · "
    "*What are the most common violations?* · "
    "*How have inspection counts changed over time?*"
)

question = st.chat_input(
    "Ask about Las Vegas restaurant inspections…", max_chars=MAX_QUESTION_CHARS
)
if question:
    query = question.strip()

    # 1) Per-session cap (casual-spam brake; bypassable with a fresh session).
    used = st.session_state.get("tiresias_used", 0)
    if used >= MAX_PER_SESSION:
        st.warning(
            f"You've reached this session's limit of {MAX_PER_SESSION} questions. "
            "Reload the page to start a new session."
        )
        st.stop()

    if not query:
        st.stop()

    # 2) Input-length cap (belt-and-suspenders behind the widget's max_chars).
    if len(query) > MAX_QUESTION_CHARS:
        st.warning("That question is too long — please shorten it.")
        st.stop()

    # 3) Daily global circuit breaker across all sessions.
    if not _claim_daily_slot():
        st.warning(
            "Tiresias has reached today's demo query limit. Please check back "
            "tomorrow — this cap keeps the public demo's costs bounded."
        )
        st.stop()

    st.session_state["tiresias_used"] = used + 1

    with st.chat_message("user"):
        st.write(query)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Grounding, planning, and querying…"):
                result = asyncio.run(agent.answer(query))
        except Exception:  # never leak internals to a public UI
            logger.exception("Tiresias agent error for question: %s", query)
            st.error("Something went wrong answering that. Please try again in a moment.")
            st.stop()

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
