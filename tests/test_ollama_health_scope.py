"""The Ollama health check ran for every AI task entity. Users of another
provider saw "⚠️ Ollama: Could not determine Ollama URL from config entries"
in every chat turn although they never configured Ollama.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kyber.http_api import _check_ollama_health


def _register(hass: HomeAssistant, domain: str, data: dict | None = None) -> str:
    entry = MockConfigEntry(domain=domain, data=data or {})
    entry.add_to_hass(hass)
    ent = er.async_get(hass).async_get_or_create(
        "ai_task", domain, f"{domain}_task", config_entry=entry,
    )
    return ent.entity_id


async def test_other_provider_is_skipped(hass: HomeAssistant) -> None:
    entity_id = _register(hass, "openai_conversation")
    result = await _check_ollama_health(hass, entity_id)
    assert result.get("skipped") is True
    assert result["error"] is None


async def test_unknown_entity_without_ollama_is_skipped(hass: HomeAssistant) -> None:
    result = await _check_ollama_health(hass, "ai_task.does_not_exist")
    assert result.get("skipped") is True
    assert result["error"] is None


async def test_ollama_entity_without_url_still_reports(hass: HomeAssistant) -> None:
    entity_id = _register(hass, "ollama")
    result = await _check_ollama_health(hass, entity_id)
    assert not result.get("skipped")
    assert result["error"] == "Could not determine Ollama URL from config entries"
