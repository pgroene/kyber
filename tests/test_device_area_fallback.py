"""Tests for device-inherited area_id fallback in get_area_entities and related tools.

Regression coverage for:
  - get_area_entities: entities assigned to an area via their device (not directly)
    were silently excluded, making the AI think lights/devices were not in the area.
  - list_entities_without_area: same entities appeared here as "no area" even though
    they had an effective area via their device.
  - _build_home_state_by_area: same entities excluded from per-area stats.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kyber.tool_execution import _execute_tool


@pytest.fixture
async def area_device_entity(hass: HomeAssistant):
    """Create an area, a device in that area, and an entity whose area is set via the device."""
    area = ar.async_get(hass).async_create("Woonkamer")

    config_entry = MockConfigEntry(domain="test", entry_id="fake_entry_001")
    config_entry.add_to_hass(hass)

    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "device_001")},
        name="Woonkamer Lamp",
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)

    entry = er.async_get(hass).async_get_or_create("light", "test", "woonkamer_lamp")
    er.async_get(hass).async_update_entity(
        entry.entity_id,
        device_id=device.id,
        # NOTE: area_id is NOT set directly — inherited from device
    )
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Woonkamer Lamp"})
    return area, device, entry


async def test_get_area_entities_finds_device_area_entities(hass, area_device_entity):
    """get_area_entities must include entities whose area comes from their device."""
    area, _device, entry = area_device_entity
    result = json.loads(_execute_tool(hass, {"name": "get_area_entities", "area": "Woonkamer"}))
    assert "entities" in result
    assert entry.entity_id in result["entities"], (
        "Entity assigned to area via device should appear in get_area_entities"
    )


async def test_get_area_entities_by_area_id(hass, area_device_entity):
    """get_area_entities must also work when called with the area ID."""
    area, _device, entry = area_device_entity
    result = json.loads(_execute_tool(hass, {"name": "get_area_entities", "area": area.id}))
    assert entry.entity_id in result["entities"]


async def test_list_entities_without_area_excludes_device_area_entities(hass, area_device_entity):
    """Entities with device-inherited area must NOT appear in list_entities_without_area."""
    _area, _device, entry = area_device_entity
    result = json.loads(_execute_tool(hass, {"name": "list_entities_without_area"}))
    assert entry.entity_id not in result, (
        "Entity with device-inherited area should NOT appear in list_entities_without_area"
    )


async def test_get_entity_state_reports_area(hass, area_device_entity):
    """get_entity_state should report the area when inherited from device."""
    area, _device, entry = area_device_entity
    result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": entry.entity_id}))
    assert result.get("area_name") == "Woonkamer"
    assert result.get("area_id") == area.id


async def test_directly_assigned_area_still_works(hass):
    """Entities with a directly assigned area_id must still be found correctly."""
    area = ar.async_get(hass).async_create("Keuken")
    entry = er.async_get(hass).async_get_or_create("light", "test", "keuken_lamp")
    er.async_get(hass).async_update_entity(entry.entity_id, area_id=area.id)
    hass.states.async_set(entry.entity_id, "off", {"friendly_name": "Keuken Lamp"})

    result = json.loads(_execute_tool(hass, {"name": "get_area_entities", "area": "Keuken"}))
    assert entry.entity_id in result["entities"]
