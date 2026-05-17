"""Tests for the _STOPWORDS set and _tokens() helper in analyzer.py — issue #121.

Verifies that Dutch function words are correctly filtered when tokenising
automation/scene names so they don't produce false area inferences.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# HA stubs (analyzer.py imports homeassistant.core)
# ---------------------------------------------------------------------------
_STUBS = [
    "homeassistant", "homeassistant.core", "homeassistant.components",
    "homeassistant.helpers", "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry",
]
for _m in _STUBS:
    sys.modules.setdefault(_m, types.ModuleType(_m))


class _HAStub:
    pass


sys.modules["homeassistant.core"].HomeAssistant = _HAStub  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Load the module
# ---------------------------------------------------------------------------
_root = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "kyber_analyzer",
    _root / "custom_components" / "kyber" / "analyzer.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_tokens = _mod._tokens
_STOPWORDS = _mod._STOPWORDS


# ---------------------------------------------------------------------------
# _STOPWORDS membership
# ---------------------------------------------------------------------------

class TestStopwordsContent:
    DUTCH_FUNCTION_WORDS = [
        "de", "het", "een", "in", "op", "aan", "uit", "van", "met", "en",
        "of", "als", "dan", "dat", "die", "dit", "ze", "zijn", "wordt",
        "door", "bij", "om", "te", "er", "ik", "je", "we", "zet",
        "doe", "maak", "ga", "gaat", "naar", "ook", "niet", "mijn", "nu",
        "al", "nog", "wel", "geen", "zo", "wat", "wie", "hoe", "waar",
        "ben", "heeft", "hebben", "was", "waren",
    ]

    ENGLISH_STOPWORDS = [
        "automation", "scene", "script", "the", "and", "or", "if",
        "for", "to", "with", "an", "my", "all", "any", "at", "by", "up", "do",
    ]

    def test_dutch_words_in_stopwords(self):
        for word in self.DUTCH_FUNCTION_WORDS:
            assert word in _STOPWORDS, f"Expected Dutch stopword '{word}' to be in _STOPWORDS"

    def test_english_words_in_stopwords(self):
        for word in self.ENGLISH_STOPWORDS:
            assert word in _STOPWORDS, f"Expected English stopword '{word}' to be in _STOPWORDS"

    def test_all_stopwords_are_lowercase(self):
        for word in _STOPWORDS:
            assert word == word.lower(), f"Stopword '{word}' is not lowercase"

    def test_no_empty_strings(self):
        assert "" not in _STOPWORDS


# ---------------------------------------------------------------------------
# _tokens() behaviour
# ---------------------------------------------------------------------------

class TestTokens:
    def test_empty_string_returns_empty(self):
        assert _tokens("") == []

    def test_none_equivalent_empty(self):
        # _tokens accepts empty string; None is not passed by callers but guard anyway
        assert _tokens("") == []

    def test_dutch_function_words_filtered(self):
        # "zet de lamp in de woonkamer aan" → only meaningful tokens remain
        result = _tokens("zet de lamp in de woonkamer aan")
        assert "de" not in result
        assert "in" not in result
        assert "aan" not in result
        assert "zet" not in result
        assert "lamp" in result
        assert "woonkamer" in result

    def test_english_stopwords_filtered(self):
        result = _tokens("turn on the lights in the living room")
        assert "the" not in result
        assert "on" not in result
        assert "turn" not in result
        assert "in" not in result
        # "living" and "room" are NOT stopwords → should remain
        assert "living" in result
        assert "room" in result

    def test_digits_filtered(self):
        result = _tokens("scene_1_living_room")
        assert "1" not in result

    def test_separator_splitting(self):
        # Underscores, hyphens, dots, spaces all split
        result = _tokens("woonkamer.licht_groep-avond")
        assert "woonkamer" in result
        assert "licht" in result
        assert "groep" in result
        assert "avond" in result

    def test_room_name_survives_dutch_sentence(self):
        # "doe de lampen in de badkamer uit" → badkamer should survive
        result = _tokens("doe de lampen in de badkamer uit")
        assert "badkamer" in result
        assert "lampen" in result
        assert "doe" not in result
        assert "de" not in result
        assert "in" not in result
        assert "uit" not in result

    def test_mixed_case_normalised(self):
        result = _tokens("WoonKamer Licht")
        assert "woonkamer" in result
        assert "licht" in result

    def test_typical_automation_name_dutch(self):
        # "Lichten woonkamer aan bij zonsondergang"
        result = _tokens("Lichten woonkamer aan bij zonsondergang")
        assert "lichten" in result
        assert "woonkamer" in result
        assert "zonsondergang" in result
        # "aan" and "bij" are stopwords → must not appear
        assert "aan" not in result
        assert "bij" not in result

    def test_typical_automation_name_english(self):
        result = _tokens("Turn on lights in the living room")
        # "turn", "on", "lights", "in", "the" are all stopwords
        assert "turn" not in result
        assert "on" not in result
        assert "the" not in result
        assert "in" not in result
        # "living" and "room" should survive
        assert "living" in result
        assert "room" in result

    def test_entity_id_style_input(self):
        # Many callers pass entity-id fragments like "light.woonkamer_spots"
        result = _tokens("light.woonkamer_spots")
        assert "woonkamer" in result
        assert "spots" in result
        # "light" is a stopword
        assert "light" not in result

    def test_all_stopwords_produce_empty_result(self):
        sentence = " ".join(_STOPWORDS)
        result = _tokens(sentence)
        assert result == [], f"Expected empty but got: {result}"
