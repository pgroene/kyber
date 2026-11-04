"""Unit tests for the recorder tools (custom_components.kyber.statistics_tool).

The pure core is tested directly; the async entry points run against a
recorder stub (the database seams _fetch_statistics/_fetch_history are
replaced).  Covers a meter over a window across midnight
(18:00-08:00) over 30 days, with mean and P90 over the buckets.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_pkg_cc = types.ModuleType("custom_components")
_pkg_cc.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _pkg_cc)

_pkg_kyber = types.ModuleType("custom_components.kyber")
_pkg_kyber.__path__ = [str(ROOT / "custom_components" / "kyber")]
sys.modules["custom_components.kyber"] = _pkg_kyber

_spec = importlib.util.spec_from_file_location(
    "custom_components.kyber.statistics_tool",
    ROOT / "custom_components" / "kyber" / "statistics_tool.py",
)
st = importlib.util.module_from_spec(_spec)
sys.modules["custom_components.kyber.statistics_tool"] = st
_spec.loader.exec_module(st)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=TZ)
FIRST_NIGHT = date(2026, 9, 10)
HOUR = 3600


# ── Helpers ────────────────────────────────────────────────────────────────────


def _hours(start: datetime, end: datetime):
    ts = int(start.timestamp()) // HOUR * HOUR
    while ts < end.timestamp():
        yield ts
        ts += HOUR


def _night_energy_rows(start: datetime, end: datetime, outside: float = 5.0) -> list[dict]:
    """Hourly 'change' rows: night n (1-based from FIRST_NIGHT) uses n kWh in
    total between 18:00 and 08:00; every other hour uses `outside` kWh."""
    window = st.Window(18, 8)
    rows = []
    for ts in _hours(start, end):
        local = datetime.fromtimestamp(ts, timezone.utc).astimezone(TZ)
        anchor = window.anchor(local)
        if anchor is None:
            change = outside
        else:
            change = ((anchor - FIRST_NIGHT).days + 1) / 14
        rows.append({"start": float(ts), "end": float(ts + HOUR), "change": change})
    return rows


class _FakeInstance:
    def __init__(self):
        self.jobs = 0
        self.keep_days = 10

    async def async_add_executor_job(self, fn, *args):
        self.jobs += 1
        return fn(*args)


def _hass(states: dict[str, tuple[str, dict]]) -> SimpleNamespace:
    objs = {
        eid: SimpleNamespace(entity_id=eid, state=s, attributes=a)
        for eid, (s, a) in states.items()
    }
    return SimpleNamespace(
        config=SimpleNamespace(components={"recorder", "http"}),
        states=SimpleNamespace(get=objs.get),
    )


@pytest.fixture
def recorder(monkeypatch):
    """Recorder stub: tests fill `stats`, `meta` and `history`."""
    data = SimpleNamespace(stats={}, meta={}, history={}, instance=_FakeInstance(), calls=[])

    def fetch_statistics(_hass, start, end, ids):
        data.calls.append(("statistics", sorted(ids)))
        return (
            {k: v for k, v in data.stats.items() if k in ids},
            {k: v for k, v in data.meta.items() if k in ids},
        )

    def fetch_history(_hass, start, end, ids):
        data.calls.append(("history", list(ids)))
        return {k: v for k, v in data.history.items() if k in ids}

    def fetch_recent_changes(_hass, start, end, ids, max_points):
        data.calls.append(("recent", list(ids), max_points))
        return {k: (v, False) for k, v in data.history.items() if k in ids}

    monkeypatch.setattr(st, "_fetch_statistics", fetch_statistics)
    monkeypatch.setattr(st, "_fetch_history", fetch_history)
    monkeypatch.setattr(st, "_fetch_recent_changes", fetch_recent_changes)
    monkeypatch.setattr(st, "_recorder_instance", lambda _hass: data.instance)
    monkeypatch.setattr(st, "_local_now", lambda: (NOW, TZ))
    return data


def _series(result: str, index: int = 0) -> dict:
    return json.loads(result)["series"][index]


# ── Parsing ────────────────────────────────────────────────────────────────────


class TestParsing:
    def test_relative_and_iso_times(self):
        assert st.parse_time("30d", NOW, TZ) == NOW - timedelta(days=30)
        assert st.parse_time("90min", NOW, TZ) == NOW - timedelta(minutes=90)
        assert st.parse_time("2026-10-01", NOW, TZ) == datetime(2026, 10, 1, tzinfo=TZ)
        utc = st.parse_time("2026-10-01T18:00:00+00:00", NOW, TZ)
        assert utc.utcoffset() == timedelta(0)

    def test_bad_time_is_a_clear_error(self):
        with pytest.raises(st.StatsError, match="cannot read time"):
            st.parse_time("last month", NOW, TZ)

    def test_window_across_midnight(self):
        window = st.parse_window("18:00-08:00")
        assert (window.start_h, window.end_h, window.wraps) == (18, 8, True)
        assert window.anchor(datetime(2026, 10, 2, 3, 0, tzinfo=TZ)) == date(2026, 10, 1)
        assert window.anchor(datetime(2026, 10, 2, 19, 0, tzinfo=TZ)) == date(2026, 10, 2)
        assert window.anchor(datetime(2026, 10, 2, 12, 0, tzinfo=TZ)) is None

    def test_window_rounds_to_whole_hours(self):
        window = st.parse_window("18:30–07:45")
        assert window.label == "19:00-07:00"
        assert window.rounded

    @pytest.mark.parametrize("text", ["evening", "18:20-18:50", "0-24", "25-3"])
    def test_invalid_windows_rejected(self, text):
        with pytest.raises(st.StatsError):
            st.parse_window(text)

    def test_entity_limit(self):
        ids = [f"sensor.s{i}" for i in range(st.MAX_ENTITIES + 1)]
        with pytest.raises(st.StatsError, match="at most"):
            st.parse_entity_ids({"entity_ids": ids})

    def test_entity_ids_as_comma_string(self):
        assert st.parse_entity_ids({"entity_ids": "sensor.a, sensor.b"}) == ["sensor.a", "sensor.b"]

    def test_start_after_end_rejected(self):
        with pytest.raises(st.StatsError, match="before end"):
            st.resolve_range({"start": "1d", "end": "2d"}, NOW, TZ, "7d")


# ── Bucketing ─────────────────────────────────────────────────────────────────


class TestBuckets:
    def test_thirty_complete_nights(self):
        window = st.parse_window("18:00-08:00")
        buckets = st.plan_buckets(NOW - timedelta(days=30), NOW, TZ, "day", window)
        assert [b.label for b in buckets][:2] == ["2026-09-10", "2026-09-11"]
        assert len(buckets) == 30
        assert all(b.expected == 14 and not b.partial for b in buckets)

    def test_running_night_is_partial(self):
        now = datetime(2026, 10, 10, 3, 0, tzinfo=TZ)
        window = st.parse_window("18:00-08:00")
        buckets = st.plan_buckets(now - timedelta(days=2), now, TZ, "day", window)
        last = buckets[-1]
        assert last.label == "2026-10-09"
        assert last.partial and len(last.hours) == 9

    def test_dst_day_has_25_hours(self):
        start = datetime(2026, 10, 24, tzinfo=TZ)
        end = datetime(2026, 10, 27, tzinfo=TZ)
        by_label = {b.label: b for b in st.plan_buckets(start, end, TZ, "day", None)}
        assert by_label["2026-10-25"].expected == 25
        assert not by_label["2026-10-25"].partial

    def test_weeks_start_on_monday(self):
        start = datetime(2026, 9, 28, tzinfo=TZ)  # a Monday
        buckets = st.plan_buckets(start, start + timedelta(days=14), TZ, "week", None)
        assert [b.label for b in buckets] == ["2026-09-28", "2026-10-05"]


# ── Aggregation ───────────────────────────────────────────────────────────────


class TestDistribution:
    def test_quantiles_interpolate(self):
        dist = st.distribution([float(v) for v in range(1, 31)])
        assert dist["n"] == 30
        assert dist["mean"] == 15.5
        assert dist["median"] == 15.5
        assert dist["p10"] == pytest.approx(3.9)
        assert dist["p90"] == pytest.approx(27.1)
        assert (dist["min"], dist["max"]) == (1.0, 30.0)


class TestStatisticsTool:
    async def test_night_window_p90_over_30_days(self, recorder):
        recorder.stats["sensor.energy_import"] = _night_energy_rows(NOW - timedelta(days=31), NOW)
        recorder.meta["sensor.energy_import"] = {"has_sum": True, "circular": False, "unit": "kWh"}
        hass = _hass({"sensor.energy_import": ("4711.2", {
            "state_class": "total_increasing", "unit_of_measurement": "kWh",
        })})
        out = json.loads(await st.async_execute_statistics(hass, {
            "entity_ids": ["sensor.energy_import"], "start": "30d",
            "interval": "day", "window": "18:00-08:00", "distribution": True,
        }))
        assert out["window"] == "18:00-08:00"
        series = out["series"][0]
        assert (series["kind"], series["source"], series["unit"]) == ("counter", "statistics", "kWh")
        assert series["rows"][0] == ["2026-09-10", 1.0]
        assert series["rows"][-1] == ["2026-10-09", 30.0]
        dist = series["distribution"]
        assert dist["of"] == "change"
        assert dist["n"] == 30
        assert dist["mean"] == 15.5
        assert dist["p90"] == pytest.approx(27.1)
        assert dist["p10"] == pytest.approx(3.9)
        assert recorder.calls == [("statistics", ["sensor.energy_import"])]

    async def test_partial_night_left_out_of_distribution(self, recorder, monkeypatch):
        now = datetime(2026, 10, 10, 3, 0, tzinfo=TZ)
        monkeypatch.setattr(st, "_local_now", lambda: (now, TZ))
        recorder.stats["sensor.energy_import"] = _night_energy_rows(now - timedelta(days=4), now)
        recorder.meta["sensor.energy_import"] = {"has_sum": True}
        hass = _hass({"sensor.energy_import": ("1", {"state_class": "total_increasing"})})
        out = json.loads(await st.async_execute_statistics(hass, {
            "entity_ids": ["sensor.energy_import"], "start": "3d",
            "window": "18:00-08:00", "distribution": True,
        }))
        series = out["series"][0]
        # The night the period starts in and the night still running
        assert series["partial"] == ["2026-10-06", "2026-10-09"]
        assert "left out of the distribution" in out["legend"]
        assert series["distribution"]["n"] == len(series["rows"]) - 2 == 2

    async def test_counter_uses_difference_not_mean(self, recorder):
        # Meter at 1000 kWh, +1 kWh every hour (at half past), no statistics.
        start = NOW - timedelta(days=3, hours=1)
        changes, reading = [], 1000.0
        for ts in _hours(start, NOW):
            changes.append((ts + 1800.0, f"{reading:.1f}"))
            reading += 1
        recorder.history["sensor.meter"] = changes
        hass = _hass({"sensor.meter": (f"{reading}", {"state_class": "total_increasing"})})
        series = _series(await st.async_execute_statistics(hass, {
            "entity_ids": ["sensor.meter"], "start": "3d", "interval": "day",
        }))
        assert (series["kind"], series["source"]) == ("counter", "history")
        assert series["columns"] == ["start", "change"]
        complete = [r for r in series["rows"] if r[0] not in series.get("partial", [])]
        assert complete and all(r[1] == 24.0 for r in complete)
        assert recorder.calls == [("statistics", ["sensor.meter"]), ("history", ["sensor.meter"])]

    def test_total_increasing_reset_counts_new_reading(self):
        base = 1_000_000 * HOUR
        changes = [(base + 0.0, "50"), (base + 600.0, "52"), (base + 1200.0, "0.5"), (base + 1800.0, "1.5")]
        points = st.history_counter_points(changes, base, base + HOUR, "total_increasing")
        assert points[base]["change"] == pytest.approx(2 + 0.5 + 1)

    async def test_measurement_mean_min_max_from_statistics(self, recorder):
        rows = []
        day_start = datetime(2026, 10, 8, tzinfo=TZ)
        for i, ts in enumerate(_hours(day_start, day_start + timedelta(days=1))):
            rows.append({"start": float(ts), "mean": 20.0 + (i % 2), "min": 18.0 + i / 100, "max": 23.0 - i / 100})
        recorder.stats["sensor.room_temperature"] = rows
        recorder.meta["sensor.room_temperature"] = {"has_sum": False, "unit": "°C"}
        hass = _hass({"sensor.room_temperature": ("21", {"state_class": "measurement"})})
        series = _series(await st.async_execute_statistics(hass, {
            "entity_ids": ["sensor.room_temperature"],
            "start": "2026-10-08", "end": "2026-10-09",
            "distribution": True, "stat": "max",
        }))
        assert (series["kind"], series["unit"]) == ("measurement", "°C")
        assert series["columns"] == ["start", "mean", "min", "max"]
        assert series["rows"] == [["2026-10-08", 20.5, 18.0, 23.0]]
        assert series["distribution"]["of"] == "max"
        assert series["distribution"]["mean"] == 23.0

    async def test_non_numeric_states_hours_per_option(self, recorder):
        day = datetime(2026, 10, 8, tzinfo=TZ).timestamp()
        recorder.history["input_select.heating_mode"] = [
            (day - HOUR, "eco"),
            (day + 6 * HOUR, "comfort"),
            (day + 8 * HOUR, "away"),
            (day + 17 * HOUR, "comfort"),
            (day + 22 * HOUR, "eco"),
        ]
        hass = _hass({"input_select.heating_mode": ("eco", {"options": ["eco", "comfort", "away"]})})
        series = _series(await st.async_execute_statistics(hass, {
            "entity_ids": ["input_select.heating_mode"],
            "start": "2026-10-08", "end": "2026-10-09",
            "distribution": True, "state": "comfort",
        }))
        assert series["kind"] == "states"
        assert series["unit"] == "h"
        row = dict(zip(series["columns"], series["rows"][0]))
        assert row == {"start": "2026-10-08", "eco": 8.0, "away": 9.0, "comfort": 7.0}
        assert series["distribution"]["of"] == "hours in 'comfort'"
        assert series["distribution"]["mean"] == 7.0

    async def test_states_without_target_explain_distribution(self, recorder):
        recorder.history["binary_sensor.window"] = [(NOW.timestamp() - 5 * HOUR, "off")]
        hass = _hass({"binary_sensor.window": ("off", {})})
        series = _series(await st.async_execute_statistics(hass, {
            "entity_ids": ["binary_sensor.window"], "start": "1d", "distribution": True,
        }))
        assert "pass 'state'" in series["distribution"]["error"]

    async def test_answer_size_is_bounded(self, recorder):
        ids = [f"sensor.power_{i}" for i in range(st.MAX_ENTITIES)]
        states = {}
        for eid in ids:
            recorder.stats[eid] = _night_energy_rows(NOW - timedelta(days=31), NOW)
            recorder.meta[eid] = {"has_sum": True, "unit": "kWh"}
            states[eid] = ("1", {"state_class": "total"})
        result = await st.async_execute_statistics(_hass(states), {
            "entity_ids": ids, "start": "30d", "interval": "hour", "distribution": True,
        })
        assert len(result) <= st.MAX_RESULT_CHARS
        out = json.loads(result)
        assert "coarser interval" in out["note"]
        for series in out["series"]:
            assert series["rows_omitted"] > 0
            assert series["distribution"]["n"] > 600

    async def test_missing_recorder_is_a_clear_error(self, monkeypatch):
        monkeypatch.setattr(st, "_local_now", lambda: (NOW, TZ))
        hass = SimpleNamespace(
            config=SimpleNamespace(components={"http"}),
            states=SimpleNamespace(get=lambda _eid: None),
        )
        for run in (st.async_execute_statistics, st.async_execute_history):
            out = json.loads(await run(hass, {"entity_ids": ["sensor.energy_import"]}))
            assert "recorder is not available" in out["error"]

    async def test_bad_arguments_return_error_json(self, recorder):
        out = json.loads(await st.async_execute_statistics(_hass({}), {
            "entity_ids": ["sensor.a"], "window": "after dinner",
        }))
        assert "window must look like" in out["error"]
        assert recorder.instance.jobs == 0

    async def test_unknown_entity_reported_per_series(self, recorder):
        recorder.stats["sensor.energy_import"] = _night_energy_rows(NOW - timedelta(days=2), NOW)
        recorder.meta["sensor.energy_import"] = {"has_sum": True}
        hass = _hass({"sensor.energy_import": ("1", {"state_class": "total"})})
        out = json.loads(await st.async_execute_statistics(hass, {
            "entity_ids": ["sensor.energy_import", "sensor.does_not_exist"], "start": "1d",
        }))
        assert out["series"][0]["kind"] == "counter"
        assert "not found" in out["series"][1]["error"]

    async def test_recorder_failure_is_reported(self, recorder, monkeypatch):
        def boom(*_args):
            raise RuntimeError("database is locked")
        monkeypatch.setattr(st, "_fetch_statistics", boom)
        hass = _hass({"sensor.a": ("1", {"state_class": "measurement"})})
        out = json.loads(await st.async_execute_statistics(hass, {"entity_ids": ["sensor.a"]}))
        assert "database is locked" in out["error"]


class TestHistoryTool:
    async def test_changes_merged_and_newest_kept(self, recorder):
        base = NOW.timestamp() - 10 * HOUR
        recorder.history["switch.pump"] = [
            (base + i * 600.0, "on" if i % 2 else "off") for i in range(30)
        ] + [(base + 30 * 600.0, "on")]
        hass = _hass({"switch.pump": ("on", {"friendly_name": "Pump"})})
        out = json.loads(await st.async_execute_history(hass, {
            "entity_ids": "switch.pump", "max_points": 5,
        }))
        series = out["series"][0]
        assert series["name"] == "Pump"
        assert len(series["rows"]) == 5
        assert series["rows"][-1] == ["2026-10-10 06:50:00", "on"]  # trailing repeat merged
        assert series["more_before"] is True
        assert "newest changes" in out["more_before"]
        assert recorder.calls == [("recent", ["switch.pump"], 5)]

    async def test_period_before_purge_horizon_is_explained(self, recorder):
        hass = _hass({"sensor.energy_import": ("1", {"state_class": "total_increasing"})})
        out = json.loads(await st.async_execute_history(hass, {
            "entity_ids": ["sensor.energy_import"],
            "start": "2026-09-18T18:00", "end": "2026-09-19T08:00",
        }))
        assert out["series"][0]["rows"] == []
        assert "only kept since 2026-09-30T12:00" in out["note"]
        assert "no outage" in out["note"]

    async def test_recent_period_has_no_purge_note(self, recorder):
        recorder.history["switch.pump"] = [(NOW.timestamp() - HOUR, "on")]
        out = json.loads(await st.async_execute_history(_hass({"switch.pump": ("on", {})}), {
            "entity_ids": ["switch.pump"], "start": "6h",
        }))
        assert "note" not in out
        assert "more_before" not in out["series"][0]


class TestStatisticsPurgeHorizon:
    async def test_history_fallback_before_horizon_is_a_note_not_an_error(self, recorder):
        hass = _hass({"input_select.heating_mode": ("eco", {})})
        series = _series(await st.async_execute_statistics(hass, {
            "entity_ids": ["input_select.heating_mode"], "start": "30d",
        }))
        assert series["source"] == "history"
        assert "error" not in series
        assert "get_statistics" in series["note"]

    async def test_statistics_source_needs_no_note(self, recorder):
        recorder.stats["sensor.energy_import"] = _night_energy_rows(NOW - timedelta(days=31), NOW)
        recorder.meta["sensor.energy_import"] = {"has_sum": True}
        hass = _hass({"sensor.energy_import": ("1", {"state_class": "total_increasing"})})
        series = _series(await st.async_execute_statistics(hass, {
            "entity_ids": ["sensor.energy_import"], "start": "30d",
        }))
        assert "note" not in series


class TestRecorderRowFormats:
    def test_compressed_and_state_rows(self):
        state = SimpleNamespace(state="on", last_changed=datetime(2026, 10, 1, tzinfo=timezone.utc))
        assert st._change_of({"s": "21.5", "lu": 100.0}) == (100.0, "21.5")
        assert st._change_of({"s": "on", "lu": 200.0, "lc": 150.0}) == (150.0, "on")
        assert st._change_of(state) == (state.last_changed.timestamp(), "on")
        assert st._change_of({"lu": 1.0}) is None

    def test_history_since_from_keep_days(self):
        assert st._history_since(SimpleNamespace(keep_days=10), NOW) == NOW - timedelta(days=10)
        assert st._history_since(SimpleNamespace(), NOW) is None


# ── Contract with Home Assistant's recorder API ──────────────────────────────


def test_recorder_calls_match_home_assistant_signatures():
    """The calls in the _fetch_* seams bind to HA's functions."""
    stats = pytest.importorskip("homeassistant.components.recorder.statistics")
    history = pytest.importorskip("homeassistant.components.recorder.history")
    now = datetime.now(timezone.utc)
    inspect.signature(stats.statistics_during_period).bind(
        None, now, now, {"sensor.a"}, "hour", None, {"change", "mean", "min", "max"}
    )
    inspect.signature(stats.get_metadata).bind(None, statistic_ids={"sensor.a"})
    inspect.signature(history.get_significant_states).bind(
        None, now, now, ["sensor.a"],
        include_start_time_state=True, significant_changes_only=True,
        minimal_response=True, no_attributes=True, compressed_state_format=True,
    )
    inspect.signature(history.state_changes_during_period).bind(
        None, now, now, "sensor.a", no_attributes=True, include_start_time_state=False,
    )
