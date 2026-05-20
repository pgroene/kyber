"""Functional tests for the Kyber HTTP API views.

Covers all four endpoints:
  - POST /api/kyber/complete
  - POST /api/kyber/execute
  - POST /api/kyber/parse_yaml   (→ tests/test_parse_yaml.py)
  - POST /api/kyber/summarize    (→ tests/test_summarize.py)

Helper functions (_extract_yaml_blocks, _extract_plan_block, _build_service_undo)
are tested in tests/test_helpers.py.
"""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from custom_components.kyber.const import DOMAIN
from custom_components.kyber.http_api import KyberView, KyberSaveView, KyberExecuteView, KyberSummarizeView
from custom_components.kyber.knowledge import get_store as get_knowledge_store

# Correct patch target — all tests must use this path
_PATCH_GENERATE = "custom_components.kyber.http_api.async_generate_data"
_PATCH_GENERATE_DEBUG = "custom_components.kyber.debug_and_diagnostics.async_generate_data"


def _make_ai_result(text: str) -> MagicMock:
    """Create a mock async_generate_data result with .data = text."""
    r = MagicMock()
    r.data = text
    return r


# ──────────────────────────────────────────────────────────────────────────────
# /complete — authentication
# ──────────────────────────────────────────────────────────────────────────────

async def test_unauthenticated_request_rejected(
    hass: HomeAssistant, setup_integration
) -> None:
    """All Kyber views must require authentication (requires_auth = True)."""
    assert KyberView.requires_auth is True
    assert KyberSaveView.requires_auth is True
    assert KyberExecuteView.requires_auth is True
    assert KyberSummarizeView.requires_auth is True


async def test_chat_history_roundtrip_for_current_user(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Chat history endpoint should load, save, and return current-user history."""
    client = await hass_client()

    resp = await client.get("/api/kyber/history")
    assert resp.status == 200
    body = await resp.json()
    assert body["history"] == []
    assert body["compacted_summary"] == ""
    assert "session_id" in body
    assert "session_name" in body

    payload = {
        "history": [
            {"role": "user", "content": "Turn on kitchen lights"},
            {"role": "assistant", "content": "Done"},
        ],
        "compacted_summary": "User asked to turn on kitchen lights.",
    }
    save_resp = await client.post("/api/kyber/history", json=payload)
    assert save_resp.status == 200
    assert await save_resp.json() == {"status": "ok"}

    reload_resp = await client.get("/api/kyber/history")
    assert reload_resp.status == 200
    reload_body = await reload_resp.json()
    assert reload_body["history"] == payload["history"]
    assert reload_body["compacted_summary"] == payload["compacted_summary"]


async def test_chat_history_is_user_scoped(
    hass: HomeAssistant,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
) -> None:
    """Chat history should be isolated per authenticated Home Assistant user."""
    admin_client = await hass_client()
    readonly_client = await hass_client(hass_read_only_access_token)

    admin_payload = {
        "history": [{"role": "user", "content": "Admin message"}],
        "compacted_summary": "Admin summary",
    }
    ro_payload = {
        "history": [{"role": "user", "content": "Readonly message"}],
        "compacted_summary": "Readonly summary",
    }

    admin_save = await admin_client.post("/api/kyber/history", json=admin_payload)
    assert admin_save.status == 200

    ro_initial = await readonly_client.get("/api/kyber/history")
    assert ro_initial.status == 200
    ro_initial_body = await ro_initial.json()
    assert ro_initial_body["history"] == []
    assert ro_initial_body["compacted_summary"] == ""

    ro_save = await readonly_client.post("/api/kyber/history", json=ro_payload)
    assert ro_save.status == 200

    admin_reload = await admin_client.get("/api/kyber/history")
    assert admin_reload.status == 200
    admin_body = await admin_reload.json()
    assert admin_body["history"] == admin_payload["history"]
    assert admin_body["compacted_summary"] == admin_payload["compacted_summary"]

    ro_reload = await readonly_client.get("/api/kyber/history")
    assert ro_reload.status == 200
    ro_body = await ro_reload.json()
    assert ro_body["history"] == ro_payload["history"]
    assert ro_body["compacted_summary"] == ro_payload["compacted_summary"]


async def test_chat_history_delete_clears_current_user_only(
    hass: HomeAssistant,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
) -> None:
    """DELETE /history should clear only the current authenticated user's active session history."""
    admin_client = await hass_client()
    readonly_client = await hass_client(hass_read_only_access_token)

    await admin_client.post(
        "/api/kyber/history",
        json={
            "history": [{"role": "user", "content": "Admin keep"}],
            "compacted_summary": "Admin keep summary",
        },
    )
    await readonly_client.post(
        "/api/kyber/history",
        json={
            "history": [{"role": "user", "content": "Readonly clear"}],
            "compacted_summary": "Readonly clear summary",
        },
    )

    clear_resp = await readonly_client.delete("/api/kyber/history")
    assert clear_resp.status == 200
    assert await clear_resp.json() == {"status": "ok"}

    ro_reload = await readonly_client.get("/api/kyber/history")
    assert ro_reload.status == 200
    ro_body = await ro_reload.json()
    assert ro_body["history"] == []
    assert ro_body["compacted_summary"] == ""

    admin_reload = await admin_client.get("/api/kyber/history")
    assert admin_reload.status == 200
    admin_body = await admin_reload.json()
    assert admin_body["history"] == [{"role": "user", "content": "Admin keep"}]
    assert admin_body["compacted_summary"] == "Admin keep summary"


# ──────────────────────────────────────────────────────────────────────────────
# /sessions — multi-session management
# ──────────────────────────────────────────────────────────────────────────────


async def test_sessions_list_returns_default_session(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """GET /sessions should return at least one session for a fresh user."""
    client = await hass_client()
    resp = await client.get("/api/kyber/sessions")
    assert resp.status == 200
    body = await resp.json()
    assert "sessions" in body
    assert len(body["sessions"]) >= 1
    assert "active_session" in body
    active = next(s for s in body["sessions"] if s["active"])
    assert active["name"]


async def test_sessions_create_and_switch(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST /sessions should create a new session and switch to it."""
    client = await hass_client()

    create_resp = await client.post("/api/kyber/sessions", json={"name": "Work", "switch": True})
    assert create_resp.status == 200
    created = await create_resp.json()
    assert created["status"] == "ok"
    new_sid = created["session_id"]
    assert created["name"] == "Work"

    list_resp = await client.get("/api/kyber/sessions")
    list_body = await list_resp.json()
    active = next((s for s in list_body["sessions"] if s["active"]), None)
    assert active is not None
    assert active["id"] == new_sid

    # History endpoint should now operate on the new session
    hist_resp = await client.get("/api/kyber/history")
    hist_body = await hist_resp.json()
    assert hist_body["history"] == []
    assert hist_body["session_id"] == new_sid


async def test_sessions_rename(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """PATCH /sessions with action=rename should rename the active session."""
    client = await hass_client()

    list_resp = await client.get("/api/kyber/sessions")
    sid = (await list_resp.json())["active_session"]

    rename_resp = await client.put(
        "/api/kyber/sessions",
        json={"action": "rename", "session_id": sid, "name": "Evening Automation"},
    )
    assert rename_resp.status == 200
    assert (await rename_resp.json())["status"] == "ok"

    list_after = await client.get("/api/kyber/sessions")
    sessions = (await list_after.json())["sessions"]
    renamed = next(s for s in sessions if s["id"] == sid)
    assert renamed["name"] == "Evening Automation"


async def test_sessions_delete_switches_to_other(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """DELETE /sessions should delete the specified session and switch to another."""
    client = await hass_client()

    # Create a second session
    create = await client.post("/api/kyber/sessions", json={"name": "Extra", "switch": False})
    extra_sid = (await create.json())["session_id"]

    # Get active session (should still be the original)
    active_sid = (await (await client.get("/api/kyber/sessions")).json())["active_session"]

    # Delete the extra session
    del_resp = await client.delete("/api/kyber/sessions", json={"session_id": extra_sid})
    assert del_resp.status == 200
    del_body = await del_resp.json()
    assert del_body["active_session"] == active_sid  # original session still active

    # Only one session should remain
    list_resp = await client.get("/api/kyber/sessions")
    sessions = (await list_resp.json())["sessions"]
    assert not any(s["id"] == extra_sid for s in sessions)


# ──────────────────────────────────────────────────────────────────────────────
# /complete — input validation
# ──────────────────────────────────────────────────────────────────────────────

async def test_missing_prompt_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST /api/kyber/complete without a 'prompt' field should return 400."""
    client = await hass_client()
    resp = await client.post("/api/kyber/complete", json={"yaml": "automation:"})
    assert resp.status == 400


async def test_empty_prompt_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST /api/kyber/complete with an empty prompt string should return 400."""
    client = await hass_client()
    resp = await client.post("/api/kyber/complete", json={"prompt": "   "})
    assert resp.status == 400


# ──────────────────────────────────────────────────────────────────────────────
# /complete — context building
# ──────────────────────────────────────────────────────────────────────────────

async def test_context_includes_entity_ids(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The instructions sent to async_generate_data should contain domain stats (not raw entity IDs)."""
    hass.states.async_set("light.living_room", "on")
    hass.states.async_set("switch.bedroom_fan", "off")

    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("```yaml\nautomation:\n  alias: test\n```")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={"yaml": "automation:", "prompt": "Add a condition"},
        )

    assert resp.status == 200
    # New format: domain stats (e.g. "light: 1") instead of raw entity IDs
    assert "light" in captured["v"]
    assert "switch" in captured["v"]


async def test_context_includes_areas(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The instructions should contain area names from the area registry."""
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")
    area_reg.async_create("Bedroom")

    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("```yaml\nautomation:\n  alias: test\n```")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={"yaml": "automation:", "prompt": "Add a condition"},
        )

    assert resp.status == 200
    assert "Living Room" in captured["v"]
    assert "Bedroom" in captured["v"]


async def test_context_includes_labels(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The instructions should contain label names from the label registry."""
    label_reg = lr.async_get(hass)
    label_reg.async_create("Outdoor")
    label_reg.async_create("Security")

    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("```yaml\nautomation:\n  alias: test\n```")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post("/api/kyber/complete", json={"prompt": "help"})

    assert resp.status == 200
    instr = captured["v"]
    assert "Outdoor" in instr or "outdoor" in instr.lower()
    assert "Security" in instr or "security" in instr.lower()


async def test_context_includes_automations(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Automations are accessible via the search_automations tool; the home summary
    should reflect the automation count."""
    hass.states.async_set(
        "automation.morning_lights", "on",
        attributes={"friendly_name": "Morning Lights"},
    )

    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post("/api/kyber/complete", json={"prompt": "list automations"})

    assert resp.status == 200
    # Automations are accessed via search_automations/get_automation tools, not
    # pre-listed in the context. Verify the home summary counter reflects them.
    assert "1 automations" in captured["v"]


async def test_context_includes_scripts(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Scripts are accessible via the search_automations tool; the home summary
    should reflect the script count."""
    hass.states.async_set(
        "script.welcome_home", "off",
        attributes={"friendly_name": "Welcome Home"},
    )

    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post("/api/kyber/complete", json={"prompt": "list scripts"})

    assert resp.status == 200
    # Scripts are accessed via tools, not pre-listed in context.
    assert "1 scripts" in captured["v"]


async def test_dashboards_included_in_context(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """The instructions should list dashboards provided by the frontend."""
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={
                "prompt": "what dashboards do I have?",
                "dashboards": [
                    {"title": "Home", "url_path": "home", "mode": "storage"},
                    {"title": "Energy", "url_path": "energy", "mode": "storage"},
                ],
            },
        )

    assert resp.status == 200
    instr = captured["v"]
    assert "home" in instr
    assert "energy" in instr or "Energy" in instr


async def test_history_and_summary_included_in_context(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Conversation history and compacted_summary should appear in the instructions."""
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={
                "prompt": "continue",
                "compacted_summary": "User asked about lights.",
                "history": [
                    {"role": "user", "content": "Turn off lights"},
                    {"role": "assistant", "content": "Done."},
                ],
            },
        )

    assert resp.status == 200
    instr = captured["v"]
    assert "User asked about lights" in instr
    assert "Turn off lights" in instr
    assert "Done." in instr


async def test_dashboard_editor_mode_injects_yaml_section(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """When editor_mode=dashboard the instructions must include the dashboard YAML section."""
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("```yaml\ntitle: Home\n```")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={
                "prompt": "add a clock card",
                "editor_mode": "dashboard",
                "yaml": "title: My Dashboard\nviews: []",
            },
        )

    assert resp.status == 200
    instr = captured["v"]
    assert "DASHBOARD EDITOR" in instr.upper()
    assert "title: My Dashboard" in instr


# ──────────────────────────────────────────────────────────────────────────────
# /complete — AI entity and response parsing
# ──────────────────────────────────────────────────────────────────────────────

async def test_ai_task_called_with_correct_entity(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """async_generate_data should be called with the configured ai_task_entity_id."""
    called_with = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        called_with["entity_id"] = entity_id
        return _make_ai_result("```yaml\nautomation:\n  alias: test\n```")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        await client.post("/api/kyber/complete", json={"prompt": "help"})

    assert called_with["entity_id"] == "ai_task.ollama_ai_task"


async def test_yaml_blocks_extracted(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Response should parse ```yaml``` blocks from the AI response text."""
    ai_response = (
        "Sure!\n"
        "```yaml\n"
        "automation:\n"
        "  alias: My Automation\n"
        "  trigger: []\n"
        "```\n"
        "That's it."
    )

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=lambda *a, **kw: _make_ai_result(ai_response)):
        resp = await client.post("/api/kyber/complete", json={"prompt": "help"})

    assert resp.status == 200
    data = await resp.json()
    assert data["response"] == ai_response
    assert len(data["yaml_blocks"]) == 1
    assert "alias: My Automation" in data["yaml_blocks"][0]


async def test_plan_block_extracted(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Response should parse the ```plan``` JSON block and return it as 'plan'."""
    plan_json = '{"overview": "Rename lights", "actions": [{"type": "rename_entity", "entity_id": "light.desk", "name": "Desk Light"}]}'
    ai_response = f"Here is my plan:\n```plan\n{plan_json}\n```"

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=lambda *a, **kw: _make_ai_result(ai_response)):
        resp = await client.post("/api/kyber/complete", json={"prompt": "rename desk light"})

    assert resp.status == 200
    data = await resp.json()
    assert data["plan"] is not None
    assert data["plan"]["overview"] == "Rename lights"
    assert data["plan"]["actions"][0]["type"] == "rename_entity"


async def test_no_plan_block_returns_null_plan(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """When the AI response contains no plan block, 'plan' should be null."""
    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=lambda *a, **kw: _make_ai_result("Just a text answer.")):
        resp = await client.post("/api/kyber/complete", json={"prompt": "hello"})

    assert resp.status == 200
    data = await resp.json()
    assert data["plan"] is None


async def test_ai_task_failure_returns_503(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """When async_generate_data raises HomeAssistantError, return 503."""
    async def failing(*a, **kw):
        raise HomeAssistantError("Ollama is not available")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=failing):
        resp = await client.post("/api/kyber/complete", json={"prompt": "help"})

    assert resp.status == 503


# ──────────────────────────────────────────────────────────────────────────────
# /execute — validation
# ──────────────────────────────────────────────────────────────────────────────

async def test_execute_empty_actions_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST /api/kyber/execute with empty actions list should return 400."""
    client = await hass_client()
    resp = await client.post("/api/kyber/execute", json={"actions": []})
    assert resp.status == 400


async def test_execute_unauthenticated_returns_401(
    hass: HomeAssistant, setup_integration, hass_client_no_auth
) -> None:
    """Unauthenticated /execute requests should return 401."""
    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/kyber/execute",
        json={"actions": [{"type": "rename_entity", "entity_id": "light.x", "name": "X"}]},
    )
    assert resp.status == 401


async def test_execute_unknown_entity_returns_error(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute should return an error result for entities not in the registry."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "assign_label", "entity_id": "light.nonexistent", "label_id": "outdoor"}]},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["results"][0]["status"] == "error"


# ──────────────────────────────────────────────────────────────────────────────
# /labels
# ──────────────────────────────────────────────────────────────────────────────

async def test_labels_endpoint_includes_narrator_metadata_and_aliases(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Labels endpoint should enrich entities with narrator metadata and aliases."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)
    area = area_reg.async_create("Living Room")
    entry = entity_reg.async_get_or_create("light", "test", "lamp_labels", suggested_object_id="lamp_labels")
    label = label_reg.async_create("kyber:climate")
    entity_reg.async_update_entity(entry.entity_id, area_id=area.id, labels={label.label_id})
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Reading Lamp"})

    kstore = get_knowledge_store(hass)
    await kstore.async_load()
    await kstore.async_add(
        "general",
        "A narrated lamp description.",
        subject=entry.entity_id,
        tags=[entry.entity_id, "light"],
        source="entity_narrator",
        provenance="AI narrator v6",
    )
    await kstore.async_add(
        "entity_alias",
        entry.entity_id,
        subject="reading light",
        tags=[entry.entity_id, "search_alias"],
        source="entity_narrator",
    )
    await kstore.async_add(
        "entity_alias",
        entry.entity_id,
        subject="cozy lamp",
        tags=[entry.entity_id, "search_alias"],
        source="entity_narrator",
    )

    client = await hass_client()
    resp = await client.get("/api/kyber/labels")

    assert resp.status == 200
    data = await resp.json()
    entity = data[label.label_id]["entities"][0]
    assert entity == {
        "entity_id": entry.entity_id,
        "name": entry.entity_id,
        "description": "A narrated lamp description.",
        "domain": "light",
        "area": "Living Room",
        "provenance": "AI narrator v6",
        "aliases": ["cozy lamp", "reading light"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# /execute — label actions
# ──────────────────────────────────────────────────────────────────────────────

async def test_execute_assign_label(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute endpoint should assign a label to an entity and return undo_action."""
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)
    entry = entity_reg.async_get_or_create("light", "test", "lamp_1", suggested_object_id="lamp_1")
    label_reg.async_create("outdoor")

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"actions": [{"type": "assign_label", "entity_id": entry.entity_id, "label_id": "outdoor"}], "approved": True},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert result["undo_action"]["type"] == "remove_label"
    updated = entity_reg.async_get(entry.entity_id)
    assert "outdoor" in updated.labels


async def test_execute_assign_kyber_label_creates_knowledge_entry_when_missing(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Assigning a kyber label should seed general knowledge when none exists."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)
    area = area_reg.async_create("Kitchen")
    entry = entity_reg.async_get_or_create(
        "sensor",
        "mqtt",
        "coffee_maker_power",
        suggested_object_id="coffee_maker_power",
    )
    entity_reg.async_update_entity(entry.entity_id, area_id=area.id)
    label = label_reg.async_create("kyber:coffee")
    hass.states.async_set(
        entry.entity_id,
        "on",
        {"friendly_name": "Coffee Maker Power", "device_class": "power"},
    )

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "assign_label", "entity_id": entry.entity_id, "label_id": label.label_id}]},
    )

    assert resp.status == 200
    kstore = get_knowledge_store(hass)
    await kstore.async_load()
    entries = [
        item for item in await kstore.async_search(category="general", subject=entry.entity_id, limit=10, exclude_low_quality=False)
        if item.get("subject") == entry.entity_id
    ]
    created = next(item for item in entries if item.get("source") == "label_assignment")
    assert created["content"] == (
        "sensor entity 'Coffee Maker Power' [sensor.coffee_maker_power], located in Kitchen. "
        "Provided by the mqtt integration. Device class: power. Tagged with label 'kyber:coffee'."
    )
    assert created["tags"] == [
        entry.entity_id,
        "sensor",
        "labeled",
        "kyber:coffee",
        "label_assignment",
    ]
    assert created["confidence"] == 0.75


async def test_execute_assign_kyber_label_skips_knowledge_when_general_entry_exists(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Assigning a kyber label should not add duplicate baseline knowledge."""
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)
    entry = entity_reg.async_get_or_create("light", "test", "lamp_existing", suggested_object_id="lamp_existing")
    label = label_reg.async_create("kyber:lighting")
    kstore = get_knowledge_store(hass)
    await kstore.async_load()
    await kstore.async_add(
        "general",
        "Existing knowledge.",
        subject=entry.entity_id,
        tags=[entry.entity_id, "light"],
        source="manual",
    )

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "assign_label", "entity_id": entry.entity_id, "label_id": label.label_id}]},
    )

    assert resp.status == 200
    entries = [
        item for item in await kstore.async_search(category="general", subject=entry.entity_id, limit=10, exclude_low_quality=False)
        if item.get("subject") == entry.entity_id
    ]
    assert len(entries) == 1
    assert entries[0]["source"] == "manual"


async def test_execute_remove_label(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute endpoint should remove a label from an entity and return undo_action."""
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)
    label_reg.async_create("outdoor")
    entry = entity_reg.async_get_or_create("light", "test", "lamp_2", suggested_object_id="lamp_2")
    entity_reg.async_update_entity(entry.entity_id, labels={"outdoor"})

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"actions": [{"type": "remove_label", "entity_id": entry.entity_id, "label_id": "outdoor"}], "approved": True},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert result["undo_action"]["type"] == "assign_label"
    updated = entity_reg.async_get(entry.entity_id)
    assert "outdoor" not in updated.labels


# ──────────────────────────────────────────────────────────────────────────────
# /execute — entity actions
# ──────────────────────────────────────────────────────────────────────────────

async def test_execute_rename_entity(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute rename_entity should update entity name and return undo_action."""
    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get_or_create("light", "test", "desk", suggested_object_id="desk")

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "rename_entity", "entity_id": entry.entity_id, "name": "Desk Light"}]},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert result["undo_action"]["type"] == "rename_entity"
    updated = entity_reg.async_get(entry.entity_id)
    assert updated.name == "Desk Light"


async def test_execute_assign_area(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute assign_area should move entity to the area and return undo_action."""
    entity_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Office")
    entry = entity_reg.async_get_or_create("light", "test", "desk2", suggested_object_id="desk2")

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "assign_area", "entity_id": entry.entity_id, "area_id": area.id}]},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert result["undo_action"]["type"] == "assign_area"
    updated = entity_reg.async_get(entry.entity_id)
    assert updated.area_id == area.id


async def test_execute_assign_area_nonexistent_returns_error(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """assign_area with a non-existent area_id should return an error result."""
    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get_or_create("light", "test", "desk3", suggested_object_id="desk3")

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "assign_area", "entity_id": entry.entity_id, "area_id": "no_such_area"}]},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["results"][0]["status"] == "error"


# ──────────────────────────────────────────────────────────────────────────────
# /execute — area management actions
# ──────────────────────────────────────────────────────────────────────────────

async def test_execute_create_area(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute create_area should create the area and return a delete undo_action."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "create_area", "name": "Garage"}]},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert result["name"] == "Garage"
    assert result["undo_action"]["type"] == "delete_area"

    area_reg = ar.async_get(hass)
    assert area_reg.async_get_area(result["area_id"]) is not None


async def test_execute_create_area_missing_name_returns_error(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """create_area without a name should return an error result."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "create_area", "name": ""}]},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["results"][0]["status"] == "error"


async def test_execute_rename_area(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute rename_area should rename the area and return undo_action with old name."""
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Old Name")

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "rename_area", "area_id": area.id, "name": "New Name"}]},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert result["undo_action"]["type"] == "rename_area"
    assert result["undo_action"]["name"] == "Old Name"

    updated = area_reg.async_get_area(area.id)
    assert updated.name == "New Name"


async def test_execute_delete_area(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute delete_area should remove the area and return create undo_action."""
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Basement")

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "delete_area", "area_id": area.id}]},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert result["undo_action"]["type"] == "create_area"
    assert result["undo_action"]["name"] == "Basement"

    assert area_reg.async_get_area(area.id) is None


async def test_execute_delete_area_nonexistent_returns_error(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """delete_area with a non-existent area_id should return an error result."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"approved": True, "actions": [{"type": "delete_area", "area_id": "no_such_area"}]},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["results"][0]["status"] == "error"


# ──────────────────────────────────────────────────────────────────────────────
# /execute — call_service action
# ──────────────────────────────────────────────────────────────────────────────

async def test_execute_call_service(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Execute call_service should call the HA service and return ok status."""
    service_calls = []

    async def fake_service(call):
        service_calls.append(call)

    hass.services.async_register("light", "turn_on", fake_service)
    hass.states.async_set("light.kitchen", "off")

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"actions": [{
            "type": "call_service",
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.kitchen",
        }]},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert len(service_calls) == 1


async def test_execute_call_service_turn_off_returns_undo(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """call_service for turn_off on a light that was on should return an undo (turn_on)."""
    service_calls = []

    async def fake_service(call):
        service_calls.append(call)

    hass.services.async_register("light", "turn_off", fake_service)
    hass.states.async_set("light.kitchen", "on", attributes={"brightness": 200})

    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"actions": [{
            "type": "call_service",
            "domain": "light",
            "service": "turn_off",
            "entity_id": "light.kitchen",
        }]},
    )

    assert resp.status == 200
    data = await resp.json()
    result = data["results"][0]
    assert result["status"] == "ok"
    assert "undo_action" in result
    assert result["undo_action"]["service"] == "turn_on"


async def test_execute_call_service_missing_domain_returns_error(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """call_service without domain/service fields should return an error result."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={"actions": [{"type": "call_service", "entity_id": "light.desk"}]},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["results"][0]["status"] == "error"


# ---------------------------------------------------------------------------
# /complete - context injection gaps
# ---------------------------------------------------------------------------

async def test_lovelace_resources_included_in_context(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Lovelace resource URLs provided by the frontend should appear in the instructions."""
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={
                "prompt": "help",
                "lovelace_resources": [
                    "/hacsfiles/mini-graph-card/mini-graph-card-bundle.js",
                    "/hacsfiles/mushroom/mushroom.js",
                ],
            },
        )

    assert resp.status == 200
    instr = captured["v"]
    assert "mini-graph-card" in instr or "hacsfiles" in instr


async def test_script_editor_mode_injects_yaml_section(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """editor_mode=script should inject the YAML but NOT the dashboard override section."""
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={
                "prompt": "add step",
                "editor_mode": "script",
                "yaml": "alias: My Script\nsequence: []",
            },
        )

    assert resp.status == 200
    instr = captured["v"]
    assert "alias: My Script" in instr
    assert "The user is actively editing the dashboard" not in instr


async def test_automation_yaml_included_in_default_editor_mode(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """YAML should be injected when no editor_mode is specified (defaults to automation)."""
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["v"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post(
            "/api/kyber/complete",
            json={
                "prompt": "add trigger",
                "yaml": "alias: Test\ntrigger: []",
            },
        )

    assert resp.status == 200
    assert "alias: Test" in captured["v"]


async def test_response_includes_context_stats(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Response JSON should include context_stats with entity/automation counts."""
    hass.states.async_set("light.test", "on", {"friendly_name": "Test Light"})
    hass.states.async_set("automation.test", "on", {"friendly_name": "Test Auto", "id": "x1"})

    client = await hass_client()
    with patch(_PATCH_GENERATE, return_value=_make_ai_result("ok")):
        resp = await client.post(
            "/api/kyber/complete",
            json={"prompt": "hello"},
        )

    assert resp.status == 200
    data = await resp.json()
    assert "context_stats" in data
    stats = data["context_stats"]
    assert "entity_count" in stats
    assert "automation_count" in stats
    assert "area_count" in stats
    assert stats["entity_count"] >= 1
    assert stats["automation_count"] >= 1


async def test_debug_bug_report_defaults_bundle_upload_off(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Bug report endpoint should not include bundle summary unless explicitly enabled."""
    hass.data["kyber_debug_last_turn"] = {
        "request_id": "req-default-off",
        "intent": "action",
        "char_count": 123,
        "elapsed_ms": 45,
        "tool_log": [{"name": "get_entity_state", "args": {"entity_id": "light.kitchen_main"}, "status": "ok"}],
        "response_text": "Checked light.kitchen_main",
        "logs": [{"level": "ERROR", "message": "Failed for light.kitchen_main"}],
    }
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["instructions"] = instructions
        return _make_ai_result("TITLE: test bug\nBODY:\nBody text")

    client = await hass_client()
    fake_entry = MagicMock(options={}, data={"ai_task_entity_id": "ai_task.ollama_ai_task"})
    with (
        patch.object(hass.config_entries, "async_entries", return_value=[fake_entry]),
        patch(_PATCH_GENERATE_DEBUG, side_effect=fake),
        patch("aiohttp.ClientSession", side_effect=RuntimeError("offline")),
    ):
        resp = await client.post(
            "/api/kyber/debug/bug-report",
            json={
                "request_id": "req-default-off",
                "what_happened": "Wrong entity toggled",
                "bundle_name": "kyber-debug-req-default-off.zip",
            },
        )

    assert resp.status == 200
    data = await resp.json()
    assert data["title"] == "test bug"
    assert "**Bundle filename:** kyber-debug-req-default-off.zip" in captured["instructions"]
    assert "Debug bundle summary (PII has been redacted):" not in captured["instructions"]


async def test_debug_bug_report_includes_redacted_summary_when_enabled(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Bug report endpoint should add a redacted bundle summary when include_bundle=true."""
    hass.data["kyber_debug_last_turn"] = {
        "request_id": "req-include-on",
        "intent": "action",
        "char_count": 123,
        "elapsed_ms": 45,
        "tool_log": [{"name": "get_entity_state", "args": {"entity_id": "light.kitchen_main"}, "status": "ok"}],
        "response_text": "Checked light.kitchen_main",
        "logs": [{"level": "ERROR", "message": "Failed for light.kitchen_main"}],
    }
    captured = {}

    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["instructions"] = instructions
        return _make_ai_result("TITLE: test bug\nBODY:\nBody text")

    client = await hass_client()
    fake_entry = MagicMock(options={}, data={"ai_task_entity_id": "ai_task.ollama_ai_task"})
    with (
        patch.object(hass.config_entries, "async_entries", return_value=[fake_entry]),
        patch(_PATCH_GENERATE_DEBUG, side_effect=fake),
        patch("aiohttp.ClientSession", side_effect=RuntimeError("offline")),
    ):
        resp = await client.post(
            "/api/kyber/debug/bug-report",
            json={
                "request_id": "req-include-on",
                "what_happened": "Wrong entity toggled",
                "include_bundle": True,
                "bundle_name": "kyber-debug-req-include-on.zip",
            },
        )

    assert resp.status == 200
    assert "Debug bundle summary (PII has been redacted):" in captured["instructions"]
    assert "light.kitchen_main" not in captured["instructions"]
    assert "***redacted-" in captured["instructions"]


# ──────────────────────────────────────────────────────────────────────────────
# Device context expansion — entity_alias → sibling entities
# ──────────────────────────────────────────────────────────────────────────────

async def test_device_context_expansion_injects_siblings(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """When memory returns an entity_alias, sibling entities on the same HA device
    should appear in the injected instructions so the model can pick the right one."""
    from homeassistant.helpers import device_registry as _dr

    halfload_eid = "switch.dishwasher_halfload"
    start_eid = "switch.dishwasher_program_start"
    fake_device_id = "dev-dishwasher-001"

    # Fake entity registry entries
    halfload_reg = MagicMock()
    halfload_reg.entity_id = halfload_eid
    halfload_reg.device_id = fake_device_id
    halfload_reg.name = None
    halfload_reg.original_name = "Halfload Option"

    start_reg = MagicMock()
    start_reg.entity_id = start_eid
    start_reg.device_id = fake_device_id
    start_reg.name = None
    start_reg.original_name = "Program Start"

    # Patch the real registry instances (they're singletons per hass)
    real_entity_reg = er.async_get(hass)
    real_device_reg = _dr.async_get(hass)

    fake_device = MagicMock()
    fake_device.name_by_user = None
    fake_device.name = "Dishwasher"

    # Seed memory alias for the halfload entity
    kstore = get_knowledge_store(hass)
    await kstore.async_load()
    await kstore.async_add(
        "entity_alias",
        halfload_eid,
        subject="dishwasher half load",
        tags=[halfload_eid, "search_alias"],
        source="entity_narrator",
    )

    captured: dict = {}

    async def fake_generate(hass, *, task_name, entity_id, instructions, **kw):
        captured["instructions"] = instructions
        return _make_ai_result("I'll start the dishwasher.")

    client = await hass_client()
    with (
        patch.object(real_entity_reg, "async_get", side_effect=lambda eid: (
            halfload_reg if eid == halfload_eid else None
        )),
        patch.object(real_entity_reg.entities, "get_entries_for_device_id",
                     return_value=[halfload_reg, start_reg]),
        patch.object(real_device_reg, "async_get", return_value=fake_device),
        patch(_PATCH_GENERATE, side_effect=fake_generate),
    ):
        resp = await client.post(
            "/api/kyber/complete",
            json={"prompt": "start the dishwasher"},
        )

    assert resp.status == 200
    instructions = captured.get("instructions", "")

    assert "Sibling entities on the same device" in instructions
    assert start_eid in instructions
    assert halfload_eid in instructions
    assert "Dishwasher" in instructions


async def test_device_context_expansion_no_device_skipped(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """entity_alias entries without a device_id should not produce a sibling section."""
    entity_reg = er.async_get(hass)

    # Register an entity without attaching it to a device
    lamp = entity_reg.async_get_or_create(
        "light", "test", "floating_lamp",
        suggested_object_id="floating_lamp",
    )

    kstore = get_knowledge_store(hass)
    await kstore.async_load()
    await kstore.async_add(
        "entity_alias",
        lamp.entity_id,
        subject="floating lamp",
        tags=[lamp.entity_id, "search_alias"],
        source="entity_narrator",
    )

    captured: dict = {}

    async def fake_generate(hass, *, task_name, entity_id, instructions, **kw):
        captured["instructions"] = instructions
        return _make_ai_result("ok")

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake_generate):
        resp = await client.post(
            "/api/kyber/complete",
            json={"prompt": "turn on floating lamp"},
        )

    assert resp.status == 200
    instructions = captured.get("instructions", "")
    # No sibling section when there's no device
    assert "Sibling entities on the same device" not in instructions
