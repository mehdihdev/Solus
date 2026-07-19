"""Email-verification gating (SOLUSDEV-82 / SOLUS-FND-02, AC #2).

Sensitive write actions (create team, invite, connect a source, delete account)
require a verified email. The `require_verified` dependency reads the Supabase
JWT's `email_verified` claim; an *absent* claim is treated as verified (Supabase
may omit it), while an explicit `false` engages the gate.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from conftest import ALICE, bearer, create_project, create_team
from httpx import AsyncClient
from solus_api.core.config import Settings
from solus_api.core.security import decode_token

TEST_JWT_SECRET = "dummy-jwt-signing-value-tests-only"  # noqa: S105 - matches conftest


def _encode(**claims: Any) -> str:
    payload = {
        "sub": ALICE["sub"],
        "email": ALICE["email"],
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        **claims,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _settings() -> Settings:
    return Settings(supabase_jwt_secret=TEST_JWT_SECRET, supabase_jwt_audience="authenticated")


def _token(**kwargs: Any) -> str:
    from conftest import make_token

    return make_token(ALICE["sub"], ALICE["email"], **kwargs)


# --- unit: claim parsing --------------------------------------------------


def test_decode_absent_claim_is_verified() -> None:
    claims = decode_token(_token(), _settings())
    assert claims.email_verified is True


def test_decode_explicit_false_is_unverified() -> None:
    claims = decode_token(_token(email_verified=False), _settings())
    assert claims.email_verified is False


def test_decode_explicit_true_is_verified() -> None:
    claims = decode_token(_token(email_verified=True), _settings())
    assert claims.email_verified is True


def test_app_metadata_email_verified_is_trusted() -> None:
    claims = decode_token(_encode(app_metadata={"email_verified": False}), _settings())
    assert claims.email_verified is False


def test_user_metadata_email_verified_is_not_trusted() -> None:
    # user_metadata is user-writable (Supabase updateUser({data})). A self-set
    # value must NOT drive the gate — absent from trusted sources ⇒ verified.
    claims = decode_token(_encode(user_metadata={"email_verified": False}), _settings())
    assert claims.email_verified is True


# --- integration: the gate on sensitive routes ----------------------------


async def test_create_team_requires_verified_email(client: AsyncClient) -> None:
    unverified = bearer(ALICE["sub"], ALICE["email"], email_verified=False)
    resp = await client.post("/api/v1/teams", json={"name": "Robotics"}, headers=unverified)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_verified_user_can_create_team(client: AsyncClient) -> None:
    verified = bearer(ALICE["sub"], ALICE["email"], email_verified=True)
    resp = await client.post("/api/v1/teams", json={"name": "Robotics"}, headers=verified)
    assert resp.status_code == 201, resp.text


async def test_invite_requires_verified_email(client: AsyncClient) -> None:
    # Set up as a verified user, then attempt the invite with an unverified token
    # for the same account — only the invite call should be gated.
    verified = bearer(ALICE["sub"], ALICE["email"], email_verified=True)
    team = await create_team(client, verified)
    unverified = bearer(ALICE["sub"], ALICE["email"], email_verified=False)
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/invites",
        json={"email": "bob@example.com", "role": "member"},
        headers=unverified,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_connect_source_requires_verified_email(client: AsyncClient) -> None:
    verified = bearer(ALICE["sub"], ALICE["email"], email_verified=True)
    team = await create_team(client, verified)
    project = await create_project(client, verified, team["id"])
    unverified = bearer(ALICE["sub"], ALICE["email"], email_verified=False)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/sources",
        json={"type": "github", "name": "fw", "config": {}},
        headers=unverified,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_delete_account_requires_verified_email(client: AsyncClient) -> None:
    unverified = bearer(ALICE["sub"], ALICE["email"], email_verified=False)
    resp = await client.delete("/api/v1/users/me", headers=unverified)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "email_not_verified"
