"""Reviewed wiring is scoped evidence, never permission to flash hardware."""

import uuid

import pytest
from solus_api.core.errors import APIError
from solus_api.hardware.presence import PreparePresence
from test_firmware_presence import fixture_service


async def test_typed_wiring_requires_acceptance_and_revalidation(
    client, alice_headers, db, tmp_path
):
    from solus_api.hardware.presence_topology import WiringRequest, WiringService

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    service = WiringService(presence)
    proposal = await service.propose(
        robot,
        brain,
        WiringRequest(
            profile_id="uno_avr",
            mode="typed",
            wiring=[{"channel": "light.raw", "pin": "A0", "kind": "analog_input"}],
        ),
    )
    body = PreparePresence(
        profile_id="uno_avr",
        kind="topology",
        channel="uno.alive",
        wiring_proposal_id=proposal["proposal_id"],
    )
    with pytest.raises(APIError) as error:
        await presence.prepare(robot, brain, body)
    assert error.value.status_code == 409
    await service.accept(robot, brain, uuid.UUID(proposal["proposal_id"]), proposal["digest"])
    prepared = await presence.prepare(robot, brain, body)
    assert prepared["plan_id"]
    presence.provider.prepare.assert_awaited_once()
    assert presence.provider.prepare.await_args.args[-1] == [
        {"channel": "light.raw", "pin": "A0", "kind": "analog_input"}
    ]
    presence.provider.upload.assert_not_awaited()


async def test_empty_wiring_is_explicit_and_actor_scoped(client, alice_headers, db, tmp_path):
    from solus_api.hardware.presence_topology import WiringRequest, WiringService

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    service = WiringService(presence)
    proposal = await service.propose(
        robot, brain, WiringRequest(profile_id="uno_avr", mode="typed")
    )
    assert proposal["wiring"] == []
    with pytest.raises(APIError) as error:
        await service.accept(robot, brain, uuid.UUID(proposal["proposal_id"]), "0" * 64)
    assert error.value.status_code == 409
    presence.user_id = uuid.uuid4()
    with pytest.raises(APIError) as error:
        await service.accept(robot, brain, uuid.UUID(proposal["proposal_id"]), proposal["digest"])
    assert error.value.status_code == 404


@pytest.mark.parametrize(
    "patch",
    [
        {"mode": "schematic"},
        {"mode": "probe"},
        {"source_id": str(uuid.uuid4())},
        {"wiring": [{"channel": "motor", "pin": "D2", "kind": "output"}]},
    ],
)
def test_wiring_request_rejects_ambiguous_source_and_output(patch):
    from pydantic import ValidationError
    from solus_api.hardware.presence_topology import WiringRequest

    with pytest.raises(ValidationError):
        WiringRequest.model_validate({"profile_id": "uno_avr", "mode": "typed"} | patch)


async def test_schematic_changes_invalidate_accepted_wiring(client, alice_headers, db, tmp_path):
    from solus_api.hardware.presence_topology import WiringRequest, WiringService
    from solus_api.models import Domain, GraphEntity, Project, Source, SourceType

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    project = await db.get(Project, presence.project_id)
    source = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.KICAD,
        name="Test schematic",
        config={},
        status="connected",
    )
    db.add(source)
    await db.flush()
    part = GraphEntity(
        project_id=project.id,
        source_id=source.id,
        source_connector="kicad",
        external_ref="sensor",
        origin="connector",
        domain=Domain.ELECTRICAL,
        kind="component",
        name="Unknown sensor",
        attrs={"pin": "A0"},
    )
    db.add(part)
    await db.commit()
    service = WiringService(presence)
    proposal = await service.propose(
        robot, brain, WiringRequest(profile_id="uno_avr", mode="schematic", source_id=source.id)
    )
    assert proposal["wiring"] == []  # A source pin is not a guessed sensor driver.
    assert proposal["unresolved"]
    await service.accept(robot, brain, uuid.UUID(proposal["proposal_id"]), proposal["digest"])
    part.attrs = {"pin": "A1"}
    await db.flush()
    with pytest.raises(APIError) as error:
        await service.checked(robot, brain, uuid.UUID(proposal["proposal_id"]), accepted=True)
    assert error.value.status_code == 409
    source.status = "disconnected"
    await db.flush()
    with pytest.raises(APIError) as error:
        await service.checked(robot, brain, uuid.UUID(proposal["proposal_id"]), accepted=True)
    assert error.value.status_code == 404


@pytest.mark.parametrize("field,value", [("relation_type", "depends_on"), ("confidence", 0.2)])
async def test_schematic_relation_meaning_change_invalidates_review(
    client, alice_headers, db, tmp_path, field, value
):
    from solus_api.hardware.presence_topology import WiringRequest, WiringService
    from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Source, SourceType

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    project = await db.get(Project, presence.project_id)
    source = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.KICAD,
        name="QA net",
        config={},
        status="connected",
    )
    db.add(source)
    await db.flush()
    parts = [
        GraphEntity(
            project_id=project.id,
            source_id=source.id,
            source_connector="kicad",
            external_ref=f"qa:{n}",
            kind="component",
            domain=Domain.ELECTRICAL,
            origin="connector",
            name=f"QA pin {n}",
            attrs={},
        )
        for n in range(2)
    ]
    db.add_all(parts)
    await db.flush()
    edge = GraphEdge(
        project_id=project.id,
        source_id=source.id,
        src_id=parts[0].id,
        dst_id=parts[1].id,
        relation_type="connected_to",
        origin="connector",
        domain_pair="electrical:electrical",
        confidence=0.9,
        attrs={},
    )
    db.add(edge)
    await db.commit()
    service = WiringService(presence)
    proposal = await service.propose(
        robot, brain, WiringRequest(profile_id="uno_avr", mode="schematic", source_id=source.id)
    )
    setattr(edge, field, value)
    await db.flush()
    with pytest.raises(APIError) as error:
        await service.accept(robot, brain, uuid.UUID(proposal["proposal_id"]), proposal["digest"])
    assert error.value.status_code == 409


async def probe_run(presence, robot, db, *, device="usb:port-3-1", values=None):
    from solus_api.graph.packet import TelemetryPacket
    from solus_api.livebench.runs import store
    from solus_api.livebench.runs.models import RunManifest, RunSummary
    from solus_api.models import utcnow

    now = utcnow()
    manifest = RunManifest(
        robot_id=robot,
        started_at=now,
        packets=[
            TelemetryPacket(
                device_id=device,
                timestamp=now,
                values=values
                if values is not None
                else {"probe.analog.0": 523, "probe.i2c.responding": 0},
                units={
                    key: "count"
                    for key in (values or {"probe.analog.0": 523, "probe.i2c.responding": 0})
                },
            )
        ],
    )
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=robot,
        name="Synthetic probe fixture",
        origin="synthetic",
        status="completed",
        started_at=now,
        ended_at=now,
    )
    entity = store.new_record(presence.project_id, info, presence.user_id)
    db.add(entity)
    await db.flush()
    await store.save(db, presence.store, entity, info, manifest, presence.user_id, final=True)
    return entity


async def test_probe_empty_i2c_and_analog_never_create_parts(client, alice_headers, db, tmp_path):
    from solus_api.hardware.presence_topology import WiringRequest, WiringService

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    record = await probe_run(presence, robot, db)
    service = WiringService(presence)
    proposal = await service.propose(
        robot, brain, WiringRequest(profile_id="uno_avr", mode="probe", run_id=record.id)
    )
    assert proposal["wiring"] == []
    assert all(row["confidence"] is None for row in proposal["observations"])
    assert "synthetic" in proposal["observations"][0]["detail"]
    assert "does not establish empty wiring" in proposal["unresolved"][0]
    await service.accept(robot, brain, uuid.UUID(proposal["proposal_id"]), proposal["digest"])
    prepared = await presence.prepare(
        robot,
        brain,
        PreparePresence(
            profile_id="uno_avr",
            kind="topology",
            channel="uno.alive",
            wiring_proposal_id=proposal["proposal_id"],
        ),
    )
    record.attrs = {**record.attrs, "summary": {**record.attrs["summary"], "status": "truncated"}}
    await db.flush()
    with pytest.raises(APIError) as error:
        await presence.checked(uuid.UUID(prepared["plan_id"]))
    assert error.value.status_code == 409
    presence.provider.upload.assert_not_awaited()


@pytest.mark.parametrize(
    "device,values",
    [
        ("other-device", {"probe.i2c.responding": 0}),
        ("usb:port-3-1", {"position": 0}),
    ],
)
async def test_probe_requires_matching_device_observations(
    client, alice_headers, db, tmp_path, device, values
):
    from solus_api.hardware.presence_topology import WiringRequest, WiringService

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    record = await probe_run(presence, robot, db, device=device, values=values)
    with pytest.raises(APIError) as error:
        await WiringService(presence).propose(
            robot, brain, WiringRequest(profile_id="uno_avr", mode="probe", run_id=record.id)
        )
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "access,expected",
    [("anonymous", 401), ("unverified", 403), ("foreign", 404), ("viewer", 403), ("member", 201)],
)
async def test_wiring_http_scope_and_verified_decision(
    client, alice_headers, bob_headers, db, tmp_path, app, access, expected
):
    from conftest import ALICE, BOB, add_member, bearer, me
    from solus_api.models import Project

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    app.state.presence_provider = presence.provider
    base = (
        f"/api/v1/projects/{presence.project_id}/hardware/robots/{robot}"
        f"/brains/{brain}/presence/wiring"
    )
    body = {"profile_id": "uno_avr", "mode": "typed", "wiring": []}
    original = (await client.post(base + "/propose", headers=alice_headers, json=body)).json()[
        "data"
    ]
    await me(client, bob_headers)
    if access in {"viewer", "member"}:
        project = await db.get(Project, presence.project_id)
        await add_member(client, alice_headers, bob_headers, BOB, str(project.team_id), role=access)
    headers = (
        {}
        if access == "anonymous"
        else bearer(**ALICE, email_verified=False)
        if access == "unverified"
        else bob_headers
    )
    response = await client.post(base + "/propose", headers=headers, json=body)
    assert response.status_code == expected, response.text
    accepted = await client.post(
        base + f"/{original['proposal_id']}/accept",
        headers=headers,
        json={"digest": original["digest"]},
    )
    assert accepted.status_code == (404 if access == "member" else expected)
    if access == "member":
        own = response.json()["data"]
        accepted = await client.post(
            base + f"/{own['proposal_id']}/accept", headers=headers, json={"digest": own["digest"]}
        )
        assert accepted.status_code == 200
    presence.provider.upload.assert_not_awaited()


async def test_wiring_change_during_uncertainty_checkpoint_refuses_before_upload(
    client, alice_headers, db, tmp_path, monkeypatch
):
    from solus_api.hardware.presence_topology import WiringRequest, WiringService
    from solus_api.models import GraphEntity

    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    wiring = WiringService(presence)
    proposal = await wiring.propose(robot, brain, WiringRequest(profile_id="uno_avr", mode="typed"))
    proposal_id = uuid.UUID(proposal["proposal_id"])
    await wiring.accept(robot, brain, proposal_id, proposal["digest"])
    plan = await presence.prepare(
        robot,
        brain,
        PreparePresence(
            profile_id="uno_avr",
            kind="topology",
            channel="uno.alive",
            wiring_proposal_id=proposal_id,
        ),
    )
    original = presence.record_outcome

    async def concurrent_change(*args, **kwargs):
        await original(*args, **kwargs)
        if kwargs.get("event_type") == "hardware.presence_attempt":
            entity = await db.get(GraphEntity, proposal_id)
            entity.attrs = {**entity.attrs, "digest": "0" * 64}
            await db.flush()

    monkeypatch.setattr(presence, "record_outcome", concurrent_change)
    with pytest.raises(APIError) as error:
        await presence.execute(uuid.UUID(plan["plan_id"]))
    assert error.value.status_code == 409
    presence.provider.upload.assert_not_awaited()
    assert (await presence.plan(uuid.UUID(plan["plan_id"]))).attrs["status"] == "prepared"
