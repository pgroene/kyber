from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from custom_components.kyber.ci_integration import (
    _CI_EVENT_LOG_KEY,
    handle_celebrate,
    handle_ci_event,
    handle_get_home_context,
    handle_peace_briefing,
)


def _make_hass():
    hass = MagicMock()
    hass.data = {}
    hass.bus.async_fire = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.mark.asyncio
async def test_handle_ci_event_fires_and_logs_event():
    hass = _make_hass()

    result = await handle_ci_event(
        hass,
        {
            "type": "build_failed",
            "repo": "pgroene/ProspectPilot",
            "branch": "main",
            "status": "failure",
            "message": "Deploy failed",
        },
    )

    assert result["fired"] is True
    hass.bus.async_fire.assert_called_once()
    logged = list(hass.data[_CI_EVENT_LOG_KEY])
    assert len(logged) == 1
    assert logged[0]["type"] == "build_failed"
    assert logged[0]["status"] == "failure"


@pytest.mark.asyncio
async def test_handle_celebrate_sends_notification_and_logs_event():
    hass = _make_hass()

    result = await handle_celebrate(hass, {"reason": "Merged to prod"})

    assert result == {"celebrated": True, "reason": "Merged to prod"}
    hass.bus.async_fire.assert_called_once()
    hass.services.async_call.assert_awaited_once()
    assert list(hass.data[_CI_EVENT_LOG_KEY])[0]["type"] == "celebrate"


@pytest.mark.asyncio
async def test_handle_get_home_context_falls_back_when_ai_returns_invalid_json():
    hass = _make_hass()
    now = datetime(2025, 1, 1, 18, 15, tzinfo=timezone.utc)

    with patch("custom_components.kyber.ci_integration._run_kyber_prompt", new=AsyncMock(return_value="not json")), \
         patch("custom_components.kyber.ci_integration.ha_dt.now", return_value=now):
        result = await handle_get_home_context(hass, {}, {"ai_task_entity_id": "conversation.mock"}, "user-1")

    assert result["can_deploy"] is False
    assert result["reason"] == "dinner_window"
    assert result["local_time"] == "18:15"
    assert result["raw_kyber_response"] == "not json"


@pytest.mark.asyncio
async def test_handle_peace_briefing_uses_fallback_when_ai_fails():
    hass = _make_hass()
    hass.data[_CI_EVENT_LOG_KEY] = deque(
        [
            {
                "type": "deploy_success",
                "repo": "pgroene/ProspectPilot",
                "branch": "main",
                "status": "success",
                "message": "Production deploy completed",
                "local_time": "20:05",
            }
        ],
        maxlen=50,
    )

    with patch("custom_components.kyber.ci_integration._run_kyber_prompt", new=AsyncMock(side_effect=RuntimeError("offline"))):
        result = await handle_peace_briefing(hass, {"max_events": 5}, {"ai_task_entity_id": "conversation.mock"}, "user-1")

    assert result["count"] == 1
    assert "Production deploy completed" in result["briefing"]
    assert result["events"][0]["type"] == "deploy_success"
