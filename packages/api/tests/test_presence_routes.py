"""Actual presence routes and central confirmation, with a fake hardware provider."""

import hashlib
import uuid

import pytest
from conftest import ALICE, BOB, add_member, bearer, me
from solus_api.agent.confirmations import request_confirmation
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.models import DataEvent, Project, ToolConfirmation, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_firmware_presence import fixture_service

BODY = {"profile_id": "uno_avr", "kind": "heartbeat", "channel": "uno.alive"}


async def setup(client, headers, db, tmp_path, app):
    service, robot, brain = await fixture_service(client, headers, db, tmp_path)
    app.state.presence_provider = service.provider
    service.store = app.state.artifact_store
    source = ("// status only\n" * 80).encode()
    service.provider.prepare.return_value.update(
        source=source, source_sha256=hashlib.sha256(source).hexdigest()
    )
    service.provider.profiles.return_value = [
        {"id": "uno_avr", "label": "Arduino Uno (AVR)", "available": True, "reason": None}
    ]
    base = f"/api/v1/projects/{service.project_id}/hardware"
    route = f"{base}/robots/{robot}/brains/{brain}/presence/prepare"
    return service, base, route


@pytest.mark.parametrize(
    "access,status",
    [("anonymous", 401), ("unverified", 403), ("foreign", 404), ("viewer", 403), ("member", 201)],
)
async def test_presence_routes_authorize_every_entry(
    client, alice_headers, bob_headers, db, tmp_path, app, access, status
):
    service, base, route = await setup(client, alice_headers, db, tmp_path, app)
    project = await db.get(Project, service.project_id)
    await me(client, bob_headers)
    if access in ("viewer", "member"):
        await add_member(client, alice_headers, bob_headers, BOB, str(project.team_id), role=access)
    headers = (
        {}
        if access == "anonymous"
        else bearer(**ALICE, email_verified=False)
        if access == "unverified"
        else bob_headers
    )
    response = await client.post(route, headers=headers, json=BODY)
    assert response.status_code == status, response.text
    profiles = await client.get(base + "/presence/profiles", headers=headers)
    assert profiles.status_code == (200 if status == 201 else status), profiles.text
    service.provider.upload.assert_not_awaited()
    if status != 201:
        service.provider.prepare.assert_not_awaited()


@pytest.mark.parametrize("decision", ["approve", "reject", "changed"])
async def test_real_registry_and_http_decision_preserve_gate_and_outcome_event(
    client, alice_headers, db, tmp_path, app, engine, decision
):
    service, base, route = await setup(client, alice_headers, db, tmp_path, app)
    user = await db.get(User, service.user_id)
    user.data_collection_consent = True
    await db.commit()
    response = await client.post(route, headers=alice_headers, json=BODY)
    assert response.status_code == 201, response.text
    prepared = response.json()["data"]
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        service.project_id,
        user_id=service.user_id,
        presence_service=service,
    )
    assert any(
        t.name == "hardware.flash_presence" and t.requires_confirmation for t in registry.list()
    )
    project = await db.get(Project, service.project_id)
    parked = await request_confirmation(
        db,
        registry,
        ToolCall(tool="hardware.flash_presence", args={"plan_id": prepared["plan_id"]}),
        project_id=service.project_id,
        team_id=project.team_id,
        user_id=service.user_id,
    )
    assert parked is not None
    await db.commit()
    row = await db.scalar(
        select(ToolConfirmation).where(ToolConfirmation.project_id == service.project_id)
    )
    assert row is not None
    assert (
        "".join(
            p["after"] for p in row.preview if p["label"].startswith("Complete firmware source")
        )
        == prepared["source"]
    )
    service.provider.upload.assert_not_awaited()
    if decision == "changed":
        service.provider.validate.side_effect = ValueError("USB changed")
    response = await client.post(
        f"/api/v1/projects/{service.project_id}/sol/confirmations/{row.id}",
        headers=alice_headers,
        json={"decision": "reject" if decision == "reject" else "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is (decision == "approve")
    assert service.provider.upload.await_count == int(decision == "approve")
    events = list(
        await db.scalars(
            select(DataEvent).where(
                DataEvent.project_id == service.project_id,
                DataEvent.event_type == "hardware.presence_outcome",
            )
        )
    )
    assert len(events) == int(decision == "approve")
    if events:
        event = events[0]
        assert event.user_id == service.user_id and event.team_id == project.team_id
        assert event.payload == {
            "plan_id": prepared["plan_id"],
            "robot_id": str((await service.plan(uuid.UUID(prepared["plan_id"]))).attrs["robot_id"]),
            "brain_id": str((await service.plan(uuid.UUID(prepared["plan_id"]))).attrs["brain_id"]),
            "status": "flashed",
            "source_sha256": prepared["source_sha256"],
            "binary_sha256": prepared["binary_sha256"],
        }


async def test_failed_complete_preview_cannot_mint_a_confirmation(
    client, alice_headers, db, tmp_path, app, engine
):
    service, _, route = await setup(client, alice_headers, db, tmp_path, app)
    response = await client.post(route, headers=alice_headers, json=BODY)
    assert response.status_code == 201
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        service.project_id,
        user_id=service.user_id,
        presence_service=service,
    )
    project = await db.get(Project, service.project_id)
    service.provider.validate.side_effect = ValueError("Changed USB snapshot")
    parked = await request_confirmation(
        db,
        registry,
        ToolCall(
            tool="hardware.flash_presence", args={"plan_id": response.json()["data"]["plan_id"]}
        ),
        project_id=service.project_id,
        team_id=project.team_id,
        user_id=service.user_id,
    )
    assert parked is not None and parked.confirmation_id is None
    assert not parked.result.ok and parked.result.error.code.value == "unavailable"
    assert (
        await db.scalar(
            select(ToolConfirmation).where(ToolConfirmation.project_id == service.project_id)
        )
        is None
    )
    service.provider.upload.assert_not_awaited()


async def test_own_project_cannot_prepare_another_projects_robot(
    client, alice_headers, db, tmp_path, app
):
    service, _, route = await setup(client, alice_headers, db, tmp_path / "first", app)
    other, _, _ = await setup(client, alice_headers, db, tmp_path / "second", app)
    response = await client.post(
        route.replace(str(service.project_id), str(other.project_id)),
        headers=alice_headers,
        json=BODY,
    )
    assert response.status_code == 404, response.text
    service.provider.prepare.assert_not_awaited()
    other.provider.prepare.assert_not_awaited()


@pytest.mark.parametrize(
    "status,consent", [("unknown", True), ("unchanged", True), ("flashed", False)]
)
async def test_outcome_event_tracks_actual_state_and_consent(
    client, alice_headers, db, tmp_path, app, status, consent
):
    from solus_api.core.errors import APIError
    from solus_api.hardware.presence import PresenceRefusalError

    service, _, route = await setup(client, alice_headers, db, tmp_path, app)
    user = await db.get(User, service.user_id)
    user.data_collection_consent = consent
    await db.commit()
    response = await client.post(route, headers=alice_headers, json=BODY)
    assert response.status_code == 201
    plan_id = uuid.UUID(response.json()["data"]["plan_id"])
    if status != "flashed":
        service.provider.upload.side_effect = (
            PresenceRefusalError("busy") if status == "unchanged" else RuntimeError("failed")
        )
        with pytest.raises(APIError):
            await service.execute(plan_id)
    else:
        await service.execute(plan_id)
    events = list(
        await db.scalars(
            select(DataEvent).where(
                DataEvent.project_id == service.project_id,
                DataEvent.event_type == "hardware.presence_outcome",
            )
        )
    )
    assert len(events) == int(consent)
    if events:
        assert events[0].payload["status"] == status
        assert set(events[0].payload) == {
            "plan_id",
            "robot_id",
            "brain_id",
            "status",
            "source_sha256",
            "binary_sha256",
        }
