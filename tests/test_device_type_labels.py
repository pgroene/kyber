"""Tests for device_type_labels.py — infer_device_type and auto-label pipeline."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    """Load device_type_labels.py without triggering HA's __init__.py."""
    # Stub homeassistant packages
    for mod_name in [
        "homeassistant",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_registry",
        "homeassistant.helpers.label_registry",
    ]:
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

    if not hasattr(sys.modules["homeassistant.core"], "HomeAssistant"):
        sys.modules["homeassistant.core"].HomeAssistant = object

    spec = importlib.util.spec_from_file_location(
        "device_type_labels",
        ROOT / "custom_components" / "kyber" / "device_type_labels.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()
infer_device_type = _mod.infer_device_type
DEVICE_TYPE_LABELS = _mod.DEVICE_TYPE_LABELS


# ── infer_device_type ──────────────────────────────────────────────────────────

class TestInferDeviceType:
    def test_espresso_entity_id(self):
        result = infer_device_type("switch.onoff_keuken_espresso_304", "", None)
        assert result == "koffiemachine"

    def test_espresso_friendly_name(self):
        result = infer_device_type("switch.onoff_304", "Espresso Machine", None)
        assert result == "koffiemachine"

    def test_lamp_entity_id(self):
        result = infer_device_type("light.woonkamer_lamp_1", "", None)
        assert result == "lamp"

    def test_tv_keyword(self):
        result = infer_device_type("media_player.woonkamer_tv", "TV Woonkamer", None)
        assert result == "tv"

    def test_vacuum_device_class(self):
        result = infer_device_type("vacuum.freddy", "Stofzuiger", "vacuum")
        assert result == "stofzuiger"

    def test_device_class_fallback(self):
        # No keyword match but device_class matches
        result = infer_device_type("sensor.xyz_abc", "Unnamed", "temperature")
        assert result == "sensor"

    def test_user_query_wins(self):
        # "lamp" in query overrides ambiguous entity
        result = infer_device_type("switch.hal_001", "HAL", None, user_query="dim de lamp")
        assert result == "lamp"

    def test_no_match_returns_none(self):
        result = infer_device_type("binary_sensor.motion_abc", "Motion", None)
        assert result is None

    def test_compound_word_koffiemachine(self):
        # "koffiemachine" as a single token
        result = infer_device_type("switch.koffiemachine_keuken", "", None)
        assert result == "koffiemachine"

    def test_garage_maps_to_poort(self):
        result = infer_device_type("cover.garage_deur", "", None)
        assert result == "poort"

    def test_sonos_speaker(self):
        result = infer_device_type("media_player.sonos_keuken", "", None)
        assert result == "speaker"

    def test_all_labels_have_required_keys(self):
        for key, cfg in DEVICE_TYPE_LABELS.items():
            assert "name" in cfg, f"{key} missing 'name'"
            assert cfg["name"].startswith("kyber:"), f"{key} name must start with 'kyber:'"
            assert "icon" in cfg, f"{key} missing 'icon'"
            assert "color" in cfg, f"{key} missing 'color'"


# ── async_ensure_kyber_label ───────────────────────────────────────────────────

class TestEnsureKyberLabel:
    def _make_hass(self, existing_label=None):
        label_reg = MagicMock()
        label_reg.async_get_label.return_value = existing_label
        label_reg.async_create = MagicMock()

        lr_mod = sys.modules["homeassistant.helpers.label_registry"]
        lr_mod.async_get = MagicMock(return_value=label_reg)

        hass = MagicMock()
        return hass, label_reg

    def _run(self, coro):
        import asyncio
        original = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
            asyncio.set_event_loop_policy(original)

    def test_creates_label_when_missing(self):
        hass, label_reg = self._make_hass(existing_label=None)
        result = self._run(_mod.async_ensure_kyber_label(hass, "koffiemachine"))
        assert result == "koffiemachine"
        label_reg.async_create.assert_called_once()
        call_kwargs = label_reg.async_create.call_args
        assert "kyber:Koffiemachine" in str(call_kwargs)

    def test_skips_create_when_label_exists(self):
        existing = MagicMock()
        hass, label_reg = self._make_hass(existing_label=existing)
        result = self._run(_mod.async_ensure_kyber_label(hass, "lamp"))
        assert result == "lamp"
        label_reg.async_create.assert_not_called()

    def test_returns_none_for_unknown_device_type(self):
        hass, _ = self._make_hass()
        result = self._run(_mod.async_ensure_kyber_label(hass, "unknown_type"))
        assert result is None
