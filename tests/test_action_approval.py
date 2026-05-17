"""Unit tests for action approval and plan annotation helpers in http_api.py.

Covers:
  - _action_requires_approval
  - _annotate_plan_approval
  - narration pattern stripping
  - bare JSON tool result stripping
"""
from __future__ import annotations

import json
import re
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

_action_requires_approval = http_api._action_requires_approval
_annotate_plan_approval = http_api._annotate_plan_approval
_NARRATION_PATTERNS = http_api._NARRATION_PATTERNS
_BARE_JSON_TOOL_RESULT_RE = http_api._BARE_JSON_TOOL_RESULT_RE


# ── _action_requires_approval ─────────────────────────────────────────────────

class TestActionRequiresApproval:
    def test_config_changing_type_requires_approval(self):
        assert _action_requires_approval({"type": "assign_area"}) is True

    def test_rename_entity_requires_approval(self):
        assert _action_requires_approval({"type": "rename_entity"}) is True

    def test_create_area_requires_approval(self):
        assert _action_requires_approval({"type": "create_area"}) is True

    def test_create_automation_requires_approval(self):
        assert _action_requires_approval({"type": "create_automation"}) is True

    def test_update_dashboard_requires_approval(self):
        assert _action_requires_approval({"type": "update_dashboard"}) is True

    def test_add_knowledge_requires_approval(self):
        assert _action_requires_approval({"type": "add_knowledge"}) is True

    def test_call_service_light_turn_on_no_approval(self):
        assert _action_requires_approval({
            "type": "call_service", "domain": "light", "service": "turn_on"
        }) is False

    def test_call_service_switch_turn_off_no_approval(self):
        assert _action_requires_approval({
            "type": "call_service", "domain": "switch", "service": "turn_off"
        }) is False

    def test_destructive_unlock_requires_approval(self):
        assert _action_requires_approval({
            "type": "call_service", "domain": "lock", "service": "unlock"
        }) is True

    def test_destructive_alarm_disarm_requires_approval(self):
        assert _action_requires_approval({
            "type": "call_service",
            "domain": "alarm_control_panel",
            "service": "alarm_disarm",
        }) is True

    def test_cover_open_requires_approval(self):
        assert _action_requires_approval({
            "type": "call_service", "domain": "cover", "service": "open_cover"
        }) is True

    def test_non_dict_returns_false(self):
        assert _action_requires_approval("not a dict") is False
        assert _action_requires_approval(None) is False

    def test_type_case_insensitive(self):
        assert _action_requires_approval({"type": "ASSIGN_AREA"}) is True


# ── _annotate_plan_approval ───────────────────────────────────────────────────

class TestAnnotatePlanApproval:
    def test_safe_plan_not_requires_approval(self):
        plan = {
            "actions": [
                {"type": "call_service", "domain": "light", "service": "turn_on"},
                {"type": "call_service", "domain": "switch", "service": "turn_off"},
            ]
        }
        result = _annotate_plan_approval(plan)
        assert result["requires_approval"] is False
        assert result["actions"][0]["requires_approval"] is False
        assert result["actions"][1]["requires_approval"] is False

    def test_config_action_sets_plan_flag(self):
        plan = {
            "actions": [
                {"type": "call_service", "domain": "light", "service": "turn_on"},
                {"type": "assign_area", "entity_id": "light.x", "area_id": "bedroom"},
            ]
        }
        result = _annotate_plan_approval(plan)
        assert result["requires_approval"] is True
        assert result["actions"][0]["requires_approval"] is False
        assert result["actions"][1]["requires_approval"] is True

    def test_all_config_changing_sets_flag(self):
        plan = {"actions": [{"type": "create_label", "name": "MyLabel"}]}
        result = _annotate_plan_approval(plan)
        assert result["requires_approval"] is True

    def test_empty_actions_no_approval(self):
        plan = {"actions": []}
        result = _annotate_plan_approval(plan)
        assert result["requires_approval"] is False

    def test_non_dict_plan_returned_unchanged(self):
        assert _annotate_plan_approval(None) is None
        assert _annotate_plan_approval("not a plan") == "not a plan"

    def test_plan_without_actions_key_returned_unchanged(self):
        plan = {"description": "no actions"}
        result = _annotate_plan_approval(plan)
        assert "requires_approval" not in result


# ── Narration pattern stripping ───────────────────────────────────────────────

class TestNarrationPatterns:
    def _strip(self, text: str) -> str:
        for pattern in _NARRATION_PATTERNS:
            text = pattern.sub("", text)
        return text.strip()

    def test_strips_ill_call_pattern(self):
        text = "I'll call `list_entities_by_domain` for the lights.\nHere is your plan."
        result = self._strip(text)
        assert "I'll call" not in result
        assert "Here is your plan" in result

    def test_strips_will_start_by_calling(self):
        text = "I will start by calling get_area_entities for the 'Woonkamer' area.\nDone."
        result = self._strip(text)
        assert "I will start by calling" not in result

    def test_strips_based_on_result(self):
        text = "Based on the result, I can see the light is on.\nHere is your plan."
        result = self._strip(text)
        assert "Based on the result" not in result
        assert "Here is your plan" in result

    def test_strips_please_let_me_know(self):
        text = "Here is the plan.\nPlease let me know if this is what you were expecting."
        result = self._strip(text)
        assert "Please let me know" not in result
        assert "Here is the plan" in result

    def test_clean_response_unchanged(self):
        text = "Here is your plan to turn on the lights."
        result = self._strip(text)
        assert result == text


# ── Bare JSON tool result stripping ──────────────────────────────────────────

class TestBareJsonToolResult:
    def _strip(self, text: str) -> str:
        return _BARE_JSON_TOOL_RESULT_RE.sub("", text).strip()

    def test_strips_area_result_line(self):
        text = 'Before\n{"area": "Woonkamer", "entities": {}}\nAfter'
        result = self._strip(text)
        assert '"area"' not in result
        assert "Before" in result
        assert "After" in result

    def test_strips_items_result_line(self):
        text = 'Text\n{"items": [], "_total_items": 0}\nMore'
        result = self._strip(text)
        assert '"items"' not in result

    def test_leaves_plan_json_alone(self):
        text = '{"title": "My plan", "actions": []}'
        result = self._strip(text)
        # Plan JSON doesn't match the pattern (no area/entities/items keys)
        assert result == text

    def test_leaves_regular_text_alone(self):
        text = "Turn on the kitchen lights."
        result = self._strip(text)
        assert result == text
