"""SOLUSDEV-216 S216-T4: GET /teams/{id}/github/installation (ADR-039, docs/api/github-orgs.md)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import bearer
from fixtures.team_installation_seed import (
    SeededTeam,
    seed_installation,
    seed_installation_source,
    seed_team,
    seed_user,
)
from httpx import AsyncClient
from solus_api.models import Membership, Role, SourceStatus, TeamKind, User, utcnow
from sqlalchemy.ext.asyncio import AsyncSession


def _headers(user: User) -> dict[str, str]:
    headers: dict[str, str] = bearer(user.supabase_user_id, user.email)
    return headers


async def _viewer(db: AsyncSession, seeded: SeededTeam) -> User:
    viewer = await seed_user(db, "viewer")
    db.add(Membership(team_id=seeded.team.id, user_id=viewer.id, role=Role.VIEWER))
    await db.flush()
    return viewer


def _url(seeded: SeededTeam) -> str:
    return f"/api/v1/teams/{seeded.team.id}/github/installation"


async def test_member_reads_installation_with_linked_by_and_zero_sources(
    client: AsyncClient, db: AsyncSession
) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded, login="acme")
    await db.commit()

    resp = await client.get(_url(seeded), headers=_headers(seeded.users[Role.MEMBER]))

    assert resp.status_code == 200, resp.text
    inst = resp.json()["data"]["installation"]
    assert inst["account_login"] == "acme"
    assert inst["provider"] == "github"
    assert inst["status"] == "active"
    assert inst["bound_source_count"] == 0
    assert inst["linked_by"]["user_id"] == str(seeded.users[Role.OWNER].id)
    assert inst["html_url"] == "https://github.com/acme"
    assert inst["manage_url"].startswith("https://github.com/organizations/acme/settings/")


async def test_viewer_can_read(client: AsyncClient, db: AsyncSession) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded)
    viewer = await _viewer(db, seeded)
    await db.commit()

    resp = await client.get(_url(seeded), headers=_headers(viewer))

    assert resp.status_code == 200
    assert resp.json()["data"]["installation"] is not None


async def test_no_installation_is_null(client: AsyncClient, db: AsyncSession) -> None:
    seeded = await seed_team(db)
    await db.commit()
    resp = await client.get(_url(seeded), headers=_headers(seeded.users[Role.MEMBER]))
    assert resp.status_code == 200
    assert resp.json()["data"] == {"installation": None}


async def test_personal_team_answers_null_not_409(client: AsyncClient, db: AsyncSession) -> None:
    seeded = await seed_team(db, kind=TeamKind.PERSONAL)
    await db.commit()
    resp = await client.get(_url(seeded), headers=_headers(seeded.users[Role.OWNER]))
    assert resp.status_code == 200
    assert resp.json()["data"] == {"installation": None}


async def test_cross_team_read_is_404_and_leaks_nothing(
    client: AsyncClient, db: AsyncSession
) -> None:
    team_a = await seed_team(db, name="A")
    team_b = await seed_team(db, name="B")
    await seed_installation(db, team_b, login="secret-org")
    await db.commit()

    resp = await client.get(_url(team_b), headers=_headers(team_a.users[Role.OWNER]))

    assert resp.status_code == 404
    assert "secret-org" not in resp.text


async def test_unauthenticated_is_401(client: AsyncClient, db: AsyncSession) -> None:
    seeded = await seed_team(db)
    await db.commit()
    assert (await client.get(_url(seeded))).status_code == 401


async def test_counts_only_live_bound_sources(client: AsyncClient, db: AsyncSession) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded)
    await seed_installation_source(db, seeded, repo="acme/a")
    await seed_installation_source(db, seeded, repo="acme/b", status=SourceStatus.ERROR)
    await seed_installation_source(db, seeded, repo="acme/c", status=SourceStatus.DISCONNECTED)
    await db.commit()

    resp = await client.get(_url(seeded), headers=_headers(seeded.users[Role.MEMBER]))

    assert resp.json()["data"]["installation"]["bound_source_count"] == 2


async def test_body_carries_no_token_key_or_numeric_installation_id_field(
    client: AsyncClient, db: AsyncSession
) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded, external_id=424242)
    await db.commit()

    resp = await client.get(_url(seeded), headers=_headers(seeded.users[Role.MEMBER]))

    body: dict[str, Any] = resp.json()["data"]["installation"]
    assert set(body) == {
        "id",
        "provider",
        "account_login",
        "account_type",
        "account_avatar_url",
        "repository_selection",
        "status",
        "linked_by",
        "linked_at",
        "html_url",
        "manage_url",
        "bound_source_count",
    }
    assert body["id"] == str(inst.id)
    lowered = json.dumps(body).lower()
    assert "token" not in lowered and "secret" not in lowered and "jwt" not in lowered


async def test_linker_leaving_the_team_keeps_installation_and_sources(
    client: AsyncClient, db: AsyncSession
) -> None:
    seeded = await seed_team(db)
    linker = await seed_user(db, "linker")
    membership = Membership(team_id=seeded.team.id, user_id=linker.id, role=Role.ADMIN)
    db.add(membership)
    await seed_installation(db, seeded, linked_by=linker)
    await seed_installation_source(db, seeded)
    membership.deleted_at = utcnow()
    await db.commit()

    resp = await client.get(_url(seeded), headers=_headers(seeded.users[Role.MEMBER]))

    data = resp.json()["data"]["installation"]
    assert resp.status_code == 200
    assert data["linked_by"]["user_id"] == str(linker.id)
    assert data["bound_source_count"] == 1
    assert data["status"] == "active"


@pytest.mark.parametrize("who", ["owner", "member"])
async def test_linked_by_is_null_when_linker_user_row_is_gone(
    client: AsyncClient, db: AsyncSession, who: str
) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    inst.linked_by = None
    await db.commit()
    role = Role.OWNER if who == "owner" else Role.MEMBER

    resp = await client.get(_url(seeded), headers=_headers(seeded.users[role]))

    assert resp.json()["data"]["installation"]["linked_by"] is None
