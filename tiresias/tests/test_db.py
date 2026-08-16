"""Tests for the read-only warehouse access layer."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from tiresias import db


def test_query_reads_rows(_require_warehouse: None) -> None:
    result = db.query("select 1 as n")
    assert result["n"].tolist() == [1]


def test_reads_a_real_restaurant_row(_require_warehouse: None) -> None:
    df = db.query("select permit_number, failure_rate_pct from main.mart_restaurants limit 1")
    assert list(df.columns) == ["permit_number", "failure_rate_pct"]
    assert len(df) == 1


def test_connection_is_read_only(_require_warehouse: None) -> None:
    # A write must be physically impossible, not merely guarded against.
    with pytest.raises((duckdb.Error, RuntimeError)):
        db.query("create table main.should_not_exist as select 1")


def test_missing_warehouse_raises_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="build_warehouse"):
        db.query("select 1", db_path=tmp_path / "nope.duckdb")
