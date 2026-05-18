"""Tests for deep_analyzer.py improvements: device registry context and entity_id validation."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_deep():
    """Load deep_analyzer using the same pattern as test_deep_analyzer.py."""
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
    if "homeassistant.core" not in sys.modules:
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object  # type: ignore[attr-defined]
        sys.modules["homeassistant.core"] = core
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = types.ModuleType("homeassistant.helpers")
    storage = sys.modules.get("homeassistant.helpers.storage") or types.ModuleType("homeassistant.helpers.storage")

    class _Store:
        def __init__(self, *a, **kw): self._data = None
        async def async_load(self): return self._data
        async def async_save(self, data): self._data = data

    storage.Store = _Store
    sys.modules["homeassistant.helpers.storage"] = storage
    if "homeassistant.exceptions" not in sys.modules:
        exc = types.ModuleType("homeassistant.exceptions")
        class HomeAssistantError(Exception): pass
        exc.HomeAssistantError = HomeAssistantError  # type: ignore[attr-defined]
        sys.modules["homeassistant.exceptions"] = exc

    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules.setdefault("custom_components.kyber", types.ModuleType("custom_components.kyber"))

    const_mod = types.ModuleType("custom_components.kyber.const")
    const_mod.CONF_AI_TASK_ENTITY_ID = "ai_task_entity_id"  # type: ignore[attr-defined]
    sys.modules["custom_components.kyber.const"] = const_mod

    # Load real source.py (same as test_deep_analyzer.py does)
    src_spec = importlib.util.spec_from_file_location(
        "custom_components.kyber.source",
        ROOT / "custom_components" / "kyber" / "source.py",
    )
    src_mod = importlib.util.module_from_spec(src_spec)
    assert src_spec.loader is not None
    src_spec.loader.exec_module(src_mod)
    sys.modules["custom_components.kyber.source"] = src_mod

    spec = importlib.util.spec_from_file_location(
        "custom_components.kyber.deep_analyzer",
        ROOT / "custom_components" / "kyber" / "deep_analyzer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestDeviceRegistryInPrompt:
    """_build_prompt includes manufacturer/model when entity_devices is provided."""

    def _make_automation(self, alias="test_automation", entity_ids=None):
        return {
            "alias": alias,
            "id": "123",
            "trigger": [{"platform": "state", "entity_id": entity_ids or []}],
            "action": [],
        }

    def test_device_info_in_prompt(self):
        mod = _load_deep()
        eid = "binary_sensor.0x00124b_occupancy"
        item = self._make_automation(entity_ids=[eid])
        prompt = mod._build_prompt(
            "automation",
            item,
            prompt_variant=6,  # entity_relationships lens
            entity_names={eid: "Slaapkamer aanwezigheid"},
            entity_areas={eid: "Slaapkamer"},
            entity_devices={eid: ("Aqara", "MS-FP2")},
        )
        assert "Aqara" in prompt
        assert "MS-FP2" in prompt

    def test_device_info_absent_without_entity_devices(self):
        mod = _load_deep()
        eid = "binary_sensor.0x00124b_occupancy"
        item = self._make_automation(entity_ids=[eid])
        prompt = mod._build_prompt(
            "automation",
            item,
            prompt_variant=0,
            entity_names={eid: "Slaapkamer aanwezigheid"},
        )
        assert "Aqara" not in prompt

    def test_none_device_parts_omitted(self):
        mod = _load_deep()
        eid = "light.woonkamer"
        item = self._make_automation(entity_ids=[eid])
        prompt = mod._build_prompt(
            "automation",
            item,
            prompt_variant=0,
            entity_names={eid: "Woonkamer lamp"},
            entity_devices={eid: (None, None)},
        )
        assert "device:" not in prompt

    def test_partial_device_info(self):
        """Only manufacturer without model → still shown."""
        mod = _load_deep()
        eid = "light.kitchen"
        item = self._make_automation(entity_ids=[eid])
        prompt = mod._build_prompt(
            "automation",
            item,
            prompt_variant=0,
            entity_names={eid: "Kitchen light"},
            entity_devices={eid: ("Philips", None)},
        )
        assert "Philips" in prompt


class TestMinConfidenceThreshold:
    """_MIN_CONFIDENCE should be >= 0.65 after the improvement."""

    def test_min_confidence_is_65(self):
        mod = _load_deep()
        assert mod._MIN_CONFIDENCE >= 0.65, (
            f"_MIN_CONFIDENCE should be >=0.65 to reduce low-quality facts, got {mod._MIN_CONFIDENCE}"
        )

