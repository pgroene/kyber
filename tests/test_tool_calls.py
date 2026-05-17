"""Unit tests for tool call parsing helpers (_parse_tool_calls, _strip_tool_calls).

Regression coverage for:
  - GH bug: tool call with JSON array field (e.g. "fields": ["next_rising"]) was not
    parsed because [^]]* stopped at the ] inside the array, silently showing the raw
    [TOOL_CALL: ...] to the user.
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

_parse_tool_calls = http_api._parse_tool_calls
_strip_tool_calls = http_api._strip_tool_calls


# ── _parse_tool_calls ─────────────────────────────────────────────────────────

class TestParseToolCalls:
    def test_simple_tool_call(self):
        text = '[TOOL_CALL: {"name": "get_areas"}]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "get_areas"

    def test_tool_call_with_string_field(self):
        text = '[TOOL_CALL: {"name": "get_entity_state", "entity_id": "light.lamp"}]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["entity_id"] == "light.lamp"

    # ── REGRESSION: array values inside JSON body ─────────────────────────────
    def test_tool_call_with_array_field(self):
        """Regression: [^]]* stopped at ] inside array, dropping the tool call."""
        text = '[TOOL_CALL: {"name": "get_entity_state", "entity_id": "sun", "fields": ["next_rising"]}]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1, (
            "Tool call with array field was not parsed — regex stopped at ] inside JSON array"
        )
        assert calls[0]["name"] == "get_entity_state"
        assert calls[0]["entity_id"] == "sun"
        assert calls[0]["fields"] == ["next_rising"]

    def test_tool_call_with_multi_element_array(self):
        text = '[TOOL_CALL: {"name": "get_entity_state", "entity_id": "sun", "fields": ["next_rising", "next_setting"]}]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["fields"] == ["next_rising", "next_setting"]

    def test_tool_call_with_nested_object(self):
        text = '[TOOL_CALL: {"name": "call_service", "domain": "light", "service_data": {"brightness": 255}}]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["service_data"]["brightness"] == 255

    def test_multiple_tool_calls_extracted(self):
        text = (
            'First call:\n'
            '[TOOL_CALL: {"name": "get_areas"}]\n'
            'Second call:\n'
            '[TOOL_CALL: {"name": "get_entity_state", "entity_id": "sun", "fields": ["next_rising"]}]\n'
        )
        calls = _parse_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["name"] == "get_areas"
        assert calls[1]["name"] == "get_entity_state"
        assert calls[1]["fields"] == ["next_rising"]

    def test_tolerates_o0_confusion(self):
        """Model sometimes writes T00L_CALL instead of TOOL_CALL."""
        text = '[T00L_CALL: {"name": "get_areas"}]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1

    def test_tolerates_dash_separator(self):
        text = '[TOOL-CALL: {"name": "get_areas"}]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1

    def test_invalid_json_skipped(self):
        text = '[TOOL_CALL: not json at all]'
        calls = _parse_tool_calls(text)
        assert calls == []

    def test_no_tool_calls_returns_empty(self):
        text = "Here is a nice response with no tool calls."
        calls = _parse_tool_calls(text)
        assert calls == []

    def test_whitespace_inside_brackets(self):
        text = '[TOOL_CALL:  {"name": "get_areas"}  ]'
        calls = _parse_tool_calls(text)
        assert len(calls) == 1


# ── _strip_tool_calls ─────────────────────────────────────────────────────────

class TestStripToolCalls:
    def test_strips_simple_call(self):
        text = 'Fetching data...\n[TOOL_CALL: {"name": "get_areas"}]\nDone.'
        result = _strip_tool_calls(text)
        assert "[TOOL_CALL:" not in result
        assert "Fetching data" in result

    def test_strips_call_with_array_field(self):
        """Regression: strip should also work when call contains array values."""
        text = '[TOOL_CALL: {"name": "get_entity_state", "entity_id": "sun", "fields": ["next_rising"]}]'
        result = _strip_tool_calls(text)
        assert result == ""

    def test_strips_multiple_calls(self):
        text = (
            '[TOOL_CALL: {"name": "get_areas"}]\n'
            'Some text\n'
            '[TOOL_CALL: {"name": "get_entity_state", "entity_id": "sun", "fields": ["next_rising"]}]'
        )
        result = _strip_tool_calls(text)
        assert "[TOOL_CALL:" not in result
        assert "Some text" in result

    def test_no_calls_unchanged(self):
        text = "No tool calls here."
        assert _strip_tool_calls(text) == text
