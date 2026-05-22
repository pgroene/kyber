"""Action execution and approval helpers extracted from http_api.py."""
from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .action_history import get_store as get_action_history_store
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

# Domains that should never silently auto-execute under autopilot.
_HIGH_RISK_DOMAINS: set[str] = {
    "lock",
    "alarm_control_panel",
    "cover",
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


def _classify_risk(action: dict, denylist: set[str] | None = None) -> dict[str, str] | None:
    """Return metadata for high-risk actions that need explicit approval."""
    if not isinstance(action, dict):
        return None
    deny = {str(item).strip().lower() for item in (denylist or _HIGH_RISK_DOMAINS) if str(item).strip()}
    if str(action.get("type", "")).lower() != "call_service":
        return None
    domain = str(action.get("domain", "")).lower()
    service = str(action.get("service", "")).lower()
    if not domain:
        return None
    if (domain, service) in _DESTRUCTIVE_SERVICES or domain in deny:
        reason = f"{domain}.{service}" if service else domain
        return {"risk_domain": domain, "risk_reason": reason}
    return None


def _action_requires_approval(action: dict, denylist: set[str] | None = None) -> bool:
    """Return True if this action must require explicit user approval."""
    if not isinstance(action, dict):
        return False
    atype = str(action.get("type", "")).lower()
    if atype in _CONFIG_CHANGING_ACTION_TYPES:
        return True
    return _classify_risk(action, denylist) is not None


def _annotate_plan_approval(plan: dict | None, denylist: set[str] | None = None) -> dict | None:
    """Annotate plan actions with approval and high-risk metadata."""
    if not isinstance(plan, dict):
        return plan
    actions = plan.get("actions")
    if not isinstance(actions, list):
        return plan
    any_requires = False
    high_risk_domains: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        risk = _classify_risk(action, denylist)
        needs = _action_requires_approval(action, denylist)
        action["requires_approval"] = needs
        action["high_risk"] = risk is not None
        if risk is not None:
            action.update(risk)
            high_risk_domains.add(risk["risk_domain"])
        else:
            action.pop("risk_domain", None)
            action.pop("risk_reason", None)
        if needs:
            any_requires = True
    plan["requires_approval"] = any_requires
    plan["high_risk"] = bool(high_risk_domains)
    plan["high_risk_domains"] = sorted(high_risk_domains)
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
        ha_user = request.get("hass_user")
        user_id = str(getattr(ha_user, "id", "") or "") or None
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

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
        guardrail_domains = _HIGH_RISK_DOMAINS
        if not approved:
            blocked: list[dict] = []
            for action in actions:
                risk = _classify_risk(action, guardrail_domains)
                if _action_requires_approval(action, guardrail_domains):
                    blocked.append({
                        "type": action.get("type"),
                        "entity_id": action.get("entity_id"),
                        "domain": action.get("domain"),
                        "service": action.get("service"),
                        "high_risk": risk is not None,
                        "risk_domain": (risk or {}).get("risk_domain"),
                        "risk_reason": (risk or {}).get("risk_reason"),
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
        device_reg = dr.async_get(hass)

        results: list[dict] = []
        applied_actions: list[dict[str, Any]] = []
        entity_changes: list[dict[str, Any]] = []
        history_entry: dict[str, Any] | None = None

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
                            owner_id=user_id,
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
                        ok = await kstore.async_delete(
                            entry_id,
                            requesting_user_id=user_id,
                            is_admin=bool(getattr(ha_user, "is_admin", False)),
                        )
                        results.append({
                            "status": "ok" if ok else "error", "type": action_type,
                            "entry_id": entry_id,
                            **({"message": f"Knowledge entry '{entry_id}' not found"} if not ok else {}),
                        })
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("Knowledge action %s failed: %s", action_type, err)
                    results.append({"status": "error", "message": "Internal error"})
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
                    results.append({"status": "error", "message": "Internal error"})
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
                    results.append({"status": "error", "message": "Internal error"})
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
                    results.append({"status": "error", "message": "Internal error"})
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
                    # Inner try: first attempt; retry if HA schema rejects extra keys
                    # (e.g. light.turn_on rejects color_temp when the entity's
                    # supported_color_modes doesn't include it — HA 2025.x).
                    try:
                        await hass.services.async_call(domain, service, service_data, blocking=True)
                    except Exception as _svc_err:  # noqa: BLE001
                        err_str = str(_svc_err)
                        extra_keys = re.findall(
                            r"extra keys not allowed @ data\['([^']+)'\]", err_str
                        )
                        if extra_keys:
                            _LOGGER.warning(
                                "Kyber: call_service %s.%s — retrying without unsupported keys %s",
                                domain, service, extra_keys,
                            )
                            cleaned_data = {k: v for k, v in service_data.items() if k not in extra_keys}
                            await hass.services.async_call(domain, service, cleaned_data, blocking=True)
                        else:
                            raise
                    undo_action = _build_service_undo(domain, service, svc_entity_id, pre_state)
                    post_state = hass.states.get(svc_entity_id) if svc_entity_id else None
                    result: dict = {"status": "ok", "type": action_type, "entity_id": svc_entity_id or domain}
                    if undo_action:
                        result["undo_action"] = undo_action
                    if svc_entity_id:
                        entity_changes.append({
                            "entity_id": svc_entity_id,
                            "service": f"{domain}.{service}",
                            "from_state": pre_state.state if pre_state else None,
                            "to_state": post_state.state if post_state else None,
                        })
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
                    results.append({"status": "error", "entity_id": svc_entity_id or domain, "message": "Internal error"})
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
                    label_entry = label_reg.async_get_label(label_id)
                    label_name = label_entry.name if label_entry else label_id
                    old_labels = set(entry.labels)
                    new_labels = old_labels | {label_id}
                    entity_reg.async_update_entity(entity_id, labels=new_labels)
                    results.append({
                        "entity_id": entity_id, "status": "ok", "type": action_type,
                        "undo_action": {"type": "remove_label", "entity_id": entity_id,
                                        "label_id": label_id,
                                        "current_state": str(new_labels), "new_state": str(old_labels),
                                        "description": f"Remove label '{label_name}' from {entity_id}"},
                    })
                    if label_name.startswith("kyber:"):
                        try:
                            kstore = get_knowledge_store(hass)
                            await kstore.async_load()
                            has_general_entry = any(
                                item.get("category") == "general"
                                and str(item.get("subject") or "") == entity_id
                                for item in kstore._entries.values()  # noqa: SLF001
                            )
                            if not has_general_entry:
                                state = hass.states.get(entity_id)
                                friendly_name = (
                                    (state.attributes.get("friendly_name") if state else None)
                                    or entry.name
                                    or entry.original_name
                                    or entity_id
                                )
                                domain = entity_id.split(".", 1)[0]
                                area_id = entry.area_id
                                if not area_id and entry.device_id:
                                    device_entry = device_reg.async_get(entry.device_id)
                                    if device_entry:
                                        area_id = device_entry.area_id
                                area_entry = area_reg.async_get_area(area_id) if area_id else None
                                area_name = area_entry.name if area_entry else ""
                                integration = (entry.platform or "").strip()
                                device_class = (
                                    (state.attributes.get("device_class") if state else None)
                                    or (entry.device_class if hasattr(entry, "device_class") else None)
                                    or ""
                                )
                                content = f"{domain} entity '{friendly_name}' [{entity_id}]"
                                if area_name:
                                    content += f", located in {area_name}"
                                if integration:
                                    content += f". Provided by the {integration} integration"
                                if device_class:
                                    content += f". Device class: {device_class}"
                                content += f". Tagged with label '{label_name}'."
                                await kstore.async_add(
                                    category="general",
                                    content=content,
                                    subject=entity_id,
                                    tags=[entity_id, domain, "labeled", label_name, "label_assignment"],
                                    source="label_assignment",
                                    confidence=0.75,
                                )
                        except Exception as err:  # noqa: BLE001
                            _LOGGER.warning("Label knowledge seed failed for %s: %s", entity_id, err)

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
                results.append({"entity_id": entity_id, "status": "error", "message": "Internal error"})

        applied_actions = [
            action
            for action, result in zip(actions, results)
            if action.get("type") not in _READ_TOOL_TYPES and result.get("status") == "ok"
        ]

        # ── Correction micro-agent — triggered when call_service actions fail ─
        # Only call_service failures are correctable; config/registry errors are
        # not (renaming an entity that doesn't exist won't be fixed by an AI).
        correction: dict | None = None
        _has_service_failures = any(
            r.get("status") == "error"
            for r in results
            if any(
                a.get("type") == "call_service" and
                a.get("entity_id", "") == r.get("entity_id", "")
                for a in actions
            )
        )
        if _has_service_failures:
            try:
                from .correction_agent import async_try_correct_failures
                _LOGGER.info(
                    "Kyber: execution had failures — invoking correction micro-agent"
                )
                correction = await async_try_correct_failures(
                    hass, results, actions, _plan_summary
                )
                if correction:
                    _LOGGER.info(
                        "Kyber: correction agent returned %d corrected action(s)",
                        len(correction.get("corrected_actions", [])),
                    )
            except Exception as _corr_err:  # noqa: BLE001
                _LOGGER.warning(
                    "Kyber: correction micro-agent raised an error: %s", _corr_err
                )

        has_failures = any(result.get("status") != "ok" for result in results)
        if applied_actions and not has_failures:
            try:
                astore = get_action_history_store(hass)
                history_entry = await astore.async_record(
                    _plan_summary or "Applied Kyber actions",
                    applied_actions,
                    entity_changes,
                    user_id=user_id,
                    high_risk=any(_classify_risk(action, guardrail_domains) for action in applied_actions),
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Kyber: action history record failed: %s", err)

        response_payload: dict = {"results": results}
        if history_entry:
            response_payload["history_entry"] = history_entry
        if correction:
            response_payload["correction"] = correction

        return self.json(response_payload)
