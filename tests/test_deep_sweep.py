"""Forced deep-analysis runs work through all items instead of
repeating the first `limit` ones."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant

# Imported at test time: other test modules swap stubs into sys.modules while
# they are collected; conftest restores the real modules before each test.


def _deep():
    from custom_components.kyber import deep_analyzer
    return deep_analyzer


def _automations(n: int) -> list[dict]:
    return [
        {
            "id": f"a{i:02d}",
            "alias": f"Automation {i}",
            "description": "",
            "mode": "single",
            "trigger": [],
            "condition": [],
            "action": [],
            "num_triggers": 0,
            "num_actions": 0,
            "hash": f"h{i}",
        }
        for i in range(n)
    ]


async def _run(hass: HomeAssistant, items: list[dict], run_ai: AsyncMock, **kwargs) -> dict:
    deep = _deep()
    with (
        patch.object(deep, "read_automations", return_value=items),
        patch.object(deep, "_run_ai", run_ai),
    ):
        return await deep.analyze_pending(
            hass, ai_entity_id="ai_task.test", kinds=["automation"], force=True, **kwargs
        )


def _idents(result: dict) -> list[str]:
    return [a["ident"] for a in result["analyzed"]]


async def test_forced_runs_cover_all_items_with_rotating_lens(hass: HomeAssistant) -> None:
    items = _automations(12)
    run_ai = AsyncMock(return_value="[]")
    sweep: set[str] = set()
    seen: list[str] = []
    for variant in range(3):
        result = await _run(hass, items, run_ai, limit=5, prompt_variant=variant, sweep=sweep)
        seen += _idents(result)

    assert sorted(seen) == [f"a{i:02d}" for i in range(12)]  # each exactly once
    # The lens follows prompt_variant per run.
    from custom_components.kyber.source import get_memo
    memo = get_memo(hass)
    assert memo.get("automation", "a00")["lenses_done"] == [0]
    assert memo.get("automation", "a11")["lenses_done"] == [2]


async def test_sweep_starts_next_round_when_exhausted(hass: HomeAssistant) -> None:
    items = _automations(4)
    run_ai = AsyncMock(return_value="[]")
    sweep: set[str] = set()
    first = await _run(hass, items, run_ai, limit=5, prompt_variant=0, sweep=sweep)
    second = await _run(hass, items, run_ai, limit=5, prompt_variant=1, sweep=sweep)

    assert sorted(_idents(first)) == ["a00", "a01", "a02", "a03"]
    assert sorted(_idents(second)) == ["a00", "a01", "a02", "a03"]


async def test_failing_item_does_not_block_the_sweep(hass: HomeAssistant) -> None:
    items = _automations(4)

    async def _ai(_hass, _eid, prompt):
        if "Automation 0" in prompt:
            raise RuntimeError("model down")
        return "[]"

    sweep: set[str] = set()
    first = await _run(hass, items, AsyncMock(side_effect=_ai), limit=2, sweep=sweep)
    second = await _run(hass, items, AsyncMock(side_effect=_ai), limit=2, sweep=sweep)

    assert [e["ident"] for e in first["errors"]] == ["a00"]
    assert _idents(first) == ["a01"]
    assert sorted(_idents(second)) == ["a02", "a03"]  # a00 not retried in this round


async def test_without_sweep_least_recently_analysed_first(hass: HomeAssistant) -> None:
    """Single forced calls (synchronous view path) also rotate."""
    items = _automations(6)
    run_ai = AsyncMock(return_value="[]")
    first = await _run(hass, items, run_ai, limit=3)
    second = await _run(hass, items, run_ai, limit=3)

    assert _idents(first) == ["a00", "a01", "a02"]
    assert _idents(second) == ["a03", "a04", "a05"]
