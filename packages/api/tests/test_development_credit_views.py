"""Development entitlement is current-user-only and leaves accounting truthful."""

import pytest
from conftest import ALICE, BOB, bearer, me
from fastapi import FastAPI
from httpx import AsyncClient


@pytest.mark.parametrize("environment", ["dev", "production", "staging"])
async def test_credit_views_scope(client: AsyncClient, app: FastAPI, environment: str) -> None:
    alice = bearer(ALICE["sub"], ALICE["email"])
    bob = bearer(BOB["sub"], BOB["email"])
    identity = await me(client, alice)
    await me(client, bob)
    app.state.settings.app_env = environment
    app.state.settings.development_unlimited_credit_user_ids = identity["id"]
    for endpoint in ("credits", "usage"):
        for headers, eligible in ((alice, environment == "dev"), (bob, False)):
            result = await client.get(f"/api/v1/users/me/{endpoint}", headers=headers)
            assert result.status_code == 200
            data = result.json()["data"]
            assert data["unlimited"] is eligible
            assert data["balance"] == 1000
            assert "development_unlimited_credit_user_ids" not in data
        anonymous = await client.get(f"/api/v1/users/me/{endpoint}")
        assert anonymous.status_code == 401
