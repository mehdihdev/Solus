"""ADR-037 §5 — stream re-verification and the per-user stream cap."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import bearer, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.graph.live import Channel
from solus_api.graph.live_access import (
    LiveAccessVerifier,
    StreamLimiter,
    account_channels,
    live_team_ids,
)
from solus_api.models import Team, utcnow
from sqlalchemy.ext.asyncio import AsyncSession


def _token(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


def _verifier(app: FastAPI, token: str) -> LiveAccessVerifier:
    return LiveAccessVerifier(
        sessionmaker=app.state.sessionmaker,
        settings=app.state.settings,
        jwks_client=None,
        token=token,
    )


def test_limiter_caps_per_user_and_release_frees_a_slot() -> None:
    limiter = StreamLimiter(max_per_user=2)
    user, other = uuid.uuid4(), uuid.uuid4()

    first, second = limiter.acquire(user), limiter.acquire(user)

    assert first is not None and second is not None
    assert limiter.acquire(user) is None
    assert limiter.acquire(other) is not None  # another user is unaffected
    first.release()
    assert limiter.acquire(user) is not None


def test_releasing_a_permit_twice_frees_only_one_slot() -> None:
    limiter = StreamLimiter(max_per_user=1)
    user = uuid.uuid4()
    permit = limiter.acquire(user)
    assert permit is not None

    permit.release()
    permit.release()
    held = limiter.acquire(user)

    assert held is not None
    assert limiter.acquire(user) is None, "a double release leaked a slot"
    assert limiter.open_count(user) == 1


def test_account_channels_is_the_user_channel_plus_one_per_team() -> None:
    user, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    assert account_channels(user, [a, b]) == [Channel.user(user), Channel.team(a), Channel.team(b)]
    assert account_channels(user, []) == [Channel.user(user)]


async def test_live_team_ids_excludes_deleted_teams_and_memberships(
    client: AsyncClient, alice_headers: Any, db: AsyncSession
) -> None:
    alice = await me(client, alice_headers)
    kept = await create_team(client, alice_headers, "Kept")
    gone = await create_team(client, alice_headers, "Gone")
    team = await db.get(Team, uuid.UUID(gone["id"]))
    assert team is not None
    team.deleted_at = utcnow()
    await db.commit()

    ids = await live_team_ids(db, uuid.UUID(alice["id"]))

    assert uuid.UUID(kept["id"]) in ids
    assert uuid.UUID(gone["id"]) not in ids
    assert ids == sorted(set(ids), key=str)


async def test_verifier_accepts_a_valid_token_and_its_own_user(
    app: FastAPI, client: AsyncClient, alice_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    alice = uuid.UUID((await me(client, alice_headers))["id"])
    verifier = _verifier(app, _token(alice_headers))

    assert await verifier.project_access(uuid.UUID(project["id"]), alice) is True
    assert uuid.UUID(team["id"]) in (await verifier.account_teams(alice) or [])


@pytest.mark.parametrize(
    "token", ["garbage", "", bearer("x", "x@y.z", expires_in=-5)["Authorization"][7:]]
)
async def test_verifier_rejects_a_dead_credential(
    app: FastAPI, client: AsyncClient, alice_headers: Any, token: str
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    alice = uuid.UUID((await me(client, alice_headers))["id"])
    verifier = _verifier(app, token)

    assert await verifier.project_access(uuid.UUID(project["id"]), alice) is False
    assert await verifier.account_teams(alice) is None


async def test_verifier_rejects_a_token_for_a_different_user(
    app: FastAPI, client: AsyncClient, alice_headers: Any, bob_headers: Any
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    alice = uuid.UUID((await me(client, alice_headers))["id"])
    await me(client, bob_headers)
    verifier = _verifier(app, _token(bob_headers))  # bob's credential, alice's id

    assert await verifier.project_access(uuid.UUID(project["id"]), alice) is False
    assert await verifier.account_teams(alice) is None


async def test_verifier_does_not_provision_an_unknown_user(
    app: FastAPI, client: AsyncClient, alice_headers: Any, db: AsyncSession
) -> None:
    verifier = _verifier(app, bearer("ghost-sub", "ghost@example.com")["Authorization"][7:])

    assert await verifier.account_teams(uuid.uuid4()) is None

    from solus_api.models import User
    from sqlalchemy import select

    assert await db.scalar(select(User).where(User.supabase_user_id == "ghost-sub")) is None


async def test_verifier_denies_a_non_member_a_deleted_project_and_a_deleted_team(
    app: FastAPI, client: AsyncClient, alice_headers: Any, bob_headers: Any, db: AsyncSession
) -> None:
    from solus_api.models import Project

    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    alice = uuid.UUID((await me(client, alice_headers))["id"])
    bob = uuid.UUID((await me(client, bob_headers))["id"])
    pid = uuid.UUID(project["id"])

    assert await _verifier(app, _token(bob_headers)).project_access(pid, bob) is False
    assert await _verifier(app, _token(alice_headers)).project_access(pid, alice) is True

    row = await db.get(Project, pid)
    assert row is not None
    row.deleted_at = utcnow()
    await db.commit()
    assert await _verifier(app, _token(alice_headers)).project_access(pid, alice) is False

    row.deleted_at = None
    team_row = await db.get(Team, uuid.UUID(team["id"]))
    assert team_row is not None
    team_row.deleted_at = utcnow()
    await db.commit()
    assert await _verifier(app, _token(alice_headers)).project_access(pid, alice) is False


async def test_token_decoding_runs_off_the_event_loop(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PyJWKClient can block on a JWKS fetch, so the decode must not run on the loop."""
    import threading

    from solus_api.graph import live_access

    loop_thread = threading.get_ident()
    seen: list[int] = []
    real = live_access.decode_token

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(live_access, "decode_token", spy)
    user = await me(client, alice_headers)

    teams = await _verifier(app, _token(alice_headers)).account_teams(uuid.UUID(user["id"]))

    assert teams is not None
    assert seen and all(t != loop_thread for t in seen)
