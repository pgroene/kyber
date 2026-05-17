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

from .const import CONF_AI_TASK_ENTITY_ID, CONF_USER_NAME, DOMAIN, SYSTEM_PROMPT_TEMPLATE, AUTOMATION_EDITOR_GUIDANCE, LOVELACE_CARDS_REFERENCE
from .knowledge import CATEGORIES as KNOWLEDGE_CATEGORIES, get_store as get_knowledge_store
from .analyzer import analyze_automations as _analyze_automations
from .source import (
    read_automations as _src_read_automations,
    read_scripts as _src_read_scripts,
    read_blueprints as _src_read_blueprints,
    read_blueprint as _src_read_blueprint,
)
from . import deep_analyzer as _deep
from .response_processing import (
    _YAML_BLOCK_RE, _PLAN_BLOCK_RE, _CLARIFY_BLOCK_RE, _TOOL_CALL_RE,
    _TOOL_RESULT_STRIP_RE, _TOOL_RESULT_ECHO_RE, _TOOL_CALL_MAX_ROUNDS,
    _BARE_FENCE_RE, _ACTION_TYPE_RE, _AUTOMATION_EDIT_RE,
    _parse_tool_calls, _strip_tool_calls, _extract_yaml_blocks, _extract_plan_block,
    _rewrap_bare_action_fences, _NARRATION_PATTERNS, _BARE_JSON_TOOL_RESULT_RE,
    _strip_role_echo_prefix, _BRIGHTNESS_INTENT_RE, _DIM_INTENT_RE,
    _augment_brightness_intent, _extract_clarify_block,
)
from .intent_and_context import (
    _QUICK_CREATE_AREA_RE, _try_quick_intent,
    _ACTION_KEYWORDS, _ACTION_RE_PATTERNS,
    _classify_intent,
    _build_home_state_by_area, _build_context,
)
from .tool_execution import _tool_result_summary, _state_matches, _execute_tool
from .session_and_storage import (
    _CHAT_HISTORY_STORE_VERSION, _CHAT_HISTORY_STORE_KEY,
    _CHAT_HISTORY_MAX_MESSAGES, _CHAT_MESSAGE_MAX_CHARS, _CHAT_SUMMARY_MAX_CHARS,
    _SESSIONS_MAX, _SESSION_NAME_MAX_CHARS,
    _new_session_id, _migrate_user_to_sessions, _get_active_session,
    _sanitize_history, _sanitize_summary, _async_load_chat_store, _async_save_chat_store,
    _find_session_by_name,
    KyberHistoryView, KyberSessionsView, KyberSessionNameView,
)
from .debug_and_diagnostics import (
    _KyberTurnLogHandler, _debug_attach_log_capture, _debug_detach_log_capture,
    _debug_record_turn,
    KyberDebugLastTurnView, KyberDebugToolHistoryView, KyberDebugStatusView,
    KyberDebugBundleView, KyberBugReportView, KyberDebugModeView,
    _build_redaction_map, _restore_kyber_version_in_bug_report, _build_redacted_bundle_summary,
)

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


def _sanitize_prompt_value(text: str) -> str:
    """Sanitize a user-supplied string before embedding it in the system prompt.

    Replaces newline and carriage-return characters with a single space so that
    a maliciously crafted area name, label, entity friendly name, or memory
    entry cannot inject new markdown sections or instructions into the prompt.
    Other ASCII control characters are also stripped for the same reason.
    """
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    # Replace runs of control characters (including \\n, \\r, \\t, etc.) with one space.
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return cleaned.strip()


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



# Appended to the tool-exchange when we need a plain-text synthesis pass
# (model looped on tool calls and never wrote a prose answer).
_SYNTHESIS_INSTRUCTIONS = (
    "\n\n[SYSTEM: You already have all the data you need from the tool results "
    "shown above. Answer the user's question directly in plain text now. "
    "Do NOT output any [TOOL_CALL:] blocks — only a prose answer. "
    "List EVERY item from the results; do not truncate with '...' or 'and X more'.]\n"
    "Assistant:"
)


# Regex that detects correction turns: user is clarifying a name mismatch.
# Triggers the post-response learned-fact extraction pass.
_CORRECTION_SIGNALS_RE = re.compile(
    r"\b(it'?s\s+(called|named|known\s+as)"
    r"|i\s+mean\b"
    r"|the\s+(correct|right|actual|real)\s+(name|term|word)\s+is"
    r"|use\s+\w+\s+instead"
    r"|that'?s\s+(called|named)"
    r"|het\s+heet"          # Dutch: "it is called"
    r"|bedoel\s+ik"         # Dutch: "I mean"
    r"|ik\s+bedoel"
    r"|noem\s+(het|ik)"     # Dutch: "call it"
    r"|is\s+genaamd"        # Dutch: "is named"
    r"|heet\s+eigenlijk"    # Dutch: "is actually called"
    r")\b",
    re.IGNORECASE,
)

# Mini prompt used for the post-turn fact-extraction LLM call.
# Kept intentionally tiny to be fast and not cost much context budget.
_FACT_EXTRACTION_PROMPT = """\
You are a fact extractor for a Home Assistant assistant.
Given a user correction, extract ONE name alias mapping — what the user calls something \
vs what it is named in Home Assistant.

User said: "{user_prompt}"
Recent conversation context:
{context_snippet}

If you can identify a clear name mismatch, output ONLY a JSON object (no extra text):
{{"subject": "<HA name>", "user_term": "<user word>", \
"content": "When user says '<user word>' they mean '<HA name>'.", \
"category": "area_alias", "tags": ["<user word>", "<HA name>"]}}

If there is no clear mismatch to learn, output: null
"""

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

# Hard cap on total instructions to avoid exceeding Ollama's context window (~8K tokens ≈ 32K chars)
_MAX_INSTRUCTIONS_CHARS = 32_000
# Reserve budget for knowledge facts so they survive the loop's re-truncation.
# Base prompt is capped at (_MAX_INSTRUCTIONS_CHARS - _KNOWLEDGE_BUDGET); knowledge
# is then appended within the remaining space, keeping total ≤ _MAX_INSTRUCTIONS_CHARS.
_KNOWLEDGE_BUDGET = 2_000
_BASE_INSTRUCTIONS_CHARS = _MAX_INSTRUCTIONS_CHARS - _KNOWLEDGE_BUDGET  # 30 000
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


async def _try_extract_learned_fact(
    hass: HomeAssistant,
    entity_id: str,
    user_prompt: str,
    context_snippet: str,
) -> dict[str, Any] | None:
    """Run a mini LLM call to extract a learned name alias from a correction turn.

    Returns a dict with keys subject, user_term, content, category, tags — or None.
    Failures are silently swallowed; this is a best-effort enhancement.
    """
    import json as _json
    try:
        prompt = _FACT_EXTRACTION_PROMPT.format(
            user_prompt=user_prompt[:200],
            context_snippet=context_snippet[-400:],
        )
        result = await async_generate_data(
            hass,
            task_name=f"{DOMAIN}_fact_extract",
            entity_id=entity_id,
            instructions=prompt,
        )
        raw = result.data if isinstance(result.data, str) else str(result.data)
        raw = raw.strip()
        # Strip common model wrappers (```json ... ```, ```...```)
        raw = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.IGNORECASE)
        raw = raw.strip()
        if raw.lower() == "null" or not raw.startswith("{"):
            return None
        data = _json.loads(raw)
        subject = data.get("subject", "").strip()
        user_term = data.get("user_term", "").strip()
        content = data.get("content", "").strip()
        if not subject or not user_term or not content:
            return None
        return {
            "subject": subject,
            "user_term": user_term,
            "content": content,
            "category": data.get("category", "area_alias"),
            "tags": data.get("tags", [user_term, subject]),
        }
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber: fact extraction failed (non-critical): %s", err)
        return None


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

        context, context_stats = _build_context(
            hass,
            user_name=self._config.get(CONF_USER_NAME, ""),
        )

        # Dashboard list from frontend (may be empty list if fetch failed)
        dash_lines = ["- Overview (default) — url_path: (default)"]
        for d in (dashboards or []):
            title = _sanitize_prompt_value(d.get("title") or d.get("url_path", "?"))
            url_path = _sanitize_prompt_value(d.get("url_path", ""))
            mode = _sanitize_prompt_value(d.get("mode", "unknown"))
            if url_path:  # skip entries with no url_path to avoid duplicating default
                dash_lines.append(f"- {title} — url_path: {url_path} — mode: {mode}")
        dashboard_section = "## Dashboards\n" + "\n".join(dash_lines) + "\n\n"

        # Custom Lovelace card resources
        if lovelace_resources:
            resource_lines = [f"- {_sanitize_prompt_value(url)}" for url in lovelace_resources]
            dashboard_section += "## Custom card resources (installed via HACS or manually)\n" + "\n".join(resource_lines) + "\nWhen using custom cards use `type: custom:<card-name>` syntax.\n\n"

        # Current user info (always available — view requires auth)
        ha_user = request.get("hass_user")
        if ha_user:
            user_display = _sanitize_prompt_value(ha_user.name or ha_user.id)
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

        # Lazy-load sections: inject only when relevant to save prompt budget.
        automation_guidance = (
            AUTOMATION_EDITOR_GUIDANCE
            if user_yaml.strip() or _AUTOMATION_EDIT_RE.search(user_prompt)
            else ""
        )
        lovelace_ref = LOVELACE_CARDS_REFERENCE if editor_mode == "dashboard" else ""

        instructions = (
            f"{context}\n\n"
            f"{automation_guidance}"
            f"{lovelace_ref}"
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
                cat = _sanitize_prompt_value(entry.get("category", "general"))
                subj = _sanitize_prompt_value(entry.get("subject", ""))
                content = _sanitize_prompt_value(entry.get("content", ""))
                tags = ",".join(_sanitize_prompt_value(t) for t in (entry.get("tags", []) or []))
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

        # Post-turn fact extraction: if the user made a correction (e.g. "it's
        # called keuken") and the AI didn't already propose an add_knowledge
        # action, run a mini LLM call to extract the name alias automatically.
        learned_fact: dict[str, Any] | None = None
        if (
            _CORRECTION_SIGNALS_RE.search(user_prompt)
            and not any(
                a.get("type") == "add_knowledge"
                for a in (plan_block or {}).get("actions", [])
            )
        ):
            _LOGGER.info("Kyber: correction signal detected — running fact extraction")
            fact = await _try_extract_learned_fact(
                hass,
                entity_id,
                user_prompt,
                conversation_block,
            )
            if fact:
                _LOGGER.info(
                    "Kyber: extracted learned fact: %s → %s",
                    fact.get("user_term"), fact.get("subject"),
                )
                learned_fact = {
                    "summary": f"Remember: '{fact['user_term']}' → '{fact['subject']}'",
                    "actions": [{
                        "type": "add_knowledge",
                        "category": fact["category"],
                        "subject": fact["subject"],
                        "content": fact["content"],
                        "tags": fact["tags"],
                        "current_state": "(not learned)",
                        "new_state": "Remembered for next time",
                        "description": f"Save alias: {fact['user_term']} → {fact['subject']}",
                    }],
                }
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
            "learned_fact": learned_fact,
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
