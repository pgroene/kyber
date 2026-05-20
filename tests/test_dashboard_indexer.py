"""Unit tests for dashboard_indexer.async_store_dashboard_labels.

Covers:
- Area-name-only labels are skipped (not stored)
- Very short labels are skipped
- Proper entity_alias entry: subject=label, content=entity_id
- Proper general entry: semantic description using domain
- www mirror behaves identically
"""
from __future__ import annotations

import sys
import types
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ── HA + dependency stubs ─────────────────────────────────────────────────────
_STUBS = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.helpers",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.label_registry",
    "homeassistant.helpers.template",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.config",
    "homeassistant.loader",
    "aiohttp",
    "aiohttp.web",
]
for _m in _STUBS:
    sys.modules.setdefault(_m, types.ModuleType(_m))
sys.modules["aiohttp"].web = types.ModuleType("aiohttp.web")


class _Stub:
    pass


sys.modules["homeassistant.components.http"].HomeAssistantView = _Stub
sys.modules["homeassistant.core"].HomeAssistant = _Stub
sys.modules["homeassistant.core"].callback = lambda f: f
sys.modules["homeassistant.helpers.storage"].Store = _Stub
sys.modules["homeassistant.exceptions"].HomeAssistantError = type(
    "HomeAssistantError", (Exception,), {}
)
sys.modules["homeassistant.helpers"].area_registry = sys.modules[
    "homeassistant.helpers.area_registry"
]
sys.modules["homeassistant.helpers"].entity_registry = sys.modules[
    "homeassistant.helpers.entity_registry"
]

# ── Load the module under test ────────────────────────────────────────────────
_SRC = (
    Path(__file__).parent.parent
    / "custom_components"
    / "kyber"
    / "dashboard_indexer.py"
)

spec = importlib.util.spec_from_file_location("dashboard_indexer", _SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

async_store_dashboard_labels = mod.async_store_dashboard_labels


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_area(name: str) -> MagicMock:
    a = MagicMock()
    a.name = name
    a.id = name.lower()
    return a


def _make_entity_entry(area_id: str | None = None) -> MagicMock:
    e = MagicMock()
    e.area_id = area_id
    return e


def _make_hass(names: dict[str, str], areas=(), entity_areas=None) -> MagicMock:
    """Build a minimal hass mock with area/entity registry stubs."""
    area_mocks = [_make_area(a) for a in areas]
    entity_areas = entity_areas or {}

    area_reg = MagicMock()
    area_reg.async_list_areas.return_value = area_mocks
    area_reg.async_get_area = lambda aid: next(
        (a for a in area_mocks if a.id == aid), None
    )

    entity_reg = MagicMock()
    entity_reg.async_get = lambda eid: _make_entity_entry(entity_areas.get(eid))

    hass = MagicMock()
    hass.data = {}

    # Patch the registry imports inside the module function
    import homeassistant.helpers.area_registry as ar_mod
    import homeassistant.helpers.entity_registry as er_mod
    ar_mod.async_get = lambda _hass: area_reg
    er_mod.async_get = lambda _hass: entity_reg

    return hass, names


def _make_kstore() -> MagicMock:
    """Return a mock knowledge store that tracks async_add calls."""
    kstore = MagicMock()
    kstore._entries = {}
    kstore.async_load = AsyncMock()
    kstore.async_delete = AsyncMock()
    kstore.async_force_save = AsyncMock()

    added: list[dict] = []

    async def _add(category, content, *, subject=None, tags=None,
                   source=None, confidence=None, provenance=None, _save=True):
        added.append({
            "category": category,
            "content": content,
            "subject": subject,
            "tags": tags or [],
            "source": source,
        })

    kstore.async_add = _add
    kstore._added = added
    return kstore


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_area_name_label_is_skipped():
    """Labels that are just an area name should not be stored."""
    names = {
        "sensor.rollerblind_0001_battery": "Werkkamer",
        "switch.0xa4c138ee65f45d6b": "Werkkamer monitors and docks",
    }
    hass, _ = _make_hass(names, areas=["Werkkamer"])
    kstore = _make_kstore()

    with patch.object(mod, "get_dashboard_entity_names", return_value=names):
        count = await async_store_dashboard_labels(hass, kstore)

    assert count == 1
    subjects = [e["subject"] for e in kstore._added]
    # battery sensor with area-name label should NOT appear
    assert "werkkamer" not in subjects
    # the switch label SHOULD appear as entity_alias subject
    assert "werkkamer monitors and docks" in subjects


@pytest.mark.asyncio
async def test_short_label_is_skipped():
    """Labels shorter than 3 chars should not be stored."""
    names = {"switch.abc": "Fan", "switch.def": "AB"}
    hass, _ = _make_hass(names)
    kstore = _make_kstore()

    with patch.object(mod, "get_dashboard_entity_names", return_value=names):
        count = await async_store_dashboard_labels(hass, kstore)

    assert count == 1
    subjects = [e["subject"] for e in kstore._added]
    assert "fan" in subjects
    assert "ab" not in subjects and "AB" not in subjects


@pytest.mark.asyncio
async def test_entity_alias_format():
    """entity_alias entry must use label as subject and entity_id as content."""
    names = {"switch.0xa4c138ee65f45d6b": "Werkkamer monitors and docks"}
    hass, _ = _make_hass(names, areas=["Slaapkamer"])
    kstore = _make_kstore()

    with patch.object(mod, "get_dashboard_entity_names", return_value=names):
        await async_store_dashboard_labels(hass, kstore)

    alias_entries = [e for e in kstore._added if e["category"] == "entity_alias"]
    assert alias_entries, "No entity_alias entry written"
    entry = alias_entries[0]
    assert entry["subject"] == "werkkamer monitors and docks"
    assert entry["content"] == "switch.0xa4c138ee65f45d6b"


@pytest.mark.asyncio
async def test_general_entry_uses_domain_phrase():
    """general entry must include domain-specific phrase in content."""
    names = {"switch.monitors_dock": "Monitors and dock"}
    hass, _ = _make_hass(names)
    kstore = _make_kstore()

    with patch.object(mod, "get_dashboard_entity_names", return_value=names):
        await async_store_dashboard_labels(hass, kstore)

    general_entries = [e for e in kstore._added if e["category"] == "general"]
    assert general_entries, "No general entry written"
    content = general_entries[0]["content"]
    assert "switch" in content.lower() or "on/off" in content.lower()
    assert "switch.monitors_dock" in content
    assert "Monitors and dock" in content


@pytest.mark.asyncio
async def test_general_entry_includes_area():
    """general entry should include area name when entity is in an area."""
    names = {"light.bedroom_main": "Slaapkamer light"}
    hass, _ = _make_hass(
        names,
        areas=["Slaapkamer"],
        entity_areas={"light.bedroom_main": "slaapkamer"},
    )
    kstore = _make_kstore()

    with patch.object(mod, "get_dashboard_entity_names", return_value=names):
        await async_store_dashboard_labels(hass, kstore)

    general_entries = [e for e in kstore._added if e["category"] == "general"]
    assert general_entries
    content = general_entries[0]["content"]
    assert "Slaapkamer" in content


@pytest.mark.asyncio
async def test_both_entries_written_per_label():
    """Each valid label should produce exactly one entity_alias + one general entry."""
    names = {
        "switch.a": "My Switch",
        "sensor.b": "My Sensor",
    }
    hass, _ = _make_hass(names)
    kstore = _make_kstore()

    with patch.object(mod, "get_dashboard_entity_names", return_value=names):
        count = await async_store_dashboard_labels(hass, kstore)

    assert count == 2
    categories = [e["category"] for e in kstore._added]
    assert categories.count("entity_alias") == 2
    assert categories.count("general") == 2


@pytest.mark.asyncio
async def test_empty_names_returns_zero():
    """When no named dashboard entities exist, return 0 and write nothing."""
    hass, _ = _make_hass({})
    kstore = _make_kstore()

    with patch.object(mod, "get_dashboard_entity_names", return_value={}):
        count = await async_store_dashboard_labels(hass, kstore)

    assert count == 0
    assert kstore._added == []
