"""Area lookup in get_area_entities and dedup of repeated area calls.

Background (upstream PR #261): the model called get_area_entities for the same
area over and over, alternating "Zitkamer" and "zitkamer". The AI loop's dedup
signature was built from the raw call, so the two spellings never counted as a
repeat. The PR hid one of two same-named areas from the context instead, which
would make that area's entities unreachable.

Now:
  - resolve_tool_call gives every spelling of an area the same form, and the
    loop builds its signature from the resolved call;
  - get_area_entities matches like HA (case and spaces ignored) and merges all
    matching areas. HA refuses to create such a second area, but an older
    stored registry can still contain one.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="requires pytest-homeassistant-custom-component",
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component


def _entity_in_area(hass: HomeAssistant, object_id: str, area_id: str) -> str:
    entry = er.async_get(hass).async_get_or_create("light", "test", object_id)
    er.async_get(hass).async_update_entity(entry.entity_id, area_id=area_id)
    hass.states.async_set(entry.entity_id, "on")
    return entry.entity_id


def _area_entities(hass: HomeAssistant, area: str) -> dict:
    from custom_components.kyber.tool_execution import _execute_tool

    return json.loads(_execute_tool(hass, {"name": "get_area_entities", "area": area}))


@pytest.mark.parametrize("query", ["Zitkamer", "zitkamer", "ZITKAMER", "  Zit kamer ", "zitkamer_id"])
async def test_area_found_in_any_spelling(hass: HomeAssistant, query: str) -> None:
    area = ar.async_get(hass).async_create("Zitkamer")
    if query == "zitkamer_id":
        query = area.id
    entity_id = _entity_in_area(hass, "lamp", area.id)

    result = _area_entities(hass, query)
    assert result["area"] == "Zitkamer"
    assert list(result["entities"]) == [entity_id]
    assert "area_ids" not in result


async def test_unknown_area_reports_not_found(hass: HomeAssistant) -> None:
    ar.async_get(hass).async_create("Keuken")
    assert "not found" in _area_entities(hass, "Zolder")["error"]


async def test_legacy_same_named_areas_are_merged(hass: HomeAssistant) -> None:
    """Two stored areas whose names differ only in case: both keep their entities."""
    reg = ar.async_get(hass)
    first = reg.async_create("Zitkamer")
    second = reg.async_create("Keuken")
    lamp = _entity_in_area(hass, "lamp", first.id)
    tv = _entity_in_area(hass, "tv", second.id)
    # HA blocks this name on create, an old storage file does not.
    legacy = dataclasses.replace(second, name="zitkamer")

    with patch.object(reg, "async_list_areas", return_value=[first, legacy]):
        result = _area_entities(hass, "Zitkamer")

    assert sorted(result["entities"]) == sorted([lamp, tv])
    assert result["area_ids"] == sorted([first.id, second.id])


@pytest.mark.parametrize(
    ("call", "area"),
    [
        ({"name": "get_area_entities", "area": "Zitkamer"}, "zitkamer"),
        ({"name": "get_area_entities", "area": "  Zit   Kamer "}, "zit kamer"),
        ({"name": "get_area_entities", "area_name": "Living Room"}, "living room"),
        ({"name": "list_entities_by_area", "area_id": "living_room"}, "living_room"),
    ],
)
def test_resolve_tool_call_gives_one_form_per_area(call: dict, area: str) -> None:
    from custom_components.kyber.tool_execution import resolve_tool_call

    resolved = resolve_tool_call(call)
    assert resolved["name"] == "get_area_entities"
    assert resolved["area"] == area


# ── AI loop: a repeat in another spelling is a repeat ────────────────────────

def _ai_result(text: str) -> MagicMock:
    r = MagicMock()
    r.data = text
    return r


async def test_repeated_area_call_in_other_case_runs_once(hass: HomeAssistant, hass_client) -> None:
    from custom_components.kyber import async_setup_entry
    from custom_components.kyber.const import (
        CLOUD_PROVIDER_OPENAI,
        CONF_CLOUD_PROVIDER,
        CONF_CLOUD_USE_FOR_CHAT,
        CONF_OPENAI_API_KEY,
        CONF_OPENAI_MODEL,
        DOMAIN,
    )

    mock_component(hass, "ai_task")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ai_task_entity_id": "ai_task.test",
            "max_tokens": 32_000,
            CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_OPENAI,
            CONF_CLOUD_USE_FOR_CHAT: True,
            CONF_OPENAI_API_KEY: "sk-test",
            CONF_OPENAI_MODEL: "gpt-4o",
        },
        title="Kyber",
    )
    await async_setup_component(hass, "http", {})
    with (
        patch("custom_components.kyber._async_run_initial_learning"),
        patch("custom_components.kyber._async_explore_integrations", new_callable=AsyncMock),
        patch("custom_components.kyber._async_seed_language_hints"),
    ):
        await async_setup_entry(hass, entry)
        await asyncio.sleep(0)

    replies = iter([
        '[TOOL_CALL: {"name": "get_area_entities", "area": "Zitkamer"}]',
        '[TOOL_CALL: {"name": "get_area_entities", "area": "zitkamer"}]',
    ])
    executed: list[dict] = []

    def _fake_tool(_hass, call):
        executed.append(call)
        return json.dumps({"area": "Zitkamer", "entities": {}})

    client = await hass_client()
    with (
        patch(
            "custom_components.kyber.http_api.async_openai_ai_call",
            new_callable=AsyncMock,
            side_effect=lambda *a, **k: _ai_result(next(replies, "The living room is empty.")),
        ),
        patch("custom_components.kyber.http_api._execute_tool", side_effect=_fake_tool),
    ):
        resp = await client.post("/api/kyber/complete", json={"prompt": "What is in the zitkamer?"})

    assert resp.status == 200
    area_calls = [c for c in executed if c.get("name") == "get_area_entities"]
    assert len(area_calls) == 1
