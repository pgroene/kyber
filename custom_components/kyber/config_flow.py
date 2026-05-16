"""Config flow for the kyber integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_MAX_TOKENS,
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


def _build_schema(hass: HomeAssistant) -> vol.Schema:
    """Build the config form schema with a sensible default entity."""
    registry = er.async_get(hass)
    ai_task_entities = [
        entry.entity_id
        for entry in registry.entities.values()
        if entry.entity_id.startswith("ai_task.")
    ]
    default_entity = ai_task_entities[0] if ai_task_entities else ""

    return vol.Schema(
        {
            vol.Required(CONF_AI_TASK_ENTITY_ID, default=default_entity): str,
            vol.Optional(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): vol.All(
                int, vol.Range(min=256, max=2_000_000)
            ),
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
                        CONF_MAX_TOKENS: user_input.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(self.hass),
            errors=errors,
        )
