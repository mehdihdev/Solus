"""SOLUSDEV-167 acceptance #8: before/after call counts for a realistic session.

The "before" column is MEASURED, never asserted — the same scripted session runs
against the code with the freshness gate and single-flight disabled, then with
them on. An asserted before-number rots into a stale constant the first time
anything changes; a measured one cannot.

Run it for the headline number:  make onshape-budget
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import respx
from conftest import requires_occt
from fixtures.onshape_fake import FakeOnshape, Meter
from solus_api.connectors.httpcache import CacheStore, InMemoryCacheStore
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import refresh_secret_ref
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.connectors.worker import execute_source_sync
from solus_api.models import Project, Source, SourceStatus, SourceType, Team
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

#: The before/after session drives real syncs, so it needs the STEP reader.
#: Without OCCT both columns collapse to the same failed-sync number and the
#: headline saving reads as zero.
pytestmark = requires_occt

DID = "dA"


@pytest.fixture
async def onshape() -> AsyncIterator[tuple[FakeOnshape, Meter]]:
    fake = FakeOnshape()
    async with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=fake)
        yield fake, Meter(router)


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, InMemorySecretStore]:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        secret_ref = f"source/{uuid.uuid4()}/onshape"
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={"documents": [DID]},
            secret_ref=secret_ref,
            account_external_id="acct-1",
        )
        db.add(source)
        await db.commit()
        source_id = source.id
    store = InMemorySecretStore()
    await store.put(secret_ref, "tok")
    await store.put(refresh_secret_ref(secret_ref), "rt")
    return source_id, store


def _registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(
        "onshape",
        lambda: OnshapeConnector(client_id="cid", client_secret="sec", poll_interval=0.0),
    )
    return registry


async def _session(
    maker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    secrets: InMemorySecretStore,
    cache: CacheStore | None,
    *,
    force: bool = False,
) -> None:
    """One realistic stretch of work, mirroring what the tester actually did:
    connect-and-sync once, then keep working — a few more triggers while nothing
    upstream has changed, and a burst of simultaneous ones (several widgets and
    a Sync-now click landing together)."""

    async def sync() -> None:
        await execute_source_sync(
            source_id=source_id,
            sessionmaker=maker,
            registry=_registry(),
            secret_store=secrets,
            store=cache,
            force=force,
        )

    await sync()  # first connect + full ingest
    await sync()  # user clicks Sync now; nothing changed
    await sync()  # and again
    await asyncio.gather(*(sync() for _ in range(5)))  # a simultaneous burst


async def test_session_cost_before_and_after(onshape: Any, maker: Any, capsys: Any) -> None:
    fake, meter = onshape

    # BEFORE: the pre-ticket behaviour — no freshness gate, no coalescing.
    source_id, secrets = await _seed(maker)
    meter.reset()
    # `force=True` bypasses the freshness gate, which IS the pre-ticket path:
    # `run_sync` never consulted `detect_changes`. Combined with no shared store
    # (nothing coalesces), this column is the code as it actually behaved.
    await _session(maker, source_id, secrets, cache=None, force=True)
    before = meter.counted
    before_routes = dict(meter.by_route)

    # AFTER: the shared store is present, so the burst collapses.
    source_id, secrets = await _seed(maker)
    meter.reset()
    await _session(maker, source_id, secrets, cache=InMemoryCacheStore())
    after = meter.counted
    after_routes = dict(meter.by_route)

    saved = before - after
    pct = (saved / before * 100) if before else 0.0
    with capsys.disabled():
        print("\n" + "=" * 62)
        print("SOLUSDEV-167 — Onshape calls for one realistic session")
        print("=" * 62)
        print(f"  before (no gate, no coalescing): {before:>4} quota-counted calls")
        print(f"  after                          : {after:>4} quota-counted calls")
        print(f"  saved                          : {saved:>4}  ({pct:.0f}%)")
        print(f"\n  before by route: {before_routes}")
        print(f"  after  by route: {after_routes}")
        print(
            f"\n  Onshape's quota is ANNUAL: 2500/user/year on Free/Standard."
            f"\n  This session is {before / 2500 * 100:.1f}% of a YEAR before,"
            f" {after / 2500 * 100:.1f}% after."
        )
        print(
            "\n  NOTE: the before column UNDERSTATES the real saving. It already"
            "\n  includes this ticket's other reductions — the translation poll"
            "\n  backs off (9 polls/export here, was a flat 30) and the probe"
            "\n  reads its workspace from the cursor. Against the code as it"
            "\n  actually shipped the before column would be materially higher."
        )
        print("=" * 62)

    # Only the AFTER column is asserted; the before column is reported, never
    # pinned, so it cannot rot into a stale constant.
    assert after < before, "the session must cost less than it used to"
    assert after_routes.get("translations_start", 0) == 1, (
        "one document, one change: exactly one export should ever be requested"
    )
