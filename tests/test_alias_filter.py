"""Tests for _alias_is_plausible and statement intent classification."""
import re
import pytest
from custom_components.kyber.entity_narrator import _alias_is_plausible
from custom_components.kyber.intent_and_context import _classify_intent


# ── _alias_is_plausible ─────────────────────────────────────────────────────

def test_tv_child_lock_rejects_coffee_alias():
    """TV child-lock switch must NOT accept 'coffee maker' alias."""
    assert not _alias_is_plausible(
        "coffee maker",
        "switch.onoff_tv_221_child_lock",
        "Child lock switch for television [switch.onoff_tv_221_child_lock]",
        "TV 221",
    )


def test_tv_child_lock_rejects_espresso_alias():
    assert not _alias_is_plausible(
        "espresso machine control",
        "switch.onoff_tv_221_child_lock",
        "Child lock switch for television [switch.onoff_tv_221_child_lock]",
        "TV 221",
    )


def test_tv_child_lock_accepts_tv_alias():
    assert _alias_is_plausible(
        "television child lock",
        "switch.onoff_tv_221_child_lock",
        "Child lock switch for television [switch.onoff_tv_221_child_lock]",
        "TV 221",
    )


def test_espresso_entity_accepts_espresso_alias():
    assert _alias_is_plausible(
        "espresso machine",
        "switch.onoff_keuken_espresso_304",
        "Espresso machine in kitchen [switch.onoff_keuken_espresso_304]",
        "keuken espresso",
    )


def test_empty_term_is_plausible():
    """Empty term should pass (upstream handles it)."""
    assert _alias_is_plausible("", "switch.test", "A test switch [switch.test]", "Test")


def test_short_tokens_only_passes():
    """Term with only short/stop words should pass (no meaningful tokens to reject)."""
    assert _alias_is_plausible("on", "switch.test", "A test [switch.test]", "Test")


def test_manufacturer_match_allows_alias():
    """Alias that matches manufacturer name should be accepted."""
    assert _alias_is_plausible(
        "philips hue bulb",
        "light.abc123_light",
        "A smart light [light.abc123_light]",
        "ABC Light",
        "Philips",
    )


# ── _classify_intent — statement location patterns ──────────────────────────

def test_dutch_staat_in_is_action():
    """'de espresso machine staat in de keuken' should be ACTION."""
    assert _classify_intent("de espresso machine staat in de keuken") == "action"


def test_dutch_zit_in_is_action():
    assert _classify_intent("de router zit in de hal") == "action"


def test_dutch_hangt_in_is_action():
    assert _classify_intent("de speaker hangt in de woonkamer") == "action"


def test_english_is_in_the_room_is_action():
    assert _classify_intent("the sensor is in the bedroom") == "action"


def test_english_belongs_in_is_action():
    assert _classify_intent("the thermostat belongs in the hallway") == "action"


def test_informational_question_still_informational():
    """'wat zijn de lampen in de woonkamer' must remain informational."""
    assert _classify_intent("wat zijn de lampen in de woonkamer") == "informational"


def test_simple_status_question_informational():
    assert _classify_intent("is the light on?") == "informational"


def test_turn_on_still_action():
    assert _classify_intent("turn on the living room lights") == "action"
