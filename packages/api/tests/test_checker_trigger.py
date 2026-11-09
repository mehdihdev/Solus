"""SOLUSDEV-321 P3-T3 — the checker trigger (`checkers/checker_trigger.py`).

After every graph change the matrix runs ONCE per project, 10 s after the last change: as the ARQ
job `run_matrix_checkers` when the host has a queue, or in-process when it has none. The job opens
its own session, runs every cell and commits. A failed run is logged, never raised. The budgets
recompute still fires beside it. Both jobs register with `keep_result=0` under their own stable
ids (R46), so each comes back after a run.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterable
from typing import Any, cast

import pytest
from arq.worker import Function
from fastapi import FastAPI
from fixtures.fake_arm import seed_fake_arm
from solus_api import main
from solus_api.checkers import checker_trigger
from solus_api.checkers.checker_trigger import (
    DEBOUNCE_SECONDS,
    MATRIX_JOB,
    make_checker_trigger,
    matrix_job_id,
    run_matrix_checkers,
)
from solus_api.connectors import worker
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.core.config import Settings
from solus_api.graph import kinds
from solus_api.graph.graph_changed_fanout import GraphChangedFanout, graph_changed_callbacks
from solus_api.graph.live import LiveHub
from solus_api.graph.read_scope import GraphReadScope, bind_scope
from solus_api.models import (
    GraphEntity,
    Membership,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
)
from solus_api.services.budgets import JOB_NAME as BUDGETS_JOB
from solus_api.services.budgets import budget_job_id
from solus_contracts.relations import MatrixCell
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_LOGGER = "solus.checkers.checker_trigger"


class _ArqQueue:
    """ArqRedis as far as a stable id goes: arq refuses an id while its job waits, and after the
    job ran while its result is kept (`keep_result_s` other than 0; None is the worker's hour).
    Enough of a store for the fan-out's cache drops."""

    def __init__(self, functions: Iterable[Function]) -> None:
        self.keep = {function.name: function.keep_result_s for function in functions}
        self.waiting: dict[str, str] = {}
        self.kept: set[str] = set()
        self.accepted: list[tuple[str, str]] = []

    async def enqueue_job(self, name: str, *args: str, _job_id: str) -> object | None:
        if _job_id in self.waiting or _job_id in self.kept:
            return None
        self.waiting[_job_id] = name
        self.accepted.append((name, _job_id))
        return object()

    def run_all(self) -> None:
        """Every waiting job runs; arq keeps the result of each whose function keeps one."""
        self.kept |= {job_id for job_id, name in self.waiting.items() if self.keep[name] != 0}
        self.waiting.clear()

    async def get(self, key: str) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None


def _worker_functions(settings: Settings) -> dict[str, Function]:
    functions = cast(Any, worker.build_worker_settings(settings)).functions
    return {f.name: f for f in functions if isinstance(f, Function)}


def _both_ids(project: uuid.UUID) -> list[tuple[str, str]]:
    return [(BUDGETS_JOB, budget_job_id(str(project))), (MATRIX_JOB, matrix_job_id(str(project)))]


async def _start_worker(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, redis: _ArqQueue
) -> dict[str, Any]:
    """The worker's startup around `redis`, its I/O stubbed, with both debounces at 0."""

    class _Engine:
        async def dispose(self) -> None:
            return None

    async def no_relay(self: LiveHub) -> None:
        return None

    monkeypatch.setattr("solus_api.core.config.Settings", lambda: settings)
    monkeypatch.setattr(worker, "build_engine", lambda _url: _Engine())
    monkeypatch.setattr(worker, "build_integration_cache", lambda *_a, **_k: object())
    monkeypatch.setattr(worker, "build_registry", lambda *_a, **_k: object())
    monkeypatch.setattr(worker, "build_secret_store", lambda *_a, **_k: object())
    monkeypatch.setattr("solus_api.storage.build_artifact_store", lambda _s: object())
    monkeypatch.setattr(LiveHub, "start", no_relay)
    monkeypatch.setattr("solus_api.services.budgets.DEBOUNCE_SECONDS", 0.0)
    monkeypatch.setattr(checker_trigger, "DEBOUNCE_SECONDS", 0.0)
    ctx: dict[str, Any] = {"redis": redis}
    await worker._on_startup(ctx)
    return ctx


async def _trigger_project(db: AsyncSession) -> uuid.UUID:
    """A project holding the fake arm, committed."""
    tag = uuid.uuid4().hex[:8]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@ex.com")
    team = Team(name=f"trigger-{tag}")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=f"trigger-{tag}", created_by=user.id)
    db.add(project)
    await db.flush()
    await seed_fake_arm(db, project.id, user_id=None)
    await db.commit()
    return project.id


async def test_debounce_10s_per_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changes inside the window run the matrix ONCE for a project, after the last change; another
    project's are its own. The window is 10 s, read when the trigger is built."""
    enqueued: list[tuple[str, str]] = []

    async def enqueue(job: str, project: str) -> None:
        enqueued.append((job, project))

    assert DEBOUNCE_SECONDS == 10.0
    monkeypatch.setattr(checker_trigger, "DEBOUNCE_SECONDS", 0.2)
    trigger = make_checker_trigger(sessionmaker=async_sessionmaker(), enqueue=enqueue)
    mine, theirs = uuid.uuid4(), uuid.uuid4()

    await trigger(mine)
    await asyncio.sleep(0.1)
    await trigger(mine)  # inside the window: the first run is dropped, the window restarts
    await trigger(theirs)
    await asyncio.sleep(0.15)
    assert enqueued == []  # past the first change's window, inside the second's
    await asyncio.sleep(0.3)
    trigger.close()

    assert sorted(enqueued) == sorted([(MATRIX_JOB, str(mine)), (MATRIX_JOB, str(theirs))])


async def test_a_queue_that_refuses_the_job_is_logged_as_the_matrix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """m6 (P3-T3 fix 1): when the queue refuses the matrix job, the log says so under the
    trigger's own name, answering "why did this project's checks not run", never as "budget
    trigger failed"."""

    async def down(job: str, project: str) -> None:
        raise ConnectionError("the queue is down")

    trigger = make_checker_trigger(sessionmaker=async_sessionmaker(), enqueue=down, delay=0.0)
    project = uuid.uuid4()

    with caplog.at_level(logging.ERROR):
        await trigger(project)
        await asyncio.sleep(0.05)
    trigger.close()

    assert f"matrix run not queued project={project}" in caplog.text
    assert "budget trigger failed" not in caplog.text


async def test_budget_trigger_still_fires(
    app: FastAPI, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beside the matrix trigger, a graph change still recomputes the budgets, in both sync modes.
    Queued: the API's `enqueue` gives each job its own stable id, and after a run a change
    enqueues both again. Inline (`sync_inline`, no Redis): both jobs run in-process."""
    monkeypatch.setattr("solus_api.services.budgets.DEBOUNCE_SECONDS", 0.0)
    monkeypatch.setattr(checker_trigger, "DEBOUNCE_SECONDS", 0.0)
    queue = _ArqQueue(_worker_functions(settings).values())
    app.state.arq_pool = queue
    queued = GraphChangedFanout(
        graph_changed_callbacks(
            sessionmaker=async_sessionmaker(),
            enqueue=main._enqueue_budgets_job(app),
            store=InMemoryCacheStore(),
        )
    )
    project = uuid.uuid4()

    await queued(project)
    await asyncio.sleep(0.05)
    queue.run_all()
    await queued(project)
    await asyncio.sleep(0.05)
    queued.close()

    assert sorted(queue.accepted) == sorted(_both_ids(project) * 2)

    ran: list[tuple[str, str]] = []

    async def recompute(ctx: dict[str, Any], project_id: str) -> None:
        ran.append((BUDGETS_JOB, project_id))

    async def matrix(ctx: dict[str, Any], project_id: str) -> None:
        ran.append((MATRIX_JOB, project_id))

    monkeypatch.setattr("solus_api.services.budgets.recompute_budgets", recompute)
    monkeypatch.setattr(checker_trigger, "run_matrix_checkers", matrix)
    inline = GraphChangedFanout(
        graph_changed_callbacks(
            sessionmaker=async_sessionmaker(), enqueue=None, store=InMemoryCacheStore()
        )
    )
    await inline(project)
    await asyncio.sleep(0.05)
    inline.close()

    assert sorted(ran) == sorted([(BUDGETS_JOB, str(project)), (MATRIX_JOB, str(project))])


async def test_keep_result_zero_for_matrix_and_budgets(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both graph-change jobs register with `keep_result=0`, one try and their bounds (300 s for
    the matrix, as `test_matrix_runner` measures against), and the worker's own `enqueue` gives
    each its stable id: after a run, a change enqueues both again."""
    functions = _worker_functions(settings)
    for name, timeout in ((MATRIX_JOB, 300), (BUDGETS_JOB, 120)):
        registered = functions[name]
        assert (registered.keep_result_s, registered.timeout_s, registered.max_tries) == (
            0,
            timeout,
            1,
        )
    queue = _ArqQueue(functions.values())
    ctx = await _start_worker(settings, monkeypatch, queue)
    fanout = ctx["graph_hub"].on_graph_changed
    project = uuid.uuid4()

    await fanout(project)
    await asyncio.sleep(0.05)
    queue.run_all()
    await fanout(project)
    await asyncio.sleep(0.05)
    await worker._on_shutdown(ctx)

    assert sorted(queue.accepted) == sorted(_both_ids(project) * 2)


async def test_the_job_runs_every_cell_in_its_own_session_and_commits(
    db: AsyncSession,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`run_matrix_checkers(ctx, project_id)` opens its own session from `ctx["sessionmaker"]`,
    runs every cell and commits: another session sees the standing infos. A failing run is rolled
    back and logged, and the job returns."""
    project_id = await _trigger_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    await run_matrix_checkers({"sessionmaker": maker}, str(project_id))

    cells = await db.scalars(
        select(GraphEntity.attrs["matrix_cell"].astext).where(
            GraphEntity.project_id == project_id, GraphEntity.kind == kinds.FINDING
        )
    )
    # m9 (P3-T3 fix 1): the arm's standing infos come from every cell — the job ran them all — and
    # the job's own session committed them.
    assert set(cells) == {cell.value for cell in MatrixCell}

    async def _broken_run(*_: object, **__: object) -> None:
        raise RuntimeError("matrix exploded")

    monkeypatch.setattr(checker_trigger, "run_matrix", _broken_run)
    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        await run_matrix_checkers({"sessionmaker": maker}, str(project_id))
    assert f"matrix run failed project={project_id}" in caplog.text


async def test_the_job_judges_the_shared_view_whoever_scheduled_it(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """A change published inside a request carries that user's personal read scope (a branch
    view) into the debounced task with it. The job still judges the project's shared view, as the
    worker does: what it writes is shared by everyone."""
    project_id = await _trigger_project(db)
    project = await db.get(Project, project_id)
    assert project is not None
    base, branch = (
        Source(
            project_id=project_id,
            team_id=project.team_id,
            type=SourceType.LOCAL,
            name=name,
            status=SourceStatus.CONNECTED,
            config={},
        )
        for name in ("fw", "fw on a branch")
    )
    db.add_all([base, branch])
    await db.flush()
    code = (
        await db.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id, GraphEntity.kind == kinds.CODE_FILE
            )
        )
    ).one()
    code.source_id = base.id  # the arm's code comes from `base`, which a branch view swaps out
    await db.commit()
    maker = async_sessionmaker(engine, expire_on_commit=False)

    with bind_scope(GraphReadScope(project_id, replacements=((base.id, branch.id),))):
        await run_matrix_checkers({"sessionmaker": maker}, str(project_id))

    commanded = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.FINDING,
            GraphEntity.attrs["rule_id"].astext == "commanded_range_vs_joint_limit",
        )
    )
    assert [finding.attrs["subjects"] for finding in commanded] == [[str(code.id)]]
