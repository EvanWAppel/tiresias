"""Tiresias — a grounded text-to-SQL agent for dbt + DuckDB warehouses.

Tiresias reads a city's DuckDB warehouse and dbt artifacts read-only. It answers
natural-language questions with the SQL and citations shown, or abstains when it
cannot ground the answer in a real row. Each city describes its warehouse in a
``tiresias.yml`` (see ``tiresias.config``); the engine holds no city specifics.
"""

__all__ = ["__version__"]

__version__ = "0.1.1"
