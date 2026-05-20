"""Pytest configuration and shared fixtures for kyber tests."""
import threading

import pytest

try:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import storage as _ha_storage
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.kyber.const import DOMAIN
    from custom_components.kyber import async_setup_entry

    # Capture the real Store class at import time, before any stub test file
    # can overwrite it. Several test files do:
    #   sys.modules["homeassistant.helpers.storage"].Store = _Stub
    # at module scope, permanently corrupting the real Store for the pytest
    # session. The restore_ha_store fixture below undoes this before each test.
    _REAL_STORE = _ha_storage.Store

    _HA_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _HA_AVAILABLE = False


if _HA_AVAILABLE:
    @pytest.fixture(autouse=True)
    def restore_ha_store():
        """Restore the real Store class before each test.

        Stub test files overwrite homeassistant.helpers.storage.Store at module
        scope. mock_storage() (used by the hass fixture) accesses Store._async_load,
        which the stub doesn't have. Restoring the real class here prevents the
        AttributeError from contaminating unrelated tests.
        """
        _ha_storage.Store = _REAL_STORE
        yield
        _ha_storage.Store = _REAL_STORE

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Enable custom integrations for all tests in this package."""
        yield

    @pytest.fixture(autouse=True)
    def filter_ha_background_threads(monkeypatch):
        """Filter expected HA background threads so teardown checks don't false-positive."""
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
