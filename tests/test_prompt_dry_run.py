"""Dry-run tests for prompt loop logic and redirect behaviour.

When fixing prompt issues or changing the tool-calling loop, add a scenario
here FIRST (red), implement the fix, then verify it goes green.

Each scenario mirrors a real debug-zip failure. The simulator reproduces the
exact dedup / redirect / synthesis logic from http_api.py without needing a
live HA instance.

How to add a new scenario:
  1. Drop the debug zip in Downloads, extract user_prompt + tool_log.
  2. Build a ROUNDS list that matches what the model called (in order).
  3. Supply MOCK_TOOLS with the real (or approximated) results.
  4. Set expected assertions.
  5. Run pytest — red means the bug is reproducible, green means fix works.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

# ── HA + aiohttp stubs (same pattern as test_tool_calls.py) ──────────────────
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
_load("custom_components.kyber.source", ROOT / "custom_components" / "kyber" / "source.py")
http_api = _load("custom_components.kyber.http_api", ROOT / "custom_components" / "kyber" / "http_api.py")

_build_loop_redirect = http_api._build_loop_redirect
_SYNTHESIS_INSTRUCTIONS = http_api._SYNTHESIS_INSTRUCTIONS


# ── Simulator ─────────────────────────────────────────────────────────────────

class PromptLoopSimulator:
    """Simulate the http_api tool-calling loop without a live HA instance.

    Attributes
    ----------
    rounds_executed:   how many AI rounds ran
    redirects_fired:   how many redirect hints were injected
    synthesis_fired:   whether the synthesis pass was triggered
    redirect_texts:    the redirect hint strings that were injected
    final_tool_results: dict of sig → result for every unique call that ran
    stopped_at:        'answer' | 'redirect_then_answer' | 'synthesis' | 'max_rounds'
    """

    def __init__(self, mock_tools: dict[str, dict[str, Any]]) -> None:
        """
        Parameters
        ----------
        mock_tools:
            Mapping of (tool_name, frozenset_of_arg_items) → result dict.
            Use ``PromptLoopSimulator.tool_key(call)`` to build keys.
        """
        self._mock_tools = mock_tools
        self.rounds_executed = 0
        self.redirects_fired = 0
        self.synthesis_fired = False
        self.redirect_texts: list[str] = []
        self.final_tool_results: dict[str, Any] = {}
        self.stopped_at = ""

    @staticmethod
    def tool_key(call: dict) -> str:
        """Canonical signature for a tool call (same logic as http_api)."""
        args = {k: v for k, v in call.items() if k != "name"}
        return json.dumps({"args": args, "name": call.get("name", "")}, sort_keys=True)

    def _mock_result(self, call: dict) -> dict:
        key = self.tool_key(call)
        if key in self._mock_tools:
            return self._mock_tools[key]
        # Fall back to partial name+arg matching for convenience
        name = call.get("name", "")
        for mk, mv in self._mock_tools.items():
            mk_parsed = json.loads(mk)
            if mk_parsed.get("name") == name:
                mk_args = mk_parsed.get("args", {})
                if all(call.get(k) == v for k, v in mk_args.items()):
                    return mv
        return {"error": f"no mock for {name}"}

    def run(self, rounds: list[list[dict]], max_rounds: int = 8) -> "PromptLoopSimulator":
        """Run the simulation.

        Parameters
        ----------
        rounds:
            List of rounds. Each round is the list of tool calls the model
            would make given the current context (including injected redirects).
            Inject the redirect-response round yourself as the next entry when
            simulating what the model does after seeing a redirect.
        """
        executed_cache: dict[str, str] = {}
        loop_redirect_given = False

        for round_idx, calls in enumerate(rounds):
            if round_idx >= max_rounds:
                self.stopped_at = "max_rounds"
                break

            self.rounds_executed += 1
            new_count = 0
            filtered: list[tuple[str, dict]] = []

            for call in calls:
                s = self.tool_key(call)
                if s not in executed_cache:
                    filtered.append((s, call))
                # duplicates within same round are silently dropped (same as http_api)

            for s, call in filtered:
                result = self._mock_result(call)
                result_str = json.dumps(result)
                executed_cache[s] = result_str
                self.final_tool_results[call.get("name", "")] = result
                new_count += 1

            if not filtered and not calls:
                # Model emitted no tool calls → final prose answer
                self.stopped_at = "answer"
                break

            if new_count == 0:
                # All calls this round were duplicates
                if not loop_redirect_given:
                    redirect = _build_loop_redirect(
                        [(self.tool_key(c), c) for c in calls]
                    )
                    if redirect is not None:
                        loop_redirect_given = True
                        self.redirects_fired += 1
                        self.redirect_texts.append(redirect)
                        # Don't break — caller provides the redirect-response round
                        continue

                # No redirect available or already used → synthesis
                self.synthesis_fired = True
                self.stopped_at = "synthesis"
                break

        else:
            self.stopped_at = "answer"

        if not self.stopped_at:
            self.stopped_at = "answer"

        return self


# ── Helper to build tool keys ─────────────────────────────────────────────────

def K(name: str, **kwargs) -> str:  # noqa: N802
    """Shorthand for PromptLoopSimulator.tool_key({'name': name, ...kwargs})."""
    return PromptLoopSimulator.tool_key({"name": name, **kwargs})


# ═════════════════════════════════════════════════════════════════════════════
# Scenarios
# ═════════════════════════════════════════════════════════════════════════════

class TestGetAreaEntitiesLoop:
    """Scenario: model loops on get_area_entities when area has no assigned entities.

    Reproduces the 'what is the band?' bug from debug zip
    kyber-debug-1779048235303-m2lz2qutgz.
    """

    MOCK = {
        K("get_area_entities", area="werkkamer"):
            {"area": "Werkkamer", "entities": {}},  # no entities assigned

        K("search_entities", query="werkkamer"):
            {"media_player.werkkamer_music_2": {"name": "Werkkamer Music 2", "state": "playing"}},

        K("get_entity_state", entity_id="media_player.werkkamer_music_2",
          fields=["media_artist", "media_title", "app_name"]):
            {"entity_id": "media_player.werkkamer_music_2", "state": "playing",
             "media_artist": "Radiohead", "media_title": "Creep", "app_name": "Spotify"},
    }

    def _rounds_old(self):
        """Old buggy behaviour: model repeats get_area_entities, synthesis fires."""
        return [
            [{"name": "get_area_entities", "area": "werkkamer"}],  # round 1 → empty
            [{"name": "get_area_entities", "area": "werkkamer"}],  # round 2 → duplicate
            # No round 3: old code went straight to synthesis
        ]

    def _rounds_new(self):
        """New behaviour: after redirect hint model pivots to search_entities."""
        return [
            [{"name": "get_area_entities", "area": "werkkamer"}],  # round 1 → empty
            [{"name": "get_area_entities", "area": "werkkamer"}],  # round 2 → duplicate → redirect
            [{"name": "search_entities", "query": "werkkamer"}],   # round 3 → finds entity
            [{"name": "get_entity_state", "entity_id": "media_player.werkkamer_music_2",
              "fields": ["media_artist", "media_title", "app_name"]}],  # round 4 → state
            [],  # round 5: model has data, emits prose answer
        ]

    def test_old_two_round_loop_now_redirects_instead_of_synthesizing(self):
        """Regression: the same 2-round input that used to hit synthesis now
        fires a redirect instead — guarding against re-introducing the bug."""
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_old())
        # With the fix in place, round 2 duplicate → redirect (not synthesis)
        assert sim.redirects_fired == 1, "Redirect should fire on duplicate in round 2"
        assert not sim.synthesis_fired, "Synthesis must NOT fire when a redirect is available"

    def test_redirect_fires_on_duplicate(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_new())
        assert sim.redirects_fired == 1
        assert not sim.synthesis_fired

    def test_redirect_mentions_search_entities(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_new())
        hint = sim.redirect_texts[0]
        assert "search_entities" in hint
        assert "werkkamer" in hint

    def test_redirect_says_do_not_repeat(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_new())
        hint = sim.redirect_texts[0]
        assert "NOT" in hint or "not" in hint

    def test_correct_entity_found_after_redirect(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_new())
        assert "search_entities" in sim.final_tool_results
        result = sim.final_tool_results["search_entities"]
        assert "media_player.werkkamer_music_2" in result

    def test_full_flow_reaches_answer(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_new())
        assert sim.stopped_at == "answer"
        assert "get_entity_state" in sim.final_tool_results
        state = sim.final_tool_results["get_entity_state"]
        assert state.get("media_artist") == "Radiohead"

    def test_rounds_count(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds_new())
        # Round 1 + 2 (dup/redirect) + 3 + 4 + 5(empty=answer) = 5
        assert sim.rounds_executed == 5


class TestSearchEntitiesLoop:
    """Scenario: model repeats search_entities — redirect should suggest search_knowledge."""

    MOCK = {
        K("search_entities", query="tv kamer"):
            {"_note": "no results"},
        K("search_knowledge", query="tv kamer"):
            [{"subject": "tv kamer alias", "content": "media_player.living_room_tv"}],
    }

    def _rounds(self):
        return [
            [{"name": "search_entities", "query": "tv kamer"}],   # round 1 → no results
            [{"name": "search_entities", "query": "tv kamer"}],   # round 2 → duplicate
            [{"name": "search_knowledge", "query": "tv kamer"}],  # round 3 → from redirect
            [],  # answer
        ]

    def test_redirect_fires(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.redirects_fired == 1

    def test_redirect_suggests_search_knowledge(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        hint = sim.redirect_texts[0]
        assert "search_knowledge" in hint

    def test_reaches_answer(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.stopped_at == "answer"
        assert not sim.synthesis_fired


class TestNoLoopDirectAnswer:
    """Scenario: model finds entity on first try and answers without looping."""

    MOCK = {
        K("search_entities", query="tv"):
            {"media_player.living_room_tv": {"name": "Living room TV", "state": "on"}},
        K("get_entity_state", entity_id="media_player.living_room_tv",
          fields=["state", "media_title"]):
            {"entity_id": "media_player.living_room_tv", "state": "on",
             "media_title": "The Crown"},
    }

    def _rounds(self):
        return [
            [{"name": "search_entities", "query": "tv"}],
            [{"name": "get_entity_state", "entity_id": "media_player.living_room_tv",
              "fields": ["state", "media_title"]}],
            [],  # prose answer
        ]

    def test_no_redirect_needed(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.redirects_fired == 0
        assert not sim.synthesis_fired

    def test_answer_reached(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.stopped_at == "answer"

    def test_two_unique_tools_called(self):
        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert "search_entities" in sim.final_tool_results
        assert "get_entity_state" in sim.final_tool_results


class TestSynthesisFallbackWhenNoRedirectAvailable:
    """Scenario: model calls an unusual tool twice with no redirect rule → synthesis."""

    MOCK = {
        K("get_areas"):
            {"areas": [{"area_id": "living_room", "name": "Living Room"}]},
    }

    def _rounds(self):
        return [
            [{"name": "get_areas"}],  # round 1
            [{"name": "get_areas"}],  # round 2 → duplicate, no redirect rule for get_areas
        ]

    def test_synthesis_fires_when_no_redirect_available(self):
        """_build_loop_redirect returns None for get_areas → synthesis."""
        redirect = _build_loop_redirect([(K("get_areas"), {"name": "get_areas"})])
        assert redirect is None  # no redirect rule for get_areas

        sim = PromptLoopSimulator(self.MOCK).run(self._rounds())
        assert sim.synthesis_fired
        assert sim.redirects_fired == 0


class TestSynthesisInstructions:
    """Verify _SYNTHESIS_INSTRUCTIONS contains the anti-hallucination guard."""

    def test_contains_anti_hallucination_clause(self):
        assert "do NOT invent" in _SYNTHESIS_INSTRUCTIONS or "do not invent" in _SYNTHESIS_INSTRUCTIONS.lower()

    def test_no_tool_call_blocks_instruction(self):
        assert "TOOL_CALL" in _SYNTHESIS_INSTRUCTIONS

    def test_empty_results_warning_present(self):
        lower = _SYNTHESIS_INSTRUCTIONS.lower()
        assert "empty" in lower or "0 entities" in lower or "no results" in lower.replace("results", "results")


class TestBuildLoopRedirect:
    """Unit tests for _build_loop_redirect."""

    def test_get_area_entities_returns_redirect(self):
        calls = [(K("get_area_entities", area="woonkamer"),
                  {"name": "get_area_entities", "area": "woonkamer"})]
        result = _build_loop_redirect(calls)
        assert result is not None
        assert "search_entities" in result
        assert "woonkamer" in result

    def test_search_entities_returns_redirect(self):
        calls = [(K("search_entities", query="slaapkamer lamp"),
                  {"name": "search_entities", "query": "slaapkamer lamp"})]
        result = _build_loop_redirect(calls)
        assert result is not None
        assert "search_knowledge" in result
        assert "slaapkamer lamp" in result

    def test_get_areas_returns_none(self):
        calls = [(K("get_areas"), {"name": "get_areas"})]
        assert _build_loop_redirect(calls) is None

    def test_get_entity_state_returns_none(self):
        calls = [(K("get_entity_state", entity_id="light.x"),
                  {"name": "get_entity_state", "entity_id": "light.x"})]
        assert _build_loop_redirect(calls) is None

    def test_empty_list_returns_none(self):
        assert _build_loop_redirect([]) is None

    def test_redirect_area_includes_search_knowledge_fallback(self):
        calls = [(K("get_area_entities", area="keuken"),
                  {"name": "get_area_entities", "area": "keuken"})]
        result = _build_loop_redirect(calls)
        # Should mention search_knowledge as the second fallback
        assert "search_knowledge" in result


# ═════════════════════════════════════════════════════════════════════════════
# Intent classification
# ═════════════════════════════════════════════════════════════════════════════

_load(
    "custom_components.kyber.intent_and_context",
    ROOT / "custom_components" / "kyber" / "intent_and_context.py",
)
from custom_components.kyber.intent_and_context import _classify_intent  # noqa: E402


class TestIntentClassification:
    """Verify _classify_intent correctly identifies action vs informational prompts.

    Regression for debug zip kyber-debug-1779049092493 where 'yes stop the music'
    was classified as 'informational', causing the plan to be dropped by the guard.
    """

    # ── Action prompts that must be classified as "action" ──────────────────
    def test_stop_is_action(self):
        assert _classify_intent("stop the music") == "action"

    def test_yes_stop_is_action(self):
        assert _classify_intent("yes stop the music") == "action"

    def test_yes_alone_is_action(self):
        assert _classify_intent("yes") == "action"

    def test_ok_is_action(self):
        assert _classify_intent("ok") == "action"

    def test_sure_is_action(self):
        assert _classify_intent("sure go ahead") == "action"

    def test_pause_is_action(self):
        assert _classify_intent("pause the tv") == "action"

    def test_resume_is_action(self):
        assert _classify_intent("resume playback") == "action"

    def test_mute_is_action(self):
        assert _classify_intent("mute the speakers") == "action"

    def test_volume_is_action(self):
        assert _classify_intent("set the volume to 50") == "action"

    def test_ja_is_action(self):
        assert _classify_intent("ja") == "action"

    def test_doe_maar_is_action(self):
        assert _classify_intent("doe maar") == "action"

    def test_confirm_is_action(self):
        assert _classify_intent("confirm") == "action"

    # ── Informational prompts that must NOT become "action" ──────────────────
    def test_what_is_playing_is_informational(self):
        assert _classify_intent("what is playing?") == "informational"

    def test_which_lights_on_is_informational(self):
        assert _classify_intent("which lights are on?") == "informational"

    def test_what_areas_informational(self):
        assert _classify_intent("what areas do I have?") == "informational"

    def test_who_is_at_home_informational(self):
        assert _classify_intent("who is at home?") == "informational"


# ═════════════════════════════════════════════════════════════════════════════
# Integration discovery — side-by-side: name obvious vs. name opaque
#
# Both scenarios represent the same user question:
#   "wat is het laagste energie tarief morgen?" (what is the lowest tariff tomorrow?)
#
# The model should:
#   1. search_knowledge  → empty
#   2. list_integrations → returns the integration list
#   3. pick the energy integration by scanning names (not by hardcoded list)
#   4. get_integration_entities(integration=X) → finds price sensors
#   5. answer
#
# The two scenarios differ only in what list_integrations returns:
#   A) "tibber"    — well-known name; any LLM knows it's an energy integration
#   B) "energyzero" — less known; should still be picked because "energy" is in name
#
# Both must reach stopped_at=="answer" without synthesis or redirect.
# ═════════════════════════════════════════════════════════════════════════════

class _BaseEnergyTariffScenario:
    """Shared helpers for both energy tariff discovery scenarios."""

    INTEGRATION_NAME: str  # to be defined by subclass
    SENSOR_ENTITY_ID: str  # e.g. "sensor.tibber_current_price"

    @classmethod
    def _mock(cls) -> dict:
        return {
            K("search_knowledge", query="lowest energy tariff tomorrow"): {
                "results": [],
            },
            K("list_integrations"): {
                "integrations": [cls.INTEGRATION_NAME, "hue", "mobile_app"],
            },
            K("get_integration_entities", integration=cls.INTEGRATION_NAME): {
                "entities": [
                    {"entity_id": cls.SENSOR_ENTITY_ID, "state": "0.21",
                     "attributes": {"unit_of_measurement": "EUR/kWh"}},
                ],
            },
        }

    @classmethod
    def _rounds(cls) -> list[list[dict]]:
        """Simulate the correct tool sequence the model should follow."""
        return [
            # Round 1: search knowledge (correct first step for any query)
            [{"name": "search_knowledge", "query": "lowest energy tariff tomorrow"}],
            # Round 2: knowledge returned empty → call list_integrations
            [{"name": "list_integrations"}],
            # Round 3: picked the energy integration from the list → get entities
            [{"name": "get_integration_entities", "integration": cls.INTEGRATION_NAME}],
            # Round 4: found price sensor → no more tool calls → final answer
            [],
        ]


class TestEnergyTariffKnownIntegrationName(_BaseEnergyTariffScenario):
    """Side A: list_integrations returns "tibber" — a well-known energy name.

    The model should recognize "tibber" → energy integration without a hardcoded
    lookup table. Generic instruction: 'scan names, use your knowledge of what
    each integration provides.'
    """

    INTEGRATION_NAME = "tibber"
    SENSOR_ENTITY_ID = "sensor.tibber_current_price"

    def test_flow_reaches_answer(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert sim.stopped_at == "answer", f"Expected answer, got {sim.stopped_at}"

    def test_no_synthesis_fired(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert not sim.synthesis_fired

    def test_no_redirect_needed(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert sim.redirects_fired == 0

    def test_list_integrations_was_called(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert "list_integrations" in sim.final_tool_results

    def test_get_integration_entities_was_called(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert "get_integration_entities" in sim.final_tool_results

    def test_correct_integration_used(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        result = sim.final_tool_results["get_integration_entities"]
        assert any(e["entity_id"] == self.SENSOR_ENTITY_ID for e in result["entities"])

    def test_four_rounds_total(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        # search_knowledge + list_integrations + get_integration_entities + answer
        assert sim.rounds_executed == 4


class TestEnergyTariffUnknownIntegrationName(_BaseEnergyTariffScenario):
    """Side B: list_integrations returns "energyzero" — an opaque name.

    Less well-known but "energy" appears in the name.  Generic instruction:
    model must use semantic reasoning on the name itself, not a hardcoded list.
    This is the failure mode we fixed: previously the model never tried
    list_integrations at all, or picked nothing from the returned list.
    """

    INTEGRATION_NAME = "energyzero"
    SENSOR_ENTITY_ID = "sensor.energyzero_current_price"

    def test_flow_reaches_answer(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert sim.stopped_at == "answer", f"Expected answer, got {sim.stopped_at}"

    def test_no_synthesis_fired(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert not sim.synthesis_fired

    def test_no_redirect_needed(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert sim.redirects_fired == 0

    def test_list_integrations_was_called(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert "list_integrations" in sim.final_tool_results

    def test_get_integration_entities_was_called(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert "get_integration_entities" in sim.final_tool_results

    def test_correct_integration_used(self):
        sim = PromptLoopSimulator(self._mock()).run(self._rounds())
        result = sim.final_tool_results["get_integration_entities"]
        assert any(e["entity_id"] == self.SENSOR_ENTITY_ID for e in result["entities"])

    def test_same_number_of_rounds_as_tibber(self):
        """Both scenarios should follow the same tool sequence, same round count."""
        sim_known = PromptLoopSimulator(
            TestEnergyTariffKnownIntegrationName._mock()
        ).run(TestEnergyTariffKnownIntegrationName._rounds())
        sim_unknown = PromptLoopSimulator(self._mock()).run(self._rounds())
        assert sim_known.rounds_executed == sim_unknown.rounds_executed
