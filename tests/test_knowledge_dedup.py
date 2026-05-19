"""Tests for KnowledgeStore.async_dedup — including the clean-marker skip.

These tests run entirely in-process without HA; `hass` is stubbed out.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (same pattern as test_embeddings.py)
# ---------------------------------------------------------------------------

def _load_knowledge():
    root = Path(__file__).resolve().parents[1]
    path = root / "custom_components" / "kyber" / "knowledge.py"

    for name in ["homeassistant", "homeassistant.core", "homeassistant.helpers"]:
        sys.modules.setdefault(name, types.ModuleType(name))
    if not hasattr(sys.modules["homeassistant.core"], "HomeAssistant"):
        sys.modules["homeassistant.core"].HomeAssistant = object  # type: ignore[attr-defined]

    storage = sys.modules.get("homeassistant.helpers.storage") or types.ModuleType("homeassistant.helpers.storage")

    class _Store:
        def __init__(self, *a, **kw): ...
        async def async_load(self): return None
        async def async_save(self, data): ...

    storage.Store = _Store
    sys.modules["homeassistant.helpers.storage"] = storage
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules.setdefault("custom_components.kyber", types.ModuleType("custom_components.kyber"))

    spec = importlib.util.spec_from_file_location("custom_components.kyber.knowledge", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_KM = _load_knowledge()


def _make_store():
    """Return a KnowledgeStore with hass=None and already-loaded."""

    class _FakeHass:
        async def async_add_executor_job(self, fn, *args):
            return fn(*args)

    store = _KM.KnowledgeStore(hass=_FakeHass())  # type: ignore[arg-type]
    store._loaded = True
    return store


def _run(coro):
    # HA overrides the event loop policy to use ProactorEventLoop, which needs
    # socket.socketpair() — blocked by pytest_socket on Windows. Temporarily
    # reset to the default policy so we can create a plain event loop.
    original_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop_policy(original_policy)


# ---------------------------------------------------------------------------
# async_dedup — basic duplicate removal
# ---------------------------------------------------------------------------

class TestDedupBasic:
    def test_no_duplicates_returns_zero(self):
        store = _make_store()
        store._entries = {
            "a": {"id": "a", "subject": "foo", "content": "bar", "category": "general", "confidence": 1.0, "created": 1},
            "b": {"id": "b", "subject": "baz", "content": "qux", "category": "general", "confidence": 1.0, "created": 1},
        }
        removed = _run(store.async_dedup())
        assert removed == 0
        assert len(store._entries) == 2  # nothing deleted

    def test_exact_duplicate_removed(self):
        store = _make_store()
        store._entries = {
            "a": {"id": "a", "subject": "foo", "content": "bar", "category": "general", "confidence": 1.0, "created": 1},
            "b": {"id": "b", "subject": "foo", "content": "bar", "category": "general", "confidence": 1.0, "created": 2},
        }
        removed = _run(store.async_dedup())
        assert removed == 1
        assert len(store._entries) in (1, 2)  # dedup marker may be added

    def test_keeps_higher_confidence_winner(self):
        store = _make_store()
        store._entries = {
            "low":  {"id": "low",  "subject": "s", "content": "c", "category": "general", "confidence": 0.5, "created": 1},
            "high": {"id": "high", "subject": "s", "content": "c", "category": "general", "confidence": 0.9, "created": 2},
        }
        _run(store.async_dedup())
        remaining = [e for eid, e in store._entries.items()
                     if e.get("subject") != store._DEDUP_CLEAN_SUBJECT]
        assert len(remaining) == 1
        assert remaining[0]["confidence"] == 0.9

    def test_different_category_not_deduped(self):
        store = _make_store()
        store._entries = {
            "a": {"id": "a", "subject": "s", "content": "c", "category": "general",     "confidence": 1.0, "created": 1},
            "b": {"id": "b", "subject": "s", "content": "c", "category": "entity_note", "confidence": 1.0, "created": 2},
        }
        removed = _run(store.async_dedup())
        assert removed == 0


# ---------------------------------------------------------------------------
# async_dedup — clean-marker skip
# ---------------------------------------------------------------------------

class TestDedupCleanMarker:
    def test_marker_written_after_zero_removal(self):
        store = _make_store()
        store._entries = {
            "a": {"id": "a", "subject": "foo", "content": "bar", "category": "general", "confidence": 1.0, "created": 1},
        }
        _run(store.async_dedup(schema_version=3))
        markers = [e for e in store._entries.values()
                   if e.get("subject") == store._DEDUP_CLEAN_SUBJECT]
        assert len(markers) == 1
        assert markers[0]["content"] == "3"

    def test_marker_skips_scan_on_second_call(self):
        """Second call with same schema_version must return 0 and not alter entries."""
        store = _make_store()
        store._entries = {
            "a": {"id": "a", "subject": "foo", "content": "bar", "category": "general", "confidence": 1.0, "created": 1},
        }
        # First call — runs scan, writes marker
        _run(store.async_dedup(schema_version=3))
        entry_count_after_first = len(store._entries)

        # Add a duplicate AFTER the marker is written
        store._entries["b"] = {"id": "b", "subject": "foo", "content": "bar",
                               "category": "general", "confidence": 1.0, "created": 2}

        # Second call — should be skipped entirely (marker present)
        removed = _run(store.async_dedup(schema_version=3))
        assert removed == 0
        # The duplicate was NOT cleaned (scan was skipped)
        assert store._entries.get("b") is not None

    def test_no_schema_version_always_runs(self):
        """Calling async_dedup() with no schema_version skips marker logic entirely."""
        store = _make_store()
        store._entries = {
            "a": {"id": "a", "subject": "foo", "content": "bar", "category": "general", "confidence": 1.0, "created": 1},
            "b": {"id": "b", "subject": "foo", "content": "bar", "category": "general", "confidence": 1.0, "created": 2},
        }
        removed = _run(store.async_dedup())  # no schema_version
        assert removed == 1
        # No marker written
        markers = [e for e in store._entries.values()
                   if e.get("subject") == store._DEDUP_CLEAN_SUBJECT]
        assert len(markers) == 0

    def test_marker_overwritten_on_schema_bump(self):
        """Old v2 marker is ignored when schema_version=3 is passed."""
        store = _make_store()
        # Pre-populate a stale marker for schema v2
        store._entries = {
            "marker": {"id": "marker", "subject": store._DEDUP_CLEAN_SUBJECT,
                       "content": "2", "source": "system", "category": "general",
                       "confidence": 1.0, "created": 1},
            "dup1": {"id": "dup1", "subject": "x", "content": "y", "category": "general", "confidence": 1.0, "created": 1},
            "dup2": {"id": "dup2", "subject": "x", "content": "y", "category": "general", "confidence": 1.0, "created": 2},
        }
        # schema_version=3 — old marker (v2) should be ignored and scan should run
        removed = _run(store.async_dedup(schema_version=3))
        assert removed == 1
        # New marker for v3 written
        v3_markers = [e for e in store._entries.values()
                      if e.get("subject") == store._DEDUP_CLEAN_SUBJECT and e.get("content") == "3"]
        assert len(v3_markers) == 1
