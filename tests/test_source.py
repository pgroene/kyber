"""Tests for the source readers + content hashing in source.py.

We bypass HA entirely by faking `hass.config.config_dir` to point at a
tmp_path. The functions `read_automations`, `read_scripts`, `read_blueprints`
and `content_hash` are pure-python and do not need HA at all.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_source_module():
    """Load source.py with minimal HA stubs."""
    root = Path(__file__).resolve().parents[1]
    path = root / "custom_components" / "kyber" / "source.py"

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

    if "custom_components" not in sys.modules:
        sys.modules["custom_components"] = types.ModuleType("custom_components")
    if "custom_components.kyber" not in sys.modules:
        sys.modules["custom_components.kyber"] = types.ModuleType("custom_components.kyber")

    spec = importlib.util.spec_from_file_location("custom_components.kyber.source", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakeConfig:
    def __init__(self, config_dir: str) -> None:
        self.config_dir = config_dir


class _FakeHass:
    def __init__(self, config_dir: str) -> None:
        self.config = _FakeConfig(config_dir)
        self.data: dict = {}


# ── content_hash ─────────────────────────────────────────────────────
def test_content_hash_stable_across_key_order():
    mod = _load_source_module()
    a = {"trigger": [{"platform": "time", "at": "07:00"}], "alias": "Morning"}
    b = {"alias": "Morning", "trigger": [{"platform": "time", "at": "07:00"}]}
    assert mod.content_hash(a) == mod.content_hash(b)


def test_content_hash_changes_on_edit():
    mod = _load_source_module()
    a = {"alias": "Morning", "trigger": [{"platform": "time", "at": "07:00"}]}
    b = {"alias": "Morning", "trigger": [{"platform": "time", "at": "08:00"}]}
    assert mod.content_hash(a) != mod.content_hash(b)


# ── read_automations / read_scripts ──────────────────────────────────
AUTO_YAML = """\
- id: morning_lights
  alias: Morning lights
  description: Turn on the kitchen lights at sunrise
  mode: single
  trigger:
    - platform: sun
      event: sunrise
  action:
    - service: light.turn_on
      target:
        entity_id: light.kitchen
"""

SCRIPT_YAML = """\
welcome_home:
  alias: Welcome home
  mode: single
  sequence:
    - service: light.turn_on
      target:
        entity_id: light.hallway
    - delay: "00:00:05"
    - service: notify.mobile_app
      data:
        message: Welcome!
"""


def test_read_automations_parses_basic_file(tmp_path):
    mod = _load_source_module()
    (tmp_path / "automations.yaml").write_text(AUTO_YAML, encoding="utf-8")
    hass = _FakeHass(str(tmp_path))
    items = mod.read_automations(hass)
    assert len(items) == 1
    a = items[0]
    assert a["id"] == "morning_lights"
    assert a["alias"] == "Morning lights"
    assert a["num_triggers"] == 1
    assert a["num_actions"] == 1
    assert a["hash"].startswith("sha256:")


def test_read_automations_returns_empty_if_no_file(tmp_path):
    mod = _load_source_module()
    hass = _FakeHass(str(tmp_path))
    assert mod.read_automations(hass) == []


def test_read_scripts_handles_mapping_form(tmp_path):
    mod = _load_source_module()
    (tmp_path / "scripts.yaml").write_text(SCRIPT_YAML, encoding="utf-8")
    hass = _FakeHass(str(tmp_path))
    items = mod.read_scripts(hass)
    assert len(items) == 1
    s = items[0]
    assert s["id"] == "welcome_home"
    assert s["alias"] == "Welcome home"
    assert s["num_steps"] == 3


# ── blueprints ───────────────────────────────────────────────────────
BLUEPRINT_YAML = """\
blueprint:
  name: Motion-activated light
  description: Turn on a light when motion is detected
  domain: automation
  input:
    motion_entity:
      name: Motion sensor
    light_target:
      name: Light to control
"""


def test_read_blueprints_finds_yaml_files(tmp_path):
    mod = _load_source_module()
    bp_dir = tmp_path / "blueprints" / "automation" / "kyber"
    bp_dir.mkdir(parents=True)
    (bp_dir / "motion_light.yaml").write_text(BLUEPRINT_YAML, encoding="utf-8")
    hass = _FakeHass(str(tmp_path))
    items = mod.read_blueprints(hass)
    assert len(items) == 1
    b = items[0]
    assert b["name"] == "Motion-activated light"
    assert b["kind"] == "automation"
    assert "motion_entity" in b["input_keys"]
    assert b["hash"].startswith("sha256:")


def test_read_blueprint_rejects_path_escape(tmp_path):
    mod = _load_source_module()
    hass = _FakeHass(str(tmp_path))
    result = mod.read_blueprint(hass, "../../etc/passwd")
    assert "error" in result


# ── memo ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_memo_records_and_detects_unchanged(tmp_path):
    mod = _load_source_module()
    hass = _FakeHass(str(tmp_path))
    memo = mod.AnalysisMemo(hass)
    await memo.async_load()
    assert memo.is_changed("automation", "abc", "sha256:xyz") is True
    await memo.async_record(
        kind="automation",
        ident="abc",
        new_hash="sha256:xyz",
        fact_ids=["f1"],
    )
    assert memo.is_changed("automation", "abc", "sha256:xyz") is False
    assert memo.is_changed("automation", "abc", "sha256:abc") is True
    records = memo.all_records()
    assert len(records) == 1
    assert records[0]["fact_ids"] == ["f1"]


@pytest.mark.asyncio
async def test_memo_get_memo_returns_singleton(tmp_path):
    mod = _load_source_module()
    hass = _FakeHass(str(tmp_path))
    a = mod.get_memo(hass)
    b = mod.get_memo(hass)
    assert a is b
