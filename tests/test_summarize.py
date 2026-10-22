"""Functional tests for POST /api/kyber/summarize.

Documented in docs/chat-and-ai.md — the frontend calls this when the chat
history exceeds ~20 messages, to compact older turns into a running summary.
The summary is bounded to the stored limit. If the AI is unavailable the
endpoint answers 503 and the panel keeps the messages (#223); it no longer
appends them as raw text, which grew the summary without bound.
"""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_PATCH_GENERATE = "custom_components.kyber.api_utilities.async_generate_data"


def _make_ai_result(text: str) -> MagicMock:
    r = MagicMock()
    r.data = text
    return r


async def test_summarize_returns_ai_summary(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The AI-generated summary should be returned in the 'summary' field."""
    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        return _make_ai_result("User turned on lights. Automation was created.")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/summarize",
            json={
                "messages": [
                    {"role": "user", "content": "Turn on lights"},
                    {"role": "assistant", "content": "Done, lights are on."},
                ],
            },
        )

    assert resp.status == 200
    data = await resp.json()
    assert "summary" in data
    assert len(data["summary"]) > 0


async def test_summarize_passes_previous_summary_to_ai(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The previous_summary should be included in the instructions sent to the AI."""
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["instructions"] = instructions
        return _make_ai_result("Updated summary.")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/summarize",
            json={
                "previous_summary": "Earlier the user asked about temperature.",
                "messages": [{"role": "user", "content": "Now lights please"}],
            },
        )

    assert resp.status == 200
    assert "Earlier the user asked about temperature." in captured["instructions"]
    assert "Now lights please" in captured["instructions"]


async def test_summarize_empty_messages_returns_previous_summary(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """When messages list is empty, the previous_summary should be returned unchanged."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/summarize",
        json={
            "previous_summary": "User turned on lights.",
            "messages": [],
        },
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["summary"] == "User turned on lights."


async def test_summarize_no_messages_key_returns_previous_summary(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """When the messages key is omitted, previous_summary is returned unchanged."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/summarize",
        json={"previous_summary": "Some prior context."},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["summary"] == "Some prior context."


async def test_summarize_ai_failure_answers_503(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """When the AI fails, answer 503 so the panel keeps the messages and retries later."""
    async def failing(*a, **kw):
        raise HomeAssistantError("AI unavailable")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=failing):
        resp = await client.post(
            "/api/kyber/summarize",
            json={
                "previous_summary": "Context so far.",
                "messages": [
                    {"role": "user", "content": "What is the temperature?"},
                    {"role": "assistant", "content": "It is 22°C."},
                ],
            },
        )

    assert resp.status == 503


async def test_summarize_is_bounded_and_told_its_limit(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The summarizer gets the limit; an overlong answer loses its oldest part, not its newest."""
    from custom_components.kyber.session_and_storage import _CHAT_SUMMARY_MAX_CHARS

    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["instructions"] = instructions
        return _make_ai_result("OLD " + "x" * (_CHAT_SUMMARY_MAX_CHARS + 500) + " NEWEST")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/summarize",
            json={"messages": [{"role": "user", "content": "Continue"}]},
        )

    assert resp.status == 200
    summary = (await resp.json())["summary"]
    assert len(summary) == _CHAT_SUMMARY_MAX_CHARS
    assert summary.endswith("NEWEST") and not summary.startswith("OLD")
    assert f"must not exceed {_CHAT_SUMMARY_MAX_CHARS} characters" in captured["instructions"]


async def test_summarize_unauthenticated_returns_401(
    hass: HomeAssistant, setup_integration, hass_client_no_auth
) -> None:
    """Unauthenticated /summarize requests should return 401."""
    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/kyber/summarize",
        json={"messages": [{"role": "user", "content": "test"}]},
    )

    assert resp.status == 401


async def test_invalid_json_body_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Non-JSON body to /summarize should return 400."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/summarize",
        data=b"definitely not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400
