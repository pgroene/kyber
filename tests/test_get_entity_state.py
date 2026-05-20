"""Unit tests for _execute_tool / get_entity_state.

Regression coverage for:
  - GH bug: media_player attributes containing datetime objects
    (e.g. media_position_updated_at) caused json.JSONDecodeError /
    TypeError: Object of type datetime is not JSON serializable, resulting
    in the AI receiving an exception instead of the entity state.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

# ── HA + dependency stubs ──────────────────────────────────────────────────────
_STUBS = [
    "homeassistant", "homeassistant.core", "homeassistant.components",
    "homeassistant.components.http", "homeassistant.helpers",
    "homeassistant.helpers.storage", "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry",
    "homeassistant.helpers.label_registry", "homeassistant.helpers.template",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.const", "homeassistant.exceptions",
    "homeassistant.util", "homeassistant.util.dt",
    "homeassistant.config", "homeassistant.loader",
    "aiohttp", "aiohttp.web",
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
sys.modules["homeassistant.helpers"].label_registry = sys.modules[
    "homeassistant.helpers.label_registry"
]
sys.modules["homeassistant.helpers"].device_registry = sys.modules[
    "homeassistant.helpers.device_registry"
]
for _r in ("entity_registry", "area_registry", "device_registry", "label_registry"):
    sys.modules[f"homeassistant.helpers.{_r}"].async_get = lambda *a, **k: None
sys.modules.setdefault(
    "homeassistant.components.ai_task",
    types.ModuleType("homeassistant.components.ai_task"),
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_pkg_cc = types.ModuleType("custom_components")
_pkg_cc.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _pkg_cc)

_pkg_kyber = types.ModuleType("custom_components.kyber")
_pkg_kyber.__path__ = [str(ROOT / "custom_components" / "kyber")]
sys.modules["custom_components.kyber"] = _pkg_kyber


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.kyber.const", ROOT / "custom_components" / "kyber" / "const.py")
_load("custom_components.kyber.knowledge", ROOT / "custom_components" / "kyber" / "knowledge.py")
_load("custom_components.kyber.analyzer", ROOT / "custom_components" / "kyber" / "analyzer.py")
_load("custom_components.kyber.source", ROOT / "custom_components" / "kyber" / "source.py")
_load("custom_components.kyber.domain_docs", ROOT / "custom_components" / "kyber" / "domain_docs.py")
tool_execution = _load(
    "custom_components.kyber.tool_execution",
    ROOT / "custom_components" / "kyber" / "tool_execution.py",
)
_execute_tool = tool_execution._execute_tool


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_hass(entity_id: str, state_str: str, attributes: dict) -> MagicMock:
    """Return a minimal hass mock with one entity in states."""
    state = MagicMock()
    state.entity_id = entity_id
    state.state = state_str
    state.attributes = attributes

    hass = MagicMock()
    hass.states.get = lambda eid: state if eid == entity_id else None
    hass.states.async_all = lambda: [state]

    # Registries return None (no area / entry overrides needed for these tests)
    area_reg = MagicMock()
    area_reg.async_get_area = lambda _: None
    entity_reg = MagicMock()
    entity_reg.async_get = lambda _: None
    label_reg = MagicMock()
    label_reg.async_list_entries = lambda: []

    sys.modules["homeassistant.helpers.area_registry"].async_get = lambda _h: area_reg
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda _h: entity_reg
    sys.modules["homeassistant.helpers.label_registry"].async_get = lambda _h: label_reg

    return hass


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestGetEntityStateDatetimeSerialization:
    """Regression tests: datetime attributes must not crash get_entity_state."""

    def test_datetime_attribute_is_serialized(self):
        """media_position_updated_at is a datetime — must not raise TypeError."""
        dt = datetime(2026, 5, 20, 16, 6, 54, tzinfo=timezone.utc)
        hass = _make_hass(
            "media_player.werkkamer_music_2",
            "playing",
            {
                "friendly_name": "Werkkamer Music 2",
                "media_title": "Some Song",
                "media_position_updated_at": dt,   # <-- the culprit
                "volume_level": 0.4,
            },
        )
        result = _execute_tool(hass, {
            "name": "get_entity_state",
            "entity_id": "media_player.werkkamer_music_2",
        })
        # Must be valid JSON — no TypeError
        data = json.loads(result)
        assert data["entity_id"] == "media_player.werkkamer_music_2"
        assert data["state"] == "playing"
        # datetime must be serialized as an ISO string, not drop or crash
        assert isinstance(data["attributes"]["media_position_updated_at"], str)
        assert "2026-05-20" in data["attributes"]["media_position_updated_at"]

    def test_multiple_datetime_attributes(self):
        """Multiple datetime attributes in one entity all serialize cleanly."""
        dt1 = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
        dt2 = datetime(2026, 5, 20, 11, 0, 0, tzinfo=timezone.utc)
        hass = _make_hass(
            "media_player.test",
            "idle",
            {
                "friendly_name": "Test Player",
                "media_position_updated_at": dt1,
                "last_changed": dt2,
            },
        )
        result = _execute_tool(hass, {
            "name": "get_entity_state",
            "entity_id": "media_player.test",
        })
        data = json.loads(result)
        assert isinstance(data["attributes"]["media_position_updated_at"], str)
        assert isinstance(data["attributes"]["last_changed"], str)

    def test_datetime_in_fields_request(self):
        """When fields= is used, datetime attributes requested explicitly must serialize."""
        dt = datetime(2026, 5, 20, 16, 0, 0, tzinfo=timezone.utc)
        hass = _make_hass(
            "media_player.test",
            "playing",
            {
                "friendly_name": "Test",
                "media_position_updated_at": dt,
                "volume_level": 0.5,
            },
        )
        result = _execute_tool(hass, {
            "name": "get_entity_state",
            "entity_id": "media_player.test",
            "fields": ["state", "media_position_updated_at"],
        })
        data = json.loads(result)
        assert data["state"] == "playing"
        assert isinstance(data["media_position_updated_at"], str)

    def test_normal_attributes_unaffected(self):
        """Plain string/int/float/bool attributes must still work correctly."""
        hass = _make_hass(
            "light.kitchen",
            "on",
            {
                "friendly_name": "Kitchen Light",
                "brightness": 200,
                "color_temp": 4000,
                "rgb_color": [255, 200, 100],
            },
        )
        result = _execute_tool(hass, {
            "name": "get_entity_state",
            "entity_id": "light.kitchen",
        })
        data = json.loads(result)
        assert data["state"] == "on"
        assert data["attributes"]["brightness"] == 200

    def test_entity_not_found_returns_error_json(self):
        """Unknown entity_id returns a JSON error dict, not an exception."""
        hass = _make_hass("light.known", "on", {"friendly_name": "Known"})
        result = _execute_tool(hass, {
            "name": "get_entity_state",
            "entity_id": "light.unknown",
        })
        data = json.loads(result)
        assert "error" in data
