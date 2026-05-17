"""Automation / scene / script analyzer for knowledge inference.

Scans existing HA automations, scenes, and scripts to infer relationships
that aren't in the registries:
- Entities frequently controlled together â†’ likely same area or scene group
- Trigger â†’ action pairs that reveal device dependencies (turn on switch.X
  then turn on light.Y â†’ switch.X powers light.Y)
- Area inferences from automation/scene names mentioning rooms

Each inferred fact is returned as a KnowledgeStore-shaped dict (NOT yet
persisted) so the UI can present them for user approval.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Words to ignore when extracting room hints from names.
_STOPWORDS = {
    "automation", "scene", "script", "schedule", "morning", "evening",
    "night", "day", "on", "off", "turn", "toggle", "set", "the", "a",
    "and", "or", "if", "then", "when", "auto", "smart", "home", "ha",
    "light", "lights", "switch", "switches", "sensor", "sensors",
    "for", "to", "from", "with", "trigger", "test", "demo", "new", "old",
}


def _tokens(text: str) -> list[str]:
    """Split a name/id into lowercase tokens, dropping stopwords."""
    if not text:
        return []
    parts = re.split(r"[\s._\-/]+", text.lower())
    return [p for p in parts if p and p not in _STOPWORDS and not p.isdigit()]


def _entities_in_config(cfg: Any) -> list[str]:
    """Walk an arbitrary config structure (dict/list/str) and return entity_ids."""
    found: list[str] = []
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            if k in ("entity_id", "entity_ids") and isinstance(v, str):
                found.append(v)
            elif k in ("entity_id", "entity_ids") and isinstance(v, list):
                found.extend(str(x) for x in v if isinstance(x, str))
            else:
                found.extend(_entities_in_config(v))
    elif isinstance(cfg, list):
        for item in cfg:
            found.extend(_entities_in_config(item))
    elif isinstance(cfg, str):
        # Bare entity_id strings (template references)
        if re.match(r"^[a-z_]+\.[a-z0-9_]+$", cfg):
            found.append(cfg)
    return found


def analyze_automations(hass: HomeAssistant) -> dict[str, Any]:
    """Scan automations / scenes / scripts and return inferred knowledge.

    Returns a dict with keys:
        proposals: list of suggested knowledge entries (not yet saved)
        stats: counts of what was scanned
    """
    proposals: list[dict[str, Any]] = []
    co_occurrence: dict[frozenset[str], int] = Counter()
    entity_to_groups: dict[str, set[str]] = defaultdict(set)

    automations = []
    scenes = []
    scripts = []

    for state in hass.states.async_all():
        eid = state.entity_id
        domain = eid.split(".", 1)[0]
        if domain == "automation":
            automations.append(state)
        elif domain == "scene":
            scenes.append(state)
        elif domain == "script":
            scripts.append(state)

    # â”€â”€ Scene analysis: entities in same scene â†’ likely same area / grouping
    for scene in scenes:
        entities_state = scene.attributes.get("entity_id") or []
        if isinstance(entities_state, str):
            entities_state = [entities_state]
        entities = list({str(e) for e in entities_state if isinstance(e, str)})
        if len(entities) < 2:
            continue
        scene_name = scene.attributes.get("friendly_name") or scene.entity_id
        for e in entities:
            entity_to_groups[e].add(scene.entity_id)
        # Room-name hint from scene name
        toks = _tokens(scene_name)
        if toks:
            for tok in toks:
                if len(tok) >= 4:
                    proposals.append({
                        "category": "general",
                        "subject": scene.entity_id,
                        "content": (
                            f"Scene '{scene_name}' groups {len(entities)} entities "
                            f"(token '{tok}' may indicate the area)."
                        ),
                        "tags": [tok, "scene_inference"],
                        "source": "inferred", "provenance": "Inferred from automation/scene/script analysis",
                        "confidence": 0.5,
                    })
                    break
        for i, a in enumerate(entities):
            for b in entities[i + 1:]:
                co_occurrence[frozenset({a, b})] += 1

    # â”€â”€ Automation analysis: trigger entity â†’ action entity reveals dependencies
    for autom in automations:
        name = autom.attributes.get("friendly_name") or autom.entity_id
        # HA exposes trigger/action through attributes only on some setups,
        # so fall back to entity_id token hints + co-occurrence in entity_id attr.
        related = autom.attributes.get("entity_id") or []
        if isinstance(related, str):
            related = [related]
        related = [str(e) for e in related if isinstance(e, str)]
        # Look for switchâ†’light pairs in the same automation (potential power chain)
        switches = [e for e in related if e.startswith("switch.")]
        downstream = [e for e in related if e.startswith(("light.", "media_player.", "climate."))]
        for sw in switches:
            for dn in downstream:
                proposals.append({
                    "category": "device_chain",
                    "subject": dn,
                    "content": (
                        f"{dn} appears together with {sw} in automation '{name}'. "
                        f"It may need {sw} to be on first."
                    ),
                    "tags": [sw, dn, "power_chain"],
                    "source": "inferred", "provenance": "Inferred from automation/scene/script analysis",
                    "confidence": 0.45,
                })
        # Co-occurrence
        for i, a in enumerate(related):
            for b in related[i + 1:]:
                co_occurrence[frozenset({a, b})] += 1
        # Area hints from automation name
        for tok in _tokens(name):
            if len(tok) >= 4:
                for ent in related:
                    proposals.append({
                        "category": "general",
                        "subject": ent,
                        "content": (
                            f"Used in automation '{name}'. Token '{tok}' in the "
                            f"name may indicate the relevant area or context."
                        ),
                        "tags": [tok, "automation_inference"],
                        "source": "inferred", "provenance": "Inferred from automation/scene/script analysis",
                        "confidence": 0.4,
                    })

    # â”€â”€ Script analysis: similar to automations
    for script in scripts:
        name = script.attributes.get("friendly_name") or script.entity_id
        toks = _tokens(name)
        # Scripts often encode procedures â€” propose a procedure entry per script
        if toks:
            proposals.append({
                "category": "procedure",
                "subject": script.entity_id,
                "content": (
                    f"Script '{name}' likely encodes a procedure. "
                    f"Call it directly via `script.turn_on` on `{script.entity_id}` "
                    f"when the user asks for: {', '.join(toks[:5])}."
                ),
                "tags": toks[:5] + ["script"],
                "source": "inferred", "provenance": "Inferred from automation/scene/script analysis",
                "confidence": 0.55,
            })

    # â”€â”€ Strong co-occurrence (3+ groups) â†’ likely-same-area entries
    for pair, count in co_occurrence.items():
        if count < 3:
            continue
        a, b = sorted(pair)
        proposals.append({
            "category": "general",
            "subject": a,
            "content": (
                f"{a} and {b} appear together in {count} automation(s)/scene(s). "
                f"They may belong to the same area or functional group."
            ),
            "tags": [a, b, "co_occurrence"],
            "source": "inferred", "provenance": "Inferred from automation/scene/script analysis",
            "confidence": min(0.85, 0.4 + count * 0.08),
        })

    # Deduplicate proposals by (category, subject, content)
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for p in proposals:
        key = (p["category"], p["subject"], p["content"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    return {
        "proposals": unique,
        "stats": {
            "automations_scanned": len(automations),
            "scenes_scanned": len(scenes),
            "scripts_scanned": len(scripts),
            "proposals_generated": len(unique),
        },
    }
