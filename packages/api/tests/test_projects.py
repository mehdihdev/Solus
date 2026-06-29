"""§2.3 Projects — CRUD under team, detail, cross-tenant isolation."""

from conftest import BOB, add_member, create_project, create_team, me
from httpx import AsyncClient


async def test_create_and_list_projects(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"], "Rover MK2")
    assert project["name"] == "Rover MK2"
    assert project["team_id"] == team["id"]

    resp = await client.get(f"/api/v1/teams/{team['id']}/projects", headers=alice_headers)
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["data"]] == [project["id"]]


async def test_project_detail_includes_summaries(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])

    resp = await client.get(f"/api/v1/projects/{project['id']}", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Graph/sources land in Phases 2–3; the detail shape ships now with empty summaries.
    assert data["stats"] == {"entities": 0, "relations": 0}
    assert data["sources"] == []


async def test_update_project(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])

    resp = await client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"description": "Six-wheel autonomous rover"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["description"] == "Six-wheel autonomous rover"


async def test_delete_project_requires_admin_and_confirmation(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="member")

    no_confirm = await client.delete(f"/api/v1/projects/{project['id']}", headers=alice_headers)
    assert no_confirm.status_code == 400

    not_admin = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=bob_headers
    )
    assert not_admin.status_code == 403

    ok = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=alice_headers
    )
    assert ok.status_code == 204

    gone = await client.get(f"/api/v1/projects/{project['id']}", headers=alice_headers)
    assert gone.status_code == 404


async def test_viewer_cannot_create_project(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="viewer")

    resp = await client.post(
        f"/api/v1/teams/{team['id']}/projects", json={"name": "Nope"}, headers=bob_headers
    )
    assert resp.status_code == 403


async def test_cross_tenant_project_isolation(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)

    read = await client.get(f"/api/v1/projects/{project['id']}", headers=bob_headers)
    assert read.status_code == 404

    mutate = await client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "Stolen"}, headers=bob_headers
    )
    assert mutate.status_code == 404

    delete = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=bob_headers
    )
    assert delete.status_code == 404
