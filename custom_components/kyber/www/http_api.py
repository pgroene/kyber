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

from .const import (
    AUTOMATION_EDITOR_GUIDANCE,
    CONF_AI_TASK_ENTITY_ID,
    DOMAIN,
    KNOWLEDGE_BUDGET_CHARS,
    LOVELACE_CARDS_REFERENCE,
    MAX_INSTRUCTIONS_CHARS,
    MAX_TOOL_RESULT_CHARS,
    SYSTEM_PROMPT_TEMPLATE,
)
from .knowledge import CATEGORIES as KNOWLEDGE_CATEGORIES, get_store as get_knowledge_store
from .language_hints import detect_language, get_hints_for_language, language_display_name
from .analyzer import analyze_automations as _analyze_automations
from .source import (
    read_automations as _src_read_automations,
    read_scripts as _src_read_scripts,
    read_blueprints as _src_read_blueprints,
    read_blueprint as _src_read_blueprint,
)
from . import deep_analyzer as _deep
from .response_processing import (
    _YAML_BLOCK_RE, _PLAN_BLOCK_RE, _CLARIFY_BLOCK_RE,
    _TOOL_RESULT_STRIP_RE, _TOOL_RESULT_ECHO_RE, _TOOL_CALL_MAX_ROUNDS,
    _BARE_FENCE_RE, _ACTION_TYPE_RE, _AUTOMATION_EDIT_RE,
    _parse_tool_calls, _strip_tool_calls, _extract_yaml_blocks, _extract_plan_block,
    _rewrap_bare_action_fences, _NARRATION_PATTERNS, _BARE_JSON_TOOL_RESULT_RE,
    _strip_role_echo_prefix, _BRIGHTNESS_INTENT_RE, _DIM_INTENT_RE,
    _augment_brightness_intent, _extract_clarify_block, _strip_plan_block,
)
from .intent_and_context import (
    _QUICK_CREATE_AREA_RE, _try_quick_intent,
    _ACTION_KEYWORDS, _ACTION_RE_PATTERNS,
    _classify_intent,
    _build_home_state_by_area, _build_context,
)
from .tool_execution import _tool_result_summary, _state_matches, _execute_tool, _async_execute_tool, _ASYNC_TOOLS, TOOL_ALIASES, resolve_tool_call
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
from .action_execution import (
    _CONFIG_CHANGING_ACTION_TYPES, _DESTRUCTIVE_SERVICES,
    _action_requires_approval, _annotate_plan_approval, _build_service_undo,
    KyberExecuteView,
)
from .knowledge_integration import (
    _FACT_EXTRACTION_PROMPT, _try_extract_learned_fact,
    KyberKnowledgeView, KyberKnowledgeAnalyzeView,
    KyberKnowledgeDeepAnalyzeView, KyberKnowledgeFeedbackView, KyberKnowledgePurgeView,
)
from .api_utilities import (
    _PROGRESS_KEY,
    _progress_emit, _progress_complete,
    KyberProgressView, KyberSaveView, _SUMMARIZE_SYSTEM_PROMPT, KyberSummarizeView,
)

_LOGGER = logging.getLogger(__name__)

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


# Appended to the tool-exchange when we need a plain-text synthesis pass
# (model looped on tool calls and never wrote a prose answer).
_SYNTHESIS_INSTRUCTIONS = (
    "\n\n[SYSTEM: You already have all the data you need from the tool results "
    "shown above. Answer the user's question directly in plain text now. "
    "IMPORTANT: If the tool results were empty or returned 0 entities/results, "
    "do NOT invent entity names, states, or make up answers — honestly say you "
    "couldn't find the information and suggest trying a more specific search. "
    "Do NOT output any [TOOL_CALL:] blocks — only a prose answer. "
    "List EVERY item from the results; do not truncate with '...' or 'and X more'.]\n"
    "Assistant:"
)


def _build_loop_redirect(tool_calls_filtered: list[tuple[str, dict]]) -> str | None:
    """Build a system hint to redirect the model when it repeated tool calls.

    Returns a string to append to the tool_exchange, or None if no targeted
    redirect is available (fall through to synthesis in that case).
    """
    for _, call in tool_calls_filtered:
        name = call.get("name", "")
        if name == "get_area_entities":
            area = call.get("area", "")
            return (
                f"\n[SYSTEM: get_area_entities(area='{area}') returned 0 entities — "
                f"same empty result as the previous round. "
                f"Do NOT call get_area_entities again. "
                f"Follow the fallback rules: call search_entities(query='{area}') "
                f"to find entities whose entity_id or friendly name contains this room word. "
                f"If that also returns nothing, call search_knowledge(query='{area}').]\n"
                f"Assistant:"
            )
        if name == "search_entities":
            q = call.get("query") or ", ".join(call.get("queries") or [])
            return (
                f"\n[SYSTEM: search_entities for '{q}' returned the same result as the "
                f"previous round. Try a different approach: broaden the search term, "
                f"try search_knowledge(query='{q}'), or use list_entities_by_domain.]\n"
                f"Assistant:"
            )
    return None


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
_MAX_INSTRUCTIONS_CHARS = MAX_INSTRUCTIONS_CHARS
# Reserve budget for knowledge facts so they survive the loop's re-truncation.
# Base prompt is capped at (_MAX_INSTRUCTIONS_CHARS - _KNOWLEDGE_BUDGET); knowledge
# is then appended within the remaining space, keeping total ≤ _MAX_INSTRUCTIONS_CHARS.
_KNOWLEDGE_BUDGET = KNOWLEDGE_BUDGET_CHARS
_BASE_INSTRUCTIONS_CHARS = _MAX_INSTRUCTIONS_CHARS - _KNOWLEDGE_BUDGET  # 30 000
_MAX_TOOL_RESULT_CHARS = MAX_TOOL_RESULT_CHARS


async def _auto_record_search_alias(kstore: Any, query: str, entity_ids: list[str]) -> None:
    """Silently save a search query → entity mapping as a knowledge alias.

    Called fire-and-forget after search_entities returns 1–3 results so future
    turns can recall the mapping without searching again.  Skips if an identical
    fact (same subject) already exists.
    """
    try:
        await kstore.async_load()
        query_lower = query.lower()
        # Skip if already recorded: any fact with matching subject
        existing = await kstore.async_semantic_search(query_lower, min_score=0.95)
        for e in existing:
            if e.get("category") == "entity_alias" and e.get("subject", "").lower() == query_lower:
                return
        entity_str = ", ".join(entity_ids)
        await kstore.async_add(
            "entity_alias",
            f"When user searches for '{query}', the matching entit{'y is' if len(entity_ids) == 1 else 'ies are'}: {entity_str}",
            subject=query_lower,
            tags=query_lower.split() + entity_ids,
            source="search_alias_auto",
            confidence=0.7,
        )
        _LOGGER.debug("Kyber: auto-saved search alias '%s' → %s", query, entity_str)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber: auto-record search alias failed (non-critical): %s", err)


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
        # Sanitize to safe alphanumeric + hyphen/underscore only.
        # request_id is used as a dict key and appears in debug filenames,
        # so we must prevent path-traversal and injection payloads.
        request_id = re.sub(r"[^a-zA-Z0-9_\-]", "", request_id)[:64]
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
            # Drop low-relevance facts that add noise without helping.
            # Always keep entity_alias / area_alias regardless of score since
            # they answer "what is 'the TV'?" type questions definitively.
            # IMPORTANT: do NOT fall back to "show top-2 regardless" —
            # injecting low-score irrelevant facts confuses the model into
            # hallucinating entity IDs from unrelated context.
            _MIN_KNOWLEDGE_SCORE = 0.45
            _ABS_FLOOR_SCORE = 0.15  # hard floor: never inject below this
            filtered_knowledge = [
                e for e in relevant_knowledge
                if float(e.get("_score") or 0) >= _MIN_KNOWLEDGE_SCORE
                or e.get("category") in ("entity_alias", "area_alias")
            ]
            # If nothing passed the soft threshold, only keep facts above the
            # absolute floor (never show completely irrelevant facts).
            if not filtered_knowledge:
                filtered_knowledge = [
                    e for e in relevant_knowledge
                    if float(e.get("_score") or 0) >= _ABS_FLOOR_SCORE
                    or e.get("category") in ("entity_alias", "area_alias")
                ]
            relevant_knowledge = filtered_knowledge  # empty = inject nothing

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

        # Inject language-specific vocabulary hints when the user writes in a
        # non-English language.  These are stored as knowledge entries with
        # category="language_hint" and are retrieved deterministically by tag
        # (not by TF-IDF score) so they are always complete and consistent.
        _detected_lang = detect_language(user_prompt)
        if _detected_lang != "en":
            _lang_hints = await kstore.async_get_by_tag(
                _detected_lang, category="language_hint"
            )
            if _lang_hints:
                _lang_name = language_display_name(_detected_lang)
                _LOGGER.info(
                    "Kyber: detected language '%s' (%s) — injecting %d vocabulary hints",
                    _detected_lang, _lang_name, len(_lang_hints),
                )
                _progress_emit(hass, request_id, {
                    "type": "info",
                    "message": f"Detected language: {_lang_name} — injecting vocabulary hints",
                })
                lang_lines = [
                    "",
                    f"## Language hints ({_lang_name})",
                    "The user is writing in "
                    + _lang_name
                    + ". Use the vocabulary below to map their words to HA domains, "
                    "service calls, and entity types. These hints are helpers — always "
                    "confirm entity IDs with tool calls; never guess them.",
                ]
                for hint_entry in _lang_hints:
                    lang_lines.append(f"- {hint_entry.get('content', '')}")
                instructions = instructions + "\n" + "\n".join(lang_lines) + "\n"

        # Tool-calling loop — the AI may request live HA data via [TOOL_CALL: {...}]
        # We execute tools and re-send up to _TOOL_CALL_MAX_ROUNDS times.
        tool_exchange = ""  # accumulated tool call/result pairs appended to instructions
        tool_log: list[dict[str, Any]] = []  # summary of tool calls for UI feedback
        executed_calls_cache: dict[str, str] = {}  # signature → result str (dedup across rounds)
        response_text = ""
        _loop_redirect_given = False  # allow one redirect hint before falling back to synthesis
        _auto_plan_rescued = False    # set when call_service tool call is auto-converted to plan
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

            response_text = result.data if isinstance(result.data, str) else (
                str(result.data) if result.data is not None else ""
            )
            if not isinstance(result.data, str):
                _LOGGER.warning(
                    "Kyber: AI result.data is not str (type=%s); coerced to string",
                    type(result.data).__name__,
                )
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
                # Resolve aliases before deciding sync vs async path
                call = resolve_tool_call(call)
                if call.get("name") in _ASYNC_TOOLS:
                    result = await _async_execute_tool(hass, call)
                else:
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

                # Auto-plan rescue: when call_service was used as a tool and the
                # backend auto-built a plan, inject it as the final response now.
                if isinstance(tool_result_data, dict) and tool_result_data.get("_auto_plan"):
                    plan_json = tool_result_data.get("_plan_json", "")
                    if plan_json:
                        _LOGGER.info("Kyber: auto-converting call_service tool call to plan block")
                        response_text = f"```plan\n{plan_json}\n```"
                        intent = "action"  # ensure informational guard doesn't strip it
                        _auto_plan_rescued = True
                        break  # exit tool-results inner loop

                # Auto-record entity aliases: when search_entities returns 1–3 primary
                # entities, silently save the query→entity mapping so future turns don't
                # need to search again.
                if call.get("name") == "search_entities" and isinstance(tool_result_data, dict):
                    _primary_eids = [
                        k for k in tool_result_data
                        if isinstance(k, str) and "." in k and not k.startswith("_")
                    ]
                    if 1 <= len(_primary_eids) <= 3:
                        _q = (call.get("query") or ", ".join(call.get("queries") or [])).strip()
                        if _q:
                            asyncio.ensure_future(
                                _auto_record_search_alias(kstore, _q, _primary_eids)
                            )

                # Also record aliases from get_entity_state: when entity_id words
                # overlap with the user prompt we know the user was asking about that
                # entity — save the mapping so next time we don't need to search.
                if (
                    call.get("name") == "get_entity_state"
                    and isinstance(tool_result_data, dict)
                    and "error" not in tool_result_data
                ):
                    _eid = call.get("entity_id", "")
                    if _eid and "." in _eid:
                        # Extract meaningful words from the entity_id (ignore domain prefix)
                        _eid_words = set(re.split(r"[._]", _eid.split(".", 1)[-1].lower()))
                        _eid_words.discard("")
                        # Build the prompt search space: current prompt + last history message
                        _prompt_words = set(re.split(r"\W+", user_prompt.lower()))
                        _last_hist = ""
                        if history:
                            _last_hist = str(history[-1].get("content", "")).lower()
                        _hist_words = set(re.split(r"\W+", _last_hist))
                        _all_context_words = _prompt_words | _hist_words
                        # Require at least one meaningful entity word (>3 chars) in context
                        _overlap = {
                            w for w in _eid_words
                            if len(w) > 3 and w in _all_context_words
                        }
                        if _overlap:
                            # Build a natural alias from the overlapping context words
                            _alias_words = sorted(_overlap, key=lambda w: -len(w))
                            _alias_q = " ".join(_alias_words[:3])
                            asyncio.ensure_future(
                                _auto_record_search_alias(kstore, _alias_q, [_eid])
                            )

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

            # Auto-plan rescue already set response_text — exit the round loop.
            if _auto_plan_rescued:
                break

            # Stop early if model is looping (every call was a duplicate)
            if new_call_count == 0:
                # First time: try a targeted redirect hint so the model can
                # try a different tool before we fall back to synthesis.
                if not _loop_redirect_given:
                    redirect = _build_loop_redirect(tool_calls_filtered)
                    if redirect is not None:
                        _loop_redirect_given = True
                        tool_exchange += redirect
                        _progress_emit(hass, request_id, {
                            "type": "info",
                            "message": "Redirecting — trying alternative search approach.",
                        })
                        continue  # one more AI round with the redirect hint

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
                            else (str(synth_result.data) if synth_result.data is not None else "")
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

        # NOTE: plan block is stripped from response_text AFTER the informational guard
        # (see below) so that a mis-classified query that produces only a plan doesn't
        # result in an empty response.

        # Strip any [TOOL_RESULT: ...] or [T00L_RESULT: ...] lines the model echoed back.
        response_text = _TOOL_RESULT_STRIP_RE.sub("", response_text).strip()
        # Also strip multi-line [TOOL_RESULT: ...] payloads (block form)
        response_text = re.sub(
            r"\[T[O0]{2}L[_\-]RESULT:[^\]]*\][^\n]*\n(?:.*?\n)*?(?=\n[A-Z]|\n\n|\Z)",
            "",
            response_text,
            flags=re.IGNORECASE,
        ).strip()

        # Strip any unparsed tool calls in any format from the final response.
        response_text = _strip_tool_calls(response_text)

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

        # Strip leftover bare JSON-result lines where the key looks like an entity_id (domain.name)
        # or known result wrapper keys. Covers all domains the model might echo back.
        response_text = re.sub(
            r"^\s*\{\"[a-z_]+\.[a-z0-9_][^\"]*\":[^\n]*\}\s*$",
            "",
            response_text,
            flags=re.MULTILINE,
        ).strip()
        response_text = re.sub(
            r"^\s*\{\"(?:_truncated|info|result|area|entities|count)[^\n]*\}\s*$",
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

        # Remove plan block from displayed response — do this AFTER the informational
        # guard so that a dropped plan doesn't leave response_text empty (the raw plan
        # JSON stays in the text, which is better than a blank response).
        if plan_block:
            response_text = _strip_plan_block(response_text)

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
