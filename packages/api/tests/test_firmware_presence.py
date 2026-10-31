"""Central gate descriptors and immutable presence plan validation, and the flash card's
simulation pre-check (SOLUSDEV-321 P4-T5, R116)."""

import hashlib
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from solus_api.agent.confirmations import (
    PRECHECK_LABEL,
    ParkedCall,
    decide_confirmation,
    request_confirmation,
)
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools import simulate as simulate_module
from solus_api.agent.tools.firmware_presence import make_presence_tool
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.graph.live import LiveHub
from solus_api.hardware.presence import PreparePresence, PresenceRefusalError
from solus_api.models import Project
from solus_api.simulation.sim_capability import SimResult
from solus_api.simulation.sim_facts import record_sim_result
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_prepare_has_no_client_paths_or_commands() -> None:
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


async def test_real_tool_is_confirmation_required_and_preview_never_uploads() -> None:
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


async def fixture_service(
    client: Any, headers: Any, db: Any, tmp_path: Any
) -> tuple[Any, uuid.UUID, uuid.UUID]:
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
    prepared: dict[str, Any] = {
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


async def test_plan_is_retained_creator_scoped_and_one_shot(
    client: Any, alice_headers: Any, db: Any, tmp_path: Any
) -> None:
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
async def test_plan_refusals_and_unknown_are_honest(
    client: Any, alice_headers: Any, db: Any, tmp_path: Any, failure: str
) -> None:
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


async def test_changed_config_and_actuator_bus_cannot_prepare(
    client: Any, alice_headers: Any, db: Any, tmp_path: Any
) -> None:
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


async def _near_its_yield(engine: Any, project_id: uuid.UUID, subject: uuid.UUID) -> None:
    """A rung-1 run that found `subject` at 85 % of its yield, inside the ladder's 0.8 band: the
    matrix's bracket rule is inconclusive about it, so the ladder proposes a higher rung first."""
    await record_sim_result(
        async_sessionmaker(engine, expire_on_commit=False),
        LiveHub(),
        project_id=project_id,
        subject_id=subject,
        rung=1,
        result=SimResult.model_validate(
            {
                "values": {
                    "stress_mpa": {"value": 234.6, "unit": "MPa"},
                    "yield_fraction": {"value": 0.85, "unit": None},
                },
                "provenance": {
                    "solver": "deterministic_mech:cantilever_bending",
                    "inputs": {
                        "load": {"value": {"force_n": 1173.0, "arm_m": 0.025}, "source": "known"}
                    },
                    "leaves_out": ["fatigue"],
                },
            }
        ),
        created_by=None,
    )


async def _flash_card(
    engine: Any, db: Any, service: Any, plan_id: str
) -> tuple[ToolRegistry, ParkedCall | None]:
    """The flash parked through the real registry and gate, as a SOL turn parks it."""
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        service.project_id,
        user_id=service.user_id,
        presence_service=service,
    )
    project = await db.get(Project, service.project_id)
    parked = await request_confirmation(
        db,
        registry,
        ToolCall(tool="hardware.flash_presence", args={"plan_id": plan_id}),
        project_id=service.project_id,
        team_id=project.team_id,
        user_id=service.user_id,
    )
    await db.commit()
    return registry, parked


@pytest.mark.parametrize("precheck", ["proposes", "raises", "outlasts its timeout"])
async def test_the_flash_card_shows_the_simulation_first_and_parks_without_it(
    client: Any,
    alice_headers: Any,
    db: Any,
    tmp_path: Any,
    engine: Any,
    monkeypatch: pytest.MonkeyPatch,
    precheck: str,
) -> None:
    """R116: the flash card's pre-check is about the robot it flashes, its focus entities. When
    the ladder proposes a run for one, the card carries that line after its own rows; when the
    pre-check raises or outlasts its timeout, the card parks with exactly its own rows (R99).
    Either way the approval flashes: the advice is no effect the gate holds it to (R118)."""
    service, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    prepared = await service.prepare(
        robot, brain, PreparePresence(profile_id="uno_avr", kind="heartbeat", channel="uno.alive")
    )
    await db.commit()
    own = [row["label"] for row in await service.preview(uuid.UUID(prepared["plan_id"]))]
    await _near_its_yield(engine, service.project_id, robot)

    async def stalled(session: AsyncSession, *args: Any) -> Any:
        await session.execute(select(func.pg_sleep(5)))

    def broken(*args: Any) -> Any:
        raise RuntimeError("the facts did not read")

    if precheck != "proposes":
        monkeypatch.setattr(simulate_module, "PRECHECK_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(
            simulate_module, "build_fact_store", broken if precheck == "raises" else stalled
        )
    registry, parked = await _flash_card(engine, db, service, prepared["plan_id"])

    assert parked is not None and parked.confirmation_id is not None
    labels = [row["label"] for row in parked.preview]
    assert labels == [*own, *([PRECHECK_LABEL] if precheck == "proposes" else [])]
    if precheck == "proposes":
        assert "yield_fraction is at 85% of its limit at rung 1" in parked.preview[-1]["after"]
    result = await decide_confirmation(
        db,
        registry,
        parked.confirmation_id,
        approve=True,
        project_id=service.project_id,
        user_id=service.user_id,
    )
    await db.commit()
    assert result.ok, result.error
    service.provider.upload.assert_awaited_once()


async def test_a_full_flash_card_leaves_the_pre_check_no_room_and_still_parks(
    client: Any, alice_headers: Any, db: Any, tmp_path: Any, engine: Any
) -> None:
    """Minor 3: firmware filling the card's 50 rows (4 + 46 source chunks) leaves the pre-check
    no room, so the card parks without its line rather than being refused as over its bound."""
    service, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    source = ("// status only\n" * 1534)[:23_000].encode()
    service.provider.prepare.return_value.update(
        source=source, source_sha256=hashlib.sha256(source).hexdigest()
    )
    prepared = await service.prepare(
        robot, brain, PreparePresence(profile_id="uno_avr", kind="heartbeat", channel="uno.alive")
    )
    await db.commit()
    await _near_its_yield(engine, service.project_id, robot)

    _, parked = await _flash_card(engine, db, service, prepared["plan_id"])

    assert parked is not None and parked.confirmation_id is not None
    assert len(parked.preview) == 50
    assert PRECHECK_LABEL not in {row["label"] for row in parked.preview}
