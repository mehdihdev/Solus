"""§2.2 Activity feed — recorded on meaningful team actions, filterable."""

from conftest import BOB, add_member, create_project, create_team, me
from httpx import AsyncClient


async def test_team_actions_append_activity(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await create_project(client, alice_headers, team["id"], "Rover")

    resp = await client.get(f"/api/v1/teams/{team['id']}/activity", headers=alice_headers)
    assert resp.status_code == 200
    types = [a["type"] for a in resp.json()["data"]]
    assert "project.created" in types
    assert "team.created" in types
    # Newest first
    assert types.index("project.created") < types.index("team.created")


async def test_activity_filter_by_type(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    await create_project(client, alice_headers, team["id"])

    resp = await client.get(
        f"/api/v1/teams/{team['id']}/activity?type=project.created", headers=alice_headers
    )
    rows = resp.json()["data"]
    assert rows
    assert all(a["type"] == "project.created" for a in rows)


async def test_activity_filter_by_actor(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.get(
        f"/api/v1/teams/{team['id']}/activity?actor={bob['id']}", headers=alice_headers
    )
    rows = resp.json()["data"]
    assert rows
    assert all(a["actor_id"] == bob["id"] for a in rows)


async def test_activity_meta_total_counts_matching_rows(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    for i in range(3):
        await create_project(client, alice_headers, team["id"], f"P{i}")

    everything = await client.get(
        f"/api/v1/teams/{team['id']}/activity?limit=100", headers=alice_headers
    )
    full_count = len(everything.json()["data"])
    assert everything.json()["meta"]["total"] == full_count

    # Total spans the whole feed, not just the returned page.
    first = await client.get(f"/api/v1/teams/{team['id']}/activity?limit=2", headers=alice_headers)
    body = first.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == full_count

    # Total is stable when following the cursor.
    rest = await client.get(
        f"/api/v1/teams/{team['id']}/activity?limit=2&cursor={body['meta']['next_cursor']}",
        headers=alice_headers,
    )
    assert rest.json()["meta"]["total"] == full_count


async def test_activity_meta_total_respects_filters(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    for i in range(2):
        await create_project(client, alice_headers, team["id"], f"P{i}")

    resp = await client.get(
        f"/api/v1/teams/{team['id']}/activity?type=project.created", headers=alice_headers
    )
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2


async def test_activity_pagination(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    for i in range(3):
        await create_project(client, alice_headers, team["id"], f"P{i}")

    first = await client.get(f"/api/v1/teams/{team['id']}/activity?limit=2", headers=alice_headers)
    body = first.json()
    assert len(body["data"]) == 2
    assert body["meta"]["has_next"] is True

    rest = await client.get(
        f"/api/v1/teams/{team['id']}/activity?limit=50&cursor={body['meta']['next_cursor']}",
        headers=alice_headers,
    )
    assert rest.json()["meta"]["has_next"] is False
