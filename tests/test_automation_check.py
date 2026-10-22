"""Proposed automations are checked before the user sees them.

The case behind it (see tests/heating_case.py): asked to fix a living room heating
automation, Kyber kept selector options and schedule values that do not exist,
read a schedule attribute ``temperature`` that is not there and never set
``hvac_mode``, so the thermostat stayed off. In tests against the same local
model, the real entity data plus one correction round with named findings
lifted the result from 3/13 to 10-13/13 behaviour checks.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.heating_case import (
    COMFORT,
    MODE,
    MODE_OPTIONS,
    SCHEDULE,
    SETBACK,
    THERMOSTAT,
    set_up_home,
)

AUTO_ID = "1700000000042"
ENTITY = "automation.kyber_livingroom_heating"

# Shortened from Kyber's attempts before the check: invented options and
# schedule values, data_template, no hvac_mode, singular keys.
BROKEN = {
    "alias": "Kyber living room heating",
    "mode": "single",
    "trigger": [
        {"trigger": "state", "entity_id": [MODE], "to": ["Off", "Night", "Auto", "Lower"]},
        {"trigger": "state", "entity_id": SCHEDULE, "attribute": "mode", "to": ["Off", "Day", "Auto"]},
    ],
    "condition": [],
    "action": [{
        "choose": [
            {
                "conditions": [{"condition": "state", "entity_id": MODE, "state": "Lower"}],
                "sequence": [{
                    "action": "climate.set_temperature", "target": {"entity_id": THERMOSTAT},
                    "data_template": {"temperature": f"{{{{ states('{SETBACK}') | float }}}}"},
                }],
            },
            {
                "conditions": [
                    {"condition": "state", "entity_id": MODE, "state": "Auto"},
                    {"condition": "state", "entity_id": SCHEDULE, "attribute": "mode", "state": "Day"},
                ],
                "sequence": [{
                    "action": "climate.set_temperature", "target": {"entity_id": THERMOSTAT},
                    "data": {"temperature": f"{{{{ state_attr('{SCHEDULE}', 'temperature') }}}}"},
                }],
            },
        ],
    }],
}

FIXED = {
    "alias": "Kyber living room heating",
    "mode": "restart",
    "triggers": [
        {"trigger": "state", "entity_id": [MODE], "to": ["Off", "Auto", "Setback", "Heat"]},
        {"trigger": "state", "entity_id": SCHEDULE},
    ],
    "conditions": [],
    "actions": [{
        "choose": [
            {
                "conditions": [{"condition": "state", "entity_id": MODE, "state": "Off"}],
                "sequence": [{"action": "climate.set_hvac_mode", "target": {"entity_id": THERMOSTAT},
                              "data": {"hvac_mode": "off"}}],
            },
            {
                "conditions": [
                    {"condition": "state", "entity_id": MODE, "state": "Auto"},
                    {"condition": "state", "entity_id": SCHEDULE, "attribute": "mode", "state": "Auto"},
                ],
                "sequence": [{"action": "climate.set_temperature", "target": {"entity_id": THERMOSTAT},
                              "data": {"hvac_mode": "heat", "temperature": f"{{{{ states('{COMFORT}') | float }}}}"}}],
            },
            {
                "conditions": [{"condition": "state", "entity_id": MODE, "state": "Setback"}],
                "sequence": [{"action": "climate.set_temperature", "target": {"entity_id": THERMOSTAT},
                              "data": {"hvac_mode": "heat", "temperature": f"{{{{ states('{SETBACK}') | float }}}}"}}],
            },
        ],
    }],
}


@pytest.fixture
def kyber():
    """Import at test time so module-level stubs of other test files cannot bind first."""
    from custom_components import kyber as init
    from custom_components.kyber import (
        automation_check,
        const,
        debug_and_diagnostics,
        http_api,
        tool_execution,
    )

    return SimpleNamespace(
        check=automation_check, const=const, debug=debug_and_diagnostics, http_api=http_api,
        init=init, tools=tool_execution,
    )


@pytest.fixture
def home(hass: HomeAssistant):
    """The heating entities of the case, thermostat off."""
    set_up_home(hass)
    return hass


def _keys(findings):
    return sorted({f.key for f in findings})


# ── the check ────────────────────────────────────────────────────────────────

async def test_kybers_broken_fix_gets_named_findings(kyber, home):
    findings = await kyber.check.check_config(home, BROKEN)
    errors = [f.text for f in findings if f.severity == kyber.check.ERROR]

    assert any("'Lower' is not a valid state of " + MODE in e for e in errors)
    assert any("'Night' is not a valid state of " + MODE in e for e in errors)
    assert any("'Day' is not a valid attribute 'mode' of " + SCHEDULE in e for e in errors)
    assert any(f"{SCHEDULE} has no attribute 'temperature'" in e for e in errors)
    assert {"rule_hvac_mode", "rule_schedule_end", "style_data_template", "style_plural"} <= set(_keys(findings))
    assert "schema" not in _keys(findings), "Home Assistant still accepts the old syntax"


async def test_the_fixed_config_has_no_errors(kyber, home):
    findings = await kyber.check.check_config(home, FIXED)
    assert [f.text for f in findings if f.severity == kyber.check.ERROR] == []


async def test_valid_values_come_from_all_schedule_blocks(kyber, home):
    """mode "Setback" is not active now, but a block uses it."""
    config = {**FIXED, "triggers": [{"trigger": "state", "entity_id": SCHEDULE, "attribute": "mode", "to": "Setback"},
                                    {"trigger": "state", "entity_id": SCHEDULE}]}
    findings = await kyber.check.check_config(home, config)
    assert "bad_value" not in _keys(findings)


async def test_switching_on_first_satisfies_the_hvac_rule(kyber, home):
    config = {**FIXED, "actions": [
        {"action": "climate.set_hvac_mode", "target": {"entity_id": THERMOSTAT}, "data": {"hvac_mode": "heat"}},
        {"action": "climate.set_temperature", "target": {"entity_id": THERMOSTAT}, "data": {"temperature": 21}},
    ]}
    findings = await kyber.check.check_config(home, config)
    assert "rule_hvac_mode" not in _keys(findings)


async def test_home_assistant_schema_errors_are_findings(kyber, home):
    """A measured run: HA disabled the automation for a choose with ``default: true``."""
    config = {**FIXED, "actions": [{"choose": [], "default": True}]}
    findings = await kyber.check.check_config(home, config)
    schema = [f for f in findings if f.key == "schema"]
    assert schema and schema[0].severity == kyber.check.ERROR
    assert "default" in schema[0].text


async def test_unknown_entities_are_findings(kyber, home):
    config = {**FIXED, "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.does_not_exist"}}]}
    findings = await kyber.check.check_config(home, config)
    assert any(f.key == "no_entity" and f.params["entity_id"] == "light.does_not_exist" for f in findings)


async def test_style_alone_triggers_no_correction(kyber, home):
    config = {**FIXED, "actions": [{"service": "climate.set_hvac_mode", "target": {"entity_id": THERMOSTAT},
                                    "data": {"hvac_mode": "off"}}]}
    findings = await kyber.check.check_config(home, config)
    assert "style_service" in _keys(findings)
    assert kyber.check.feedback_for_model(findings) == ""


async def test_feedback_lists_errors_then_style(kyber, home):
    feedback = kyber.check.feedback_for_model(await kyber.check.check_config(home, BROKEN))
    assert feedback.startswith("The proposed configuration was checked")
    assert feedback.index("hvac_mode") < feedback.index("Also modernise the syntax:")
    assert "data_template is deprecated" in feedback


def test_plan_config_finds_the_proposed_config(kyber):
    assert kyber.check.plan_config({"edit_automation": True, "modified_config": {"a": 1}}) == ({"a": 1}, "automation")
    assert kyber.check.plan_config({"create_automation": True, "config": {"b": 2}}) == ({"b": 2}, "automation")
    assert kyber.check.plan_config(
        {"edit_automation": True, "entity_id": "script.x", "modified_config": {"c": 3}}
    ) == ({"c": 3}, "script")
    assert kyber.check.plan_config({"actions": []}) == (None, "")


# ── entity context ───────────────────────────────────────────────────────────

async def test_entity_context_shows_options_attributes_and_block_values(kyber, home):
    ids = kyber.check.referenced_entity_ids(home, BROKEN)
    assert ids == [MODE, SCHEDULE, THERMOSTAT, SETBACK], "services such as climate.set_temperature drop out"
    text = await kyber.check.entity_context(home, ids, await kyber.check.collect_schedule_values(home, ids))
    assert json.dumps(MODE_OPTIONS) in text
    assert 'mode ∈ ["Auto", "Setback"]' in text
    assert 'hvac_modes=["off", "heat"]' in text


async def test_a_missing_schedule_service_leaves_no_block_values(kyber, hass):
    hass.states.async_set(SCHEDULE, "off", {})
    assert await kyber.check.schedule_data_values(hass, SCHEDULE) == {}


# ── tools and response handling ──────────────────────────────────────────────

async def test_get_entity_state_returns_all_attributes_on_request(kyber, home):
    """The model asked with fields ["state", "attributes"] and got only "_missing_fields"."""
    result = json.loads(kyber.tools._execute_tool(home, {
        "name": "get_entity_state", "entity_id": SCHEDULE, "fields": ["state", "attributes"],
    }))
    assert result["state"] == "on"
    assert result["attributes"]["mode"] == "Auto"
    assert "_missing_fields" not in result


async def test_service_names_are_not_reported_as_unknown_entities(kyber, home):
    async def _noop(call):
        return None

    home.services.async_register("climate", "set_temperature", _noop)
    text = "I call `climate.set_temperature` on `climate.does_not_exist`."
    out = kyber.http_api._extract_response_components(text, "action", "x", home, [])
    assert "climate.set_temperature`" not in out["response_text"].split("Note:")[-1]
    assert "climate.does_not_exist" in out["response_text"].split("Note:")[-1]


def test_debug_snapshot_keeps_start_and_end(kyber):
    text = "A" * 300_000 + "User: question\nAssistant:"
    kept = kyber.debug._keep_ends(text, kyber.debug._SNAPSHOT_PROMPT_CHARS)
    assert len(kept) == kyber.debug._SNAPSHOT_PROMPT_CHARS
    assert kept.startswith("AAAA")
    assert kept.endswith("User: question\nAssistant:")
    assert "chars cut from the middle" in kept
    assert kyber.debug._keep_ends("short", 100) == "short"


# ── migration of the old round default ───────────────────────────────────────

@pytest.mark.parametrize(("stored", "expected"), [(3, 6), (5, 5), (8, 8)])
async def test_the_old_default_round_count_is_raised(kyber, hass, stored, expected):
    entry = MockConfigEntry(
        domain="kyber", version=1, minor_version=1,
        data={"ai_task_entity_id": "ai_task.x", "max_tool_rounds": stored},
        options={"max_tool_rounds": stored},
    )
    entry.add_to_hass(hass)
    assert await kyber.init.async_migrate_entry(hass, entry)
    assert entry.minor_version == 2
    assert entry.data["max_tool_rounds"] == expected
    assert entry.options["max_tool_rounds"] == expected


async def test_an_entry_without_the_option_migrates_untouched(kyber, hass):
    entry = MockConfigEntry(domain="kyber", version=1, minor_version=1, data={"ai_task_entity_id": "ai_task.x"})
    entry.add_to_hass(hass)
    assert await kyber.init.async_migrate_entry(hass, entry)
    assert "max_tool_rounds" not in entry.data


async def test_feedback_is_built_from_a_model_answer(kyber, home):
    feedback = await kyber.http_api._automation_check_feedback(home, _plan(BROKEN))
    assert "'Lower' is not a valid state" in feedback


# ── end to end through /api/kyber/complete ───────────────────────────────────

@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    # Not an Ollama entity, so the chat turn skips the Ollama health check.
    return MockConfigEntry(
        domain="kyber",
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 32768},
        title="Kyber",
    )


PROMPT = (
    f"/{ENTITY} please review this automation and fix what is wrong."
)


def _plan(config: dict) -> str:
    plan = {
        "edit_automation": True, "entity_id": ENTITY, "automation_id": AUTO_ID, "summary": "Heating",
        "original_config": BROKEN, "modified_config": config,
    }
    return f"Proposal:\n\n```plan\n{json.dumps(plan, ensure_ascii=False)}\n```"


def _write_automation(hass: HomeAssistant) -> None:
    import yaml

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


async def test_a_rejected_proposal_gets_one_correction_round(home, setup_integration, hass_client) -> None:
    _write_automation(home)
    seen: list[str] = []

    async def fake_ai(*_args, instructions="", **_kwargs):
        if "User: /automation." not in instructions:
            return SimpleNamespace(data="[]")
        seen.append(instructions)
        corrected = '[TOOL_RESULT: {"name": "check_configuration"}]' in instructions
        return SimpleNamespace(data=_plan(FIXED if corrected else BROKEN))

    data = await _complete(hass_client, fake_ai)

    assert len(seen) == 2, "first proposal, then one correction"
    assert "### Entities this configuration uses" in seen[0]
    assert json.dumps(MODE_OPTIONS)[1:-1] in seen[0]
    from homeassistant.const import MAJOR_VERSION, MINOR_VERSION

    assert f"#### Home Assistant {MAJOR_VERSION}.{MINOR_VERSION}: write configurations" in seen[0]
    assert "{{" not in seen[0].split("#### Chat-driven edit")[1].split("## AUTOMATION NAMED")[0], \
        "the plan templates reach the model with single braces"
    assert "'Lower' is not a valid state" in seen[1]
    assert data["plan"]["modified_config"] == FIXED
    assert "check_warnings" not in data["plan"]


async def test_after_two_corrections_the_rest_goes_on_the_card(home, setup_integration, hass_client) -> None:
    _write_automation(home)
    seen: list[str] = []

    async def fake_ai(*_args, instructions="", **_kwargs):
        if "User: /automation." not in instructions:
            return SimpleNamespace(data="[]")
        seen.append(instructions)
        return SimpleNamespace(data=_plan(BROKEN))

    data = await _complete(hass_client, fake_ai)

    assert len(seen) == 3, "the proposal plus MAX_CHECK_ROUNDS corrections"
    keys = {w["key"] for w in data["plan"]["check_warnings"]}
    assert {"bad_value", "rule_hvac_mode"} <= keys
    assert all(w["severity"] == "error" for w in data["plan"]["check_warnings"])
