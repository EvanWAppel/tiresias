"""Schema truth for Tiresias, sourced from the real dbt artifacts.

Column *types* come from ``target/catalog.json`` (dbt's warehouse introspection);
column and model *descriptions* come from ``target/manifest.json`` (the dbt docs).
The catalog is bounded to the table allowlist so retrieval, the MCP
resource, and the SQL guard all share one honest picture of what exists.

Regenerate the artifacts with ``dbt docs generate`` (in the city repo) if the
warehouse schema changes.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from tiresias.config import TiresiasConfig

logger = logging.getLogger(__name__)


class Column(BaseModel):
    """One column: a real name/type from the warehouse plus its dbt doc string."""

    model_config = {"frozen": True}

    name: str
    type: str
    description: str = ""


class Table(BaseModel):
    """One table: its schema-qualified identity, columns, and dbt description."""

    model_config = {"frozen": True}

    name: str
    db_schema: str
    database: str
    description: str = ""
    columns: tuple[Column, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(col.name for col in self.columns)

    def to_prompt(self) -> str:
        """Render this table as grounding text for retrieval / the MCP resource."""
        header = f"Table {self.db_schema}.{self.name}"
        if self.description:
            header += f" — {self.description}"
        lines = [header, "Columns:"]
        for col in self.columns:
            doc = f" — {col.description}" if col.description else ""
            lines.append(f"  - {col.name} ({col.type}){doc}")
        return "\n".join(lines)


class Catalog(BaseModel):
    """The bounded set of tables Tiresias may reference."""

    model_config = {"frozen": True}

    tables: tuple[Table, ...]

    def get(self, name: str) -> Table:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(f"Table {name!r} not in catalog; known tables: {list(self.table_names)}")

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(table.name for table in self.tables)


def load_catalog(config: TiresiasConfig) -> Catalog:
    """Build the bounded catalog from the dbt artifacts.

    Only the config's allowed tables are included, minus their map-only
    columns. Raises if the artifacts
    are missing (a clear instruction to run ``dbt docs generate``) or yield no
    allowed tables (a scope/config mismatch worth failing loudly on).
    """
    for path in (config.catalog_path, config.manifest_path):
        if not path.exists():
            raise FileNotFoundError(
                f"dbt artifact not found at {path}. Run `dbt docs generate` in the city repo first."
            )

    catalog_json = json.loads(config.catalog_path.read_text())
    manifest_json = json.loads(config.manifest_path.read_text())
    manifest_nodes = manifest_json.get("nodes", {})

    map_only = config.tables.map_only_columns
    tables: list[Table] = []
    for unique_id, node in catalog_json.get("nodes", {}).items():
        meta = node["metadata"]
        name = meta["name"]
        if name not in config.tables.allowed:
            continue

        doc_columns = manifest_nodes.get(unique_id, {}).get("columns", {})
        columns = tuple(
            Column(
                name=col["name"],
                type=col["type"],
                description=(doc_columns.get(col["name"], {}) or {}).get("description") or "",
            )
            for col in sorted(node["columns"].values(), key=lambda c: c["index"])
            # Map-only columns are not part of the agent's world (see config).
            if col["name"] not in map_only.get(name, frozenset())
        )
        tables.append(
            Table(
                name=name,
                db_schema=meta["schema"],
                database=meta["database"],
                description=manifest_nodes.get(unique_id, {}).get("description") or "",
                columns=columns,
            )
        )

    if not tables:
        raise ValueError(
            f"No allowed tables found in {config.catalog_path}; "
            f"allowlist={sorted(config.tables.allowed)}. "
            "Check the allowlist or regenerate the catalog."
        )

    tables.sort(key=lambda t: t.name)
    logger.debug("Loaded catalog with %d tables: %s", len(tables), [t.name for t in tables])
    return Catalog(tables=tuple(tables))
