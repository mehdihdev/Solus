"""Account deletion edges (SOLUSDEV-82 / SOLUS-FND-02, AC #3 & #4).

Covers credit forfeiture with ledger preservation (ADR-024), Supabase session
revocation, remaining-member notification, the transfer-then-delete happy path,
and durable deletion (a deleted identity cannot silently re-provision).
"""

import uuid

from conftest import ALICE, BOB, add_member, bearer, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import CreditBalance, CreditLedger, CreditTxnType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class FakeSupabaseAdmin:
    """Records the auth users asked to be deleted; stands in for the real client."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    async def delete_user(self, supabase_user_id: str) -> bool:
        self.deleted.append(supabase_user_id)
        return True


async def test_delete_forfeits_credits_and_preserves_ledger(
    client: AsyncClient, app: FastAPI, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    before = await me(client, alice_headers)
    user_id = uuid.UUID(before["id"])
    # Provisioning already granted trial credits (SOLUSDEV-83); pin the cached
    # balance to a known value so the forfeiture amount is deterministic.
    balance = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user_id))
    if balance is None:
        db.add(CreditBalance(user_id=user_id, balance=500))
    else:
        balance.balance = 500
    seeded = CreditLedger(
        user_id=user_id,
        amount=500,
        type=CreditTxnType.TRIAL_GRANT,
        balance_after=500,
    )
    db.add(seeded)
    await db.commit()
    seeded_id = seeded.id

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204, resp.text

    # The app committed via its own session; drop this session's cached copies so
    # the assertions re-read the post-deletion database state.
    db.expire_all()

    # The cached balance is gone; the append-only ledger row survives (user_id
    # detached to NULL) alongside a new forfeiture ADJUSTMENT entry.
    assert (await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user_id))) is None
    preserved = await db.get(CreditLedger, seeded_id)
    assert preserved is not None
    assert preserved.user_id is None
    forfeiture = (
        await db.scalars(select(CreditLedger).where(CreditLedger.type == CreditTxnType.ADJUSTMENT))
    ).all()
    assert len(forfeiture) == 1
    assert forfeiture[0].amount == -500
    assert forfeiture[0].balance_after == 0
    assert forfeiture[0].attrs.get("reason") == "account_deleted"


async def test_delete_revokes_supabase_session(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    fake = FakeSupabaseAdmin()
    app.state.supabase_admin = fake
    before = await me(client, alice_headers)

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204, resp.text
    assert before["email"] == ALICE["email"]
    assert fake.deleted == [ALICE["sub"]]


async def test_delete_notifies_remaining_members(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    # Bob (a member, not the sole owner) deletes his account and leaves the team.
    resp = await client.delete("/api/v1/users/me", headers=bob_headers)
    assert resp.status_code == 204, resp.text

    notes = await client.get("/api/v1/users/me/notifications", headers=alice_headers)
    types = [n["type"] for n in notes.json()["data"]]
    assert "member.left" in types


async def test_delete_after_ownership_transfer_succeeds(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team = await create_team(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    # Transfer ownership to Bob, then Alice is no longer the sole owner.
    promote = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}",
        json={"role": "owner"},
        headers=alice_headers,
    )
    assert promote.status_code == 200, promote.text

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204, resp.text


async def test_deleted_account_cannot_reprovision(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204

    # A still-valid token for the deleted identity must not silently recreate the
    # account — deletion is durable.
    after = await client.get("/api/v1/users/me", headers=alice_headers)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "account_deleted"


async def test_delete_unverified_still_gated(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    unverified = bearer(ALICE["sub"], ALICE["email"], email_verified=False)
    resp = await client.delete("/api/v1/users/me", headers=unverified)
    assert resp.status_code == 403


async def test_sole_owner_block_ignores_soft_deleted_members(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    # Alice owns a shared team; Bob joins then is removed (soft-deleted membership).
    team = await create_team(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    removed = await client.delete(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}", headers=alice_headers
    )
    assert removed.status_code == 204, removed.text

    # Alice is now the only LIVE member — the soft-deleted row must not wedge the
    # sole-owner guard (M1). Deletion succeeds.
    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204, resp.text


async def test_deleting_member_leaves_team_and_others_intact(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    # Cross-tenant isolation: a member deleting their account must not touch the
    # team, its projects, or other members' data.
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.delete("/api/v1/users/me", headers=bob_headers)
    assert resp.status_code == 204, resp.text

    detail = await client.get(f"/api/v1/teams/{team['id']}", headers=alice_headers)
    assert detail.status_code == 200
    members = await client.get(f"/api/v1/teams/{team['id']}/members", headers=alice_headers)
    emails = [m["email"] for m in members.json()["data"]]
    assert BOB["email"] not in emails
    assert ALICE["email"] in emails
    projects = await client.get(f"/api/v1/teams/{team['id']}/projects", headers=alice_headers)
    assert any(p["id"] == project["id"] for p in projects.json()["data"])
