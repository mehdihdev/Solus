"""Deleting a team removes its GitHub installation (SOLUSDEV-216 S216-T3, ADR-039)."""

from __future__ import annotations

import pytest
from fixtures.team_installation_seed import (
    seed_installation,
    seed_installation_source,
    seed_team,
)
from solus_api.models import Project, Source, TeamInstallation
from solus_api.services import account_deletion
from solus_api.services import team_installations as svc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def test_team_deletion_removes_installation_and_frees_external_id(
    db: AsyncSession,
) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, external_id=4242)
    await seed_installation_source(db, seeded)
    inst_id, project_id = inst.id, seeded.project.id
    await db.commit()

    await account_deletion.delete_team_cascade(db, seeded.team.id)
    await db.commit()
    db.expunge_all()

    assert await db.get(TeamInstallation, inst_id) is None
    assert await svc.find_by_external_id(db, 4242) is None
    assert await db.get(Project, project_id) is None
    assert (await db.scalars(select(Source).where(Source.project_id == project_id))).all() == []

    other = await seed_team(db)
    relinked = await seed_installation(db, other, external_id=4242)  # unique constraint freed
    await db.commit()
    assert await svc.find_by_external_id(db, 4242) is relinked


async def test_team_deletion_leaves_other_teams_installation(db: AsyncSession) -> None:
    doomed, keeper = await seed_team(db), await seed_team(db)
    await seed_installation(db, doomed)
    kept = await seed_installation(db, keeper)
    kept_source = await seed_installation_source(db, keeper)
    kept_id, source_id = kept.id, kept_source.id
    await db.commit()
    await account_deletion.delete_team_cascade(db, doomed.team.id)
    await db.commit()
    db.expunge_all()
    assert await db.get(TeamInstallation, kept_id) is not None
    assert await db.get(Source, source_id) is not None


async def test_team_deletion_drops_token_and_caches(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    dropped: list[int] = []
    monkeypatch.setattr(account_deletion, "invalidate_installation_token", dropped.append)

    class Spy:
        keys: list[str] = []
        durable_store = None

        async def invalidate(self, key: str) -> None:
            self.keys.append(key)

        async def invalidate_account(self, *args: object, **kwargs: object) -> int:
            return 0

    spy = Spy()
    seeded = await seed_team(db)
    await seed_installation(db, seeded, external_id=8888)
    await db.commit()
    await account_deletion.delete_team_cascade(
        db,
        seeded.team.id,
        cache=spy,  # type: ignore[arg-type]
    )
    assert dropped == [8888]
    assert set(spy.keys) == {svc.repos_cache_key(8888), svc.roster_cache_key(8888)}
