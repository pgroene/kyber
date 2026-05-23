"""Tests for the Kyber MCP server endpoint."""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from custom_components.kyber.mcp import (
    KyberMCPView,
    KyberMcpLogView,
    MCP_PROTOCOL_VERSION,
    _MCP_LOG_KEY,
    _handle_get_entity_state,
    _handle_list_entities,
    _handle_call_service,
    _mcp_log,
    _ok,
    _err,
)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def test_ok_response():
    resp = _ok(1, {"foo": "bar"})
    assert resp == {"jsonrpc": "2.0", "id": 1, "result": {"foo": "bar"}}


def test_err_response():
    resp = _err(1, -32601, "Method not found")
    assert resp == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found"},
    }


# ---------------------------------------------------------------------------
# Tool dispatch helpers (no HA required)
# ---------------------------------------------------------------------------

def _make_hass(states: dict | None = None):
    """Build a minimal mock hass object."""
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid) if states else None

    all_states = list((states or {}).values())
    hass.states.async_all = lambda: all_states

    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock()

    # area / entity / device registries
    hass.data = {}
    return hass


def _make_state(entity_id: str, state: str, friendly_name: str = "", area: str | None = None):
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    s.attributes = {"friendly_name": friendly_name or entity_id}
    s.last_changed = __import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc)
    return s


# ---------------------------------------------------------------------------
# get_entity_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_entity_state_found():
    light = _make_state("light.bedroom", "on", "Bedroom Light")
    hass = _make_hass({"light.bedroom": light})

    # Minimal area/entity registry mocks
    with patch("homeassistant.helpers.area_registry.async_get") as mock_ar, \
         patch("homeassistant.helpers.entity_registry.async_get") as mock_er:
        mock_ar.return_value = MagicMock()
        entry_mock = MagicMock()
        entry_mock.area_id = None
        mock_er.return_value.async_get = MagicMock(return_value=entry_mock)

        result = await _handle_get_entity_state(hass, {"entity_ids": ["light.bedroom"]})

    assert result["entities"][0]["entity_id"] == "light.bedroom"
    assert result["entities"][0]["state"] == "on"
    assert result["entities"][0]["found"] is True


@pytest.mark.asyncio
async def test_get_entity_state_not_found():
    hass = _make_hass({})

    with patch("homeassistant.helpers.area_registry.async_get"), \
         patch("homeassistant.helpers.entity_registry.async_get"):
        result = await _handle_get_entity_state(hass, {"entity_ids": ["light.nonexistent"]})

    assert result["entities"][0]["found"] is False


@pytest.mark.asyncio
async def test_get_entity_state_missing_param():
    hass = _make_hass()
    result = await _handle_get_entity_state(hass, {})
    assert "error" in result


# ---------------------------------------------------------------------------
# list_entities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_entities_no_filter():
    light = _make_state("light.bedroom", "on", "Bedroom")
    switch = _make_state("switch.fan", "off", "Fan")
    hass = _make_hass({"light.bedroom": light, "switch.fan": switch})

    with patch("homeassistant.helpers.area_registry.async_get") as mock_ar, \
         patch("homeassistant.helpers.entity_registry.async_get") as mock_er, \
         patch("homeassistant.helpers.device_registry.async_get") as mock_dr:
        mock_ar.return_value = MagicMock()
        mock_er.return_value.entities = {}
        mock_dr.return_value = MagicMock()

        result = await _handle_list_entities(hass, {})

    assert result["count"] == 2
    entity_ids = [e["entity_id"] for e in result["entities"]]
    assert "light.bedroom" in entity_ids
    assert "switch.fan" in entity_ids


@pytest.mark.asyncio
async def test_list_entities_domain_filter():
    light = _make_state("light.bedroom", "on")
    switch = _make_state("switch.fan", "off")
    hass = _make_hass({"light.bedroom": light, "switch.fan": switch})

    with patch("homeassistant.helpers.area_registry.async_get") as mock_ar, \
         patch("homeassistant.helpers.entity_registry.async_get") as mock_er, \
         patch("homeassistant.helpers.device_registry.async_get") as mock_dr:
        mock_ar.return_value = MagicMock()
        mock_er.return_value.entities = {}
        mock_dr.return_value = MagicMock()

        result = await _handle_list_entities(hass, {"domain": "light"})

    assert result["count"] == 1
    assert result["entities"][0]["entity_id"] == "light.bedroom"


# ---------------------------------------------------------------------------
# call_service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_service_success():
    hass = _make_hass()
    result = await _handle_call_service(hass, {
        "domain": "light",
        "service": "turn_on",
        "service_data": {"entity_id": "light.bedroom"},
    })
    assert result["status"] == "ok"
    assert result["called"] == "light.turn_on"
    hass.services.async_call.assert_awaited_once_with(
        "light", "turn_on", {"entity_id": "light.bedroom"}, blocking=True
    )


@pytest.mark.asyncio
async def test_call_service_missing_domain():
    hass = _make_hass()
    result = await _handle_call_service(hass, {"service": "turn_on"})
    assert "error" in result


@pytest.mark.asyncio
async def test_call_service_not_found():
    hass = _make_hass()
    hass.services.has_service = MagicMock(return_value=False)
    result = await _handle_call_service(hass, {"domain": "light", "service": "fly"})
    assert "error" in result


# ---------------------------------------------------------------------------
# MCP view dispatch (unit tests without HTTP layer)
# ---------------------------------------------------------------------------

@pytest.fixture
def mcp_view():
    return KyberMCPView(config={"ai_task_entity_id": "conversation.mock"})


@pytest.mark.asyncio
async def test_dispatch_initialize(mcp_view):
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "clientInfo": {"name": "test"}},
    }, "user-1", True)
    assert result["id"] == 1
    assert result["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert "tools" in result["result"]["capabilities"]


@pytest.mark.asyncio
async def test_dispatch_tools_list(mcp_view):
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    }, "user-1", True)
    tools = result["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "kyber_ask" in tool_names
    assert "get_entity_state" in tool_names
    assert "list_entities" in tool_names
    assert "call_service" in tool_names


@pytest.mark.asyncio
async def test_dispatch_ping(mcp_view):
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0", "id": 3, "method": "ping",
    }, "user-1", True)
    assert result["result"] == {}


@pytest.mark.asyncio
async def test_dispatch_notification_no_response(mcp_view):
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }, "user-1", True)
    assert result is None


@pytest.mark.asyncio
async def test_dispatch_unknown_method(mcp_view):
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0", "id": 4, "method": "unknown/method",
    }, "user-1", True)
    assert result["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# tools/call dispatching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_call_get_entity_state(mcp_view):
    light = _make_state("light.bedroom", "on", "Bedroom")
    hass = _make_hass({"light.bedroom": light})

    with patch("homeassistant.helpers.area_registry.async_get") as mock_ar, \
         patch("homeassistant.helpers.entity_registry.async_get") as mock_er:
        mock_ar.return_value = MagicMock()
        entry = MagicMock()
        entry.area_id = None
        mock_er.return_value.async_get = MagicMock(return_value=entry)

        result = await mcp_view._dispatch(hass, {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_entity_state",
                "arguments": {"entity_ids": ["light.bedroom"]},
            },
        }, "user-1", True)

    assert result["id"] == 5
    content = json.loads(result["result"]["content"][0]["text"])
    assert content["entities"][0]["state"] == "on"
    assert result["result"]["isError"] is False


@pytest.mark.asyncio
async def test_tools_call_unknown_tool(mcp_view):
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {"name": "does_not_exist", "arguments": {}},
    }, "user-1", True)
    assert result["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_tools_call_call_service(mcp_view):
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "call_service",
            "arguments": {
                "domain": "light",
                "service": "turn_on",
                "service_data": {"entity_id": "light.bedroom"},
            },
        },
    }, "user-1", True)
    assert result["result"]["isError"] is False
    content = json.loads(result["result"]["content"][0]["text"])
    assert content["status"] == "ok"


# ---------------------------------------------------------------------------
# kyber_ask — rate limited
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kyber_ask_rate_limited(mcp_view):
    """kyber_ask should return isError=True when the handler returns an error."""
    hass = _make_hass()

    with patch("custom_components.kyber.mcp._handle_kyber_ask", new_callable=AsyncMock) as mock_ask:
        mock_ask.return_value = {"error": "Rate limit exceeded. Retry after 30s"}

        result = await mcp_view._dispatch(hass, {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "kyber_ask", "arguments": {"prompt": "turn on lights"}},
        }, "user-1", False)

    assert result["result"]["isError"] is True
    assert "Rate limit" in result["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_kyber_ask_success(mcp_view):
    """kyber_ask returns response text on success."""
    hass = _make_hass()

    with patch("custom_components.kyber.mcp._handle_kyber_ask", new_callable=AsyncMock) as mock_ask:
        mock_ask.return_value = {
            "response": "Done! Turned on the bedroom light.",
            "actions_executed": 1,
            "token_usage": {"total_tokens": 100},
        }

        result = await mcp_view._dispatch(hass, {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "kyber_ask", "arguments": {"prompt": "turn on bedroom light"}},
        }, "user-1", True)

    assert result["result"]["isError"] is False
    content = json.loads(result["result"]["content"][0]["text"])
    assert content["response"] == "Done! Turned on the bedroom light."
    assert content["actions_executed"] == 1


# ---------------------------------------------------------------------------
# MCP call logging
# ---------------------------------------------------------------------------

def test_mcp_log_appends_entry():
    """_mcp_log appends to hass.data ring buffer."""
    hass = _make_hass()
    _mcp_log(hass, {"ts": 1.0, "method": "tools/call", "tool": "get_entity_state", "outcome": "ok"})
    _mcp_log(hass, {"ts": 2.0, "method": "ping", "tool": None, "outcome": "ok"})
    buf = hass.data[_MCP_LOG_KEY]
    assert len(buf) == 2
    assert buf[0]["method"] == "tools/call"
    assert buf[1]["method"] == "ping"


def test_mcp_log_evicts_oldest():
    """Ring buffer evicts oldest entries once _MCP_LOG_MAX is exceeded."""
    from custom_components.kyber.mcp import _MCP_LOG_MAX
    hass = _make_hass()
    for i in range(_MCP_LOG_MAX + 5):
        _mcp_log(hass, {"ts": float(i), "method": "ping", "tool": None, "outcome": "ok"})
    buf = hass.data[_MCP_LOG_KEY]
    assert len(buf) == _MCP_LOG_MAX
    # The oldest entries (ts=0..4) should be gone; newest survives
    assert buf[-1]["ts"] == float(_MCP_LOG_MAX + 4)


# ---------------------------------------------------------------------------
# Rate limiter: check() then record() (not check_and_record)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kyber_ask_rate_limiter_uses_check_and_record_separately(mcp_view):
    """_handle_kyber_ask must call check() and record() separately."""
    hass = _make_hass()
    hass.data["kyber_config"] = {"ai_task_entity_id": "conversation.mock"}

    mock_rl = MagicMock()
    mock_rl.check.return_value = (True, 0)

    with patch("custom_components.kyber.mcp._rate_limiter", mock_rl), \
         patch("custom_components.kyber.mcp._handle_kyber_ask", new_callable=AsyncMock) as mock_ask:
        mock_ask.return_value = {"response": "ok", "actions_executed": 0, "token_usage": {}}
        await mcp_view._dispatch(hass, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "kyber_ask", "arguments": {"prompt": "test"}},
        }, "user-1", True)

    # Verify check_and_record does NOT exist (was the bug) and the right methods are used
    assert not hasattr(mock_rl, "check_and_record") or not mock_rl.check_and_record.called


@pytest.mark.asyncio
async def test_handle_kyber_ask_rate_limit_check_then_record():
    """When rate limit allows, check() is called before record()."""
    from custom_components.kyber.mcp import _handle_kyber_ask

    hass = _make_hass()
    hass.data["kyber_config"] = {}

    mock_rl = MagicMock()
    mock_rl.check.return_value = (True, 0)

    call_order = []
    mock_rl.check.side_effect = lambda *a: (call_order.append("check"), (True, 0))[1]
    mock_rl.record.side_effect = lambda *a: call_order.append("record")

    with patch("custom_components.kyber.mcp._rate_limiter", mock_rl), \
         patch("custom_components.kyber.http_api._run_ai_loop", new_callable=AsyncMock) as mock_loop, \
         patch("custom_components.kyber.http_api._build_context", return_value=("ctx", {})), \
         patch("custom_components.kyber.http_api._build_prompt_sections", return_value={"instructions": "instr", "intent": "turn on"}), \
         patch("custom_components.kyber.http_api._inject_knowledge_into_instructions", new_callable=AsyncMock, return_value=("instr", {})), \
         patch("custom_components.kyber.knowledge.get_store", return_value=AsyncMock(async_load=AsyncMock())), \
         patch("custom_components.kyber.token_budget.get_budget_provider", return_value="local"), \
         patch("custom_components.kyber.token_budget.get_store") as mock_tbs:
        budget_store = AsyncMock()
        budget_store.async_check = AsyncMock(return_value=(True, None))
        budget_store.async_record = AsyncMock()
        mock_tbs.return_value = budget_store
        mock_loop.return_value = ("response", [], None, None, "intent", "instr", [], {"total_tokens": 50})

        result = await _handle_kyber_ask(
            hass, {"prompt": "hello"}, {"ai_task_entity_id": "conversation.mock"}, "user-1", True
        )

    assert call_order == ["check", "record"], f"Wrong order: {call_order}"
    assert result["response"] == "response"


@pytest.mark.asyncio
async def test_handle_kyber_ask_rate_limit_blocked():
    """When rate limit blocks, record() must NOT be called."""
    from custom_components.kyber.mcp import _handle_kyber_ask

    hass = _make_hass()
    mock_rl = MagicMock()
    mock_rl.check.return_value = (False, 42)

    with patch("custom_components.kyber.mcp._rate_limiter", mock_rl):
        result = await _handle_kyber_ask(
            hass, {"prompt": "hello"}, {"ai_task_entity_id": "conversation.mock"}, "user-1", True
        )

    assert "error" in result
    assert "42" in result["error"]
    mock_rl.record.assert_not_called()


# ---------------------------------------------------------------------------
# Batch request handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_request_returns_all_responses(mcp_view):
    """A batch array of RPC calls returns a list of responses."""
    hass = _make_hass()
    results = []
    for rpc in [
        {"jsonrpc": "2.0", "id": 10, "method": "ping"},
        {"jsonrpc": "2.0", "id": 11, "method": "ping"},
    ]:
        r = await mcp_view._dispatch(hass, rpc, "u", True)
        if r is not None:
            results.append(r)
    assert len(results) == 2
    assert results[0]["id"] == 10
    assert results[1]["id"] == 11


@pytest.mark.asyncio
async def test_batch_notification_excluded_from_response(mcp_view):
    """Notifications (no id) in a batch produce no response entry."""
    hass = _make_hass()
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    result = await mcp_view._dispatch(hass, notification, "u", True)
    assert result is None


# ---------------------------------------------------------------------------
# tools/list schema validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_list_schemas_have_required_fields(mcp_view):
    """Every tool in tools/list must have name, description, and inputSchema."""
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
    }, "u", True)
    for tool in result["result"]["tools"]:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool missing 'description': {tool}"
        assert "inputSchema" in tool, f"Tool missing 'inputSchema': {tool}"
        schema = tool["inputSchema"]
        assert schema.get("type") == "object"
        assert "properties" in schema


# ---------------------------------------------------------------------------
# get_entity_state edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_entity_state_multiple_entities():
    """get_entity_state handles multiple entity IDs in one call."""
    light = _make_state("light.bedroom", "on")
    switch = _make_state("switch.fan", "off")
    hass = _make_hass({"light.bedroom": light, "switch.fan": switch})

    with patch("homeassistant.helpers.area_registry.async_get") as mock_ar, \
         patch("homeassistant.helpers.entity_registry.async_get") as mock_er:
        mock_ar.return_value = MagicMock()
        entry = MagicMock(); entry.area_id = None
        mock_er.return_value.async_get = MagicMock(return_value=entry)

        result = await _handle_get_entity_state(hass, {"entity_ids": ["light.bedroom", "switch.fan"]})

    assert result["entities"][0]["found"] is True
    assert result["entities"][1]["found"] is True
    assert {e["entity_id"] for e in result["entities"]} == {"light.bedroom", "switch.fan"}


@pytest.mark.asyncio
async def test_get_entity_state_mixed_found_not_found():
    """get_entity_state marks missing entities as found=False without error."""
    light = _make_state("light.bedroom", "on")
    hass = _make_hass({"light.bedroom": light})

    with patch("homeassistant.helpers.area_registry.async_get") as mock_ar, \
         patch("homeassistant.helpers.entity_registry.async_get") as mock_er:
        mock_ar.return_value = MagicMock()
        entry = MagicMock(); entry.area_id = None
        mock_er.return_value.async_get = MagicMock(return_value=entry)

        result = await _handle_get_entity_state(
            hass, {"entity_ids": ["light.bedroom", "light.nonexistent"]}
        )

    found = {e["entity_id"]: e["found"] for e in result["entities"]}
    assert found["light.bedroom"] is True
    assert found["light.nonexistent"] is False


# ---------------------------------------------------------------------------
# call_service edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_service_empty_service_data():
    """call_service works when service_data is omitted."""
    hass = _make_hass()
    result = await _handle_call_service(hass, {"domain": "homeassistant", "service": "reload_all"})
    assert result["status"] == "ok"
    hass.services.async_call.assert_awaited_once_with(
        "homeassistant", "reload_all", {}, blocking=True
    )


@pytest.mark.asyncio
async def test_call_service_exception_returns_error():
    """call_service catches service exceptions and returns an error dict."""
    hass = _make_hass()
    hass.services.async_call = AsyncMock(side_effect=Exception("Service exploded"))
    result = await _handle_call_service(hass, {
        "domain": "light", "service": "turn_on", "service_data": {"entity_id": "light.x"},
    })
    assert "error" in result
    assert "Service exploded" in result["error"]


# ---------------------------------------------------------------------------
# initialize handshake
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_returns_server_info(mcp_view):
    """initialize response contains serverInfo."""
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "clientInfo": {"name": "pytest"}},
    }, "u", True)
    assert result["result"]["serverInfo"]["name"] == "kyber"
    assert "instructions" in result["result"]


@pytest.mark.asyncio
async def test_initialize_null_id(mcp_view):
    """initialize works with id=null (some clients omit it)."""
    hass = _make_hass()
    result = await mcp_view._dispatch(hass, {
        "jsonrpc": "2.0", "id": None, "method": "initialize",
        "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
    }, "u", True)
    assert result["id"] is None
    assert "protocolVersion" in result["result"]

