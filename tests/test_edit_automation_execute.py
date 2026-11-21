"""Executing an automation edit from a chat proposal.

Bug: the model put the edit into ``actions`` as ``{"type": "edit_automation"}``
instead of the top-level ``edit_automation`` plan block. The panel showed the
generic proposal card, and Execute failed with "Missing entity_id": the
executor only knew ``update_automation`` and handed the unknown type to the
entity registry branch.
"""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.kyber.action_execution import (
    _action_requires_approval,
    _resolve_config_target,
)
from custom_components.kyber.response_processing import _lift_config_edit_plan

_ALIAS = "Heizkörper Büro"
_ENTITY = "automation.heizkorper_buro"
_CONFIG_ID = "1712345678901"

_ORIGINAL = {
    "alias": _ALIAS,
    "trigger": [{"platform": "state", "entity_id": "schedule.office"}],
    "action": [{"service": "climate.set_temperature", "target": {"entity_id": "climate.office"}}],
}
_MODIFIED = {
    **_ORIGINAL,
    "trigger": _ORIGINAL["trigger"] + [{"platform": "state", "entity_id": "input_select.heating_mode"}],
}


class _FakeResp:
    ok = True
    status = 200

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class _FakeSession:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def post(self, url, *, json=None, headers=None):
        self._calls.append({"url": url, "json": json})
        return _FakeResp()


def _set_automation_state(hass: HomeAssistant) -> None:
    hass.states.async_set(_ENTITY, "on", {"id": _CONFIG_ID, "friendly_name": _ALIAS})


async def _execute(hass_client, actions: list[dict], calls: list[dict], approved: bool = True):
    client = await hass_client()
    with patch(
        "custom_components.kyber.action_execution.async_get_clientsession",
        return_value=_FakeSession(calls),
    ):
        resp = await client.post("/api/kyber/execute", json={"approved": approved, "actions": actions})
    return resp.status, await resp.json()


# ── /api/kyber/execute ───────────────────────────────────────────────────────

async def test_edit_automation_by_entity_id_saves_to_config_id(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    _set_automation_state(hass)
    calls: list[dict] = []
    status, data = await _execute(hass_client, [{
        "type": "edit_automation",
        "entity_id": _ENTITY,
        "original_config": _ORIGINAL,
        "modified_config": _MODIFIED,
    }], calls)

    assert status == 200
    result = data["results"][0]
    assert result["status"] == "ok", result
    assert result["automation_id"] == _CONFIG_ID
    assert calls[0]["url"].endswith(f"/api/config/automation/config/{_CONFIG_ID}")
    assert calls[0]["json"]["trigger"] == _MODIFIED["trigger"]
    assert calls[0]["json"]["id"] == _CONFIG_ID
    # Undo restores the previous config instead of deleting the automation.
    assert result["undo_action"]["type"] == "update_automation"
    assert result["undo_action"]["config"] == _ORIGINAL


async def test_edit_automation_without_ids_resolves_alias(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The failing proposal had neither entity_id nor automation_id."""
    _set_automation_state(hass)
    calls: list[dict] = []
    status, data = await _execute(hass_client, [{
        "type": "edit_automation",
        "modified_config": _MODIFIED,
    }], calls)

    assert status == 200
    assert data["results"][0]["status"] == "ok", data["results"][0]
    assert calls[0]["url"].endswith(f"/api/config/automation/config/{_CONFIG_ID}")
    # No original config known → no undo that would restore the wrong state.
    assert data["results"][0]["undo_action"] is None


async def test_edit_automation_unknown_target_explains_error(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    calls: list[dict] = []
    _, data = await _execute(hass_client, [{
        "type": "edit_automation",
        "modified_config": {"alias": "Does not exist", "trigger": [], "action": []},
    }], calls)

    result = data["results"][0]
    assert result["status"] == "error"
    assert "Missing entity_id" not in result["message"]
    assert "automation" in result["message"]
    assert calls == []


async def test_edit_automation_needs_approval(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    _set_automation_state(hass)
    calls: list[dict] = []
    status, data = await _execute(hass_client, [{
        "type": "edit_automation", "entity_id": _ENTITY, "modified_config": _MODIFIED,
    }], calls, approved=False)

    assert status == 403
    assert data["status"] == "approval_required"
    assert calls == []


def test_edit_types_are_config_changing() -> None:
    assert _action_requires_approval({"type": "edit_automation"}) is True
    assert _action_requires_approval({"type": "edit_script"}) is True


# ── _resolve_config_target ───────────────────────────────────────────────────

async def test_resolve_entity_id_given_as_automation_id(hass: HomeAssistant) -> None:
    _set_automation_state(hass)
    assert _resolve_config_target(hass, {"type": "edit_automation", "automation_id": _ENTITY}) == (
        "automation", _CONFIG_ID, _ENTITY,
    )


async def test_resolve_config_id_finds_entity(hass: HomeAssistant) -> None:
    _set_automation_state(hass)
    assert _resolve_config_target(hass, {"type": "edit_automation", "automation_id": _CONFIG_ID}) == (
        "automation", _CONFIG_ID, _ENTITY,
    )


async def test_resolve_script_uses_object_id(hass: HomeAssistant) -> None:
    assert _resolve_config_target(hass, {"type": "edit_automation", "entity_id": "script.good_night"}) == (
        "script", "good_night", "script.good_night",
    )


# ── _lift_config_edit_plan ───────────────────────────────────────────────────

def test_lift_single_edit_action_into_edit_plan() -> None:
    plan = {
        "summary": f"Korrigiert die Automatisierung '{_ALIAS}'",
        "actions": [{"type": "edit_automation", "modified_config": _MODIFIED, "original_config": _ORIGINAL}],
        "warnings": ["Reagiert auch auf manuelle Änderungen des input_select."],
    }
    lifted = _lift_config_edit_plan(plan)

    assert lifted["edit_automation"] is True
    assert lifted["summary"] == plan["summary"]
    assert lifted["modified_config"] == _MODIFIED
    assert lifted["original_config"] == _ORIGINAL
    assert lifted["changes"] == plan["warnings"]
    assert "actions" not in lifted


def test_lift_keeps_ids_and_marks_scripts() -> None:
    lifted = _lift_config_edit_plan({"actions": [{
        "type": "update_script", "entity_id": "script.x", "config": {"sequence": []},
    }]})
    assert lifted["script"] is True
    assert lifted["entity_id"] == "script.x"
    assert lifted["modified_config"] == {"sequence": []}


def test_lift_leaves_other_plans_unchanged() -> None:
    native = {"edit_automation": True, "modified_config": _MODIFIED}
    without_config = {"actions": [{"type": "edit_automation", "entity_id": _ENTITY}]}
    two_actions = {"actions": [
        {"type": "edit_automation", "modified_config": _MODIFIED},
        {"type": "call_service", "domain": "light", "service": "turn_on"},
    ]}
    service = {"actions": [{"type": "call_service", "domain": "light", "service": "turn_on"}]}
    for plan in (native, without_config, two_actions, service, None):
        assert _lift_config_edit_plan(plan) is plan
