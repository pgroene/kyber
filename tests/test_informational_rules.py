"""INFORMATIONAL mode carries its own tool whitelist ("Use ONLY these tool
names").  A tool missing there is forbidden for exactly the questions it was
built for: calc was missing, and an answer converted kWh to an
average power in the model's head (400 W instead of 270 W).
"""
from __future__ import annotations

import re

from custom_components.kyber.const import SYSTEM_PROMPT_TEMPLATE
from custom_components.kyber.http_api import _RESPONSE_MODE_INFORMATIONAL


def _whitelist() -> set[str]:
    match = re.search(r"Use ONLY these tool names: ([^\n]+?)\.\n", _RESPONSE_MODE_INFORMATIONAL)
    assert match
    return {name.strip() for name in match.group(1).split(",")}


def test_calc_and_recorder_tools_are_allowed() -> None:
    assert {"calc", "get_statistics", "get_history"} <= _whitelist()


def test_every_whitelisted_tool_is_in_the_tool_table() -> None:
    table = set(re.findall(r"^\| `(\w+)` \|", SYSTEM_PROMPT_TEMPLATE, re.MULTILINE))
    assert _whitelist() - table <= {"search_automations", "get_datetime", "get_todo_items"}


def test_derived_numbers_must_come_from_calc() -> None:
    assert "must come from a calc call" in _RESPONSE_MODE_INFORMATIONAL
