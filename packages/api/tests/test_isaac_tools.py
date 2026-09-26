"""The Isaac cloud adapter owns public inputs, graph scope and one-shot consent."""

import asyncio
import copy
import hashlib
import json
import uuid
from typing import Any

import pytest
from solus_api.agent.tools.isaac_tools import build_isaac_tools
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.models import Domain, GraphEntity, Project, Team, User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

SESSION = str(uuid.uuid4())
LINKS = ("pedestal", "boom", "tool_mount")
JOINTS = ("azimuth", "elevation")


def simulation_model(
    identities: list[str], *, joint_count: int = 2, sensor: bool = True
) -> dict[str, Any]:
    files = {"models/robot.urdf": "a" * 64}
    asset = {
        "urdf_path": "models/robot.urdf",
        "files": files,
        "sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    links = [{"entity_id": identities[i], "name": f"link_{i}"} for i in range(joint_count + 1)]
    joints = [
        {
            "entity_id": identities[joint_count + 1 + i],
            "name": f"axis_{i}",
            "parent_link_entity_id": links[i]["entity_id"],
            "child_link_entity_id": links[i + 1]["entity_id"],
            "lower_rad": -1.0 - i * 0.1,
            "upper_rad": 1.0 + i * 0.1,
        }
        for i in range(joint_count)
    ]
    sensors = (
        [
            {
                "entity_id": identities[-1],
                "parent_link_entity_id": links[-1]["entity_id"],
                "kind": "contact",
                "translation_m": [0.0, 0.0, 0.0],
                "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
                "radius_m": 0.01,
            }
        ]
        if sensor
        else []
    )
    return {
        "schema_version": 2,
        "asset": asset,
        "links": links,
        "joints": joints,
        "sensors": sensors,
    }


NAMES = (
    "probe",
    "status",
    "start",
    "stop",
    "load_model",
    "set_joint_limits",
    "set_sensor_pose",
    "run_routine",
)


class Native:
    def __init__(
        self, name: str, calls: list[tuple[str, dict[str, Any]]], state: dict[str, Any]
    ) -> None:
        self.descriptor = ToolDescriptor(
            name="isaac." + name,
            description="untrusted advert",
            params={"type": "object", "properties": {"resolved_model": {}, "script": {}}},
            returns={},
        )
        self.name, self.calls, self.state = name, calls, state
        self.plan: dict[str, Any] = {
            "ok": True,
            "dry_run": True,
            "preview": [
                {
                    "label": "Complete native action",
                    "before": "Observed state",
                    "after": "Concrete proposed state",
                }
            ],
            "fingerprint": "a" * 64,
        }

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((self.name, copy.deepcopy(args)))
        if self.name == "status":
            return copy.deepcopy(self.state)
        if self.name == "probe":
            return {"available": True, "platform": "Linux"}
        if args.get("dry_run") is True:
            return copy.deepcopy(self.plan)
        return {"ok": True, "session_id": SESSION}


def tools(
    engine: AsyncEngine, project: uuid.UUID
) -> tuple[dict[str, Any], dict[str, Native], list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    state = {
        "state": "running",
        "session_id": SESSION,
        "scene_generation": 0,
        "graph_digest": None,
        "model_entity_id": None,
        "loaded": False,
    }
    native = {"isaac." + name: Native(name, calls, state) for name in NAMES}
    built = build_isaac_tools(async_sessionmaker(engine, expire_on_commit=False), project, native)
    return {t.descriptor.name: t for t in built}, native, calls, state


async def graph(
    db: AsyncSession, *, nested_foreign: bool = False
) -> tuple[Project, GraphEntity, list[GraphEntity]]:
    user = User(supabase_user_id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.test")
    team = Team(name="Isaac test")
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Isaac", created_by=user.id)
    other = Project(team_id=team.id, name="Other", created_by=user.id)
    db.add_all([project, other])
    await db.flush()
    entities = [
        GraphEntity(
            project_id=project.id, domain=Domain.MECHANICAL, kind="component", name=name, attrs={}
        )
        for name in (*LINKS, *JOINTS, "contact")
    ]
    db.add_all(entities)
    await db.flush()
    if nested_foreign:
        entities[-1].project_id = other.id
    model = simulation_model([str(entity.id) for entity in entities])
    root = GraphEntity(
        project_id=project.id,
        domain=Domain.MECHANICAL,
        kind="assembly",
        name="Synthetic arm",
        attrs={"simulation_model": model},
    )
    db.add(root)
    await db.commit()
    return project, root, entities


def test_public_descriptors_are_cloud_owned(engine: AsyncEngine) -> None:
    built, _, _, _ = tools(engine, uuid.uuid4())
    assert set(built) == {"isaac." + n for n in NAMES}
    for name, tool in built.items():
        descriptor = tool.descriptor
        assert descriptor.params["additionalProperties"] is False
        assert not {"resolved_model", "graph_digest", "expected_scene_generation", "script"} & set(
            descriptor.params.get("properties", {})
        )
        assert descriptor.requires_confirmation is (name not in ("isaac.probe", "isaac.status"))
        if descriptor.requires_confirmation:
            assert tool.requires_complete_preview is True


@pytest.mark.parametrize("name", NAMES)
async def test_unknown_public_arguments_never_reach_bridge(engine: AsyncEngine, name: str) -> None:
    built, _, calls, _ = tools(engine, uuid.uuid4())
    with pytest.raises(ToolException) as error:
        await built["isaac." + name].invoke({"script": "bad"})
    assert error.value.code == ToolErrorCode.INVALID_ARGS
    assert not calls


async def test_load_resolves_every_entity_and_consumes_approval(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, root, _ = await graph(db)
    built, _, calls, _ = tools(engine, project.id)
    tool = built["isaac.load_model"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id)}
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert not calls
    rows = await tool.preview(args)
    assert any("Graph" in row["label"] for row in rows)
    assert await tool.invoke(args) == {"ok": True, "session_id": SESSION}
    writes = [arg for name, arg in calls if name == "load_model" and not arg["dry_run"]]
    assert len(writes) == 1
    assert writes[0]["resolved_model"]["asset"] == root.attrs["simulation_model"]["asset"]
    assert writes[0]["model_entity_id"] == str(root.id)
    assert writes[0]["expected_scene_generation"] == 0
    assert len(writes[0]["graph_digest"]) == 64
    with pytest.raises(ToolException):
        await tool.invoke(args)


@pytest.mark.parametrize("foreign", [False, True])
async def test_unknown_or_foreign_nested_graph_refused(
    db: AsyncSession, engine: AsyncEngine, foreign: bool
) -> None:
    project, root, _ = await graph(db, nested_foreign=foreign)
    built, _, calls, _ = tools(engine, project.id)
    if not foreign:
        root_id = str(uuid.uuid4())
    else:
        root_id = str(root.id)
    with pytest.raises(ToolException) as error:
        await built["isaac.load_model"].preview({"session_id": SESSION, "model_entity_id": root_id})
    assert error.value.code == ToolErrorCode.NOT_FOUND
    assert not any(name == "load_model" for name, _ in calls)


@pytest.mark.parametrize("target", ["root", "nested"])
async def test_different_team_graph_reference_is_refused(
    db: AsyncSession, engine: AsyncEngine, target: str
) -> None:
    project, root, entities = await graph(db)
    foreign_project, foreign_root, _ = await graph(db)
    assert foreign_project.team_id != project.team_id
    if target == "nested":
        entities[-1].project_id = foreign_project.id
        await db.commit()
    built, _, calls, _ = tools(engine, project.id)
    with pytest.raises(ToolException) as error:
        await built["isaac.load_model"].preview(
            {
                "session_id": SESSION,
                "model_entity_id": str(foreign_root.id if target == "root" else root.id),
            }
        )
    assert error.value.code == ToolErrorCode.NOT_FOUND
    assert not any(name == "load_model" for name, _ in calls)


async def test_child_task_execution_consumes_parent_approval(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, root, _ = await graph(db)
    built, _, calls, _ = tools(engine, project.id)
    tool = built["isaac.load_model"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id)}
    await tool.preview(args)
    await asyncio.create_task(tool.invoke(args))
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert sum(name == "load_model" and not arg["dry_run"] for name, arg in calls) == 1


async def test_independent_task_cannot_borrow_later_approval(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, root, _ = await graph(db)
    built, _, calls, _ = tools(engine, project.id)
    tool = built["isaac.load_model"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id)}
    ready = asyncio.Event()

    async def independent() -> None:
        await ready.wait()
        with pytest.raises(ToolException):
            await tool.invoke(args)

    task = asyncio.create_task(independent())
    try:
        await tool.preview(args)
    finally:
        ready.set()
    await task
    assert not any(name == "load_model" and not arg["dry_run"] for name, arg in calls)
    await tool.invoke(args)


@pytest.mark.parametrize("change", ["graph", "scene", "args", "native"])
async def test_approval_rechecks_graph_scene_arguments_and_native_plan(
    db: AsyncSession, engine: AsyncEngine, change: str
) -> None:
    project, root, entities = await graph(db)
    built, native, calls, state = tools(engine, project.id)
    tool = built["isaac.load_model"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id)}
    await tool.preview(args)
    if change == "graph":
        entities[0].version += 1
        await db.commit()
    if change == "scene":
        state["scene_generation"] = 1
    if change == "args":
        args["dry_run"] = True
    if change == "native":
        native["isaac.load_model"].plan["fingerprint"] = "b" * 64
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert not any(name == "load_model" and not value["dry_run"] for name, value in calls)


@pytest.mark.parametrize(
    "plan",
    [
        {"ok": True, "dry_run": False},
        {"ok": True, "dry_run": True, "preview": [], "fingerprint": "a" * 64},
        {
            "ok": True,
            "dry_run": True,
            "preview": [{"label": "x", "before": None, "after": "x" * 401}],
            "fingerprint": "a" * 64,
        },
    ],
)
async def test_no_complete_native_preview_means_no_action(
    engine: AsyncEngine, plan: dict[str, Any]
) -> None:
    built, native, calls, _ = tools(engine, uuid.uuid4())
    native["isaac.start"].plan = plan
    with pytest.raises(ToolException):
        await built["isaac.start"].preview({})
    with pytest.raises(ToolException):
        await built["isaac.start"].invoke({})
    assert not any(name == "start" and not arg["dry_run"] for name, arg in calls)


@pytest.mark.parametrize(
    "bad",
    [{"asset": "other"}, {"script": "bad"}, {"schema_version": True}, {"asset_sha256": "b" * 64}],
)
async def test_graph_model_is_strict_and_versioned(
    db: AsyncSession, engine: AsyncEngine, bad: dict[str, Any]
) -> None:
    project, root, _ = await graph(db)
    root.attrs = {"simulation_model": {**root.attrs["simulation_model"], **bad}}
    flag_modified(root, "attrs")
    await db.commit()
    built, _, calls, _ = tools(engine, project.id)
    with pytest.raises(ToolException):
        await built["isaac.load_model"].preview(
            {"session_id": SESSION, "model_entity_id": str(root.id)}
        )
    assert not any(name == "load_model" for name, _ in calls)


@pytest.mark.parametrize("operation", ["set_joint_limits", "set_sensor_pose", "run_routine"])
async def test_loaded_operations_bind_exact_graph_targets(
    db: AsyncSession, engine: AsyncEngine, operation: str
) -> None:
    project, root, entities = await graph(db)
    built, _, calls, state = tools(engine, project.id)
    await built["isaac.load_model"].preview(
        {"session_id": SESSION, "model_entity_id": str(root.id)}
    )
    digest = next(arg["graph_digest"] for name, arg in calls if name == "load_model")
    state.update({"loaded": True, "model_entity_id": str(root.id), "graph_digest": digest})
    args: dict[str, Any] = {"session_id": SESSION}
    if operation == "set_joint_limits":
        args.update({"joint_entity_id": str(entities[3].id), "lower": -0.5, "upper": 0.5})
    if operation == "set_sensor_pose":
        args.update(
            {
                "sensor_entity_id": str(entities[5].id),
                "translation_m": [0.01, 0, 0],
                "orientation_wxyz": [1, 0, 0, 0],
            }
        )
    if operation == "run_routine":
        positions = [{"joint_entity_id": str(e.id), "position_rad": 0.0} for e in entities[3:5]]
        args.update(
            {
                "routine": "joint_trajectory",
                "duration_s": 10.0,
                "joints": [
                    {"joint_entity_id": str(e.id), "lower": -0.1, "upper": 0.1}
                    for e in entities[3:5]
                ],
                "waypoints": [{"positions": positions} for _ in range(3)],
            }
        )
    tool = built["isaac." + operation]
    await tool.preview(args)
    await tool.invoke(args)
    write = [arg for name, arg in calls if name == operation and not arg["dry_run"]][0]
    assert write["graph_digest"] == digest
    assert write["expected_scene_generation"] == 0
    if operation == "run_routine":
        assert write["routine_spec"]["routine"] == "joint_trajectory"
    else:
        assert write["entity_id"] == args.get("joint_entity_id", args.get("sensor_entity_id"))


async def test_graph_change_during_final_native_preview_prevents_write(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, root, entities = await graph(db)
    built, native, calls, _ = tools(engine, project.id)
    tool = built["isaac.load_model"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id)}
    await tool.preview(args)
    original = native["isaac.load_model"].invoke

    async def changing_preview(arguments: dict[str, Any]) -> dict[str, Any]:
        result = await original(arguments)
        if arguments.get("dry_run") is True:
            entities[0].version += 1
            await db.commit()
        return result

    native["isaac.load_model"].invoke = changing_preview  # type: ignore[method-assign]
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert not any(name == "load_model" and not value["dry_run"] for name, value in calls)


async def test_native_mapper_redaction_and_full_routine_binding_fit_card(db, engine):
    import json
    import sys
    from pathlib import Path

    from mcp.types import CallToolResult
    from solus_api.agent.tools.untrusted import redact_value
    from solus_companion.dispatch import map_result

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from integrations.mcp.isaac.solus.server import wire_result

    project, root, entities = await graph(db)
    built, native, calls, state = tools(engine, project.id)
    resolved = await built["isaac.run_routine"].resolver.resolve(str(root.id))
    state.update(loaded=True, model_entity_id=str(root.id), graph_digest=resolved.digest)
    plan = native["isaac.run_routine"].plan
    plan["fingerprint"] = "0123456789abcdef" * 4
    plan["preview"] = [
        {"label": f"Native fact {index}", "before": None, "after": str(index)}
        for index in range(39)
    ]

    class Mapped:
        def __init__(self, source):
            self.source = source

        async def invoke(self, args):
            value = wire_result(await self.source.invoke(args))
            sdk = CallToolResult.model_validate_json(
                CallToolResult(content=[], structuredContent=value).model_dump_json()
            )
            frame = json.loads(map_result("owned", sdk))
            return redact_value(frame["data"]["value"])

    raw = {name: Mapped(tool) for name, tool in native.items()}
    wrappers = {
        tool.descriptor.name: tool
        for tool in build_isaac_tools(
            async_sessionmaker(engine, expire_on_commit=False), project.id, raw
        )
    }
    tool = wrappers["isaac.run_routine"]
    ids = [str(entity.id) for entity in entities[3:5]]
    args = {
        "session_id": SESSION,
        "routine": "joint_trajectory",
        "duration_s": 6,
        "joints": [{"joint_entity_id": identity, "lower": -0.1, "upper": 0.1} for identity in ids],
        "waypoints": [
            {
                "positions": [
                    {"joint_entity_id": identity, "position_rad": 0.05} for identity in ids
                ],
            }
            for _ in range(3)
        ],
    }
    rows = await tool.preview(args)
    assert len(rows) == 40
    assert rows[:39] == plan["preview"]
    assert str(root.id) in rows[-1]["after"]
    assert ":".join(plan["fingerprint"][i : i + 16] for i in range(0, 64, 16)) in rows[-1]["after"]
    assert ":".join(resolved.digest[i : i + 16] for i in range(0, 64, 16)) in rows[-1]["after"]
    assert await tool.invoke(args) == {"ok": True, "session_id": SESSION}
    writes = [value for name, value in calls if name == "run_routine" and not value["dry_run"]]
    assert len(writes) == 1 and writes[0]["graph_digest"] == resolved.digest


@pytest.mark.parametrize("value", ["[REDACTED]", "a" * 63, "a" * 16 + ":" + "b" * 48, "A" * 64])
async def test_malformed_wire_fingerprint_refused(engine, value):
    built, native, _, _ = tools(engine, uuid.uuid4())
    native["isaac.start"].plan["fingerprint"] = value
    with pytest.raises(ToolException):
        await built["isaac.start"].preview({})


async def test_legacy_model_refused_with_migration_guidance(db, engine):
    project, root, _ = await graph(db)
    root.attrs = {"simulation_model": {"schema_version": 1}}
    await db.commit()
    built, _, calls, _ = tools(engine, project.id)
    with pytest.raises(ToolException, match="version 2"):
        await built["isaac.load_model"].preview(
            {"session_id": SESSION, "model_entity_id": str(root.id)}
        )
    assert not any(name == "load_model" for name, _ in calls)


async def test_joint_bounds_come_from_selected_model(db, engine):
    project, root, entities = await graph(db)
    built, _, calls, state = tools(engine, project.id)
    graph_state = await built["isaac.set_joint_limits"].resolver.resolve(str(root.id))
    state.update(loaded=True, model_entity_id=str(root.id), graph_digest=graph_state.digest)
    args = {
        "session_id": SESSION,
        "joint_entity_id": str(entities[3].id),
        "lower": -1.1,
        "upper": 0.5,
    }
    with pytest.raises(ToolException, match="model limits"):
        await built["isaac.set_joint_limits"].preview(args)
    assert not any(name == "set_joint_limits" for name, _ in calls)
    args["lower"] = -0.9
    await built["isaac.set_joint_limits"].preview(args)
    await built["isaac.set_joint_limits"].invoke(args)


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_range",
        "missing_position",
        "foreign_position",
        "duplicate_position",
        "outside_model",
    ],
)
async def test_invalid_trajectory_never_reaches_native_action(db, engine, damage):
    project, root, entities = await graph(db)
    built, _, calls, state = tools(engine, project.id)
    resolved = await built["isaac.run_routine"].resolver.resolve(str(root.id))
    state.update(loaded=True, model_entity_id=str(root.id), graph_digest=resolved.digest)
    ids = [str(entity.id) for entity in entities[3:5]]
    args = {
        "session_id": SESSION,
        "routine": "joint_trajectory",
        "duration_s": 3.0,
        "joints": [{"joint_entity_id": identity, "lower": -0.5, "upper": 0.5} for identity in ids],
        "waypoints": [
            {"positions": [{"joint_entity_id": identity, "position_rad": 0.1} for identity in ids]}
        ],
    }
    positions = args["waypoints"][0]["positions"]
    if damage == "duplicate_range":
        args["joints"].append(args["joints"][0].copy())
    elif damage == "missing_position":
        positions.pop()
    elif damage == "foreign_position":
        positions[0]["joint_entity_id"] = str(uuid.uuid4())
    elif damage == "duplicate_position":
        positions.append(positions[0].copy())
    else:
        args["joints"][0]["lower"] = -1.5
    with pytest.raises(ToolException):
        await built["isaac.run_routine"].preview(args)
    assert not any(name == "run_routine" for name, _ in calls)
