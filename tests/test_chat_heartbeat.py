"""A long chat turn keeps a reverse proxy in front of HA from timing out.

nginx answered 504 after its 60 s ``proxy_read_timeout`` because the panel's
POST /api/kyber/complete sent nothing until the model was done. A turn that
is not done after the grace period now gets its 200 at once, a space every
interval and the JSON document at the end.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import MagicMock, patch

from aiohttp import web
from homeassistant.core import HomeAssistant
import pytest

_MODULE = "custom_components.kyber.http_api"


@pytest.fixture
def short_heartbeat():
    with patch(f"{_MODULE}._HEARTBEAT_GRACE_SEC", 0.05), \
         patch(f"{_MODULE}._HEARTBEAT_INTERVAL_SEC", 0.05):
        yield


async def _client_for(hass, hass_client, work_factory):
    """A client for a view that answers through the heartbeat (HA's test server allows no other)."""
    from homeassistant.components.http import HomeAssistantView
    from homeassistant.setup import async_setup_component

    from custom_components.kyber.http_api import _respond_with_heartbeat

    class _TurnView(HomeAssistantView):
        url = "/api/kyber_test/turn"
        name = "api:kyber_test:turn"

        async def post(self, request: web.Request) -> web.StreamResponse:
            return await _respond_with_heartbeat(request, work_factory())

    await async_setup_component(hass, "http", {})
    hass.http.register_view(_TurnView())
    return await hass_client()


async def test_quick_reply_keeps_its_status(hass: HomeAssistant, hass_client, short_heartbeat) -> None:
    async def work():
        return web.json_response({"message": "Missing 'prompt' field"}, status=400)

    client = await _client_for(hass, hass_client, work)
    resp = await client.post("/api/kyber_test/turn")
    assert resp.status == 400
    assert await resp.json() == {"message": "Missing 'prompt' field"}


async def test_slow_reply_sends_spaces_then_the_document(hass: HomeAssistant, hass_client, short_heartbeat) -> None:
    async def work():
        await asyncio.sleep(0.3)
        return web.json_response({"response": "It is 17 °C."})

    client = await _client_for(hass, hass_client, work)
    resp = await client.post("/api/kyber_test/turn")
    assert resp.status == 200
    assert resp.headers["X-Accel-Buffering"] == "no"
    text = await resp.text()
    assert text.startswith(" ")
    assert len(text) - len(text.lstrip(" ")) >= 3  # one space per interval
    assert json.loads(text) == {"response": "It is 17 °C."}


async def test_slow_error_carries_its_status_in_the_body(hass: HomeAssistant, hass_client, short_heartbeat) -> None:
    async def work():
        await asyncio.sleep(0.15)
        return web.json_response({"message": "AI provider error: overloaded"}, status=503)

    client = await _client_for(hass, hass_client, work)
    resp = await client.post("/api/kyber_test/turn")
    assert resp.status == 200
    assert json.loads(await resp.text()) == {
        "message": "AI provider error: overloaded",
        "_http_status": 503,
    }


async def test_slow_plain_text_error_becomes_a_message(hass: HomeAssistant, hass_client, short_heartbeat) -> None:
    async def work():
        await asyncio.sleep(0.15)
        return web.Response(text="upstream broke", status=502)

    client = await _client_for(hass, hass_client, work)
    resp = await client.post("/api/kyber_test/turn")
    assert json.loads(await resp.text()) == {"message": "upstream broke", "_http_status": 502}


async def test_slow_crash_still_ends_with_a_document(hass: HomeAssistant, hass_client, short_heartbeat) -> None:
    async def work():
        await asyncio.sleep(0.15)
        raise RuntimeError("boom")

    client = await _client_for(hass, hass_client, work)
    resp = await client.post("/api/kyber_test/turn")
    assert resp.status == 200
    assert json.loads(await resp.text()) == {"message": "Internal error", "_http_status": 500}


async def test_cancelling_the_request_cancels_the_turn(short_heartbeat) -> None:
    """HA cancels the handler when the browser goes away; the turn must stop with it."""
    from custom_components.kyber.http_api import _respond_with_heartbeat

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with patch(f"{_MODULE}._HEARTBEAT_GRACE_SEC", 60):
        handler = asyncio.ensure_future(_respond_with_heartbeat(MagicMock(), work()))
        await started.wait()
        handler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await handler

    assert cancelled.is_set()


async def test_complete_endpoint_streams_a_slow_failure(
    hass: HomeAssistant, setup_integration, hass_client, short_heartbeat
) -> None:
    """The real view: the turn's shared state is released after the stream ends."""
    from custom_components.kyber.http_api import _CHAT_BUSY_KEY

    async def slow_failure(*args, **kwargs):
        await asyncio.sleep(0.2)
        raise RuntimeError("boom")

    client = await hass_client()
    with patch(f"{_MODULE}._run_ai_loop", new=slow_failure):
        resp = await client.post("/api/kyber/complete", json={"prompt": "hello"})
        text = await resp.text()

    assert resp.status == 200
    assert text.startswith(" ")
    assert json.loads(text)["_http_status"] == 500
    assert hass.data[_CHAT_BUSY_KEY] == 0
