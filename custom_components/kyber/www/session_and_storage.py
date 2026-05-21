"""Session management and chat history storage for Kyber."""
from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

_CHAT_HISTORY_STORE_VERSION = 1
_CHAT_HISTORY_STORE_KEY = f"{DOMAIN}_chat_history"
_CHAT_HISTORY_MAX_MESSAGES = 20
_CHAT_MESSAGE_MAX_CHARS = 1500
_CHAT_SUMMARY_MAX_CHARS = 2000
_SESSIONS_MAX = 20
_SESSION_NAME_MAX_CHARS = 80

# hass.data keys for the shared Store instance and its lock
_STORE_DATA_KEY = f"{DOMAIN}_chat_store_instance"
_LOCK_DATA_KEY = f"{DOMAIN}_chat_store_lock"


def _new_session_id() -> str:
    """Generate a short unique session ID."""
    import time, random, string
    ts = hex(int(time.time()))[2:]
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{ts}{rand}"


def _migrate_user_to_sessions(user_data: dict[str, Any]) -> dict[str, Any]:
    """Migrate old {history, compacted_summary} to new sessions schema in place."""
    if "sessions" in user_data:
        return user_data  # already migrated
    sid = _new_session_id()
    return {
        "active_session": sid,
        "sessions": {
            sid: {
                "name": "Session 1",
                "history": user_data.get("history", []),
                "compacted_summary": user_data.get("compacted_summary", ""),
                "created_at": __import__("time").time(),
            }
        },
    }


def _get_active_session(user_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (session_id, session_data) for the active session, creating one if needed."""
    sessions: dict[str, Any] = user_data.get("sessions", {})
    active_id: str | None = user_data.get("active_session")
    if active_id and active_id in sessions:
        return active_id, sessions[active_id]
    # Fall back to first session or create a new one
    if sessions:
        first_id = next(iter(sessions))
        user_data["active_session"] = first_id
        return first_id, sessions[first_id]
    # No sessions — create default
    sid = _new_session_id()
    session = {"name": "Session 1", "history": [], "compacted_summary": "", "created_at": __import__("time").time()}
    sessions[sid] = session
    user_data["sessions"] = sessions
    user_data["active_session"] = sid
    return sid, session


def _sanitize_history(messages: Any) -> list[dict[str, str]]:
    """Normalize chat history payload to a safe, bounded list."""
    if not isinstance(messages, list):
        return []
    normalized: list[dict[str, str]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = "user" if msg.get("role") == "user" else "assistant"
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content[:_CHAT_MESSAGE_MAX_CHARS]})
    return normalized[-_CHAT_HISTORY_MAX_MESSAGES:]


def _sanitize_summary(summary: Any) -> str:
    """Normalize compacted summary to a bounded string."""
    return str(summary or "").strip()[:_CHAT_SUMMARY_MAX_CHARS]


def _get_or_create_store(hass: HomeAssistant) -> tuple[Store, asyncio.Lock]:
    """Return the shared Store instance and its lock, creating both on first call."""
    if _STORE_DATA_KEY not in hass.data:
        hass.data[_STORE_DATA_KEY] = Store(hass, _CHAT_HISTORY_STORE_VERSION, _CHAT_HISTORY_STORE_KEY)
    if _LOCK_DATA_KEY not in hass.data:
        hass.data[_LOCK_DATA_KEY] = asyncio.Lock()
    return hass.data[_STORE_DATA_KEY], hass.data[_LOCK_DATA_KEY]


async def _async_load_chat_store(hass: HomeAssistant) -> dict[str, Any]:
    """Load persisted chat history store, migrating old single-session format if needed."""
    store, lock = _get_or_create_store(hass)
    async with lock:
        data = await store.async_load()
        if not isinstance(data, dict):
            return {"users": {}}
        users = data.get("users")
        if not isinstance(users, dict):
            data["users"] = {}
            return data
        # Migrate users from old {history, compacted_summary} format to sessions format
        migrated = False
        pre_migration_users: dict[str, Any] = {}
        for uid, udata in list(users.items()):
            if isinstance(udata, dict) and "sessions" not in udata and "history" in udata:
                pre_migration_users[uid] = udata  # snapshot for rollback
                users[uid] = _migrate_user_to_sessions(udata)
                migrated = True
        if migrated:
            try:
                await store.async_save(data)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Kyber: chat history migration succeeded in memory but failed to persist "
                    "(%s). History will be re-migrated on next restart — no data is lost.",
                    err,
                )
                # Roll back in-memory changes so callers see the original format
                for uid, original in pre_migration_users.items():
                    users[uid] = original
        return data


async def _async_save_chat_store(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Persist chat history store."""
    store, lock = _get_or_create_store(hass)
    async with lock:
        await store.async_save(data)


class KyberHistoryView(HomeAssistantView):
    """Handle user-scoped chat history persistence for the active session."""

    url = "/api/kyber/history"
    name = "api:kyber:history"
    requires_auth = True

    @staticmethod
    def _user_id_from_request(request: web.Request) -> str | None:
        """Extract the authenticated Home Assistant user id from request."""
        ha_user = request.get("hass_user")
        user_id = getattr(ha_user, "id", None)
        return str(user_id) if user_id else None

    async def get(self, request: web.Request) -> web.Response:
        """Return persisted chat history for the active session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        data = await _async_load_chat_store(hass)
        users = data.setdefault("users", {})
        user_data = users.get(user_id, {})
        is_new = "sessions" not in user_data
        user_data = _migrate_user_to_sessions(user_data) if is_new else user_data
        before = len(user_data.get("sessions", {}))
        sid, session = _get_active_session(user_data)
        if is_new or len(user_data.get("sessions", {})) > before:
            users[user_id] = user_data
            await _async_save_chat_store(hass, data)
        return self.json(
            {
                "history": _sanitize_history(session.get("history", [])),
                "compacted_summary": _sanitize_summary(session.get("compacted_summary", "")),
                "session_id": sid,
                "session_name": session.get("name", "Session 1"),
            }
        )

    async def post(self, request: web.Request) -> web.Response:
        """Save persisted chat history for the active session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        data = await _async_load_chat_store(hass)
        users = data.setdefault("users", {})
        user_data = users.get(user_id, {})
        user_data = _migrate_user_to_sessions(user_data) if "sessions" not in user_data else user_data
        sid, session = _get_active_session(user_data)
        session["history"] = _sanitize_history(body.get("history", []))
        session["compacted_summary"] = _sanitize_summary(body.get("compacted_summary", ""))
        users[user_id] = user_data
        await _async_save_chat_store(hass, data)
        return self.json({"status": "ok"})

    async def delete(self, request: web.Request) -> web.Response:
        """Clear persisted chat history for the active session only."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        data = await _async_load_chat_store(hass)
        users = data.get("users", {})
        user_data = users.get(user_id)
        if user_data:
            user_data = _migrate_user_to_sessions(user_data) if "sessions" not in user_data else user_data
            sid, session = _get_active_session(user_data)
            session["history"] = []
            session["compacted_summary"] = ""
            users[user_id] = user_data
            await _async_save_chat_store(hass, data)
        return self.json({"status": "ok"})


class KyberSessionsView(HomeAssistantView):
    """Manage multiple chat sessions per user."""

    url = "/api/kyber/sessions"
    name = "api:kyber:sessions"
    requires_auth = True

    @staticmethod
    def _user_id_from_request(request: web.Request) -> str | None:
        ha_user = request.get("hass_user")
        user_id = getattr(ha_user, "id", None)
        return str(user_id) if user_id else None

    async def _load_user(self, hass: HomeAssistant, user_id: str) -> tuple[dict, dict]:
        """Return (data, user_data) ensuring sessions format. Persists on first creation."""
        data = await _async_load_chat_store(hass)
        users = data.setdefault("users", {})
        user_data = users.get(user_id, {})
        needs_save = "sessions" not in user_data
        user_data = _migrate_user_to_sessions(user_data) if needs_save else user_data
        before = len(user_data.get("sessions", {}))
        _get_active_session(user_data)  # ensure at least one session exists
        if len(user_data.get("sessions", {})) > before:
            needs_save = True
        users[user_id] = user_data
        if needs_save:
            await _async_save_chat_store(hass, data)
        return data, user_data

    async def get(self, request: web.Request) -> web.Response:
        """List all sessions for the current user."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        data, user_data = await self._load_user(hass, user_id)
        active_id = user_data.get("active_session")
        sessions_list = [
            {
                "id": sid,
                "name": s.get("name", "Session"),
                "message_count": len(s.get("history", [])),
                "created_at": s.get("created_at", 0),
                "active": sid == active_id,
            }
            for sid, s in user_data.get("sessions", {}).items()
        ]
        return self.json({"sessions": sessions_list, "active_session": active_id})

    async def post(self, request: web.Request) -> web.Response:
        """Create a new session and optionally switch to it."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}

        data, user_data = await self._load_user(hass, user_id)
        sessions = user_data.setdefault("sessions", {})
        if len(sessions) >= _SESSIONS_MAX:
            return self.json_message(
                f"Maximum {_SESSIONS_MAX} sessions reached", HTTPStatus.UNPROCESSABLE_ENTITY
            )

        import time as _time
        sid = _new_session_id()
        raw_name = str(body.get("name", f"Session {len(sessions) + 1}")).strip()
        name = raw_name[:_SESSION_NAME_MAX_CHARS] or f"Session {len(sessions) + 1}"
        sessions[sid] = {"name": name, "history": [], "compacted_summary": "", "created_at": _time.time()}
        if body.get("switch", True):
            user_data["active_session"] = sid
        data["users"][user_id] = user_data
        await _async_save_chat_store(hass, data)
        return self.json({"status": "ok", "session_id": sid, "name": name})

    async def put(self, request: web.Request) -> web.Response:
        """Switch active session or rename a session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        data, user_data = await self._load_user(hass, user_id)
        sessions = user_data.get("sessions", {})

        action = body.get("action", "switch")
        if action == "switch":
            sid = body.get("session_id") or _find_session_by_name(sessions, body.get("name", ""))
            if not sid or sid not in sessions:
                return self.json_message("Session not found", HTTPStatus.NOT_FOUND)
            user_data["active_session"] = sid
            data["users"][user_id] = user_data
            await _async_save_chat_store(hass, data)
            return self.json({"status": "ok", "active_session": sid})

        if action == "rename":
            sid = body.get("session_id") or user_data.get("active_session")
            if not sid or sid not in sessions:
                return self.json_message("Session not found", HTTPStatus.NOT_FOUND)
            new_name = str(body.get("name", "")).strip()[:_SESSION_NAME_MAX_CHARS]
            if not new_name:
                return self.json_message("Name cannot be empty", HTTPStatus.BAD_REQUEST)
            sessions[sid]["name"] = new_name
            data["users"][user_id] = user_data
            await _async_save_chat_store(hass, data)
            return self.json({"status": "ok"})

        return self.json_message(f"Unknown action: {action}", HTTPStatus.BAD_REQUEST)

    async def delete(self, request: web.Request) -> web.Response:
        """Delete a session (defaults to active). Switches to another session."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — body is optional on DELETE
            body = {}

        data, user_data = await self._load_user(hass, user_id)
        sessions = user_data.get("sessions", {})
        sid = body.get("session_id") or user_data.get("active_session")

        if not sid or sid not in sessions:
            return self.json_message("Session not found", HTTPStatus.NOT_FOUND)

        del sessions[sid]

        # Switch to the first remaining session or create a new one
        if sessions:
            user_data["active_session"] = next(iter(sessions))
        else:
            new_sid = _new_session_id()
            sessions[new_sid] = {"name": "Session 1", "history": [], "compacted_summary": "", "created_at": __import__("time").time()}
            user_data["active_session"] = new_sid

        data["users"][user_id] = user_data
        await _async_save_chat_store(hass, data)
        return self.json({"status": "ok", "active_session": user_data["active_session"]})


def _find_session_by_name(sessions: dict[str, Any], name: str) -> str | None:
    """Find a session id by exact name match (case-insensitive)."""
    name_lower = name.lower()
    for sid, s in sessions.items():
        if s.get("name", "").lower() == name_lower:
            return sid
    return None


class KyberSessionNameView(HomeAssistantView):
    """Generate an AI session title from recent messages and optionally save it."""

    url = "/api/kyber/sessions/name"
    name = "api:kyber:sessions:name"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @staticmethod
    def _user_id_from_request(request: web.Request) -> str | None:
        ha_user = request.get("hass_user")
        user_id = getattr(ha_user, "id", None)
        return str(user_id) if user_id else None

    async def post(self, request: web.Request) -> web.Response:
        """Generate a short title for the current session and save it."""
        hass: HomeAssistant = request.app["hass"]
        user_id = self._user_id_from_request(request)
        if not user_id:
            return self.json_message("Unable to resolve authenticated user", HTTPStatus.UNAUTHORIZED)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json_message("Invalid JSON body", HTTPStatus.BAD_REQUEST)

        messages: list[dict] = body.get("messages", [])
        if not messages:
            return self.json_message("No messages provided", HTTPStatus.BAD_REQUEST)

        # Build a compact transcript for the naming prompt (last 10 messages max)
        snippet_lines = []
        for msg in messages[-10:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = str(msg.get("content", "")).strip()[:200]
            if content:
                snippet_lines.append(f"{role}: {content}")
        transcript = "\n".join(snippet_lines)

        instructions = (
            "You are a helpful assistant. Based on the conversation below, "
            "generate a very short title (3–6 words, no punctuation at the end) "
            "that captures the main topic. Reply with ONLY the title — no quotes, "
            "no explanation, nothing else. "
            "Write the title in the same language as the conversation.\n\n"
            f"Conversation:\n{transcript}\n\nTitle:"
        )

        entity_id: str = self._config[CONF_AI_TASK_ENTITY_ID]
        from .api_utilities import async_ai_call  # local to avoid circular import
        try:
            result = await async_ai_call(
                hass,
                task_name=f"{DOMAIN}_session_name",
                entity_id=entity_id,
                instructions=instructions,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Session naming AI call failed: %s", err)
            return self.json_message(f"AI error: {err}", HTTPStatus.SERVICE_UNAVAILABLE)

        raw: str = result.data if isinstance(result.data, str) else str(result.data)
        # Take only the first line, strip quotes/punctuation
        name = raw.strip().splitlines()[0].strip().strip('"\'').strip(".,;:!?")
        name = name[:_SESSION_NAME_MAX_CHARS] or "Session"

        # Save the new name to the active session
        data = await _async_load_chat_store(hass)
        users = data.setdefault("users", {})
        user_data = users.get(user_id, {})
        user_data = _migrate_user_to_sessions(user_data) if "sessions" not in user_data else user_data
        sid, session = _get_active_session(user_data)
        session["name"] = name
        users[user_id] = user_data
        await _async_save_chat_store(hass, data)

        return self.json({"name": name, "session_id": sid})
