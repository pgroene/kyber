"""entity_alias entries must resolve to entity_ids whatever wording their content uses.

Auto-recorded search aliases store a sentence ("When user searches for 'tv', the
matching entity is: media_player.tv"), while the prompt tells the model to store
the bare entity_id. The alias fallback in search_entities used to treat the whole
content as the entity_id, so every auto-recorded alias was dead.
"""
import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="requires pytest-homeassistant-custom-component",
)

from homeassistant.core import HomeAssistant

from custom_components.kyber.knowledge import alias_entity_ids
from custom_components.kyber.tool_execution import _search_entity_aliases


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("media_player.tv", ["media_player.tv"]),
        ("  light.kitchen  ", ["light.kitchen"]),
        (
            "When user searches for 'tv', the matching entity is: media_player.tv",
            ["media_player.tv"],
        ),
        (
            "When user searches for 'koffie', the matching entities are: switch.espresso, sensor.espresso_power",
            ["switch.espresso", "sensor.espresso_power"],
        ),
        ("When user says 'tv' they mean 'media_player.living_tv'.", ["media_player.living_tv"]),
        ("switch.0x00124b_relay", ["switch.0x00124b_relay"]),
        ("light.a, light.a", ["light.a"]),
        ("see https://example.com/x.html", []),
        ("", []),
        ("no entity here", []),
    ],
)
def test_alias_entity_ids(content, expected) -> None:
    assert alias_entity_ids(content) == expected


class _FakeStore:
    is_loaded = True

    def __init__(self, entries: list[dict]) -> None:
        self._entries = {str(i): e for i, e in enumerate(entries)}


async def test_auto_recorded_alias_is_found(hass: HomeAssistant) -> None:
    hass.states.async_set("media_player.living_tv", "on", {"friendly_name": "Living TV"})
    kstore = _FakeStore([
        {
            "category": "entity_alias",
            "subject": "televisie",
            "content": "When user searches for 'televisie', the matching entity is: media_player.living_tv",
        }
    ])
    result = _search_entity_aliases(hass, ["televisie"], kstore)
    assert "media_player.living_tv" in result


async def test_bare_alias_still_found_and_missing_entities_skipped(hass: HomeAssistant) -> None:
    hass.states.async_set("switch.espresso", "off", {"friendly_name": "Espresso"})
    kstore = _FakeStore([
        {"category": "entity_alias", "subject": "koffie", "content": "switch.espresso"},
        {
            "category": "entity_alias",
            "subject": "koffie machine",
            "content": "When user searches for 'koffie machine', the matching entity is: switch.gone",
        },
    ])
    result = _search_entity_aliases(hass, ["koffie"], kstore)
    assert "switch.espresso" in result
    assert "switch.gone" not in result


async def test_multi_entity_alias_returns_all_existing(hass: HomeAssistant) -> None:
    hass.states.async_set("switch.espresso", "off")
    hass.states.async_set("sensor.espresso_power", "3")
    kstore = _FakeStore([
        {
            "category": "entity_alias",
            "subject": "koffie",
            "content": "When user searches for 'koffie', the matching entities are: switch.espresso, sensor.espresso_power",
        }
    ])
    result = _search_entity_aliases(hass, ["koffie"], kstore)
    assert {"switch.espresso", "sensor.espresso_power"} <= set(result)
