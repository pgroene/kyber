"""Every text of the setup, reconfigure and options dialogs comes from translations.

Background: several fields had no label at all (HA showed the raw key), the
cloud section was only labelled in en.json, select options carried hard-coded
English labels, and the stats lines were English sentences built in Python.

The stats lines are sentences in translations/*.json with plain "{name}"
placeholders. HA core compares each translation's placeholders with English
(string.Formatter) and drops a translation that differs or does not parse, so
ICU select/plural cannot be used there. The tests check that every placeholder
is in the flow's description_placeholders on every render of the options form,
since the frontend fails the whole description on a missing one.
"""
from __future__ import annotations

import json
import string
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="requires pytest-homeassistant-custom-component",
)

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

KYBER = Path(__file__).resolve().parents[1] / "custom_components" / "kyber"
LANGUAGE_FILES = {
    "strings": KYBER / "strings.json",
    "en": KYBER / "translations" / "en.json",
    "de": KYBER / "translations" / "de.json",
    "nl": KYBER / "translations" / "nl.json",
}
ALL_TRANSLATIONS = sorted((KYBER / "translations").glob("*.json"))


def _load(name: str) -> dict:
    return json.loads(LANGUAGE_FILES[name].read_text(encoding="utf-8"))


def _placeholders(text: str) -> set[str]:
    """Placeholder names the way HA core reads them (raises ValueError on ICU syntax)."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def _flat(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _flat(v, f"{path}.{k}" if path else k)
    elif isinstance(node, str):
        yield path, node


def _fields(schema) -> dict[str | None, list[str]]:
    """Map section name (None = top level) to its field keys."""
    out: dict[str | None, list[str]] = {None: []}
    for key, value in schema.schema.items():
        inner = getattr(value, "schema", None)
        if inner is not None and hasattr(inner, "schema"):
            out[str(key)] = [str(k) for k in inner.schema]
        else:
            out[None].append(str(key))
    return out


def _selectors(schema) -> list:
    found = []
    for value in schema.schema.values():
        inner = getattr(value, "schema", None)
        values = inner.schema.values() if inner is not None and hasattr(inner, "schema") else [value]
        for sel in values:
            if getattr(sel, "config", {}).get("translation_key"):
                found.append(sel)
    return found


def _step_placeholders(step: dict) -> set[str]:
    args = set()
    for section in step.get("sections", {}).values():
        for text in section.get("data_description", {}).values():
            args |= _placeholders(text)
    return args


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    mock_component(hass, "ai_task")
    entry = MockConfigEntry(
        domain="kyber",
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize("lang", list(LANGUAGE_FILES))
async def test_options_dialog_labels_every_field_and_section(hass: HomeAssistant, entry, lang) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    step = _load(lang)["options"]["step"]["init"]
    sections = step["sections"]

    missing = []
    for section, keys in _fields(result["data_schema"]).items():
        if section is None:
            missing += [f"<top>.{k}" for k in keys]
            continue
        if not sections.get(section, {}).get("name"):
            missing.append(f"{section}.name")
        labels = sections.get(section, {}).get("data", {})
        missing += [f"{section}.{k}" for k in keys if k not in labels]
    assert missing == []


@pytest.mark.parametrize("lang", list(LANGUAGE_FILES))
@pytest.mark.parametrize("step_id", ["user", "reconfigure"])
async def test_setup_dialogs_label_every_field_and_section(hass: HomeAssistant, lang, step_id) -> None:
    from custom_components.kyber.config_flow import _build_setup_schema

    step = _load(lang)["config"]["step"][step_id]
    missing = []
    for section, keys in _fields(_build_setup_schema(hass)).items():
        if section is None:
            missing += [k for k in keys if k not in step.get("data", {})]
            continue
        sec = step.get("sections", {}).get(section, {})
        if not sec.get("name"):
            missing.append(f"{section}.name")
        missing += [f"{section}.{k}" for k in keys if k not in sec.get("data", {})]
    assert missing == []
    # The setup steps get no placeholders, so their texts must not use any.
    assert _step_placeholders(step) == set()


@pytest.mark.parametrize("lang", list(LANGUAGE_FILES))
async def test_select_options_are_translated(hass: HomeAssistant, entry, lang) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    selector_texts = _load(lang).get("selector", {})
    missing = []
    for sel in _selectors(result["data_schema"]):
        key = sel.config["translation_key"]
        options = selector_texts.get(key, {}).get("options", {})
        values = [o if isinstance(o, str) else o["value"] for o in sel.config["options"]]
        missing += [f"{key}.{v}" for v in values if v not in options]
        # Labels come from the translation, not from the code.
        assert all(isinstance(o, str) for o in sel.config["options"])
    assert _selectors(result["data_schema"]), "no translated select found"
    assert missing == []


@pytest.mark.parametrize("lang", list(LANGUAGE_FILES))
async def test_options_placeholders_cover_every_placeholder(hass: HomeAssistant, entry, lang) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    args = _step_placeholders(_load(lang)["options"]["step"]["init"])
    assert args, "stats lines lost their placeholders"
    assert args <= set(result["description_placeholders"])
    assert all(isinstance(v, str) for v in result["description_placeholders"].values())


async def test_every_options_rerender_carries_the_placeholders(hass: HomeAssistant, entry) -> None:
    """The unknown-entity and the provider-change re-render use the same descriptions."""
    args = _step_placeholders(_load("en")["options"]["step"]["init"])

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"model_config": {"ai_task_entity_id": "ai_task.does_not_exist"}},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"ai_task_entity_id": "entity_not_found"}
    assert args <= set(result["description_placeholders"])

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"model_config": {}, "cloud_config": {"cloud_provider": "openai"}},
    )
    assert result["type"] == FlowResultType.FORM
    assert args <= set(result["description_placeholders"])


@pytest.mark.parametrize("lang", ["de", "nl"])
def test_translation_covers_all_keys_of_strings_json(lang) -> None:
    base = dict(_flat(_load("strings")))
    assert sorted(set(base) - set(dict(_flat(_load(lang))))) == []


@pytest.mark.parametrize("path", ALL_TRANSLATIONS, ids=lambda p: p.name)
def test_ha_core_keeps_every_translation(path: Path) -> None:
    """Replay HA core's placeholder check (helpers/translation.py, _validate_placeholders).

    A text that does not parse, or uses other placeholders than English, is
    dropped and logged as an error; an English text that does not parse even
    raises while loading another language.
    """
    en = dict(_flat(json.loads((KYBER / "translations" / "en.json").read_text(encoding="utf-8"))))
    loc = dict(_flat(json.loads(path.read_text(encoding="utf-8"))))
    dropped = []
    for key, text in loc.items():
        try:
            mine = _placeholders(text)
        except ValueError:
            dropped.append(f"{key}: does not parse")
            continue
        if key in en and mine != _placeholders(en[key]):
            dropped.append(f"{key}: {sorted(mine)} != {sorted(_placeholders(en[key]))}")
    assert dropped == []



# ── model_stats placeholders ─────────────────────────────────────────────────

def _hass() -> SimpleNamespace:
    return SimpleNamespace(data={})


def test_stats_placeholders_without_and_with_calls() -> None:
    from custom_components.kyber.model_stats import (
        NO_VALUE,
        record_call,
        stats_placeholders,
    )

    hass = _hass()
    none = {
        "chat_calls": "0", "chat_avg": NO_VALUE, "chat_min": NO_VALUE, "chat_max": NO_VALUE,
        "chat_tokens": "0", "chat_errors": "0",
    }
    assert stats_placeholders(hass, "", "chat") == none
    assert stats_placeholders(hass, "ai_task.x", "chat") == none

    record_call(hass, "ai_task.x", 0, 0, success=False)
    assert stats_placeholders(hass, "ai_task.x", "chat") == {**none, "chat_errors": "1"}

    record_call(hass, "ai_task.x", 4000, 1000, success=True)
    record_call(hass, "ai_task.x", 2000, 500, success=True)
    assert stats_placeholders(hass, "ai_task.x", "chat") == {
        "chat_calls": "2",
        "chat_avg": "3.0",
        "chat_min": "2.0",
        "chat_max": "4.0",
        "chat_tokens": "1500",
        "chat_errors": "1",
    }


def test_run_stats_placeholders_never_run() -> None:
    from custom_components.kyber.model_stats import NO_VALUE, run_stats_placeholders

    assert run_stats_placeholders(_hass(), "deep_learning", "deep_learning") == {
        "deep_learning_last": NO_VALUE,
        "deep_learning_next": NO_VALUE,
        "deep_learning_total": "0",
    }


@pytest.mark.parametrize(
    ("interval", "expected_next"),
    [
        (0, "–"),
        (86400, "2026-10-23 14:00"),
    ],
)
def test_run_stats_placeholders_use_local_time(interval, expected_next) -> None:
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from homeassistant.util import dt as dt_util

    from custom_components.kyber import model_stats

    noon_utc = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc).timestamp()
    hass = _hass()
    with patch.object(model_stats._time, "time", return_value=noon_utc):
        model_stats.record_run(hass, "narrator", interval_secs=interval)
    # Restored before the plugin's teardown checks that the zone is UTC again.
    with patch.object(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Berlin")):
        placeholders = model_stats.run_stats_placeholders(hass, "narrator", "narrator")
    assert placeholders == {
        "narrator_last": "2026-10-22 14:00",
        "narrator_next": expected_next,
        "narrator_total": "1",
    }
