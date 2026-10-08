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


def test_external_access_is_off_even_without_the_guard(
    config: TiresiasConfig, tmp_path: Path
) -> None:
    # Defense in depth: if a query ever slipped the SQL guard, the connection
    # itself still cannot read files or reach the network.
    probe = tmp_path / "probe.csv"
    probe.write_text("secret\nvalue\n")
    for sql in (f"select * from read_csv('{probe}')", f"select * from '{probe}'"):
        with pytest.raises(duckdb.Error):
            db.query(sql, config.db_path)


def test_configuration_cannot_be_unlocked(config: TiresiasConfig) -> None:
    with pytest.raises(duckdb.Error):
        db.query("set enable_external_access = true", config.db_path)


def test_coexists_with_the_city_apps_own_connection(config: TiresiasConfig, tmp_path: Path) -> None:
    # A city app opens the same warehouse with its own (default-config) read-only
    # connection; Tiresias's locked-down instance must not conflict with it.
    import shutil

    copy = tmp_path / "w.duckdb"
    shutil.copy(config.db_path, copy)
    app = duckdb.connect(str(copy), read_only=True)
    assert db.query("select count(*) as n from mart_inspections", copy)["n"].tolist() == [50]
    assert app.execute("select count(*) from mart_inspections").fetchone() == (50,)
    app.close()
