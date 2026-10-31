"""SOLUSDEV-321 P0-T5 — the graph-changed fan-out (`graph/graph_changed_fanout.py`).

`LiveHub.on_graph_changed` holds ONE callback; the fan-out is that callback for every
consumer `graph_changed_callbacks` registers — the budgets trigger, the project-card
invalidation, the envelope cache's, and later phases'. Each runs in order under a time bound, a
failure or a timeout is logged and never stops the rest, and the synchronous `close()` the
lifespan's exit stack calls closes every consumer that can be closed, one failing close never
skipping the next.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import pytest
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.graph.graph_changed_fanout import (
    FANOUT_JOB_IDS,
    GraphChangedFanout,
    graph_changed_callbacks,
)
from solus_api.graph.live import LiveHub, graph_changed_frame
from solus_api.livebench.findings.envelopes import Envelope, EnvelopeCache, EnvelopeKey
from solus_api.services.budgets import BudgetTrigger
from solus_api.services.physical_robots import GraphChangeCounts
from sqlalchemy.ext.asyncio import async_sessionmaker

_LOGGER = "solus.graph.graph_changed_fanout"


class _Closable:
    """A consumer with a synchronous `close()`, like the budgets trigger."""

    def __init__(self) -> None:
        self.seen: list[uuid.UUID] = []
        self.closed = 0

    async def __call__(self, project_id: uuid.UUID) -> None:
        self.seen.append(project_id)

    def close(self) -> None:
        self.closed += 1


class _BrokenCloser(_Closable):
    def close(self) -> None:
        super().close()
        raise RuntimeError("close exploded")


async def _explodes(project_id: uuid.UUID) -> None:
    raise RuntimeError(f"consumer exploded for {project_id}")


async def _publish_changed(hub: LiveHub, project_id: uuid.UUID) -> None:
    frame = graph_changed_frame(
        project_id=project_id,
        source_id=None,
        sync_id=None,
        counts=GraphChangeCounts(entities_created=1),
        at="now",
    )
    await hub.publish(project_id, frame)


async def test_budget_trigger_still_fires(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Behind the fan-out — and behind a first consumer that raises — a published
    `graph.changed` still queues the project's budgets recompute, once."""
    monkeypatch.setattr("solus_api.services.budgets.DEBOUNCE_SECONDS", 0.0)
    enqueued: list[tuple[str, str]] = []

    async def enqueue(job: str, project: str) -> None:
        enqueued.append((job, project))

    # The queue path never opens a session: an unbound sessionmaker is enough.
    callbacks = graph_changed_callbacks(
        sessionmaker=async_sessionmaker(), enqueue=enqueue, store=InMemoryCacheStore()
    )
    assert isinstance(callbacks[0], BudgetTrigger)
    fanout = GraphChangedFanout([_explodes, *callbacks])
    hub = LiveHub(None)
    hub.on_graph_changed = fanout
    project_id = uuid.uuid4()

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        await _publish_changed(hub, project_id)
        await asyncio.sleep(0.05)
    fanout.close()

    assert enqueued == [("recompute_budgets", str(project_id))]
    assert "consumer exploded" in caplog.text


async def test_close_closes_every_closable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`close()` reaches every consumer that has one — past one whose close raises — skips the
    ones that have none, and a real trigger's pending recompute dies with it; also on the
    registration list itself."""
    ran: list[uuid.UUID] = []

    async def recompute(project_id: uuid.UUID) -> None:
        ran.append(project_id)

    async def plain(project_id: uuid.UUID) -> None:
        return None

    first, broken, last = _Closable(), _BrokenCloser(), _Closable()
    fanout = GraphChangedFanout([first, BudgetTrigger(recompute, delay=0.05), broken, plain, last])
    project_id = uuid.uuid4()
    await fanout(project_id)
    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        fanout.close()  # never raises past the one that exploded
    await asyncio.sleep(0.1)

    assert first.seen == broken.seen == last.seen == [project_id]
    assert first.closed == broken.closed == last.closed == 1
    assert ran == []  # the debounced recompute was cancelled by the trigger's close()
    (record,) = [r for r in caplog.records if r.name == _LOGGER]
    assert "_BrokenCloser" in record.getMessage() and record.exc_info is not None

    monkeypatch.setattr("solus_api.services.budgets.DEBOUNCE_SECONDS", 0.05)
    enqueued: list[tuple[str, str]] = []

    async def enqueue(job: str, project: str) -> None:
        enqueued.append((job, project))

    registered = GraphChangedFanout(
        graph_changed_callbacks(
            sessionmaker=async_sessionmaker(), enqueue=enqueue, store=InMemoryCacheStore()
        )
    )
    await registered(project_id)
    registered.close()
    await asyncio.sleep(0.1)
    assert enqueued == []


async def test_one_failing_callback_does_not_stop_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    before, after = _Closable(), _Closable()
    fanout = GraphChangedFanout([before, _explodes, after])
    project_id = uuid.uuid4()

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        await fanout(project_id)  # never raises into the publishing hub

    assert before.seen == after.seen == [project_id]
    (record,) = [r for r in caplog.records if r.name == _LOGGER]
    assert record.exc_info is not None
    assert str(project_id) in record.getMessage()


async def test_hung_callback_is_bounded_and_others_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A consumer that never returns — a stalled store's DEL — cannot hang the publisher: it is
    timed out, logged like a failure, and the next consumer still runs."""

    async def hangs(project_id: uuid.UUID) -> None:
        await asyncio.Event().wait()  # never set

    after = _Closable()
    fanout = GraphChangedFanout([hangs, after], timeout=0.05)
    project_id = uuid.uuid4()
    started = time.monotonic()

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        await fanout(project_id)

    assert time.monotonic() - started < 0.5
    assert after.seen == [project_id]
    (record,) = [r for r in caplog.records if r.name == _LOGGER]
    assert "hangs" in record.getMessage() and str(project_id) in record.getMessage()
    assert record.exc_info is not None and record.exc_info[0] is TimeoutError


async def test_the_envelope_cache_passed_in_is_the_one_a_change_drops() -> None:
    """P2-T3: main.py hands the fan-out the ONE `EnvelopeCache` the window evaluator reads
    through, so a graph change resets that very instance — its full-index warning is logged once
    per instance and re-armed by the drop. The worker passes none and gets a cache of its own."""
    dropped: list[uuid.UUID] = []

    class _Spy(EnvelopeCache):
        async def invalidate(self, project_id: uuid.UUID) -> None:
            dropped.append(project_id)
            await super().invalidate(project_id)

    async def enqueue(job: str, project: str) -> None:
        return None

    store = InMemoryCacheStore()
    shared = _Spy(store)
    fanout = GraphChangedFanout(
        graph_changed_callbacks(
            sessionmaker=async_sessionmaker(), enqueue=enqueue, store=store, envelopes=shared
        )
    )
    project = uuid.uuid4()

    await fanout(project)
    fanout.close()

    assert dropped == [project]


async def test_the_registered_list_also_drops_the_projects_cached_envelopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2-T1: the list both processes install drops, through the envelope cache's invalidator,
    that project's cached part envelopes on a published `graph.changed` — another project's stay
    — with the budgets recompute still queued. P3-T3 appends the checker trigger last (its 10 s
    debounce runs nothing here), and each job a callback enqueues has its own stable id."""
    monkeypatch.setattr("solus_api.services.budgets.DEBOUNCE_SECONDS", 0.0)
    enqueued: list[tuple[str, str]] = []

    async def enqueue(job: str, project: str) -> None:
        enqueued.append((job, project))

    store = InMemoryCacheStore()
    callbacks = graph_changed_callbacks(
        sessionmaker=async_sessionmaker(), enqueue=enqueue, store=store
    )
    assert len(callbacks) == 4 and isinstance(callbacks[-1], BudgetTrigger)
    assert {job: job_id("p") for job, job_id in FANOUT_JOB_IDS.items()} == {
        "recompute_budgets": "recompute_budgets:p",
        "run_matrix_checkers": "run_matrix_checkers:p",
    }
    cache, part = EnvelopeCache(store), uuid.uuid4()
    envelope = Envelope(part_id=part, quantity="current", bounds_source={}, confidence=1.0)
    mine, theirs = (EnvelopeKey(uuid.uuid4(), part, "current", 1, None, None) for _ in range(2))
    for key in (mine, theirs):
        await cache.put(key, envelope)
    fanout = GraphChangedFanout(callbacks)

    await fanout(mine.project_id)
    await asyncio.sleep(0.05)
    fanout.close()

    assert await cache.get(mine) is None
    assert await cache.get(theirs) == envelope
    assert enqueued == [("recompute_budgets", str(mine.project_id))]
