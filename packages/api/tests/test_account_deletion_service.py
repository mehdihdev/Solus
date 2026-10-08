"""AccountDeletionService (SOLUSDEV-313 T7): ownership transfers + parity of the cascade."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import pytest
from conftest import BOB, add_member, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import (
    DeletedAccount,
    Membership,
    Role,
    Team,
    TeamKind,
    User,
    utcnow,
)
from solus_api.services.account_deletion import (
    AccountDeletionError,
    AccountDeletionService,
    InvalidOwnershipTransfer,
    OwnershipTransferRequired,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _Admin:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_user(self, supabase_user_id: str) -> bool:
        self.deleted.append(supabase_user_id)
        return True


def _service(app: FastAPI, db: AsyncSession, admin: _Admin | None = None) -> AccountDeletionService:
    return AccountDeletionService(
        db,
        secret_store=app.state.secret_store,
        supabase_admin=admin or _Admin(),
        cache=app.state.integration_cache,
        gateway=None,
    )


async def _user(db: AsyncSession, name: str) -> User:
    uid = uuid.uuid4()
    user = User(id=uid, supabase_user_id=f"sb-{uid}", email=f"{name}-{uid}@example.com")
    db.add(user)
    await db.flush()
    return user


async def _team(db: AsyncSession, name: str, kind: TeamKind = TeamKind.COLLABORATIVE) -> Team:
    team = Team(name=name, kind=kind)
    db.add(team)
    await db.flush()
    return team


async def _join(
    db: AsyncSession, team: Team, user: User, role: Role, *, deleted: bool = False
) -> Membership:
    row = Membership(team_id=team.id, user_id=user.id, role=role)
    if deleted:
        row.deleted_at = utcnow()
    db.add(row)
    await db.flush()
    return row


async def _role(db: AsyncSession, team: Team, user: User) -> Role | None:
    row = await db.scalar(
        select(Membership)
        .where(Membership.team_id == team.id, Membership.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    return row.role if row else None


async def _world(db: AsyncSession) -> tuple[User, User, Team]:
    """An owner and a member on a collaborative team the owner solely owns."""
    owner, member = await _user(db, "owner"), await _user(db, "member")
    team = await _team(db, "T")
    await _join(db, team, owner, Role.OWNER)
    await _join(db, team, member, Role.MEMBER)
    await db.commit()
    return owner, member, team


async def _delete(
    svc: AccountDeletionService, user: User, transfers: Mapping[uuid.UUID, uuid.UUID] | None
) -> None:
    await svc.delete_account(user, ownership_transfers=transfers)


# ------------------------------------------------------------ happy path


async def test_valid_transfer_allows_deletion_and_recipient_becomes_owner(
    app: FastAPI, db: AsyncSession
) -> None:
    owner, member, team = await _world(db)
    admin = _Admin()
    owner_id, owner_sb = owner.id, owner.supabase_user_id

    await _delete(_service(app, db, admin), owner, {team.id: member.id})

    assert await db.get(User, owner_id, populate_existing=True) is None
    assert await _role(db, team, member) is Role.OWNER
    assert await db.get(Team, team.id, populate_existing=True) is not None  # the team survives
    assert admin.deleted == [owner_sb]


async def test_no_transfers_and_none_behave_identically(app: FastAPI, db: AsyncSession) -> None:
    owner, _member, team = await _world(db)
    cases: list[Mapping[uuid.UUID, uuid.UUID] | None] = [None, {}]
    for transfers in cases:
        with pytest.raises(OwnershipTransferRequired) as err:
            await _delete(_service(app, db), owner, transfers)
        assert err.value.team_ids == [team.id]
        assert err.value.code == "ownership_transfer_required"


async def test_partially_covering_transfers_still_block(app: FastAPI, db: AsyncSession) -> None:
    owner, member, team = await _world(db)
    other = await _team(db, "T2")
    await _join(db, other, owner, Role.OWNER)
    await _join(db, other, await _user(db, "x"), Role.MEMBER)
    await db.commit()

    with pytest.raises(OwnershipTransferRequired) as err:
        await _delete(_service(app, db), owner, {team.id: member.id})

    assert err.value.team_ids == [other.id]
    assert await _role(db, team, member) is Role.MEMBER  # nothing applied
    assert await db.get(User, owner.id, populate_existing=True) is not None


async def test_transfer_on_non_blocking_team_is_allowed(app: FastAPI, db: AsyncSession) -> None:
    owner, member, team = await _world(db)
    await _join(db, team, await _user(db, "co"), Role.OWNER)
    await db.commit()

    await _delete(_service(app, db), owner, {team.id: member.id})

    assert await _role(db, team, member) is Role.OWNER


async def test_already_owner_target_is_idempotent(app: FastAPI, db: AsyncSession) -> None:
    owner, member, team = await _world(db)
    co = await _user(db, "co")
    await _join(db, team, co, Role.OWNER)
    await db.commit()
    await _delete(_service(app, db), owner, {team.id: co.id})
    assert await _role(db, team, co) is Role.OWNER
    assert await _role(db, team, member) is Role.MEMBER


# ------------------------------------------------------------ invalid entries


async def _assert_invalid(
    app: FastAPI,
    db: AsyncSession,
    owner: User,
    transfers: Mapping[uuid.UUID, uuid.UUID],
    code: str,
    team_id: uuid.UUID,
) -> None:
    with pytest.raises(InvalidOwnershipTransfer) as err:
        await _delete(_service(app, db), owner, transfers)
    assert err.value.code == code
    assert err.value.team_id == team_id
    assert isinstance(err.value, AccountDeletionError)
    assert err.value.reason
    assert await db.get(User, owner.id, populate_existing=True) is not None
    assert await db.scalar(select(DeletedAccount)) is None


async def test_target_not_a_member(app: FastAPI, db: AsyncSession) -> None:
    owner, _member, team = await _world(db)
    stranger = await _user(db, "stranger")
    await db.commit()
    await _assert_invalid(
        app, db, owner, {team.id: stranger.id}, "transfer_target_not_member", team.id
    )
    assert await _role(db, team, stranger) is None


async def test_target_is_the_deleting_user(app: FastAPI, db: AsyncSession) -> None:
    owner, _member, team = await _world(db)
    await _assert_invalid(app, db, owner, {team.id: owner.id}, "transfer_target_is_self", team.id)


async def test_target_membership_soft_deleted(app: FastAPI, db: AsyncSession) -> None:
    owner, _member, team = await _world(db)
    gone = await _user(db, "gone")
    await _join(db, team, gone, Role.MEMBER, deleted=True)
    await db.commit()
    await _assert_invalid(app, db, owner, {team.id: gone.id}, "transfer_target_not_member", team.id)


async def test_target_user_does_not_exist(app: FastAPI, db: AsyncSession) -> None:
    owner, _member, team = await _world(db)
    await _assert_invalid(
        app, db, owner, {team.id: uuid.uuid4()}, "transfer_target_not_found", team.id
    )


async def test_nonexistent_team(app: FastAPI, db: AsyncSession) -> None:
    owner, member, _team_row = await _world(db)
    ghost = uuid.uuid4()
    await _assert_invalid(app, db, owner, {ghost: member.id}, "transfer_team_not_found", ghost)


async def test_foreign_team_is_not_touched(app: FastAPI, db: AsyncSession) -> None:
    owner, _member, _team_row = await _world(db)
    boss, victim = await _user(db, "boss"), await _user(db, "victim")
    foreign = await _team(db, "Foreign")
    await _join(db, foreign, boss, Role.OWNER)
    await _join(db, foreign, victim, Role.MEMBER)
    await db.commit()
    await _assert_invalid(app, db, owner, {foreign.id: victim.id}, "transfer_not_owner", foreign.id)
    assert await _role(db, foreign, victim) is Role.MEMBER
    assert await _role(db, foreign, boss) is Role.OWNER


async def test_user_is_only_admin_not_owner(app: FastAPI, db: AsyncSession) -> None:
    owner, _member, _t = await _world(db)
    peer = await _user(db, "peer")
    team = await _team(db, "A")
    await _join(db, team, owner, Role.ADMIN)
    await _join(db, team, peer, Role.MEMBER)
    await db.commit()
    await _assert_invalid(app, db, owner, {team.id: peer.id}, "transfer_not_owner", team.id)


async def test_owner_membership_soft_deleted_is_not_ownership(
    app: FastAPI, db: AsyncSession
) -> None:
    owner, member, _t = await _world(db)
    team = await _team(db, "Old")
    await _join(db, team, owner, Role.OWNER, deleted=True)
    await _join(db, team, member, Role.MEMBER)
    await db.commit()
    await _assert_invalid(app, db, owner, {team.id: member.id}, "transfer_not_owner", team.id)


async def test_personal_team_cannot_be_transferred(app: FastAPI, db: AsyncSession) -> None:
    owner, member, _t = await _world(db)
    personal = await _team(db, "Me", TeamKind.PERSONAL)
    await _join(db, personal, owner, Role.OWNER)
    await _join(db, personal, member, Role.MEMBER)
    await db.commit()
    await _assert_invalid(
        app, db, owner, {personal.id: member.id}, "transfer_personal_team", personal.id
    )
    assert await _role(db, personal, member) is Role.MEMBER


async def test_one_invalid_entry_applies_nothing(app: FastAPI, db: AsyncSession) -> None:
    owner, member, team = await _world(db)
    with pytest.raises(InvalidOwnershipTransfer):
        await _delete(_service(app, db), owner, {team.id: member.id, uuid.uuid4(): member.id})
    assert await _role(db, team, member) is Role.MEMBER
    assert await db.get(User, owner.id, populate_existing=True) is not None


async def test_a_valid_entry_cannot_smuggle_in_another_teams_transfer(
    app: FastAPI, db: AsyncSession
) -> None:
    """Scoped to the deleting user: another owner's team can never be targeted."""
    owner, member, team = await _world(db)
    other_team = await _team(db, "Other")
    await _join(db, other_team, await _user(db, "oo"), Role.OWNER)
    await _join(db, other_team, member, Role.MEMBER)
    await db.commit()
    with pytest.raises(InvalidOwnershipTransfer):
        await _delete(_service(app, db), owner, {team.id: member.id, other_team.id: member.id})
    assert await _role(db, other_team, member) is Role.MEMBER
    assert await _role(db, team, member) is Role.MEMBER


# ------------------------------------------------------------ router parity


async def test_self_delete_409_body_is_unchanged(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)

    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "ownership_transfer_required"
    assert error["message"] == "Transfer ownership of your teams before deleting your account"
    assert error["details"] == [{"team_id": team["id"]}]


async def test_self_delete_request_body_never_carries_transfers(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=alice_headers,
        json={"ownership_transfers": {team["id"]: bob["id"]}},
    )

    assert resp.status_code == 409  # the body is ignored


async def test_cascade_helpers_stay_importable_from_the_router_module() -> None:
    from solus_api.routers.users import delete_projects_cascade, delete_team_cascade

    assert callable(delete_team_cascade) and callable(delete_projects_cascade)
