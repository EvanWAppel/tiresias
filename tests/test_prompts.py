"""The prompts and user-facing copy are built from the city config."""

from __future__ import annotations

from tiresias.config import TiresiasConfig
from tiresias.prompts import abstain_message, plan_system_prompt


def test_plan_prompt_names_the_city_and_its_holdings(config: TiresiasConfig) -> None:
    prompt = plan_system_prompt(config)
    assert "Testville" in prompt
    assert config.blurb in prompt
    assert "abstain" in prompt.lower()
    assert "SELECT" in prompt


def test_plan_prompt_carries_city_notes(config: TiresiasConfig) -> None:
    prompt = plan_system_prompt(config)
    for note in config.planner_notes:
        assert note in prompt


def test_plan_prompt_without_notes_has_no_notes_section(config: TiresiasConfig) -> None:
    bare = config.model_copy(update={"planner_notes": ()})
    assert "City-specific notes" not in plan_system_prompt(bare)


def test_abstain_message_names_the_city(config: TiresiasConfig) -> None:
    message = abstain_message(config)
    assert "Testville" in message
    assert config.blurb in message
    assert "guess" in message
