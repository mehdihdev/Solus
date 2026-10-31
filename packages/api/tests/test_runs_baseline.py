"""SOLUSDEV-321 P2-T1 — `POST /bench/runs/{run_id}/baseline`: the run a robot's learned envelope
bounds are read from.

Marking a run reassigns its record's attrs (never mutates them) and unmarks the robot's previous
baseline in the same commit, so a robot has one. A run is loaded through the project-scoped loader
the other run routes use: another project's run, a deleted one and a record of another kind are all
the same 404, and a run still capturing is refused, since its next checkpoint rewrites its record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.models import PartEvidence, RunManifest, RunSummary
from solus_api.livebench.runs.store import new_record
from solus_api.models import GraphEntity, User
from solus_api.storage import LocalArtifactStore
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_hardware_router import _hw_project
from test_window_evaluator import (
    T0,
    _arm,
    _CountingBuffer,
    _evaluator,
    _event_time,
    _feed,
    _maker,
    _Seen,
    _session_view,
)

_STARTED = datetime(2026, 10, 1, tzinfo=UTC)


def _run(project: str, robot: uuid.UUID, *, status: str = "completed", marked: bool = False) -> Any:
    summary = RunSummary(
        id=uuid.uuid4(),
        robot_id=robot,
        name="a run",
        origin="recorded",
        status=status,  # type: ignore[arg-type]
        started_at=_STARTED,
    )
    row = new_record(uuid.UUID(project), summary, uuid.uuid4())
    row.attrs = {
        **row.attrs,
        "checkpoint_id": str(uuid.uuid4()),
        **({"baseline": True} if marked else {}),
    }
    return row


async def _marks(db: AsyncSession, **rows: GraphEntity) -> dict[str, Any]:
    """What each named run's record says about being a baseline, read fresh from the database."""
    marks = {}
    for name, row in rows.items():
        stored = await db.get(GraphEntity, row.id, populate_existing=True)
        assert stored is not None
        marks[name] = stored.attrs.get("baseline")
    return marks


def _baseline_url(project: str, run: GraphEntity) -> str:
    return f"/api/v1/projects/{project}/bench/runs/{run.id}/baseline"


async def _flags(client: AsyncClient, headers: dict[str, str], project: str) -> dict[str, Any]:
    """`baseline` as each run's own read says it (the list route), by run id."""
    listing = await client.get(f"/api/v1/projects/{project}/bench/runs", headers=headers)
    assert listing.status_code == 200, listing.text
    return {run["id"]: run["baseline"] for run in listing.json()["data"]["runs"]}


def test_the_run_read_takes_the_flag_from_the_record_not_the_stored_summary() -> None:
    marked = _run(str(uuid.uuid4()), uuid.uuid4(), marked=True)
    plain = _run(str(uuid.uuid4()), uuid.uuid4())
    assert (run_store.summary(marked).baseline, run_store.summary(plain).baseline) == (True, False)
    # a record is created, and saved, without the flag inside its summary
    assert "baseline" not in plain.attrs["summary"]
    # a copy of the flag inside the stored summary never decides: the record's own attr does
    marked.attrs = {**marked.attrs, "summary": {**marked.attrs["summary"], "baseline": False}}
    assert run_store.summary(marked).baseline is True


@pytest.mark.asyncio
async def test_baseline_marks_run(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    arm, elsewhere = uuid.uuid4(), uuid.uuid4()
    old = _run(project, arm, marked=True)
    new, stopped = _run(project, arm), _run(project, arm, status="interrupted")
    other_robot = _run(project, elsewhere, marked=True)
    live = _run(project, arm, status="running")
    db.add_all([old, new, stopped, other_robot, live])
    await db.commit()
    rows = {"old": old, "new": new, "stopped": stopped, "other": other_robot, "live": live}

    done = await client.post(_baseline_url(project, new), headers=alice_headers)
    assert done.status_code == 200, done.text
    summary = done.json()["data"]
    assert (summary["id"], summary["status"], summary["robot_id"]) == (
        str(new.id),
        "completed",
        str(arm),
    )
    assert summary["baseline"] is True  # the answer already says what it did
    # one baseline per robot: the old one is unmarked, the other robot's is left alone
    assert await _marks(db, **rows) == {
        "old": None,
        "new": True,
        "stopped": None,
        "other": True,
        "live": None,
    }
    # and every run read says which run is the baseline
    assert await _flags(client, alice_headers, project) == {
        str(old.id): False,
        str(new.id): True,
        str(stopped.id): False,
        str(other_robot.id): True,
        str(live.id): False,
    }
    stored = await db.get(GraphEntity, new.id, populate_existing=True)
    assert stored is not None
    assert stored.attrs["checkpoint_id"] == new.attrs["checkpoint_id"]  # the rest is kept
    assert stored.attrs["summary"]["id"] == str(new.id)

    again = await client.post(_baseline_url(project, new), headers=alice_headers)
    assert again.status_code == 200, again.text  # marking the baseline again changes nothing
    assert (await _marks(db, **rows))["new"] is True

    refused = await client.post(_baseline_url(project, live), headers=alice_headers)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "run_active"
    assert (await _marks(db, **rows))["new"] is True and (await _marks(db, **rows))["live"] is None

    # a run that was cut short is still a recording: it can be the baseline
    moved = await client.post(_baseline_url(project, stopped), headers=alice_headers)
    assert moved.status_code == 200, moved.text
    assert await _marks(db, **rows) == {
        "old": None,
        "new": None,
        "stopped": True,
        "other": True,
        "live": None,
    }
    flags = await _flags(client, alice_headers, project)
    assert (flags[str(stopped.id)], flags[str(new.id)], flags[str(old.id)]) == (True, False, False)


@pytest.mark.asyncio
async def test_cross_team_404(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """Team B cannot mark team A's run — by its project or by its id from B's own project — and
    an unknown, deleted or wrong-kind record is the same 404, with nothing marked."""
    mine, _ = await _hw_project(client, alice_headers)
    theirs, _ = await _hw_project(client, bob_headers)
    run = _run(mine, uuid.uuid4())
    deleted = _run(mine, uuid.uuid4())
    deleted.deleted_at = datetime.now(UTC)
    not_a_run = _run(mine, uuid.uuid4())
    not_a_run.kind = "unrelated"
    db.add_all([run, deleted, not_a_run])
    await db.commit()

    assert (await client.post(_baseline_url(mine, run))).status_code == 401
    assert (await client.post(_baseline_url(mine, run), headers=bob_headers)).status_code == 404
    through_theirs = await client.post(_baseline_url(theirs, run), headers=bob_headers)
    assert through_theirs.status_code == 404
    assert through_theirs.json()["error"]["code"] == "not_found"
    for gone in (deleted, not_a_run):
        response = await client.post(_baseline_url(mine, gone), headers=alice_headers)
        assert response.status_code == 404, gone.kind
    unknown = f"/api/v1/projects/{mine}/bench/runs/{uuid.uuid4()}/baseline"
    assert (await client.post(unknown, headers=alice_headers)).status_code == 404

    assert await _marks(db, run=run, deleted=deleted, not_a_run=not_a_run) == {
        "run": None,
        "deleted": None,
        "not_a_run": None,
    }
    assert (await client.post(_baseline_url(mine, run), headers=alice_headers)).status_code == 200


@pytest.mark.asyncio
async def test_baseline_for_reads_the_robots_marked_run_of_its_own_project(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """SOLUSDEV-321 P2-T3 (M56): the window evaluator finds a robot's baseline — the marked run
    of THIS project whose summary names the robot. An unmarked run, another robot's, another
    project's and a deleted one are not it."""
    mine, _ = await _hw_project(client, alice_headers)
    theirs, _ = await _hw_project(client, bob_headers)
    robot, other, ghost = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    marked, plain = _run(mine, robot, marked=True), _run(mine, robot)
    elsewhere, foreign = _run(mine, other, marked=True), _run(theirs, robot, marked=True)
    gone = _run(mine, ghost, marked=True)
    gone.deleted_at = datetime.now(UTC)
    db.add_all([marked, plain, elsewhere, foreign, gone])
    await db.commit()

    found = await run_store.baseline_for(db, uuid.UUID(mine), robot)
    assert found is not None and (found.id, found.baseline) == (marked.id, True)
    theirs_found = await run_store.baseline_for(db, uuid.UUID(theirs), robot)
    assert theirs_found is not None and theirs_found.id == foreign.id
    assert await run_store.baseline_for(db, uuid.UUID(theirs), other) is None
    assert await run_store.baseline_for(db, uuid.UUID(mine), ghost) is None
    assert await run_store.baseline_for(db, uuid.UUID(mine), uuid.uuid4()) is None


async def test_the_robots_baseline_run_reaches_the_window_evaluators_envelopes(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """M56: the window evaluator (P2-T3) reads the robot's baseline run through the artifact store
    as the session's owner and builds the envelopes with it — the rate the baseline streamed servo
    3's current at reaches the rules as a learned bound."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    async with maker() as db:
        owner = User(supabase_user_id=f"sub-{uuid.uuid4().hex[:8]}", email="owner@example.com")
        db.add(owner)
        await db.flush()
        part = PartEvidence(entity_id=servo, name="servo 3", device_id="usb:ARM/3")
        packets = [
            TelemetryPacket(
                device_id="usb:ARM/3",
                timestamp=_event_time(index / 10),
                values={"servo3.current": 0.5},
                units={"servo3.current": "A"},
            )
            for index in range(40)
        ]
        baseline = RunManifest(robot_id=arm.robot, started_at=T0, parts=[part], packets=packets)
        info = RunSummary(
            id=uuid.uuid4(),
            robot_id=arm.robot,
            name="baseline",
            origin="recorded",
            status="completed",
            started_at=T0,
        )
        record = new_record(project, info, owner.id)
        db.add(record)
        await db.flush()
        await run_store.save(db, artifacts, record, info, baseline, owner.id, final=False)
        record.attrs = {**record.attrs, "baseline": True}
        await db.commit()
        owner_id = owner.id
    buffer, seen = _CountingBuffer(), _Seen()
    await _feed(buffer, project, servo, "servo3.current", "A", [0.5] * 20, start=0.0)
    view = _session_view(project, arm, {servo: {"servo3.current": _event_time(0)}}, owner=owner_id)

    await _evaluator(maker, buffer, rules=(seen,), artifacts=artifacts).tick(view)

    current = seen.windows[-1].envelopes["current"]
    assert current.expected_hz == pytest.approx(10.0)
    assert current.bounds_source["expected_hz"] == "learned"
