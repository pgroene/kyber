"""A plan block with small JSON slips must still become a card.

Models write raw line breaks inside long Jinja templates and leave a comma
before a closing bracket. _extract_plan_block returned None for both, the
panel cut the block from the reply, and the user saw a reply ending in a
colon without any proposal card.
"""
from __future__ import annotations

import logging

from custom_components.kyber.response_processing import _extract_plan_block


def _fence(body: str) -> str:
    return f"Here is the corrected draft:\n\n```plan\n{body}\n```"


def test_raw_newline_inside_template_string():
    body = (
        '{"edit_automation": true, "entity_id": "automation.heating", '
        '"modified_config": {"action": [{"service": "climate.set_temperature", '
        '"data": {"temperature": "{{ states(\'input_number.comfort\')\n | float }}"}}]}}'
    )
    plan = _extract_plan_block(_fence(body))
    assert plan is not None
    temp = plan["modified_config"]["action"][0]["data"]["temperature"]
    assert "input_number.comfort" in temp


def test_trailing_commas():
    body = '{"edit_automation": true, "changes": ["a", "b",], "modified_config": {"alias": "x",},}'
    plan = _extract_plan_block(_fence(body))
    assert plan == {"edit_automation": True, "changes": ["a", "b"], "modified_config": {"alias": "x"}}


def test_valid_json_is_untouched():
    # A comma before a bracket inside a string must survive when the JSON is valid
    body = '{"summary": "keep ,] and ,} as written", "actions": []}'
    plan = _extract_plan_block(_fence(body))
    assert plan["summary"] == "keep ,] and ,} as written"


def test_unreadable_block_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        assert _extract_plan_block(_fence('{"edit_automation": true, "summary": oops}')) is None
    assert "plan block is not valid JSON" in caplog.text
