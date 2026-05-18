"""Tests for the TF-IDF area/entity_id exact-match boost in KnowledgeStore."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_knowledge():
    """Load knowledge.py directly without triggering __init__.py."""
    for mod_name in ["homeassistant", "homeassistant.core", "homeassistant.helpers"]:
        sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

    if not hasattr(sys.modules["homeassistant.core"], "HomeAssistant"):
        sys.modules["homeassistant.core"].HomeAssistant = object  # type: ignore[attr-defined]

    storage = sys.modules.get("homeassistant.helpers.storage") or types.ModuleType("homeassistant.helpers.storage")

    class _FakeStore:
        def __init__(self, *a, **kw): self._data: dict = {}
        async def async_load(self): return self._data or None
        async def async_save(self, data): self._data = data

    storage.Store = _FakeStore  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.storage"] = storage

    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules.setdefault("custom_components.kyber", types.ModuleType("custom_components.kyber"))

    spec = importlib.util.spec_from_file_location(
        "custom_components.kyber.knowledge",
        ROOT / "custom_components" / "kyber" / "knowledge.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sys.modules["custom_components.kyber.knowledge"] = mod
    return mod


_KNOWLEDGE = _load_knowledge()
KnowledgeStore = _KNOWLEDGE.KnowledgeStore


def _make_hass():
    hass = MagicMock()
    return hass


async def _make_store_with_entries(entries):
    """Create a KnowledgeStore and add entries directly."""
    hass = _make_hass()
    store = KnowledgeStore(hass)
    store._loaded = True  # skip actual load
    for e in entries:
        await store.async_add(
            category=e.get("category", "general"),
            content=e["content"],
            subject=e.get("subject", ""),
            tags=e.get("tags", []),
            source=e.get("source", "test"),
        )
    return store


@pytest.mark.asyncio
async def test_area_boost_ranks_correct_room_higher():
    """
    Two entries: one tagged 'slaapkamer', one tagged 'woonkamer'.
    Query 'motion sensor slaapkamer' should rank the slaapkamer entry higher.
    """
    slaapkamer_entry = {
        "content": "binary_sensor.0x00124b motion sensor",
        "subject": "binary_sensor.0x00124b",
        "tags": ["binary_sensor", "occupancy", "slaapkamer"],
        "source": "entity_explorer",
    }
    woonkamer_entry = {
        "content": "binary_sensor.0xaabbcc motion sensor",
        "subject": "binary_sensor.0xaabbcc",
        "tags": ["binary_sensor", "occupancy", "woonkamer"],
        "source": "entity_explorer",
    }
    store = await _make_store_with_entries([slaapkamer_entry, woonkamer_entry])

    results = await store.async_semantic_search("motion sensor slaapkamer", limit=5)
    assert len(results) >= 2
    # Slaapkamer should rank above woonkamer
    ids = [r.get("subject") for r in results]
    assert ids.index("binary_sensor.0x00124b") < ids.index("binary_sensor.0xaabbcc"), (
        f"slaapkamer entry should rank above woonkamer entry, got: {ids}"
    )


@pytest.mark.asyncio
async def test_entity_id_subject_boost():
    """
    Query containing a specific entity_id fragment should rank that entity's entry higher.
    """
    target_entry = {
        "content": "Aqara presence sensor.",
        "subject": "binary_sensor.0xspecific_occupancy",
        "tags": ["binary_sensor", "occupancy", "kantoor"],
        "source": "entity_explorer",
    }
    other_entry = {
        "content": "Aqara presence sensor.",
        "subject": "binary_sensor.0xother_occupancy",
        "tags": ["binary_sensor", "occupancy", "kantoor"],
        "source": "entity_explorer",
    }
    store = await _make_store_with_entries([target_entry, other_entry])

    results = await store.async_semantic_search("0xspecific occupancy", limit=5)
    assert results[0]["subject"] == "binary_sensor.0xspecific_occupancy"


@pytest.mark.asyncio
async def test_area_boost_does_not_exceed_1():
    """Score with boost should never exceed 1.0."""
    entry = {
        "content": "binary_sensor.0x001 motion sensor in slaapkamer",
        "subject": "binary_sensor.0x001",
        "tags": ["binary_sensor", "slaapkamer", "slaapkamer", "slaapkamer"],
        "source": "entity_explorer",
    }
    store = await _make_store_with_entries([entry])
    results = await store.async_semantic_search("slaapkamer slaapkamer slaapkamer motion", limit=5)
    for r in results:
        assert r["_score"] <= 1.0, f"score {r['_score']} exceeds 1.0"


@pytest.mark.asyncio
async def test_no_boost_when_no_query_match():
    """Entries not matching query words in tags should not be boosted."""
    entry = {
        "content": "light in the living room",
        "subject": "light.woonkamer",
        "tags": ["light", "woonkamer"],
        "source": "entity_explorer",
    }
    store = await _make_store_with_entries([entry])
    # Query has no overlap with tags
    results = await store.async_semantic_search("slaapkamer temperature sensor", limit=5, min_score=0.0)
    # Should still return but without significant boost
    if results:
        assert results[0]["_score"] < 0.5
