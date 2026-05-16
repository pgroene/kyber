"""Unit tests for the _build_context() helper in http_api.py."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

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
