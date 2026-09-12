"""Personal selections preserve another member's graph and previous ready views."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import SourceViewSelection
from solus_api.services.source_revisions import view_payload
from sqlalchemy.ext.asyncio import AsyncSession


def test_pending_selection_retains_previous_ready_graph() -> None:
    base, active = uuid.uuid4(), uuid.uuid4()
    selection = SourceViewSelection(
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        base_source_id=base,
        status="pending",
        requested_branch="new",
        request_generation=uuid.uuid4(),
    )
    payload = view_payload(
        base, selection, active_source_id=active, active_branch="old", active_commit="a" * 40
    )
    assert payload["source_id"] == str(active)
    assert payload["branch"] == "old"
    assert payload["status"] == "pending"


def test_default_view_names_only_base_source() -> None:
    base = uuid.uuid4()
    payload = view_payload(base, None)
    assert payload == {
        "base_source_id": str(base),
        "source_id": str(base),
        "status": "default",
        "branch": None,
        "commit": None,
        "error": None,
    }


async def test_revision_routes_are_personal_and_hide_internal_sources(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from conftest import create_project, create_team, me
    from solus_api.models import (
        Domain,
        GraphEdge,
        GraphEntity,
        Membership,
        Role,
        Source,
        SourceRevision,
        SourceStatus,
        SourceType,
    )
    from sqlalchemy import select

    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    pid = uuid.UUID(project["id"])
    tid = uuid.UUID(team["id"])
    db.add(Membership(team_id=tid, user_id=uuid.UUID(bob["id"]), role=Role.MEMBER))
    base = Source(
        project_id=pid,
        team_id=tid,
        type=SourceType.GITHUB,
        name="repo",
        status=SourceStatus.CONNECTED,
        config={"repo": "acme/robot"},
    )
    db.add(base)
    await db.flush()
    snapshot = Source(
        project_id=pid,
        team_id=tid,
        type=SourceType.GITHUB,
        name="hidden",
        status=SourceStatus.CONNECTED,
        revision_base_source_id=base.id,
    )
    db.add(snapshot)
    await db.flush()
    revision = SourceRevision(
        project_id=pid,
        base_source_id=base.id,
        materialized_source_id=snapshot.id,
        commit_id="a" * 40,
        branch="feature",
    )
    db.add(revision)
    await db.flush()
    db.add_all(
        [
            GraphEntity(
                project_id=pid,
                source_id=base.id,
                kind="code_repo",
                domain=Domain.CODE,
                name="base",
                external_ref=":repo",
            ),
            GraphEntity(
                project_id=pid,
                source_id=snapshot.id,
                external_ref=":repo",
                kind="code_repo",
                domain=Domain.CODE,
                name="feature",
            ),
        ]
    )
    await db.flush()
    base_root = await db.scalar(select(GraphEntity).where(GraphEntity.source_id == base.id))
    snapshot_root = await db.scalar(select(GraphEntity).where(GraphEntity.source_id == snapshot.id))
    assert base_root is not None and snapshot_root is not None
    local = GraphEntity(project_id=pid, kind="local_folder", domain=Domain.CODE, name="local")
    db.add(local)
    await db.flush()
    db.add(
        GraphEdge(
            project_id=pid,
            src_id=local.id,
            dst_id=base_root.id,
            relation_type="clone_of",
            domain_pair="code:code",
        )
    )
    db.add(
        SourceViewSelection(
            project_id=pid,
            user_id=uuid.UUID(alice["id"]),
            base_source_id=base.id,
            active_revision_id=revision.id,
            active_branch="feature",
            status="ready",
            request_generation=uuid.uuid4(),
        )
    )
    await db.commit()
    prefix = f"/api/v1/projects/{pid}/sources"
    for headers, name in [(alice_headers, "feature"), (bob_headers, "base")]:
        response = await client.get(f"/api/v1/projects/{pid}/entities", headers=headers)
        assert response.status_code == 200
        assert {e["name"] for e in response.json()["data"] if e["name"] in {"base", "feature"}} == {
            name
        }
        relations = (
            await client.get(f"/api/v1/projects/{pid}/relations?type=clone_of", headers=headers)
        ).json()["data"]
        assert len(relations) == 1
        expected_root = snapshot_root.id if name == "feature" else base_root.id
        assert relations[0]["to_entity_id"] == str(expected_root)
        graph = await client.get(f"/api/v1/projects/{pid}/graph?root={local.id}", headers=headers)
        assert graph.status_code == 200
        response = await client.get(prefix, headers=headers)
        assert snapshot.id not in {uuid.UUID(s["id"]) for s in response.json()["data"]}
        assert (
            await client.get(f"{prefix}/{snapshot.id}/view", headers=headers)
        ).status_code == 404
    from solus_api.graph.read_scope import resolve_scope

    bob_selection = SourceViewSelection(
        project_id=pid,
        user_id=uuid.UUID(bob["id"]),
        base_source_id=base.id,
        active_revision_id=revision.id,
        active_branch="release",
        status="ready",
        request_generation=uuid.uuid4(),
    )
    db.add(bob_selection)
    await db.commit()
    alice_scope = await resolve_scope(db, pid, uuid.UUID(alice["id"]))
    bob_scope = await resolve_scope(db, pid, uuid.UUID(bob["id"]))
    assert alice_scope.branch_for_source(snapshot.id) == "feature"
    assert bob_scope.branch_for_source(snapshot.id) == "release"
    await db.delete(bob_selection)
    await db.commit()
    monkeypatch.setattr("solus_api.routers.source_revisions.acquire_revision", AsyncMock())
    response = await client.put(
        f"{prefix}/{base.id}/view", headers=alice_headers, json={"branch": "new"}
    )
    assert response.status_code == 202
    assert response.json()["data"]["source_id"] == str(snapshot.id)
    assert response.json()["data"]["status"] == "pending"
    assert (await client.get(f"{prefix}/{base.id}/view", headers=bob_headers)).json()["data"][
        "status"
    ] == "default"
    response = await client.delete(f"{prefix}/{base.id}/view", headers=alice_headers)
    assert response.status_code == 200
    assert response.json()["data"]["source_id"] == str(base.id)

    # An older queue failure must not overwrite a newer personal request.
    app.state.settings.redis_url = "redis://localhost:6379"
    from types import SimpleNamespace

    enqueues = 0

    async def enqueue(*args: Any) -> None:
        nonlocal enqueues
        enqueues += 1
        if enqueues == 1:
            newer = await client.put(
                f"{prefix}/{base.id}/view", headers=alice_headers, json={"branch": "newer"}
            )
            assert newer.status_code == 202
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr(
        "solus_api.routers.source_revisions._arq_pool",
        AsyncMock(return_value=SimpleNamespace(enqueue_job=enqueue)),
    )
    older = await client.put(
        f"{prefix}/{base.id}/view", headers=alice_headers, json={"branch": "older"}
    )
    assert older.status_code == 202
    assert older.json()["data"]["status"] == "pending"


async def test_acquisition_materializes_commit_without_changing_base(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from conftest import create_project, create_team, me
    from solus_api.connectors.contracts import Domain, EntityOut, SyncResult
    from solus_api.connectors.github import GitHubConnector
    from solus_api.models import Source, SourceRevision, SourceStatus, SourceType
    from solus_api.services.source_revisions import acquire_revision
    from sqlalchemy import select

    user = await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    source = Source(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        type=SourceType.GITHUB,
        name="repo",
        config={"repo": "acme/robot", "branch": "main"},
        secret_ref="fixture",
        status=SourceStatus.CONNECTED,
    )
    db.add(source)
    await db.flush()
    generation = uuid.uuid4()
    user_id = uuid.UUID(user["id"])
    selection = SourceViewSelection(
        project_id=source.project_id,
        user_id=user_id,
        base_source_id=source.id,
        request_generation=generation,
        requested_branch="feature",
        status="pending",
    )
    db.add(selection)
    await db.commit()
    await app.state.secret_store.put("fixture", "fixture-token")
    connector = GitHubConnector()
    sync = AsyncMock(
        return_value=SyncResult(
            entities=[
                EntityOut(source_key=":repo", type="code_repo", domain=Domain.CODE, name="repo")
            ],
            cursor={"sha": "a" * 40, "branch": "a" * 40},
        )
    )
    monkeypatch.setattr(connector, "sync", sync)
    monkeypatch.setattr(app.state.connector_registry, "create", lambda provider: connector)
    monkeypatch.setattr(
        "solus_api.services.source_revisions.resolve_branch", AsyncMock(return_value="a" * 40)
    )
    kwargs: dict[str, Any] = dict(
        sessionmaker=app.state.sessionmaker,
        registry=app.state.connector_registry,
        secret_store=app.state.secret_store,
        source_id=source.id,
        user_id=user_id,
        generation=generation,
    )
    await acquire_revision(**kwargs)
    await db.refresh(selection)
    assert selection.status == "ready", selection.error
    assert selection.active_revision_id is not None
    revision = await db.get(SourceRevision, selection.active_revision_id)
    assert revision is not None
    snapshot = await db.get(Source, revision.materialized_source_id)
    assert snapshot is not None and snapshot.secret_ref is None
    assert snapshot.cursor["sha"] == "a" * 40
    assert snapshot.cursor["branch"] == "feature"
    assert sync.call_args.args[0].config["branch"] == "a" * 40
    await db.refresh(source)
    assert source.config["branch"] == "main"
    await acquire_revision(**kwargs)
    assert sync.call_count == 1
    assert len((await db.scalars(select(SourceRevision))).all()) == 1

    # A failed next selection keeps the completed revision active.
    from solus_api.connectors.contracts import ConnectorError

    next_generation = uuid.uuid4()
    selection.status = "pending"
    selection.request_generation = next_generation
    selection.requested_branch = "missing"
    await db.commit()
    monkeypatch.setattr(
        "solus_api.services.source_revisions.resolve_branch",
        AsyncMock(side_effect=ConnectorError("not_found", "private upstream detail")),
    )
    await acquire_revision(**{**kwargs, "generation": next_generation})
    await db.refresh(selection)
    assert selection.status == "failed"
    assert selection.active_revision_id == revision.id
    assert "private" not in (selection.error or "")

    # Clearing while an old request resolves prevents that late result winning.
    selection.status = "pending"
    selection.request_generation = uuid.uuid4()
    late_generation = selection.request_generation
    await db.commit()

    async def clear_while_resolving(*args: Any) -> str:
        response = await client.delete(
            f"/api/v1/projects/{source.project_id}/sources/{source.id}/view", headers=alice_headers
        )
        assert response.status_code == 200
        return "a" * 40

    monkeypatch.setattr("solus_api.services.source_revisions.resolve_branch", clear_while_resolving)
    await acquire_revision(**{**kwargs, "generation": late_generation})
    response = await client.get(
        f"/api/v1/projects/{source.project_id}/sources/{source.id}/view", headers=alice_headers
    )
    assert response.json()["data"]["status"] == "default"
    assert sync.call_count == 1


@pytest.mark.parametrize(
    "method,path", [("GET", "revisions"), ("GET", "view"), ("PUT", "view"), ("DELETE", "view")]
)
async def test_revision_routes_refuse_foreign_team_and_anonymous(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    from unittest.mock import AsyncMock

    from conftest import create_project, create_team, me
    from solus_api.models import Source, SourceStatus, SourceType
    from sqlalchemy import select

    await me(client, alice_headers)
    await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    source = Source(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        type=SourceType.GITHUB,
        name="private",
        status=SourceStatus.CONNECTED,
        config={"repo": "acme/private"},
    )
    db.add(source)
    await db.commit()
    provider = AsyncMock()
    acquisition = AsyncMock()
    monkeypatch.setattr("solus_api.routers.source_revisions.list_branches", provider)
    monkeypatch.setattr("solus_api.routers.source_revisions.acquire_revision", acquisition)
    url = f"/api/v1/projects/{source.project_id}/sources/{source.id}/{path}"
    payload = {"branch": "main"} if method == "PUT" else None
    assert (await client.request(method, url, headers=bob_headers, json=payload)).status_code == 404
    assert (await client.request(method, url, json=payload)).status_code == 401
    provider.assert_not_called()
    acquisition.assert_not_called()
    assert (await db.scalars(select(SourceViewSelection))).all() == []


async def test_project_context_remains_awaitable_for_bridge(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    from conftest import create_project, create_team, me
    from solus_api.deps import get_project_context
    from solus_api.models import User

    account = await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    user = await db.get(User, uuid.UUID(account["id"]))
    assert user is not None
    context = await get_project_context(uuid.UUID(project["id"]), user, db)
    assert context.project.id == uuid.UUID(project["id"])


async def test_branch_discovery_uses_standard_response_envelope(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from conftest import create_project, create_team
    from solus_api.models import Source, SourceStatus, SourceType

    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    source = Source(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        type=SourceType.GITHUB,
        name="repo",
        config={"repo": "acme/robot"},
        secret_ref="fixture",
        status=SourceStatus.CONNECTED,
    )
    db.add(source)
    await db.commit()
    await app.state.secret_store.put("fixture", "fixture-token")
    payload = {
        "supported": True,
        "kind": "git_branch",
        "items": [{"name": "main", "commit": "a" * 40}],
        "next_page": 2,
    }
    discovery = AsyncMock(return_value=payload)
    monkeypatch.setattr("solus_api.routers.source_revisions.list_branches", discovery)
    response = await client.get(
        f"/api/v1/projects/{source.project_id}/sources/{source.id}/revisions?page=1",
        headers=alice_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"data": payload}
    discovery.assert_awaited_once()
