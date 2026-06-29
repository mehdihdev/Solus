"""Centralized auth middleware/dependencies (CLAUDE.md §7, API.md §1.2/§1.3).

Covers: bearer enforcement, auto-provisioning of the user + personal team at
first authenticated request, and team/project scoping basics.
"""

from conftest import ALICE, bearer, me
from httpx import AsyncClient


async def test_protected_route_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_protected_route_rejects_invalid_token(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


async def test_protected_route_rejects_expired_token(client: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"], expires_in=-60)
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 401


async def test_first_login_provisions_user_and_personal_team(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    data = await me(client, alice_headers)
    assert data["email"] == ALICE["email"]
    assert len(data["teams"]) == 1
    team = data["teams"][0]
    assert team["is_personal"] is True
    assert team["role"] == "owner"


async def test_second_login_does_not_duplicate_user(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    first = await me(client, alice_headers)
    second = await me(client, alice_headers)
    assert first["id"] == second["id"]
    assert len(second["teams"]) == 1
