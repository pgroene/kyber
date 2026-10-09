"""Progress events ("thinking" lines) and tool result summaries were English
only. The backend now sends a translation key with params; the panel looks the
key up in www/src/i18n.js and falls back to the English message.

These tests keep backend and panel in step: every key the backend sends must
exist in i18n.js with the same placeholder names.
"""
from __future__ import annotations

import re
from pathlib import Path

from custom_components.kyber.tool_execution import (
    _TOOL_SUMMARY_EN,
    _tool_result_summary,
    _tool_result_summary_parts,
)

_ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "kyber"
_I18N = (_ROOT / "www" / "src" / "i18n.js").read_text(encoding="utf-8")
_EN_BLOCK = _I18N[_I18N.index("export const EN = {"):_I18N.index("\n};", _I18N.index("export const EN = {"))]


def _en_text(key: str) -> str | None:
    m = re.search(rf'^\s+{key}:\s+"((?:[^"\\]|\\.)*)",', _EN_BLOCK, re.M)
    return m.group(1) if m else None


def _names(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)(?:\}|\|)", text))


def test_backend_event_keys_exist_in_panel() -> None:
    source = (_ROOT / "http_api.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'"key":\s*"(ev_\w+)"', source))
    assert len(keys) >= 10
    missing = sorted(k for k in keys if _en_text(k) is None)
    assert missing == []


def test_tool_summary_keys_match_panel_placeholders() -> None:
    for key, english in _TOOL_SUMMARY_EN.items():
        panel = _en_text(key)
        assert panel is not None, key
        assert _names(panel) == _names(english), key


def test_english_summary_is_unchanged() -> None:
    call = {"name": "search_entities", "query": "heizkorper schlafzimmer"}
    result = {f"climate.x{i}": {} for i in range(27)}
    assert _tool_result_summary(call, result) == "27 matches for 'heizkorper schlafzimmer'"
    assert _tool_result_summary_parts(call, result) == (
        "ts_search_matches", {"count": 27, "query": "heizkorper schlafzimmer"},
    )
    area = _tool_result_summary(
        {"name": "get_area_entities", "area": "schlafzimmer"},
        {"area": "Schlafzimmer", "entities": {"climate.a": {}}},
    )
    assert area == "1 entities in Schlafzimmer"  # English log form; the panel says "1 entity"
    assert _tool_result_summary({"name": "x"}, {"error": "boom"}) == "error: boom"
    assert _tool_result_summary({"name": "unknown_tool"}, {}) == "done"
