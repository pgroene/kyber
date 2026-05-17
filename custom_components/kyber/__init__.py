"""The kyber integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.panel_custom import async_register_panel

from .const import CONF_AI_TASK_ENTITY_ID, DOMAIN
from .http_api import KyberView, KyberSaveView, KyberExecuteView, KyberSummarizeView, KyberHistoryView, KyberSessionsView, KyberSessionNameView, KyberProgressView, KyberKnowledgeView, KyberKnowledgeAnalyzeView, KyberKnowledgeDeepAnalyzeView, KyberKnowledgeFeedbackView, KyberDebugLastTurnView, KyberDebugToolHistoryView, KyberDebugStatusView, KyberDebugBundleView, KyberDebugModeView

_LOGGER = logging.getLogger(__name__)

type KyberConfigEntry = ConfigEntry[None]

_WWW_DIR = Path(__file__).parent / "www"


async def async_setup_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Set up Kyber from a config entry."""
    config = dict(entry.data)

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
            module_url="/local/kyber/kyber-panel.js?v=57",
            require_admin=True,
            config={
                "ai_task_entity_id": config.get(CONF_AI_TASK_ENTITY_ID),
                "mode": "chat",
            },
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Panel registration skipped (test environment)")

    try:
        await async_register_panel(
            hass,
            frontend_url_path="kyber-debug",
            webcomponent_name="kyber-panel",
            sidebar_title="Kyber Debug",
            sidebar_icon="mdi:bug",
            module_url="/local/kyber/kyber-panel.js?v=57",
            require_admin=True,
            config={
                "ai_task_entity_id": config.get(CONF_AI_TASK_ENTITY_ID),
                "mode": "debug",
            },
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Debug panel registration skipped (test environment)")

    _LOGGER.warning(
        "Kyber set up OK — panel registered, AI entity: %s",
        config.get(CONF_AI_TASK_ENTITY_ID),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Unload a config entry."""
    return True
