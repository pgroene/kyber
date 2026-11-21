"""The fallback reply when the model produced no text was hard-coded: Dutch
after the tool loop ran out of rounds, English after the synthesis pass. It now
follows the language of the prompt, or the Home Assistant language when the
prompt is too short to tell (e.g. "prüfe die IDs").
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.kyber.http_api import _NO_ANSWER_MESSAGES, _no_answer_message


def _hass(language: str) -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(language=language))


def test_short_german_prompt_uses_ha_language() -> None:
    msg = _no_answer_message(_hass("de"), "prüfe die IDs", "no_answer")
    assert msg == _NO_ANSWER_MESSAGES["no_answer"]["de"]
    assert "Ik kon" not in msg


def test_detected_prompt_language_wins() -> None:
    msg = _no_answer_message(_hass("de"), "zet de lamp aan in de keuken", "no_answer")
    assert msg == _NO_ANSWER_MESSAGES["no_answer"]["nl"]


def test_regional_ha_language_and_unknown_language() -> None:
    assert _no_answer_message(_hass("de-CH"), "ok", "no_action") == _NO_ANSWER_MESSAGES["no_action"]["de"]
    assert _no_answer_message(_hass("fi"), "ok", "no_action") == _NO_ANSWER_MESSAGES["no_action"]["en"]


def test_german_texts_follow_the_style_rules() -> None:
    for texts in _NO_ANSWER_MESSAGES.values():
        assert "—" not in texts["de"]
        assert set(texts) == {"en", "nl", "de"}
