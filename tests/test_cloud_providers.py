"""Unit tests for cloud provider API calls.

Covers async_openai_ai_call and async_anthropic_ai_call in api_utilities.py.
Uses stub modules so no HA fixtures are required.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Minimal stubs so api_utilities can be imported stand-alone ────────────────
for _m in [
    "homeassistant", "homeassistant.core", "homeassistant.exceptions",
    "homeassistant.helpers", "homeassistant.helpers.storage",
    "homeassistant.helpers.entity_registry", "homeassistant.helpers.area_registry",
    "homeassistant.helpers.device_registry", "homeassistant.helpers.label_registry",
    "homeassistant.components", "homeassistant.components.http",
    "homeassistant.const", "aiohttp", "aiohttp.web",
]:
    sys.modules.setdefault(_m, types.ModuleType(_m))

sys.modules["homeassistant.exceptions"].HomeAssistantError = type(
    "HomeAssistantError", (Exception,), {}
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_pkg_cc = types.ModuleType("custom_components")
_pkg_cc.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _pkg_cc)

import importlib.util  # noqa: E402

_pkg_kyber = types.ModuleType("custom_components.kyber")
_pkg_kyber.__path__ = [str(ROOT / "custom_components" / "kyber")]
sys.modules["custom_components.kyber"] = _pkg_kyber


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_kyber_root = ROOT / "custom_components" / "kyber"
_load("custom_components.kyber.const", _kyber_root / "const.py")
api_utilities = _load("custom_components.kyber.api_utilities", _kyber_root / "api_utilities.py")

# Re-export the real HomeAssistantError via the api_utilities module reference
HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError

async_openai_ai_call = api_utilities.async_openai_ai_call
async_anthropic_ai_call = api_utilities.async_anthropic_ai_call
async_azure_ai_call = api_utilities.async_azure_ai_call


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(status: int, json_data: dict | None = None, text_data: str = "") -> AsyncMock:
    """Build an async context-manager mock that looks like an aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text_data)
    resp.headers = {}
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


def _mock_session(response: AsyncMock) -> AsyncMock:
    """Build an async context-manager mock that looks like an aiohttp ClientSession."""
    session = AsyncMock()
    session.post = MagicMock(return_value=response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


def _patch_session(response: AsyncMock):
    """Patch aiohttp.ClientSession used inside api_utilities."""
    import aiohttp as _aiohttp_stub
    session = _mock_session(response)
    return patch.object(_aiohttp_stub, "ClientSession", return_value=session)


# ══════════════════════════════════════════════════════════════════════════════
# async_openai_ai_call
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_openai_happy_path_returns_text() -> None:
    """Happy path: returns the text from choices[0].message.content."""
    resp = _mock_response(200, {"choices": [{"message": {"content": "Hello from GPT"}}]})
    with _patch_session(resp):
        result = await async_openai_ai_call(
            task_name="test",
            api_key="sk-test",
            model="gpt-4o",
            instructions="Say hello",
        )
    assert result.data == "Hello from GPT"


@pytest.mark.asyncio
async def test_openai_custom_base_url_used() -> None:
    """A custom base_url should be used instead of api.openai.com."""
    resp = _mock_response(200, {"choices": [{"message": {"content": "Groq reply"}}]})

    captured_url: list[str] = []

    import aiohttp as _aiohttp_stub
    session_mock = AsyncMock()

    def _post(url, **kw):
        captured_url.append(url)
        return resp

    session_mock.post = MagicMock(side_effect=_post)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        result = await async_openai_ai_call(
            task_name="test",
            api_key="sk-groq",
            model="llama3-70b",
            instructions="Hi",
            base_url="https://api.groq.com/openai",
        )

    assert result.data == "Groq reply"
    assert captured_url[0] == "https://api.groq.com/openai/v1/chat/completions"


def _capture_payloads(response_json: dict):
    """Patch ClientSession so every POSTed JSON payload lands in the returned list."""
    import aiohttp as _aiohttp_stub
    captured: list[dict] = []
    resp = _mock_response(200, response_json)
    session_mock = AsyncMock()
    session_mock.post = MagicMock(side_effect=lambda url, json=None, **kw: (captured.append(json), resp)[-1])
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)
    return captured, patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock)


_CONVERSATION = [
    {"role": "user", "content": "First question"},
    {"role": "assistant", "content": "First answer"},
    {"role": "user", "content": "Follow up"},
]


@pytest.mark.asyncio
async def test_openai_sends_system_then_the_conversation_once() -> None:
    """The core goes as system message, the history only as messages."""
    captured, patched = _capture_payloads({"choices": [{"message": {"content": "ok"}}]})
    with patched:
        await async_openai_ai_call(
            task_name="test", api_key="sk-test", model="gpt-4o",
            system="CORE RULES", messages=_CONVERSATION,
        )
    assert captured[0]["messages"] == [{"role": "system", "content": "CORE RULES"}, *_CONVERSATION]


@pytest.mark.asyncio
async def test_openai_without_messages_sends_instructions_as_the_user_message() -> None:
    captured, patched = _capture_payloads({"choices": [{"message": {"content": "ok"}}]})
    with patched:
        await async_openai_ai_call(task_name="test", api_key="sk-test", model="gpt-4o", instructions="Hi")
    assert captured[0]["messages"] == [{"role": "user", "content": "Hi"}]


@pytest.mark.asyncio
async def test_azure_sends_system_then_the_conversation_once() -> None:
    captured, patched = _capture_payloads({"choices": [{"message": {"content": "ok"}}]})
    with patched:
        await async_azure_ai_call(
            task_name="test", endpoint="https://x.openai.azure.com", api_key="k",
            deployment="d", api_version="v", system="CORE RULES", messages=_CONVERSATION,
        )
    assert captured[0]["messages"] == [{"role": "system", "content": "CORE RULES"}, *_CONVERSATION]


@pytest.mark.asyncio
async def test_openai_http_500_raises_error() -> None:
    """HTTP 500 response should raise HomeAssistantError with status info."""
    resp = _mock_response(500, text_data="Internal Server Error")
    with _patch_session(resp):
        with pytest.raises(HomeAssistantError, match="500"):
            await async_openai_ai_call(
                task_name="test", api_key="sk-test", model="gpt-4o", instructions="Hi"
            )


@pytest.mark.asyncio
async def test_openai_malformed_response_raises_error() -> None:
    """Response missing choices should raise HomeAssistantError."""
    resp = _mock_response(200, {"not_choices": []})
    with _patch_session(resp):
        with pytest.raises(HomeAssistantError, match="unexpected response format"):
            await async_openai_ai_call(
                task_name="test", api_key="sk-test", model="gpt-4o", instructions="Hi"
            )


@pytest.mark.asyncio
async def test_openai_429_exhausts_retries_raises_error() -> None:
    """Three consecutive 429 responses should raise a rate-limit HomeAssistantError."""
    resp = _mock_response(429)
    resp.headers = {"Retry-After": "1"}

    import aiohttp as _aiohttp_stub
    session_mock = AsyncMock()
    session_mock.post = MagicMock(return_value=resp)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock):  # skip real sleep
            with pytest.raises(HomeAssistantError, match="rate limit"):
                await async_openai_ai_call(
                    task_name="test", api_key="sk-test", model="gpt-4o", instructions="Hi"
                )


@pytest.mark.asyncio
async def test_openai_429_retries_then_succeeds() -> None:
    """A 429 on first attempt followed by 200 should return the text."""
    import aiohttp as _aiohttp_stub

    call_count = 0

    def _make_resp():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = _mock_response(429)
            r.headers = {"Retry-After": "1"}
            return r
        return _mock_response(200, {"choices": [{"message": {"content": "retry ok"}}]})

    session_mock = AsyncMock()
    session_mock.post = MagicMock(side_effect=lambda *a, **k: _make_resp())
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await async_openai_ai_call(
                task_name="test", api_key="sk-test", model="gpt-4o", instructions="Hi"
            )

    assert result.data == "retry ok"
    assert call_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# async_anthropic_ai_call
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_anthropic_happy_path_returns_text() -> None:
    """Happy path: returns the text from content[0].text."""
    resp = _mock_response(200, {"content": [{"type": "text", "text": "Hello from Claude"}]})
    with _patch_session(resp):
        result = await async_anthropic_ai_call(
            task_name="test",
            api_key="sk-ant-test",
            model="claude-sonnet-4-5",
            instructions="Say hello",
        )
    assert result.data == "Hello from Claude"


@pytest.mark.asyncio
async def test_anthropic_caches_the_system_part_and_sends_the_conversation() -> None:
    """The core is the cached system part; messages arrive as rendered."""
    captured, patched = _capture_payloads({"content": [{"type": "text", "text": "ok"}]})
    with patched:
        await async_anthropic_ai_call(
            task_name="test", api_key="sk-ant-test", model="claude-sonnet-4-5",
            system="CORE RULES", messages=_CONVERSATION,
        )
    payload = captured[0]
    assert payload["system"] == [{"type": "text", "text": "CORE RULES", "cache_control": {"type": "ephemeral"}}]
    assert payload["messages"] == _CONVERSATION


@pytest.mark.asyncio
async def test_anthropic_without_system_has_no_system_field() -> None:
    captured, patched = _capture_payloads({"content": [{"type": "text", "text": "ok"}]})
    with patched:
        await async_anthropic_ai_call(task_name="test", api_key="k", model="m", instructions="Hi")
    assert "system" not in captured[0]
    assert captured[0]["messages"] == [{"role": "user", "content": "Hi"}]


@pytest.mark.asyncio
async def test_anthropic_http_500_raises_error() -> None:
    """HTTP 500 should raise HomeAssistantError."""
    resp = _mock_response(500, text_data="Server Error")
    with _patch_session(resp):
        with pytest.raises(HomeAssistantError, match="500"):
            await async_anthropic_ai_call(
                task_name="test", api_key="sk-ant-test",
                model="claude-sonnet-4-5", instructions="Hi"
            )


@pytest.mark.asyncio
async def test_anthropic_malformed_response_raises_error() -> None:
    """Response missing content key should raise HomeAssistantError."""
    resp = _mock_response(200, {"not_content": []})
    with _patch_session(resp):
        with pytest.raises(HomeAssistantError, match="unexpected response format"):
            await async_anthropic_ai_call(
                task_name="test", api_key="sk-ant-test",
                model="claude-sonnet-4-5", instructions="Hi"
            )


@pytest.mark.asyncio
async def test_anthropic_429_exhausts_retries_raises_error() -> None:
    """Three consecutive 429 responses should raise a rate-limit HomeAssistantError."""
    resp = _mock_response(429)
    resp.headers = {"retry-after": "1"}

    import aiohttp as _aiohttp_stub
    session_mock = AsyncMock()
    session_mock.post = MagicMock(return_value=resp)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(HomeAssistantError, match="rate limit"):
                await async_anthropic_ai_call(
                    task_name="test", api_key="sk-ant-test",
                    model="claude-sonnet-4-5", instructions="Hi"
                )


@pytest.mark.asyncio
async def test_anthropic_uses_correct_endpoint_and_headers() -> None:
    """The Anthropic API endpoint and authentication headers must be correct."""
    captured_url: list[str] = []
    captured_headers: list[dict] = []

    import aiohttp as _aiohttp_stub
    resp = _mock_response(200, {"content": [{"type": "text", "text": "ok"}]})
    session_mock = AsyncMock()

    def _post(url, json=None, headers=None, **kw):
        captured_url.append(url)
        captured_headers.append(headers or {})
        return resp

    session_mock.post = MagicMock(side_effect=_post)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        await async_anthropic_ai_call(
            task_name="test",
            api_key="sk-ant-mykey",
            model="claude-sonnet-4-5",
            instructions="Hello",
        )

    assert captured_url[0] == "https://api.anthropic.com/v1/messages"
    assert captured_headers[0]["x-api-key"] == "sk-ant-mykey"
    assert captured_headers[0]["anthropic-version"] == "2023-06-01"


# ══════════════════════════════════════════════════════════════════════════════
# async_azure_ai_call
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_azure_happy_path_returns_text() -> None:
    """Happy path: returns the text from choices[0].message.content."""
    resp = _mock_response(200, {"choices": [{"message": {"content": "Hello from Azure"}}]})
    with _patch_session(resp):
        result = await async_azure_ai_call(
            task_name="test",
            endpoint="https://my-resource.openai.azure.com",
            api_key="azure-key",
            deployment="gpt-4o",
            api_version="2025-04-01-preview",
            instructions="Hi",
        )
    assert result.data == "Hello from Azure"


@pytest.mark.asyncio
async def test_azure_url_uses_deployment_and_api_version() -> None:
    """The request URL must target /openai/deployments/{deployment}/chat/completions."""
    captured_url: list[str] = []

    import aiohttp as _aiohttp_stub
    resp = _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})
    session_mock = AsyncMock()

    def _post(url, **kw):
        captured_url.append(url)
        return resp

    session_mock.post = MagicMock(side_effect=_post)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        await async_azure_ai_call(
            task_name="test",
            endpoint="https://my-resource.openai.azure.com",
            api_key="azure-key",
            deployment="gpt-5.4-nano",
            api_version="2025-04-01-preview",
            instructions="Hi",
        )

    assert captured_url[0] == (
        "https://my-resource.openai.azure.com/openai/deployments/gpt-5.4-nano"
        "/chat/completions?api-version=2025-04-01-preview"
    )


@pytest.mark.asyncio
async def test_azure_strips_foundry_project_path_from_endpoint() -> None:
    """Regression: an Azure AI Foundry *project* endpoint (with a /api/projects/...
    path, as copied from the Foundry portal) must not be used verbatim — Azure
    OpenAI chat completions only exist at the resource root. Using the project
    path breaks routing and Azure returns a misleading HTTP 400
    "API version not supported" instead of the real problem.
    """
    captured_url: list[str] = []

    import aiohttp as _aiohttp_stub
    resp = _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})
    session_mock = AsyncMock()

    def _post(url, **kw):
        captured_url.append(url)
        return resp

    session_mock.post = MagicMock(side_effect=_post)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        await async_azure_ai_call(
            task_name="test",
            endpoint="https://my-resource.services.ai.azure.com/api/projects/proj-default",
            api_key="azure-key",
            deployment="gpt-5.4-nano",
            api_version="2025-04-01-preview",
            instructions="Hi",
        )

    assert captured_url[0] == (
        "https://my-resource.services.ai.azure.com/openai/deployments/gpt-5.4-nano"
        "/chat/completions?api-version=2025-04-01-preview"
    )


@pytest.mark.asyncio
async def test_azure_non_200_raises_with_body_in_message() -> None:
    """A non-200 response should raise HomeAssistantError including the response body."""
    resp = _mock_response(400, text_data='{"error":{"code":"BadRequest","message":"API version not supported"}}')
    with _patch_session(resp):
        with pytest.raises(HomeAssistantError, match="API version not supported"):
            await async_azure_ai_call(
                task_name="test",
                endpoint="https://my-resource.openai.azure.com",
                api_key="azure-key",
                deployment="gpt-4o",
                api_version="2025-04-01-preview",
                instructions="Hi",
            )


@pytest.mark.asyncio
async def test_azure_429_exhausts_retries_raises_error() -> None:
    """Three consecutive 429 responses should raise a rate-limit HomeAssistantError."""
    resp = _mock_response(429)
    resp.headers = {"Retry-After": "1"}

    import aiohttp as _aiohttp_stub
    session_mock = AsyncMock()
    session_mock.post = MagicMock(return_value=resp)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(HomeAssistantError, match="rate limit"):
                await async_azure_ai_call(
                    task_name="test",
                    endpoint="https://my-resource.openai.azure.com",
                    api_key="azure-key",
                    deployment="gpt-4o",
                    api_version="2025-04-01-preview",
                    instructions="Hi",
                )
