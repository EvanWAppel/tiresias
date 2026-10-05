"""Prompts and user-facing copy, built from a city's config.

The wording is the engine's; the city supplies its name, a one-line blurb of what
its warehouse holds, and any caveats the planner must respect.
"""

from __future__ import annotations

from tiresias.config import TiresiasConfig

_PLAN_RULES = (
    "It is a point-in-time snapshot, not live data. You are given the exact schema "
    "(tables and columns) and the governed metric definitions. Draft exactly ONE "
    "read-only DuckDB SELECT that answers the user's question using ONLY the listed "
    "tables and columns, and prefer a governed metric's canonical expression over "
    "inventing arithmetic. Reference tables by their bare table name, without the "
    "schema prefix shown in the schema listing. "
    "If the question cannot be answered from these tables and columns — including "
    "forecasts, live/current conditions, or topics the warehouse does not hold — do "
    "NOT guess; abstain. Respect each column's documented caveats. Tables document "
    "their coverage period; if a question asks about a period outside it (e.g. a "
    "year with no loaded data), abstain rather than report a zero. Return "
    "action='query' with the SQL, or action='abstain' with a brief reason. SELECT "
    "only; never DDL/DML."
)

SYNTHESIZE_SYSTEM = (
    "You are Tiresias. Answer the user's question using ONLY the query results "
    "provided — never invent numbers that are not in the results. Be concise and "
    "factual. The SQL and its source tables are shown to the user separately, so "
    "do not repeat the SQL. If the results are empty, say so plainly."
)


def plan_system_prompt(config: TiresiasConfig) -> str:
    """The planner's system prompt for one city."""
    prompt = (
        f"You are Tiresias, a grounded SQL analyst for the {config.city} open-data "
        f"warehouse ({config.blurb}). {_PLAN_RULES}"
    )
    if config.planner_notes:
        notes = "\n".join(f"- {note}" for note in config.planner_notes)
        prompt += f"\n\nCity-specific notes:\n{notes}"
    return prompt


def abstain_message(config: TiresiasConfig) -> str:
    """What the user sees when Tiresias declines to answer."""
    return (
        f"I can't answer that from the {config.city} open-data warehouse, so I'm not "
        f"going to guess. Try a question about what it holds: {config.blurb}."
    )
