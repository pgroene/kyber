from __future__ import annotations

from unittest.mock import patch

from custom_components.kyber.action_history import ActionHistoryStore, get_store


async def test_action_history_record_generates_undo_plan(hass):
    store = ActionHistoryStore(hass)

    entry = await store.async_record(
        "Turn on espresso machine",
        [{
            "type": "call_service",
            "domain": "switch",
            "service": "turn_on",
            "entity_id": "switch.espresso",
        }],
        [{
            "entity_id": "switch.espresso",
            "service": "switch.turn_on",
            "from_state": "off",
            "to_state": "on",
        }],
    )

    assert entry["status"] == "applied"
    assert entry["undo_plan"] == [{
        "type": "call_service",
        "domain": "switch",
        "service": "turn_off",
        "entity_id": "switch.espresso",
        "service_data": {},
        "description": "Undo switch.turn_on for switch.espresso",
    }]

    entries = await store.async_list()
    assert entries[0]["summary"] == "Turn on espresso machine"
    assert entries[0]["entity_changes"][0]["to_state"] == "on"


async def test_action_history_async_undo_marks_entry_undone(hass):
    store = ActionHistoryStore(hass)
    entry = await store.async_record(
        "Turn off bedroom light",
        [{
            "type": "call_service",
            "domain": "light",
            "service": "turn_off",
            "entity_id": "light.bedroom",
        }],
        [],
    )

    undo_plan = await store.async_undo(entry["id"])
    updated = await store.async_get(entry["id"])

    assert undo_plan[0]["service"] == "turn_on"
    assert updated is not None
    assert updated["status"] == "undone"


async def test_action_history_list_returns_newest_first(hass):
    store = ActionHistoryStore(hass)
    first = await store.async_record("First", [], [])
    second = await store.async_record("Second", [], [])

    entries = await store.async_list(limit=2)

    assert [entry["id"] for entry in entries] == [second["id"], first["id"]]


async def test_action_history_undo_endpoint_executes_reverse_service(hass, setup_integration, hass_client):
    calls: list[tuple[str, str, dict]] = []

    async def _handle_turn_off(call):
        calls.append((call.domain, call.service, dict(call.data or {})))

    hass.services.async_register("switch", "turn_off", _handle_turn_off)
    store = get_store(hass)
    entry = await store.async_record(
        "Turn on espresso machine",
        [{
            "type": "call_service",
            "domain": "switch",
            "service": "turn_on",
            "entity_id": "switch.espresso",
        }],
        [{
            "entity_id": "switch.espresso",
            "service": "switch.turn_on",
            "from_state": "off",
            "to_state": "on",
        }],
        user_id="user-1",
    )

    client = await hass_client()
    with patch("custom_components.kyber.action_history._user_id_from_request", return_value="user-1"):
        resp = await client.post(f"/api/kyber/history/actions/{entry['id']}/undo")

    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert calls == [("switch", "turn_off", {"entity_id": "switch.espresso"})]

    updated = await store.async_get(entry["id"])
    assert updated is not None
    assert updated["status"] == "undone"


async def test_action_history_entry_view_returns_entry(hass, setup_integration, hass_client):
    """GET /api/kyber/history/actions/{entry_id} returns the entry by ID."""
    store = get_store(hass)
    entry = await store.async_record(
        "Turn on kitchen light",
        [{
            "type": "call_service",
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.kitchen",
        }],
        [],
        user_id="user-1",
    )

    client = await hass_client()
    with patch("custom_components.kyber.action_history._user_id_from_request", return_value="user-1"):
        resp = await client.get(f"/api/kyber/history/actions/{entry['id']}")

    assert resp.status == 200
    data = await resp.json()
    assert data["id"] == entry["id"]
    assert data["summary"] == "Turn on kitchen light"
    assert data["status"] == "applied"
    assert len(data["undo_plan"]) == 1
    assert data["undo_plan"][0]["service"] == "turn_off"


async def test_action_history_entry_view_returns_404_for_unknown_id(hass, setup_integration, hass_client):
    """GET /api/kyber/history/actions/{id} returns 404 when entry is not found."""
    client = await hass_client()
    with patch("custom_components.kyber.action_history._user_id_from_request", return_value="user-1"):
        resp = await client.get("/api/kyber/history/actions/nonexistent-id")
    assert resp.status == 404


async def test_action_history_entry_view_returns_undone_status(hass, setup_integration, hass_client):
    """GET /api/kyber/history/actions/{id} reflects updated status after undo."""
    store = get_store(hass)
    entry = await store.async_record(
        "Turn off bedroom light",
        [{
            "type": "call_service",
            "domain": "light",
            "service": "turn_off",
            "entity_id": "light.bedroom",
        }],
        [],
        user_id="user-1",
    )
    await store.async_mark_status(entry["id"], "undone", user_id="user-1")

    client = await hass_client()
    with patch("custom_components.kyber.action_history._user_id_from_request", return_value="user-1"):
        resp = await client.get(f"/api/kyber/history/actions/{entry['id']}")

    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "undone"
