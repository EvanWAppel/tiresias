"""The engine holds no city specifics; everything comes from ``tiresias.yml``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tiresias

PACKAGE = Path(tiresias.__file__).resolve().parent

# City and agency names from the cities that install Tiresias, plus the dbt
# "mart_" prefix: a table name in the engine means a city leaked into it.
FORBIDDEN = [
    "elvis",
    "vegas",
    "henderson",
    "lvmpd",
    "snhd",
    "lvcva",
    "lake mead",
    "nevada",
    "robbins",
    "seattle",
    "king county",
    "puget",
    "gregan",
    "glendora",
    "groening",
    "portland",
    "multnomah",
    "testville",
    "mart_",
]


def _package_files() -> list[Path]:
    return sorted(
        p
        for p in PACKAGE.rglob("*")
        if p.is_file() and p.suffix in {".py", ".yml", ".yaml", ".md", ".txt"}
    )


def test_package_has_files() -> None:
    assert any(p.name == "agent.py" for p in _package_files())


@pytest.mark.parametrize("path", _package_files(), ids=lambda p: p.name)
def test_no_city_strings_in_engine(path: Path) -> None:
    text = path.read_text().lower()
    found = [word for word in FORBIDDEN if re.search(re.escape(word), text)]
    assert found == [], f"{path.relative_to(PACKAGE)} mentions {found}"
