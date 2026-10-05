"""The `tiresias` command line: check, calibrate, eval, mcp."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FakeEmbedder
from tiresias import cli


@pytest.fixture(autouse=True)
def _offline_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "FastEmbedEmbedder", FakeEmbedder)


def test_check_clean_city_exits_zero(config_path: Path, capsys) -> None:
    assert cli.main(["check", "--config", str(config_path)]) == 0
    assert "no problems" in capsys.readouterr().out


def test_check_reports_errors_and_exits_nonzero(config_path: Path, capsys) -> None:
    # A sibling of the fixture's tiresias.yml, so its relative paths resolve the same.
    broken = config_path.with_name("broken.yml")
    broken.write_text(
        config_path.read_text().replace("- mart_events\n", "- mart_events\n    - mart_gone\n")
    )
    assert cli.main(["check", "--config", str(broken)]) == 1
    assert "mart_gone" in capsys.readouterr().out


def test_calibrate_prints_the_score_table(config_path: Path, capsys) -> None:
    assert cli.main(["calibrate", "--config", str(config_path)]) == 0
    out = capsys.readouterr().out
    assert "current threshold" in out
    assert "How many restaurants are there?" in out


def test_eval_retrieval_only_needs_no_key(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(["eval", "--config", str(config_path), "--retrieval-only"]) == 0
    assert "recall@3 = 1.00" in capsys.readouterr().out


def test_eval_without_key_refuses_to_run_gold(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(["eval", "--config", str(config_path)]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_eval_runs_gold_through_the_agent(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tests.test_agent import COUNT, FakeProvider, FakeRetriever
    from tiresias.agent import TiresiasAgent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")

    def fake_agent(config, retriever):
        return TiresiasAgent(config, retriever=FakeRetriever(True), provider=FakeProvider([COUNT]))

    monkeypatch.setattr(cli, "_make_agent", fake_agent)
    # The fake always answers with a count, so the off-topic case fails (no abstain)
    # and worst_failure_rate fails (no failure_rate_pct in the SQL).
    assert cli.main(["eval", "--config", str(config_path)]) == 1
    out = capsys.readouterr().out
    assert "1/3 passed" in out
    assert "FAIL off_topic" in out


def test_missing_config_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="tiresias.yml"):
        cli.main(["check", "--config", str(tmp_path / "tiresias.yml")])


def test_mcp_serves_stdio(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    served = []
    monkeypatch.setattr(cli, "serve_stdio", lambda config: served.append(config.city))
    assert cli.main(["mcp", "--config", str(config_path)]) == 0
    assert served == ["Testville"]
