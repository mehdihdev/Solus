"""§2.2 Teams — CRUD, roles, deletion safeguards, cross-tenant isolation."""

from conftest import BOB, add_member, create_team, me
from httpx import AsyncClient


async def test_create_and_list_teams(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers, "Mars Rover Lab")
    assert team["name"] == "Mars Rover Lab"
    assert team["is_personal"] is False

    resp = await client.get("/api/v1/teams", headers=alice_headers)
    assert resp.status_code == 200
    teams = resp.json()["data"]
    assert len(teams) == 2  # personal + created
    roles = {t["id"]: t["role"] for t in teams}
    assert roles[team["id"]] == "owner"


async def test_team_detail_includes_member_count(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    resp = await client.get(f"/api/v1/teams/{team['id']}", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["member_count"] == 1
    assert data["role"] == "owner"


async def test_team_isolation_non_member_gets_404(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    for method, url in [
        ("get", f"/api/v1/teams/{team['id']}"),
        ("get", f"/api/v1/teams/{team['id']}/members"),
        ("get", f"/api/v1/teams/{team['id']}/invites"),
        ("get", f"/api/v1/teams/{team['id']}/activity"),
        ("get", f"/api/v1/teams/{team['id']}/projects"),
    ]:
        resp = await client.request(method.upper(), url, headers=bob_headers)
        assert resp.status_code == 404, f"{url} leaked to non-member"


async def test_rename_team_requires_admin(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="member")

    denied = await client.patch(
        f"/api/v1/teams/{team['id']}", json={"name": "Hijacked"}, headers=bob_headers
    )
    assert denied.status_code == 403

    ok = await client.patch(
        f"/api/v1/teams/{team['id']}", json={"name": "Renamed"}, headers=alice_headers
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["name"] == "Renamed"


async def test_delete_team_requires_owner_and_confirmation(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="admin")

    no_confirm = await client.delete(f"/api/v1/teams/{team['id']}", headers=alice_headers)
    assert no_confirm.status_code == 400
    assert no_confirm.json()["error"]["code"] == "confirmation_required"

    not_owner = await client.delete(f"/api/v1/teams/{team['id']}?confirm=true", headers=bob_headers)
    assert not_owner.status_code == 403

    ok = await client.delete(f"/api/v1/teams/{team['id']}?confirm=true", headers=alice_headers)
    assert ok.status_code == 204

    gone = await client.get(f"/api/v1/teams/{team['id']}", headers=alice_headers)
    assert gone.status_code == 404


async def test_personal_team_cannot_be_deleted(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    personal = (await me(client, alice_headers))["teams"][0]
    resp = await client.delete(
        f"/api/v1/teams/{personal['team_id']}?confirm=true", headers=alice_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "personal_team_undeletable"


async def test_team_settings_default_and_persist(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """FND-07: team settings persist to the DB and come back on detail."""
    team = await create_team(client, alice_headers)
    detail = (await client.get(f"/api/v1/teams/{team['id']}", headers=alice_headers)).json()["data"]
    assert detail["settings"] == {"notify_project_created": True}

    resp = await client.patch(
        f"/api/v1/teams/{team['id']}",
        json={"settings": {"notify_project_created": False}},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["settings"]["notify_project_created"] is False

    detail = (await client.get(f"/api/v1/teams/{team['id']}", headers=alice_headers)).json()["data"]
    assert detail["settings"]["notify_project_created"] is False


async def test_team_settings_reject_unknown_keys(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    resp = await client.patch(
        f"/api/v1/teams/{team['id']}",
        json={"settings": {"evil_flag": True}},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_team_settings_require_admin(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="member")
    resp = await client.patch(
        f"/api/v1/teams/{team['id']}",
        json={"settings": {"notify_project_created": False}},
        headers=bob_headers,
    )
    assert resp.status_code == 403
