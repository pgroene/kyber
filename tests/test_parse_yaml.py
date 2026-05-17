"""Functional tests for POST /api/kyber/parse_yaml.

Documented in docs/editor.md — the frontend uses this endpoint to convert
editor YAML to JSON before saving via HA's own config REST endpoints.
"""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant


async def test_valid_yaml_returns_config_dict(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Valid YAML mapping should return HTTP 200 with the parsed config."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/parse_yaml",
        json={"yaml": "alias: My Automation\ntrigger: []\naction: []"},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["config"]["alias"] == "My Automation"
    assert data["config"]["trigger"] == []
    assert data["config"]["action"] == []


async def test_valid_nested_yaml_returned_correctly(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Nested YAML structures should be fully preserved in the returned config."""
    client = await hass_client()
    yaml_text = (
        "alias: Climate\n"
        "trigger:\n"
        "  - platform: time\n"
        "    at: '07:00'\n"
        "action:\n"
        "  - service: climate.set_temperature\n"
        "    data:\n"
        "      temperature: 21\n"
    )
    resp = await client.post("/api/kyber/parse_yaml", json={"yaml": yaml_text})

    assert resp.status == 200
    data = await resp.json()
    assert data["config"]["trigger"][0]["platform"] == "time"
    assert data["config"]["action"][0]["data"]["temperature"] == 21


async def test_invalid_yaml_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Syntactically invalid YAML should return HTTP 400."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/parse_yaml",
        json={"yaml": "key: [\nbad indent"},
    )

    assert resp.status == 400


async def test_non_mapping_yaml_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """YAML that parses to a list (not a dict) should return HTTP 400."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/parse_yaml",
        json={"yaml": "- item1\n- item2"},
    )

    assert resp.status == 400


async def test_scalar_yaml_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """YAML that parses to a scalar (string) should return HTTP 400."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/parse_yaml",
        json={"yaml": "just a string"},
    )

    assert resp.status == 400


async def test_missing_yaml_field_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST without the 'yaml' field should return HTTP 400."""
    client = await hass_client()
    resp = await client.post("/api/kyber/parse_yaml", json={"other": "data"})

    assert resp.status == 400


async def test_empty_yaml_field_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """POST with an empty 'yaml' string should return HTTP 400."""
    client = await hass_client()
    resp = await client.post("/api/kyber/parse_yaml", json={"yaml": ""})

    assert resp.status == 400


async def test_unauthenticated_returns_401(
    hass: HomeAssistant, setup_integration, hass_client_no_auth
) -> None:
    """Unauthenticated /parse_yaml requests should return 401."""
    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/kyber/parse_yaml",
        json={"yaml": "alias: test"},
    )

    assert resp.status == 401


async def test_invalid_json_body_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """Non-JSON body to /parse_yaml should return 400."""
    client = await hass_client()
    resp = await client.post(
        "/api/kyber/parse_yaml",
        data=b"not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


async def test_whitespace_only_yaml_returns_400(
    hass: HomeAssistant, setup_integration, hass_client
) -> None:
    """YAML that is all spaces parses to None (not a dict) — should return 400."""
    client = await hass_client()
    resp = await client.post("/api/kyber/parse_yaml", json={"yaml": "      "})
    # yaml.safe_load("      ") returns None, which is not a dict
    assert resp.status == 400
