"""SOLUSDEV-321 P1-T2 — the fake arm: the graph half of the acceptance robot (P1, P2 and §5).

Q3: nothing vendor- or motor-specific. Every name and number here is synthetic and labelled
fake, and no part carries a `definition_id`. The frames that drive it are recorded in
`livebench/tests/fixtures/serial_fake_arm_stall.json` (P2-T4, made by `make_fake_arm_stall.py`
beside it; `test_stall_replay.py` checks the two agree). Seeded through the production writers —
`put_entity_config` for every config, `write_edge` for every edge — and idempotent: a second seed
of the same project returns the ids already there.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.hardware.config import (
    BusMapEntry,
    EntityHardwareConfig,
    FieldProvenance,
    PartConfig,
    PartLimits,
    PortableTransportBinding,
    ProtocolBinding,
    ProvenanceRecord,
    TelemetryChannel,
    TransportKind,
    part_ref,
)
from solus_api.hardware.store import put_entity_config
from solus_api.models import Domain, GraphEntity
from solus_contracts.relations import EdgeEvidence, EdgeOrigin, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

USB_SERIAL: Final = "FAKE-ARM-0001"
DEVICE_REF: Final = f"usb:{USB_SERIAL}"
#: Solus's generic line driver: data in the config, not a vendor.
DRIVER_ID: Final = "lb06"
CODE_PATH: Final = "fw/fake_arm.ino"
ROBOT_NAME: Final = "Fake arm"
BRAIN_NAME: Final = "fake brain"
BUS_NAME: Final = "fake bus"
#: Address n is part n; `actuator 5` is the one part not named a servo.
PART_NAMES: Final = (
    "servo 1 (joint 1)",
    "servo 2 (joint 2)",
    "servo 3 (joint 3)",
    "servo 4 (joint 4)",
    "actuator 5 (joint 5)",
    "servo 6 (joint 6)",
)
#: Fake, labelled limits — every part the same.
LIMITS: Final[dict[str, float | int]] = {
    "stall_current_a": 2.0,
    "current_a": 1.0,
    "temp_c": 70,
    "voltage_min_v": 6.0,
    "voltage_max_v": 8.4,
    "position_min": -150,
    "position_max": 150,
}
#: Five channels per part, `servoN.<quantity>` for every N.
CHANNELS: Final = (
    ("position", "deg"),
    ("commanded_position", "deg"),
    ("current", "A"),
    ("temperature", "degC"),
    ("voltage", "V"),
)
_FIRST_LINE: Final = 10
_SEEDED: Final = ProvenanceRecord(by=FieldProvenance.USER)


@dataclass(frozen=True)
class FakeArm:
    robot: uuid.UUID
    brain: uuid.UUID
    bus: uuid.UUID
    #: In address order: `parts[n - 1]` is address n.
    parts: tuple[uuid.UUID, ...]
    code_file: uuid.UUID


async def seed_fake_arm(
    session: AsyncSession, project_id: uuid.UUID, *, user_id: uuid.UUID | None
) -> FakeArm:
    """The fake arm in `project_id`. Flushes; the caller commits."""
    existing = await _entity(session, project_id, kinds.PHYSICAL_ROBOT, ROBOT_NAME)
    if existing is not None:
        return await _seeded(session, project_id, existing)
    robot = _node(project_id, kinds.PHYSICAL_ROBOT, Domain.PROJECT, ROBOT_NAME, ref=DEVICE_REF)
    brain = _node(project_id, kinds.HARDWARE_BRAIN, Domain.ELECTRICAL, BRAIN_NAME)
    bus = _node(project_id, kinds.HARDWARE_BUS, Domain.ELECTRICAL, BUS_NAME)
    code = _node(project_id, kinds.CODE_FILE, Domain.CODE, CODE_PATH, path=CODE_PATH)
    parts = [
        _node(project_id, kinds.PART, Domain.ELECTRICAL, name, ref=part_ref(DEVICE_REF, str(n)))
        for n, name in enumerate(PART_NAMES, start=1)
    ]
    session.add_all([robot, brain, bus, code, *parts])
    await session.flush()
    await put_entity_config(
        session,
        project_id,
        robot,
        EntityHardwareConfig(
            entity_id=robot.id,
            identity=PortableTransportBinding(kind=TransportKind.USB_SERIAL, binding=USB_SERIAL),
            protocol=ProtocolBinding(driver_id=DRIVER_ID),
            bus_map=[
                BusMapEntry(protocol=DRIVER_ID, address=str(n), part_entity_id=part.id)
                for n, part in enumerate(parts, start=1)
            ],
            provenance={"identity": _SEEDED, "protocol": _SEEDED, "bus_map": _SEEDED},
        ),
        expected_version=0,
        created_by=user_id,
    )
    for n, part in enumerate(parts, start=1):
        await put_entity_config(
            session,
            project_id,
            part,
            EntityHardwareConfig(
                entity_id=part.id,
                component=PartConfig(
                    telemetry=[
                        TelemetryChannel(name=f"servo{n}.{quantity}", unit=unit)
                        for quantity, unit in CHANNELS
                    ],
                    limits=PartLimits(values=dict(LIMITS)),
                ),
                provenance={"component": _SEEDED},
            ),
            expected_version=0,
            created_by=user_id,
        )
    edges = [
        (brain.id, bus.id, RelationType.HARDWARE_CONNECTED_TO, []),
        *((robot.id, part.id, RelationType.CONTAINS, []) for part in parts),
        *((bus.id, part.id, RelationType.DRIVES, []) for part in parts),
        *(
            (
                code.id,
                part.id,
                RelationType.COMMANDS,
                [
                    EdgeEvidence(
                        kind=EvidenceKind.FIRMWARE_SYMBOL, ref=f"{CODE_PATH}:{_FIRST_LINE + n}"
                    )
                ],
            )
            for n, part in enumerate(parts, start=1)
        ),
    ]
    for src_id, dst_id, relation, evidence in edges:
        await write_edge(
            session,
            project_id=project_id,
            src_id=src_id,
            dst_id=dst_id,
            relation_type=relation.value,
            origin=EdgeOrigin.MANUAL.value,
            confidence=1.0,
            evidence=evidence,
            created_by=user_id,
        )
    return FakeArm(
        robot=robot.id,
        brain=brain.id,
        bus=bus.id,
        parts=tuple(part.id for part in parts),
        code_file=code.id,
    )


def _node(
    project_id: uuid.UUID,
    kind: str,
    domain: Domain,
    name: str,
    *,
    ref: str | None = None,
    path: str | None = None,
) -> GraphEntity:
    attrs: dict[str, object] = {"fake": True, **({"path": path} if path else {})}
    return GraphEntity(
        id=uuid.uuid4(),
        project_id=project_id,
        kind=kind,
        domain=domain,
        origin="manual",
        name=name,
        external_ref=ref,
        attrs=attrs,
    )


async def _entity(
    session: AsyncSession, project_id: uuid.UUID, kind: str, name: str
) -> GraphEntity | None:
    row: GraphEntity | None = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kind,
            GraphEntity.name == name,
            GraphEntity.deleted_at.is_(None),
        )
    )
    return row


async def _seeded(session: AsyncSession, project_id: uuid.UUID, robot: GraphEntity) -> FakeArm:
    found = [
        await _entity(session, project_id, kind, name)
        for kind, name in (
            (kinds.HARDWARE_BRAIN, BRAIN_NAME),
            (kinds.HARDWARE_BUS, BUS_NAME),
            (kinds.CODE_FILE, CODE_PATH),
            *((kinds.PART, name) for name in PART_NAMES),
        )
    ]
    if any(row is None for row in found):
        raise RuntimeError("a partial fake arm is in this project; delete it and seed again")
    brain, bus, code, *parts = (row.id for row in found if row is not None)
    return FakeArm(robot=robot.id, brain=brain, bus=bus, parts=tuple(parts), code_file=code)
