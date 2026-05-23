"""Kyber MCP (Model Context Protocol) server.

Exposes Kyber as an MCP server so external LLM clients (Claude Desktop,
ChatGPT, Cursor, Mistral le Chat, etc.) can control your home through
Kyber's full AI pipeline — including planning, self-correction, memory
and token budgeting.

Transport: Streamable HTTP (MCP spec 2024-11-05)
  POST /api/kyber/mcp  — JSON-RPC 2.0 endpoint

Authentication: Home Assistant long-lived access token in Authorization header.

Exposed tools:
  kyber_ask         — Natural-language query through Kyber's full AI pipeline.
  get_entity_state  — Get current state of one or more HA entities.
  list_entities     — List all HA entities with their states and areas.
  call_service      — Call a Home Assistant service directly.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_MAX_REQUESTS_PER_MINUTE,
    DEFAULT_MAX_REQUESTS_PER_MINUTE,
    DOMAIN,
    _sanitize_user_input,
)
from .rate_limiter import _rate_limiter

_LOGGER = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
_SERVER_INFO = {"name": "kyber", "version": "1.0.0"}

# hass.data key for the MCP call log ring buffer
_MCP_LOG_KEY = "kyber_mcp_call_log"
_MCP_LOG_MAX = 200  # keep last 200 calls


def _mcp_log(hass: HomeAssistant, entry: dict) -> None:
    """Append an entry to the MCP call log ring buffer."""
    buf: list[dict] = hass.data.setdefault(_MCP_LOG_KEY, [])
    buf.append(entry)
    if len(buf) > _MCP_LOG_MAX:
        del buf[: len(buf) - _MCP_LOG_MAX]


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_TOOLS: list[dict] = [
    {
        "name": "kyber_ask",
        "description": (
            "Ask Kyber to control your smart home using natural language. "
            "Kyber will plan, execute, and self-correct if needed. "
            "Use this for any home automation request: turning on lights, "
            "adjusting thermostats, running scenes, checking device states, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Natural-language instruction, e.g. 'turn off all lights in the bedroom'",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "get_entity_state",
        "description": "Get the current state of one or more Home Assistant entities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of entity IDs, e.g. ['light.bedroom', 'sensor.temperature']",
                },
            },
            "required": ["entity_ids"],
        },
    },
    {
        "name": "list_entities",
        "description": (
            "List Home Assistant entities. Optionally filter by domain or area. "
            "Returns entity_id, state, friendly_name and area for each entity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter, e.g. 'light', 'switch', 'sensor'",
                },
                "area": {
                    "type": "string",
                    "description": "Optional area name filter, e.g. 'bedroom', 'kitchen'",
                },
            },
        },
    },
    {
        "name": "get_datetime",
        "description": (
            "Get the current date, time, day of week, and timezone from Home Assistant. "
            "Call this whenever you need to know the current time for scheduling, "
            "calendar queries, or time-aware responses."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_todo_items",
        "description": (
            "Get items from Home Assistant todo list entities (shopping lists, task lists, etc.). "
            "Returns items filtered by status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Todo list entity IDs, e.g. ['todo.shopping', 'todo.tasks']. If omitted, all todo lists are queried.",
                },
                "status": {
                    "type": "string",
                    "enum": ["needs_action", "completed", "all"],
                    "description": "Filter by status. Defaults to 'needs_action'.",
                },
            },
        },
    },
    {
        "name": "calendar_get_events",
        "description": (
            "Get calendar events from Home Assistant calendar entities. "
            "Returns events within a time range for the specified calendars."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Calendar entity IDs, e.g. ['calendar.work', 'calendar.home']. If omitted, all calendars are queried.",
                },
                "start": {
                    "type": "string",
                    "description": "Start of time range in ISO 8601 format, e.g. '2026-05-23T00:00:00'. Defaults to now.",
                },
                "end": {
                    "type": "string",
                    "description": "End of time range in ISO 8601 format, e.g. '2026-05-30T23:59:59'. Defaults to 7 days from now.",
                },
            },
        },
    },
    {
        "name": "call_service",
        "description": (
            "Call a Home Assistant service directly. Use kyber_ask for most requests; "
            "use this only when you need precise control over a specific service call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain, e.g. 'light'",
                },
                "service": {
                    "type": "string",
                    "description": "Service name, e.g. 'turn_on'",
                },
                "service_data": {
                    "type": "object",
                    "description": "Optional service data, e.g. {\"entity_id\": \"light.bedroom\", \"brightness\": 128}",
                },
            },
            "required": ["domain", "service"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def _handle_kyber_ask(
    hass: HomeAssistant,
    params: dict,
    config: dict,
    user_id: str,
    is_admin: bool,
) -> dict:
    """Run the user prompt through Kyber's full AI pipeline."""
    from .http_api import (
        _run_ai_loop,
        _build_context,
        _build_prompt_sections,
        _inject_knowledge_into_instructions,
    )
    from .knowledge import get_store as get_knowledge_store
    from .token_budget import get_budget_provider, get_store as get_token_budget_store
    from .const import CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS

    prompt: str = str(params.get("prompt", "")).strip()
    if not prompt:
        return {"error": "prompt is required"}

    prompt, _ = _sanitize_user_input(prompt)

    # Rate limiting
    max_rpm = int(config.get(CONF_MAX_REQUESTS_PER_MINUTE, DEFAULT_MAX_REQUESTS_PER_MINUTE))
    allowed, retry_after = _rate_limiter.check(user_id, max_rpm)
    if not allowed:
        return {"error": f"Rate limit exceeded. Retry after {retry_after}s"}
    _rate_limiter.record(user_id)

    entity_id: str = str(config.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    if not entity_id:
        return {"error": "No AI task entity configured in Kyber settings"}

    request_id = str(uuid.uuid4())

    context, context_stats = _build_context(hass)

    kstore = get_knowledge_store(hass)
    await kstore.async_load()

    # Build minimal body_fields (no dashboard context or editor mode for MCP)
    body_fields = {
        "user_prompt": prompt,
        "user_yaml": "",
        "history": [],
        "compacted_summary": "",
        "editor_mode": "chat",
        "dashboards": [],
        "lovelace_resources": [],
        "request_id": request_id,
    }

    # Build instructions using a minimal mock request for user info
    class _MockRequest:
        def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
            if key == "hass_user":
                return _MockUser(user_id, is_admin)
            return default

    class _MockUser:
        def __init__(self, uid: str, admin: bool) -> None:
            self.id = uid
            self.is_admin = admin
            self.name = "MCP client"

    mock_request = _MockRequest()
    sections = _build_prompt_sections(body_fields, context, mock_request)
    instructions = sections["instructions"]
    intent = sections["intent"]

    instructions, _ = await _inject_knowledge_into_instructions(
        hass,
        kstore,
        prompt,
        instructions,
        request_id,
        entity_id=entity_id,
        user_id=user_id or None,
        is_admin=is_admin,
    )

    # Token budget check
    budget_provider = get_budget_provider(config)
    max_daily_tokens = int(config.get(CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS) or 0)
    token_budget_store = get_token_budget_store(hass)
    estimated_tokens = len(instructions) // 4
    budget_allowed, _ = await token_budget_store.async_check(
        budget_provider, max_daily_tokens, estimated_tokens=estimated_tokens
    )
    if not budget_allowed:
        return {"error": "Daily token budget exceeded. Resets at midnight."}

    try:
        response_text, tool_log, _exchange, _cache, _intent, _loop_instr, _aliases, token_usage = \
            await _run_ai_loop(hass, entity_id, instructions, kstore, prompt, request_id, [], intent, config=config)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Kyber MCP: AI loop error: %s", err)
        await token_budget_store.async_record(budget_provider, 0, max_daily_tokens)
        return {"error": f"AI error: {err}"}

    await token_budget_store.async_record(
        budget_provider,
        int(token_usage.get("total_tokens", 0) or 0),
        max_daily_tokens,
    )

    actions_executed = [
        entry for entry in (tool_log or [])
        if entry.get("type") == "tool_call"
    ]

    # Build a compact tool_calls list for the MCP call log
    tool_calls_log = [
        {
            "tool": e.get("tool") or e.get("name", "?"),
            "input": str(e.get("input") or e.get("arguments") or "")[:300],
            "output": str(e.get("output") or e.get("result") or "")[:300],
        }
        for e in (tool_log or [])
        if e.get("type") == "tool_call"
    ]

    return {
        "response": response_text,
        "actions_executed": len(actions_executed),
        "token_usage": token_usage,
        "_tool_calls": tool_calls_log,
        "_prompt": prompt[:200],
    }


async def _handle_get_entity_state(hass: HomeAssistant, params: dict) -> dict:
    """Return current state for requested entity IDs."""
    from homeassistant.helpers import area_registry as ar, entity_registry as er

    entity_ids: list[str] = params.get("entity_ids", [])
    if not entity_ids:
        return {"error": "entity_ids is required"}

    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)

    results = []
    for eid in entity_ids:
        state = hass.states.get(eid)
        if state is None:
            results.append({"entity_id": eid, "found": False})
            continue

        entry = entity_reg.async_get(eid)
        area_name: str | None = None
        if entry and entry.area_id:
            area = area_reg.async_get_area(entry.area_id)
            area_name = area.name if area else None

        results.append({
            "entity_id": eid,
            "found": True,
            "state": state.state,
            "friendly_name": state.attributes.get("friendly_name", eid),
            "attributes": dict(state.attributes),
            "area": area_name,
            "last_changed": state.last_changed.isoformat(),
        })

    return {"entities": results}


async def _handle_list_entities(hass: HomeAssistant, params: dict) -> dict:
    """List HA entities with optional domain/area filter."""
    from homeassistant.helpers import area_registry as ar, entity_registry as er, device_registry as dr

    domain_filter: str | None = params.get("domain", "").strip() or None
    area_filter: str | None = params.get("area", "").strip().lower() or None

    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    # Build entity_id → area_name map
    entity_area: dict[str, str] = {}
    for entry in entity_reg.entities.values():
        if entry.area_id:
            area = area_reg.async_get_area(entry.area_id)
            if area:
                entity_area[entry.entity_id] = area.name
        elif entry.device_id:
            device = device_reg.async_get(entry.device_id)
            if device and device.area_id:
                area = area_reg.async_get_area(device.area_id)
                if area:
                    entity_area[entry.entity_id] = area.name

    results = []
    for state in hass.states.async_all():
        eid = state.entity_id
        if domain_filter and not eid.startswith(f"{domain_filter}."):
            continue
        area_name = entity_area.get(eid)
        if area_filter and (area_name or "").lower() != area_filter:
            continue
        results.append({
            "entity_id": eid,
            "state": state.state,
            "friendly_name": state.attributes.get("friendly_name", eid),
            "area": area_name,
        })

    results.sort(key=lambda e: e["entity_id"])
    return {"entities": results, "count": len(results)}


async def _handle_call_service(hass: HomeAssistant, params: dict) -> dict:
    """Call a HA service directly."""
    domain: str = str(params.get("domain", "")).strip()
    service: str = str(params.get("service", "")).strip()
    service_data: dict = params.get("service_data") or {}

    if not domain or not service:
        return {"error": "domain and service are required"}

    if not hass.services.has_service(domain, service):
        return {"error": f"Service {domain}.{service} not found"}

    try:
        await hass.services.async_call(
            domain, service, service_data, blocking=True
        )
    except Exception as err:  # noqa: BLE001
        return {"error": str(err)}

    return {"status": "ok", "called": f"{domain}.{service}"}


async def _handle_calendar_get_events(hass: HomeAssistant, params: dict) -> dict:
    """Get calendar events from HA calendar entities."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(tz=timezone.utc)
    default_end = now + timedelta(days=7)

    def _parse_dt(val: str | None, default: datetime) -> datetime:
        if not val:
            return default
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return default

    start_dt = _parse_dt(params.get("start"), now)
    end_dt = _parse_dt(params.get("end"), default_end)

    requested_ids: list[str] = params.get("entity_ids") or []
    if requested_ids:
        calendar_ids = [e for e in requested_ids if hass.states.get(e)]
        not_found = [e for e in requested_ids if not hass.states.get(e)]
    else:
        calendar_ids = [s.entity_id for s in hass.states.async_all("calendar")]
        not_found = []

    if not calendar_ids:
        return {"error": "No calendar entities found", "not_found": not_found}

    all_events: list[dict] = []
    errors: list[str] = []

    for entity_id in calendar_ids:
        try:
            result = await hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": entity_id,
                    "start_date_time": start_dt.isoformat(),
                    "end_date_time": end_dt.isoformat(),
                },
                blocking=True,
                return_response=True,
            )
            events = (result or {}).get(entity_id, {}).get("events", [])
            for ev in events:
                ev["calendar"] = entity_id
            all_events.extend(events)
        except Exception as err:  # noqa: BLE001
            errors.append(f"{entity_id}: {err}")

    all_events.sort(key=lambda e: e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", ""))

    return {
        "events": all_events,
        "count": len(all_events),
        "range": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "calendars_queried": calendar_ids,
        **({"not_found": not_found} if not_found else {}),
        **({"errors": errors} if errors else {}),
    }


async def _handle_get_datetime(hass: HomeAssistant, params: dict) -> dict:  # noqa: ARG001
    """Return current date/time and timezone from HA config."""
    from datetime import datetime, timezone
    from homeassistant.util import dt as ha_dt

    now_utc = datetime.now(tz=timezone.utc)
    now_local = ha_dt.as_local(now_utc)
    return {
        "datetime": now_local.isoformat(),
        "date": now_local.strftime("%Y-%m-%d"),
        "time": now_local.strftime("%H:%M:%S"),
        "day_of_week": now_local.strftime("%A"),
        "timezone": str(hass.config.time_zone or "UTC"),
        "utc": now_utc.isoformat(),
    }


async def _handle_get_todo_items(hass: HomeAssistant, params: dict) -> dict:
    """Get items from HA todo list entities."""
    entity_ids_arg: list[str] = params.get("entity_ids") or []
    status_filter: str = str(params.get("status") or "needs_action").lower()

    if entity_ids_arg:
        todo_ids = [e for e in entity_ids_arg if hass.states.get(e)]
        not_found = [e for e in entity_ids_arg if not hass.states.get(e)]
    else:
        todo_ids = [s.entity_id for s in hass.states.async_all("todo")]
        not_found = []

    if not todo_ids:
        return {"error": "No todo entities found", "not_found": not_found}

    all_items: list[dict] = []
    errors: list[str] = []

    for eid in todo_ids:
        try:
            result = await hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": eid},
                blocking=True,
                return_response=True,
            )
            raw_items = (result or {}).get(eid, {}).get("items", [])
            state = hass.states.get(eid)
            list_name = state.attributes.get("friendly_name", eid) if state else eid
            for item in raw_items:
                item_status = str(item.get("status") or "needs_action").lower()
                if status_filter == "all" or item_status == status_filter:
                    all_items.append({
                        "todo_list": eid,
                        "todo_list_name": list_name,
                        "summary": item.get("summary") or "",
                        "status": item_status,
                        "due": item.get("due"),
                        "description": item.get("description"),
                        "uid": item.get("uid"),
                    })
        except Exception as err:  # noqa: BLE001
            errors.append(f"{eid}: {err}")

    return {
        "items": all_items,
        "count": len(all_items),
        "status_filter": status_filter,
        "todo_lists": todo_ids,
        **({"not_found": not_found} if not_found else {}),
        **({"errors": errors} if errors else {}),
    }


# ---------------------------------------------------------------------------
# Main MCP view
# ---------------------------------------------------------------------------

class KyberMCPView(HomeAssistantView):
    """POST /api/kyber/mcp — MCP Streamable HTTP transport.

    Implements MCP protocol version 2024-11-05 over a single JSON-RPC 2.0
    POST endpoint. Supports batch requests (array of requests).

    Clients should POST with:
      Content-Type: application/json
      Authorization: Bearer <long_lived_access_token>
    """

    url = "/api/kyber/mcp"
    name = "api:kyber:mcp"
    requires_auth = True

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json(
                _err(None, -32700, "Parse error"),
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # Support single request or batch
        is_batch = isinstance(body, list)
        requests_list: list[dict] = body if is_batch else [body]

        ha_user = request.get("hass_user")
        user_id = str(getattr(ha_user, "id", "") or "mcp-client")
        is_admin = bool(getattr(ha_user, "is_admin", False))

        responses = []
        for rpc in requests_list:
            if not isinstance(rpc, dict):
                responses.append(_err(None, -32600, "Invalid Request"))
                continue
            t0 = time.monotonic()
            resp = await self._dispatch(hass, rpc, user_id, is_admin)
            latency_ms = round((time.monotonic() - t0) * 1000)

            method: str = rpc.get("method", "")
            params: dict = rpc.get("params") or {}
            tool_name: str | None = params.get("name") if method == "tools/call" else None

            # Determine outcome for the log
            is_notification = resp is None
            if is_notification:
                outcome = "notification"
            elif "error" in resp:
                outcome = "error"
            elif method == "tools/call" and resp.get("result", {}).get("isError"):
                outcome = "tool_error"
            else:
                outcome = "ok"

            # Extract extra detail for kyber_ask calls
            log_extras: dict = {}
            if method == "tools/call" and resp and "result" in resp:
                try:
                    content_text = resp["result"].get("content", [{}])[0].get("text", "{}")
                    data = json.loads(content_text) if content_text.startswith("{") else {}
                    if tool_name == "kyber_ask":
                        log_extras = {
                            "prompt": data.pop("_prompt", str(params.get("arguments", {}).get("prompt", ""))[:200]),
                            "response": str(data.get("response", ""))[:300],
                            "actions_executed": data.get("actions_executed", 0),
                            "token_total": (data.get("token_usage") or {}).get("total_tokens"),
                            "tool_calls": data.pop("_tool_calls", []),
                        }
                    else:
                        args = params.get("arguments") or {}
                        log_extras = {
                            "input": json.dumps(args, ensure_ascii=False)[:300],
                            "output": content_text[:300],
                        }
                except Exception:  # noqa: BLE001
                    pass

            _mcp_log(hass, {
                "ts": time.time(),
                "method": method,
                "tool": tool_name,
                "user_id": user_id,
                "latency_ms": latency_ms,
                "outcome": outcome,
                "error": resp.get("error", {}).get("message") if resp and "error" in resp else None,
                **log_extras,
            })
            _LOGGER.debug(
                "MCP %s%s → %s (%dms)",
                method,
                f"/{tool_name}" if tool_name else "",
                outcome,
                latency_ms,
            )

            if resp is not None:
                responses.append(resp)

        if not responses:
            # All were notifications (no id) — return 204
            return web.Response(status=204)

        if is_batch:
            return self.json(responses)
        return self.json(responses[0])

    async def _dispatch(
        self,
        hass: HomeAssistant,
        rpc: dict,
        user_id: str,
        is_admin: bool,
    ) -> dict | None:
        req_id = rpc.get("id")  # None for notifications
        method: str = str(rpc.get("method", ""))
        params: dict = rpc.get("params") or {}

        # Notifications (no id) — handle but return None
        if method == "notifications/initialized":
            return None

        if method == "ping":
            return _ok(req_id, {})

        if method == "initialize":
            return _ok(req_id, {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": _SERVER_INFO,
                "instructions": (
                    "Kyber is an AI-powered Home Assistant controller. "
                    "Use kyber_ask for natural-language home control. "
                    "Use get_entity_state and list_entities to read device states. "
                    "Use call_service for direct HA service calls."
                ),
            })

        if method == "tools/list":
            return _ok(req_id, {"tools": _TOOLS})

        if method == "tools/call":
            tool_name: str = str(params.get("name", ""))
            tool_args: dict = params.get("arguments") or {}
            return await self._call_tool(hass, req_id, tool_name, tool_args, user_id, is_admin)

        # Unknown method
        return _err(req_id, -32601, f"Method not found: {method}")

    async def _call_tool(
        self,
        hass: HomeAssistant,
        req_id: Any,
        name: str,
        args: dict,
        user_id: str,
        is_admin: bool,
    ) -> dict:
        try:
            if name == "kyber_ask":
                result = await _handle_kyber_ask(hass, args, self._config, user_id, is_admin)
            elif name == "get_entity_state":
                result = await _handle_get_entity_state(hass, args)
            elif name == "list_entities":
                result = await _handle_list_entities(hass, args)
            elif name == "call_service":
                result = await _handle_call_service(hass, args)
            elif name == "calendar_get_events":
                result = await _handle_calendar_get_events(hass, args)
            elif name == "get_datetime":
                result = await _handle_get_datetime(hass, args)
            elif name == "get_todo_items":
                result = await _handle_get_todo_items(hass, args)
            else:
                return _err(req_id, -32602, f"Unknown tool: {name}")
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Kyber MCP: tool %s raised: %s", name, err)
            return _err(req_id, -32603, f"Internal error in {name}: {err}")

        if "error" in result:
            # Return tool errors as MCP content with isError=True
            return _ok(req_id, {
                "content": [{"type": "text", "text": result["error"]}],
                "isError": True,
            })

        return _ok(req_id, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "isError": False,
        })


# ---------------------------------------------------------------------------
# MCP call log view
# ---------------------------------------------------------------------------

class KyberMcpLogView(HomeAssistantView):
    """Expose the MCP call log ring buffer.

    GET    /api/kyber/mcp/log  → {"calls": [...], "total": N}
    DELETE /api/kyber/mcp/log  → {"cleared": true}
    """

    url = "/api/kyber/mcp/log"
    name = "api:kyber:mcp:log"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        buf: list[dict] = list(hass.data.get(_MCP_LOG_KEY) or [])
        return self.json({"calls": buf, "total": len(buf)})

    async def delete(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        hass.data[_MCP_LOG_KEY] = []
        return self.json({"cleared": True})
