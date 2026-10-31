"""SOLUSDEV-321 P3-T3 — the matrix runs after every graph change (R49).

`make_checker_trigger` is a `graph.changed` callback (`graph/graph_changed_fanout.py`). A change
schedules ONE run per project, `DEBOUNCE_SECONDS` after its last change; the debounce is the
budgets recompute's `BudgetTrigger`. The run is the ARQ job `run_matrix_checkers`, enqueued by
name when the host has a queue (the host gives it its stable id, `matrix_job_id`, R46), or run
in-process when it has none (`sync_inline`, no Redis). A change carries only its project id, so
every run runs every cell. The job opens its own session from the host's sessionmaker and
commits; a failed run is rolled back and logged, never raised into the fan-out or the worker.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.checkers.matrix_runner import run_matrix
from solus_api.services.budgets import BudgetTrigger

logger = logging.getLogger("solus.checkers.checker_trigger")

MATRIX_JOB: Final = "run_matrix_checkers"
#: A project's changes inside this window run the matrix once, after the last of them (R49).
DEBOUNCE_SECONDS: Final = 10.0


def matrix_job_id(project_id: str) -> str:
    """ARQ's dedupe key for the matrix job: one queued-or-running run per project across every
    API replica and the worker, never the budgets job's id (R46)."""
    return f"{MATRIX_JOB}:{project_id}"


async def run_matrix_checkers(ctx: dict[str, Any], project_id: str) -> None:
    """The ARQ job, and the inline path: every cell over one project, in a session of its own,
    committed. It judges the project's shared view even when the change that scheduled it was
    published under one user's branch view (the debounced task inherits the request's context):
    `run_matrix` binds that view whenever it writes. A failed run is rolled back and logged; a
    malformed id is the caller's bug and raises."""
    key = uuid.UUID(project_id)
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        try:
            await run_matrix(session, key)
            await session.commit()
        except Exception:  # noqa: BLE001 — a derived result must never poison the worker
            await session.rollback()
            logger.exception("matrix run failed project=%s", key)


def make_checker_trigger(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    enqueue: Callable[[str, str], Awaitable[Any]] | None,
    delay: float | None = None,
) -> BudgetTrigger:
    """The `graph.changed` callback: enqueue `run_matrix_checkers` by name when the host has a
    queue (`enqueue(job_name, project_id)`), else run it in-process. `delay` defaults to
    `DEBOUNCE_SECONDS`, read here."""

    async def run(project_id: uuid.UUID) -> None:
        if enqueue is None:
            await run_matrix_checkers({"sessionmaker": sessionmaker}, str(project_id))
            return
        try:
            await enqueue(MATRIX_JOB, str(project_id))
        except Exception:  # noqa: BLE001 — a queue that is down never fails the fan-out (m6)
            logger.exception("matrix run not queued project=%s", project_id)

    return BudgetTrigger(run, delay=DEBOUNCE_SECONDS if delay is None else delay)
