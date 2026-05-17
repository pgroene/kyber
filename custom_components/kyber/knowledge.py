"""Knowledge / memory store for Kyber.

Persists learned facts about the user's home that aren't captured by HA's
registries — area aliases (werkkamer = office), entity notes (xbox is
behind switch.xbox_power), procedures (espresso machine routine), device
chains (TV needs power switch first), and free-form general knowledge.

The store is exposed to the AI via the `search_knowledge` and
`get_entity_notes` tools, and via context injection (top entries are
prepended to the system prompt). The model can also emit `add_knowledge`
plan actions to record new facts.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_STORAGE_KEY = "kyber.knowledge"

# Allowed categories — keep small and meaningful.
CATEGORIES = {
    "area_alias",      # "werkkamer" → office
    "entity_note",     # facts about a specific entity
    "procedure",       # how to do something (e.g. start espresso machine)
    "device_chain",    # X depends on Y (TV behind switch.tv_power)
    "general",         # anything else
}


class KnowledgeStore:
    """In-memory cache backed by HA Store for persistence."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        async with self._lock:
            if self._loaded:
                return
            data = await self._store.async_load() or {}
            self._entries = data.get("entries", {})
            self._loaded = True
            _LOGGER.info("Kyber knowledge: loaded %d entries", len(self._entries))

    async def _persist(self) -> None:
        await self._store.async_save({"entries": self._entries})

    async def async_add(
        self,
        category: str,
        content: str,
        *,
        subject: str = "",
        tags: list[str] | None = None,
        source: str = "manual",
        confidence: float = 1.0,
        provenance: str = "",
        user_rating: int = 0,
    ) -> dict[str, Any]:
        await self.async_load()
        if category not in CATEGORIES:
            category = "general"
        entry_id = uuid.uuid4().hex[:12]
        now = int(time.time())
        entry = {
            "id": entry_id,
            "category": category,
            "subject": (subject or "").strip(),
            "content": content.strip(),
            "tags": [t.strip().lower() for t in (tags or []) if t.strip()],
            "source": source,
            "provenance": (provenance or "").strip(),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "user_rating": max(0, min(5, int(user_rating))),
            "created": now,
            "updated": now,
            "hits": 0,
        }
        self._entries[entry_id] = entry
        await self._persist()
        return entry

    async def async_update(self, entry_id: str, **changes: Any) -> dict[str, Any] | None:
        await self.async_load()
        entry = self._entries.get(entry_id)
        if not entry:
            return None
        allowed = {"category", "subject", "content", "tags", "confidence",
                   "source", "provenance", "user_rating"}
        for k, v in changes.items():
            if k in allowed:
                if k == "confidence":
                    v = max(0.0, min(1.0, float(v)))
                elif k == "user_rating":
                    v = max(0, min(5, int(v)))
                entry[k] = v
        entry["updated"] = int(time.time())
        await self._persist()
        return entry

    async def async_delete(self, entry_id: str) -> bool:
        await self.async_load()
        if entry_id in self._entries:
            del self._entries[entry_id]
            await self._persist()
            return True
        return False

    async def async_all(self) -> list[dict[str, Any]]:
        await self.async_load()
        return list(self._entries.values())

    async def async_search(
        self,
        query: str = "",
        category: str | None = None,
        subject: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        await self.async_load()
        q = (query or "").lower().strip()
        subj = (subject or "").lower().strip()
        cat = (category or "").lower().strip() or None
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in self._entries.values():
            if cat and entry.get("category") != cat:
                continue
            if subj and subj not in (entry.get("subject", "") or "").lower():
                continue
            score = 0.0
            blob = " ".join([
                entry.get("subject", ""),
                entry.get("content", ""),
                " ".join(entry.get("tags", []) or []),
            ]).lower()
            if q:
                if q in blob:
                    score += 1.0 + blob.count(q) * 0.1
                # token overlap
                q_tokens = {t for t in q.split() if len(t) > 2}
                blob_tokens = set(blob.split())
                score += 0.3 * len(q_tokens & blob_tokens)
                if score <= 0:
                    continue
            else:
                score = 0.5  # no query → return everything sorted by recency
            score += entry.get("confidence", 1.0) * 0.2
            score += min(entry.get("hits", 0), 20) * 0.02
            scored.append((score, entry))
        scored.sort(key=lambda p: (p[0], p[1].get("updated", 0)), reverse=True)
        return [e for _, e in scored[:limit]]

    async def async_get_for_entity(self, entity_id: str) -> list[dict[str, Any]]:
        """Return entries whose subject matches the entity_id exactly or
        whose tags include it.
        """
        await self.async_load()
        out = []
        eid = entity_id.lower()
        for entry in self._entries.values():
            if entry.get("subject", "").lower() == eid:
                out.append(entry)
            elif eid in (entry.get("tags") or []):
                out.append(entry)
        return out

    async def async_record_hit(self, entry_ids: Iterable[str]) -> None:
        """Bump hit counter for entries that were exposed to the AI. Async-safe."""
        await self.async_load()
        changed = False
        for eid in entry_ids:
            entry = self._entries.get(eid)
            if entry:
                entry["hits"] = int(entry.get("hits", 0)) + 1
                changed = True
        if changed:
            await self._persist()

    async def async_apply_feedback(
        self,
        entry_ids: Iterable[str],
        *,
        rating: int,
        notes: str = "",
        auto: bool = False,
    ) -> list[dict[str, Any]]:
        """Apply rating feedback to a batch of entries.

        Low ratings nudge confidence down and flag ``needs_review``;
        high ratings nudge confidence up. Feedback is appended to
        ``entry.feedback`` (rolling list, max 10).
        """
        await self.async_load()
        rating = max(1, min(5, int(rating)))
        if rating <= 2:
            delta = -0.10
        elif rating == 3:
            delta = -0.03
        elif rating == 4:
            delta = 0.05
        else:
            delta = 0.10
        now = int(time.time())
        updated: list[dict[str, Any]] = []
        for eid in entry_ids:
            entry = self._entries.get(eid)
            if not entry:
                continue
            new_conf = max(0.0, min(1.0, float(entry.get("confidence", 1.0)) + delta))
            entry["confidence"] = new_conf
            if rating <= 2:
                entry["needs_review"] = True
            elif rating >= 4 and entry.get("needs_review"):
                entry["needs_review"] = False
            fb = list(entry.get("feedback") or [])
            fb.append({
                "rating": rating,
                "notes": (notes or "")[:200],
                "auto": bool(auto),
                "ts": now,
            })
            entry["feedback"] = fb[-10:]
            entry["updated"] = now
            updated.append(entry)
        if updated:
            await self._persist()
        return updated

    async def async_mark_review(self, entry_ids: Iterable[str], needs_review: bool = True) -> int:
        """Mark/unmark entries as needing user review. Returns number changed."""
        await self.async_load()
        n = 0
        for eid in entry_ids:
            entry = self._entries.get(eid)
            if not entry:
                continue
            entry["needs_review"] = bool(needs_review)
            entry["updated"] = int(time.time())
            n += 1
        if n:
            await self._persist()
        return n

    # ── Sync read helpers (caller must ensure async_load() was awaited) ──
    def search_sync(self, query: str = "", category: str | None = None, subject: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Synchronous variant of async_search — for use after load()."""
        q = (query or "").lower().strip()
        subj = (subject or "").lower().strip()
        cat = (category or "").lower().strip() or None
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in self._entries.values():
            if cat and entry.get("category") != cat:
                continue
            if subj and subj not in (entry.get("subject", "") or "").lower():
                continue
            score = 0.0
            blob = " ".join([
                entry.get("subject", ""),
                entry.get("content", ""),
                " ".join(entry.get("tags", []) or []),
            ]).lower()
            if q:
                if q in blob:
                    score += 1.0 + blob.count(q) * 0.1
                q_tokens = {t for t in q.split() if len(t) > 2}
                blob_tokens = set(blob.split())
                score += 0.3 * len(q_tokens & blob_tokens)
                if score <= 0:
                    continue
            else:
                score = 0.5
            score += entry.get("confidence", 1.0) * 0.2
            score += min(entry.get("hits", 0), 20) * 0.02
            scored.append((score, entry))
        scored.sort(key=lambda p: (p[0], p[1].get("updated", 0)), reverse=True)
        return [e for _, e in scored[:limit]]

    def get_for_entity_sync(self, entity_id: str) -> list[dict[str, Any]]:
        eid = entity_id.lower()
        out = []
        for entry in self._entries.values():
            if entry.get("subject", "").lower() == eid:
                out.append(entry)
            elif eid in (entry.get("tags") or []):
                out.append(entry)
        return out

    async def async_pick_relevant(self, prompt: str, *, max_entries: int = 8) -> list[dict[str, Any]]:
        """Pick entries relevant to a free-form prompt for context injection."""
        results = await self.async_search(prompt, limit=max_entries)
        if results:
            return results
        # Always include high-confidence area aliases as background context
        return await self.async_search("", category="area_alias", limit=max_entries)


_INSTANCE_KEY = "kyber_knowledge_store"


def get_store(hass: HomeAssistant) -> KnowledgeStore:
    """Return a singleton store for this HA instance."""
    store = hass.data.get(_INSTANCE_KEY)
    if store is None:
        store = KnowledgeStore(hass)
        hass.data[_INSTANCE_KEY] = store
    return store
