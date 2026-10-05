"""Read-only SQL guard for agent-drafted queries.

Untrusted, model-generated SQL passes through here before it is ever executed. The
guard uses a real parser (sqlglot, DuckDB dialect) rather than regex so it can:

  * reject anything that is not a single SELECT (no DDL/DML, no multi-statement),
  * restrict table/schema references to an allowlist,
  * reject map-only geometry columns (directly, via star expansion, or as a
    whole-row struct),
  * inject a hard row cap, and
  * validate the query against the live catalog via EXPLAIN (catching hallucinated
    columns/tables before execution).

This is defense-in-depth on top of the physically read-only connection in
``tiresias.db`` — a guard bug still cannot mutate the warehouse, and a write that
somehow slipped the guard would still be refused by DuckDB.
"""

from __future__ import annotations

import logging

import duckdb
import sqlglot
from pydantic import BaseModel
from sqlglot import exp

from tiresias.config import TiresiasConfig

logger = logging.getLogger(__name__)

# DML/DDL node types forbidden anywhere in the tree (belt-and-suspenders behind the
# "top level must be a SELECT" check).
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,  # SET, CALL, VACUUM, and other bare commands
    exp.Copy,
)


class SqlGuardError(ValueError):
    """Raised when agent-drafted SQL violates the read-only safety policy."""


class SafeSql(BaseModel):
    """A query that has passed every guard check and carries a hard row cap."""

    model_config = {"frozen": True}

    sql: str
    tables: tuple[str, ...]
    row_cap: int


def _effective_limit(tree: exp.Expression, max_rows: int) -> int:
    """Keep an existing LIMIT if it is already within the cap, else use the cap."""
    limit = tree.args.get("limit")
    if limit is None:
        return max_rows
    try:
        requested = int(limit.expression.name)
    except (AttributeError, ValueError):
        return max_rows
    return min(requested, max_rows)


def _map_only_names(map_only: dict[str, frozenset[str]], referenced: set[str]) -> frozenset[str]:
    return frozenset().union(*(map_only.get(t, frozenset()) for t in referenced))


def _reject_map_only_references(
    tree: exp.Expression, referenced: set[str], map_only: dict[str, frozenset[str]]
) -> None:
    """Reject direct references to map-only columns, and whole-row references.

    DuckDB lets a bare table name or alias stand for the entire row as a STRUCT
    (``select t from some_table t``), which would smuggle the geometry
    out, so a column reference that names a map-only table or its alias is
    rejected too.
    """
    blocked = _map_only_names(map_only, referenced)
    if not blocked:
        return
    row_names = {
        name.lower()
        for table in tree.find_all(exp.Table)
        if table.name in map_only
        for name in (table.name, table.alias)
        if name
    }
    for column in tree.find_all(exp.Column):
        name = column.name.lower()
        if name in {b.lower() for b in blocked}:
            raise SqlGuardError(
                f"column {column.name!r} is map-only geometry and cannot be queried"
            )
        if not column.table and name in row_names:
            raise SqlGuardError(
                f"{column.name!r} selects a whole row including map-only geometry; "
                "name the columns you need"
            )


def _reject_map_only_output(
    described: list[tuple], referenced: set[str], map_only: dict[str, frozenset[str]]
) -> None:
    """Reject if the planned output exposes a map-only column (by name or nested)."""
    blocked = {b.lower() for b in _map_only_names(map_only, referenced)}
    for row in described:
        column_name, column_type = str(row[0]).lower(), str(row[1]).lower()
        if any(b in column_name or b in column_type for b in blocked):
            raise SqlGuardError(
                f"output column {row[0]!r} exposes map-only geometry; "
                "list the columns you need instead of * / COLUMNS()"
            )


def guard_sql(
    sql: str,
    config: TiresiasConfig,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> SafeSql:
    """Validate and harden ``sql``; raise ``SqlGuardError`` on any violation.

    When ``connection`` is provided, the hardened query is additionally EXPLAINed
    against the live catalog so hallucinated columns/tables fail here rather than at
    execution time.
    """
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SqlGuardError(f"could not parse SQL: {exc}") from exc

    if not statements:
        raise SqlGuardError("empty SQL")
    if len(statements) > 1:
        raise SqlGuardError("only a single statement is allowed")

    tree = statements[0]
    # Spelled inline (not a tuple constant) so the type checker narrows `tree`.
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise SqlGuardError(f"only SELECT queries are allowed, got {type(tree).__name__}")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlGuardError(f"forbidden statement type: {type(node).__name__}")

    # CTE names are query-local, not real tables — don't hold them to the allowlist.
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}

    referenced: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name
        if name in cte_names:
            continue
        schema = table.db  # schema qualifier, "" if unqualified
        if name not in config.tables.allowed:
            raise SqlGuardError(
                f"table {name!r} is not in the allowlist {sorted(config.tables.allowed)}"
            )
        if schema and schema not in config.tables.schemas:
            raise SqlGuardError(f"schema {schema!r} is not allowed")
        referenced.add(name)

    if not referenced:
        raise SqlGuardError("query references no allowed table")

    map_only = config.tables.map_only_columns
    _reject_map_only_references(tree, referenced, map_only)

    row_cap = _effective_limit(tree, config.limits.max_rows)
    guarded = tree.limit(row_cap)
    final_sql = guarded.sql(dialect="duckdb")

    if connection is not None:
        try:
            connection.cursor().execute(f"EXPLAIN {final_sql}")
            # DESCRIBE plans the query (no execution) and reports its output
            # columns — catching star / COLUMNS() expansion of map-only columns.
            described = connection.cursor().execute(f"DESCRIBE {final_sql}").fetchall()
        except duckdb.Error as exc:
            raise SqlGuardError(f"query failed catalog validation: {exc}") from exc
        _reject_map_only_output(described, referenced, map_only)

    logger.debug("Guarded SQL (cap=%d, tables=%s): %s", row_cap, sorted(referenced), final_sql)
    return SafeSql(sql=final_sql, tables=tuple(sorted(referenced)), row_cap=row_cap)
