from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from custom_components.kyber.action_execution import KyberExecuteView
from custom_components.kyber.debug_and_diagnostics import (
    KyberDebugBundleView,
    KyberDebugLastTurnView,
    KyberDebugModeView,
    KyberDebugStatusView,
)
from custom_components.kyber.prompt_regression_api import (
    KyberPromptTestsCaptureView,
    KyberPromptTestsRegenerateView,
    KyberPromptTestsRunView,
    KyberPromptTestsView,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "custom_components" / "kyber"

_ADMIN_ENDPOINTS = [
    ("get", "/api/kyber/debug/last_turn", None),
    ("get", "/api/kyber/debug/status", None),
    ("get", "/api/kyber/debug/bundle", None),
    ("get", "/api/kyber/debug/mode", None),
    ("post", "/api/kyber/debug/mode", {"enabled": True}),
    ("get", "/api/kyber/prompt_tests", None),
    ("post", "/api/kyber/prompt_tests/run", {}),
    ("post", "/api/kyber/prompt_tests/capture", {}),
    ("post", "/api/kyber/prompt_tests/regenerate", {}),
    ("get", "/api/kyber/self_update", None),
    ("post", "/api/kyber/self_update", None),
    ("post", "/api/kyber/proposals/approve", None),
]


def _is_homeassistant_view(base: ast.expr) -> bool:
    return (
        isinstance(base, ast.Name) and base.id == "HomeAssistantView"
    ) or (
        isinstance(base, ast.Attribute) and base.attr == "HomeAssistantView"
    )


def test_all_homeassistant_views_require_auth() -> None:
    for path in sorted(SOURCE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(_is_homeassistant_view(base) for base in node.bases):
                continue
            has_requires_auth = any(
                isinstance(stmt, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "requires_auth" for target in stmt.targets)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is True
                for stmt in node.body
            )
            assert has_requires_auth, f"{path.name}:{node.name} must declare requires_auth = True"


@pytest.mark.parametrize(("method", "path", "payload"), _ADMIN_ENDPOINTS)
async def test_admin_endpoints_require_auth(
    hass,
    setup_integration,
    hass_client_no_auth,
    method: str,
    path: str,
    payload: dict | None,
) -> None:
    client = await hass_client_no_auth()
    request = getattr(client, method)
    kwargs = {"json": payload} if payload is not None else {}
    resp = await request(path, **kwargs)
    assert resp.status == 401


class _FakeRequest(dict):
    def __init__(self, *, is_admin: bool) -> None:
        super().__init__(hass_user=type("User", (), {"is_admin": is_admin})())
        self.app = {}

    async def json(self) -> dict:
        return {}


_ADMIN_VIEW_CALLS = [
    (KyberDebugLastTurnView(), "get"),
    (KyberDebugStatusView(), "get"),
    (KyberDebugBundleView(), "get"),
    (KyberDebugModeView(), "get"),
    (KyberDebugModeView(), "post"),
    (KyberPromptTestsView(), "get"),
    (KyberPromptTestsRunView(), "post"),
    (KyberPromptTestsCaptureView(), "post"),
    (KyberPromptTestsRegenerateView(), "post"),
]


@pytest.mark.parametrize(("view", "method"), _ADMIN_VIEW_CALLS)
async def test_admin_endpoints_reject_non_admins(
    view,
    method: str,
) -> None:
    request = _FakeRequest(is_admin=False)
    response = await getattr(view, method)(request)
    assert response.status == 403
    body = json.loads(response.text)
    assert body["message"] == "Admin required"


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/api/kyber/self_update"),
    ("post", "/api/kyber/self_update"),
    ("post", "/api/kyber/proposals/approve"),
])
async def test_admin_http_views_reject_non_admins(
    hass,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
    method: str,
    path: str,
) -> None:
    """Verify that non-admin authenticated requests to admin-only views return 403."""
    client = await hass_client(hass_read_only_access_token)
    resp = await getattr(client, method)(path)
    assert resp.status == 403
    body = await resp.json()
    assert body.get("message") == "Admin required"


async def test_execute_action_errors_do_not_leak_exception_details(
    hass,
    setup_integration,
    hass_client,
) -> None:
    async def _handle_turn_on(call) -> None:
        raise RuntimeError("sensitive failure details")

    hass.services.async_register("switch", "turn_on", _handle_turn_on)
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/execute",
        json={
            "summary": "Broken action",
            "actions": [{
                "type": "call_service",
                "domain": "switch",
                "service": "turn_on",
                "entity_id": "switch.broken_test",
            }],
        },
    )
    assert resp.status == 200
    payload = await resp.json()
    assert payload["results"][0]["message"] == "Internal error"


async def test_action_history_is_scoped_to_request_user(
    hass,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
) -> None:
    async def _handle_turn_on(call) -> None:
        return None

    async def _handle_turn_off(call) -> None:
        return None

    hass.services.async_register("switch", "turn_on", _handle_turn_on)
    hass.services.async_register("switch", "turn_off", _handle_turn_off)

    admin_client = await hass_client()
    readonly_client = await hass_client(hass_read_only_access_token)

    admin_execute = await admin_client.post(
        "/api/kyber/execute",
        json={
            "summary": "Admin action",
            "actions": [{
                "type": "call_service",
                "domain": "switch",
                "service": "turn_on",
                "entity_id": "switch.admin_test",
            }],
        },
    )
    assert admin_execute.status == 200
    admin_payload = await admin_execute.json()
    admin_entry_id = admin_payload["history_entry"]["id"]

    readonly_execute = await readonly_client.post(
        "/api/kyber/execute",
        json={
            "summary": "Readonly action",
            "actions": [{
                "type": "call_service",
                "domain": "switch",
                "service": "turn_on",
                "entity_id": "switch.readonly_test",
            }],
        },
    )
    assert readonly_execute.status == 200
    readonly_payload = await readonly_execute.json()
    readonly_entry_id = readonly_payload["history_entry"]["id"]

    admin_history = await admin_client.get("/api/kyber/history/actions")
    assert admin_history.status == 200
    admin_entries = (await admin_history.json())["entries"]
    assert [entry["summary"] for entry in admin_entries] == ["Admin action"]
    assert admin_entries[0]["user_id"] is not None
    assert admin_entries[0]["id"] == admin_entry_id

    readonly_history = await readonly_client.get("/api/kyber/history/actions")
    assert readonly_history.status == 200
    readonly_entries = (await readonly_history.json())["entries"]
    assert [entry["summary"] for entry in readonly_entries] == ["Readonly action"]
    assert readonly_entries[0]["id"] == readonly_entry_id

    readonly_entry = await readonly_client.get(f"/api/kyber/history/actions/{admin_entry_id}")
    assert readonly_entry.status == 404

    readonly_undo = await readonly_client.post(f"/api/kyber/history/actions/{admin_entry_id}/undo")
    assert readonly_undo.status == 404


async def test_execute_rejects_requests_without_resolved_user_id(hass) -> None:
    class _Request(dict):
        def __init__(self) -> None:
            super().__init__(hass_user=type("User", (), {"id": None})())
            self.app = {"hass": hass}

        async def json(self) -> dict:
            return {
                "summary": "Missing user",
                "actions": [{"type": "call_service", "domain": "light", "service": "turn_on", "entity_id": "light.kitchen"}],
            }

    response = await KyberExecuteView().post(_Request())

    assert response.status == 401
    assert json.loads(response.text) == {"message": "Unable to resolve authenticated user"}
