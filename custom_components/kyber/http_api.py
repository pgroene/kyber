"""HTTP API view for kyber: proxies AI completion requests."""
from __future__ import annotations

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

_LOGGER = logging.getLogger(__name__)

_YAML_BLOCK_RE = re.compile(r"```yaml\s*([\s\S]+?)\s*```", re.IGNORECASE)
_PLAN_BLOCK_RE = re.compile(r"```plan\s*([\s\S]+?)\s*```", re.IGNORECASE)
# Match [TOOL_CALL: ...] tolerating O/0 confusion from small models
_TOOL_CALL_RE = re.compile(r"\[T[O0]{2}L[_\-]CALL:\s*(\{[^]]*?\})\s*\]", re.DOTALL | re.IGNORECASE)
# Match [TOOL_RESULT: ...] with same tolerance
_TOOL_RESULT_STRIP_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?", re.IGNORECASE)
_TOOL_RESULT_ECHO_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?.*?(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE)
_TOOL_CALL_MAX_ROUNDS = 5

# Keywords that indicate the user wants to change/act on something (ACTION intent).
# Anything else is INFORMATIONAL — the AI should just respond in plain text.
_ACTION_KEYWORDS: frozenset[str] = frozenset({
    "edit", "modify", "change", "update", "rename", "assign", "move",
    "turn on", "turn off", "switch on", "switch off", "set", "create",
    "delete", "remove", "add", "enable", "disable", "fix", "open editor",
    "open automation", "open script", "open dashboard", "adjust", "configure",
    "schedule", "trigger", "automate", "control", "dim", "brighten",
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

    automation_list = "\n".join(automation_lines) or "(no automations)"
    script_list = "\n".join(script_lines) or "(no scripts)"

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
            results[state.entity_id] = {
                "name": state.attributes.get("friendly_name", state.entity_id),
                "state": state.state,
            }
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
        return json.dumps({
            "entity_id": entity_id,
            "state": state.state,
            "attributes": dict(state.attributes),
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
            results[entry.entity_id] = {
                "name": state.attributes.get("friendly_name", entry.entity_id) if state else entry.original_name,
                "state": state.state if state else "unknown",
                "domain": entry.entity_id.split(".")[0],
            }
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
            results[entry.entity_id] = {
                "name": state.attributes.get("friendly_name", entry.entity_id) if state else entry.original_name,
                "state": state.state if state else "unknown",
            }
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
            results[state.entity_id] = {
                "name": state.attributes.get("friendly_name", state.entity_id),
                "state": state.state,
                "domain": state.entity_id.split(".")[0],
            }
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
            results[entry.entity_id] = {
                "name": (state.attributes.get("friendly_name", entry.entity_id)
                         if state else entry.original_name or entry.entity_id),
                "state": state.state if state else "unknown",
                "domain": entry.entity_id.split(".")[0],
            }
        return json.dumps(results or {"info": "All entities have an area assigned"})

    if name == "get_areas":
        areas = area_reg.async_list_areas()
        return json.dumps({a.id: a.name for a in areas})

    if name == "get_labels":
        labels = label_reg.async_list_labels()
        return json.dumps({lbl.label_id: lbl.name for lbl in labels})

    valid_tools = [
        "list_entities_by_domain", "get_entity_state", "get_area_entities",
        "list_entities_by_label", "search_entities", "list_entities_without_area",
        "get_areas", "get_labels",
    ]
    return json.dumps({
        "error": f"Unknown tool '{name}'",
        "valid_tools": valid_tools,
        "hint": "Retry with one of the valid tool names listed above.",
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

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        user_yaml: str = body.get("yaml", "")
        user_prompt: str = body.get("prompt", "").strip()
        history: list[dict] = body.get("history", [])
        compacted_summary: str = body.get("compacted_summary", "").strip()
        editor_mode: str = body.get("editor_mode", "automation")
        dashboards: list[dict] = body.get("dashboards", [])
        lovelace_resources: list[str] = body.get("lovelace_resources", [])

        if not user_prompt:
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

        if len(instructions) > _MAX_INSTRUCTIONS_CHARS:
            _LOGGER.warning(
                "Kyber: instructions truncated from %d to %d chars to fit context window.",
                len(instructions),
                _MAX_INSTRUCTIONS_CHARS,
            )
            instructions = instructions[:_MAX_INSTRUCTIONS_CHARS]

        entity_id: str = self._config[CONF_AI_TASK_ENTITY_ID]

        # Tool-calling loop — the AI may request live HA data via [TOOL_CALL: {...}]
        # We execute tools and re-send up to _TOOL_CALL_MAX_ROUNDS times.
        tool_exchange = ""  # accumulated tool call/result pairs appended to instructions
        tool_log: list[dict[str, Any]] = []  # summary of tool calls for UI feedback
        response_text = ""
        for _round in range(_TOOL_CALL_MAX_ROUNDS):
            loop_instructions = instructions + tool_exchange
            if len(loop_instructions) > _MAX_INSTRUCTIONS_CHARS:
                loop_instructions = loop_instructions[:_MAX_INSTRUCTIONS_CHARS]

            try:
                result = await async_generate_data(
                    hass,
                    task_name=f"{DOMAIN}_complete",
                    entity_id=entity_id,
                    instructions=loop_instructions,
                )
            except HomeAssistantError as err:
                _LOGGER.error("AI task failed: %s", err)
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

            # Execute tools and build result block
            clean_response = _strip_tool_calls(response_text)
            tool_results_block = ""
            for call in tool_calls:
                tool_result_str = _execute_tool(hass, call)
                tool_result_data = json.loads(tool_result_str)
                _LOGGER.debug("Tool call %s → %s chars", call.get("name"), len(tool_result_str))

                # Build a short human-readable summary for the UI
                summary = _tool_result_summary(call, tool_result_data)
                args_display = {k: v for k, v in call.items() if k != "name"}
                tool_log.append({
                    "name": call.get("name", ""),
                    "args": args_display,
                    "summary": summary,
                })

                tool_results_block += (
                    f"\n[TOOL_RESULT: {json.dumps(call)}]\n{tool_result_str}\n"
                )
            tool_exchange += f"{clean_response}\n{tool_results_block}\nAssistant:"

        yaml_blocks = _extract_yaml_blocks(response_text)
        plan_block = _extract_plan_block(response_text)

        # Strip any [TOOL_RESULT: ...] or [T00L_RESULT: ...] lines the model echoed back.
        response_text = _TOOL_RESULT_STRIP_RE.sub("", response_text).strip()

        # Strip any unparsed [TOOL_CALL: ...] / [T00L_CALL: ...] from the final response.
        response_text = _TOOL_CALL_RE.sub("", response_text).strip()

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
        if intent == "informational" and plan_block and (
            plan_block.get("open_editor") or plan_block.get("open_dashboard")
        ):
            _LOGGER.warning(
                "Kyber: dropping spurious open_editor/open_dashboard plan for informational query: %r",
                user_prompt[:80],
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

        # Detect hallucinated entity IDs: if no tool was called but the response
        # contains entity-id patterns (domain.name), check them against HA state.
        # If none match real states, append a warning so the user knows.
        if not tool_log:
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

        return self.json({"response": response_text, "yaml_blocks": yaml_blocks, "plan": plan_block, "context_stats": context_stats, "tool_log": tool_log})


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
