"""Response processing helpers extracted from http_api.py."""
from __future__ import annotations

import json
import re
from typing import Any

_YAML_BLOCK_RE = re.compile(r"```yaml\s*([\s\S]+?)\s*```", re.IGNORECASE)
_PLAN_BLOCK_RE = re.compile(r"```plan\s*([\s\S]+?)\s*```", re.IGNORECASE)
# Bare ## Plan\n{...} blocks emitted by models that skip the backtick fences
_BARE_PLAN_RE = re.compile(r"^#{1,3}\s*Plan\s*\n(\{[\s\S]*?\n\})\s*(?=\n|$)", re.MULTILINE)
_CLARIFY_BLOCK_RE = re.compile(r"```clarify\s*([\s\S]+?)\s*```", re.IGNORECASE)
# Match [TOOL_CALL: ...] tolerating O/0 confusion from small models.
# NOTE: Use .*? (not [^]]*?) so JSON arrays inside the body (e.g. "fields": ["x"])
# are matched correctly — [^]]* would stop at the first ] inside the JSON.
# Also tolerates models that emit `}}` instead of `}]` or omit the closing `]` at EOL.
_TOOL_CALL_RE = re.compile(
    r"\[T[O0]{2}L[_\-]CALL:\s*(\{.*?\})\}?\s*(?:\]|(?=\n|\Z))",
    re.DOTALL | re.IGNORECASE,
)
# Match [TOOL_RESULT: ...] with same tolerance
_TOOL_RESULT_STRIP_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?", re.IGNORECASE)
_TOOL_RESULT_ECHO_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?.*?(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE)
_TOOL_CALL_MAX_ROUNDS = 5


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
    """Extract the first ```plan``` JSON block from a response string.

    Also handles bare ``## Plan\\n{...}`` blocks that some models emit without
    backtick fences.
    """
    match = _PLAN_BLOCK_RE.search(text)
    if not match:
        match = _BARE_PLAN_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def _strip_plan_block(text: str) -> str:
    """Remove ```plan``` and bare ## Plan blocks from response text so the
    frontend does not render raw JSON in the chat bubble (the plan card handles it).
    """
    text = _PLAN_BLOCK_RE.sub("", text)
    text = _BARE_PLAN_RE.sub("", text)
    return text.strip()


_BARE_FENCE_RE = re.compile(r"```(?!plan|clarify|yaml|json)([a-z]*)\n([\s\S]+?)\n```", re.IGNORECASE)
_ACTION_TYPE_RE = re.compile(r'"type"\s*:\s*"(call_service|assign_area|rename_entity|create_\w+|update_\w+|delete_\w+|add_knowledge|update_knowledge|delete_knowledge|open_dashboard|open_editor)"')

# Detect user intent to edit an automation/script YAML — used to lazy-load editor guidance.
_AUTOMATION_EDIT_RE = re.compile(
    r'(?:'
    r'(?:edit|modify|update|change|bewerk|aanpas|aanpassen|wijzig|open|pas\s+aan)'
    r'.{0,80}(?:automat|script|flow)'
    r'|'
    r'(?:automat|script|flow).{0,80}'
    r'(?:edit|modify|update|change|bewerk|aanpas|aanpassen|wijzig|open|pas\s+aan)'
    r')',
    re.I | re.S,
)


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
