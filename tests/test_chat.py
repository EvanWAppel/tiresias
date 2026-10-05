"""The optional Streamlit chat: abuse guards and the rendered page."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiresias.chat import DailyLimiter, limits_from_env, question_problem
from tiresias.config import TiresiasConfig

APP = str(Path(__file__).with_name("chat_app.py"))


def test_env_overrides_config_limits(config: TiresiasConfig) -> None:
    limits = limits_from_env(config.limits, {"TIRESIAS_MAX_PER_DAY": "3"})
    assert limits.max_per_day == 3
    assert limits.max_per_session == config.limits.max_per_session


def test_invalid_env_override_raises(config: TiresiasConfig) -> None:
    with pytest.raises(ValueError):
        limits_from_env(config.limits, {"TIRESIAS_MAX_PER_DAY": "0"})


def test_daily_limiter_caps_and_resets_on_a_new_day() -> None:
    limiter = DailyLimiter(max_per_day=2)
    assert [limiter.claim("2026-10-04") for _ in range(3)] == [True, True, False]
    assert limiter.claim("2026-10-05") is True


def test_question_problem(config: TiresiasConfig) -> None:
    limits = config.limits
    assert question_problem("how many?", used=0, limits=limits) is None
    assert "too long" in (question_problem("x" * 501, used=0, limits=limits) or "")
    assert "limit" in (question_problem("q", used=limits.max_per_session, limits=limits) or "")


@pytest.fixture
def app_env(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("streamlit")
    monkeypatch.setenv("TIRESIAS_TEST_CONFIG", str(config_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")


def _app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=30)


def test_page_names_the_city(app_env: None) -> None:
    at = _app().run()
    assert not at.exception
    assert "Testville" in at.title[0].value


def test_answer_shows_sql_and_citations(app_env: None) -> None:
    at = _app().run()
    at.chat_input[0].set_value("how many restaurants?").run()
    assert not at.exception
    assert any("50 restaurants" in m.value for m in at.markdown)
    assert "mart_inspections" in at.code[0].value


def test_abstention_is_a_warning(app_env: None) -> None:
    at = _app().run()
    at.chat_input[0].set_value("bitcoin tomorrow?").run()
    assert "can't answer" in at.warning[0].value


def test_missing_key_stops_with_a_notice(app_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    at = _app().run()
    assert "ANTHROPIC_API_KEY" in at.info[0].value
    assert len(at.chat_input) == 0


def test_session_cap_blocks_further_questions(
    app_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TIRESIAS_MAX_PER_SESSION", "1")
    at = _app().run()
    at.chat_input[0].set_value("how many restaurants?").run()
    at.chat_input[0].set_value("and again?").run()
    assert any("session's limit" in w.value for w in at.warning)


def test_agent_cache_is_keyed_on_the_whole_config(app_env: None) -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(__file__).with_name("chat_app_two.py")), default_timeout=30)
    at.run()
    at.chat_input[0].set_value("which agent?").run()
    assert any("agent A" in m.value for m in at.markdown)
    at.session_state["use_b"] = True
    at.chat_input[0].set_value("which agent now?").run()
    assert any("agent B" in m.value for m in at.markdown)
