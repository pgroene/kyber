"""Response processing helpers extracted from http_api.py."""
from __future__ import annotations

import json
import re
from typing import Any

from .const import TOOL_CALL_MAX_ROUNDS

_YAML_BLOCK_RE = re.compile(r"```yaml\s*([\s\S]+?)\s*```", re.IGNORECASE)
_PLAN_BLOCK_RE = re.compile(r"```plan\s*([\s\S]+?)\s*```", re.IGNORECASE)
# Bare ## Plan\n{...} blocks emitted by models that skip the backtick fences
_BARE_PLAN_RE = re.compile(r"^#{1,3}\s*Plan\s*\n(\{[\s\S]*?\n\})\s*(?=\n|$)", re.MULTILINE)
_CLARIFY_BLOCK_RE = re.compile(r"```clarify\s*([\s\S]+?)\s*```", re.IGNORECASE)
# Matches the start of a tool-call block in any format a model might emit:
#   [TOOL_CALL: {...}]         standard brackets
#   [TOOL-CALL: {...}]         dash separator
#   [T00L_CALL: {...}]         O/0 confusion
#   ## TOOL_CALL: {...}        markdown heading (1–3 #)
#   **TOOL_CALL**: {...}       bold / **TOOL_CALL:** {...}
#   *TOOL_CALL*: {...}         italic
#   TOOL_CALL: {...}           bare (no decoration)
#   tool_call: {...}           lowercase
#   <tool_call>...</tool_call> XML tag
# The lookahead (?=\{) ensures we only match when a JSON body follows.
_TOOL_CALL_PREFIX_RE = re.compile(
    r"(?:"
    # XML opening tags: <tool_call>, <toolcall>, <tool-call>
    r"<tool[_\-]?call>\s*"
    r"|"
    # All keyword variants (decorated or bare)
    r"(?:#{1,3}[\t ]*|\[[\t ]*|\*{1,2})?"   # optional prefix: ###  [  **
    r"T[O0]{2}L[_\- ]?CALL"                  # TOOL_CALL core (O/0 + sep variants)
    r"(?:\*+)?:?(?:\*+)?"                    # optional closing stars / colon
    r"[\t ]*"                                # optional trailing horizontal whitespace
    r")"
    r"(?=\{)",
    re.IGNORECASE,
)
# Matches closing XML tool-call tag or bracket (used in _strip_tool_calls)
_TOOL_CALL_CLOSE_RE = re.compile(r"\s*(?:\]|</tool[_\-]?call>)\s*", re.IGNORECASE)

# Match [TOOL_RESULT: ...] with same tolerance
_TOOL_RESULT_STRIP_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?", re.IGNORECASE)
_TOOL_RESULT_ECHO_RE = re.compile(r"\[T[O0]{2}L[_\-]RESULT:[^\]]*?\][^\n]*\n?.*?(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE)
_TOOL_CALL_MAX_ROUNDS = TOOL_CALL_MAX_ROUNDS


def _find_json_end(text: str, start: int) -> int:
    """Starting at `start` (the opening `{`), return the index just after the
    matching closing `}`.  Returns `start` on failure (unmatched brace)."""
    depth = 0
    i = start
    in_str = False
    escaped = False
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
        elif ch == "\\" and in_str:
            escaped = True
        elif ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return start  # unmatched brace


def _parse_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract all tool-call JSON blocks from a response.

    Supports every format variant a model might emit:
      [TOOL_CALL: {...}]         standard
      [TOOL-CALL: {...}]         dash separator
      [T00L_CALL: {...}]         O/0 confusion
      ## TOOL_CALL: {...}        markdown heading
      **TOOL_CALL**: {...}       bold
      TOOL_CALL: {...}           bare
      tool_call: {...}           lowercase
      <tool_call>...</tool_call> XML
    Uses bracket-depth counting so nested JSON (e.g. service_data) is parsed correctly.
    """
    calls = []
    for m in _TOOL_CALL_PREFIX_RE.finditer(text):
        end = _find_json_end(text, m.end())
        if end == m.end():
            continue
        try:
            calls.append(json.loads(text[m.end():end]))
        except (json.JSONDecodeError, ValueError):
            pass
    return calls


def _strip_tool_calls(text: str) -> str:
    """Remove all tool-call blocks (any format) from a response string."""
    spans: list[tuple[int, int]] = []
    for m in _TOOL_CALL_PREFIX_RE.finditer(text):
        # Back up to start of line unless real text precedes the match
        line_start = text.rfind("\n", 0, m.start())
        span_start = (line_start + 1) if line_start >= 0 else 0
        prefix_before = text[span_start:m.start()]
        if not re.match(r"^[\s#*\[\]<>]*$", prefix_before):
            span_start = m.start()

        json_end = _find_json_end(text, m.end())
        if json_end == m.end():
            continue

        span_end = json_end
        # Consume optional closing ] or </tool_call> (with surrounding whitespace)
        close = re.match(r"\s*(?:\]|</tool[_\-]?call>)\s*", text[span_end:], re.IGNORECASE)
        if close:
            span_end += close.end()
        # Eat one trailing newline
        if span_end < len(text) and text[span_end] == "\n":
            span_end += 1

        spans.append((span_start, span_end))

    if not spans:
        return text.strip()

    # Sort and merge overlapping spans
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    parts: list[str] = []
    prev = 0
    for s, e in merged:
        parts.append(text[prev:s])
        prev = e
    parts.append(text[prev:])
    return "".join(parts).strip()



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
# Matches ```json blocks — used to detect plan-shaped JSON emitted with wrong language tag.
_JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]+?)\s*```", re.IGNORECASE)
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


def _normalize_json_plan_blocks(text: str) -> str:
    """Rewrap ```json blocks that are plan-shaped as ```plan blocks.

    The AI occasionally emits the plan JSON inside a ```json fence instead of
    a ```plan fence (attempting to "comply" with "do not output a plan block"
    while still using the plan structure).  This makes them invisible to
    _extract_plan_block and bypasses the informational guard.  Convert them here
    so the rest of the pipeline handles them correctly.
    """
    if _PLAN_BLOCK_RE.search(text):
        return text  # already a real plan block

    for m in _JSON_BLOCK_RE.finditer(text):
        body = m.group(1).strip()
        try:
            obj = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            continue
        # Plan shape: has "summary" key and "actions" list (even if empty)
        if isinstance(obj, dict) and "summary" in obj and "actions" in obj:
            return text.replace(m.group(0), f"```plan\n{body}\n```")
    return text


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
    r"\b(?:to\s+)?(?:max(?:imum)?|full(?:\s+brightness)?|brightest|100\s*%"
    r"|maximaal|volledig|helemaal\s+aan|vol(?:\s+aan)?|zo\s+fel\s+mogelijk)\b",
    re.IGNORECASE,
)
_DIM_INTENT_RE = re.compile(
    r"\b(?:dim(?:med)?|low(?:est)?|min(?:imum)?|10\s*%"
    r"|gedimd|zwak(?:ste)?|minimaal|zo\s+laag\s+mogelijk)\b",
    re.IGNORECASE,
)


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
