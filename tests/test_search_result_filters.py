"""Post-filters applied to search_entities results inside the AI loop.

1. The on/off state filter used substring checks ("aan" in "staan", "uit" in
   "buiten") and ran for informational prompts too, so "Welke deuren staan open?"
   was filtered down to closed doors.
2. The seen-entity exclusion compared missing scores (0 <= 0) and dropped every
   entity a previous search had shown, so a follow-up search with other fields
   returned only "All matches already shown".
"""
import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="requires pytest-homeassistant-custom-component",
)

from custom_components.kyber.http_api import (
    _detect_switch_request,
    _drop_already_seen_entities,
    _record_seen_entity_scores,
)
from custom_components.kyber.intent_and_context import _classify_intent


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        # informational questions containing "aan"/"uit" inside other words
        ("Welke deuren staan open?", None),
        ("Wat is de temperatuur buiten?", None),
        ("Is de ruit van de keuken kapot?", None),
        ("Waar gaan de rolluiken naartoe?", None),
        # real switch requests
        ("zet de keukenlamp uit", "off"),
        ("zet de keukenlamp aan", "on"),
        ("doe de lamp in de woonkamer uit", "off"),
        ("turn off the kitchen light", "off"),
        ("turn on the kitchen light", "on"),
        # both directions → ambiguous
        ("zet de lamp aan en de tv uit", None),
    ],
)
def test_detect_switch_request(prompt, expected) -> None:
    assert _detect_switch_request(prompt, _classify_intent(prompt)) == expected


def test_detect_switch_request_ignores_informational_intent() -> None:
    assert _detect_switch_request("is de lamp aan", "informational") is None
    assert _detect_switch_request("zet de lamp aan", "informational") is None


def test_follow_up_search_without_scores_keeps_entities() -> None:
    seen: dict[str, float] = {}
    round1 = {"light.kitchen": {"state": "on"}, "light.hall": {"state": "off"}}
    _record_seen_entity_scores(round1, seen)

    round2 = {"light.kitchen": {"state": "on", "brightness": 200}, "light.hall": {"state": "off"}}
    data, dropped = _drop_already_seen_entities(round2, seen)
    assert dropped == 0
    assert data["light.kitchen"]["brightness"] == 200
    assert "_note" not in data


def test_scored_rows_dropped_only_without_improvement() -> None:
    seen: dict[str, float] = {}
    _record_seen_entity_scores({"automation.a": {"_score": 0.8}, "automation.b": {"_score": 0.5}}, seen)

    data, dropped = _drop_already_seen_entities(
        {"automation.a": {"_score": 0.8}, "automation.b": {"_score": 0.9}, "automation.c": {"_score": 0.1}},
        seen,
    )
    assert dropped == 1
    assert "automation.a" not in data
    assert "automation.b" in data  # improved score is kept
    assert "automation.c" in data  # never seen before


def test_all_dropped_adds_note() -> None:
    seen = {"automation.a": 0.9}
    data, dropped = _drop_already_seen_entities({"automation.a": {"_score": 0.5}}, seen)
    assert dropped == 1
    assert data == {"_note": "All matches already shown in a previous round with equal or better relevance."}
