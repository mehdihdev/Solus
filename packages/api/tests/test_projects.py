"""§2.3 Projects — CRUD under team, detail, cross-tenant isolation."""

from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient


async def test_create_and_list_projects(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"], "Rover MK2")
    assert project["name"] == "Rover MK2"
    assert project["team_id"] == team["id"]

    resp = await client.get(f"/api/v1/teams/{team['id']}/projects", headers=alice_headers)
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["data"]] == [project["id"]]


async def test_project_detail_includes_summaries(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])

    resp = await client.get(f"/api/v1/projects/{project['id']}", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Graph/sources land in Phases 2–3; the detail shape ships now with empty summaries.
    assert data["stats"] == {"entities": 0, "relations": 0}
    assert data["sources"] == []


async def test_update_project(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])

    resp = await client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"description": "Six-wheel autonomous rover"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["description"] == "Six-wheel autonomous rover"


async def test_delete_project_requires_admin_and_confirmation(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="member")

    no_confirm = await client.delete(f"/api/v1/projects/{project['id']}", headers=alice_headers)
    assert no_confirm.status_code == 400

    not_admin = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=bob_headers
    )
    assert not_admin.status_code == 403

    ok = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=alice_headers
    )
    assert ok.status_code == 204

    gone = await client.get(f"/api/v1/projects/{project['id']}", headers=alice_headers)
    assert gone.status_code == 404


async def test_viewer_cannot_create_project(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="viewer")

    resp = await client.post(
        f"/api/v1/teams/{team['id']}/projects", json={"name": "Nope"}, headers=bob_headers
    )
    assert resp.status_code == 403


async def test_cross_tenant_project_isolation(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)

    read = await client.get(f"/api/v1/projects/{project['id']}", headers=bob_headers)
    assert read.status_code == 404

    mutate = await client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "Stolen"}, headers=bob_headers
    )
    assert mutate.status_code == 404

    delete = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=bob_headers
    )
    assert delete.status_code == 404


async def test_project_create_notifies_other_members(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """FND-04/FND-05 seam: creating a project notifies the rest of the team,
    but not the actor themselves."""
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="member")

    project = await create_project(client, alice_headers, team["id"], "Notify Rover")

    bob_notes = (await client.get("/api/v1/users/me/notifications", headers=bob_headers)).json()[
        "data"
    ]
    created = [n for n in bob_notes if n["type"] == "project.created"]
    assert len(created) == 1
    assert created[0]["payload"]["project_id"] == project["id"]

    alice_notes = (
        await client.get("/api/v1/users/me/notifications", headers=alice_headers)
    ).json()["data"]
    assert [n for n in alice_notes if n["type"] == "project.created"] == []


async def test_archive_and_unarchive_project(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    keep = await create_project(client, alice_headers, team["id"], "Keep")
    project = await create_project(client, alice_headers, team["id"], "Old Rover")

    resp = await client.post(f"/api/v1/projects/{project['id']}/archive", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["archived_at"] is not None

    # Archived projects drop out of the default list…
    listing = (
        await client.get(f"/api/v1/teams/{team['id']}/projects", headers=alice_headers)
    ).json()["data"]
    assert [p["id"] for p in listing] == [keep["id"]]

    # …but stay reachable with the flag and via detail.
    with_archived = (
        await client.get(
            f"/api/v1/teams/{team['id']}/projects?include_archived=true", headers=alice_headers
        )
    ).json()["data"]
    assert {p["id"] for p in with_archived} == {keep["id"], project["id"]}
    detail = (await client.get(f"/api/v1/projects/{project['id']}", headers=alice_headers)).json()[
        "data"
    ]
    assert detail["archived_at"] is not None

    resp = await client.post(f"/api/v1/projects/{project['id']}/unarchive", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["archived_at"] is None
    listing = (
        await client.get(f"/api/v1/teams/{team['id']}/projects", headers=alice_headers)
    ).json()["data"]
    assert {p["id"] for p in listing} == {keep["id"], project["id"]}


async def test_archive_requires_member_role(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="viewer")

    resp = await client.post(f"/api/v1/projects/{project['id']}/archive", headers=bob_headers)
    assert resp.status_code == 403


async def test_archive_cross_tenant_denied(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    resp = await client.post(f"/api/v1/projects/{project['id']}/archive", headers=bob_headers)
    assert resp.status_code == 404


async def test_dashboard_list_and_detail_have_real_stats(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """FND-04 dashboard: list rows carry summary counts and detail carries real
    graph stats + connected-source summary (not the Phase-1 placeholder zeros)."""
    import uuid as _uuid

    from solus_api.models import Entity, Relation, Source, SourceStatus, SourceType

    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"], "Statful")

    async with app.state.sessionmaker() as db:
        source = Source(
            project_id=_uuid.UUID(project["id"]),
            team_id=_uuid.UUID(team["id"]),
            type=SourceType.GITHUB,
            name="octo/r",
            status=SourceStatus.CONNECTED,
        )
        db.add(source)
        await db.flush()
        a = Entity(
            project_id=_uuid.UUID(project["id"]),
            source_id=source.id,
            source_key=":repo",
            type="code_repo",
            domain="software",
            name="octo/r",
        )
        b = Entity(
            project_id=_uuid.UUID(project["id"]),
            source_id=source.id,
            source_key="main.py",
            type="code_file",
            domain="software",
            name="main.py",
        )
        db.add_all([a, b])
        await db.flush()
        db.add(
            Relation(
                project_id=_uuid.UUID(project["id"]),
                source_id=source.id,
                from_entity_id=a.id,
                to_entity_id=b.id,
                type="contains",
            )
        )
        await db.commit()

    listing = (
        await client.get(f"/api/v1/teams/{team['id']}/projects", headers=alice_headers)
    ).json()["data"]
    row = next(p for p in listing if p["id"] == project["id"])
    assert row["stats"] == {"entities": 2, "sources": 1}

    detail = (await client.get(f"/api/v1/projects/{project['id']}", headers=alice_headers)).json()[
        "data"
    ]
    assert detail["stats"] == {"entities": 2, "relations": 1}
    assert len(detail["sources"]) == 1
    assert detail["sources"][0]["name"] == "octo/r"
    assert detail["sources"][0]["status"] == "connected"
    assert "secret_ref" not in detail["sources"][0]


async def test_delete_project_removes_graph_data(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """Deleting a project must remove its graph rows explicitly (SQLite doesn't
    enforce FK cascade; PG shouldn't be relied on either)."""
    import uuid as _uuid

    from solus_api.models import Entity, Relation, Source, SourceType, Sync
    from sqlalchemy import func, select

    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"], "Doomed")
    pid = _uuid.UUID(project["id"])

    async with app.state.sessionmaker() as db:
        source = Source(
            project_id=pid, team_id=_uuid.UUID(team["id"]), type=SourceType.GITHUB, name="r"
        )
        db.add(source)
        await db.flush()
        a = Entity(
            project_id=pid,
            source_id=source.id,
            source_key="a",
            type="code_file",
            domain="software",
            name="a",
        )
        b = Entity(
            project_id=pid,
            source_id=source.id,
            source_key="b",
            type="code_file",
            domain="software",
            name="b",
        )
        db.add_all([a, b])
        await db.flush()
        db.add(Relation(project_id=pid, from_entity_id=a.id, to_entity_id=b.id, type="contains"))
        db.add(Sync(source_id=source.id, project_id=pid))
        await db.commit()

    resp = await client.delete(
        f"/api/v1/projects/{project['id']}?confirm=true", headers=alice_headers
    )
    assert resp.status_code == 204

    async with app.state.sessionmaker() as db:
        for model in (Entity, Relation, Source, Sync):
            count = await db.scalar(
                select(func.count()).select_from(model).where(model.project_id == pid)
            )
            assert count == 0, f"{model.__name__} rows leaked after project delete"


async def test_delete_project_leaves_sibling_graph_intact(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """The delete cascade is scoped to exactly the deleted project — a sibling
    project in the same team keeps its graph and its stored credential."""
    import uuid as _uuid

    from solus_api.models import Entity, Source, SourceStatus, SourceType, Sync
    from sqlalchemy import func, select

    team = await create_team(client, alice_headers)
    doomed = await create_project(client, alice_headers, team["id"], "Doomed")
    survivor = await create_project(client, alice_headers, team["id"], "Survivor")

    async def seed(project_id: str, secret_ref: str) -> None:
        async with app.state.sessionmaker() as db:
            source = Source(
                project_id=_uuid.UUID(project_id),
                team_id=_uuid.UUID(team["id"]),
                type=SourceType.GITHUB,
                name="r",
                status=SourceStatus.CONNECTED,
                secret_ref=secret_ref,
            )
            db.add(source)
            await db.flush()
            db.add(
                Entity(
                    project_id=_uuid.UUID(project_id),
                    source_id=source.id,
                    source_key="a",
                    type="code_file",
                    domain="software",
                    name="a",
                )
            )
            db.add(Sync(source_id=source.id, project_id=_uuid.UUID(project_id)))
            await db.commit()

    await seed(doomed["id"], "source/doomed/github")
    await seed(survivor["id"], "source/survivor/github")
    store = app.state.secret_store
    await store.put("source/doomed/github", "doomed-token")
    await store.put("source/survivor/github", "survivor-token")

    resp = await client.delete(
        f"/api/v1/projects/{doomed['id']}?confirm=true", headers=alice_headers
    )
    assert resp.status_code == 204

    async with app.state.sessionmaker() as db:
        for model in (Entity, Source, Sync):
            count = await db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.project_id == _uuid.UUID(survivor["id"]))
            )
            assert count == 1, f"sibling {model.__name__} rows were destroyed"
    # Sibling's credential survives; the deleted project's is gone.
    assert await store.get("source/survivor/github") == "survivor-token"
    import pytest as _pytest
    from solus_api.connectors.secrets import SecretNotFoundError

    with _pytest.raises(SecretNotFoundError):
        await store.get("source/doomed/github")


async def test_unarchive_cross_tenant_denied(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await client.post(f"/api/v1/projects/{project['id']}/archive", headers=alice_headers)
    await me(client, bob_headers)
    resp = await client.post(f"/api/v1/projects/{project['id']}/unarchive", headers=bob_headers)
    assert resp.status_code == 404


async def test_unarchive_requires_member_role(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await client.post(f"/api/v1/projects/{project['id']}/archive", headers=alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="viewer")
    resp = await client.post(f"/api/v1/projects/{project['id']}/unarchive", headers=bob_headers)
    assert resp.status_code == 403


async def test_team_setting_suppresses_project_created_notification(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """FND-07 team setting controls the FND-04/05 fan-out."""
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="member")
    resp = await client.patch(
        f"/api/v1/teams/{team['id']}",
        json={"settings": {"notify_project_created": False}},
        headers=alice_headers,
    )
    assert resp.status_code == 200

    await create_project(client, alice_headers, team["id"], "Quiet Rover")
    bob_notes = (
        await client.get("/api/v1/users/me/notifications", headers=bob_headers)
    ).json()["data"]
    assert [n for n in bob_notes if n["type"] == "project.created"] == []
