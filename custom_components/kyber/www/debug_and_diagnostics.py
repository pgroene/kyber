"""Debug and diagnostics views/helpers extracted from http_api.py."""
from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CONF_AI_TASK_ENTITY_ID, CONF_MAX_DAILY_TOKENS, DOMAIN, _redact_secrets
from .knowledge import get_store as get_knowledge_store
from .token_budget import get_budget_provider, get_store as get_token_budget_store
from .entity_narrator import NARRATOR_STATS_KEY
from .knowledge_integration import get_deep_job_status as _get_deep_job_status
from .api_utilities import async_ai_call

_LOGGER = logging.getLogger(__name__)

# Read manifest version once at import time (safe: not inside event loop)
try:
    import os as _os
    _KYBER_VERSION: str = json.loads(
        open(_os.path.join(_os.path.dirname(__file__), "manifest.json"), encoding="utf-8").read()
    ).get("version", "unknown")
except Exception:  # noqa: BLE001
    _KYBER_VERSION = "unknown"

# Redefine debug constants (same values as http_api.py — both files have them)
_DEBUG_MODE_KEY = "kyber_debug_mode"
_DEBUG_MODE_DEFAULT = True

_DEBUG_LAST_TURN_KEY = "kyber_debug_last_turn"
_DEBUG_SNAPSHOTS_KEY = "kyber_debug_snapshots"
_DEBUG_SNAPSHOTS_MAX = 50
_DEBUG_TOOL_HISTORY_KEY = "kyber_debug_tool_history"
_DEBUG_TOOL_HISTORY_MAX = 20
_DEBUG_LOG_CAPTURE_KEY = "kyber_debug_log_capture"
_DEBUG_LOG_CAPTURE_MAX_PER_TURN = 500

# Key for background explorer progress (written by integration_explorer.py)
EXPLORER_PROGRESS_KEY = "kyber_explorer_progress"

_KYBER_GLOBAL_LOG_KEY = "kyber_global_logs"
_KYBER_GLOBAL_LOG_MAX = 2000  # keep last 2000 records


def _get_debug_mode(hass: HomeAssistant) -> bool:
    val = hass.data.get(_DEBUG_MODE_KEY)
    if val is None:
        return _DEBUG_MODE_DEFAULT
    return bool(val)


def _admin_required(view: HomeAssistantView, request: web.Request) -> web.Response | None:
    """Return a 403 response when the request is not from an admin user."""
    ha_user = request.get("hass_user")
    if not ha_user or not getattr(ha_user, "is_admin", False):
        return view.json_message("Admin required", HTTPStatus.FORBIDDEN)
    return None


class _KyberTurnLogHandler(logging.Handler):
    """Logging handler that captures kyber.* records for a single turn."""

    def __init__(self, sink: list[dict]) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            name = record.name or ""
            if not (name.startswith("custom_components.kyber") or name.startswith("kyber")):
                return
            if len(self._sink) >= _DEBUG_LOG_CAPTURE_MAX_PER_TURN:
                return
            self._sink.append({
                "ts": record.created,
                "level": record.levelname,
                "logger": name,
                "message": record.getMessage(),
            })
        except Exception:  # noqa: BLE001
            pass


class KyberGlobalLogHandler(logging.Handler):
    """Persistent logging handler: captures all kyber.* records into hass.data ring buffer.

    Installed once at async_setup_entry; stores logs in
    hass.data[_KYBER_GLOBAL_LOG_KEY] as a list (newest appended, oldest evicted).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(level=logging.DEBUG)
        self._hass = hass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            name = record.name or ""
            if not (name.startswith("custom_components.kyber") or name.startswith("kyber")):
                return
            buf: list = self._hass.data.setdefault(_KYBER_GLOBAL_LOG_KEY, [])
            buf.append({
                "ts": record.created,
                "level": record.levelname,
                "logger": name.replace("custom_components.kyber.", "kyber.").replace("custom_components.kyber", "kyber"),
                "message": record.getMessage(),
            })
            # Evict oldest when over limit
            if len(buf) > _KYBER_GLOBAL_LOG_MAX:
                del buf[: len(buf) - _KYBER_GLOBAL_LOG_MAX]
        except Exception:  # noqa: BLE001
            pass


def _debug_attach_log_capture(request_id: str) -> tuple[list[dict], _KyberTurnLogHandler] | tuple[None, None]:
    """Attach a per-turn log handler to the root logger; returns (sink, handler) or (None, None)."""
    if not request_id:
        return None, None
    try:
        sink: list[dict] = []
        handler = _KyberTurnLogHandler(sink)
        logging.getLogger().addHandler(handler)
        return sink, handler
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber: failed to attach per-turn log capture: %s", err)
        return None, None


def _debug_detach_log_capture(handler: _KyberTurnLogHandler | None) -> None:
    if handler is None:
        return
    try:
        logging.getLogger().removeHandler(handler)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Kyber: failed to detach per-turn log capture: %s", err)


def _debug_record_turn(
    hass: HomeAssistant,
    *,
    request_id: str,
    user_prompt: str,
    expanded_prompt: str,
    instructions_used: str,
    picked_knowledge: list[dict],
    tool_log: list[dict],
    intent: str | None,
    response_text: str,
    plan_block: dict | None,
    auto_rating: int | None,
    elapsed_ms: int,
    logs: list[dict] | None = None,
    progress_events: list[dict] | None = None,
    session_meta: dict | None = None,
) -> None:
    """Capture a per-turn debug snapshot. Single slot + ring buffer + per-request_id map."""
    import time
    snapshot = {
        "request_id": request_id,
        "ts": int(time.time()),
        "user_prompt": user_prompt,
        "expanded_prompt": expanded_prompt[:32000],
        "instructions_used": instructions_used[:32000],
        "picked_knowledge": picked_knowledge,
        "tool_log": tool_log,
        "intent": intent,
        "response_text": (response_text or "")[:8000],
        "plan_block": plan_block,
        "auto_rating": auto_rating,
        "elapsed_ms": elapsed_ms,
        "char_count": len(expanded_prompt),
        "approx_tokens": len(expanded_prompt) // 4,
        "logs": logs or [],
        "progress_events": progress_events or [],
        "session_meta": session_meta or {},
    }
    hass.data[_DEBUG_LAST_TURN_KEY] = snapshot
    # Per-request_id map (newest wins, evict oldest beyond max).
    from collections import OrderedDict, deque
    snaps = hass.data.get(_DEBUG_SNAPSHOTS_KEY)
    if not isinstance(snaps, OrderedDict):
        snaps = OrderedDict()
        hass.data[_DEBUG_SNAPSHOTS_KEY] = snaps
    if request_id:
        snaps[request_id] = snapshot
        while len(snaps) > _DEBUG_SNAPSHOTS_MAX:
            snaps.popitem(last=False)
    # Tool ring buffer
    history = hass.data.get(_DEBUG_TOOL_HISTORY_KEY)
    if not isinstance(history, deque):
        history = deque(maxlen=_DEBUG_TOOL_HISTORY_MAX)
        hass.data[_DEBUG_TOOL_HISTORY_KEY] = history
    for entry in tool_log or []:
        history.append({
            "ts": snapshot["ts"],
            "request_id": request_id,
            **entry,
        })


class KyberDebugLastTurnView(HomeAssistantView):
    """Return the most recent turn's debug snapshot (in-memory only).

    GET /api/kyber/debug/last_turn → {prompt, picked_knowledge, tool_log, ...}
    """

    url = "/api/kyber/debug/last_turn"
    name = "api:kyber:debug:last_turn"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        hass: HomeAssistant = request.app["hass"]
        snap = hass.data.get(_DEBUG_LAST_TURN_KEY)
        if not snap:
            return self.json({"snapshot": None})
        return self.json({"snapshot": snap})


class KyberDebugToolHistoryView(HomeAssistantView):
    """Return the in-memory ring buffer of recent tool calls."""

    url = "/api/kyber/debug/tool_history"
    name = "api:kyber:debug:tool_history"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        history = hass.data.get(_DEBUG_TOOL_HISTORY_KEY)
        try:
            limit = max(1, min(_DEBUG_TOOL_HISTORY_MAX, int(request.query.get("limit", _DEBUG_TOOL_HISTORY_MAX))))
        except ValueError:
            limit = _DEBUG_TOOL_HISTORY_MAX
        items = list(history)[-limit:] if history else []
        return self.json({"items": items, "count": len(items), "max": _DEBUG_TOOL_HISTORY_MAX})


class KyberDebugStatusView(HomeAssistantView):
    """Runtime status: model, autopilot, session, store stats."""

    url = "/api/kyber/debug/status"
    name = "api:kyber:debug:status"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        import os as _os
        hass: HomeAssistant = request.app["hass"]
        kstore = get_knowledge_store(hass)
        await kstore.async_load()
        all_entries = await kstore.async_all()
        cat_counts: dict[str, int] = {}
        flagged = 0
        total_hits = 0
        for e in all_entries:
            cat_counts[e.get("category", "general")] = cat_counts.get(e.get("category", "general"), 0) + 1
            if e.get("needs_review"):
                flagged += 1
            total_hits += int(e.get("hits", 0) or 0)
        snap = hass.data.get(_DEBUG_LAST_TURN_KEY)
        ai_task_entity = str(hass.data.get("kyber_ai_task_entity", ""))
        narrator_ai_task_entity = str(hass.data.get("kyber_narrator_ai_task_entity", ""))
        config = dict(hass.data.get("kyber_config", {}))
        budget_provider = get_budget_provider(config)
        token_budget = int(config.get(CONF_MAX_DAILY_TOKENS, 0) or 0)
        token_usage = await get_token_budget_store(hass).async_get_usage(budget_provider, token_budget)

        def _entity_info(entity_id: str) -> dict:
            """Return display name, model, and server URL for an ai_task entity."""
            if not entity_id:
                return {}
            state = hass.states.get(entity_id)
            if not state:
                return {"entity_id": entity_id}
            attrs = dict(state.attributes)
            model = attrs.get("model_id") or attrs.get("model") or attrs.get("model_name") or ""
            server = attrs.get("url") or attrs.get("base_url") or attrs.get("host") or ""
            friendly = attrs.get("friendly_name") or entity_id
            return {"entity_id": entity_id, "friendly_name": friendly, "model": model, "server": server}

        # -- Storage (on-disk) --
        def _fsize(path: str) -> int | None:
            try:
                return _os.path.getsize(path)
            except OSError:
                return None

        def _dirsize(path: str) -> int | None:
            try:
                total = 0
                for dirpath, _dirnames, filenames in _os.walk(path):
                    for fname in filenames:
                        try:
                            total += _os.path.getsize(_os.path.join(dirpath, fname))
                        except OSError:
                            pass
                return total
            except OSError:
                return None

        storage_dir = hass.config.path(".storage")
        knowledge_bytes = _fsize(_os.path.join(storage_dir, "kyber.knowledge"))
        chat_bytes = _fsize(_os.path.join(storage_dir, "kyber_chat_history"))

        # Scan all kyber* files in .storage/ for a complete picture
        storage_files: dict[str, int] = {}
        try:
            for _fname in _os.listdir(storage_dir):
                if _fname.startswith("kyber"):
                    _fpath = _os.path.join(storage_dir, _fname)
                    if _os.path.isfile(_fpath):
                        try:
                            storage_files[_fname] = _os.path.getsize(_fpath)
                        except OSError:
                            pass
        except OSError:
            pass
        storage_total_bytes = sum(storage_files.values()) if storage_files else None

        # Component directory (Python code + www assets)
        component_dir = hass.config.path("custom_components", "kyber")
        component_bytes = _dirsize(component_dir)

        # -- In-memory resources --
        snapshots = hass.data.get(_DEBUG_SNAPSHOTS_KEY) or {}
        global_logs = hass.data.get(_KYBER_GLOBAL_LOG_KEY) or []

        # Process RSS via /proc (Linux/Docker only; None on other platforms)
        rss_bytes: int | None = None
        try:
            with open("/proc/self/status", encoding="utf-8") as _f:
                for _line in _f:
                    if _line.startswith("VmRSS:"):
                        rss_bytes = int(_line.split()[1]) * 1024
                        break
        except Exception:  # noqa: BLE001
            pass

        return self.json({
            "ai_task_entity": ai_task_entity,
            "ai_task_info": _entity_info(ai_task_entity),
            "narrator_ai_task_entity": narrator_ai_task_entity,
            "narrator_ai_task_info": _entity_info(narrator_ai_task_entity),
            "token_usage": token_usage,
            "knowledge": {
                "total": len(all_entries),
                "by_category": cat_counts,
                "needs_review": flagged,
                "total_hits": total_hits,
            },
            "last_turn": {
                "ts": snap.get("ts") if snap else None,
                "request_id": snap.get("request_id") if snap else None,
                "elapsed_ms": snap.get("elapsed_ms") if snap else None,
                "intent": snap.get("intent") if snap else None,
                "char_count": snap.get("char_count") if snap else None,
                "approx_tokens": snap.get("approx_tokens") if snap else None,
            } if snap else None,
            "tool_history_size": len(hass.data.get(_DEBUG_TOOL_HISTORY_KEY, []) or []),
            "explorer_progress": hass.data.get(EXPLORER_PROGRESS_KEY),
            "narrator_stats": hass.data.get(NARRATOR_STATS_KEY),
            "deep_job": _get_deep_job_status(),
            "storage": {
                "knowledge_file_bytes": knowledge_bytes,
                "chat_history_file_bytes": chat_bytes,
                "files": storage_files,
                "total_bytes": storage_total_bytes,
                "component_bytes": component_bytes,
            },
            "resources": {
                "snapshots_buffered": len(snapshots),
                "snapshots_max": _DEBUG_SNAPSHOTS_MAX,
                "global_log_entries": len(global_logs),
                "global_log_max": _KYBER_GLOBAL_LOG_MAX,
                "tfidf_terms": len(kstore._idf),
                "knowledge_vectors": len(kstore._vectors),
                "process_rss_bytes": rss_bytes,
            },
        })


class KyberDebugBundleView(HomeAssistantView):
    """Return a zip bundle of one turn's debug info (or the last turn).

    GET /api/kyber/debug/bundle?request_id=XYZ  → application/zip
    GET /api/kyber/debug/bundle                 → uses last turn
    """

    url = "/api/kyber/debug/bundle"
    name = "api:kyber:debug:bundle"
    requires_auth = True

    @staticmethod
    def _read_manifest_version() -> str:
        return _KYBER_VERSION

    async def get(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        import io
        import json as _json
        import zipfile
        from collections import OrderedDict
        hass: HomeAssistant = request.app["hass"]
        rid = (request.query.get("request_id") or "").strip()
        snaps = hass.data.get(_DEBUG_SNAPSHOTS_KEY)
        snap: dict | None = None
        if rid and isinstance(snaps, OrderedDict):
            snap = snaps.get(rid)
        if snap is None:
            snap = hass.data.get(_DEBUG_LAST_TURN_KEY)
        if not snap:
            return self.json_message("No turn snapshot available", HTTPStatus.NOT_FOUND)

        redacted_snap = _redact_secrets(snap)
        manifest_obj: dict = _redact_secrets({
            "kyber_version": self._read_manifest_version(),
            "request_id": redacted_snap.get("request_id"),
            "ts": redacted_snap.get("ts"),
            "intent": redacted_snap.get("intent"),
            "elapsed_ms": redacted_snap.get("elapsed_ms"),
            "char_count": redacted_snap.get("char_count"),
            "approx_tokens": redacted_snap.get("approx_tokens"),
            "auto_rating": redacted_snap.get("auto_rating"),
            "session_meta": redacted_snap.get("session_meta") or {},
        })

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", _json.dumps(manifest_obj, indent=2, default=str))
            zf.writestr("snapshot.json", _json.dumps(redacted_snap, indent=2, default=str))
            zf.writestr("user_prompt.txt", redacted_snap.get("user_prompt") or "")
            zf.writestr("expanded_prompt.txt", redacted_snap.get("expanded_prompt") or "")
            zf.writestr("instructions_used.txt", redacted_snap.get("instructions_used") or "")
            zf.writestr("response.txt", redacted_snap.get("response_text") or "")
            zf.writestr("tool_log.json", _json.dumps(redacted_snap.get("tool_log") or [], indent=2, default=str))
            zf.writestr("knowledge_used.json", _json.dumps(redacted_snap.get("picked_knowledge") or [], indent=2, default=str))
            zf.writestr("progress_events.json", _json.dumps(redacted_snap.get("progress_events") or [], indent=2, default=str))
            # Logs as text (one line per record) + json.
            logs = redacted_snap.get("logs") or []
            log_lines: list[str] = []
            for r in logs:
                ts_iso = ""
                try:
                    import datetime as _dt
                    ts_iso = _dt.datetime.fromtimestamp(r.get("ts", 0)).strftime("%H:%M:%S.%f")[:-3]
                except Exception:  # noqa: BLE001
                    pass
                log_lines.append(f"{ts_iso} {r.get('level','?'):<8} {r.get('logger','?')}: {r.get('message','')}")
            zf.writestr("logs.txt", "\n".join(log_lines))
            zf.writestr("logs.json", _json.dumps(logs, indent=2, default=str))
            readme = (
                "Kyber debug bundle\n"
                "==================\n\n"
                f"request_id: {redacted_snap.get('request_id')}\n"
                f"ts: {redacted_snap.get('ts')}\n"
                f"intent: {redacted_snap.get('intent')}\n"
                f"elapsed_ms: {redacted_snap.get('elapsed_ms')}\n\n"
                "Contents:\n"
                "  manifest.json         - bundle meta (kyber version, ts, intent, ...)\n"
                "  snapshot.json         - full per-turn snapshot (single source of truth)\n"
                "  user_prompt.txt       - what the user typed\n"
                "  expanded_prompt.txt   - the full system prompt the model actually saw\n"
                "  instructions_used.txt - instructions for the final round of the tool loop\n"
                "  response.txt          - assistant's final reply\n"
                "  tool_log.json         - all tool calls made this turn (name, args, status, ms)\n"
                "  knowledge_used.json   - which memory entries were injected (with score)\n"
                "  progress_events.json  - progress updates streamed to the panel\n"
                "  logs.txt / logs.json  - kyber.* log records captured during the turn\n"
            )
            zf.writestr("README.txt", readme)

        data = buf.getvalue()
        fname = f"kyber-debug-{snap.get('request_id') or 'last'}-{snap.get('ts') or 'now'}.zip"
        return web.Response(
            body=data,
            content_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )


class KyberBugReportView(HomeAssistantView):
    """Generate an AI-drafted GitHub issue from a debug turn snapshot.

    POST /api/kyber/debug/bug-report
    Body: { request_id, what_asked, what_expected, what_happened, include_bundle, bundle_name }
    Returns: { title, body, similar_issues }
    """

    url = "/api/kyber/debug/bug-report"
    name = "api:kyber:debug:bug_report"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        import re as _re
        from collections import OrderedDict
        from urllib.parse import quote as _quote

        hass: HomeAssistant = request.app["hass"]
        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Kyber: failed to parse bug report request body: %s", err)
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        rid = (body.get("request_id") or "").strip()
        what_asked = (body.get("what_asked") or "").strip()
        what_expected = (body.get("what_expected") or "").strip()
        what_happened = (body.get("what_happened") or "").strip()
        include_bundle = bool(body.get("include_bundle", False))
        bundle_name = (body.get("bundle_name") or "").strip()

        if not (what_asked or what_happened):
            return self.json_message("Provide at least what_asked or what_happened", HTTPStatus.BAD_REQUEST)

        snaps = hass.data.get(_DEBUG_SNAPSHOTS_KEY)
        snap: dict | None = None
        if rid and isinstance(snaps, OrderedDict):
            snap = snaps.get(rid)
        if snap is None:
            snap = hass.data.get(_DEBUG_LAST_TURN_KEY)

        entity_id = ""
        entries = hass.config_entries.async_entries(DOMAIN)
        if entries:
            first = entries[0]
            entity_id = str(first.options.get(CONF_AI_TASK_ENTITY_ID) or first.data.get(CONF_AI_TASK_ENTITY_ID, ""))
        if not entity_id:
            return self.json_message("No AI task entity configured", HTTPStatus.BAD_REQUEST)

        bundle_summary = _build_redacted_bundle_summary(snap) if include_bundle and snap else ""

        prompt_parts = [
            "Generate a concise GitHub issue report for the Kyber Home Assistant integration.",
            "Respond with EXACTLY this format (no extra text before or after):",
            "",
            "TITLE: <one-line issue title, max 80 chars, no markdown>",
            "BODY:",
            "<the full GitHub issue body in markdown>",
            "",
            "The body must include: ## Summary, ## Steps to reproduce, ## Expected behavior,",
            "## Actual behavior, and (if bundle data is provided) ## Debug info.",
            "",
            "User description:",
            f"**What was asked / typed:** {what_asked or '(not provided)'}",
            f"**What was expected:** {what_expected or '(not provided)'}",
            f"**What actually happened:** {what_happened or '(not provided)'}",
        ]
        if bundle_name:
            prompt_parts.append(f"**Bundle filename:** {bundle_name}")
        if bundle_summary:
            prompt_parts += ["", "Debug bundle summary (PII has been redacted):", bundle_summary]

        try:
            result = await async_ai_call(
                hass,
                task_name=f"{DOMAIN}_bug_report",
                entity_id=entity_id,
                instructions="\n".join(prompt_parts),
            )
            raw = result.data if isinstance(result.data, str) else str(result.data)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Kyber bug report generation failed")
            return self.json_message("Internal error", HTTPStatus.INTERNAL_SERVER_ERROR)

        title, body_lines, in_body = "", [], False
        for line in raw.strip().splitlines():
            if not in_body and line.startswith("TITLE:"):
                title = line[len("TITLE:"):].strip()
            elif not in_body and line.strip() == "BODY:":
                in_body = True
            elif in_body:
                body_lines.append(line)
        if not title:
            title = f"bug: {(what_asked or what_happened)[:70]}"
        body_md = "\n".join(body_lines).strip() or raw.strip()
        kyber_version = (snap or {}).get("kyber_version") or KyberDebugBundleView._read_manifest_version()
        body_md = _restore_kyber_version_in_bug_report(body_md, kyber_version)

        similar: list[dict] = []
        try:
            import aiohttp as _aiohttp
            stopwords = {"when", "with", "this", "that", "from", "into", "does", "kyber"}
            words = [w for w in _re.split(r"\W+", (title + " " + what_happened).lower())
                     if len(w) > 4 and w not in stopwords]
            q = _quote(" ".join(words[:6]) + " repo:pgroene/kyber")
            search_url = f"https://api.github.com/search/issues?q={q}&per_page=3"
            async with _aiohttp.ClientSession() as sess:
                async with sess.get(
                    search_url,
                    headers={"Accept": "application/vnd.github.v3+json"},
                    timeout=_aiohttp.ClientTimeout(total=6),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        similar = [
                            {"number": i["number"], "title": i["title"], "url": i["html_url"], "state": i["state"]}
                            for i in data.get("items", [])[:3]
                        ]
        except Exception as err:  # noqa: BLE001 — GitHub search is best-effort
            _LOGGER.debug("Kyber: similar-issue search failed (non-critical): %s", err)

        return self.json({"title": title, "body": body_md, "similar_issues": similar, "bundle_available": snap is not None})


def _build_redaction_map(snap: dict) -> dict[str, str]:
    """Build {token: redacted-N} map from entity IDs in the snap."""
    import re as _re
    tokens: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        tok = tok.strip()
        if len(tok) < 3 or tok.lower() in {"the", "and", "for", "are", "not", "can", "get", "set"}:
            return
        if tok not in seen:
            seen.add(tok)
            tokens.append(tok)

    for entry in snap.get("tool_log") or []:
        for m in _re.finditer(r"\b[a-z_]+\.[a-z0-9_]+\b", str(entry)):
            _add(m.group(0))
            for part in _re.split(r"[._]", m.group(0)):
                if len(part) >= 4 and not part.isdigit():
                    _add(part)
    for field in ("instructions_used", "expanded_prompt"):
        for m in _re.finditer(r"\b[a-z_]+\.[a-z0-9_]+\b", snap.get(field) or ""):
            _add(m.group(0))
    return {t: f"***redacted-{i + 1}***" for i, t in enumerate(sorted(tokens, key=len, reverse=True))}


def _restore_kyber_version_in_bug_report(body_md: str, kyber_version: str) -> str:
    """Replace redacted or unknown Kyber version lines with the actual version."""
    import re as _re

    if not body_md or not kyber_version:
        return body_md
    return _re.sub(
        r"^(\s*(?:[-*]\s+)?(?:\*\*)?Kyber version(?:\*\*)?:\s*).*$",
        rf"\g<1>{kyber_version}",
        body_md,
        flags=_re.IGNORECASE | _re.MULTILINE,
    )


def _build_redacted_bundle_summary(snap: dict) -> str:
    """Short redacted summary of key snap fields for the AI prompt."""
    rmap = _build_redaction_map(snap)
    kyber_version = snap.get("kyber_version") or KyberDebugBundleView._read_manifest_version()

    def _r(text: str) -> str:
        for tok, rep in rmap.items():
            text = text.replace(tok, rep)
        return text

    lines = [
        f"- Kyber version: {kyber_version}",
        f"- Intent: {snap.get('intent', '?')}",
        f"- Prompt size: {snap.get('char_count', '?')} chars",
        f"- Response time: {snap.get('elapsed_ms', '?')} ms",
        f"- Tool calls: {len(snap.get('tool_log') or [])}",
    ]
    for entry in (snap.get("tool_log") or [])[:6]:
        lines.append(f"  - {entry.get('name', '?')}: {entry.get('status', '?')}")
    response = (snap.get("response_text") or "")[:600]
    if response:
        lines.append(f"- AI response snippet: {_r(response)}")
    for rec in (snap.get("logs") or []):
        if rec.get("level") in ("WARNING", "ERROR"):
            lines.append(f"- Log {rec['level']}: {_r(rec.get('message', ''))}")
    return "\n".join(lines)


class KyberDebugLogsView(HomeAssistantView):
    """Return the global Kyber log ring buffer.

    GET /api/kyber/debug/logs               → JSON {"logs": [...], "total": N}
    GET /api/kyber/debug/logs?format=txt    → plain text download
    GET /api/kyber/debug/logs?level=WARNING → filter by minimum level
    """

    url = "/api/kyber/debug/logs"
    name = "api:kyber:debug:logs"
    requires_auth = True

    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

    async def get(self, request: web.Request) -> web.Response:
        import datetime as _dt
        hass: HomeAssistant = request.app["hass"]
        buf: list[dict] = list(hass.data.get(_KYBER_GLOBAL_LOG_KEY) or [])

        min_level_str = (request.query.get("level") or "").upper()
        min_level_val = self._LEVEL_ORDER.get(min_level_str, 0)
        if min_level_val > 0:
            buf = [r for r in buf if self._LEVEL_ORDER.get(r.get("level", "DEBUG"), 0) >= min_level_val]

        fmt = (request.query.get("format") or "").lower()
        if fmt == "txt":
            lines = []
            for r in buf:
                try:
                    ts = _dt.datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S.%f")[:-3]
                except Exception:  # noqa: BLE001
                    ts = "?"
                lines.append(f"{ts} {r.get('level','?'):<8} {r.get('logger','?')}: {r.get('message','')}")
            text = "\n".join(lines)
            return web.Response(
                body=text.encode(),
                content_type="text/plain",
                headers={"Content-Disposition": "attachment; filename=\"kyber-logs.txt\""},
            )

        return self.json({"logs": buf, "total": len(buf)})

    async def delete(self, request: web.Request) -> web.Response:
        """Clear the log buffer. DELETE /api/kyber/debug/logs"""
        hass: HomeAssistant = request.app["hass"]
        hass.data[_KYBER_GLOBAL_LOG_KEY] = []
        return self.json({"cleared": True})


class KyberDebugModeView(HomeAssistantView):
    """Get/set the debug-mode flag used by the panel.

    GET  /api/kyber/debug/mode → {"enabled": bool}
    POST /api/kyber/debug/mode {"enabled": bool} → {"enabled": bool}
    """

    url = "/api/kyber/debug/mode"
    name = "api:kyber:debug:mode"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        hass: HomeAssistant = request.app["hass"]
        return self.json({"enabled": _get_debug_mode(hass)})

    async def post(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        hass: HomeAssistant = request.app["hass"]
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)
        enabled = bool(body.get("enabled", _DEBUG_MODE_DEFAULT))
        hass.data[_DEBUG_MODE_KEY] = enabled
        # Also persist to the integration's options so the change survives
        # restart and the sidebar panel registration updates accordingly.
        # We avoid importing from .const at module top to keep the existing
        # import surface stable for tests.
        try:
            from .const import CONF_ENABLE_DEBUG_VIEWS
            entries = hass.config_entries.async_entries(DOMAIN)
            if entries:
                entry = entries[0]
                current = entry.options.get(CONF_ENABLE_DEBUG_VIEWS)
                if current != enabled:
                    new_options = {**entry.options, CONF_ENABLE_DEBUG_VIEWS: enabled}
                    hass.config_entries.async_update_entry(entry, options=new_options)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed to persist debug-mode to options: %s", err)
        # Adjust kyber root logger level to match debug mode
        _kyber_root = logging.getLogger("custom_components.kyber")
        if enabled:
            _kyber_root.setLevel(logging.DEBUG)
        else:
            _kyber_root.setLevel(logging.WARNING)
        return self.json({"enabled": enabled})




class KyberMemoryExportView(HomeAssistantView):
    """Export knowledge store entries with triage assessment.

    GET /api/kyber/export/memory → application/json (download)

    Each entry is annotated with a ``triage`` object:
      - ``recommend``:  "skip" | "consider" | "good"
      - ``reason``:     short slug explaining the decision
      - ``test_prompt``: suggested question to test this entry (when recommend != "skip")
    """

    url = "/api/kyber/export/memory"
    name = "api:kyber:export:memory"
    requires_auth = True

    # Regex to detect entity_id patterns like light.living_room
    _ENTITY_RE = re.compile(r"\b[a-z_]+\.[a-z_0-9]+\b")

    async def get(self, request: web.Request) -> web.Response:
        import datetime as _dt

        hass: HomeAssistant = request.app["hass"]

        kstore = get_knowledge_store(hass)
        await kstore.async_load()
        all_entries: list[dict] = list(kstore._entries.values())

        triaged: list[dict] = []
        for entry in all_entries:
            annotated = dict(entry)
            annotated["triage"] = _triage_knowledge_entry(entry)
            triaged.append(annotated)

        # Sort: good → consider → skip, then by category
        _order = {"good": 0, "consider": 1, "skip": 2}
        triaged.sort(key=lambda e: (_order.get(e["triage"]["recommend"], 9), e.get("category", "")))

        counts = {r: sum(1 for e in triaged if e["triage"]["recommend"] == r) for r in ("good", "consider", "skip")}

        payload = {
            "metadata": {
                "exported_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "total_entries": len(triaged),
                "triage_counts": counts,
                "triage_heuristics": [
                    "skip: category=language_hint (system entries, not useful for tests)",
                    "skip: content shorter than 25 chars",
                    "skip: confidence < 0.35",
                    "good: category=entity_alias (maps user phrase to entity_id)",
                    "good: category=entity_note and contains entity_id pattern",
                    "good: category=procedure (multi-step actions)",
                    "consider: everything else with an entity_id pattern",
                ],
            },
            "entries": triaged,
        }

        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"kyber-memory-{ts}.json"
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        return web.Response(
            body=body,
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


_ENTITY_RE = re.compile(r"\b[a-z_]+\.[a-z0-9_]+\b")


def _triage_knowledge_entry(entry: dict) -> dict:
    """Return triage assessment for a knowledge entry.

    Returns dict with keys: recommend ("skip"|"consider"|"good"), reason, test_prompt.
    """
    category = entry.get("category", "")
    content = entry.get("content") or ""
    subject = entry.get("subject") or ""
    confidence = float(entry.get("confidence") or 1.0)

    # ── Hard skips ──────────────────────────────────────────────────────────
    if category == "language_hint":
        return {"recommend": "skip", "reason": "language_hint_system_entry", "test_prompt": None}
    if len(content) < 25:
        return {"recommend": "skip", "reason": "content_too_short", "test_prompt": None}
    if confidence < 0.35:
        return {"recommend": "skip", "reason": "low_confidence", "test_prompt": None}

    has_entity = bool(_ENTITY_RE.search(content) or _ENTITY_RE.search(subject))

    # ── Good candidates ─────────────────────────────────────────────────────
    if category == "entity_alias" and has_entity:
        prompt = f"Can you turn on the {subject}?" if subject else None
        return {"recommend": "good", "reason": "entity_alias_with_entity_id", "test_prompt": prompt}

    if category == "entity_note" and has_entity:
        prompt = f"Tell me about {subject or 'this device'}." if subject else None
        return {"recommend": "good", "reason": "entity_note_with_entity_id", "test_prompt": prompt}

    if category == "procedure":
        prompt = f"How do I {subject}?" if subject else None
        return {"recommend": "good", "reason": "procedure_knowledge", "test_prompt": prompt}

    if category == "area_alias" and has_entity:
        prompt = f"Turn off the lights in the {subject}." if subject else None
        return {"recommend": "good", "reason": "area_alias_with_entity", "test_prompt": prompt}

    # ── Consider (has entity but category is general or other) ──────────────
    if has_entity:
        return {"recommend": "consider", "reason": "has_entity_id_reference", "test_prompt": None}

    # ── Skip the rest ────────────────────────────────────────────────────────
    return {"recommend": "skip", "reason": "no_entity_reference_and_not_procedure", "test_prompt": None}


class KyberHomeExportView(HomeAssistantView):
    """Export a snapshot of the current home state for testing / evaluation.

    GET /api/kyber/export/home-state → application/json (download)

    Returns a structured JSON containing:
    - entities   (all states with domain, area_id, labels, attributes)
    - areas      (from area registry)
    - labels     (from label registry, HA 2024+)
    - devices    (device registry — name, area_id, manufacturer, model)
    - metadata   (HA version, counts, timestamp)
    """

    url = "/api/kyber/export/home-state"
    name = "api:kyber:export:home_state"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        import datetime as _dt

        hass: HomeAssistant = request.app["hass"]

        try:
            from homeassistant.helpers import area_registry as ar
            from homeassistant.helpers import entity_registry as er
            from homeassistant.helpers import device_registry as dr
            area_reg = ar.async_get(hass)
            entity_reg = er.async_get(hass)
            device_reg = dr.async_get(hass)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber export: registry error: %s", err)
            area_reg = entity_reg = device_reg = None

        # ── Areas ────────────────────────────────────────────────────────────
        areas: list[dict] = []
        if area_reg:
            for a in area_reg.async_list_areas():
                entry: dict = {"area_id": a.id, "name": a.name}
                if getattr(a, "aliases", None):
                    entry["aliases"] = list(a.aliases)
                areas.append(entry)

        # ── Labels (HA 2024+) ─────────────────────────────────────────────
        labels: list[dict] = []
        try:
            from homeassistant.helpers import label_registry as lr
            label_reg = lr.async_get(hass)
            for lbl in label_reg.async_list_labels():
                labels.append({"label_id": lbl.label_id, "name": lbl.name})
        except Exception:  # noqa: BLE001
            pass

        # ── Devices ───────────────────────────────────────────────────────
        devices: list[dict] = []
        if device_reg:
            for d in device_reg.devices.values():
                dev: dict = {
                    "id": d.id,
                    "name": d.name or d.name_by_user or "",
                    "area_id": d.area_id,
                    "manufacturer": d.manufacturer,
                    "model": d.model,
                }
                devices.append(dev)

        # ── Entities ──────────────────────────────────────────────────────
        entities: list[dict] = []
        er_by_eid: dict = {}
        if entity_reg:
            er_by_eid = {e.entity_id: e for e in entity_reg.entities.values()}

        for state in hass.states.async_all():
            eid = state.entity_id
            domain = eid.split(".")[0]
            reg_entry = er_by_eid.get(eid)
            ent: dict = {
                "entity_id": eid,
                "domain": domain,
                "state": state.state,
                "friendly_name": state.attributes.get("friendly_name", ""),
            }
            # Prefer area from entity registry, fall back to device
            area_id = None
            if reg_entry and reg_entry.area_id:
                area_id = reg_entry.area_id
            elif reg_entry and reg_entry.device_id and device_reg:
                dev = device_reg.devices.get(reg_entry.device_id)
                if dev:
                    area_id = dev.area_id
            if area_id:
                ent["area_id"] = area_id
            # Labels
            if reg_entry and getattr(reg_entry, "labels", None):
                ent["labels"] = sorted(reg_entry.labels)
            # Selected useful attributes (keep payload manageable)
            attrs: dict = {}
            skip = {"friendly_name", "icon", "entity_picture", "supported_features",
                    "attribution", "restored", "supported_color_modes"}
            for k, v in state.attributes.items():
                if k not in skip and not k.startswith("_"):
                    attrs[k] = v
            if attrs:
                ent["attributes"] = attrs
            entities.append(ent)

        # Sort for readability
        entities.sort(key=lambda e: e["entity_id"])

        # ── Automations ───────────────────────────────────────────────────
        automations: list[dict] = []
        try:
            for state in hass.states.async_all("automation"):
                eid = state.entity_id
                reg_entry = er_by_eid.get(eid)
                aut: dict = {
                    "entity_id": eid,
                    "friendly_name": state.attributes.get("friendly_name", ""),
                    "state": state.state,
                    "last_triggered": str(state.attributes.get("last_triggered", "")),
                }
                # unique_id from entity registry lets us find the config entry
                if reg_entry and reg_entry.unique_id:
                    aut["unique_id"] = reg_entry.unique_id
                automations.append(aut)
            automations.sort(key=lambda a: a["friendly_name"].lower())
        except Exception as _err:  # noqa: BLE001
            _LOGGER.debug("Kyber export: automation error: %s", _err)

        # ── Dashboards (Lovelace) ─────────────────────────────────────────
        dashboards: list[dict] = []
        try:
            from homeassistant.components.lovelace import dashboard as ll_dash  # type: ignore[attr-defined]
            lovelace = hass.data.get("lovelace")
            if lovelace:
                # Raw config for each dashboard
                for dash_id, dash_obj in (lovelace.get("dashboards") or {}).items():
                    try:
                        config = await dash_obj.async_load(force=False)
                        dashboards.append({
                            "dashboard_id": dash_id,
                            "url_path": getattr(dash_obj, "url_path", dash_id),
                            "title": (config or {}).get("title", dash_id),
                            "views": len((config or {}).get("views", [])),
                            "config": config,
                        })
                    except Exception as _e:  # noqa: BLE001
                        dashboards.append({"dashboard_id": dash_id, "error": str(_e)})
        except Exception as _err:  # noqa: BLE001
            _LOGGER.debug("Kyber export: lovelace error: %s", _err)

        # ── Metadata ──────────────────────────────────────────────────────
        metadata: dict = {
            "exported_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "ha_version": str(getattr(hass.config, "version", "unknown")),
            "total_entities": len(entities),
            "total_areas": len(areas),
            "total_devices": len(devices),
            "total_labels": len(labels),
            "total_automations": len(automations),
            "total_dashboards": len(dashboards),
            "domains": sorted({e["domain"] for e in entities}),
            "areas_configured": len(areas) > 0,
            "entities_with_area": sum(1 for e in entities if "area_id" in e),
            "entities_without_area": sum(1 for e in entities if "area_id" not in e),
        }

        payload = {
            "metadata": metadata,
            "areas": areas,
            "labels": labels,
            "devices": devices,
            "entities": entities,
            "automations": automations,
            "dashboards": dashboards,
        }

        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"kyber-home-state-{ts}.json"
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        return web.Response(
            body=body,
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

