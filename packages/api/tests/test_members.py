"""§2.2 Team members — roles, role changes, removal, last-owner safeguards."""

from conftest import BOB, add_member, create_team, me
from httpx import AsyncClient


async def test_list_members(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.get(f"/api/v1/teams/{team['id']}/members", headers=alice_headers)
    assert resp.status_code == 200
    members = resp.json()["data"]
    assert len(members) == 2
    by_email = {m["email"]: m["role"] for m in members}
    assert by_email[BOB["email"]] == "member"


async def test_change_role_requires_admin(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    denied = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{alice['id']}",
        json={"role": "member"},
        headers=bob_headers,
    )
    assert denied.status_code == 403

    ok = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}",
        json={"role": "admin"},
        headers=alice_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["role"] == "admin"


async def test_granting_owner_requires_owner(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="admin")

    # Admin (bob) cannot self-promote to owner.
    denied = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}",
        json={"role": "owner"},
        headers=bob_headers,
    )
    assert denied.status_code == 403

    ok = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}",
        json={"role": "owner"},
        headers=alice_headers,
    )
    assert ok.status_code == 200


async def test_cannot_demote_last_owner(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    alice = await me(client, alice_headers)
    resp = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{alice['id']}",
        json={"role": "member"},
        headers=alice_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "last_owner"


async def test_remove_member_and_self_leave(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    # Bob (member) cannot remove Alice, but can leave.
    alice = await me(client, alice_headers)
    denied = await client.delete(
        f"/api/v1/teams/{team['id']}/members/{alice['id']}", headers=bob_headers
    )
    assert denied.status_code == 403

    left = await client.delete(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}", headers=bob_headers
    )
    assert left.status_code == 204

    members = await client.get(f"/api/v1/teams/{team['id']}/members", headers=alice_headers)
    assert len(members.json()["data"]) == 1


async def test_last_owner_cannot_leave(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    alice = await me(client, alice_headers)
    resp = await client.delete(
        f"/api/v1/teams/{team['id']}/members/{alice['id']}", headers=alice_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "last_owner"
