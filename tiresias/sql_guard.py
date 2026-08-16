"""Read-only SQL guard for agent-drafted queries.

Untrusted, model-generated SQL passes through here before it is ever executed. The
guard uses a real parser (sqlglot, DuckDB dialect) rather than regex so it can:

  * reject anything that is not a single SELECT (no DDL/DML, no multi-statement),
  * restrict table/schema references to an allowlist,
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

from tiresias.config import DEFAULT_SETTINGS, TiresiasSettings

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

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.Union, exp.Subquery)


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


def guard_sql(
    sql: str,
    settings: TiresiasSettings = DEFAULT_SETTINGS,
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
    if not isinstance(tree, _ALLOWED_ROOTS):
        raise SqlGuardError(
            f"only SELECT queries are allowed, got {type(tree).__name__}"
        )
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
        if name not in settings.allowed_tables:
            raise SqlGuardError(
                f"table {name!r} is not in the Phase-0 allowlist "
                f"{sorted(settings.allowed_tables)}"
            )
        if schema and schema not in settings.allowed_schemas:
            raise SqlGuardError(f"schema {schema!r} is not allowed")
        referenced.add(name)

    if not referenced:
        raise SqlGuardError("query references no allowed table")

    row_cap = _effective_limit(tree, settings.max_rows)
    guarded = tree.limit(row_cap)
    final_sql = guarded.sql(dialect="duckdb")

    if connection is not None:
        try:
            connection.cursor().execute(f"EXPLAIN {final_sql}")
        except duckdb.Error as exc:
            raise SqlGuardError(f"query failed catalog validation: {exc}") from exc

    logger.debug("Guarded SQL (cap=%d, tables=%s): %s", row_cap, sorted(referenced), final_sql)
    return SafeSql(sql=final_sql, tables=tuple(sorted(referenced)), row_cap=row_cap)
