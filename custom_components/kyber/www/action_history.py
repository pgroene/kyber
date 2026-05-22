from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_STORAGE_KEY = "kyber.action_history"
_ALLOWED_STATUS = {"applied", "undone", "failed"}
_STORE: ActionHistoryStore | None = None


class ActionHistoryStore:
    """Persistent store for applied Kyber action plans."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._entries: list[dict[str, Any]] = []
        self._loaded = False
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        async with self._lock:
            if self._loaded:
                return
            data = await self._store.async_load() or {}
            entries = data.get("entries", [])
            self._entries = entries if isinstance(entries, list) else []
            self._loaded = True

    async def _persist_unlocked(self) -> None:
        await self._store.async_save({"entries": copy.deepcopy(self._entries)})

    def _build_undo_plan(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        undo_actions: list[dict[str, Any]] = []
        for action in reversed(actions):
            if not isinstance(action, dict) or action.get("type") != "call_service":
                continue
            domain = str(action.get("domain", "")).strip().lower()
            service = str(action.get("service", "")).strip().lower()
            entity_id = str(action.get("entity_id", "")).strip()
            if not domain or not service or not entity_id:
                continue

            reverse_service: str | None = None
            if domain in {"switch", "light"} and service == "turn_on":
                reverse_service = "turn_off"
            elif domain in {"switch", "light"} and service == "turn_off":
                reverse_service = "turn_on"
            elif domain == "media_player" and service == "media_play":
                reverse_service = "media_pause"

            if not reverse_service:
                continue

            undo_actions.append({
                "type": "call_service",
                "domain": domain,
                "service": reverse_service,
                "entity_id": entity_id,
                "service_data": copy.deepcopy(action.get("service_data") or {}),
                "description": f"Undo {domain}.{service} for {entity_id}",
            })
        return undo_actions

    async def async_record(
        self,
        summary: str,
        actions: list[dict[str, Any]],
        entity_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        await self.async_load()
        entry = {
            "id": str(uuid.uuid4()),
            "ts": int(time.time()),
            "summary": str(summary or "").strip(),
            "actions": copy.deepcopy(actions),
            "entity_changes": copy.deepcopy(entity_changes),
            "status": "applied",
            "undo_plan": self._build_undo_plan(actions),
        }
        async with self._lock:
            self._entries.insert(0, entry)
            self._entries = self._entries[:200]
            await self._persist_unlocked()
        return copy.deepcopy(entry)

    async def async_get(self, entry_id: str) -> dict[str, Any] | None:
        await self.async_load()
        for entry in self._entries:
            if entry.get("id") == entry_id:
                return copy.deepcopy(entry)
        return None

    async def async_mark_status(self, entry_id: str, status: str) -> dict[str, Any] | None:
        await self.async_load()
        if status not in _ALLOWED_STATUS:
            raise ValueError(f"Unsupported action history status: {status}")
        async with self._lock:
            for entry in self._entries:
                if entry.get("id") == entry_id:
                    entry["status"] = status
                    await self._persist_unlocked()
                    return copy.deepcopy(entry)
        return None

    async def async_undo(self, entry_id: str) -> list[dict[str, Any]]:
        entry = await self.async_mark_status(entry_id, "undone")
        return copy.deepcopy((entry or {}).get("undo_plan") or [])

    async def async_list(self, limit: int = 50) -> list[dict[str, Any]]:
        await self.async_load()
        limit = max(1, min(200, int(limit)))
        return copy.deepcopy(self._entries[:limit])


def get_store(hass: HomeAssistant) -> ActionHistoryStore:
    """Return the singleton action history store for this Home Assistant instance."""
    global _STORE
    if _STORE is None or _STORE.hass is not hass:
        _STORE = ActionHistoryStore(hass)
    return _STORE


async def _async_execute_undo_plan(
    hass: HomeAssistant, actions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Execute a generated undo plan consisting of simple service calls."""
    results: list[dict[str, Any]] = []
    for action in actions:
        domain = str(action.get("domain", "")).strip().lower()
        service = str(action.get("service", "")).strip().lower()
        entity_id = str(action.get("entity_id", "")).strip()
        service_data = copy.deepcopy(action.get("service_data") or {})
        if entity_id:
            service_data = {"entity_id": entity_id, **service_data}
        try:
            await hass.services.async_call(domain, service, service_data, blocking=True)
            results.append({
                "status": "ok",
                "type": action.get("type", "call_service"),
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
            })
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber action-history undo failed for %s.%s: %s", domain, service, err)
            results.append({
                "status": "error",
                "type": action.get("type", "call_service"),
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "message": str(err),
            })
    return results


class KyberActionHistoryEntryView(HomeAssistantView):
    """Return a single action history entry by ID."""

    url = "/api/kyber/history/actions/{entry_id}"
    name = "api:kyber:history:actions:entry"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        store = get_store(hass)
        entry = await store.async_get(entry_id)
        if not entry:
            return self.json_message(f"Action history entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
        return self.json(entry)


class KyberActionHistoryView(HomeAssistantView):
    """Return recent applied action history."""

    url = "/api/kyber/history/actions"
    name = "api:kyber:history:actions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        try:
            limit = max(1, min(200, int(request.query.get("limit", "50"))))
        except ValueError:
            limit = 50
        store = get_store(hass)
        entries = await store.async_list(limit=limit)
        return self.json({"entries": entries, "count": len(entries)})


class KyberActionHistoryUndoView(HomeAssistantView):
    """Undo a previously applied reversible action plan."""

    url = "/api/kyber/history/actions/{entry_id}/undo"
    name = "api:kyber:history:actions:undo"
    requires_auth = True

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        store = get_store(hass)
        entry = await store.async_get(entry_id)
        if not entry:
            return self.json_message(f"Action history entry '{entry_id}' not found", HTTPStatus.NOT_FOUND)
        if entry.get("status") != "applied":
            return self.json({
                "status": "noop",
                "message": "This history entry is no longer applied.",
                "entry": entry,
            })
        undo_plan = list(entry.get("undo_plan") or [])
        if not undo_plan:
            return self.json({
                "status": "noop",
                "message": "This history entry has no reversible actions.",
                "entry": entry,
            })

        results = await _async_execute_undo_plan(hass, undo_plan)
        failures = [result for result in results if result.get("status") != "ok"]
        if failures:
            updated = await store.async_mark_status(entry_id, "failed")
            return self.json({
                "status": "failed",
                "results": results,
                "entry": updated or entry,
            }, status_code=HTTPStatus.BAD_REQUEST)

        updated = await store.async_mark_status(entry_id, "undone")
        return self.json({
            "status": "ok",
            "results": results,
            "entry": updated or entry,
        })
