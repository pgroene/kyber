from __future__ import annotations

import io
import json
import zipfile

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from custom_components.kyber.const import _redact_secrets


def test_redact_secrets_redacts_nested_values() -> None:
    payload = {
        "Authorization": "Bearer super-secret-token",
        "nested": {
            "api_key": "abc123456",
            "items": ["password=hunter22", {"token": "keep-out"}],
        },
        "note": "sk-ABCDEFGHIJKLMNOPQRSTUVWX",
    }

    redacted = _redact_secrets(payload)

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["items"][0] == "[REDACTED]"
    assert redacted["nested"]["items"][1]["token"] == "[REDACTED]"
    assert redacted["note"] == "[REDACTED]"


async def test_debug_bundle_redacts_secrets(
    hass,
    setup_integration,
    hass_client,
) -> None:
    hass.data["kyber_debug_last_turn"] = {
        "request_id": "req-1",
        "ts": 123,
        "intent": "debug",
        "elapsed_ms": 10,
        "char_count": 20,
        "approx_tokens": 5,
        "auto_rating": None,
        "session_meta": {"access_token": "super-secret-token"},
        "user_prompt": "Bearer topsecretvalue",
        "expanded_prompt": "api_key=abc123456",
        "instructions_used": "password=hunter22",
        "response_text": "sk-ABCDEFGHIJKLMNOPQRSTUVWX",
        "tool_log": [{"headers": {"Authorization": "Bearer anothersecret"}}],
        "picked_knowledge": [{"content": "api_key=abcdefghi"}],
        "progress_events": [{"message": "password=anothersecret"}],
        "logs": [{"ts": 1, "level": "INFO", "logger": "kyber.test", "message": "Bearer hidden-token"}],
    }

    client = await hass_client()
    resp = await client.get("/api/kyber/debug/bundle")

    assert resp.status == 200
    bundle = await resp.read()
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        snapshot = json.loads(zf.read("snapshot.json"))
        logs_txt = zf.read("logs.txt").decode("utf-8")
        response_text = zf.read("response.txt").decode("utf-8")

    assert snapshot["session_meta"]["access_token"] == "[REDACTED]"
    assert snapshot["tool_log"][0]["headers"]["Authorization"] == "[REDACTED]"
    assert snapshot["user_prompt"] == "[REDACTED]"
    assert snapshot["expanded_prompt"] == "[REDACTED]"
    assert snapshot["instructions_used"] == "[REDACTED]"
    assert response_text == "[REDACTED]"
    assert "hidden-token" not in logs_txt
    assert "[REDACTED]" in logs_txt


async def test_knowledge_endpoint_rejects_credential_content(
    hass,
    setup_integration,
    hass_client,
) -> None:
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/knowledge",
        json={"content": "api_key=supersecret123", "subject": "bad entry"},
    )

    assert resp.status == 400
    assert await resp.json() == {"error": "Content contains credential pattern"}
