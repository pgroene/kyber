"""Tests for _try_quick_intent in http_api.py.

These tests exercise the regex-only intent parser without needing HA. We
import a tiny shim that only loads the regex + helper.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path


def _load_helpers():
    """Extract the helper + regex from http_api.py without importing HA."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "custom_components" / "kyber" / "http_api.py").read_text(encoding="utf-8")
    # Normalise line endings
    src = src.replace("\r\n", "\n")
    start = src.index("_QUICK_CREATE_AREA_RE = re.compile(")
    # Find the end of _try_quick_intent (the next blank-line block AFTER it)
    func_start = src.index("def _try_quick_intent", start)
    end = src.index("\n\n\n", func_start)
    snippet = src[start:end]
    ns: dict = {"re": re, "json": __import__("json")}
    snippet = "from typing import Any\n" + snippet
    exec(snippet, ns)
    return ns


def test_quick_intent_matches_basic_create():
    ns = _load_helpers()
    out = ns["_try_quick_intent"]("create an area outside")
    assert out is not None
    assert out["shortcut"] == "quick_create_area"
    assert out["plan"]["actions"][0]["type"] == "create_area"
    assert out["plan"]["actions"][0]["name"] == "outside"
    assert "entity_id" not in out["plan"]["actions"][0]


def test_quick_intent_matches_variants():
    ns = _load_helpers()
    cases = [
        ("create an area garage", "garage"),
        ("create area office", "office"),
        ("add area Garden", "Garden"),
        ("make a new area called Loft", "Loft"),
        ("new area Attic", "Attic"),
        ("please create an area basement", "basement"),
        ("Can you create an area called Sun Room?", "Sun Room"),
    ]
    for prompt, expected_name in cases:
        out = ns["_try_quick_intent"](prompt)
        assert out is not None, f"Failed to match: {prompt!r}"
        assert out["plan"]["actions"][0]["name"] == expected_name, prompt


def test_quick_intent_skips_non_matches():
    ns = _load_helpers()
    for prompt in [
        "what areas do I have?",
        "show me the areas",
        "delete area outside",  # delete not handled here
        "rename area kitchen to keuken",
        "turn on the light in outside",
        "",
        "   ",
        "create",
        "area",
    ]:
        assert ns["_try_quick_intent"](prompt) is None, f"Should NOT match: {prompt!r}"


def test_quick_intent_rejects_generic_name():
    ns = _load_helpers()
    # "create an area area" — name resolves to "area" which we reject
    assert ns["_try_quick_intent"]("create an area area") is None


def test_quick_intent_response_text_includes_plan_block():
    ns = _load_helpers()
    out = ns["_try_quick_intent"]("create area outside")
    assert "```plan" in out["response_text"]
    assert "outside" in out["response_text"]
    assert "create_area" in out["response_text"]
