"""Tests for _truncate_tool_result() — issue #112.

Covers: already-fits, empty collections, single oversized item,
multi-item dict, list, unicode, hard-slice fallback.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load the module under test without importing the full HA stack
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))


def _load() -> object:
    """Import _truncate_tool_result directly from http_api source.

    Extract the function body using AST so we don't accidentally
    capture module-level code that follows the function.
    """
    import ast
    src = (
        Path(__file__).parent.parent
        / "custom_components" / "kyber" / "http_api.py"
    ).read_text(encoding="utf-8-sig")  # utf-8-sig strips the BOM if present
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_truncate_tool_result":
            fn_node = node
            break
    if fn_node is None:
        raise RuntimeError("Could not locate _truncate_tool_result in http_api.py")
    # ast line numbers are 1-based; end_lineno is the last line of the function
    fn_src = "".join(lines[fn_node.lineno - 1 : fn_node.end_lineno])
    ns: dict = {"json": json, "Any": object}
    exec(fn_src, ns)  # noqa: S102
    return ns["_truncate_tool_result"]


_fn = _load()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Already fits
# ---------------------------------------------------------------------------

def test_already_fits_dict():
    data = {"a": 1, "b": 2}
    result = _fn(data, 10_000)
    assert json.loads(result) == data


def test_already_fits_list():
    data = [1, 2, 3]
    result = _fn(data, 10_000)
    assert json.loads(result) == data


def test_already_fits_string():
    result = _fn("hello", 10_000)
    assert result == '"hello"'


def test_already_fits_empty_dict():
    result = _fn({}, 10_000)
    assert json.loads(result) == {}


def test_already_fits_empty_list():
    result = _fn([], 10_000)
    assert json.loads(result) == []


# ---------------------------------------------------------------------------
# Empty collections (over budget — edge case, budget is absurdly tiny)
# ---------------------------------------------------------------------------

def test_empty_dict_tiny_budget():
    # {} is 2 chars; with budget=1 it should still return a valid truncated string
    result = _fn({}, 1)
    # Must not crash; result is allowed to be '…[TRUNCATED]' or the raw value
    assert isinstance(result, str)


def test_empty_list_tiny_budget():
    result = _fn([], 1)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Single oversized item
# ---------------------------------------------------------------------------

def test_single_item_dict_oversized():
    """Old code had `len(data) > 1` guard — single-item dicts fell through to
    naive string slice producing broken JSON like '{...[TRUNCATED]"}'."""
    big_val = "x" * 5000
    data = {"key": big_val}
    result = _fn(data, 200)
    assert len(result) <= 500  # generous; main thing is it's bounded
    # The result must contain a truncation marker or valid JSON
    assert "_truncated" in result or "TRUNCATED" in result or _is_valid_json(result)


def test_single_item_list_oversized():
    data = ["x" * 5000]
    result = _fn(data, 200)
    assert len(result) <= 500
    assert "_truncated" in result or "TRUNCATED" in result or _is_valid_json(result)


# ---------------------------------------------------------------------------
# Multi-item dict truncation
# ---------------------------------------------------------------------------

def test_dict_truncated_has_metadata():
    # Use small values so at least 1 item fits in the wrapper within budget
    data = {str(i): "v" * 20 for i in range(50)}
    result = _fn(data, 500)
    assert len(result) <= 1500  # wrapper overhead allowed
    parsed = json.loads(result)
    assert parsed["_truncated"] is True
    assert "_total_items" in parsed
    assert "_returned_items" in parsed
    assert parsed["_total_items"] == 50
    assert parsed["_returned_items"] < 50


def test_dict_truncated_items_are_subset():
    """Items in the truncated result must be the first N items."""
    data = {f"k{i}": i for i in range(50)}
    result = _fn(data, 300)
    parsed = json.loads(result)
    kept = parsed["items"]
    for key in kept:
        assert key in data


def test_dict_not_truncated_if_fits():
    data = {"a": 1, "b": 2, "c": 3}
    result = _fn(data, 10_000)
    assert json.loads(result) == data
    assert "_truncated" not in result


# ---------------------------------------------------------------------------
# List truncation
# ---------------------------------------------------------------------------

def test_list_truncated_has_metadata():
    data = [{"entity_id": f"light.light_{i}", "state": "on"} for i in range(100)]
    result = _fn(data, 500)
    parsed = json.loads(result)
    assert parsed["_truncated"] is True
    assert parsed["_total_items"] == 100
    assert parsed["_returned_items"] < 100


def test_list_truncated_items_are_prefix():
    # Use strings so the raw JSON exceeds budget and wrapper is triggered
    data = [f"entity_id_number_{i:04d}" for i in range(200)]
    result = _fn(data, 500)
    parsed = json.loads(result)
    assert parsed["_truncated"] is True
    kept = parsed["items"]
    # Items must be the first N items of data
    assert kept == data[:len(kept)]


# ---------------------------------------------------------------------------
# Unicode
# ---------------------------------------------------------------------------

def test_unicode_multibyte_chars_do_not_exceed_budget():
    """Unicode chars are multiple bytes but 1 char — truncation must use len()
    (chars), not byte length, to stay consistent with the rest of the pipeline."""
    data = {"msg": "こんにちは" * 500}
    budget = 300
    result = _fn(data, budget)
    # The char count of the result must be <= budget + wrapper overhead
    assert len(result) <= budget + 500  # generous for wrapper


def test_unicode_string_truncated():
    big = "é" * 10_000
    result = _fn(big, 100)
    assert len(result) <= 200


# ---------------------------------------------------------------------------
# Hard-slice fallback (primitives)
# ---------------------------------------------------------------------------

def test_primitive_int_fits():
    result = _fn(42, 100)
    assert json.loads(result) == 42


def test_primitive_string_truncated():
    result = _fn("a" * 5000, 50)
    assert len(result) <= 200  # 50 + marker
    assert "TRUNCATED" in result


def test_none_value():
    result = _fn(None, 100)
    assert result == "null"


def test_bool_value():
    result = _fn(True, 100)
    assert result == "true"


# ---------------------------------------------------------------------------
# Budget boundary: result is always within budget + small constant
# ---------------------------------------------------------------------------

def test_result_fits_within_reasonable_bounds():
    """No matter the input, result should never wildly exceed budget."""
    import random
    rng = random.Random(42)
    budget = 300
    for _ in range(50):
        choice = rng.randint(0, 3)
        if choice == 0:
            data = {str(i): "val" * rng.randint(1, 200) for i in range(rng.randint(1, 30))}
        elif choice == 1:
            data = ["item" * rng.randint(1, 200) for _ in range(rng.randint(1, 30))]
        elif choice == 2:
            data = "x" * rng.randint(1, 5000)
        else:
            data = rng.randint(0, 10000)
        result = _fn(data, budget)
        # Allow up to budget + 600 (wrapper overhead + marker)
        assert len(result) <= budget + 600, f"Result too long for input type {type(data)}"
