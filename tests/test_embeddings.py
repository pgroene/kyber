"""Tests for the TF-IDF embedding helpers in knowledge.py.

We exercise the pure-python helpers directly without bringing in the full
HA-dependent KnowledgeStore class. The helpers are: `_tokenize`, `_cosine`,
`_vec_norm`, `_vec_dot`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
import sys
import types
from pathlib import Path


def _load_module():
    """Load knowledge.py with HA stubs so import succeeds offline."""
    root = Path(__file__).resolve().parents[1]
    path = root / "custom_components" / "kyber" / "knowledge.py"

    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        sys.modules["homeassistant"] = ha
    if "homeassistant.core" not in sys.modules:
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object  # type: ignore[attr-defined]
        sys.modules["homeassistant.core"] = core
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = types.ModuleType("homeassistant.helpers")

    # Always override storage.Store with a permissive stub so KnowledgeStore
    # construction with hass=None works regardless of what other tests stubbed.
    storage = sys.modules.get("homeassistant.helpers.storage") or types.ModuleType("homeassistant.helpers.storage")

    class _Store:
        def __init__(self, *a, **kw):
            self._args = a
            self._kw = kw

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    storage.Store = _Store
    sys.modules["homeassistant.helpers.storage"] = storage

    if "custom_components" not in sys.modules:
        sys.modules["custom_components"] = types.ModuleType("custom_components")
    if "custom_components.kyber" not in sys.modules:
        sys.modules["custom_components.kyber"] = types.ModuleType("custom_components.kyber")

    spec = importlib.util.spec_from_file_location(
        "custom_components.kyber.knowledge", path
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_tokenize_picks_words_and_bigrams():
    mod = _load_module()
    toks = mod._tokenize("Werkkamer light is off")
    assert "werkkamer" in toks
    assert "light" in toks
    # bigram
    assert "werkkamer_light" in toks


def test_tokenize_strips_short_tokens():
    mod = _load_module()
    toks = mod._tokenize("a b cd")
    # single-letter tokens dropped (len > 1 required)
    assert "a" not in toks
    assert "b" not in toks
    assert "cd" in toks


def test_cosine_identical_vectors_is_one():
    mod = _load_module()
    v = {"werkkamer": 2.0, "office": 1.0}
    assert math.isclose(mod._cosine(v, v), 1.0, abs_tol=1e-9)


def test_cosine_orthogonal_vectors_is_zero():
    mod = _load_module()
    a = {"werkkamer": 1.0}
    b = {"badkamer": 1.0}
    assert mod._cosine(a, b) == 0.0


def test_cosine_partial_overlap_is_between_zero_and_one():
    mod = _load_module()
    a = {"werkkamer": 1.0, "light": 1.0}
    b = {"werkkamer": 1.0, "switch": 1.0}
    score = mod._cosine(a, b)
    assert 0.0 < score < 1.0


def test_record_hit_does_not_dirty_index():
    mod = _load_module()
    store = mod.KnowledgeStore(hass=None)  # type: ignore[arg-type]
    store._entries = {
        "e1": {"id": "e1", "category": "general", "subject": "", "content": "alpha", "tags": []},
    }
    store._loaded = True
    store._rebuild_index()

    assert store._index_dirty is False
    async def _run():
        await store.async_record_hit(["e1"])

    asyncio.run(_run())
    assert store._index_dirty is False


def test_add_and_delete_dirty_index():
    mod = _load_module()
    store = mod.KnowledgeStore(hass=None)  # type: ignore[arg-type]
    store._entries = {
        "e1": {"id": "e1", "category": "general", "subject": "", "content": "alpha", "tags": []},
    }
    store._loaded = True
    store._rebuild_index()
    assert store._index_dirty is False

    async def _run():
        await store.async_add("general", "beta")
        assert store._index_dirty is True
        store._index_dirty = False
        added_id = next(eid for eid in store._entries if eid != "e1")
        deleted = await store.async_delete(added_id)
        assert deleted is True
        assert store._index_dirty is True

    asyncio.run(_run())


def test_query_and_index_via_full_class():
    """End-to-end exercise of KnowledgeStore._rebuild_index + semantic search."""
    mod = _load_module()
    store = mod.KnowledgeStore(hass=None)  # type: ignore[arg-type]
    store._entries = {
        "e1": {"id": "e1", "category": "area_alias", "subject": "werkkamer", "content": "werkkamer means office", "tags": ["office"]},
        "e2": {"id": "e2", "category": "entity_note", "subject": "switch.tv_power", "content": "TV is behind switch.tv_power; turn on first", "tags": ["tv"]},
        "e3": {"id": "e3", "category": "general", "subject": "", "content": "Espresso machine warms up in 20 seconds", "tags": []},
    }
    store._loaded = True
    store._rebuild_index()
    qv = store._query_vector("how do I turn on the TV?")
    # The TV note should win
    sims = {eid: mod._cosine(qv, vec) for eid, vec in store._vectors.items()}
    best = max(sims, key=sims.get)
    assert best == "e2", f"expected TV note to win, got sims={sims}"
