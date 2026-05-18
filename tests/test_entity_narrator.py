"""Tests for entity_narrator.py â€” Phase 3 AI-generated descriptions."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Load entity_narrator.py directly via importlib to avoid __init__.py
# ---------------------------------------------------------------------------

def _load_narrator():
    """Load entity_narrator module isolated from HA's __init__.py."""
    for mod_name in ["homeassistant", "homeassistant.core", "homeassistant.helpers"]:
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

    if not hasattr(sys.modules["homeassistant.core"], "HomeAssistant"):
        sys.modules["homeassistant.core"].HomeAssistant = object  # type: ignore[attr-defined]

    # Stub HA helper sub-modules used by async_narrate_entities
    for sub in ["homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry"]:
        if sub not in sys.modules:
            stub = types.ModuleType(sub)
            stub.async_get = MagicMock()  # type: ignore[attr-defined]
            sys.modules[sub] = stub
            # Also attach to parent
            parent = sys.modules["homeassistant.helpers"]
            setattr(parent, sub.split(".")[-1], stub)

    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules.setdefault("custom_components.kyber", types.ModuleType("custom_components.kyber"))

    # Stub integration_explorer so the relative import in async_narrate_entities works.
    ie_stub = types.ModuleType("custom_components.kyber.integration_explorer")
    ie_stub.EXPLORER_PROGRESS_KEY = "kyber_explorer_progress"  # type: ignore[attr-defined]
    sys.modules["custom_components.kyber.integration_explorer"] = ie_stub

    spec = importlib.util.spec_from_file_location(
        "custom_components.kyber.entity_narrator",
        ROOT / "custom_components" / "kyber" / "entity_narrator.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sys.modules["custom_components.kyber.entity_narrator"] = mod
    return mod


# Load once at module level (pure-python, no side effects).
_NARRATOR = _load_narrator()


# ---------------------------------------------------------------------------
# is_interesting
# ---------------------------------------------------------------------------

class TestIsInteresting:
    def test_device_class_makes_interesting(self):
        assert _NARRATOR.is_interesting("light.living_room", "light", 0)

    def test_occupancy_device_class(self):
        assert _NARRATOR.is_interesting("binary_sensor.0xabcdef", "occupancy", 0)

    def test_cryptic_hex_id(self):
        assert _NARRATOR.is_interesting("binary_sensor.0x00124b00251202d6_occupancy", None, 0)

    def test_cryptic_long_hex_suffix(self):
        assert _NARRATOR.is_interesting("sensor.0x12345678_temperature", None, 0)

    def test_cryptic_long_numeric_suffix(self):
        assert _NARRATOR.is_interesting("sensor.device_12345678901", None, 0)

    def test_sibling_count_threshold(self):
        assert _NARRATOR.is_interesting("light.plain_name", None, 3)
        assert not _NARRATOR.is_interesting("light.plain_name", None, 2)

    def test_not_interesting_simple_light(self):
        assert not _NARRATOR.is_interesting("light.bedroom", None, 0)

    def test_not_interesting_named_switch(self):
        assert not _NARRATOR.is_interesting("switch.coffee_machine", None, 1)


# ---------------------------------------------------------------------------
# build_entity_context
# ---------------------------------------------------------------------------

class TestBuildEntityContext:
    def _ctx(self, **kwargs):
        defaults = dict(
            entity_id="sensor.0x00124b_temp",
            name="Slaapkamer temperatuur",
            domain="sensor",
            device_class="temperature",
            unit="Â°C",
            area_name="Slaapkamer",
            state_str="21.5",
            attributes={"battery": "85", "linkquality": "200"},
            manufacturer="Aqara",
            model="WSDCGQ11LM",
            siblings=[
                ("sensor.0x00124b_humidity", "Slaapkamer vochtigheid"),
                ("sensor.0x00124b_battery", "Slaapkamer batterij"),
            ],
        )
        defaults.update(kwargs)
        return _NARRATOR.build_entity_context(**defaults)

    def test_entity_id_in_context(self):
        assert "sensor.0x00124b_temp" in self._ctx()

    def test_area_in_context(self):
        assert "Slaapkamer" in self._ctx()

    def test_manufacturer_in_context(self):
        assert "Aqara" in self._ctx()

    def test_model_in_context(self):
        assert "WSDCGQ11LM" in self._ctx()

    def test_sibling_ids_in_context(self):
        ctx = self._ctx()
        assert "sensor.0x00124b_humidity" in ctx

    def test_unavailable_state_omitted(self):
        ctx = self._ctx(state_str="unavailable")
        assert "current_state" not in ctx

    def test_unknown_state_omitted(self):
        ctx = self._ctx(state_str="unknown")
        assert "current_state" not in ctx

    def test_valid_state_included(self):
        ctx = self._ctx(state_str="21.5")
        assert "21.5" in ctx

    def test_skip_internal_attributes(self):
        # supported_features is a noisy internal flag and should be omitted from the dump.
        # But the explicit name field IS shown via the 'name' parameter.
        ctx = self._ctx(
            name="Slaapkamer sensor",
            attributes={"supported_features": "3", "battery": "80"},
        )
        assert "supported_features" not in ctx
        assert "Slaapkamer sensor" in ctx  # name shown explicitly

    def test_no_manufacturer(self):
        ctx = self._ctx(manufacturer=None, model=None)
        assert "device_manufacturer" not in ctx


# ---------------------------------------------------------------------------
# build_generation_prompt
# ---------------------------------------------------------------------------

class TestBuildGenerationPrompt:
    def test_contains_strict_rules(self):
        ctx = "entity_id: sensor.foo\nfriendly_name: Foo"
        prompt = _NARRATOR.build_generation_prompt(ctx)
        assert "STRICT RULES" in prompt
        assert "VERBATIM" in prompt

    def test_contains_context(self):
        ctx = "entity_id: sensor.abc\narea: Woonkamer"
        prompt = _NARRATOR.build_generation_prompt(ctx)
        assert "sensor.abc" in prompt
        assert "Woonkamer" in prompt


# ---------------------------------------------------------------------------
# build_verification_prompt
# ---------------------------------------------------------------------------

class TestBuildVerificationPrompt:
    def test_contains_yes_or_no_instruction(self):
        prompt = _NARRATOR.build_verification_prompt("source", "description")
        assert "yes" in prompt.lower()
        assert "no" in prompt.lower()

    def test_contains_source_and_description(self):
        prompt = _NARRATOR.build_verification_prompt("MY SOURCE", "MY DESC")
        assert "MY SOURCE" in prompt
        assert "MY DESC" in prompt


# ---------------------------------------------------------------------------
# is_hallucinated
# ---------------------------------------------------------------------------

class TestIsHallucinated:
    def test_no_answer(self):
        assert _NARRATOR.is_hallucinated("no") is False
        assert _NARRATOR.is_hallucinated("No") is False
        assert _NARRATOR.is_hallucinated("NO.") is False

    def test_yes_answer(self):
        assert _NARRATOR.is_hallucinated("yes") is True
        assert _NARRATOR.is_hallucinated("Yes.") is True

    def test_unclear_answer_is_conservative(self):
        assert _NARRATOR.is_hallucinated("maybe") is True
        assert _NARRATOR.is_hallucinated("") is True
        assert _NARRATOR.is_hallucinated("I'm not sure") is True

    def test_no_with_extra_text(self):
        assert _NARRATOR.is_hallucinated("no, the description is accurate") is False


# ---------------------------------------------------------------------------
# async_narrate_entities integration tests (mock AI)
# ---------------------------------------------------------------------------

def _make_hass():
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    return hass


def _make_kstore():
    kstore = MagicMock()
    kstore._entries = {}
    kstore._loaded = True
    kstore.async_load = AsyncMock()
    kstore.async_add = AsyncMock(return_value={"id": "abc123"})
    kstore.async_delete = AsyncMock()
    kstore.async_force_save = AsyncMock()
    return kstore


def _make_entity_reg(entity_id, device_id=None):
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.device_id = device_id
    entry.area_id = None
    entry.device_class = "occupancy"
    entry.platform = "mqtt"
    reg = MagicMock()
    reg.entities = {entity_id: entry}
    return reg


def _make_state(entity_id, device_class="occupancy"):
    state = MagicMock()
    state.entity_id = entity_id
    state.state = "on"
    state.attributes = {
        "friendly_name": f"Test {entity_id}",
        "device_class": device_class,
    }
    return state


def _area_reg_mock():
    return MagicMock(async_get_area=MagicMock(return_value=None))


def _device_reg_mock():
    return MagicMock(async_get=MagicMock(return_value=None))


@pytest.mark.asyncio
async def test_generate_and_verify_first_pass():
    """AI returns good description on first try â†’ accepted_first incremented."""
    mod = _NARRATOR
    eid = "binary_sensor.0x00124b00_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        mock_ai.side_effect = [f"This is {eid} in the bedroom.", "no"]
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["accepted_first"] == 1
    assert stats["accepted_retry"] == 0
    assert stats["rejected"] == 0
    assert stats["errors"] == 0


@pytest.mark.asyncio
async def test_generate_retry_on_yes():
    """First verify returns yes â†’ retry â†’ second verify returns no â†’ accepted_retry."""
    mod = _NARRATOR
    eid = "binary_sensor.0x00124b00_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        mock_ai.side_effect = [
            f"Attempt 1 {eid}", "yes",
            f"Attempt 2 {eid}", "no",
        ]
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["accepted_first"] == 0
    assert stats["accepted_retry"] == 1
    assert stats["rejected"] == 0


@pytest.mark.asyncio
async def test_generate_fallback_after_3_failures():
    """All three verify calls return yes â†’ rejected (template fallback)."""
    mod = _NARRATOR
    eid = "binary_sensor.0x00124b00_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        mock_ai.side_effect = [
            f"Attempt {eid} 1", "yes",
            f"Attempt {eid} 2", "yes",
            f"Attempt {eid} 3", "yes",
        ]
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["rejected"] == 1
    assert stats["accepted_first"] == 0
    assert stats["accepted_retry"] == 0
    narrator_calls = [
        c for c in kstore.async_add.call_args_list
        if c.kwargs.get("source") == "entity_narrator"
    ]
    assert narrator_calls == []


@pytest.mark.asyncio
async def test_entity_id_must_be_in_description():
    """Generated description missing entity_id â†’ treated as failed attempt (retry)."""
    mod = _NARRATOR
    eid = "binary_sensor.0x00124b00_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        mock_ai.side_effect = [
            "This entity is a motion sensor in the bedroom.",  # no entity_id â†’ skip
            f"This is {eid} in the bedroom.",                  # entity_id present
            "no",                                              # verify
        ]
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["accepted_retry"] == 1
    assert stats["rejected"] == 0


@pytest.mark.asyncio
async def test_stats_tracking():
    """Stats dict is updated correctly across mix of pass/fail entities."""
    mod = _NARRATOR
    eid1 = "binary_sensor.0xaabbcc_occupancy"
    eid2 = "binary_sensor.0xddeeff_occupancy"
    hass = _make_hass()
    states = {eid1: _make_state(eid1), eid2: _make_state(eid2)}
    hass.states.get = MagicMock(side_effect=lambda eid: states.get(eid))
    kstore = _make_kstore()

    entry1, entry2 = MagicMock(), MagicMock()
    for entry, eid in ((entry1, eid1), (entry2, eid2)):
        entry.entity_id = eid
        entry.device_id = None
        entry.area_id = None
        entry.device_class = "occupancy"
    entity_reg = MagicMock()
    entity_reg.entities = {eid1: entry1, eid2: entry2}

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        mock_ai.side_effect = [
            f"This is {eid1}.", "no",                       # eid1: accepted first
            f"missing {eid2}", "yes",
            f"missing {eid2}", "yes",
            f"missing {eid2}", "yes",                       # eid2: rejected
        ]
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["total"] == 2
    assert stats["accepted_first"] == 1
    assert stats["rejected"] == 1


@pytest.mark.asyncio
async def test_stats_persisted_to_knowledge_store():
    """Stats are saved to the knowledge store as source='narrator_stats'."""
    mod = _NARRATOR
    eid = "binary_sensor.0x00124b_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        mock_ai.side_effect = [f"This is {eid}.", "no"]
        await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    stats_calls = [
        c for c in kstore.async_add.call_args_list
        if c.kwargs.get("source") == "narrator_stats"
    ]
    assert len(stats_calls) == 1


@pytest.mark.asyncio
async def test_ai_call_error_falls_back():
    """Exception during AI generation â†’ errors counter incremented, no narrator entry stored."""
    mod = _NARRATOR
    eid = "binary_sensor.0xabcdef_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        mock_ai.side_effect = RuntimeError("AI unavailable")
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["errors"] >= 1
    narrator_calls = [
        c for c in kstore.async_add.call_args_list
        if c.kwargs.get("source") == "entity_narrator"
    ]
    assert narrator_calls == []


@pytest.mark.asyncio
async def test_already_narrated_entity_skipped():
    """Entity with existing narrator entry at current version is skipped entirely."""
    mod = _NARRATOR
    eid = "binary_sensor.0x00124b_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    kstore._entries = {
        "existing_entry": {
            "subject": eid,
            "source": "entity_narrator",
            "tags": [mod._NARRATOR_VERSION_TAG],
        }
    }
    entity_reg = _make_entity_reg(eid)

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch.object(mod, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.sleep = AsyncMock()
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["total"] == 0
    mock_ai.assert_not_called()


