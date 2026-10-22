"""Check a proposed automation or script against Home Assistant and the real entities.

A local model knows in isolation that ``climate.set_temperature`` does not
switch on a thermostat, yet wrote it without ``hvac_mode`` in 30 of 30 tries;
it invents input_select options and schedule values even with the real ones in
the prompt, and keeps broken parts of the configuration it was asked to fix
(measured on a living room heating case). Told what is wrong, it fixes most of it in
one more round. This module finds what is wrong:

- whether Home Assistant accepts the configuration (its own validator),
- whether every entity, attribute, option and attribute value exists,
- two domain rules with evidence behind them,
- outdated syntax, which Home Assistant still accepts (style only).

It also renders the entities a configuration uses, so the model sees their
real states, options and attributes before it writes anything.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

ERROR = "error"
STYLE = "style"

_ENTITY_ID_RE = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")
_STATE_ATTR_RE = re.compile(
    r"\b(?:state_attr|is_state_attr)\(\s*['\"]([a-z_]+\.[a-z0-9_]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)
# States every entity can take; a trigger on them is legitimate.
_ALWAYS_VALID_STATES = ("unavailable", "unknown")
_ON_OFF_DOMAINS = frozenset({
    "automation", "binary_sensor", "fan", "input_boolean", "light", "schedule",
    "script", "siren", "switch",
})
# Attributes that only add noise to the entity context.
_CONTEXT_SKIP_ATTRS = frozenset({"entity_picture", "icon", "supported_features", "attribution"})
_CONTEXT_VALUE_CHARS = 200
_CONTEXT_MAX_CHARS = 4_000


@dataclass(frozen=True)
class Finding:
    """One problem in a proposed configuration.

    ``key`` and ``params`` let the panel translate it; ``text`` is what the
    model reads (and the fallback for the panel).
    """

    severity: str
    key: str
    text: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "key": self.key, "text": self.text, "params": self.params}


# ── Entities a configuration uses ───────────────────────────────────────────

def _entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    if hass.states.get(entity_id) is not None:
        return True
    return er.async_get(hass).async_get(entity_id) is not None


def referenced_entity_ids(hass: HomeAssistant, config: Any) -> list[str]:
    """Entity ids in ``config`` (dict or YAML text) that exist, in order of appearance.

    Service names such as ``climate.set_temperature`` look like entity ids but
    have no state, so they drop out here.
    """
    text = config if isinstance(config, str) else json.dumps(config, ensure_ascii=False, default=str)
    found = dict.fromkeys(m.group(1) for m in _ENTITY_ID_RE.finditer(text))
    return [eid for eid in found if hass.states.get(eid) is not None]


async def schedule_data_values(hass: HomeAssistant, entity_id: str) -> dict[str, list[Any]]:
    """Every value each block-data key of a schedule helper takes, across all blocks.

    The state only carries the data of the block running now; a trigger on a
    value that is not active right now is still valid. Empty when the service
    is missing or fails.
    """
    try:
        response = await hass.services.async_call(
            "schedule", "get_schedule", target={"entity_id": entity_id},
            blocking=True, return_response=True,
        )
    except Exception as err:  # noqa: BLE001 – the check must never break a turn
        _LOGGER.debug("Kyber: could not read schedule %s: %s", entity_id, err)
        return {}
    days = (response or {}).get(entity_id) or {}
    values: dict[str, list[Any]] = {}
    for blocks in days.values():
        for block in blocks or []:
            for key, value in ((block or {}).get("data") or {}).items():
                bucket = values.setdefault(key, [])
                if value not in bucket:
                    bucket.append(value)
    return values


def _valid_states(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """The states an entity can take, when that set is known; else None."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    domain = entity_id.split(".", 1)[0]
    if domain in ("input_select", "select"):
        options = state.attributes.get("options")
        return [str(o) for o in options] if isinstance(options, list) else None
    if domain == "climate":
        modes = state.attributes.get("hvac_modes")
        return [str(m) for m in modes] if isinstance(modes, list) else None
    if domain in _ON_OFF_DOMAINS:
        return ["on", "off"]
    return None


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= _CONTEXT_VALUE_CHARS else text[:_CONTEXT_VALUE_CHARS] + "…"


async def entity_context(hass: HomeAssistant, entity_ids: list[str], schedule_values: dict) -> str:
    """Prompt section with the live state, attributes and valid values of ``entity_ids``."""
    if not entity_ids:
        return ""
    lines = [
        "### Entities this configuration uses (live state, attributes, valid values)",
        "Use only these option values, attribute names and attribute values; never invent them.",
    ]
    for eid in entity_ids:
        state = hass.states.get(eid)
        if state is None:
            continue
        attrs = {k: v for k, v in state.attributes.items() if k not in _CONTEXT_SKIP_ATTRS}
        parts = [f'- `{eid}`: state "{state.state}"']
        valid = _valid_states(hass, eid)
        if valid and eid.split(".", 1)[0] not in _ON_OFF_DOMAINS:
            parts.append(f"valid states {_short(valid)}")
        if attrs:
            parts.append("attributes " + ", ".join(f"{k}={_short(v)}" for k, v in attrs.items()))
        data = schedule_values.get(eid)
        if data:
            parts.append(
                "block data across all blocks: "
                + ", ".join(f"{k} ∈ {_short(v)}" for k, v in data.items())
                + ' (state is "on" inside a block, "off" outside; the block data attributes are absent outside a block)'
            )
        lines.append("; ".join(parts))
    text = "\n".join(lines) + "\n\n"
    if len(text) > _CONTEXT_MAX_CHARS:
        text = text[:_CONTEXT_MAX_CHARS].rsplit("\n", 1)[0] + "\n(…more entities omitted)\n\n"
    return text


async def collect_schedule_values(hass: HomeAssistant, entity_ids: list[str]) -> dict[str, dict]:
    """Block-data values of every schedule helper among ``entity_ids``."""
    out: dict[str, dict] = {}
    for eid in entity_ids:
        if eid.startswith("schedule."):
            values = await schedule_data_values(hass, eid)
            if values:
                out[eid] = values
    return out


# ── The check ───────────────────────────────────────────────────────────────

# Target keys a service call may carry in data (the old form of target:).
_TARGET_KEYS = frozenset({"entity_id", "device_id", "area_id", "floor_id", "label_id"})


def _field_names(description: dict) -> set[str]:
    """Field names of a service description; sections (e.g. temperature_range) are opened up."""
    names: set[str] = set()
    for key, value in (description.get("fields") or {}).items():
        if isinstance(value, dict) and isinstance(value.get("fields"), dict):
            names |= set(value["fields"])
        else:
            names.add(key)
    return names


async def service_fields(hass: HomeAssistant) -> dict[str, set[str]]:
    """``domain.service`` -> its field names, for every described service that has fields.

    Services without a description or without fields are left out, so a
    custom integration that documents nothing never produces a finding.
    """
    from homeassistant.helpers.service import async_get_all_descriptions

    try:
        descriptions = await async_get_all_descriptions(hass)
    except Exception as err:  # noqa: BLE001 – the check must never break a turn
        _LOGGER.debug("Kyber: service descriptions unavailable: %s", err)
        return {}
    out: dict[str, set[str]] = {}
    for domain, services in (descriptions or {}).items():
        for service, description in (services or {}).items():
            names = _field_names(description or {})
            if names:
                out[f"{domain}.{service}"] = names
    return out


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


async def _schema_findings(hass: HomeAssistant, config: dict, kind: str) -> list[Finding]:
    """Ask Home Assistant's own validator, the one its config editor uses on save."""
    try:
        if kind == "script":
            from homeassistant.components.script.config import (
                async_validate_config_item,
            )

            await async_validate_config_item(hass, "kyber_check", copy.deepcopy(config))
        else:
            from homeassistant.components.automation.config import (
                async_validate_config_item,
            )

            await async_validate_config_item(hass, "kyber_check", copy.deepcopy(config))
    except Exception as err:  # noqa: BLE001 – any rejection is a finding
        message = _schema_message(config, err)
        return [Finding(ERROR, "schema", f"Home Assistant rejects this configuration: {message}", {"message": message})]
    return []


def _key_locations(node: Any, key: str, path: str = "") -> list[str]:
    """Paths of the mappings in ``node`` that contain ``key``."""
    found: list[str] = []
    if isinstance(node, dict):
        if key in node:
            found.append(path or "top level")
        for k, v in node.items():
            found += _key_locations(v, key, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _key_locations(v, key, f"{path}[{i}]")
    return found


def _schema_message(config: dict, err: Exception) -> str:
    """Every sub-error of a rejection, each with where it is when that can be found.

    Home Assistant validates each trigger on its own, so its path names only
    the key ("event_type"), not the trigger, and str() shows only the first
    sub-error. Told just "not a valid option at 'event_type'", the model
    deleted the trigger instead of writing "event: start".
    """
    parts: list[str] = []
    for sub in getattr(err, "errors", None) or [err]:
        text = str(sub) or type(sub).__name__
        path = getattr(sub, "path", None) or []
        key = path[-1] if path and isinstance(path[-1], str) else None
        if key and ("not a valid option" in text or "extra keys not allowed" in text):
            where = _key_locations(config, key)
            if where:
                text += f" (in {', '.join(where[:3])})"
        if text not in parts:
            parts.append(text)
    return "; ".join(parts)


class _Walker:
    """Collects entity, attribute and value findings over a configuration."""

    def __init__(
        self, hass: HomeAssistant, schedule_values: dict[str, dict], service_fields: dict[str, set[str]] | None = None,
    ) -> None:
        self.hass = hass
        self.schedule_values = schedule_values
        self.service_fields = service_fields or {}
        self.findings: list[Finding] = []

    def check_service_data(self, node: dict, path: str) -> None:
        """Every data key must be a field of the service (Home Assistant's own service descriptions).

        Measured: a model wrote ``target_temp`` for climate.set_temperature;
        HA accepts the automation and rejects every call at run time.
        """
        service = node.get("action") or node.get("service")
        fields = self.service_fields.get(service) if isinstance(service, str) else None
        data = node.get("data") if isinstance(node.get("data"), dict) else node.get("data_template")
        if not fields or not isinstance(data, dict):
            return
        for key in data:
            if key not in fields and key not in _TARGET_KEYS:
                valid = sorted(fields)
                self._add(
                    ERROR, "unknown_field",
                    f"action {path}: {service} has no field '{key}'. Fields: {valid}.",
                    service=service, field=key, valid=valid,
                )

    def _add(self, severity: str, key: str, text: str, **params: Any) -> None:
        self.findings.append(Finding(severity, key, text, params))

    def check_entity(self, eid: str, where: str) -> bool:
        if _entity_exists(self.hass, eid):
            return True
        self._add(ERROR, "no_entity", f"{where}: entity {eid} does not exist.", entity_id=eid)
        return False

    def check_attribute(self, eid: str, attr: str, where: str) -> bool:
        state = self.hass.states.get(eid)
        if state is None:
            return False
        known = set(state.attributes) | set(self.schedule_values.get(eid, {}))
        if attr in known:
            return True
        available = sorted(k for k in known if k not in _CONTEXT_SKIP_ATTRS)
        self._add(
            ERROR, "no_attribute",
            f"{where}: {eid} has no attribute '{attr}'. Available: {available}.",
            entity_id=eid, attribute=attr, available=available,
        )
        return False

    def check_values(self, eid: str, attr: str | None, values: list, where: str) -> None:
        if attr:
            valid = self.schedule_values.get(eid, {}).get(attr)
        else:
            valid = _valid_states(self.hass, eid)
        if valid is None:
            return
        allowed = [str(v) for v in valid] + ([] if attr else list(_ALWAYS_VALID_STATES))
        for value in values:
            if value is None or isinstance(value, (dict, list)):
                continue
            if str(value) in allowed:
                continue
            what = f"attribute '{attr}'" if attr else "state"
            self._add(
                ERROR, "bad_value",
                f"{where}: '{value}' is not a valid {what} of {eid}. Valid values: {[str(v) for v in valid]}.",
                entity_id=eid, attribute=attr or "", value=str(value), valid=[str(v) for v in valid],
            )

    def state_check(self, node: dict, values: list, where: str) -> None:
        attr = node.get("attribute")
        for eid in _as_list(node.get("entity_id")):
            if not isinstance(eid, str) or not self.check_entity(eid, where):
                continue
            if attr and not self.check_attribute(eid, attr, where):
                continue
            self.check_values(eid, attr, values, where)

    def walk(self, node: Any, path: str) -> None:
        if isinstance(node, list):
            self._sequence_rules(node, path)
            for i, item in enumerate(node):
                self.walk(item, f"{path}[{i}]")
            return
        if not isinstance(node, dict):
            return
        if node.get("trigger") == "state" or node.get("platform") == "state":
            self.state_check(node, _as_list(node.get("to")) + _as_list(node.get("from")), f"trigger {path}")
        if node.get("condition") == "state":
            self.state_check(node, _as_list(node.get("state")), f"condition {path}")
        self.check_service_data(node, path)
        if "data_template" in node:
            self._add(STYLE, "style_data_template", f"{path}: data_template is deprecated; put templates directly into data.")
        if "service" in node and "action" not in node:
            self._add(STYLE, "style_service", f"{path}: use action: instead of service:.")
        if "platform" in node and "trigger" not in node:
            self._add(STYLE, "style_platform", f"{path}: write the trigger type as trigger: instead of platform:.")
        target = node.get("target")
        if isinstance(target, dict):
            for eid in _as_list(target.get("entity_id")):
                if isinstance(eid, str) and "{" not in eid:
                    self.check_entity(eid, f"action {path}")
        for key, value in node.items():
            self.walk(value, f"{path}.{key}")

    def _sequence_rules(self, items: list, path: str) -> None:
        """Domain rule: set_temperature needs hvac_mode unless the thermostat is switched on first."""
        switched_on: set[str] = set()
        for i, step in enumerate(items):
            if not isinstance(step, dict):
                continue
            action = step.get("action") or step.get("service")
            targets = {
                e for e in _as_list((step.get("target") or {}).get("entity_id") or step.get("entity_id"))
                if isinstance(e, str)
            }
            if action in ("climate.turn_on", "climate.set_hvac_mode"):
                switched_on |= targets
            if action == "climate.set_temperature":
                data = step.get("data") or step.get("data_template") or {}
                if "hvac_mode" not in data and not (targets and targets <= switched_on):
                    self._add(
                        ERROR, "rule_hvac_mode",
                        f"action {path}[{i}]: climate.set_temperature without hvac_mode does not switch on "
                        "a thermostat that is off; add hvac_mode (e.g. heat) to the same call.",
                    )

    def template_checks(self, config: dict) -> None:
        text = json.dumps(config, ensure_ascii=False, default=str)
        for eid, attr in dict.fromkeys(_STATE_ATTR_RE.findall(text)):
            if self.check_entity(eid, "template"):
                self.check_attribute(eid, attr, "template")


def _top_level_findings(config: dict, kind: str, schedule_values: dict) -> list[Finding]:
    findings: list[Finding] = []
    if kind == "automation":
        for old in ("trigger", "condition", "action"):
            if old in config:
                findings.append(Finding(STYLE, "style_plural", f"top level: use '{old}s' instead of '{old}'."))
    triggers = _as_list(config.get("triggers", config.get("trigger")))
    schedule_triggers = [
        t for t in triggers
        if isinstance(t, dict)
        and any(isinstance(e, str) and e.startswith("schedule.") for e in _as_list(t.get("entity_id")))
    ]
    if schedule_triggers and all(t.get("attribute") for t in schedule_triggers):
        findings.append(Finding(
            ERROR, "rule_schedule_end",
            "triggers: a schedule trigger on an attribute does not fire when a block ends (the state "
            "turns off and the block data disappears); also trigger on the schedule state itself.",
        ))
    return findings


async def check_config(
    hass: HomeAssistant, config: dict, kind: str = "automation", schedule_values: dict | None = None,
) -> list[Finding]:
    """All findings for ``config``; errors first, duplicates removed."""
    if not isinstance(config, dict):
        return [Finding(ERROR, "schema", "The configuration is not a mapping.", {"message": "not a mapping"})]
    if schedule_values is None:
        schedule_values = await collect_schedule_values(hass, referenced_entity_ids(hass, config))
    walker = _Walker(hass, schedule_values, await service_fields(hass))
    findings = await _schema_findings(hass, config, kind)
    body = {k: v for k, v in config.items() if k not in ("id", "alias", "description")}
    walker.walk(body, "")
    walker.template_checks(body)
    findings += walker.findings + _top_level_findings(config, kind, schedule_values)
    unique = list({(f.severity, f.text): f for f in findings}.values())
    return sorted(unique, key=lambda f: f.severity != ERROR)


def plan_config(plan: dict | None) -> tuple[dict | None, str]:
    """The configuration an automation/script plan proposes, and its kind."""
    if not isinstance(plan, dict):
        return None, ""
    if plan.get("edit_automation") or plan.get("edit_script"):
        config = plan.get("modified_config")
    elif plan.get("create_automation") or plan.get("create_script"):
        config = plan.get("config")
    else:
        return None, ""
    target = str(plan.get("entity_id") or "")
    kind = "script" if target.startswith("script.") or plan.get("edit_script") or plan.get("create_script") else "automation"
    return (config if isinstance(config, dict) else None), kind


def feedback_for_model(findings: list[Finding]) -> str:
    """The tool result a correction round sends; empty when no error needs fixing."""
    if not any(f.severity == ERROR for f in findings):
        return ""
    # Live run: told a trigger was invalid, the model dropped the trigger.
    lines = [(
        "The proposed configuration was checked against Home Assistant and the real entities. "
        "Fix every finding in place and emit the complete corrected plan block again. Repair a "
        "rejected trigger, condition or action in valid syntax; never delete it to make a finding go away:"
    )]
    lines += [f"- {f.text}" for f in findings if f.severity == ERROR]
    style = [f"- {f.text}" for f in findings if f.severity == STYLE]
    if style:
        lines.append("Also modernise the syntax:")
        lines += style
    return "\n".join(lines)
