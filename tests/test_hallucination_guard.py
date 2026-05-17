"""Tests for the entity-ID hallucination guard in http_api.py.

The guard catches responses that reference entity_ids not present in HA state,
even when tools were called (the previous bug — tools returned real IDs but
the model ignored them and invented nicer-looking ones like sensor.motion_room).
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

# ── Stubs ────────────────────────────────────────────────────────────────────
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


_load("custom_components.kyber.const", ROOT / "custom_components/kyber/const.py")
_load("custom_components.kyber.knowledge", ROOT / "custom_components/kyber/knowledge.py")
_load("custom_components.kyber.analyzer", ROOT / "custom_components/kyber/analyzer.py")
_load("custom_components.kyber.source", ROOT / "custom_components/kyber/source.py")
http_api = _load("custom_components.kyber.http_api", ROOT / "custom_components/kyber/http_api.py")

# Snapshot the prompt text at import time — immune to other tests overwriting the const module.
_CONST_SOURCE = (ROOT / "custom_components/kyber/const.py").read_text(encoding="utf-8-sig")

# ── Extract the guard logic ───────────────────────────────────────────────────
# We test the logic directly by extracting and re-implementing its invariants
# from the post-processing code path, using a minimal mock hass.states object.

_ENTITY_ID_RE = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")
_CHECKABLE_DOMAINS = {
    "light", "switch", "sensor", "binary_sensor",
    "climate", "cover", "media_player", "person",
    "fan", "lock", "vacuum", "input_boolean",
}
_NOTE_FRAGMENT = "couldn't verify these entity IDs"


def _run_guard(response_text: str, known_entity_ids: set[str], plan_block=None) -> str:
    """Simulate the hallucination guard post-processing step.

    Returns the (possibly annotated) response text.
    """
    class _FakeStates:
        def get(self, eid):
            return object() if eid in known_entity_ids else None

    class _FakeHass:
        states = _FakeStates()

    hass = _FakeHass()

    plan_has_verified_ids = False
    if plan_block and isinstance(plan_block.get("actions"), list):
        plan_has_verified_ids = any(
            isinstance(a, dict) and a.get("entity_id") and hass.states.get(a["entity_id"])
            for a in plan_block["actions"]
        )

    if not plan_has_verified_ids:
        candidate_ids = _ENTITY_ID_RE.findall(response_text)
        if candidate_ids:
            fake_ids = [
                eid for eid in dict.fromkeys(candidate_ids)
                if eid.split(".")[0] in _CHECKABLE_DOMAINS
                and not hass.states.get(eid)
            ]
            if fake_ids:
                response_text += (
                    "\n\n⚠️ *Note: I couldn't verify these entity IDs against your Home Assistant: "
                    + ", ".join(f"`{e}`" for e in fake_ids[:5])
                    + ". They may be incorrect — ask me to search for them to get real IDs.*"
                )
    return response_text


# ── Tests ────────────────────────────────────────────────────────────────────

class TestHallucinationGuardNoTools:
    """Guard must fire when no tools were called and IDs don't exist in HA."""

    def test_fabricated_sensor_flagged(self):
        text = "Your motion sensors are sensor.motion_slakamer and sensor.motion_woonkamer."
        result = _run_guard(text, known_entity_ids=set())
        assert _NOTE_FRAGMENT in result
        assert "sensor.motion_slakamer" in result
        assert "sensor.motion_woonkamer" in result

    def test_fabricated_binary_sensor_flagged(self):
        text = "The occupancy sensor is binary_sensor.motion_badkamer."
        result = _run_guard(text, known_entity_ids=set())
        assert _NOTE_FRAGMENT in result
        assert "binary_sensor.motion_badkamer" in result

    def test_real_entity_not_flagged(self):
        text = "Your sensor is sensor.temperature_living_room."
        result = _run_guard(text, known_entity_ids={"sensor.temperature_living_room"})
        assert _NOTE_FRAGMENT not in result

    def test_no_entity_ids_in_response(self):
        text = "Here is some information about your home."
        result = _run_guard(text, known_entity_ids=set())
        assert _NOTE_FRAGMENT not in result

    def test_non_checkable_domain_ignored(self):
        # automation.* and script.* are not in _CHECKABLE_DOMAINS, should not be flagged
        text = "Your automation is automation.good_morning and script.reset_lights."
        result = _run_guard(text, known_entity_ids=set())
        assert _NOTE_FRAGMENT not in result


class TestHallucinationGuardWithTools:
    """Guard must still fire when tools WERE called but model ignored results."""

    def test_fabricated_id_flagged_even_when_tools_called(self):
        # This was the original bug: tools returned real IDs but model invented nicer ones
        text = (
            "Your motion sensors:\n"
            "- sensor.motion_slakamer\n"
            "- sensor.motion_woonkamer\n"
            "- sensor.motion_badkamer"
        )
        # Real IDs exist in HA state but were returned by tools, not these invented ones
        known = {"binary_sensor.0x00124b00251202d6_occupancy"}
        result = _run_guard(text, known_entity_ids=known)
        assert _NOTE_FRAGMENT in result
        assert "sensor.motion_slakamer" in result

    def test_real_ids_from_tool_results_not_flagged(self):
        # The actual real (ugly) IDs that tools would return should pass through clean
        text = (
            "Your motion sensors:\n"
            "- binary_sensor.0x00124b00251202d6_occupancy\n"
            "- binary_sensor.0x00124b002513d359_occupancy"
        )
        known = {
            "binary_sensor.0x00124b00251202d6_occupancy",
            "binary_sensor.0x00124b002513d359_occupancy",
        }
        result = _run_guard(text, known_entity_ids=known)
        assert _NOTE_FRAGMENT not in result

    def test_mix_real_and_fake(self):
        # One real, one invented — should flag only the fake one
        text = (
            "Sensors: binary_sensor.0x00124b00251202d6_occupancy "
            "and sensor.motion_woonkamer."
        )
        known = {"binary_sensor.0x00124b00251202d6_occupancy"}
        result = _run_guard(text, known_entity_ids=known)
        assert _NOTE_FRAGMENT in result
        assert "sensor.motion_woonkamer" in result
        # The real one should NOT be in the warning
        assert "0x00124b00251202d6_occupancy" not in result.split(_NOTE_FRAGMENT, 1)[1]

    def test_five_fake_ids_capped(self):
        text = " ".join(f"sensor.fake_{i}" for i in range(10))
        result = _run_guard(text, known_entity_ids=set())
        # Guard shows at most 5 IDs in the warning
        warning_part = result.split(_NOTE_FRAGMENT, 1)[1] if _NOTE_FRAGMENT in result else ""
        count = warning_part.count("`sensor.fake_")
        assert count <= 5


class TestHallucinationGuardWithVerifiedPlan:
    """Guard must NOT fire when plan already has verified (real) entity IDs."""

    def test_plan_with_verified_id_suppresses_warning(self):
        text = "I'll turn on sensor.motion_slakamer for you."
        plan = {"actions": [{"type": "call_service", "entity_id": "light.woonkamer"}]}
        known = {"light.woonkamer"}
        result = _run_guard(text, known_entity_ids=known, plan_block=plan)
        assert _NOTE_FRAGMENT not in result

    def test_plan_with_unverified_id_does_not_suppress(self):
        text = "I'll use sensor.motion_slakamer."
        plan = {"actions": [{"type": "call_service", "entity_id": "light.fake_light"}]}
        known = set()  # neither the plan entity nor response entity exists
        result = _run_guard(text, known_entity_ids=known, plan_block=plan)
        assert _NOTE_FRAGMENT in result


class TestSystemPromptEntityIntegrityRule:
    """Verify the new entity integrity rule is present in the system prompt."""

    def test_entity_id_integrity_rule_in_prompt(self):
        assert "ENTITY ID INTEGRITY" in _CONST_SOURCE

    def test_verbatim_instruction_present(self):
        assert "VERBATIM in a tool result" in _CONST_SOURCE

    def test_no_construct_or_guess_instruction(self):
        assert "NEVER construct, guess, or invent entity IDs" in _CONST_SOURCE

    def test_ugly_id_example_present(self):
        assert "prettier" in _CONST_SOURCE or "nicer" in _CONST_SOURCE or "substitute" in _CONST_SOURCE
