"""Per-city configuration, loaded from a ``tiresias.yml`` in the city's repo.

The engine holds no city specifics: the warehouse, the queryable tables, the
retrieval examples, prompt notes, the grounding threshold, and every limit come
from this file. Relative paths resolve against the YAML file's own directory, so a
city's config works the same from any working directory.

Unknown keys are rejected rather than ignored: a typo in a security-relevant key
(the table allowlist, a limit) must fail loudly, not silently fall back.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TableScope(_Strict):
    """The security boundary: which tables and columns the agent may see and query.

    Kept as explicit lists (not "every mart") so a new table must be deliberately
    opted in. ``excluded`` records tables deliberately kept out, so a city can test
    that every built model is classified one way or the other.
    """

    # dbt materializes marts into these schemas; any other qualifier is rejected.
    schemas: frozenset[str] = frozenset({"main"})
    allowed: frozenset[str]
    excluded: frozenset[str] = frozenset()
    # Columns inside allowed tables that are hidden from the agent's catalog and
    # rejected by the SQL guard (e.g. large JSON shapes used only by map pages).
    # Read-only after validation: it is shared by every component holding the config.
    map_only_columns: Mapping[str, frozenset[str]] = Field(default_factory=dict)

    @field_validator("map_only_columns", mode="after")
    @classmethod
    def _read_only(cls, value: Mapping[str, frozenset[str]]) -> Mapping[str, frozenset[str]]:
        return MappingProxyType(dict(value))

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        overlap = self.allowed & self.excluded
        if overlap:
            raise ValueError(f"tables both allowed and excluded: {sorted(overlap)}")
        stray = set(self.map_only_columns) - self.allowed
        if stray:
            raise ValueError(f"map_only_columns names tables that are not allowed: {sorted(stray)}")
        return self


class Example(_Strict):
    """A retrieval exemplar: how people ask -> what holds the answer.

    ``grounds`` is the structured target (table or metric names); ``guidance`` may
    mention other tables, e.g. to disambiguate, without grounding to them.
    """

    question: str
    guidance: str
    grounds: tuple[str, ...]


class GoldPaths(_Strict):
    answers: Path | None = None
    retrieval: Path | None = None


class Grounding(_Strict):
    # Below this top-1 dense cosine, retrieval hard-abstains before planning. It is
    # a lenient pre-filter; the planner is the authoritative abstain decider.
    threshold: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.56
    # Why this value: the measured score bands it was picked from.
    calibration: str = ""


class Limits(_Strict):
    # Hard row cap injected into every executed query.
    max_rows: PositiveInt = 1000
    # Backstop on the serialized result size (bytes).
    max_result_bytes: PositiveInt = 256_000
    # Wall-clock cap (seconds) on executing a validated query.
    statement_timeout_s: Annotated[PositiveFloat, Field(allow_inf_nan=False)] = 15.0
    # Abuse caps for a public chat front end.
    max_question_chars: PositiveInt = 500
    max_per_session: PositiveInt = 15
    max_per_day: PositiveInt = 200


class Chat(_Strict):
    example_questions: tuple[str, ...] = ()


class TiresiasConfig(_Strict):
    """Everything the engine needs to know about one city's warehouse."""

    # Directory the relative paths resolve against (set by ``load_config``).
    root: Path = Path(".")

    city: str
    # One line naming what the warehouse holds; used in prompts and the abstain message.
    blurb: str
    warehouse: Path
    dbt_target: Path
    metrics: Path
    gold: GoldPaths = GoldPaths()
    tables: TableScope
    examples: tuple[Example, ...] = ()
    # City-specific caveats the planner must respect (appended to its system prompt).
    planner_notes: tuple[str, ...] = ()
    grounding: Grounding = Grounding()
    limits: Limits = Limits()
    chat: Chat = Chat()

    @model_validator(mode="after")
    def _resolve_paths(self) -> Self:
        # Frozen model: resolve relative paths once, at construction.
        def resolve(path: Path) -> Path:
            path = path.expanduser()
            return path if path.is_absolute() else self.root / path

        for name in ("warehouse", "dbt_target", "metrics"):
            object.__setattr__(self, name, resolve(getattr(self, name)))
        object.__setattr__(
            self,
            "gold",
            GoldPaths(
                answers=resolve(self.gold.answers) if self.gold.answers else None,
                retrieval=resolve(self.gold.retrieval) if self.gold.retrieval else None,
            ),
        )
        return self

    @property
    def db_path(self) -> Path:
        return self.warehouse

    @property
    def catalog_path(self) -> Path:
        return self.dbt_target / "catalog.json"

    @property
    def manifest_path(self) -> Path:
        return self.dbt_target / "manifest.json"

    @property
    def metrics_path(self) -> Path:
        return self.metrics

    def with_limits(self, **overrides: float) -> TiresiasConfig:
        """A copy with some limits replaced (e.g. a tighter timeout in a test).

        The new limits are validated like the YAML: an unknown or out-of-range cap
        raises rather than silently leaving the old value in place.
        """
        limits = Limits.model_validate({**self.limits.model_dump(), **overrides})
        return self.model_copy(update={"limits": limits})


def load_config(path: Path) -> TiresiasConfig:
    """Parse and validate a city's ``tiresias.yml``."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Tiresias config not found at {path}")
    data = yaml.safe_load(path.read_text()) or {}
    config = TiresiasConfig.model_validate({**data, "root": path.resolve().parent})
    logger.debug("Loaded config for %s from %s", config.city, path)
    return config
