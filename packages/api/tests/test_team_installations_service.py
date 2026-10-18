"""Team-installation core service (SOLUSDEV-216 S216-T3, ADR-039)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fixtures.team_installation_seed import (
    seed_installation,
    seed_installation_source,
    seed_plain_source,
    seed_team,
)
from solus_api.connectors import github_app
from solus_api.connectors.github_app import InstallationInfo
from solus_api.core.errors import APIError
from solus_api.models import (
    Activity,
    DataEvent,
    InstallationStatus,
    Role,
    SourceStatus,
    TeamKind,
    utcnow,
)
from solus_api.services import team_installations as svc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _activities(db: AsyncSession, team_id: Any) -> list[Activity]:
    return list((await db.scalars(select(Activity).where(Activity.team_id == team_id))).all())


# ---------------------------------------------------------------- lookups


async def test_live_lookup_returns_installation_of_collaborative_team(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    assert await svc.get_live_installation(db, seeded.team.id) is inst


async def test_live_lookup_is_none_for_personal_team(db: AsyncSession) -> None:
    seeded = await seed_team(db, kind=TeamKind.PERSONAL)
    await seed_installation(db, seeded)
    assert await svc.get_live_installation(db, seeded.team.id) is None


async def test_live_lookup_is_none_for_soft_deleted_installation_or_team(db: AsyncSession) -> None:
    gone = await seed_team(db)
    (await seed_installation(db, gone)).deleted_at = utcnow()
    dead_team = await seed_team(db)
    await seed_installation(db, dead_team)
    dead_team.team.deleted_at = utcnow()
    await db.flush()
    assert await svc.get_live_installation(db, gone.team.id) is None
    assert await svc.get_live_installation(db, dead_team.team.id) is None


async def test_live_lookup_is_scoped_to_the_team(db: AsyncSession) -> None:
    a, b = await seed_team(db), await seed_team(db)
    inst_a = await seed_installation(db, a)
    assert await svc.get_live_installation(db, b.team.id) is None
    assert await svc.get_live_installation(db, a.team.id) is inst_a


async def test_require_active_raises_missing(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    with pytest.raises(APIError) as exc:
        await svc.require_active_installation(db, seeded.team.id)
    assert (exc.value.status_code, exc.value.code) == (409, "installation_missing")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (InstallationStatus.SUSPENDED, "installation_suspended"),
        (InstallationStatus.REVOKED, "installation_revoked"),
    ],
)
async def test_require_active_raises_for_inactive_status(
    db: AsyncSession, status: InstallationStatus, code: str
) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded, status=status)
    with pytest.raises(APIError) as exc:
        await svc.require_active_installation(db, seeded.team.id)
    assert (exc.value.status_code, exc.value.code) == (409, code)


async def test_require_active_returns_active(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    assert await svc.require_active_installation(db, seeded.team.id) is inst


async def test_find_by_external_id_routes_live_rows_only(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, external_id=111)
    assert await svc.find_by_external_id(db, 111) is inst
    assert await svc.find_by_external_id(db, 999) is None
    inst.status = InstallationStatus.SUSPENDED  # suspended still routes (unsuspend arrives here)
    await db.flush()
    assert await svc.find_by_external_id(db, 111) is inst


async def test_find_by_external_id_ignores_revoked_deleted_and_dead_team(db: AsyncSession) -> None:
    revoked = await seed_team(db)
    await seed_installation(db, revoked, external_id=201, status=InstallationStatus.REVOKED)
    soft = await seed_team(db)
    (await seed_installation(db, soft, external_id=202)).deleted_at = utcnow()
    dead = await seed_team(db)
    await seed_installation(db, dead, external_id=203)
    dead.team.deleted_at = utcnow()
    personal = await seed_team(db, kind=TeamKind.PERSONAL)
    await seed_installation(db, personal, external_id=204)
    await db.flush()
    for external_id in (201, 202, 203, 204):
        assert await svc.find_by_external_id(db, external_id) is None


# ---------------------------------------------------------------- revoke


async def test_revoke_disconnects_only_this_installations_sources(db: AsyncSession) -> None:
    mine, other = await seed_team(db), await seed_team(db)
    inst = await seed_installation(db, mine)
    other_inst = await seed_installation(db, other)
    connected = await seed_installation_source(db, mine, repo="acme/a")
    errored = await seed_installation_source(
        db, mine, repo="acme/b", status=SourceStatus.ERROR, last_error={"code": "x", "message": "m"}
    )
    already = await seed_installation_source(
        db, mine, repo="acme/c", status=SourceStatus.DISCONNECTED
    )
    foreign = await seed_installation_source(db, other, repo="acme/a")
    own = await seed_plain_source(db, mine, created_by=mine.users[Role.OWNER])

    count = await svc.revoke_installation(db, inst, actor=None)

    assert count == 2
    for source in (connected, errored):
        assert source.status is SourceStatus.DISCONNECTED
        assert source.secret_ref is None
        assert source.installation_id == inst.id  # kept for the audit
        assert source.last_error is not None
        assert source.last_error["code"] == "installation_unlinked"
        assert source.last_error["message"]
    assert already.status is SourceStatus.DISCONNECTED
    assert already.last_error is None
    assert foreign.status is SourceStatus.CONNECTED
    assert foreign.secret_ref is not None
    assert other_inst.deleted_at is None
    assert own.status is SourceStatus.CONNECTED
    assert own.secret_ref is not None


async def test_revoke_marks_row_revoked_and_soft_deleted(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, external_id=301)
    await svc.revoke_installation(db, inst, actor=None, reason_code="installation_deleted")
    assert inst.status is InstallationStatus.REVOKED
    assert inst.revoked_at is not None
    assert inst.deleted_at is not None
    assert await svc.get_live_installation(db, seeded.team.id) is None
    assert await svc.find_by_external_id(db, 301) is None


async def test_revoke_with_custom_reason_code(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    source = await seed_installation_source(db, seeded)
    await svc.revoke_installation(db, inst, actor=None, reason_code="installation_deleted")
    assert source.last_error is not None
    assert source.last_error["code"] == "installation_deleted"


async def test_revoke_with_system_actor_records_null_actor_and_no_event(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    await svc.revoke_installation(db, inst, actor=None)
    await db.flush()
    rows = [a for a in await _activities(db, seeded.team.id) if a.type == "github_org.unlinked"]
    assert len(rows) == 1
    assert rows[0].actor_id is None
    assert rows[0].payload["disabled_sources"] == 0
    assert (await db.scalars(select(DataEvent))).all() == []


async def test_revoke_with_user_actor_emits_event_when_consented(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    actor = seeded.users[Role.OWNER]
    actor.data_collection_consent = True
    await svc.revoke_installation(db, inst, actor=actor)
    await db.flush()
    rows = [a for a in await _activities(db, seeded.team.id) if a.type == "github_org.unlinked"]
    assert [a.actor_id for a in rows] == [actor.id]
    events = (await db.scalars(select(DataEvent))).all()
    assert [e.event_type for e in events] == ["github_org.unlinked"]
    assert events[0].team_id == seeded.team.id


async def test_revoke_invalidates_token_cache(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    dropped: list[int] = []
    monkeypatch.setattr(svc, "invalidate_installation_token", dropped.append)
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, external_id=555)
    await svc.revoke_installation(db, inst, actor=None)
    assert dropped == [555]


class _SpyCache:
    def __init__(self) -> None:
        self.invalidated: list[str] = []

    async def invalidate(self, key: str) -> None:
        self.invalidated.append(key)


async def test_revoke_invalidates_repo_and_roster_caches(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, external_id=556)
    spy = _SpyCache()
    await svc.revoke_installation(db, inst, actor=None, cache=spy)  # type: ignore[arg-type]
    assert sorted(spy.invalidated) == sorted([svc.repos_cache_key(556), svc.roster_cache_key(556)])


async def test_revoke_does_not_commit(db: AsyncSession, engine: Any) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession as Fresh

    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    await db.commit()
    await svc.revoke_installation(db, inst, actor=None)
    async with Fresh(engine) as other:
        from solus_api.models import TeamInstallation

        row = await other.get(TeamInstallation, inst.id)
        assert row is not None
        assert row.deleted_at is None
    await db.rollback()


# ---------------------------------------------------------------- repos / suspend


async def test_disable_sources_for_repos_is_case_insensitive_and_targeted(
    db: AsyncSession,
) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded)
    hit = await seed_installation_source(db, seeded, repo="Acme/Robot")
    miss = await seed_installation_source(db, seeded, repo="acme/other")
    other = await seed_team(db)
    await seed_installation(db, other)
    foreign = await seed_installation_source(db, other, repo="acme/robot")
    assert seeded.installation is not None

    count = await svc.disable_sources_for_repos(
        db, seeded.installation, {"acme/ROBOT"}, "repo_access_removed"
    )

    assert count == 1
    assert hit.status is SourceStatus.ERROR
    assert hit.last_error is not None
    assert hit.last_error["code"] == "repo_access_removed"
    assert miss.status is SourceStatus.CONNECTED
    assert foreign.status is SourceStatus.CONNECTED


async def test_disable_sources_for_repos_empty_set_is_noop(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    source = await seed_installation_source(db, seeded)
    assert await svc.disable_sources_for_repos(db, inst, set(), "repo_deleted") == 0
    assert source.status is SourceStatus.CONNECTED


async def test_suspend_unsuspend_round_trip_restores_only_suspended_sources(
    db: AsyncSession,
) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    ok = await seed_installation_source(db, seeded, repo="acme/ok")
    broken = await seed_installation_source(
        db,
        seeded,
        repo="acme/broken",
        status=SourceStatus.ERROR,
        last_error={"code": "repo_deleted", "message": "gone"},
    )
    when = datetime(2026, 10, 1, tzinfo=UTC)

    await svc.mark_suspended(db, inst, when)
    assert inst.status is InstallationStatus.SUSPENDED
    assert inst.suspended_at == when
    assert ok.status is SourceStatus.ERROR
    assert ok.last_error is not None
    assert ok.last_error["code"] == "installation_suspended"
    assert broken.last_error is not None
    assert broken.last_error["code"] == "repo_deleted"  # untouched

    await svc.mark_unsuspended(db, inst)
    assert inst.status is InstallationStatus.ACTIVE
    assert inst.suspended_at is None
    assert ok.status is SourceStatus.CONNECTED
    assert ok.last_error is None
    assert broken.status is SourceStatus.ERROR
    assert broken.last_error is not None
    assert broken.last_error["code"] == "repo_deleted"


async def test_suspend_drops_cached_token(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    dropped: list[int] = []
    monkeypatch.setattr(svc, "invalidate_installation_token", dropped.append)
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, external_id=777)
    await svc.mark_suspended(db, inst, utcnow())
    assert dropped == [777]


def _info(**overrides: Any) -> InstallationInfo:
    base: dict[str, Any] = {
        "installation_id": 1,
        "account_login": "renamed",
        "account_id": 42,
        "account_type": "User",
        "account_avatar_url": "https://avatars.example/a.png",
        "repository_selection": "selected",
        "suspended_at": None,
    }
    return InstallationInfo(**{**base, **overrides})


async def test_refresh_updates_fields_and_never_changes_team(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    team_id = inst.team_id
    await svc.refresh_installation_fields(db, inst, _info())
    assert inst.team_id == team_id
    assert (inst.account_login, inst.account_type) == ("renamed", "User")
    assert inst.account_external_id == 42
    assert inst.repository_selection == "selected"
    assert inst.account_avatar_url == "https://avatars.example/a.png"


async def test_refresh_follows_github_suspension_state(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    source = await seed_installation_source(db, seeded)
    when = datetime(2026, 10, 2, tzinfo=UTC)
    await svc.refresh_installation_fields(db, inst, _info(suspended_at=when))
    assert inst.status is InstallationStatus.SUSPENDED
    assert source.status is SourceStatus.ERROR
    await svc.refresh_installation_fields(db, inst, _info())
    assert inst.status is InstallationStatus.ACTIVE
    assert source.status is SourceStatus.CONNECTED


async def test_refresh_does_not_revive_a_revoked_row(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, status=InstallationStatus.REVOKED)
    await svc.refresh_installation_fields(db, inst, _info())
    assert inst.status is InstallationStatus.REVOKED
    assert inst.account_login == "renamed"


# ---------------------------------------------------------------- caches / counts


def test_cache_keys_are_installation_scoped() -> None:
    assert svc.repos_cache_key(5) != svc.repos_cache_key(6)
    assert svc.repos_cache_key(5) != svc.roster_cache_key(5)
    for key in (svc.repos_cache_key(5), svc.roster_cache_key(5)):
        assert "installation%3A5" in key
        assert "team" not in key


async def test_invalidate_caches_flags_and_none_cache(db: AsyncSession) -> None:
    await svc.invalidate_installation_caches(9, None)  # no cache: no-op
    spy = _SpyCache()
    await svc.invalidate_installation_caches(9, spy, roster=False)  # type: ignore[arg-type]
    assert spy.invalidated == [svc.repos_cache_key(9)]


async def test_count_bound_sources_excludes_disconnected_and_other_installations(
    db: AsyncSession,
) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    await seed_installation_source(db, seeded, repo="a/a")
    await seed_installation_source(db, seeded, repo="a/b", status=SourceStatus.ERROR)
    await seed_installation_source(db, seeded, repo="a/c", status=SourceStatus.DISCONNECTED)
    other = await seed_team(db)
    await seed_installation(db, other)
    await seed_installation_source(db, other, repo="a/a")
    assert await svc.count_bound_sources(db, inst) == 2
    assert github_app.installation_secret_ref(inst.id)


# ---------------------------------------------------------------- repo-name normalisation (B14)


def test_normalise_repo_is_case_insensitive_and_idempotent() -> None:
    assert svc.normalise_repo("Acme/Robot") == svc.normalise_repo("ACME/robot") == "acme/robot"
    assert svc.normalise_repo(svc.normalise_repo("Acme/Robot")) == "acme/robot"
    # casefold, not lower: the two forms of the German sharp s compare equal
    assert svc.normalise_repo("acme/Straße") == svc.normalise_repo("ACME/STRASSE")


async def test_disable_sources_matches_with_the_shared_normaliser(db: AsyncSession) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    source = await seed_installation_source(db, seeded, repo="Acme/Straße")

    count = await svc.disable_sources_for_repos(db, inst, {"ACME/STRASSE"}, "repo_deleted")

    assert count == 1 and source.status is SourceStatus.ERROR
