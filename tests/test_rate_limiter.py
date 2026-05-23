from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from custom_components.kyber.rate_limiter import RateLimiter


def _make_ai_result(text: str) -> MagicMock:
    result = MagicMock()
    result.data = text
    return result


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter()

    allowed, retry_after = limiter.check_and_record("user-1", 2)
    assert allowed is True
    assert retry_after == 0

    allowed, retry_after = limiter.check_and_record("user-1", 2)
    assert allowed is True
    assert retry_after == 0

    allowed, retry_after = limiter.check_and_record("user-1", 2)
    assert allowed is False
    assert retry_after > 0


async def test_complete_endpoint_returns_429_when_rate_limited(
    hass,
    setup_integration,
    hass_client,
) -> None:
    client = await hass_client()
    with patch(
        "custom_components.kyber.http_api._rate_limiter.check_and_record",
        return_value=(False, 17),
    ) as check_mock, patch(
        "custom_components.kyber.http_api._run_ai_loop", new=AsyncMock()
    ) as run_ai_mock:
        resp = await client.post("/api/kyber/complete", json={"prompt": "hello"})

    assert resp.status == 429
    assert await resp.json() == {"error": "Too many requests", "retry_after": 17}
    check_mock.assert_called_once()
    run_ai_mock.assert_not_awaited()


async def test_complete_endpoint_records_request_when_allowed(
    hass,
    setup_integration,
    hass_client,
) -> None:
    client = await hass_client()
    with patch(
        "custom_components.kyber.http_api._rate_limiter.check_and_record",
        return_value=(True, 0),
    ) as check_mock, patch(
        "custom_components.kyber.api_utilities.async_generate_data",
        side_effect=lambda *a, **kw: _make_ai_result("ok"),
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "hello"})

    assert resp.status == 200
    check_mock.assert_called_once()
    user_id, max_rpm = check_mock.call_args.args
    assert max_rpm == 30
