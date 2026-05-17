"""Tests for the AI response parser and prompt builder in deep_analyzer.py."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_deep():
    root = Path(__file__).resolve().parents[1]
    path = root / "custom_components" / "kyber" / "deep_analyzer.py"

    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
    if "homeassistant.core" not in sys.modules:
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object  # type: ignore[attr-defined]
        sys.modules["homeassistant.core"] = core
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = types.ModuleType("homeassistant.helpers")
    storage = sys.modules.get("homeassistant.helpers.storage") or types.ModuleType(
        "homeassistant.helpers.storage"
    )

    class _Store:
        def __init__(self, *a, **kw):
            self._data = None
        async def async_load(self):
            return self._data
        async def async_save(self, data):
            self._data = data

    storage.Store = _Store
    sys.modules["homeassistant.helpers.storage"] = storage
    if "homeassistant.exceptions" not in sys.modules:
        exc = types.ModuleType("homeassistant.exceptions")
        class HomeAssistantError(Exception):
            pass
        exc.HomeAssistantError = HomeAssistantError
        sys.modules["homeassistant.exceptions"] = exc

    if "custom_components" not in sys.modules:
        sys.modules["custom_components"] = types.ModuleType("custom_components")
    if "custom_components.kyber" not in sys.modules:
        sys.modules["custom_components.kyber"] = types.ModuleType("custom_components.kyber")

    # Stub the const + knowledge + source modules deep_analyzer imports
    const_mod = types.ModuleType("custom_components.kyber.const")
    const_mod.CONF_AI_TASK_ENTITY_ID = "ai_task_entity_id"
    sys.modules["custom_components.kyber.const"] = const_mod

    # Load source first (deep_analyzer imports from it)
    src_spec = importlib.util.spec_from_file_location(
        "custom_components.kyber.source",
        root / "custom_components" / "kyber" / "source.py",
    )
    src_mod = importlib.util.module_from_spec(src_spec)
    assert src_spec.loader is not None
    src_spec.loader.exec_module(src_mod)
    sys.modules["custom_components.kyber.source"] = src_mod

    spec = importlib.util.spec_from_file_location("custom_components.kyber.deep_analyzer", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_parse_facts_handles_clean_json():
    mod = _load_deep()
    raw = '[{"category":"area_alias","subject":"office","content":"werkkamer = office","tags":["dutch"],"confidence":0.8}]'
    facts = mod._parse_facts(raw)
    assert len(facts) == 1
    assert facts[0]["content"] == "werkkamer = office"
    assert facts[0]["confidence"] == 0.8


def test_parse_facts_strips_markdown_fence():
    mod = _load_deep()
    raw = '```json\n[{"category":"general","content":"A fact","confidence":0.7}]\n```'
    facts = mod._parse_facts(raw)
    assert len(facts) == 1
    assert facts[0]["category"] == "general"


def test_parse_facts_returns_empty_on_garbage():
    mod = _load_deep()
    assert mod._parse_facts("I'm sorry I can't help.") == []
    assert mod._parse_facts("") == []


def test_parse_facts_clamps_confidence():
    mod = _load_deep()
    raw = '[{"content":"x","confidence":99},{"content":"y","confidence":-3}]'
    facts = mod._parse_facts(raw)
    assert facts[0]["confidence"] == 1.0
    assert facts[1]["confidence"] == 0.0


def test_parse_facts_skips_empty_content():
    mod = _load_deep()
    raw = '[{"content":""},{"content":"ok"}]'
    facts = mod._parse_facts(raw)
    assert len(facts) == 1
    assert facts[0]["content"] == "ok"


def test_build_prompt_includes_alias_and_yaml_body():
    mod = _load_deep()
    item = {
        "id": "x1",
        "alias": "Bedtime",
        "description": "Turn off lights at 23:00",
        "mode": "single",
        "trigger": [{"platform": "time", "at": "23:00"}],
        "condition": [],
        "action": [{"service": "light.turn_off"}],
    }
    prompt = mod._build_prompt("automation", item)
    assert "Bedtime" in prompt
    assert "JSON array" in prompt
    assert "23:00" in prompt
