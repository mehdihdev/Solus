"""Widget invalidations expose only committed project-scoped registration state."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fixtures.extensions.routes import (
    FULL_GRANTS,
    ext_url,
    install,
    manifest_with,
    project_for,
    seed_extension,
)
from httpx import AsyncClient
from solus_api.widgets.graph_nodes import load_workspace_graph
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class CommittedObserver:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.frames: list[tuple[uuid.UUID, dict[str, Any], list[dict[str, Any]]]] = []

    async def publish(self, project: uuid.UUID, frame: dict[str, Any]) -> None:
        async with async_sessionmaker(self.engine)() as independent:
            graph = await load_workspace_graph(independent, project)
            self.frames.append((project, frame, [dict(node.attrs) for node in graph.widgets]))

    def latest(self, project: str) -> list[dict[str, Any]]:
        actual, frame, widgets = self.frames[-1]
        assert str(actual) == project == frame["project_id"]
        assert frame["type"] == "graph.changed"
        assert frame["source_id"] is None
        assert all(value == 0 for value in frame["counts"].values())
        return widgets


async def test_install_update_toggle_and_uninstall_notify_after_commit(
    app: FastAPI,
    client: AsyncClient,
    db: AsyncSession,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
) -> None:
    _, project = await project_for(client, alice_headers)
    await seed_extension(
        db,
        "bom-lite",
        {
            "1.2.0": manifest_with("1.2.0", slug="bom-lite"),
            "1.3.0": manifest_with("1.3.0", slug="bom-lite"),
        },
    )
    observer = CommittedObserver(engine)
    app.state.graph_hub = observer
    response = await install(
        client, alice_headers, project, "bom-lite", grants=FULL_GRANTS, version="1.2.0"
    )
    assert response.status_code == 201
    assert observer.latest(project)[0]["version"] == "1.2.0"
    response = await install(
        client, alice_headers, project, "bom-lite", grants=FULL_GRANTS, version="1.3.0"
    )
    assert response.status_code == 200
    assert observer.latest(project)[0]["version"] == "1.3.0"
    for enabled in (False, True):
        response = await client.patch(
            ext_url(project, "bom-lite"), headers=alice_headers, json={"enabled": enabled}
        )
        assert response.status_code == 200
        assert observer.latest(project)[0]["enabled"] is enabled
    response = await client.delete(ext_url(project, "bom-lite"), headers=alice_headers)
    assert response.status_code == 204
    assert observer.latest(project) == []
    assert len(observer.frames) == 5


async def test_reconcile_notifies_committed_registration_and_refusals_do_not(
    app: FastAPI,
    client: AsyncClient,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    _, project = await project_for(client, alice_headers)
    observer = CommittedObserver(engine)
    app.state.graph_hub = observer
    response = await client.post(
        f"/api/v1/projects/{project}/widgets/graph/reconcile", headers=alice_headers
    )
    assert response.status_code == 200
    observer.latest(project)
    before = len(observer.frames)
    response = await client.post(
        f"/api/v1/projects/{project}/widgets/graph/reconcile", headers=bob_headers
    )
    assert response.status_code == 404
    response = await client.patch(
        ext_url(project, "missing"), headers=alice_headers, json={"enabled": False}
    )
    assert response.status_code == 404
    assert len(observer.frames) == before


async def test_team_block_unblock_and_policy_delete_notify_only_installed_team_projects(
    app: FastAPI,
    client: AsyncClient,
    db: AsyncSession,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team, project = await project_for(client, alice_headers)
    _, foreign = await project_for(client, bob_headers)
    await seed_extension(db, "bom-lite")
    for headers, target in ((alice_headers, project), (bob_headers, foreign)):
        assert (
            await install(client, headers, target, "bom-lite", grants=FULL_GRANTS)
        ).status_code == 201
    observer = CommittedObserver(engine)
    app.state.graph_hub = observer
    url = f"/api/v1/teams/{team}/extensions/policies/bom-lite"
    for blocked in (True, False, True):
        response = await client.put(url, headers=alice_headers, json={"blocked": blocked})
        assert response.status_code in (200, 201)
        attrs = observer.latest(project)[0]
        assert attrs["blocked"] is blocked
        assert attrs["enabled"] is False
    assert (await client.delete(url, headers=alice_headers)).status_code == 204
    assert observer.latest(project)[0]["blocked"] is False
    assert len(observer.frames) == 4
    assert all(str(pid) == project for pid, _, _ in observer.frames)


async def test_failed_commit_never_publishes_registration(
    app: FastAPI,
    client: AsyncClient,
    db: AsyncSession,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project = await project_for(client, alice_headers)
    await seed_extension(db, "bom-lite")
    observer = CommittedObserver(engine)
    app.state.graph_hub = observer

    async def failed_commit(self: AsyncSession) -> None:
        raise RuntimeError("commit unavailable")

    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    with pytest.raises(RuntimeError, match="commit unavailable"):
        await install(client, alice_headers, project, "bom-lite", grants=FULL_GRANTS)
    assert observer.frames == []
    async with async_sessionmaker(engine)() as independent:
        assert (await load_workspace_graph(independent, uuid.UUID(project))).widgets == []
