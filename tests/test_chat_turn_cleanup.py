"""A chat turn releases its shared state on every exit, including a client abort.

HA cancels the request handler when the browser goes away (Stop button, panel
timeout). The CancelledError passed every ``except Exception`` and left the busy
flag, the preempt event, a root-logger handler and the token reservation behind.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.kyber.api_utilities import _PROGRESS_KEY
from custom_components.kyber.http_api import (
    _CHAT_BUSY_KEY,
    _PREEMPT_EVENT_KEY,
    _ChatTurn,
)
from custom_components.kyber.token_budget import get_budget_provider
from custom_components.kyber.token_budget import get_store as get_token_budget_store


async def test_cancelled_turn_releases_everything(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    hass.data["kyber_config"] = {**(hass.data.get("kyber_config") or {}), "max_daily_tokens": 1_000_000}
    store = get_token_budget_store(hass)
    provider = get_budget_provider(hass.data["kyber_config"])
    root_handlers = len(logging.getLogger().handlers)
    seen: dict = {}

    async def cancelled_loop(*args, **kwargs):
        seen["busy"] = hass.data.get(_CHAT_BUSY_KEY)
        seen["preempt"] = hass.data[_PREEMPT_EVENT_KEY].is_set()
        seen["handlers"] = len(logging.getLogger().handlers)
        seen["pending"] = store._pending.get(provider, 0)
        raise asyncio.CancelledError  # what HA raises when the client disconnects

    client = await hass_client()
    # The server drops the connection, which is the point.
    with patch("custom_components.kyber.http_api._run_ai_loop", new=cancelled_loop), \
         contextlib.suppress(Exception):
        await client.post("/api/kyber/complete", json={"prompt": "hello", "request_id": "abort1"})

    # Mid-flight the turn held everything …
    assert seen["busy"] == 1
    assert seen["preempt"] is True
    assert seen["handlers"] == root_handlers + 1
    assert seen["pending"] > 0
    # … and gave all of it back.
    assert hass.data[_CHAT_BUSY_KEY] == 0
    assert not hass.data[_PREEMPT_EVENT_KEY].is_set()
    assert len(logging.getLogger().handlers) == root_handlers
    assert store._pending.get(provider, 0) == 0
    assert hass.data[_PROGRESS_KEY]["abort1"]["status"] == "done"


async def test_error_before_the_ai_loop_releases_busy(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Context building used to sit outside every cleanup branch."""
    client = await hass_client()
    with patch("custom_components.kyber.http_api._build_context", side_effect=RuntimeError("boom")):
        resp = await client.post("/api/kyber/complete", json={"prompt": "hello"})

    assert resp.status == 500
    assert hass.data[_CHAT_BUSY_KEY] == 0
    assert not hass.data[_PREEMPT_EVENT_KEY].is_set()


async def test_parallel_turns_count_instead_of_resetting(hass: HomeAssistant) -> None:
    first, second = _ChatTurn(hass), _ChatTurn(hass)
    first.begin()
    second.begin()
    assert hass.data[_CHAT_BUSY_KEY] == 2

    first.close()
    assert hass.data[_CHAT_BUSY_KEY] == 1  # still busy: background work keeps waiting
    assert hass.data[_PREEMPT_EVENT_KEY].is_set()

    first.close()  # idempotent: must not release the second turn's mark
    assert hass.data[_CHAT_BUSY_KEY] == 1

    second.end_busy()
    second.close()
    assert hass.data[_CHAT_BUSY_KEY] == 0
    assert not hass.data[_PREEMPT_EVENT_KEY].is_set()


async def test_close_releases_an_unsettled_reservation(hass: HomeAssistant) -> None:
    store = get_token_budget_store(hass)
    turn = _ChatTurn(hass)
    turn.begin()
    reservation, _ = await store.async_reserve("home_assistant", 10_000, 400)
    turn.hold(reservation)
    assert store._pending["home_assistant"] == 400

    turn.close()
    assert store._pending["home_assistant"] == 0


@pytest.mark.parametrize("settled", [True, False])
async def test_settled_reservation_is_not_released_again(hass: HomeAssistant, settled: bool) -> None:
    store = get_token_budget_store(hass)
    other, _ = await store.async_reserve("home_assistant", 10_000, 100)
    turn = _ChatTurn(hass)
    turn.begin()
    mine, _ = await store.async_reserve("home_assistant", 10_000, 400)
    turn.hold(mine)
    if settled:
        await mine.async_settle(50)

    turn.close()
    assert store._pending["home_assistant"] == 100  # only the other request's reservation is left
    other.release()
