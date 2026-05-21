"""Tests for _try_quick_intent and _classify_intent in intent_and_context.py.

These tests exercise the regex-only intent parser without needing HA. We
import a tiny shim that only loads the regex + helper.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path


def _load_helpers():
    """Extract the helper + regex from intent_and_context.py without importing HA."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "custom_components" / "kyber" / "intent_and_context.py").read_text(encoding="utf-8")
    src = src.replace("\r\n", "\n")
    start = src.index("_QUICK_CREATE_AREA_RE = re.compile(")
    func_start = src.index("def _try_quick_intent", start)
    end = src.index("\n\n\n", func_start)
    snippet = src[start:end]
    ns: dict = {"re": re, "json": __import__("json")}
    snippet = "from typing import Any\n" + snippet
    exec(snippet, ns)
    return ns


def _load_classify():
    """Extract _classify_intent and its deps from intent_and_context.py."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "custom_components" / "kyber" / "intent_and_context.py").read_text(encoding="utf-8")
    src = src.replace("\r\n", "\n")
    start = src.index("_ACTION_KEYWORDS")
    end = src.index("\n\n\n", src.index("def _classify_intent"))
    snippet = "from __future__ import annotations\nimport re\nfrozenset = frozenset\n" + src[start:end]
    ns: dict = {"re": re, "frozenset": frozenset}
    exec(snippet, ns)
    return ns["_classify_intent"]


def test_quick_intent_matches_basic_create():
    ns = _load_helpers()
    out = ns["_try_quick_intent"]("create an area outside")
    assert out is not None
    assert out["shortcut"] == "quick_create_area"
    assert out["plan"]["actions"][0]["type"] == "create_area"
    assert out["plan"]["actions"][0]["name"] == "outside"
    assert "entity_id" not in out["plan"]["actions"][0]


def test_quick_intent_matches_variants():
    ns = _load_helpers()
    cases = [
        ("create an area garage", "garage"),
        ("create area office", "office"),
        ("add area Garden", "Garden"),
        ("make a new area called Loft", "Loft"),
        ("new area Attic", "Attic"),
        ("please create an area basement", "basement"),
        ("Can you create an area called Sun Room?", "Sun Room"),
    ]
    for prompt, expected_name in cases:
        out = ns["_try_quick_intent"](prompt)
        assert out is not None, f"Failed to match: {prompt!r}"
        assert out["plan"]["actions"][0]["name"] == expected_name, prompt


def test_quick_intent_skips_non_matches():
    ns = _load_helpers()
    for prompt in [
        "what areas do I have?",
        "show me the areas",
        "delete area outside",  # delete not handled here
        "rename area kitchen to keuken",
        "turn on the light in outside",
        "",
        "   ",
        "create",
        "area",
    ]:
        assert ns["_try_quick_intent"](prompt) is None, f"Should NOT match: {prompt!r}"


def test_quick_intent_rejects_generic_name():
    ns = _load_helpers()
    # "create an area area" — name resolves to "area" which we reject
    assert ns["_try_quick_intent"]("create an area area") is None


def test_quick_intent_skips_multiline():
    ns = _load_helpers()
    # Multi-line prompts with extra instructions must go to the AI, not quick-intent
    multiline_cases = [
        "create an area Yard\nmake it a dutch name because my home is dutch",
        "create an area Garden\nplease use a nice name",
        "add area Test\nwith some extra context",
    ]
    for prompt in multiline_cases:
        assert ns["_try_quick_intent"](prompt) is None, (
            f"Should NOT match multi-line prompt: {prompt!r}"
        )


def test_quick_intent_response_text_includes_plan_block():
    ns = _load_helpers()
    out = ns["_try_quick_intent"]("create area outside")
    assert "```plan" in out["response_text"]
    assert "outside" in out["response_text"]
    assert "create_area" in out["response_text"]


def test_quick_intent_make_area_variant():
    """Regression: 'make area tuin' was dropping the plan due to 'make' missing from action keywords."""
    ns = _load_helpers()
    out = ns["_try_quick_intent"]("make area tuin")
    assert out is not None
    assert out["shortcut"] == "quick_create_area"
    assert out["plan"]["actions"][0]["name"] == "tuin"
    assert out["intent"] == "action"


# ── _classify_intent tests ────────────────────────────────────────────────────

class TestClassifyIntent:
    """_classify_intent must return 'action' for commands, 'informational' for questions."""

    def _classify(self, prompt: str) -> str:
        return _load_classify()(prompt)

    # ── English action phrases ─────────────────────────────────────────────────

    def test_turn_on_english(self):
        assert self._classify("turn on the kitchen lights") == "action"

    def test_turn_off_english(self):
        assert self._classify("turn off all lights") == "action"

    def test_set_english(self):
        assert self._classify("set the thermostat to 21") == "action"

    def test_dim_english(self):
        assert self._classify("dim the living room") == "action"

    # ── Dutch action phrases ───────────────────────────────────────────────────

    def test_zet_aan_dutch(self):
        assert self._classify("zet de werkkamer lichten aan") == "action"

    def test_zet_uit_dutch(self):
        assert self._classify("zet het licht in de keuken uit") == "action"

    def test_aan_doen_regression(self):
        """Regression: 'kan je nu de werkkamer muziek aan doen' was misclassified as informational."""
        assert self._classify("kan je nu de werkkamer muziek aan doen") == "action"

    def test_uit_doen_dutch(self):
        assert self._classify("kan je de muziek uit doen") == "action"

    def test_doe_aan_dutch(self):
        assert self._classify("doe het licht aan") == "action"

    def test_doe_uit_dutch(self):
        assert self._classify("doe de TV uit") == "action"

    def test_aanzetten_one_word(self):
        assert self._classify("muziek aanzetten") == "action"

    def test_uitzetten_one_word(self):
        assert self._classify("lichten uitzetten") == "action"

    def test_muziek_aan_doen_short(self):
        assert self._classify("muziek aan doen") == "action"

    def test_kan_je_music_aan(self):
        assert self._classify("kan je de muziek aan doen in de woonkamer") == "action"

    # ── Informational phrases ──────────────────────────────────────────────────

    def test_what_lights_informational(self):
        assert self._classify("what lights do I have?") == "informational"

    def test_welke_lampen_informational(self):
        assert self._classify("welke lampen heb ik?") == "informational"

    def test_show_areas_informational(self):
        assert self._classify("show me all areas") == "informational"

    def test_empty_informational(self):
        assert self._classify("") == "informational"

    def test_status_query_informational(self):
        assert self._classify("is the front door open?") == "informational"

    # ── False-positive regression tests (#113) ────────────────────────────────

    def test_tell_me_if_light_on_informational(self):
        """'tell me if the light is on' must not be classified as action (keyword 'on')."""
        assert self._classify("tell me if the light is on") == "informational"

    def test_tell_me_which_on_informational(self):
        assert self._classify("tell me which lights are on") == "informational"

    def test_what_does_turn_on_informational(self):
        """'what does turn on do' starts with 'what' → informational."""
        assert self._classify("what does turn on do?") == "informational"

    def test_show_me_whats_playing_informational(self):
        assert self._classify("show me what's playing") == "informational"

    def test_is_the_light_on_informational(self):
        assert self._classify("is the light on?") == "informational"

    def test_are_the_lights_on_informational(self):
        assert self._classify("are the lights on?") == "informational"

    def test_does_the_tv_turn_on_informational(self):
        assert self._classify("does the TV turn on automatically?") == "informational"

    def test_what_time_lights_turn_on_informational(self):
        assert self._classify("what time should the lights turn on?") == "informational"

    def test_how_many_lights_on_informational(self):
        assert self._classify("how many lights are on?") == "informational"

    def test_which_devices_on_informational(self):
        assert self._classify("which devices are on right now?") == "informational"

    def test_turn_on_still_action(self):
        """Core action commands must still be classified as action after the fix."""
        assert self._classify("turn on the kitchen lights") == "action"

    def test_turn_off_still_action(self):
        assert self._classify("turn off the living room lights") == "action"

    def test_switch_on_still_action(self):
        assert self._classify("switch on the fan") == "action"
