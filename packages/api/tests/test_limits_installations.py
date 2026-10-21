"""Plan accounting for team installations (SOLUSDEV-216 S216-T3, ADR-039 section 8)."""

from __future__ import annotations

import pytest
from fixtures.team_installation_seed import (
    SeededTeam,
    seed_installation,
    seed_installation_source,
    seed_plain_source,
    seed_team,
)
from solus_api.core.errors import APIError
from solus_api.models import (
    InstallationStatus,
    Membership,
    Role,
    Subscription,
    User,
    utcnow,
)
from solus_api.services.limits import check_can_add_integration
from solus_api.services.team_installations import link_counts_for_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _set_cap(db: AsyncSession, user: User, cap: int | None) -> None:
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    assert sub is not None
    sub.limits = {"max_integrations": cap}
    await db.flush()


async def _blocked(db: AsyncSession, user: User) -> bool:
    try:
        await check_can_add_integration(db, user)
    except APIError as exc:
        assert exc.code == "plan_limit_reached"
        return True
    return False


async def test_installation_bound_sources_do_not_count_for_creator(db: AsyncSession) -> None:
    seeded: SeededTeam = await seed_team(db)
    creator = seeded.users[Role.MEMBER]
    await seed_installation(db, seeded, linked_by=seeded.users[Role.OWNER])
    for i in range(5):
        await seed_installation_source(db, seeded, repo=f"acme/r{i}", created_by=creator)
    await _set_cap(db, creator, 1)
    assert not await _blocked(db, creator)


async def test_adding_through_installation_is_free_at_zero_cap(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    creator = seeded.users[Role.MEMBER]
    await seed_installation(db, seeded)
    await seed_installation_source(db, seeded, created_by=creator)
    await _set_cap(db, creator, 0)
    # The bind path does not call the check; the creator holds no counted integration.
    assert await link_counts_for_user(db, creator.id) == 0
    assert await _blocked(db, creator)  # and a NEW own integration is still refused at 0


async def test_live_link_counts_one_against_the_linker(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    linker = seeded.users[Role.OWNER]
    await seed_installation(db, seeded, linked_by=linker)
    assert await link_counts_for_user(db, linker.id) == 1
    await _set_cap(db, linker, 1)
    assert await _blocked(db, linker)
    await _set_cap(db, linker, 2)
    assert not await _blocked(db, linker)


async def test_link_adds_to_the_users_own_sources(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    linker = seeded.users[Role.OWNER]
    await seed_installation(db, seeded, linked_by=linker)
    await seed_plain_source(db, seeded, created_by=linker)
    await _set_cap(db, linker, 2)
    assert await _blocked(db, linker)  # 1 source + 1 link
    await _set_cap(db, linker, 3)
    assert not await _blocked(db, linker)


@pytest.mark.parametrize("how", ["revoked", "soft_deleted"])
async def test_dead_installation_counts_zero(db: AsyncSession, how: str) -> None:
    seeded = await seed_team(db)
    linker = seeded.users[Role.OWNER]
    inst = await seed_installation(db, seeded, linked_by=linker)
    if how == "revoked":
        inst.status = InstallationStatus.REVOKED
    inst.deleted_at = utcnow()
    await db.flush()
    assert await link_counts_for_user(db, linker.id) == 0
    await _set_cap(db, linker, 1)
    assert not await _blocked(db, linker)


async def test_linker_who_left_the_team_counts_zero(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    linker = seeded.users[Role.MEMBER]
    await seed_installation(db, seeded, linked_by=linker)
    assert await link_counts_for_user(db, linker.id) == 1
    membership = await db.scalar(
        select(Membership).where(
            Membership.team_id == seeded.team.id, Membership.user_id == linker.id
        )
    )
    assert membership is not None
    membership.deleted_at = utcnow()
    await db.flush()
    assert await link_counts_for_user(db, linker.id) == 0


async def test_link_never_counts_for_other_users(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded, linked_by=seeded.users[Role.OWNER])
    assert await link_counts_for_user(db, seeded.users[Role.MEMBER].id) == 0


async def test_existing_integration_limit_is_unchanged(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    user = seeded.users[Role.OWNER]
    await _set_cap(db, user, 2)
    await seed_plain_source(db, seeded, created_by=user, name="a")
    assert not await _blocked(db, user)
    await seed_plain_source(db, seeded, created_by=user, name="b")
    assert await _blocked(db, user)


async def test_null_cap_is_unlimited(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    user = seeded.users[Role.OWNER]
    await seed_installation(db, seeded, linked_by=user)
    await _set_cap(db, user, None)
    assert not await _blocked(db, user)
