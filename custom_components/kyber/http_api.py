"""HTTP API view for kyber: proxies AI completion requests."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from http import HTTPStatus
from typing import Any

import yaml
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.storage import Store

try:
    from homeassistant.components.ai_task import async_generate_data
except ImportError:  # HA < 2025.2 (test environments)
    async def async_generate_data(*args, **kwargs):  # type: ignore[misc]
        raise RuntimeError("homeassistant.components.ai_task not available (HA < 2025.2)")

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN, SYSTEM_PROMPT_TEMPLATE
from .knowledge import CATEGORIES as KNOWLEDGE_CATEGORIES, get_store as get_knowledge_store
from .analyzer import analyze_automations as _analyze_automations
from .source import (
    read_automations as _src_read_automations,
    read_scripts as _src_read_scripts,
    read_blueprints as _src_read_blueprints,
    read_blueprint as _src_read_blueprint,
)
from . import deep_analyzer as _deep

_LOGGER = logging.getLogger(__name__)

_PROGRESS_KEY = "kyber_progress"
_PROGRESS_MAX_AGE = 300  # seconds — purge entries older than this on access
_PROGRESS_MAX_ENTRIES = 64

_DEBUG_MODE_KEY = "kyber_debug_mode"
_DEBUG_MODE_DEFAULT = True


def _get_debug_mode(hass: HomeAssistant) -> bool:
    val = hass.data.get(_DEBUG_MODE_KEY)
    if val is None:
        return _DEBUG_MODE_DEFAULT
    return bool(val)


# Debug snapshot keys — in-memory only, purged on HA restart.
_DEBUG_LAST_TURN_KEY = "kyber_debug_last_turn"
_DEBUG_SNAPSHOTS_KEY = "kyber_debug_snapshots"  # request_id -> snapshot ring buffer
_DEBUG_SNAPSHOTS_MAX = 50
_DEBUG_TOOL_HISTORY_KEY = "kyber_debug_tool_history"
_DEBUG_TOOL_HISTORY_MAX = 20
_DEBUG_LOG_CAPTURE_KEY = "kyber_debug_log_capture"  # request_id -> list[dict]
_DEBUG_LOG_CAPTURE_MAX_PER_TURN = 500


class _KyberTurnLogHandler(logging.Handler):
    """Logging handler that captures kyber.* records for a single turn."""

    def __init__(self, sink: list[dict]) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            name = record.name or ""
            if not (name.startswith("custom_components.kyber") or name.startswith("kyber")):
                return
            if len(self._sink) >= _DEBUG_LOG_CAPTURE_MAX_PER_TURN:
                return
            self._sink.append({
                "ts": record.created,
                "level": record.levelname,
                "logger": name,
                "message": record.getMessage(),
            })
        except Exception:  # noqa: BLE001
            pass


def _debug_attach_log_capture(request_id: str) -> tuple[list[dict], _KyberTurnLogHandler] | tuple[None, None]:
    """Attach a per-turn log handler to the root logger; returns (sink, handler) or (None, None)."""
    if not request_id:
        return None, None
    try:
        sink: list[dict] = []
        handler = _KyberTurnLogHandler(sink)
        logging.getLogger().addHandler(handler)
        return sink, handler
    except Exception:  # noqa: BLE001
        return None, None


def _debug_detach_log_capture(handler: _KyberTurnLogHandler | None) -> None:
    if handler is None:
        return
    try:
        logging.getLogger().removeHandler(handler)
    except Exception:  # noqa: BLE001
        pass


def _debug_record_turn(
    hass: HomeAssistant,
    *,
    request_id: str,
    user_prompt: str,
    expanded_prompt: str,
    instructions_used: str,
    picked_knowledge: list[dict],
    tool_log: list[dict],
    intent: str | None,
    response_text: str,
    auto_rating: int | None,
    elapsed_ms: int,
    logs: list[dict] | None = None,
    progress_events: list[dict] | None = None,
    session_meta: dict | None = None,
) -> None:
    """Capture a per-turn debug snapshot. Single slot + ring buffer + per-request_id map."""
    import time
    snapshot = {
        "request_id": request_id,
        "ts": int(time.time()),
        "user_prompt": user_prompt,
        "expanded_prompt": expanded_prompt[:32000],
        "instructions_used": instructions_used[:32000],
        "picked_knowledge": picked_knowledge,
        "tool_log": tool_log,
        "intent": intent,
        "response_text": (response_text or "")[:8000],
        "auto_rating": auto_rating,
        "elapsed_ms": elapsed_ms,
        "char_count": len(expanded_prompt),
        "approx_tokens": len(expanded_prompt) // 4,
        "logs": logs or [],
        "progress_events": progress_events or [],
        "session_meta": session_meta or {},
    }
    hass.data[_DEBUG_LAST_TURN_KEY] = snapshot
    # Per-request_id map (newest wins, evict oldest beyond max).
    from collections import OrderedDict, deque
    snaps = hass.data.get(_DEBUG_SNAPSHOTS_KEY)
    if not isinstance(snaps, OrderedDict):
        snaps = OrderedDict()
        hass.data[_DEBUG_SNAPSHOTS_KEY] = snaps
    if request_id:
        snaps[request_id] = snapshot
        while len(snaps) > _DEBUG_SNAPSHOTS_MAX:
            snaps.popitem(last=False)
    # Tool ring buffer
    history = hass.data.get(_DEBUG_TOOL_HISTORY_KEY)
    if not isinstance(history, deque):
        history = deque(maxlen=_DEBUG_TOOL_HISTORY_MAX)
        hass.data[_DEBUG_TOOL_HISTORY_KEY] = history
    for entry in tool_log or []:
        history.append({
            "ts": snapshot["ts"],
            "request_id": request_id,
            **entry,
        })


def _progress_emit(hass: HomeAssistant, request_id: str, event: dict) -> None:
    """Append a progress event for a request_id (in-memory)."""
    if not request_id:
        return
    import time
    store: dict = hass.data.setdefault(_PROGRESS_KEY, {})
    # Purge old entries (best effort, cheap)
    now = time.time()
    if len(store) > _PROGRESS_MAX_ENTRIES:
        stale = [k for k, v in store.items() if now - v.get("ts", now) > _PROGRESS_MAX_AGE]
        for k in stale:
            store.pop(k, None)
    entry = store.setdefault(request_id, {"events": [], "ts": now, "status": "running"})
    entry["ts"] = now
    entry["events"].append({**event, "t": now})


def _progress_complete(hass: HomeAssistant, request_id: str) -> None:
    """Mark a request as complete (kept briefly so client can fetch last events)."""
    if not request_id:
        return
    import time
    store: dict = hass.data.setdefault(_PROGRESS_KEY, {})
    entry = store.setdefault(request_id, {"events": [], "ts": time.time(), "status": "running"})
    entry["status"] = "done"
    entry["ts"] = time.time()


_YAML_BLOCK_RE = re.compile(r"```yaml\s*([\s\S]+?)\s*```", re.IGNORECASE)
_PLAN_BLOCK_RE = re.compile(r"```plan\s*([\s\S]+?)\s*```", re.IGNORECASE)
_CLARIFY_BLOCK_RE = re.compile(r"```clarify\s*([\s\S]+?)\s*```", re.IGNORECASE)
# Match [TOOL_CALL: ...] tolerating O/0 confusion from small models
_TOOL_CALL_RE = re.compile(r"\[T[O0]{2}L[_\-]CALL:\s*(\{[^]]*?\})\s*\]", re.DOTALL | re.IGNORECASE)
# Match [TOOL_RESULT: ...] with same tolerance
_TOOL_RESULT_STRIP_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?", re.IGNORECASE)
_TOOL_RESULT_ECHO_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?.*?(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE)
_TOOL_CALL_MAX_ROUNDS = 5

# ── Quick-intent shortcuts (sidestep the AI for trivially parseable requests) ──
# Small models often loop on `get_areas` instead of emitting a `create_area`
# plan because every example action in the prompt has an `entity_id` and they
# don't realise create_area has none. For 100% unambiguous requests we
# short-circuit the model entirely.

_QUICK_CREATE_AREA_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?"
    r"(?:create|add|make|new)"
    r"\s+(?:an?\s+|a\s+new\s+)?area"
    r"\s+(?:called\s+|named\s+)?[\"'`]?([\w][\w\s\-]{0,50}?)[\"'`]?\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def _try_quick_intent(user_prompt: str) -> dict[str, Any] | None:
    """Detect trivially parseable single-action requests.

    Returns a dict suitable for emitting as the final response, or None.

    Currently handles:
      - "create (an?) area NAME"
      - "add area NAME"
      - "make a new area called NAME"

    Multi-line prompts (e.g. "create an area Yard\\nmake it Dutch") are
    intentionally skipped so the AI can process the extra instructions.
    """
    if not user_prompt:
        return None
    # If the user added extra instructions on additional lines (e.g.
    # "create an area Yard\nmake it a dutch name"), skip the shortcut so
    # the AI loop can honour those instructions (e.g. translating the name).
    lines = [l for l in user_prompt.split("\n") if l.strip()]
    if len(lines) > 1:
        return None
    text = user_prompt.strip()
    m = _QUICK_CREATE_AREA_RE.match(text)
    if m:
        name = m.group(1).strip().strip("'\"`").strip()
        if not name:
            return None
        # Reject obviously non-name tokens that a casual user wouldn't intend
        if name.lower() in {"area", "the area", "new", "one"}:
            return None
        # Reject names that contain newlines (should have been caught above,
        # but guard defensively against other multi-line edge cases).
        if "\n" in name or "\r" in name:
            return None
        plan = {
            "summary": f"Create area '{name}'",
            "actions": [{
                "type": "create_area",
                "name": name,
                "current_state": "(none)",
                "new_state": name,
                "description": f"Create new area '{name}'",
            }],
        }
        response = (
            f"I'll create a new area called **{name}**. "
            "Approve the plan below to apply.\n\n"
            "```plan\n" + json.dumps(plan) + "\n```"
        )
        return {
            "response_text": response,
            "intent": "action",
            "shortcut": "quick_create_area",
            "plan": plan,
        }
    return None


# Appended to the tool-exchange when we need a plain-text synthesis pass
# (model looped on tool calls and never wrote a prose answer).
_SYNTHESIS_INSTRUCTIONS = (
    "\n\n[SYSTEM: You already have all the data you need from the tool results "
    "shown above. Answer the user's question directly in plain text now. "
    "Do NOT output any [TOOL_CALL:] blocks — only a prose answer. "
    "List EVERY item from the results; do not truncate with '...' or 'and X more'.]\n"
    "Assistant:"
)


# Keywords that indicate the user wants to change/act on something (ACTION intent).
# Anything else is INFORMATIONAL — the AI should just respond in plain text.
_ACTION_KEYWORDS: frozenset[str] = frozenset({
    "edit", "modify", "change", "update", "rename", "assign", "move",
    "turn on", "turn off", "switch on", "switch off", "set", "create",
    "delete", "remove", "add", "make", "enable", "disable", "fix", "open editor",
    "open automation", "open script", "open dashboard", "adjust", "configure",
    "schedule", "trigger", "automate", "dim", "brighten",
    "lock", "unlock", "arm", "disarm",
    "zet aan", "zet uit",  # Dutch on/off
    "organise", "organize", "order my", "sort my", "clean up", "tidy",
    "propose", "suggest changes", "suggest a plan",
})

# Regex patterns for split-word action intent (e.g. "turn those off", "switch it on")
_ACTION_RE_PATTERNS: tuple = (
    re.compile(r"\bturn\b.{0,30}\b(on|off)\b", re.IGNORECASE),
    re.compile(r"\bswitch\b.{0,30}\b(on|off)\b", re.IGNORECASE),
    re.compile(r"\b(on|off)\b.{0,30}\bturn\b", re.IGNORECASE),
    re.compile(r"\bzet\b.{0,20}\b(aan|uit)\b", re.IGNORECASE),  # Dutch
)

_RESPONSE_MODE_INFORMATIONAL = (
    "<<RULES — never echo or quote these>>\n"
    "INFORMATIONAL mode:\n"
    "- Areas/labels/automations/scripts are in context → answer directly from there.\n"
    "- Entity IDs/states not in context → output [TOOL_CALL:{\"name\":\"...\"}] immediately, nothing else.\n"
    "- If question is about a SPECIFIC state (e.g. 'lights that are on', 'open doors'), ADD a \"state\" filter to the tool call (e.g. \"state\":\"on\"). This returns only matching items — list ALL of them.\n"
    "- After tool result: list EVERY SINGLE item from the result. If result has 83 items, output 83 bullets. NEVER stop at 5/10/20. NEVER write '...' or 'and more'.\n"
    "- Use ONLY these tool names: list_entities_by_domain, get_entity_state, get_area_entities, list_entities_by_label, search_entities, list_entities_without_area, get_areas, get_labels.\n"
    "- No preamble. No footer. No 'What would you like to do?' No 'Please let me know'.\n"
    "- Do NOT output a plan block.\n"
    "<</RULES>>\n\n"
)

_RESPONSE_MODE_ACTION = (
    "<<RULES — never echo or quote these>>\n"
    "ACTION mode:\n"
    "- Need entity IDs not yet in context? → output [TOOL_CALL:{\"name\":\"...\"}] immediately.\n"
    "- Entity IDs already in context or tool results? → output plan block directly.\n"
    "- If user says 'those'/'them'/'it' → use the entities from the conversation history above.\n"
    "- Control devices via plan/actions block (call_service). Editing areas/labels/names uses assign_area/rename_entity/assign_label actions. NOT open_editor.\n"
    "- Use ONLY these tool names: list_entities_by_domain, get_entity_state, get_area_entities, list_entities_by_label, search_entities, list_entities_without_area, get_areas, get_labels.\n"
    "- For 'fix/organise/order my entities': call list_entities_without_area, then propose a plan with assign_area actions.\n"
    "- No preamble. No footer.\n"
    "<</RULES>>\n\n"
)


def _classify_intent(user_prompt: str) -> str:
    """Return 'action' if the prompt requests a change, otherwise 'informational'."""
    lower = user_prompt.lower()
    if any(kw in lower for kw in _ACTION_KEYWORDS):
        return "action"
    if any(p.search(lower) for p in _ACTION_RE_PATTERNS):
        return "action"
    return "informational"
_CHAT_HISTORY_STORE_VERSION = 1
_CHAT_HISTORY_STORE_KEY = f"{DOMAIN}_chat_history"
_CHAT_HISTORY_MAX_MESSAGES = 20
_CHAT_MESSAGE_MAX_CHARS = 1500
_CHAT_SUMMARY_MAX_CHARS = 2000
# Hard cap on total instructions to avoid exceeding Ollama's context window (~8K tokens ≈ 32K chars)
_MAX_INSTRUCTIONS_CHARS = 32_000
# Reserve budget for knowledge facts so they survive the loop's re-truncation.
# Base prompt is capped at (_MAX_INSTRUCTIONS_CHARS - _KNOWLEDGE_BUDGET); knowledge
# is then appended within the remaining space, keeping total ≤ _MAX_INSTRUCTIONS_CHARS.
_KNOWLEDGE_BUDGET = 2_000
_BASE_INSTRUCTIONS_CHARS = _MAX_INSTRUCTIONS_CHARS - _KNOWLEDGE_BUDGET  # 30 000
_SESSIONS_MAX = 20
_SESSION_NAME_MAX_CHARS = 80


def _new_session_id() -> str:
    """Generate a short unique session ID."""
    import time, random, string
    ts = hex(int(time.time()))[2:]
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{ts}{rand}"


def _migrate_user_to_sessions(user_data: dict[str, Any]) -> dict[str, Any]:
    """Migrate old {history, compacted_summary} to new sessions schema in place."""
    if "sessions" in user_data:
        return user_data  # already migrated
    sid = _new_session_id()
    return {
        "active_session": sid,
        "sessions": {
            sid: {
                "name": "Session 1",
                "history": user_data.get("history", []),
                "compacted_summary": user_data.get("compacted_summary", ""),
                "created_at": __import__("time").time(),
            }
        },
    }


def _get_active_session(user_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (session_id, session_data) for the active session, creating one if needed."""
    sessions: dict[str, Any] = user_data.get("sessions", {})
    active_id: str | None = user_data.get("active_session")
    if active_id and active_id in sessions:
        return active_id, sessions[active_id]
    # Fall back to first session or create a new one
    if sessions:
        first_id = next(iter(sessions))
        user_data["active_session"] = first_id
        return first_id, sessions[first_id]
    # No sessions — create default
    sid = _new_session_id()
    session = {"name": "Session 1", "history": [], "compacted_summary": "", "created_at": __import__("time").time()}
    sessions[sid] = session
    user_data["sessions"] = sessions
    user_data["active_session"] = sid
    return sid, session


def _build_home_state_by_area(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
    area_by_id: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    """Build a per-area home state snapshot and aggregate stats."""
    # area_name → collected metrics
    area_data: dict[str, dict[str, Any]] = {}

    def _area(name: str) -> dict[str, Any]:
        if name not in area_data:
            area_data[name] = {
                "lights_on": 0, "lights_total": 0,
                "presence": False,
                "temps": [],
                "media": [],
                "open_windows": 0, "open_doors": 0,
            }
        return area_data[name]

    unavailable_count = 0
    low_battery_count = 0
    total_lights_on = 0

    for state in hass.states.async_all():
        entity_id = state.entity_id
        domain = entity_id.split(".")[0]
        if domain in ("automation", "script", "scene", "group", "persistent_notification",
                      "sun", "zone", "update", "event", "schedule"):
            continue

        if state.state == "unavailable":
            unavailable_count += 1
            continue

        # Battery alerts (any entity with a battery_level attribute < 20%)
        batt = state.attributes.get("battery_level") or state.attributes.get("battery")
        if batt is not None:
            try:
                if float(batt) < 20:
                    low_battery_count += 1
            except (ValueError, TypeError):
                pass

        entry = entity_reg.async_get(entity_id)
        area_id = entry.area_id if entry else None
        area_name = area_by_id.get(area_id or "", "") if area_id else ""

        if domain == "light":
            if area_name:
                d = _area(area_name)
                d["lights_total"] += 1
                if state.state == "on":
                    d["lights_on"] += 1
                    total_lights_on += 1
            elif state.state == "on":
                total_lights_on += 1

        elif domain == "binary_sensor":
            device_class = state.attributes.get("device_class", "")
            if device_class in ("occupancy", "presence", "motion"):
                if state.state == "on" and area_name:
                    _area(area_name)["presence"] = True
            elif device_class == "window" and state.state == "on" and area_name:
                _area(area_name)["open_windows"] += 1
            elif device_class == "door" and state.state == "on" and area_name:
                _area(area_name)["open_doors"] += 1

        elif domain == "person" and area_name:
            if state.state not in ("not_home", "away", "unknown"):
                _area(area_name)["presence"] = True

        elif domain == "climate" and area_name:
            temp = state.attributes.get("current_temperature")
            if temp is not None:
                try:
                    _area(area_name)["temps"].append(float(temp))
                except (ValueError, TypeError):
                    pass

        elif domain == "sensor" and area_name:
            if state.attributes.get("device_class") == "temperature" and state.state not in ("unknown", "unavailable"):
                try:
                    _area(area_name)["temps"].append(float(state.state))
                except (ValueError, TypeError):
                    pass

        elif domain == "media_player" and area_name:
            if state.state not in ("idle", "off", "standby", "unavailable", "unknown"):
                friendly = state.attributes.get("friendly_name", entity_id)
                title = state.attributes.get("media_title", "")
                _area(area_name)["media"].append(f"{friendly}" + (f": {title}" if title else f" ({state.state})"))

    # Format lines
    lines: list[str] = []
    for area_name in sorted(area_data.keys()):
        d = area_data[area_name]
        parts: list[str] = []
        if d["lights_total"] > 0:
            parts.append(f"💡 {d['lights_on']}/{d['lights_total']} lights on")
        if d["presence"]:
            parts.append("👤 occupied")
        if d["temps"]:
            avg_temp = sum(d["temps"]) / len(d["temps"])
            parts.append(f"🌡 {avg_temp:.1f}°C")
        for m in d["media"][:2]:
            parts.append(f"📺 {m}")
        if d["open_windows"]:
            parts.append(f"🪟 {d['open_windows']} open")
        if d["open_doors"]:
            parts.append(f"🚪 {d['open_doors']} open")
        if parts:
            lines.append(f"  {area_name}: {' | '.join(parts)}")

    alerts: list[str] = []
    if unavailable_count:
        alerts.append(f"{unavailable_count} unavailable")
    if low_battery_count:
        alerts.append(f"{low_battery_count} low battery")
    if alerts:
        lines.append(f"  ⚠️ Alerts: {', '.join(alerts)}")

    home_state = "\n".join(lines) or "(no area state available)"
    stats = {
        "total_lights_on": total_lights_on,
        "unavailable_count": unavailable_count,
        "low_battery_count": low_battery_count,
    }
    return home_state, stats


def _build_context(hass: HomeAssistant) -> tuple[str, dict[str, Any]]:
    """Build a compact context string with domain stats + area home state."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)

    areas = area_reg.async_list_areas()
    area_list = "\n".join(f"- {a.name} → {a.id}" for a in areas) or "(no areas)"
    area_by_id = {a.id: a.name for a in areas}

    labels = label_reg.async_list_labels()
    label_list = "\n".join(f"- {lbl.label_id} | {lbl.name}" for lbl in labels) or "(no labels)"

    automation_lines: list[str] = []
    script_lines: list[str] = []
    domain_counts: dict[str, int] = {}

    all_states = hass.states.async_all()
    entity_count = 0

    for state in sorted(all_states, key=lambda s: s.entity_id):
        domain = state.entity_id.split(".")[0]
        if state.entity_id.startswith("automation."):
            friendly = state.attributes.get("friendly_name", state.entity_id)
            config_id = state.attributes.get("id", state.entity_id)
            automation_lines.append(f"- {state.entity_id} | {friendly} | config_id: {config_id}")
        elif state.entity_id.startswith("script."):
            friendly = state.attributes.get("friendly_name", state.entity_id)
            script_lines.append(f"- {state.entity_id} | {friendly}")
        else:
            entity_count += 1
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

    _AUTO_LIMIT = 50
    _SCRIPT_LIMIT = 25
    if len(automation_lines) > _AUTO_LIMIT:
        automation_lines_shown = automation_lines[:_AUTO_LIMIT]
        automation_lines_shown.append(
            f"… and {len(automation_lines) - _AUTO_LIMIT} more (use list_automations tool to see all)"
        )
    else:
        automation_lines_shown = automation_lines
    if len(script_lines) > _SCRIPT_LIMIT:
        script_lines_shown = script_lines[:_SCRIPT_LIMIT]
        script_lines_shown.append(
            f"… and {len(script_lines) - _SCRIPT_LIMIT} more (use list_scripts tool to see all)"
        )
    else:
        script_lines_shown = script_lines

    automation_list = "\n".join(automation_lines_shown) or "(no automations)"
    script_list = "\n".join(script_lines_shown) or "(no scripts)"

    # Domain stats: top 10 by count
    sorted_domains = sorted(domain_counts.items(), key=lambda x: -x[1])
    stats_parts = [f"{d}: {c}" for d, c in sorted_domains[:10]]
    if len(sorted_domains) > 10:
        stats_parts.append(f"… {len(sorted_domains) - 10} more domains")
    entity_stats = f"{entity_count} total — {' | '.join(stats_parts)}"

    # Per-area home state
    home_state_by_area, area_stats = _build_home_state_by_area(hass, entity_reg, area_by_id)

    context_stats: dict[str, Any] = {
        "entity_count": entity_count,
        "automation_count": len(automation_lines),
        "area_count": len(areas),
        "lights_on": area_stats["total_lights_on"],
        "unavailable_count": area_stats["unavailable_count"],
        "low_battery_count": area_stats["low_battery_count"],
    }

    context = SYSTEM_PROMPT_TEMPLATE.format(
        area_list=area_list,
        label_list=label_list,
        entity_stats=entity_stats,
        home_state_by_area=home_state_by_area,
        automation_list=automation_list,
        script_list=script_list,
    )
    return context, context_stats


def _tool_result_summary(call: dict[str, Any], result: Any) -> str:
    """Build a short human-readable summary of a tool call result for the UI."""
    name = call.get("name", "")
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"
    if name == "list_entities_by_domain":
        count = len(result) if isinstance(result, dict) else 0
        domain = call.get("domain", "?")
        return f"{count} {domain} entities"
    if name == "get_entity_state":
        eid = call.get("entity_id", "?")
        state = result.get("state", "?") if isinstance(result, dict) else "?"
        return f"{eid} = {state}"
    if name == "get_area_entities":
        area = result.get("area", call.get("area", "?")) if isinstance(result, dict) else "?"
        count = len(result.get("entities", {})) if isinstance(result, dict) else 0
        return f"{count} entities in {area}"
    if name == "list_entities_by_label":
        label = result.get("label", call.get("label", "?")) if isinstance(result, dict) else "?"
        count = len(result.get("entities", {})) if isinstance(result, dict) else 0
        return f"{count} entities with label '{label}'"
    if name == "search_entities":
        count = len(result) if isinstance(result, dict) else 0
        return f"{count} matches for '{call.get('query', '?')}'"
    if name == "get_areas":
        count = len(result) if isinstance(result, dict) else 0
        return f"{count} areas"
    if name == "get_labels":
        count = len(result) if isinstance(result, dict) else 0
        return f"{count} labels"
    return "done"


def _state_matches(state_obj: Any, state_filter: str | list | None) -> bool:
    """Return True if the entity's state matches the filter (str, list, or None)."""
    if state_filter is None or state_filter == "":
        return True
    if state_obj is None:
        return False
    actual = state_obj.state if hasattr(state_obj, "state") else str(state_obj)
    if isinstance(state_filter, list):
        return actual in [str(s) for s in state_filter]
    return actual == str(state_filter)


def _execute_tool(hass: HomeAssistant, call: dict[str, Any]) -> str:
    """Execute a tool call and return the result as a JSON string."""
    name = call.get("name", "")
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)

    # Tool name aliases — small models often invent close-but-wrong tool names.
    _ALIASES = {
        "list_entities_by_area": "get_area_entities",
        "list_area_entities": "get_area_entities",
        "get_entities_by_area": "get_area_entities",
        "get_entities_in_area": "get_area_entities",
        "list_entities": "list_entities_by_domain",
        "list_domain_entities": "list_entities_by_domain",
        "get_state": "get_entity_state",
        "entity_state": "get_entity_state",
        "search": "search_entities",
        "find_entities": "search_entities",
        "list_areas": "get_areas",
        "list_labels": "get_labels",
        "get_entities_by_label": "list_entities_by_label",
        "get_knowledge": "search_knowledge",
        "list_knowledge": "search_knowledge",
        "knowledge": "search_knowledge",
        "entity_notes": "get_entity_notes",
        "get_notes": "get_entity_notes",
    }
    if name in _ALIASES:
        _LOGGER.info("Kyber: tool alias %s → %s", name, _ALIASES[name])
        name = _ALIASES[name]
        call = {**call, "name": name}

    # Also map common argument-key aliases
    if name == "get_area_entities" and "area" not in call:
        for alt in ("area_id", "area_name"):
            if alt in call:
                call = {**call, "area": call[alt]}
                break

    state_filter = call.get("state")

    # `fields` lets the model request only specific properties per entity to
    # keep responses small. Accepts a list of strings. Synthetic keys:
    #   "name", "state", "domain", "area", "area_id"
    # Any other key is looked up in state.attributes (e.g. "brightness",
    # "current_temperature", "rgb_color"). When omitted, the tool uses its
    # default minimal projection ({name, state}).
    fields_raw = call.get("fields")
    fields_set: set[str] | None = None
    if isinstance(fields_raw, list) and fields_raw:
        fields_set = {str(f).strip() for f in fields_raw if str(f).strip()}
    elif isinstance(fields_raw, str) and fields_raw.strip():
        fields_set = {f.strip() for f in fields_raw.split(",") if f.strip()}

    def _project_entity(eid: str, st, entry=None) -> dict:
        """Return a dict for an entity using the active fields_set, or the
        default {name, state} projection when no fields were requested.
        """
        attrs = st.attributes if st else {}
        domain = eid.split(".")[0]
        if fields_set is None:
            return {
                "name": attrs.get("friendly_name", eid),
                "state": st.state if st else "unknown",
            }
        out: dict = {}
        for f in fields_set:
            if f in ("entity_id", "id"):
                out["entity_id"] = eid
            elif f == "name":
                out["name"] = attrs.get("friendly_name", eid)
            elif f == "state":
                out["state"] = st.state if st else "unknown"
            elif f == "domain":
                out["domain"] = domain
            elif f in ("area", "area_name", "area_id"):
                resolved_entry = entry if entry is not None else entity_reg.async_get(eid)
                aid = resolved_entry.area_id if resolved_entry else None
                if f == "area_id":
                    out["area_id"] = aid
                else:
                    aobj = area_reg.async_get_area(aid) if aid else None
                    out["area"] = aobj.name if aobj else None
            else:
                # Look up in attributes (drop None values to save bytes)
                if f in attrs and attrs[f] is not None:
                    out[f] = attrs[f]
        return out

    if name == "list_entities_by_domain":
        domain = call.get("domain", "").strip().lower()
        if not domain:
            return json.dumps({"error": "Missing 'domain' argument"})
        results = {}
        for state in sorted(hass.states.async_all(), key=lambda s: s.entity_id):
            if state.entity_id.split(".")[0] != domain:
                continue
            if not _state_matches(state, state_filter):
                continue
            results[state.entity_id] = _project_entity(state.entity_id, state)
        if not results:
            msg = f"No entities found for domain '{domain}'"
            if state_filter:
                msg += f" with state={state_filter!r}"
            return json.dumps({"info": msg})
        return json.dumps(results)

    if name == "get_entity_state":
        entity_id = call.get("entity_id", "").strip()
        if not entity_id:
            return json.dumps({"error": "Missing 'entity_id' argument"})
        state = hass.states.get(entity_id)
        if not state:
            return json.dumps({"error": f"Entity '{entity_id}' not found"})
        entry = entity_reg.async_get(entity_id)
        area_id = entry.area_id if entry else None
        area_name = None
        if area_id:
            area_obj = area_reg.async_get_area(area_id)
            area_name = area_obj.name if area_obj else None
        # If the caller specified `fields`, return ONLY those attributes
        # (synthetic keys: name, state, area, area_id, domain — anything else
        # is looked up in state.attributes).
        if fields_set is not None:
            return json.dumps({
                "entity_id": entity_id,
                **_project_entity(entity_id, state, entry),
            })
        # Default: trim noisy metadata
        _DROP_ATTRS = {
            "supported_features", "supported_color_modes", "effect_list",
            "min_mireds", "max_mireds", "min_color_temp_kelvin", "max_color_temp_kelvin",
            "hs_color", "xy_color",
            "icon", "entity_picture", "device_class", "state_class",
            "attribution", "assumed_state", "editable",
            "fan_modes", "swing_modes", "preset_modes", "hvac_modes",
            "source_list", "sound_mode_list",
        }
        attrs = {
            k: v for k, v in state.attributes.items()
            if k not in _DROP_ATTRS
        }
        return json.dumps({
            "entity_id": entity_id,
            "state": state.state,
            "attributes": attrs,
            "area_id": area_id,
            "area_name": area_name,
        })

    if name == "get_area_entities":
        area_query = call.get("area", "").strip().lower()
        if not area_query:
            return json.dumps({"error": "Missing 'area' argument"})
        areas = area_reg.async_list_areas()
        area_obj = next(
            (a for a in areas if a.id == area_query or a.name.lower() == area_query),
            None,
        )
        if not area_obj:
            return json.dumps({"error": f"Area '{area_query}' not found"})
        domain_filter = call.get("domain", "").strip().lower()
        results = {}
        for entry in entity_reg.entities.values():
            if entry.area_id != area_obj.id:
                continue
            if domain_filter and entry.entity_id.split(".")[0] != domain_filter:
                continue
            state = hass.states.get(entry.entity_id)
            if not _state_matches(state, state_filter):
                continue
            projection = _project_entity(entry.entity_id, state, entry)
            # Preserve legacy default 'domain' key when no explicit fields requested
            if fields_set is None:
                projection["domain"] = entry.entity_id.split(".")[0]
            results[entry.entity_id] = projection
        return json.dumps({"area": area_obj.name, "entities": results})

    if name == "list_entities_by_label":
        label_query = call.get("label", "").strip().lower()
        if not label_query:
            return json.dumps({"error": "Missing 'label' argument"})
        labels = label_reg.async_list_labels()
        label_obj = next(
            (lbl for lbl in labels if lbl.label_id == label_query or lbl.name.lower() == label_query),
            None,
        )
        if not label_obj:
            return json.dumps({"error": f"Label '{label_query}' not found"})
        results = {}
        for entry in entity_reg.entities.values():
            if label_obj.label_id not in (entry.labels or set()):
                continue
            state = hass.states.get(entry.entity_id)
            if not _state_matches(state, state_filter):
                continue
            results[entry.entity_id] = _project_entity(entry.entity_id, state, entry)
        return json.dumps({"label": label_obj.name, "entities": results})

    if name == "search_entities":
        query = call.get("query", "").strip().lower()
        if not query:
            return json.dumps({"error": "Missing 'query' argument"})
        results = {}
        for state in hass.states.async_all():
            friendly = state.attributes.get("friendly_name", "").lower()
            if not (query in state.entity_id.lower() or query in friendly):
                continue
            if not _state_matches(state, state_filter):
                continue
            projection = _project_entity(state.entity_id, state)
            if fields_set is None:
                projection["domain"] = state.entity_id.split(".")[0]
            results[state.entity_id] = projection
        return json.dumps(results or {"info": f"No entities matching '{query}'"})

    if name == "list_entities_without_area":
        domain_filter = call.get("domain", "").strip().lower()
        results = {}
        for entry in entity_reg.entities.values():
            if entry.area_id is not None:
                continue
            if domain_filter and entry.entity_id.split(".")[0] != domain_filter:
                continue
            state = hass.states.get(entry.entity_id)
            if not _state_matches(state, state_filter):
                continue
            projection = _project_entity(entry.entity_id, state, entry)
            if fields_set is None:
                projection["domain"] = entry.entity_id.split(".")[0]
            results[entry.entity_id] = projection
        return json.dumps(results or {"info": "All entities have an area assigned"})

    if name == "get_areas":
        areas = area_reg.async_list_areas()
        return json.dumps({a.id: a.name for a in areas})

    if name == "get_labels":
        labels = label_reg.async_list_labels()
        return json.dumps({lbl.label_id: lbl.name for lbl in labels})

    # ── Knowledge / memory tools ──────────────────────────────────────────
    # Searches the learned-knowledge store for relevant facts (area aliases,
    # entity notes, procedures, device chains). Use when the user uses a
    # name/term that doesn't match HA's registries, or when looking for
    # special handling instructions.
    if name == "search_knowledge":
        kstore = get_knowledge_store(hass)
        query = str(call.get("query", "")).strip()
        category = call.get("category")
        subject = str(call.get("subject", "")).strip()
        limit_arg = call.get("limit", 10)
        try:
            limit = max(1, min(50, int(limit_arg)))
        except (TypeError, ValueError):
            limit = 10
        # Caller must ensure store was loaded before; if not, return empty.
        if not kstore._loaded:
            return json.dumps({"entries": [], "_note": "knowledge store not yet loaded"})
        entries = kstore.search_sync(query=query, category=category, subject=subject, limit=limit)
        return json.dumps({"entries": entries, "count": len(entries)})

    if name == "get_entity_notes":
        kstore = get_knowledge_store(hass)
        eid = str(call.get("entity_id", "")).strip()
        if not eid:
            return json.dumps({"error": "Missing 'entity_id' argument"})
        if not kstore._loaded:
            return json.dumps({"entries": [], "_note": "knowledge store not yet loaded"})
        entries = kstore.get_for_entity_sync(eid)
        return json.dumps({"entity_id": eid, "entries": entries, "count": len(entries)})

    if name == "analyze_automations":
        # Scan existing automations/scenes/scripts for inferred relationships.
        # Read-only — returns proposed knowledge entries (not saved). The
        # model can then propose `add_knowledge` actions for ones it finds
        # useful, which the user approves.
        try:
            result = _analyze_automations(hass)
        except Exception as err:  # noqa: BLE001
            return json.dumps({"error": f"Analysis failed: {err}"})
        # Cap the proposals returned to the model — could be 100s of entries
        proposals = result.get("proposals", [])
        if len(proposals) > 30:
            proposals = proposals[:30]
            result["_truncated"] = True
            result["_total_proposals"] = len(result.get("proposals", []))
        result["proposals"] = proposals
        return json.dumps(result)

    # ── Automation / script / blueprint source readers ────────────────
    # Expose the *raw* YAML configs so the model can deeply reason about
    # trigger/condition/action structures (not just state attributes).
    if name == "list_automations":
        try:
            items = _src_read_automations(hass)
        except Exception as err:  # noqa: BLE001
            return json.dumps({"error": f"Read failed: {err}"})
        out = [{
            "id": it.get("id"),
            "alias": it.get("alias"),
            "mode": it.get("mode"),
            "num_triggers": it.get("num_triggers"),
            "num_actions": it.get("num_actions"),
            "description": it.get("description"),
        } for it in items]
        return json.dumps({"automations": out, "count": len(out)})

    if name == "get_automation":
        wanted = str(call.get("id") or call.get("alias") or call.get("entity_id") or "").strip()
        if not wanted:
            return json.dumps({"error": "Missing 'id' (or 'alias') argument"})
        try:
            items = _src_read_automations(hass)
        except Exception as err:  # noqa: BLE001
            return json.dumps({"error": f"Read failed: {err}"})
        # Match by id (exact), then alias (case-insensitive), then entity_id suffix
        match = None
        for it in items:
            if str(it.get("id", "")) == wanted:
                match = it
                break
        if not match:
            for it in items:
                if str(it.get("alias", "")).lower() == wanted.lower():
                    match = it
                    break
        if not match:
            # entity_id form: automation.<slug>
            slug = wanted.split(".", 1)[-1].lower()
            for it in items:
                a = str(it.get("alias", "")).lower().replace(" ", "_")
                if a == slug:
                    match = it
                    break
        if not match:
            return json.dumps({"error": f"Automation '{wanted}' not found"})
        return json.dumps(match, default=str)

    if name == "list_scripts":
        try:
            items = _src_read_scripts(hass)
        except Exception as err:  # noqa: BLE001
            return json.dumps({"error": f"Read failed: {err}"})
        out = [{
            "id": it.get("id"),
            "alias": it.get("alias"),
            "mode": it.get("mode"),
            "num_steps": it.get("num_steps"),
            "description": it.get("description"),
        } for it in items]
        return json.dumps({"scripts": out, "count": len(out)})

    if name == "get_script":
        wanted = str(call.get("id") or call.get("alias") or call.get("entity_id") or "").strip()
        if not wanted:
            return json.dumps({"error": "Missing 'id' (or 'alias') argument"})
        try:
            items = _src_read_scripts(hass)
        except Exception as err:  # noqa: BLE001
            return json.dumps({"error": f"Read failed: {err}"})
        match = None
        for it in items:
            if str(it.get("id", "")) == wanted:
                match = it
                break
        if not match:
            for it in items:
                if str(it.get("alias", "")).lower() == wanted.lower():
                    match = it
                    break
        if not match:
            slug = wanted.split(".", 1)[-1].lower()
            for it in items:
                if str(it.get("id", "")).lower() == slug:
                    match = it
                    break
        if not match:
            return json.dumps({"error": f"Script '{wanted}' not found"})
        return json.dumps(match, default=str)

    if name == "list_blueprints":
        try:
            items = _src_read_blueprints(hass)
        except Exception as err:  # noqa: BLE001
            return json.dumps({"error": f"Read failed: {err}"})
        return json.dumps({"blueprints": items, "count": len(items)})

    if name == "get_blueprint":
        path = str(call.get("path") or "").strip()
        if not path:
            return json.dumps({"error": "Missing 'path' argument"})
        try:
            data = _src_read_blueprint(hass, path)
        except Exception as err:  # noqa: BLE001
            return json.dumps({"error": f"Read failed: {err}"})
        return json.dumps(data, default=str)

    # call_service / assign_area / etc. are ACTIONS that belong in a plan
    # block, not [TOOL_CALL:]s. If the model tries to use them as a tool,
    # return a guidance error so it stops and emits a plan instead.
    _ACTION_AS_TOOL = {
        "call_service", "assign_area", "rename_entity", "assign_label",
        "turn_on", "turn_off", "toggle", "service_call",
        "create_area", "delete_area", "rename_area",
        "add_knowledge", "update_knowledge", "delete_knowledge",
    }
    if name in _ACTION_AS_TOOL:
        return json.dumps({
            "error": f"'{name}' is NOT a tool — it is an ACTION.",
            "guidance": (
                "STOP calling tools. You already have what you need. "
                "Emit a ```plan``` block with this action inside `actions`. "
                "Do not call any more tools."
            ),
        })

    valid_tools = [
        "list_entities_by_domain", "get_entity_state", "get_area_entities",
        "list_entities_by_label", "search_entities", "list_entities_without_area",
        "get_areas", "get_labels",
        "search_knowledge", "get_entity_notes", "analyze_automations",
        "list_automations", "get_automation",
        "list_scripts", "get_script",
        "list_blueprints", "get_blueprint",
    ]
    # If the bogus "tool" name looks like a word from a user request (e.g.
    # they typed "create an area outside" and the model called tool
    # `outside`), nudge the model towards emitting a plan instead of
    # retrying with another tool.
    hint = (
        "Retry with one of the valid tool names listed above. "
        "If your goal is to CREATE/RENAME/DELETE an area or to control "
        "entities, do NOT call a tool — emit a ```plan``` block with the "
        "appropriate action (`create_area`, `rename_area`, `delete_area`, "
        "`assign_area`, `call_service`, ...). For 'create an area X' just "
        "emit a plan with one `create_area` action where `name` is X."
    )
    return json.dumps({
        "error": f"Unknown tool '{name}'",
        "valid_tools": valid_tools,
        "hint": hint,
    })


def _parse_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract all [TOOL_CALL: {...}] blocks from a response."""
    calls = []
    for m in _TOOL_CALL_RE.finditer(text):
        try:
            calls.append(json.loads(m.group(1)))
        except (json.JSONDecodeError, ValueError):
            pass
    return calls


def _strip_tool_calls(text: str) -> str:
    """Remove [TOOL_CALL: ...] blocks from a response string."""
    return _TOOL_CALL_RE.sub("", text).strip()


def _extract_yaml_blocks(text: str) -> list[str]:
    """Extract YAML code blocks from a markdown response string."""
    return [match.group(1) for match in _YAML_BLOCK_RE.finditer(text)]


def _extract_plan_block(text: str) -> dict | None:
    """Extract the first ```plan``` JSON block from a response string."""
    match = _PLAN_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


_BARE_FENCE_RE = re.compile(r"```(?!plan|clarify|yaml|json)([a-z]*)\n([\s\S]+?)\n```", re.IGNORECASE)
_ACTION_TYPE_RE = re.compile(r'"type"\s*:\s*"(call_service|assign_area|rename_entity|create_\w+|update_\w+|delete_\w+|add_knowledge|update_knowledge|delete_knowledge|open_dashboard|open_editor)"')


def _rewrap_bare_action_fences(text: str) -> str:
    """Find bare ``` fences that contain a single JSON action object and
    merge them into a single ```plan``` block at the bottom of the response.

    The model occasionally emits each action in its own bare code fence
    instead of wrapping them in a ``` ```plan ``` ``` block, which prevents
    the frontend from showing the Execute button. We detect those, parse
    them, drop the bare fences, and append a real plan block.
    """
    if _PLAN_BLOCK_RE.search(text):
        return text  # already a real plan block
    actions: list[dict] = []
    leftover = text
    for m in _BARE_FENCE_RE.finditer(text):
        body = m.group(2).strip()
        if not _ACTION_TYPE_RE.search(body):
            continue
        # Try direct JSON parse, then fall back to wrapping with [] if it's a
        # comma-separated list, then to a {"actions":[...]} shape.
        parsed: Any = None
        for candidate in (body, f"[{body}]", "{\"actions\":[" + body + "]}"):
            try:
                parsed = json.loads(candidate)
                break
            except (json.JSONDecodeError, ValueError):
                continue
        if parsed is None:
            continue
        if isinstance(parsed, dict):
            if "actions" in parsed and isinstance(parsed["actions"], list):
                actions.extend([a for a in parsed["actions"] if isinstance(a, dict)])
            else:
                actions.append(parsed)
        elif isinstance(parsed, list):
            actions.extend([a for a in parsed if isinstance(a, dict)])
        # Drop the bare fence from the running text
        leftover = leftover.replace(m.group(0), "").strip()
    if not actions:
        return text
    plan = {"actions": actions}
    return leftover.rstrip() + "\n\n```plan\n" + json.dumps(plan, indent=2) + "\n```\n"


# Patterns for narrated/role-played tool calling the model occasionally
# emits as plain prose. Each is applied once on the response.
_NARRATION_PATTERNS = [
    # "For your request, I'll start by calling `list_entities_by_domain` for ..."
    re.compile(r"(?:^|\n)\s*(?:For your request,?\s*)?I(?:'ll| will) (?:start by )?call(?:ing)?\s+`?[a-z_]+`?[^.\n]*\.\s*", re.IGNORECASE),
    # "I'll call get_area_entities for the 'X' area:"
    re.compile(r"(?:^|\n)\s*I(?:'ll| will) call\s+`?[a-z_]+`?[^.\n:]*[.:]?\s*", re.IGNORECASE),
    # "The result will be: { ... }" (single line or with following JSON line)
    re.compile(r"(?:^|\n)\s*The result(?:s)? (?:will be|is|was)\s*:?\s*\{[^\n]*\}?\n?", re.IGNORECASE),
    # "Based on the result, I can see ..." / "Based on this result, ..."
    re.compile(r"(?:^|\n)\s*Based on (?:the|this) results?,?\s*[^\n]*\.\s*", re.IGNORECASE),
    # "After executing the tool call ..."
    re.compile(r"(?:^|\n)\s*After (?:executing|running|making) the (?:tool )?call[^\n]*\.\s*", re.IGNORECASE),
    # "Please let me know if this is what you were expecting." / "if this is acceptable."
    re.compile(r"(?:^|\n)\s*Please let me know if (?:this is what|this is acceptable|you would like|you want)[^\n]*\.\s*", re.IGNORECASE),
]


# Bare JSON-object lines like '{"area": "Werkkamer", "entities": {}}'
# that the model echoes back from tool results outside of any code fence.
_BARE_JSON_TOOL_RESULT_RE = re.compile(
    r"(?:^|\n)\s*\{(?:\"(?:area|entities|_truncated|_total_items|_returned_items|items|result|state|name)\"[^\n]*)\}\s*(?=\n|$)",
    re.IGNORECASE,
)


def _strip_role_echo_prefix(text: str) -> str:
    """Strip a leading 'User: ...\\nAssistant: ...' role-echo block that the
    model sometimes prepends. Handles a multi-line user line and an optional
    short assistant ack on the next line.
    """
    # Drop the leading "User: ..." line (up to first blank line or 'Assistant:')
    text = re.sub(
        r"\A\s*User:\s.*?(?=\n\s*Assistant:|\n\s*\n|\Z)",
        "",
        text,
        flags=re.DOTALL,
    ).lstrip()
    # Drop the next "Assistant: ..." line (single line; the real answer follows after a blank line)
    text = re.sub(
        r"\A\s*Assistant:\s.*?(?=\n\s*\n|\Z)",
        "",
        text,
        flags=re.DOTALL,
    ).lstrip()
    return text


_BRIGHTNESS_INTENT_RE = re.compile(
    r"\b(?:to\s+)?(?:max(?:imum)?|full(?:\s+brightness)?|brightest|100\s*%)\b",
    re.IGNORECASE,
)
_DIM_INTENT_RE = re.compile(r"\b(?:dim(?:med)?|low(?:est)?|min(?:imum)?|10\s*%)\b", re.IGNORECASE)


def _augment_brightness_intent(plan: dict | None, prompt: str) -> dict | None:
    """If the user asked for 'max'/'full'/'brightest' and the plan has
    ``light.turn_on`` actions without a brightness, inject
    ``brightness_pct: 100``. Likewise add ``brightness_pct: 10`` for 'dim'.
    """
    if not plan or not isinstance(plan, dict):
        return plan
    actions = plan.get("actions") or []
    if not isinstance(actions, list):
        return plan
    want_max = bool(_BRIGHTNESS_INTENT_RE.search(prompt or ""))
    want_dim = bool(_DIM_INTENT_RE.search(prompt or ""))
    if not (want_max or want_dim):
        return plan
    target_pct = 100 if want_max else 10
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "call_service":
            continue
        domain = (action.get("domain") or "").lower()
        service = (action.get("service") or "").lower()
        if domain != "light" or service != "turn_on":
            continue
        data = action.get("service_data") or action.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if any(k in data for k in ("brightness", "brightness_pct", "brightness_step", "brightness_step_pct")):
            continue
        data["brightness_pct"] = target_pct
        action["service_data"] = data
        # Update description if it doesn't already mention brightness
        desc = action.get("description", "")
        if "brightness" not in desc.lower() and "%" not in desc:
            action["description"] = (desc.rstrip(".") + f" at {target_pct}% brightness").strip()
    return plan


def _extract_clarify_block(text: str) -> dict | None:
    """Extract a ```clarify``` block where the model asks the user a question.

    Expected JSON shape:
        {"question": "...", "options": ["opt1", "opt2"], "context": "optional"}
    """
    match = _CLARIFY_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("question"):
        return None
    opts = data.get("options")
    if opts is not None and not isinstance(opts, list):
        opts = None
    return {
        "question": str(data["question"]),
        "options": [str(o) for o in (opts or [])],
        "context": str(data.get("context", "")),
    }


# Action types that change Home Assistant CONFIGURATION (registry/persistent
# data) and therefore must always require explicit user approval, even when
# autopilot is enabled. Runtime state changes (call_service turn_on/off) can
# auto-execute under autopilot; config changes cannot.
_CONFIG_CHANGING_ACTION_TYPES: set[str] = {
    "assign_area",
    "rename_entity",
    "assign_label",
    "remove_label",
    "create_area",
    "rename_area",
    "delete_area",
    "create_label",
    "rename_label",
    "delete_label",
    "create_automation",
    "update_automation",
    "delete_automation",
    "create_script",
    "update_script",
    "delete_script",
    "update_dashboard",
    "create_dashboard",
    "delete_dashboard",
    "add_knowledge",
    "update_knowledge",
    "delete_knowledge",
}

# Domain.service combinations that are considered DESTRUCTIVE runtime actions
# (locks, alarms, garage doors, etc.) and always require explicit approval.
_DESTRUCTIVE_SERVICES: set[tuple[str, str]] = {
    ("lock", "unlock"),
    ("alarm_control_panel", "alarm_disarm"),
    ("alarm_control_panel", "alarm_arm_away"),
    ("alarm_control_panel", "alarm_arm_home"),
    ("alarm_control_panel", "alarm_arm_night"),
    ("alarm_control_panel", "alarm_trigger"),
    ("cover", "open_cover"),
    ("cover", "close_cover"),
    ("vacuum", "start"),
    ("vacuum", "return_to_base"),
}


def _action_requires_approval(action: dict) -> bool:
    """Return True if this action must require explicit user approval.

    Config-changing actions (assign_area, rename_entity, area/label CRUD,
    automations, dashboards) always require approval. Destructive runtime
    services (unlock, disarm alarm, cover open/close) also require approval.
    Plain runtime state changes (light/switch turn_on/off, climate temp,
    media volume) can auto-execute under autopilot.
    """
    if not isinstance(action, dict):
        return False
    atype = str(action.get("type", "")).lower()
    if atype in _CONFIG_CHANGING_ACTION_TYPES:
        return True
    if atype == "call_service":
        domain = str(action.get("domain", "")).lower()
        service = str(action.get("service", "")).lower()
        if (domain, service) in _DESTRUCTIVE_SERVICES:
            return True
    return False


def _annotate_plan_approval(plan: dict | None) -> dict | None:
    """Mark each action with `requires_approval` and set `requires_approval`
    at the plan level if ANY action requires approval. The frontend must
    block autopilot auto-execute when `plan.requires_approval` is true.
    """
    if not isinstance(plan, dict):
        return plan
    actions = plan.get("actions")
    if not isinstance(actions, list):
        return plan
    any_requires = False
    for action in actions:
        if not isinstance(action, dict):
            continue
        needs = _action_requires_approval(action)
        action["requires_approval"] = needs
        if needs:
            any_requires = True
    plan["requires_approval"] = any_requires
    return plan


def _build_service_undo(domain: str, service: str, entity_id: str, pre_state: Any) -> dict | None:
    """Build an undo action for a service call using the captured pre-execution state."""
    if not entity_id or not pre_state:
        return None
    state = pre_state.state
    attrs = pre_state.attributes

    if service in ("turn_on", "toggle") and state == "off":
        return {"type": "call_service", "domain": domain, "service": "turn_off",
                "entity_id": entity_id, "current_state": "on", "new_state": "off",
                "description": f"Turn off {entity_id}"}
    if service in ("turn_off", "toggle") and state == "on":
        if domain == "light":
            svc_data: dict = {}
            if attrs.get("brightness"):
                svc_data["brightness"] = attrs["brightness"]
            if attrs.get("color_temp"):
                svc_data["color_temp"] = attrs["color_temp"]
            if attrs.get("rgb_color"):
                svc_data["rgb_color"] = list(attrs["rgb_color"])
            return {"type": "call_service", "domain": "light", "service": "turn_on",
                    "entity_id": entity_id, "service_data": svc_data,
                    "current_state": "off", "new_state": state,
                    "description": f"Restore {entity_id} to previous state"}
        return {"type": "call_service", "domain": domain, "service": "turn_on",
                "entity_id": entity_id, "current_state": "off", "new_state": "on",
                "description": f"Turn on {entity_id}"}
    if domain == "climate" and service == "set_temperature":
        old_temp = attrs.get("temperature")
        if old_temp is not None:
            return {"type": "call_service", "domain": "climate", "service": "set_temperature",
                    "entity_id": entity_id, "service_data": {"temperature": old_temp},
                    "current_state": str(old_temp), "new_state": str(old_temp),
                    "description": f"Restore {entity_id} temperature to {old_temp}"}
    if domain == "climate" and service == "set_hvac_mode":
        old_mode = attrs.get("hvac_mode") or state
        return {"type": "call_service", "domain": "climate", "service": "set_hvac_mode",
                "entity_id": entity_id, "service_data": {"hvac_mode": old_mode},
                "current_state": old_mode, "new_state": old_mode,
                "description": f"Restore {entity_id} HVAC mode to {old_mode}"}
    if domain == "cover" and service == "set_cover_position":
        old_pos = attrs.get("current_position")
        if old_pos is not None:
            return {"type": "call_service", "domain": "cover", "service": "set_cover_position",
                    "entity_id": entity_id, "service_data": {"position": old_pos},
                    "current_state": str(old_pos), "new_state": str(old_pos),
                    "description": f"Restore {entity_id} position to {old_pos}%"}
    if domain == "media_player" and service == "volume_set":
        old_vol = attrs.get("volume_level")
        if old_vol is not None:
            return {"type": "call_service", "domain": "media_player", "service": "volume_set",
                    "entity_id": entity_id, "service_data": {"volume_level": old_vol},
                    "current_state": str(old_vol), "new_state": str(old_vol),
                    "description": f"Restore {entity_id} volume to {old_vol}"}
    return None


def _sanitize_history(messages: Any) -> list[dict[str, str]]:
    """Normalize chat history payload to a safe, bounded list."""
    if not isinstance(messages, list):
        return []
    normalized: list[dict[str, str]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = "user" if msg.get("role") == "user" else "assistant"
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content[:_CHAT_MESSAGE_MAX_CHARS]})
    return normalized[-_CHAT_HISTORY_MAX_MESSAGES:]


def _sanitize_summary(summary: Any) -> str:
    """Normalize compacted summary to a bounded string."""
    return str(summary or "").strip()[:_CHAT_SUMMARY_MAX_CHARS]


async def _async_load_chat_store(hass: HomeAssistant) -> dict[str, Any]:
    """Load persisted chat history store, migrating old single-session format if needed."""
    store: Store[dict[str, Any]] = Store(hass, _CHAT_HISTORY_STORE_VERSION, _CHAT_HISTORY_STORE_KEY)
    data = await store.async_load()
    if not isinstance(data, dict):
        return {"users": {}}
    users = data.get("users")
    if not isinstance(users, dict):
        data["users"] = {}
        return data
    # Migrate users from old {history, compacted_summary} format to sessions format
    migrated = False
    for uid, udata in list(users.items()):
        if isinstance(udata, dict) and "sessions" not in udata and "history" in udata:
            users[uid] = _migrate_user_to_sessions(udata)
            migrated = True
    if migrated:
        await _async_save_chat_store(hass, data)
    return data


async def _async_save_chat_store(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Persist chat history store."""
    store: Store[dict[str, Any]] = Store(hass, _CHAT_HISTORY_STORE_VERSION, _CHAT_HISTORY_STORE_KEY)
    await store.async_save(data)


class KyberView(HomeAssistantView):
    """Handle POST /api/kyber/complete."""

    url = "/api/kyber/complete"
    name = "api:kyber:complete"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        """Store config entry data."""
        self._config = config

    async def post(self, request: web.Request) -> web.Response:
        """Handle an AI completion request from the frontend panel."""
        hass: HomeAssistant = request.app["hass"]
        import time as _time
        _turn_started_at = _time.time()

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        user_yaml: str = body.get("yaml", "")
        user_prompt: str = body.get("prompt", "").strip()
        history: list[dict] = body.get("history", [])
        compacted_summary: str = body.get("compacted_summary", "").strip()
        editor_mode: str = body.get("editor_mode", "automation")
        request_id: str = str(body.get("request_id", "")).strip()
        if not request_id:
            import uuid as _uuid
            request_id = _uuid.uuid4().hex[:12]
        # Per-turn log capture for the Debug bundle download.
        _debug_log_sink, _debug_log_handler = _debug_attach_log_capture(request_id)
        dashboards: list[dict] = body.get("dashboards", [])
        lovelace_resources: list[str] = body.get("lovelace_resources", [])

        if not user_prompt:
            _debug_detach_log_capture(_debug_log_handler)
            return self.json_message("Missing 'prompt' field", HTTPStatus.BAD_REQUEST)

        _LOGGER.debug(
            "Complete request — history messages: %d, has_summary: %s",
            len(history),
            bool(compacted_summary),
        )

        context, context_stats = _build_context(hass)

        # Dashboard list from frontend (may be empty list if fetch failed)
        dash_lines = ["- Overview (default) — url_path: (default)"]
        for d in (dashboards or []):
            title = d.get("title") or d.get("url_path", "?")
            url_path = d.get("url_path", "")
            mode = d.get("mode", "unknown")
            if url_path:  # skip entries with no url_path to avoid duplicating default
                dash_lines.append(f"- {title} — url_path: {url_path} — mode: {mode}")
        dashboard_section = "## Dashboards\n" + "\n".join(dash_lines) + "\n\n"

        # Custom Lovelace card resources
        if lovelace_resources:
            resource_lines = [f"- {url}" for url in lovelace_resources]
            dashboard_section += "## Custom card resources (installed via HACS or manually)\n" + "\n".join(resource_lines) + "\nWhen using custom cards use `type: custom:<card-name>` syntax.\n\n"

        # Current user info (always available — view requires auth)
        ha_user = request.get("hass_user")
        if ha_user:
            user_display = ha_user.name or ha_user.id
            user_role = "administrator" if ha_user.is_admin else "standard user"
            user_section = f"## Current user (the person you are talking to)\nYou are speaking with: {user_display} ({user_role})\n\n"
        else:
            user_section = ""

        if editor_mode == "dashboard":
            if user_yaml.strip():
                yaml_section = (
                    f"## ⚠️ DASHBOARD EDITOR IS CURRENTLY OPEN\n"
                    f"The user is actively editing the dashboard. The current YAML is shown below.\n"
                    f"**You MUST respond with a ```yaml block containing the FULL updated YAML — do NOT use a plan block or open_dashboard. "
                    f"The user will click Apply to update the editor.**\n\n"
                    f"```yaml\n{user_yaml}\n```\n\n"
                )
            else:
                yaml_section = (
                    "## ⚠️ DASHBOARD EDITOR IS CURRENTLY OPEN (empty/no config yet)\n"
                    "**You MUST respond with a ```yaml block containing the new full dashboard YAML — do NOT use a plan block or open_dashboard.**\n\n"
                )
        else:
            yaml_section = (
                f"## Current automation YAML\n```yaml\n{user_yaml}\n```\n\n"
                if user_yaml.strip()
                else ""
            )

        # Build conversation history block — placed right before the user message
        # so the model sees it as the most recent context.
        conversation_block = ""
        if compacted_summary or history:
            parts = []
            if compacted_summary:
                parts.append(f"[Earlier in this conversation]\n{compacted_summary}")
            if history:
                lines = []
                for msg in history:
                    role = msg.get("role", "user")
                    content = str(msg.get("content", "")).strip()
                    if content:
                        lines.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
                if lines:
                    parts.append("[Recent messages]\n" + "\n".join(lines))
            conversation_block = "\n\n".join(parts) + "\n\n"

        # Classify intent and inject mandatory response-mode constraint.
        # This prevents small models from generating plan blocks (e.g. open_editor)
        # for simple informational queries like "what lights do I have".
        intent = _classify_intent(user_prompt)
        response_mode_block = (
            _RESPONSE_MODE_INFORMATIONAL if intent == "informational"
            else _RESPONSE_MODE_ACTION
        )

        instructions = (
            f"{context}\n\n"
            f"{response_mode_block}"
            f"{user_section}"
            f"{dashboard_section}"
            f"{yaml_section}"
            f"---\n\n"
            f"{conversation_block}"
            f"User: {user_prompt}\n"
            f"Assistant:"
        )

        if len(instructions) > _BASE_INSTRUCTIONS_CHARS:
            _LOGGER.warning(
                "Kyber: instructions truncated from %d to %d chars to fit context window.",
                len(instructions),
                _BASE_INSTRUCTIONS_CHARS,
            )
            instructions = instructions[:_BASE_INSTRUCTIONS_CHARS]

        entity_id: str = self._config[CONF_AI_TASK_ENTITY_ID]

        # Load knowledge store and inject relevant entries into the instructions.
        kstore = get_knowledge_store(hass)
        await kstore.async_load()
        try:
            relevant_knowledge = await kstore.async_pick_relevant(user_prompt, max_entries=8)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber: knowledge lookup failed: %s", err)
            relevant_knowledge = []
        if relevant_knowledge:
            # Report which facts were selected so the user can see them in
            # the live progress card AND in the debug snapshot.
            picked_summary = ", ".join(
                f"{e.get('subject') or e.get('category','?')} (score {round(float(e.get('_score') or 0), 2)})"
                for e in relevant_knowledge[:5]
            )
            _LOGGER.info(
                "Kyber: injected %d memory facts via hybrid retrieval — %s",
                len(relevant_knowledge),
                picked_summary,
            )
            _progress_emit(hass, request_id, {
                "type": "info",
                "message": f"Recalled {len(relevant_knowledge)} memory fact(s): {picked_summary}",
            })
            kn_lines = ["", "## Learned knowledge (from previous interactions)"]
            kn_lines.append(
                "These facts were retrieved by hybrid semantic + keyword search; "
                "the most relevant ones for your current prompt come first. "
                "Use them when relevant; they override default assumptions. "
                "If a fact looks wrong, ask the user."
            )
            for entry in relevant_knowledge:
                cat = entry.get("category", "general")
                subj = entry.get("subject", "")
                content = entry.get("content", "")
                tags = ",".join(entry.get("tags", []) or [])
                score = entry.get("_score")
                src = entry.get("_source", "?")
                score_note = f" [match: {round(float(score), 2)} via {src}]" if score is not None else ""
                kn_lines.append(
                    f"- [{cat}]{(' '+subj) if subj else ''}: {content}"
                    + (f"  (tags: {tags})" if tags else "")
                    + score_note
                )
            instructions = instructions + "\n" + "\n".join(kn_lines) + "\n"
            await kstore.async_record_hit([e["id"] for e in relevant_knowledge])

        # Tool-calling loop — the AI may request live HA data via [TOOL_CALL: {...}]
        # We execute tools and re-send up to _TOOL_CALL_MAX_ROUNDS times.
        tool_exchange = ""  # accumulated tool call/result pairs appended to instructions
        tool_log: list[dict[str, Any]] = []  # summary of tool calls for UI feedback
        executed_calls_cache: dict[str, str] = {}  # signature → result str (dedup across rounds)
        response_text = ""
        _progress_emit(hass, request_id, {"type": "info", "message": f"Built context: {context_stats.get('entity_count', 0)} entities, {context_stats.get('area_count', 0)} areas"})

        # ── Quick-intent shortcut — skip the AI for trivially parseable requests
        # like "create an area outside". Small local models loop on get_areas
        # because every action example in the prompt has an entity_id; bypassing
        # the model entirely is far more reliable for these patterns.
        _skip_ai_loop = False
        _quick = _try_quick_intent(user_prompt)
        if _quick is not None:
            _LOGGER.info("Kyber: quick-intent shortcut hit (%s)", _quick.get("shortcut"))
            _progress_emit(hass, request_id, {
                "type": "info",
                "message": f"Quick-intent shortcut: {_quick.get('shortcut')}",
            })
            response_text = _quick["response_text"]
            intent = "action"  # quick intents are always actions; prevent informational guard from dropping the plan
            _skip_ai_loop = True

        for _round in range(0 if _skip_ai_loop else _TOOL_CALL_MAX_ROUNDS):
            loop_instructions = instructions + tool_exchange
            if len(loop_instructions) > _MAX_INSTRUCTIONS_CHARS:
                loop_instructions = loop_instructions[:_MAX_INSTRUCTIONS_CHARS]

            _progress_emit(hass, request_id, {
                "type": "info",
                "message": f"Asking AI (round {_round + 1})…",
            })
            try:
                result = await async_generate_data(
                    hass,
                    task_name=f"{DOMAIN}_complete",
                    entity_id=entity_id,
                    instructions=loop_instructions,
                )
            except HomeAssistantError as err:
                _LOGGER.error("AI task failed: %s", err)
                _progress_emit(hass, request_id, {"type": "error", "message": str(err)})
                _progress_complete(hass, request_id)
                return self.json_message(
                    f"AI provider error: {err}", HTTPStatus.SERVICE_UNAVAILABLE
                )

            response_text = result.data if isinstance(result.data, str) else str(result.data)
            tool_calls = _parse_tool_calls(response_text)

            # Also handle plan blocks where the AI put tool calls inside actions
            if not tool_calls:
                plan_for_tools = _extract_plan_block(response_text)
                if plan_for_tools and plan_for_tools.get("actions"):
                    _TOOL_CALL_TYPES = {
                        "list_entities_by_domain", "get_entity_state", "get_area_entities",
                        "list_entities_by_label", "search_entities", "get_areas", "get_labels",
                        "list_entities_without_area",
                    }
                    tool_calls = [
                        {**a, "name": a["type"]}
                        for a in plan_for_tools["actions"]
                        if a.get("type") in _TOOL_CALL_TYPES
                    ]
                    if tool_calls:
                        # Strip the plan block from response so it never reaches the frontend
                        response_text = _PLAN_BLOCK_RE.sub("", response_text).strip()

            if not tool_calls:
                break  # no tool calls — final answer

            # Dedup: within this round and against prior rounds.
            seen_signatures: set[str] = set()
            unique_calls = []
            for call in tool_calls:
                # Canonical signature: tool name + sorted args
                sig_dict = {k: v for k, v in call.items() if k != "name"}
                sig = json.dumps({"name": call.get("name", ""), "args": sig_dict}, sort_keys=True)
                if sig in seen_signatures:
                    _LOGGER.info("Kyber: skipping duplicate tool call %s", sig[:120])
                    continue
                seen_signatures.add(sig)
                unique_calls.append((sig, call))
            tool_calls_filtered = unique_calls

            # Execute tools and build result block
            clean_response = _strip_tool_calls(response_text)
            tool_results_block = ""
            # Cap each tool result fed back to the model to keep context small.
            # Small models (8K window) choke on huge JSON payloads and forget
            # to continue. Truncate at ~6KB with a note.
            _MAX_TOOL_RESULT_CHARS = 6000
            new_call_count = 0

            # Emit tool_call progress events upfront, then execute uncached calls
            # in parallel via the HA executor. Read-only tools (list_*, get_*) are
            # safe to fan out; mutating actions go through plan blocks, not tools.
            for sig, call in tool_calls_filtered:
                _progress_emit(hass, request_id, {
                    "type": "tool_call",
                    "name": call.get("name", ""),
                    "args": {k: v for k, v in call.items() if k != "name"},
                })

            async def _run_one_tool(sig: str, call: dict) -> tuple[str, dict, str]:
                if sig in executed_calls_cache:
                    return sig, call, executed_calls_cache[sig]
                result = await hass.async_add_executor_job(_execute_tool, hass, call)
                return sig, call, result

            tool_results_parallel = await asyncio.gather(
                *[_run_one_tool(s, c) for s, c in tool_calls_filtered],
                return_exceptions=True,
            )

            for idx, item in enumerate(tool_results_parallel):
                sig_call = tool_calls_filtered[idx]
                sig, call = sig_call
                if isinstance(item, BaseException):
                    _LOGGER.warning("Kyber: tool %s raised %s", call.get("name"), item)
                    tool_result_str = json.dumps({"error": str(item)})
                else:
                    _, _, tool_result_str = item
                    if sig not in executed_calls_cache:
                        executed_calls_cache[sig] = tool_result_str
                        new_call_count += 1
                try:
                    tool_result_data = json.loads(tool_result_str)
                except json.JSONDecodeError:
                    tool_result_data = {"error": "invalid_json", "raw": tool_result_str[:200]}
                _LOGGER.debug("Tool call %s → %s chars", call.get("name"), len(tool_result_str))

                # Build a short human-readable summary for the UI
                summary = _tool_result_summary(call, tool_result_data)
                args_display = {k: v for k, v in call.items() if k != "name"}
                tool_log.append({
                    "name": call.get("name", ""),
                    "args": args_display,
                    "summary": summary,
                })
                # Build a short preview of the result for the live UI
                preview = tool_result_str
                if len(preview) > 400:
                    preview = preview[:400] + "…"
                _progress_emit(hass, request_id, {
                    "type": "tool_result",
                    "name": call.get("name", ""),
                    "summary": summary,
                    "preview": preview,
                })

                # Truncate the version sent BACK to the model (UI summary above is unaffected)
                feedback_str = tool_result_str
                if len(feedback_str) > _MAX_TOOL_RESULT_CHARS:
                    if isinstance(tool_result_data, dict) and len(tool_result_data) > 1:
                        items = list(tool_result_data.items())
                        kept: dict = {}
                        running = 0
                        for k, v in items:
                            piece = json.dumps({k: v})
                            if running + len(piece) > _MAX_TOOL_RESULT_CHARS:
                                break
                            kept[k] = v
                            running += len(piece) + 2
                        omitted = len(items) - len(kept)
                        feedback_str = json.dumps({
                            "_truncated": True,
                            "_total_items": len(items),
                            "_returned_items": len(kept),
                            "_note": f"{omitted} more items omitted. Use a more specific filter (state, domain, area) to narrow results.",
                            "items": kept,
                        })
                    else:
                        feedback_str = feedback_str[:_MAX_TOOL_RESULT_CHARS] + '..."[TRUNCATED]"}'
                    _LOGGER.info(
                        "Kyber: truncated tool result %s from %d → %d chars",
                        call.get("name"), len(tool_result_str), len(feedback_str),
                    )

                tool_results_block += (
                    f"\n[TOOL_RESULT: {json.dumps(call)}]\n{feedback_str}\n"
                )
            tool_exchange += f"{clean_response}\n{tool_results_block}\nAssistant:"
            _progress_emit(hass, request_id, {"type": "thinking", "stage": "follow_up"})

            # Stop early if model is looping (every call was a duplicate)
            if new_call_count == 0:
                _LOGGER.info("Kyber: all tool calls in round were duplicates; stopping loop")
                _progress_emit(hass, request_id, {
                    "type": "info",
                    "message": "Model repeated previous tool calls — synthesizing answer from results.",
                })
                # The model looped instead of answering in prose. Do one final
                # synthesis pass with no tool-calling instructions so it turns
                # the collected data into a natural-language response.
                if not _strip_tool_calls(response_text).strip() and tool_exchange:
                    synth_prompt = instructions + tool_exchange + _SYNTHESIS_INSTRUCTIONS
                    if len(synth_prompt) > _MAX_INSTRUCTIONS_CHARS:
                        synth_prompt = synth_prompt[:_MAX_INSTRUCTIONS_CHARS]
                    try:
                        _progress_emit(hass, request_id, {"type": "thinking", "stage": "synthesize"})
                        synth_result = await async_generate_data(
                            hass,
                            task_name=f"{DOMAIN}_complete",
                            entity_id=entity_id,
                            instructions=synth_prompt,
                        )
                        synth_text = (
                            synth_result.data
                            if isinstance(synth_result.data, str)
                            else str(synth_result.data)
                        )
                        synth_text = _strip_tool_calls(synth_text).strip()
                        if synth_text:
                            response_text = synth_text
                    except Exception as _synth_err:  # noqa: BLE001
                        _LOGGER.warning("Kyber: synthesis pass failed: %s", _synth_err)
                # Final guard: if synthesis also produced nothing, show a helpful message.
                if not _strip_tool_calls(response_text).strip():
                    response_text = (
                        "I wasn't able to figure out the right action for that "
                        "request — could you rephrase or be more specific?"
                    )
                break

        # Strip leading "User: ...\nAssistant: ..." echo block before parsing.
        response_text = _strip_role_echo_prefix(response_text)
        # Rewrap bare ``` JSON action fences as a ```plan``` block so the
        # frontend can render an Execute button. This MUST run before plan extraction.
        response_text = _rewrap_bare_action_fences(response_text)

        yaml_blocks = _extract_yaml_blocks(response_text)
        plan_block = _extract_plan_block(response_text)
        # Honour brightness intent ("max" / "full" / "dim" / "100%") by
        # injecting brightness_pct on light.turn_on actions.
        plan_block = _augment_brightness_intent(plan_block, user_prompt)
        clarify_block = _extract_clarify_block(response_text)

        # Remove the raw clarify code block from the displayed response; UI renders it.
        if clarify_block:
            response_text = _CLARIFY_BLOCK_RE.sub("", response_text).strip()

        # Strip any [TOOL_RESULT: ...] or [T00L_RESULT: ...] lines the model echoed back.
        response_text = _TOOL_RESULT_STRIP_RE.sub("", response_text).strip()
        # Also strip multi-line [TOOL_RESULT: ...] payloads (block form)
        response_text = re.sub(
            r"\[T[O0]{2}L[_\-]RESULT:[^\]]*\][^\n]*\n(?:.*?\n)*?(?=\n[A-Z]|\n\n|\Z)",
            "",
            response_text,
            flags=re.IGNORECASE,
        ).strip()

        # Strip any unparsed [TOOL_CALL: ...] / [T00L_CALL: ...] from the final response.
        response_text = _TOOL_CALL_RE.sub("", response_text).strip()

        # Strip "User: ..." and "Assistant:" turn echoes (anywhere, not just at start)
        response_text = re.sub(r"^\s*User:\s.*?(?=\n\n|\Z)", "", response_text, flags=re.DOTALL).strip()
        response_text = re.sub(r"^\s*Assistant:\s*", "", response_text, flags=re.MULTILINE).strip()

        # Strip narrated/role-played tool calls and "Based on the result..." fluff.
        for pattern in _NARRATION_PATTERNS:
            response_text = pattern.sub("\n", response_text)
        # Collapse blank lines left by narration scrubbing
        response_text = re.sub(r"\n{3,}", "\n\n", response_text).strip()

        # Strip bare JSON tool-result lines (e.g. {"area": "X", "entities": {...}})
        # that the model echoed inline outside of any code fence.
        response_text = _BARE_JSON_TOOL_RESULT_RE.sub("\n", response_text)
        response_text = re.sub(r"\n{3,}", "\n\n", response_text).strip()

        # Strip leftover bare JSON-result lines (e.g. {"_truncated": true, ...} or {"light.X": ...})
        # that escaped the [TOOL_RESULT:] wrapper.
        response_text = re.sub(
            r"^\s*\{\"(?:_truncated|light\.|switch\.|sensor\.|result)[^\n]+\}\s*$",
            "",
            response_text,
            flags=re.MULTILINE,
        ).strip()

        # Strip [SYSTEM: ...] / [END SYSTEM] blocks the model echoed back.
        response_text = re.sub(r"\[SYSTEM:[^\]]*?\].*?\[END SYSTEM\]\s*", "", response_text, flags=re.DOTALL).strip()
        response_text = re.sub(r"<<RULES:.*?>>.*?<</RULES>>\s*", "", response_text, flags=re.DOTALL).strip()

        # Strip common model preamble and narration patterns (applied left-to-right, each once).
        _PREAMBLE_PATTERNS = [
            # "I'm happy to help!" / "I'm here to help!"
            re.compile(r"^I'?m (happy|here) to help[^.!]*[.!]?\s*", re.IGNORECASE),
            # "Since this is an INFORMATIONAL query..."
            re.compile(r"^Since this is an? (INFORMATIONAL|ACTION)[^.]*\.\s*", re.IGNORECASE),
            # "Since the user asked about X, I'll output a tool call..."
            re.compile(r"^Since the user (asked|is asking)[^.]*\.\s*", re.IGNORECASE),
            # "I'll respond in plain text and use tool calls if needed."
            re.compile(r"^I('ll| will) (respond in plain text|use tool calls?)[^.]*\.\s*", re.IGNORECASE),
            # "To get the IDs of all X, I'll need to execute some tool calls."
            re.compile(r"^To (get|find|retrieve)[^,]+,\s*I('ll| will) need to (execute|call|run)[^.]+\.\s*", re.IGNORECASE),
            # "Here are the results:" / "Here's my response:"
            re.compile(r"^Here (are the results|is my response|are the (presence|motion|light)[^:]*):?\s*", re.IGNORECASE),
            # "After executing the tool call, I found that..."
            re.compile(r"^After (executing|running) the tool call[^,]*,\s*", re.IGNORECASE),
            # "Let me call some tools to get more information..."
            re.compile(r"^Let me (call|use|run) (some |a )?tools?[^.]*\.\s*", re.IGNORECASE),
            # "According to the current state of the house,"
            re.compile(r"^According to the (current state|context)[^,]*,\s*", re.IGNORECASE),
        ]
        for pattern in _PREAMBLE_PATTERNS:
            response_text = pattern.sub("", response_text).strip()

        # Strip model footer noise (end of response).
        _FOOTER_PATTERNS = [
            re.compile(r"\s*Please (let me know|note)[^.!?]*[.!?]\s*$", re.IGNORECASE),
            re.compile(r"\s*Just let me know[.!]?\s*$", re.IGNORECASE),
            re.compile(r"\s*What would you like to do\?\s*$", re.IGNORECASE),
            re.compile(r"\s*Can I help you with anything else\?\s*$", re.IGNORECASE),
            re.compile(r"\s*Let me know if you (need|have|want|would like)[^.!?]*[.!?]?\s*$", re.IGNORECASE),
            re.compile(r"\s*Is there anything else[^?]*\?\s*$", re.IGNORECASE),
        ]
        for pattern in _FOOTER_PATTERNS:
            response_text = pattern.sub("", response_text).strip()

        # Guard: if intent was informational and the model still hallucinated an
        # open_editor or open_dashboard plan, drop it.
        # Also drop create/delete/update action plans for informational queries
        # (e.g. "what areas do I have" should never become "create_area outside").
        if intent == "informational" and plan_block:
            has_editor = plan_block.get("open_editor") or plan_block.get("open_dashboard")
            mutating_action_types = {
                "create_area", "delete_area", "rename_entity", "assign_area",
                "assign_label", "call_service", "update_knowledge", "add_knowledge",
                "delete_knowledge",
            }
            actions = plan_block.get("actions", [])
            has_mutating = any(a.get("type") in mutating_action_types for a in actions)
            if has_editor or has_mutating:
                _LOGGER.warning(
                    "Kyber: dropping spurious action plan for informational query: %r (types: %s)",
                    user_prompt[:80],
                    [a.get("type") for a in actions],
                )
                plan_block = None

        # Rescue: if the model used open_editor with a non-automation/script entity
        # (e.g. light.*, switch.*), convert to a call_service actions plan.
        if plan_block and plan_block.get("open_editor"):
            aid = plan_block.get("automation_id", "")
            entity_domain = aid.split(".")[0] if "." in aid else ""
            if entity_domain and entity_domain not in ("automation", "script"):
                summary_lower = plan_block.get("summary", "").lower()
                prompt_lower = user_prompt.lower()
                # Infer service from summary / original prompt
                if any(w in summary_lower or w in prompt_lower for w in ("turn off", "switch off", "zet uit", "off")):
                    service = "turn_off"
                    new_state = "off"
                    current_state = "on"
                elif any(w in summary_lower or w in prompt_lower for w in ("turn on", "switch on", "zet aan", "on")):
                    service = "turn_on"
                    new_state = "on"
                    current_state = "off"
                elif any(w in summary_lower or w in prompt_lower for w in ("toggle")):
                    service = "toggle"
                    new_state = "toggled"
                    current_state = ""
                else:
                    service = None

                if service and aid:
                    _LOGGER.info(
                        "Kyber: rescued open_editor plan for %s → call_service %s.%s",
                        aid, entity_domain, service,
                    )
                    plan_block = {
                        "summary": plan_block.get("summary", f"{service} {aid}"),
                        "actions": [{
                            "type": "call_service",
                            "domain": entity_domain,
                            "service": service,
                            "entity_id": aid,
                            "description": plan_block.get("summary", ""),
                            "current_state": current_state,
                            "new_state": new_state,
                        }],
                    }
                else:
                    _LOGGER.warning(
                        "Kyber: dropping open_editor plan for non-automation entity %r (cannot infer service)",
                        aid,
                    )
                    plan_block = None

        # Plan auto-resolution: when a plan references an entity_id that does
        # not exist (e.g. `light.werkkamer`) but the local part matches an area
        # name, expand to the REAL entities in that area for the requested
        # domain. This rescues small models that skip the area lookup tool.
        if plan_block and isinstance(plan_block.get("actions"), list):
            try:
                area_reg = ar.async_get(hass)
                entity_reg = er.async_get(hass)
                # Build lookup: lowercase area-name → area_id
                area_by_name: dict[str, str] = {}
                for a in area_reg.async_list_areas():
                    area_by_name[a.name.lower()] = a.id
                    area_by_name[a.id.lower()] = a.id
                # Build lookup: area_id → list of entity_ids
                entities_by_area: dict[str, list[str]] = {}
                for entry in entity_reg.entities.values():
                    if entry.area_id:
                        entities_by_area.setdefault(entry.area_id, []).append(entry.entity_id)

                new_actions: list[dict] = []
                resolved_any = False
                for action in plan_block["actions"]:
                    if not isinstance(action, dict):
                        new_actions.append(action)
                        continue
                    eid = action.get("entity_id", "")
                    if not eid or "." not in eid:
                        new_actions.append(action)
                        continue
                    if hass.states.get(eid):
                        new_actions.append(action)
                        continue
                    # Bogus entity_id — try to resolve `<domain>.<area>` → area
                    domain, _, local = eid.partition(".")
                    candidate = local.replace("_", " ").lower()
                    area_id = area_by_name.get(candidate) or area_by_name.get(local.lower())
                    real_ids: list[str] = []
                    if area_id:
                        real_ids = [
                            e for e in entities_by_area.get(area_id, [])
                            if e.split(".")[0] == domain and hass.states.get(e)
                        ]
                    if not real_ids:
                        # Fallback: name-hint matching — find entities of the
                        # right domain whose id or friendly_name contains the
                        # candidate token. Useful when areas aren't configured.
                        tokens = [t for t in re.split(r"[\s_\-]+", candidate) if t]
                        if tokens:
                            hint_matches: list[str] = []
                            for st in hass.states.async_all():
                                if st.entity_id.split(".")[0] != domain:
                                    continue
                                hay = (
                                    st.entity_id.lower()
                                    + " "
                                    + str(st.attributes.get("friendly_name", "")).lower()
                                )
                                if all(t in hay for t in tokens):
                                    hint_matches.append(st.entity_id)
                            real_ids = hint_matches
                    if not real_ids:
                        new_actions.append(action)
                        continue
                    _LOGGER.info(
                        "Kyber: resolved bogus entity %r → %d real %s entities",
                        eid, len(real_ids), domain,
                    )
                    resolved_any = True
                    for real_id in real_ids:
                        rs = hass.states.get(real_id)
                        new_actions.append({
                            **action,
                            "entity_id": real_id,
                            "current_state": rs.state if rs else action.get("current_state", ""),
                        })
                if resolved_any:
                    plan_block["actions"] = new_actions
            except Exception as err:  # pragma: no cover - best effort
                _LOGGER.debug("Kyber: plan auto-resolve failed: %s", err)

        # Detect hallucinated entity IDs: if no tool was called but the response
        # contains entity-id patterns (domain.name), check them against HA state.
        # If none match real states, append a warning so the user knows.
        # Skip the warning when we already produced a plan with verified IDs
        # (auto-resolution above will have fixed any bogus IDs).
        plan_has_verified_ids = False
        if plan_block and isinstance(plan_block.get("actions"), list):
            plan_has_verified_ids = any(
                isinstance(a, dict) and a.get("entity_id") and hass.states.get(a["entity_id"])
                for a in plan_block["actions"]
            )
        if not tool_log and not plan_has_verified_ids:
            _ENTITY_ID_RE = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")
            candidate_ids = _ENTITY_ID_RE.findall(response_text)
            if candidate_ids:
                fake_ids = [
                    eid for eid in candidate_ids
                    if "." in eid and not hass.states.get(eid)
                    and eid.split(".")[0] in (
                        "light", "switch", "sensor", "binary_sensor",
                        "climate", "cover", "media_player", "person",
                    )
                ]
                if fake_ids:
                    _LOGGER.warning(
                        "Kyber: response may contain fabricated entity IDs (not in HA state): %s",
                        fake_ids[:5],
                    )
                    response_text += (
                        "\n\n⚠️ *Note: I couldn't verify these entity IDs against your Home Assistant. "
                        "They may be incorrect — ask me to search for them to get real IDs.*"
                    )

        _progress_complete(hass, request_id)
        plan_block = _annotate_plan_approval(plan_block)
        # Auto-rate: detect negative cues in the response and auto-flag any
        # knowledge entries that were injected this turn. The user can
        # override via the 👍/👎 buttons on the message.
        knowledge_used_ids = [e["id"] for e in (relevant_knowledge or [])]
        auto_rating: int | None = None
        if knowledge_used_ids:
            low = (response_text or "").lower()
            negative_cues = (
                "i couldn't find", "couldn't find", "no entities found",
                "i don't know", "i'm not sure", "unable to find",
                "no matching", "doesn't exist", "i can't find",
            )
            if any(c in low for c in negative_cues):
                try:
                    await kstore.async_apply_feedback(
                        knowledge_used_ids,
                        rating=2,
                        notes="auto: response contained negative cue",
                        auto=True,
                    )
                    auto_rating = 2
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Kyber: auto-rate failed: %s", err)
        # Capture a debug snapshot for the in-panel debug tab.
        try:
            _progress_store = hass.data.get(_PROGRESS_KEY) or {}
            _progress_entry = _progress_store.get(request_id) or {}
            _debug_record_turn(
                hass,
                request_id=request_id,
                user_prompt=user_prompt,
                expanded_prompt=instructions,
                instructions_used=loop_instructions if 'loop_instructions' in locals() else instructions,
                picked_knowledge=[
                    {
                        "id": e.get("id"),
                        "category": e.get("category"),
                        "subject": e.get("subject"),
                        "content": e.get("content"),
                        "confidence": e.get("confidence"),
                        "user_rating": e.get("user_rating"),
                        "needs_review": e.get("needs_review"),
                        "provenance": e.get("provenance"),
                        "score": e.get("_score"),
                    }
                    for e in (relevant_knowledge or [])
                ],
                tool_log=tool_log,
                intent=intent,
                response_text=response_text,
                auto_rating=auto_rating,
                elapsed_ms=int((_time.time() - _turn_started_at) * 1000),
                logs=_debug_log_sink or [],
                progress_events=list(_progress_entry.get("events") or []),
                session_meta={
                    "history_messages": len(history),
                    "had_summary": bool(compacted_summary),
                    "editor_mode": editor_mode,
                    "context_stats": context_stats,
                },
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Kyber: debug snapshot capture failed: %s", err)
        finally:
            _debug_detach_log_capture(_debug_log_handler)
        return self.json({
            "response": response_text,
            "yaml_blocks": yaml_blocks,
            "plan": plan_block,
            "clarify": clarify_block,
            "context_stats": context_stats,
            "tool_log": tool_log,
            "knowledge_used": knowledge_used_ids,
            "auto_rating": auto_rating,
            "request_id": request_id,
        })


class KyberProgressView(HomeAssistantView):
    """Return progress events for an in-flight chat request."""

    url = "/api/kyber/progress"
    name = "api:kyber:progress"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        request_id = request.query.get("id", "").strip()
        since = int(request.query.get("since", "0") or 0)
        if not request_id:
            return self.json({"events": [], "status": "unknown", "next": 0})
        store: dict = hass.data.get(_PROGRESS_KEY, {})
        entry = store.get(request_id)
        if not entry:
            return self.json({"events": [], "status": "unknown", "next": 0})
        events = entry.get("events", [])
        new_events = events[since:]
        return self.json({
            "events": new_events,
            "status": entry.get("status", "running"),
            "next": len(events),
        })


class KyberKnowledgeView(HomeAssistantView):
    """CRUD endpoint for learned knowledge entries.

    GET    /api/kyber/knowledge            → list all
    GET    /api/kyber/knowledge?q=...      → search
    POST   /api/kyber/knowledge            → add (body: category, content, ...)
    DELETE /api/kyber/knowledge?id=ENTRYID → delete
    """

    url = "/api/kyber/knowledge"
    name = "api:kyber:knowledge"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        q = request.query.get("q", "").strip()
        category = request.query.get("category", "").strip() or None
        subject = request.query.get("subject", "").strip()
        try:
            limit = max(1, min(500, int(request.query.get("limit", "200"))))
        except ValueError:
            limit = 200
        if q or category or subject:
            entries = await kstore.async_search(query=q, category=category, subject=subject, limit=limit)
        else:
            entries = await kstore.async_all()
        needs_review = request.query.get("needs_review", "").strip().lower()
        if needs_review in ("1", "true", "yes"):
            entries = [e for e in entries if e.get("needs_review")]
        return self.json({
            "entries": entries,
            "count": len(entries),
            "categories": sorted(KNOWLEDGE_CATEGORIES),
            "needs_review_count": sum(1 for e in await kstore.async_all() if e.get("needs_review")),
        })

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        # Update vs create
        entry_id = body.get("id") or body.get("entry_id")
        if entry_id:
            # Rating-only update is allowed even without content
            changes = {k: v for k, v in body.items()
                       if k in ("category", "subject", "content", "tags",
                                "confidence", "source", "provenance",
                                "user_rating", "needs_review")}
            updated = await kstore.async_update(str(entry_id), **changes)
            if not updated:
                return self.json_message(f"Entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
            return self.json({"status": "ok", "entry": updated})
        content = str(body.get("content", "")).strip()
        if not content:
            return self.json_message("Missing 'content' field", HTTPStatus.BAD_REQUEST)
        entry = await kstore.async_add(
            category=str(body.get("category", "general")),
            content=content,
            subject=str(body.get("subject", "")),
            tags=list(body.get("tags", []) or []),
            source=str(body.get("source", "user")),
            confidence=float(body.get("confidence", 1.0)),
            provenance=str(body.get("provenance", "Added manually by user")),
            user_rating=int(body.get("user_rating", 0)),
        )
        return self.json({"status": "ok", "entry": entry})

    async def delete(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        entry_id = request.query.get("id", "").strip()
        if not entry_id:
            return self.json_message("Missing 'id' query parameter", HTTPStatus.BAD_REQUEST)
        ok = await kstore.async_delete(entry_id)
        if not ok:
            return self.json_message(f"Entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
        return self.json({"status": "ok"})


class KyberKnowledgeAnalyzeView(HomeAssistantView):
    """Run the automation/scene/script analyzer and return inferred proposals.

    GET  /api/kyber/knowledge/analyze         → return proposals (not saved)
    POST /api/kyber/knowledge/analyze         → body: {entry_indices: [...], save: true}
                                                save selected proposals
    """

    url = "/api/kyber/knowledge/analyze"
    name = "api:kyber:knowledge:analyze"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        result = _analyze_automations(hass)
        return self.json(result)

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        proposals = body.get("proposals") or []
        if not isinstance(proposals, list):
            return self.json_message("Field 'proposals' must be a list", HTTPStatus.BAD_REQUEST)
        saved = []
        for p in proposals:
            if not isinstance(p, dict) or not p.get("content"):
                continue
            entry = await kstore.async_add(
                category=str(p.get("category", "general")),
                content=str(p.get("content", "")),
                subject=str(p.get("subject", "")),
                tags=list(p.get("tags", []) or []),
                source=str(p.get("source", "inferred")),
                confidence=float(p.get("confidence", 0.5)),
                provenance=str(p.get("provenance", "Inferred from automation/scene/script analysis")),
            )
            saved.append(entry["id"])
        return self.json({"status": "ok", "saved": saved, "count": len(saved)})


class KyberKnowledgeDeepAnalyzeView(HomeAssistantView):
    """AI-driven deep analyzer for automations / scripts / blueprints.

    Each item is hashed; unchanged items are skipped. Up to `limit` changed
    items are sent to the AI per run, which proposes durable facts about
    the home that the item implies. Accepted facts are saved into the
    KnowledgeStore tagged with `deep:<kind>` + `src:<ident>`.

    GET  /api/kyber/knowledge/analyze_deep        → memo status (what's been analyzed)
    POST /api/kyber/knowledge/analyze_deep        → run a sweep
       body: {kinds?: ["automation","script","blueprint"],
              limit?: int = 5,
              force?: bool = false}
    """

    url = "/api/kyber/knowledge/analyze_deep"
    name = "api:kyber:knowledge:analyze_deep"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        status = await _deep.memo_status(hass)
        return self.json(status)

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        ai_entity_id: str = self._config.get(CONF_AI_TASK_ENTITY_ID, "")
        if not ai_entity_id:
            return self.json_message("AI task entity not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        kinds = body.get("kinds") or ["automation", "script", "blueprint"]
        if not isinstance(kinds, list):
            kinds = ["automation", "script", "blueprint"]
        try:
            limit = int(body.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(50, limit))
        force = bool(body.get("force", False))
        try:
            result = await _deep.analyze_pending(
                hass,
                ai_entity_id=ai_entity_id,
                kinds=kinds,
                limit=limit,
                force=force,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Kyber deep_analyzer: unexpected error: %s", err, exc_info=True)
            return self.json_message(f"Deep analyze error: {err}", HTTPStatus.INTERNAL_SERVER_ERROR)
        try:
            return self.json({"status": "ok", **result})
        except Exception as ser_err:  # noqa: BLE001
            _LOGGER.error("Kyber deep_analyzer: JSON serialization failed: %s", ser_err, exc_info=True)
            # Return a safe minimal response so the frontend doesn't get a 500 text body
            return self.json({
                "status": "ok",
                "analyzed": [],
                "skipped_unchanged": result.get("skipped_unchanged", 0),
                "errors": [{"kind": "?", "ident": "?", "error": f"serialization error: {ser_err}"}],
                "candidates_total": result.get("candidates_total", 0),
                "processed": result.get("processed", 0),
                "limit": result.get("limit", limit),
            })



class KyberKnowledgeFeedbackView(HomeAssistantView):
    """Record user (or auto) feedback on a chat response, applied to the
    knowledge entries that were injected into that turn's context.

    POST /api/kyber/knowledge/feedback
      body: {rating: 1-5, knowledge_ids: [...], notes?, auto?}
    """

    url = "/api/kyber/knowledge/feedback"
    name = "api:kyber:knowledge:feedback"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        try:
            rating = int(body.get("rating", 0))
        except (TypeError, ValueError):
            return self.json_message("'rating' must be 1-5", HTTPStatus.BAD_REQUEST)
        if rating < 1 or rating > 5:
            return self.json_message("'rating' must be 1-5", HTTPStatus.BAD_REQUEST)
        ids = body.get("knowledge_ids") or []
        if not isinstance(ids, list):
            return self.json_message("'knowledge_ids' must be a list", HTTPStatus.BAD_REQUEST)
        notes = str(body.get("notes", ""))[:200]
        auto = bool(body.get("auto", False))
        updated = await kstore.async_apply_feedback(
            [str(i) for i in ids if i],
            rating=rating,
            notes=notes,
            auto=auto,
        )
        return self.json({
            "status": "ok",
            "updated": [e["id"] for e in updated],
            "count": len(updated),
        })


class KyberDebugLastTurnView(HomeAssistantView):
    """Return the most recent turn's debug snapshot (in-memory only).

    GET /api/kyber/debug/last_turn → {prompt, picked_knowledge, tool_log, ...}
    """

    url = "/api/kyber/debug/last_turn"
    name = "api:kyber:debug:last_turn"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        snap = hass.data.get(_DEBUG_LAST_TURN_KEY)
        if not snap:
            return self.json({"snapshot": None})
        return self.json({"snapshot": snap})


class KyberDebugToolHistoryView(HomeAssistantView):
    """Return the in-memory ring buffer of recent tool calls."""

    url = "/api/kyber/debug/tool_history"
    name = "api:kyber:debug:tool_history"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        history = hass.data.get(_DEBUG_TOOL_HISTORY_KEY)
        try:
            limit = max(1, min(_DEBUG_TOOL_HISTORY_MAX, int(request.query.get("limit", _DEBUG_TOOL_HISTORY_MAX))))
        except ValueError:
            limit = _DEBUG_TOOL_HISTORY_MAX
        items = list(history)[-limit:] if history else []
        return self.json({"items": items, "count": len(items), "max": _DEBUG_TOOL_HISTORY_MAX})


class KyberDebugStatusView(HomeAssistantView):
    """Runtime status: model, autopilot, session, store stats."""

    url = "/api/kyber/debug/status"
    name = "api:kyber:debug:status"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        await kstore.async_load()
        all_entries = await kstore.async_all()
        cat_counts: dict[str, int] = {}
        flagged = 0
        total_hits = 0
        for e in all_entries:
            cat_counts[e.get("category", "general")] = cat_counts.get(e.get("category", "general"), 0) + 1
            if e.get("needs_review"):
                flagged += 1
            total_hits += int(e.get("hits", 0) or 0)
        snap = hass.data.get(_DEBUG_LAST_TURN_KEY)
        # Find the configured AI Task entity from any entry in hass.data[DOMAIN]
        entries = hass.data.get(DOMAIN, {})
        ai_task_entity = ""
        if isinstance(entries, dict) and entries:
            first = next(iter(entries.values()), None)
            if isinstance(first, dict):
                ai_task_entity = str(first.get(CONF_AI_TASK_ENTITY_ID, ""))
        return self.json({
            "ai_task_entity": ai_task_entity,
            "knowledge": {
                "total": len(all_entries),
                "by_category": cat_counts,
                "needs_review": flagged,
                "total_hits": total_hits,
            },
            "last_turn": {
                "ts": snap.get("ts") if snap else None,
                "request_id": snap.get("request_id") if snap else None,
                "elapsed_ms": snap.get("elapsed_ms") if snap else None,
                "intent": snap.get("intent") if snap else None,
                "char_count": snap.get("char_count") if snap else None,
                "approx_tokens": snap.get("approx_tokens") if snap else None,
            } if snap else None,
            "tool_history_size": len(hass.data.get(_DEBUG_TOOL_HISTORY_KEY, []) or []),
        })


class KyberDebugBundleView(HomeAssistantView):
    """Return a zip bundle of one turn's debug info (or the last turn).

    GET /api/kyber/debug/bundle?request_id=XYZ  → application/zip
    GET /api/kyber/debug/bundle                 → uses last turn
    """

    url = "/api/kyber/debug/bundle"
    name = "api:kyber:debug:bundle"
    requires_auth = True

    @staticmethod
    def _read_manifest_version() -> str:
        try:
            import json as _json
            import os
            here = os.path.dirname(__file__)
            with open(os.path.join(here, "manifest.json"), "r", encoding="utf-8") as f:
                return _json.load(f).get("version", "unknown")
        except Exception:  # noqa: BLE001
            return "unknown"

    async def get(self, request: web.Request) -> web.Response:
        import io
        import json as _json
        import zipfile
        from collections import OrderedDict
        hass: HomeAssistant = request.app["hass"]
        rid = (request.query.get("request_id") or "").strip()
        snaps = hass.data.get(_DEBUG_SNAPSHOTS_KEY)
        snap: dict | None = None
        if rid and isinstance(snaps, OrderedDict):
            snap = snaps.get(rid)
        if snap is None:
            snap = hass.data.get(_DEBUG_LAST_TURN_KEY)
        if not snap:
            return self.json_message("No turn snapshot available", HTTPStatus.NOT_FOUND)

        manifest_obj: dict = {
            "kyber_version": self._read_manifest_version(),
            "request_id": snap.get("request_id"),
            "ts": snap.get("ts"),
            "intent": snap.get("intent"),
            "elapsed_ms": snap.get("elapsed_ms"),
            "char_count": snap.get("char_count"),
            "approx_tokens": snap.get("approx_tokens"),
            "auto_rating": snap.get("auto_rating"),
            "session_meta": snap.get("session_meta") or {},
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", _json.dumps(manifest_obj, indent=2, default=str))
            zf.writestr("snapshot.json", _json.dumps(snap, indent=2, default=str))
            zf.writestr("user_prompt.txt", snap.get("user_prompt") or "")
            zf.writestr("expanded_prompt.txt", snap.get("expanded_prompt") or "")
            zf.writestr("instructions_used.txt", snap.get("instructions_used") or "")
            zf.writestr("response.txt", snap.get("response_text") or "")
            zf.writestr("tool_log.json", _json.dumps(snap.get("tool_log") or [], indent=2, default=str))
            zf.writestr("knowledge_used.json", _json.dumps(snap.get("picked_knowledge") or [], indent=2, default=str))
            zf.writestr("progress_events.json", _json.dumps(snap.get("progress_events") or [], indent=2, default=str))
            # Logs as text (one line per record) + json.
            logs = snap.get("logs") or []
            log_lines: list[str] = []
            for r in logs:
                ts_iso = ""
                try:
                    import datetime as _dt
                    ts_iso = _dt.datetime.fromtimestamp(r.get("ts", 0)).strftime("%H:%M:%S.%f")[:-3]
                except Exception:  # noqa: BLE001
                    pass
                log_lines.append(f"{ts_iso} {r.get('level','?'):<8} {r.get('logger','?')}: {r.get('message','')}")
            zf.writestr("logs.txt", "\n".join(log_lines))
            zf.writestr("logs.json", _json.dumps(logs, indent=2, default=str))
            readme = (
                "Kyber debug bundle\n"
                "==================\n\n"
                f"request_id: {snap.get('request_id')}\n"
                f"ts: {snap.get('ts')}\n"
                f"intent: {snap.get('intent')}\n"
                f"elapsed_ms: {snap.get('elapsed_ms')}\n\n"
                "Contents:\n"
                "  manifest.json         - bundle meta (kyber version, ts, intent, ...)\n"
                "  snapshot.json         - full per-turn snapshot (single source of truth)\n"
                "  user_prompt.txt       - what the user typed\n"
                "  expanded_prompt.txt   - the full system prompt the model actually saw\n"
                "  instructions_used.txt - instructions for the final round of the tool loop\n"
                "  response.txt          - assistant's final reply\n"
                "  tool_log.json         - all tool calls made this turn (name, args, status, ms)\n"
                "  knowledge_used.json   - which memory entries were injected (with score)\n"
                "  progress_events.json  - progress updates streamed to the panel\n"
                "  logs.txt / logs.json  - kyber.* log records captured during the turn\n"
            )
            zf.writestr("README.txt", readme)

        data = buf.getvalue()
        fname = f"kyber-debug-{snap.get('request_id') or 'last'}-{snap.get('ts') or 'now'}.zip"
        return web.Response(
            body=data,
            content_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )


class KyberDebugModeView(HomeAssistantView):
    """Get/set the debug-mode flag used by the panel.

    GET  /api/kyber/debug/mode → {"enabled": bool}
    POST /api/kyber/debug/mode {"enabled": bool} → {"enabled": bool}
    """

    url = "/api/kyber/debug/mode"
    name = "api:kyber:debug:mode"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        return self.json({"enabled": _get_debug_mode(hass)})

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        enabled = bool(body.get("enabled", _DEBUG_MODE_DEFAULT))
        hass.data[_DEBUG_MODE_KEY] = enabled
        # Also persist to the integration's options so the change survives
        # restart and the sidebar panel registration updates accordingly.
        # We avoid importing from .const at module top to keep the existing
        # import surface stable for tests.
        try:
            from .const import CONF_ENABLE_DEBUG_VIEWS
            entries = hass.config_entries.async_entries(DOMAIN)
            if entries:
                entry = entries[0]
                current = entry.options.get(CONF_ENABLE_DEBUG_VIEWS)
                if current != enabled:
                    new_options = {**entry.options, CONF_ENABLE_DEBUG_VIEWS: enabled}
                    hass.config_entries.async_update_entry(entry, options=new_options)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed to persist debug-mode to options: %s", err)
        return self.json({"enabled": enabled})


class KyberHistoryView(HomeAssistantView):
    """Handle user-scoped chat history persistence for the active session."""

    url = "/api/kyber/history"
    name = "api:kyber:history"
    requires_auth = True

    @staticmethod
    def _user_id_from_request(request: web.Request) -> str | None:
        """Extract the authenticated Home Assistant user id from request."""
        ha_user = request.get("hass_user")
        user_id = getattr(ha_user, "id", None)
        return str(user_id) if user_id else None

    async def get(self, request: web.Request) -> web.Response:
        """Return persisted chat history for the active session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        data = await _async_load_chat_store(hass)
        user_data = data.get("users", {}).get(user_id, {})
        user_data = _migrate_user_to_sessions(user_data) if "sessions" not in user_data else user_data
        sid, session = _get_active_session(user_data)
        return self.json(
            {
                "history": _sanitize_history(session.get("history", [])),
                "compacted_summary": _sanitize_summary(session.get("compacted_summary", "")),
                "session_id": sid,
                "session_name": session.get("name", "Session 1"),
            }
        )

    async def post(self, request: web.Request) -> web.Response:
        """Save persisted chat history for the active session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        data = await _async_load_chat_store(hass)
        users = data.setdefault("users", {})
        user_data = users.get(user_id, {})
        user_data = _migrate_user_to_sessions(user_data) if "sessions" not in user_data else user_data
        sid, session = _get_active_session(user_data)
        session["history"] = _sanitize_history(body.get("history", []))
        session["compacted_summary"] = _sanitize_summary(body.get("compacted_summary", ""))
        users[user_id] = user_data
        await _async_save_chat_store(hass, data)
        return self.json({"status": "ok"})

    async def delete(self, request: web.Request) -> web.Response:
        """Clear persisted chat history for the active session only."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        data = await _async_load_chat_store(hass)
        users = data.get("users", {})
        user_data = users.get(user_id)
        if user_data:
            user_data = _migrate_user_to_sessions(user_data) if "sessions" not in user_data else user_data
            sid, session = _get_active_session(user_data)
            session["history"] = []
            session["compacted_summary"] = ""
            users[user_id] = user_data
            await _async_save_chat_store(hass, data)
        return self.json({"status": "ok"})


class KyberSessionsView(HomeAssistantView):
    """Manage multiple chat sessions per user."""

    url = "/api/kyber/sessions"
    name = "api:kyber:sessions"
    requires_auth = True

    @staticmethod
    def _user_id_from_request(request: web.Request) -> str | None:
        ha_user = request.get("hass_user")
        user_id = getattr(ha_user, "id", None)
        return str(user_id) if user_id else None

    async def _load_user(self, hass: HomeAssistant, user_id: str) -> tuple[dict, dict]:
        """Return (data, user_data) ensuring sessions format. Persists on first creation."""
        data = await _async_load_chat_store(hass)
        users = data.setdefault("users", {})
        user_data = users.get(user_id, {})
        is_new = "sessions" not in user_data
        user_data = _migrate_user_to_sessions(user_data) if is_new else user_data
        _get_active_session(user_data)  # ensure at least one session exists
        users[user_id] = user_data
        if is_new:
            await _async_save_chat_store(hass, data)
        return data, user_data

    async def get(self, request: web.Request) -> web.Response:
        """List all sessions for the current user."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        data, user_data = await self._load_user(hass, user_id)
        active_id = user_data.get("active_session")
        sessions_list = [
            {
                "id": sid,
                "name": s.get("name", "Session"),
                "message_count": len(s.get("history", [])),
                "created_at": s.get("created_at", 0),
                "active": sid == active_id,
            }
            for sid, s in user_data.get("sessions", {}).items()
        ]
        return self.json({"sessions": sessions_list, "active_session": active_id})

    async def post(self, request: web.Request) -> web.Response:
        """Create a new session and optionally switch to it."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}

        data, user_data = await self._load_user(hass, user_id)
        sessions = user_data.setdefault("sessions", {})
        if len(sessions) >= _SESSIONS_MAX:
            return self.json_message(
                f"Maximum {_SESSIONS_MAX} sessions reached", HTTPStatus.UNPROCESSABLE_ENTITY
            )

        import time as _time
        sid = _new_session_id()
        raw_name = str(body.get("name", f"Session {len(sessions) + 1}")).strip()
        name = raw_name[:_SESSION_NAME_MAX_CHARS] or f"Session {len(sessions) + 1}"
        sessions[sid] = {"name": name, "history": [], "compacted_summary": "", "created_at": _time.time()}
        if body.get("switch", True):
            user_data["active_session"] = sid
        data["users"][user_id] = user_data
        await _async_save_chat_store(hass, data)
        return self.json({"status": "ok", "session_id": sid, "name": name})

    async def put(self, request: web.Request) -> web.Response:
        """Switch active session or rename a session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        data, user_data = await self._load_user(hass, user_id)
        sessions = user_data.get("sessions", {})

        action = body.get("action", "switch")
        if action == "switch":
            sid = body.get("session_id") or _find_session_by_name(sessions, body.get("name", ""))
            if not sid or sid not in sessions:
                return self.json_message("Session not found", HTTPStatus.NOT_FOUND)
            user_data["active_session"] = sid
            data["users"][user_id] = user_data
            await _async_save_chat_store(hass, data)
            return self.json({"status": "ok", "active_session": sid})

        if action == "rename":
            sid = body.get("session_id") or user_data.get("active_session")
            if not sid or sid not in sessions:
                return self.json_message("Session not found", HTTPStatus.NOT_FOUND)
            new_name = str(body.get("name", "")).strip()[:_SESSION_NAME_MAX_CHARS]
            if not new_name:
                return self.json_message("Name cannot be empty", HTTPStatus.BAD_REQUEST)
            sessions[sid]["name"] = new_name
            data["users"][user_id] = user_data
            await _async_save_chat_store(hass, data)
            return self.json({"status": "ok"})

        return self.json_message(f"Unknown action: {action}", HTTPStatus.BAD_REQUEST)

    async def delete(self, request: web.Request) -> web.Response:
        """Delete a session (defaults to active). Switches to another session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except Exception:
            body = {}

        data, user_data = await self._load_user(hass, user_id)
        sessions = user_data.get("sessions", {})
        sid = body.get("session_id") or user_data.get("active_session")

        if not sid or sid not in sessions:
            return self.json_message("Session not found", HTTPStatus.NOT_FOUND)

        del sessions[sid]

        # Switch to the first remaining session or create a new one
        if sessions:
            user_data["active_session"] = next(iter(sessions))
        else:
            new_sid = _new_session_id()
            sessions[new_sid] = {"name": "Session 1", "history": [], "compacted_summary": "", "created_at": __import__("time").time()}
            user_data["active_session"] = new_sid

        data["users"][user_id] = user_data
        await _async_save_chat_store(hass, data)
        return self.json({"status": "ok", "active_session": user_data["active_session"]})


def _find_session_by_name(sessions: dict[str, Any], name: str) -> str | None:
    """Find a session id by exact name match (case-insensitive)."""
    name_lower = name.lower()
    for sid, s in sessions.items():
        if s.get("name", "").lower() == name_lower:
            return sid
    return None


class KyberSessionNameView(HomeAssistantView):
    """Generate an AI session title from recent messages and optionally save it."""

    url = "/api/kyber/sessions/name"
    name = "api:kyber:sessions:name"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @staticmethod
    def _user_id_from_request(request: web.Request) -> str | None:
        ha_user = request.get("hass_user")
        user_id = getattr(ha_user, "id", None)
        return str(user_id) if user_id else None

    async def post(self, request: web.Request) -> web.Response:
        """Generate a short title for the current session and save it."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        messages: list[dict] = body.get("messages", [])
        if not messages:
            return self.json_message("No messages provided", HTTPStatus.BAD_REQUEST)

        # Build a compact transcript for the naming prompt (last 10 messages max)
        snippet_lines = []
        for msg in messages[-10:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = str(msg.get("content", "")).strip()[:200]
            if content:
                snippet_lines.append(f"{role}: {content}")
        transcript = "\n".join(snippet_lines)

        instructions = (
            "You are a helpful assistant. Based on the conversation below, "
            "generate a very short title (3–6 words, no punctuation at the end) "
            "that captures the main topic. Reply with ONLY the title — no quotes, "
            "no explanation, nothing else.\n\n"
            f"Conversation:\n{transcript}\n\nTitle:"
        )

        entity_id: str = self._config[CONF_AI_TASK_ENTITY_ID]
        try:
            result = await async_generate_data(
                hass,
                task_name=f"{DOMAIN}_session_name",
                entity_id=entity_id,
                instructions=instructions,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Session naming AI call failed: %s", err)
            return self.json_message(f"AI error: {err}", HTTPStatus.SERVICE_UNAVAILABLE)

        raw: str = result.data if isinstance(result.data, str) else str(result.data)
        # Take only the first line, strip quotes/punctuation
        name = raw.strip().splitlines()[0].strip().strip('"\'').strip(".,;:!?")
        name = name[:_SESSION_NAME_MAX_CHARS] or "Session"

        # Save the new name to the active session
        data = await _async_load_chat_store(hass)
        users = data.setdefault("users", {})
        user_data = users.get(user_id, {})
        user_data = _migrate_user_to_sessions(user_data) if "sessions" not in user_data else user_data
        sid, session = _get_active_session(user_data)
        session["name"] = name
        users[user_id] = user_data
        await _async_save_chat_store(hass, data)

        return self.json({"name": name, "session_id": sid})


class KyberExecuteView(HomeAssistantView):
    """Handle POST /api/kyber/execute — applies entity registry actions."""

    url = "/api/kyber/execute"
    name = "api:kyber:execute"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Execute a list of entity registry actions from a plan."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        actions: list[dict] = body.get("actions", [])
        if not actions:
            return self.json_message("Missing 'actions' field", HTTPStatus.BAD_REQUEST)

        # Enforce explicit approval for config-changing/destructive actions.
        # The client must POST `approved: true` to apply them. Autopilot
        # auto-execute MUST set this to false (or omit it), in which case
        # we refuse and instruct the UI to require a user click.
        approved: bool = bool(body.get("approved", False))
        if not approved:
            blocked: list[dict] = []
            for action in actions:
                if _action_requires_approval(action):
                    blocked.append({
                        "type": action.get("type"),
                        "entity_id": action.get("entity_id"),
                        "domain": action.get("domain"),
                        "service": action.get("service"),
                        "reason": "Configuration / destructive action requires explicit user approval.",
                    })
            if blocked:
                return self.json({
                    "status": "approval_required",
                    "blocked_actions": blocked,
                    "message": (
                        "These actions change Home Assistant configuration or are "
                        "destructive and cannot be auto-executed. The user must click "
                        "Execute to approve them."
                    ),
                }, status_code=HTTPStatus.FORBIDDEN)

        entity_reg = er.async_get(hass)
        label_reg = lr.async_get(hass)
        area_reg = ar.async_get(hass)

        results: list[dict] = []

        # Read-only tool call types — execute transparently without entity_id
        _READ_TOOL_TYPES = {
            "list_entities_by_domain", "get_entity_state", "get_area_entities",
            "list_entities_by_label", "search_entities", "get_areas", "get_labels",
        }

        for action in actions:
            action_type: str = action.get("type", "")

            # ── Read-only tool calls (no approval needed) ──────────────────
            if action_type in _READ_TOOL_TYPES:
                call = {**action, "name": action_type}
                tool_result = _execute_tool(hass, call)
                results.append({
                    "status": "ok", "type": action_type,
                    "tool_result": json.loads(tool_result),
                })
                continue

            # ── Knowledge management actions ───────────────────────────────
            if action_type in ("add_knowledge", "update_knowledge", "delete_knowledge"):
                kstore = get_knowledge_store(hass)
                try:
                    if action_type == "add_knowledge":
                        entry = await kstore.async_add(
                            category=str(action.get("category", "general")),
                            content=str(action.get("content", "")),
                            subject=str(action.get("subject", "")),
                            tags=list(action.get("tags", []) or []),
                            source=str(action.get("source", "user")),
                            confidence=float(action.get("confidence", 1.0)),
                        )
                        results.append({
                            "status": "ok", "type": action_type, "entry_id": entry["id"],
                            "undo_action": {
                                "type": "delete_knowledge", "entry_id": entry["id"],
                                "current_state": entry.get("content", "")[:60],
                                "new_state": "(deleted)",
                                "description": "Remove learned knowledge entry",
                            },
                        })
                    elif action_type == "update_knowledge":
                        entry_id = str(action.get("entry_id", ""))
                        changes = {k: v for k, v in action.items()
                                   if k in ("category", "subject", "content", "tags", "confidence", "source")}
                        updated = await kstore.async_update(entry_id, **changes)
                        if updated:
                            results.append({"status": "ok", "type": action_type, "entry_id": entry_id})
                        else:
                            results.append({"status": "error", "message": f"Knowledge entry '{entry_id}' not found"})
                    elif action_type == "delete_knowledge":
                        entry_id = str(action.get("entry_id", ""))
                        ok = await kstore.async_delete(entry_id)
                        results.append({
                            "status": "ok" if ok else "error", "type": action_type,
                            "entry_id": entry_id,
                            **({"message": f"Knowledge entry '{entry_id}' not found"} if not ok else {}),
                        })
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("Knowledge action %s failed: %s", action_type, err)
                    results.append({"status": "error", "message": str(err)})
                continue

            # ── Area management actions (no entity_id needed) ──────────────
            if action_type == "create_area":
                area_name: str = action.get("name", "").strip()
                if not area_name:
                    results.append({"status": "error", "message": "Missing 'name' for create_area"})
                    continue
                try:
                    new_area = area_reg.async_create(area_name)
                    results.append({
                        "status": "ok", "type": action_type,
                        "area_id": new_area.id, "name": new_area.name,
                        "undo_action": {"type": "delete_area", "area_id": new_area.id,
                                        "current_state": new_area.name, "new_state": "(deleted)",
                                        "description": f"Delete area '{new_area.name}'"},
                    })
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("create_area '%s' failed: %s", area_name, err)
                    results.append({"status": "error", "message": str(err)})
                continue

            if action_type == "rename_area":
                area_id: str = action.get("area_id", "").strip()
                new_area_name: str = action.get("name", "").strip()
                if not area_id or not new_area_name:
                    results.append({"status": "error", "message": "Missing 'area_id' or 'name' for rename_area"})
                    continue
                area_entry = area_reg.async_get_area(area_id)
                if area_entry is None:
                    results.append({"status": "error", "message": f"Area '{area_id}' not found"})
                    continue
                old_area_name = area_entry.name
                try:
                    area_reg.async_update(area_id, name=new_area_name)
                    results.append({
                        "status": "ok", "type": action_type, "area_id": area_id, "name": new_area_name,
                        "undo_action": {"type": "rename_area", "area_id": area_id, "name": old_area_name,
                                        "current_state": new_area_name, "new_state": old_area_name,
                                        "description": f"Rename area back to '{old_area_name}'"},
                    })
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("rename_area '%s' failed: %s", area_id, err)
                    results.append({"status": "error", "message": str(err)})
                continue

            if action_type == "delete_area":
                area_id = action.get("area_id", "").strip()
                if not area_id:
                    results.append({"status": "error", "message": "Missing 'area_id' for delete_area"})
                    continue
                area_entry = area_reg.async_get_area(area_id)
                if area_entry is None:
                    results.append({"status": "error", "message": f"Area '{area_id}' not found"})
                    continue
                old_name = area_entry.name
                try:
                    area_reg.async_delete(area_id)
                    results.append({
                        "status": "ok", "type": action_type, "area_id": area_id,
                        # Undo recreates the area (loses original id, but name is preserved)
                        "undo_action": {"type": "create_area", "name": old_name,
                                        "current_state": "(deleted)", "new_state": old_name,
                                        "description": f"Recreate area '{old_name}'"},
                    })
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("delete_area '%s' failed: %s", area_id, err)
                    results.append({"status": "error", "message": str(err)})
                continue

            # ── Service call actions ───────────────────────────────────────
            if action_type == "call_service":
                domain: str = action.get("domain", "").strip()
                service: str = action.get("service", "").strip()
                service_data: dict = action.get("service_data") or {}
                svc_entity_id: str = action.get("entity_id", "").strip()
                if not domain or not service:
                    results.append({"status": "error", "message": "Missing 'domain' or 'service' for call_service"})
                    continue
                # Capture state before call for undo
                pre_state = hass.states.get(svc_entity_id) if svc_entity_id else None
                if svc_entity_id:
                    service_data = {"entity_id": svc_entity_id, **service_data}
                try:
                    await hass.services.async_call(domain, service, service_data, blocking=True)
                    undo_action = _build_service_undo(domain, service, svc_entity_id, pre_state)
                    result: dict = {"status": "ok", "type": action_type, "entity_id": svc_entity_id or domain}
                    if undo_action:
                        result["undo_action"] = undo_action
                    results.append(result)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("call_service %s.%s failed: %s", domain, service, err)
                    results.append({"status": "error", "entity_id": svc_entity_id or domain, "message": str(err)})
                continue

            entity_id: str = action.get("entity_id", "")

            if not entity_id:
                results.append({"entity_id": entity_id, "status": "error", "message": "Missing entity_id"})
                continue

            entry = entity_reg.async_get(entity_id)
            if entry is None:
                results.append({"entity_id": entity_id, "status": "error", "message": "Entity not found in registry"})
                continue

            try:
                if action_type == "assign_area":
                    area_id: str = action.get("area_id", "")
                    if area_id and area_reg.async_get_area(area_id) is None:
                        results.append({"entity_id": entity_id, "status": "error", "message": f"Area '{area_id}' not found"})
                        continue
                    old_area_id = entry.area_id or ""
                    old_area_name = (area_reg.async_get_area(old_area_id).name if old_area_id and area_reg.async_get_area(old_area_id) else "") or "(none)"
                    new_area_name2 = (area_reg.async_get_area(area_id).name if area_id and area_reg.async_get_area(area_id) else "") or "(none)"
                    entity_reg.async_update_entity(entity_id, area_id=area_id or None)
                    results.append({
                        "entity_id": entity_id, "status": "ok", "type": action_type,
                        "undo_action": {"type": "assign_area", "entity_id": entity_id,
                                        "area_id": old_area_id,
                                        "current_state": new_area_name2, "new_state": old_area_name,
                                        "description": f"Move {entity_id} back to {old_area_name}"},
                    })

                elif action_type == "rename_entity":
                    new_name: str = action.get("name", "")
                    old_name2 = entry.name or entry.original_name or entity_id
                    entity_reg.async_update_entity(entity_id, name=new_name or None)
                    results.append({
                        "entity_id": entity_id, "status": "ok", "type": action_type,
                        "undo_action": {"type": "rename_entity", "entity_id": entity_id,
                                        "name": old_name2,
                                        "current_state": new_name, "new_state": old_name2,
                                        "description": f"Rename {entity_id} back to '{old_name2}'"},
                    })

                elif action_type == "assign_label":
                    label_id: str = action.get("label_id", "")
                    if not label_id:
                        results.append({"entity_id": entity_id, "status": "error", "message": "Missing label_id"})
                        continue
                    if label_reg.async_get_label(label_id) is None:
                        label_reg.async_create(label_id)
                    old_labels = set(entry.labels)
                    new_labels = old_labels | {label_id}
                    entity_reg.async_update_entity(entity_id, labels=new_labels)
                    results.append({
                        "entity_id": entity_id, "status": "ok", "type": action_type,
                        "undo_action": {"type": "remove_label", "entity_id": entity_id,
                                        "label_id": label_id,
                                        "current_state": str(new_labels), "new_state": str(old_labels),
                                        "description": f"Remove label '{label_id}' from {entity_id}"},
                    })

                elif action_type == "remove_label":
                    label_id = action.get("label_id", "")
                    if not label_id:
                        results.append({"entity_id": entity_id, "status": "error", "message": "Missing label_id"})
                        continue
                    old_labels = set(entry.labels)
                    new_labels = old_labels - {label_id}
                    entity_reg.async_update_entity(entity_id, labels=new_labels)
                    results.append({
                        "entity_id": entity_id, "status": "ok", "type": action_type,
                        "undo_action": {"type": "assign_label", "entity_id": entity_id,
                                        "label_id": label_id,
                                        "current_state": str(new_labels), "new_state": str(old_labels),
                                        "description": f"Re-add label '{label_id}' to {entity_id}"},
                    })

                else:
                    results.append({"entity_id": entity_id, "status": "error", "message": f"Unknown action type '{action_type}'"})

            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Execute action %s on %s failed: %s", action_type, entity_id, err)
                results.append({"entity_id": entity_id, "status": "error", "message": str(err)})

        return self.json({"results": results})


class KyberSaveView(HomeAssistantView):
    """Handle POST /api/kyber/parse_yaml — parses YAML, returns JSON config.

    The frontend uses this to convert editor YAML to JSON, then calls
    HA's own config/automation/config/{id} REST endpoint directly.
    """

    url = "/api/kyber/parse_yaml"
    name = "api:kyber:parse_yaml"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Parse YAML and return the resulting JSON object."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        yaml_text: str | None = body.get("yaml")
        if not yaml_text:
            return self.json_message("Missing 'yaml' field", HTTPStatus.BAD_REQUEST)

        try:
            config = yaml.safe_load(yaml_text)
        except yaml.YAMLError as err:
            return self.json_message(f"Invalid YAML: {err}", HTTPStatus.BAD_REQUEST)

        if not isinstance(config, dict):
            return self.json_message("YAML must be a mapping object", HTTPStatus.BAD_REQUEST)

        return self.json({"config": config})


_SUMMARIZE_SYSTEM_PROMPT = """\
You are a conversation summarizer for a Home Assistant AI assistant.
Your job is to maintain a running summary of a conversation between a user and an AI assistant.

Rules:
- Merge the previous summary with the new messages into one updated, concise summary.
- Always copy lines that start with [CHANGE] into the new summary exactly as written. These record actual changes made to the Home Assistant setup and must never be dropped.
- Keep the summary short and factual — focus on what was asked, what was decided, and what was changed.
- Do not include pleasantries or meta-commentary. Output only the summary text.\
"""


class KyberSummarizeView(HomeAssistantView):
    """Handle POST /api/kyber/summarize — merges overflow messages into a running summary."""

    url = "/api/kyber/summarize"
    name = "api:kyber:summarize"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        """Store config entry data."""
        self._config = config

    async def post(self, request: web.Request) -> web.Response:
        """Merge previous summary + overflow messages into a new summary."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        previous_summary: str = body.get("previous_summary", "").strip()
        messages: list[dict] = body.get("messages", [])

        if not messages:
            return self.json({"summary": previous_summary})

        # Format the messages for the AI
        msg_lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", "")).strip()
            if content:
                msg_lines.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")

        instructions = _SUMMARIZE_SYSTEM_PROMPT
        if previous_summary:
            instructions += f"\n\nPrevious summary:\n{previous_summary}"
        instructions += f"\n\nNew messages to incorporate:\n" + "\n".join(msg_lines)
        instructions += "\n\nOutput the updated summary:"

        entity_id: str = self._config[CONF_AI_TASK_ENTITY_ID]

        try:
            result = await async_generate_data(
                hass,
                task_name=f"{DOMAIN}_summarize",
                entity_id=entity_id,
                instructions=instructions,
            )
        except HomeAssistantError as err:
            _LOGGER.error("Summarize AI task failed: %s", err)
            # Fall back: append messages as plain text rather than failing
            fallback_lines = [f"[{m.get('role','user').upper()}] {m.get('content','')}" for m in messages]
            fallback = (previous_summary + "\n" + "\n".join(fallback_lines)).strip()
            return self.json({"summary": fallback})

        summary_text: str = result.data if isinstance(result.data, str) else str(result.data)
        return self.json({"summary": summary_text.strip()})
