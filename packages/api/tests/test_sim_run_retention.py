"""SOLUSDEV-322 P7-T3: sim-run payload retention (`livebench/runs/sim_run_retention.py`).

Under a frozen clock: only `origin == "sim"` runs ended more than `keep_days` ago and beyond the
newest `keep_newest` of their robot lose their payload; pinned, baseline and finding-linked runs
survive; real runs, the run record itself (its summary and `attrs.sim`) and the rung-4
`sim_result` are never touched; the worker registers the cron at 03:17."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from solus_api.connectors.worker import build_worker_settings
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.livebench.runs import sim_run_retention
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.models import RunManifest, RunSummary, SimRunInfo
from solus_api.livebench.runs.sim_run_retention import PruneReport, prune_sim_runs
from solus_api.models import Artifact, Domain, GraphEntity, Project, User
from solus_api.services.solus_graph import lock_project as real_lock
from solus_api.storage import LocalArtifactStore
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_solus_layer import _project

NOW = datetime(2026, 11, 9, 3, 17, tzinfo=UTC)
DAY = timedelta(days=1)
OLD = NOW - 40 * DAY
RECENT = NOW - 5 * DAY

Maker = async_sessionmaker[AsyncSession]


async def _setup(engine: AsyncEngine) -> tuple[Maker, uuid.UUID, uuid.UUID]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project = await _project(maker)
    async with maker() as db:
        user = User(supabase_user_id=f"sub-{uuid.uuid4().hex[:8]}", email="ret@example.com")
        db.add(user)
        await db.commit()
        return maker, project, user.id


async def _run(
    db: AsyncSession,
    store: LocalArtifactStore,
    project: uuid.UUID,
    user: uuid.UUID,
    robot: uuid.UUID,
    *,
    ended_at: datetime,
    origin: str = "sim",
    **flags: Any,
) -> uuid.UUID:
    """One completed run filed the way a capture or `record_sim_run` files it (`store.save`,
    final), ended at `ended_at`; `flags` are stamped on the record like `POST …/pin` does."""
    started = ended_at - timedelta(minutes=1)
    info = RunSummary.model_validate(
        {
            "id": uuid.uuid4(),
            "robot_id": robot,
            "name": f"{origin} {ended_at:%Y-%m-%d %H:%M}",
            "origin": origin,
            "status": "completed",
            "started_at": started,
            "ended_at": ended_at,
        }
    )
    manifest = RunManifest(
        robot_id=robot,
        started_at=started,
        sim=SimRunInfo(provider="gazebo", scene_ref="demo.sdf") if origin == "sim" else None,
    )
    entity = run_store.new_record(project, info, user)
    db.add(entity)
    await db.flush()
    await run_store.save(db, store, entity, info, manifest, user, final=True)
    if flags:
        entity.attrs = {**entity.attrs, **flags}
        await db.commit()
    return entity.id


async def _runs(
    db: AsyncSession,
    store: LocalArtifactStore,
    project: uuid.UUID,
    user: uuid.UUID,
    robot: uuid.UUID,
    count: int,
    *,
    ended_at: datetime,
    origin: str = "sim",
) -> list[uuid.UUID]:
    """`count` runs, oldest first, one minute apart ending at `ended_at`."""
    return [
        await _run(
            db,
            store,
            project,
            user,
            robot,
            ended_at=ended_at - timedelta(minutes=count - index),
            origin=origin,
        )
        for index in range(count)
    ]


async def _payload_state(db: AsyncSession, store: LocalArtifactStore, run_id: uuid.UUID) -> str:
    """`deleted` when the artifact row is soft-deleted, its bytes gone and the record stamped;
    `live` when none of that happened; anything in between is a bug."""
    entity = await db.get(GraphEntity, run_id)
    assert entity is not None and entity.deleted_at is None
    artifact = await db.get(Artifact, uuid.UUID(entity.attrs["checkpoint_id"]))
    assert artifact is not None
    row_deleted = artifact.deleted_at is not None
    bytes_gone = not (store.root / str(artifact.id)).exists()
    stamped = entity.attrs.get("payload_deleted_at") is not None
    assert row_deleted == bytes_gone == stamped, (run_id, row_deleted, bytes_gone, stamped)
    return "deleted" if row_deleted else "live"


async def test_deletes_only_sim_runs_older_than_30_days_beyond_the_newest_20(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Robot A: 22 sim runs 40 days old and 2 five days old — the newest 20 are the 2 recent
    plus the 18 newest old ones, so exactly the 4 oldest lose their payload; robot B's 3 old
    runs are all within its newest 20 and survive. A second pass under the same clock finds
    nothing left to do."""
    maker, project, user = await _setup(engine)
    store = LocalArtifactStore(str(tmp_path))
    robot_a, robot_b = uuid.uuid4(), uuid.uuid4()
    async with maker() as db:
        old = await _runs(db, store, project, user, robot_a, 22, ended_at=OLD)
        recent = await _runs(db, store, project, user, robot_a, 2, ended_at=RECENT)
        other = await _runs(db, store, project, user, robot_b, 3, ended_at=OLD)

    async with maker() as db:
        report = await prune_sim_runs(db, store, now=NOW)
        assert report == PruneReport(deleted=4, kept=23)
        for run_id in old[:4]:
            assert await _payload_state(db, store, run_id) == "deleted"
        for run_id in [*old[4:], *recent, *other]:
            assert await _payload_state(db, store, run_id) == "live"

    async with maker() as db:
        assert await prune_sim_runs(db, store, now=NOW) == PruneReport(deleted=0, kept=23)
        # keep only 2 per robot: A's 18 remaining old runs and B's oldest one go
        assert (await prune_sim_runs(db, store, now=NOW, keep_newest=2)).deleted == 18 + 1


async def test_pinned_baseline_and_finding_linked_runs_survive(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Of the 4 runs beyond robot's newest 20, the pinned, the baseline and the finding-linked
    one keep their payload; only the plain one loses it — whatever its age."""
    maker, project, user = await _setup(engine)
    store = LocalArtifactStore(str(tmp_path))
    robot = uuid.uuid4()
    async with maker() as db:
        pinned = await _run(db, store, project, user, robot, ended_at=OLD - 4 * DAY, pinned=True)
        baseline = await _run(
            db, store, project, user, robot, ended_at=OLD - 3 * DAY, baseline=True
        )
        linked = await _run(
            db, store, project, user, robot, ended_at=OLD - 2 * DAY, findings_linked=True
        )
        plain = await _run(db, store, project, user, robot, ended_at=OLD - DAY)
        newest = await _runs(db, store, project, user, robot, 20, ended_at=OLD)

    async with maker() as db:
        report = await prune_sim_runs(db, store, now=NOW)
        assert report == PruneReport(deleted=1, kept=23)
        assert await _payload_state(db, store, plain) == "deleted"
        for run_id in [pinned, baseline, linked, *newest]:
            assert await _payload_state(db, store, run_id) == "live"


async def test_real_runs_are_never_touched(engine: AsyncEngine, tmp_path: Path) -> None:
    """25 live runs older than the window, beyond any newest-20, keep every payload; they do
    not even count as candidates. Only the robot's 21st sim run loses its payload."""
    maker, project, user = await _setup(engine)
    store = LocalArtifactStore(str(tmp_path))
    robot = uuid.uuid4()
    async with maker() as db:
        real = await _runs(db, store, project, user, robot, 25, ended_at=OLD, origin="live")
        sim = await _runs(db, store, project, user, robot, 21, ended_at=OLD)

    async with maker() as db:
        report = await prune_sim_runs(db, store, now=NOW)
        assert report == PruneReport(deleted=1, kept=20)
        assert await _payload_state(db, store, sim[0]) == "deleted"
        for run_id in [*real, *sim[1:]]:
            assert await _payload_state(db, store, run_id) == "live"
            entity = await db.get(GraphEntity, run_id)
            assert entity is not None and "payload_deleted_at" not in entity.attrs


async def test_inputs_and_sim_result_survive_a_payload_delete(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """A payload delete removes the manifest bytes and nothing else: the run record stays live
    with its summary and `attrs.sim` byte-identical, `payload_deleted_at` is the frozen clock,
    the robot's `sim_result` is untouched, and loading the manifest now says the checkpoint is
    gone instead of raising anything else."""
    maker, project, user = await _setup(engine)
    store = LocalArtifactStore(str(tmp_path))
    robot = uuid.uuid4()
    async with maker() as db:
        fact = GraphEntity(
            project_id=project,
            kind=kinds.SIM_RESULT,
            domain=Domain.PROJECT,
            origin="system",
            name="joint_trajectory",
            attrs={"rung": 4, "subject_id": str(robot), "values": {"joint_trajectory": 0.02}},
        )
        db.add(fact)
        await db.commit()
        runs = await _runs(db, store, project, user, robot, 21, ended_at=OLD)
        before = await db.get(GraphEntity, runs[0])
        assert before is not None
        attrs_before = dict(before.attrs)

    async with maker() as db:
        assert (await prune_sim_runs(db, store, now=NOW)).deleted == 1

    async with maker() as db:
        record = await run_store.record(db, project, runs[0])  # still a live run record
        assert record.attrs["payload_deleted_at"] == NOW.isoformat()
        assert {k: v for k, v in record.attrs.items() if k != "payload_deleted_at"} == attrs_before
        assert record.attrs["sim"] == attrs_before["sim"] and record.attrs["sim"]["provider"]
        assert run_store.summary(record).origin == "sim"
        kept_fact = await db.get(GraphEntity, fact.id)
        assert kept_fact is not None and kept_fact.deleted_at is None
        assert kept_fact.attrs == fact.attrs
        with pytest.raises(APIError) as caught:
            await run_store.load(db, store, record, user, ttl_seconds=3600)
        assert caught.value.status_code == 404


async def test_a_pin_committed_between_the_read_and_the_lock_wins(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST …/pin` landing after the candidate read but before the project lock is honoured:
    the run is re-read under the lock, stays pinned, keeps its artifact row and bytes, and the
    stale snapshot never overwrites `attrs` (no lost update)."""
    maker, project, user = await _setup(engine)
    store = LocalArtifactStore(str(tmp_path))
    robot = uuid.uuid4()
    async with maker() as db:
        runs = await _runs(db, store, project, user, robot, 21, ended_at=OLD)
    victim = runs[0]

    async def pin_then_lock(session: AsyncSession, project_id: uuid.UUID) -> None:
        async with maker() as other:  # the pin endpoint: same lock, own commit
            await real_lock(other, project_id)
            row = await other.get(GraphEntity, victim)
            assert row is not None
            row.attrs = {**row.attrs, "pinned": True}
            await other.commit()
        await real_lock(session, project_id)

    monkeypatch.setattr(sim_run_retention, "lock_project", pin_then_lock)
    async with maker() as db:
        assert await prune_sim_runs(db, store, now=NOW) == PruneReport(deleted=0, kept=21)

    async with maker() as db:
        assert await _payload_state(db, store, victim) == "live"
        entity = await db.get(GraphEntity, victim)
        assert entity is not None and entity.attrs["pinned"] is True


async def test_newest_window_is_per_project_even_for_the_same_robot_id(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Two projects, one robot id: A's 21 old runs lose exactly one payload, B's 5 are ranked on
    their own and all survive."""
    maker, project_a, user = await _setup(engine)
    project_b = await _project(maker)
    store = LocalArtifactStore(str(tmp_path))
    robot = uuid.uuid4()
    async with maker() as db:
        runs_a = await _runs(db, store, project_a, user, robot, 21, ended_at=OLD)
        runs_b = await _runs(db, store, project_b, user, robot, 5, ended_at=OLD)

    async with maker() as db:
        assert await prune_sim_runs(db, store, now=NOW) == PruneReport(deleted=1, kept=25)
        assert await _payload_state(db, store, runs_a[0]) == "deleted"
        for run_id in [*runs_a[1:], *runs_b]:
            assert await _payload_state(db, store, run_id) == "live"


async def test_a_checkpoint_id_naming_another_projects_artifact_cannot_delete_it(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """A run in project A whose `attrs.checkpoint_id` points at project B's artifact (a recent
    run, no candidate itself): B's artifact row keeps `retained`/`deleted_at` and its bytes stay
    in the store."""
    maker, project_a, user = await _setup(engine)
    project_b = await _project(maker)
    store = LocalArtifactStore(str(tmp_path))
    async with maker() as db:
        run_b = await _run(db, store, project_b, user, uuid.uuid4(), ended_at=RECENT)
        entity_b = await db.get(GraphEntity, run_b)
        assert entity_b is not None
        foreign = entity_b.attrs["checkpoint_id"]
        run_a = await _run(db, store, project_a, user, uuid.uuid4(), ended_at=OLD)
        entity_a = await db.get(GraphEntity, run_a)
        assert entity_a is not None
        entity_a.attrs = {**entity_a.attrs, "checkpoint_id": foreign}
        await db.commit()

    async with maker() as db:
        await prune_sim_runs(db, store, now=NOW, keep_newest=0)

    async with maker() as db:
        artifact = await db.get(Artifact, uuid.UUID(foreign))
        assert artifact is not None
        assert artifact.deleted_at is None and artifact.retained is True
        assert (store.root / foreign).exists()
        assert await _payload_state(db, store, run_b) == "live"


async def test_a_deleted_project_is_skipped_while_others_are_pruned(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Project A soft-deleted with candidates, project B live with candidates: B loses one
    payload, A's runs are left exactly as they were, and the pass does not raise."""
    maker, project_a, user = await _setup(engine)
    project_b = await _project(maker)
    store = LocalArtifactStore(str(tmp_path))
    async with maker() as db:
        runs_a = await _runs(db, store, project_a, user, uuid.uuid4(), 21, ended_at=OLD)
        runs_b = await _runs(db, store, project_b, user, uuid.uuid4(), 21, ended_at=OLD)
        gone = await db.get(Project, project_a)
        assert gone is not None
        gone.deleted_at = NOW - DAY
        await db.commit()

    async with maker() as db:
        assert (await prune_sim_runs(db, store, now=NOW)).deleted == 1
        assert await _payload_state(db, store, runs_b[0]) == "deleted"
        for run_id in [*runs_a, *runs_b[1:]]:
            assert await _payload_state(db, store, run_id) == "live"


def test_cron_is_registered() -> None:
    settings = build_worker_settings(
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            supabase_jwt_secret="test-only",
            redis_url="redis://localhost:6379",
        )
    )
    crons = {job.coroutine.__name__: job for job in settings.cron_jobs}  # type: ignore[attr-defined]
    prune = crons["prune_sim_runs_job"]
    assert prune.hour == {3} and prune.minute == {17} and prune.second == 0
    assert prune.run_at_startup is False
