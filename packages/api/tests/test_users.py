"""§2.1 Users & settings (api-keys deferred to a later slice per §8 Phase 1)."""

from conftest import ALICE, BOB, add_member, create_team, me
from httpx import AsyncClient


async def test_get_me_shape(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    data = await me(client, alice_headers)
    assert set(data) >= {"id", "email", "name", "avatar_url", "created_at", "teams"}
    team = data["teams"][0]
    assert set(team) >= {"team_id", "name", "role", "is_personal", "plan_status", "trial_ends_at"}
    assert team["plan_status"] == "trial"


async def test_patch_me_updates_profile(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        json={"name": "Alice Liddell", "avatar_url": "https://example.com/a.png"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Alice Liddell"
    assert (await me(client, alice_headers))["name"] == "Alice Liddell"


async def test_patch_me_rejects_unknown_fields(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch("/api/v1/users/me", json={"email": "x@y.z"}, headers=alice_headers)
    assert resp.status_code == 422


async def test_settings_default_sol_mode_guide(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["sol_mode"] == "guide"


async def test_settings_patch_sol_mode(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    resp = await client.patch(
        "/api/v1/users/me/settings", json={"sol_mode": "expert"}, headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["sol_mode"] == "expert"


async def test_settings_patch_rejects_invalid_mode(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/settings", json={"sol_mode": "yolo"}, headers=alice_headers
    )
    assert resp.status_code == 422


async def test_delete_me_removes_account_and_personal_team(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    before = await me(client, alice_headers)
    old_team_id = before["teams"][0]["team_id"]

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204

    # Re-auth re-provisions a fresh account; the old personal team is gone.
    after = await me(client, alice_headers)
    assert after["id"] != before["id"]
    assert after["teams"][0]["team_id"] != old_team_id


async def test_delete_me_blocked_while_sole_owner_of_shared_team(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ownership_transfer_required"


async def test_users_cannot_read_each_other(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    assert alice["id"] != bob["id"]
    assert alice["email"] == ALICE["email"]
    assert bob["email"] == BOB["email"]
