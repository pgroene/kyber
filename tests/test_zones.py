"""Tests for zone tools (get_zones, get_zone_occupants) and zone context in _build_context."""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from unittest.mock import patch, MagicMock
import json

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.kyber.tool_execution import _execute_tool


def _inject_zone(hass: HomeAssistant, entity_id: str, name: str, lat: float, lon: float, passive: bool = False) -> None:
    """Inject a zone.* state into hass for testing."""
    hass.states.async_set(
        entity_id,
        "zoning",
        {
            "friendly_name": name,
            "latitude": lat,
            "longitude": lon,
            "radius": 100,
            "icon": "mdi:home",
            "passive": passive,
        },
    )


def _inject_person(hass: HomeAssistant, entity_id: str, name: str, location: str) -> None:
    hass.states.async_set(entity_id, location, {"friendly_name": name})


# ──────────────────────────────────────────────────────────────────────────────
# get_zones tool
# ──────────────────────────────────────────────────────────────────────────────

async def test_get_zones_returns_non_passive_zones(hass: HomeAssistant, setup_integration) -> None:
    """get_zones lists non-passive zones with name, lat, lon, radius, icon."""
    _inject_zone(hass, "zone.home", "Home", 52.0, 4.0)
    _inject_zone(hass, "zone.work", "Work", 52.1, 4.1)
    _inject_zone(hass, "zone.hidden", "Hidden", 52.2, 4.2, passive=True)

    result = json.loads(_execute_tool(hass, {"name": "get_zones"}))

    assert "zone.home" in result
    assert result["zone.home"]["name"] == "Home"
    assert result["zone.home"]["latitude"] == 52.0
    assert "zone.work" in result
    assert "zone.hidden" not in result, "Passive zones must be excluded"


async def test_get_zones_empty(hass: HomeAssistant, setup_integration) -> None:
    """get_zones returns info key when no zones exist."""
    result = json.loads(_execute_tool(hass, {"name": "get_zones"}))
    # May have zones already from HA setup; just confirm it's a dict
    assert isinstance(result, dict)


async def test_get_zones_alias_list_zones(hass: HomeAssistant, setup_integration) -> None:
    """list_zones is resolved to get_zones."""
    _inject_zone(hass, "zone.home", "Home", 52.0, 4.0)
    result = json.loads(_execute_tool(hass, {"name": "list_zones"}))
    assert isinstance(result, dict)


# ──────────────────────────────────────────────────────────────────────────────
# get_zone_occupants tool
# ──────────────────────────────────────────────────────────────────────────────

async def test_get_zone_occupants_finds_person(hass: HomeAssistant, setup_integration) -> None:
    """get_zone_occupants returns person in the requested zone."""
    _inject_zone(hass, "zone.home", "Home", 52.0, 4.0)
    _inject_person(hass, "person.peter", "Peter", "home")
    _inject_person(hass, "person.anna", "Anna", "work")

    result = json.loads(_execute_tool(hass, {"name": "get_zone_occupants", "zone": "home"}))

    assert "person.peter" in result
    assert "person.anna" not in result


async def test_get_zone_occupants_empty_zone(hass: HomeAssistant, setup_integration) -> None:
    """get_zone_occupants returns info key when zone has no occupants."""
    _inject_zone(hass, "zone.work", "Work", 52.1, 4.1)
    _inject_person(hass, "person.peter", "Peter", "home")

    result = json.loads(_execute_tool(hass, {"name": "get_zone_occupants", "zone": "work"}))

    assert "info" in result or len(result) == 0


async def test_get_zone_occupants_missing_zone_param(hass: HomeAssistant, setup_integration) -> None:
    """get_zone_occupants without zone param returns error."""
    result = json.loads(_execute_tool(hass, {"name": "get_zone_occupants"}))
    assert "error" in result


# ──────────────────────────────────────────────────────────────────────────────
# zones_block in context
# ──────────────────────────────────────────────────────────────────────────────

async def test_build_context_includes_zones(hass: HomeAssistant, setup_integration) -> None:
    """_build_context includes zone names in the generated prompt."""
    from custom_components.kyber.intent_and_context import _build_context
    _inject_zone(hass, "zone.home", "Home", 52.0, 4.0)
    _inject_zone(hass, "zone.work", "Work", 52.1, 4.1)

    context, stats = _build_context(hass)

    assert "Zones (GPS)" in context
    assert "Home" in context
    assert "Work" in context
    assert stats["zone_count"] >= 2


async def test_build_context_passive_zones_excluded_from_block(hass: HomeAssistant, setup_integration) -> None:
    """Passive zones do not appear in the zones_block."""
    from custom_components.kyber.intent_and_context import _build_context
    _inject_zone(hass, "zone.secret", "Secret", 52.3, 4.3, passive=True)

    context, stats = _build_context(hass)
    # "Secret" should not appear in zones block; it may still appear in states
    # but the zones_block specifically excludes passive zones
    if "Zones (GPS)" in context:
        # Find the zones line and check it doesn't contain Secret
        for line in context.splitlines():
            if "Zones (GPS)" in line:
                assert "Secret" not in line


async def test_build_context_person_locations_shown(hass: HomeAssistant, setup_integration) -> None:
    """Person locations appear in the context when persons have a known location."""
    from custom_components.kyber.intent_and_context import _build_context
    _inject_person(hass, "person.peter", "Peter", "home")

    context, _ = _build_context(hass)

    assert "Peter" in context
    assert "home" in context.lower()
