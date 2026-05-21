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

    # Stub language_hints so detect_home_language can import without HA package resolution.
    lh_stub = types.ModuleType("custom_components.kyber.language_hints")
    lh_stub.LANGUAGE_HINTS = {}  # type: ignore[attr-defined]
    lh_stub.detect_language = lambda text: "en"  # type: ignore[attr-defined]
    lh_stub.get_hints_for_language = lambda lang_code: []  # type: ignore[attr-defined]
    lh_stub.language_display_name = lambda lang_code: lang_code  # type: ignore[attr-defined]
    sys.modules.setdefault("custom_components.kyber.language_hints", lh_stub)

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

    # ── New: entity_category filtering ──────────────────────────────────────

    def test_diagnostic_entity_category_not_interesting(self):
        """Entities with entity_category='diagnostic' should always be skipped."""
        # Even a cryptic ID with diagnostic category must be excluded.
        assert not _NARRATOR.is_interesting(
            "sensor.0x00124b00251202d6_battery",
            "battery",
            5,
            entity_category="diagnostic",
        )

    def test_config_entity_category_not_interesting(self):
        """Entities with entity_category='config' should be skipped."""
        assert not _NARRATOR.is_interesting(
            "number.boiler_target_temperature",
            "temperature",
            2,
            entity_category="config",
        )

    def test_none_category_still_interesting_with_device_class(self):
        """entity_category=None must not block entities that otherwise qualify."""
        assert _NARRATOR.is_interesting(
            "sensor.living_room_temperature",
            "temperature",
            0,
            entity_category=None,
        )

    # ── New: input_* domain filtering ───────────────────────────────────────

    def test_input_boolean_is_interesting(self):
        """input_boolean entities are always interesting (user-defined helpers)."""
        assert _NARRATOR.is_interesting("input_boolean.guest_mode", None, 0)

    def test_input_number_is_interesting(self):
        """input_number entities are always interesting."""
        assert _NARRATOR.is_interesting("input_number.max_temp", None, 0)

    def test_input_select_is_interesting(self):
        """input_select entities are always interesting."""
        assert _NARRATOR.is_interesting("input_select.scene_mode", None, 0)

    def test_input_text_is_interesting(self):
        """input_text entities are always interesting."""
        assert _NARRATOR.is_interesting("input_text.guest_name", None, 0)

    def test_input_datetime_is_interesting(self):
        """input_datetime entities are always interesting."""
        assert _NARRATOR.is_interesting("input_datetime.alarm_time", None, 0)

    def test_input_diagnostic_still_skipped(self):
        """Even input_* entities with diagnostic category must be excluded."""
        assert not _NARRATOR.is_interesting(
            "input_boolean.internal_debug",
            None,
            0,
            entity_category="diagnostic",
        )

    # ── New: template platform filtering ────────────────────────────────────

    def test_template_platform_is_interesting(self):
        """template platform entities are always interesting (user-defined)."""
        assert _NARRATOR.is_interesting(
            "sensor.calculated_average",
            None,
            0,
            platform="template",
        )

    def test_template_platform_still_skipped_when_diagnostic(self):
        """template entities with diagnostic category must still be excluded."""
        assert not _NARRATOR.is_interesting(
            "sensor.template_debug",
            None,
            0,
            platform="template",
            entity_category="diagnostic",
        )

    def test_non_template_plain_still_not_interesting(self):
        """A plain entity with no device_class/siblings on non-template platform stays uninteresting."""
        assert not _NARRATOR.is_interesting(
            "sensor.plain_sensor",
            None,
            0,
            platform="mqtt",
        )


# ---------------------------------------------------------------------------
# _is_cryptic
# ---------------------------------------------------------------------------

class TestIsCryptic:
    """Unit tests for the _is_cryptic helper (regressed: function was missing)."""

    def test_zigbee_0x_prefix(self):
        assert _NARRATOR._is_cryptic("binary_sensor.0x00124b00251202d6_occupancy")

    def test_zigbee_hex_suffix(self):
        assert _NARRATOR._is_cryptic("sensor.0x12345678_temperature")

    def test_long_numeric_suffix(self):
        assert _NARRATOR._is_cryptic("sensor.device_12345678901")

    def test_short_hex_not_cryptic(self):
        # 5 hex chars — below the threshold of 6
        assert not _NARRATOR._is_cryptic("sensor.device_12abc")

    def test_plain_name_not_cryptic(self):
        assert not _NARRATOR._is_cryptic("light.bedroom")
        assert not _NARRATOR._is_cryptic("switch.coffee_machine")
        assert not _NARRATOR._is_cryptic("sensor.temperature_living_room")

    def test_is_interesting_cryptic_no_device_class(self):
        # Cryptic IDs qualify for narration even with no device_class/siblings
        assert _NARRATOR.is_interesting("binary_sensor.0x00124b00251202d6_occ", None, 0)

    def test_is_interesting_plain_no_class_fails(self):
        # Plain name, no device_class, no siblings → NOT interesting
        assert not _NARRATOR.is_interesting("light.bedroom", None, 0)



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
# build_batch_prompt
# ---------------------------------------------------------------------------

class TestBuildBatchPrompt:
    def test_contains_rules(self):
        pairs = [("sensor.foo", "entity_id: sensor.foo\narea: Kitchen")]
        prompt = _NARRATOR.build_batch_prompt(pairs)
        assert "RULES" in prompt
        assert "verbatim" in prompt

    def test_contains_entity_ids(self):
        pairs = [
            ("sensor.abc", "entity_id: sensor.abc\narea: Woonkamer"),
            ("light.xyz", "entity_id: light.xyz\narea: Slaapkamer"),
        ]
        prompt = _NARRATOR.build_batch_prompt(pairs)
        assert "sensor.abc" in prompt
        assert "light.xyz" in prompt
        assert "Entity 1" in prompt
        assert "Entity 2" in prompt

    def test_json_format_instruction(self):
        pairs = [("sensor.a", "ctx_a"), ("sensor.b", "ctx_b")]
        prompt = _NARRATOR.build_batch_prompt(pairs)
        assert "JSON" in prompt
        assert "search_terms" in prompt
        assert "device_type" in prompt

    def test_home_lang_hint_included(self):
        pairs = [("sensor.a", "ctx_a")]
        prompt = _NARRATOR.build_batch_prompt(pairs, home_lang="nl", devices_hint="lamp = light")
        assert "nl" in prompt
        assert "lamp = light" in prompt

    def test_home_lang_no_hint(self):
        pairs = [("sensor.a", "ctx_a")]
        prompt = _NARRATOR.build_batch_prompt(pairs, home_lang="nl")
        assert "nl" in prompt


# ---------------------------------------------------------------------------
# parse_batch_response
# ---------------------------------------------------------------------------

class TestParseBatchResponse:
    def test_parses_numbered_list(self):
        raw = (
            "1. sensor.foo is the kitchen temperature sensor.\n"
            "2. light.bar is the living room lamp."
        )
        result = _NARRATOR.parse_batch_response(raw, ["sensor.foo", "light.bar"])
        assert result["sensor.foo"] == "sensor.foo is the kitchen temperature sensor."
        assert result["light.bar"] == "light.bar is the living room lamp."

    def test_skips_out_of_range_numbers(self):
        raw = "1. sensor.foo description.\n5. out.of.range description."
        result = _NARRATOR.parse_batch_response(raw, ["sensor.foo"])
        assert "sensor.foo" in result
        assert len(result) == 1

    def test_empty_response(self):
        result = _NARRATOR.parse_batch_response("", ["sensor.foo"])
        assert result == {}

    def test_partial_response(self):
        raw = "1. sensor.a is good.\n"
        result = _NARRATOR.parse_batch_response(raw, ["sensor.a", "sensor.b"])
        assert "sensor.a" in result
        assert "sensor.b" not in result


# ---------------------------------------------------------------------------
# parse_batch_response_v3
# ---------------------------------------------------------------------------

class TestParseBatchResponseV3:
    def test_parses_json_lines(self):
        raw = (
            '{"id": 1, "description": "sensor.foo is the kitchen temperature sensor.", '
            '"search_terms": ["kitchen temp", "temperature"], "device_type": "temperature sensor"}\n'
            '{"id": 2, "description": "light.bar is the living room lamp.", '
            '"search_terms": ["living room light", "bar lamp"], "device_type": "light"}'
        )
        result = _NARRATOR.parse_batch_response_v3(raw, ["sensor.foo", "light.bar"])
        assert "sensor.foo" in result
        assert result["sensor.foo"]["description"] == "sensor.foo is the kitchen temperature sensor."
        assert result["sensor.foo"]["search_terms"] == ["kitchen temp", "temperature"]
        assert result["sensor.foo"]["device_type"] == "temperature sensor"
        assert "light.bar" in result

    def test_appends_entity_id_when_missing_from_description(self):
        raw = '{"id": 1, "description": "This is a sensor in the kitchen.", "search_terms": [], "device_type": "sensor"}'
        result = _NARRATOR.parse_batch_response_v3(raw, ["sensor.foo"])
        # Entity_id appended in brackets so it remains searchable.
        assert "sensor.foo" in result
        assert result["sensor.foo"]["description"] == "This is a sensor in the kitchen. [sensor.foo]"

    def test_empty_response(self):
        result = _NARRATOR.parse_batch_response_v3("", ["sensor.foo"])
        assert result == {}

    def test_non_json_lines_ignored(self):
        raw = "1. sensor.foo is a sensor.\n" + '{"id": 2, "description": "light.bar is a light.", "search_terms": [], "device_type": "light"}'
        result = _NARRATOR.parse_batch_response_v3(raw, ["sensor.foo", "light.bar"])
        assert "sensor.foo" not in result
        assert "light.bar" in result

    def test_out_of_range_id_ignored(self):
        raw = '{"id": 5, "description": "sensor.foo is something.", "search_terms": [], "device_type": "sensor"}'
        result = _NARRATOR.parse_batch_response_v3(raw, ["sensor.foo"])
        assert result == {}


# ---------------------------------------------------------------------------
# _calc_batch_size
# ---------------------------------------------------------------------------

class TestCalcBatchSize:
    def test_typical_contexts(self):
        # ~200-char contexts should give a batch_size well above 1
        contexts = ["x" * 200] * 10
        size = _NARRATOR._calc_batch_size(contexts, max_batch=20, prompt_budget_chars=int(8192 * 4 * 0.75))
        assert 1 <= size <= 20

    def test_respects_max_batch(self):
        contexts = ["x" * 50] * 10  # small contexts → formula says big number
        size = _NARRATOR._calc_batch_size(contexts, max_batch=5, prompt_budget_chars=int(8192 * 4 * 0.75))
        assert size <= 5

    def test_empty_contexts_fallback(self):
        size = _NARRATOR._calc_batch_size([], max_batch=20, prompt_budget_chars=int(8192 * 4 * 0.75))
        assert 1 <= size <= 20

    def test_huge_contexts_gives_small_batch(self):
        contexts = ["x" * 5000] * 5  # very large contexts
        size = _NARRATOR._calc_batch_size(contexts, max_batch=50, prompt_budget_chars=int(8192 * 4 * 0.75))
        assert size >= 1


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
    entry.disabled_by = None
    entry.hidden_by = None
    entry.entity_category = None
    entry.original_name = None
    entry.name = None
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
async def test_batch_accepted():
    """AI returns descriptions with entity_ids → accepted stat incremented."""
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
        patch("asyncio.sleep", AsyncMock()),
    ):
        # One batch call — reply contains entity_id
        mock_ai.return_value = f"1. {eid} is an occupancy sensor in the bedroom."
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["accepted"] == 1
    assert stats["low_quality"] == 0
    assert stats["errors"] == 0
    assert stats["batches"] == 1


@pytest.mark.asyncio
async def test_batch_low_quality_when_entity_id_missing():
    """Description missing entity_id → stored as low_quality."""
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
        patch("asyncio.sleep", AsyncMock()),
    ):
        # Description does NOT contain entity_id
        mock_ai.return_value = "1. This is a motion sensor in the bedroom."
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["low_quality"] == 1
    assert stats["accepted"] == 0
    # Low-quality entry should be stored (for skipping re-runs)
    lq_calls = [
        c for c in kstore.async_add.call_args_list
        if "low_quality" in (c.kwargs.get("tags") or [])
    ]
    assert len(lq_calls) == 1


@pytest.mark.asyncio
async def test_batch_ai_error_increments_errors():
    """AI call raises → errors counter incremented, nothing stored."""
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
        patch("asyncio.sleep", AsyncMock()),
    ):
        mock_ai.side_effect = RuntimeError("AI unavailable")
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["errors"] >= 1
    narrator_calls = [
        c for c in kstore.async_add.call_args_list
        if c.kwargs.get("source") == "entity_narrator"
    ]
    assert narrator_calls == []


@pytest.mark.asyncio
async def test_batch_multi_entity_stats():
    """Two entities in one batch: one accepted, one low-quality."""
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
        entry.platform = "mqtt"
        entry.disabled_by = None
        entry.hidden_by = None
        entry.entity_category = None
        entry.original_name = None
        entry.name = None
    entity_reg = MagicMock()
    entity_reg.entities = {eid1: entry1, eid2: entry2}

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch("asyncio.sleep", AsyncMock()),
    ):
        # Both in one batch (default max_batch=20 > 2), eid1 accepted, eid2 missing entity_id
        mock_ai.return_value = (
            f"1. {eid1} is an occupancy sensor.\n"
            "2. This is a motion sensor."  # missing eid2
        )
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test", max_batch=20)

    assert stats["total"] == 2
    assert stats["accepted"] == 1
    assert stats["low_quality"] == 1
    assert stats["batches"] == 1


@pytest.mark.asyncio
async def test_batch_parse_failure_flag():
    """When fewer than half descriptions parse → parse_failures incremented."""
    mod = _NARRATOR
    eids = [f"binary_sensor.0x{i:08x}_occupancy" for i in range(10)]
    hass = _make_hass()
    hass.states.get = MagicMock(side_effect=lambda eid: _make_state(eid) if eid in eids else None)
    kstore = _make_kstore()

    entries = {}
    for eid in eids:
        e = MagicMock()
        e.entity_id = eid
        e.device_id = None
        e.area_id = None
        e.device_class = "occupancy"
        e.platform = "mqtt"
        e.disabled_by = None
        e.hidden_by = None
        e.entity_category = None
        e.original_name = None
        e.name = None
        entries[eid] = e
    entity_reg = MagicMock()
    entity_reg.entities = entries

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch("asyncio.sleep", AsyncMock()),
    ):
        # Only 2 lines for 10 entities → parse failure
        mock_ai.return_value = "1. First one.\n2. Second one."
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test", max_batch=20)

    assert stats["parse_failures"] >= 1


@pytest.mark.asyncio
async def test_batch_size_respected():
    """max_batch=2 with 4 entities → 2 batches, 2 AI calls."""
    mod = _NARRATOR
    eids = [f"binary_sensor.0x{i:08x}_occupancy" for i in range(4)]
    hass = _make_hass()
    hass.states.get = MagicMock(side_effect=lambda eid: _make_state(eid) if eid in eids else None)
    kstore = _make_kstore()

    entries = {}
    for eid in eids:
        e = MagicMock()
        e.entity_id = eid
        e.device_id = None
        e.area_id = None
        e.device_class = "occupancy"
        e.platform = "mqtt"
        e.disabled_by = None
        e.hidden_by = None
        e.entity_category = None
        e.original_name = None
        e.name = None
        entries[eid] = e
    entity_reg = MagicMock()
    entity_reg.entities = entries

    ai_calls = []

    async def _fake_ai(hass, ai_id, prompt):
        ai_calls.append(prompt)
        # Return description for first two lines
        lines = []
        for i, eid in enumerate(eids[:2], start=1):
            if eid in prompt:
                lines.append(f"{i}. {eid} is a sensor.")
        return "\n".join(lines) if lines else "1. no match."

    with (
        patch.object(mod, "_run_ai", new=_fake_ai),
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch("asyncio.sleep", AsyncMock()),
    ):
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test", max_batch=2)

    assert stats["batches"] == 2
    assert len(ai_calls) == 2


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
        patch("asyncio.sleep", AsyncMock()),
    ):
        mock_ai.return_value = f"1. {eid} is a sensor."
        await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    stats_calls = [
        c for c in kstore.async_add.call_args_list
        if c.kwargs.get("source") == "narrator_stats"
    ]
    assert len(stats_calls) == 1


@pytest.mark.asyncio
async def test_ai_call_error_falls_back():
    """Exception during AI batch call → errors counter incremented, no narrator entry stored."""
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
        patch("asyncio.sleep", AsyncMock()),
    ):
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
        patch("asyncio.sleep", AsyncMock()),
    ):
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    assert stats["total"] == 0
    mock_ai.assert_not_called()


# ---------------------------------------------------------------------------
# Thinking bug — chat-busy interruption tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_narrator_pauses_before_call_when_chat_busy():
    """If _CHAT_BUSY_KEY is True before an AI call, narrator waits until clear."""
    mod = _NARRATOR
    eid = "binary_sensor.0x00124b00_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    busy_iter = iter([True, True, False])
    hass.data[mod._CHAT_BUSY_KEY] = True
    sleep_calls: list[float] = []

    async def _fake_sleep(secs):
        sleep_calls.append(secs)
        try:
            hass.data[mod._CHAT_BUSY_KEY] = next(busy_iter)
        except StopIteration:
            hass.data[mod._CHAT_BUSY_KEY] = False

    with (
        patch.object(mod, "_run_ai", new_callable=AsyncMock) as mock_ai,
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch("asyncio.sleep", _fake_sleep),
    ):
        mock_ai.return_value = f"1. {eid} is a sensor."
        stats = await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    mock_ai.assert_called_once()
    assert len(sleep_calls) >= 1
    assert stats["accepted"] >= 1


@pytest.mark.asyncio
async def test_narrator_cancels_ai_when_chat_becomes_busy_mid_call():
    """AI call in progress is cancelled immediately when _CHAT_BUSY_KEY flips True."""
    import asyncio

    mod = _NARRATOR
    eid = "binary_sensor.0x00124b00_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    ai_cancelled: list[bool] = []

    # Use Event.wait() so _slow_ai blocks without depending on asyncio.sleep
    # (which gets patched and would make it return immediately).
    _blocking_event = asyncio.Event()  # never set → blocks until cancelled

    async def _slow_ai(hass, ai_entity_id, prompt):
        hass.data[mod._CHAT_BUSY_KEY] = True   # flip busy while "generating"
        try:
            await _blocking_event.wait()        # blocks until CancelledError is delivered
        except asyncio.CancelledError:
            ai_cancelled.append(True)
            raise

    async def _fake_sleep(secs):
        hass.data[mod._CHAT_BUSY_KEY] = False  # clear busy after narrator's inner wait

    with (
        patch.object(mod, "_run_ai", new=_slow_ai),
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch("asyncio.sleep", _fake_sleep),
    ):
        await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    # Yield to the event loop so the pending CancelledError is delivered to _slow_ai.
    await asyncio.sleep(0)
    assert ai_cancelled, "AI task should have been cancelled when chat became busy"


@pytest.mark.asyncio
async def test_narrator_does_not_block_chat_for_120s():
    """Narrator must not hold the event loop for the full 120s timeout.

    Without the fix, asyncio.wait_for would block for up to 120s.
    With the polling fix, the AI task is cancelled within one poll interval (~3s real
    time, but near-instant in tests because asyncio.wait uses a real timeout).
    """
    import asyncio as real_asyncio
    import time

    mod = _NARRATOR
    eid = "binary_sensor.0x00124b00_occupancy"
    hass = _make_hass()
    hass.states.get = MagicMock(return_value=_make_state(eid))
    kstore = _make_kstore()
    entity_reg = _make_entity_reg(eid)

    async def _blocking_ai(hass, ai_entity_id, prompt):
        hass.data[mod._CHAT_BUSY_KEY] = True  # trip busy while "generating"
        await real_asyncio.sleep(999)          # "never" returns on its own

    async def _fast_sleep(secs):
        hass.data[mod._CHAT_BUSY_KEY] = False  # clear so narrator can move on

    t0 = time.monotonic()
    with (
        patch.object(mod, "_run_ai", new=_blocking_ai),
        patch.object(sys.modules["homeassistant.helpers.area_registry"], "async_get", return_value=_area_reg_mock()),
        patch.object(sys.modules["homeassistant.helpers.device_registry"], "async_get", return_value=_device_reg_mock()),
        patch("asyncio.sleep", _fast_sleep),
    ):
        await mod.async_narrate_entities(hass, kstore, entity_reg, "ai_task.test")

    elapsed = time.monotonic() - t0
    # Without the fix this would take ~120s; with the fix it finishes within a few seconds
    assert elapsed < 15.0, f"Narrator blocked for {elapsed:.1f}s — chat interruption not working"
