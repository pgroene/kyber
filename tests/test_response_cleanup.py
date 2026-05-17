"""Tests for the response post-processing helpers in http_api.py.

These exercise the regression introduced in v0.1.26 where the model
role-played tool calls as plain text and emitted action plans in bare
``` ``` ``` fences instead of ``` ```plan ``` ``` blocks.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

# Stub homeassistant + aiohttp at import-time so http_api can load.
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


class _Stub:  # noqa: D401
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
for r in ("entity_registry", "area_registry", "device_registry", "label_registry"):
    sys.modules[f"homeassistant.helpers.{r}"].async_get = lambda *a, **k: None
# ai_task is optional; http_api wraps it in try/except
sys.modules.setdefault("homeassistant.components.ai_task", types.ModuleType("homeassistant.components.ai_task"))

# Make repo root importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Now import the helpers we want to test — bypass the package __init__ which
# eagerly imports HA-only modules. We pre-register stub parent packages so the
# relative imports inside http_api resolve.
import importlib.util  # noqa: E402

# Create stub packages so `from .const import ...` works inside http_api.
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

_augment_brightness_intent = http_api._augment_brightness_intent
_extract_plan_block = http_api._extract_plan_block
_rewrap_bare_action_fences = http_api._rewrap_bare_action_fences
_strip_role_echo_prefix = http_api._strip_role_echo_prefix


SAMPLE = """User: turn the lights on in the woonkamer
Assistant: You are correct, we need to use a tool call to get the actual entity IDs.

For your request, I will start by calling `list_entities_by_domain` for the "light" domain:

The result will be: {"_truncated": true, "items": {}}

Based on this result, I propose the following plan to turn on the lights in the woonkamer:
```
{
  "type": "call_service",
  "domain": "light",
  "service": "turn_on",
  "entity_id": "light.woonkamer_1",
  "description": "Turn on light switch 1 in woonkamer"
}
```
Please let me know if this is acceptable.

{"area": "Werkkamer", "entities": {}}

Based on this result, I propose the following plan to turn on the lights in the werkkamer:
```
{
  "type": "call_service",
  "domain": "light",
  "service": "turn_on",
  "entity_id": "light.werkkamer_1",
  "description": "Turn on light switch 1 in werkkamer"
}
```
"""


def test_rewrap_bare_action_fences_merges_into_single_plan():
    out = _rewrap_bare_action_fences(SAMPLE)
    plan = _extract_plan_block(out)
    assert plan is not None, "expected a ```plan``` block to be produced"
    assert isinstance(plan.get("actions"), list)
    # Both woonkamer and werkkamer actions should be present
    ids = {a.get("entity_id") for a in plan["actions"] if isinstance(a, dict)}
    assert "light.woonkamer_1" in ids
    assert "light.werkkamer_1" in ids


def test_rewrap_leaves_existing_plan_block_alone():
    text = 'Some text\n```plan\n{"actions": [{"type": "call_service"}]}\n```\n'
    assert _rewrap_bare_action_fences(text) == text


def test_strip_role_echo_prefix_removes_leading_user_and_assistant():
    text = "User: turn on lights\nAssistant: ok\n\nReal answer here."
    out = _strip_role_echo_prefix(text)
    assert out.startswith("Real answer"), f"got: {out!r}"
    assert "User:" not in out
    assert "Assistant:" not in out


def test_strip_role_echo_prefix_keeps_normal_responses():
    text = "Sure, here are the lights you asked about."
    assert _strip_role_echo_prefix(text) == text


def test_augment_brightness_intent_max_adds_100():
    plan = {"actions": [{
        "type": "call_service", "domain": "light",
        "service": "turn_on", "entity_id": "light.x",
    }]}
    out = _augment_brightness_intent(plan, "set the lights in werkkamer to max")
    assert out["actions"][0]["service_data"]["brightness_pct"] == 100


def test_augment_brightness_intent_dim_adds_10():
    plan = {"actions": [{
        "type": "call_service", "domain": "light",
        "service": "turn_on", "entity_id": "light.x",
    }]}
    out = _augment_brightness_intent(plan, "dim the bedroom lights")
    assert out["actions"][0]["service_data"]["brightness_pct"] == 10


def test_augment_brightness_intent_no_keyword_unchanged():
    plan = {"actions": [{
        "type": "call_service", "domain": "light",
        "service": "turn_on", "entity_id": "light.x",
    }]}
    out = _augment_brightness_intent(plan, "turn on the lights")
    assert "service_data" not in out["actions"][0]


def test_augment_brightness_intent_respects_existing_brightness():
    plan = {"actions": [{
        "type": "call_service", "domain": "light",
        "service": "turn_on", "entity_id": "light.x",
        "service_data": {"brightness": 50},
    }]}
    out = _augment_brightness_intent(plan, "set to max")
    assert "brightness_pct" not in out["actions"][0]["service_data"]
    assert out["actions"][0]["service_data"]["brightness"] == 50


def test_augment_brightness_intent_ignores_non_light():
    plan = {"actions": [{
        "type": "call_service", "domain": "switch",
        "service": "turn_on", "entity_id": "switch.x",
    }]}
    out = _augment_brightness_intent(plan, "to max")
    assert "service_data" not in out["actions"][0]


def test_classify_intent_informational_queries():
    """Regression: 'control' in a query like 'what automations control X' must be informational."""
    _classify_intent = http_api._classify_intent
    # These should all be INFORMATIONAL — not action
    for prompt in [
        "what automations does control my downlights in the livingroom",
        "what controls the downlights",
        "which automation controls the zitkamer lights",
        "what lights do I have",
        "show me all automations",
        "list my devices",
    ]:
        result = _classify_intent(prompt)
        assert result == "informational", f"Expected informational for: {prompt!r}, got: {result!r}"


def test_classify_intent_action_queries():
    """These prompts should be classified as action."""
    _classify_intent = http_api._classify_intent
    for prompt in [
        "turn on the lights",
        "turn off the kitchen light",
        "rename area bedroom to slaapkamer",
        "create a new area",
        "set brightness to 50",
        "zet aan de lamp",
        "zet uit alle lichten",
    ]:
        result = _classify_intent(prompt)
        assert result == "action", f"Expected action for: {prompt!r}, got: {result!r}"
