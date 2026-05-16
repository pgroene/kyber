"""Tests for integration branding assets."""
from pathlib import Path


_COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "kyber"


def test_kyber_branding_assets_exist() -> None:
    """Kyber should include icon and logo assets for HA/HACS display."""
    assert (_COMPONENT_DIR / "icon.png").is_file()
    assert (_COMPONENT_DIR / "logo.png").is_file()
