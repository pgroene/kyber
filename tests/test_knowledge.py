import pytest

pytest.importorskip("pytest_homeassistant_custom_component", reason="requires pytest-homeassistant-custom-component")

from homeassistant.core import HomeAssistant


async def _create_knowledge_entry(client, *, content: str, personal: bool = False) -> dict:
    response = await client.post(
        "/api/kyber/knowledge",
        json={"category": "general", "content": content, "personal": personal},
    )
    assert response.status == 200
    return (await response.json())["entry"]


async def test_knowledge_visibility_is_scoped_per_user(
    hass: HomeAssistant,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
) -> None:
    admin_client = await hass_client()
    readonly_client = await hass_client(hass_read_only_access_token)

    global_entry = await _create_knowledge_entry(admin_client, content="global fact")
    admin_personal = await _create_knowledge_entry(admin_client, content="admin personal fact", personal=True)
    readonly_personal = await _create_knowledge_entry(readonly_client, content="readonly personal fact", personal=True)

    readonly_list = await readonly_client.get("/api/kyber/knowledge")
    assert readonly_list.status == 200
    readonly_entries = (await readonly_list.json())["entries"]
    readonly_contents = {entry["content"] for entry in readonly_entries}
    assert "global fact" in readonly_contents
    assert "readonly personal fact" in readonly_contents
    assert "admin personal fact" not in readonly_contents

    readonly_search = await readonly_client.get("/api/kyber/knowledge?q=personal")
    assert readonly_search.status == 200
    readonly_search_entries = (await readonly_search.json())["entries"]
    assert {entry["content"] for entry in readonly_search_entries} == {"readonly personal fact"}

    global_visible = next(entry for entry in readonly_entries if entry["id"] == global_entry["id"])
    own_visible = next(entry for entry in readonly_entries if entry["id"] == readonly_personal["id"])
    assert global_visible["owner_id"] is None
    assert own_visible["owner_id"] is not None

    admin_list = await admin_client.get("/api/kyber/knowledge")
    assert admin_list.status == 200
    admin_entries = (await admin_list.json())["entries"]
    admin_contents = {entry["content"] for entry in admin_entries}
    assert "global fact" in admin_contents
    assert "admin personal fact" in admin_contents
    assert "readonly personal fact" in admin_contents
    assert any(entry["id"] == admin_personal["id"] for entry in admin_entries)


async def test_knowledge_delete_requires_owner_or_admin(
    hass: HomeAssistant,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
) -> None:
    admin_client = await hass_client()
    readonly_client = await hass_client(hass_read_only_access_token)

    admin_personal = await _create_knowledge_entry(admin_client, content="admin private", personal=True)
    denied = await readonly_client.delete(f"/api/kyber/knowledge?id={admin_personal['id']}")
    assert denied.status == 403

    readonly_personal = await _create_knowledge_entry(readonly_client, content="readonly private", personal=True)
    own_delete = await readonly_client.delete(f"/api/kyber/knowledge?id={readonly_personal['id']}")
    assert own_delete.status == 200

    readonly_personal_2 = await _create_knowledge_entry(readonly_client, content="readonly private 2", personal=True)
    admin_override = await admin_client.delete(f"/api/kyber/knowledge?id={readonly_personal_2['id']}")
    assert admin_override.status == 200


async def test_knowledge_purge_is_admin_only(
    hass: HomeAssistant,
    setup_integration,
    hass_client,
    hass_read_only_access_token: str,
) -> None:
    admin_client = await hass_client()
    readonly_client = await hass_client(hass_read_only_access_token)

    personal_entry = await _create_knowledge_entry(readonly_client, content="purge target", personal=True)

    denied = await readonly_client.post("/api/kyber/knowledge/purge", json={"ids": [personal_entry["id"]]})
    assert denied.status == 403

    allowed = await admin_client.post("/api/kyber/knowledge/purge", json={"ids": [personal_entry["id"]]})
    assert allowed.status == 200
    assert await allowed.json() == {"status": "ok", "deleted": 1, "not_found": 0}
