"""Dashboard entity indexer for Kyber.

Scans all Lovelace dashboards (both UI-managed storage JSON and YAML-managed
configs) to extract entity IDs that the user has placed on their dashboards.
These are the entities the user actually interacts with — they get priority
in narrator narration, TF-IDF boosts in knowledge search, and a dedicated
section in the system prompt context.

Storage layout scanned:
  .storage/lovelace          — default Overview dashboard (UI-managed)
  .storage/lovelace.*        — named dashboards (UI-managed)
  ui-lovelace.yaml           — root YAML dashboard (YAML-managed)
  lovelace/                  — YAML-managed dashboard directory
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Key under hass.data where the indexed result is stored.
DASHBOARD_ENTITIES_KEY = "kyber_dashboard_entities"
# Key under hass.data where the entity→label map is stored.
DASHBOARD_ENTITY_NAMES_KEY = "kyber_dashboard_entity_names"

# ── Public API ─────────────────────────────────────────────────────────────


async def async_index_dashboard_entities(hass: Any) -> dict[str, list[str]]:
    """Return a mapping of dashboard_slug → sorted list of entity_ids.

    Runs synchronous file I/O in the executor so the event loop is not blocked.
    Results are cached under hass.data[DASHBOARD_ENTITIES_KEY] (entity lists)
    and hass.data[DASHBOARD_ENTITY_NAMES_KEY] (entity_id → human label map).
    """
    config_dir: str = hass.config.config_dir
    result, names = await hass.async_add_executor_job(_index_sync, config_dir)
    hass.data[DASHBOARD_ENTITIES_KEY] = result
    hass.data[DASHBOARD_ENTITY_NAMES_KEY] = names
    total = sum(len(v) for v in result.values())
    _LOGGER.info(
        "Kyber dashboard indexer: %d entity references (%d named) across %d dashboard(s): %s",
        total,
        len(names),
        len(result),
        list(result.keys()),
    )
    return result


# ── Synchronous scanning helpers ───────────────────────────────────────────


def _index_sync(config_dir: str) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Scan dashboard files synchronously (called via executor).

    Returns:
        entities: dashboard_slug → sorted list of entity_ids
        names:    entity_id → human-readable label from card name/title
    """
    result: dict[str, list[str]] = {}
    names: dict[str, str] = {}

    # 1. UI-managed dashboards: .storage/lovelace and .storage/lovelace.*
    storage_path = Path(config_dir) / ".storage"
    if storage_path.is_dir():
        for f in sorted(storage_path.iterdir()):
            if f.name != "lovelace" and not f.name.startswith("lovelace."):
                continue
            try:
                with open(f, encoding="utf-8") as fp:
                    raw = json.load(fp)
                config = (raw.get("data") or {}).get("config") or {}
                title = (config.get("title") or f.name).strip()
                entities = _extract_entities(config)
                if entities:
                    result[title] = sorted(entities)
                names.update(_extract_entity_names(config))
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Kyber dashboard indexer: skipping %s — %s", f, err)

    # 2. YAML-managed root dashboard
    root_yaml = Path(config_dir) / "ui-lovelace.yaml"
    if root_yaml.is_file():
        entities, file_names = _parse_yaml_file(root_yaml)
        if entities:
            result["ui-lovelace"] = sorted(entities)
        names.update(file_names)

    # 3. YAML-managed dashboard directory
    lovelace_dir = Path(config_dir) / "lovelace"
    if lovelace_dir.is_dir():
        for yf in sorted(lovelace_dir.glob("*.yaml")):
            entities, file_names = _parse_yaml_file(yf)
            if entities:
                result[yf.stem] = sorted(entities)
            names.update(file_names)

    return result, names


def _parse_yaml_file(path: Path) -> tuple[set[str], dict[str, str]]:
    """Parse a YAML dashboard file and return (entity_ids, entity_names)."""
    try:
        import yaml  # HA ships with PyYAML
        with open(path, encoding="utf-8") as fp:
            config = yaml.safe_load(fp)
        if isinstance(config, dict):
            return _extract_entities(config), _extract_entity_names(config)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber dashboard indexer: could not parse %s — %s", path, err)
    return set(), {}


# ── Recursive entity extraction ────────────────────────────────────────────


def _extract_entities(obj: Any) -> set[str]:
    """Recursively walk a Lovelace config dict/list and collect entity IDs.

    Handles all card shapes:
      entity: "light.xxx"              — single entity key
      entities: ["light.xxx", ...]     — list of strings
      entities: [{entity: "light.xxx"}]— list of objects
      Nested cards inside vertical-stack, horizontal-stack, grid, conditional,
      entity-filter, etc. are recursed automatically.
    """
    entities: set[str] = set()
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "entity" and isinstance(val, str) and _looks_like_entity(val):
                entities.add(val)
            elif key == "entities" and isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and _looks_like_entity(item):
                        entities.add(item)
                    elif isinstance(item, dict):
                        # {entity: "light.xxx", name: "Override"} shape
                        if "entity" in item and isinstance(item["entity"], str) and _looks_like_entity(item["entity"]):
                            entities.add(item["entity"])
                        entities |= _extract_entities(item)
            elif isinstance(val, (dict, list)):
                entities |= _extract_entities(val)
    elif isinstance(obj, list):
        for item in obj:
            entities |= _extract_entities(item)
    return entities


def _extract_entity_names(obj: Any, _names: "dict[str, str] | None" = None) -> dict[str, str]:
    """Recursively walk a Lovelace config and return {entity_id: human_label}.

    Captures the card-level ``name:`` or ``title:`` that the user wrote next to
    an entity reference.  First name encountered wins (most-specific card wins).
    """
    if _names is None:
        _names = {}
    if isinstance(obj, dict):
        label_raw = obj.get("name") or obj.get("title")
        label = label_raw.strip() if isinstance(label_raw, str) and label_raw.strip() else None

        # Single-entity card: {entity: "switch.x", name: "Espresso"}
        eid = obj.get("entity")
        if isinstance(eid, str) and _looks_like_entity(eid) and label:
            _names.setdefault(eid, label)

        # entities list items with inline name override
        ents = obj.get("entities")
        if isinstance(ents, list):
            for item in ents:
                if isinstance(item, dict):
                    item_eid = item.get("entity")
                    item_label_raw = item.get("name") or item.get("title")
                    item_label = (
                        item_label_raw.strip()
                        if isinstance(item_label_raw, str) and item_label_raw.strip()
                        else None
                    )
                    if isinstance(item_eid, str) and _looks_like_entity(item_eid) and item_label:
                        _names.setdefault(item_eid, item_label)

        # Recurse into all nested structures
        for val in obj.values():
            if isinstance(val, (dict, list)):
                _extract_entity_names(val, _names)
    elif isinstance(obj, list):
        for item in obj:
            _extract_entity_names(item, _names)
    return _names



def _looks_like_entity(val: str) -> bool:
    """Return True if val looks like a real entity_id (domain.name)."""
    if "." not in val:
        return False
    if val.startswith("attribute."):
        return False
    # Reject obvious Jinja2 template expressions
    if "{{" in val or "}}" in val:
        return False
    return True


# ── Helpers ────────────────────────────────────────────────────────────────


def get_all_dashboard_entities(hass: Any) -> set[str]:
    """Return the flat set of all entity IDs found across all dashboards."""
    data: dict[str, list[str]] = hass.data.get(DASHBOARD_ENTITIES_KEY) or {}
    result: set[str] = set()
    for entities in data.values():
        result.update(entities)
    return result


def get_dashboard_entity_names(hass: Any) -> dict[str, str]:
    """Return {entity_id: human_label} for entities with a named card on any dashboard."""
    return dict(hass.data.get(DASHBOARD_ENTITY_NAMES_KEY) or {})


async def async_store_dashboard_labels(hass: Any, kstore: Any) -> int:
    """Store each named dashboard entity as its own knowledge entry.

    Entries use source="dashboard_indexer" so they are never overwritten by
    the narrator or other sources.  On every call the old dashboard_indexer
    entries are removed first so renamed/removed cards are kept in sync.

    Returns the number of entries written.
    """
    await kstore.async_load()

    # Remove all previous dashboard_indexer entries (full refresh).
    old_ids = [
        eid for eid, e in kstore._entries.items()
        if e.get("source") == "dashboard_indexer"
    ]
    for old_id in old_ids:
        await kstore.async_delete(old_id)

    names: dict[str, str] = get_dashboard_entity_names(hass)
    if not names:
        return 0

    for entity_id, label in names.items():
        domain = entity_id.split(".")[0]
        content = (
            f"{entity_id} is labelled '{label}' on the user's dashboard."
        )
        await kstore.async_add(
            "entity_alias",
            content,
            subject=entity_id,
            tags=[entity_id, domain, label.lower(), "dashboard"],
            source="dashboard_indexer",
            confidence=0.95,
            provenance="dashboard card name",
            _save=False,
        )

    await kstore.async_force_save()
    _LOGGER.info(
        "Kyber dashboard indexer: stored %d label entries in knowledge store", len(names)
    )
    return len(names)
