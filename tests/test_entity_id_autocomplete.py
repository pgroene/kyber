"""Unit tests for entity_id auto-complete in get_entity_state tool.

Regression coverage:
  - AI guesses entity_id "sun" instead of "sun.sun" (domain-only, no dot).
  - Backend should auto-resolve "sun" → "sun.sun" instead of returning error.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

# ── HA + aiohttp stubs ────────────────────────────────────────────────────────
_STUBS = [
    "homeassistant", "homeassistant.core", "homeassistant.components",
    "homeassistant.components.http", "homeassistant.helpers",
    "homeassistant.helpers.storage", "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry",
    "homeassistant.helpers.label_registry", "homeassistant.helpers.template",
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
sys.modules["homeassistant.exceptions"].HomeAssistantError = type("HomeAssistantError", (Exception,), {})
sys.modules["homeassistant.helpers"].area_registry = sys.modules["homeassistant.helpers.area_registry"]
sys.modules["homeassistant.helpers"].entity_registry = sys.modules["homeassistant.helpers.entity_registry"]
sys.modules["homeassistant.helpers"].label_registry = sys.modules["homeassistant.helpers.label_registry"]
sys.modules["homeassistant.helpers"].device_registry = sys.modules["homeassistant.helpers.device_registry"]
for _r in ("entity_registry", "area_registry", "device_registry", "label_registry"):
    sys.modules[f"homeassistant.helpers.{_r}"].async_get = lambda *a, **k: None
sys.modules.setdefault("homeassistant.components.ai_task", types.ModuleType("homeassistant.components.ai_task"))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

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
http_api = _load("custom_components.kyber.http_api", ROOT / "custom_components" / "kyber" / "http_api.py")

_execute_tool = http_api._execute_tool


# ── Mock HA state/registry objects ────────────────────────────────────────────

class _State:
    def __init__(self, entity_id: str, state: str = "unknown", attributes: dict | None = None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class _MockStates:
    def __init__(self, states: list[_State]):
        self._by_id = {s.entity_id: s for s in states}

    def get(self, entity_id: str):
        return self._by_id.get(entity_id)

    def async_all(self):
        return list(self._by_id.values())


class _MockEntry:
    def __init__(self, entity_id: str, area_id=None, labels=None):
        self.entity_id = entity_id
        self.area_id = area_id
        self.labels = labels or set()


class _MockEntityRegistry:
    def __init__(self, entries: list):
        self._by_id = {e.entity_id: e for e in entries}
        self.entities = {e.entity_id: e for e in entries}

    def async_get(self, entity_id: str):
        return self._by_id.get(entity_id)


class _MockAreaRegistry:
    def async_get_area(self, area_id):
        return None

    def async_list_areas(self):
        return []


class _MockLabelRegistry:
    def async_list_labels(self):
        return []


def _make_hass(states: list[_State]):
    """Build a minimal mock HomeAssistant object."""
    hass = types.SimpleNamespace()
    hass.states = _MockStates(states)
    hass.data = {}

    # Patch registry getters used inside _execute_tool
    import homeassistant.helpers.entity_registry as _er
    import homeassistant.helpers.area_registry as _ar
    import homeassistant.helpers.label_registry as _lr

    entries = [_MockEntry(s.entity_id) for s in states]
    _er.async_get = lambda h: _MockEntityRegistry(entries)
    _ar.async_get = lambda h: _MockAreaRegistry()
    _lr.async_get = lambda h: _MockLabelRegistry()
    return hass


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGetEntityStateAutoComplete:
    """Tests for entity_id auto-complete in get_entity_state."""

    def test_exact_entity_id_works(self):
        """Sanity check: full entity_id still works."""
        hass = _make_hass([_State("sun.sun", "above_horizon", {"next_rising": "06:00"})])
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": "sun.sun"}))
        assert result["entity_id"] == "sun.sun"
        assert result["state"] == "above_horizon"

    def test_domain_only_autocompletes_to_domain_dot_domain(self):
        """Regression: 'sun' (no dot) should resolve to 'sun.sun' automatically."""
        hass = _make_hass([_State("sun.sun", "above_horizon", {"next_rising": "06:00"})])
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": "sun"}))
        assert "error" not in result, f"Expected auto-complete, got error: {result}"
        assert result["entity_id"] == "sun.sun"

    def test_domain_only_with_fields(self):
        """Auto-complete still works when fields are requested."""
        sun_attrs = {"next_rising": "2026-05-18T03:40:58+00:00", "friendly_name": "Sun"}
        hass = _make_hass([_State("sun.sun", "above_horizon", sun_attrs)])
        result = json.loads(_execute_tool(hass, {
            "name": "get_entity_state",
            "entity_id": "sun",
            "fields": ["next_rising"],
        }))
        assert "error" not in result, f"Expected auto-complete, got error: {result}"
        assert result.get("next_rising") == "2026-05-18T03:40:58+00:00"

    def test_fuzzy_single_match_resolves(self):
        """If 'sun.sun' doesn't exist but exactly one entity matches the query, use it."""
        hass = _make_hass([_State("sun.sun_sensor", "unknown", {"friendly_name": "Sun Sensor"})])
        # "sunsensor" doesn't match sun.sun_sensor exactly, but "sun_sensor" does
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": "sun_sensor"}))
        # Should resolve to sun.sun_sensor via fuzzy match
        assert "error" not in result, f"Expected fuzzy match, got error: {result}"
        assert result["entity_id"] == "sun.sun_sensor"

    def test_fuzzy_multiple_matches_returns_suggestions(self):
        """If multiple entities match, return error with the list of candidates."""
        hass = _make_hass([
            _State("light.sun_lamp", "on"),
            _State("sensor.sun_uv", "5"),
        ])
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": "sun"}))
        assert "error" in result
        # Should mention the candidates
        assert "light.sun_lamp" in result["error"] or "sensor.sun_uv" in result["error"]

    def test_completely_unknown_entity_helpful_error(self):
        """Unknown entity_id returns error mentioning the domain.name format."""
        hass = _make_hass([_State("sun.sun", "above_horizon")])
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": "nonexistent"}))
        assert "error" in result
        assert "domain" in result["error"].lower() or "list_entities" in result["error"].lower()

    def test_entity_with_dot_not_found_gives_format_hint(self):
        """If entity_id has a dot but isn't found, give a helpful error (no fuzzy for dotted IDs)."""
        hass = _make_hass([_State("sun.sun", "above_horizon")])
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": "light.fake_lamp"}))
        assert "error" in result

    def test_missing_entity_id_still_errors(self):
        """Empty entity_id still returns the missing argument error."""
        hass = _make_hass([])
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": ""}))
        assert "error" in result
        assert "missing" in result["error"].lower()

    def test_zone_domain_not_autocompleted_wrong(self):
        """'zone' (no dot) should NOT auto-complete to 'zone.zone' if it doesn't exist."""
        hass = _make_hass([_State("zone.home", "zoning")])
        result = json.loads(_execute_tool(hass, {"name": "get_entity_state", "entity_id": "zone"}))
        # zone.zone doesn't exist; fuzzy should find zone.home as single match
        assert "error" not in result or "zone.home" in result.get("error", ""), (
            f"Expected zone.home suggestion or resolution, got: {result}"
        )
