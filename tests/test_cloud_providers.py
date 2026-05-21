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


@pytest.mark.asyncio
async def test_openai_history_included_in_messages() -> None:
    """History messages should be included before the current turn."""
    captured_payload: list[dict] = []

    import aiohttp as _aiohttp_stub

    resp = _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})
    session_mock = AsyncMock()

    def _post(url, json=None, **kw):
        captured_payload.append(json)
        return resp

    session_mock.post = MagicMock(side_effect=_post)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        await async_openai_ai_call(
            task_name="test",
            api_key="sk-test",
            model="gpt-4o",
            instructions="Follow up",
            history=[
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
            ],
        )

    messages = captured_payload[0]["messages"]
    assert messages[0] == {"role": "user", "content": "First question"}
    assert messages[1] == {"role": "assistant", "content": "First answer"}
    assert messages[2] == {"role": "user", "content": "Follow up"}


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
async def test_anthropic_system_messages_extracted() -> None:
    """System messages in history should be extracted to the top-level system field."""
    captured: list[dict] = []

    import aiohttp as _aiohttp_stub
    resp = _mock_response(200, {"content": [{"type": "text", "text": "ok"}]})
    session_mock = AsyncMock()

    def _post(url, json=None, **kw):
        captured.append(json)
        return resp

    session_mock.post = MagicMock(side_effect=_post)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        await async_anthropic_ai_call(
            task_name="test",
            api_key="sk-ant-test",
            model="claude-sonnet-4-5",
            instructions="What's the weather?",
            history=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
        )

    payload = captured[0]
    assert payload["system"] == "You are a helpful assistant."
    # System message should not appear in messages list
    roles = [m["role"] for m in payload["messages"]]
    assert "system" not in roles


@pytest.mark.asyncio
async def test_anthropic_consecutive_user_messages_merged() -> None:
    """Consecutive user messages must be merged to satisfy Anthropic's alternation rule."""
    captured: list[dict] = []

    import aiohttp as _aiohttp_stub
    resp = _mock_response(200, {"content": [{"type": "text", "text": "ok"}]})
    session_mock = AsyncMock()
    session_mock.post = MagicMock(side_effect=lambda url, json=None, **kw: (captured.append(json), resp)[-1])
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        await async_anthropic_ai_call(
            task_name="test",
            api_key="sk-ant-test",
            model="claude-sonnet-4-5",
            instructions="Question 3",
            history=[
                {"role": "user", "content": "Question 1"},
                {"role": "user", "content": "Question 2"},  # consecutive — should merge
            ],
        )

    messages = captured[0]["messages"]
    # Questions 1, 2, and 3 should all be in a single user message
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "Question 1" in messages[0]["content"]
    assert "Question 2" in messages[0]["content"]
    assert "Question 3" in messages[0]["content"]


@pytest.mark.asyncio
async def test_anthropic_current_turn_appended_to_last_user_message() -> None:
    """If the last history message is from the user, the instruction appends to it."""
    captured: list[dict] = []

    import aiohttp as _aiohttp_stub
    resp = _mock_response(200, {"content": [{"type": "text", "text": "ok"}]})
    session_mock = AsyncMock()
    session_mock.post = MagicMock(side_effect=lambda url, json=None, **kw: (captured.append(json), resp)[-1])
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_aiohttp_stub, "ClientSession", return_value=session_mock):
        await async_anthropic_ai_call(
            task_name="test",
            api_key="sk-ant-test",
            model="claude-sonnet-4-5",
            instructions="New question",
            history=[
                {"role": "user", "content": "Existing question"},
            ],
        )

    messages = captured[0]["messages"]
    assert len(messages) == 1
    assert "Existing question" in messages[0]["content"]
    assert "New question" in messages[0]["content"]


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
