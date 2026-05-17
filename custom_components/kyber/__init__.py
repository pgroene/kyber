"""The kyber integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.panel_custom import async_register_panel

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_ENABLE_DEBUG_VIEWS,
    CONF_INITIAL_DEEP_LEARNING_RUNS,
    CONF_INITIAL_LEARNING_DONE,
    CONF_RUN_INITIAL_ANALYZE,
    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
    DEFAULT_RUN_INITIAL_ANALYZE,
    DOMAIN,
)
from .analyzer import analyze_automations as _analyze_automations
from . import deep_analyzer as _deep
from .http_api import KyberView, KyberSaveView, KyberExecuteView, KyberSummarizeView, KyberHistoryView, KyberSessionsView, KyberSessionNameView, KyberProgressView, KyberKnowledgeView, KyberKnowledgeAnalyzeView, KyberKnowledgeDeepAnalyzeView, KyberKnowledgeFeedbackView, KyberDebugLastTurnView, KyberDebugToolHistoryView, KyberDebugStatusView, KyberDebugBundleView, KyberBugReportView, KyberDebugModeView

_LOGGER = logging.getLogger(__name__)

type KyberConfigEntry = ConfigEntry[None]

_WWW_DIR = Path(__file__).parent / "www"

_DEBUG_MODE_KEY = "kyber_debug_mode"


async def _async_run_initial_learning(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Run first-install analysis helpers once, in the background."""
    data = dict(entry.data)
    if CONF_INITIAL_LEARNING_DONE in data:
        _LOGGER.debug("Kyber initial learning already done — skipping")
        return

    ai_entity_id = str(data.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    run_initial_analyze = bool(
        data.get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)
    )
    deep_runs = max(
        1,
        min(
            10,
            int(
                data.get(
                    CONF_INITIAL_DEEP_LEARNING_RUNS,
                    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
                )
            ),
        ),
    )

    _LOGGER.warning(
        "Kyber initial learning starting — analyze=%s, deep_runs=%d, ai_entity=%s",
        run_initial_analyze,
        deep_runs,
        ai_entity_id,
    )

    if run_initial_analyze:
        _LOGGER.warning("Kyber initial learning: running automation analysis…")
        try:
            await hass.async_add_executor_job(_analyze_automations, hass)
            _LOGGER.warning("Kyber initial learning: automation analysis complete")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber initial analyze run failed: %s", err)

    for i in range(deep_runs):
        _LOGGER.warning(
            "Kyber initial learning: deep-learning run %d/%d…", i + 1, deep_runs
        )
        try:
            await _deep.analyze_pending(hass, ai_entity_id=ai_entity_id, limit=5)
            _LOGGER.warning(
                "Kyber initial learning: deep-learning run %d/%d complete",
                i + 1,
                deep_runs,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Kyber initial deep learning run %d/%d failed: %s", i + 1, deep_runs, err
            )

    data[CONF_INITIAL_LEARNING_DONE] = True
    hass.config_entries.async_update_entry(entry, data=data)
    _LOGGER.warning("Kyber initial learning: all runs complete ✓")


def _resolve_debug_enabled(entry: ConfigEntry) -> bool:
    """Resolve effective debug-views setting for an entry.

    Precedence: entry.options → entry.data → fallback True.

    The fallback True preserves the experience for entries that existed
    BEFORE this option was introduced (they had no key anywhere). New
    entries get the key written to entry.data via the config flow, so
    they default to False as the user requested.
    """
    if CONF_ENABLE_DEBUG_VIEWS in entry.options:
        return bool(entry.options[CONF_ENABLE_DEBUG_VIEWS])
    if CONF_ENABLE_DEBUG_VIEWS in entry.data:
        return bool(entry.data[CONF_ENABLE_DEBUG_VIEWS])
    # Pre-existing entry from before the option existed — preserve previous behavior
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry whenever options change so panel registration follows."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Set up Kyber from a config entry."""
    config = dict(entry.data)

    debug_enabled = _resolve_debug_enabled(entry)
    hass.data[_DEBUG_MODE_KEY] = debug_enabled

    hass.http.register_view(KyberView(config))
    hass.http.register_view(KyberProgressView())
    hass.http.register_view(KyberHistoryView())
    hass.http.register_view(KyberSessionsView())
    hass.http.register_view(KyberSessionNameView(config))
    hass.http.register_view(KyberSaveView())
    hass.http.register_view(KyberExecuteView())
    hass.http.register_view(KyberSummarizeView(config))
    hass.http.register_view(KyberKnowledgeView())
    hass.http.register_view(KyberKnowledgeAnalyzeView())
    hass.http.register_view(KyberKnowledgeDeepAnalyzeView(config))
    hass.http.register_view(KyberKnowledgeFeedbackView())
    hass.http.register_view(KyberDebugLastTurnView())
    hass.http.register_view(KyberDebugToolHistoryView())
    hass.http.register_view(KyberDebugStatusView())
    hass.http.register_view(KyberDebugBundleView())
    hass.http.register_view(KyberBugReportView())
    hass.http.register_view(KyberDebugModeView())

    # Serve frontend files from the component's www/ directory.
    # This makes HACS installs work without manual file copying.
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/local/kyber", str(_WWW_DIR), cache_headers=True)]
    )

    try:
        await async_register_panel(
            hass,
            frontend_url_path="kyber",
            webcomponent_name="kyber-panel",
            sidebar_title="Kyber",
            sidebar_icon="mdi:robot",
            module_url="/local/kyber/kyber-panel.js?v=75",
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Panel registration skipped (test environment)")

    # Only register the separate "Kyber Debug" sidebar entry when debug views
    # are enabled — otherwise the panel would appear with nothing useful.
    if debug_enabled:
        try:
            await async_register_panel(
                hass,
                frontend_url_path="kyber-debug",
                webcomponent_name="kyber-panel",
                sidebar_title="Kyber Debug",
                sidebar_icon="mdi:bug",
                module_url="/local/kyber/kyber-panel.js?v=75",
                config={"mode": "debug"},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Debug panel registration skipped (test environment)")

    # Always schedule the initial learning task; the function itself guards
    # against re-running via CONF_INITIAL_LEARNING_DONE.
    hass.async_create_task(_async_run_initial_learning(hass, entry))

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    _LOGGER.warning(
        "Kyber set up OK — panel registered, AI entity: %s, debug_views=%s",
        config.get(CONF_AI_TASK_ENTITY_ID),
        debug_enabled,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Unload a config entry."""
    # Remove the debug panel if we registered one so reloads can re-evaluate.
    try:
        from homeassistant.components.frontend import async_remove_panel
        async_remove_panel(hass, "kyber-debug")
    except Exception:  # noqa: BLE001
        pass
    return True

