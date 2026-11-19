"""Tests for Kyber token budget enforcement and reporting."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component


def _kyber_imports():
    from custom_components.kyber import async_setup_entry
    from custom_components.kyber.const import (
        CONF_MAX_DAILY_TOKENS,
        DEFAULT_MAX_DAILY_TOKENS,
        DOMAIN,
    )
    from custom_components.kyber.token_budget import get_budget_provider, get_store as get_token_budget_store

    return (
        async_setup_entry,
        CONF_MAX_DAILY_TOKENS,
        DEFAULT_MAX_DAILY_TOKENS,
        DOMAIN,
        get_budget_provider,
        get_token_budget_store,
    )


@pytest.fixture(autouse=True)
def mock_dependencies(hass: HomeAssistant) -> None:
    """Mark ai_task as available during config-flow and HTTP tests."""
    mock_component(hass, "ai_task")


@pytest.fixture(autouse=True)
def mock_initial_learning() -> None:
    """Prevent long-running background tasks during tests."""
    with patch("custom_components.kyber._async_run_initial_learning"), \
         patch("custom_components.kyber._async_explore_integrations"), \
         patch("custom_components.kyber._async_seed_language_hints"):
        yield


async def _setup_token_budget_integration(
    hass: HomeAssistant,
    *,
    max_daily_tokens: int,
) -> MockConfigEntry:
    (
        async_setup_entry,
        CONF_MAX_DAILY_TOKENS,
        _,
        DOMAIN,
        _,
        _,
    ) = _kyber_imports()
    await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kyber",
        data={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "max_tokens": 4096,
            CONF_MAX_DAILY_TOKENS: max_daily_tokens,
        },
    )
    entry.add_to_hass(hass)
    with patch("custom_components.kyber._async_explore_integrations", new_callable=AsyncMock):
        assert await async_setup_entry(hass, entry)
        await asyncio.sleep(0)
    return entry


async def test_token_budget_store_resets_on_date_change(hass: HomeAssistant) -> None:
    """Stored usage should reset automatically when the local date changes."""
    (_, _, _, _, _, get_token_budget_store) = _kyber_imports()
    store = get_token_budget_store(hass)

    with patch("custom_components.kyber.token_budget.dt_util.now", return_value=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)):
        usage = await store.async_record("home_assistant", 120, 1000)
        assert usage["used"] == 120
        assert usage["pct"] == 12

    with patch("custom_components.kyber.token_budget.dt_util.now", return_value=datetime(2025, 1, 2, 0, 1, tzinfo=timezone.utc)):
        usage = await store.async_get_usage("home_assistant", 1000)
        assert usage["used"] == 0
        assert usage["pct"] == 0


async def test_config_flow_defaults_max_daily_tokens_to_zero(hass: HomeAssistant) -> None:
    """The new token budget option should default to disabled."""
    (_, CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS, DOMAIN, _, _) = _kyber_imports()
    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "model_config": {"max_tokens": 32_000},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MAX_DAILY_TOKENS] == DEFAULT_MAX_DAILY_TOKENS


async def test_complete_rejects_when_daily_budget_exceeded(
    hass: HomeAssistant,
    hass_client,
) -> None:
    """The AI call should be blocked once the configured daily budget is exhausted."""
    (_, _, _, _, get_budget_provider, get_token_budget_store) = _kyber_imports()
    entry = await _setup_token_budget_integration(hass, max_daily_tokens=100)
    store = get_token_budget_store(hass)
    provider = get_budget_provider(entry.data)
    await store.async_record(provider, 100, 100)

    client = await hass_client()
    with patch("custom_components.kyber.http_api._run_ai_loop", new_callable=AsyncMock) as run_ai_loop:
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello Kyber"})

    assert resp.status == 429
    body = await resp.json()
    assert body["error"] == "Daily token budget exceeded. Resets at midnight."
    assert body["budget_warning"] is True
    assert body["token_usage"]["used"] == 100
    assert body["token_usage"]["budget"] == 100
    run_ai_loop.assert_not_awaited()


async def test_complete_reports_token_usage_and_warning(
    hass: HomeAssistant,
    hass_client,
) -> None:
    """Successful responses should include updated usage and soft-limit warnings."""
    (_, _, _, _, get_budget_provider, get_token_budget_store) = _kyber_imports()
    entry = await _setup_token_budget_integration(hass, max_daily_tokens=5000)
    store = get_token_budget_store(hass)
    provider = get_budget_provider(entry.data)
    await store.async_record(provider, 0, 10000)

    client = await hass_client()
    with patch.object(
        store,
        "async_check",
        new=AsyncMock(return_value=(True, {"used": 0, "budget": 5000, "pct": 0, "warning": False})),
    ), patch(
        "custom_components.kyber.http_api._run_ai_loop",
        new=AsyncMock(
            return_value=(
                "Budget-aware answer",
                [],
                "",
                {},
                "informational",
                "instructions",
                [],
                {
                    "provider": provider,
                    "prompt_tokens": 1400,
                    "response_tokens": 2800,
                    "total_tokens": 4200,
                    "calls": 1,
                },
            )
        ),
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Summarize my home"})

    assert resp.status == 200
    body = await resp.json()
    assert body["response"] == "Budget-aware answer"
    assert body["token_usage"]["used"] == 4200
    assert body["token_usage"]["budget"] == 5000
    assert body["token_usage"]["pct"] == 84
    assert body["budget_warning"] is True


async def test_debug_status_includes_token_usage(
    hass: HomeAssistant,
    hass_client,
) -> None:
    """Debug status should expose the same token budget snapshot as chat."""
    (_, _, _, _, get_budget_provider, get_token_budget_store) = _kyber_imports()
    entry = await _setup_token_budget_integration(hass, max_daily_tokens=1000)
    store = get_token_budget_store(hass)
    provider = get_budget_provider(entry.data)
    await store.async_record(provider, 250, 1000)

    client = await hass_client()
    resp = await client.get("/api/kyber/debug/status")

    assert resp.status == 200
    body = await resp.json()
    assert body["token_usage"]["provider"] == provider
    assert body["token_usage"]["used"] == 250
    assert body["token_usage"]["budget"] == 1000
    assert body["token_usage"]["pct"] == 25


@pytest.mark.parametrize(
    ("raised_kind", "expected_status"),
    [
        ("provider", 503),
        ("unexpected", 500),
    ],
)
async def test_complete_releases_token_reservation_on_ai_failures(
    hass: HomeAssistant,
    hass_client,
    raised_kind: str,
    expected_status: int,
) -> None:
    """On AI failure the previously-reserved tokens should be released (net usage = 0)."""
    from custom_components.kyber import http_api as http_api_module

    (_, _, _, _, get_budget_provider, get_token_budget_store) = _kyber_imports()
    entry = await _setup_token_budget_integration(hass, max_daily_tokens=1_000_000)
    store = get_token_budget_store(hass)
    provider = get_budget_provider(entry.data)
    raised = (
        http_api_module.HomeAssistantError("provider unavailable")
        if raised_kind == "provider"
        else RuntimeError("boom")
    )
    reserved: list[int] = []

    async def failing_loop(*args, **kwargs):
        reserved.append(store._pending.get(provider, 0))
        raise raised

    client = await hass_client()
    with patch("custom_components.kyber.http_api._run_ai_loop", new=failing_loop):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Explain the living room lights"})

    assert resp.status == expected_status
    assert reserved and reserved[0] > 0  # the turn did reserve tokens
    assert store._pending.get(provider, 0) == 0  # … and released them
    usage = await store.async_get_usage(provider, 1_000_000)
    assert usage["used"] == 0  # nothing burned


async def test_reservation_settles_once(hass: HomeAssistant) -> None:
    """Settling books the real usage; a later release must not free it twice."""
    (_, _, _, _, _, get_token_budget_store) = _kyber_imports()
    store = get_token_budget_store(hass)

    other, _ = await store.async_reserve("home_assistant", 10_000, 300)
    mine, _ = await store.async_reserve("home_assistant", 10_000, 500)
    assert store._pending["home_assistant"] == 800

    usage = await mine.async_settle(120)
    mine.release()  # e.g. from a finally after success: must be a no-op
    assert usage["used"] == 120
    assert store._pending["home_assistant"] == 300  # the other request keeps its reservation

    other.release()
    other.release()
    assert store._pending["home_assistant"] == 0


async def test_reserve_refuses_without_reservation(hass: HomeAssistant) -> None:
    """Over budget: no reservation is made, so there is nothing to release."""
    (_, _, _, _, _, get_token_budget_store) = _kyber_imports()
    store = get_token_budget_store(hass)
    await store.async_record("home_assistant", 1_000, 1_000)

    reservation, usage = await store.async_reserve("home_assistant", 1_000, 50)

    assert reservation is None
    assert usage["exceeded"] is True
    assert store._pending.get("home_assistant", 0) == 0


async def test_pending_resets_on_date_change(hass: HomeAssistant) -> None:
    """Reservations from yesterday must not block today, nor eat today's reservations."""
    (_, _, _, _, _, get_token_budget_store) = _kyber_imports()
    store = get_token_budget_store(hass)
    day1 = datetime(2025, 1, 1, 23, 59, tzinfo=timezone.utc)
    day2 = datetime(2025, 1, 2, 0, 1, tzinfo=timezone.utc)

    with patch("custom_components.kyber.token_budget.dt_util.now", return_value=day1):
        # A leaked reservation that alone would exhaust the budget.
        await store.async_check("home_assistant", 1_000, estimated_tokens=990)
        spanning, _ = await store.async_reserve("home_assistant", 1_000, 5)
        allowed, _ = await store.async_check("home_assistant", 1_000, estimated_tokens=10)
        assert allowed is False

    with patch("custom_components.kyber.token_budget.dt_util.now", return_value=day2):
        today, _ = await store.async_reserve("home_assistant", 1_000, 10)
        assert today is not None
        assert store._pending["home_assistant"] == 10
        spanning.release()  # reserved yesterday: must not touch today's reservation
        assert store._pending["home_assistant"] == 10
