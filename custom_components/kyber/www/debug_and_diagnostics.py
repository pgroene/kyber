"""Debug and diagnostics views/helpers extracted from http_api.py."""
from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN
from .knowledge import get_store as get_knowledge_store

try:
    from homeassistant.components.ai_task import async_generate_data
except ImportError:  # HA < 2025.2 (test environments)
    async def async_generate_data(*args, **kwargs):  # type: ignore[misc]
        raise RuntimeError("homeassistant.components.ai_task not available (HA < 2025.2)")

_LOGGER = logging.getLogger(__name__)

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


def _get_debug_mode(hass: HomeAssistant) -> bool:
    val = hass.data.get(_DEBUG_MODE_KEY)
    if val is None:
        return _DEBUG_MODE_DEFAULT
    return bool(val)


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


def _debug_attach_log_capture(request_id: str) -> tuple[list[dict], _KyberTurnLogHandler] | tuple[None, None]:
    """Attach a per-turn log handler to the root logger; returns (sink, handler) or (None, None)."""
    if not request_id:
        return None, None
    try:
        sink: list[dict] = []
        handler = _KyberTurnLogHandler(sink)
        logging.getLogger().addHandler(handler)
        return sink, handler
    except Exception:  # noqa: BLE001
        return None, None


def _debug_detach_log_capture(handler: _KyberTurnLogHandler | None) -> None:
    if handler is None:
        return
    try:
        logging.getLogger().removeHandler(handler)
    except Exception:  # noqa: BLE001
        pass


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
        # Find the configured AI Task entity from any entry in hass.data[DOMAIN]
        entries = hass.data.get(DOMAIN, {})
        ai_task_entity = ""
        if isinstance(entries, dict) and entries:
            first = next(iter(entries.values()), None)
            if isinstance(first, dict):
                ai_task_entity = str(first.get(CONF_AI_TASK_ENTITY_ID, ""))
        return self.json({
            "ai_task_entity": ai_task_entity,
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
        try:
            import json as _json
            import os
            here = os.path.dirname(__file__)
            with open(os.path.join(here, "manifest.json"), "r", encoding="utf-8") as f:
                return _json.load(f).get("version", "unknown")
        except Exception:  # noqa: BLE001
            return "unknown"

    async def get(self, request: web.Request) -> web.Response:
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

        manifest_obj: dict = {
            "kyber_version": self._read_manifest_version(),
            "request_id": snap.get("request_id"),
            "ts": snap.get("ts"),
            "intent": snap.get("intent"),
            "elapsed_ms": snap.get("elapsed_ms"),
            "char_count": snap.get("char_count"),
            "approx_tokens": snap.get("approx_tokens"),
            "auto_rating": snap.get("auto_rating"),
            "session_meta": snap.get("session_meta") or {},
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", _json.dumps(manifest_obj, indent=2, default=str))
            zf.writestr("snapshot.json", _json.dumps(snap, indent=2, default=str))
            zf.writestr("user_prompt.txt", snap.get("user_prompt") or "")
            zf.writestr("expanded_prompt.txt", snap.get("expanded_prompt") or "")
            zf.writestr("instructions_used.txt", snap.get("instructions_used") or "")
            zf.writestr("response.txt", snap.get("response_text") or "")
            zf.writestr("tool_log.json", _json.dumps(snap.get("tool_log") or [], indent=2, default=str))
            zf.writestr("knowledge_used.json", _json.dumps(snap.get("picked_knowledge") or [], indent=2, default=str))
            zf.writestr("progress_events.json", _json.dumps(snap.get("progress_events") or [], indent=2, default=str))
            # Logs as text (one line per record) + json.
            logs = snap.get("logs") or []
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
                f"request_id: {snap.get('request_id')}\n"
                f"ts: {snap.get('ts')}\n"
                f"intent: {snap.get('intent')}\n"
                f"elapsed_ms: {snap.get('elapsed_ms')}\n\n"
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
        except Exception:
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
            result = await async_generate_data(
                hass,
                task_name=f"{DOMAIN}_bug_report",
                entity_id=entity_id,
                instructions="\n".join(prompt_parts),
            )
            raw = result.data if isinstance(result.data, str) else str(result.data)
        except Exception as exc:
            return self.json_message(f"AI generation failed: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

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
        except Exception:
            pass

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


class KyberDebugModeView(HomeAssistantView):
    """Get/set the debug-mode flag used by the panel.

    GET  /api/kyber/debug/mode → {"enabled": bool}
    POST /api/kyber/debug/mode {"enabled": bool} → {"enabled": bool}
    """

    url = "/api/kyber/debug/mode"
    name = "api:kyber:debug:mode"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        return self.json({"enabled": _get_debug_mode(hass)})

    async def post(self, request: web.Request) -> web.Response:
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
        return self.json({"enabled": enabled})
