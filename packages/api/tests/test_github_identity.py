"""SOLUSDEV-216 T7 - verified GitHub identity (ADR-039 section 6, docs/api/github-orgs.md).

A GitHub id is proven ONLY by a live connected GitHub AccountConnection, or by the Supabase
admin identity. JWT user_metadata is never a source."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import respx
from fixtures.team_installation_seed import seed_team, seed_user
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    Membership,
    Role,
    SourceType,
    User,
    utcnow,
)
from solus_api.services.github_identity import github_ids_for_team_members, verified_github_id
from solus_api.services.supabase_admin import SupabaseAdmin
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

BASE = "https://proj.supabase.test"


class FakeAdmin:
    def __init__(self, value: int | None) -> None:
        self.value = value
        self.calls: list[str] = []

    async def github_identity(self, user_supabase_id: str) -> int | None:
        self.calls.append(user_supabase_id)
        return self.value


async def connect(
    db: AsyncSession,
    user: User,
    external_id: str | None,
    *,
    status: ConnectionStatus = ConnectionStatus.CONNECTED,
    provider: SourceType = SourceType.GITHUB,
) -> AccountConnection:
    row = AccountConnection(
        user_id=user.id,
        provider=provider,
        status=status,
        account_external_id=external_id,
        account_login="someone",
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------- verified_github_id


async def test_connection_is_the_first_source(db: AsyncSession) -> None:
    user = await seed_user(db)
    await connect(db, user, "4242")
    admin = FakeAdmin(999)

    assert await verified_github_id(db, user, admin=admin) == 4242
    assert admin.calls == []  # the admin API is not even asked


async def test_admin_identity_is_the_fallback(db: AsyncSession) -> None:
    user = await seed_user(db)
    admin = FakeAdmin(999)

    assert await verified_github_id(db, user, admin=admin) == 999
    assert admin.calls == [user.supabase_user_id]


async def test_no_source_gives_none(db: AsyncSession) -> None:
    user = await seed_user(db)
    assert await verified_github_id(db, user, admin=None) is None
    assert await verified_github_id(db, user, admin=FakeAdmin(None)) is None


async def test_dead_or_foreign_connections_do_not_prove_identity(db: AsyncSession) -> None:
    user = await seed_user(db)
    dead = (ConnectionStatus.REVOKED, ConnectionStatus.ERROR, ConnectionStatus.PENDING)
    for offset, status in enumerate(dead):
        await connect(db, user, str(20 + offset), status=status)
    await connect(db, user, "12", provider=SourceType.GITLAB)
    assert await verified_github_id(db, user, admin=None) is None


async def test_unparseable_connection_ids_are_skipped(db: AsyncSession) -> None:
    user = await seed_user(db)
    for bad in (None, "abc", "0", "-5", "12.5", " ", "1e3", "٣"):
        row = await connect(db, user, bad)
        row.status = ConnectionStatus.CONNECTED
    assert await verified_github_id(db, user, admin=None) is None
    await connect(db, user, "77")
    assert await verified_github_id(db, user, admin=None) == 77


# ---------------------------------------------------------------- batch lookup


async def test_team_member_ids_map_to_live_members_only(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    owner, member = seeded.users[Role.OWNER], seeded.users[Role.MEMBER]
    outsider = await seed_user(db, "out")
    removed = await seed_user(db, "gone")
    row = Membership(team_id=seeded.team.id, user_id=removed.id, role=Role.MEMBER)
    db.add(row)
    await db.flush()
    row.deleted_at = utcnow()
    await connect(db, owner, "1")
    await connect(db, member, "2")
    await connect(db, outsider, "3")
    await connect(db, removed, "4")
    await connect(db, seeded.users[Role.OWNER], "9", status=ConnectionStatus.REVOKED)

    ids = await github_ids_for_team_members(db, seeded.team.id)

    assert ids == {1: owner.id, 2: member.id}


async def test_batch_query_has_no_n_plus_one(db: AsyncSession, engine: AsyncEngine) -> None:
    seeded = await seed_team(db)
    for i in range(8):
        user = await seed_user(db, f"m{i}")
        db.add(Membership(team_id=seeded.team.id, user_id=user.id, role=Role.MEMBER))
        await connect(db, user, str(100 + i))
    await db.commit()
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        ids = await github_ids_for_team_members(db, seeded.team.id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert len(ids) == 8
    assert len(statements) == 1


async def test_empty_team_gives_empty_mapping(db: AsyncSession) -> None:
    assert await github_ids_for_team_members(db, uuid.uuid4()) == {}


# ---------------------------------------------------------------- SupabaseAdmin


def admin() -> SupabaseAdmin:
    return SupabaseAdmin(BASE, "service-role-placeholder")


def identity_url(user_id: str) -> str:
    return f"{BASE}/auth/v1/admin/users/{user_id}"


async def test_admin_unconfigured_makes_no_request() -> None:
    with respx.mock(assert_all_called=False) as router:
        result = await SupabaseAdmin(None, None).github_identity("abc-123")
    assert result is None
    assert len(router.calls) == 0


async def test_admin_reads_the_github_identity_id() -> None:
    body = {
        "identities": [
            {"provider": "email", "id": "u-1"},
            {"provider": "github", "id": "314159", "identity_data": {"sub": "1"}},
        ]
    }
    with respx.mock(assert_all_called=False) as router:
        route = router.get(identity_url("abc-123")).mock(
            return_value=httpx.Response(200, json=body)
        )
        assert await admin().github_identity("abc-123") == 314159
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer service-role-placeholder"


async def test_admin_failures_give_none_and_never_raise() -> None:
    cases: list[Any] = [
        httpx.Response(200, json={"identities": [{"provider": "email", "id": "1"}]}),
        httpx.Response(200, json={"identities": [{"provider": "github", "id": "abc"}]}),
        httpx.Response(200, json={"identities": [{"provider": "github", "id": "-3"}]}),
        httpx.Response(200, json={"identities": "nope"}),
        httpx.Response(200, json=["x"]),
        httpx.Response(200, content=b"not json"),
        httpx.Response(404, json={}),
        httpx.Response(500, json={}),
        httpx.ConnectError("down"),
    ]
    for case in cases:
        with respx.mock(assert_all_called=False) as router:
            router.get(identity_url("abc-123")).mock(
                side_effect=case if isinstance(case, Exception) else None,
                return_value=None if isinstance(case, Exception) else case,
            )
            assert await admin().github_identity("abc-123") is None


async def test_admin_refuses_path_shaped_user_ids() -> None:
    with respx.mock(assert_all_called=False) as router:
        for bad in ("../users", "a/b", "", "a?b", "a b"):
            assert await admin().github_identity(bad) is None
    assert len(router.calls) == 0
