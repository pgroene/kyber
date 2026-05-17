"""Tool execution helpers extracted from http_api.py."""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .knowledge import get_store as get_knowledge_store
from .analyzer import analyze_automations as _analyze_automations
from .domain_docs import get_domain_docs as _get_domain_docs
from .source import (
    read_automations as _src_read_automations,
    read_scripts as _src_read_scripts,
    read_blueprints as _src_read_blueprints,
    read_blueprint as _src_read_blueprint,
)

_LOGGER = logging.getLogger(__name__)

# Domain priority for search result ranking — lower = more useful for control.
# Satellite/diagnostic entities (button, update, number) rank last so the
# primary controllable entity wins when a device exposes many sub-entities.
_DOMAIN_PRIORITY: dict[str, int] = {
    "media_player": 0,
    "light": 1,
    "climate": 2,
    "switch": 3,
    "fan": 4,
    "cover": 5,
    "lock": 6,
    "alarm_control_panel": 7,
    "vacuum": 8,
    "input_boolean": 9,
    "sensor": 10,
    "binary_sensor": 11,
    "camera": 12,
    "number": 15,
    "input_number": 15,
    "select": 16,
    "input_select": 16,
    "button": 20,
    "update": 21,
}

# Tool name aliases — small models often invent close-but-wrong tool names.
# Defined at module level so both sync and async paths can resolve them.
TOOL_ALIASES: dict[str, str] = {
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
    "get_integrations": "list_integrations",
    "integrations": "list_integrations",
    "integration_entities": "get_integration_entities",
    "get_entities_by_integration": "get_integration_entities",
    "ask_ai_task": "run_ai_task",
    "call_ai_task": "run_ai_task",
    "query_ai_task": "run_ai_task",
    "ask_ollama": "run_ai_task",
}


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
        count = len(result) if isinstance(result, dict) and "info" not in result else 0
        return f"{count} matches for '{call.get('query', '?')}'"
    if name == "get_areas":
        count = len(result) if isinstance(result, dict) else 0
        return f"{count} areas"
    if name == "get_labels":
        count = len(result) if isinstance(result, dict) else 0
        return f"{count} labels"
    if name == "list_integrations":
        count = result.get("count", 0) if isinstance(result, dict) else 0
        return f"{count} integrations"
    if name == "get_integration_entities":
        integration = call.get("integration", "?")
        count = result.get("count", 0) if isinstance(result, dict) else 0
        return f"{count} entities from '{integration}'"
    if name == "run_ai_task":
        entity_id = call.get("entity_id", "?")
        snippet = ""
        if isinstance(result, dict) and "response" in result:
            snippet = " — " + str(result["response"])[:80]
        return f"ai_task response from {entity_id}{snippet}"
    if name == "get_domain_docs":
        domain = call.get("domain", "?")
        return f"domain docs for '{domain}'"
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
    _ALIASES = TOOL_ALIASES
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
        missing_attr_fields: list[str] = []
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
                # Strip "attributes." prefix — the AI sometimes uses dot-notation
                # (e.g. "attributes.next_rising") instead of just "next_rising".
                attr_key = f[len("attributes."):] if f.startswith("attributes.") else f
                if attr_key in attrs and attrs[attr_key] is not None:
                    out[attr_key] = attrs[attr_key]
                else:
                    missing_attr_fields.append(f)
        # Always include available attribute keys when fields were specified,
        # so the AI knows what else it can request — even if no field was missing.
        # Only suppress this hint for entities with no useful extra attributes.
        _DROP_HINT = {"friendly_name", "icon", "entity_picture", "attribution"}
        available = [k for k in attrs if k not in _DROP_HINT]
        if missing_attr_fields:
            out["_missing_fields"] = missing_attr_fields
        if available:
            out["_available_attrs"] = available
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
            # Auto-complete: entity IDs always have format domain.name.
            # If the caller omitted the domain (e.g. "sun" instead of "sun.sun"),
            # try domain.name pattern and fuzzy search before returning an error.
            original_id = entity_id
            if "." not in entity_id:
                # Try domain.domain (e.g. "sun" → "sun.sun", "zone" → "zone.home" won't match but "sun" will)
                candidate = f"{entity_id}.{entity_id}"
                state = hass.states.get(candidate)
                if state:
                    entity_id = candidate
                else:
                    # Fuzzy search: find entities whose entity_id or friendly name contains the query
                    q = entity_id.lower()
                    matches = [
                        s.entity_id for s in hass.states.async_all()
                        if q in s.entity_id.lower()
                        or q in s.attributes.get("friendly_name", "").lower()
                    ]
                    if len(matches) == 1:
                        entity_id = matches[0]
                        state = hass.states.get(entity_id)
                    elif matches:
                        return json.dumps({
                            "error": f"Entity '{original_id}' not found — entity IDs require domain prefix (format: domain.name). Did you mean one of: {matches[:5]}?"
                        })
            if not state:
                return json.dumps({
                    "error": f"Entity '{original_id}' not found — entity IDs require domain prefix (format: domain.name, e.g. 'sun.sun'). Use list_entities_by_domain or search_entities to find the correct ID."
                })
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
        # Support multi-query: `queries` accepts a list of strings; results are
        # merged (OR semantics — entity matches if ANY query matches it).
        queries_raw = call.get("queries")
        if queries_raw and isinstance(queries_raw, list):
            query_list = [str(q).strip().lower() for q in queries_raw if str(q).strip()]
        elif query:
            query_list = [query]
        else:
            return json.dumps({"error": "Missing 'query' argument (or 'queries' list)"})

        results = {}
        for state in hass.states.async_all():
            entity_lower = state.entity_id.lower()
            friendly = state.attributes.get("friendly_name", "").lower()
            matched = False
            for q in query_list:
                q_words = q.split()
                # 1. Direct substring match
                if q in entity_lower or q in friendly:
                    matched = True
                    break
                # 2. Word-token match: all query words present in entity text
                #    (handles brackets/punctuation like "[LG] webOS TV")
                target = entity_lower + " " + friendly
                if all(w in target for w in q_words):
                    matched = True
                    break
            if not matched:
                continue
            if not _state_matches(state, state_filter):
                continue
            projection = _project_entity(state.entity_id, state)
            if fields_set is None:
                projection["domain"] = state.entity_id.split(".")[0]
            results[state.entity_id] = projection

        # Sort by domain priority (most-controllable first), then entity_id.
        # This must run AFTER the loop so all matching entities are collected.
        def _sort_key(eid: str) -> tuple[int, str]:
            return (_DOMAIN_PRIORITY.get(eid.split(".")[0], 50), eid)

        sorted_items = sorted(results.items(), key=lambda kv: _sort_key(kv[0]))

        # Deduplicate satellite entities: if a higher-priority entity has slug
        # "foo" and another entity has slug "foo_bar…", the latter is a sub-
        # entity of the same physical device — drop it so the AI isn't confused
        # by dozens of buttons/sensors from the same device.
        final: dict[str, Any] = {}
        kept_slugs: list[str] = []
        for eid, proj in sorted_items:
            slug = eid.split(".", 1)[1]
            if any(slug.startswith(ks + "_") for ks in kept_slugs):
                continue  # satellite of an already-kept primary entity
            final[eid] = proj
            kept_slugs.append(slug)

        query_display = query or ", ".join(query_list)
        return json.dumps(final or {"info": f"No entities matching '{query_display}'"})

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

    if name == "list_integrations":
        from homeassistant.helpers import device_registry as dr
        device_reg = dr.async_get(hass)
        integrations: dict[str, dict] = {}
        for entry in entity_reg.entities.values():
            platform = entry.platform or "unknown"
            if platform not in integrations:
                integrations[platform] = {
                    "entity_count": 0,
                    "domains": set(),
                    "sample_entities": [],
                }
            integrations[platform]["entity_count"] += 1
            integrations[platform]["domains"].add(entry.entity_id.split(".")[0])
            if len(integrations[platform]["sample_entities"]) < 3:
                state = hass.states.get(entry.entity_id)
                label = state.attributes.get("friendly_name", entry.entity_id) if state else entry.entity_id
                integrations[platform]["sample_entities"].append(
                    {"entity_id": entry.entity_id, "name": label}
                )
        result = {
            platform: {
                "entity_count": info["entity_count"],
                "domains": sorted(info["domains"]),
                "sample_entities": info["sample_entities"],
            }
            for platform, info in sorted(
                integrations.items(), key=lambda kv: -kv[1]["entity_count"]
            )
        }
        return json.dumps({"integrations": result, "count": len(result)})

    if name == "get_integration_entities":
        integration = str(call.get("integration", "")).strip().lower()
        if not integration:
            return json.dumps({"error": "Missing 'integration' argument"})
        domain_filter = call.get("domain", "").strip().lower()
        results = {}
        for entry in entity_reg.entities.values():
            if (entry.platform or "").lower() != integration:
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
        if not results:
            return json.dumps({"info": f"No entities found for integration '{integration}'"})
        return json.dumps({"integration": integration, "entities": results, "count": len(results)})

    # ── Domain action reference (on-demand) ──────────────────────────────────
    # Returns a compact service/parameter reference for a specific domain so
    # the AI can emit correct plan actions without guessing argument names.
    if name == "get_domain_docs":
        domain_arg = str(call.get("domain", "")).strip().lower()
        if not domain_arg:
            from .domain_docs import _AVAILABLE_DOMAINS
            return json.dumps({
                "error": "Missing 'domain' argument",
                "available_domains": _AVAILABLE_DOMAINS,
            })
        return json.dumps({"domain": domain_arg, "docs": _get_domain_docs(domain_arg)})

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
        "list_integrations", "get_integration_entities",
        "run_ai_task",
        "get_domain_docs",
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


# Async tools — tools that require awaiting (e.g. ai_task calls).
# Called directly from _run_one_tool in http_api.py without going through executor.
_ASYNC_TOOLS = {"run_ai_task"}


async def _async_execute_tool(hass: HomeAssistant, call: dict[str, Any]) -> str:
    """Execute an async tool call and return the result as a JSON string."""
    name = call.get("name", "")

    if name == "run_ai_task":
        try:
            from homeassistant.components.ai_task import async_generate_data  # type: ignore[import]
        except ImportError:
            return json.dumps({"error": "ai_task component not available (HA < 2025.2)"})

        entity_id = str(call.get("entity_id") or call.get("ai_task_entity") or "").strip()
        prompt = str(call.get("prompt") or call.get("question") or "").strip()

        if not entity_id:
            # Auto-detect first ai_task entity
            from homeassistant.helpers import entity_registry as _er
            reg = _er.async_get(hass)
            candidates = [e.entity_id for e in reg.entities.values() if e.entity_id.startswith("ai_task.")]
            if not candidates:
                return json.dumps({"error": "No ai_task entities found. Configure an AI integration (Ollama, OpenAI, etc.) first."})
            entity_id = candidates[0]

        if not prompt:
            return json.dumps({"error": "Missing 'prompt' argument"})

        try:
            result = await async_generate_data(
                hass=hass,
                task_name="kyber_tool_query",
                entity_id=entity_id,
                instructions=prompt,
            )
            text = getattr(result, "data", None)
            if text is None:
                text = str(result)
            return json.dumps({"entity_id": entity_id, "response": text})
        except Exception as exc:  # pylint: disable=broad-except
            return json.dumps({"error": str(exc)})

    return json.dumps({"error": f"Unknown async tool '{name}'"})
