"""Unit tests for pure helper functions in custom_components.kyber.http_api.

These functions have no HA dependencies and can be tested without fixtures.
Covered:
  - _extract_yaml_blocks
  - _extract_plan_block
  - _build_service_undo
"""
from unittest.mock import MagicMock

import pytest

from custom_components.kyber.http_api import (
    _build_service_undo,
    _extract_plan_block,
    _extract_yaml_blocks,
)


# ──────────────────────────────────────────────────────────────────────────────
# _extract_yaml_blocks
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_yaml_blocks_single():
    """A single ```yaml block should be extracted."""
    text = "Sure!\n```yaml\nalias: test\ntrigger: []\n```\nDone."
    blocks = _extract_yaml_blocks(text)
    assert len(blocks) == 1
    assert "alias: test" in blocks[0]
    assert "trigger: []" in blocks[0]


def test_extract_yaml_blocks_multiple():
    """Multiple ```yaml blocks should all be extracted in order."""
    text = (
        "First:\n```yaml\nalias: a\n```\n"
        "Second:\n```yaml\nalias: b\n```"
    )
    blocks = _extract_yaml_blocks(text)
    assert len(blocks) == 2
    assert "alias: a" in blocks[0]
    assert "alias: b" in blocks[1]


def test_extract_yaml_blocks_none():
    """A response with no yaml blocks should return an empty list."""
    text = "This is just plain text without any code blocks."
    blocks = _extract_yaml_blocks(text)
    assert blocks == []


def test_extract_yaml_blocks_case_insensitive():
    """```YAML (uppercase) should also be matched."""
    text = "```YAML\nalias: test\n```"
    blocks = _extract_yaml_blocks(text)
    assert len(blocks) == 1
    assert "alias: test" in blocks[0]


def test_extract_yaml_blocks_strips_surrounding_whitespace():
    """Extra newlines around block content should be stripped."""
    text = "```yaml\n\nalias: test\n\n```"
    blocks = _extract_yaml_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].strip() == "alias: test"


# ──────────────────────────────────────────────────────────────────────────────
# _extract_plan_block
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_plan_block_valid():
    """A valid ```plan JSON block should be parsed and returned as a dict."""
    plan_json = '{"overview": "Rename lights", "actions": []}'
    text = f"Here is my plan:\n```plan\n{plan_json}\n```"
    result = _extract_plan_block(text)
    assert result is not None
    assert result["overview"] == "Rename lights"
    assert result["actions"] == []


def test_extract_plan_block_with_actions():
    """Plan block with action entries should be fully parsed."""
    plan_json = (
        '{"overview": "Assign area", "actions": ['
        '{"type": "assign_area", "entity_id": "light.desk", "area_id": "office"}'
        ']}'
    )
    text = f"```plan\n{plan_json}\n```"
    result = _extract_plan_block(text)
    assert result is not None
    assert result["actions"][0]["type"] == "assign_area"


def test_extract_plan_block_no_block():
    """When no ```plan block is present, should return None."""
    text = "This response has no plan block, just text."
    result = _extract_plan_block(text)
    assert result is None


def test_extract_plan_block_invalid_json():
    """A ```plan block with invalid JSON should return None (not raise)."""
    text = "```plan\n{broken json here\n```"
    result = _extract_plan_block(text)
    assert result is None


def test_extract_plan_block_only_first_block():
    """When multiple plan blocks are present, only the first should be returned."""
    plan1 = '{"overview": "First plan"}'
    plan2 = '{"overview": "Second plan"}'
    text = f"```plan\n{plan1}\n```\n```plan\n{plan2}\n```"
    result = _extract_plan_block(text)
    assert result["overview"] == "First plan"


# ──────────────────────────────────────────────────────────────────────────────
# _build_service_undo
# ──────────────────────────────────────────────────────────────────────────────

def _mock_state(state: str, attributes: dict = None) -> MagicMock:
    s = MagicMock()
    s.state = state
    s.attributes = attributes or {}
    return s


def test_build_service_undo_turn_off_light_on():
    """Turning off an ON light should produce a turn_on undo action."""
    pre_state = _mock_state("on", {"brightness": 200, "color_temp": 300})
    undo = _build_service_undo("light", "turn_off", "light.desk", pre_state)
    assert undo is not None
    assert undo["service"] == "turn_on"
    assert undo["domain"] == "light"
    assert undo["entity_id"] == "light.desk"
    assert undo["service_data"]["brightness"] == 200
    assert undo["service_data"]["color_temp"] == 300


def test_build_service_undo_turn_on_light_off():
    """Turning on an OFF light should produce a turn_off undo action."""
    pre_state = _mock_state("off")
    undo = _build_service_undo("light", "turn_on", "light.desk", pre_state)
    assert undo is not None
    assert undo["service"] == "turn_off"


def test_build_service_undo_toggle_on():
    """Toggling an ON entity should produce a turn_off undo."""
    pre_state = _mock_state("on")
    undo = _build_service_undo("switch", "toggle", "switch.fan", pre_state)
    assert undo is not None
    assert undo["service"] == "turn_on"


def test_build_service_undo_toggle_off():
    """Toggling an OFF entity should produce a turn_on undo."""
    pre_state = _mock_state("off")
    undo = _build_service_undo("switch", "toggle", "switch.fan", pre_state)
    assert undo is not None
    assert undo["service"] == "turn_off"


def test_build_service_undo_climate_set_temperature():
    """set_temperature should produce an undo restoring the old temperature."""
    pre_state = _mock_state("heat", {"temperature": 19.0})
    undo = _build_service_undo("climate", "set_temperature", "climate.living_room", pre_state)
    assert undo is not None
    assert undo["service"] == "set_temperature"
    assert undo["service_data"]["temperature"] == 19.0


def test_build_service_undo_climate_set_hvac_mode():
    """set_hvac_mode should produce an undo restoring the old HVAC mode."""
    pre_state = _mock_state("cool", {"hvac_mode": "cool"})
    undo = _build_service_undo("climate", "set_hvac_mode", "climate.living_room", pre_state)
    assert undo is not None
    assert undo["service_data"]["hvac_mode"] == "cool"


def test_build_service_undo_cover_set_position():
    """set_cover_position should produce an undo restoring the old position."""
    pre_state = _mock_state("open", {"current_position": 75})
    undo = _build_service_undo("cover", "set_cover_position", "cover.blind", pre_state)
    assert undo is not None
    assert undo["service_data"]["position"] == 75


def test_build_service_undo_media_player_volume():
    """volume_set should produce an undo restoring the old volume."""
    pre_state = _mock_state("playing", {"volume_level": 0.5})
    undo = _build_service_undo("media_player", "volume_set", "media_player.tv", pre_state)
    assert undo is not None
    assert undo["service_data"]["volume_level"] == 0.5


def test_build_service_undo_unknown_service_returns_none():
    """An unknown service with no known undo mapping should return None."""
    pre_state = _mock_state("on")
    undo = _build_service_undo("input_boolean", "toggle", "input_boolean.test", pre_state)
    # input_boolean toggle: state is 'on' so toggle → turn_off, which IS handled
    # Test a genuinely unknown domain/service combo
    undo = _build_service_undo("custom_domain", "custom_service", "sensor.test", pre_state)
    assert undo is None


def test_build_service_undo_no_pre_state_returns_none():
    """When pre_state is None (entity not in states), should return None."""
    undo = _build_service_undo("light", "turn_off", "light.unknown", None)
    assert undo is None


def test_build_service_undo_no_entity_id_returns_none():
    """When entity_id is empty, should return None."""
    undo = _build_service_undo("light", "turn_off", "", MagicMock())
    assert undo is None
