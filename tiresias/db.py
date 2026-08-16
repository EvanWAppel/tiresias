"""Read-only DuckDB access for Tiresias.

Mirrors ``app_db.py``'s core discipline — the connection is opened
``read_only=True`` so even a bug in the SQL guard physically cannot mutate the
warehouse — but drops the Streamlit caching so the MCP server and eval harness can
use it headless. Errors are never swallowed; a failing query raises for the caller.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

from tiresias.config import DB_PATH

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _connection(db_path_str: str) -> duckdb.DuckDBPyConnection:
    """One shared read-only connection per warehouse path (cached).

    DuckDB permits multiple concurrent read-only handles, and a per-call cursor
    (see :func:`query`) keeps reads thread-safe over this shared connection.
    """
    db_path = Path(db_path_str)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Warehouse not found at {db_path}. "
            "Run `uv run python build_warehouse.py` then `uv run dbt build` first."
        )
    logger.debug("Opening read-only DuckDB connection at %s", db_path)
    return duckdb.connect(str(db_path), read_only=True)


def get_connection(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Return the shared read-only connection for ``db_path``."""
    return _connection(str(db_path))


def query(sql: str, db_path: Path = DB_PATH) -> pd.DataFrame:
    """Run ``sql`` on a fresh cursor and return a DataFrame.

    This is the raw reader used by the catalog/profiling helpers. Untrusted,
    agent-drafted SQL must instead go through ``tiresias.sql_guard`` +
    ``run_validated_sql`` — never call this directly with model output.
    """
    logger.debug("Executing read-only query: %s", sql)
    return get_connection(db_path).cursor().execute(sql).df()
