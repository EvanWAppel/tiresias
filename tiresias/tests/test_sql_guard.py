"""Tests for the read-only SQL guard."""

from __future__ import annotations

import pytest

from tiresias import db
from tiresias.sql_guard import SqlGuardError, guard_sql


def test_accepts_simple_select_and_caps_rows() -> None:
    safe = guard_sql("select permit_number from mart_restaurants")
    assert safe.tables == ("mart_restaurants",)
    assert safe.row_cap == 1000
    assert "limit 1000" in safe.sql.lower()


def test_preserves_smaller_existing_limit() -> None:
    safe = guard_sql("select * from mart_restaurants limit 5")
    assert safe.row_cap == 5
    assert "limit 5" in safe.sql.lower()


def test_caps_oversized_limit() -> None:
    safe = guard_sql("select * from mart_restaurants limit 999999")
    assert safe.row_cap == 1000


def test_accepts_cte_over_allowed_table() -> None:
    sql = (
        "with worst as (select permit_number, failure_rate_pct from mart_restaurants) "
        "select * from worst order by failure_rate_pct desc"
    )
    safe = guard_sql(sql)
    # The CTE alias `worst` must not be mistaken for a disallowed table.
    assert safe.tables == ("mart_restaurants",)


@pytest.mark.parametrize(
    "sql",
    [
        "insert into mart_restaurants values (1)",
        "update mart_restaurants set restaurant_name = 'x'",
        "delete from mart_restaurants",
        "drop table mart_restaurants",
        "create table t as select 1",
        "alter table mart_restaurants add column c int",
    ],
)
def test_rejects_dml_and_ddl(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        guard_sql(sql)


def test_rejects_multi_statement() -> None:
    with pytest.raises(SqlGuardError, match="single statement"):
        guard_sql("select 1 from mart_restaurants; select 2 from mart_restaurants")


def test_rejects_table_outside_allowlist() -> None:
    with pytest.raises(SqlGuardError, match="allowlist"):
        guard_sql("select * from mart_crime_by_type")


def test_rejects_disallowed_schema() -> None:
    with pytest.raises(SqlGuardError, match="schema"):
        guard_sql("select * from raw.mart_restaurants")


def test_explain_rejects_hallucinated_column(_require_warehouse: None) -> None:
    conn = db.get_connection()
    with pytest.raises(SqlGuardError, match="catalog validation"):
        guard_sql("select no_such_column from mart_restaurants", connection=conn)


def test_explain_accepts_valid_query(_require_warehouse: None) -> None:
    conn = db.get_connection()
    safe = guard_sql(
        "select permit_number, failure_rate_pct from mart_restaurants", connection=conn
    )
    assert safe.tables == ("mart_restaurants",)
