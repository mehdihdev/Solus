"""Cross-team isolation and role floors for the §6–§8 project routes
(SOLUSDEV-235 EXT-09, docs/api/extensions.md §14, CLAUDE.md §7).

Team A's member cannot read or mutate team B's installs, storage or layout —
`404` (from `ProjectCtx`), never `403`. A `viewer` and an ADR-025 share-only
user may GET installs, storage and layout but get `403` on every write."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from conftest import BOB, add_member, create_team, me
from fastapi import FastAPI
from fixtures.extensions.routes import (
    FULL_GRANTS,
    ext_url,
    install,
    installs_app,
    manifest_with,
    project_for,
    seed_extension,
)
from httpx import AsyncClient, Response
from solus_api.core.config import Settings
from solus_api.models import ExtensionInstall, ExtensionStorage, ProjectMembership, WidgetLayout
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

STORAGE_MANIFEST = {"1.2.0": manifest_with(scopes=["storage.own"])}
STORAGE_GRANTS = {"scopes": ["storage.own"], "network": []}
LAYOUT = {"layout": [{"ref": "ext:bom", "size": "wide"}]}


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    return installs_app(settings, engine)


def layout_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/widget-layout"


async def _alice_project_with_install_and_storage(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> tuple[str, str]:
    await seed_extension(db, versions=STORAGE_MANIFEST)
    team_id, project_id = await project_for(client, alice_headers)
    assert (
        await install(client, alice_headers, project_id, grants=STORAGE_GRANTS)
    ).status_code == 201
    put = await client.put(ext_url(project_id, "bom") + "/storage/k", json=1, headers=alice_headers)
    assert put.status_code == 201
    saved = await client.put(layout_url(project_id), json=LAYOUT, headers=alice_headers)
    assert saved.status_code == 200
    return team_id, project_id


Attempt = Callable[[AsyncClient, str, dict[str, str]], Awaitable[Response]]

WRITES: dict[str, Attempt] = {
    "install": lambda c, p, h: c.put(ext_url(p, "bom"), json={"grants": STORAGE_GRANTS}, headers=h),
    "patch": lambda c, p, h: c.patch(ext_url(p, "bom"), json={"enabled": False}, headers=h),
    "uninstall": lambda c, p, h: c.delete(ext_url(p, "bom"), headers=h),
    "storage-put": lambda c, p, h: c.put(ext_url(p, "bom") + "/storage/k", json=2, headers=h),
    "storage-delete": lambda c, p, h: c.delete(ext_url(p, "bom") + "/storage/k", headers=h),
    "layout-put": lambda c, p, h: c.put(layout_url(p), json=LAYOUT, headers=h),
}
READS: dict[str, Attempt] = {
    "list": lambda c, p, h: c.get(ext_url(p), headers=h),
    "storage-get": lambda c, p, h: c.get(ext_url(p, "bom") + "/storage/k", headers=h),
    "layout-get": lambda c, p, h: c.get(layout_url(p), headers=h),
}


# ------------------------------------------------------------ foreign team
@pytest.mark.parametrize("attempt", list(WRITES) + list(READS))
async def test_a_member_of_another_team_gets_404_on_every_route(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    attempt: str,
) -> None:
    _, project_id = await _alice_project_with_install_and_storage(client, alice_headers, db)
    await create_team(client, bob_headers)  # Bob is an owner — of HIS team

    resp = await {**WRITES, **READS}[attempt](client, project_id, bob_headers)

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "not_found"


async def test_a_foreign_write_attempt_mutates_nothing(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    _, project_id = await _alice_project_with_install_and_storage(client, alice_headers, db)
    await create_team(client, bob_headers)

    for attempt in WRITES.values():
        await attempt(client, project_id, bob_headers)

    installs = (await db.scalars(select(ExtensionInstall))).all()
    storage = (await db.scalars(select(ExtensionStorage))).all()
    layouts = (await db.scalars(select(WidgetLayout))).all()
    assert len(installs) == 1 and installs[0].enabled is True
    assert len(storage) == 1 and storage[0].value == 1
    assert len(layouts) == 1 and layouts[0].layout == LAYOUT["layout"]


# ----------------------------------------------------- viewer / share-only
async def _bob_as_viewer(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str], team_id: str
) -> None:
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="viewer")


async def _bob_share_only(
    client: AsyncClient, bob_headers: dict[str, str], db: AsyncSession, project_id: str
) -> None:
    bob = await me(client, bob_headers)
    db.add(ProjectMembership(project_id=uuid.UUID(project_id), user_id=uuid.UUID(bob["id"])))
    await db.commit()


@pytest.mark.parametrize("who", ["viewer", "share-only"])
@pytest.mark.parametrize("attempt", list(WRITES))
async def test_viewer_and_share_only_users_get_403_on_writes(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    who: str,
    attempt: str,
) -> None:
    team_id, project_id = await _alice_project_with_install_and_storage(client, alice_headers, db)
    if who == "viewer":
        await _bob_as_viewer(client, alice_headers, bob_headers, team_id)
    else:
        await _bob_share_only(client, bob_headers, db, project_id)

    resp = await WRITES[attempt](client, project_id, bob_headers)

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("who", ["viewer", "share-only"])
@pytest.mark.parametrize("attempt", list(READS))
async def test_viewer_and_share_only_users_can_read(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    who: str,
    attempt: str,
) -> None:
    team_id, project_id = await _alice_project_with_install_and_storage(client, alice_headers, db)
    if who == "viewer":
        await _bob_as_viewer(client, alice_headers, bob_headers, team_id)
    else:
        await _bob_share_only(client, bob_headers, db, project_id)

    resp = await READS[attempt](client, project_id, bob_headers)

    assert resp.status_code == 200, resp.text


async def test_member_role_is_enough_to_write(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team_id, project_id = await _alice_project_with_install_and_storage(client, alice_headers, db)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="member")

    resp = await client.patch(
        ext_url(project_id, "bom"), json={"enabled": False}, headers=bob_headers
    )

    assert resp.status_code == 200, resp.text


async def test_unauthenticated_requests_are_401(client: AsyncClient) -> None:
    project_id = str(uuid.uuid4())
    for attempt in {**WRITES, **READS}.values():
        resp = await attempt(client, project_id, {})
        assert resp.status_code == 401


# -------------------------------------------- storage keys never collide
async def test_the_same_storage_key_in_two_projects_and_two_extensions_is_four_rows(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, slug="bom", versions=STORAGE_MANIFEST)
    await seed_extension(
        db,
        slug="scope",
        versions={"0.1.0": manifest_with("0.1.0", slug="scope", scopes=["storage.own"])},
    )
    team = await create_team(client, alice_headers)
    from conftest import create_project

    projects = [
        (await create_project(client, alice_headers, team["id"], name))["id"]
        for name in ("P1", "P2")
    ]
    for pid in projects:
        for slug in ("bom", "scope"):
            assert (
                await install(client, alice_headers, pid, slug=slug, grants=STORAGE_GRANTS)
            ).status_code == 201
            put = await client.put(
                ext_url(pid, slug) + "/storage/shared", json=f"{pid}:{slug}", headers=alice_headers
            )
            assert put.status_code == 201, put.text

    for pid in projects:
        for slug in ("bom", "scope"):
            got = await client.get(ext_url(pid, slug) + "/storage/shared", headers=alice_headers)
            assert got.json()["data"]["value"] == f"{pid}:{slug}"
    assert len((await db.scalars(select(ExtensionStorage))).all()) == 4


async def test_the_install_body_never_names_the_project_or_team(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Ids come only from the resolved context: a body carrying another
    project's id is an unknown field (422), never a redirect of the write."""
    await seed_extension(db)
    _, alice_project = await project_for(client, alice_headers)
    _, bob_project = await project_for(client, bob_headers)

    resp = await client.put(
        ext_url(bob_project, "bom"),
        json={"grants": FULL_GRANTS, "project_id": alice_project},
        headers=bob_headers,
    )

    assert resp.status_code == 422
    assert (await db.scalars(select(ExtensionInstall))).all() == []
