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
import math
import re
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
    "entity_alias",    # user term → entity_id mapping
    "procedure",       # how to do something (e.g. start espresso machine)
    "device_chain",    # X depends on Y (TV behind switch.tv_power)
    "language_hint",   # locale-specific vocabulary (seeded from language_hints.py)
    "general",         # anything else
    "proposal",        # pending review items that execute on approval
}


# ── Embeddings (lightweight, in-memory TF-IDF over knowledge entries) ──────
# We avoid pulling heavy deps (sentence-transformers etc.) so that Kyber stays
# pure-python + zero-install. Tokens = lowercased word unigrams ∪ bigrams.
# IDF is computed lazily over the current corpus and cached.

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    words = [w.lower() for w in _TOKEN_RE.findall(text) if len(w) > 1]
    bigrams = [f"{a}_{b}" for a, b in zip(words, words[1:])]
    return words + bigrams


def _vec_dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def _vec_norm(a: dict[str, float]) -> float:
    return math.sqrt(sum(v * v for v in a.values())) or 1.0


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    return _vec_dot(a, b) / (_vec_norm(a) * _vec_norm(b))


# ── Domain-intent boosting ──────────────────────────────────────────────────
# When a user query contains domain-specific keywords (e.g. "muziek"),
# entries whose subject starts with the matching HA domain (e.g.
# "media_player.") receive a score boost so they are not crowded out by
# structural/infrastructure entities (e.g. adaptive_lighting switches) that
# happen to share an area name with the query.

_DOMAIN_INTENT: dict[str, list[str]] = {
    "media_player": [
        "muziek", "music", "speelt", "playing", "speel", "play",
        "radio", "stream", "song", "playlist", "speaker", "luidspreker",
        "afspelen", "volume", "album", "artiest", "artist", "track",
        "nummer", "liedje", "geluid", "audio",
    ],
    "light": [
        "licht", "lamp", "lampen", "lights", "dimmer", "brightness",
        "helderheid", "kleur", "color", "colour", "verlicht", "verlichting",
        "spots", "spot", "spotlight",
    ],
    "climate": [
        "temperatuur", "temperature", "warm", "koud", "cold", "hot",
        "heating", "cooling", "thermostat", "thermostaat", "verwarming",
        "koeling", "graden", "degrees",
    ],
    "cover": [
        "gordijn", "gordijnen", "curtain", "curtains", "jaloezie",
        "jaloezieën", "blind", "blinds", "shutter", "shutters",
        "rolluik", "rolgordijn", "zonnescherm",
    ],
    "binary_sensor": [
        "beweging", "motion", "aanwezig", "presence", "open", "deur",
        "raam", "window",
    ],
    "vacuum": [
        "stofzuiger", "robot", "vacuum", "schoonmaken", "clean", "zuigen",
    ],
}

# Domains that are structural/infrastructure and should be suppressed unless
# the query is explicitly about them.  Applied when query has NO matching
# domain intent keywords.
_INFRASTRUCTURE_PREFIXES = (
    "switch.adaptive_lighting_",
)

_DOMAIN_BOOST = 0.15          # added to sim when entry domain matches intent
_INFRA_PENALTY = 0.12         # subtracted from sim for infra entities

# ── Signal-word filter ───────────────────────────────────────────────────────
# After hybrid retrieval we check whether retrieved entries actually share a
# "signal word" with the query.  Signal words are non-stopword, non-generic
# query tokens — the words that distinguish "espresso machine" from "washing
# machine".  If an entry shares no signal words with the query, it matched
# only on peripheral terms (like "machine") and is dropped so the AI isn't
# misled.  Only applied when the query contains at least one signal word.

_QUERY_STOPWORDS: frozenset[str] = frozenset({
    # Dutch
    "mijn", "de", "het", "een", "is", "zijn", "heeft", "van", "in", "op",
    "aan", "met", "voor", "naar", "bij", "over", "door", "kan", "wil",
    "wat", "welk", "welke", "ons", "uw", "hun", "dit", "dat", "deze",
    "die", "niet", "wel", "ook", "nog", "al", "maar", "en", "of", "als",
    "dan", "er", "je", "ik", "ze", "we", "hij", "zij", "hoe", "zet",
    "doe", "maak", "zet", "aan", "uit",
    # English
    "my", "the", "a", "an", "is", "are", "has", "have", "of", "in",
    "on", "at", "with", "for", "to", "from", "by", "about", "can",
    "will", "would", "what", "which", "this", "that", "these", "those",
    "not", "also", "but", "and", "or", "if", "then", "there", "you",
    "i", "they", "he", "she", "it", "how", "where", "when", "turn",
    "set", "get", "put", "show", "tell", "give", "make",
})

# Generic device nouns — too common to serve as signal words alone.
_GENERIC_DEVICE_WORDS: frozenset[str] = frozenset({
    "machine", "apparaat", "device", "sensor", "switch", "light", "lamp",
    "ding", "entity", "smart", "home", "huis", "kamer", "room",
    "system", "systeem", "unit", "module", "power", "energy",
})


def _query_signal_words(query: str) -> frozenset[str]:
    """Return the 'signal words' in a query — specific, non-generic tokens.

    These are tokens that must appear in a retrieved entry for the match to
    be considered relevant.  Stopwords and generic device nouns are excluded.
    """
    tokens = {w.lower() for w in _TOKEN_RE.findall(query) if len(w) > 2}
    return frozenset(tokens - _QUERY_STOPWORDS - _GENERIC_DEVICE_WORDS)


def _detect_domain_intents(query_words: set[str]) -> set[str]:
    """Return HA domain prefixes implied by keywords in the query."""
    domains: set[str] = set()
    for domain, keywords in _DOMAIN_INTENT.items():
        if query_words & set(keywords):
            domains.add(domain)
    return domains


class KnowledgeStore:
    """In-memory cache backed by HA Store for persistence."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._lock = asyncio.Lock()
        # Embedding index — rebuilt lazily on entry mutation.
        self._idf: dict[str, float] = {}
        self._vectors: dict[str, dict[str, float]] = {}
        self._index_dirty = True

    @property
    def is_loaded(self) -> bool:
        """Return True once async_load() has completed successfully."""
        return self._loaded

    # ── Embedding index helpers ──────────────────────────────────────
    def _entry_blob(self, entry: dict[str, Any]) -> str:
        parts = [
            str(entry.get("subject") or ""),
            str(entry.get("content") or ""),
            " ".join(str(t) for t in (entry.get("tags") or []) if t is not None),
            str(entry.get("category") or ""),
        ]
        return " ".join(p for p in parts if p)

    def _rebuild_index(self) -> None:
        """Recompute IDF and per-entry TF-IDF vectors over current corpus.

        low_quality entries are excluded: they are "already attempted" markers
        only and must not pollute IDF weights or appear in semantic search.
        """
        docs: dict[str, list[str]] = {}
        df: dict[str, int] = {}
        for eid, entry in self._entries.items():
            if "low_quality" in (entry.get("tags") or []):
                continue
            toks = _tokenize(self._entry_blob(entry))
            docs[eid] = toks
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        n_docs = max(1, len(docs))
        self._idf = {t: math.log((n_docs + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        self._vectors = {}
        for eid, toks in docs.items():
            tf: dict[str, float] = {}
            for t in toks:
                tf[t] = tf.get(t, 0.0) + 1.0
            self._vectors[eid] = {t: f * self._idf.get(t, 1.0) for t, f in tf.items()}
        self._index_dirty = False

    async def _async_rebuild_index_if_needed(self) -> None:
        """Rebuild the TF-IDF index, offloading to executor for large corpora."""
        if not self._index_dirty:
            return
        if len(self._entries) > 150:
            await self.hass.async_add_executor_job(self._rebuild_index)
        else:
            self._rebuild_index()

    def _query_vector(self, text: str) -> dict[str, float]:
        if self._index_dirty:
            self._rebuild_index()
        toks = _tokenize(text)
        tf: dict[str, float] = {}
        for t in toks:
            tf[t] = tf.get(t, 0.0) + 1.0
        # Use existing IDF; unseen tokens get neutral weight 1.0 so the vector
        # still has signal even if the corpus is empty.
        return {t: f * self._idf.get(t, 1.0) for t, f in tf.items()}

    async def async_semantic_search(
        self, query: str, *, limit: int = 8, min_score: float = 0.05
    ) -> list[dict[str, Any]]:
        """Return top-N entries ranked by cosine similarity over TF-IDF.

        Area/entity_id exact-match boost: when a query token exactly matches an
        area tag or entity_id segment in an entry, the score is boosted so that
        e.g. "slaapkamer" returns slaapkamer facts above woonkamer facts even when
        both have similar TF-IDF weights.

        Domain-intent boost: when the query contains domain keywords (e.g.
        "muziek" → media_player domain), entries whose subject starts with that
        domain prefix receive an additional boost so they rank above structural
        entities (e.g. adaptive_lighting switches) that share the area name.

        Infrastructure penalty: adaptive_lighting and other infrastructure
        entities receive a slight penalty when the query contains no
        domain-specific keywords, preventing them from crowding out relevant
        entities.
        """
        await self.async_load()
        if not query or not self._entries:
            return []
        await self._async_rebuild_index_if_needed()
        qv = self._query_vector(query)
        if not qv:
            return []

        # Pre-compute query word set for exact-match and domain-intent boosts.
        query_words = set(_TOKEN_RE.findall(query.lower()))
        domain_intents = _detect_domain_intents(query_words)

        scored: list[tuple[float, dict[str, Any]]] = []
        for eid, vec in self._vectors.items():
            entry = self._entries[eid]
            # Skip low-quality entries — same filter as keyword search.
            if "low_quality" in (entry.get("tags") or []):
                continue
            sim = _cosine(qv, vec)
            if sim >= min_score:
                entry = dict(entry)
                subject = (entry.get("subject") or "").lower()
                if query_words:
                    tags = set(t.lower() for t in (entry.get("tags") or []) if t)
                    subject_tokens = set(_TOKEN_RE.findall(subject))
                    # Boost for exact area/entity token matches.
                    exact_hits = len(query_words & (tags | subject_tokens))
                    if exact_hits:
                        sim = min(1.0, sim + 0.12 * exact_hits)
                # Domain-intent boost: push matching domain entries to the top.
                if domain_intents:
                    for domain in domain_intents:
                        if subject.startswith(domain + "."):
                            sim = min(1.0, sim + _DOMAIN_BOOST)
                            break
                # Infrastructure penalty: suppress structural entities when
                # the query has no explicit domain keywords for them.
                if not domain_intents or "light" not in domain_intents:
                    if any(subject.startswith(pfx) for pfx in _INFRASTRUCTURE_PREFIXES):
                        sim = max(0.0, sim - _INFRA_PENALTY)
                entry["_score"] = round(sim, 4)
                scored.append((sim, entry))
        scored.sort(key=lambda p: p[0], reverse=True)
        return [e for _, e in scored[:limit]]


    async def async_load(self) -> None:
        async with self._lock:
            if self._loaded:
                return
            data = await self._store.async_load() or {}
            self._entries = data.get("entries", {})
            self._loaded = True
            self._index_dirty = True
            _LOGGER.info("Kyber knowledge: loaded %d entries", len(self._entries))

    async def _persist(self, *, invalidate_index: bool = False) -> None:
        if invalidate_index:
            self._index_dirty = True
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
        _save: bool = True,
    ) -> dict[str, Any]:
        await self.async_load()
        if category not in CATEGORIES:
            category = "general"
        content_stripped = content.strip()
        subject_stripped = (subject or "").strip()
        # Dedup: skip if identical content+subject+category already exists.
        for existing in self._entries.values():
            if (
                existing.get("content", "").strip() == content_stripped
                and existing.get("subject", "").strip() == subject_stripped
                and existing.get("category") == category
            ):
                return existing
        entry_id = uuid.uuid4().hex[:12]
        now = int(time.time())
        entry = {
            "id": entry_id,
            "category": category,
            "subject": subject_stripped,
            "content": content_stripped,
            "tags": [t.strip().lower() for t in (tags or []) if t.strip()],
            "source": source,
            "provenance": (provenance or "").strip(),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "user_rating": max(0, min(5, int(user_rating))),
            "created": now,
            "updated": now,
            "hits": 0,
        }
        # Supersede dedup: when a higher-quality source stores a general entry
        # for a subject, evict any existing entity_explorer entry for the same
        # subject so both don't compete in retrieval.
        _SUPERSEDES = {"entity_narrator": {"entity_explorer"}}
        if subject_stripped and category == "general":
            evict_sources = _SUPERSEDES.get(source, set())
            if evict_sources:
                to_evict = [
                    eid for eid, e in self._entries.items()
                    if e.get("subject", "").strip() == subject_stripped
                    and e.get("source") in evict_sources
                    and e.get("category") == "general"
                ]
                for eid in to_evict:
                    del self._entries[eid]
        self._entries[entry_id] = entry
        if _save:
            await self._persist(invalidate_index=True)
        else:
            self._index_dirty = True
        return entry

    async def async_add_proposal(
        self,
        proposal_type: str,
        subject: str,
        content: str,
        pending_action: dict[str, Any],
        *,
        entity_name: str = "",
        area_name: str = "",
        label_name: str = "",
        source: str = "system",
        confidence: float = 0.9,
    ) -> dict[str, Any]:
        """Add a pending proposal (area or label assignment) to the review queue."""
        entry = await self.async_add(
            category="proposal",
            content=content,
            subject=subject,
            source=source,
            confidence=confidence,
            _save=False,
        )
        entry["needs_review"] = True
        entry["pending_action"] = pending_action
        entry["proposal_type"] = proposal_type
        if entity_name:
            entry["entity_name"] = entity_name
        if area_name:
            entry["area_name"] = area_name
        if label_name:
            entry["label_name"] = label_name
        entry["updated"] = int(time.time())
        await self._persist(invalidate_index=True)
        return entry

    async def async_force_save(self) -> None:
        """Flush pending in-memory entries to disk. Use after bulk async_add(_save=False) calls."""
        await self._persist(invalidate_index=False)

    async def async_update(self, entry_id: str, **changes: Any) -> dict[str, Any] | None:
        await self.async_load()
        entry = self._entries.get(entry_id)
        if not entry:
            return None
        allowed = {"category", "subject", "content", "tags", "confidence",
                   "source", "provenance", "user_rating"}
        index_fields = {"category", "subject", "content", "tags"}
        invalidate_index = False
        for k, v in changes.items():
            if k in allowed:
                if k == "confidence":
                    v = max(0.0, min(1.0, float(v)))
                elif k == "user_rating":
                    v = max(0, min(5, int(v)))
                if entry.get(k) != v and k in index_fields:
                    invalidate_index = True
                entry[k] = v
        entry["updated"] = int(time.time())
        await self._persist(invalidate_index=invalidate_index)
        return entry

    async def async_delete(self, entry_id: str) -> bool:
        await self.async_load()
        if entry_id in self._entries:
            del self._entries[entry_id]
            await self._persist(invalidate_index=True)
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
        exclude_low_quality: bool = True,
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
            if exclude_low_quality and "low_quality" in (entry.get("tags") or []):
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

    async def async_get_by_tag(
        self,
        tag: str,
        *,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all entries whose tags list contains *tag*.

        Optionally restrict to a specific *category*.  Useful for deterministic
        retrieval of pre-seeded entries (e.g. language hints) that should not
        depend on TF-IDF scoring.
        """
        await self.async_load()
        tag_lower = tag.lower()
        out = []
        for entry in self._entries.values():
            if category and entry.get("category") != category:
                continue
            if tag_lower in (t.lower() for t in (entry.get("tags") or [])):
                out.append(entry)
        return out

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
    def search_sync(self, query: str = "", category: str | None = None, subject: str = "", limit: int = 20, exclude_low_quality: bool = True) -> list[dict[str, Any]]:
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
            if exclude_low_quality and "low_quality" in (entry.get("tags") or []):
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

    async def async_pick_relevant(self, prompt: str, *, max_entries: int = 8, extra_queries: list[str] | None = None) -> list[dict[str, Any]]:
        """Pick entries relevant to a free-form prompt for context injection.

        Hybrid scoring: TF-IDF cosine similarity (semantic) + keyword overlap
        (legacy). Each entry gets a unified `_score` field used downstream
        (UI + debug snapshot). High-confidence area aliases are always kept
        as a safety net even when scores are low.

        extra_queries: additional search terms (e.g. from LLM query expansion)
        that are searched and merged alongside the main prompt. Allows
        cross-lingual and synonym matching ("koffie" → finds espresso entries).
        """
        await self.async_load()
        all_queries = [prompt] + [q for q in (extra_queries or []) if q and q != prompt]
        merged: dict[str, dict[str, Any]] = {}

        for q in all_queries:
            semantic = await self.async_semantic_search(q, limit=max_entries * 2)
            keyword = await self.async_search(q, limit=max_entries * 2)
            for e in semantic:
                score = float(e.get("_score", 0.0))
                existing = merged.get(e["id"])
                if existing:
                    if score > existing["_score"]:
                        existing["_score"] = score
                    existing["_source"] = "expanded"
                else:
                    merged[e["id"]] = {**e, "_score": score, "_source": "semantic"}
            for e in keyword:
                kw_score = 0.3
                existing = merged.get(e["id"])
                if existing:
                    existing["_score"] = max(existing["_score"], kw_score) + 0.05
                    existing["_source"] = "expanded"
                else:
                    merged[e["id"]] = {**e, "_score": kw_score, "_source": "keyword"}

        ranked = sorted(merged.values(), key=lambda x: x["_score"], reverse=True)

        # Subject-level dedup: when multiple entries describe the same entity,
        # keep the best one. Prefer entity_narrator > entity_explorer for the
        # same subject (narrator adds human-readable context; explorer is mostly
        # a structural fallback).
        _SOURCE_PRIORITY = {"entity_narrator": 0, "deep-analyzer": 1, "integration_explorer": 2,
                            "entity_explorer": 3}
        seen_subjects: dict[str, dict] = {}
        for entry in ranked:
            subj = (entry.get("subject") or "").strip().lower()
            if not subj:
                continue
            existing = seen_subjects.get(subj)
            if existing is None:
                seen_subjects[subj] = entry
            else:
                # Replace if this entry has higher source priority OR same priority + higher score
                my_pri = _SOURCE_PRIORITY.get(entry.get("source", ""), 99)
                ex_pri = _SOURCE_PRIORITY.get(existing.get("source", ""), 99)
                if my_pri < ex_pri or (my_pri == ex_pri and entry["_score"] > existing["_score"]):
                    seen_subjects[subj] = entry
        # Re-sort after subject dedup (order may change)
        deduped = sorted(seen_subjects.values(), key=lambda x: x["_score"], reverse=True)

        # Signal-word filter: if the query contains specific non-generic terms
        # (e.g. "espresso"), only keep entries that actually contain at least
        # one of those terms.  This prevents "espresso machine" from returning
        # "washing machine" entries that matched only on the generic word
        # "machine".  Entries with category "area_alias" are always kept —
        # they anchor the user's home geography regardless of query terms.
        signal = _query_signal_words(prompt)
        if signal:
            def _entry_has_signal(entry: dict[str, Any]) -> bool:
                if entry.get("category") == "area_alias":
                    return True
                blob = " ".join([
                    (entry.get("subject") or "").lower(),
                    (entry.get("content") or "").lower(),
                    " ".join(str(t).lower() for t in (entry.get("tags") or [])),
                ]).lower()
                return any(sw in blob for sw in signal)
            filtered = [e for e in deduped if _entry_has_signal(e)]
        else:
            filtered = deduped

        if filtered[:max_entries]:
            return filtered[:max_entries]
        # Fallback: always include high-confidence area aliases as background.
        aliases = await self.async_search("", category="area_alias", limit=max_entries)
        return [{**e, "_score": 0.0, "_source": "fallback_alias"} for e in aliases]


    async def async_purge_auto_generated(self) -> int:
        """Delete all entries created by the narrator and integration explorer.

        Called on version upgrade so stale AI-generated descriptions are wiped
        and rebuilt fresh with current filters and prompts.
        Returns number of entries deleted.
        """
        await self.async_load()
        auto_sources = {"entity_narrator", "integration_explorer", "dashboard_indexer"}
        to_delete = [
            eid for eid, entry in self._entries.items()
            if entry.get("source") in auto_sources
        ]
        for eid in to_delete:
            del self._entries[eid]
        if to_delete:
            await self._persist(invalidate_index=True)
            _LOGGER.info(
                "Kyber: purged %d auto-generated memory entries on schema upgrade",
                len(to_delete),
            )
        return len(to_delete)

    _DEDUP_CLEAN_SUBJECT = "_dedup_clean"

    async def async_dedup(self, *, schema_version: int = 0) -> int:
        """Remove exact duplicate entries (same subject+content+category).

        Keeps the entry with the highest confidence, then oldest created timestamp.
        Skips the scan entirely when a clean-marker entry is present for the
        current schema_version — avoids O(n) work on every HA restart once the
        store is already duplicate-free.  Returns number of entries removed.
        """
        await self.async_load()

        # Check for a stored clean-marker from a previous dedup run.
        if schema_version:
            for e in self._entries.values():
                if (e.get("subject") == self._DEDUP_CLEAN_SUBJECT
                        and e.get("source") == "system"
                        and e.get("content") == str(schema_version)):
                    _LOGGER.debug("Kyber: dedup skipped — store is clean for schema v%d", schema_version)
                    return 0

        seen: dict[tuple, str] = {}  # (subject, content, category) → winning entry_id
        to_delete: list[str] = []
        for eid, entry in self._entries.items():
            if entry.get("subject") == self._DEDUP_CLEAN_SUBJECT:
                continue  # skip the marker itself
            key = (
                (entry.get("subject") or "").strip().lower(),
                (entry.get("content") or "").strip().lower(),
                entry.get("category", "general"),
            )
            if key in seen:
                # Keep higher confidence; on tie keep older (lower created timestamp)
                winner_id = seen[key]
                winner = self._entries[winner_id]
                challenger_wins = (
                    entry.get("confidence", 1.0) > winner.get("confidence", 1.0)
                    or (
                        entry.get("confidence", 1.0) == winner.get("confidence", 1.0)
                        and entry.get("created", 0) < winner.get("created", 0)
                    )
                )
                if challenger_wins:
                    to_delete.append(winner_id)
                    seen[key] = eid
                else:
                    to_delete.append(eid)
            else:
                seen[key] = eid
        for eid in to_delete:
            self._entries.pop(eid, None)
        if to_delete:
            await self._persist(invalidate_index=True)
            _LOGGER.info("Kyber: dedup removed %d duplicate memory entries", len(to_delete))
        else:
            _LOGGER.debug("Kyber: dedup found no duplicates")

        # Write or update the clean-marker so the next startup can skip the scan.
        if schema_version:
            # Remove any stale marker first.
            stale = [k for k, e in self._entries.items()
                     if e.get("subject") == self._DEDUP_CLEAN_SUBJECT and e.get("source") == "system"]
            for k in stale:
                self._entries.pop(k, None)
            await self.async_add(
                "general",
                str(schema_version),
                subject=self._DEDUP_CLEAN_SUBJECT,
                source="system",
                confidence=1.0,
                _save=True,
            )
        return len(to_delete)


_INSTANCE_KEY = "kyber_knowledge_store"


def get_store(hass: HomeAssistant) -> KnowledgeStore:
    """Return a singleton store for this HA instance."""
    store = hass.data.get(_INSTANCE_KEY)
    if store is None:
        store = KnowledgeStore(hass)
        hass.data[_INSTANCE_KEY] = store
    return store


# Alias used by __init__.py and other modules that import by this name.
get_knowledge_store = get_store
