"""SOLUSDEV-321 P0-T5 — the ONE list of what runs on every published `graph.changed`.

`LiveHub.on_graph_changed` holds a single callback; `GraphChangedFanout` makes it many. Each
callback is awaited in order under `timeout` — the hub bounds its own Redis publish the same, and
these run inline in every graph-writing request and sync — and a failure or a timeout is logged
while the rest still run. `close()` — synchronous, for `AsyncExitStack.callback` like the budgets
trigger's — closes every callback that has a `close()`, each isolated the same way. Both processes
install the same list: `main.py`'s lifespan and `connectors/worker.py:_on_startup` call
`graph_changed_callbacks`. A later phase that must react to graph changes (P2's envelope cache,
P3's checker trigger) appends its callback there and never touches either host again.
`FANOUT_JOB_IDS` is how both hosts' `enqueue` name the stable ARQ id of each job a callback
enqueues (SOLUSDEV-321 P3-T3, R46).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from solus_api.agent.project_card import ProjectCardCache
from solus_api.checkers.checker_trigger import MATRIX_JOB, make_checker_trigger, matrix_job_id
from solus_api.livebench.findings.envelopes import EnvelopeCache
from solus_api.services.budgets import JOB_NAME as BUDGETS_JOB
from solus_api.services.budgets import budget_job_id, make_budget_trigger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.connectors.httpcache import CacheStore

logger = logging.getLogger("solus.graph.graph_changed_fanout")

#: Each callback's bound: the same as the hub's own Redis publish (graph/live.py).
CALLBACK_TIMEOUT_SECONDS: Final = 2.0
#: Each job a callback enqueues by name → its stable ARQ id (R46). Both hosts' `enqueue` pass
#: `_job_id=FANOUT_JOB_IDS[job_name](project_id)`, so one job's queued (or kept) id never refuses
#: the other's.
FANOUT_JOB_IDS: Final[Mapping[str, Callable[[str], str]]] = {
    BUDGETS_JOB: budget_job_id,
    MATRIX_JOB: matrix_job_id,
}

GraphChangedCallback = Callable[[uuid.UUID], Awaitable[None]]


class GraphChangedFanout:
    """The hub's one `on_graph_changed`: every registered callback, in order, each bounded."""

    def __init__(
        self,
        callbacks: Sequence[GraphChangedCallback],
        *,
        timeout: float = CALLBACK_TIMEOUT_SECONDS,
    ) -> None:
        self._callbacks = tuple(callbacks)
        self._timeout = timeout

    async def __call__(self, project_id: uuid.UUID) -> None:
        for callback in self._callbacks:
            try:
                await asyncio.wait_for(callback(project_id), self._timeout)
            except Exception:  # noqa: BLE001 — a timeout too: one consumer never starves the next
                logger.exception(
                    "graph.changed callback %s failed project=%s",
                    _callback_name(callback),
                    project_id,
                )

    def close(self) -> None:
        for callback in self._callbacks:
            close = getattr(callback, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception:  # noqa: BLE001 — one consumer's close never skips the next
                logger.exception(
                    "graph.changed callback %s failed to close", _callback_name(callback)
                )


def _callback_name(callback: object) -> str:
    return str(getattr(callback, "__qualname__", repr(callback)))


def graph_changed_callbacks(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    enqueue: Callable[[str, str], Awaitable[Any]] | None,
    store: CacheStore,
    envelopes: EnvelopeCache | None = None,
) -> list[GraphChangedCallback]:
    """What every `graph.changed` runs, in order: the debounced budgets recompute (SOLUSDEV-320
    resolution 18; queued by name through `enqueue`, else inline), dropping the project's cached
    card from `store` (P0-T5), then dropping its cached part envelopes (P2-T1: a scene or an
    expected value changed under them; a config bump changes their key instead) — through
    `envelopes` when the host shares its one cache with the window evaluator (P2-T3: the cache's
    log-once state is per instance), else a cache of its own on `store` — and last the debounced
    matrix run (P3-T3; queued by name like the budgets, else inline). Append later consumers
    here."""
    return [
        make_budget_trigger(sessionmaker=sessionmaker, enqueue=enqueue),
        ProjectCardCache(store).invalidator(),
        (envelopes if envelopes is not None else EnvelopeCache(store)).invalidator(),
        make_checker_trigger(sessionmaker=sessionmaker, enqueue=enqueue),
    ]
