from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

def get_knowledge_store(hass):
    """Get knowledge store via live sys.modules so conftest restoration takes effect."""
    import sys
    return sys.modules["custom_components.kyber.knowledge"].get_store(hass)

_PATCH_GENERATE = "custom_components.kyber.api_utilities.async_generate_data"
_PATCH_AREA_SUGGESTIONS = "custom_components.kyber.area_assignment.async_detect_conversation_suggestions"


def _make_ai_result(text: str) -> MagicMock:
    result = MagicMock()
    result.data = text
    return result


async def test_async_add_proposal_updates_existing_pending_action(hass: HomeAssistant) -> None:
    """Deduped proposals should still refresh pending_action metadata."""
    kstore = get_knowledge_store(hass)
    await kstore.async_load()

    first = await kstore.async_add_proposal(
        proposal_type="area_assignment",
        subject="switch.koffiezetapparaat",
        content="📍 koffiezetapparaat toewijzen aan keuken",
        pending_action={"type": "assign_area", "entity_id": "switch.koffiezetapparaat", "area_id": "kitchen"},
        entity_name="koffiezetapparaat",
        area_name="keuken",
    )
    second = await kstore.async_add_proposal(
        proposal_type="area_assignment",
        subject="switch.koffiezetapparaat",
        content="📍 koffiezetapparaat toewijzen aan keuken",
        pending_action={"type": "assign_area", "entity_id": "switch.koffiezetapparaat", "area_id": "kitchen_v2"},
        entity_name="koffiezetapparaat",
        area_name="keuken",
    )

    assert second["id"] == first["id"]
    assert second["needs_review"] is True
    assert second["proposal_type"] == "area_assignment"
    assert second["pending_action"]["area_id"] == "kitchen_v2"


async def test_proposal_approve_assign_area_executes_and_creates_memory(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Approving an area proposal should assign the area and store Dutch memory."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    area = area_reg.async_create("keuken")
    entry = entity_reg.async_get_or_create("switch", "test", "koffiezetapparaat", suggested_object_id="koffiezetapparaat")

    kstore = get_knowledge_store(hass)
    proposal = await kstore.async_add_proposal(
        proposal_type="area_assignment",
        subject=entry.entity_id,
        content="📍 koffiezetapparaat toewijzen aan keuken",
        pending_action={"type": "assign_area", "entity_id": entry.entity_id, "area_id": area.id},
        entity_name="koffiezetapparaat",
        area_name="keuken",
    )

    client = await hass_client()
    resp = await client.post("/api/kyber/proposals/approve", json={"entry_id": proposal["id"]})

    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert data["memory"] == "De koffiezetapparaat (switch.koffiezetapparaat) staat in de keuken."
    assert entity_reg.async_get(entry.entity_id).area_id == area.id

    await kstore.async_load()
    assert kstore._entries[proposal["id"]]["needs_review"] is False  # noqa: SLF001
    memories = [
        item
        for item in await kstore.async_search(subject=entry.entity_id, limit=10, exclude_low_quality=False)
        if item.get("source") == "proposal_approve"
    ]
    assert any(item["content"] == data["memory"] for item in memories)


async def test_proposal_approve_assign_label_executes_and_creates_memory(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Approving a label proposal should apply the label and store Dutch memory."""
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)
    entry = entity_reg.async_get_or_create("switch", "test", "koffiezetapparaat", suggested_object_id="koffiezetapparaat")
    label = label_reg.async_create("kyber:appliance")

    kstore = get_knowledge_store(hass)
    proposal = await kstore.async_add_proposal(
        proposal_type="label_assignment",
        subject=entry.entity_id,
        content="🏷 Label 'kyber:appliance' toewijzen aan koffiezetapparaat",
        pending_action={"type": "assign_label", "entity_id": entry.entity_id, "label_id": label.label_id},
        entity_name="switch.koffiezetapparaat",
        label_name="kyber:appliance",
    )

    client = await hass_client()
    resp = await client.post("/api/kyber/proposals/approve", json={"entry_id": proposal["id"]})

    assert resp.status == 200
    data = await resp.json()
    assert data["memory"] == "De switch.koffiezetapparaat (switch.koffiezetapparaat) is gemarkeerd als kyber:appliance."
    assert label.label_id in (entity_reg.async_get(entry.entity_id).labels or set())


async def test_complete_saves_assign_label_plan_action_as_proposal(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Plan assign_label actions should be queued as proposal knowledge entries."""
    entity_reg = er.async_get(hass)
    label_reg = lr.async_get(hass)
    entry = entity_reg.async_get_or_create("switch", "test", "koffiezetapparaat", suggested_object_id="koffiezetapparaat")
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Koffiezetapparaat"})
    label = label_reg.async_create("kyber:appliance")

    plan_json = json.dumps(
        {
            "overview": "Ken een label toe",
            "actions": [
                {"type": "assign_label", "entity_id": entry.entity_id, "label_id": label.label_id}
            ],
        }
    )
    ai_response = f"Voorstel:\n```plan\n{plan_json}\n```"

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=lambda *a, **kw: _make_ai_result(ai_response)):
        resp = await client.post("/api/kyber/complete", json={"prompt": "assign the kyber:appliance label to switch.koffiezetapparaat"})

    assert resp.status == 200
    kstore = get_knowledge_store(hass)
    proposals = [
        item
        for item in await kstore.async_search(category="proposal", subject=entry.entity_id, limit=10, exclude_low_quality=False)
        if item.get("proposal_type") == "label_assignment"
    ]
    assert len(proposals) == 1
    assert proposals[0]["pending_action"] == {
        "type": "assign_label",
        "entity_id": entry.entity_id,
        "label_id": label.label_id,
    }
    assert proposals[0]["needs_review"] is True


async def test_complete_saves_area_suggestion_as_proposal(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Unapplied conversation area suggestions should be queued for review."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    area = area_reg.async_create("keuken")
    entry = entity_reg.async_get_or_create("switch", "test", "koffiezetapparaat", suggested_object_id="koffiezetapparaat")
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Koffiezetapparaat"})

    plan_json = json.dumps(
        {
            "overview": "Zet aan",
            "actions": [
                {"type": "call_service", "domain": "switch", "service": "turn_on", "entity_id": entry.entity_id}
            ],
        }
    )
    ai_response = f"Voorstel:\n```plan\n{plan_json}\n```"
    suggestions = [
        {
            "entity_id": entry.entity_id,
            "friendly_name": "Koffiezetapparaat",
            "suggested_area_name": "keuken",
            "suggested_area_id": area.id,
            "applied": False,
        }
    ]

    async def _fake_area_suggestions(*args, **kwargs):
        return suggestions

    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=lambda *a, **kw: _make_ai_result(ai_response)), patch(
        _PATCH_AREA_SUGGESTIONS, side_effect=_fake_area_suggestions
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "zet de keuken koffiezetapparaat aan"})

    assert resp.status == 200
    data = await resp.json()
    assert data["area_suggestions"][0]["entity_id"] == entry.entity_id

    kstore = get_knowledge_store(hass)
    proposals = [
        item
        for item in await kstore.async_search(category="proposal", subject=entry.entity_id, limit=10, exclude_low_quality=False)
        if item.get("proposal_type") == "area_assignment"
    ]
    assert len(proposals) == 1
    assert proposals[0]["pending_action"] == {
        "type": "assign_area",
        "entity_id": entry.entity_id,
        "area_id": area.id,
    }
