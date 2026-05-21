"""Lightweight per-entity AI call statistics stored in hass.data.

Stats are in-memory and reset on HA restart — they represent "recent session" usage.
Keyed by ai_task entity_id so chat and operations models are tracked separately.

Also tracks agent run stats (narrator, deep learning) keyed by a string key.
"""
from __future__ import annotations

import time as _time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STATS_KEY = "kyber_model_stats"
RUN_STATS_KEY = "kyber_run_stats"


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


def format_stats(hass: "HomeAssistant", entity_id: str) -> str:
    """Return a one-line stats summary for display in the options panel."""
    s = _store(hass).get(entity_id)
    if not s or s["calls"] == 0:
        errors = s["errors"] if s else 0
        return f"No successful calls yet{f' ({errors} errors)' if errors else ''}"
    calls = s["calls"]
    avg_s = s["total_ms"] / calls / 1000
    min_s = (s["min_ms"] or 0) / 1000
    max_s = s["max_ms"] / 1000
    tokens = s["total_tokens_est"]
    errors = s["errors"]
    parts = [
        f"Calls: {calls}",
        f"Avg: {avg_s:.1f}s",
        f"Min: {min_s:.1f}s",
        f"Max: {max_s:.1f}s",
        f"~{tokens:,} tokens",
    ]
    if errors:
        parts.append(f"Errors: {errors}")
    return " · ".join(parts)


def record_run(hass: "HomeAssistant", key: str, interval_secs: float = 0) -> None:
    """Record a completed agent run (narrator / deep_learning)."""
    now = _time.time()
    s = _run_store(hass).setdefault(key, {"total_runs": 0, "last_run_ts": None, "next_run_ts": None})
    s["total_runs"] += 1
    s["last_run_ts"] = now
    s["next_run_ts"] = now + interval_secs if interval_secs > 0 else None


def format_run_stats(hass: "HomeAssistant", key: str) -> str:
    """Return a one-line run-stats summary for display in the options panel."""
    s = _run_store(hass).get(key)
    if not s or not s.get("last_run_ts"):
        return "Not run yet this session"
    total = s["total_runs"]
    now = _time.time()
    elapsed = int(now - s["last_run_ts"])
    if elapsed < 60:
        when = "just now"
    elif elapsed < 3600:
        when = f"{elapsed // 60}m ago"
    elif elapsed < 86400:
        when = f"{elapsed // 3600}h ago"
    else:
        when = f"{elapsed // 86400}d ago"

    next_run_ts = s.get("next_run_ts")
    if next_run_ts:
        remaining = int(next_run_ts - now)
        if remaining <= 0:
            next_str = "due now"
        elif remaining < 3600:
            next_str = f"in {remaining // 60}m"
        elif remaining < 86400:
            next_str = f"in {remaining // 3600}h"
        else:
            next_str = f"in {remaining // 86400}d"
        return f"Last run: {when} · Next: {next_str} · Total this session: {total}"
    return f"Last run: {when} · Total runs this session: {total}"
