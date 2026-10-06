"""Tests for the configurable chat timeout (option ``chat_timeout``).

Covers:
  - get_chat_timeout(): default, clamping, invalid values
  - Options flow: field present, value stored
  - GET /api/kyber/chat_settings returns the configured / default value
  - _run_ai_loop: per-round wait_for limit and cloud HTTP limit grow with the
    chat timeout but never drop below their old fixed values (180s / 120s)
"""
import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="requires pytest-homeassistant-custom-component",
)

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.kyber.const import (
    CLOUD_PROVIDER_OPENAI,
    CONF_CHAT_TIMEOUT,
    CONF_CLOUD_PROVIDER,
    CONF_CLOUD_USE_FOR_CHAT,
    CONF_OPENAI_API_KEY,
    CONF_OPENAI_MODEL,
    DEFAULT_CHAT_TIMEOUT,
    DOMAIN,
    MAX_CHAT_TIMEOUT,
    MIN_AI_CALL_TIMEOUT,
    MIN_CHAT_TIMEOUT,
    MIN_CLOUD_HTTP_TIMEOUT,
    get_chat_timeout,
)

_PATCH_OPENAI = "custom_components.kyber.http_api.async_openai_ai_call"


@pytest.fixture(autouse=True)
def mock_background_tasks(hass: HomeAssistant):
    """Keep setup free of background learning tasks."""
    mock_component(hass, "ai_task")
    with (
        patch("custom_components.kyber._async_run_initial_learning"),
        patch("custom_components.kyber._async_explore_integrations"),
        patch("custom_components.kyber._async_seed_language_hints"),
    ):
        yield


def _make_ai_result(text: str) -> MagicMock:
    r = MagicMock()
    r.data = text
    return r


async def _setup(hass: HomeAssistant, extra: dict | None = None) -> MockConfigEntry:
    from custom_components.kyber import async_setup_entry as _setup_entry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "max_tokens": 2048,
            CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_OPENAI,
            CONF_CLOUD_USE_FOR_CHAT: True,
            CONF_OPENAI_API_KEY: "sk-test",
            CONF_OPENAI_MODEL: "gpt-4o",
            **(extra or {}),
        },
        title="Kyber",
    )
    await async_setup_component(hass, "http", {})
    with patch("custom_components.kyber._async_explore_integrations", new_callable=AsyncMock):
        await _setup_entry(hass, entry)
        await asyncio.sleep(0)
    return entry


# ── get_chat_timeout ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (None, DEFAULT_CHAT_TIMEOUT),
        ({}, DEFAULT_CHAT_TIMEOUT),
        ({CONF_CHAT_TIMEOUT: 600}, 600),
        ({CONF_CHAT_TIMEOUT: "300"}, 300),
        ({CONF_CHAT_TIMEOUT: 1}, MIN_CHAT_TIMEOUT),
        ({CONF_CHAT_TIMEOUT: 99_999}, MAX_CHAT_TIMEOUT),
        ({CONF_CHAT_TIMEOUT: "abc"}, DEFAULT_CHAT_TIMEOUT),
        ({CONF_CHAT_TIMEOUT: None}, DEFAULT_CHAT_TIMEOUT),
    ],
)
def test_get_chat_timeout(config, expected) -> None:
    assert get_chat_timeout(config) == expected


def test_default_is_180_seconds() -> None:
    """Default 180s, range 30–1800s."""
    assert DEFAULT_CHAT_TIMEOUT == 180
    assert (MIN_CHAT_TIMEOUT, MAX_CHAT_TIMEOUT) == (30, 1800)


# ── Options flow ──────────────────────────────────────────────────────────────

async def test_options_flow_offers_and_saves_chat_timeout(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    model_section = result["data_schema"].schema
    section_key = next(k for k in model_section if str(k) == "model_config")
    model_keys = [str(k) for k in model_section[section_key].schema.schema]
    assert CONF_CHAT_TIMEOUT in model_keys

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.test_model",
                "max_tokens": 20_000,
                CONF_CHAT_TIMEOUT: 600,
            },
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CHAT_TIMEOUT] == 600


async def test_options_flow_keeps_stored_chat_timeout_when_omitted(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
        options={CONF_CHAT_TIMEOUT: 900},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"model_config": {}, "agents": {}, "area_assignment": {}, "developer": {}},
    )
    assert result["data"][CONF_CHAT_TIMEOUT] == 900


# ── /api/kyber/chat_settings ──────────────────────────────────────────────────

async def test_chat_settings_endpoint_returns_configured_value(hass: HomeAssistant, hass_client) -> None:
    await _setup(hass, {CONF_CHAT_TIMEOUT: 720})
    client = await hass_client()
    resp = await client.get("/api/kyber/chat_settings")
    assert resp.status == 200
    assert (await resp.json()) == {"chat_timeout": 720}


async def test_chat_settings_endpoint_returns_default(hass: HomeAssistant, hass_client) -> None:
    await _setup(hass)
    client = await hass_client()
    resp = await client.get("/api/kyber/chat_settings")
    assert (await resp.json()) == {"chat_timeout": DEFAULT_CHAT_TIMEOUT}


# ── Backend limits follow the chat timeout ────────────────────────────────────

async def _complete_and_capture(hass: HomeAssistant, hass_client) -> tuple[list[float], dict]:
    """POST /complete with a mocked OpenAI call; return wait_for timeouts and call kwargs."""
    real_wait_for = asyncio.wait_for
    timeouts: list[float] = []

    async def _recording_wait_for(aw, timeout):
        timeouts.append(timeout)
        return await real_wait_for(aw, timeout)

    client = await hass_client()
    with (
        patch(_PATCH_OPENAI, new_callable=AsyncMock, return_value=_make_ai_result("ok")) as mock_call,
        patch("custom_components.kyber.http_api.asyncio.wait_for", side_effect=_recording_wait_for),
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})
    assert resp.status == 200
    mock_call.assert_called_once()
    return timeouts, mock_call.call_args.kwargs


@pytest.mark.parametrize(
    ("chat_timeout", "expected_round", "expected_http"),
    [
        (None, MIN_AI_CALL_TIMEOUT, DEFAULT_CHAT_TIMEOUT),  # default 180 → 180 / 180
        (60, MIN_AI_CALL_TIMEOUT, MIN_CLOUD_HTTP_TIMEOUT),  # short → floors 180 / 120
        (900, 900, 900),                                     # long → both grow
    ],
)
async def test_backend_limits_follow_chat_timeout(
    hass: HomeAssistant, hass_client, chat_timeout, expected_round, expected_http,
) -> None:
    extra = {} if chat_timeout is None else {CONF_CHAT_TIMEOUT: chat_timeout}
    await _setup(hass, extra)
    timeouts, kwargs = await _complete_and_capture(hass, hass_client)
    assert expected_round in timeouts
    assert kwargs["http_timeout"] == expected_http
