"""Lifecycle of the config entry: reload trigger, runtime state, gated views,
unload, and the periodic learning check."""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

# Kyber modules are imported at test time: other test modules swap stubs into
# sys.modules while they are collected; conftest restores the real modules
# before each test.
CONF_DEEP_LEARNING_LAST_RUN_TS = "deep_learning_last_run_ts"
CONF_ENABLE_MCP = "enable_mcp"
CONF_INITIAL_LEARNING_DONE = "initial_learning_done"
CONF_INITIAL_LEARNING_VERSION = "initial_learning_version"
CONF_NARRATOR_LAST_RUN_TS = "narrator_last_run_ts"
CONF_NARRATOR_MAX_BATCH = "narrator_max_batch"
DOMAIN = "kyber"


@pytest.fixture
def kyber():
    import custom_components.kyber as mod
    return mod


@pytest.fixture
def rt():
    from custom_components.kyber import runtime_state
    return runtime_state


def test_mirrored_constants_match() -> None:
    from custom_components.kyber import const
    assert const.CONF_DEEP_LEARNING_LAST_RUN_TS == CONF_DEEP_LEARNING_LAST_RUN_TS
    assert const.CONF_ENABLE_MCP == CONF_ENABLE_MCP
    assert const.CONF_INITIAL_LEARNING_DONE == CONF_INITIAL_LEARNING_DONE
    assert const.CONF_INITIAL_LEARNING_VERSION == CONF_INITIAL_LEARNING_VERSION
    assert const.CONF_NARRATOR_LAST_RUN_TS == CONF_NARRATOR_LAST_RUN_TS
    assert const.CONF_NARRATOR_MAX_BATCH == CONF_NARRATOR_MAX_BATCH
    assert const.DOMAIN == DOMAIN

class _Entry:
    def __init__(self, data=None, options=None):
        self.entry_id = "kyber-test"
        self.data = data or {}
        self.options = options or {}


# ---------------------------------------------------------------------------
# Update listener: reload only on real options changes
# ---------------------------------------------------------------------------

async def test_listener_ignores_data_only_update(kyber) -> None:
    hass = type("H", (), {})()
    hass.data = {}
    hass.config_entries = type("CE", (), {})()
    hass.config_entries.async_reload = AsyncMock()
    entry = _Entry(data={"ai_task_entity_id": "ai_task.x"}, options={"chat_model": "a"})
    listener = kyber._make_update_listener(entry.options)

    # The integration itself writes entry.data (formerly run timestamps).
    entry.data = {**entry.data, CONF_NARRATOR_LAST_RUN_TS: time.time()}
    await listener(hass, entry)

    hass.config_entries.async_reload.assert_not_awaited()


async def test_listener_reloads_on_options_change(kyber) -> None:
    hass = type("H", (), {})()
    hass.data = {}
    hass.config_entries = type("CE", (), {})()
    hass.config_entries.async_reload = AsyncMock()
    entry = _Entry(options={"chat_model": "a"})
    listener = kyber._make_update_listener(entry.options)

    entry.options = {"chat_model": "b"}
    await listener(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with("kyber-test")

    # Same options again (e.g. a later data write) → no second reload.
    await listener(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once()


async def test_listener_narrator_only_change_refreshes_live_config(kyber) -> None:
    hass = type("H", (), {})()
    hass.data = {"kyber_config": {CONF_NARRATOR_MAX_BATCH: 10}}
    hass.config_entries = type("CE", (), {})()
    hass.config_entries.async_reload = AsyncMock()
    entry = _Entry(data={"ai_task_entity_id": "ai_task.x"}, options={CONF_NARRATOR_MAX_BATCH: 10})
    listener = kyber._make_update_listener(entry.options)

    entry.options = {CONF_NARRATOR_MAX_BATCH: 25}
    await listener(hass, entry)

    hass.config_entries.async_reload.assert_not_awaited()
    assert hass.data["kyber_config"][CONF_NARRATOR_MAX_BATCH] == 25
    assert hass.data["kyber_config"]["ai_task_entity_id"] == "ai_task.x"


# ---------------------------------------------------------------------------
# Runtime state: timestamps and learning version live outside entry.data
# ---------------------------------------------------------------------------

async def test_runtime_state_takes_over_legacy_entry_data(hass: HomeAssistant, rt) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ai_task_entity_id": "ai_task.x",
            CONF_NARRATOR_LAST_RUN_TS: 1000.0,
            CONF_DEEP_LEARNING_LAST_RUN_TS: 2000.0,
            CONF_INITIAL_LEARNING_VERSION: 3,
            CONF_INITIAL_LEARNING_DONE: True,
        },
    )
    entry.add_to_hass(hass)

    state = await rt.async_setup_runtime_state(hass, entry)

    assert entry.data == {"ai_task_entity_id": "ai_task.x"}
    assert state.get(CONF_NARRATOR_LAST_RUN_TS) == 1000.0
    assert state.get(CONF_DEEP_LEARNING_LAST_RUN_TS) == 2000.0
    assert state.get(CONF_INITIAL_LEARNING_VERSION) == 3
    assert rt.get_runtime_state(hass) is state

    # Persisted: a fresh instance reads the same values.
    reread = rt.RuntimeState(hass)
    await reread.async_load()
    assert reread.get(CONF_NARRATOR_LAST_RUN_TS) == 1000.0


async def test_runtime_state_keeps_newer_values_over_legacy(hass: HomeAssistant, rt) -> None:
    first = rt.RuntimeState(hass)
    await first.async_load()
    await first.async_set(CONF_NARRATOR_LAST_RUN_TS, 5000.0)

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NARRATOR_LAST_RUN_TS: 1000.0})
    entry.add_to_hass(hass)
    state = await rt.async_setup_runtime_state(hass, entry)

    assert state.get(CONF_NARRATOR_LAST_RUN_TS) == 5000.0
    assert CONF_NARRATOR_LAST_RUN_TS not in entry.data


# ---------------------------------------------------------------------------
# HTTP views: registered once, gated on load state and enable_mcp
# ---------------------------------------------------------------------------

_MCP_PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


async def test_views_answer_503_after_unload(
    hass: HomeAssistant, setup_integration, hass_client, kyber
) -> None:
    client = await hass_client()
    assert (await client.get("/api/kyber/ping")).status == 200
    assert (await client.post("/api/kyber/mcp", json=_MCP_PING)).status == 200

    assert await kyber.async_unload_entry(hass, setup_integration)

    assert "kyber_config" not in hass.data
    assert (await client.get("/api/kyber/ping")).status == 503
    assert (await client.post("/api/kyber/mcp", json=_MCP_PING)).status == 503


async def test_mcp_answers_404_when_disabled(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    client = await hass_client()
    hass.data["kyber_config"] = {**hass.data["kyber_config"], CONF_ENABLE_MCP: False}

    assert (await client.post("/api/kyber/mcp", json=_MCP_PING)).status == 404
    assert (await client.get("/api/kyber/mcp/log")).status == 404
    # Other views are unaffected.
    assert (await client.get("/api/kyber/ping")).status == 200

    hass.data["kyber_config"] = {**hass.data["kyber_config"], CONF_ENABLE_MCP: True}
    assert (await client.post("/api/kyber/mcp", json=_MCP_PING)).status == 200


async def test_views_registered_once_across_reload(
    hass: HomeAssistant, setup_integration, kyber
) -> None:
    assert await kyber.async_unload_entry(hass, setup_integration)
    with (
        patch.object(hass.http, "register_view") as register_view,
        patch.object(hass.http, "async_register_static_paths", new_callable=AsyncMock) as static,
        patch("custom_components.kyber._async_run_initial_learning", new_callable=AsyncMock),
        patch("custom_components.kyber._async_explore_integrations", new_callable=AsyncMock),
        patch("custom_components.kyber._async_seed_language_hints", new_callable=AsyncMock),
    ):
        assert await kyber.async_setup_entry(hass, setup_integration)
        await asyncio.sleep(0)

    register_view.assert_not_called()
    static.assert_not_awaited()
    assert "kyber_config" in hass.data
    await kyber.async_unload_entry(hass, setup_integration)


def test_view_list_has_no_duplicate_urls(kyber) -> None:
    urls = [view.url for view in kyber._build_views({})]
    assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# Unload: bounded wait for cancelled background tasks
# ---------------------------------------------------------------------------

async def test_unload_does_not_hang_on_task_ignoring_cancel(
    hass: HomeAssistant, setup_integration, kyber
) -> None:
    release = asyncio.Event()

    async def _stubborn() -> None:
        while not release.is_set():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                continue  # swallows cancellation, like the old narrator did

    task = asyncio.ensure_future(_stubborn())
    hass.data[kyber._BG_TASKS_KEY].append(task)
    await asyncio.sleep(0)  # let it reach the sleep, so cancel() hits the try block

    with (
        patch.object(kyber, "_UNLOAD_TASK_TIMEOUT", 0.05),
        patch.object(kyber._LOGGER, "warning") as warn,
    ):
        assert await kyber.async_unload_entry(hass, setup_integration)

    assert not task.done()  # unload returned although the task kept running
    assert "still running" in warn.call_args[0][0]
    release.set()
    task.cancel()
    await asyncio.wait({task})


# ---------------------------------------------------------------------------
# Periodic learning check
# ---------------------------------------------------------------------------

async def test_hourly_tick_runs_due_learning_until_unload(
    hass: HomeAssistant, setup_integration, kyber
) -> None:
    with patch(
        "custom_components.kyber._async_run_due_learning", new_callable=AsyncMock
    ) as due:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, seconds=1))
        await hass.async_block_till_done()
        assert due.await_count == 1

        await kyber.async_unload_entry(hass, setup_integration)
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=2, seconds=2))
        await hass.async_block_till_done()
        assert due.await_count == 1


async def _run_due(kyber, hass: HomeAssistant, entry) -> tuple[AsyncMock, AsyncMock]:
    narrate = AsyncMock(return_value={"errors": 0})
    analyze = AsyncMock(return_value={"analyzed": [], "errors": []})
    with (
        patch("custom_components.kyber.entity_narrator.async_narrate_entities", narrate),
        patch.object(kyber._deep, "analyze_pending", analyze),
        patch.object(kyber, "_analyze_automations"),
    ):
        await kyber._async_run_due_learning(hass, entry)
    return narrate, analyze


async def test_due_learning_runs_when_interval_elapsed(
    hass: HomeAssistant, setup_integration, kyber, rt
) -> None:
    entry = setup_integration
    runtime = rt.get_runtime_state(hass)
    old = time.time() - 30 * 86400
    await runtime.async_set(CONF_NARRATOR_LAST_RUN_TS, old)
    await runtime.async_set(CONF_DEEP_LEARNING_LAST_RUN_TS, old)
    data_before = dict(entry.data)

    narrate, analyze = await _run_due(kyber, hass, entry)

    narrate.assert_awaited_once()
    analyze.assert_awaited_once()
    assert runtime.get(CONF_NARRATOR_LAST_RUN_TS) > old
    assert runtime.get(CONF_DEEP_LEARNING_LAST_RUN_TS) > old
    assert dict(entry.data) == data_before  # nothing written into the config entry
    await kyber.async_unload_entry(hass, entry)


async def test_due_learning_skips_when_recent(
    hass: HomeAssistant, setup_integration, kyber, rt
) -> None:
    runtime = rt.get_runtime_state(hass)
    await runtime.async_set(CONF_NARRATOR_LAST_RUN_TS, time.time() - 60)
    await runtime.async_set(CONF_DEEP_LEARNING_LAST_RUN_TS, time.time() - 60)

    narrate, analyze = await _run_due(kyber, hass, setup_integration)

    narrate.assert_not_awaited()
    analyze.assert_not_awaited()
    await kyber.async_unload_entry(hass, setup_integration)


async def test_due_learning_skips_while_cycle_running(
    hass: HomeAssistant, setup_integration, kyber
) -> None:
    lock = hass.data.setdefault(kyber._LEARNING_CYCLE_LOCK_KEY, asyncio.Lock())
    async with lock:
        narrate, analyze = await _run_due(kyber, hass, setup_integration)
    narrate.assert_not_awaited()
    analyze.assert_not_awaited()
    await kyber.async_unload_entry(hass, setup_integration)
