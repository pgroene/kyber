"""Kyber compares "Let the model think" with what the chat model really did.

The option only stops Kyber from appending /no_think; thinking itself is
switched on in the service behind the AI task. On 2026-10-22 the option was on
while the model did not think, and nobody noticed. Kyber now looks at every
chat call for traces of thinking (no extra model call) and warns once when the
setting and the behaviour disagree:

- AI task path: the result never holds the thinking text, but Home Assistant
  keeps the call's chat log with ``thinking_content``. Turns through Kyber's
  endpoint get that chat log handed in; one test checks the contract against
  Home Assistant's own code with a real AI task entity that streams into the
  chat log the way Local OpenAI LLM and Ollama do (requirements-test.txt
  installs hassil and the other packages those components need).
- Kyber's own OpenAI-compatible call: a stand-in LLM on localhost sends
  ``reasoning_content`` as the counter-check.
"""
from __future__ import annotations

import itertools
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

ROOT = Path(__file__).resolve().parents[1]
I18N = (ROOT / "custom_components" / "kyber" / "www" / "src" / "i18n.js").read_text(encoding="utf-8")
ENTITY = "ai_task.chat_model"


@pytest.fixture
def tc():
    from custom_components.kyber import thinking_check

    return thinking_check


# ── signals in a raw response ────────────────────────────────────────────────

@pytest.mark.parametrize(("payload", "state", "source"), [
    ({"choices": [{"message": {"content": "a", "reasoning_content": "hmm"}}]}, "thinking", "reasoning_content"),
    ({"choices": [{"message": {"content": "a", "reasoning": "hmm"}}]}, "thinking", "reasoning_content"),
    ({"choices": [{"message": {"content": "<think>hmm</think>a"}}]}, "thinking", "think_tags"),
    ({"choices": [{"message": {"content": "hmm</think>a"}}]}, "thinking", "think_tags"),
    ({"choices": [{"message": {"content": "a"}}],
      "usage": {"completion_tokens_details": {"reasoning_tokens": 812}}}, "thinking", "reasoning_tokens"),
    ({"choices": [{"message": {"content": "a"}}],
      "usage": {"completion_tokens_details": {"reasoning_tokens": 0}}}, "not_thinking", "no_reasoning"),
    ({"choices": [{"message": {"content": "a", "reasoning_content": None}}]}, "not_thinking", "no_reasoning"),
    ({}, "not_thinking", "no_reasoning"),
])
def test_openai_compatible_response(tc, payload, state, source) -> None:
    assert tc.observe_openai_payload(payload) == tc.Observation(state, source)


def test_anthropic_thinks_only_with_thinking_blocks(tc) -> None:
    thought = {"content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "a"}]}
    redacted = {"content": [{"type": "redacted_thinking", "data": "x"}, {"type": "text", "text": "a"}]}
    plain = {"content": [{"type": "text", "text": "a"}]}
    assert tc.observe_anthropic_payload(thought).state == "thinking"
    assert tc.observe_anthropic_payload(redacted).state == "thinking"
    assert tc.observe_anthropic_payload(plain) == tc.Observation("not_thinking", "not_requested")


# ── judging one model over several calls ─────────────────────────────────────

def _record(tc, hass, state, *, allow, path="local_openai", key="ai_task.m"):
    return tc.record_observation(
        hass, key=key, model="m", path=path,
        observation=tc.Observation(state, "x"), allow_thinking=allow,
    )


@pytest.mark.parametrize(("allow", "state", "hint"), [
    (True, "thinking", None),
    (True, "not_thinking", "ev_thinking_on_local_openai"),
    (False, "thinking", "ev_thinking_off"),
    (False, "not_thinking", None),
    (True, "unknown", None),
    (False, "unknown", None),
])
def test_setting_against_behaviour(tc, hass, allow, state, hint) -> None:
    assert _record(tc, hass, state, allow=allow) == hint
    status = tc.thinking_status(hass, allow)
    assert (status["observed"], status["hint"], status["model"]) == (state, hint, "m")


def test_a_mismatch_warns_once_and_again_after_it_went_away(tc, hass) -> None:
    assert _record(tc, hass, "not_thinking", allow=True) == "ev_thinking_on_local_openai"
    assert _record(tc, hass, "not_thinking", allow=True) is None
    assert _record(tc, hass, "thinking", allow=True) is None
    assert _record(tc, hass, "not_thinking", allow=True) == "ev_thinking_on_local_openai"


def test_unknown_calls_keep_the_last_judgement(tc, hass) -> None:
    _record(tc, hass, "not_thinking", allow=True)
    assert _record(tc, hass, "unknown", allow=True) is None
    status = tc.thinking_status(hass, True)
    assert status["observed"] == "not_thinking"
    assert status["counts"] == {"thinking": 0, "not_thinking": 1, "unknown": 1}


def test_the_status_follows_the_current_setting(tc, hass) -> None:
    _record(tc, hass, "thinking", allow=False)
    assert tc.thinking_status(hass, False)["hint"] == "ev_thinking_off"
    assert tc.thinking_status(hass, True)["hint"] is None


def test_no_call_yet(tc, hass) -> None:
    status = tc.thinking_status(hass, True)
    assert (status["model"], status["observed"], status["hint"]) == (None, "unknown", None)


@pytest.mark.parametrize(("path", "hint"), [
    ("local_openai", "ev_thinking_on_local_openai"),
    ("ollama", "ev_thinking_on_ollama"),
    ("anthropic", "ev_thinking_on_integration"),
    ("", "ev_thinking_on_integration"),
    ("cloud_openai", "ev_thinking_on_cloud"),
    ("cloud_azure", "ev_thinking_on_cloud"),
    ("cloud_anthropic", "ev_thinking_on_cloud_anthropic"),
])
def test_the_hint_names_where_to_switch_it_on(tc, hass, path, hint) -> None:
    assert _record(tc, hass, "not_thinking", allow=True, path=path) == hint


def test_every_hint_is_translated_with_its_placeholder(tc) -> None:
    for block in ("EN", "NL", "DE"):
        start = I18N.index(f"export const {block} = {{")
        body = I18N[start:I18N.index("\n};", start)]
        for key, text in tc.HINTS_EN.items():
            m = re.search(rf'^\s+{key}:\s+"((?:[^"\\]|\\.)*)",', body, re.M)
            assert m, (block, key)
            assert set(re.findall(r"\{(\w+)\}", m.group(1))) == {"model"}, (block, key)
            if block == "EN":  # the backend's fallback text is the panel's English text
                assert m.group(1) == text, key


# ── reading an AI task call's chat log ───────────────────────────────────────

def _assistant(thinking: str | None = None, native=None) -> SimpleNamespace:
    return SimpleNamespace(role="assistant", content="Hello!", thinking_content=thinking, native=native)


def _observe(tc, hass, domain, *contents, data="Hello!"):
    logs = {"c1": SimpleNamespace(content=[SimpleNamespace(role="user", content="Hi"), *contents])}
    with patch.object(tc, "_chat_logs", lambda _hass: logs):
        return tc.observe_ai_task(hass, SimpleNamespace(data=data, conversation_id="c1"), domain)


def test_thinking_text_in_the_chat_log(tc, hass) -> None:
    for domain in ("local_openai", "ollama", "openai_conversation"):
        assert _observe(tc, hass, domain, _assistant("hmm")) == tc.Observation("thinking", "chat_log")
    redacted = _assistant(native=SimpleNamespace(redacted_thinking="x"))
    assert _observe(tc, hass, "anthropic", redacted).state == "thinking"


def test_no_thinking_text_counts_only_where_it_would_be_passed_on(tc, hass) -> None:
    for domain in ("local_openai", "ollama", "anthropic"):
        assert _observe(tc, hass, domain, _assistant()) == tc.Observation("not_thinking", "chat_log_empty")
    assert _observe(tc, hass, "openai_conversation", _assistant()) == tc.Observation("unknown", "not_passed_on")


def test_think_tags_left_in_the_answer(tc, hass) -> None:
    obs = _observe(tc, hass, "local_openai", _assistant(), data="<think>hmm</think>Hello!")
    assert obs == tc.Observation("thinking", "think_tags")


def test_without_a_chat_log_nothing_is_known(tc, hass) -> None:
    unknown = tc.Observation("unknown", "no_chat_log")
    assert tc.observe_ai_task(hass, SimpleNamespace(data="Hello!", conversation_id="gone"), "local_openai") == unknown
    assert tc.observe_ai_task(hass, SimpleNamespace(data="Hello!"), "local_openai") == unknown
    # Home Assistant before 2025.9: assistant messages without a thinking field
    old = SimpleNamespace(role="assistant", content="Hello!")
    assert _observe(tc, hass, "local_openai", old) == unknown


# ── turns through /api/kyber/complete on the AI task path ────────────────────

class _FakeModel:
    """Stands in for the AI task call; leaves a chat log as Home Assistant does."""

    def __init__(self) -> None:
        self.thinks = False
        self.calls = 0
        self.chat_logs: dict[str, SimpleNamespace] = {}
        self._ids = itertools.count(1)

    async def __call__(self, *_args, instructions="", **_kwargs):
        self.calls += 1
        conversation_id = f"conv{next(self._ids)}"
        thinking = "The user greets me, so I greet back." if self.thinks else None
        self.chat_logs[conversation_id] = SimpleNamespace(content=[
            SimpleNamespace(role="user", content=instructions),
            _assistant(thinking),
        ])
        return SimpleNamespace(data="Hello!", conversation_id=conversation_id)


@pytest.fixture
def provider_domain(request) -> str:
    return getattr(request, "param", "local_openai")


@pytest.fixture
def allow_thinking(request) -> bool:
    return getattr(request, "param", True)


@pytest.fixture
def cloud_chat(request) -> dict:
    """Options for chatting through Kyber's own OpenAI call to the stand-in LLM (param True)."""
    if not getattr(request, "param", False):
        return {}
    return {
        "cloud_provider": "openai", "cloud_use_for_chat": True, "openai_api_key": "k",
        "openai_model": "fake", "openai_base_url": request.getfixturevalue("fake_llm"),
    }


@pytest.fixture
def mock_config_entry(allow_thinking, cloud_chat) -> MockConfigEntry:
    return MockConfigEntry(
        domain="kyber",
        data={"ai_task_entity_id": ENTITY, "max_tokens": 32768, "allow_thinking": allow_thinking, **cloud_chat},
        title="Kyber",
    )


@pytest.fixture
def model(hass: HomeAssistant, provider_domain: str) -> _FakeModel:
    """The chat model, registered as an AI task entity of ``provider_domain``."""
    er.async_get(hass).async_get_or_create("ai_task", provider_domain, "chat", suggested_object_id="chat_model")
    return _FakeModel()


async def _turn(hass, hass_client, model: _FakeModel, request_id: str) -> list[dict]:
    """One chat turn; returns its thinking-check warnings."""
    from custom_components.kyber import thinking_check

    client = await hass_client()
    with patch("custom_components.kyber.http_api.async_ai_call", new=model), \
         patch("custom_components.kyber.knowledge_integration.async_ai_call", new=model), \
         patch.object(thinking_check, "_chat_logs", lambda _hass: model.chat_logs):
        resp = await client.post("/api/kyber/complete", json={"prompt": "Hello", "request_id": request_id})
    assert resp.status == 200, await resp.text()
    events = hass.data["kyber_progress"][request_id]["events"]
    return [e for e in events if str(e.get("key", "")).startswith("ev_thinking_")]


async def _status(hass_client) -> dict:
    client = await hass_client()
    resp = await client.get("/api/kyber/debug/status")
    assert resp.status == 200, await resp.text()
    return (await resp.json())["thinking"]


@pytest.mark.parametrize(("allow_thinking", "thinks", "hint"), [
    (True, True, None),
    (True, False, "ev_thinking_on_local_openai"),
    (False, True, "ev_thinking_off"),
    (False, False, None),
], indirect=["allow_thinking"])
async def test_ai_task_turn(hass, model, setup_integration, hass_client, allow_thinking, thinks, hint) -> None:
    model.thinks = thinks
    warnings = await _turn(hass, hass_client, model, "t1")
    assert [w["key"] for w in warnings] == ([hint] if hint else [])
    if hint:
        assert (warnings[0]["type"], warnings[0]["params"]) == ("warning", {"model": ENTITY})
    # The check reads what the call left behind; it never calls the model itself.
    assert model.calls == 1
    status = await _status(hass_client)
    assert status["allow_thinking"] is allow_thinking
    assert status["observed"] == ("thinking" if thinks else "not_thinking")
    assert status["source"] == ("chat_log" if thinks else "chat_log_empty")
    assert (status["model"], status["path"], status["hint"]) == (ENTITY, "local_openai", hint)


async def test_the_warning_comes_once(hass, model, setup_integration, hass_client) -> None:
    assert len(await _turn(hass, hass_client, model, "t1")) == 1
    assert await _turn(hass, hass_client, model, "t2") == []
    model.thinks = True
    assert await _turn(hass, hass_client, model, "t3") == []
    assert (await _status(hass_client))["hint"] is None
    model.thinks = False
    assert len(await _turn(hass, hass_client, model, "t4")) == 1


@pytest.mark.parametrize("provider_domain", ["ollama"], indirect=True)
async def test_ollama_gets_its_own_hint(hass, model, setup_integration, hass_client) -> None:
    warnings = await _turn(hass, hass_client, model, "t1")
    assert [w["key"] for w in warnings] == ["ev_thinking_on_ollama"]


@pytest.mark.parametrize("provider_domain", ["openai_conversation"], indirect=True)
async def test_missing_thinking_text_proves_nothing_elsewhere(hass, model, setup_integration, hass_client) -> None:
    assert await _turn(hass, hass_client, model, "t1") == []
    status = await _status(hass_client)
    assert (status["observed"], status["source"], status["hint"]) == ("unknown", "not_passed_on", None)


# ── the contract with Home Assistant's own chat log ──────────────────────────

async def test_home_assistant_keeps_the_thinking_text_after_the_call(hass: HomeAssistant, tc) -> None:
    """A real AI task call: the result has no thinking text, its chat log does."""
    from homeassistant.components.ai_task import AITaskEntity, AITaskEntityFeature, GenDataTaskResult

    from custom_components.kyber.api_utilities import async_ai_call

    class ChatModel(AITaskEntity):
        _attr_supported_features = AITaskEntityFeature.GENERATE_DATA
        _attr_name = "Chat model"
        _attr_unique_id = "chat_model"
        thinks = True

        async def _async_generate_data(self, task, chat_log) -> GenDataTaskResult:
            async def stream():
                yield {"role": "assistant"}
                if self.thinks:
                    yield {"thinking_content": "The user greets me, so I greet back."}
                yield {"content": "Hello!"}

            async for _content in chat_log.async_add_delta_content_stream(self.entity_id, stream()):
                pass
            return GenDataTaskResult(conversation_id=chat_log.conversation_id, data=chat_log.content[-1].content)

    entity = ChatModel()

    async def setup_entry(hass, entry):
        await hass.config_entries.async_forward_entry_setups(entry, ["ai_task"])
        return True

    async def setup_platform(hass, entry, async_add_entities):
        async_add_entities([entity])

    assert await async_setup_component(hass, "homeassistant", {})
    await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "ai_task", {})
    mock_integration(hass, MockModule("local_openai", async_setup_entry=setup_entry))
    mock_platform(hass, "local_openai.ai_task", MockPlatform(async_setup_entry=setup_platform))
    mock_platform(hass, "local_openai.config_flow")
    entry = MockConfigEntry(domain="local_openai")
    entry.add_to_hass(hass)
    with mock_config_flow("local_openai", ConfigFlow):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    domain = tc.provider_domain(hass, ENTITY)
    assert domain == "local_openai"

    result = await async_ai_call(hass, task_name="t", entity_id=ENTITY, instructions="Hello")
    assert result.data == "Hello!"
    assert tc.observe_ai_task(hass, result, domain) == tc.Observation("thinking", "chat_log")

    entity.thinks = False
    result = await async_ai_call(hass, task_name="t", entity_id=ENTITY, instructions="Hello")
    assert tc.observe_ai_task(hass, result, domain) == tc.Observation("not_thinking", "chat_log_empty")


# ── Kyber's own OpenAI-compatible call, against a stand-in LLM ───────────────

@pytest.fixture
async def fake_llm(socket_enabled):
    """An OpenAI-compatible endpoint on localhost whose answers carry reasoning_content."""
    from aiohttp import web

    async def completions(request: web.Request) -> web.Response:
        await request.json()
        return web.json_response({
            "choices": [{"message": {"content": "[]", "reasoning_content": "thinking"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    app = web.Application()
    app.router.add_post("/v1/chat/completions", completions)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    yield f"http://127.0.0.1:{runner.addresses[0][1]}"
    await runner.cleanup()


async def test_the_stand_in_llm_is_seen_thinking(fake_llm) -> None:
    from custom_components.kyber.api_utilities import async_openai_ai_call

    result = await async_openai_ai_call(
        task_name="t", api_key="k", model="fake", instructions="Hello", base_url=fake_llm,
    )
    assert (result.thinking.state, result.thinking.source) == ("thinking", "reasoning_content")


@pytest.mark.parametrize(("allow_thinking", "cloud_chat"), [(False, True)], indirect=True)
async def test_cloud_turn_against_the_stand_in_llm(hass, setup_integration, hass_client) -> None:
    client = await hass_client()
    resp = await client.post("/api/kyber/complete", json={"prompt": "Hello", "request_id": "t1"})
    assert resp.status == 200, await resp.text()
    events = hass.data["kyber_progress"]["t1"]["events"]
    warnings = [e for e in events if str(e.get("key", "")).startswith("ev_thinking_")]
    assert [(w["key"], w["params"]) for w in warnings] == [("ev_thinking_off", {"model": "openai/fake"})]
    status = await _status(hass_client)
    assert (status["observed"], status["source"], status["path"]) == ("thinking", "reasoning_content", "cloud_openai")
