"""The recorder tools against Home Assistant's real recorder (in-memory SQLite).

test_statistics_tool.py replaces the database seams; this file runs
_fetch_statistics and _fetch_history for real, so a changed recorder API
shows up here and not only on a live instance.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.components.recorder.common")

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.kyber.statistics_tool import (
    async_execute_history,
    async_execute_statistics,
)


@pytest.fixture(autouse=True)
def mock_recorder_before_hass(async_test_recorder) -> None:
    """The recorder must be prepared before the hass fixture starts."""


async def test_counter_statistics_per_day(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.energy_import", "1000",
        {"state_class": "total_increasing", "unit_of_measurement": "kWh"},
    )
    last_hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    first = last_hour - timedelta(hours=96)
    rows = [
        {"start": first + timedelta(hours=i), "state": 1000.0 + i, "sum": float(i)}
        for i in range(97)
    ]
    async_import_statistics(hass, {
        "has_mean": False,
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": None,
        "source": "recorder",
        "statistic_id": "sensor.energy_import",
        "unit_class": "energy",
        "unit_of_measurement": "kWh",
    }, rows)
    await async_wait_recording_done(hass)

    out = json.loads(await async_execute_statistics(hass, {
        "entity_ids": ["sensor.energy_import"], "start": "3d", "distribution": True,
    }))
    series = out["series"][0]
    assert (series["kind"], series["source"], series["unit"]) == ("counter", "statistics", "kWh")
    skipped = set(series.get("partial", [])) | set(series.get("missing_hours", {}))
    complete = [row for row in series["rows"] if row[0] not in skipped]
    assert complete and all(row[1] == 24.0 for row in complete)
    assert series["distribution"]["median"] == 24.0


async def test_select_history_hours_and_changes(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    now = dt_util.utcnow().timestamp()
    for offset, state in ((-5, "eco"), (-3, "comfort"), (-1, "away")):
        hass.states.async_set(
            "input_select.heating_mode", state,
            {"options": ["eco", "comfort", "away"]},
            timestamp=now + offset * 3600,
        )
    await async_wait_recording_done(hass)

    history = json.loads(await async_execute_history(hass, {
        "entity_ids": ["input_select.heating_mode"], "start": "6h",
    }))
    assert [row[1] for row in history["series"][0]["rows"]] == ["eco", "comfort", "away"]

    stats = json.loads(await async_execute_statistics(hass, {
        "entity_ids": ["input_select.heating_mode"], "start": "6h", "interval": "hour",
    }))
    series = stats["series"][0]
    assert (series["kind"], series["source"]) == ("states", "history")
    assert series["totals_h"]["comfort"] == pytest.approx(2.0, abs=0.02)


async def test_history_returns_newest_changes_of_a_busy_meter(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    # A meter reporting every 10 s for 8 hours, then an attribute-only update.
    count = 8 * 360
    now = dt_util.utcnow().timestamp()
    first = now - count * 10
    for i in range(count):
        hass.states.async_set("sensor.energy_import", f"{1000 + i * 0.001:.3f}",
                              {"unit_of_measurement": "kWh"}, timestamp=first + i * 10)
    last = f"{1000 + (count - 1) * 0.001:.3f}"
    hass.states.async_set("sensor.energy_import", last,
                          {"unit_of_measurement": "kWh", "extra": 1}, timestamp=now - 1)
    await async_wait_recording_done(hass)

    out = json.loads(await async_execute_history(hass, {
        "entity_ids": ["sensor.energy_import"], "start": "1d", "max_points": 20,
    }))
    series = out["series"][0]
    assert len(series["rows"]) == 20
    assert series["more_before"] is True
    assert series["rows"][-1][1] == last
    newest = [float(r[1]) for r in series["rows"]]
    assert newest == sorted(newest)


async def test_history_before_purge_horizon_is_explained(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    hass.states.async_set("sensor.energy_import", "1000", {"state_class": "total_increasing"})
    await async_wait_recording_done(hass)
    keep_days = recorder_mock.keep_days
    out = json.loads(await async_execute_history(hass, {
        "entity_ids": ["sensor.energy_import"], "start": f"{keep_days + 5}d",
    }))
    assert "no outage" in out["note"]
