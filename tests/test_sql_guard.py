"""Tests for the read-only SQL guard."""

from __future__ import annotations

import pytest

from tiresias import db
from tiresias.config import TiresiasConfig
from tiresias.sql_guard import SqlGuardError, guard_sql


def test_accepts_simple_select_and_caps_rows(config: TiresiasConfig) -> None:
    safe = guard_sql("select permit_number from mart_inspections", config)
    assert safe.tables == ("mart_inspections",)
    assert safe.row_cap == 1000
    assert "limit 1000" in safe.sql.lower()


def test_row_cap_comes_from_config(config: TiresiasConfig) -> None:
    safe = guard_sql("select permit_number from mart_inspections", config.with_limits(max_rows=7))
    assert safe.row_cap == 7


def test_preserves_smaller_existing_limit(config: TiresiasConfig) -> None:
    safe = guard_sql("select * from mart_inspections limit 5", config)
    assert safe.row_cap == 5
    assert "limit 5" in safe.sql.lower()


def test_caps_oversized_limit(config: TiresiasConfig) -> None:
    assert guard_sql("select * from mart_inspections limit 999999", config).row_cap == 1000


def test_accepts_cte_over_allowed_table(config: TiresiasConfig) -> None:
    sql = (
        "with worst as (select permit_number, failure_rate_pct from mart_inspections) "
        "select * from worst order by failure_rate_pct desc"
    )
    # The CTE alias `worst` must not be mistaken for a disallowed table.
    assert guard_sql(sql, config).tables == ("mart_inspections",)


@pytest.mark.parametrize(
    "sql",
    [
        "insert into mart_inspections values (1)",
        "update mart_inspections set restaurant_name = 'x'",
        "delete from mart_inspections",
        "drop table mart_inspections",
        "create table t as select 1",
        "alter table mart_inspections add column c int",
    ],
)
def test_rejects_dml_and_ddl(config: TiresiasConfig, sql: str) -> None:
    with pytest.raises(SqlGuardError):
        guard_sql(sql, config)


def test_rejects_multi_statement(config: TiresiasConfig) -> None:
    with pytest.raises(SqlGuardError, match="single statement"):
        guard_sql("select 1 from mart_inspections; select 2 from mart_inspections", config)


def test_rejects_excluded_table(config: TiresiasConfig) -> None:
    with pytest.raises(SqlGuardError, match="allowlist"):
        guard_sql("select * from mart_qa_audit", config)


def test_rejects_staging_view(config: TiresiasConfig) -> None:
    with pytest.raises(SqlGuardError, match="allowlist"):
        guard_sql("select * from stg_service_calls", config)


def test_rejects_disallowed_schema(config: TiresiasConfig) -> None:
    with pytest.raises(SqlGuardError, match="schema"):
        guard_sql("select * from raw.mart_inspections", config)


@pytest.mark.parametrize(
    "sql",
    [
        "select * from read_text('/etc/passwd')",
        "select * from read_csv('x.csv')",
        "select * from duckdb_settings()",
        "select * from information_schema.tables",
        "select 1",
    ],
)
def test_rejects_file_and_metadata_access(config: TiresiasConfig, sql: str) -> None:
    with pytest.raises(SqlGuardError):
        guard_sql(sql, config)


def test_explain_rejects_hallucinated_column(config: TiresiasConfig) -> None:
    conn = db.get_connection(config.db_path)
    with pytest.raises(SqlGuardError, match="catalog validation"):
        guard_sql("select no_such_column from mart_inspections", config, connection=conn)


def test_explain_accepts_valid_query(config: TiresiasConfig) -> None:
    conn = db.get_connection(config.db_path)
    safe = guard_sql(
        "select permit_number, failure_rate_pct from mart_inspections", config, connection=conn
    )
    assert safe.tables == ("mart_inspections",)
