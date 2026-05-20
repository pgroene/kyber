"""Tests for integration_explorer.py improvements.

Covers:
- Disabled/hidden entities are skipped in phase 2.
- Diagnostic/config category entities are skipped in phase 2.
- original_name alias is stored when user has renamed an entity.
- Explorer version is bumped (forces re-index of all entities).
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Minimal HA stubs required to import integration_explorer.py
# ---------------------------------------------------------------------------

def _setup_stubs():
    for mod_name in [
        "homeassistant",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.area_registry",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_registry",
    ]:
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

    for attr in ("async_get",):
        for sub in ("area_registry", "device_registry", "entity_registry"):
            mod = sys.modules[f"homeassistant.helpers.{sub}"]
            if not hasattr(mod, attr):
                setattr(mod, attr, MagicMock())


_setup_stubs()


def _load_explorer():
    # Also stub the knowledge module imported by integration_explorer
    k_stub = types.ModuleType("custom_components.kyber.knowledge")
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules.setdefault("custom_components.kyber", types.ModuleType("custom_components.kyber"))
    sys.modules["custom_components.kyber.knowledge"] = k_stub

    spec = importlib.util.spec_from_file_location(
        "custom_components.kyber.integration_explorer",
        ROOT / "custom_components" / "kyber" / "integration_explorer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sys.modules["custom_components.kyber.integration_explorer"] = mod
    return mod


_EXPLORER = _load_explorer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity_entry(
    entity_id: str,
    platform: str = "test_integration",
    disabled_by=None,
    hidden_by=None,
    entity_category=None,
    area_id=None,
    device_id=None,
    original_name: str | None = None,
    name: str | None = None,
) -> MagicMock:
    e = MagicMock()
    e.entity_id = entity_id
    e.platform = platform
    e.disabled_by = disabled_by
    e.hidden_by = hidden_by
    e.entity_category = entity_category
    e.area_id = area_id
    e.device_id = device_id
    e.original_name = original_name
    e.name = name
    e.device_class = None
    return e


def _make_hass(states: dict[str, str] | None = None) -> MagicMock:
    """Build a minimal hass mock."""
    hass = MagicMock()
    hass.data = {}
    hass.services.async_services.return_value = {}

    state_map: dict[str, MagicMock] = {}
    for eid, state_val in (states or {}).items():
        s = MagicMock()
        s.state = state_val
        s.attributes = {"friendly_name": eid.split(".")[-1].replace("_", " ").title()}
        state_map[eid] = s

    def _get_state(eid):
        return state_map.get(eid)

    hass.states.get = _get_state
    return hass


def _make_entity_reg(entries: list[MagicMock]) -> MagicMock:
    reg = MagicMock()
    reg.entities = {e.entity_id: e for e in entries}
    return reg


def _make_kstore() -> tuple[MagicMock, list[dict]]:
    added: list[dict] = []
    kstore = MagicMock()
    kstore._entries = {}

    async def _add(category, content, *, subject=None, tags=None,
                   source=None, confidence=None, _save=True, **kwargs):
        added.append({
            "category": category,
            "content": content,
            "subject": subject,
            "tags": tags or [],
            "source": source,
        })

    kstore.async_add = _add
    kstore.async_load = AsyncMock()
    kstore.async_force_save = AsyncMock()
    return kstore, added


def _make_area_reg() -> MagicMock:
    reg = MagicMock()
    reg.async_get_area = lambda _: None
    return reg


# Patch area_registry.async_get to return our mock area reg
import homeassistant.helpers.area_registry as _ar_mod
import homeassistant.helpers.device_registry as _dr_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPhase2SkipsDisabledEntities:
    """Disabled and hidden entities must not be indexed."""

    @pytest.mark.asyncio
    async def test_disabled_entity_is_skipped(self):
        entry = _make_entity_entry("switch.broken", disabled_by="user")
        hass = _make_hass()
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        entity_ids_indexed = {a["subject"] for a in added}
        assert "switch.broken" not in entity_ids_indexed

    @pytest.mark.asyncio
    async def test_hidden_entity_is_skipped(self):
        entry = _make_entity_entry("sensor.internal", hidden_by="integration")
        hass = _make_hass()
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        entity_ids_indexed = {a["subject"] for a in added}
        assert "sensor.internal" not in entity_ids_indexed

    @pytest.mark.asyncio
    async def test_non_disabled_entity_is_indexed(self):
        entry = _make_entity_entry("light.living_room", disabled_by=None, hidden_by=None)
        hass = _make_hass({"light.living_room": "on"})
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        entity_ids_indexed = {a["subject"] for a in added}
        assert "light.living_room" in entity_ids_indexed


class TestPhase2SkipsDiagnosticEntities:
    """Diagnostic and config category entities must not be indexed."""

    @pytest.mark.asyncio
    async def test_diagnostic_category_skipped(self):
        entry = _make_entity_entry("sensor.hub_battery", entity_category="diagnostic")
        hass = _make_hass({"sensor.hub_battery": "87"})
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        entity_ids_indexed = {a["subject"] for a in added}
        assert "sensor.hub_battery" not in entity_ids_indexed

    @pytest.mark.asyncio
    async def test_config_category_skipped(self):
        entry = _make_entity_entry("number.thermostat_target", entity_category="config")
        hass = _make_hass({"number.thermostat_target": "21"})
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        entity_ids_indexed = {a["subject"] for a in added}
        assert "number.thermostat_target" not in entity_ids_indexed

    @pytest.mark.asyncio
    async def test_no_category_entity_is_indexed(self):
        entry = _make_entity_entry("switch.desk_lamp", entity_category=None)
        hass = _make_hass({"switch.desk_lamp": "off"})
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        entity_ids_indexed = {a["subject"] for a in added}
        assert "switch.desk_lamp" in entity_ids_indexed


class TestOriginalNameAlias:
    """When a user renames an entity, the original integration name is stored as alias."""

    @pytest.mark.asyncio
    async def test_original_name_alias_stored(self):
        entry = _make_entity_entry(
            "switch.home_connect_dishwasher_start",
            name="Start",                          # user's chosen name
            original_name="Dishwasher Start",      # integration's original name
        )
        hass = _make_hass({"switch.home_connect_dishwasher_start": "off"})
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        alias_entries = [a for a in added if a["category"] == "entity_alias"]
        assert alias_entries, "No entity_alias entry written for renamed entity"
        alias = alias_entries[0]
        assert alias["subject"] == "Dishwasher Start"
        assert alias["content"] == "switch.home_connect_dishwasher_start"
        assert "original_name" in alias["tags"]

    @pytest.mark.asyncio
    async def test_no_alias_when_name_unchanged(self):
        """When entity has no user rename, no alias entry should be written."""
        entry = _make_entity_entry(
            "light.ceiling",
            name=None,           # user never set a custom name
            original_name=None,
        )
        hass = _make_hass({"light.ceiling": "on"})
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        alias_entries = [a for a in added if a["category"] == "entity_alias"
                         and "original_name" in (a.get("tags") or [])]
        assert not alias_entries, "Unexpected alias for unmodified entity"

    @pytest.mark.asyncio
    async def test_no_alias_when_name_same_as_original(self):
        """When user name equals original name, no alias should be written."""
        entry = _make_entity_entry(
            "light.bedroom",
            name="Bedroom Ceiling",
            original_name="Bedroom Ceiling",  # same
        )
        hass = _make_hass({"light.bedroom": "off"})
        entity_reg = _make_entity_reg([entry])
        kstore, added = _make_kstore()
        _ar_mod.async_get = lambda _h: _make_area_reg()
        _dr_mod.async_get = lambda _h: MagicMock()

        await _EXPLORER.async_startup_explore_all(hass, kstore, entity_reg)

        alias_entries = [a for a in added if a["category"] == "entity_alias"
                         and "original_name" in (a.get("tags") or [])]
        assert not alias_entries


class TestExplorerVersion:
    """The explorer version must be ≥ 5 (bumped for this release)."""

    def test_explorer_version_bumped(self):
        assert _EXPLORER._EXPLORER_VERSION >= 5, (
            f"_EXPLORER_VERSION should be ≥ 5 after filtering changes, got {_EXPLORER._EXPLORER_VERSION}"
        )

    def test_explorer_version_tag_matches(self):
        assert _EXPLORER._EXPLORER_VERSION_TAG == f"explorer-v{_EXPLORER._EXPLORER_VERSION}"
