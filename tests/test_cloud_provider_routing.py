"""Integration tests for cloud provider routing in the AI loop.

Covers _run_ai_loop routing logic in http_api.py:
  - provider=openai  → async_openai_ai_call
  - provider=anthropic → async_anthropic_ai_call
  - provider=azure   → async_azure_ai_call
  - provider=none    → HA ai_task fallback
  - cloud_use_for_chat=False → always falls back to HA ai_task
  - Backward compat: no cloud_provider key but Azure creds present → Azure
  - CLOUD_PROVIDER_ANTHROPIC import (regression for NameError fix)
"""
import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="requires pytest-homeassistant-custom-component",
)

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kyber.const import (
    CLOUD_PROVIDER_ANTHROPIC,
    CLOUD_PROVIDER_AZURE,
    CLOUD_PROVIDER_NONE,
    CLOUD_PROVIDER_OPENAI,
    CONF_ANTHROPIC_API_KEY,
    CONF_ANTHROPIC_MODEL,
    CONF_AZURE_API_KEY,
    CONF_AZURE_DEPLOYMENT,
    CONF_AZURE_ENDPOINT,
    CONF_CLOUD_PROVIDER,
    CONF_CLOUD_USE_FOR_CHAT,
    CONF_OPENAI_API_KEY,
    CONF_OPENAI_MODEL,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    DOMAIN,
)
# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_ai_result(text: str) -> MagicMock:
    r = MagicMock()
    r.data = text
    return r


_PATCH_GENERATE = "custom_components.kyber.api_utilities.async_generate_data"
_PATCH_OPENAI = "custom_components.kyber.http_api.async_openai_ai_call"
_PATCH_ANTHROPIC = "custom_components.kyber.http_api.async_anthropic_ai_call"
_PATCH_AZURE = "custom_components.kyber.http_api.async_azure_ai_call"


@pytest.fixture(autouse=True)
def mock_background_tasks():
    """Prevent background tasks from running during cloud routing tests."""
    with (
        patch("custom_components.kyber._async_run_initial_learning"),
        patch("custom_components.kyber._async_explore_integrations"),
        patch("custom_components.kyber._async_seed_language_hints"),
    ):
        yield


async def _setup_with_cloud(
    hass: HomeAssistant,
    cloud_options: dict,
) -> MockConfigEntry:
    """Create and set up an integration with cloud provider options."""
    from custom_components.kyber import async_setup_entry as _setup  # late import: real module restored by pytest_runtest_setup

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "max_tokens": 2048,
            **cloud_options,
        },
        title="Kyber",
    )
    await async_setup_component(hass, "http", {})
    with patch("custom_components.kyber._async_explore_integrations", new_callable=AsyncMock):
        await _setup(hass, entry)
        await asyncio.sleep(0)
    return entry


# ══════════════════════════════════════════════════════════════════════════════
# Import regression test
# ══════════════════════════════════════════════════════════════════════════════

def test_cloud_provider_anthropic_is_importable() -> None:
    """CLOUD_PROVIDER_ANTHROPIC must be importable from http_api (regression for NameError)."""
    import importlib
    import custom_components.kyber.http_api as http_api_mod
    importlib.reload(http_api_mod)  # reload to flush any cached import state
    # If the import is broken, the reload itself will raise NameError or ImportError
    assert hasattr(http_api_mod, "_run_ai_loop")


def test_cloud_provider_constants_have_expected_values() -> None:
    """Cloud provider constant values should match what the UI and config store."""
    assert CLOUD_PROVIDER_NONE == "none"
    assert CLOUD_PROVIDER_AZURE == "azure"
    assert CLOUD_PROVIDER_OPENAI == "openai"
    assert CLOUD_PROVIDER_ANTHROPIC == "anthropic"


# ══════════════════════════════════════════════════════════════════════════════
# Provider routing via HTTP API
# ══════════════════════════════════════════════════════════════════════════════

async def test_openai_provider_routes_to_openai_call(
    hass: HomeAssistant, hass_client,
) -> None:
    """When cloud_provider=openai and use_for_chat=True, async_openai_ai_call is used."""
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_OPENAI,
        CONF_CLOUD_USE_FOR_CHAT: True,
        CONF_OPENAI_API_KEY: "sk-test-openai",
        CONF_OPENAI_MODEL: "gpt-4o",
    })

    client = await hass_client()
    with patch(_PATCH_OPENAI, new_callable=AsyncMock, return_value=_make_ai_result("OpenAI reply")) as mock_call:
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    mock_call.assert_called_once()
    kwargs = mock_call.call_args.kwargs
    assert kwargs["api_key"] == "sk-test-openai"
    assert kwargs["model"] == "gpt-4o"


async def test_anthropic_provider_routes_to_anthropic_call(
    hass: HomeAssistant, hass_client,
) -> None:
    """When cloud_provider=anthropic and use_for_chat=True, async_anthropic_ai_call is used."""
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_ANTHROPIC,
        CONF_CLOUD_USE_FOR_CHAT: True,
        CONF_ANTHROPIC_API_KEY: "sk-ant-test",
        CONF_ANTHROPIC_MODEL: DEFAULT_ANTHROPIC_MODEL,
    })

    client = await hass_client()
    with patch(_PATCH_ANTHROPIC, new_callable=AsyncMock, return_value=_make_ai_result("Claude reply")) as mock_call:
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    mock_call.assert_called_once()
    kwargs = mock_call.call_args.kwargs
    assert kwargs["api_key"] == "sk-ant-test"
    assert kwargs["model"] == DEFAULT_ANTHROPIC_MODEL


async def test_azure_provider_routes_to_azure_call(
    hass: HomeAssistant, hass_client,
) -> None:
    """When cloud_provider=azure and use_for_chat=True, async_azure_ai_call is used."""
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_AZURE,
        CONF_CLOUD_USE_FOR_CHAT: True,
        CONF_AZURE_ENDPOINT: "https://my-resource.openai.azure.com",
        CONF_AZURE_API_KEY: "azure-key",
        CONF_AZURE_DEPLOYMENT: "gpt-4o-deployment",
    })

    client = await hass_client()
    with patch(_PATCH_AZURE, new_callable=AsyncMock, return_value=_make_ai_result("Azure reply")) as mock_call:
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    mock_call.assert_called_once()
    kwargs = mock_call.call_args.kwargs
    assert "azure-key" in (kwargs.get("api_key") or "")


async def test_none_provider_falls_back_to_ha_ai_task(
    hass: HomeAssistant, hass_client,
) -> None:
    """When cloud_provider=none, the HA ai_task entity is used (no cloud call)."""
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_NONE,
        CONF_CLOUD_USE_FOR_CHAT: True,
    })

    client = await hass_client()
    with (
        patch(_PATCH_OPENAI, new_callable=AsyncMock) as openai_mock,
        patch(_PATCH_ANTHROPIC, new_callable=AsyncMock) as anthropic_mock,
        patch(_PATCH_AZURE, new_callable=AsyncMock) as azure_mock,
        patch(_PATCH_GENERATE, new_callable=AsyncMock,
              return_value=_make_ai_result("HA reply")) as ha_mock,
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    openai_mock.assert_not_called()
    anthropic_mock.assert_not_called()
    azure_mock.assert_not_called()
    ha_mock.assert_called_once()


async def test_use_for_chat_false_skips_cloud_provider(
    hass: HomeAssistant, hass_client,
) -> None:
    """When cloud_use_for_chat=False, the HA ai_task entity is used even if a cloud provider is configured."""
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_OPENAI,
        CONF_CLOUD_USE_FOR_CHAT: False,
        CONF_OPENAI_API_KEY: "sk-test-openai",
        CONF_OPENAI_MODEL: "gpt-4o",
    })

    client = await hass_client()
    with (
        patch(_PATCH_OPENAI, new_callable=AsyncMock) as openai_mock,
        patch(_PATCH_GENERATE, new_callable=AsyncMock,
              return_value=_make_ai_result("HA reply")),
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    openai_mock.assert_not_called()


async def test_backward_compat_azure_credentials_without_provider_key(
    hass: HomeAssistant, hass_client,
) -> None:
    """If no cloud_provider key but Azure creds present, backward compat activates Azure."""
    # Old-style config: no cloud_provider, but Azure credentials are there
    await _setup_with_cloud(hass, {
        CONF_AZURE_ENDPOINT: "https://my-resource.openai.azure.com",
        CONF_AZURE_API_KEY: "azure-key-compat",
        CONF_AZURE_DEPLOYMENT: "gpt-4o-compat",
    })

    client = await hass_client()
    with patch(_PATCH_AZURE, new_callable=AsyncMock, return_value=_make_ai_result("Azure compat")) as mock_call:
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    mock_call.assert_called_once()


async def test_openai_provider_missing_api_key_falls_back_to_ha(
    hass: HomeAssistant, hass_client,
) -> None:
    """OpenAI selected but no api_key → falls back to HA ai_task (not crash)."""
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_OPENAI,
        CONF_CLOUD_USE_FOR_CHAT: True,
        CONF_OPENAI_API_KEY: "",       # intentionally empty
        CONF_OPENAI_MODEL: "gpt-4o",
    })

    client = await hass_client()
    with (
        patch(_PATCH_OPENAI, new_callable=AsyncMock) as openai_mock,
        patch(_PATCH_GENERATE, new_callable=AsyncMock,
              return_value=_make_ai_result("HA fallback")),
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    openai_mock.assert_not_called()


async def test_anthropic_provider_missing_api_key_falls_back_to_ha(
    hass: HomeAssistant, hass_client,
) -> None:
    """Anthropic selected but no api_key → falls back to HA ai_task (not crash)."""
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_ANTHROPIC,
        CONF_CLOUD_USE_FOR_CHAT: True,
        CONF_ANTHROPIC_API_KEY: "",    # intentionally empty
        CONF_ANTHROPIC_MODEL: DEFAULT_ANTHROPIC_MODEL,
    })

    client = await hass_client()
    with (
        patch(_PATCH_ANTHROPIC, new_callable=AsyncMock) as anthropic_mock,
        patch(_PATCH_GENERATE, new_callable=AsyncMock,
              return_value=_make_ai_result("HA fallback")),
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello"})

    assert resp.status == 200
    anthropic_mock.assert_not_called()


async def test_synthesis_pass_does_not_call_local_ha_when_openai_configured(
    hass: HomeAssistant, hass_client,
) -> None:
    """Synthesis pass must use the configured cloud provider, not local HA ai_task.

    This is a regression test for the bug where _run_ai_loop's synthesis fallback
    always called async_ai_call() (local HA ai_task) regardless of cloud config.
    We verify indirectly: when OpenAI is configured and all AI responses succeed,
    the local HA async_generate_data is never called.
    """
    await _setup_with_cloud(hass, {
        CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_OPENAI,
        CONF_CLOUD_USE_FOR_CHAT: True,
        CONF_OPENAI_API_KEY: "sk-test",
        CONF_OPENAI_MODEL: "gpt-4o",
    })

    client = await hass_client()
    with (
        patch(_PATCH_OPENAI, new_callable=AsyncMock,
              return_value=_make_ai_result("OpenAI direct answer")) as openai_mock,
        patch(_PATCH_GENERATE, new_callable=AsyncMock) as ha_mock,
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "What is the status?"})

    assert resp.status == 200
    # OpenAI was called, local HA was NOT called
    openai_mock.assert_called()
    ha_mock.assert_not_called()
