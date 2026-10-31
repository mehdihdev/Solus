"""SOLUSDEV-321 P2-T7 — a run records the graph findings its bench session raised while it ran,
and compare reports how two runs' findings differ (docs/api/bench-runs.md).

Seeded rows only: no bench session is started, so the app's evaluator and narrator never run
(R31). A finding's id is per bench session, so compare matches findings on their rule and
sorted subjects, never on the id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from solus_api.checkers.interface import Severity
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.findings import dismiss_finding, raise_finding
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.analysis import compare
from solus_api.livebench.runs.capture import Capture, RunCaptureManager, findings_during
from solus_api.livebench.runs.models import RunFinding, RunManifest, RunSummary
from solus_api.livebench.runs.snapshot import validate_references
from solus_api.models import Domain, GraphEntity, Project, Team, TeamKind, User, utcnow
from solus_api.storage import LocalArtifactStore
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_findings import _finding_spec


async def _arm(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, GraphEntity, GraphEntity]:
    """A project with one robot containing one part; returns project, user, robot, part."""
    user = User(supabase_user_id=uuid.uuid4().hex, email=f"{uuid.uuid4().hex[:8]}@runs.io")
    team = Team(name="T", kind=TeamKind.COLLABORATIVE)
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Arm", created_by=user.id)
    db.add(project)
    await db.flush()
    robot, part = (
        GraphEntity(
            project_id=project.id, kind=kind, domain=domain, origin="manual", name=name, attrs={}
        )
        for kind, domain, name in (
            (kinds.PHYSICAL_ROBOT, Domain.PROJECT, "Fake arm"),
            (kinds.PART, Domain.ELECTRICAL, "servo 3"),
        )
    )
    db.add_all([robot, part])
    await db.flush()
    await write_edge(
        db,
        project_id=project.id,
        src_id=robot.id,
        dst_id=part.id,
        relation_type="contains",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=user.id,
    )
    return project.id, user.id, robot, part


async def _observed(
    db: AsyncSession,
    project_id: uuid.UUID,
    part: GraphEntity,
    session_id: uuid.UUID,
    rule_id: str,
    severity: Severity = Severity.WARNING,
) -> GraphEntity:
    """An observer finding as the window evaluator raises it: one node per bench session."""
    spec = _finding_spec(
        [part.id],
        rule_id=rule_id,
        severity=severity,
        source="observer",
        headline=f"{rule_id} on servo 3",
        evidence={"session_id": str(session_id)},
        bucket=str(session_id),
    )
    return await raise_finding(db, project_id, spec)


def _summary(robot: GraphEntity, session_id: uuid.UUID | None, started: datetime) -> RunSummary:
    return RunSummary(
        id=uuid.uuid4(),
        robot_id=robot.id,
        session_id=session_id,
        name="stall run",
        origin="live",
        status="running",
        started_at=started,
    )


async def test_capture_records_finding_ids(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path
) -> None:
    project_id, user_id, robot, part = await _arm(db)
    session_id = uuid.uuid4()
    started = utcnow() - timedelta(minutes=1)
    stall = await _observed(
        db, project_id, part, session_id, "tracking_error_stall", Severity.CRITICAL
    )
    await _observed(db, project_id, part, session_id, "tracking_error_stall", Severity.CRITICAL)
    frozen = await _observed(db, project_id, part, session_id, "sensor_frozen")
    earlier = await _observed(db, project_id, part, session_id, "stream_gap")
    before = (started - timedelta(seconds=30)).isoformat()
    earlier.attrs = {**earlier.attrs, "first_seen": before, "last_seen": before}
    await _observed(db, project_id, part, uuid.uuid4(), "tracking_error_stall")  # another session
    await db.commit()
    # Dismissed since, but raised during the run: the run still records it.
    await dismiss_finding(db, project_id, frozen.id, user_id, 24)
    await db.commit()

    info = _summary(robot, session_id, started)
    record = run_store.new_record(project_id, info, user_id)
    db.add(record)
    await db.commit()
    artifacts = LocalArtifactStore(str(tmp_path))
    manager = RunCaptureManager(
        async_sessionmaker(engine, expire_on_commit=False), artifacts, AsyncMock()
    )
    # Registered without `add`, so no checkpoint task runs: `stop` makes the one final persist.
    manager.active[info.id] = Capture(
        project_id, user_id, info, RunManifest(robot_id=robot.id, started_at=started), 100
    )
    stopped = await manager.stop(info.id)
    assert stopped is not None and stopped.status == "completed"

    await db.refresh(record)
    saved = await run_store.load(db, artifacts, record, user_id, 3600)
    by_id = {item.finding_id: item for item in saved.findings}
    assert set(by_id) == {stall.id, frozen.id}
    assert by_id[stall.id].rule_id == "tracking_error_stall"
    assert by_id[stall.id].subjects == [part.id]
    assert (by_id[stall.id].severity, by_id[stall.id].count) == ("critical", 2)
    assert by_id[frozen.id].count == 1


async def test_capture_window_ends_at_the_run_and_needs_a_session(db: AsyncSession) -> None:
    project_id, _user_id, robot, part = await _arm(db)
    session_id = uuid.uuid4()
    started = utcnow() - timedelta(minutes=1)
    late = await _observed(db, project_id, part, session_id, "temp_trend_to_limit")
    await db.commit()
    info = _summary(robot, session_id, started)
    assert [item.finding_id for item in await findings_during(db, project_id, info)] == [late.id]
    # A finding first seen after the run ended was not raised during it.
    ended = info.model_copy(update={"ended_at": started + timedelta(seconds=5)})
    assert await findings_during(db, project_id, ended) == []
    # An imported run has no bench session: nothing to record.
    assert await findings_during(db, project_id, _summary(robot, None, started)) == []


async def test_imported_findings_must_name_this_projects_graph(db: AsyncSession) -> None:
    project_id, _user_id, robot, part = await _arm(db)
    _other_project, _other_user, _other_robot, foreign_part = await _arm(db)
    own = await _observed(db, project_id, part, uuid.uuid4(), "tracking_error_stall")
    await db.commit()
    at = datetime(2026, 10, 27, tzinfo=UTC)

    def recording(finding_id: uuid.UUID, subjects: list[uuid.UUID]) -> RunManifest:
        item = _run_finding("tracking_error_stall", subjects).model_copy(
            update={"finding_id": finding_id}
        )
        return RunManifest(robot_id=robot.id, started_at=at, findings=[item])

    await validate_references(db, project_id, recording(own.id, [part.id]))
    # An unknown finding, or another project's subject, is refused like any foreign reference.
    for finding_id, subjects in ((uuid.uuid4(), [part.id]), (own.id, [foreign_part.id])):
        with pytest.raises(APIError) as refused:
            await validate_references(db, project_id, recording(finding_id, subjects))
        assert refused.value.status_code == 404


def _run_finding(rule_id: str, subjects: list[uuid.UUID], count: int = 1) -> RunFinding:
    at = datetime(2026, 10, 27, tzinfo=UTC)
    return RunFinding(
        finding_id=uuid.uuid4(),
        rule_id=rule_id,
        subjects=subjects,
        severity="critical" if rule_id == "tracking_error_stall" else "warning",
        count=count,
        first_seen=at,
        last_seen=at,
    )


def test_compare_reports_finding_deltas() -> None:
    robot, part, bus = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    at = datetime(2026, 10, 27, tzinfo=UTC)
    stall_before = _run_finding("tracking_error_stall", [part, bus], count=3)
    stall_after = _run_finding("tracking_error_stall", [bus, part], count=5)
    frozen = _run_finding("sensor_frozen", [part])
    sag = _run_finding("rail_sag_correlated", [bus, part])
    baseline = RunManifest(robot_id=robot, started_at=at, findings=[stall_before, frozen])
    candidate = RunManifest(robot_id=robot, started_at=at, findings=[sag, stall_after])

    result = compare(baseline, candidate)

    assert result["expected_source"] == "baseline_run"
    assert result["source_snapshots_changed"] is False
    deltas = result["finding_deltas"]
    assert [(d["change"], d["rule_id"]) for d in deltas] == [
        ("new", "rail_sag_correlated"),
        ("cleared", "sensor_frozen"),
        ("persisting", "tracking_error_stall"),
    ]
    new, cleared, persisting = deltas
    # Each session's finding has its own id: the stall matches on rule and sorted subjects.
    assert persisting["subjects"] == sorted([str(part), str(bus)])
    assert persisting["severity"] == "critical"
    assert persisting["baseline"] == {"finding_id": str(stall_before.finding_id), "count": 3}
    assert persisting["candidate"] == {"finding_id": str(stall_after.finding_id), "count": 5}
    assert new["baseline"] is None
    assert new["candidate"] == {"finding_id": str(sag.finding_id), "count": 1}
    assert cleared["candidate"] is None
    assert cleared["baseline"] == {"finding_id": str(frozen.finding_id), "count": 1}


def test_manifests_without_findings_still_load_and_compare() -> None:
    robot = uuid.uuid4()
    started = datetime(2026, 10, 27, tzinfo=UTC)
    older = RunManifest.model_validate_json(
        f'{{"schema_version": 1, "robot_id": "{robot}", "started_at": "{started.isoformat()}"}}'
    )
    assert older.findings == []
    assert compare(older, older)["finding_deltas"] == []
    with pytest.raises(ValidationError):
        RunManifest(robot_id=robot, started_at=started, findings=[_run_finding("x", [])] * 1000)
