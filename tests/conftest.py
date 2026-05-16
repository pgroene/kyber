"""Pytest configuration and shared fixtures for kyber tests."""
import threading

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kyber.const import DOMAIN
from custom_components.kyber import async_setup_entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests in this package."""
    yield


@pytest.fixture(autouse=True)
def filter_ha_background_threads(monkeypatch):
    """Filter expected HA background threads so teardown checks don't false-positive.

    HA's HTTP server spawns a '_run_safe_shutdown_loop' daemon thread that may
    still be alive during the post-test thread check in
    pytest-homeassistant-custom-component.  Patching threading.enumerate here
    removes it from the enumeration before the check runs.
    """
    _orig = threading.enumerate

    def _filtered():
        return [t for t in _orig() if "_run_safe_shutdown_loop" not in t.name]

    monkeypatch.setattr(threading, "enumerate", _filtered)
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry with default test settings."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "max_tokens": 2048,
        },
        title="Kyber",
    )


@pytest.fixture
async def setup_integration(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """Set up HTTP component and register views directly, bypassing external dependencies."""
    await async_setup_component(hass, "http", {})
    await async_setup_entry(hass, mock_config_entry)
    yield mock_config_entry
