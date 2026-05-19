"""Action execution and approval helpers extracted from http_api.py."""
from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN
from .knowledge import get_store as get_knowledge_store
from .tool_execution import _execute_tool

_LOGGER = logging.getLogger(__name__)
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
        _plan_summary: str = str(body.get("summary", "") or body.get("plan_summary", "")).strip()

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
                domain: str = action.get("domain", "").strip().lower()
                service: str = action.get("service", "").strip().lower()
                service_data: dict = action.get("service_data") or {}
                svc_entity_id: str = action.get("entity_id", "").strip()
                # Infer missing domain from entity_id (e.g. "switch.onoff_..." → "switch")
                if not domain and svc_entity_id and "." in svc_entity_id:
                    domain = svc_entity_id.split(".", 1)[0]
                if not domain or not service:
                    results.append({"status": "error", "message": "Missing 'domain' or 'service' for call_service"})
                    continue
                # Normalize entity_id: if the model emitted just the local part
                # (e.g. "onoff_keuken_espresso_304" instead of
                # "switch.onoff_keuken_espresso_304"), recover the full id.
                if svc_entity_id and "." not in svc_entity_id:
                    candidate = f"{domain}.{svc_entity_id}"
                    if hass.states.get(candidate):
                        svc_entity_id = candidate
                    else:
                        for st in hass.states.async_all():
                            local = st.entity_id.split(".", 1)[-1]
                            if local == svc_entity_id and (
                                not domain or st.entity_id.startswith(f"{domain}.")
                            ):
                                svc_entity_id = st.entity_id
                                break
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
                    # Auto-label on first control interaction
                    if svc_entity_id and service in ("turn_on", "turn_off", "toggle"):
                        try:
                            from .device_type_labels import async_infer_and_apply_label
                            label_info = await async_infer_and_apply_label(hass, svc_entity_id, _plan_summary)
                            if label_info:
                                label_info["undo_action"] = {
                                    "type": "remove_label",
                                    "entity_id": svc_entity_id,
                                    "label_id": label_info["label_id"],
                                    "description": f"Verwijder label '{label_info['label_name']}' van {label_info['entity_name']}",
                                }
                                result["label_applied"] = label_info
                        except Exception as _label_err:  # noqa: BLE001
                            _LOGGER.debug("Kyber: label inference skipped for %s: %s", svc_entity_id, _label_err)
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
