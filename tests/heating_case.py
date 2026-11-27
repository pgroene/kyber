"""Shared data of the living room heating case, with generic names.

A user asked Kyber to fix the automation that heats the living room by a mode
selector and a schedule helper. Kyber's first two attempts invented selector
options and schedule values, read a schedule attribute that does not exist
and never set ``hvac_mode``, so the thermostat stayed off. After the
automation check went in, the live model produced a working fix in one
correction round. The real entity names are replaced by generic ones here.

The automations live in ``fixtures/heating_case/``:

- ``reference.yaml``: written by hand as the reference solution,
- ``kyber_attempt_1.yaml``, ``kyber_attempt_2.yaml``: the broken attempts,
- ``kyber_checked_fix.yaml``: the live answer after the check's correction.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from homeassistant.core import HomeAssistant, SupportsResponse

FIXTURES = Path(__file__).parent / "fixtures" / "heating_case"

MODE = "input_select.livingroom_heating_mode"
SCHEDULE = "schedule.livingroom_heating_schedule"
THERMOSTAT = "climate.livingroom_thermostat"
COMFORT = "input_number.livingroom_comfort_temperature"
SETBACK = "input_number.livingroom_setback_temperature"
WORKDAY = "binary_sensor.workday"
AWAY = "input_boolean.heating_away"
AWAY_MODE = "input_select.heating_away_mode"

MODE_OPTIONS = ["Heat", "Auto", "Setback", "Off"]
# Block data of the schedule helper, as schedule.get_schedule returns it.
SCHEDULE_BLOCKS = {
    "monday": [
        {"from": "05:30:00", "to": "07:30:00", "data": {"mode": "Auto"}},
        {"from": "21:30:00", "to": "23:59:59", "data": {"mode": "Setback"}},
    ],
    "tuesday": [{"from": "05:30:00", "to": "07:30:00", "data": {"mode": "Auto"}}],
}


def load(name: str) -> dict[str, Any]:
    """One automation from the fixtures, as a dict."""
    return yaml.safe_load((FIXTURES / f"{name}.yaml").read_text(encoding="utf-8"))


def set_up_home(hass: HomeAssistant, *, thermostat: str = "off") -> None:
    """The entities of the case, and schedule.get_schedule answering with the blocks."""
    hass.states.async_set(MODE, "Auto", {"options": MODE_OPTIONS})
    hass.states.async_set(SCHEDULE, "on", {"mode": "Auto", "next_event": "2026-10-22T07:30:00", "editable": True})
    hass.states.async_set(
        THERMOSTAT, thermostat,
        {"hvac_modes": ["off", "heat"], "temperature": 20.5, "current_temperature": 18.1},
    )
    hass.states.async_set(COMFORT, "20.5", {"min": 15, "max": 25})
    hass.states.async_set(SETBACK, "17.0", {"min": 12, "max": 20})
    hass.states.async_set(WORKDAY, "on")
    hass.states.async_set(AWAY, "off")
    hass.states.async_set(AWAY_MODE, "Setback", {"options": ["Setback", "Off"]})

    async def get_schedule(call):
        return {SCHEDULE: SCHEDULE_BLOCKS}

    hass.services.async_register("schedule", "get_schedule", get_schedule, supports_response=SupportsResponse.ONLY)
