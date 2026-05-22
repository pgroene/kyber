"""Unit tests for the Kyber correction micro-agent.

Covers:
  - _build_correction_prompt includes domain docs and error details
  - async_try_correct_failures returns None when no correctable failures
  - async_try_correct_failures returns None when AI returns empty response
  - async_try_correct_failures returns None when AI returns no plan block
  - async_try_correct_failures returns corrected actions on success
  - async_try_correct_failures handles AI timeout gracefully
  - async_try_correct_failures handles unconfigured provider gracefully
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── HA + dependency stubs ────────────────────────────────────────────────────
_STUBS = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.helpers",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.label_registry",
    "homeassistant.helpers.template",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.config",
    "homeassistant.loader",
    "aiohttp",
    "aiohttp.web",
]
for _m in _STUBS:
    sys.modules.setdefault(_m, types.ModuleType(_m))
sys.modules["aiohttp"].web = types.ModuleType("aiohttp.web")


class _Stub:
    pass


sys.modules["homeassistant.components.http"].HomeAssistantView = _Stub
sys.modules["homeassistant.core"].HomeAssistant = _Stub
sys.modules["homeassistant.core"].callback = lambda f: f
sys.modules["homeassistant.helpers.storage"].Store = _Stub
sys.modules["homeassistant.exceptions"].HomeAssistantError = type(
    "HomeAssistantError", (Exception,), {}
)
for _r in (
    "entity_registry",
    "area_registry",
    "device_registry",
    "label_registry",
):
    sys.modules[f"homeassistant.helpers.{_r}"].async_get = lambda *a, **k: None
sys.modules.setdefault(
    "homeassistant.components.ai_task",
    types.ModuleType("homeassistant.components.ai_task"),
)

# ── Add repo root to sys.path ────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

# ── Import the modules under test ────────────────────────────────────────────
from custom_components.kyber.correction_agent import (  # noqa: E402
    _build_correction_prompt,
    _make_ai_call,
    async_try_correct_failures,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_hass(config: dict | None = None) -> MagicMock:
    """Return a mock HomeAssistant instance with one Kyber config entry."""
    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.data = config or {}
    hass.config_entries.async_entries.return_value = [entry]
    return hass


def _failed_result(entity_id: str, message: str) -> dict:
    return {"status": "error", "entity_id": entity_id, "message": message}


def _ok_result(entity_id: str) -> dict:
    return {"status": "ok", "entity_id": entity_id}


def _call_service_action(entity_id: str, service: str = "turn_on", **service_data) -> dict:
    domain = entity_id.split(".")[0]
    return {
        "type": "call_service",
        "domain": domain,
        "service": service,
        "entity_id": entity_id,
        "service_data": service_data,
        "description": f"{domain}.{service} on {entity_id}",
    }


_VALID_PLAN_RESPONSE = """
Here is the corrected plan:

```plan
{
  "summary": "Set lights to white using rgb_color",
  "actions": [
    {
      "type": "call_service",
      "domain": "light",
      "service": "turn_on",
      "entity_id": "light.test",
      "service_data": {"rgb_color": [255, 255, 255]},
      "description": "Turn on light with white rgb color"
    }
  ]
}
```
"""


# ──────────────────────────────────────────────────────────────────────────────
# _build_correction_prompt
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildCorrectionPrompt:
    def test_includes_plan_summary(self):
        prompt = _build_correction_prompt(
            [_call_service_action("light.test", color_temp=200)],
            [_call_service_action("light.test", color_temp=200)],
            "Set living room lights to white",
            ["extra keys not allowed @ data['color_temp']"],
        )
        assert "Set living room lights to white" in prompt

    def test_includes_error_message(self):
        prompt = _build_correction_prompt(
            [_call_service_action("light.test")],
            [_call_service_action("light.test")],
            "Turn on light",
            ["Service call failed: xyz"],
        )
        assert "Service call failed: xyz" in prompt

    def test_includes_domain_docs_for_light(self):
        prompt = _build_correction_prompt(
            [_call_service_action("light.test")],
            [_call_service_action("light.test")],
            "Turn on light",
            ["error"],
        )
        # domain_docs.py should have light docs
        assert "light" in prompt.lower()

    def test_includes_domain_docs_for_unknown_domain(self):
        action = {
            "type": "call_service",
            "domain": "unknown_domain_xyz",
            "service": "turn_on",
            "entity_id": "unknown_domain_xyz.test",
            "service_data": {},
        }
        prompt = _build_correction_prompt([action], [action], "test", ["error"])
        assert "unknown_domain_xyz" in prompt

    def test_includes_all_original_actions(self):
        actions = [
            _call_service_action("light.a"),
            _call_service_action("light.b"),
        ]
        prompt = _build_correction_prompt(actions, actions, "Test", ["error"])
        assert "light.a" in prompt
        assert "light.b" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# async_try_correct_failures
# ──────────────────────────────────────────────────────────────────────────────

class TestAsyncTryCorrectFailures:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_failures(self):
        hass = _make_hass()
        results = [_ok_result("light.test")]
        actions = [_call_service_action("light.test")]
        result = await async_try_correct_failures(hass, results, actions, "Turn on light")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_call_service_failures(self):
        hass = _make_hass()
        # Registry action failure — not correctable
        results = [{"status": "error", "entity_id": "light.test", "message": "Entity not found"}]
        actions = [{"type": "assign_area", "entity_id": "light.test", "area_id": "living_room"}]
        result = await async_try_correct_failures(hass, results, actions, "Assign area")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_provider_not_configured(self):
        hass = _make_hass(config={})  # no AI config
        results = [_failed_result("light.test", "error")]
        actions = [_call_service_action("light.test")]
        result = await async_try_correct_failures(hass, results, actions, "Turn on light")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_ai_timeout(self):
        hass = _make_hass(config={
            "cloud_provider": "azure",
            "cloud_use_for_chat": True,
            "azure_endpoint": "https://test.openai.azure.com",
            "azure_api_key": "test-key",
            "azure_deployment": "gpt-4",
        })
        results = [_failed_result("light.test", "extra keys not allowed @ data['color_temp']")]
        actions = [_call_service_action("light.test", color_temp=200)]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError,
        ):
            result = await async_try_correct_failures(hass, results, actions, "Set lights to white")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_ai_response(self):
        hass = _make_hass(config={
            "cloud_provider": "azure",
            "cloud_use_for_chat": True,
            "azure_endpoint": "https://test.openai.azure.com",
            "azure_api_key": "test-key",
            "azure_deployment": "gpt-4",
        })
        results = [_failed_result("light.test", "extra keys not allowed @ data['color_temp']")]
        actions = [_call_service_action("light.test", color_temp=200)]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await async_try_correct_failures(hass, results, actions, "Set lights to white")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_plan_block_in_response(self):
        hass = _make_hass(config={
            "cloud_provider": "azure",
            "cloud_use_for_chat": True,
            "azure_endpoint": "https://test.openai.azure.com",
            "azure_api_key": "test-key",
            "azure_deployment": "gpt-4",
        })
        results = [_failed_result("light.test", "error")]
        actions = [_call_service_action("light.test")]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            return_value="Sorry, I cannot help with that.",
        ):
            result = await async_try_correct_failures(hass, results, actions, "Turn on light")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_corrected_actions_on_success(self):
        hass = _make_hass(config={
            "cloud_provider": "azure",
            "cloud_use_for_chat": True,
            "azure_endpoint": "https://test.openai.azure.com",
            "azure_api_key": "test-key",
            "azure_deployment": "gpt-4",
        })
        results = [_failed_result("light.test", "extra keys not allowed @ data['color_temp']")]
        actions = [_call_service_action("light.test", color_temp=200)]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            return_value=_VALID_PLAN_RESPONSE,
        ):
            result = await async_try_correct_failures(hass, results, actions, "Set lights to white")

        assert result is not None
        assert "corrected_actions" in result
        assert len(result["corrected_actions"]) == 1
        assert result["corrected_actions"][0]["service_data"]["rgb_color"] == [255, 255, 255]
        assert "message" in result
        assert "learned_fact" in result
        assert "🧠" in result["learned_fact"]

    @pytest.mark.asyncio
    async def test_learned_fact_mentions_bad_key(self):
        hass = _make_hass(config={
            "cloud_provider": "azure",
            "cloud_use_for_chat": True,
            "azure_endpoint": "https://test.openai.azure.com",
            "azure_api_key": "test-key",
            "azure_deployment": "gpt-4",
        })
        results = [_failed_result("light.test", "extra keys not allowed @ data['color_temp']")]
        actions = [_call_service_action("light.test", color_temp=200)]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            return_value=_VALID_PLAN_RESPONSE,
        ):
            result = await async_try_correct_failures(hass, results, actions, "Set lights to white")

        assert result is not None
        assert "color_temp" in result["learned_fact"]

    @pytest.mark.asyncio
    async def test_uses_openai_when_configured(self):
        hass = _make_hass(config={
            "cloud_provider": "openai",
            "cloud_use_for_chat": True,
            "openai_api_key": "sk-test",
            "openai_model": "gpt-4o",
        })
        results = [_failed_result("light.test", "error")]
        actions = [_call_service_action("light.test")]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            return_value=_VALID_PLAN_RESPONSE,
        ) as mock_call:
            result = await async_try_correct_failures(hass, results, actions, "Turn on light")

        mock_call.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_uses_anthropic_when_configured(self):
        hass = _make_hass(config={
            "cloud_provider": "anthropic",
            "cloud_use_for_chat": True,
            "anthropic_api_key": "sk-ant-test",
            "anthropic_model": "claude-sonnet-4-5",
        })
        results = [_failed_result("light.test", "error")]
        actions = [_call_service_action("light.test")]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            return_value=_VALID_PLAN_RESPONSE,
        ) as mock_call:
            result = await async_try_correct_failures(hass, results, actions, "Turn on light")

        mock_call.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_handles_ai_exception_gracefully(self):
        hass = _make_hass(config={
            "cloud_provider": "azure",
            "cloud_use_for_chat": True,
            "azure_endpoint": "https://test.openai.azure.com",
            "azure_api_key": "test-key",
            "azure_deployment": "gpt-4",
        })
        results = [_failed_result("light.test", "error")]
        actions = [_call_service_action("light.test")]

        with patch(
            "custom_components.kyber.correction_agent._make_ai_call",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection refused"),
        ):
            result = await async_try_correct_failures(hass, results, actions, "Turn on light")

        assert result is None
