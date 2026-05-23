"""Intent classification and context building helpers extracted from http_api.py."""
from __future__ import annotations

import json
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .const import SYSTEM_PROMPT_TEMPLATE


def _safe_format(template: str, **kwargs: str) -> str:
    """Format a template string that may contain literal {…} JSON examples.

    Uses plain str.replace() for the known substitution keys so that any
    un-doubled braces in the prompt text (e.g. ``service_data={"key":"val"}``)
    do not raise KeyError.  After substitution, ``{{`` / ``}}`` are unescaped
    to literal ``{`` / ``}`` so authors can still write escaped examples.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", value)
    return result.replace("{{", "{").replace("}}", "}")


def _sanitize_prompt_value(text: str, max_len: int = 0) -> str:
    """Sanitize a user-supplied string before embedding it in the system prompt."""
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    cleaned = cleaned.strip()
    if max_len > 0 and len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned


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
    # Media / device control
    "start", "stop", "pause", "resume", "play", "mute", "unmute", "skip", "next",
    "volume", "restart", "reboot", "activate", "deactivate",
    "run", "launch", "begin",
    # Dutch start/run variants
    "starten", "opstarten", "opstart",
    # Confirmation words — user is approving a pending action
    "yes", "ok", "sure", "go ahead", "do it", "confirm", "execute", "proceed",
    "ja", "ja doe maar", "doe maar", "prima", "goed",  # Dutch confirmations
    # Location statements — user tells the system where a device lives.
    # These are multi-word so they require the exact phrase (e.g. "staat in" won't
    # match "wat staat er in" because there is no contiguous "staat in").
    "staat in", "zit in", "hangt in", "ligt in", "hoort in", "staan in",  # Dutch
    "is in the", "belongs in", "located in", "placed in",                  # English
})

# Regex patterns for split-word action intent (e.g. "turn those off", "switch it on")
_ACTION_RE_PATTERNS: tuple = (
    re.compile(r"\bturn\b.{0,30}\b(on|off)\b", re.IGNORECASE),
    re.compile(r"\bswitch\b.{0,30}\b(on|off)\b", re.IGNORECASE),
    re.compile(r"\b(on|off)\b.{0,30}\bturn\b", re.IGNORECASE),
    re.compile(r"\bzet\b.{0,20}\b(aan|uit)\b", re.IGNORECASE),   # Dutch: zet ... aan/uit
    re.compile(r"\b(aan|uit)\s*doen\b", re.IGNORECASE),           # Dutch: aan/uit doen  ("muziek aan doen")
    re.compile(r"\bdoe\b.{0,30}\b(aan|uit)\b", re.IGNORECASE),    # Dutch: doe ... aan/uit
    re.compile(r"\b(aan|uit)zetten\b", re.IGNORECASE),             # Dutch: aanzetten / uitzetten (one word)
    re.compile(r"\bzet\b.{0,30}\b(aan|uit)\b", re.IGNORECASE),    # Dutch: zet X aan (already covered by keyword but also split)
    # Location statements — user asserts where a device lives.
    # "de espresso machine staat in de keuken", "the speaker is in the hallway"
    # Using multi-word keyword patterns (handled in _ACTION_KEYWORDS above):
    #   "staat in", "zit in", "hangt in", "ligt in", "hoort in", "is in the", etc.
    # The patterns below catch variants with indirect phrasing that the keywords miss.
    re.compile(
        r"\b(geplaatst|opgehangen|neergezet|geïnstalleerd)\b.{0,10}\bin\b",
        re.IGNORECASE,
    ),  # Dutch past-participle placement: "is geplaatst in", "hangt geïnstalleerd in"
    re.compile(
        r"\b(?:the|my|our|de|het|mijn|onze)\s+\w[\w\s]{1,40}\b"
        r"\s+(?:belongs?|goes?|is\s+placed?|is\s+located?)\s+in\b",
        re.IGNORECASE,
    ),  # EN "the X belongs in / is placed in"
)


# Prompts that start with these question/informational phrases should never be
# classified as ACTION even if they contain action keywords (e.g. "tell me if
# the light is on" contains "on" but is clearly informational).
_INFORMATIONAL_PREFIX_RE = re.compile(
    r"^\s*("
    r"what(\s+is|\s+are|\s+does|\s+did|\s+can|\s+will|\s+'s|\s+time|\s+lights?)?"
    r"|show(\s+me)?"
    r"|tell\s+me"
    r"|does\s+(?:the|a|my|it|this)"
    r"|is\s+(?:the|a|my|it|there|this)"
    r"|are\s+(?:the|my|there|all|any|these|those)"
    r"|which"
    r"|how\s+(?:many|much|do|does|can|is|are)"
    r"|why"
    r"|when\s+(?:is|does|did|will|do)"
    r"|where\s+(?:is|are|can)"
    r")\b",
    re.IGNORECASE,
)


def _classify_intent(user_prompt: str) -> str:
    """Return 'action' if the prompt requests a change, otherwise 'informational'."""
    lower = user_prompt.lower()
    # Guard: prompts that start with an informational question word are never
    # actions, even if they contain action vocabulary (e.g. "tell me if the
    # light is on", "what does turn on do?", "show me what's playing").
    if _INFORMATIONAL_PREFIX_RE.match(lower):
        return "informational"
    for kw in _ACTION_KEYWORDS:
        if " " in kw:
            # Multi-word phrase: plain substring match is fine
            if kw in lower:
                return "action"
        else:
            # Single word: require word boundary to avoid false positives
            # (e.g. "play" must not match "playing", "stop" not "stopping")
            if re.search(r"\b" + re.escape(kw) + r"\b", lower):
                return "action"
    if any(p.search(lower) for p in _ACTION_RE_PATTERNS):
        return "action"
    return "informational"


def _build_home_state_by_area(
    entity_reg: er.EntityRegistry,
    device_reg: dr.DeviceRegistry,
    area_by_id: dict[str, str],
    all_states: list,
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

    for state in all_states:
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
        if not area_id and entry and entry.device_id:
            device = device_reg.async_get(entry.device_id)
            if device:
                area_id = device.area_id
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
                _area(area_name)["media"].append(state.state)  # only state string, no entity names or titles

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
        if d["media"]:
            parts.append(f"📺 {len(d['media'])} playing")
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
    device_reg = dr.async_get(hass)
    label_reg = lr.async_get(hass)

    areas = area_reg.async_list_areas()
    # Deduplicate areas whose names are identical when lowercased (e.g. "Zitkamer" vs "zitkamer").
    # Keep the one with the most-capitalised / longer name; drop pure-lowercase duplicates.
    _seen_area_names: dict[str, Any] = {}
    for _a in areas:
        _key = _a.name.lower().replace(" ", "_")
        if _key not in _seen_area_names:
            _seen_area_names[_key] = _a
        else:
            # Prefer the area whose name contains uppercase (i.e. the "display" name)
            if _a.name != _a.name.lower():
                _seen_area_names[_key] = _a
    areas = list(_seen_area_names.values())
    area_list = "\n".join(
        f"- {_sanitize_prompt_value(a.name, max_len=60)} → {_sanitize_prompt_value(a.id, max_len=60)}"
        for a in areas
    ) or "(no areas)"
    area_by_id = {a.id: _sanitize_prompt_value(a.name, max_len=60) for a in areas}

    labels = label_reg.async_list_labels()

    automation_count = 0
    script_count = 0
    domain_counts: dict[str, int] = {}

    all_states = hass.states.async_all()
    entity_count = 0

    for state in sorted(all_states, key=lambda s: s.entity_id):
        domain = state.entity_id.split(".")[0]
        if state.entity_id.startswith("automation."):
            automation_count += 1
        elif state.entity_id.startswith("script."):
            script_count += 1
        else:
            entity_count += 1
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

    # Domain stats: top 10 by count
    sorted_domains = sorted(domain_counts.items(), key=lambda x: -x[1])
    stats_parts = [f"{d}:{c}" for d, c in sorted_domains[:10]]
    if len(sorted_domains) > 10:
        stats_parts.append(f"+{len(sorted_domains) - 10} more")
    entity_stats = f"{entity_count} entities"
    if stats_parts:
        entity_stats += f" ({', '.join(stats_parts)})"

    # Per-area home state
    home_state_by_area, area_stats = _build_home_state_by_area(entity_reg, device_reg, area_by_id, all_states)
    notable_state_block = ""
    if home_state_by_area != "(no area state available)":
        notable_state_block = f"\n### Current Home State (notable only)\n{home_state_by_area}\n"

    home_summary = (
        f"**Home:** {len(areas)} areas · {len(labels)} labels · "
        f"{automation_count} automations · {script_count} scripts · {entity_stats}"
    )

    # Compact area list — model needs this to call get_area_entities with the right area_id.
    areas_block = "**Areas:** " + ", ".join(
        f"{_sanitize_prompt_value(a.name, max_len=60)} ({_sanitize_prompt_value(a.id, max_len=60)})"
        for a in sorted(areas, key=lambda a: a.name)
    ) if areas else "**Areas:** (no areas)"

    # Labels block — list names so model can reference them directly (up to 30)
    label_list = list(labels)
    if label_list:
        label_names = ", ".join(
            _sanitize_prompt_value(lbl.name, max_len=60)
            for lbl in sorted(label_list, key=lambda l: l.name)[:30]
        )
        suffix = f" (+{len(label_list) - 30} more)" if len(label_list) > 30 else ""
        labels_block = f"\n**Labels:** {label_names}{suffix}"
    else:
        labels_block = ""

    # Zones block — list GPS zones (skip passive/hidden ones like zone.home_2 helpers)
    zone_states = sorted(
        [s for s in all_states if s.entity_id.startswith("zone.") and not s.attributes.get("passive", False)],
        key=lambda s: s.attributes.get("friendly_name", s.entity_id),
    )
    if zone_states:
        zone_parts = []
        for zs in zone_states:
            zname = _sanitize_prompt_value(
                str(zs.attributes.get("friendly_name") or zs.entity_id.split(".", 1)[-1]), max_len=60
            )
            icon = zs.attributes.get("icon", "")
            icon_str = f" {icon}" if icon else ""
            zone_parts.append(f"{zname}{icon_str}")
        zones_block = "\n**Zones (GPS):** " + ", ".join(zone_parts)
    else:
        zones_block = ""

    # Person locations — add to notable state
    person_location_lines: list[str] = []
    for s in sorted(all_states, key=lambda s: s.entity_id):
        if not s.entity_id.startswith("person."):
            continue
        pname = _sanitize_prompt_value(
            str(s.attributes.get("friendly_name") or s.entity_id.split(".", 1)[-1]), max_len=40
        )
        loc = _sanitize_prompt_value(str(s.state), max_len=60) if s.state not in ("unknown", "unavailable", "") else None
        if loc:
            person_location_lines.append(f"  {pname}: {loc}")
    if person_location_lines:
        person_block = "\n### Person Locations\n" + "\n".join(person_location_lines) + "\n"
        notable_state_block = person_block + notable_state_block

    tz_name = str(getattr(hass.config, "time_zone", "UTC") or "UTC")
    timezone_block = f"**Timezone:** {tz_name} — display all times in this timezone, not UTC.\n"

    context_stats: dict[str, Any] = {
        "entity_count": entity_count,
        "automation_count": automation_count,
        "area_count": len(areas),
        "zone_count": len(zone_states),
        "lights_on": area_stats["total_lights_on"],
        "unavailable_count": area_stats["unavailable_count"],
        "low_battery_count": area_stats["low_battery_count"],
    }

    context = _safe_format(
        SYSTEM_PROMPT_TEMPLATE,
        home_summary=home_summary,
        areas_block="\n" + areas_block,
        labels_block=labels_block,
        zones_block=zones_block,
        timezone_block=timezone_block,
        notable_state_block=notable_state_block,
    )
    context_stats["prompt_chars"] = len(context)
    return context, context_stats
