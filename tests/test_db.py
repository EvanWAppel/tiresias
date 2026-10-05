"""Tests for the read-only warehouse access layer."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from tiresias import db
from tiresias.config import TiresiasConfig


def test_query_reads_rows(config: TiresiasConfig) -> None:
    result = db.query("select 1 as n", config.db_path)
    assert result["n"].tolist() == [1]


def test_reads_a_real_row(config: TiresiasConfig) -> None:
    df = db.query(
        "select permit_number, failure_rate_pct from main.mart_inspections limit 1",
        config.db_path,
    )
    assert list(df.columns) == ["permit_number", "failure_rate_pct"]
    assert len(df) == 1


def test_connection_is_read_only(config: TiresiasConfig) -> None:
    # A write must be physically impossible, not merely guarded against.
    with pytest.raises((duckdb.Error, RuntimeError)):
        db.query("create table main.should_not_exist as select 1", config.db_path)


def test_missing_warehouse_raises_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Warehouse not found"):
        db.query("select 1", tmp_path / "nope.duckdb")
