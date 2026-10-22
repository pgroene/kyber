"""Edit requests about a named automation end in a checked plan, and thinking can stay on.

Measured 2026-10-22 against a local model through Kyber's endpoint:

- with thinking, one answer had original_config and modified_config but no
  "edit_automation" and no ids, so Kyber showed no apply card and never
  checked it (its content was wrong);
- without thinking, two of five answers ended on an analysis without a plan;
- the "/no_think" Kyber appends for qwen3 entities would switch thinking off
  again on hybrid Qwen3 models even when the user turned it on on purpose.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.heating_case import load, set_up_home

ENTITY = "automation.kyber_livingroom_heating"
AUTO_ID = "1700000000042"
BROKEN = load("kyber_attempt_2")
FIXED = load("kyber_checked_fix")
REF = [{"kind": "automation", "entity_id": ENTITY, "id": AUTO_ID}]


@pytest.fixture
def http_api():
    from custom_components.kyber import http_api

    return http_api


# ── completing a plan without its flag ───────────────────────────────────────

def test_a_plan_with_configs_but_no_flag_becomes_an_edit(http_api):
    plan = {"summary": "s", "original_config": BROKEN, "modified_config": FIXED}
    out = http_api._complete_automation_plan(plan, REF)
    assert out["edit_automation"] is True
    assert (out["entity_id"], out["automation_id"]) == (ENTITY, AUTO_ID)


def test_the_config_id_picks_the_automation_among_several(http_api):
    refs = [{"kind": "automation", "entity_id": "automation.other", "id": "1"}, *REF]
    out = http_api._complete_automation_plan({"modified_config": {**FIXED, "id": AUTO_ID}}, refs)
    assert out["entity_id"] == ENTITY


def test_without_a_named_automation_the_plan_stays_as_it_is(http_api):
    plan = {"modified_config": FIXED}
    assert http_api._complete_automation_plan(plan, []) is plan
    two = [{"kind": "automation", "entity_id": "automation.a", "id": "1"},
           {"kind": "automation", "entity_id": "automation.b", "id": "2"}]
    assert "edit_automation" not in http_api._complete_automation_plan(plan, two)


def test_an_edit_plan_missing_its_ids_gets_them(http_api):
    out = http_api._complete_automation_plan({"edit_automation": True, "modified_config": FIXED}, REF)
    assert (out["entity_id"], out["automation_id"]) == (ENTITY, AUTO_ID)


def test_other_plans_are_untouched(http_api):
    plan = {"actions": [{"type": "call_service", "domain": "light", "service": "turn_on"}]}
    assert http_api._complete_automation_plan(plan, REF) is plan


# ── correction requests ──────────────────────────────────────────────────────

async def test_an_analysis_without_plan_is_sent_back(hass, http_api):
    feedback = await http_api._correction_request(hass, "The automation uses wrong states …", REF, "action")
    assert feedback.startswith("No plan block found.")
    assert ENTITY in feedback


async def test_no_request_for_questions_or_clarifications(hass, http_api):
    assert await http_api._correction_request(hass, "It heats by the schedule.", REF, "informational") == ""
    clarify = 'Which mode?\n\n```clarify\n{"question": "Which?", "options": ["A", "B"]}\n```'
    assert await http_api._correction_request(hass, clarify, REF, "action") == ""
    assert await http_api._correction_request(hass, "Done.", [], "action") == ""


# ── end to end through /api/kyber/complete ───────────────────────────────────

@pytest.fixture
def mock_config_entry(request) -> MockConfigEntry:
    """A qwen3 entity; allow_thinking from the test's parameter (default off)."""
    allow = getattr(request, "param", False)
    return MockConfigEntry(
        domain="kyber",
        data={"ai_task_entity_id": "ai_task.qwen3_local", "max_tokens": 32768, "allow_thinking": allow},
        title="Kyber",
    )


PROMPT = f"/{ENTITY} please update this automation."


def _write_automation(hass: HomeAssistant) -> None:
    with open(hass.config.path("automations.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump([{"id": AUTO_ID, **BROKEN}], fh, allow_unicode=True)
    hass.states.async_set(ENTITY, "on", {"id": AUTO_ID, "friendly_name": BROKEN["alias"]})


async def _complete(hass_client, fake_ai) -> dict:
    client = await hass_client()
    with patch("custom_components.kyber.http_api.async_ai_call", new=fake_ai), \
         patch("custom_components.kyber.knowledge_integration.async_ai_call", new=fake_ai):
        resp = await client.post("/api/kyber/complete", json={"prompt": PROMPT, "request_id": "t1"})
    assert resp.status == 200, await resp.text()
    return await resp.json()


def _plan(**plan) -> str:
    return f"Proposal:\n\n```plan\n{json.dumps(plan, ensure_ascii=False)}\n```"


@pytest.fixture
def home(hass: HomeAssistant) -> HomeAssistant:
    set_up_home(hass)
    _write_automation(hass)
    return hass


async def test_a_missing_plan_gets_one_more_round(home, setup_integration, hass_client) -> None:
    seen: list[str] = []

    async def fake_ai(*_args, instructions="", **_kwargs):
        if "User: /automation." not in instructions:
            return SimpleNamespace(data="[]")
        seen.append(instructions)
        if "No plan block found." in instructions:
            return SimpleNamespace(data=_plan(original_config=BROKEN, modified_config=FIXED))
        return SimpleNamespace(data="The automation uses states that do not exist and sets no hvac_mode.")

    data = await _complete(hass_client, fake_ai)

    assert len(seen) == 2, "the analysis, then the plan"
    assert data["plan"]["edit_automation"] is True, "flag filled in"
    assert (data["plan"]["entity_id"], data["plan"]["automation_id"]) == (ENTITY, AUTO_ID)
    assert data["plan"]["modified_config"] == FIXED
    assert "check_warnings" not in data["plan"]


async def test_a_plan_without_flag_is_checked_and_corrected(home, setup_integration, hass_client) -> None:
    seen: list[str] = []

    async def fake_ai(*_args, instructions="", **_kwargs):
        if "User: /automation." not in instructions:
            return SimpleNamespace(data="[]")
        seen.append(instructions)
        config = FIXED if '[TOOL_RESULT: {"name": "check_configuration"}]' in instructions else BROKEN
        return SimpleNamespace(data=_plan(summary="fix", original_config=BROKEN, modified_config=config))

    data = await _complete(hass_client, fake_ai)

    assert len(seen) == 2, "the unflagged broken plan went through the check"
    assert "'Lower' is not a valid state" in seen[1]
    assert data["plan"]["edit_automation"] is True
    assert data["plan"]["modified_config"] == FIXED


@pytest.mark.parametrize(("mock_config_entry", "no_think"), [(False, True), (True, False)],
                         indirect=["mock_config_entry"], ids=["thinking-off", "thinking-allowed"])
async def test_no_think_only_when_thinking_is_not_allowed(home, setup_integration, hass_client, no_think) -> None:
    seen: list[str] = []

    async def fake_ai(*_args, instructions="", **_kwargs):
        if "User: /automation." in instructions:
            seen.append(instructions)
            return SimpleNamespace(data=_plan(original_config=BROKEN, modified_config=FIXED))
        return SimpleNamespace(data="[]")

    await _complete(hass_client, fake_ai)
    assert ("/no_think" in seen[0]) is no_think
