"""API.md §2.13 — client-originated data-event ingest (SOLUSDEV-235).

The desktop host reports bridge refusals (`extension.bridge_refused`, ADR-035 §2)
through this route. Everything here is untrusted client input: a closed
`event_type` set, strict bodies, small caps, the caller's identity from the
JWT, and `project_id` honoured only when the caller can resolve that project.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import ALICE, BOB, bearer, create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import DataEvent, User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def _consented_user(client: AsyncClient, db: AsyncSession, claims: dict[str, str]) -> str:
    user = await me(client, bearer(claims["sub"], claims["email"]))
    await db.execute(
        update(User).where(User.id == uuid.UUID(user["id"])).values(data_collection_consent=True)
    )
    await db.commit()
    return str(user["id"])


async def _project(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    team = await create_team(client, headers)
    project: dict[str, Any] = await create_project(client, headers, team["id"])
    return project


def _refusal(project_id: str | None = None, **over: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_type": "extension.bridge_refused",
        "payload": {
            "slug": "bom",
            "version": "1.2.0",
            "method": "net.fetch",
            "code": "network_denied",
        },
    }
    if project_id is not None:
        event["project_id"] = project_id
    event.update(over)
    return event


async def _stored(db: AsyncSession) -> list[DataEvent]:
    stmt = select(DataEvent).where(DataEvent.event_type == "extension.bridge_refused")
    return list((await db.scalars(stmt.order_by(DataEvent.created_at))).all())


async def test_ingest_stores_consented_events_for_the_caller(
    client: AsyncClient, db: AsyncSession
) -> None:
    alice_id = await _consented_user(client, db, ALICE)
    headers = bearer(ALICE["sub"], ALICE["email"])
    project = await _project(client, headers)
    resp = await client.post(
        "/api/v1/events", json={"events": [_refusal(project["id"]), _refusal()]}, headers=headers
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["data"] == {"accepted": 2}
    rows = await _stored(db)
    assert len(rows) == 2
    assert all(str(r.user_id) == alice_id for r in rows)
    scoped = next(r for r in rows if r.project_id is not None)
    assert str(scoped.project_id) == project["id"]
    assert str(scoped.team_id) == project["team_id"]
    assert scoped.payload["code"] == "network_denied"


async def test_without_consent_nothing_is_stored_but_the_call_succeeds(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(client, headers)
    resp = await client.post("/api/v1/events", json={"events": [_refusal()]}, headers=headers)
    assert resp.status_code == 202
    assert await _stored(db) == []


async def test_a_foreign_project_id_is_dropped_not_an_oracle(
    client: AsyncClient, db: AsyncSession
) -> None:
    alice_headers = bearer(ALICE["sub"], ALICE["email"])
    await me(client, alice_headers)
    project = await _project(client, alice_headers)
    bob_id = await _consented_user(client, db, BOB)
    resp = await client.post(
        "/api/v1/events",
        json={"events": [_refusal(project["id"])]},
        headers=bearer(BOB["sub"], BOB["email"]),
    )
    # Bob cannot learn that Alice's project exists: the event lands, unscoped.
    assert resp.status_code == 202
    rows = await _stored(db)
    assert len(rows) == 1
    assert str(rows[0].user_id) == bob_id and rows[0].project_id is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"events": []},
        {"events": [{"event_type": "user.signed_in", "payload": {}}]},
        {"events": [{"event_type": "extension.bridge_refused", "payload": {}, "user_id": "x"}]},
        {"events": [{"event_type": "extension.bridge_refused"}]},
        {"events": [_refusal() for _ in range(51)]},
        {"events": [_refusal(payload={"slug": "bom", "big": "x" * 5000})]},
        {"events": [_refusal(project_id="not-a-uuid")]},
    ],
)
async def test_strict_bodies(client: AsyncClient, body: dict[str, Any]) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(client, headers)
    resp = await client.post("/api/v1/events", json=body, headers=headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


async def test_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/events", json={"events": [_refusal()]})
    assert resp.status_code == 401


async def test_per_user_rate_limit(client: AsyncClient, app: Any) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(client, headers)
    app.state.settings.client_event_batches_per_minute_per_user = 2
    for _ in range(2):
        ok = await client.post("/api/v1/events", json={"events": [_refusal()]}, headers=headers)
        assert ok.status_code == 202
    resp = await client.post("/api/v1/events", json={"events": [_refusal()]}, headers=headers)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert resp.headers["Retry-After"]


async def test_a_429_is_itself_a_data_event(
    client: AsyncClient, db: AsyncSession, app: Any
) -> None:
    await _consented_user(client, db, ALICE)
    headers = bearer(ALICE["sub"], ALICE["email"])
    app.state.settings.client_event_batches_per_minute_per_user = 1
    await client.post("/api/v1/events", json={"events": [_refusal()]}, headers=headers)
    await client.post("/api/v1/events", json={"events": [_refusal()]}, headers=headers)
    stmt = select(DataEvent).where(DataEvent.event_type == "client_events.rate_limited")
    assert len(list((await db.scalars(stmt)).all())) == 1


async def test_a_removed_member_cannot_scope_events_to_the_old_project(
    client: AsyncClient, db: AsyncSession
) -> None:
    from solus_api.models import Membership, ProjectMembership, utcnow

    alice_id = await _consented_user(client, db, ALICE)
    headers = bearer(ALICE["sub"], ALICE["email"])
    project = await _project(client, headers)
    # Removed from the team AND from any direct project share (ADR-025): the
    # project is no longer visible, exactly as get_project_context would rule.
    await db.execute(
        update(Membership)
        .where(Membership.user_id == uuid.UUID(alice_id))
        .values(deleted_at=utcnow())
    )
    await db.execute(
        update(ProjectMembership)
        .where(ProjectMembership.user_id == uuid.UUID(alice_id))
        .values(deleted_at=utcnow())
    )
    await db.commit()
    resp = await client.post(
        "/api/v1/events", json={"events": [_refusal(project["id"])]}, headers=headers
    )
    assert resp.status_code == 202
    rows = await _stored(db)
    assert len(rows) == 1 and rows[0].project_id is None
