from __future__ import annotations

from types import SimpleNamespace

from custom_components.kyber.http_api import _CORRECTION_SIGNALS_RE
from custom_components.kyber.knowledge_integration import _try_extract_learned_fact


def test_correction_signal_regex_matches_equivalence_statements() -> None:
    assert _CORRECTION_SIGNALS_RE.search("koffie en espresso zijn voor hier in huis hetzelfde")
    assert _CORRECTION_SIGNALS_RE.search("coffee is hetzelfde als espresso")
    assert _CORRECTION_SIGNALS_RE.search("coffee and espresso are the same here")


async def test_try_extract_learned_fact_returns_alias_and_routine(hass, monkeypatch) -> None:
    async def _fake_ai_call(*args, **kwargs):
        return SimpleNamespace(data="""
        [
          {"type": "alias", "subject": "switch.espresso", "user_term": "koffie", "content": "When user says 'koffie' they mean 'switch.espresso'", "category": "entity_alias", "tags": ["koffie", "switch.espresso"]},
          {"type": "routine", "subject": "morning espresso", "user_term": "als ik wakker word", "content": "When user wakes up, action: turn on the espresso machine", "category": "routine", "tags": ["wake_up", "espresso"]}
        ]
        """)

    monkeypatch.setattr("custom_components.kyber.knowledge_integration.async_ai_call", _fake_ai_call)

    facts = await _try_extract_learned_fact(
        hass,
        "ai_task.test",
        "koffie en espresso zijn hetzelfde, en als ik wakker word wil ik espresso",
        "assistant talked about switch.espresso earlier",
    )

    assert len(facts) == 2
    assert facts[0]["category"] == "entity_alias"
    assert facts[1]["category"] == "routine"
    assert facts[1]["user_term"] == "als ik wakker word"
