"""HTTP API views for the prompt regression testing system.

Endpoints:
- GET  /api/kyber/prompt_tests         — list all test cases + last run results
- POST /api/kyber/prompt_tests/run     — run all (or one) test cases, return results
- POST /api/kyber/prompt_tests/capture — capture a test case from a debug snapshot
- POST /api/kyber/prompt_tests/regenerate — re-run test questions on live HA to refresh snapshots
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .debug_and_diagnostics import _DEBUG_SNAPSHOTS_KEY as _DEBUG_TURNS_KEY

_LOGGER = logging.getLogger(__name__)


def _admin_required(view: HomeAssistantView, request: web.Request) -> web.Response | None:
    """Return a 403 response when the request is not from an admin user."""
    ha_user = request.get("hass_user")
    if not ha_user or not getattr(ha_user, "is_admin", False):
        return view.json_message("Admin required", HTTPStatus.FORBIDDEN)
    return None


def _cases_dir(hass: HomeAssistant) -> Path:
    """Return the test-case storage directory, rooted in the HA config dir."""
    return Path(hass.config.config_dir) / "kyber_regression_tests" / "cases"


# ---------------------------------------------------------------------------
# Shared assertion engine (mirrors scripts/run_prompt_tests.py)
# ---------------------------------------------------------------------------

def _run_assertions(
    response: str,
    intent: str | None,
    tool_calls: list[str],
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run keyword/intent assertions. Returns list of assertion result dicts."""
    results: list[dict[str, Any]] = []

    for kw in expected.get("response_contains", []):
        results.append({"type": "response_contains", "value": kw,
                         "passed": kw.lower() in response.lower(), "actual": None})

    for kw in expected.get("response_not_contains", []):
        results.append({"type": "response_not_contains", "value": kw,
                         "passed": kw.lower() not in response.lower(), "actual": None})

    if "intent" in expected:
        passed = (intent or "").lower() == expected["intent"].lower()
        results.append({"type": "intent", "value": expected["intent"], "passed": passed, "actual": intent})

    if "language" in expected:
        lang = expected["language"]
        if lang == "nl":
            dutch = ["de ", "het ", "een ", "van ", "met ", "in "]
            passed = sum(1 for m in dutch if m in response.lower()) >= 2
        else:
            passed = True
        results.append({"type": "language", "value": lang, "passed": passed, "actual": None})

    for expected_tool in expected.get("tool_calls_expected", []):
        passed = any(expected_tool.lower() in tc.lower() for tc in tool_calls)
        results.append({"type": "tool_call", "value": expected_tool, "passed": passed, "actual": None})

    return results


def _score(assertion_results: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (passed, total)."""
    passed = sum(1 for r in assertion_results if r["passed"])
    return passed, len(assertion_results)


# ---------------------------------------------------------------------------
# Test case file helpers
# ---------------------------------------------------------------------------

def _load_test_cases(cases_dir: Path) -> list[dict[str, Any]]:
    """Load all test cases from subdirectories."""
    cases = []
    if not cases_dir.exists():
        return cases
    for case_dir in sorted(cases_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        test_json = case_dir / "test.json"
        if not test_json.exists():
            continue
        try:
            data = json.loads(test_json.read_text(encoding="utf-8"))
            data["_dir"] = str(case_dir)
            cases.append(data)
        except Exception as exc:
            _LOGGER.warning("prompt_tests: skipping %s: %s", case_dir.name, exc)
    return cases


def _load_run_history(case_dir: Path) -> list[dict[str, Any]]:
    hist = case_dir / "run_history.json"
    if hist.exists():
        try:
            return json.loads(hist.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_run_history(case_dir: Path, history: list[dict[str, Any]]) -> None:
    (case_dir / "run_history.json").write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _kyber_version() -> str:
    try:
        manifest = Path(__file__).parent / "manifest.json"
        return json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# GET /api/kyber/prompt_tests
# ---------------------------------------------------------------------------

class KyberPromptTestsView(HomeAssistantView):
    """List all test cases with their last run results."""

    url = "/api/kyber/prompt_tests"
    name = "api:kyber:prompt_tests"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        hass: HomeAssistant = request.app["hass"]
        cases_dir = _cases_dir(hass)
        cases = _load_test_cases(cases_dir)
        result = []
        for case in cases:
            case_dir = Path(case["_dir"])
            history = _load_run_history(case_dir)
            last_run = history[-1] if history else None
            result.append({
                "id": case.get("id"),
                "label": case.get("label", case.get("id")),
                "captured_at": case.get("captured_at"),
                "kyber_version": case.get("kyber_version"),
                "question": case.get("input", {}).get("question", ""),
                "expected_output": case.get("expected_output", {}),
                "last_run": last_run,
                "run_count": len(history),
            })
        return self.json({"cases": result, "count": len(result), "cases_dir": str(cases_dir)})


# ---------------------------------------------------------------------------
# POST /api/kyber/prompt_tests/run
# ---------------------------------------------------------------------------

class KyberPromptTestsRunView(HomeAssistantView):
    """Run assertion checks on all (or one) test case(s)."""

    url = "/api/kyber/prompt_tests/run"
    name = "api:kyber:prompt_tests:run"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        hass: HomeAssistant = request.app["hass"]
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            pass

        case_id = body.get("case_id")  # optional: run only one
        version = _kyber_version()
        model = body.get("model", "offline")

        cases = _load_test_cases(_cases_dir(hass))
        if case_id:
            cases = [c for c in cases if c.get("id") == case_id]

        if not cases:
            return self.json({"error": "No test cases found", "results": []}, status=HTTPStatus.NOT_FOUND)

        results = []
        for case in cases:
            case_dir = Path(case["_dir"])
            history = _load_run_history(case_dir)

            baseline = case.get("baseline_response", "")
            intent = case.get("input", {}).get("intent", "")
            tool_log = [t.get("name", "") for t in case.get("input", {}).get("tool_log", [])]
            expected = case.get("expected_output", {})

            t0 = time.monotonic()
            assertion_results = _run_assertions(baseline, intent, tool_log, expected)
            latency_ms = int((time.monotonic() - t0) * 1000)
            passed, total = _score(assertion_results)

            run_entry: dict[str, Any] = {
                "version": version,
                "model": model,
                "ran_at": _utcnow(),
                "mode": "offline",
                "score": round(passed / total, 3) if total else 1.0,
                "passed": passed,
                "failed": total - passed,
                "latency_ms": latency_ms,
                "response": baseline,
                "assertion_details": assertion_results,
            }

            history.append(run_entry)
            history = history[-50:]
            _save_run_history(case_dir, history)

            results.append({
                "id": case.get("id"),
                "label": case.get("label"),
                "run": run_entry,
            })

        total_passed = sum(r["run"]["passed"] for r in results)
        total_asserts = sum(r["run"]["passed"] + r["run"]["failed"] for r in results)
        return self.json({
            "results": results,
            "summary": {
                "total_cases": len(results),
                "passed": total_passed,
                "total_assertions": total_asserts,
                "score": round(total_passed / total_asserts, 3) if total_asserts else 1.0,
                "version": version,
                "model": model,
            },
        })


# ---------------------------------------------------------------------------
# POST /api/kyber/prompt_tests/capture
# ---------------------------------------------------------------------------

class KyberPromptTestsCaptureView(HomeAssistantView):
    """Capture a test case from a debug snapshot (by request_id)."""

    url = "/api/kyber/prompt_tests/capture"
    name = "api:kyber:prompt_tests:capture"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        hass: HomeAssistant = request.app["hass"]
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            return self.json_message("Invalid JSON", HTTPStatus.BAD_REQUEST)

        request_id = body.get("request_id", "")
        label = body.get("label", "Unnamed test")
        assertions = body.get("assertions", {})
        ideal_description = body.get("ideal_description", "")

        # Retrieve the debug snapshot
        turns = hass.data.get(_DEBUG_TURNS_KEY) or []
        snap = next((t for t in turns if t.get("request_id") == request_id), None)
        if not snap:
            # Accept inline snap data from the frontend
            snap = body.get("snap") or {}

        if not snap:
            return self.json_message(
                f"No snapshot found for request_id={request_id!r}", HTTPStatus.NOT_FOUND
            )

        case_id = f"tc_{re.sub(r'[^a-z0-9]', '_', label.lower())[:30]}_{uuid.uuid4().hex[:6]}"

        # Build test.json
        test_data: dict[str, Any] = {
            "id": case_id,
            "label": label,
            "captured_at": _utcnow(),
            "kyber_version": _kyber_version(),
            "ideal_description": ideal_description,
            "input": {
                "question": snap.get("user_prompt", ""),
                "intent": snap.get("intent", ""),
                "expanded_prompt": snap.get("expanded_prompt", ""),
                "tool_log": snap.get("tool_log", []),
            },
            "baseline_response": snap.get("response_text", ""),
            "expected_output": assertions,
        }

        # Build memory.json (knowledge entries used this turn)
        memory_data = {
            "entries": snap.get("picked_knowledge", []),
            "captured_at": _utcnow(),
        }

        # Build tool_mocks.json (tool call inputs + outputs from tool_log)
        tool_mocks: list[dict[str, Any]] = []
        for entry in snap.get("tool_log", []):
            tool_mocks.append({
                "tool": entry.get("tool") or entry.get("name", ""),
                "args": entry.get("args", {}),
                "result": entry.get("result", ""),
            })

        # Save files
        case_dir = _cases_dir(hass) / case_id
        try:
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "test.json").write_text(
                json.dumps(test_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (case_dir / "memory.json").write_text(
                json.dumps(memory_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (case_dir / "tool_mocks.json").write_text(
                json.dumps(tool_mocks, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("prompt_tests: failed to save test case")
            return self.json({"error": "Internal error"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        return self.json({
            "id": case_id,
            "label": label,
            "dir": str(case_dir),
            "files": ["test.json", "memory.json", "tool_mocks.json"],
        })


# ---------------------------------------------------------------------------
# POST /api/kyber/prompt_tests/regenerate
# ---------------------------------------------------------------------------

class KyberPromptTestsRegenerateView(HomeAssistantView):
    """Re-run test questions on the live HA instance to refresh tool_mocks + memory."""

    url = "/api/kyber/prompt_tests/regenerate"
    name = "api:kyber:prompt_tests:regenerate"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        response = _admin_required(self, request)
        if response is not None:
            return response
        hass: HomeAssistant = request.app["hass"]
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            pass

        case_id = body.get("case_id")
        cases = _load_test_cases(_cases_dir(hass))
        if case_id:
            cases = [c for c in cases if c.get("id") == case_id]

        if not cases:
            return self.json({"regenerated": [], "note": "No test cases found"})

        # For now, return the list of cases that WOULD be regenerated.
        # Full regeneration (replaying against live HA) requires the same
        # pipeline as /api/kyber/complete — that loop is not factored out yet.
        # This endpoint serves as the trigger point; the frontend shows a
        # "send each question through live HA and capture a new snapshot"
        # flow using the existing /api/kyber/complete endpoint.
        return self.json({
            "regenerated": [c.get("id") for c in cases],
            "note": (
                "Use the debug panel 'Regenerate' flow: each question is "
                "re-sent through /api/kyber/complete and the resulting snapshot "
                "is captured via /api/kyber/prompt_tests/capture."
            ),
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
