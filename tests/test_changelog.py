"""CHANGELOG.md keeps up with the package version, so every release has notes."""

import re
from pathlib import Path

import tiresias

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def _released_versions() -> list[str]:
    text = CHANGELOG.read_text(encoding="utf-8")
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.MULTILINE)


def test_changelog_has_a_section_for_the_current_version():
    assert tiresias.__version__ in _released_versions()


def test_changelog_lists_every_release_newest_first():
    versions = _released_versions()
    assert "0.1.0" in versions
    keyed = [tuple(int(p) for p in v.split(".")) for v in versions]
    assert keyed == sorted(keyed, reverse=True)
    assert len(set(versions)) == len(versions)
