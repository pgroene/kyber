"""A chat turn the client gives up on still leaves a Debug snapshot.

The panel aborts a turn at its chat timeout or on Stop, and HA cancels the
handler. The snapshot used to be written only at the end of a finished turn,
so "Last turn" stayed empty exactly when there was something to debug.
"""
from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.kyber.api_utilities import _progress_emit
from custom_components.kyber.debug_and_diagnostics import (
    _DEBUG_LAST_TURN_KEY,
    _debug_record_aborted_turn,
    _debug_record_turn,
)
from custom_components.kyber.http_api import _ChatTurn


async def _abort_after_a_tool_round(hass: HomeAssistant, request_id: str):
    async def loop(*args, **kwargs):
        _progress_emit(hass, request_id, {"type": "tool_call", "name": "search_entities", "args": {"query": "lamp"}})
        _progress_emit(hass, request_id, {"type": "info", "message": "Asking AI (round 2)…", "key": "ev_asking_ai"})
        raise asyncio.CancelledError  # what HA raises when the client disconnects

    return loop


async def test_a_cancelled_turn_leaves_a_snapshot(hass: HomeAssistant, setup_integration, hass_client) -> None:
    client = await hass_client()
    loop = await _abort_after_a_tool_round(hass, "abort-dbg")
    with patch("custom_components.kyber.http_api._run_ai_loop", new=loop), contextlib.suppress(Exception):
        await client.post("/api/kyber/complete", json={"prompt": "How many lamps are on?", "request_id": "abort-dbg"})

    snap = hass.data[_DEBUG_LAST_TURN_KEY]
    assert snap["request_id"] == "abort-dbg"
    assert snap["aborted"]["reason"] == "client_gone"
    assert snap["aborted"]["after_ms"] >= 0
    assert snap["user_prompt"] == "How many lamps are on?"
    assert "How many lamps are on?" in snap["expanded_prompt"], "the prompt built before the model call"
    assert snap["tool_log"] == [{"type": "tool_call", "name": "search_entities", "args": {"query": "lamp"}}]
    assert [e.get("key") for e in snap["progress_events"]][-1] == "ev_asking_ai"
    assert snap["response_text"] == ""

    resp = await client.get("/api/kyber/debug/last_turn")
    assert (await resp.json())["snapshot"]["aborted"]["reason"] == "client_gone"


async def test_a_finished_turn_is_not_overwritten(hass: HomeAssistant) -> None:
    """The client may leave while the finished answer is on its way."""
    _debug_record_turn(hass, request_id="done1", user_prompt="hi", expanded_prompt="p", instructions_used="p",
                       picked_knowledge=[], tool_log=[], intent="chat", response_text="Hallo", elapsed_ms=10)
    _debug_record_aborted_turn(hass, request_id="done1", user_prompt="hi", expanded_prompt="p",
                               elapsed_ms=20, reason="client_gone")
    snap = hass.data[_DEBUG_LAST_TURN_KEY]
    assert snap["response_text"] == "Hallo"
    assert "aborted" not in snap


async def test_a_turn_without_request_id_records_nothing(hass: HomeAssistant) -> None:
    turn = _ChatTurn(hass)
    turn.begin()
    turn.record_abort("client_gone")
    turn.close()
    assert _DEBUG_LAST_TURN_KEY not in hass.data
