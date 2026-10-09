"""The knowledge store drops explorer/narrator facts of vanished entities."""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant

# Imported at test time: other test modules swap stubs into sys.modules while
# they are collected; conftest restores the real modules before each test.


def _knowledge():
    from custom_components.kyber import knowledge
    return knowledge


async def _store(hass: HomeAssistant):
    store = _knowledge().KnowledgeStore(hass)
    await store.async_load()
    return store


async def _seed(store) -> dict[str, str]:
    """One entry of every relevant kind; returns name → id."""
    ids = {}
    # Narrator first: storing a narrator description evicts the explorer fact
    # of the same entity, which would hide the explorer case.
    ids["narrator_gone"] = (await store.async_add(
        "general", "light.gone lights the hall", subject="light.gone", source="entity_narrator",
    ))["id"]
    ids["explorer_gone"] = (await store.async_add(
        "general", 'light "Old" [light.gone]', subject="light.gone", source="entity_explorer",
    ))["id"]
    ids["explorer_alias_gone"] = (await store.async_add(
        "entity_alias", "light.gone", subject="Old original", source="entity_explorer",
    ))["id"]
    ids["narrator_alias_gone"] = (await store.async_add(
        "entity_alias", "light.gone", subject="hall light", source="entity_narrator",
    ))["id"]
    ids["explorer_kept"] = (await store.async_add(
        "general", 'light "Desk" [light.desk]', subject="light.desk", source="entity_explorer",
    ))["id"]
    ids["narrator_alias_kept"] = (await store.async_add(
        "entity_alias", "light.desk", subject="desk lamp", source="entity_narrator",
    ))["id"]
    # Not generated per entity: must survive even though light.gone is gone.
    ids["user_fact"] = (await store.async_add(
        "general", "light.gone was the hall light", subject="light.gone", source="manual",
    ))["id"]
    ids["deep_fact"] = (await store.async_add(
        "general", "Automation x uses light.gone", subject="light.gone", source="deep-analyzer",
    ))["id"]
    ids["integration_summary"] = (await store.async_add(
        "integration_capability", "hue offers lights", subject="hue", source="integration_explorer",
    ))["id"]
    return ids


async def test_prune_removes_only_generated_facts_of_vanished_entities(hass: HomeAssistant) -> None:
    store = await _store(hass)
    ids = await _seed(store)

    removed = await store.async_prune_orphaned_entity_facts({"light.desk"})

    assert removed == 4
    remaining = {e["id"] for e in await store.async_all(is_admin=True)}
    for gone in ("explorer_gone", "explorer_alias_gone", "narrator_gone", "narrator_alias_gone"):
        assert ids[gone] not in remaining, gone
    for kept in ("explorer_kept", "narrator_alias_kept", "user_fact", "deep_fact", "integration_summary"):
        assert ids[kept] in remaining, kept


async def test_prune_is_noop_when_registry_complete(hass: HomeAssistant) -> None:
    store = await _store(hass)
    await _seed(store)
    assert await store.async_prune_orphaned_entity_facts({"light.desk", "light.gone"}) == 0


def test_entity_fact_target_shapes() -> None:
    entity_fact_target = _knowledge().entity_fact_target
    assert entity_fact_target({"source": "entity_explorer", "category": "general", "subject": "light.a"}) == "light.a"
    assert entity_fact_target({"source": "entity_narrator", "category": "entity_alias", "content": "light.a"}) == "light.a"
    # Old sentence-style alias still resolves when it names exactly one entity.
    assert entity_fact_target({
        "source": "entity_narrator", "category": "entity_alias",
        "content": "When user searches for 'lamp', the matching entity is: light.a",
    }) == "light.a"
    # Ambiguous or foreign entries are never treated as orphaned.
    assert entity_fact_target({
        "source": "entity_narrator", "category": "entity_alias", "content": "light.a or light.b",
    }) is None
    assert entity_fact_target({"source": "entity_explorer", "category": "general", "subject": "Kitchen"}) is None
    assert entity_fact_target({"source": "manual", "category": "general", "subject": "light.a"}) is None


async def test_add_tags_appends_once_and_persists_once(hass: HomeAssistant) -> None:
    store = await _store(hass)
    a = await store.async_add("general", "a", subject="light.a", tags=["x"], source="entity_narrator")
    b = await store.async_add("general", "b", subject="light.b", tags=["sig:old"], source="entity_narrator")

    changed = await store.async_add_tags({a["id"]: ["sig:1"], b["id"]: ["sig:old"], "missing": ["y"]})

    assert changed == 1
    assert (await store.async_get(a["id"]))["tags"] == ["x", "sig:1"]
    assert (await store.async_get(b["id"]))["tags"] == ["sig:old"]
