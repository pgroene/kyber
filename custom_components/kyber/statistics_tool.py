"""Recorder-backed history and statistics tools for the chat AI.

Kyber only saw the current state of an entity, so questions about the past
("average kWh per day", "what was the average indoor temperature last month,
and how cold was the coldest day") could only be estimated.  Two tools close
that gap:

``get_history``
    The recorded state changes of one or more entities, newest last, capped
    to a small number of points.  For "when did X last change" or a quick
    look at a short span.

``get_statistics``
    Aggregates over a period: per hour, day or week, optionally restricted
    to a time-of-day window that may cross midnight ("18:00-08:00", counted
    for the day it starts), optionally with a distribution over the buckets (mean,
    median, P10, P90, min, max).  The model gets the answer, not 720 hourly
    values it would have to add up itself.

How values are aggregated depends on the entity:

* counters (state_class ``total``/``total_increasing``): the difference per
  bucket, never a mean of meter readings;
* measurements (any other numeric entity): mean, min and max per bucket;
* non-numeric entities (on/off, heat/idle, an input_select with many
  options): hours spent in each state per bucket.

Long-term statistics (hourly, kept indefinitely) are preferred; entities
without statistics fall back to the state history, which is turned into the
same hourly points.  Every bucket that is not fully inside the requested
period is marked ``partial`` and every bucket with hours lacking data is
listed under ``missing_hours``; both are left out of the distribution.

The pure core (parsing, bucketing, aggregation, size limiting) has no Home
Assistant imports and is tested directly.  Database access happens in
``_fetch_statistics``/``_fetch_history`` on the recorder's own executor.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

MAX_ENTITIES = 10
MAX_SPAN = timedelta(days=400)
# Below MAX_TOOL_RESULT_CHARS so the generic truncation never cuts the JSON.
MAX_RESULT_CHARS = 3_500
HISTORY_DEFAULT_POINTS = 40
HISTORY_MAX_POINTS = 200
MAX_STATE_COLUMNS = 6

COUNTER_CLASSES = {"total", "total_increasing"}
_NO_VALUE = {"unknown", "unavailable", "none", ""}
_HOUR = 3600

_REL_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(min|m|h|d|w)\s*$", re.IGNORECASE)
_REL_UNITS = {"min": 60, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_WINDOW_RE = re.compile(
    r"^\s*(\d{1,2})(?::(\d{2}))?\s*(?:-|–|—|to)\s*(\d{1,2})(?::(\d{2}))?\s*$", re.IGNORECASE
)
_INTERVALS = {
    "hour": "hour", "hourly": "hour", "h": "hour",
    "day": "day", "daily": "day", "d": "day",
    "week": "week", "weekly": "week", "w": "week",
}
_STATS = ("mean", "min", "max")


class StatsError(ValueError):
    """Raised for a rejected tool call; the message is safe to show the AI."""


# ── Parsing ───────────────────────────────────────────────────────────────────


def parse_time(value: Any, now: datetime, tz: tzinfo) -> datetime:
    """Parse '30d'/'12h'/'90min' (that long before *now*) or an ISO date/time.

    A naive ISO value is local time; a bare date means local midnight.
    """
    text = str(value or "").strip()
    match = _REL_RE.match(text)
    if match:
        seconds = float(match.group(1)) * _REL_UNITS[match.group(2).lower()]
        return now - timedelta(seconds=seconds)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise StatsError(
            f"cannot read time {text!r} — use a relative span like '30d', '12h' "
            "or an ISO date/time like '2026-10-01' or '2026-10-01T18:00'"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def resolve_range(
    call: dict[str, Any], now: datetime, tz: tzinfo, default_start: str
) -> tuple[datetime, datetime]:
    """Return (start, end) from the call's `start`/`period` and `end`."""
    start_raw = call.get("start") or call.get("period") or call.get("since") or default_start
    start = parse_time(start_raw, now, tz)
    end = parse_time(call["end"], now, tz) if call.get("end") else now
    end = min(end, now)
    if start >= end:
        raise StatsError("start must be before end (and in the past)")
    if end - start > MAX_SPAN:
        raise StatsError(f"period too long (max {MAX_SPAN.days} days)")
    return start, end


@dataclass(frozen=True)
class Window:
    """A time-of-day window in whole local hours; may cross midnight."""

    start_h: int
    end_h: int
    rounded: bool = False

    @property
    def wraps(self) -> bool:
        return self.end_h <= self.start_h

    @property
    def label(self) -> str:
        return f"{self.start_h:02d}:00-{self.end_h:02d}:00"

    def contains(self, hour: int) -> bool:
        if self.wraps:
            return hour >= self.start_h or hour < self.end_h
        return self.start_h <= hour < self.end_h

    def anchor(self, local: datetime) -> date | None:
        """Day a local hour belongs to; a night counts for the evening it starts."""
        if not self.contains(local.hour):
            return None
        if self.wraps and local.hour < self.end_h:
            return local.date() - timedelta(days=1)
        return local.date()


def parse_window(text: Any) -> Window:
    """Parse '18:00-08:00' (also '18-8', '18:30–07:45').

    Long-term statistics are hourly, so only hours lying wholly inside the
    window count: the start rounds up, the end rounds down.
    """
    match = _WINDOW_RE.match(str(text or ""))
    if not match:
        raise StatsError("window must look like '18:00-08:00'")
    sh, sm, eh, em = (int(g) if g else 0 for g in match.groups())
    if sh > 24 or eh > 24 or sm > 59 or em > 59:
        raise StatsError(f"invalid window {text!r}")
    start_h = (sh + (1 if sm else 0)) % 24
    end_h = eh % 24
    no_full_hour = "window holds no full hour — use whole hours like '18:00-08:00'"
    if start_h == end_h:
        if sm or em:
            raise StatsError(no_full_hour)
        raise StatsError("window covers the whole day — leave 'window' out")
    # Rounding must not turn a short same-day window into one across midnight.
    if sh * 60 + sm < eh * 60 + em and start_h > end_h:
        raise StatsError(no_full_hour)
    return Window(start_h, end_h, rounded=bool(sm or em))


def parse_interval(value: Any, default: str) -> str:
    text = str(value or default).strip().lower()
    if text not in _INTERVALS:
        raise StatsError("interval must be 'hour', 'day' or 'week'")
    return _INTERVALS[text]


def parse_entity_ids(call: dict[str, Any]) -> list[str]:
    raw = call.get("entity_ids") or call.get("entity_id") or call.get("entities")
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[,\s]+", raw) if p]
    if not isinstance(raw, list) or not raw:
        raise StatsError("Missing 'entity_ids' argument (list of entity ids)")
    ids: list[str] = []
    for item in raw:
        eid = str(item).strip()
        if "." not in eid:
            raise StatsError(f"{eid!r} is not an entity id (format: domain.name)")
        if eid not in ids:
            ids.append(eid)
    if len(ids) > MAX_ENTITIES:
        raise StatsError(f"at most {MAX_ENTITIES} entity ids per call")
    return ids


# ── Bucketing ─────────────────────────────────────────────────────────────────


@dataclass
class Bucket:
    """One output row: which hours it should have and which lie in range."""

    label: str
    expected: int = 0
    hours: list[int] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return len(self.hours) < self.expected


def _floor_hour(ts: float) -> int:
    return int(ts // _HOUR * _HOUR)


def _bucket_key(local: datetime, ts: int, interval: str, window: Window | None) -> Any:
    if window is not None:
        day = window.anchor(local)
        if day is None:
            return None
    else:
        day = local.date()
    if interval == "hour":
        return ts
    if interval == "day":
        return day
    return day - timedelta(days=day.weekday())


def _bucket_label(key: Any, local: datetime) -> str:
    if isinstance(key, int):
        return local.strftime("%Y-%m-%dT%H:%M")
    return key.isoformat()


def plan_buckets(
    start: datetime, end: datetime, tz: tzinfo, interval: str, window: Window | None
) -> list[Bucket]:
    """Buckets that hold at least one whole hour of [start, end), in order.

    Hours are enumerated in UTC and converted, so days with a DST switch get
    their real 23 or 25 hours.  `expected` counts every hour a bucket has,
    including those outside the range; fewer in-range hours make it partial.
    """
    pad = timedelta(days=8 if interval == "week" else 2)
    first = _floor_hour((start - pad).timestamp())
    last = (end + pad).timestamp()
    start_ts, end_ts = start.timestamp(), end.timestamp()
    buckets: dict[Any, Bucket] = {}
    ts = first
    while ts < last:
        local = datetime.fromtimestamp(ts, timezone.utc).astimezone(tz)
        key = _bucket_key(local, ts, interval, window)
        if key is not None:
            bucket = buckets.get(key)
            if bucket is None:
                bucket = buckets[key] = Bucket(_bucket_label(key, local))
            bucket.expected += 1
            if ts >= start_ts and ts + _HOUR <= end_ts:
                bucket.hours.append(ts)
        ts += _HOUR
    return [b for b in buckets.values() if b.hours]


# ── Hourly points from the state history ─────────────────────────────────────


def _as_float(value: Any) -> float | None:
    if value is None or str(value).strip().lower() in _NO_VALUE:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def looks_numeric(changes: list[tuple[float, str]]) -> bool:
    """True when the recorded values (ignoring unknown/unavailable) are numbers."""
    values = [s for _, s in changes if str(s).strip().lower() not in _NO_VALUE]
    if not values:
        return False
    numeric = sum(1 for s in values if _as_float(s) is not None)
    return numeric / len(values) >= 0.9


def _segments(changes: list[tuple[float, str]], start: float, end: float):
    """Yield (seg_start, seg_end, state) clipped to [start, end)."""
    ordered = sorted(changes, key=lambda c: c[0])
    for idx, (ts, state) in enumerate(ordered):
        nxt = ordered[idx + 1][0] if idx + 1 < len(ordered) else end
        seg_start, seg_end = max(ts, start), min(nxt, end)
        if seg_end > seg_start:
            yield seg_start, seg_end, state


def _overlaps(seg_start: float, seg_end: float):
    """Yield (hour_ts, seconds) for each hour a segment overlaps."""
    hour = _floor_hour(seg_start)
    while hour < seg_end:
        seconds = min(seg_end, hour + _HOUR) - max(seg_start, hour)
        if seconds > 0:
            yield hour, seconds
        hour += _HOUR


def history_measurement_points(
    changes: list[tuple[float, str]], start: float, end: float
) -> dict[int, dict[str, float]]:
    """Time-weighted mean, min and max per hour from numeric state changes."""
    acc: dict[int, list[float]] = {}  # hour -> [weighted sum, seconds, min, max]
    for seg_start, seg_end, state in _segments(changes, start, end):
        value = _as_float(state)
        if value is None:
            continue
        for hour, seconds in _overlaps(seg_start, seg_end):
            slot = acc.setdefault(hour, [0.0, 0.0, value, value])
            slot[0] += value * seconds
            slot[1] += seconds
            slot[2] = min(slot[2], value)
            slot[3] = max(slot[3], value)
    return {
        hour: {"mean": s[0] / s[1], "min": s[2], "max": s[3]}
        for hour, s in acc.items() if s[1] > 0
    }


def history_counter_points(
    changes: list[tuple[float, str]], start: float, end: float, state_class: str | None
) -> dict[int, dict[str, float]]:
    """Increase per hour from meter readings.

    The first reading is the baseline.  For total_increasing a drop is a
    meter reset: the new reading counts as consumption since the reset.
    Hours during which some valid reading was current get a change (0 when
    nothing moved); hours without any are missing data.
    """
    points: dict[int, dict[str, float]] = {}
    for seg_start, seg_end, state in _segments(changes, start, end):
        if _as_float(state) is None:
            continue
        for hour, _seconds in _overlaps(seg_start, seg_end):
            points.setdefault(hour, {"change": 0.0})
    previous: float | None = None
    for ts, state in sorted(changes, key=lambda c: c[0]):
        value = _as_float(state)
        if value is None:
            continue
        if previous is not None and start <= ts < end:
            delta = value - previous
            if delta < 0 and state_class == "total_increasing":
                delta = value
            points.setdefault(_floor_hour(ts), {"change": 0.0})["change"] += delta
        previous = value
    return points


def history_state_points(
    changes: list[tuple[float, str]], start: float, end: float
) -> dict[int, dict[str, float]]:
    """Seconds spent in each state per hour."""
    points: dict[int, dict[str, float]] = {}
    for seg_start, seg_end, state in _segments(changes, start, end):
        for hour, seconds in _overlaps(seg_start, seg_end):
            slot = points.setdefault(hour, {})
            slot[str(state)] = slot.get(str(state), 0.0) + seconds
    return points


# ── Aggregation ───────────────────────────────────────────────────────────────


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3) if abs(value) >= 1 else round(value, 4)


def quantile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks (as numpy's default)."""
    pos = (len(sorted_values) - 1) * q
    low = math.floor(pos)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": _round(sum(ordered) / len(ordered)),
        "median": _round(quantile(ordered, 0.5)),
        "p10": _round(quantile(ordered, 0.1)),
        "p90": _round(quantile(ordered, 0.9)),
        "min": _round(ordered[0]),
        "max": _round(ordered[-1]),
    }


def _circular_mean(degrees: list[float]) -> float:
    sin = sum(math.sin(math.radians(d)) for d in degrees)
    cos = sum(math.cos(math.radians(d)) for d in degrees)
    return math.degrees(math.atan2(sin, cos)) % 360


def _bucket_flags(out: dict[str, Any], bucket: Bucket, missing: int) -> bool:
    """Record partial/missing markers; True when the bucket is usable."""
    if bucket.partial:
        out.setdefault("partial", []).append(bucket.label)
    if missing:
        out.setdefault("missing_hours", {})[bucket.label] = missing
    return not bucket.partial and not missing


def aggregate_numeric(
    buckets: list[Bucket],
    points: dict[int, dict[str, float]],
    kind: str,
    *,
    stat: str = "mean",
    circular: bool = False,
    want_distribution: bool = False,
) -> dict[str, Any]:
    """Rows per bucket for a counter (sum of changes) or a measurement."""
    out: dict[str, Any] = {}
    if kind == "counter":
        out["columns"] = ["start", "change"]
    else:
        out["columns"] = ["start", "mean", "min", "max"]
    rows: list[list[Any]] = []
    usable: list[float] = []
    for bucket in buckets:
        hourly = [points[h] for h in bucket.hours if h in points]
        if kind == "counter":
            hourly = [p for p in hourly if p.get("change") is not None]
        else:
            hourly = [p for p in hourly if p.get("mean") is not None]
        ok = _bucket_flags(out, bucket, len(bucket.hours) - len(hourly))
        if not hourly:
            rows.append([bucket.label] + [None] * (len(out["columns"]) - 1))
            continue
        if kind == "counter":
            value = sum(p["change"] for p in hourly)
            rows.append([bucket.label, _round(value)])
            metric = value
        else:
            means = [p["mean"] for p in hourly]
            mean = _circular_mean(means) if circular else sum(means) / len(means)
            low = min(p["mean"] if p.get("min") is None else p["min"] for p in hourly)
            high = max(p["mean"] if p.get("max") is None else p["max"] for p in hourly)
            rows.append([bucket.label, _round(mean), _round(low), _round(high)])
            metric = {"mean": mean, "min": low, "max": high}[stat]
        if ok:
            usable.append(metric)
    out["rows"] = rows
    if want_distribution:
        out["distribution"] = _distribution_block(usable, kind, stat)
    return out


def aggregate_states(
    buckets: list[Bucket],
    points: dict[int, dict[str, float]],
    *,
    target_state: str | None = None,
    want_distribution: bool = False,
) -> dict[str, Any]:
    """Hours per state per bucket; the most frequent states get own columns."""
    totals: dict[str, float] = {}
    for bucket in buckets:
        for hour in bucket.hours:
            for state, seconds in points.get(hour, {}).items():
                totals[state] = totals.get(state, 0.0) + seconds
    ranked = sorted(totals, key=lambda s: -totals[s])
    shown = ranked[:MAX_STATE_COLUMNS]
    if target_state and target_state in totals and target_state not in shown:
        shown = ranked[:MAX_STATE_COLUMNS - 1] + [target_state]
    has_other = len(totals) > len(shown)
    out: dict[str, Any] = {
        "unit": "h",
        "columns": ["start"] + shown + (["other"] if has_other else []),
        "totals_h": {s: round(totals[s] / _HOUR, 2) for s in ranked[:12]},
    }
    rows: list[list[Any]] = []
    usable: list[float] = []
    for bucket in buckets:
        per_state: dict[str, float] = {}
        covered = 0
        for hour in bucket.hours:
            slot = points.get(hour)
            if not slot:
                continue
            if sum(slot.values()) >= _HOUR - 1:
                covered += 1
            for state, seconds in slot.items():
                per_state[state] = per_state.get(state, 0.0) + seconds
        ok = _bucket_flags(out, bucket, len(bucket.hours) - covered)
        row: list[Any] = [bucket.label] + [round(per_state.get(s, 0.0) / _HOUR, 2) for s in shown]
        if has_other:
            other = sum(v for s, v in per_state.items() if s not in shown)
            row.append(round(other / _HOUR, 2))
        rows.append(row)
        if ok and target_state:
            usable.append(per_state.get(target_state, 0.0) / _HOUR)
    out["rows"] = rows
    if want_distribution:
        if not target_state:
            out["distribution"] = {"error": "pass 'state' (e.g. \"heat\") to get a distribution of its hours"}
        else:
            out["distribution"] = _distribution_block(usable, "states", target_state)
    return out


def _distribution_block(values: list[float], kind: str, of: str) -> dict[str, Any]:
    """Distribution over usable buckets; `of` names the stat or target state."""
    if not values:
        return {"error": "no complete bucket with full data in the period"}
    block = distribution(values)
    if kind == "counter":
        block["of"] = "change"
    elif kind == "states":
        block["of"] = f"hours in '{of}'"
    else:
        block["of"] = of
    return block


# ── Size limit ────────────────────────────────────────────────────────────────


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def fit_to_limit(payload: dict[str, Any], limit: int = MAX_RESULT_CHARS) -> str:
    """Serialize, dropping the oldest rows of every series until it fits.

    Summaries (distribution, totals) survive; the model is told how many
    rows were left out and how to ask for fewer.
    """
    text = _dump(payload)
    series = [s for s in payload.get("series", []) if isinstance(s.get("rows"), list)]
    while len(text) > limit and any(s["rows"] for s in series):
        for item in series:
            rows = item["rows"]
            if not rows:
                continue
            keep = len(rows) // 2
            item["rows_omitted"] = item.get("rows_omitted", 0) + len(rows) - keep
            item["rows"] = rows[len(rows) - keep:]
            kept = {r[0] for r in item["rows"]}
            if "partial" in item:
                item["partial"] = [label for label in item["partial"] if label in kept]
            if "missing_hours" in item:
                item["missing_hours"] = {
                    label: n for label, n in item["missing_hours"].items() if label in kept
                }
            for marker in ("partial", "missing_hours"):
                if not item.get(marker):
                    item.pop(marker, None)
        payload["note"] = (
            "Older rows left out to fit the answer. Use a coarser interval, "
            "a shorter period, fewer entities or distribution=true."
        )
        text = _dump(payload)
    if len(text) > limit:
        return _dump({"error": "result too large — query fewer entities per call"})
    return text


# ── Tool calls (pure part) ───────────────────────────────────────────────────


@dataclass
class EntityInfo:
    """What the adapter knows about an entity before and after loading."""

    entity_id: str
    name: str | None = None
    unit: str | None = None
    state_class: str | None = None
    exists: bool = True
    stats: list[dict[str, Any]] | None = None
    stats_has_sum: bool | None = None
    stats_circular: bool = False
    history: list[tuple[float, str]] | None = None
    # get_history loads only the newest changes; True when older ones exist.
    more_before: bool = False


def history_note(start: datetime, history_since: datetime | None, tz: tzinfo) -> str | None:
    """Explain why the state history is empty or short before the purge horizon.

    The recorder keeps state changes only `keep_days` long, hourly statistics
    indefinitely; without this note an empty history reads like an outage.
    """
    if history_since is None or start >= history_since:
        return None
    since = history_since.astimezone(tz).isoformat(timespec="minutes")
    return (
        f"State history is only kept since {since}; earlier changes are purged, "
        "an empty or short result there is no outage. Use get_statistics "
        "(hourly, kept long-term) for older periods."
    )


def kind_of(info: EntityInfo) -> str:
    """'counter', 'measurement' or 'states'."""
    if info.state_class in COUNTER_CLASSES:
        return "counter"
    if info.stats:
        return "counter" if info.stats_has_sum else "measurement"
    if info.state_class:
        return "measurement"
    if info.history and looks_numeric(info.history):
        return "measurement"
    return "states"


def _stats_points(rows: list[dict[str, Any]], kind: str) -> dict[int, dict[str, float]]:
    points: dict[int, dict[str, float]] = {}
    for row in rows:
        start = row.get("start")
        if isinstance(start, datetime):
            start = start.timestamp()
        if start is None:
            continue
        if kind == "counter":
            if row.get("change") is not None:
                points[_floor_hour(start)] = {"change": float(row["change"])}
        elif row.get("mean") is not None:
            points[_floor_hour(start)] = {
                "mean": float(row["mean"]),
                "min": row.get("min"),
                "max": row.get("max"),
            }
    return points


@dataclass
class StatisticsRequest:
    entity_ids: list[str]
    start: datetime
    end: datetime
    interval: str
    window: Window | None
    want_distribution: bool
    stat: str
    target_state: str | None


def parse_statistics_call(call: dict[str, Any], now: datetime, tz: tzinfo) -> StatisticsRequest:
    ids = parse_entity_ids(call)
    start, end = resolve_range(call, now, tz, "7d")
    window = parse_window(call["window"]) if call.get("window") else None
    interval = parse_interval(call.get("interval") or call.get("raster"), "day")
    stat = str(call.get("stat") or "mean").strip().lower()
    if stat not in _STATS:
        raise StatsError("stat must be 'mean', 'min' or 'max'")
    dist = call.get("distribution")
    want = dist is True or str(dist).strip().lower() in ("true", "1", "yes")
    target = call.get("state")
    return StatisticsRequest(
        ids, start, end, interval, window, want, stat,
        str(target) if target not in (None, "") else None,
    )


def build_statistics(
    request: StatisticsRequest, infos: list[EntityInfo], tz: tzinfo,
    history_since: datetime | None = None,
) -> str:
    """Aggregate loaded data into the tool answer (JSON string)."""
    buckets = plan_buckets(request.start, request.end, tz, request.interval, request.window)
    if not buckets:
        hint = " in the window" if request.window else ""
        return _dump({"error": f"the period holds no complete hour{hint} — widen it"})
    start_ts, end_ts = request.start.timestamp(), request.end.timestamp()
    payload: dict[str, Any] = {
        "period": {
            "start": request.start.astimezone(tz).isoformat(timespec="minutes"),
            "end": request.end.astimezone(tz).isoformat(timespec="minutes"),
        },
        "interval": request.interval,
    }
    if request.window:
        payload["window"] = request.window.label
        if request.window.rounded:
            payload["window_note"] = "rounded to whole hours (statistics are hourly)"
        if request.window.wraps and request.interval != "hour":
            payload["window_day"] = "a window across midnight counts for the day it starts"
    series: list[dict[str, Any]] = []
    for info in infos:
        item: dict[str, Any] = {"entity_id": info.entity_id}
        if info.name:
            item["name"] = info.name
        if not info.exists and not info.stats and not info.history:
            item["error"] = "entity not found and nothing recorded for it"
            series.append(item)
            continue
        kind = kind_of(info)
        source = "statistics" if info.stats and kind != "states" else "history"
        item.update({"kind": kind, "source": source})
        if info.state_class:
            item["state_class"] = info.state_class
        note = history_note(request.start, history_since, tz) if source == "history" else None
        if note:
            item["note"] = note
        if source == "statistics":
            points = _stats_points(info.stats or [], kind)
        elif not info.history:
            if not note:
                item["error"] = "nothing recorded in this period (entity excluded from the recorder?)"
            series.append(item)
            continue
        elif kind == "counter":
            points = history_counter_points(info.history, start_ts, end_ts, info.state_class)
        elif kind == "measurement":
            points = history_measurement_points(info.history, start_ts, end_ts)
        else:
            points = history_state_points(info.history, start_ts, end_ts)
        if kind == "states":
            item.update(aggregate_states(
                buckets, points,
                target_state=request.target_state,
                want_distribution=request.want_distribution,
            ))
        else:
            if info.unit:
                item["unit"] = info.unit
            item.update(aggregate_numeric(
                buckets, points, kind,
                stat=request.stat,
                circular=info.stats_circular and source == "statistics",
                want_distribution=request.want_distribution,
            ))
        series.append(item)
    payload["series"] = series
    if any("partial" in s or "missing_hours" in s for s in series):
        payload["legend"] = (
            "partial = bucket cut off by the period; missing_hours = hours without "
            "recorded data. Both are left out of the distribution."
        )
    return fit_to_limit(payload)


def parse_history_call(
    call: dict[str, Any], now: datetime, tz: tzinfo
) -> tuple[list[str], datetime, datetime, int]:
    ids = parse_entity_ids(call)
    start, end = resolve_range(call, now, tz, "24h")
    try:
        limit = int(call.get("max_points") or HISTORY_DEFAULT_POINTS)
    except (TypeError, ValueError):
        raise StatsError("max_points must be a number") from None
    return ids, start, end, max(1, min(limit, HISTORY_MAX_POINTS))


def build_history(
    ids: list[str], start: datetime, end: datetime, max_points: int,
    infos: list[EntityInfo], tz: tzinfo,
    history_since: datetime | None = None,
) -> str:
    """Recorded state changes per entity (consecutive repeats merged), newest kept."""
    series: list[dict[str, Any]] = []
    for info in infos:
        item: dict[str, Any] = {"entity_id": info.entity_id}
        if info.name:
            item["name"] = info.name
        if info.unit:
            item["unit"] = info.unit
        if info.state_class:
            item["state_class"] = info.state_class
        if not info.exists and not info.history:
            item["error"] = "entity not found and nothing recorded for it"
            series.append(item)
            continue
        rows: list[list[Any]] = []
        last_state: str | None = None
        for ts, state in sorted(info.history or [], key=lambda c: c[0]):
            if state == last_state:
                continue
            last_state = state
            stamp = datetime.fromtimestamp(max(ts, start.timestamp()), timezone.utc)
            rows.append([stamp.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"), state])
        item["columns"] = ["time", "state"]
        if len(rows) > max_points:
            rows = rows[-max_points:]
            info.more_before = True
        if info.more_before:
            item["more_before"] = True
        item["rows"] = rows
        series.append(item)
    payload: dict[str, Any] = {
        "period": {
            "start": start.astimezone(tz).isoformat(timespec="minutes"),
            "end": end.astimezone(tz).isoformat(timespec="minutes"),
        },
        "series": series,
        "hint": "for sums, averages or per-hour/day values use get_statistics",
    }
    note = history_note(start, history_since, tz)
    if note:
        payload["note"] = note
    if any(s.get("more_before") for s in series):
        payload["more_before"] = "only the newest changes are listed; narrow the period for older ones"
    return fit_to_limit(payload)


# ── Home Assistant adapter ────────────────────────────────────────────────────

_NO_RECORDER = (
    "The recorder is not available, so there is no history or statistics. "
    "Answer from the current state (get_entity_state) and say that past data "
    "needs the recorder integration."
)


def _recorder_instance(hass: Any) -> Any:
    if "recorder" not in getattr(hass.config, "components", set()):
        return None
    try:
        from homeassistant.components.recorder import get_instance  # noqa: PLC0415
        return get_instance(hass)
    except Exception:  # noqa: BLE001
        return None


def _local_now() -> tuple[datetime, tzinfo]:
    from homeassistant.util import dt as dt_util  # noqa: PLC0415
    tz = dt_util.get_default_time_zone()
    return dt_util.now(tz), tz


def _entity_infos(hass: Any, ids: list[str]) -> list[EntityInfo]:
    infos = []
    for eid in ids:
        state = hass.states.get(eid)
        attrs = state.attributes if state is not None else {}
        infos.append(EntityInfo(
            entity_id=eid,
            name=attrs.get("friendly_name"),
            unit=attrs.get("unit_of_measurement"),
            state_class=attrs.get("state_class"),
            exists=state is not None,
        ))
    return infos


def _fetch_statistics(
    hass: Any, start: datetime, end: datetime, ids: set[str]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Hourly long-term statistics and their metadata (recorder executor)."""
    from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
        get_metadata,
        statistics_during_period,
    )
    raw_meta = get_metadata(hass, statistic_ids=ids)
    meta: dict[str, dict[str, Any]] = {}
    for sid, (_meta_id, data) in raw_meta.items():
        mean_type = data.get("mean_type")
        meta[sid] = {
            "has_sum": bool(data.get("has_sum")),
            "circular": getattr(mean_type, "name", str(mean_type)).upper() == "CIRCULAR",
            "unit": data.get("unit_of_measurement"),
        }
    rows = statistics_during_period(
        hass, start, end, ids, "hour", None, {"change", "mean", "min", "max"}
    )
    return {sid: [dict(r) for r in rs] for sid, rs in rows.items()}, meta


def _change_of(row: Any) -> tuple[float, str] | None:
    """(last_changed timestamp, state) from a State or a compressed history row."""
    if isinstance(row, dict):
        ts = row.get("lc", row.get("lu"))
        if ts is None or "s" not in row:
            return None
        return float(ts), str(row["s"])
    changed = getattr(row, "last_changed", None)
    if changed is None:
        return None
    return changed.timestamp(), str(row.state)


def _fetch_history(
    hass: Any, start: datetime, end: datetime, ids: list[str]
) -> dict[str, list[tuple[float, str]]]:
    """State changes incl. the state at `start` (recorder executor).

    Only real state changes (attribute-only updates are skipped) in HA's
    compressed row format: a meter reporting every few seconds has hundreds
    of thousands of rows a month, and building State objects for them took
    over a minute.
    """
    from homeassistant.components.recorder.history import (  # noqa: PLC0415
        get_significant_states,
    )
    states = get_significant_states(
        hass, start, end, ids,
        include_start_time_state=True,
        significant_changes_only=True,
        minimal_response=True,
        no_attributes=True,
        compressed_state_format=True,
    )
    result: dict[str, list[tuple[float, str]]] = {}
    for eid, rows in states.items():
        result[eid] = [c for c in (_change_of(r) for r in rows) if c is not None]
    return result


def _fetch_recent_changes(
    hass: Any, start: datetime, end: datetime, ids: list[str], max_points: int
) -> dict[str, tuple[list[tuple[float, str]], bool]]:
    """Newest state changes per entity, without reading the whole period.

    The recorder's `limit` keeps the oldest rows, so the window grows back
    from `end` (15 min, x4) until it holds more than `max_points` changes or
    reaches `start`.  Returns {entity_id: (changes, older_changes_exist)}.
    """
    from homeassistant.components.recorder.history import (  # noqa: PLC0415
        state_changes_during_period,
    )
    result: dict[str, tuple[list[tuple[float, str]], bool]] = {}
    for eid in ids:
        span = timedelta(minutes=15)
        while True:
            win_start = max(start, end - span)
            at_start = win_start == start
            rows = state_changes_during_period(
                hass, win_start, end, eid,
                no_attributes=True,
                include_start_time_state=at_start,
            ).get(eid, [])
            if len(rows) > max_points or at_start:
                break
            span *= 4
        changes = [c for c in (_change_of(r) for r in rows) if c is not None]
        result[eid] = (changes, not at_start or len(changes) > max_points)
    return result


def _history_since(instance: Any, now: datetime) -> datetime | None:
    """Oldest moment the recorder still keeps state history for."""
    keep_days = getattr(instance, "keep_days", None)
    if not isinstance(keep_days, (int, float)) or isinstance(keep_days, bool):
        return None
    return now - timedelta(days=keep_days)


def _load_statistics(
    hass: Any, request: StatisticsRequest, infos: list[EntityInfo]
) -> None:
    stats_start = datetime.fromtimestamp(_floor_hour(request.start.timestamp()), timezone.utc)
    rows, meta = _fetch_statistics(hass, stats_start, request.end, set(request.entity_ids))
    need_history: list[str] = []
    for info in infos:
        if rows.get(info.entity_id):
            info.stats = rows[info.entity_id]
            info.stats_has_sum = meta.get(info.entity_id, {}).get("has_sum")
            if info.stats_has_sum is None:
                info.stats_has_sum = any(r.get("change") is not None for r in info.stats)
            info.stats_circular = bool(meta.get(info.entity_id, {}).get("circular"))
            info.unit = meta.get(info.entity_id, {}).get("unit") or info.unit
        else:
            need_history.append(info.entity_id)
    if need_history:
        history = _fetch_history(hass, request.start, request.end, need_history)
        for info in infos:
            if info.entity_id in need_history:
                info.history = history.get(info.entity_id) or []


async def async_execute_statistics(hass: Any, call: dict[str, Any]) -> str:
    """Run one get_statistics tool call, return a JSON string."""
    try:
        now, tz = _local_now()
        request = parse_statistics_call(call, now, tz)
    except StatsError as err:
        return _dump({"error": str(err)})
    instance = _recorder_instance(hass)
    if instance is None:
        return _dump({"error": _NO_RECORDER})
    infos = _entity_infos(hass, request.entity_ids)
    try:
        await instance.async_add_executor_job(_load_statistics, hass, request, infos)
    except Exception as err:  # noqa: BLE001
        return _dump({"error": f"reading the recorder failed: {err}"})
    return build_statistics(request, infos, tz, _history_since(instance, now))


async def async_execute_history(hass: Any, call: dict[str, Any]) -> str:
    """Run one get_history tool call, return a JSON string."""
    try:
        now, tz = _local_now()
        ids, start, end, max_points = parse_history_call(call, now, tz)
    except StatsError as err:
        return _dump({"error": str(err)})
    instance = _recorder_instance(hass)
    if instance is None:
        return _dump({"error": _NO_RECORDER})
    infos = _entity_infos(hass, ids)
    try:
        recent = await instance.async_add_executor_job(
            _fetch_recent_changes, hass, start, end, ids, max_points
        )
    except Exception as err:  # noqa: BLE001
        return _dump({"error": f"reading the recorder failed: {err}"})
    for info in infos:
        info.history, info.more_before = recent.get(info.entity_id, ([], False))
    return build_history(ids, start, end, max_points, infos, tz, _history_since(instance, now))
