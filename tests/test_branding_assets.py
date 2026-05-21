"""Tests for integration branding assets."""
import json
from pathlib import Path


_COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "kyber"


def test_kyber_branding_assets_exist() -> None:
    """Kyber should include icon and logo assets for HA/HACS display."""
    assert (_COMPONENT_DIR / "icon.png").is_file()
    assert (_COMPONENT_DIR / "logo.png").is_file()


def test_manifest_is_valid() -> None:
    """Kyber manifest should have required fields and correct structure."""
    manifest = json.loads((_COMPONENT_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "kyber"
    assert manifest["name"] == "Kyber"
    assert "recorder" in manifest.get("after_dependencies", [])
    # 'homeassistant' min-version key was removed — Hassfest rejects it in newer HA versions
    assert "homeassistant" not in manifest
