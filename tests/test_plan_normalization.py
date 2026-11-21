"""Tests for plan-block extraction/normalization hardening.

Bug A: _normalize_json_plan_blocks emitted "domain.service" into the bare
"service" field, which the executor passed to async_call verbatim
(ServiceNotFound) and _classify_risk never matched against
_DESTRUCTIVE_SERVICES.

Bug B: _extract_plan_block returned whatever json.loads produced, so a
plan block that is a JSON list (or has a malformed "actions" value)
crashed callers with AttributeError/TypeError.
"""
from __future__ import annotations

import json

from custom_components.kyber.action_execution import (
    _DESTRUCTIVE_SERVICES,
    _classify_risk,
)
from custom_components.kyber.response_processing import (
    _extract_plan_block,
    _normalize_json_plan_blocks,
)


# ── Bug B: _extract_plan_block resilience ────────────────────────────────────

def test_extract_plan_block_dict_unchanged():
    text = '```plan\n{"summary": "ok", "actions": [{"type": "turn_on"}]}\n```'
    plan = _extract_plan_block(text)
    assert plan == {"summary": "ok", "actions": [{"type": "turn_on"}]}


def test_extract_plan_block_list_returns_none():
    text = '```plan\n[{"type": "turn_on", "entity_id": "switch.espresso"}]\n```'
    assert _extract_plan_block(text) is None


def test_extract_plan_block_actions_null_becomes_empty_list():
    text = '```plan\n{"summary": "s", "actions": null}\n```'
    plan = _extract_plan_block(text)
    assert plan is not None
    assert plan["actions"] == []


def test_extract_plan_block_actions_string_becomes_empty_list():
    text = '```plan\n{"summary": "s", "actions": "x"}\n```'
    plan = _extract_plan_block(text)
    assert plan is not None
    assert plan["actions"] == []


def test_extract_plan_block_mixed_actions_keeps_only_dicts():
    text = (
        '```plan\n{"actions": [{"type": "turn_on"}, "junk", null, '
        '[1, 2], {"type": "turn_off"}]}\n```'
    )
    plan = _extract_plan_block(text)
    assert plan is not None
    assert plan["actions"] == [{"type": "turn_on"}, {"type": "turn_off"}]


# ── Bug A: normalized call_service carries separate domain/service keys ──────

def test_direct_service_type_gets_split_domain_and_service():
    text = '```json\n{"type": "turn_on", "entity_id": "switch.espresso"}\n```'
    rewrapped = _normalize_json_plan_blocks(text)
    plan = _extract_plan_block(rewrapped)
    assert plan is not None
    assert len(plan["actions"]) == 1
    action = plan["actions"][0]
    assert action["type"] == "call_service"
    assert action["domain"] == "switch"
    assert action["service"] == "turn_on"
    assert "." not in action["service"]


def test_plan_block_call_service_keeps_domain_and_splits_service():
    text = (
        '```plan\n{"actions": [{"type": "call_service", "domain": "vacuum", '
        '"service": "vacuum.start", "entity_id": "vacuum.roborock"}]}\n```'
    )
    plan = _extract_plan_block(text)
    assert plan is not None
    action = plan["actions"][0]
    risk = _classify_risk(action)
    assert risk == {"risk_domain": "vacuum", "risk_reason": "vacuum.start"}


def test_classify_risk_splits_dotted_service_without_domain():
    action = {"type": "call_service", "service": "vacuum.start"}
    risk = _classify_risk(action)
    assert risk is not None
    assert risk["risk_domain"] == "vacuum"
    assert risk["risk_reason"] == "vacuum.start"
    assert ("vacuum", "start") in _DESTRUCTIVE_SERVICES


def test_classify_risk_splits_dotted_service_with_domain():
    action = {"type": "call_service", "domain": "vacuum", "service": "vacuum.start"}
    risk = _classify_risk(action)
    assert risk is not None
    assert risk["risk_domain"] == "vacuum"
    assert risk["risk_reason"] == "vacuum.start"


def test_classify_risk_uses_existing_domain_with_dotted_service():
    # Explicit non-empty domain wins: service keeps only the part after the dot.
    action = {"type": "call_service", "domain": "alarm_control_panel",
             "service": "lock.unlock"}
    risk = _classify_risk(action)
    assert risk == {
        "risk_domain": "alarm_control_panel",
        "risk_reason": "alarm_control_panel.unlock",
    }
    assert ("alarm_control_panel", "unlock") not in _DESTRUCTIVE_SERVICES


def test_classify_risk_undeclared_service_stays_unclassified():
    action = {"type": "call_service", "service": "switch.turn_on",
             "entity_id": "switch.espresso"}
    assert _classify_risk(action) is None
