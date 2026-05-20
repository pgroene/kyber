"""TDD tests for kyber config flow — written BEFORE implementation (RED)."""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.kyber.const import DOMAIN

from pytest_homeassistant_custom_component.common import mock_component


@pytest.fixture(autouse=True)
def mock_dependencies(hass: HomeAssistant) -> None:
    """Mark ai_task as already set up so the dependency chain is bypassed."""
    mock_component(hass, "ai_task")


async def test_form_shown(hass: HomeAssistant) -> None:
    """Config flow step 1 should show the AI task entity selector."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    schema_keys = [str(k) for k in result["data_schema"].schema.keys()]
    assert any("ai_task_entity_id" in k for k in schema_keys)


async def test_creates_entry_with_entity_id(hass: HomeAssistant) -> None:
    """Submitting a valid ai_task entity ID should proceed to step 2, then create entry."""
    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )

    # Step 1: entity selection
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"ai_task_entity_id": "ai_task.ollama_ai_task"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "model_config"
    schema_keys = [str(k) for k in result["data_schema"].schema.keys()]
    assert any("max_tokens" in k for k in schema_keys)

    # Step 2: model config
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"max_tokens": 2048},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["ai_task_entity_id"] == "ai_task.ollama_ai_task"
    assert result["data"]["max_tokens"] == 2048


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
    """Submitting max_tokens=255 (below schema minimum of 256) should raise InvalidData."""
    from homeassistant.data_entry_flow import InvalidData

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"ai_task_entity_id": "ai_task.ollama_ai_task"},
    )
    assert result["step_id"] == "model_config"
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"max_tokens": 255},
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
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"ai_task_entity_id": "ai_task.ollama_ai_task"},
    )
    assert result["step_id"] == "model_config"
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"max_tokens": 2_000_001},
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
        user_input={"ai_task_entity_id": "ai_task.ollama_ai_task"},
    )
    assert result["step_id"] == "model_config"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"max_tokens": 100_000},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["max_tokens"] == 100_000


async def test_initial_deep_learning_runs_above_maximum_returns_form_error(hass: HomeAssistant) -> None:
    """Submitting initial_deep_learning_runs=11 should raise InvalidData."""
    from homeassistant.data_entry_flow import InvalidData

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "ai_task", "ollama", "ollama_ai_task", suggested_object_id="ollama_ai_task"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"ai_task_entity_id": "ai_task.ollama_ai_task"},
    )
    assert result["step_id"] == "model_config"
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "max_tokens": 2048,
                "initial_deep_learning_runs": 11,
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
    """Submitting a Home Assistant Cloud ai_task entity should create a config entry.

    This verifies that Kyber works with HA Cloud AI without requiring Ollama.
    """
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
        user_input={"ai_task_entity_id": "ai_task.home_assistant_cloud_data_generation"},
    )
    assert result["step_id"] == "model_config"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"max_tokens": 4096},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["ai_task_entity_id"] == "ai_task.home_assistant_cloud_data_generation"
    assert result["data"]["max_tokens"] == 4096


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
    schema_keys = [str(k) for k in result["data_schema"].schema.keys()]
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
    # Other settings preserved
    assert entry.data["max_tokens"] == 4096
