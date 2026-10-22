"""The living room heating case run as real automations in a Home Assistant test instance.

Each automation from ``fixtures/heating_case/`` is set up with the automation
integration; the test switches the heating mode or the schedule and records
which climate service calls Home Assistant makes. The thermostat starts in the
state that fits the situation before the switch (off before a heating block,
heating before a setback), so doing nothing never passes by accident.

Only the basic behaviour the user asked Kyber for is required: Off = off,
Setback = setback temperature, Auto = follow the schedule. Two cases the
request left open accept two answers: outside a block (off or setback) and a
heating block on a day off (comfort or setback). The away switch and the
"Heat" mode were added later and are checked on the reference only.
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from tests.heating_case import (
    AWAY,
    AWAY_MODE,
    COMFORT,
    MODE,
    SCHEDULE,
    THERMOSTAT,
    WORKDAY,
    load,
    set_up_home,
)

OFF = "off"
COMFORT_HEAT = ("heat", 20.5)
SETBACK_HEAT = ("heat", 17.0)
GAP = "gap"  # no schedule block active
REJECTED = "call Home Assistant would reject"


def _schedule(hass: HomeAssistant, block: str) -> None:
    if block == GAP:
        hass.states.async_set(SCHEDULE, "off", {})
    else:
        hass.states.async_set(SCHEDULE, "on", {"mode": block})


def _thermostat(hass: HomeAssistant, start) -> None:
    if start == OFF:
        hass.states.async_set(THERMOSTAT, "off", {"hvac_modes": ["off", "heat"]})
    else:
        hass.states.async_set(THERMOSTAT, start[0], {"hvac_modes": ["off", "heat"], "temperature": start[1]})


async def _set_up(hass: HomeAssistant, name: str, *, mode: str, block: str, start, workday: str = "on") -> list:
    """Load the automation with the house in the given situation; return the call log."""
    set_up_home(hass)
    hass.states.async_set(WORKDAY, workday)
    _schedule(hass, block)
    _thermostat(hass, start)
    hass.states.async_set(MODE, mode, {"options": ["Heat", "Auto", "Setback", "Off"]})

    calls: list[tuple[str, dict]] = []

    async def record(call):
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("climate", "set_temperature", record)
    hass.services.async_register("climate", "set_hvac_mode", record)
    config = {"id": name, **load(name)}
    assert await async_setup_component(hass, "automation", {"automation": [config]})
    await hass.async_block_till_done()
    calls.clear()  # only what the switch below causes counts
    return calls


def _end_state(calls: list, start):
    """The thermostat after all calls, starting from ``start``."""
    hvac, temp = ("off", None) if start == OFF else start
    for service, data in calls:
        if service == "set_hvac_mode":
            hvac = data.get("hvac_mode")
            continue
        try:
            temp = float(data.get("temperature"))
        except (TypeError, ValueError):
            return REJECTED
        hvac = data.get("hvac_mode", hvac)
    return OFF if hvac == "off" else (hvac, temp)


# Switching the heating mode: (before, after, schedule block, workday, thermostat before, accepted)
MODE_SWITCHES = [
    ("Auto", "Off", "Auto", "on", COMFORT_HEAT, [OFF]),
    ("Auto", "Setback", "Auto", "on", COMFORT_HEAT, [SETBACK_HEAT]),
    ("Off", "Setback", "Auto", "on", OFF, [SETBACK_HEAT]),
    ("Off", "Auto", "Auto", "on", OFF, [COMFORT_HEAT]),
    ("Off", "Auto", "Setback", "on", OFF, [SETBACK_HEAT]),
    ("Off", "Auto", "Auto", "off", OFF, [COMFORT_HEAT, SETBACK_HEAT]),  # left open by the request
    ("Setback", "Auto", GAP, "on", SETBACK_HEAT, [OFF, SETBACK_HEAT]),   # left open by the request
]
# Schedule changes in mode Auto: (block before, block after, thermostat before, accepted)
SCHEDULE_CHANGES = [
    (GAP, "Auto", OFF, [COMFORT_HEAT]),
    ("Auto", "Setback", COMFORT_HEAT, [SETBACK_HEAT]),
    (GAP, "Setback", OFF, [SETBACK_HEAT]),
    ("Setback", "Auto", SETBACK_HEAT, [COMFORT_HEAT]),
    ("Auto", GAP, COMFORT_HEAT, [OFF, SETBACK_HEAT]),       # left open by the request
    ("Setback", GAP, SETBACK_HEAT, [OFF, SETBACK_HEAT]),    # left open by the request
]

WORKING = ["reference", "kyber_checked_fix"]


@pytest.mark.parametrize("name", WORKING)
@pytest.mark.parametrize(
    ("before", "after", "block", "workday", "start", "accepted"), MODE_SWITCHES,
    ids=[f"mode {b}->{a} block={k} workday={w}" for b, a, k, w, _, _ in MODE_SWITCHES],
)
async def test_mode_switch(hass, name, before, after, block, workday, start, accepted):
    calls = await _set_up(hass, name, mode=before, block=block, start=start, workday=workday)
    hass.states.async_set(MODE, after, {"options": ["Heat", "Auto", "Setback", "Off"]})
    await hass.async_block_till_done()
    assert _end_state(calls, start) in accepted, calls


@pytest.mark.parametrize("name", WORKING)
@pytest.mark.parametrize(
    ("before", "after", "start", "accepted"), SCHEDULE_CHANGES,
    ids=[f"schedule {b}->{a}" for b, a, _, _ in SCHEDULE_CHANGES],
)
async def test_schedule_change(hass, name, before, after, start, accepted):
    calls = await _set_up(hass, name, mode="Auto", block=before, start=start)
    _schedule(hass, after)
    await hass.async_block_till_done()
    assert _end_state(calls, start) in accepted, calls


@pytest.mark.parametrize("name", ["kyber_attempt_1", "kyber_attempt_2"])
async def test_the_broken_attempts_leave_the_thermostat_off(hass, name):
    """The reported failure: mode Auto in a heating block, and the thermostat stays off."""
    calls = await _set_up(hass, name, mode="Off", block="Auto", start=OFF)
    hass.states.async_set(MODE, "Auto", {"options": ["Heat", "Auto", "Setback", "Off"]})
    await hass.async_block_till_done()
    assert _end_state(calls, OFF) in (OFF, REJECTED), calls


# ── the reference's later additions ──────────────────────────────────────────

async def test_reference_heat_mode(hass):
    calls = await _set_up(hass, "reference", mode="Off", block=GAP, start=OFF)
    hass.states.async_set(MODE, "Heat", {"options": ["Heat", "Auto", "Setback", "Off"]})
    await hass.async_block_till_done()
    assert _end_state(calls, OFF) == COMFORT_HEAT


@pytest.mark.parametrize(("away_mode", "expected"), [("Setback", SETBACK_HEAT), ("Off", OFF)])
async def test_reference_away_overrides_a_heating_room(hass, away_mode, expected):
    calls = await _set_up(hass, "reference", mode="Heat", block=GAP, start=COMFORT_HEAT)
    hass.states.async_set(AWAY_MODE, away_mode, {"options": ["Setback", "Off"]})
    await hass.async_block_till_done()
    calls.clear()
    hass.states.async_set(AWAY, "on")
    await hass.async_block_till_done()
    assert _end_state(calls, COMFORT_HEAT) == expected


async def test_reference_away_never_switches_a_room_on(hass):
    calls = await _set_up(hass, "reference", mode="Off", block="Auto", start=OFF)
    hass.states.async_set(AWAY, "on")
    await hass.async_block_till_done()
    assert _end_state(calls, OFF) == OFF


async def test_reference_follows_a_new_temperature(hass):
    calls = await _set_up(hass, "reference", mode="Heat", block=GAP, start=COMFORT_HEAT)
    hass.states.async_set(COMFORT, "22.5", {"min": 15, "max": 25})
    await hass.async_block_till_done()
    assert _end_state(calls, COMFORT_HEAT) == ("heat", 22.5)


# ── what the automation check says about each fixture ────────────────────────

@pytest.mark.parametrize(("name", "clean"), [
    ("reference", True), ("kyber_checked_fix", True), ("kyber_attempt_1", False), ("kyber_attempt_2", False),
])
async def test_the_check_tells_working_from_broken(hass, name, clean):
    # Imported here, after the module stubs of other test files are restored.
    from custom_components.kyber import automation_check

    set_up_home(hass)
    findings = await automation_check.check_config(hass, load(name))
    errors = [f.text for f in findings if f.severity == automation_check.ERROR]
    assert (errors == []) is clean, errors
