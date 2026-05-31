"""Knowledge base integration views/helpers extracted from http_api.py."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from .api_utilities import async_ai_call

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN, _sanitize_user_input
from .knowledge import CATEGORIES as KNOWLEDGE_CATEGORIES, get_store as get_knowledge_store
from . import deep_analyzer as _deep
from .analyzer import analyze_automations as _analyze_automations

_LOGGER = logging.getLogger(__name__)


def _sanitize_knowledge_payload(
    body: dict[str, Any], *, fields: tuple[str, ...]
) -> tuple[dict[str, Any], bool]:
    """Sanitize user-controlled knowledge fields and report whether anything changed."""
    sanitized = False
    updates: dict[str, Any] = {}

    for field in fields:
        if field not in body:
            continue
        if field == "tags":
            cleaned_tags: list[str] = []
            for tag in list(body.get("tags", []) or []):
                cleaned_tag, changed = _sanitize_user_input(str(tag))
                sanitized = sanitized or changed
                cleaned_tags.append(cleaned_tag)
            updates[field] = cleaned_tags
            continue

        cleaned_value, changed = _sanitize_user_input(str(body.get(field, "")))
        sanitized = sanitized or changed
        updates[field] = cleaned_value

    return updates, sanitized


def _request_user_context(request: web.Request) -> tuple[str | None, bool]:
    """Return the authenticated Home Assistant user id + admin flag."""
    ha_user = request.get("hass_user")
    return str(getattr(ha_user, "id", "") or "") or None, bool(getattr(ha_user, "is_admin", False))


# ── Background deep-analysis job state ───────────────────────────────────────
# Single-job tracker: only one deep analysis can run at a time.
_DEEP_JOB: dict[str, Any] = {
    "running": False,
    "run": 0,           # current pass index (1-based)
    "runs": 0,          # total passes requested
    "analyzed": 0,      # items sent to AI this job
    "facts": 0,         # facts stored this job
    "errors": 0,        # AI call errors this job
    "pending": 0,       # estimated items still in queue
    "current_item": None,
    "started_at": None,
    "finished_at": None,
    "last_result": None,  # summary dict of most recent completed job
}


async def _async_background_deep_analysis(
    hass: Any,
    ai_entity_id: str,
    runs: int,
    limit: int,
    force: bool,
    kinds: list[str],
) -> None:
    """Run deep analysis as a background task, updating _DEEP_JOB in place."""
    _DEEP_JOB.update(
        running=True, run=0, runs=runs, analyzed=0, facts=0, errors=0,
        pending=0, current_item=None, started_at=time.time(), finished_at=None,
    )
    try:
        for i in range(runs):
            _DEEP_JOB["run"] = i + 1
            result = await _deep.analyze_pending(
                hass,
                ai_entity_id=ai_entity_id,
                kinds=kinds,
                limit=limit,
                force=force,
                prompt_variant=i,
            )
            n_analyzed = len(result.get("analyzed", []))
            n_facts = sum(len(a.get("fact_ids", [])) for a in result.get("analyzed", []))
            n_errors = len(result.get("errors", []))
            _DEEP_JOB["analyzed"] += n_analyzed
            _DEEP_JOB["facts"] += n_facts
            _DEEP_JOB["errors"] += n_errors
            # Estimate remaining: candidates minus what's been processed so far
            total = result.get("candidates_total", 0)
            done_this_run = result.get("processed", 0) + result.get("skipped_unchanged", 0)
            _DEEP_JOB["pending"] = max(0, total - done_this_run)
            if result.get("analyzed"):
                last = result["analyzed"][-1]
                _DEEP_JOB["current_item"] = f"{last.get('kind','?')}: {last.get('ident','?')}"
            # Stop early when force=False and every item was skipped
            # (all lenses up to this pass have already been applied)
            if not force and result.get("processed", 0) == 0 and result.get("skipped_unchanged", 0) > 0:
                break
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber background deep analysis failed: %s", err)
        _DEEP_JOB["errors"] += 1
    finally:
        _DEEP_JOB["running"] = False
        _DEEP_JOB["finished_at"] = time.time()
        _DEEP_JOB["current_item"] = None
        _DEEP_JOB["last_result"] = {
            "analyzed": _DEEP_JOB["analyzed"],
            "facts": _DEEP_JOB["facts"],
            "errors": _DEEP_JOB["errors"],
            "runs_completed": _DEEP_JOB["run"],
            "duration_s": round(_DEEP_JOB["finished_at"] - (_DEEP_JOB["started_at"] or 0), 1),
        }
        _LOGGER.warning(
            "Kyber deep analysis complete — %d items analyzed, %d facts stored in %d passes",
            _DEEP_JOB["analyzed"], _DEEP_JOB["facts"], _DEEP_JOB["run"],
        )

# Mini prompt used for the post-turn fact-extraction LLM call.
# Kept intentionally tiny to be fast and not cost much context budget.
_FACT_EXTRACTION_PROMPT = """\
You are a fact extractor for a Home Assistant AI assistant.
Analyse the user message and conversation context for TWO types of learnable facts:

TYPE 1 — ALIAS: User equates two terms ("X en Y zijn hetzelfde", "X is my Y", "X and Y are the same").
Output: {{"type":"alias","subject":"<HA entity_id or area name>","user_term":"<colloquial word>",\
"content":"When user says '<user_term>' they mean '<subject>'.","category":"entity_alias",\
"tags":["<user_term>","<subject>"]}}

TYPE 2 — ROUTINE: User expresses a recurring time/context preference ("elke ochtend", "als ik wakker word",
"every morning", "next time I ...", "volgende keer als ...").
Output: {{"type":"routine","subject":"<short label e.g. morning coffee>",\
"content":"<when context> â†’ <action>","category":"routine","tags":["<context word>","<action word>"]}}

User said: "{user_prompt}"
Recent conversation context:
{context_snippet}

Return a JSON array of found facts, e.g. [{{}}, {{}}], or [] if nothing learnable.
Output ONLY valid JSON — no prose, no markdown fences.
"""

async def _try_extract_learned_facts(
    hass: HomeAssistant,
    entity_id: str,
    user_prompt: str,
    context_snippet: str,
) -> list[dict[str, Any]]:
    """Run a mini LLM call to extract learnable facts from a correction/routine turn.

    Returns a list of fact dicts (may be empty).  Each dict has keys:
    subject, user_term, content, category, tags.
    Failures are silently swallowed; this is best-effort.
    """
    import json as _json
    try:
        prompt = _FACT_EXTRACTION_PROMPT.format(
            user_prompt=user_prompt[:200],
            context_snippet=context_snippet[-400:],
        )
        result = await async_ai_call(
            hass,
            task_name=f"{DOMAIN}_fact_extract",
            entity_id=entity_id,
            instructions=prompt,
        )
        raw = result.data if isinstance(result.data, str) else str(result.data)
        raw = raw.strip()
        raw = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.IGNORECASE)
        raw = raw.strip()
        if not raw or raw.lower() in ("null", "[]"):
            return []
        parsed = _json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []
        facts: list[dict[str, Any]] = []
        for item in parsed:
            subject = (item.get("subject") or item.get("user_term") or "").strip()
            content = (item.get("content") or "").strip()
            if not subject or not content:
                continue
            facts.append({
                "subject": subject,
                "user_term": (item.get("user_term") or subject).strip(),
                "content": content,
                "category": item.get("category", "entity_alias"),
                "tags": item.get("tags", [subject]),
            })
        return facts
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber: fact extraction failed (non-critical): %s", err)
        return []


# Keep backward-compat alias used by tests
async def _try_extract_learned_fact(
    hass: HomeAssistant,
    entity_id: str,
    user_prompt: str,
    context_snippet: str,
) -> dict[str, Any] | None:
    """Legacy single-fact wrapper — returns first extracted fact or None."""
    facts = await _try_extract_learned_facts(hass, entity_id, user_prompt, context_snippet)
    return facts[0] if facts else None


class KyberKnowledgeView(HomeAssistantView):
    """CRUD endpoint for learned knowledge entries.

    GET    /api/kyber/knowledge            â†’ list all
    GET    /api/kyber/knowledge?q=...      â†’ search
    POST   /api/kyber/knowledge            â†’ add (body: category, content, ...)
    DELETE /api/kyber/knowledge?id=ENTRYID â†’ delete
    """

    url = "/api/kyber/knowledge"
    name = "api:kyber:knowledge"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        user_id, is_admin = _request_user_context(request)
        q = request.query.get("q", "").strip()
        category = request.query.get("category", "").strip() or None
        subject = request.query.get("subject", "").strip()
        try:
            limit = max(1, min(500, int(request.query.get("limit", "200"))))
        except ValueError:
            limit = 200
        if q or category or subject:
            entries = await kstore.async_search(
                query=q,
                category=category,
                subject=subject,
                limit=limit,
                user_id=user_id,
                is_admin=is_admin,
            )
        else:
            entries = await kstore.async_list_knowledge(user_id=user_id, is_admin=is_admin)
        needs_review = request.query.get("needs_review", "").strip().lower()
        if needs_review in ("1", "true", "yes"):
            entries = [e for e in entries if e.get("needs_review")]
        visible_entries = await kstore.async_all(user_id=user_id, is_admin=is_admin)
        return self.json({
            "entries": entries,
            "count": len(entries),
            "categories": sorted(KNOWLEDGE_CATEGORIES),
            "needs_review_count": sum(1 for e in visible_entries if e.get("needs_review")),
        })

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        user_id, _is_admin = _request_user_context(request)
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
            sanitized_changes, was_sanitized = _sanitize_knowledge_payload(
                body,
                fields=("subject", "content", "tags"),
            )
            if was_sanitized:
                return self.json_message(
                    "Knowledge input contains disallowed prompt-injection content",
                    HTTPStatus.BAD_REQUEST,
                )
            changes.update(sanitized_changes)
            try:
                updated = await kstore.async_update(str(entry_id), **changes)
            except ValueError as err:
                if str(err) == "Credential pattern detected in content":
                    return self.json({"error": "Content contains credential pattern"}, status_code=HTTPStatus.BAD_REQUEST)
                raise
            if not updated:
                return self.json_message(f"Entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
            return self.json({"status": "ok", "entry": updated})
        sanitized_fields, was_sanitized = _sanitize_knowledge_payload(
            body,
            fields=("subject", "content", "tags"),
        )
        if was_sanitized:
            return self.json_message(
                "Knowledge input contains disallowed prompt-injection content",
                HTTPStatus.BAD_REQUEST,
            )
        content = str(sanitized_fields.get("content", body.get("content", ""))).strip()
        if not content:
            return self.json_message("Missing 'content' field", HTTPStatus.BAD_REQUEST)
        try:
            entry = await kstore.async_add(
                category=str(body.get("category", "general")),
                content=content,
                subject=str(sanitized_fields.get("subject", body.get("subject", ""))),
                tags=list(sanitized_fields.get("tags", body.get("tags", []) or [])),
                source=str(body.get("source", "user")),
                confidence=float(body.get("confidence", 1.0)),
                provenance=str(body.get("provenance", "Added manually by user")),
                user_rating=int(body.get("user_rating", 0)),
                owner_id=user_id if body.get("personal") else None,
            )
        except ValueError as err:
            if str(err) == "Credential pattern detected in content":
                return self.json({"error": "Content contains credential pattern"}, status_code=HTTPStatus.BAD_REQUEST)
            raise
        return self.json({"status": "ok", "entry": entry})

    async def delete(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        user_id, is_admin = _request_user_context(request)
        entry_id = request.query.get("id", "").strip()
        if not entry_id:
            return self.json_message("Missing 'id' query parameter", HTTPStatus.BAD_REQUEST)
        entry = await kstore.async_get(entry_id)
        if entry is None:
            return self.json_message(f"Entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
        ok = await kstore.async_delete(
            entry_id,
            requesting_user_id=user_id,
            is_admin=is_admin,
        )
        if not ok:
            return self.json_message("Not allowed to delete this knowledge entry", HTTPStatus.FORBIDDEN)
        return self.json({"status": "ok"})


class KyberKnowledgeEntryView(HomeAssistantView):
    """Operate on a single knowledge entry."""

    url = "/api/kyber/knowledge/{entry_id}"
    name = "api:kyber:knowledge:entry"
    requires_auth = True

    async def delete(self, request: web.Request, entry_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        user_id, is_admin = _request_user_context(request)
        entry = await kstore.async_get(entry_id)
        if entry is None:
            return self.json_message(f"Entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
        ok = await kstore.async_delete(
            entry_id,
            requesting_user_id=user_id,
            is_admin=is_admin,
        )
        if not ok:
            return self.json_message("Not allowed to delete this knowledge entry", HTTPStatus.FORBIDDEN)
        return self.json({"status": "ok"})


class KyberKnowledgeAnalyzeView(HomeAssistantView):
    """Run the automation/scene/script analyzer and return inferred proposals.

    GET  /api/kyber/knowledge/analyze         â†’ return proposals (not saved)
    POST /api/kyber/knowledge/analyze         â†’ body: {entry_indices: [...], save: true}
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
            try:
                entry = await kstore.async_add(
                    category=str(p.get("category", "general")),
                    content=str(p.get("content", "")),
                    subject=str(p.get("subject", "")),
                    tags=list(p.get("tags", []) or []),
                    source=str(p.get("source", "inferred")),
                    confidence=float(p.get("confidence", 0.5)),
                    provenance=str(p.get("provenance", "Inferred from automation/scene/script analysis")),
                )
            except ValueError as err:
                if str(err) == "Credential pattern detected in content":
                    return self.json({"error": "Content contains credential pattern"}, status_code=HTTPStatus.BAD_REQUEST)
                raise
            saved.append(entry["id"])
        return self.json({"status": "ok", "saved": saved, "count": len(saved)})


class KyberKnowledgeDeepAnalyzeView(HomeAssistantView):
    """AI-driven deep analyzer for automations / scripts / blueprints.

    Each item is hashed; unchanged items are skipped. Up to `limit` changed
    items are sent to the AI per run, which proposes durable facts about
    the home that the item implies. Accepted facts are saved into the
    KnowledgeStore tagged with `deep:<kind>` + `src:<ident>`.

    GET  /api/kyber/knowledge/analyze_deep        â†’ memo status (what's been analyzed)
    POST /api/kyber/knowledge/analyze_deep        â†’ run a sweep
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
        memo_status = await _deep.memo_status(hass)
        return self.json({**memo_status, "job": dict(_DEEP_JOB)})

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

        # background=true â†’ fire-and-forget, return immediately with job state
        if body.get("background"):
            if _DEEP_JOB["running"]:
                return self.json({"status": "already_running", "job": dict(_DEEP_JOB)})
            try:
                runs = max(1, min(50, int(body.get("runs", 10))))
            except (TypeError, ValueError):
                runs = 10
            hass.async_create_task(
                _async_background_deep_analysis(hass, ai_entity_id, runs, limit, force, kinds)
            )
            await asyncio.sleep(0.05)  # let the task start and update state
            return self.json({"status": "started", "job": dict(_DEEP_JOB)})

        # synchronous (legacy) path
        try:
            result = await _deep.analyze_pending(
                hass,
                ai_entity_id=ai_entity_id,
                kinds=kinds,
                limit=limit,
                force=force,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Kyber deep_analyzer: unexpected error")
            return self.json_message("Internal error", HTTPStatus.INTERNAL_SERVER_ERROR)
        try:
            return self.json({"status": "ok", **result})
        except Exception as ser_err:  # noqa: BLE001
            _LOGGER.error("Kyber deep_analyzer: JSON serialization failed: %s", ser_err, exc_info=True)
            return self.json({
                "status": "ok",
                "analyzed": [],
                "skipped_unchanged": result.get("skipped_unchanged", 0),
                "errors": [{"kind": "?", "ident": "?", "error": f"serialization error: {ser_err}"}],
                "candidates_total": result.get("candidates_total", 0),
                "processed": result.get("processed", 0),
                "limit": result.get("limit", limit),
            })


class KyberKnowledgePurgeView(HomeAssistantView):
    """Bulk-delete knowledge entries by ID.

    POST /api/kyber/knowledge/purge
      body: {ids: [entry_id, ...]}
      response: {deleted: N, not_found: N}
    """

    url = "/api/kyber/knowledge/purge"
    name = "api:kyber:knowledge:purge"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        _user_id, is_admin = _request_user_context(request)
        if not is_admin:
            return self.json_message("Administrator access required", HTTPStatus.FORBIDDEN)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids:
            return self.json_message("'ids' must be a non-empty list", HTTPStatus.BAD_REQUEST)
        deleted = 0
        not_found = 0
        for entry_id in ids:
            ok = await kstore.async_delete(str(entry_id), is_admin=True)
            if ok:
                deleted += 1
            else:
                not_found += 1
        _LOGGER.info("Kyber knowledge purge: deleted %d, not found %d", deleted, not_found)
        return self.json({"status": "ok", "deleted": deleted, "not_found": not_found})


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


# â”€â”€ Status accessor for _DEEP_JOB (used by debug status view) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_deep_job_status() -> dict:
    """Return a copy of the current deep analysis job state."""
    return dict(_DEEP_JOB)


class KyberNarratorRunView(HomeAssistantView):
    """Manually trigger a background narrator run.

    POST /api/kyber/narrator/run
      body: {} (no required fields)
      response: {status: "started"|"already_running"|"disabled"}
    """

    url = "/api/kyber/narrator/run"
    name = "api:kyber:narrator:run"
    requires_auth = True

    def __init__(self, config: dict) -> None:
        self._config = config

    async def post(self, request: web.Request) -> web.Response:
        import asyncio as _asyncio
        from homeassistant.helpers import entity_registry as er
        from .entity_narrator import async_narrate_entities
        from .const import (
            CONF_NARRATOR_ENABLED, CONF_NARRATOR_AI_TASK_ENTITY_ID,
            CONF_NARRATOR_MAX_BATCH, CONF_NARRATOR_MAX_TOKENS,
            DEFAULT_NARRATOR_ENABLED, DEFAULT_NARRATOR_MAX_BATCH,
            DEFAULT_NARRATOR_MAX_TOKENS,
        )
        hass: HomeAssistant = request.app["hass"]

        narrator_enabled = bool(self._config.get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED))
        if not narrator_enabled:
            return self.json({"status": "disabled", "reason": "Narrator is disabled in settings"})

        narrator_lock = hass.data.get("kyber_narrator_lock")
        if narrator_lock and narrator_lock.locked():
            return self.json({"status": "already_running"})

        ai_entity_id = (
            str(self._config.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")).strip()
            or str(self._config.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
        )
        if not ai_entity_id:
            return self.json_message("AI task entity not configured", HTTPStatus.SERVICE_UNAVAILABLE)

        max_batch = int(self._config.get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH))
        narrator_max_tokens = int(self._config.get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS))
        kstore = get_knowledge_store(hass)
        entity_reg = er.async_get(hass)

        async def _run_narrator() -> None:
            if narrator_lock:
                async with narrator_lock:
                    await async_narrate_entities(
                        hass, kstore, entity_reg, ai_entity_id,
                        max_batch=max_batch,
                        narrator_max_tokens=narrator_max_tokens,
                    )
            else:
                await async_narrate_entities(
                    hass, kstore, entity_reg, ai_entity_id,
                    max_batch=max_batch,
                    narrator_max_tokens=narrator_max_tokens,
                )

        hass.async_create_task(_run_narrator())
        await _asyncio.sleep(0.05)
        return self.json({"status": "started"})


class KyberExplorerRunView(HomeAssistantView):
    """Manually trigger a background integration explorer run.

    POST /api/kyber/explorer/run
      body: {} (no required fields)
      response: {status: "started"|"already_running"}
    """

    url = "/api/kyber/explorer/run"
    name = "api:kyber:explorer:run"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        import asyncio as _asyncio
        from homeassistant.helpers import entity_registry as er
        from .integration_explorer import async_startup_explore_all
        from .dashboard_indexer import async_index_dashboard_entities, get_dashboard_entity_names, async_store_dashboard_labels
        hass: HomeAssistant = request.app["hass"]

        explorer_lock = hass.data.setdefault("kyber_explorer_lock", _asyncio.Lock())
        if explorer_lock.locked():
            return self.json({"status": "already_running"})

        kstore = get_knowledge_store(hass)
        entity_reg = er.async_get(hass)

        async def _run_explorer() -> None:
            async with explorer_lock:
                try:
                    await kstore.async_load()
                    count = await async_startup_explore_all(hass, kstore, entity_reg)
                    _LOGGER.info("Kyber manual explorer: stored facts for %d integrations", count)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Kyber manual explorer failed: %s", err)
                try:
                    await async_index_dashboard_entities(hass)
                    dashboard_names = get_dashboard_entity_names(hass)
                    label_count = await async_store_dashboard_labels(hass, kstore)
                    _LOGGER.info("Kyber manual explorer: dashboard indexer found %d entities, stored %d labels", len(dashboard_names), label_count)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Kyber manual explorer dashboard indexer failed: %s", err)

        hass.async_create_task(_run_explorer())
        await _asyncio.sleep(0.05)
        return self.json({"status": "started"})

