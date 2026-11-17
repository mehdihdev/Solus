"""SOLUSDEV-326 P3 — declining a device offer is the caller's "Not now" to that device.

When the decide route REJECTS a parked `hardware.inspect_device`, `hardware.add_parts` or
`hardware.add_connection` row whose STORED args name a device, that device joins the caller's
own dismissals on this API's machine (the service `POST /devices/dismissals` uses, with its
`hardware.device_dismissed` event). Best effort: with no machine the decision is recorded all
the same. The decide body stays decision-only.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.confirmations import CONFIRMATION_TTL
from solus_api.models import (
    ConfirmationStatus,
    DataEvent,
    Project,
    ToolConfirmation,
    User,
    utcnow,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from test_device_memory import _fresh_machine, _machine, _team
from test_device_memory import host as host
from test_hardware_detect import DEVICE_REF, _DetectLocal

INSPECT = ("hardware.inspect_device", {"device_ref": DEVICE_REF, "restart_approved": True})
ADD_PARTS = ("hardware.add_parts", {"proposal": {"device_ref": DEVICE_REF}, "shown": {}})
ADD_CONNECTION = ("hardware.add_connection", {"proposal": {"device_ref": DEVICE_REF}, "shown": {}})


@pytest.fixture
def local(app: FastAPI) -> _DetectLocal:
    """A local runner on this API, so the route's registry carries the hardware tools."""
    runner = _DetectLocal()
    app.state.bench_local = runner
    return runner


async def _parked(
    db: AsyncSession, project: str, user: str, tool: str, args: dict[str, Any]
) -> uuid.UUID:
    project_row = await db.get(Project, uuid.UUID(project))
    assert project_row is not None
    row = ToolConfirmation(
        project_id=project_row.id,
        team_id=project_row.team_id,
        user_id=uuid.UUID(user),
        tool=tool,
        args=args,
        summary="A device offer",
        expires_at=utcnow() + CONFIRMATION_TTL,
    )
    db.add(row)
    await db.commit()
    return row.id


async def _decide(
    client: AsyncClient, project: str, row: uuid.UUID, headers: dict[str, str], decision: str
) -> Any:
    return await client.post(
        f"/api/v1/projects/{project}/sol/confirmations/{row}",
        headers=headers,
        json={"decision": decision},
    )


async def _status(db: AsyncSession, row: uuid.UUID) -> ConfirmationStatus:
    db.expire_all()
    found = await db.get(ToolConfirmation, row)
    assert found is not None
    return found.status


async def _dismissed_events(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(DataEvent).where(DataEvent.event_type == "hardware.device_dismissed")
    )
    return [row.payload for row in rows]


@pytest.mark.parametrize("offer", [INSPECT, ADD_PARTS, ADD_CONNECTION], ids=lambda o: o[0])
async def test_rejecting_a_device_offer_dismisses_the_device_for_the_caller_alone(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    local: _DetectLocal,
    host: list[str | None],
    offer: tuple[str, dict[str, Any]],
) -> None:
    project, alice, bob = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    row = await _parked(db, project, alice, *offer)

    response = await _decide(client, project, row, alice_headers, "reject")

    assert response.status_code == 200, response.text
    assert await _status(db, row) is ConfirmationStatus.REJECTED
    # Her own list on this machine; Bob's says nothing.
    assert (await _fresh_machine(app, project))["dismissed"] == {alice: [DEVICE_REF]}
    assert await _dismissed_events(db) == [{"device_ref": DEVICE_REF}]
    assert bob not in (await _fresh_machine(app, project))["dismissed"]


async def test_approving_a_device_offer_dismisses_nothing(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    local: _DetectLocal,
    host: list[str | None],
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    row = await _parked(db, project, alice, *INSPECT)

    response = await _decide(client, project, row, alice_headers, "approve")

    assert response.status_code == 200, response.text
    assert await _status(db, row) is not ConfirmationStatus.REJECTED
    assert not (await _fresh_machine(app, project)).get("dismissed")


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        # Another hardware card, and a tool that is not hardware's, each naming a device.
        (
            "hardware.set_in_graph",
            {"device_ref": DEVICE_REF, "proposal": {"device_ref": DEVICE_REF}},
        ),
        ("machine.write_file", {"device_ref": DEVICE_REF}),
        # One of the three whose stored args name no device, or no well-formed one.
        ("hardware.add_parts", {"proposal": {}}),
        ("hardware.inspect_device", {"device_ref": "usb:a/b\nApprove"}),
        ("hardware.inspect_device", {"device_ref": ["usb:A"]}),
    ],
)
async def test_only_a_device_offers_own_well_formed_device_is_dismissed(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    local: _DetectLocal,
    host: list[str | None],
    tool: str,
    args: dict[str, Any],
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    row = await _parked(db, project, alice, tool, args)

    response = await _decide(client, project, row, alice_headers, "reject")

    assert response.status_code == 200, response.text
    assert await _status(db, row) is ConfirmationStatus.REJECTED
    assert not (await _fresh_machine(app, project)).get("dismissed")
    assert await _dismissed_events(db) == []


@pytest.mark.parametrize("missing", ["unregistered", "no_identity", "no_runner"])
async def test_with_no_machine_the_decision_is_still_recorded(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    local: _DetectLocal,
    host: list[str | None],
    missing: str,
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    if missing == "no_identity":
        await _machine(db, project, alice)
        host[0] = None
    row = await _parked(db, project, alice, *INSPECT)
    if missing == "no_runner":
        # Parked while a runner was there; the API then runs on no one's machine.
        app.state.bench_local = None

    response = await _decide(client, project, row, alice_headers, "reject")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is False
    assert await _status(db, row) is ConfirmationStatus.REJECTED
    assert await _dismissed_events(db) == []


async def test_the_decide_body_stays_decision_only(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    local: _DetectLocal,
    host: list[str | None],
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    row = await _parked(db, project, alice, *INSPECT)
    response = await client.post(
        f"/api/v1/projects/{project}/sol/confirmations/{row}",
        headers=alice_headers,
        json={"decision": "reject", "device_ref": DEVICE_REF},
    )
    assert response.status_code == 422
    assert await _status(db, row) is ConfirmationStatus.PENDING


def _not_found(response: Any, *, in_project: bool) -> bool:
    """Alice's offer was not found: outside her project the route is a 404; inside a project
    the caller may read, the decide route answers 200 with the gate's own `not_found` result
    (its wire shape for every unknown confirmation id)."""
    if not in_project:
        return bool(response.status_code == 404)
    data = response.json()["data"]
    return response.status_code == 200 and not data["ok"] and data["error"]["code"] == "not_found"


async def _untouched(db: AsyncSession, app: FastAPI, project: str, row: uuid.UUID) -> None:
    assert await _status(db, row) is ConfirmationStatus.PENDING
    assert not (await _fresh_machine(app, project)).get("dismissed")
    assert await _dismissed_events(db) == []


async def test_a_teammate_cannot_decline_anothers_device_offer(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    local: _DetectLocal,
    host: list[str | None],
) -> None:
    """A confirmation is its requester's: a teammate's decide finds no such action, dismisses
    nothing on anyone's list and emits no event."""
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    row = await _parked(db, project, alice, *INSPECT)

    response = await _decide(client, project, row, bob_headers, "reject")

    assert _not_found(response, in_project=True), response.text
    await _untouched(db, app, project, row)


@pytest.mark.parametrize("through", ["her_project", "their_own_project"])
async def test_another_team_cannot_decline_a_device_offer(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    local: _DetectLocal,
    host: list[str | None],
    through: str,
) -> None:
    """Team B's member reaches Alice's offer through neither her project nor their own."""
    alice = str((await me(client, alice_headers))["id"])
    project = str(
        (
            await create_project(
                client, alice_headers, (await create_team(client, alice_headers))["id"]
            )
        )["id"]
    )
    theirs = str(
        (await create_project(client, bob_headers, (await create_team(client, bob_headers))["id"]))[
            "id"
        ]
    )
    await _machine(db, project, alice)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    row = await _parked(db, project, alice, *INSPECT)

    via = project if through == "her_project" else theirs
    response = await _decide(client, via, row, bob_headers, "reject")

    assert _not_found(response, in_project=via == theirs), response.text
    await _untouched(db, app, project, row)
