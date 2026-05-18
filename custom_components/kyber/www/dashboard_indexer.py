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

# ── Public API ─────────────────────────────────────────────────────────────


async def async_index_dashboard_entities(hass: Any) -> dict[str, list[str]]:
    """Return a mapping of dashboard_slug → sorted list of entity_ids.

    Runs synchronous file I/O in the executor so the event loop is not blocked.
    The result is also cached under hass.data[DASHBOARD_ENTITIES_KEY].
    """
    config_dir: str = hass.config.config_dir
    result: dict[str, list[str]] = await hass.async_add_executor_job(
        _index_sync, config_dir
    )
    hass.data[DASHBOARD_ENTITIES_KEY] = result
    total = sum(len(v) for v in result.values())
    _LOGGER.info(
        "Kyber dashboard indexer: %d entity references across %d dashboard(s): %s",
        total,
        len(result),
        list(result.keys()),
    )
    return result


# ── Synchronous scanning helpers ───────────────────────────────────────────


def _index_sync(config_dir: str) -> dict[str, list[str]]:
    """Scan dashboard files synchronously (called via executor)."""
    result: dict[str, list[str]] = {}

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
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Kyber dashboard indexer: skipping %s — %s", f, err)

    # 2. YAML-managed root dashboard
    root_yaml = Path(config_dir) / "ui-lovelace.yaml"
    if root_yaml.is_file():
        entities = _parse_yaml_file(root_yaml)
        if entities:
            result["ui-lovelace"] = sorted(entities)

    # 3. YAML-managed dashboard directory
    lovelace_dir = Path(config_dir) / "lovelace"
    if lovelace_dir.is_dir():
        for yf in sorted(lovelace_dir.glob("*.yaml")):
            entities = _parse_yaml_file(yf)
            if entities:
                result[yf.stem] = sorted(entities)

    return result


def _parse_yaml_file(path: Path) -> set[str]:
    """Parse a YAML dashboard file and return the set of entity IDs found."""
    try:
        import yaml  # HA ships with PyYAML
        with open(path, encoding="utf-8") as fp:
            config = yaml.safe_load(fp)
        if isinstance(config, dict):
            return _extract_entities(config)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber dashboard indexer: could not parse %s — %s", path, err)
    return set()


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
