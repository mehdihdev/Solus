"""SOLUSDEV-322 P5-T1 — `sim.map_to_parts`: a simulated joint becomes an alias of ONE graph part.

The tool is a static card (`requires_confirmation=True`, complete preview). Matching order: the
simulation model's joint binding name, then a part's name or its telemetry channel prefix; one
candidate maps, anything else stays unmapped and is named on the card. The write is
`attrs.sim_aliases = existing + [{provider, device_id}]`, deduped and REASSIGNED under the
project lock; `external_ref` is never touched. Every test in this file is driven by scripted
state only: no simulator, no companion.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import pytest
from solus_api.agent.confirmations import request_confirmation
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.runtime import DispatchFn, build_dispatch, build_sol_registry
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.agent.tools.sim_mapping import EVENT, NAME, SimMappingTool
from solus_api.agent.tools.tool import ToolException
from solus_api.hardware.config import (
    EntityHardwareConfig,
    FieldProvenance,
    PartConfig,
    ProvenanceRecord,
    TelemetryChannel,
)
from solus_api.hardware.store import put_entity_config
from solus_api.models import DataEvent, Domain, GraphEntity, Project, Team, ToolConfirmation, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]
PROVIDER = "gazebo"
REF = "feetech:usb-1/3"


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


class MappingScope:
    """One project, one person and the parts the tests map onto."""

    def __init__(self, project: Project, user: User, parts: dict[str, GraphEntity]) -> None:
        self.project, self.user, self.parts = project, user, parts
        self.team_id = project.team_id


def _arm_model(parts: dict[str, GraphEntity]) -> dict[str, Any]:
    files = {"arm.urdf": "0" * 64}
    manifest = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": 2,
        "asset": {
            "urdf_path": "arm.urdf",
            "files": files,
            "sha256": hashlib.sha256(manifest).hexdigest(),
        },
        "links": [
            {"entity_id": str(parts["base"].id), "name": "base"},
            {"entity_id": str(parts["tip"].id), "name": "tip"},
        ],
        "joints": [
            {
                "entity_id": str(parts["hinge"].id),
                "name": "hinge",
                "parent_link_entity_id": str(parts["base"].id),
                "child_link_entity_id": str(parts["tip"].id),
                "lower_rad": -1.0,
                "upper_rad": 1.0,
            }
        ],
        "sensors": [],
    }


async def _mapping_scope(db: AsyncSession, *, name: str = "Mapping") -> MappingScope:
    user = User(supabase_user_id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.test")
    team = Team(name=name)
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name=name, created_by=user.id)
    db.add(project)
    await db.flush()
    pid = project.id

    def part(label: str, **extra: Any) -> GraphEntity:
        return GraphEntity(
            project_id=pid, domain=Domain.PROJECT, kind="part", origin="manual", name=label, **extra
        )

    parts = {
        "base": part("Base plate"),
        "tip": part("Gripper"),
        # The binding's name is `hinge`; the part's name is not, so only the model maps it.
        "hinge": part("Elbow servo", external_ref=REF),
        "wrist_a": part("Wrist"),
        "wrist_b": part("wrist"),
        "shoulder": part("Shoulder servo"),
    }
    db.add_all(parts.values())
    await db.flush()
    parts["model"] = GraphEntity(
        project_id=pid,
        domain=Domain.SIMULATION,
        kind="simulation_model",
        origin="manual",
        name="Arm",
        attrs={"simulation_model": _arm_model(parts)},
    )
    db.add(parts["model"])
    await db.flush()
    # `shoulder` is found through its telemetry channel prefix (`shoulder.position`).
    await put_entity_config(
        db,
        pid,
        parts["shoulder"],
        EntityHardwareConfig(
            entity_id=parts["shoulder"].id,
            component=PartConfig(telemetry=[TelemetryChannel(name="shoulder.position")]),
            provenance={"component": ProvenanceRecord(by=FieldProvenance.USER)},
        ),
        expected_version=0,
        created_by=user.id,
    )
    await db.commit()
    return MappingScope(project, user, parts)


def _mapping_tool(maker: Maker, scope: MappingScope) -> SimMappingTool:
    return SimMappingTool(maker, scope.project.id, user_id=scope.user.id)


def _map_args(*channels: tuple[str, str], **extra: Any) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "channels": [{"device_id": d, "joint_name": j} for d, j in channels],
        **extra,
    }


async def _alias_state(maker: Maker, entity_id: uuid.UUID) -> tuple[list[Any] | None, str | None]:
    async with maker() as db:
        row = await db.get(GraphEntity, entity_id)
        assert row is not None
        return row.attrs.get("sim_aliases"), row.external_ref


async def _mapping_events(maker: Maker) -> list[DataEvent]:
    async with maker() as session:
        return list(await session.scalars(select(DataEvent).where(DataEvent.event_type == EVENT)))


def _mapping_dispatch(
    mode: ActionMode, registry: ToolRegistry, maker: Maker, scope: MappingScope
) -> DispatchFn:
    async def park(call: ToolCall) -> Any:
        async with maker() as db:
            parked = await request_confirmation(
                db,
                registry,
                call,
                project_id=scope.project.id,
                team_id=scope.team_id,
                user_id=scope.user.id,
            )
            await db.commit()
            return parked

    return build_mode_dispatch(
        mode, registry.list(), build_dispatch(registry, park), registry=registry
    )


# ------------------------------------------------------------------- matching and the write


async def test_exact_joint_name_maps_and_ambiguous_stays_unmapped_and_named(
    db: AsyncSession, maker: Maker
) -> None:
    scope = await _mapping_scope(db)
    tool = _mapping_tool(maker, scope)
    model_id = str(scope.parts["model"].id)
    args = _map_args(
        ("demo/arm/hinge", "hinge"),
        ("demo/arm/wrist", "wrist"),
        ("demo/arm/shoulder", "shoulder"),
        ("demo/arm/nothing", "nothing"),
        model_entity_id=model_id,
    )

    rows = await tool.preview(args)

    assert rows == [
        {"label": "Elbow servo", "before": None, "after": "gazebo/demo/arm/hinge"},
        {"label": "Shoulder servo", "before": None, "after": "gazebo/demo/arm/shoulder"},
        {"label": "unmapped: wrist (ambiguous: Wrist, wrist)", "before": None, "after": None},
        {"label": "unmapped: nothing (no part matches)", "before": None, "after": None},
    ]

    value = await tool.invoke(args)

    assert value == {
        "provider": PROVIDER,
        "mapped": [
            {
                "part_id": str(scope.parts["hinge"].id),
                "part": "Elbow servo",
                "device_id": "demo/arm/hinge",
            },
            {
                "part_id": str(scope.parts["shoulder"].id),
                "part": "Shoulder servo",
                "device_id": "demo/arm/shoulder",
            },
        ],
        "unmapped": [
            {"joint_name": "wrist", "reason": "ambiguous: Wrist, wrist"},
            {"joint_name": "nothing", "reason": "no part matches"},
        ],
    }
    aliases, _ = await _alias_state(maker, scope.parts["hinge"].id)
    assert aliases == [{"provider": PROVIDER, "device_id": "demo/arm/hinge"}]
    for key in ("wrist_a", "wrist_b", "base"):
        assert (await _alias_state(maker, scope.parts[key].id))[0] is None

    # The same mapping approved again is idempotent; another provider's alias is appended.
    await tool.invoke(args)
    other = _map_args(("scene/hinge", "hinge"), provider="mujoco", model_entity_id=model_id)
    rows = await tool.preview(other)
    assert rows == [{"label": "Elbow servo", "before": None, "after": "mujoco/scene/hinge"}]
    await tool.invoke(other)
    aliases, _ = await _alias_state(maker, scope.parts["hinge"].id)
    assert aliases == [
        {"provider": PROVIDER, "device_id": "demo/arm/hinge"},
        {"provider": "mujoco", "device_id": "scene/hinge"},
    ]
    rows = await tool.preview(_map_args(("demo/arm/hinge2", "hinge"), model_entity_id=model_id))
    assert rows == [
        {
            "label": "Elbow servo",
            "before": "gazebo/demo/arm/hinge",
            "after": "gazebo/demo/arm/hinge2",
        }
    ]
    assert await _mapping_events(maker) == [], "the test person has not consented"


async def test_external_ref_is_never_touched(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)
    tool = _mapping_tool(maker, scope)
    args = _map_args(("demo/arm/hinge", "hinge"), model_entity_id=str(scope.parts["model"].id))

    await tool.preview(args)
    await tool.invoke(args)

    aliases, external_ref = await _alias_state(maker, scope.parts["hinge"].id)
    assert external_ref == REF
    assert aliases == [{"provider": PROVIDER, "device_id": "demo/arm/hinge"}]


async def test_consented_mapping_emits_sim_aliases_mapped(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)
    scope.user.data_collection_consent = True
    db.add(scope.user)
    await db.commit()

    await _mapping_tool(maker, scope).invoke(
        _map_args(("demo/arm/shoulder", "shoulder"), ("demo/arm/wrist", "wrist"))
    )

    events = await _mapping_events(maker)
    assert len(events) == 1
    assert events[0].project_id == scope.project.id and events[0].team_id == scope.team_id
    assert events[0].payload == {
        "provider": PROVIDER,
        "mapped": 1,
        "unmapped": 1,
        "part_ids": [str(scope.parts["shoulder"].id)],
    }


async def test_nothing_to_map_refuses_the_card(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)
    tool = _mapping_tool(maker, scope)

    with pytest.raises(PreviewRefusal, match="no joint matched"):
        await tool.preview(_map_args(("demo/arm/wrist", "wrist")))
    with pytest.raises(ToolException, match="no joint matched"):
        await tool.invoke(_map_args(("demo/arm/wrist", "wrist")))
    assert (await _alias_state(maker, scope.parts["wrist_a"].id))[0] is None


async def test_robot_scope_narrows_the_candidates(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)
    robot = GraphEntity(
        project_id=scope.project.id,
        domain=Domain.PROJECT,
        kind="physical_robot",
        origin="manual",
        name="Arm 1",
    )
    db.add(robot)
    await db.flush()
    wrist = scope.parts["wrist_a"]
    wrist.attrs = {**wrist.attrs, "robot_id": str(robot.id)}
    db.add(wrist)
    await db.commit()

    rows = await _mapping_tool(maker, scope).preview(
        _map_args(("demo/arm/wrist", "wrist"), robot_id=str(robot.id))
    )

    assert rows == [{"label": "Wrist", "before": None, "after": "gazebo/demo/arm/wrist"}]


async def test_hostile_channel_arguments_are_refused(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)
    tool = _mapping_tool(maker, scope)
    bad = [
        _map_args(("-rf", "hinge")),
        _map_args(("demo/arm/hinge", "hinge; drop")),
        _map_args(("demo/arm/{hinge}", "hinge")),
        _map_args(*((f"demo/arm/j{i}", f"j{i}") for i in range(65))),
        _map_args(("demo/arm/a", "hinge"), ("demo/arm/b", "hinge")),
        _map_args(("demo/arm/hinge", "hinge"), provider="Gazebo Harmonic"),
        _map_args(("demo/arm/hinge", "hinge"), extra=1),
        _map_args(("demo/arm/hinge", "hinge"), session_id="-x"),
    ]
    for args in bad:
        with pytest.raises(ToolException) as failure:
            await tool.preview(args)
        assert failure.value.code is ToolErrorCode.INVALID_ARGS, args


async def test_unknown_session_is_refused(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)

    with pytest.raises(ToolException) as failure:
        await _mapping_tool(maker, scope).preview(
            _map_args(("demo/arm/shoulder", "shoulder"), session_id=str(uuid.uuid4()))
        )

    assert failure.value.code is ToolErrorCode.NOT_FOUND


# --------------------------------------------------------------------------- the gate and scope


async def test_map_is_a_card_in_build_and_refused_in_guide(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)
    registry = ToolRegistry()
    registry.register(_mapping_tool(maker, scope))
    call = ToolCall(
        tool=NAME,
        args=_map_args(("demo/arm/hinge", "hinge"), model_entity_id=str(scope.parts["model"].id)),
    )

    parked = await _mapping_dispatch(ActionMode.DO, registry, maker, scope)(call)
    assert not parked.ok and parked.error is not None
    assert parked.error.code is ToolErrorCode.UNAUTHORIZED
    assert "waiting for the person to approve" in parked.error.message
    async with maker() as session:
        rows = list(await session.scalars(select(ToolConfirmation)))
    assert [(r.tool, r.args) for r in rows] == [(call.tool, call.args)]
    assert rows[0].preview == [
        {"label": "Elbow servo", "before": None, "after": "gazebo/demo/arm/hinge"}
    ]

    refused = await _mapping_dispatch(ActionMode.GUIDE, registry, maker, scope)(call)
    assert not refused.ok and refused.error is not None
    assert "Guide mode can explain" in refused.error.message
    async with maker() as session:
        assert len(list(await session.scalars(select(ToolConfirmation)))) == 1
    assert (await _alias_state(maker, scope.parts["hinge"].id))[0] is None, "nothing ran"


async def test_cross_project_part_refused(db: AsyncSession, maker: Maker) -> None:
    mine = await _mapping_scope(db)
    theirs = await _mapping_scope(db, name="Theirs")
    tool = _mapping_tool(maker, mine)
    hinge = ("demo/arm/hinge", "hinge")
    foreign_model = _map_args(hinge, model_entity_id=str(theirs.parts["model"].id))
    foreign_robot = _map_args(hinge, robot_id=str(theirs.parts["model"].id))

    for args in (foreign_model, foreign_robot):
        for step in (tool.preview, tool.invoke):
            with pytest.raises(ToolException) as failure:
                await step(args)
            assert failure.value.code is ToolErrorCode.NOT_FOUND, (args, step)

    # A model in MY project whose binding points at THEIR part is refused too, not followed.
    model = _arm_model(mine.parts)
    model["joints"][0]["entity_id"] = str(theirs.parts["hinge"].id)
    mine.parts["model"].attrs = {"simulation_model": model}
    db.add(mine.parts["model"])
    await db.commit()
    with pytest.raises(ToolException) as failure:
        await tool.invoke(_map_args(hinge, model_entity_id=str(mine.parts["model"].id)))
    assert failure.value.code is ToolErrorCode.NOT_FOUND
    assert (await _alias_state(maker, theirs.parts["hinge"].id))[0] is None
    assert (await _alias_state(maker, mine.parts["hinge"].id))[0] is None


async def test_registered_only_when_a_person_is_bound(db: AsyncSession, maker: Maker) -> None:
    scope = await _mapping_scope(db)

    bare = {d.name for d in build_sol_registry(maker, scope.project.id).list()}
    bound = build_sol_registry(maker, scope.project.id, user_id=scope.user.id)

    assert NAME not in bare
    descriptor = next(d for d in bound.list() if d.name == NAME)
    assert descriptor.requires_confirmation is True
    tool = next(t for t in bound.tools() if t.descriptor.name == NAME)
    assert getattr(tool, "requires_complete_preview", False) is True


async def test_generated_joint_entities_map_the_part_they_move(
    db: AsyncSession, maker: Maker
) -> None:
    """Rung 3 (SOLUSDEV-322 P6-T2): a generated model's `joint` entity names the part it moves —
    its actuator when the bus map states one, else the mate's child — so a channel named after
    the generated joint maps when no binding and no part name does."""
    from solus_api.graph import kinds

    scope = await _mapping_scope(db)
    pid = scope.project.id

    def joint(name: str, child: GraphEntity, actuator: GraphEntity | None) -> GraphEntity:
        return GraphEntity(
            project_id=pid,
            domain=Domain.SIMULATION,
            kind=kinds.JOINT,
            origin="system",
            name=name,
            external_ref=f"solus:sim-joint:test:{name}",
            attrs={
                "robot_id": str(uuid.uuid4()),
                "child_part_id": str(child.id),
                "actuator_part_id": str(actuator.id) if actuator is not None else None,
            },
        )

    db.add_all(
        [
            joint("Fm9", scope.parts["tip"], None),
            joint("Fm8", scope.parts["tip"], scope.parts["hinge"]),
        ]
    )
    await db.commit()
    tool = _mapping_tool(maker, scope)

    rows = await tool.preview(_map_args(("demo/arm/Fm9", "Fm9"), ("demo/arm/Fm8", "Fm8")))

    assert rows == [
        {"label": "Gripper", "before": None, "after": "gazebo/demo/arm/Fm9"},
        {"label": "Elbow servo", "before": None, "after": "gazebo/demo/arm/Fm8"},
    ]
    # A generated joint of another robot is outside a robot-scoped mapping.
    robot = GraphEntity(
        project_id=pid, domain=Domain.PROJECT, kind="physical_robot", origin="manual", name="Arm 2"
    )
    db.add(robot)
    await db.commit()
    with pytest.raises(PreviewRefusal):
        await tool.preview(_map_args(("demo/arm/Fm9", "Fm9"), robot_id=str(robot.id)))


async def test_generated_joints_never_reach_across_projects(db: AsyncSession, maker: Maker) -> None:
    """Rung 3 isolation (CLAUDE.md §7): THEIR generated joint named like my channel, and MY
    generated joint whose moved part is THEIRS, both leave the channel unmapped; their part is
    never named on the card and never written."""
    from solus_api.graph import kinds

    mine = await _mapping_scope(db)
    theirs = await _mapping_scope(db, name="Theirs")
    theirs.parts["tip"].name, theirs.parts["hinge"].name = "Foreign gripper", "Foreign servo"

    def joint(pid: uuid.UUID, name: str, moved: GraphEntity) -> GraphEntity:
        return GraphEntity(
            project_id=pid,
            domain=Domain.SIMULATION,
            kind=kinds.JOINT,
            origin="system",
            name=name,
            external_ref=f"solus:sim-joint:{pid}:{name}",
            attrs={
                "robot_id": str(uuid.uuid4()),
                "child_part_id": str(moved.id),
                "actuator_part_id": str(moved.id),
            },
        )

    db.add_all(
        [
            theirs.parts["tip"],
            theirs.parts["hinge"],
            joint(theirs.project.id, "Fm9", theirs.parts["tip"]),
            joint(mine.project.id, "Fm8", theirs.parts["hinge"]),
        ]
    )
    await db.commit()
    tool = _mapping_tool(maker, mine)
    args = _map_args(
        ("demo/arm/hinge", "hinge"),
        ("demo/arm/Fm9", "Fm9"),
        ("demo/arm/Fm8", "Fm8"),
        model_entity_id=str(mine.parts["model"].id),
    )

    rows = await tool.preview(args)
    value = await tool.invoke(args)

    assert rows == [
        {"label": "Elbow servo", "before": None, "after": "gazebo/demo/arm/hinge"},
        {"label": "unmapped: Fm9 (no part matches)", "before": None, "after": None},
        {"label": "unmapped: Fm8 (no part matches)", "before": None, "after": None},
    ]
    assert value["unmapped"] == [
        {"joint_name": "Fm9", "reason": "no part matches"},
        {"joint_name": "Fm8", "reason": "no part matches"},
    ]
    assert "Foreign" not in json.dumps(rows) + json.dumps(value)
    for key in ("tip", "hinge"):
        assert (await _alias_state(maker, theirs.parts[key].id))[0] is None
