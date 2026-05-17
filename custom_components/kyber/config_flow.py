"""Config flow for the kyber integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_ENABLE_DEBUG_VIEWS,
    CONF_MAX_TOKENS,
    CONF_USER_NAME,
    DEFAULT_ENABLE_DEBUG_VIEWS,
    DEFAULT_MAX_TOKENS,
    DOMAIN,
)


def _entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True if the entity_id exists in the entity registry or state machine."""
    registry = er.async_get(hass)
    return (
        registry.async_get(entity_id) is not None
        or hass.states.get(entity_id) is not None
    )


def _build_schema(hass: HomeAssistant, default_entity: str = "") -> vol.Schema:
    """Build the config form schema with an entity selector for ai_task entities."""
    if not default_entity:
        registry = er.async_get(hass)
        ai_task_entities = [
            entry.entity_id
            for entry in registry.entities.values()
            if entry.entity_id.startswith("ai_task.")
        ]
        default_entity = ai_task_entities[0] if ai_task_entities else ""

    return vol.Schema(
        {
            vol.Required(CONF_AI_TASK_ENTITY_ID, default=default_entity): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="ai_task")
            ),
            vol.Optional(CONF_USER_NAME, default=""): str,
            vol.Optional(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): vol.All(
                int, vol.Range(min=256, max=2_000_000)
            ),
            vol.Optional(
                CONF_ENABLE_DEBUG_VIEWS, default=DEFAULT_ENABLE_DEBUG_VIEWS
            ): bool,
        }
    )


class KyberConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kyber."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step shown to the user."""
        errors: dict[str, str] = {}

        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            entity_id = user_input[CONF_AI_TASK_ENTITY_ID].strip()
            if not _entity_exists(self.hass, entity_id):
                errors[CONF_AI_TASK_ENTITY_ID] = "entity_not_found"
            else:
                return self.async_create_entry(
                    title="Kyber",
                    data={
                        CONF_AI_TASK_ENTITY_ID: entity_id,
                        CONF_USER_NAME: user_input.get(CONF_USER_NAME, "").strip(),
                        CONF_MAX_TOKENS: user_input.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                        CONF_ENABLE_DEBUG_VIEWS: bool(
                            user_input.get(CONF_ENABLE_DEBUG_VIEWS, DEFAULT_ENABLE_DEBUG_VIEWS)
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(self.hass),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow so users can edit settings post-install."""
        return KyberOptionsFlow(config_entry)


class KyberOptionsFlow(OptionsFlow):
    """Options flow for Kyber — lets the user toggle settings after install."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={
                CONF_USER_NAME: user_input.get(CONF_USER_NAME, "").strip(),
                CONF_ENABLE_DEBUG_VIEWS: bool(user_input.get(CONF_ENABLE_DEBUG_VIEWS, False)),
            })

        current_debug = self._config_entry.options.get(
            CONF_ENABLE_DEBUG_VIEWS,
            self._config_entry.data.get(
                CONF_ENABLE_DEBUG_VIEWS, DEFAULT_ENABLE_DEBUG_VIEWS
            ),
        )
        current_user_name = self._config_entry.options.get(
            CONF_USER_NAME,
            self._config_entry.data.get(CONF_USER_NAME, ""),
        )

        schema = vol.Schema({
            vol.Optional(CONF_USER_NAME, default=current_user_name): str,
            vol.Optional(
                CONF_ENABLE_DEBUG_VIEWS, default=current_debug
            ): bool,
        })

        return self.async_show_form(step_id="init", data_schema=schema)
