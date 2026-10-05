"""Optional Streamlit chat page (install ``tiresias[streamlit]``).

A city app adds one page that calls ``render_chat(config)``. The page answers with
the SQL and citations shown, or abstains. It is meant for a public,
unauthenticated endpoint where every question costs two model calls, so it carries
abuse guards: an input-length cap, a per-session cap, and a process-wide daily
circuit breaker. These sit *below* the hard backstop, which is a spend limit on
the app's own dedicated API key. The caps come from ``tiresias.yml`` and can be
overridden by ``TIRESIAS_MAX_*`` environment variables, so they can be tuned on
the host without a redeploy.

The guard logic is plain functions (tested without Streamlit); Streamlit itself is
imported only inside ``render_chat``.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Protocol

from tiresias.agent import TiresiasAnswer
from tiresias.config import Limits, TiresiasConfig

logger = logging.getLogger(__name__)

_ENV_OVERRIDES = {
    "TIRESIAS_MAX_QUESTION_CHARS": "max_question_chars",
    "TIRESIAS_MAX_PER_SESSION": "max_per_session",
    "TIRESIAS_MAX_PER_DAY": "max_per_day",
}


class Answers(Protocol):
    async def answer(self, question: str) -> TiresiasAnswer: ...


def limits_from_env(limits: Limits, environ: Mapping[str, str] = os.environ) -> Limits:
    """The config's limits with any ``TIRESIAS_MAX_*`` overrides applied (validated)."""
    overrides = {field: environ[var] for var, field in _ENV_OVERRIDES.items() if var in environ}
    return Limits.model_validate({**limits.model_dump(), **overrides})


class DailyLimiter:
    """Process-wide daily question counter, shared across sessions on one replica.

    Resets on a new UTC day or a process restart. With several replicas each keeps
    its own count (still bounded per replica).
    """

    def __init__(self, max_per_day: int) -> None:
        self.max_per_day = max_per_day
        self._lock = threading.Lock()
        self._day: str | None = None
        self._count = 0

    def claim(self, today: str) -> bool:
        """Reserve one of today's slots; False once the day's cap is reached."""
        with self._lock:
            if self._day != today:
                self._day, self._count = today, 0
            if self._count >= self.max_per_day:
                return False
            self._count += 1
            return True


def question_problem(question: str, used: int, limits: Limits) -> str | None:
    """Why this question can't be asked in this session, or None if it can."""
    if used >= limits.max_per_session:
        return (
            f"You've reached this session's limit of {limits.max_per_session} questions. "
            "Reload the page to start a new session."
        )
    if len(question) > limits.max_question_chars:
        return "That question is too long — please shorten it."
    return None


def render_chat(config: TiresiasConfig, agent_factory: Callable[[], Answers] | None = None) -> None:
    """Render the Tiresias chat page for one city."""
    import streamlit as st

    limits = limits_from_env(config.limits)

    st.title(f"Tiresias — ask the {config.city} warehouse")
    st.caption(
        f"A grounded agent over {config.city} open data: {config.blurb}. It shows its "
        "SQL and citations, and **abstains** rather than guess when a question falls "
        "outside the data."
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.info(
            "Tiresias needs an `ANTHROPIC_API_KEY` to run its reasoning model. "
            "Set it in the environment to enable the agent."
        )
        st.stop()

    @st.cache_resource(show_spinner="Loading the Tiresias agent…")
    def _agent(city: str) -> Answers:
        if agent_factory is not None:
            return agent_factory()
        from tiresias.agent import TiresiasAgent

        return TiresiasAgent(config)

    @st.cache_resource
    def _limiter(city: str, max_per_day: int) -> DailyLimiter:
        return DailyLimiter(max_per_day)

    agent = _agent(config.city)

    if config.chat.example_questions:
        st.markdown("**Try:** " + " · ".join(f"*{q}*" for q in config.chat.example_questions))

    question = st.chat_input(
        f"Ask about {config.city} open data…", max_chars=limits.max_question_chars
    )
    if not question or not question.strip():
        return
    query = question.strip()

    used = st.session_state.get("tiresias_used", 0)
    problem = question_problem(query, used, limits)
    if problem:
        st.warning(problem)
        st.stop()

    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    if not _limiter(config.city, limits.max_per_day).claim(today):
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
        except Exception:  # never leak internals to a public UI; logged in full
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
