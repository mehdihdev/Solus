"""End-to-end tests for the live acquisition chain wired through the real
registry/worker/main assembly (SOLUSDEV-100 T4b): F2 (API-process vs ARQ-worker
registry construction), F3 (acting-user resolution/threading), tenant
isolation at the full-stack level, and invariant 2 (content-derived identity
across acquisition paths). Mirrors `test_sources.py`'s HTTP flow and
`test_bridge_tool.py`'s fake-session construction.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ingest_result
from solus_api.connectors.contracts import Credentials, SyncContext
from solus_api.connectors.kicad import KicadConnector
from solus_api.connectors.mcp_acquire import BridgeExportAcquirer
from solus_api.connectors.registry import ConnectorContext, build_registry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.connectors.worker import build_worker_settings, execute_source_sync, sweep_artifacts
from solus_api.core.config import Settings
from solus_api.models import GraphEntity, Project, Source, SourceStatus, SourceType, Sync, Team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

TOOL_NAME = "kicad.export_netlist"


def _netlist(ref: str) -> str:
    return (
        '<?xml version="1.0"?><export version="E">'
        f'<components><comp ref="{ref}"><value>V</value></comp></components>'
        "<nets></nets></export>"
    )


async def _landed_external_refs(
    maker: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> set[str]:
    async with maker() as db:
        rows = (
            await db.scalars(select(GraphEntity).where(GraphEntity.source_id == source_id))
        ).all()
        return {r.external_ref for r in rows if r.external_ref}


def _tool_spec() -> BridgeToolSpec:
    return BridgeToolSpec(
        server="kicad",
        remote_name="export_netlist",
        descriptor=ToolDescriptor(
            name=TOOL_NAME,
            description="export",
            params={"type": "object"},
            returns={"type": "object"},
        ),
    )


def _live_session(
    sent: list[str], *, user_id: uuid.UUID, team_id: uuid.UUID, project_id: uuid.UUID
) -> BridgeSession:
    async def _send(frame: str) -> None:
        sent.append(frame)

    async def _close(code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(_tool_spec(),),
        send=_send,
        close=_close,
        max_inflight=8,
    )


async def _answer_with_content(sent: list[str], session: BridgeSession, content: str) -> None:
    while not sent:
        await asyncio.sleep(0.005)
    call_id = json.loads(sent[0])["data"]["call_id"]
    ingest_result(session, ToolResult.success(call_id, {"content": content}))


@pytest.fixture
def sessionmaker_fixture(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _make_source(
    maker: async_sessionmaker[AsyncSession],
    *,
    project_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    export: str = _netlist("COMMITTED1"),
    project_path: str = "/home/user/rover-eda",
) -> Source:
    async with maker() as db:
        team = Team(id=team_id, name="T") if team_id else Team(name="T")
        db.add(team)
        await db.flush()
        project = (
            Project(id=project_id, team_id=team.id, name="P")
            if project_id
            else Project(team_id=team.id, name="P")
        )
        db.add(project)
        await db.flush()
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.KICAD,
            name="kicad-eda",
            status=SourceStatus.CONNECTED,
            config={"export": export, "project_path": project_path},
            created_by=created_by,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source


# ------------------------------------------------------------- F2: process wiring


async def test_worker_process_registry_has_no_live_acquisition(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """The ARQ worker's `build_registry(settings)` call passes no
    `acquirer_factory` — `create_scoped` must degrade to the plain,
    acquirer-less factory even when an acting user IS resolved."""
    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only", database_url="sqlite+aiosqlite://"
    )
    registry = build_registry(settings)  # no acquirer_factory — worker posture
    source = await _make_source(sessionmaker_fixture, created_by=uuid.uuid4())

    sync_id = await execute_source_sync(
        sessionmaker=sessionmaker_fixture,
        registry=registry,
        secret_store=InMemorySecretStore(),
        source_id=source.id,
    )
    async with sessionmaker_fixture() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status.value == "succeeded"
        assert sync.entities_created == 1  # the committed inline export landed


# ------------------------------------------------------------- F3: acting-user resolution


async def test_manual_sync_acting_user_prefers_live_over_inline(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
) -> None:
    """Full HTTP flow through the REAL `main.create_app` wiring: the manual
    `/sync` trigger threads `ctx.user.id` all the way to the bridge export
    acquirer, and a live companion answer wins over the inline `export`
    config (docs/contracts/metadata-extraction.md §2.1 — "live preferred")."""
    user = await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])

    connect = await client.post(
        f"/api/v1/projects/{project['id']}/sources",
        json={
            "type": "kicad",
            "name": "kicad-eda",
            "config": {"export": _netlist("INLINE1"), "project_path": "/p"},
        },
        headers=alice_headers,
    )
    assert connect.status_code == 201, connect.text
    source_id = connect.json()["data"]["id"]

    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user["id"]),
        team_id=uuid.UUID(team["id"]),
        project_id=uuid.UUID(project["id"]),
    )
    app.state.bridge_sessions.bind(session)

    task = asyncio.create_task(_answer_with_content(sent, session, _netlist("LIVE1")))
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/sources/{source_id}/sync", headers=alice_headers
    )
    await task
    assert resp.status_code == 202, resp.text

    entities = (
        await client.get(f"/api/v1/projects/{project['id']}/entities", headers=alice_headers)
    ).json()["data"]
    keys = {e["source_key"] for e in entities}
    assert "LIVE1" in keys
    assert "INLINE1" not in keys


async def test_scheduled_sync_falls_back_to_source_created_by(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """No manual `acting_user_id` is supplied — `execute_source_sync` must
    fall back to `source.created_by` (F3) so a scheduled run can still use
    that user's live bridge session."""
    creator_id = uuid.uuid4()
    team_id = uuid.uuid4()
    project_id = uuid.uuid4()
    source = await _make_source(
        sessionmaker_fixture,
        project_id=project_id,
        team_id=team_id,
        created_by=creator_id,
        export=_netlist("COMMITTED1"),
    )

    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, user_id=creator_id, team_id=team_id, project_id=project_id)
    sessions.bind(session)

    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only", database_url="sqlite+aiosqlite://"
    )

    def acquirer_factory(ctx: ConnectorContext, tool_name: str) -> BridgeExportAcquirer:
        return BridgeExportAcquirer(
            sessions=sessions,
            sessionmaker=sessionmaker_fixture,
            store=None,  # type: ignore[arg-type]  # unused: inline-content path only
            project_id=ctx.project_id,
            team_id=ctx.team_id,
            acting_user_id=ctx.acting_user_id,
            tool_name=tool_name,
            call_cap_bytes=262_144,
            artifact_ttl_seconds=3600,
            inline_max_bytes=524_288,
        )

    registry = build_registry(settings, acquirer_factory=acquirer_factory)

    task = asyncio.create_task(_answer_with_content(sent, session, _netlist("LIVE-SCHEDULED")))
    sync_id = await execute_source_sync(
        sessionmaker=sessionmaker_fixture,
        registry=registry,
        secret_store=InMemorySecretStore(),
        source_id=source.id,
        # acting_user_id intentionally omitted — must fall back to created_by
    )
    await task
    assert await _landed_external_refs(sessionmaker_fixture, source.id) == {"LIVE-SCHEDULED"}
    assert sync_id is not None


async def test_neither_manual_nor_created_by_skips_live_acquisition(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Neither a manual acting user NOR `source.created_by` resolved — the
    acquirer must decline cleanly and the committed inline export wins,
    WITHOUT ever dispatching to the (otherwise perfectly live) companion."""
    team_id = uuid.uuid4()
    project_id = uuid.uuid4()
    source = await _make_source(
        sessionmaker_fixture,
        project_id=project_id,
        team_id=team_id,
        created_by=None,
        export=_netlist("COMMITTED-ONLY"),
    )

    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    # A session bound to an ARBITRARY user — since acting_user_id resolves to
    # None, no lookup ever reaches this (or any) session.
    session = _live_session(sent, user_id=uuid.uuid4(), team_id=team_id, project_id=project_id)
    sessions.bind(session)

    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only", database_url="sqlite+aiosqlite://"
    )

    def acquirer_factory(ctx: ConnectorContext, tool_name: str) -> BridgeExportAcquirer:
        return BridgeExportAcquirer(
            sessions=sessions,
            sessionmaker=sessionmaker_fixture,
            store=None,  # type: ignore[arg-type]
            project_id=ctx.project_id,
            team_id=ctx.team_id,
            acting_user_id=ctx.acting_user_id,
            tool_name=tool_name,
            call_cap_bytes=262_144,
            artifact_ttl_seconds=3600,
            inline_max_bytes=524_288,
        )

    registry = build_registry(settings, acquirer_factory=acquirer_factory)

    sync_id = await execute_source_sync(
        sessionmaker=sessionmaker_fixture,
        registry=registry,
        secret_store=InMemorySecretStore(),
        source_id=source.id,
    )
    assert sync_id is not None
    assert sent == []  # nothing was ever dispatched
    assert await _landed_external_refs(sessionmaker_fixture, source.id) == {"COMMITTED-ONLY"}


# ------------------------------------------------------------- tenant isolation


async def test_cross_team_scope_never_dispatches_end_to_end(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """A source in team A with an acting user whose bridge session is bound
    to team B's scope must never dispatch or fetch (highest-severity case)."""
    acting_user_id = uuid.uuid4()
    team_a = uuid.uuid4()
    team_b = uuid.uuid4()
    project_id = uuid.uuid4()
    source = await _make_source(
        sessionmaker_fixture,
        project_id=project_id,
        team_id=team_a,
        created_by=acting_user_id,
        export=_netlist("COMMITTED-ISOLATED"),
    )

    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    # Same user, same project, but WRONG team (bound to team_b, not team_a).
    session = _live_session(sent, user_id=acting_user_id, team_id=team_b, project_id=project_id)
    sessions.bind(session)

    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only", database_url="sqlite+aiosqlite://"
    )

    def acquirer_factory(ctx: ConnectorContext, tool_name: str) -> BridgeExportAcquirer:
        return BridgeExportAcquirer(
            sessions=sessions,
            sessionmaker=sessionmaker_fixture,
            store=None,  # type: ignore[arg-type]
            project_id=ctx.project_id,
            team_id=ctx.team_id,  # team_a — the source's REAL team
            acting_user_id=ctx.acting_user_id,
            tool_name=tool_name,
            call_cap_bytes=262_144,
            artifact_ttl_seconds=3600,
            inline_max_bytes=524_288,
        )

    registry = build_registry(settings, acquirer_factory=acquirer_factory)
    sync_id = await execute_source_sync(
        sessionmaker=sessionmaker_fixture,
        registry=registry,
        secret_store=InMemorySecretStore(),
        source_id=source.id,
        acting_user_id=acting_user_id,
    )
    assert sync_id is not None
    assert sent == []  # the wrong-team session was never dispatched to
    assert await _landed_external_refs(sessionmaker_fixture, source.id) == {"COMMITTED-ISOLATED"}


# ------------------------------------------------------------- invariant 2: identity


async def test_identity_invariant_inline_vs_live_content_byte_identical(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """§2.1 invariant 2: the SAME bytes acquired via inline config vs a live
    acquirer's `content` result must yield byte-identical `SyncResult`s —
    identity is content-derived, never transport-derived."""
    text = _netlist("SAME1")

    via_inline = await KicadConnector().sync(
        SyncContext(credentials=Credentials(token=""), config={"export": text})
    )

    sessions = InMemoryBridgeSessionRegistry()
    scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    sent: list[str] = []
    session = _live_session(sent, user_id=scope[0], team_id=scope[1], project_id=scope[2])
    sessions.bind(session)
    acquirer = BridgeExportAcquirer(
        sessions=sessions,
        sessionmaker=sessionmaker_fixture,
        store=None,  # type: ignore[arg-type]
        project_id=scope[2],
        team_id=scope[1],
        acting_user_id=scope[0],
        tool_name=TOOL_NAME,
        call_cap_bytes=262_144,
        artifact_ttl_seconds=3600,
        inline_max_bytes=524_288,
    )
    task = asyncio.create_task(_answer_with_content(sent, session, text))
    via_live_content = await KicadConnector(acquirer=acquirer).sync(
        SyncContext(
            credentials=Credentials(token=""),
            config={"export": "irrelevant placeholder", "project_path": "/p"},
        )
    )
    await task

    assert via_inline == via_live_content


# ------------------------------------------------------------- worker artifact sweep cron


def test_sweep_artifacts_registered_as_cron_job() -> None:
    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only",
        database_url="sqlite+aiosqlite://",
        redis_url="redis://localhost:6379/0",
    )
    worker_settings = build_worker_settings(settings)
    cron_jobs: list[Any] = worker_settings.cron_jobs  # type: ignore[attr-defined]
    assert any(job.coroutine is sweep_artifacts for job in cron_jobs)


async def test_sweep_artifacts_invokes_the_t4c_service(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Any,
) -> None:
    from solus_api.storage import LocalArtifactStore

    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only",
        database_url="sqlite+aiosqlite://",
        artifact_ttl_seconds=3600,
    )
    ctx: dict[str, Any] = {
        "settings": settings,
        "sessionmaker": sessionmaker_fixture,
        "artifact_store": LocalArtifactStore(str(tmp_path / "artifacts")),
    }
    swept = await sweep_artifacts(ctx)
    assert swept == 0  # nothing expired yet; proves the wiring works end-to-end
