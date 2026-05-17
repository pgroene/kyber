"""Unit tests for the _build_context() helper in http_api.py."""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from custom_components.kyber.http_api import _build_context


async def test_build_context_returns_tuple(hass: HomeAssistant) -> None:
    """_build_context should return a (str, dict) tuple."""
    result = _build_context(hass)
    assert isinstance(result, tuple)
    assert len(result) == 2
    context, stats = result
    assert isinstance(context, str)
    assert isinstance(stats, dict)


async def test_build_context_stats_keys(hass: HomeAssistant) -> None:
    """context_stats dict should contain the expected keys."""
    _, stats = _build_context(hass)
    assert "entity_count" in stats
    assert "automation_count" in stats
    assert "area_count" in stats
    assert "lights_on" in stats
    assert "unavailable_count" in stats
    assert "low_battery_count" in stats


async def test_build_context_includes_area_name(hass: HomeAssistant) -> None:
    """Area name should appear in the context (Areas section or home state)."""
    ar.async_get(hass).async_create("Kitchen")
    context, stats = _build_context(hass)
    assert "Kitchen" in context
    assert stats["area_count"] == 1


async def test_build_context_entity_labels_included(hass: HomeAssistant) -> None:
    """Labels appear in the label registry section of the context."""
    label_reg = lr.async_get(hass)
    label_reg.async_create("outdoor")
    label_reg.async_create("security")

    entry = er.async_get(hass).async_get_or_create("sensor", "test", "door_sensor")
    er.async_get(hass).async_update_entity(entry.entity_id, labels={"outdoor", "security"})
    hass.states.async_set(entry.entity_id, "off", {"friendly_name": "Door Sensor"})

    context, _ = _build_context(hass)
    assert "outdoor" in context
    assert "security" in context


async def test_build_context_empty_state_fallbacks(hass: HomeAssistant) -> None:
    """With nothing set, context should contain fallback placeholder strings."""
    context, stats = _build_context(hass)
    assert isinstance(context, str)
    assert len(context) > 0
    assert "(no areas)" in context
    assert stats["entity_count"] == 0


async def test_build_context_automation_includes_entity_id(hass: HomeAssistant) -> None:
    """Automation entity IDs and friendly names should appear in the context."""
    hass.states.async_set(
        "automation.morning_lights",
        "on",
        attributes={"friendly_name": "Morning Lights", "id": "abc123"},
    )
    context, stats = _build_context(hass)
    assert "automation.morning_lights" in context
    assert "Morning Lights" in context
    assert stats["automation_count"] == 1


async def test_build_context_script_included(hass: HomeAssistant) -> None:
    """Script entity IDs and friendly names should appear in the context."""
    hass.states.async_set(
        "script.good_night",
        "off",
        attributes={"friendly_name": "Good Night"},
    )
    context, _ = _build_context(hass)
    assert "script.good_night" in context
    assert "Good Night" in context


async def test_build_context_regular_entities_counted(hass: HomeAssistant) -> None:
    """Regular entities should be counted in domain stats; entity_count reflects them."""
    hass.states.async_set("sensor.temp", "22", {"friendly_name": "Temperature"})
    hass.states.async_set("sensor.humidity", "55", {"friendly_name": "Humidity"})
    hass.states.async_set("light.living_room", "on", {"friendly_name": "Living Room"})

    context, stats = _build_context(hass)
    assert stats["entity_count"] == 3
    # Domain stats appear in context
    assert "sensor" in context
    assert "light" in context


async def test_build_context_entity_stats_line_present(hass: HomeAssistant) -> None:
    """Context should include a domain stats line with entity counts."""
    hass.states.async_set("light.test", "on", {"friendly_name": "Test Light"})
    hass.states.async_set("switch.test", "off", {"friendly_name": "Test Switch"})

    context, _ = _build_context(hass)
    # Stats line: "X total — domain: N | ..."
    assert "total" in context
    assert "light: 1" in context
    assert "switch: 1" in context


async def test_build_context_home_state_by_area(hass: HomeAssistant) -> None:
    """Lights on in an area should appear in the home state section."""
    area = ar.async_get(hass).async_create("Living Room")
    entry = er.async_get(hass).async_get_or_create("light", "test", "living_light")
    er.async_get(hass).async_update_entity(entry.entity_id, area_id=area.id)
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Living Room Light"})

    context, stats = _build_context(hass)
    assert "Living Room" in context
    assert stats["lights_on"] == 1


async def test_build_context_lights_on_count(hass: HomeAssistant) -> None:
    """lights_on stat should count lights with state 'on' assigned to any area."""
    area = ar.async_get(hass).async_create("Bedroom")
    for i, state in enumerate(["on", "on", "off"]):
        entry = er.async_get(hass).async_get_or_create("light", "test", f"light_{i}")
        er.async_get(hass).async_update_entity(entry.entity_id, area_id=area.id)
        hass.states.async_set(entry.entity_id, state, {})

    _, stats = _build_context(hass)
    assert stats["lights_on"] == 2
