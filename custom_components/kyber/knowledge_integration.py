"""Knowledge base integration views/helpers extracted from http_api.py."""
from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.ai_task import async_generate_data
except ImportError:  # HA < 2025.2 (test environments)
    async def async_generate_data(*args, **kwargs):  # type: ignore[misc]
        raise RuntimeError("homeassistant.components.ai_task not available (HA < 2025.2)")

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN
from .knowledge import CATEGORIES as KNOWLEDGE_CATEGORIES, get_store as get_knowledge_store
from . import deep_analyzer as _deep
from .analyzer import analyze_automations as _analyze_automations

_LOGGER = logging.getLogger(__name__)

# Mini prompt used for the post-turn fact-extraction LLM call.
# Kept intentionally tiny to be fast and not cost much context budget.
_FACT_EXTRACTION_PROMPT = """\
You are a fact extractor for a Home Assistant assistant.
Given a user correction, extract ONE name alias mapping — what the user calls something \
vs what it is named in Home Assistant.

User said: "{user_prompt}"
Recent conversation context:
{context_snippet}

If you can identify a clear name mismatch, output ONLY a JSON object (no extra text):
{{"subject": "<HA name>", "user_term": "<user word>", \
"content": "When user says '<user word>' they mean '<HA name>'.", \
"category": "area_alias", "tags": ["<user word>", "<HA name>"]}}

If there is no clear mismatch to learn, output: null
"""

async def _try_extract_learned_fact(
    hass: HomeAssistant,
    entity_id: str,
    user_prompt: str,
    context_snippet: str,
) -> dict[str, Any] | None:
    """Run a mini LLM call to extract a learned name alias from a correction turn.

    Returns a dict with keys subject, user_term, content, category, tags — or None.
    Failures are silently swallowed; this is a best-effort enhancement.
    """
    import json as _json
    try:
        prompt = _FACT_EXTRACTION_PROMPT.format(
            user_prompt=user_prompt[:200],
            context_snippet=context_snippet[-400:],
        )
        result = await async_generate_data(
            hass,
            task_name=f"{DOMAIN}_fact_extract",
            entity_id=entity_id,
            instructions=prompt,
        )
        raw = result.data if isinstance(result.data, str) else str(result.data)
        raw = raw.strip()
        # Strip common model wrappers (```json ... ```, ```...```)
        raw = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.IGNORECASE)
        raw = raw.strip()
        if raw.lower() == "null" or not raw.startswith("{"):
            return None
        data = _json.loads(raw)
        subject = data.get("subject", "").strip()
        user_term = data.get("user_term", "").strip()
        content = data.get("content", "").strip()
        if not subject or not user_term or not content:
            return None
        return {
            "subject": subject,
            "user_term": user_term,
            "content": content,
            "category": data.get("category", "area_alias"),
            "tags": data.get("tags", [user_term, subject]),
        }
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber: fact extraction failed (non-critical): %s", err)
        return None


class KyberKnowledgeView(HomeAssistantView):
    """CRUD endpoint for learned knowledge entries.

    GET    /api/kyber/knowledge            → list all
    GET    /api/kyber/knowledge?q=...      → search
    POST   /api/kyber/knowledge            → add (body: category, content, ...)
    DELETE /api/kyber/knowledge?id=ENTRYID → delete
    """

    url = "/api/kyber/knowledge"
    name = "api:kyber:knowledge"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        q = request.query.get("q", "").strip()
        category = request.query.get("category", "").strip() or None
        subject = request.query.get("subject", "").strip()
        try:
            limit = max(1, min(500, int(request.query.get("limit", "200"))))
        except ValueError:
            limit = 200
        if q or category or subject:
            entries = await kstore.async_search(query=q, category=category, subject=subject, limit=limit)
        else:
            entries = await kstore.async_all()
        needs_review = request.query.get("needs_review", "").strip().lower()
        if needs_review in ("1", "true", "yes"):
            entries = [e for e in entries if e.get("needs_review")]
        return self.json({
            "entries": entries,
            "count": len(entries),
            "categories": sorted(KNOWLEDGE_CATEGORIES),
            "needs_review_count": sum(1 for e in await kstore.async_all() if e.get("needs_review")),
        })

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        # Update vs create
        entry_id = body.get("id") or body.get("entry_id")
        if entry_id:
            # Rating-only update is allowed even without content
            changes = {k: v for k, v in body.items()
                       if k in ("category", "subject", "content", "tags",
                                "confidence", "source", "provenance",
                                "user_rating", "needs_review")}
            updated = await kstore.async_update(str(entry_id), **changes)
            if not updated:
                return self.json_message(f"Entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
            return self.json({"status": "ok", "entry": updated})
        content = str(body.get("content", "")).strip()
        if not content:
            return self.json_message("Missing 'content' field", HTTPStatus.BAD_REQUEST)
        entry = await kstore.async_add(
            category=str(body.get("category", "general")),
            content=content,
            subject=str(body.get("subject", "")),
            tags=list(body.get("tags", []) or []),
            source=str(body.get("source", "user")),
            confidence=float(body.get("confidence", 1.0)),
            provenance=str(body.get("provenance", "Added manually by user")),
            user_rating=int(body.get("user_rating", 0)),
        )
        return self.json({"status": "ok", "entry": entry})

    async def delete(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        entry_id = request.query.get("id", "").strip()
        if not entry_id:
            return self.json_message("Missing 'id' query parameter", HTTPStatus.BAD_REQUEST)
        ok = await kstore.async_delete(entry_id)
        if not ok:
            return self.json_message(f"Entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
        return self.json({"status": "ok"})


class KyberKnowledgeAnalyzeView(HomeAssistantView):
    """Run the automation/scene/script analyzer and return inferred proposals.

    GET  /api/kyber/knowledge/analyze         → return proposals (not saved)
    POST /api/kyber/knowledge/analyze         → body: {entry_indices: [...], save: true}
                                                save selected proposals
    """

    url = "/api/kyber/knowledge/analyze"
    name = "api:kyber:knowledge:analyze"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        result = _analyze_automations(hass)
        return self.json(result)

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        proposals = body.get("proposals") or []
        if not isinstance(proposals, list):
            return self.json_message("Field 'proposals' must be a list", HTTPStatus.BAD_REQUEST)
        saved = []
        for p in proposals:
            if not isinstance(p, dict) or not p.get("content"):
                continue
            entry = await kstore.async_add(
                category=str(p.get("category", "general")),
                content=str(p.get("content", "")),
                subject=str(p.get("subject", "")),
                tags=list(p.get("tags", []) or []),
                source=str(p.get("source", "inferred")),
                confidence=float(p.get("confidence", 0.5)),
                provenance=str(p.get("provenance", "Inferred from automation/scene/script analysis")),
            )
            saved.append(entry["id"])
        return self.json({"status": "ok", "saved": saved, "count": len(saved)})


class KyberKnowledgeDeepAnalyzeView(HomeAssistantView):
    """AI-driven deep analyzer for automations / scripts / blueprints.

    Each item is hashed; unchanged items are skipped. Up to `limit` changed
    items are sent to the AI per run, which proposes durable facts about
    the home that the item implies. Accepted facts are saved into the
    KnowledgeStore tagged with `deep:<kind>` + `src:<ident>`.

    GET  /api/kyber/knowledge/analyze_deep        → memo status (what's been analyzed)
    POST /api/kyber/knowledge/analyze_deep        → run a sweep
       body: {kinds?: ["automation","script","blueprint"],
              limit?: int = 5,
              force?: bool = false}
    """

    url = "/api/kyber/knowledge/analyze_deep"
    name = "api:kyber:knowledge:analyze_deep"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        status = await _deep.memo_status(hass)
        return self.json(status)

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        ai_entity_id: str = self._config.get(CONF_AI_TASK_ENTITY_ID, "")
        if not ai_entity_id:
            return self.json_message("AI task entity not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        kinds = body.get("kinds") or ["automation", "script", "blueprint"]
        if not isinstance(kinds, list):
            kinds = ["automation", "script", "blueprint"]
        try:
            limit = int(body.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(50, limit))
        force = bool(body.get("force", False))
        try:
            result = await _deep.analyze_pending(
                hass,
                ai_entity_id=ai_entity_id,
                kinds=kinds,
                limit=limit,
                force=force,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Kyber deep_analyzer: unexpected error: %s", err, exc_info=True)
            return self.json_message(f"Deep analyze error: {err}", HTTPStatus.INTERNAL_SERVER_ERROR)
        try:
            return self.json({"status": "ok", **result})
        except Exception as ser_err:  # noqa: BLE001
            _LOGGER.error("Kyber deep_analyzer: JSON serialization failed: %s", ser_err, exc_info=True)
            # Return a safe minimal response so the frontend doesn't get a 500 text body
            return self.json({
                "status": "ok",
                "analyzed": [],
                "skipped_unchanged": result.get("skipped_unchanged", 0),
                "errors": [{"kind": "?", "ident": "?", "error": f"serialization error: {ser_err}"}],
                "candidates_total": result.get("candidates_total", 0),
                "processed": result.get("processed", 0),
                "limit": result.get("limit", limit),
            })


class KyberKnowledgeFeedbackView(HomeAssistantView):
    """Record user (or auto) feedback on a chat response, applied to the
    knowledge entries that were injected into that turn's context.

    POST /api/kyber/knowledge/feedback
      body: {rating: 1-5, knowledge_ids: [...], notes?, auto?}
    """

    url = "/api/kyber/knowledge/feedback"
    name = "api:kyber:knowledge:feedback"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        try:
            rating = int(body.get("rating", 0))
        except (TypeError, ValueError):
            return self.json_message("'rating' must be 1-5", HTTPStatus.BAD_REQUEST)
        if rating < 1 or rating > 5:
            return self.json_message("'rating' must be 1-5", HTTPStatus.BAD_REQUEST)
        ids = body.get("knowledge_ids") or []
        if not isinstance(ids, list):
            return self.json_message("'knowledge_ids' must be a list", HTTPStatus.BAD_REQUEST)
        notes = str(body.get("notes", ""))[:200]
        auto = bool(body.get("auto", False))
        updated = await kstore.async_apply_feedback(
            [str(i) for i in ids if i],
            rating=rating,
            notes=notes,
            auto=auto,
        )
        return self.json({
            "status": "ok",
            "updated": [e["id"] for e in updated],
            "count": len(updated),
        })
