"""SOLUSDEV-167: the inbound provider webhook receiver.

This endpoint is UNAUTHENTICATED by design — a provider cannot hold a Solus
session — so its security is entirely in the URL token and in what it refuses to
do with the body. These tests are the proof of both.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from solus_api.connectors.webhook_token import WEBHOOK_TOKEN_KEY, mint_webhook_token
from solus_api.models import Project, Source, SourceStatus, SourceType, Team
from solus_api.routers.webhooks import WEBHOOK_DELIVERIES_PER_DAY
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(
    maker: async_sessionmaker[AsyncSession],
    *,
    status: SourceStatus = SourceStatus.CONNECTED,
    register: bool = True,
) -> tuple[uuid.UUID, str]:
    token, digest = mint_webhook_token()
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=status,
            config={WEBHOOK_TOKEN_KEY: digest} if register else {},
        )
        db.add(source)
        await db.commit()
        return source.id, token


async def test_a_valid_delivery_is_accepted(client: AsyncClient, maker: Any) -> None:
    source_id, token = await _seed(maker)

    resp = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}", json={"event": "whatever"}
    )

    assert resp.status_code == 204


async def test_a_wrong_token_is_rejected(client: AsyncClient, maker: Any) -> None:
    source_id, _ = await _seed(maker)
    other, _ = mint_webhook_token()

    resp = await client.post(f"/api/v1/webhooks/onshape/{source_id}/{other}", json={})

    assert resp.status_code == 404


async def test_an_unregistered_source_rejects_every_token(client: AsyncClient, maker: Any) -> None:
    """Fail closed. A source that never registered a webhook has no digest, so
    knowing its id must not be enough to poke it."""
    source_id, token = await _seed(maker, register=False)

    resp = await client.post(f"/api/v1/webhooks/onshape/{source_id}/{token}", json={})

    assert resp.status_code == 404


async def test_an_unknown_source_is_indistinguishable_from_a_bad_token(
    client: AsyncClient, maker: Any
) -> None:
    """No existence oracle: a distinguishable response would let anyone
    enumerate which source ids are real."""
    source_id, token = await _seed(maker)
    missing = uuid.uuid4()

    real_but_wrong = await client.post(f"/api/v1/webhooks/onshape/{source_id}/nope", json={})
    absent = await client.post(f"/api/v1/webhooks/onshape/{missing}/{token}", json={})

    assert real_but_wrong.status_code == absent.status_code == 404
    assert real_but_wrong.json() == absent.json()


async def test_a_token_is_bound_to_its_provider(client: AsyncClient, maker: Any) -> None:
    """The provider segment is checked, so a token minted for one integration
    cannot be replayed against another's endpoint."""
    source_id, token = await _seed(maker)

    resp = await client.post(f"/api/v1/webhooks/github/{source_id}/{token}", json={})

    assert resp.status_code == 404


async def test_a_token_cannot_reach_another_teams_source(client: AsyncClient, maker: Any) -> None:
    """Cross-tenant. The URL resolves to exactly ONE source, so team A's token
    cannot cause a probe of team B's source — which is what body-matching on a
    shared document id WOULD have allowed."""
    a_id, a_token = await _seed(maker)
    b_id, _ = await _seed(maker)

    resp = await client.post(f"/api/v1/webhooks/onshape/{b_id}/{a_token}", json={})

    assert resp.status_code == 404


async def test_an_oversized_body_is_refused_before_it_is_buffered(
    client: AsyncClient, maker: Any
) -> None:
    source_id, token = await _seed(maker)

    resp = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}",
        content=b"x" * (64 * 1024 + 1),
        headers={"Content-Type": "application/octet-stream"},
    )

    assert resp.status_code == 413


async def test_a_garbage_body_is_rejected(client: AsyncClient, maker: Any) -> None:
    """The approved bounded Onshape envelope refuses malformed JSON."""
    source_id, token = await _seed(maker)

    resp = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}",
        content=b"\x00\xffnot json at all",
        headers={"Content-Type": "application/octet-stream"},
    )

    assert resp.status_code == 400


async def test_a_disconnected_source_is_not_probed(client: AsyncClient, maker: Any) -> None:
    source_id, token = await _seed(maker, status=SourceStatus.DISCONNECTED)

    resp = await client.post(f"/api/v1/webhooks/onshape/{source_id}/{token}", json={})

    assert resp.status_code == 204


async def test_a_delivery_storm_stops_scheduling_work(
    client: AsyncClient, maker: Any, monkeypatch: Any
) -> None:
    """The budget must stop WORK, not merely be consulted.

    The first version of this asserted the limiter's counter had advanced — which
    passes whenever the limiter is CALLED, and would still pass with the
    early-return deleted. It tested nothing. This patches the scheduler and counts
    how many deliveries actually reached it.

    The unit matters: one delivery does not cost one probe. It schedules a sync
    whose freshness probe loops PER TRACKED DOCUMENT, up to 50 — so a per-minute
    budget could authorise hundreds of provider calls a minute against an
    allowance of 2,500 A YEAR.
    """
    scheduled: list[uuid.UUID] = []

    async def _fake(app: object, source_id: uuid.UUID) -> None:
        scheduled.append(source_id)

    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", _fake)
    source_id, token = await _seed(maker)
    url = f"/api/v1/webhooks/onshape/{source_id}/{token}"

    codes = [(await client.post(url, json={})).status_code for _ in range(40)]

    assert set(codes) == {204}, "a rejected delivery must still answer 204"
    assert len(scheduled) == 1, (
        f"{len(scheduled)} deliveries scheduled work; budget is {WEBHOOK_DELIVERIES_PER_DAY}"
    )


async def test_a_missing_limiter_schedules_nothing(
    client: AsyncClient, maker: Any, monkeypatch: Any
) -> None:
    """Fails CLOSED. On an unauthenticated endpoint that schedules third-party
    spend, silently dropping the budget control is the wrong way to fail."""
    scheduled: list[uuid.UUID] = []

    async def _fake(app: object, source_id: uuid.UUID) -> None:
        scheduled.append(source_id)

    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", _fake)
    source_id, token = await _seed(maker)
    monkeypatch.delattr(client._transport.app.state, "webhook_limiter", raising=False)  # type: ignore[attr-defined]

    resp = await client.post(f"/api/v1/webhooks/onshape/{source_id}/{token}", json={})

    assert resp.status_code == 204
    assert scheduled == [], "work was scheduled with no budget control in place"


async def test_a_body_with_no_content_length_is_refused_before_buffering(
    client: AsyncClient, maker: Any
) -> None:
    """Chunked transfer-encoding sends no Content-Length. An earlier version
    checked the header only when present and numeric, then called
    `request.body()` — which buffers the whole stream with no cap. Both chunked
    and a malformed header sailed straight past, PRE-AUTHENTICATION, on the one
    internet-facing endpoint in the system."""
    source_id, token = await _seed(maker)

    async def _chunks() -> AsyncIterator[bytes]:
        yield b"x" * 1024

    resp = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}",
        content=_chunks(),
        headers={"Content-Type": "application/octet-stream"},
    )

    assert resp.status_code == 411


async def test_a_malformed_content_length_is_refused(client: AsyncClient, maker: Any) -> None:
    source_id, token = await _seed(maker)

    resp = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}",
        content=b"x" * 16,
        headers={"Content-Length": "not-a-number", "Content-Type": "application/octet-stream"},
    )

    assert resp.status_code == 411


async def test_a_lying_small_content_length_is_still_capped_while_streaming(
    client: AsyncClient, maker: Any
) -> None:
    """The second half of the guard: a client that declares a small body and then
    sends a large one is cut off mid-stream rather than buffered."""
    source_id, token = await _seed(maker)

    async def _chunks() -> AsyncIterator[bytes]:
        for _ in range(80):
            yield b"x" * 4096  # ~320 KiB against a 64 KiB cap

    resp = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}",
        content=_chunks(),
        headers={"Content-Length": "16", "Content-Type": "application/octet-stream"},
    )

    assert resp.status_code == 413


async def test_onshape_hints_remain_durable_while_syncing(client: Any, maker: Any) -> None:
    from solus_api.services.onshape_webhooks import STATE_KEY

    source_id, token = await _seed(maker, status=SourceStatus.SYNCING)
    url = f"/api/v1/webhooks/onshape/{source_id}/{token}"
    for _ in range(2):
        assert (await client.post(url, json={"messageId": "same-event"})).status_code == 204
    async with maker() as session:
        source = await session.get(Source, source_id)
        assert source.config[STATE_KEY]["generation"] == 1


async def test_onshape_foreign_document_does_not_dirty_source(client: Any, maker: Any) -> None:
    from solus_api.services.onshape_webhooks import STATE_KEY

    source_id, token = await _seed(maker)
    response = await client.post(
        f"/api/v1/webhooks/onshape/{source_id}/{token}", json={"documentId": "foreign"}
    )
    assert response.status_code == 204
    async with maker() as session:
        source = await session.get(Source, source_id)
        assert STATE_KEY not in source.config


async def test_deliveries_that_will_not_schedule_are_rate_limited_before_any_state_work(
    client: AsyncClient, maker: Any, monkeypatch: Any
) -> None:
    """Pings and `translation.complete` never schedule a sync, so the per-DAY scheduling
    budget never sees them - yet each one used to cost a row lock, a commit and a Redis
    write. A per-source ingest budget now bounds that work (still 204, never an error)."""
    from solus_api.routers import webhooks as router_module

    calls = 0

    async def _counted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return router_module._NO_HINT

    monkeypatch.setattr(router_module, "_accept_onshape_hint", _counted)
    source_id, token = await _seed(maker)
    url = f"/api/v1/webhooks/onshape/{source_id}/{token}"
    event = {"event": "onshape.model.translation.complete"}

    codes = [
        (await client.post(url, json=event)).status_code
        for _ in range(router_module.WEBHOOK_INGEST_PER_MINUTE + 25)
    ]

    assert set(codes) == {204}
    assert calls == router_module.WEBHOOK_INGEST_PER_MINUTE


async def test_the_ingest_budget_is_per_source_and_leaves_the_scheduling_budget_alone(
    client: AsyncClient, maker: Any, monkeypatch: Any
) -> None:
    scheduled: list[uuid.UUID] = []

    async def _fake(app: object, source_id: uuid.UUID) -> None:
        scheduled.append(source_id)

    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", _fake)
    first_id, first_token = await _seed(maker)
    second_id, second_token = await _seed(maker)
    first = f"/api/v1/webhooks/onshape/{first_id}/{first_token}"
    second = f"/api/v1/webhooks/onshape/{second_id}/{second_token}"

    for _ in range(30):
        await client.post(first, json={})
    await client.post(second, json={})

    assert scheduled.count(first_id) == 1  # the debounce lease, as before
    assert scheduled.count(second_id) == 1  # another source is unaffected by the first's traffic


async def test_a_wrong_token_never_spends_a_sources_ingest_budget(
    client: AsyncClient, maker: Any, monkeypatch: Any
) -> None:
    """The limiter keys on an AUTHENTICATED source, so an anonymous caller who knows only
    the source id cannot exhaust the real provider's budget."""
    from solus_api.routers import webhooks as router_module

    source_id, token = await _seed(maker)
    for _ in range(router_module.WEBHOOK_INGEST_PER_MINUTE + 10):
        assert (
            await client.post(f"/api/v1/webhooks/onshape/{source_id}/wrong-token", json={})
        ).status_code == 404

    assert (
        await client.post(f"/api/v1/webhooks/onshape/{source_id}/{token}", json={})
    ).status_code == 204


async def test_a_missing_ingest_limiter_does_not_drop_deliveries(
    client: AsyncClient, maker: Any, monkeypatch: Any
) -> None:
    from solus_api.routers import webhooks as router_module

    calls = 0

    async def _counted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return router_module._NO_HINT

    monkeypatch.setattr(router_module, "_accept_onshape_hint", _counted)
    monkeypatch.delattr(client._transport.app.state, "webhook_ingest_limiter", raising=False)  # type: ignore[attr-defined]
    source_id, token = await _seed(maker)

    for _ in range(router_module.WEBHOOK_INGEST_PER_MINUTE + 5):
        await client.post(f"/api/v1/webhooks/onshape/{source_id}/{token}", json={})

    assert calls == router_module.WEBHOOK_INGEST_PER_MINUTE + 5
