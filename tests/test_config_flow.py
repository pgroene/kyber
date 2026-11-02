"""TDD tests for kyber config flow — written BEFORE implementation (RED)."""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import mock_component

from custom_components.kyber.const import DOMAIN


@pytest.fixture(autouse=True)
def mock_dependencies(hass: HomeAssistant) -> None:
    """Mark ai_task as already set up so the dependency chain is bypassed."""
    mock_component(hass, "ai_task")


@pytest.fixture(autouse=True)
def mock_initial_learning():
    """Prevent background tasks from running during config flow tests.

    _async_run_initial_learning, _async_explore_integrations, and
    _async_seed_language_hints all call async_update_entry or external
    services, which schedule HA storage delayed-write timers that outlive
    the test's event loop and cause teardown errors.
    """
    with patch("custom_components.kyber._async_run_initial_learning"), \
         patch("custom_components.kyber._async_explore_integrations"), \
         patch("custom_components.kyber._async_seed_language_hints"):
        yield


async def test_form_shown(hass: HomeAssistant) -> None:
    """Config flow step 1 should show the AI task entity selector."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    schema_keys = [str(k) for k in result["data_schema"].schema]
    assert any("ai_task_entity_id" in k for k in schema_keys)


async def test_creates_entry_with_entity_id(hass: HomeAssistant) -> None:
    """Submitting a valid ai_task entity ID and settings should create a config entry."""
    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "model_config": {"max_tokens": 32_000},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["ai_task_entity_id"] == "ai_task.ollama_ai_task"
    assert result["data"]["max_tokens"] == 32_000


async def test_no_ai_task_entity_shows_error(hass: HomeAssistant) -> None:
    """Submitting an entity_id that does not exist should show a validation error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"ai_task_entity_id": "ai_task.does_not_exist"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("ai_task_entity_id") == "entity_not_found"


async def test_max_tokens_below_minimum_returns_form_error(hass: HomeAssistant) -> None:
    """Submitting max_tokens=1999 (below schema minimum of 2000) should raise InvalidData."""
    from homeassistant.data_entry_flow import InvalidData

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "ai_task_entity_id": "ai_task.ollama_ai_task",
                "model_config": {"max_tokens": 1_999},
            },
        )


async def test_max_tokens_above_maximum_returns_form_error(hass: HomeAssistant) -> None:
    """Submitting max_tokens=2000001 (above schema maximum of 2000000) should raise InvalidData."""
    from homeassistant.data_entry_flow import InvalidData

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "ai_task_entity_id": "ai_task.ollama_ai_task",
                "model_config": {"max_tokens": 2_000_001},
            },
        )


async def test_creates_entry_with_large_max_tokens(hass: HomeAssistant) -> None:
    """Submitting a large supported max_tokens value should create a config entry."""
    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "model_config": {"max_tokens": 100_000},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["max_tokens"] == 100_000


async def test_deep_learning_interval_above_maximum_returns_form_error(hass: HomeAssistant) -> None:
    """Submitting deep_learning_interval_days=91 (above schema maximum of 90) should raise InvalidData."""
    from homeassistant.data_entry_flow import InvalidData

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "ai_task_entity_id": "ai_task.ollama_ai_task",
                "agents": {"deep_learning_interval_days": 91},
            },
        )


async def test_duplicate_config_entry_aborted(hass: HomeAssistant) -> None:
    """Starting the flow when a config entry already exists should be aborted."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    existing = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test", "max_tokens": 2048},
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_creates_entry_with_cloud_entity(hass: HomeAssistant) -> None:
    """Submitting a Home Assistant Cloud ai_task entity should create a config entry."""
    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task",
        "cloud",
        "home_assistant_cloud_data_generation",
        suggested_object_id="home_assistant_cloud_data_generation",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "ai_task_entity_id": "ai_task.home_assistant_cloud_data_generation",
            "model_config": {"max_tokens": 32_000},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["ai_task_entity_id"] == "ai_task.home_assistant_cloud_data_generation"
    assert result["data"]["max_tokens"] == 32_000


async def test_reconfigure_shows_entity_selector(hass: HomeAssistant) -> None:
    """Reconfigure flow shows entity selector pre-filled with current entity."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.old_entity", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    schema_keys = [str(k) for k in result["data_schema"].schema]
    assert any("ai_task_entity_id" in k for k in schema_keys)


async def test_reconfigure_invalid_entity_shows_error(hass: HomeAssistant) -> None:
    """Reconfigure with non-existent entity shows entity_not_found error."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.old_entity", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"ai_task_entity_id": "ai_task.does_not_exist"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("ai_task_entity_id") == "entity_not_found"


async def test_reconfigure_updates_entity_and_aborts(hass: HomeAssistant) -> None:
    """Reconfigure with a valid new entity updates the entry and aborts successfully."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.old_entity", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "new_model", suggested_object_id="new_model"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"ai_task_entity_id": "ai_task.new_model"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["ai_task_entity_id"] == "ai_task.new_model"
    # Other settings preserved from original entry
    assert entry.data["max_tokens"] == 4096


async def test_creates_entry_with_narrator_max_tokens(hass: HomeAssistant) -> None:
    """narrator_max_tokens submitted in model_config section should be stored."""
    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "ai_task_entity_id": "ai_task.ollama_ai_task",
            "model_config": {"max_tokens": 32_000, "narrator_max_tokens": 8192},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["narrator_max_tokens"] == 8192


async def test_options_flow_shows_stats_placeholders(hass: HomeAssistant) -> None:
    """Options flow init step should include description_placeholders with stats keys."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    placeholders = result.get("description_placeholders", {})
    assert {"chat_calls", "ops_calls", "narrator_last", "deep_learning_total"} <= set(placeholders)


async def test_options_flow_saves_narrator_max_tokens(hass: HomeAssistant) -> None:
    """Submitting narrator_max_tokens via options flow stores it correctly."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.test_model",
                "max_tokens": 20_000,
                "narrator_max_tokens": 4_096,
            },
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["narrator_max_tokens"] == 4_096


async def test_options_flow_changes_chat_model(hass: HomeAssistant) -> None:
    """Changing ai_task_entity_id via options flow updates the stored entity."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "new_chat", suggested_object_id="new_chat"
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.old_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.new_chat",
                "max_tokens": 20_000,
                "narrator_max_tokens": 8192,
            },
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["ai_task_entity_id"] == "ai_task.new_chat"


async def test_options_flow_saves_anthropic_cloud_provider(hass: HomeAssistant) -> None:
    """Options flow should save Anthropic cloud provider settings."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.test_model",
                "max_tokens": 20_000,
            },
            "cloud_config": {
                "cloud_provider": "anthropic",
                "cloud_use_for_chat": True,
                "anthropic_api_key": "sk-ant-mykey",
                "anthropic_model": "claude-sonnet-4-5",
            },
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["cloud_provider"] == "anthropic"
    assert result["data"]["anthropic_api_key"] == "sk-ant-mykey"
    assert result["data"]["anthropic_model"] == "claude-sonnet-4-5"
    assert result["data"]["cloud_use_for_chat"] is True


async def test_options_flow_saves_openai_cloud_provider_with_custom_base_url(hass: HomeAssistant) -> None:
    """Options flow should save OpenAI provider with a custom base_url (e.g. Groq)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.test_model",
                "max_tokens": 20_000,
            },
            "cloud_config": {
                "cloud_provider": "openai",
                "cloud_use_for_chat": True,
                "openai_api_key": "sk-groq-key",
                "openai_model": "llama3-70b",
                "openai_base_url": "https://api.groq.com/openai",
            },
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["cloud_provider"] == "openai"
    assert result["data"]["openai_api_key"] == "sk-groq-key"
    assert result["data"]["openai_model"] == "llama3-70b"
    assert result["data"]["openai_base_url"] == "https://api.groq.com/openai"


async def test_options_flow_cloud_provider_none_clears_use_for_chat(hass: HomeAssistant) -> None:
    """Selecting cloud_provider=none should still save cloud_use_for_chat correctly."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.test_model",
                "max_tokens": 20_000,
            },
            "cloud_config": {
                "cloud_provider": "none",
                "cloud_use_for_chat": False,
            },
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["cloud_provider"] == "none"
    assert result["data"]["cloud_use_for_chat"] is False


async def test_options_flow_invalid_chat_model_shows_error(hass: HomeAssistant) -> None:
    """Submitting a non-existent entity in options flow shows entity_not_found error."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.test_model", "max_tokens": 4096},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.does_not_exist",
                "max_tokens": 20_000,
                "narrator_max_tokens": 8192,
            },
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("ai_task_entity_id") == "entity_not_found"


async def test_options_flow_preserves_cloud_credentials_when_cloud_section_missing(
    hass: HomeAssistant,
) -> None:
    """Saving options without submitting the cloud section must NOT wipe credentials.

    This is a regression test for the bug where saving any options step would
    reset all cloud credentials to defaults because missing sections fell back
    to empty dicts instead of the existing stored config.
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.kyber.const import (
        CLOUD_PROVIDER_OPENAI,
        CONF_CLOUD_PROVIDER,
        CONF_CLOUD_USE_FOR_CHAT,
        CONF_OPENAI_API_KEY,
        CONF_OPENAI_MODEL,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ai_task_entity_id": "ai_task.test_model",
            "max_tokens": 4096,
            CONF_CLOUD_PROVIDER: CLOUD_PROVIDER_OPENAI,
            CONF_CLOUD_USE_FOR_CHAT: True,
            CONF_OPENAI_API_KEY: "sk-keep-this-key",
            CONF_OPENAI_MODEL: "gpt-4o",
        },
    )
    entry.add_to_hass(hass)

    # Submit options WITHOUT including the cloud section at all
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "model_config": {
                "ai_task_entity_id": "ai_task.test_model",
                "max_tokens": 4096,
            },
            # cloud_config section deliberately omitted
            "agents": {},
            "area_assignment": {},
            "developer": {},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    saved = result["data"]
    # Cloud credentials must be preserved
    assert saved.get(CONF_CLOUD_PROVIDER) == CLOUD_PROVIDER_OPENAI
    assert saved.get(CONF_CLOUD_USE_FOR_CHAT) is True
    assert saved.get(CONF_OPENAI_API_KEY) == "sk-keep-this-key"
    assert saved.get(CONF_OPENAI_MODEL) == "gpt-4o"


def _model_section_defaults(data_schema) -> dict:
    """Defaults of the model_config section of an options-form schema.

    HA renders a section as {Optional(key): section(field_schema, opts)} — the
    section object sits in the dict VALUE and carries the field schema in
    .schema.schema.
    """
    for key in data_schema.schema:
        if str(key) == "model_config":
            fields = data_schema.schema[key].schema.schema
            break
    else:
        raise AssertionError("model_config section missing")
    out: dict = {}
    for k in fields:
        default = getattr(k, "default", None)
        if default is not None:
            out[str(k)] = default() if callable(default) else default
    return out


async def test_infer_max_tokens_prefers_longest_pattern(hass: HomeAssistant) -> None:
    """Regression: "qwen" matched first and shadowed the qwen3-family entries,
    giving a 262k model the generic 32768 window."""
    from custom_components.kyber.config_flow import _infer_max_tokens

    hass.states.async_set(
        "ai_task.local_qwen", "unknown", {"model_name": "qwen3.5-flash-next"}
    )
    assert _infer_max_tokens(hass, "ai_task.local_qwen") == 262_144

    hass.states.async_set("ai_task.m_qwen3", "unknown", {"model_name": "qwen3:32b"})
    assert _infer_max_tokens(hass, "ai_task.m_qwen3") == 131_072

    hass.states.async_set("ai_task.m_plain_qwen", "unknown", {"model_name": "qwen:7b"})
    assert _infer_max_tokens(hass, "ai_task.m_plain_qwen") == 32_768


async def test_infer_max_tokens_direct_attribute_wins(hass: HomeAssistant) -> None:
    """A context_window attribute on the entity beats any name inference."""
    from custom_components.kyber.config_flow import _infer_max_tokens

    hass.states.async_set(
        "ai_task.my_model", "unknown", {"model_name": "qwen3.5-flash-next", "num_ctx": 250_000}
    )
    assert _infer_max_tokens(hass, "ai_task.my_model") == 250_000


async def test_options_form_prefills_inferred_window_for_stored_default(hass: HomeAssistant) -> None:
    """A stored max_tokens that equals the old default is re-inferred from the
    model entity, so upgrading Kyber fixes the window of a qwen3.5 model."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.kyber.const import DEFAULT_MAX_TOKENS

    hass.states.async_set("ai_task.qwen_flash", "unknown", {"model_name": "qwen3.5-flash-next"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.qwen_flash", "max_tokens": DEFAULT_MAX_TOKENS},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    section = _model_section_defaults(result["data_schema"])
    assert section.get("max_tokens") == 262_144


async def test_options_form_keeps_user_chosen_window(hass: HomeAssistant) -> None:
    """A window the user chose deliberately is never overwritten by inference."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    hass.states.async_set("ai_task.qwen_flash", "unknown", {"model_name": "qwen3.5-flash-next"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ai_task_entity_id": "ai_task.qwen_flash", "max_tokens": 16_000},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    section = _model_section_defaults(result["data_schema"])
    assert section.get("max_tokens") == 16_000
