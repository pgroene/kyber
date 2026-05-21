"""Source readers for automations, scripts, and blueprints.

These helpers expose the *raw* config of automations/scripts/blueprints so
the AI can read them and the deep analyzer can hash + memoize them. They
do NOT depend on entity states; they go straight to the YAML files in
the HA config dir.

Memoization: `AnalysisMemo` stores a content hash + last-analyzed
timestamp + the knowledge entry IDs that were created from each item.
Re-running the deep analyzer skips items whose hash hasn't changed.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_MEMO_VERSION = 1
_MEMO_KEY = "kyber_analysis_memo"


# ── Hashing ──────────────────────────────────────────────────────────
def content_hash(obj: Any) -> str:
    """Stable SHA-256 hash of any JSON/YAML-serialisable structure."""
    try:
        blob = yaml.safe_dump(obj, sort_keys=True, default_flow_style=False).encode("utf-8")
    except Exception:  # noqa: BLE001
        blob = str(obj).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()[:16]


# ── YAML readers (run in executor — sync file I/O is fine) ────────────

# Custom loader that silently ignores unknown YAML tags (like HA blueprint
# `!input`, `!secret`, etc.) instead of raising a ConstructorError.
class _SafeLineLoader(yaml.SafeLoader):
    pass

_SafeLineLoader.add_multi_constructor(
    "",
    lambda loader, tag_suffix, node: (
        loader.construct_scalar(node)
        if isinstance(node, yaml.ScalarNode)
        else loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node)
    ),
)


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.load(f, Loader=_SafeLineLoader)  # noqa: S506
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber source: failed to read %s: %s", path, err)
        return None


def _read_automations_file(config_dir: str) -> list[dict[str, Any]]:
    """Load automations.yaml. Each item is a config dict."""
    data = _load_yaml(Path(config_dir) / "automations.yaml")
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _read_scripts_file(config_dir: str) -> list[dict[str, Any]]:
    """Load scripts.yaml. HA stores scripts as a mapping {id: config}."""
    data = _load_yaml(Path(config_dir) / "scripts.yaml")
    out: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for sid, cfg in data.items():
            if isinstance(cfg, dict):
                out.append({"id": sid, **cfg})
    elif isinstance(data, list):
        for cfg in data:
            if isinstance(cfg, dict):
                out.append(cfg)
    return out


def _list_blueprint_files(config_dir: str) -> list[Path]:
    """Return every blueprint YAML under <config>/blueprints/{automation,script}/**/*.yaml."""
    bp_root = Path(config_dir) / "blueprints"
    if not bp_root.exists():
        return []
    out: list[Path] = []
    for kind in ("automation", "script"):
        sub = bp_root / kind
        if not sub.exists():
            continue
        for root, _dirs, files in os.walk(sub):
            for f in files:
                if f.endswith((".yaml", ".yml")):
                    out.append(Path(root) / f)
    return out


# ── Public sync readers (call via async_add_executor_job) ────────────
def read_automations(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return normalised automation entries.

    Each item: {id, alias, mode, trigger, condition, action, hash, num_triggers, num_actions}.
    """
    items = _read_automations_file(hass.config.config_dir)
    out: list[dict[str, Any]] = []
    for idx, cfg in enumerate(items):
        triggers = cfg.get("trigger") or cfg.get("triggers") or []
        actions = cfg.get("action") or cfg.get("actions") or []
        if not isinstance(triggers, list):
            triggers = [triggers]
        if not isinstance(actions, list):
            actions = [actions]
        out.append({
            "id": str(cfg.get("id", f"_anon_{idx}")),
            "alias": cfg.get("alias") or "",
            "description": cfg.get("description") or "",
            "mode": cfg.get("mode", "single"),
            "trigger": triggers,
            "condition": cfg.get("condition") or [],
            "action": actions,
            "num_triggers": len(triggers),
            "num_actions": len(actions),
            "hash": content_hash(cfg),
        })
    return out


def read_scripts(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return normalised script entries."""
    items = _read_scripts_file(hass.config.config_dir)
    out: list[dict[str, Any]] = []
    for idx, cfg in enumerate(items):
        seq = cfg.get("sequence") or cfg.get("actions") or []
        if not isinstance(seq, list):
            seq = [seq]
        out.append({
            "id": str(cfg.get("id", f"_anon_{idx}")),
            "alias": cfg.get("alias") or cfg.get("name") or cfg.get("id") or "",
            "description": cfg.get("description") or "",
            "mode": cfg.get("mode", "single"),
            "sequence": seq,
            "fields": cfg.get("fields") or {},
            "num_steps": len(seq),
            "hash": content_hash(cfg),
        })
    return out


def read_blueprints(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return blueprint metadata for every YAML under <config>/blueprints/."""
    files = _list_blueprint_files(hass.config.config_dir)
    out: list[dict[str, Any]] = []
    for path in files:
        data = _load_yaml(path) or {}
        bp = data.get("blueprint") if isinstance(data, dict) else None
        meta = bp if isinstance(bp, dict) else {}
        try:
            rel = path.relative_to(Path(hass.config.config_dir))
            rel_str = str(rel).replace("\\", "/")
        except ValueError:
            rel_str = str(path)
        kind = "automation" if "/automation/" in rel_str or rel_str.startswith("blueprints/automation") else (
            "script" if "/script/" in rel_str or rel_str.startswith("blueprints/script") else "unknown"
        )
        out.append({
            "path": rel_str,
            "kind": kind,
            "name": meta.get("name") or path.stem,
            "description": meta.get("description") or "",
            "domain": meta.get("domain") or kind,
            "source_url": meta.get("source_url") or "",
            "input_keys": list((meta.get("input") or {}).keys()) if isinstance(meta.get("input"), dict) else [],
            "hash": content_hash(data),
        })
    return out


def read_blueprint(hass: HomeAssistant, rel_path: str) -> dict[str, Any]:
    """Return the FULL parsed blueprint config (caller MUST validate path)."""
    base = Path(hass.config.config_dir).resolve()
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return {"error": "path escapes config dir"}
    if not target.exists():
        return {"error": "not found"}
    data = _load_yaml(target) or {}
    return {"path": rel_path, "content": data, "hash": content_hash(data)}


# ── Memoization store ────────────────────────────────────────────────
class AnalysisMemo:
    """Persistent record of which configs we've already analyzed.

    Shape:
        {
          "items": {
            "<kind>:<id_or_path>": {
              "kind": "automation"|"script"|"blueprint",
              "hash": "sha256:...",
              "analyzed_at": <unix ts>,
              "fact_ids": ["...","..."],
              "skipped": false  # true if analyzer decided no useful facts
            }
          }
        }
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, _MEMO_VERSION, _MEMO_KEY)
        self._data: dict[str, Any] = {"items": {}}
        self._loaded = False

    async def async_load(self) -> None:
        if self._loaded:
            return
        data = await self._store.async_load() or {"items": {}}
        if "items" not in data or not isinstance(data["items"], dict):
            data["items"] = {}
        self._data = data
        self._loaded = True

    async def _persist(self) -> None:
        await self._store.async_save(self._data)

    def _key(self, kind: str, ident: str) -> str:
        return f"{kind}:{ident}"

    def is_changed(self, kind: str, ident: str, new_hash: str) -> bool:
        rec = self._data["items"].get(self._key(kind, ident))
        if not rec:
            return True
        return rec.get("hash") != new_hash

    def is_pending_lens(self, kind: str, ident: str, new_hash: str, lens: int) -> bool:
        """Return True if this item needs analysis with the given prompt lens.

        An item is pending when:
          - It has never been analyzed, OR
          - Its content hash changed (automation was edited), OR
          - This specific lens index hasn't been applied yet.
        """
        rec = self._data["items"].get(self._key(kind, ident))
        if not rec:
            return True
        if rec.get("hash") != new_hash:
            return True  # Content changed — all lenses are stale
        return lens not in (rec.get("lenses_done") or [])

    def get(self, kind: str, ident: str) -> dict[str, Any] | None:
        return self._data["items"].get(self._key(kind, ident))

    async def async_record(
        self,
        *,
        kind: str,
        ident: str,
        new_hash: str,
        fact_ids: list[str],
        skipped: bool = False,
    ) -> None:
        import time
        self._data["items"][self._key(kind, ident)] = {
            "kind": kind,
            "ident": ident,
            "hash": new_hash,
            "analyzed_at": int(time.time()),
            "fact_ids": fact_ids,
            "lenses_done": [],
            "skipped": skipped,
        }
        await self._persist()

    async def async_record_lens(
        self,
        *,
        kind: str,
        ident: str,
        new_hash: str,
        lens: int,
        fact_ids: list[str],
        skipped: bool = False,
    ) -> None:
        """Record analysis for a specific prompt lens, merging with existing data."""
        import time
        key = self._key(kind, ident)
        rec = self._data["items"].get(key) or {}

        # If hash changed, reset all lens tracking
        if rec.get("hash") != new_hash:
            rec = {"kind": kind, "ident": ident, "fact_ids": [], "lenses_done": []}

        lenses_done: list[int] = list(rec.get("lenses_done") or [])
        if lens not in lenses_done:
            lenses_done.append(lens)

        all_fact_ids: list[str] = list(rec.get("fact_ids") or [])
        all_fact_ids.extend(fact_ids)

        self._data["items"][key] = {
            "kind": kind,
            "ident": ident,
            "hash": new_hash,
            "analyzed_at": int(time.time()),
            "fact_ids": all_fact_ids,
            "lenses_done": sorted(lenses_done),
            "skipped": skipped and not all_fact_ids,
        }
        await self._persist()

    async def async_forget(self, kind: str, ident: str) -> None:
        self._data["items"].pop(self._key(kind, ident), None)
        await self._persist()

    def all_records(self) -> list[dict[str, Any]]:
        return list(self._data["items"].values())


_MEMO_SINGLETON_KEY = "kyber_analysis_memo_singleton"


def get_memo(hass: HomeAssistant) -> AnalysisMemo:
    memo = hass.data.get(_MEMO_SINGLETON_KEY)
    if memo is None:
        memo = AnalysisMemo(hass)
        hass.data[_MEMO_SINGLETON_KEY] = memo
    return memo
