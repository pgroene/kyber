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
_SECTION_CLOUD = "cloud_config"
_SECTION_AGENTS = "agents"
_SECTION_AREA = "area_assignment"
_SECTION_DEVELOPER = "developer"

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_NARRATOR_AI_TASK_ENTITY_ID,
    CONF_CLOUD_PROVIDER,
    CONF_CLOUD_USE_FOR_CHAT,
    CLOUD_PROVIDER_NONE,
    CLOUD_PROVIDER_AZURE,
    CLOUD_PROVIDER_OPENAI,
    CLOUD_PROVIDER_ANTHROPIC,
    DEFAULT_CLOUD_PROVIDER,
    DEFAULT_CLOUD_USE_FOR_CHAT,
    CONF_AZURE_ENDPOINT,
    CONF_AZURE_API_KEY,
    CONF_AZURE_DEPLOYMENT,
    CONF_AZURE_API_VERSION,
    DEFAULT_AZURE_API_VERSION,
    CONF_OPENAI_API_KEY,
    CONF_OPENAI_MODEL,
    CONF_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    CONF_ANTHROPIC_API_KEY,
    CONF_ANTHROPIC_MODEL,
    DEFAULT_ANTHROPIC_MODEL,
    CONF_ENABLE_DEBUG_VIEWS,
    CONF_ENABLE_MCP,
    CONF_ENABLE_MCP_IN_CHAT,
    CONF_MCP_ALLOW_STATE_CHANGES,
    CONF_MCP_CLIENT_SERVERS,
    CONF_INITIAL_DEEP_LEARNING_RUNS,
    CONF_MAX_DAILY_TOKENS,
    CONF_MAX_TOKENS,
    CONF_MAX_REQUESTS_PER_MINUTE,
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
    DEFAULT_ENABLE_MCP,
    DEFAULT_ENABLE_MCP_IN_CHAT,
    DEFAULT_MCP_ALLOW_STATE_CHANGES,
    DEFAULT_MCP_CLIENT_SERVERS,
    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
    DEFAULT_MAX_DAILY_TOKENS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_REQUESTS_PER_MINUTE,
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
    max_requests_per_minute: int = DEFAULT_MAX_REQUESTS_PER_MINUTE,
    max_daily_tokens: int = DEFAULT_MAX_DAILY_TOKENS,
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
                max_requests_per_minute=max_requests_per_minute,
                max_daily_tokens=max_daily_tokens,
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
    max_requests_per_minute: int = DEFAULT_MAX_REQUESTS_PER_MINUTE,
    max_daily_tokens: int = DEFAULT_MAX_DAILY_TOKENS,
    chat_max_limit: int = 2_000_000,
    enable_debug: bool = DEFAULT_ENABLE_DEBUG_VIEWS,
    enable_mcp: bool = DEFAULT_ENABLE_MCP,
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
    cloud_provider: str = DEFAULT_CLOUD_PROVIDER,
    cloud_use_for_chat: bool = DEFAULT_CLOUD_USE_FOR_CHAT,
    azure_endpoint: str = "",
    azure_api_key: str = "",
    azure_deployment: str = "",
    azure_api_version: str = DEFAULT_AZURE_API_VERSION,
    openai_api_key: str = "",
    openai_model: str = DEFAULT_OPENAI_MODEL,
    openai_base_url: str = "",
    anthropic_api_key: str = "",
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL,
    enable_mcp_in_chat: bool = DEFAULT_ENABLE_MCP_IN_CHAT,
    mcp_allow_state_changes: bool = DEFAULT_MCP_ALLOW_STATE_CHANGES,
    mcp_client_servers: str = DEFAULT_MCP_CLIENT_SERVERS,
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
    model_fields[vol.Optional(CONF_MAX_DAILY_TOKENS, default=max_daily_tokens)] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=100_000_000, step=1_000, mode=selector.NumberSelectorMode.BOX
        )
    )
    narrator_key = (
        vol.Optional(CONF_NARRATOR_AI_TASK_ENTITY_ID, default=narrator_ai_entity)
        if narrator_ai_entity
        else vol.Optional(CONF_NARRATOR_AI_TASK_ENTITY_ID)
    )
    model_fields[narrator_key] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="ai_task")
    )
    model_fields[vol.Optional(CONF_NARRATOR_MAX_TOKENS, default=narrator_max_tokens)] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=2_000, max=narrator_max_limit, step=1, mode=selector.NumberSelectorMode.BOX
        )
    )

    # Cloud provider fields — only show credentials for the selected provider
    _azure_endpoint_key = vol.Optional(CONF_AZURE_ENDPOINT, default=azure_endpoint) if azure_endpoint else vol.Optional(CONF_AZURE_ENDPOINT)
    _azure_key_key = vol.Optional(CONF_AZURE_API_KEY, default=azure_api_key) if azure_api_key else vol.Optional(CONF_AZURE_API_KEY)
    _azure_dep_key = vol.Optional(CONF_AZURE_DEPLOYMENT, default=azure_deployment) if azure_deployment else vol.Optional(CONF_AZURE_DEPLOYMENT)
    _openai_key_key = vol.Optional(CONF_OPENAI_API_KEY, default=openai_api_key) if openai_api_key else vol.Optional(CONF_OPENAI_API_KEY)
    _openai_base_key = vol.Optional(CONF_OPENAI_BASE_URL, default=openai_base_url) if openai_base_url else vol.Optional(CONF_OPENAI_BASE_URL)
    _anthropic_key_key = vol.Optional(CONF_ANTHROPIC_API_KEY, default=anthropic_api_key) if anthropic_api_key else vol.Optional(CONF_ANTHROPIC_API_KEY)

    cloud_fields: dict = {
        vol.Optional(CONF_CLOUD_PROVIDER, default=cloud_provider): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": CLOUD_PROVIDER_NONE, "label": "None (use local HA ai_task entity)"},
                    {"value": CLOUD_PROVIDER_AZURE, "label": "Azure AI Foundry"},
                    {"value": CLOUD_PROVIDER_OPENAI, "label": "OpenAI (or compatible: Groq, Mistral, OpenRouter…)"},
                    {"value": CLOUD_PROVIDER_ANTHROPIC, "label": "Anthropic (Claude)"},
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_CLOUD_USE_FOR_CHAT, default=cloud_use_for_chat): selector.BooleanSelector(),
        # All credential fields are always present so provider + credentials can be submitted in one step.
        # The UI hides irrelevant fields via cloud_provider selection; voluptuous accepts them as Optional.
        _azure_endpoint_key: selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
        _azure_key_key: selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        _azure_dep_key: selector.TextSelector(),
        vol.Optional(CONF_AZURE_API_VERSION, default=azure_api_version): selector.TextSelector(),
        _openai_key_key: selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        vol.Optional(CONF_OPENAI_MODEL, default=openai_model): selector.TextSelector(),
        _openai_base_key: selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
        _anthropic_key_key: selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        vol.Optional(CONF_ANTHROPIC_MODEL, default=anthropic_model): selector.TextSelector(),
    }

    return vol.Schema(
        {
            vol.Optional(_SECTION_MODEL): section(
                vol.Schema(model_fields),
                {"collapsed": collapsed},
            ),
            vol.Optional(_SECTION_CLOUD): section(
                vol.Schema(cloud_fields),
                {"collapsed": True},
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
                        vol.Optional(CONF_ENABLE_MCP, default=enable_mcp): selector.BooleanSelector(),
                        vol.Optional(CONF_ENABLE_MCP_IN_CHAT, default=enable_mcp_in_chat): selector.BooleanSelector(),
                        vol.Optional(CONF_MCP_ALLOW_STATE_CHANGES, default=mcp_allow_state_changes): selector.BooleanSelector(),
                        vol.Optional(CONF_MCP_CLIENT_SERVERS, default=mcp_client_servers): selector.TextSelector(
                            selector.TextSelectorConfig(multiline=True)
                        ),
                        vol.Optional(CONF_MAX_REQUESTS_PER_MINUTE, default=max_requests_per_minute): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0, max=600, step=1, mode=selector.NumberSelectorMode.BOX
                            )
                        ),
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
                        CONF_MAX_DAILY_TOKENS: int(model.get(CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS)),
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
                        CONF_MAX_REQUESTS_PER_MINUTE: int(developer.get(CONF_MAX_REQUESTS_PER_MINUTE, DEFAULT_MAX_REQUESTS_PER_MINUTE)),
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
            cloud = user_input.get(_SECTION_CLOUD, {})

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
                        max_requests_per_minute=int(developer.get(CONF_MAX_REQUESTS_PER_MINUTE, DEFAULT_MAX_REQUESTS_PER_MINUTE)),
                        max_daily_tokens=int(model.get(CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS)),
                        narrator_ai_entity=str(model.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")),
                        narrator_max_tokens=int(model.get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS)),
                    ),
                    errors={CONF_AI_TASK_ENTITY_ID: "entity_not_found"},
                )

            # If the cloud provider just changed to a non-None value and the user
            # hasn't provided credentials yet, re-render the form so the
            # provider-specific credential fields become visible.
            selected_provider = str(cloud.get(CONF_CLOUD_PROVIDER, DEFAULT_CLOUD_PROVIDER)).strip()
            stored_provider = _get(CONF_CLOUD_PROVIDER, DEFAULT_CLOUD_PROVIDER)
            _needs_creds = {
                CLOUD_PROVIDER_OPENAI:    not cloud.get(CONF_OPENAI_API_KEY, "").strip(),
                CLOUD_PROVIDER_AZURE:     not cloud.get(CONF_AZURE_API_KEY, "").strip(),
                CLOUD_PROVIDER_ANTHROPIC: not cloud.get(CONF_ANTHROPIC_API_KEY, "").strip(),
            }
            if (
                selected_provider != CLOUD_PROVIDER_NONE
                and selected_provider != stored_provider
                and _needs_creds.get(selected_provider, False)
            ):
                return self.async_show_form(
                    step_id="init",
                    data_schema=_build_options_schema(
                        ai_entity=_get(CONF_AI_TASK_ENTITY_ID, ""),
                        include_entity=True,
                        max_tokens=int(model.get(CONF_MAX_TOKENS, _get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))),
                        max_requests_per_minute=int(developer.get(CONF_MAX_REQUESTS_PER_MINUTE, _get(CONF_MAX_REQUESTS_PER_MINUTE, DEFAULT_MAX_REQUESTS_PER_MINUTE))),
                        max_daily_tokens=int(model.get(CONF_MAX_DAILY_TOKENS, _get(CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS))),
                        narrator_ai_entity=str(model.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, _get(CONF_NARRATOR_AI_TASK_ENTITY_ID, ""))),
                        narrator_max_tokens=int(model.get(CONF_NARRATOR_MAX_TOKENS, _get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS))),
                        cloud_provider=selected_provider,
                        cloud_use_for_chat=bool(cloud.get(CONF_CLOUD_USE_FOR_CHAT, _get(CONF_CLOUD_USE_FOR_CHAT, DEFAULT_CLOUD_USE_FOR_CHAT))),
                        collapsed=False,
                    ),
                    description_placeholders={"info": f"Enter credentials for {selected_provider}"},
                )

            data: dict[str, Any] = {
                CONF_MAX_TOKENS: int(model.get(CONF_MAX_TOKENS, _get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))),
                CONF_MAX_DAILY_TOKENS: int(model.get(CONF_MAX_DAILY_TOKENS, _get(CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS))),
                CONF_NARRATOR_AI_TASK_ENTITY_ID: str(model.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, _get(CONF_NARRATOR_AI_TASK_ENTITY_ID, ""))).strip(),
                CONF_NARRATOR_MAX_TOKENS: int(model.get(CONF_NARRATOR_MAX_TOKENS, _get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS))),
                CONF_RUN_INITIAL_ANALYZE: bool(agents.get(CONF_RUN_INITIAL_ANALYZE, _get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE))),
                CONF_DEEP_LEARNING_INTERVAL_DAYS: int(agents.get(CONF_DEEP_LEARNING_INTERVAL_DAYS, _get(CONF_DEEP_LEARNING_INTERVAL_DAYS, DEFAULT_DEEP_LEARNING_INTERVAL_DAYS))),
                CONF_DEEP_LEARNING_MAX_BATCH: int(agents.get(CONF_DEEP_LEARNING_MAX_BATCH, _get(CONF_DEEP_LEARNING_MAX_BATCH, DEFAULT_DEEP_LEARNING_MAX_BATCH))),
                CONF_NARRATOR_ENABLED: bool(agents.get(CONF_NARRATOR_ENABLED, _get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED))),
                CONF_NARRATOR_MAX_BATCH: int(agents.get(CONF_NARRATOR_MAX_BATCH, _get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH))),
                CONF_NARRATOR_INTERVAL_DAYS: int(agents.get(CONF_NARRATOR_INTERVAL_DAYS, _get(CONF_NARRATOR_INTERVAL_DAYS, DEFAULT_NARRATOR_INTERVAL_DAYS))),
                CONF_AREA_ASSIGNMENT_MODE: str(area.get(CONF_AREA_ASSIGNMENT_MODE, _get(CONF_AREA_ASSIGNMENT_MODE, DEFAULT_AREA_ASSIGNMENT_MODE))),
                CONF_LABEL_ASSIGNMENT_MODE: str(area.get(CONF_LABEL_ASSIGNMENT_MODE, _get(CONF_LABEL_ASSIGNMENT_MODE, DEFAULT_LABEL_ASSIGNMENT_MODE))),
                CONF_ENABLE_DEBUG_VIEWS: bool(developer.get(CONF_ENABLE_DEBUG_VIEWS, _get(CONF_ENABLE_DEBUG_VIEWS, False))),
                CONF_ENABLE_MCP: bool(developer.get(CONF_ENABLE_MCP, _get(CONF_ENABLE_MCP, DEFAULT_ENABLE_MCP))),
                CONF_ENABLE_MCP_IN_CHAT: bool(developer.get(CONF_ENABLE_MCP_IN_CHAT, _get(CONF_ENABLE_MCP_IN_CHAT, DEFAULT_ENABLE_MCP_IN_CHAT))),
                CONF_MCP_CLIENT_SERVERS: str(developer.get(CONF_MCP_CLIENT_SERVERS, _get(CONF_MCP_CLIENT_SERVERS, DEFAULT_MCP_CLIENT_SERVERS))),
                CONF_MAX_REQUESTS_PER_MINUTE: int(developer.get(CONF_MAX_REQUESTS_PER_MINUTE, _get(CONF_MAX_REQUESTS_PER_MINUTE, DEFAULT_MAX_REQUESTS_PER_MINUTE))),
                CONF_CLOUD_PROVIDER: str(cloud.get(CONF_CLOUD_PROVIDER, _get(CONF_CLOUD_PROVIDER, DEFAULT_CLOUD_PROVIDER))).strip(),
                CONF_CLOUD_USE_FOR_CHAT: bool(cloud.get(CONF_CLOUD_USE_FOR_CHAT, _get(CONF_CLOUD_USE_FOR_CHAT, DEFAULT_CLOUD_USE_FOR_CHAT))),
                CONF_AZURE_ENDPOINT: str(cloud.get(CONF_AZURE_ENDPOINT, _get(CONF_AZURE_ENDPOINT, ""))).strip(),
                CONF_AZURE_API_KEY: str(cloud.get(CONF_AZURE_API_KEY, _get(CONF_AZURE_API_KEY, ""))).strip(),
                CONF_AZURE_DEPLOYMENT: str(cloud.get(CONF_AZURE_DEPLOYMENT, _get(CONF_AZURE_DEPLOYMENT, ""))).strip(),
                CONF_AZURE_API_VERSION: str(cloud.get(CONF_AZURE_API_VERSION, _get(CONF_AZURE_API_VERSION, DEFAULT_AZURE_API_VERSION))).strip(),
                CONF_OPENAI_API_KEY: str(cloud.get(CONF_OPENAI_API_KEY, _get(CONF_OPENAI_API_KEY, ""))).strip(),
                CONF_OPENAI_MODEL: str(cloud.get(CONF_OPENAI_MODEL, _get(CONF_OPENAI_MODEL, DEFAULT_OPENAI_MODEL))).strip(),
                CONF_OPENAI_BASE_URL: str(cloud.get(CONF_OPENAI_BASE_URL, _get(CONF_OPENAI_BASE_URL, ""))).strip(),
                CONF_ANTHROPIC_API_KEY: str(cloud.get(CONF_ANTHROPIC_API_KEY, _get(CONF_ANTHROPIC_API_KEY, ""))).strip(),
                CONF_ANTHROPIC_MODEL: str(cloud.get(CONF_ANTHROPIC_MODEL, _get(CONF_ANTHROPIC_MODEL, DEFAULT_ANTHROPIC_MODEL))).strip(),
            }
            if new_entity_id:
                data[CONF_AI_TASK_ENTITY_ID] = new_entity_id
            return self.async_create_entry(title="", data=data)

        entity_id = _get(CONF_AI_TASK_ENTITY_ID, "")
        current_tokens = _get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        current_daily_tokens = _get(CONF_MAX_DAILY_TOKENS, DEFAULT_MAX_DAILY_TOKENS)

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
            max_requests_per_minute=int(_get(CONF_MAX_REQUESTS_PER_MINUTE, DEFAULT_MAX_REQUESTS_PER_MINUTE)),
            max_daily_tokens=int(current_daily_tokens),
            chat_max_limit=chat_max_limit,
            enable_debug=bool(_get(CONF_ENABLE_DEBUG_VIEWS, DEFAULT_ENABLE_DEBUG_VIEWS)),
            enable_mcp=bool(_get(CONF_ENABLE_MCP, DEFAULT_ENABLE_MCP)),
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
            cloud_provider=str(_get(CONF_CLOUD_PROVIDER, DEFAULT_CLOUD_PROVIDER)),
            cloud_use_for_chat=bool(_get(CONF_CLOUD_USE_FOR_CHAT, DEFAULT_CLOUD_USE_FOR_CHAT)),
            azure_endpoint=str(_get(CONF_AZURE_ENDPOINT, "")),
            azure_api_key=str(_get(CONF_AZURE_API_KEY, "")),
            azure_deployment=str(_get(CONF_AZURE_DEPLOYMENT, "")),
            azure_api_version=str(_get(CONF_AZURE_API_VERSION, DEFAULT_AZURE_API_VERSION)),
            openai_api_key=str(_get(CONF_OPENAI_API_KEY, "")),
            openai_model=str(_get(CONF_OPENAI_MODEL, DEFAULT_OPENAI_MODEL)),
            openai_base_url=str(_get(CONF_OPENAI_BASE_URL, "")),
            anthropic_api_key=str(_get(CONF_ANTHROPIC_API_KEY, "")),
            anthropic_model=str(_get(CONF_ANTHROPIC_MODEL, DEFAULT_ANTHROPIC_MODEL)),
            enable_mcp_in_chat=bool(_get(CONF_ENABLE_MCP_IN_CHAT, DEFAULT_ENABLE_MCP_IN_CHAT)),
            mcp_allow_state_changes=bool(_get(CONF_MCP_ALLOW_STATE_CHANGES, DEFAULT_MCP_ALLOW_STATE_CHANGES)),
            mcp_client_servers=str(_get(CONF_MCP_CLIENT_SERVERS, DEFAULT_MCP_CLIENT_SERVERS)),
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
