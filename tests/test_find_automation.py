"""A German edit request for a named automation must end in a proposal.

"Fixe die automation.<name with an umlaut> …" ended in
"Ich konnte auf diese Anfrage keine Antwort erzeugen" (2026-10-09). Four
causes, each covered here (with a made-up automation):

1. get_automation rebuilt the entity_id from the alias by lowercasing, so
   "Lüftung …" never matched HA's transliterated "luftung_…".
2. With three tool rounds the lookup ate every round; when they ran out the
   user got the fallback text instead of an answer.
3. German change verbs were unknown to the intent classifier, so the request
   counted as informational ...
4. ... and the informational guard dropped the edit plan as "empty".
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

AUTO_ID = "1700000000001"
ENTITY = "automation.luftung_flur_nacht"
ALIAS = "Lüftung Flur Nacht"
PROMPT = (
    f"Fix bitte {ENTITY}: Nachts soll die Lüftung nur laufen, "
    'solange input_select.lueftungsmodus auf „Automatik“ steht.'
)


@pytest.fixture
def kyber():
    """Import at test time so module-level stubs of other test files cannot bind first."""
    from custom_components.kyber import const, http_api, intent_and_context, response_processing, tool_execution

    return SimpleNamespace(
        const=const, http_api=http_api, intent=intent_and_context,
        rp=response_processing, tools=tool_execution,
    )


def _items():
    return [
        {"id": "other", "alias": "Licht Flur"},
        {"id": AUTO_ID, "alias": ALIAS, "trigger": [], "action": [], "hash": "h", "num_triggers": 0},
    ]


def _hass(state_attrs=None, unique_id=None):
    hass = MagicMock()
    hass.states.get = MagicMock(
        return_value=SimpleNamespace(attributes=state_attrs) if state_attrs is not None else None
    )
    registry = MagicMock()
    registry.async_get = MagicMock(
        return_value=SimpleNamespace(unique_id=unique_id) if unique_id else None
    )
    return hass, registry


# ── 1. find_config_item ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("state_attrs", "unique_id"),
    [({}, AUTO_ID), ({"id": AUTO_ID}, None), (None, None)],
    ids=["registry", "state-attribute", "slug-of-alias"],
)
def test_umlaut_alias_is_found_by_entity_id(kyber, state_attrs, unique_id):
    hass, registry = _hass(state_attrs, unique_id)
    with patch.object(kyber.tools.er, "async_get", return_value=registry):
        item = kyber.tools.find_config_item(hass, "automation", _items(), ENTITY)
    assert item is not None and item["id"] == AUTO_ID


def test_id_and_alias_still_match(kyber):
    hass, registry = _hass()
    with patch.object(kyber.tools.er, "async_get", return_value=registry):
        assert kyber.tools.find_config_item(hass, "automation", _items(), AUTO_ID)["id"] == AUTO_ID
        assert kyber.tools.find_config_item(hass, "automation", _items(), ALIAS.lower())["id"] == AUTO_ID
        assert kyber.tools.find_config_item(hass, "automation", _items(), "automation.gibt_es_nicht") is None


def test_script_entity_id_matches_its_key(kyber):
    hass, registry = _hass()
    with patch.object(kyber.tools.er, "async_get", return_value=registry):
        item = kyber.tools.find_config_item(hass, "script", [{"id": "gute_nacht", "alias": "Gute Nacht"}], "script.gute_nacht")
    assert item["id"] == "gute_nacht"


# ── 3. intent ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    PROMPT,
    "Ändere die Automatisierung Licht Flur",
    "Korrigiere automation.licht_flur",
    "Bearbeite das Skript script.gute_nacht",
    "Schalte das Licht im Flur aus",
    "Mach die Küche an",
    "Passe die Heizung im Bad an",
])
def test_german_change_requests_are_actions(kyber, prompt):
    assert kyber.intent._classify_intent(prompt) == "action"


@pytest.mark.parametrize("prompt", [
    "Ist das Licht im Flur an?",
    "Was passiert, wenn das Licht an ist?",
    "Welche Automatisierungen laufen nachts?",
    "Zeig mir die Heizung",
])
def test_german_questions_stay_informational(kyber, prompt):
    assert kyber.intent._classify_intent(prompt) == "informational"


def test_german_edit_request_loads_the_automation_guidance(kyber):
    assert kyber.rp._AUTOMATION_EDIT_RE.search(PROMPT)
    assert kyber.rp._AUTOMATION_EDIT_RE.search("Korrigiere das Skript für die Nacht")


# ── 4. informational guard ───────────────────────────────────────────────────

def test_edit_plan_survives_an_informational_intent(kyber):
    plan = {"edit_automation": True, "automation_id": AUTO_ID, "summary": "fix", "modified_config": {"alias": ALIAS}}
    text = f"Hier der Vorschlag:\n\n```plan\n{json.dumps(plan)}\n```"
    out = kyber.http_api._extract_response_components(text, "informational", "Was ist mit der Heizung?", MagicMock(), [])
    assert out["plan_block"]["edit_automation"] is True


# ── 2. rounds option ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(("value", "expected"), [(None, 6), (5, 5), (0, 1), (99, 15), ("x", 6)])
def test_max_tool_rounds_is_clamped(kyber, value, expected):
    cfg = {} if value is None else {kyber.const.CONF_MAX_TOOL_ROUNDS: value}
    assert kyber.const.get_max_tool_rounds(cfg) == expected


# ── end to end through /api/kyber/complete ───────────────────────────────────

@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    # Not an Ollama entity, so the chat turn skips the Ollama health check.
    return MockConfigEntry(
        domain="kyber",
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 32768},
        title="Kyber",
    )


def _write_automation(hass: HomeAssistant) -> None:
    import yaml  # noqa: PLC0415

    with open(hass.config.path("automations.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump([{"id": AUTO_ID, "alias": ALIAS, "trigger": [], "action": []}], fh, allow_unicode=True)
    hass.states.async_set(ENTITY, "on", {"id": AUTO_ID, "friendly_name": ALIAS})


async def _complete(hass_client, prompt: str, fake_ai) -> dict:
    client = await hass_client()
    with patch("custom_components.kyber.http_api.async_ai_call", new=fake_ai), \
         patch("custom_components.kyber.knowledge_integration.async_ai_call", new=fake_ai):
        resp = await client.post("/api/kyber/complete", json={"prompt": prompt, "request_id": "t1"})
    assert resp.status == 200, await resp.text()
    return await resp.json()


async def test_named_automation_is_preloaded_and_edit_plan_arrives(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    _write_automation(hass)
    seen: list[str] = []
    # A complete, valid configuration: the check sends anything Home Assistant
    # would reject back to the model, which would cost a second round here.
    plan = {
        "edit_automation": True, "entity_id": ENTITY, "automation_id": AUTO_ID, "summary": "Zeitplan",
        "original_config": {"alias": ALIAS},
        "modified_config": {
            "alias": ALIAS, "mode": "restart",
            "triggers": [{"trigger": "homeassistant", "event": "start"}],
            "actions": [{"delay": "00:00:01"}],
        },
    }

    async def fake_ai(*_args, instructions="", **_kwargs):
        if "User: Fix bitte" in instructions:
            seen.append(instructions)
            return SimpleNamespace(data=f"Vorschlag:\n\n```plan\n{json.dumps(plan)}\n```")
        return SimpleNamespace(data="[]")

    data = await _complete(hass_client, PROMPT, fake_ai)

    assert len(seen) == 1, "answered in the first round, no lookup needed"
    assert f"NAMED IN THE REQUEST: `{ENTITY}`" in seen[0]
    assert f"Config ID: `{AUTO_ID}`" in seen[0]
    assert ALIAS in seen[0]
    assert data["plan"]["edit_automation"] is True


async def test_used_up_rounds_end_in_a_final_answer(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    hass.data["kyber_config"] = {**hass.data["kyber_config"], "max_tool_rounds": 2}
    loop_calls: list[str] = []

    async def fake_ai(*_args, instructions="", **_kwargs):
        if "No more tool calls are possible" in instructions:
            return SimpleNamespace(data="Die Heizung im Wohnzimmer steht auf Automatik.")
        if "User: Stelle die Heizung" in instructions:
            loop_calls.append(instructions)
            query = f"heizung {len(loop_calls)}"  # a new call each round, never a duplicate
            return SimpleNamespace(data=f'[TOOL_CALL: {{"name": "search_entities", "query": "{query}"}}]')
        return SimpleNamespace(data="[]")

    data = await _complete(hass_client, "Stelle die Heizung im Wohnzimmer auf 20 Grad ein", fake_ai)

    assert len(loop_calls) == 2, "the configured number of tool rounds"
    assert data["response"] == "Die Heizung im Wohnzimmer steht auf Automatik."
