"""Unit tests for scripts/run_prompt_tests.py assertion engine."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_prompt_tests",
        ROOT / "scripts" / "run_prompt_tests.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_RUNNER = _load_runner()


# ---------------------------------------------------------------------------
# run_assertions
# ---------------------------------------------------------------------------

class TestRunAssertions:
    def _run(self, response, **kwargs):
        return _RUNNER.run_assertions(
            response,
            kwargs.get("intent"),
            kwargs.get("tool_calls", []),
            kwargs.get("expected", {}),
        )

    def test_response_contains_pass(self):
        results = self._run("Het is 21 graden in de slaapkamer.", expected={"response_contains": ["slaapkamer", "21"]})
        assert all(r["passed"] for r in results)

    def test_response_contains_fail(self):
        results = self._run("Het is warm.", expected={"response_contains": ["slaapkamer"]})
        assert not results[0]["passed"]

    def test_response_not_contains_pass(self):
        results = self._run("De slaapkamer is 21 graden.", expected={"response_not_contains": ["unknown"]})
        assert results[0]["passed"]

    def test_response_not_contains_fail(self):
        results = self._run("unknown state", expected={"response_not_contains": ["unknown"]})
        assert not results[0]["passed"]

    def test_intent_match(self):
        results = self._run("OK", intent="query_state", expected={"intent": "query_state"})
        assert results[0]["passed"]

    def test_intent_mismatch(self):
        results = self._run("OK", intent="execute_action", expected={"intent": "query_state"})
        assert not results[0]["passed"]

    def test_dutch_language_detection(self):
        results = self._run("De slaapkamer heeft een temperatuur van 21 graden.", expected={"language": "nl"})
        assert results[0]["passed"]

    def test_dutch_language_fail_on_english(self):
        results = self._run("The bedroom temperature is 21 degrees.", expected={"language": "nl"})
        # English text should fail the Dutch detection heuristic
        assert not results[0]["passed"]

    def test_tool_call_expected_pass(self):
        results = self._run("OK", tool_calls=["get_entity_state"], expected={"tool_calls_expected": ["get_entity_state"]})
        assert results[0]["passed"]

    def test_tool_call_expected_fail(self):
        results = self._run("OK", tool_calls=["list_entities"], expected={"tool_calls_expected": ["get_entity_state"]})
        assert not results[0]["passed"]

    def test_case_insensitive_contains(self):
        results = self._run("Slaapkamer temperatuur is 21.", expected={"response_contains": ["slaapkamer"]})
        assert results[0]["passed"]

    def test_empty_assertions(self):
        results = self._run("anything", expected={})
        assert results == []


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

class TestScore:
    def test_all_pass(self):
        r = [{"passed": True}, {"passed": True}]
        assert _RUNNER.score(r) == (2, 2)

    def test_partial_pass(self):
        r = [{"passed": True}, {"passed": False}, {"passed": True}]
        assert _RUNNER.score(r) == (2, 3)

    def test_all_fail(self):
        r = [{"passed": False}]
        assert _RUNNER.score(r) == (0, 1)

    def test_empty(self):
        assert _RUNNER.score([]) == (0, 0)


# ---------------------------------------------------------------------------
# run_offline
# ---------------------------------------------------------------------------

class TestRunOffline:
    def _make_case(self, response="OK", intent="query_state", expected=None):
        return {
            "id": "tc_test",
            "label": "Test",
            "baseline_response": response,
            "input": {"intent": intent, "tool_log": []},
            "expected_output": expected or {"response_contains": ["OK"], "intent": "query_state"},
        }

    def test_all_passing(self):
        case = self._make_case()
        result = _RUNNER.run_offline(case, "0.1.103", "offline")
        assert result["passed"] == 2
        assert result["failed"] == 0
        assert result["score"] == 1.0
        assert result["version"] == "0.1.103"
        assert result["model"] == "offline"
        assert "ran_at" in result
        assert "latency_ms" in result
        assert "assertion_details" in result

    def test_failing_assertion(self):
        case = self._make_case(response="Something else", expected={"response_contains": ["missing_keyword"]})
        result = _RUNNER.run_offline(case, "0.1.103", "offline")
        assert result["failed"] == 1
        assert result["score"] == 0.0


# ---------------------------------------------------------------------------
# run_history persistence
# ---------------------------------------------------------------------------

class TestRunHistory:
    def test_save_and_load(self, tmp_path):
        history = [{"version": "0.1.103", "model": "offline", "score": 1.0}]
        _RUNNER.save_run_history(tmp_path, history)
        loaded = _RUNNER.load_run_history(tmp_path)
        assert loaded == history

    def test_load_missing_returns_empty(self, tmp_path):
        assert _RUNNER.load_run_history(tmp_path) == []

    def test_save_load_roundtrip_unicode(self, tmp_path):
        history = [{"version": "0.1.103", "response": "De slaapkamer heeft 21°C."}]
        _RUNNER.save_run_history(tmp_path, history)
        loaded = _RUNNER.load_run_history(tmp_path)
        assert loaded[0]["response"] == "De slaapkamer heeft 21°C."


# ---------------------------------------------------------------------------
# load_test_cases
# ---------------------------------------------------------------------------

class TestLoadTestCases:
    def test_loads_valid_case(self, tmp_path):
        case_dir = tmp_path / "tc_test_001"
        case_dir.mkdir()
        (case_dir / "test.json").write_text(
            json.dumps({"id": "tc_test_001", "label": "Test", "input": {}, "expected_output": {}}),
            encoding="utf-8",
        )
        cases = _RUNNER.load_test_cases(tmp_path)
        assert len(cases) == 1
        assert cases[0]["id"] == "tc_test_001"

    def test_skips_dir_without_test_json(self, tmp_path):
        empty_dir = tmp_path / "tc_empty"
        empty_dir.mkdir()
        cases = _RUNNER.load_test_cases(tmp_path)
        assert len(cases) == 0

    def test_skips_invalid_json(self, tmp_path):
        case_dir = tmp_path / "tc_bad"
        case_dir.mkdir()
        (case_dir / "test.json").write_text("not json", encoding="utf-8")
        cases = _RUNNER.load_test_cases(tmp_path)
        assert len(cases) == 0

    def test_attaches_dir(self, tmp_path):
        case_dir = tmp_path / "tc_check"
        case_dir.mkdir()
        (case_dir / "test.json").write_text(json.dumps({"id": "tc_check"}), encoding="utf-8")
        cases = _RUNNER.load_test_cases(tmp_path)
        assert "_dir" in cases[0]
        assert Path(cases[0]["_dir"]) == case_dir


# ---------------------------------------------------------------------------
# trend arrow
# ---------------------------------------------------------------------------

class TestTrendArrow:
    def _hist(self, scores, versions):
        return [{"version": v, "model": "offline", "score": s} for v, s in zip(versions, scores)]

    def test_new_test(self):
        assert _RUNNER._trend_arrow([], 1.0, "0.1.103") == "🆕"

    def test_same_score(self):
        hist = self._hist([1.0], ["0.1.102"])
        assert _RUNNER._trend_arrow(hist, 1.0, "0.1.103") == "→"

    def test_small_improvement(self):
        hist = self._hist([0.8], ["0.1.102"])
        assert _RUNNER._trend_arrow(hist, 0.9, "0.1.103") == "↑"

    def test_big_improvement(self):
        hist = self._hist([0.5], ["0.1.102"])
        assert _RUNNER._trend_arrow(hist, 0.9, "0.1.103") == "↑↑"

    def test_regression(self):
        hist = self._hist([1.0], ["0.1.102"])
        assert _RUNNER._trend_arrow(hist, 0.8, "0.1.103") == "↓"
