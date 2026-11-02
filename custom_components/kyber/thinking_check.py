"""Does the chat model really think? Compare "Let the model think" with what it did.

Thinking is switched on in the service behind Kyber (Chat Template Arguments
``enable_thinking=true`` or "Thinking mode" in Local OpenAI LLM, "Think before
responding" in Ollama); the ``allow_thinking`` option only tells Kyber that it
is on. When the two drift apart nobody notices: answers just get worse, or
slower. Kyber therefore looks at every chat call for traces of thinking,
without an extra model call:

- AI task entities: the result holds only the answer, and integrations strip
  the thinking text from it. Home Assistant (2025.9+) keeps the chat log of the
  call for a few minutes under the result's ``conversation_id``, with the
  model's ``thinking_content``. Kyber reads it there and changes nothing.
- Kyber's own cloud calls: ``reasoning_content`` or ``reasoning`` in the
  message, ``reasoning_tokens`` in the usage, thinking blocks (Anthropic).
- Both: ``<think>`` blocks left in the answer.

Thinking text proves thinking. Its absence proves the opposite only where the
provider would have passed it on: the integrations in PASS_THROUGH_DOMAINS and
Kyber's own cloud calls. Everywhere else the result is "unknown".
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

THINKING = "thinking"
NOT_THINKING = "not_thinking"
UNKNOWN = "unknown"

STATE_KEY = "kyber_thinking_check"

# AI task integrations that put all of the model's thinking into the chat log:
# Local OpenAI LLM (reasoning_content and <think> blocks, every server type),
# Ollama (its "thinking" field) and Anthropic (thinking blocks). OpenAI only
# logs reasoning summaries, which can be switched off.
PASS_THROUGH_DOMAINS = frozenset({"local_openai", "ollama", "anthropic"})

# Cloud providers Kyber calls itself; the value is the "path" recorded for them.
CLOUD_PATHS = {"openai": "cloud_openai", "azure": "cloud_azure", "anthropic": "cloud_anthropic"}

# What to do about a mismatch, as panel i18n keys (ev_*) with the English text
# for logs and as fallback. Every key must exist in www/src/i18n.js.
HINTS_EN: dict[str, str] = {
    "ev_thinking_on_local_openai": (
        "{model} answered without thinking, although 'Let the model think' is on. "
        "In Local OpenAI LLM, switch on 'Thinking mode' (server type llama.cpp; "
        "'Enable thinking' in older versions) or add enable_thinking = true under "
        "'Chat Template Arguments'. If the model cannot think, turn the option off."
    ),
    "ev_thinking_on_ollama": (
        "{model} answered without thinking, although 'Let the model think' is on. "
        "Switch on 'Think before responding' in the Ollama AI task. "
        "If the model cannot think, turn the option off."
    ),
    "ev_thinking_on_integration": (
        "{model} answered without thinking, although 'Let the model think' is on. "
        "Switch thinking on in the integration behind the AI task. "
        "If the model cannot think, turn the option off."
    ),
    "ev_thinking_on_cloud": (
        "{model} answered without thinking, although 'Let the model think' is on. "
        "Choose a model that thinks, or switch thinking on at the server. "
        "If the model cannot think, turn the option off."
    ),
    "ev_thinking_on_cloud_anthropic": (
        "Kyber does not ask Anthropic models to think, so {model} answered without thinking. "
        "Turn 'Let the model think' off."
    ),
    "ev_thinking_off": (
        "{model} thought before answering, although 'Let the model think' is off. Turn the "
        "option on (Kyber then stops appending /no_think), or switch thinking off in the "
        "service behind the model."
    ),
}


@dataclass(frozen=True, slots=True)
class Observation:
    """What one model call showed about thinking.

    ``state`` is THINKING, NOT_THINKING or UNKNOWN; ``source`` names where it
    was seen (the Debug tab translates it as dbg_think_src_<source>).
    """

    state: str
    source: str


def _has_think_tags(text: str) -> bool:
    # Some chat templates open the block in the prompt, so only "</think>" is left.
    return "<think>" in text or "</think>" in text


def observe_openai_payload(data: Any) -> Observation:
    """Thinking in an OpenAI-compatible chat completion (OpenAI, Azure, llama.cpp, vLLM, …).

    Servers that think send the text as ``reasoning_content`` (llama.cpp,
    vLLM, DeepSeek) or ``reasoning`` (OpenRouter), leave ``<think>`` in the
    answer, or count ``reasoning_tokens`` (OpenAI, Azure). A response without
    any of them counts as not thinking.
    """
    data = data if isinstance(data, dict) else {}
    choices = data.get("choices") or [{}]
    message = (choices[0] if isinstance(choices[0], dict) else {}).get("message") or {}
    if message.get("reasoning_content") or message.get("reasoning"):
        return Observation(THINKING, "reasoning_content")
    if _has_think_tags(str(message.get("content") or "")):
        return Observation(THINKING, "think_tags")
    details = (data.get("usage") or {}).get("completion_tokens_details") or {}
    reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else None
    if isinstance(reasoning_tokens, int) and reasoning_tokens > 0:
        return Observation(THINKING, "reasoning_tokens")
    return Observation(NOT_THINKING, "no_reasoning")


def observe_anthropic_payload(data: Any) -> Observation:
    """Thinking in an Anthropic Messages response.

    Claude thinks only when the request asks for it, and Kyber does not, so a
    response without thinking blocks is the expected case.
    """
    blocks = data.get("content") if isinstance(data, dict) else None
    if any(
        isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")
        for b in blocks or ()
    ):
        return Observation(THINKING, "thinking_blocks")
    return Observation(NOT_THINKING, "not_requested")


def provider_domain(hass: "HomeAssistant", entity_id: str) -> str:
    """The integration behind an AI task entity ("" when unknown)."""
    try:
        from homeassistant.helpers import entity_registry as er

        entry = er.async_get(hass).async_get(entity_id)
    except Exception:  # noqa: BLE001
        return ""
    return str(entry.platform) if entry else ""


def _chat_logs(hass: "HomeAssistant") -> dict:
    """Home Assistant's chat logs by conversation id, read-only.

    The public way to open a chat log creates a session and notifies chat log
    subscribers when the log is gone, so Kyber only looks it up.
    """
    try:
        from homeassistant.components.conversation.chat_log import DATA_CHAT_LOGS
    except ImportError:
        return {}
    return hass.data.get(DATA_CHAT_LOGS) or {}


def _assistant_contents(hass: "HomeAssistant", conversation_id: str | None) -> list | None:
    """The assistant messages of an AI task call, or None without a usable chat log."""
    chat_log = _chat_logs(hass).get(conversation_id) if conversation_id else None
    if chat_log is None:
        return None
    contents = [c for c in chat_log.content if getattr(c, "role", None) == "assistant"]
    if not contents or not all(hasattr(c, "thinking_content") for c in contents):
        return None  # Home Assistant before 2025.9 has no place for the thinking text
    return contents


def observe_ai_task(hass: "HomeAssistant", result: Any, domain: str) -> Observation:
    """Thinking in an AI task call: <think> left in the answer, else the chat log.

    ``domain`` is the integration behind the entity (provider_domain).
    """
    data = getattr(result, "data", None)
    if isinstance(data, str) and _has_think_tags(data):
        return Observation(THINKING, "think_tags")
    contents = _assistant_contents(hass, getattr(result, "conversation_id", None))
    if contents is None:
        return Observation(UNKNOWN, "no_chat_log")
    if any(
        c.thinking_content or getattr(getattr(c, "native", None), "redacted_thinking", None)
        for c in contents
    ):
        return Observation(THINKING, "chat_log")
    if domain in PASS_THROUGH_DOMAINS:
        return Observation(NOT_THINKING, "chat_log_empty")
    return Observation(UNKNOWN, "not_passed_on")


def _mismatch_hint(allow_thinking: bool, seen: str, path: str) -> str | None:
    """The hint key (HINTS_EN) for a mismatch between setting and behaviour, else None."""
    if not allow_thinking and seen == THINKING:
        return "ev_thinking_off"
    if not allow_thinking or seen != NOT_THINKING:
        return None
    if path == CLOUD_PATHS["anthropic"]:
        return "ev_thinking_on_cloud_anthropic"
    if path in CLOUD_PATHS.values():
        return "ev_thinking_on_cloud"
    if path in ("local_openai", "ollama"):
        return f"ev_thinking_on_{path}"
    return "ev_thinking_on_integration"


def record_observation(
    hass: "HomeAssistant",
    *,
    key: str,
    model: str,
    path: str,
    observation: Observation,
    allow_thinking: bool,
) -> str | None:
    """Store one chat call's observation; return a hint key when a mismatch begins.

    ``key`` identifies the chat model (the AI task entity, or the cloud model),
    ``model`` is its display name, ``path`` the integration domain of the
    entity or a CLOUD_PATHS value. The judgement uses the latest call that
    showed something (UNKNOWN keeps the previous one). A hint is returned once
    per mismatch: again only after it went away or turned into the other one.
    """
    store = hass.data.setdefault(STATE_KEY, {"chat_model": None, "models": {}})
    rec = store["models"].setdefault(key, {
        "counts": {THINKING: 0, NOT_THINKING: 0, UNKNOWN: 0},
        "seen": None,
        "last": None,
        "warned": None,
    })
    store["chat_model"] = key
    now = time.time()
    rec["model"] = model
    rec["path"] = path
    rec["counts"][observation.state] += 1
    rec["last"] = {"state": observation.state, "source": observation.source, "ts": now}
    if observation.state != UNKNOWN:
        rec["seen"] = rec["last"]
    seen = rec["seen"]["state"] if rec["seen"] else UNKNOWN
    hint = _mismatch_hint(allow_thinking, seen, path)
    new = hint if hint and hint != rec["warned"] else None
    rec["warned"] = hint
    return new


def thinking_status(hass: "HomeAssistant", allow_thinking: bool) -> dict:
    """The Debug tab's view of the chat model: setting, what was seen, and the hint."""
    store = hass.data.get(STATE_KEY) or {}
    rec = (store.get("models") or {}).get(store.get("chat_model")) or {}
    shown = rec.get("seen") or rec.get("last") or {}
    observed = shown.get("state", UNKNOWN)
    return {
        "allow_thinking": allow_thinking,
        "model": rec.get("model"),
        "path": rec.get("path"),
        "observed": observed,
        "source": shown.get("source"),
        "ts": shown.get("ts"),
        "counts": dict(rec.get("counts") or {THINKING: 0, NOT_THINKING: 0, UNKNOWN: 0}),
        "hint": _mismatch_hint(allow_thinking, observed, rec.get("path") or ""),
    }
