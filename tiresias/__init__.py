"""Tiresias — a grounded civic-intelligence agent over the Elvis warehouse.

Tiresias reads the same ``vegas.duckdb`` and dbt artifacts that Elvis builds, but
never mutates them. It answers natural-language questions about Las Vegas open data
with citations and the SQL shown — or abstains when it cannot ground the answer in
a real row. See ``TIRESIAS-PRD.md`` for the product decisions and phase plan.
"""

__all__ = ["__version__"]

__version__ = "0.0.0"
