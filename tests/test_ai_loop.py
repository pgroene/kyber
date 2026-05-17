"""Tests for the AI tool-calling loop edge cases.

Covers:
  - resolve_tool_call: alias resolution and arg-key mapping
  - Dedup across rounds (same sig caches from round 1, skipped in round 3)
  - Max-rounds exhaustion: loop stops at _TOOL_CALL_MAX_ROUNDS
  - Synthesis fires when all rounds are duplicates and no redirect applies
  - Single redirect fires only once (second duplicate → synthesis)
  - Multi-query dedup: same queries in one round counted once
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
tool_execution = _load(
    "custom_components.kyber.tool_execution",
    ROOT / "custom_components" / "kyber" / "tool_execution.py",
)
http_api = _load("custom_components.kyber.http_api", ROOT / "custom_components" / "kyber" / "http_api.py")

resolve_tool_call = tool_execution.resolve_tool_call
TOOL_ALIASES = tool_execution.TOOL_ALIASES
_build_loop_redirect = http_api._build_loop_redirect
_TOOL_CALL_MAX_ROUNDS = http_api._TOOL_CALL_MAX_ROUNDS

# Re-use the PromptLoopSimulator from test_prompt_dry_run to avoid duplication
from tests.test_prompt_dry_run import PromptLoopSimulator, K  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════════
# resolve_tool_call
# ═════════════════════════════════════════════════════════════════════════════

class TestResolveToolCall:
    """Unit tests for the alias-resolution helper."""

    def test_known_alias_resolved(self):
        call = {"name": "list_areas"}
        result = resolve_tool_call(call)
        assert result["name"] == "get_areas"

    def test_canonical_name_unchanged(self):
        call = {"name": "search_entities", "query": "tv"}
        result = resolve_tool_call(call)
        assert result["name"] == "search_entities"

    def test_unknown_name_unchanged(self):
        call = {"name": "totally_unknown_tool"}
        result = resolve_tool_call(call)
        assert result["name"] == "totally_unknown_tool"

    def test_area_arg_alias_area_id(self):
        call = {"name": "get_area_entities", "area_id": "living_room"}
        result = resolve_tool_call(call)
        assert result.get("area") == "living_room"

    def test_area_arg_alias_area_name(self):
        call = {"name": "get_area_entities", "area_name": "Living Room"}
        result = resolve_tool_call(call)
        assert result.get("area") == "Living Room"

    def test_area_not_overwritten_when_present(self):
        call = {"name": "get_area_entities", "area": "kitchen", "area_id": "living_room"}
        result = resolve_tool_call(call)
        # area already present — should NOT be overwritten
        assert result["area"] == "kitchen"

    def test_all_aliases_resolve_to_valid_tools(self):
        """Every alias should map to a real tool (not another alias)."""
        for alias, canonical in TOOL_ALIASES.items():
            assert canonical not in TOOL_ALIASES, (
                f"Alias chain detected: {alias} → {canonical} → ? "
                f"(canonical must not itself be an alias)"
            )

    def test_original_dict_not_mutated(self):
        original = {"name": "list_areas"}
        resolve_tool_call(original)
        assert original["name"] == "list_areas"  # input must be immutable

    def test_name_alias_and_area_arg_both_resolved(self):
        """list_entities_by_area is an alias for get_area_entities; area_id should also map."""
        call = {"name": "list_entities_by_area", "area_id": "bedroom"}
        result = resolve_tool_call(call)
        assert result["name"] == "get_area_entities"
        assert result.get("area") == "bedroom"


# ═════════════════════════════════════════════════════════════════════════════
# Max rounds
# ═════════════════════════════════════════════════════════════════════════════

class TestMaxRoundsExhaustion:
    """Loop must stop at _TOOL_CALL_MAX_ROUNDS even if the model keeps calling tools."""

    MOCK = {
        K("search_entities", query="sensor"): {"sensor.temp": {"state": "20"}},
    }

    def _infinite_rounds(self, limit: int):
        """Simulate model that never stops calling search_entities."""
        return [[{"name": "search_entities", "query": "sensor"}]] * (limit + 2)

    def test_stops_at_max_rounds(self):
        rounds = self._infinite_rounds(_TOOL_CALL_MAX_ROUNDS)
        sim = PromptLoopSimulator(self.MOCK).run(rounds, max_rounds=_TOOL_CALL_MAX_ROUNDS)
        assert sim.rounds_executed <= _TOOL_CALL_MAX_ROUNDS

    def test_max_rounds_constant_is_positive(self):
        assert _TOOL_CALL_MAX_ROUNDS > 0


# ═════════════════════════════════════════════════════════════════════════════
# Dedup across rounds
# ═════════════════════════════════════════════════════════════════════════════

class TestDedupAcrossRounds:
    """A tool call executed in round 1 must be served from cache in round 3 (no re-execute)."""

    _executed_count = 0

    MOCK = {
        K("search_entities", query="light"): {"light.living_room": {"state": "on"}},
        K("get_areas"): {"living_room": "Living Room"},
    }

    def _rounds(self):
        return [
            [{"name": "search_entities", "query": "light"}],   # round 1 — unique
            [{"name": "get_areas"}],                            # round 2 — unique
            [{"name": "search_entities", "query": "light"}],   # round 3 — duplicate of round 1
            [],  # answer
        ]

    def test_dedup_stops_re_execution(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        # Duplicate in round 3 triggers redirect (search_entities redirect available)
        assert sim.redirects_fired == 1 or sim.synthesis_fired, (
            "Duplicate call should trigger redirect or synthesis, not re-execute"
        )

    def test_only_two_unique_tools_executed(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        # search_entities and get_areas — the third call (duplicate) should NOT add a new entry
        assert len(sim.final_tool_results) == 2

    def test_result_cached_correctly(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        result = sim.final_tool_results.get("search_entities")
        assert result is not None
        assert "light.living_room" in result


# ═════════════════════════════════════════════════════════════════════════════
# Synthesis fallback
# ═════════════════════════════════════════════════════════════════════════════

class TestSynthesisFallback:
    """When a tool has no redirect rule and is called twice, synthesis fires."""

    MOCK = {
        K("get_labels"): {"label_a": "Label A", "label_b": "Label B"},
    }

    def _rounds_duplicate_no_redirect(self):
        return [
            [{"name": "get_labels"}],  # round 1 — unique
            [{"name": "get_labels"}],  # round 2 — duplicate, no redirect rule for get_labels
        ]

    def test_synthesis_fires_on_duplicate_without_redirect(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_duplicate_no_redirect())
        assert sim.synthesis_fired
        assert sim.stopped_at == "synthesis"

    def test_redirect_not_fired_for_get_labels(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_duplicate_no_redirect())
        assert sim.redirects_fired == 0


# ═════════════════════════════════════════════════════════════════════════════
# Redirect fires once then synthesis
# ═════════════════════════════════════════════════════════════════════════════

class TestRedirectFiresOnceThenSynthesis:
    """After the one allowed redirect, if model still loops → synthesis."""

    MOCK = {
        K("get_area_entities", area="badroom"): {"area": "Badroom", "entities": {}},
        K("search_entities", query="badroom"): {"info": "No results"},
    }

    def _rounds(self):
        return [
            [{"name": "get_area_entities", "area": "badroom"}],  # round 1 — empty result
            [{"name": "get_area_entities", "area": "badroom"}],  # round 2 — dup → redirect
            [{"name": "get_area_entities", "area": "badroom"}],  # round 3 — dup again → synthesis
        ]

    def test_redirect_fires_only_once(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.redirects_fired == 1

    def test_synthesis_fires_after_second_dup(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.synthesis_fired

    def test_stopped_at_synthesis(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.stopped_at == "synthesis"


# ═════════════════════════════════════════════════════════════════════════════
# Build loop redirect content
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildLoopRedirectContent:
    """Unit tests for _build_loop_redirect output content."""

    def test_get_area_entities_redirect_content(self):
        calls = [("sig1", {"name": "get_area_entities", "area": "kitchen"})]
        result = _build_loop_redirect(calls)
        assert result is not None
        assert "kitchen" in result
        assert "search_entities" in result
        assert "search_knowledge" in result

    def test_search_entities_redirect_content(self):
        calls = [("sig1", {"name": "search_entities", "query": "lamp"})]
        result = _build_loop_redirect(calls)
        assert result is not None
        assert "lamp" in result
        assert "search_knowledge" in result

    def test_no_redirect_for_unknown_tool(self):
        calls = [("sig1", {"name": "get_labels"})]
        result = _build_loop_redirect(calls)
        assert result is None

    def test_redirect_ends_with_assistant(self):
        calls = [("sig1", {"name": "get_area_entities", "area": "office"})]
        result = _build_loop_redirect(calls)
        assert result.endswith("Assistant:")

    def test_search_entities_multi_query_redirect(self):
        calls = [("sig1", {"name": "search_entities", "queries": ["lamp", "light"]})]
        result = _build_loop_redirect(calls)
        assert result is not None
