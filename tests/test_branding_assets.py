"""Tests for integration branding assets."""
import json
from pathlib import Path


_COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "kyber"


def test_kyber_branding_assets_exist() -> None:
    """Kyber should include icon and logo assets for HA/HACS display."""
    assert (_COMPONENT_DIR / "icon.png").is_file()
    assert (_COMPONENT_DIR / "logo.png").is_file()


def test_manifest_declares_minimum_homeassistant_version() -> None:
    """Kyber manifest should pin a minimum Home Assistant core version."""
    manifest = json.loads((_COMPONENT_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["homeassistant"] == "2025.2.0"
