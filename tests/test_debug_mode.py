"""Tests for the /api/kyber/debug/mode endpoint (KyberDebugModeView).

Covers:
  - requires_auth is True on the view class (pure unit test, no HA needed)
  - GET returns the default enabled state
  - GET reflects changes written to hass.data
  - POST enables / disables debug mode
  - POST with invalid JSON returns 400
  - Unauthenticated request to /debug/mode returns 401
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# ── HA + aiohttp stubs (same pattern as test_entity_id_autocomplete.py) ──────
_STUBS = [
    "homeassistant", "homeassistant.core", "homeassistant.components",
    "homeassistant.components.http", "homeassistant.helpers",
    "homeassistant.helpers.storage", "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry",
    "homeassistant.helpers.label_registry", "homeassistant.helpers.template",
    "homeassistant.const", "homeassistant.exceptions",
    "homeassistant.util", "homeassistant.util.dt",
    "homeassistant.config", "homeassistant.loader",
    "aiohttp", "aiohttp.web",
]
for _m in _STUBS:
    sys.modules.setdefault(_m, types.ModuleType(_m))
sys.modules["aiohttp"].web = types.ModuleType("aiohttp.web")


class _Stub:
    pass


sys.modules["homeassistant.components.http"].HomeAssistantView = _Stub
sys.modules["homeassistant.core"].HomeAssistant = _Stub
sys.modules["homeassistant.core"].callback = lambda f: f
sys.modules["homeassistant.helpers.storage"].Store = _Stub
sys.modules["homeassistant.exceptions"].HomeAssistantError = type("HomeAssistantError", (Exception,), {})
sys.modules["homeassistant.helpers"].area_registry = sys.modules["homeassistant.helpers.area_registry"]
sys.modules["homeassistant.helpers"].entity_registry = sys.modules["homeassistant.helpers.entity_registry"]
sys.modules["homeassistant.helpers"].label_registry = sys.modules["homeassistant.helpers.label_registry"]
sys.modules["homeassistant.helpers"].device_registry = sys.modules["homeassistant.helpers.device_registry"]
for _r in ("entity_registry", "area_registry", "device_registry", "label_registry"):
    sys.modules[f"homeassistant.helpers.{_r}"].async_get = lambda *a, **k: None
sys.modules.setdefault("homeassistant.components.ai_task", types.ModuleType("homeassistant.components.ai_task"))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_pkg_cc = types.ModuleType("custom_components")
_pkg_cc.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _pkg_cc)

_pkg_kyber = types.ModuleType("custom_components.kyber")
_pkg_kyber.__path__ = [str(ROOT / "custom_components" / "kyber")]
sys.modules.setdefault("custom_components.kyber", _pkg_kyber)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.kyber.const", ROOT / "custom_components" / "kyber" / "const.py")
_load("custom_components.kyber.knowledge", ROOT / "custom_components" / "kyber" / "knowledge.py")
_dd = _load(
    "custom_components.kyber.debug_and_diagnostics",
    ROOT / "custom_components" / "kyber" / "debug_and_diagnostics.py",
)

KyberDebugModeView = _dd.KyberDebugModeView
_DEBUG_MODE_KEY = _dd._DEBUG_MODE_KEY
_DEBUG_MODE_DEFAULT = _dd._DEBUG_MODE_DEFAULT


# ──────────────────────────────────────────────────────────────────────────────
# Pure unit tests (no HA runtime needed)
# ──────────────────────────────────────────────────────────────────────────────

def test_debug_mode_view_requires_auth() -> None:
    """KyberDebugModeView must declare requires_auth = True."""
    assert KyberDebugModeView.requires_auth is True


def test_debug_mode_default_is_true() -> None:
    """The module-level default should be True so new installs start with debug on."""
    assert _DEBUG_MODE_DEFAULT is True


def test_get_debug_mode_returns_default_when_key_absent() -> None:
    """_get_debug_mode should return _DEBUG_MODE_DEFAULT when hass.data has no key."""
    class _FakeHass:
        data: dict = {}

    result = _dd._get_debug_mode(_FakeHass())
    assert result == _DEBUG_MODE_DEFAULT


def test_get_debug_mode_returns_stored_value() -> None:
    """_get_debug_mode should return whatever is stored in hass.data."""
    class _FakeHass:
        data = {_DEBUG_MODE_KEY: False}

    assert _dd._get_debug_mode(_FakeHass()) is False


def test_get_debug_mode_coerces_to_bool() -> None:
    """_get_debug_mode must return a bool even when hass.data holds an int."""
    class _FakeHass:
        data = {_DEBUG_MODE_KEY: 0}

    result = _dd._get_debug_mode(_FakeHass())
    assert result is False
    assert isinstance(result, bool)


# ──────────────────────────────────────────────────────────────────────────────
# HA integration tests (skipped when pytest-homeassistant-custom-component is absent)
# ──────────────────────────────────────────────────────────────────────────────

try:
    import pytest_homeassistant_custom_component as _phcc  # noqa: F401
    _HA_AVAILABLE = True
except ImportError:
    _HA_AVAILABLE = False

_skip_no_ha = pytest.mark.skipif(
    not _HA_AVAILABLE,
    reason="requires pytest-homeassistant-custom-component",
)

try:
    from homeassistant.core import HomeAssistant as _HomeAssistant  # noqa: F401
except ImportError:
    _HomeAssistant = object  # type: ignore[assignment,misc]


@_skip_no_ha
async def test_debug_mode_unauthenticated_returns_401(
    hass, setup_integration, hass_client_no_auth
) -> None:
    """An unauthenticated request to /api/kyber/debug/mode must be rejected with 401."""
    client = await hass_client_no_auth()
    resp = await client.get("/api/kyber/debug/mode")
    assert resp.status == 401


# ──────────────────────────────────────────────────────────────────────────────
# GET
# ──────────────────────────────────────────────────────────────────────────────

@_skip_no_ha
async def test_debug_mode_get_default(
    hass, setup_integration, hass_client
) -> None:
    """GET /api/kyber/debug/mode should return the default enabled state."""
    client = await hass_client()
    resp = await client.get("/api/kyber/debug/mode")
    assert resp.status == 200
    body = await resp.json()
    assert "enabled" in body
    assert body["enabled"] == _DEBUG_MODE_DEFAULT


@_skip_no_ha
async def test_debug_mode_get_reflects_hass_data(
    hass, setup_integration, hass_client
) -> None:
    """GET should reflect the value stored in hass.data, not just the default."""
    hass.data[_DEBUG_MODE_KEY] = not _DEBUG_MODE_DEFAULT
    client = await hass_client()
    resp = await client.get("/api/kyber/debug/mode")
    assert resp.status == 200
    body = await resp.json()
    assert body["enabled"] is not _DEBUG_MODE_DEFAULT


# ──────────────────────────────────────────────────────────────────────────────
# POST — toggle
# ──────────────────────────────────────────────────────────────────────────────

@_skip_no_ha
async def test_debug_mode_post_enable(
    hass, setup_integration, hass_client
) -> None:
    """POST {"enabled": true} should enable debug mode and persist to hass.data."""
    client = await hass_client()
    resp = await client.post("/api/kyber/debug/mode", json={"enabled": True})
    assert resp.status == 200
    body = await resp.json()
    assert body["enabled"] is True
    assert hass.data[_DEBUG_MODE_KEY] is True


@_skip_no_ha
async def test_debug_mode_post_disable(
    hass, setup_integration, hass_client
) -> None:
    """POST {"enabled": false} should disable debug mode and persist to hass.data."""
    client = await hass_client()
    resp = await client.post("/api/kyber/debug/mode", json={"enabled": False})
    assert resp.status == 200
    body = await resp.json()
    assert body["enabled"] is False
    assert hass.data[_DEBUG_MODE_KEY] is False


@_skip_no_ha
async def test_debug_mode_post_toggle_roundtrip(
    hass, setup_integration, hass_client
) -> None:
    """POST then GET should return consistent state."""
    client = await hass_client()

    # Disable
    await client.post("/api/kyber/debug/mode", json={"enabled": False})
    resp = await client.get("/api/kyber/debug/mode")
    assert (await resp.json())["enabled"] is False

    # Re-enable
    await client.post("/api/kyber/debug/mode", json={"enabled": True})
    resp = await client.get("/api/kyber/debug/mode")
    assert (await resp.json())["enabled"] is True


@_skip_no_ha
async def test_debug_mode_post_missing_enabled_uses_default(
    hass, setup_integration, hass_client
) -> None:
    """POST with no 'enabled' key should fall back to the default value."""
    client = await hass_client()
    resp = await client.post("/api/kyber/debug/mode", json={})
    assert resp.status == 200
    body = await resp.json()
    assert body["enabled"] == _DEBUG_MODE_DEFAULT


# ──────────────────────────────────────────────────────────────────────────────
# POST — error handling
# ──────────────────────────────────────────────────────────────────────────────

@_skip_no_ha
async def test_debug_mode_post_invalid_json_returns_400(
    hass, setup_integration, hass_client
) -> None:
    """POST with a non-JSON body should return 400 Bad Request."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/debug/mode",
        data="not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400
