"""Tests for GET/POST /api/kyber/blueprint.

The endpoint reads and writes automation blueprint YAML files from
/config/blueprints/automation/<relative_path>.
"""
import pytest
from pathlib import Path
from unittest.mock import patch

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="requires pytest-homeassistant-custom-component",
)

from homeassistant.core import HomeAssistant

_BLUEPRINT_YAML = "blueprint:\n  name: My Blueprint\n  domain: automation\n"


@pytest.fixture
def blueprint_dir(tmp_path: Path) -> Path:
    """Create a temp blueprint dir tree mirroring /config/blueprints/automation/."""
    bp_dir = tmp_path / "blueprints" / "automation" / "custom"
    bp_dir.mkdir(parents=True)
    (bp_dir / "my_bp.yaml").write_text(_BLUEPRINT_YAML, encoding="utf-8")
    return tmp_path


def _patch_config_path(hass: HomeAssistant, tmp_path: Path):
    """Patch hass.config.path to resolve relative to tmp_path."""
    original = hass.config.path

    def _fake_path(*args):
        return str(tmp_path.joinpath(*args))

    hass.config.path = _fake_path
    return original


# ── GET ────────────────────────────────────────────────────────────────────────

async def test_get_blueprint_returns_yaml(
    hass: HomeAssistant, setup_integration, hass_client, blueprint_dir: Path
) -> None:
    """GET with a valid path returns 200 with the file contents."""
    orig = _patch_config_path(hass, blueprint_dir)
    try:
        client = await hass_client()
        resp = await client.get("/api/kyber/blueprint?path=custom/my_bp.yaml")
    finally:
        hass.config.path = orig

    assert resp.status == 200
    data = await resp.json()
    assert data["yaml"] == _BLUEPRINT_YAML
    assert data["path"] == "custom/my_bp.yaml"


async def test_get_blueprint_missing_path_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """GET without a path query param returns 400."""
    client = await hass_client()
    resp = await client.get("/api/kyber/blueprint")
    assert resp.status == 400


async def test_get_blueprint_traversal_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """GET with .. in path returns 400 (path traversal blocked)."""
    client = await hass_client()
    resp = await client.get("/api/kyber/blueprint?path=../secrets.yaml")
    assert resp.status == 400


async def test_get_blueprint_absolute_path_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """GET with absolute path returns 400."""
    client = await hass_client()
    resp = await client.get("/api/kyber/blueprint?path=/etc/passwd")
    assert resp.status == 400


async def test_get_blueprint_not_found_returns_404(
    hass: HomeAssistant, setup_integration, hass_client, blueprint_dir: Path
) -> None:
    """GET for a file that doesn't exist returns 404."""
    orig = _patch_config_path(hass, blueprint_dir)
    try:
        client = await hass_client()
        resp = await client.get("/api/kyber/blueprint?path=custom/missing.yaml")
    finally:
        hass.config.path = orig

    assert resp.status == 404


# ── POST ───────────────────────────────────────────────────────────────────────

async def test_post_blueprint_writes_file(
    hass: HomeAssistant, setup_integration, hass_client, blueprint_dir: Path
) -> None:
    """POST with valid path and yaml writes the file and returns {"result": "ok"}."""
    orig = _patch_config_path(hass, blueprint_dir)
    new_yaml = "blueprint:\n  name: Updated\n  domain: automation\n"
    try:
        client = await hass_client()
        resp = await client.post(
            "/api/kyber/blueprint",
            json={"path": "custom/my_bp.yaml", "yaml": new_yaml},
        )
    finally:
        hass.config.path = orig

    assert resp.status == 200
    data = await resp.json()
    assert data["result"] == "ok"
    # Verify the file was actually written
    written = (blueprint_dir / "blueprints" / "automation" / "custom" / "my_bp.yaml").read_text()
    assert written == new_yaml


async def test_post_blueprint_missing_path_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST without a path field returns 400."""
    client = await hass_client()
    resp = await client.post("/api/kyber/blueprint", json={"yaml": "x: 1"})
    assert resp.status == 400


async def test_post_blueprint_traversal_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST with .. in path returns 400."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/blueprint",
        json={"path": "../../secrets.yaml", "yaml": "evil: true"},
    )
    assert resp.status == 400


async def test_post_blueprint_not_found_returns_404(
    hass: HomeAssistant, setup_integration, hass_client, blueprint_dir: Path
) -> None:
    """POST for a path where the file doesn't exist returns 404."""
    orig = _patch_config_path(hass, blueprint_dir)
    try:
        client = await hass_client()
        resp = await client.post(
            "/api/kyber/blueprint",
            json={"path": "custom/nonexistent.yaml", "yaml": "blueprint:\n  name: New\n"},
        )
    finally:
        hass.config.path = orig

    assert resp.status == 404

