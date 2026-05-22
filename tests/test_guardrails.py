import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant


async def test_high_risk_autopilot_requires_confirmation_without_override(
    hass: HomeAssistant,
    setup_integration,
    hass_client,
) -> None:
    service_calls = []

    async def fake_service(call):
        service_calls.append(call)

    hass.services.async_register("input_boolean", "turn_on", fake_service)
    hass.states.async_set("input_boolean.night_mode", "off")

    client = await hass_client()
    blocked = await client.post(
        "/api/kyber/execute",
        json={
            "approved": False,
            "actions": [{
                "type": "call_service",
                "domain": "input_boolean",
                "service": "turn_on",
                "entity_id": "input_boolean.night_mode",
            }],
        },
    )

    assert blocked.status == 403
    body = await blocked.json()
    assert body["status"] == "approval_required"
    assert body["blocked_actions"][0]["domain"] == "input_boolean"
    assert service_calls == []

    manual = await client.post(
        "/api/kyber/execute",
        json={
            "approved": True,
            "actions": [{
                "type": "call_service",
                "domain": "input_boolean",
                "service": "turn_on",
                "entity_id": "input_boolean.night_mode",
            }],
        },
    )
    assert manual.status == 200
    assert (await manual.json())["results"][0]["status"] == "ok"
    assert len(service_calls) == 1


async def test_guardrails_override_is_user_scoped_and_allows_autopilot(
    hass: HomeAssistant,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
) -> None:
    service_calls = []

    async def fake_service(call):
        service_calls.append(call)

    hass.services.async_register("input_boolean", "turn_on", fake_service)
    hass.states.async_set("input_boolean.movie_mode", "off")

    admin_client = await hass_client()
    readonly_client = await hass_client(hass_read_only_access_token)

    initial = await readonly_client.get("/api/kyber/guardrails")
    assert initial.status == 200
    assert (await initial.json())["overrides"]["input_boolean"] == "ask"

    saved = await readonly_client.post(
        "/api/kyber/guardrails",
        json={"domain": "input_boolean", "mode": "auto"},
    )
    assert saved.status == 200
    saved_body = await saved.json()
    assert saved_body["mode"] == "auto"
    assert saved_body["overrides"]["input_boolean"] == "auto"

    admin_view = await admin_client.get("/api/kyber/guardrails")
    assert admin_view.status == 200
    assert (await admin_view.json())["overrides"]["input_boolean"] == "ask"

    allowed = await readonly_client.post(
        "/api/kyber/execute",
        json={
            "approved": False,
            "actions": [{
                "type": "call_service",
                "domain": "input_boolean",
                "service": "turn_on",
                "entity_id": "input_boolean.movie_mode",
            }],
        },
    )
    assert allowed.status == 200
    assert (await allowed.json())["results"][0]["status"] == "ok"
    assert len(service_calls) == 1
