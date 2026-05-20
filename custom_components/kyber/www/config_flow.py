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
    CONF_NARRATOR_AI_TASK_ENTITY_ID,
    CONF_ENABLE_DEBUG_VIEWS,
    CONF_INITIAL_DEEP_LEARNING_RUNS,
    CONF_MAX_TOKENS,
    CONF_NARRATOR_ENABLED,
    CONF_NARRATOR_MAX_BATCH,
    CONF_RUN_INITIAL_ANALYZE,
    CONF_AREA_ASSIGNMENT_MODE,
    DEFAULT_ENABLE_DEBUG_VIEWS,
    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_NARRATOR_ENABLED,
    DEFAULT_NARRATOR_MAX_BATCH,
    DEFAULT_RUN_INITIAL_ANALYZE,
    DEFAULT_AREA_ASSIGNMENT_MODE,
    AREA_ASSIGNMENT_OFF,
    AREA_ASSIGNMENT_SUGGEST,
    AREA_ASSIGNMENT_AUTO,
    DOMAIN,
    MODEL_CONTEXT_SIZES,
)


def _entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True if the entity_id exists in the entity registry or state machine."""
    registry = er.async_get(hass)
    return (
        registry.async_get(entity_id) is not None
        or hass.states.get(entity_id) is not None
    )


def _infer_max_tokens(hass: HomeAssistant, entity_id: str) -> int:
    """Try to infer max context size from entity state attributes or model name.

    Checks (in order):
      1. Direct attributes: max_tokens, context_window, context_length, num_ctx
      2. Model name attribute matched against MODEL_CONTEXT_SIZES table
      3. Falls back to DEFAULT_MAX_TOKENS
    """
    state = hass.states.get(entity_id)
    if not state:
        return DEFAULT_MAX_TOKENS

    attrs = state.attributes

    # 1. Direct numeric attribute
    for key in ("max_tokens", "context_window", "context_length", "num_ctx"):
        if key in attrs:
            try:
                return int(attrs[key])
            except (TypeError, ValueError):
                pass

    # 2. Match model name against known table
    model_name = ""
    for key in ("model_id", "model", "model_name", "llm_model", "agent_id"):
        if key in attrs:
            model_name = str(attrs[key]).lower()
            break

    if not model_name:
        # Fall back: try to extract from entity_id itself (e.g. ai_task.ollama_llama3)
        model_name = entity_id.lower()

    for pattern, size in MODEL_CONTEXT_SIZES.items():
        if pattern in model_name:
            return size

    return DEFAULT_MAX_TOKENS


def _build_entity_schema(hass: HomeAssistant, default_entity: str = "") -> vol.Schema:
    """Step-1 schema: only the entity selector."""
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
        }
    )


def _build_options_schema(
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    enable_debug: bool = DEFAULT_ENABLE_DEBUG_VIEWS,
    run_initial_analyze: bool = DEFAULT_RUN_INITIAL_ANALYZE,
    deep_learning_runs: int = DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
    narrator_enabled: bool = DEFAULT_NARRATOR_ENABLED,
    narrator_max_batch: int = DEFAULT_NARRATOR_MAX_BATCH,
    narrator_ai_entity: str = "",
    area_assignment_mode: str = DEFAULT_AREA_ASSIGNMENT_MODE,
) -> vol.Schema:
    """Step-2 / options schema: all settings except entity."""
    return vol.Schema(
        {
            vol.Optional(CONF_MAX_TOKENS, default=max_tokens): vol.All(
                int, vol.Range(min=256, max=2_000_000)
            ),
            vol.Optional(CONF_ENABLE_DEBUG_VIEWS, default=enable_debug): bool,
            vol.Optional(CONF_RUN_INITIAL_ANALYZE, default=run_initial_analyze): bool,
            vol.Optional(
                CONF_INITIAL_DEEP_LEARNING_RUNS,
                default=deep_learning_runs,
            ): vol.All(int, vol.Range(min=1, max=10)),
            vol.Optional(CONF_NARRATOR_ENABLED, default=narrator_enabled): bool,
            vol.Optional(
                CONF_NARRATOR_MAX_BATCH,
                default=narrator_max_batch,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=50, step=1, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
            vol.Optional(
                CONF_NARRATOR_AI_TASK_ENTITY_ID,
                default=narrator_ai_entity,
            ): vol.Any("", selector.EntitySelector(
                selector.EntitySelectorConfig(domain="ai_task")
            )),
            vol.Optional(
                CONF_AREA_ASSIGNMENT_MODE,
                default=area_assignment_mode,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=AREA_ASSIGNMENT_OFF, label="Off"),
                        selector.SelectOptionDict(value=AREA_ASSIGNMENT_SUGGEST, label="Suggest (recommended)"),
                        selector.SelectOptionDict(value=AREA_ASSIGNMENT_AUTO, label="Automatic"),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }
    )


class KyberConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kyber."""

    VERSION = 1

    def __init__(self) -> None:
        self._entity_id: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 — pick the AI task entity."""
        errors: dict[str, str] = {}

        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            entity_id = user_input[CONF_AI_TASK_ENTITY_ID].strip()
            if not _entity_exists(self.hass, entity_id):
                errors[CONF_AI_TASK_ENTITY_ID] = "entity_not_found"
            else:
                self._entity_id = entity_id
                return await self.async_step_model_config()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_entity_schema(self.hass),
            errors=errors,
        )

    async def async_step_model_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 — configure tokens and options, pre-filled from entity."""
        if user_input is not None:
            return self.async_create_entry(
                title="Kyber",
                data={
                    CONF_AI_TASK_ENTITY_ID: self._entity_id,
                    CONF_MAX_TOKENS: int(user_input.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
                    CONF_ENABLE_DEBUG_VIEWS: bool(
                        user_input.get(CONF_ENABLE_DEBUG_VIEWS, DEFAULT_ENABLE_DEBUG_VIEWS)
                    ),
                    CONF_RUN_INITIAL_ANALYZE: bool(
                        user_input.get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)
                    ),
                    CONF_INITIAL_DEEP_LEARNING_RUNS: int(
                        user_input.get(
                            CONF_INITIAL_DEEP_LEARNING_RUNS,
                            DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
                        )
                    ),
                    CONF_NARRATOR_MAX_BATCH: int(
                        user_input.get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH)
                    ),
                    CONF_NARRATOR_ENABLED: bool(
                        user_input.get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED)
                    ),
                    CONF_NARRATOR_AI_TASK_ENTITY_ID: str(
                        user_input.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")
                    ).strip(),
                },
            )

        suggested_tokens = _infer_max_tokens(self.hass, self._entity_id)

        return self.async_show_form(
            step_id="model_config",
            data_schema=_build_options_schema(max_tokens=suggested_tokens),
            description_placeholders={
                "entity_id": self._entity_id,
                "suggested_tokens": str(suggested_tokens),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow so users can edit settings post-install."""
        return KyberOptionsFlow()


class KyberOptionsFlow(OptionsFlow):
    """Options flow for Kyber — lets the user edit all settings after install."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self.config_entry.data
        opts = self.config_entry.options

        def _get(key: str, default: Any) -> Any:
            return opts.get(key, cfg.get(key, default))

        if user_input is not None:
            return self.async_create_entry(title="", data={
                CONF_MAX_TOKENS: int(user_input.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
                CONF_ENABLE_DEBUG_VIEWS: bool(user_input.get(CONF_ENABLE_DEBUG_VIEWS, False)),
                CONF_RUN_INITIAL_ANALYZE: bool(
                    user_input.get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)
                ),
                CONF_INITIAL_DEEP_LEARNING_RUNS: int(
                    user_input.get(CONF_INITIAL_DEEP_LEARNING_RUNS, DEFAULT_INITIAL_DEEP_LEARNING_RUNS)
                ),
                CONF_NARRATOR_MAX_BATCH: int(
                    user_input.get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH)
                ),
                CONF_NARRATOR_ENABLED: bool(
                    user_input.get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED)
                ),
                CONF_NARRATOR_AI_TASK_ENTITY_ID: str(
                    user_input.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")
                ).strip(),
                CONF_AREA_ASSIGNMENT_MODE: str(
                    user_input.get(CONF_AREA_ASSIGNMENT_MODE, DEFAULT_AREA_ASSIGNMENT_MODE)
                ),
            })

        entity_id = _get(CONF_AI_TASK_ENTITY_ID, "")
        current_tokens = _get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)

        # Always offer the inferred value when opening options — user can still override
        if entity_id:
            inferred = _infer_max_tokens(self.hass, entity_id)
            if inferred != DEFAULT_MAX_TOKENS:
                current_tokens = inferred

        schema = _build_options_schema(
            max_tokens=current_tokens,
            enable_debug=bool(_get(CONF_ENABLE_DEBUG_VIEWS, DEFAULT_ENABLE_DEBUG_VIEWS)),
            run_initial_analyze=bool(_get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)),
            deep_learning_runs=int(_get(CONF_INITIAL_DEEP_LEARNING_RUNS, DEFAULT_INITIAL_DEEP_LEARNING_RUNS)),
            narrator_enabled=bool(_get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED)),
            narrator_max_batch=int(_get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH)),
            narrator_ai_entity=str(_get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")),
        )

        return self.async_show_form(step_id="init", data_schema=schema)
