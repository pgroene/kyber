"""Tests for language_hints: detection, hint data integrity, and injection."""

import importlib.util
import sys
from pathlib import Path
import pytest

# language_hints.py has no HA deps — load it directly
_root = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "language_hints",
    _root / "custom_components" / "kyber" / "language_hints.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

LANGUAGE_HINTS = _mod.LANGUAGE_HINTS
LANG_HINTS_VERSION = _mod.LANG_HINTS_VERSION
LangHintEntry = _mod.LangHintEntry
detect_language = _mod.detect_language
get_hints_for_language = _mod.get_hints_for_language
language_display_name = _mod.language_display_name


# ── Data integrity ───────────────────────────────────────────────────────────

class TestLanguageHintsData:
    def test_all_languages_have_name(self):
        for code, lang in LANGUAGE_HINTS.items():
            assert isinstance(lang["name"], str) and lang["name"], f"{code}: missing name"

    def test_all_languages_have_markers(self):
        for code, lang in LANGUAGE_HINTS.items():
            assert isinstance(lang["markers"], set) and len(lang["markers"]) >= 5, \
                f"{code}: not enough markers"

    def test_all_languages_have_hints(self):
        for code, lang in LANGUAGE_HINTS.items():
            assert len(lang["hints"]) >= 3, f"{code}: too few hints"

    def test_all_hints_are_namedtuple(self):
        for code, lang in LANGUAGE_HINTS.items():
            for h in lang["hints"]:
                assert isinstance(h, LangHintEntry), f"{code}: hint is not LangHintEntry"
                assert h.subject and h.content

    def test_hint_subjects_unique_per_language(self):
        for code, lang in LANGUAGE_HINTS.items():
            subjects = [h.subject for h in lang["hints"]]
            assert len(subjects) == len(set(subjects)), f"{code}: duplicate subjects"

    def test_version_is_positive_int(self):
        assert isinstance(LANG_HINTS_VERSION, int) and LANG_HINTS_VERSION >= 1

    def test_expected_languages_present(self):
        for code in ("nl", "de", "fr", "es", "it", "pt"):
            assert code in LANGUAGE_HINTS, f"Missing language: {code}"


# ── Language detection ───────────────────────────────────────────────────────

class TestDetectLanguage:
    def test_dutch_basic(self):
        assert detect_language("kan je het licht aan doen") == "nl"

    def test_dutch_turn_off(self):
        assert detect_language("zet de verwarming uit aub") == "nl"

    def test_dutch_music(self):
        assert detect_language("kan je de werkkamer muziek aan doen") == "nl"

    def test_german_basic(self):
        assert detect_language("kannst du das Licht einschalten bitte") == "de"

    def test_french_basic(self):
        assert detect_language("allume la lumière dans le salon") == "fr"

    def test_spanish_basic(self):
        assert detect_language("enciende las luces del salon por favor") == "es"

    def test_italian_basic(self):
        assert detect_language("accendi la luce nel soggiorno per favore") == "it"

    def test_portuguese_basic(self):
        assert detect_language("liga a luz da sala por favor") == "pt"

    def test_english_returns_en(self):
        assert detect_language("turn on the living room lights") == "en"

    def test_empty_returns_en(self):
        assert detect_language("") == "en"

    def test_single_word_returns_en(self):
        # Not enough markers to confidently identify a language
        assert detect_language("aan") == "en"

    def test_requires_two_markers(self):
        # Only one Dutch marker — should not trigger
        assert detect_language("het") == "en"

    def test_none_equivalent(self):
        # Non-word input
        assert detect_language("123 456 789") == "en"


# ── get_hints_for_language ───────────────────────────────────────────────────

class TestGetHintsForLanguage:
    def test_returns_list_for_known_language(self):
        hints = get_hints_for_language("nl")
        assert isinstance(hints, list) and len(hints) > 0

    def test_returns_empty_for_english(self):
        assert get_hints_for_language("en") == []

    def test_returns_empty_for_unknown(self):
        assert get_hints_for_language("xx") == []

    def test_all_hints_are_lang_hint_entry(self):
        for code in LANGUAGE_HINTS:
            for h in get_hints_for_language(code):
                assert isinstance(h, LangHintEntry)

    def test_does_not_mutate_source(self):
        h1 = get_hints_for_language("nl")
        h2 = get_hints_for_language("nl")
        assert h1 is not h2  # returns a new list each time


# ── language_display_name ────────────────────────────────────────────────────

class TestLanguageDisplayName:
    def test_known_languages(self):
        assert language_display_name("nl") == "Dutch"
        assert language_display_name("de") == "German"
        assert language_display_name("fr") == "French"
        assert language_display_name("es") == "Spanish"
        assert language_display_name("it") == "Italian"
        assert language_display_name("pt") == "Portuguese"

    def test_unknown_returns_code(self):
        assert language_display_name("zz") == "zz"

    def test_english_returns_en(self):
        # "en" is not in LANGUAGE_HINTS (it's the default)
        assert language_display_name("en") == "en"
