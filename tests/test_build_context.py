"""Unit tests for the _build_context() helper in http_api.py."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from unittest.mock import patch

from custom_components.kyber.http_api import _build_context


async def test_build_context_includes_entity_with_area(hass: HomeAssistant) -> None:
    """Entity area name should appear in the context string."""
    area = ar.async_get(hass).async_create("Kitchen")
    entry = er.async_get(hass).async_get_or_create("light", "test", "kitchen_light")
    er.async_get(hass).async_update_entity(entry.entity_id, area_id=area.id)

    # State must exist for the entity to appear in entity_lines
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Kitchen Light"})

    context = _build_context(hass)
    assert "Kitchen" in context


async def test_build_context_entity_labels_included(hass: HomeAssistant) -> None:
    """Labels assigned to an entity should appear in the context string."""
    label_reg = lr.async_get(hass)
    label_reg.async_create("outdoor")
    label_reg.async_create("security")

    entry = er.async_get(hass).async_get_or_create("sensor", "test", "door_sensor")
    er.async_get(hass).async_update_entity(
        entry.entity_id, labels={"outdoor", "security"}
    )
    hass.states.async_set(entry.entity_id, "off", {"friendly_name": "Door Sensor"})

    context = _build_context(hass)
    # Labels appear in the label registry section (label_id | name)
    assert "outdoor" in context
    assert "security" in context


async def test_build_context_empty_state_fallbacks(hass: HomeAssistant) -> None:
    """With nothing set, context should contain fallback placeholder strings."""
    context = _build_context(hass)
    assert isinstance(context, str)
    assert len(context) > 0
    assert "(no areas)" in context


async def test_build_context_automation_includes_entity_id(hass: HomeAssistant) -> None:
    """Automation entity IDs and friendly names should appear in the context."""
    hass.states.async_set(
        "automation.morning_lights",
        "on",
        attributes={"friendly_name": "Morning Lights", "id": "abc123"},
    )

    context = _build_context(hass)
    assert "automation.morning_lights" in context
    assert "Morning Lights" in context


async def test_build_context_script_included(hass: HomeAssistant) -> None:
    """Script entity IDs and friendly names should appear in the context."""
    hass.states.async_set(
        "script.good_night",
        "off",
        attributes={"friendly_name": "Good Night"},
    )

    context = _build_context(hass)
    assert "script.good_night" in context
    assert "Good Night" in context


async def test_build_context_regular_entities_listed(hass: HomeAssistant) -> None:
    """Regular (non-automation, non-script) entities should appear in the context."""
    hass.states.async_set(
        "sensor.temp",
        "22",
        attributes={"friendly_name": "Temperature"},
    )

    context = _build_context(hass)
    assert "sensor.temp" in context
    assert "Temperature" in context


async def test_build_context_compact_no_trailing_pipes_when_no_area_no_labels(
    hass: HomeAssistant,
) -> None:
    """Entities with no area and no labels should use compact 2-field format (no trailing pipes)."""
    hass.states.async_set(
        "light.living_room",
        "on",
        {"friendly_name": "Living Room Light"},
    )

    context = _build_context(hass)
    # The compact line should NOT end with trailing " |  | "
    assert "light.living_room | Living Room Light |  | " not in context
    # The line should appear in the short form
    assert "- light.living_room | Living Room Light" in context


async def test_build_context_full_format_when_area_and_labels(hass: HomeAssistant) -> None:
    """Entities with both area and labels keep the full 4-field format."""
    area = ar.async_get(hass).async_create("Bathroom")
    label_reg = lr.async_get(hass)
    label_reg.async_create("wet-room")

    entry = er.async_get(hass).async_get_or_create("light", "test", "bath_light")
    er.async_get(hass).async_update_entity(
        entry.entity_id, area_id=area.id, labels={"wet-room"}
    )
    hass.states.async_set(entry.entity_id, "off", {"friendly_name": "Bath Light"})

    context = _build_context(hass)
    assert "Bathroom" in context
    assert "wet-room" in context
    # Full 4-field line present
    assert f"- {entry.entity_id} | Bath Light | Bathroom | wet-room" in context


async def test_build_context_entity_list_truncated_at_budget(hass: HomeAssistant) -> None:
    """When the entity list exceeds MAX_ENTITY_LIST_CHARS, it should be truncated with a notice."""
    # Create enough entities to exceed the budget
    for i in range(50):
        hass.states.async_set(
            f"sensor.entity_{i:03d}",
            "on",
            {"friendly_name": f"Sensor {i:03d}"},
        )

    small_budget = 200  # tiny budget so truncation is certain to trigger
    with patch("custom_components.kyber.http_api.MAX_ENTITY_LIST_CHARS", small_budget):
        context = _build_context(hass)

    assert "context budget exceeded" in context


async def test_build_context_truncation_logs_warning(hass: HomeAssistant) -> None:
    """Truncation should emit a WARNING log message."""
    for i in range(50):
        hass.states.async_set(
            f"sensor.entity_{i:03d}",
            "on",
            {"friendly_name": f"Sensor {i:03d}"},
        )

    small_budget = 200
    with patch("custom_components.kyber.http_api.MAX_ENTITY_LIST_CHARS", small_budget):
        with patch("custom_components.kyber.http_api._LOGGER") as mock_logger:
            _build_context(hass)
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "truncated" in warning_msg
