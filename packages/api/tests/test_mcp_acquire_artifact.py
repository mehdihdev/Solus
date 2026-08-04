"""`BridgeExportAcquirer` artifact_ref consumption tests (SOLUSDEV-100 T4b) —
the docs/api/artifacts.md §4.3 anti-forgery checks now enforced end-to-end by
`services/artifacts.py::consume_tool_artifact` (Phase 4 H1/M3 fix: the ONLY
consumption path in the codebase). Uses a real Postgres session (via the
shared `engine` fixture) and a `LocalArtifactStore` — mirrors
`test_artifact_upload.py`'s project setup and `test_bridge_tool.py`'s
fake-session construction.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ArtifactRef, ToolDescriptor, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ingest_result
from solus_api.connectors.contracts import Credentials, SyncContext
from solus_api.connectors.mcp_acquire import PROJECT_PATH_CONFIG_KEY, BridgeExportAcquirer
from solus_api.core.errors import APIError
from solus_api.models import Artifact, ArtifactStorage, Membership, ProjectMembership
from solus_api.services.artifacts import consume_tool_artifact, create_artifact
from solus_api.storage import LocalArtifactStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

CALL_CAP = 262_144
ARTIFACT_TTL = 3600
TOOL_NAME = "kicad.export_netlist"
DEFAULT_EXPORT_BYTES = b"(export (version D) )"


def _export_tool_spec() -> BridgeToolSpec:
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
        inventory=(_export_tool_spec(),),
        send=_send,
        close=_close,
        max_inflight=8,
    )


async def _project_and_user(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    """`(project_id, user_id, team_id)` — the REAL team the project belongs
    to (Phase 4: `consume_tool_artifact`'s condition 2 checks the project's
    ACTUAL team_id, so tests must scope the acquirer to that same team rather
    than an arbitrary uuid)."""
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id: str = project["id"]
    user_id: str = user["id"]
    team_id: str = team["id"]
    return project_id, user_id, team_id


async def _wait_for_call_id(sent: list[str]) -> str:
    while not sent:
        await asyncio.sleep(0.005)
    call_id: str = json.loads(sent[0])["data"]["call_id"]
    return call_id


def _ref_dict(ref: ArtifactRef) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(ref.model_dump_json())
    return result


async def _latest_artifact(db: AsyncSession) -> Artifact:
    row = (
        await db.execute(select(Artifact).order_by(Artifact.created_at.desc()).limit(1))
    ).scalar_one()
    return row


@pytest.fixture
def store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(str(tmp_path / "artifacts"))


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _acquirer(
    *,
    sessions: InMemoryBridgeSessionRegistry,
    sessionmaker: async_sessionmaker[AsyncSession],
    store: LocalArtifactStore,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    artifact_ttl_seconds: int = ARTIFACT_TTL,
) -> BridgeExportAcquirer:
    return BridgeExportAcquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=project_id,
        team_id=team_id,
        acting_user_id=acting_user_id,
        tool_name=TOOL_NAME,
        call_cap_bytes=CALL_CAP,
        artifact_ttl_seconds=artifact_ttl_seconds,
        inline_max_bytes=512,
    )


def _acquire_ctx() -> SyncContext:
    return SyncContext(credentials=Credentials(token=""), config={PROJECT_PATH_CONFIG_KEY: "/p"})


# ------------------------------------------- the REAL fork envelope (Phase 4 H5)
# Mirrors test_mcp_acquire.py's `_real_envelope`: the plan-locked export_netlist
# result carries format/filename/bytes/degraded/reason alongside artifact_ref
# (integrations/mcp/kicad/solus/netlist_export.py; the companion preserves them
# verbatim and rewrites artifact_path -> artifact_ref before the frame leaves
# the machine). H5 residual: this suite's happy-path test used to send a bare
# `{"artifact_ref": ...}` value, never proving the REAL companion-rewritten
# envelope round-trips end to end.


def _real_envelope(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "format": "kicadxml",
        "filename": "solus_sample.net.xml",
        "bytes": len(DEFAULT_EXPORT_BYTES),
        "content": None,
        "degraded": False,
        "reason": None,
    }
    envelope.update(overrides)
    return envelope


async def _upload_and_answer_after_dispatch(
    sent: list[str],
    session: BridgeSession,
    db: AsyncSession,
    store: LocalArtifactStore,
    *,
    project_id: uuid.UUID,
    created_by: uuid.UUID,
    source_tool: str = TOOL_NAME,
    data: bytes = DEFAULT_EXPORT_BYTES,
    media_type: str = "text/plain",
    tool_call_id_override: str | None = None,
    real_envelope: bool = False,
) -> None:
    """Simulates the real flow: the companion sees the dispatched `tool_call`,
    uploads the bytes (binding `tool_call_id` to the call it was answering),
    then replies with a `tool_result` carrying the resulting `artifact_ref`.
    `real_envelope=True` sends the FULL companion-rewritten shape (Phase 4 H5)
    instead of a bare `{"artifact_ref": ...}` value."""
    call_id = await _wait_for_call_id(sent)
    artifact = await create_artifact(
        db,
        store,
        project_id=project_id,
        created_by=created_by,
        data=data,
        media_type=media_type,
        source_tool=source_tool,
        tool_call_id=tool_call_id_override or call_id,
    )
    await db.commit()
    ref = ArtifactRef(
        artifact_id=artifact.id,
        uri=artifact.uri,
        media_type=media_type,
        storage=ArtifactStorage.LOCAL,
        size_bytes=len(data),
    )
    value = (
        _real_envelope(bytes=len(data), artifact_ref=_ref_dict(ref))
        if real_envelope
        else {"artifact_ref": _ref_dict(ref)}
    )
    ingest_result(session, ToolResult.success(call_id, value))


async def test_happy_path_consumes_artifact_and_returns_text(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Phase 4 H5 residual: exercises the REAL companion-rewritten envelope
    (format/filename/bytes/degraded/reason alongside artifact_ref), not a bare
    `{"artifact_ref": ...}` value."""
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
            data=b"U1\nR1",
            real_envelope=True,
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result == "U1\nR1"


async def test_replayed_artifact_is_consumed_exactly_once(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    first = await acquirer.acquire(_acquire_ctx())
    await task
    assert first is not None

    # A second dispatch answered with the SAME (now-consumed) artifact must be
    # refused — one-shot consumption (§4.2), first consumer wins.
    artifact_row = await _latest_artifact(db)
    sent2: list[str] = []
    session2 = _live_session(
        sent2,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session2)

    async def _reanswer_with_same_artifact() -> None:
        call_id = await _wait_for_call_id(sent2)
        ref = ArtifactRef(
            artifact_id=artifact_row.id,
            uri=artifact_row.uri,
            media_type=artifact_row.media_type,
            storage=ArtifactStorage.LOCAL,
        )
        ingest_result(session2, ToolResult.success(call_id, {"artifact_ref": _ref_dict(ref)}))

    task2 = asyncio.create_task(_reanswer_with_same_artifact())
    second = await acquirer.acquire(_acquire_ctx())
    await task2
    assert second is None


async def test_created_by_mismatch_refuses_without_consuming(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, alice_id, team_id = await _project_and_user(client, alice_headers)
    bob = await me(client, bob_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(alice_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    # Artifact was created by BOB, not the acting user (Alice) — must refuse.
    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(bob["id"]),
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(alice_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None

    # Not consumed: its actual creator (Bob) can still consume it directly
    # through the SAME (only) consumption path, with Bob's own identity.
    artifact_row = await _latest_artifact(db)
    data, _media_type = await consume_tool_artifact(
        db,
        store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        artifact_id=artifact_row.id,
        requester_id=uuid.UUID(bob["id"]),
        source_tool=artifact_row.source_tool or TOOL_NAME,
        tool_call_id=artifact_row.tool_call_id or "",
        ttl_seconds=ARTIFACT_TTL,
    )
    assert data == DEFAULT_EXPORT_BYTES


async def test_source_tool_mismatch_refuses(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
            source_tool="altium.export_netlist",  # a DIFFERENT tool than dispatched
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None


async def test_tool_call_id_mismatch_refuses(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
            tool_call_id_override="not-the-dispatched-call-id",
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None


async def test_cross_project_artifact_refuses(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Highest-severity isolation case: an artifact that belongs to a
    DIFFERENT project than the one the acquirer is scoped to must never be
    consumed, even if every other field (created_by, source_tool, call_id)
    would otherwise match."""
    project_a, user_id, team_id = await _project_and_user(client, alice_headers)
    other_team = await create_team(client, alice_headers, name="Team B")
    project_b_resp = await create_project(
        client, alice_headers, other_team["id"], name="Other Project"
    )
    project_b = project_b_resp["id"]

    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_a),
    )
    sessions.bind(session)

    # Artifact belongs to project_b — the acquirer is scoped to project_a.
    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_b),
            created_by=uuid.UUID(user_id),
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_a),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None


async def test_cross_team_scope_mismatch_refuses(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Phase 4 H1/M3 condition 2 (new): even with a correct project scope,
    created_by, source_tool, and tool_call_id, the acquirer's OWN `team_id`
    must match the project's ACTUAL team — otherwise a source misconfigured
    (or attacked) to carry the wrong team scope could still consume an
    artifact belonging to a project it has no real team relationship with."""
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    other_team = await create_team(client, alice_headers, name="Unrelated Team")

    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    # The live bridge session is scoped to the WRONG team on purpose — proves
    # the routing scope alone (session lookup) is not what the anti-forgery
    # check relies on; `consume_tool_artifact` re-derives the project's real
    # team_id itself from the DB.
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(other_team["id"]),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(other_team["id"]),  # WRONG team for this project
        acting_user_id=uuid.UUID(user_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None

    # Not consumed: the artifact is still live and fetchable with the RIGHT team.
    artifact_row = await _latest_artifact(db)
    data, _media_type = await consume_tool_artifact(
        db,
        store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        artifact_id=artifact_row.id,
        requester_id=uuid.UUID(user_id),
        source_tool=artifact_row.source_tool or TOOL_NAME,
        tool_call_id=artifact_row.tool_call_id or "",
        ttl_seconds=ARTIFACT_TTL,
    )
    assert data == DEFAULT_EXPORT_BYTES


async def test_expired_artifact_refuses(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
        artifact_ttl_seconds=0,  # already expired the instant it's created
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None


async def test_undecodable_bytes_refuse(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
            data=b"\xff\xfe\xfd not valid utf-8",
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None


async def test_malformed_artifact_ref_shape_refuses(
    client: AsyncClient,
    alice_headers: dict[str, str],
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    async def _answer_malformed() -> None:
        call_id = await _wait_for_call_id(sent)
        ingest_result(
            session,
            ToolResult.success(call_id, {"artifact_ref": {"artifact_id": "not-a-uuid"}}),
        )

    task = asyncio.create_task(_answer_malformed())
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None


# ------------------------------------------------------------- Phase 4 M4


async def test_removed_team_member_declines_without_dispatching(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
    sessionmaker: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Phase 4 M4: the acquirer used to hardcode `requester_has_project_access
    =True` — a user removed from the team AFTER being resolved as this sync
    run's acting user (F3: `source.created_by`) must still decline, not
    silently consume as if nothing changed. Revokes BOTH the team `Membership`
    AND the ADR-025 dual-source `ProjectMembership` share auto-granted at
    project creation (`routers/projects.py::create_project`) — leaving either
    live would still grant access, per that ADR's own semantics."""
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)

    membership = await db.scalar(
        select(Membership).where(
            Membership.team_id == uuid.UUID(team_id), Membership.user_id == uuid.UUID(user_id)
        )
    )
    assert membership is not None
    membership.deleted_at = datetime.now(UTC)
    share = await db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == uuid.UUID(project_id),
            ProjectMembership.user_id == uuid.UUID(user_id),
        )
    )
    assert share is not None
    share.deleted_at = datetime.now(UTC)
    await db.commit()

    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(
        sent,
        user_id=uuid.UUID(user_id),
        team_id=uuid.UUID(team_id),
        project_id=uuid.UUID(project_id),
    )
    sessions.bind(session)

    task = asyncio.create_task(
        _upload_and_answer_after_dispatch(
            sent,
            session,
            db,
            store,
            project_id=uuid.UUID(project_id),
            created_by=uuid.UUID(user_id),
        )
    )
    acquirer = _acquirer(
        sessions=sessions,
        sessionmaker=sessionmaker,
        store=store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        acting_user_id=uuid.UUID(user_id),
    )
    with caplog.at_level("WARNING", logger="solus.connectors.mcp_acquire"):
        result = await acquirer.acquire(_acquire_ctx())
    await task
    assert result is None
    assert "no longer has access" in caplog.text

    # Not consumed: the artifact is still live.
    artifact_row = await _latest_artifact(db)
    assert artifact_row.deleted_at is None


# --------------------------------------- Phase 4 H1/M3: consume_tool_artifact


async def _seeded_artifact(
    db: AsyncSession,
    store: LocalArtifactStore,
    *,
    project_id: uuid.UUID,
    created_by: uuid.UUID,
    source_tool: str = TOOL_NAME,
    tool_call_id: str = "call-fixed-1",
    data: bytes = b"payload",
) -> Artifact:
    artifact = await create_artifact(
        db,
        store,
        project_id=project_id,
        created_by=created_by,
        data=data,
        media_type="text/plain",
        source_tool=source_tool,
        tool_call_id=tool_call_id,
    )
    await db.commit()
    return artifact


async def test_consume_tool_artifact_happy_path_consumes_once(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    artifact = await _seeded_artifact(
        db, store, project_id=uuid.UUID(project_id), created_by=uuid.UUID(user_id)
    )
    data, media_type = await consume_tool_artifact(
        db,
        store,
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        artifact_id=artifact.id,
        requester_id=uuid.UUID(user_id),
        source_tool=TOOL_NAME,
        tool_call_id="call-fixed-1",
        ttl_seconds=ARTIFACT_TTL,
    )
    assert data == b"payload"
    assert media_type == "text/plain"

    consumed = await db.get(Artifact, artifact.id)
    assert consumed is not None
    assert consumed.deleted_at is not None


@pytest.mark.parametrize(
    "override_field,override_value,label",
    [
        ("project_id", "other_project", "project scope (condition 1)"),
        ("team_id", "other_team", "team scope (condition 2)"),
        ("requester_id", "bob", "created_by (condition 3)"),
        ("source_tool", "altium.export_netlist", "source_tool (condition 4)"),
        ("tool_call_id", "not-the-dispatched-call", "tool_call_id (condition 5)"),
    ],
)
async def test_consume_tool_artifact_rejects_each_anti_forgery_mismatch(
    override_field: str,
    override_value: str,
    label: str,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    bob = await me(client, bob_headers)
    other_team = await create_team(client, alice_headers, name="Other Team")
    other_project = await create_project(client, alice_headers, other_team["id"], name="Other")

    resolved = {
        "other_project": other_project["id"],
        "other_team": other_team["id"],
        "bob": bob["id"],
    }

    artifact = await _seeded_artifact(
        db, store, project_id=uuid.UUID(project_id), created_by=uuid.UUID(user_id)
    )
    kwargs: dict[str, Any] = {
        "project_id": uuid.UUID(project_id),
        "team_id": uuid.UUID(team_id),
        "artifact_id": artifact.id,
        "requester_id": uuid.UUID(user_id),
        "source_tool": TOOL_NAME,
        "tool_call_id": "call-fixed-1",
        "ttl_seconds": ARTIFACT_TTL,
    }
    resolved_value = resolved.get(override_value, override_value)
    if override_field in {"project_id", "team_id", "requester_id"}:
        kwargs[override_field] = uuid.UUID(resolved_value)
    else:
        kwargs[override_field] = resolved_value

    with pytest.raises(APIError) as excinfo:
        await consume_tool_artifact(db, store, **kwargs)
    assert excinfo.value.status_code == 404, label

    # Never consumed: the row is still live.
    refreshed = await db.get(Artifact, artifact.id)
    assert refreshed is not None
    assert refreshed.deleted_at is None, label


async def test_consume_tool_artifact_rejects_expired_liveness_condition(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
) -> None:
    """Condition 6: liveness/one-shot — a TTL-expired artifact is refused
    exactly like a consumed one, and is left untouched (not soft-deleted a
    second time, not double-billed as a decline)."""
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    artifact = await _seeded_artifact(
        db, store, project_id=uuid.UUID(project_id), created_by=uuid.UUID(user_id)
    )
    with pytest.raises(APIError) as excinfo:
        await consume_tool_artifact(
            db,
            store,
            project_id=uuid.UUID(project_id),
            team_id=uuid.UUID(team_id),
            artifact_id=artifact.id,
            requester_id=uuid.UUID(user_id),
            source_tool=TOOL_NAME,
            tool_call_id="call-fixed-1",
            ttl_seconds=0,  # already expired the instant it's created
        )
    assert excinfo.value.status_code == 404


async def test_consume_tool_artifact_is_one_shot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    store: LocalArtifactStore,
) -> None:
    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    artifact = await _seeded_artifact(
        db, store, project_id=uuid.UUID(project_id), created_by=uuid.UUID(user_id)
    )
    good_kwargs: dict[str, Any] = {
        "project_id": uuid.UUID(project_id),
        "team_id": uuid.UUID(team_id),
        "artifact_id": artifact.id,
        "requester_id": uuid.UUID(user_id),
        "source_tool": TOOL_NAME,
        "tool_call_id": "call-fixed-1",
        "ttl_seconds": ARTIFACT_TTL,
    }
    first = await consume_tool_artifact(db, store, **good_kwargs)
    assert first == (b"payload", "text/plain")

    with pytest.raises(APIError) as excinfo:
        await consume_tool_artifact(db, store, **good_kwargs)
    assert excinfo.value.status_code == 404
