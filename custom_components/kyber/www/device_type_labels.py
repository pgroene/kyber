"""Device type → HA label mapping and auto-apply helpers for Kyber."""
from __future__ import annotations
import logging
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

_LOGGER = logging.getLogger(__name__)

# label_id (slug, no spaces) → {name, icon, color}
# name must start with "kyber:" prefix
DEVICE_TYPE_LABELS: dict[str, dict[str, str]] = {
    "koffiemachine":  {"name": "kyber:Koffiemachine",  "icon": "mdi:coffee",           "color": "#6F4E37"},
    "lamp":           {"name": "kyber:Lamp",            "icon": "mdi:lamp",             "color": "#FFC107"},
    "verwarming":     {"name": "kyber:Verwarming",      "icon": "mdi:radiator",         "color": "#FF5722"},
    "airco":          {"name": "kyber:Airco",           "icon": "mdi:air-conditioner",  "color": "#2196F3"},
    "stofzuiger":     {"name": "kyber:Stofzuiger",      "icon": "mdi:robot-vacuum",     "color": "#9C27B0"},
    "wasmachine":     {"name": "kyber:Wasmachine",      "icon": "mdi:washing-machine",  "color": "#00BCD4"},
    "droger":         {"name": "kyber:Droger",          "icon": "mdi:tumble-dryer",     "color": "#009688"},
    "vaatwasser":     {"name": "kyber:Vaatwasser",      "icon": "mdi:dishwasher",       "color": "#3F51B5"},
    "oven":           {"name": "kyber:Oven",            "icon": "mdi:stove",            "color": "#FF9800"},
    "magnetron":      {"name": "kyber:Magnetron",       "icon": "mdi:microwave",        "color": "#795548"},
    "koelkast":       {"name": "kyber:Koelkast",        "icon": "mdi:fridge",           "color": "#607D8B"},
    "tv":             {"name": "kyber:TV",              "icon": "mdi:television",       "color": "#1976D2"},
    "speaker":        {"name": "kyber:Speaker",         "icon": "mdi:speaker",          "color": "#E91E63"},
    "ventilator":     {"name": "kyber:Ventilator",      "icon": "mdi:fan",              "color": "#00ACC1"},
    "jaloezie":       {"name": "kyber:Jaloezie",        "icon": "mdi:blinds",           "color": "#78909C"},
    "deur":           {"name": "kyber:Deur",            "icon": "mdi:door",             "color": "#546E7A"},
    "poort":          {"name": "kyber:Poort",           "icon": "mdi:gate",             "color": "#455A64"},
    "alarm":          {"name": "kyber:Alarm",           "icon": "mdi:shield-home",      "color": "#F44336"},
    "camera":         {"name": "kyber:Camera",          "icon": "mdi:cctv",             "color": "#37474F"},
    "sensor":         {"name": "kyber:Sensor",          "icon": "mdi:chip",             "color": "#8D6E63"},
}

# Keywords (lowercase) → device_type key
_KEYWORD_MAP: dict[str, str] = {
    # Coffee
    "espresso": "koffiemachine", "koffie": "koffiemachine", "coffee": "koffiemachine",
    "nespresso": "koffiemachine", "senseo": "koffiemachine", "cappuccino": "koffiemachine",
    # Lights
    "lamp": "lamp", "light": "lamp", "licht": "lamp", "verlichting": "lamp",
    "dimmer": "lamp", "led": "lamp",
    # Heating
    "verwarming": "verwarming", "radiator": "verwarming", "heater": "verwarming",
    "warmte": "verwarming", "heating": "verwarming", "cv": "verwarming",
    # AC
    "airco": "airco", "airconditioner": "airco", "koeling": "airco", "ac": "airco",
    "klimaat": "airco",
    # Vacuum
    "stofzuiger": "stofzuiger", "robot": "stofzuiger", "vacuum": "stofzuiger",
    "roomba": "stofzuiger", "freddy": "stofzuiger",
    # Washer
    "wasmachine": "wasmachine", "washer": "wasmachine", "washing": "wasmachine",
    "was": "wasmachine",
    # Dryer
    "droger": "droger", "dryer": "droger",
    # Dishwasher
    "vaatwasser": "vaatwasser", "dishwasher": "vaatwasser",
    # Oven
    "oven": "oven", "bop": "oven", "fornuis": "oven",
    # Microwave
    "magnetron": "magnetron", "microwave": "magnetron",
    # Fridge
    "koelkast": "koelkast", "fridge": "koelkast", "freezer": "koelkast",
    # TV
    "tv": "tv", "televisie": "tv", "television": "tv", "webos": "tv",
    # Speaker
    "speaker": "speaker", "sonos": "speaker", "audio": "speaker",
    # Fan
    "ventilator": "ventilator", "fan": "ventilator",
    # Blinds/shutters
    "jaloezie": "jaloezie", "rolgordijn": "jaloezie", "blind": "jaloezie",
    "shutter": "jaloezie", "gordijn": "jaloezie",
    # Door
    "deur": "deur", "door": "deur",
    # Gate
    "poort": "poort", "gate": "poort", "garage": "poort",
    # Alarm
    "alarm": "alarm", "security": "alarm",
    # Camera
    "camera": "camera", "cam": "camera",
}

# device_class → device_type (fallback when keyword matching fails)
_DEVICE_CLASS_MAP: dict[str, str] = {
    "vacuum": "stofzuiger",
    "climate": "verwarming",
    "camera": "camera",
    "door": "deur",
    "gate": "poort",
    "blind": "jaloezie",
    "shade": "jaloezie",
    "motion": "sensor",
    "temperature": "sensor",
    "humidity": "sensor",
}


def infer_device_type(
    entity_id: str,
    friendly_name: str,
    device_class: str | None,
    user_query: str = "",
) -> str | None:
    """Infer a device_type key from entity metadata + optional user query words.
    Returns a key from DEVICE_TYPE_LABELS or None if no match.
    """
    import re
    tokens: list[str] = []
    for text in (user_query, friendly_name, entity_id):
        tokens.extend(re.split(r'[\s._\-]+', text.lower()))

    for token in tokens:
        if token in _KEYWORD_MAP:
            return _KEYWORD_MAP[token]
        # substring check for compound words (e.g. "koffiemachine" contains "koffie")
        for kw, dtype in _KEYWORD_MAP.items():
            if len(kw) >= 4 and kw in token:
                return dtype

    if device_class:
        dc = device_class.lower()
        if dc in _DEVICE_CLASS_MAP:
            return _DEVICE_CLASS_MAP[dc]

    return None


async def async_ensure_kyber_label(hass: HomeAssistant, device_type: str) -> str | None:
    """Get or create the kyber: label for device_type. Returns label_id or None."""
    cfg = DEVICE_TYPE_LABELS.get(device_type)
    if not cfg:
        return None

    label_reg = lr.async_get(hass)
    label_name: str = cfg["name"]
    label_id: str = device_type  # stable slug — HA ≥ 2025.2 always supports label_id param

    if label_reg.async_get_label(label_id) is None:
        try:
            try:
                label_reg.async_create(
                    name=label_name,
                    icon=cfg.get("icon", ""),
                    color=cfg.get("color", ""),
                    label_id=label_id,
                )
            except TypeError:
                # HA versions that dropped the label_id kwarg — create without it
                label_reg.async_create(
                    name=label_name,
                    icon=cfg.get("icon", ""),
                    color=cfg.get("color", ""),
                )
            _LOGGER.info("Kyber: created label '%s' (%s)", label_name, label_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber: could not create label '%s': %s", label_name, err)
            return None
    return label_id


async def async_infer_and_apply_label(
    hass: HomeAssistant,
    entity_id: str,
    user_query: str = "",
) -> dict[str, Any] | None:
    """Infer device type for entity_id and apply a kyber: label if not already labelled.
    Returns label info dict if a label was applied, None otherwise.
    """
    if not entity_id:
        return None

    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get(entity_id)
    if entry is None:
        return None

    # Skip if entity already has any kyber: label
    label_reg = lr.async_get(hass)
    for existing_label_id in (entry.labels or set()):
        lbl = label_reg.async_get_label(existing_label_id)
        if lbl and lbl.name.startswith("kyber:"):
            return None  # already labelled

    # Get entity metadata
    state = hass.states.get(entity_id)
    friendly_name: str = (
        (state.attributes.get("friendly_name") if state else None)
        or entry.name
        or entity_id
    )
    device_class: str | None = (
        (state.attributes.get("device_class") if state else None)
        or entry.device_class
        or entry.original_device_class
    )

    device_type = infer_device_type(entity_id, friendly_name, device_class, user_query)
    if not device_type:
        return None

    label_id = await async_ensure_kyber_label(hass, device_type)
    if not label_id:
        return None

    # Apply label
    try:
        new_labels = set(entry.labels or set()) | {label_id}
        entity_reg.async_update_entity(entity_id, labels=new_labels)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber: could not apply label '%s' to %s: %s", label_id, entity_id, err)
        return None

    cfg = DEVICE_TYPE_LABELS[device_type]
    _LOGGER.info("Kyber: auto-labelled %s → %s", entity_id, cfg["name"])
    return {
        "entity_id": entity_id,
        "label_id": label_id,
        "label_name": cfg["name"],
        "icon": cfg.get("icon", ""),
        "color": cfg.get("color", ""),
        "entity_name": friendly_name,
    }
