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
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

# Section keys — used as dict keys in user_input when form is submitted
_SECTION_MODEL = "model_config"
_SECTION_AGENTS = "agents"
_SECTION_AREA = "area_assignment"
_SECTION_DEVELOPER = "developer"

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_NARRATOR_AI_TASK_ENTITY_ID,
    CONF_ENABLE_DEBUG_VIEWS,
    CONF_INITIAL_DEEP_LEARNING_RUNS,
    CONF_MAX_TOKENS,
    CONF_NARRATOR_ENABLED,
    CONF_NARRATOR_MAX_BATCH,
    CONF_NARRATOR_MAX_TOKENS,
    CONF_NARRATOR_INTERVAL_DAYS,
    CONF_DEEP_LEARNING_INTERVAL_DAYS,
    CONF_DEEP_LEARNING_MAX_BATCH,
    CONF_RUN_INITIAL_ANALYZE,
    CONF_AREA_ASSIGNMENT_MODE,
    CONF_LABEL_ASSIGNMENT_MODE,
    DEFAULT_ENABLE_DEBUG_VIEWS,
    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_NARRATOR_ENABLED,
    DEFAULT_NARRATOR_MAX_BATCH,
    DEFAULT_NARRATOR_MAX_TOKENS,
    DEFAULT_NARRATOR_INTERVAL_DAYS,
    DEFAULT_DEEP_LEARNING_INTERVAL_DAYS,
    DEFAULT_DEEP_LEARNING_MAX_BATCH,
    DEFAULT_RUN_INITIAL_ANALYZE,
    DEFAULT_AREA_ASSIGNMENT_MODE,
    DEFAULT_LABEL_ASSIGNMENT_MODE,
    AREA_ASSIGNMENT_OFF,
    AREA_ASSIGNMENT_SUGGEST,
    AREA_ASSIGNMENT_AUTO,
    LABEL_ASSIGNMENT_OFF,
    LABEL_ASSIGNMENT_SUGGEST,
    LABEL_ASSIGNMENT_AUTO,
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


def _build_setup_schema(
    hass: HomeAssistant,
    default_entity: str = "",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    enable_debug: bool = DEFAULT_ENABLE_DEBUG_VIEWS,
    run_initial_analyze: bool = DEFAULT_RUN_INITIAL_ANALYZE,
    deep_learning_interval_days: int = DEFAULT_DEEP_LEARNING_INTERVAL_DAYS,
    deep_learning_max_batch: int = DEFAULT_DEEP_LEARNING_MAX_BATCH,
    narrator_enabled: bool = DEFAULT_NARRATOR_ENABLED,
    narrator_max_batch: int = DEFAULT_NARRATOR_MAX_BATCH,
    narrator_interval_days: int = DEFAULT_NARRATOR_INTERVAL_DAYS,
    narrator_ai_entity: str = "",
    area_assignment_mode: str = DEFAULT_AREA_ASSIGNMENT_MODE,
    label_assignment_mode: str = DEFAULT_LABEL_ASSIGNMENT_MODE,
) -> vol.Schema:
    """Single-step setup schema: entity selector + all settings."""
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
            **_build_options_schema(
                max_tokens=max_tokens,
                enable_debug=enable_debug,
                run_initial_analyze=run_initial_analyze,
                deep_learning_interval_days=deep_learning_interval_days,
                deep_learning_max_batch=deep_learning_max_batch,
                narrator_enabled=narrator_enabled,
                narrator_max_batch=narrator_max_batch,
                narrator_interval_days=narrator_interval_days,
                narrator_ai_entity=narrator_ai_entity,
                area_assignment_mode=area_assignment_mode,
                label_assignment_mode=label_assignment_mode,
            ).schema,
        }
    )


def _build_options_schema(
    *,
    ai_entity: str = "",
    include_entity: bool = False,
    collapsed: bool = False,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    chat_max_limit: int = 2_000_000,
    enable_debug: bool = DEFAULT_ENABLE_DEBUG_VIEWS,
    run_initial_analyze: bool = DEFAULT_RUN_INITIAL_ANALYZE,
    deep_learning_interval_days: int = DEFAULT_DEEP_LEARNING_INTERVAL_DAYS,
    deep_learning_max_batch: int = DEFAULT_DEEP_LEARNING_MAX_BATCH,
    narrator_enabled: bool = DEFAULT_NARRATOR_ENABLED,
    narrator_max_batch: int = DEFAULT_NARRATOR_MAX_BATCH,
    narrator_interval_days: int = DEFAULT_NARRATOR_INTERVAL_DAYS,
    narrator_ai_entity: str = "",
    narrator_max_tokens: int = DEFAULT_NARRATOR_MAX_TOKENS,
    narrator_max_limit: int = 2_000_000,
    area_assignment_mode: str = DEFAULT_AREA_ASSIGNMENT_MODE,
    label_assignment_mode: str = DEFAULT_LABEL_ASSIGNMENT_MODE,
) -> vol.Schema:
    """Options schema grouped into sections."""
    model_fields: dict = {}
    if include_entity:
        model_fields[vol.Optional(CONF_AI_TASK_ENTITY_ID, default=ai_entity)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="ai_task")
        )
    model_fields[vol.Optional(CONF_MAX_TOKENS, default=max_tokens)] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=2_000, max=chat_max_limit, step=1, mode=selector.NumberSelectorMode.BOX
        )
    )
    model_fields[vol.Optional(CONF_NARRATOR_AI_TASK_ENTITY_ID)] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="ai_task")
    )
    model_fields[vol.Optional(CONF_NARRATOR_MAX_TOKENS, default=narrator_max_tokens)] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=2_000, max=narrator_max_limit, step=1, mode=selector.NumberSelectorMode.BOX
        )
    )

    return vol.Schema(
        {
            vol.Optional(_SECTION_MODEL): section(
                vol.Schema(model_fields),
                {"collapsed": collapsed},
            ),
            vol.Optional(_SECTION_AGENTS): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_NARRATOR_ENABLED, default=narrator_enabled): selector.BooleanSelector(),
                        vol.Optional(
                            CONF_NARRATOR_INTERVAL_DAYS,
                            default=narrator_interval_days,
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1, max=30, step=1, mode=selector.NumberSelectorMode.SLIDER
                            )
                        ),
                        vol.Optional(
                            CONF_NARRATOR_MAX_BATCH,
                            default=narrator_max_batch,
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1, max=50, step=1, mode=selector.NumberSelectorMode.SLIDER
                            )
                        ),
                        vol.Optional(CONF_RUN_INITIAL_ANALYZE, default=run_initial_analyze): selector.BooleanSelector(),
                        vol.Optional(
                            CONF_DEEP_LEARNING_INTERVAL_DAYS,
                            default=deep_learning_interval_days,
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1, max=90, step=1, mode=selector.NumberSelectorMode.SLIDER
                            )
                        ),
                        vol.Optional(
                            CONF_DEEP_LEARNING_MAX_BATCH,
                            default=deep_learning_max_batch,
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1, max=50, step=1, mode=selector.NumberSelectorMode.SLIDER
                            )
                        ),
                    }
                ),
                {"collapsed": collapsed},
            ),
            vol.Optional(_SECTION_AREA): section(
                vol.Schema(
                    {
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
                        vol.Optional(
                            CONF_LABEL_ASSIGNMENT_MODE,
                            default=label_assignment_mode,
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(value=LABEL_ASSIGNMENT_OFF, label="Off"),
                                    selector.SelectOptionDict(value=LABEL_ASSIGNMENT_SUGGEST, label="Suggest (recommended)"),
                                    selector.SelectOptionDict(value=LABEL_ASSIGNMENT_AUTO, label="Automatic"),
                                ],
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        ),
                    }
                ),
                {"collapsed": collapsed},
            ),
            vol.Optional(_SECTION_DEVELOPER): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_ENABLE_DEBUG_VIEWS, default=enable_debug): selector.BooleanSelector(),
                    }
                ),
                {"collapsed": True},
            ),
        },
        extra=vol.ALLOW_EXTRA,
    )


class KyberConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kyber."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-step setup — pick AI entity and configure all settings."""
        errors: dict[str, str] = {}

        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            entity_id = user_input[CONF_AI_TASK_ENTITY_ID].strip()
            if not _entity_exists(self.hass, entity_id):
                errors[CONF_AI_TASK_ENTITY_ID] = "entity_not_found"
            else:
                model = user_input.get(_SECTION_MODEL, {})
                agents = user_input.get(_SECTION_AGENTS, {})
                area = user_input.get(_SECTION_AREA, {})
                developer = user_input.get(_SECTION_DEVELOPER, {})
                return self.async_create_entry(
                    title="Kyber",
                    data={
                        CONF_AI_TASK_ENTITY_ID: entity_id,
                        CONF_MAX_TOKENS: int(model.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
                        CONF_NARRATOR_AI_TASK_ENTITY_ID: str(model.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")).strip(),
                        CONF_NARRATOR_MAX_TOKENS: int(model.get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS)),
                        CONF_RUN_INITIAL_ANALYZE: bool(agents.get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)),
                        CONF_DEEP_LEARNING_INTERVAL_DAYS: int(agents.get(CONF_DEEP_LEARNING_INTERVAL_DAYS, DEFAULT_DEEP_LEARNING_INTERVAL_DAYS)),
                        CONF_DEEP_LEARNING_MAX_BATCH: int(agents.get(CONF_DEEP_LEARNING_MAX_BATCH, DEFAULT_DEEP_LEARNING_MAX_BATCH)),
                        CONF_NARRATOR_ENABLED: bool(agents.get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED)),
                        CONF_NARRATOR_MAX_BATCH: int(agents.get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH)),
                        CONF_NARRATOR_INTERVAL_DAYS: int(agents.get(CONF_NARRATOR_INTERVAL_DAYS, DEFAULT_NARRATOR_INTERVAL_DAYS)),
                        CONF_AREA_ASSIGNMENT_MODE: str(area.get(CONF_AREA_ASSIGNMENT_MODE, DEFAULT_AREA_ASSIGNMENT_MODE)),
                        CONF_LABEL_ASSIGNMENT_MODE: str(area.get(CONF_LABEL_ASSIGNMENT_MODE, DEFAULT_LABEL_ASSIGNMENT_MODE)),
                        CONF_ENABLE_DEBUG_VIEWS: bool(developer.get(CONF_ENABLE_DEBUG_VIEWS, DEFAULT_ENABLE_DEBUG_VIEWS)),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_setup_schema(self.hass),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow so users can edit settings post-install."""
        return KyberOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow the user to change the AI task entity after initial setup."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            entity_id = user_input[CONF_AI_TASK_ENTITY_ID].strip()
            if not _entity_exists(self.hass, entity_id):
                errors[CONF_AI_TASK_ENTITY_ID] = "entity_not_found"
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={CONF_AI_TASK_ENTITY_ID: entity_id},
                )

        current_entity = reconfigure_entry.data.get(CONF_AI_TASK_ENTITY_ID, "")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_setup_schema(self.hass, default_entity=current_entity),
            errors=errors,
        )


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
            model = user_input.get(_SECTION_MODEL, {})
            agents = user_input.get(_SECTION_AGENTS, {})
            area = user_input.get(_SECTION_AREA, {})
            developer = user_input.get(_SECTION_DEVELOPER, {})

            new_entity_id = str(model.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
            current_entity_id = str(self.config_entry.data.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
            # Only validate the entity when it has changed — it was already validated at setup
            if new_entity_id and new_entity_id != current_entity_id and not _entity_exists(self.hass, new_entity_id):
                return self.async_show_form(
                    step_id="init",
                    data_schema=_build_options_schema(
                        ai_entity=new_entity_id,
                        include_entity=True,
                        max_tokens=int(model.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
                        narrator_ai_entity=str(model.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")),
                        narrator_max_tokens=int(model.get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS)),
                    ),
                    errors={CONF_AI_TASK_ENTITY_ID: "entity_not_found"},
                )

            data: dict[str, Any] = {
                CONF_MAX_TOKENS: int(model.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
                CONF_NARRATOR_AI_TASK_ENTITY_ID: str(model.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")).strip(),
                CONF_NARRATOR_MAX_TOKENS: int(model.get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS)),
                CONF_RUN_INITIAL_ANALYZE: bool(agents.get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)),
                CONF_DEEP_LEARNING_INTERVAL_DAYS: int(agents.get(CONF_DEEP_LEARNING_INTERVAL_DAYS, DEFAULT_DEEP_LEARNING_INTERVAL_DAYS)),
                CONF_DEEP_LEARNING_MAX_BATCH: int(agents.get(CONF_DEEP_LEARNING_MAX_BATCH, DEFAULT_DEEP_LEARNING_MAX_BATCH)),
                CONF_NARRATOR_ENABLED: bool(agents.get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED)),
                CONF_NARRATOR_MAX_BATCH: int(agents.get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH)),
                CONF_NARRATOR_INTERVAL_DAYS: int(agents.get(CONF_NARRATOR_INTERVAL_DAYS, DEFAULT_NARRATOR_INTERVAL_DAYS)),
                CONF_AREA_ASSIGNMENT_MODE: str(area.get(CONF_AREA_ASSIGNMENT_MODE, DEFAULT_AREA_ASSIGNMENT_MODE)),
                CONF_LABEL_ASSIGNMENT_MODE: str(area.get(CONF_LABEL_ASSIGNMENT_MODE, DEFAULT_LABEL_ASSIGNMENT_MODE)),
                CONF_ENABLE_DEBUG_VIEWS: bool(developer.get(CONF_ENABLE_DEBUG_VIEWS, False)),
            }
            if new_entity_id:
                data[CONF_AI_TASK_ENTITY_ID] = new_entity_id
            return self.async_create_entry(title="", data=data)

        entity_id = _get(CONF_AI_TASK_ENTITY_ID, "")
        current_tokens = _get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)

        # Always offer the inferred value when opening options — user can still override
        if entity_id:
            inferred = _infer_max_tokens(self.hass, entity_id)
            if inferred != DEFAULT_MAX_TOKENS:
                current_tokens = inferred

        narrator_entity = str(_get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")).strip() or entity_id

        chat_max_limit = _infer_max_tokens(self.hass, entity_id) if entity_id else 2_000_000
        narrator_max_limit = _infer_max_tokens(self.hass, narrator_entity) if narrator_entity else 2_000_000

        schema = _build_options_schema(
            ai_entity=entity_id,
            include_entity=True,
            collapsed=True,
            max_tokens=current_tokens,
            chat_max_limit=chat_max_limit,
            enable_debug=bool(_get(CONF_ENABLE_DEBUG_VIEWS, DEFAULT_ENABLE_DEBUG_VIEWS)),
            run_initial_analyze=bool(_get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)),
            deep_learning_interval_days=int(_get(CONF_DEEP_LEARNING_INTERVAL_DAYS, DEFAULT_DEEP_LEARNING_INTERVAL_DAYS)),
            deep_learning_max_batch=int(_get(CONF_DEEP_LEARNING_MAX_BATCH, DEFAULT_DEEP_LEARNING_MAX_BATCH)),
            narrator_enabled=bool(_get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED)),
            narrator_max_batch=int(_get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH)),
            narrator_interval_days=int(_get(CONF_NARRATOR_INTERVAL_DAYS, DEFAULT_NARRATOR_INTERVAL_DAYS)),
            narrator_ai_entity=str(_get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")),
            narrator_max_tokens=int(_get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS)),
            narrator_max_limit=narrator_max_limit,
            area_assignment_mode=str(_get(CONF_AREA_ASSIGNMENT_MODE, DEFAULT_AREA_ASSIGNMENT_MODE)),
            label_assignment_mode=str(_get(CONF_LABEL_ASSIGNMENT_MODE, DEFAULT_LABEL_ASSIGNMENT_MODE)),
        )

        from .model_stats import format_stats as _fmt_stats, format_run_stats as _fmt_run_stats
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "chat_stats": _fmt_stats(self.hass, entity_id) if entity_id else "No model configured",
                "ops_stats": _fmt_stats(self.hass, narrator_entity) if narrator_entity else "No model configured",
                "narrator_run_stats": _fmt_run_stats(self.hass, "narrator"),
                "deep_learning_run_stats": _fmt_run_stats(self.hass, "deep_learning"),
            },
        )
