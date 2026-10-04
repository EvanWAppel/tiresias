"""The statement timeout actually stops runaway queries (security review S1)."""

from __future__ import annotations

import time

import pytest

from tiresias import tools
from tiresias.config import DEFAULT_SETTINGS
from tiresias.tools import QueryTimeoutError

# An aggregate over an unfiltered 3-way self cross join: guard-legal (one allowed
# table, SELECT-only) but defeats limit pushdown, so it runs for minutes uncapped.
RUNAWAY_SQL = (
    "select count(*) as n from mart_inspection_history a, "
    "mart_inspection_history b, mart_inspection_history c"
)


def test_runaway_query_is_interrupted(_require_warehouse: None) -> None:
    settings = DEFAULT_SETTINGS.model_copy(update={"statement_timeout_s": 0.5})
    started = time.monotonic()
    with pytest.raises(QueryTimeoutError, match="timed out"):
        tools.run_validated_sql(RUNAWAY_SQL, settings=settings)
    assert time.monotonic() - started < 10


def test_fast_query_is_unaffected_by_timeout(_require_warehouse: None) -> None:
    settings = DEFAULT_SETTINGS.model_copy(update={"statement_timeout_s": 0.5})
    result = tools.run_validated_sql(
        "select count(*) as n from mart_restaurants", settings=settings
    )
    assert result.row_count == 1


def test_connection_still_usable_after_interrupt(_require_warehouse: None) -> None:
    settings = DEFAULT_SETTINGS.model_copy(update={"statement_timeout_s": 0.5})
    with pytest.raises(QueryTimeoutError):
        tools.run_validated_sql(RUNAWAY_SQL, settings=settings)
    result = tools.run_validated_sql("select 1 as one from mart_restaurants limit 1")
    assert result.row_count == 1
