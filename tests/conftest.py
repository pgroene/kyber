"""Pytest configuration and shared fixtures for kyber tests."""
import sys
import threading

import pytest

try:
    import homeassistant.components.http as _ha_http
    import homeassistant.core as _ha_core
    import homeassistant.exceptions as _ha_exc
    import homeassistant.helpers.area_registry as _ha_area_reg
    import homeassistant.helpers.device_registry as _ha_device_reg
    import homeassistant.helpers.entity_registry as _ha_entity_reg
    import homeassistant.helpers.label_registry as _ha_label_reg
    import homeassistant.helpers.storage as _ha_storage
    from homeassistant.core import HomeAssistant
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    # Import all kyber sub-modules that stub test files corrupt, so we capture
    # their real objects before any test file is imported.
    import custom_components.kyber as _kyber_pkg
    import custom_components.kyber.analyzer as _kyber_analyzer
    import custom_components.kyber.const as _kyber_const_mod
    import custom_components.kyber.debug_and_diagnostics as _kyber_debug
    import custom_components.kyber.entity_narrator as _kyber_entity_narrator
    import custom_components.kyber.http_api as _kyber_http_api
    import custom_components.kyber.integration_explorer as _kyber_ie
    import custom_components.kyber.intent_and_context as _kyber_intent
    import custom_components.kyber.knowledge as _kyber_knowledge
    import custom_components.kyber.language_hints as _kyber_language_hints
    import custom_components.kyber.source as _kyber_source
    import custom_components.kyber.tool_execution as _kyber_tool_execution
    from custom_components.kyber.const import DOMAIN
    from custom_components.kyber import async_setup_entry

    # ── Real HA attributes ────────────────────────────────────────────────────
    # Several test files overwrite HA module attributes at module scope:
    #   sys.modules["homeassistant.helpers.storage"].Store = _Stub
    # Capture the real values here (conftest is imported before any test file).
    _REAL_HA_ATTRS = [
        (_ha_storage,    "Store",              _ha_storage.Store),
        (_ha_core,        "HomeAssistant",      _ha_core.HomeAssistant),
        (_ha_core,        "callback",           _ha_core.callback),
        (_ha_http,        "HomeAssistantView",  _ha_http.HomeAssistantView),
        (_ha_exc,         "HomeAssistantError", _ha_exc.HomeAssistantError),
        (_ha_area_reg,    "async_get",          _ha_area_reg.async_get),
        (_ha_device_reg,  "async_get",          _ha_device_reg.async_get),
        (_ha_entity_reg,  "async_get",          _ha_entity_reg.async_get),
        (_ha_label_reg,   "async_get",          _ha_label_reg.async_get),
    ]

    # ── Kyber modules fully replaced in sys.modules by stubs ─────────────────
    # Some stub test files do:  sys.modules["custom_components.kyber.X"] = stub
    # (without setdefault), completely replacing the real module.  Restore just
    # those specific modules — not ALL kyber modules, to avoid disrupting tests
    # that use patch() on kyber modules legitimately.
    _STUB_REPLACED_KYBER_MODULES = {
        "custom_components.kyber":                          _kyber_pkg,
        "custom_components.kyber.analyzer":                 _kyber_analyzer,
        "custom_components.kyber.const":                    _kyber_const_mod,
        "custom_components.kyber.debug_and_diagnostics":    _kyber_debug,
        "custom_components.kyber.http_api":                 _kyber_http_api,
        "custom_components.kyber.integration_explorer":     _kyber_ie,
        "custom_components.kyber.entity_narrator":          _kyber_entity_narrator,
        "custom_components.kyber.intent_and_context":       _kyber_intent,
        "custom_components.kyber.knowledge":                _kyber_knowledge,
        "custom_components.kyber.language_hints":           _kyber_language_hints,
        "custom_components.kyber.source":                   _kyber_source,
        "custom_components.kyber.tool_execution":           _kyber_tool_execution,
    }

    # ── Real kyber module attributes ──────────────────────────────────────────
    # Stub files overwrite specific attributes on real module objects. Only
    # include attributes that are confirmed to exist in the current codebase.
    _REAL_KYBER_ATTRS = [
        entry for entry in [
            (_kyber_analyzer, "analyze_automations",
             getattr(_kyber_analyzer, "analyze_automations", None)),
            (_kyber_ie, "IntegrationExplorer",
             getattr(_kyber_ie, "IntegrationExplorer", None)),
            (_kyber_knowledge, "CATEGORIES",
             getattr(_kyber_knowledge, "CATEGORIES", None)),
            (_kyber_knowledge, "get_store",
             getattr(_kyber_knowledge, "get_store", None)),
            (_kyber_source, "read_automations",
             getattr(_kyber_source, "read_automations", None)),
            (_kyber_source, "read_scenes",
             getattr(_kyber_source, "read_scenes", None)),
            (_kyber_source, "read_scripts",
             getattr(_kyber_source, "read_scripts", None)),
        ]
        if entry[2] is not None
    ]

    _HA_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _HA_AVAILABLE = False


if _HA_AVAILABLE:
    def pytest_runtest_setup(item):  # noqa: ARG001
        """Restore real HA and kyber modules/attributes before any fixture runs.

        Stub test files corrupt global state at module scope (both HA and kyber
        modules). pytest_runtest_setup fires before any fixture — earlier than
        the plugin's autouse hass_storage fixture — ensuring the real objects
        are always in place when fixtures set up.
        """
        # Restore HA module attributes
        for mod, attr, real_val in _REAL_HA_ATTRS:
            setattr(mod, attr, real_val)
        # Restore kyber modules that stubs fully replaced in sys.modules
        for mod_name, real_mod in _STUB_REPLACED_KYBER_MODULES.items():
            sys.modules[mod_name] = real_mod
        # Restore kyber module attributes overwritten on the real objects
        for mod, attr, real_val in _REAL_KYBER_ATTRS:
            setattr(mod, attr, real_val)

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
