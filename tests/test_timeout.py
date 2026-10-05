"""The statement timeout actually stops runaway queries (security review S1)."""

from __future__ import annotations

import time

import pytest

from tiresias import tools
from tiresias.config import TiresiasConfig
from tiresias.tools import QueryTimeoutError

# An aggregate over an unfiltered 3-way self cross join: guard-legal (one allowed
# table, SELECT-only) but defeats limit pushdown, so it runs for minutes uncapped.
RUNAWAY_SQL = "select count(*) as n from mart_events a, mart_events b, mart_events c"


def test_runaway_query_is_interrupted(config: TiresiasConfig) -> None:
    started = time.monotonic()
    with pytest.raises(QueryTimeoutError, match="timed out"):
        tools.run_validated_sql(RUNAWAY_SQL, config.with_limits(statement_timeout_s=0.5))
    assert time.monotonic() - started < 10


def test_fast_query_is_unaffected_by_timeout(config: TiresiasConfig) -> None:
    result = tools.run_validated_sql(
        "select count(*) as n from mart_inspections", config.with_limits(statement_timeout_s=0.5)
    )
    assert result.row_count == 1
    assert result.rows[0]["n"] == 50


def test_connection_still_usable_after_interrupt(config: TiresiasConfig) -> None:
    with pytest.raises(QueryTimeoutError):
        tools.run_validated_sql(RUNAWAY_SQL, config.with_limits(statement_timeout_s=0.5))
    result = tools.run_validated_sql("select 1 as one from mart_inspections limit 1", config)
    assert result.row_count == 1
