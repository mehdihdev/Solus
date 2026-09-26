"""Central gate descriptors and immutable presence plan validation."""

import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from solus_api.agent.tools.firmware_presence import make_presence_tool
from solus_api.hardware.presence import PreparePresence, PresenceRefusalError


def test_prepare_has_no_client_paths_or_commands():
    assert PreparePresence(profile_id="uno_avr", kind="heartbeat", channel="uno.alive")
    for patch in (
        {"profile_id": "custom:fqbn"},
        {"path": "/dev/ttyACM0"},
        {"channel": 'bad";code'},
    ):
        with pytest.raises(ValidationError):
            PreparePresence.model_validate(
                dict(profile_id="uno_avr", kind="heartbeat", channel="uno.alive") | patch
            )


async def test_real_tool_is_confirmation_required_and_preview_never_uploads():
    service = AsyncMock()
    service.preview.return_value = [
        {"label": "Firmware", "before": "Existing program", "after": "full source"}
    ]
    service.execute.return_value = {"status": "flashed"}
    tool = make_presence_tool(service)
    plan = uuid.uuid4()
    assert tool.descriptor.name == "hardware.flash_presence"
    assert tool.descriptor.requires_confirmation
    rows = await tool.preview({"plan_id": str(plan)})
    assert rows[0]["after"] == "full source"
    service.execute.assert_not_awaited()
    assert await tool.invoke({"plan_id": str(plan)}) == {"status": "flashed"}
    service.execute.assert_awaited_once_with(plan)


async def fixture_service(client, headers, db, tmp_path):
    import hashlib
    from unittest.mock import Mock

    from conftest import me
    from solus_api.hardware.config import (
        FieldProvenance,
        HardwareConfig,
        ProvenanceRecord,
        TransportBinding,
        TransportKind,
    )
    from solus_api.hardware.presence import PresenceService
    from solus_api.hardware.topology import MARKER
    from solus_api.storage import LocalArtifactStore
    from test_hardware_router import _hw_project, _hw_url, _robot

    user = await me(client, headers)
    project, _ = await _hw_project(client, headers)
    robot = await _robot(client, headers, project)
    robot_id, project_id = uuid.UUID(robot["id"]), uuid.UUID(project)
    config = HardwareConfig(
        robot_entity_id=robot_id,
        identity=TransportBinding(
            kind=TransportKind.USB_SERIAL, binding="port-3-1", vid=0x1A86, pid=0x7523
        ),
        provenance={"identity": ProvenanceRecord(by=FieldProvenance.USER)},
    )
    response = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=headers,
        json={"config": config.model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    brain_id = uuid.uuid5(project_id, f"{MARKER}:endpoint:usb:port-3-1")
    provider = Mock()
    prepared = {
        "source": b"// status only",
        "binary": b":00000001FF\n",
        "target": {"binding": "port-3-1", "serial": None, "vid": 0x1A86, "pid": 0x7523},
    }
    for key in ("source", "binary"):
        prepared[key + "_sha256"] = hashlib.sha256(prepared[key]).hexdigest()
    provider.prepare = AsyncMock(return_value=prepared)
    provider.upload = AsyncMock()
    service = PresenceService(
        db, project_id, uuid.UUID(user["id"]), LocalArtifactStore(str(tmp_path)), provider
    )
    return service, robot_id, brain_id


async def test_plan_is_retained_creator_scoped_and_one_shot(client, alice_headers, db, tmp_path):
    from solus_api.core.errors import APIError
    from solus_api.hardware.presence import PresenceService

    service, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    prepared = await service.prepare(
        robot, brain, PreparePresence(profile_id="uno_avr", kind="heartbeat", channel="uno.alive")
    )
    await db.commit()
    plan = uuid.UUID(prepared["plan_id"])
    assert (await service.preview(plan))[-1]["after"] == "// status only"
    service.provider.upload.assert_not_awaited()
    foreign = PresenceService(db, service.project_id, uuid.uuid4(), service.store, service.provider)
    with pytest.raises(APIError, match="not found"):
        await foreign.preview(plan)
    wrong_project = PresenceService(
        db, uuid.uuid4(), service.user_id, service.store, service.provider
    )
    with pytest.raises(APIError, match="not found"):
        await wrong_project.preview(plan)
    assert (await service.execute(plan))["status"] == "flashed"
    with pytest.raises(APIError, match="already been attempted"):
        await service.execute(plan)
    service.provider.upload.assert_awaited_once()


@pytest.mark.parametrize("failure", ["digest", "identity", "in_use", "write", "write_value"])
async def test_plan_refusals_and_unknown_are_honest(client, alice_headers, db, tmp_path, failure):
    from solus_api.core.errors import APIError

    service, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    prepared = await service.prepare(
        robot, brain, PreparePresence(profile_id="uno_avr", kind="heartbeat", channel="uno.alive")
    )
    await db.commit()
    plan = uuid.UUID(prepared["plan_id"])
    entity = await service.plan(plan)
    if failure == "digest":
        await service.store.put(entity.attrs["binary_artifact_id"], b"changed")
    elif failure == "identity":
        service.provider.validate.side_effect = ValueError("changed")
    else:
        service.provider.upload.side_effect = (
            PresenceRefusalError("busy")
            if failure == "in_use"
            else ValueError("late write error")
            if failure == "write_value"
            else RuntimeError("interrupted")
        )
    with pytest.raises(APIError):
        await service.execute(plan)
    entity = await service.plan(plan)
    assert entity.attrs["status"] == (
        "unknown" if failure in ("write", "write_value") else "prepared"
    )
    if failure in ("digest", "identity"):
        service.provider.upload.assert_not_awaited()


async def test_changed_config_and_actuator_bus_cannot_prepare(client, alice_headers, db, tmp_path):
    from unittest.mock import AsyncMock

    from solus_api.core.errors import APIError

    service, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    with pytest.raises(APIError, match="target not found"):
        await service.binding(robot, uuid.uuid4())
    from test_hardware_router import _hw_url, _saved_serial_arm

    config = await _saved_serial_arm(client, alice_headers, str(service.project_id), str(robot))
    response = await client.put(
        _hw_url(str(service.project_id), "robots", str(robot), "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert response.status_code == 200
    from solus_api.hardware.topology import MARKER

    new_brain = uuid.uuid5(
        service.project_id, f"{MARKER}:endpoint:usb:{config['identity']['binding']}"
    )
    with pytest.raises(APIError, match="driver boards"):
        await service.prepare(
            robot,
            new_brain,
            PreparePresence(profile_id="uno_avr", kind="heartbeat", channel="uno.alive"),
        )
    service.provider.prepare.assert_not_awaited()
    service.provider = None
    assert service.profiles() == []
    with pytest.raises(APIError, match="unavailable"):
        await service.prepare(
            robot,
            brain,
            PreparePresence(profile_id="uno_avr", kind="heartbeat", channel="uno.alive"),
        )
    service.execute = AsyncMock(side_effect=APIError(409, "presence_changed", "changed"))
    from solus_api.agent.tools.tool import ToolException

    with pytest.raises(ToolException, match="changed"):
        await make_presence_tool(service).invoke({"plan_id": str(uuid.uuid4())})
