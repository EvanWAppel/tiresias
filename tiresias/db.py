"""Read-only, locked-down DuckDB access for Tiresias.

Tiresias gets its own in-memory DuckDB instance that ATTACHes the city warehouse
``READ_ONLY`` and then turns off external access (file and network reads),
extension auto-install/auto-load, and locks the configuration. So even a bug in
the SQL guard cannot mutate the warehouse, read local files, or fetch URLs.

A separate instance is required: opening the warehouse path directly with a
different config would conflict with the city app's own connection to the same
file in the same process. Every cursor must start with ``USE warehouse`` (the
default catalog is per connection), so always go through :func:`cursor`.

No Streamlit caching, so the MCP server and eval harness can use it headless.
Errors are never swallowed; a failing query raises for the caller.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

WAREHOUSE = "warehouse"

_LOCKDOWN = (
    "SET enable_external_access = false",
    "SET autoinstall_known_extensions = false",
    "SET autoload_known_extensions = false",
    "SET lock_configuration = true",
)


@lru_cache(maxsize=8)
def _connection(db_path_str: str) -> duckdb.DuckDBPyConnection:
    """One locked-down instance per warehouse path (cached).

    Per-call cursors (see :func:`cursor`) keep reads thread-safe over it.
    """
    db_path = Path(db_path_str)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Warehouse not found at {db_path}. "
            "Build the city's warehouse (and run `dbt build`) first."
        )
    logger.debug("Attaching %s read-only to a locked-down DuckDB instance", db_path)
    conn = duckdb.connect(":memory:")
    escaped = str(db_path).replace("'", "''")
    conn.execute(f"ATTACH '{escaped}' AS {WAREHOUSE} (READ_ONLY)")
    for statement in _LOCKDOWN:
        conn.execute(statement)
    return conn


def get_connection(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Return the shared locked-down connection for ``db_path``."""
    return _connection(str(db_path))


def cursor(connection: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """A fresh cursor whose default catalog is the attached warehouse."""
    cur = connection.cursor()
    cur.execute(f"USE {WAREHOUSE}")
    return cur


def query(sql: str, db_path: Path) -> pd.DataFrame:
    """Run ``sql`` on a fresh cursor and return a DataFrame.

    This is the raw reader used by the catalog/profiling helpers. Untrusted,
    agent-drafted SQL must instead go through ``tiresias.sql_guard`` +
    ``run_validated_sql`` — never call this directly with model output.
    """
    logger.debug("Executing read-only query: %s", sql)
    return cursor(get_connection(db_path)).execute(sql).df()
