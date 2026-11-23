"""Lightweight per-entity AI call statistics stored in hass.data.

Stats are in-memory and reset on HA restart — they represent "recent session" usage.
Keyed by ai_task entity_id so chat and operations models are tracked separately.

Also tracks agent run stats (narrator, deep learning) keyed by a string key.

The options dialog gets placeholders only; the sentences are translated in
translations/*.json. HA core checks that every language uses the same plain
"{name}" placeholders as English and drops a translation that does not, so the
values are language-neutral: numbers, local "YYYY-MM-DD HH:MM" times and "–"
for a value that does not exist yet.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STATS_KEY = "kyber_model_stats"
RUN_STATS_KEY = "kyber_run_stats"
NO_VALUE = "–"


def _store(hass: "HomeAssistant") -> dict:
    if STATS_KEY not in hass.data:
        hass.data[STATS_KEY] = {}
    return hass.data[STATS_KEY]


def _run_store(hass: "HomeAssistant") -> dict:
    if RUN_STATS_KEY not in hass.data:
        hass.data[RUN_STATS_KEY] = {}
    return hass.data[RUN_STATS_KEY]


def record_call(
    hass: "HomeAssistant",
    entity_id: str,
    elapsed_ms: int,
    tokens_est: int,
    *,
    success: bool,
) -> None:
    """Record one AI call result for the given entity."""
    s = _store(hass).setdefault(
        entity_id,
        {"calls": 0, "errors": 0, "total_ms": 0, "min_ms": None, "max_ms": 0, "total_tokens_est": 0},
    )
    if success:
        s["calls"] += 1
        s["total_ms"] += elapsed_ms
        s["min_ms"] = elapsed_ms if s["min_ms"] is None else min(s["min_ms"], elapsed_ms)
        s["max_ms"] = max(s["max_ms"], elapsed_ms)
        s["total_tokens_est"] += tokens_est
    else:
        s["errors"] += 1


def stats_placeholders(hass: "HomeAssistant", entity_id: str, prefix: str) -> dict[str, str]:
    """Return the options dialog placeholders for one model's call stats.

    Durations are seconds with one decimal; without a successful call they are
    NO_VALUE. Every placeholder is always present: the frontend fails on a
    missing one.
    """
    s = (_store(hass).get(entity_id) if entity_id else None) or {}
    calls = s.get("calls", 0)

    def _secs(ms_key: str) -> str:
        if not calls:
            return NO_VALUE
        ms = s["total_ms"] / calls if ms_key == "avg" else (s[ms_key] or 0)
        return f"{ms / 1000:.1f}"

    return {
        f"{prefix}_calls": str(calls),
        f"{prefix}_avg": _secs("avg"),
        f"{prefix}_min": _secs("min_ms"),
        f"{prefix}_max": _secs("max_ms"),
        f"{prefix}_tokens": str(s.get("total_tokens_est", 0)),
        f"{prefix}_errors": str(s.get("errors", 0)),
    }


def record_run(hass: "HomeAssistant", key: str, interval_secs: float = 0) -> None:
    """Record a completed agent run (narrator / deep_learning)."""
    now = _time.time()
    s = _run_store(hass).setdefault(key, {"total_runs": 0, "last_run_ts": None, "next_run_ts": None})
    s["total_runs"] += 1
    s["last_run_ts"] = now
    s["next_run_ts"] = now + interval_secs if interval_secs > 0 else None


def _local_time(ts: float | None) -> str:
    """Format a Unix timestamp as local "YYYY-MM-DD HH:MM", or NO_VALUE."""
    if not ts:
        return NO_VALUE
    return dt_util.as_local(datetime.fromtimestamp(ts, timezone.utc)).strftime("%Y-%m-%d %H:%M")


def run_stats_placeholders(hass: "HomeAssistant", key: str, prefix: str) -> dict[str, str]:
    """Return the options dialog placeholders for one agent's run stats.

    Last and next run are local times (a next run in the past is overdue).
    Every placeholder is always present.
    """
    s = _run_store(hass).get(key) or {}
    return {
        f"{prefix}_last": _local_time(s.get("last_run_ts")),
        f"{prefix}_next": _local_time(s.get("next_run_ts")),
        f"{prefix}_total": str(s.get("total_runs", 0)),
    }
