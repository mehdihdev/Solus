"""The Isaac cloud adapter owns public inputs, graph scope and one-shot consent."""

import asyncio
import base64
import copy
import hashlib
import json
import re
import uuid
from typing import Any, cast

import pytest
from pydantic import ValidationError
from solus_api.agent.confirmations import request_confirmation
from solus_api.agent.dynamic_gate import APPROVAL_REQUIRED_LABEL, needs_card
from solus_api.agent.execution_policy import BuildExecutionPolicy, register_owned_routine
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.runtime import DispatchFn, build_dispatch
from solus_api.agent.tools.isaac_models import PUBLIC_MODELS, READ_ONLY, Sensor
from solus_api.agent.tools.isaac_tools import build_isaac_tools
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.sim_assets import CHUNK_BYTES, MAX_DATA_B64
from solus_api.agent.tools.tool import Tool, ToolException
from solus_api.models import Domain, GraphEntity, Project, Team, ToolConfirmation, User
from solus_api.simulation.sessions_ledger import SessionsLedger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from test_gazebo_tools import FILES, MANIFEST, MODEL_SHA, MemoryStore
from test_gazebo_tools import graph as stage_graph

SESSION = str(uuid.uuid4())
STAGE = "nested/arm.usd"
ARTICULATION = "/World/arm"
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


NAMES = tuple(PUBLIC_MODELS)
assert NAMES[:8] == (
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
        self,
        name: str,
        calls: list[tuple[str, dict[str, Any]]],
        state: dict[str, Any],
        assets: set[str] | None = None,
    ) -> None:
        self.descriptor = ToolDescriptor(
            name="isaac." + name,
            description="untrusted advert",
            params={"type": "object", "properties": {"resolved_model": {}, "script": {}}},
            returns={},
        )
        self.name, self.calls, self.state = name, calls, state
        self.assets = {MODEL_SHA} if assets is None else assets
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

    READS = {
        "status": None,  # the shared state dict
        "probe": {"available": True, "platform": "Linux", "gui_attach": "unsupported"},
        "list_stages": {"ok": True, "roots": 1, "stages": [{"path": STAGE}]},
        "find_articulations": {"ok": True, "articulations": [{"path": ARTICULATION}]},
        "read_state": {"ok": True, "articulation": {"path": ARTICULATION, "dofs": {}}},
    }

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((self.name, copy.deepcopy(args)))
        if self.name in self.READS:
            return copy.deepcopy(self.READS[self.name] or self.state)
        if self.name == "put_asset":
            if args["index"] + 1 == args["total"]:
                self.assets.add(args["sha256"])
            return {"ok": True, "received": args["index"] + 1, "promoted": True}
        if self.name == "spawn_at" and args["model_sha256"] not in self.assets:
            return {"ok": False, "code": "model_not_verified", "reason": "push it first"}
        if args.get("dry_run") is True:
            return copy.deepcopy(self.plan)
        if self.name == "open_stage":
            return {"ok": True, "session_id": SESSION, "stage_ref": args["stage_ref"]}
        return {"ok": True, "session_id": SESSION}


def tools(
    engine: AsyncEngine,
    project: uuid.UUID,
    *,
    ledger: SessionsLedger | None = None,
    store: MemoryStore | None = None,
    asset_present: bool = True,
    put_asset: bool = True,
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
    assets: set[str] = {MODEL_SHA} if asset_present else set()
    native = {
        "isaac." + name: Native(name, calls, state, assets)
        for name in (*NAMES, *(("put_asset",) if put_asset else ()))
    }
    maker = async_sessionmaker(engine, expire_on_commit=False)
    built = build_isaac_tools(
        maker, project, native, ledger=ledger or SessionsLedger(maker), artifacts=store
    )
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
        # SOLUSDEV-322 P2-T3/P4-T2: the gate is per call (ownership ledger), not a static flag;
        # only `save_stage` (a write into the user's own file) is statically gated.
        assert descriptor.requires_confirmation is (name == "isaac.save_stage")
        assert tool.requires_complete_preview is (name[6:] not in READ_ONLY)
        assert callable(tool.needs_confirmation)
    assert READ_ONLY == {"probe", "status", "list_stages", "find_articulations", "read_state"}
    assert built["isaac.spawn_at"].descriptor.timeout_seconds == 300, "covers the chunk push"


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
    args: dict[str, Any] = {"session_id": SESSION, "model_entity_id": str(root.id)}
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
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
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

    monkeypatch.setattr(native["isaac.load_model"], "invoke", changing_preview)
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert not any(name == "load_model" and not value["dry_run"] for name, value in calls)


async def test_native_mapper_redaction_and_full_routine_binding_fit_card(
    db: AsyncSession, engine: AsyncEngine
) -> None:
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
        def __init__(self, source: Native) -> None:
            self.source = source
            self.descriptor = source.descriptor

        async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
            value = wire_result(await self.source.invoke(args))
            sdk = CallToolResult.model_validate_json(
                CallToolResult(content=[], structuredContent=value).model_dump_json()
            )
            frame = json.loads(map_result("owned", sdk))
            redacted: dict[str, Any] = redact_value(frame["data"]["value"])
            return redacted

    raw = {name: Mapped(tool) for name, tool in native.items()}
    maker = async_sessionmaker(engine, expire_on_commit=False)
    wrappers: dict[str, Any] = {
        tool.descriptor.name: tool
        for tool in build_isaac_tools(maker, project.id, raw, ledger=SessionsLedger(maker))
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
async def test_malformed_wire_fingerprint_refused(engine: AsyncEngine, value: str) -> None:
    built, native, _, _ = tools(engine, uuid.uuid4())
    native["isaac.start"].plan["fingerprint"] = value
    with pytest.raises(ToolException):
        await built["isaac.start"].preview({})


async def test_legacy_model_refused_with_migration_guidance(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, root, _ = await graph(db)
    root.attrs = {"simulation_model": {"schema_version": 1}}
    await db.commit()
    built, _, calls, _ = tools(engine, project.id)
    with pytest.raises(ToolException, match="version 2"):
        await built["isaac.load_model"].preview(
            {"session_id": SESSION, "model_entity_id": str(root.id)}
        )
    assert not any(name == "load_model" for name, _ in calls)


async def test_joint_bounds_come_from_selected_model(db: AsyncSession, engine: AsyncEngine) -> None:
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
async def test_invalid_trajectory_never_reaches_native_action(
    db: AsyncSession, engine: AsyncEngine, damage: str
) -> None:
    project, root, entities = await graph(db)
    built, _, calls, state = tools(engine, project.id)
    resolved = await built["isaac.run_routine"].resolver.resolve(str(root.id))
    state.update(loaded=True, model_entity_id=str(root.id), graph_digest=resolved.digest)
    ids = [str(entity.id) for entity in entities[3:5]]
    args: dict[str, Any] = {
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


# ------------------------------------------------- SOLUSDEV-322 P2-T3: gated per call by ownership


PROVIDER = "isaac"


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _registry(built: dict[str, Any]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in built.values():
        registry.register(tool)
    return registry


def _parking_dispatch(
    mode: ActionMode,
    registry: ToolRegistry,
    maker: async_sessionmaker[AsyncSession],
    project: Project,
) -> DispatchFn:
    """The production shape: Guide/Build mode layer outside, the real park inside."""
    user_id = project.created_by
    assert user_id is not None

    async def park(call: ToolCall) -> Any:
        async with maker() as db:
            parked = await request_confirmation(
                db,
                registry,
                call,
                project_id=project.id,
                team_id=project.team_id,
                user_id=user_id,
            )
            await db.commit()
            return parked

    return build_mode_dispatch(
        mode, registry.list(), build_dispatch(registry, park), registry=registry
    )


async def _confirmation_rows(maker: async_sessionmaker[AsyncSession]) -> list[ToolConfirmation]:
    async with maker() as db:
        return list(await db.scalars(select(ToolConfirmation)))


def _writes(calls: list[tuple[str, dict[str, Any]]], name: str) -> list[dict[str, Any]]:
    return [arg for op, arg in calls if op == name and not arg.get("dry_run")]


def _loaded_args(entities: list[GraphEntity]) -> dict[str, dict[str, Any]]:
    ids = [str(e.id) for e in entities[3:5]]
    return {
        "set_joint_limits": {"joint_entity_id": ids[0], "lower": -0.5, "upper": 0.5},
        "set_sensor_pose": {
            "sensor_entity_id": str(entities[5].id),
            "translation_m": [0.01, 0, 0],
            "orientation_wxyz": [1, 0, 0, 0],
        },
        "run_routine": {
            "routine": "joint_trajectory",
            "duration_s": 3.0,
            "joints": [{"joint_entity_id": i, "lower": -0.1, "upper": 0.1} for i in ids],
            "waypoints": [
                {"positions": [{"joint_entity_id": i, "position_rad": 0.0} for i in ids]}
                for _ in range(2)
            ],
        },
    }


@pytest.mark.parametrize("mode", [ActionMode.DO, ActionMode.GUIDE])
async def test_owned_session_runs_every_op_with_zero_cards_in_guide_and_build(
    db: AsyncSession, engine: AsyncEngine, mode: ActionMode
) -> None:
    project, root, entities = await graph(db)
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    built, _, calls, state = tools(engine, project.id, ledger=ledger)
    dispatch = _parking_dispatch(mode, _registry(built), maker, project)

    started = await dispatch(ToolCall(tool="isaac.start", args={}, call_id="call-start"))
    assert started.ok, started.error
    rows = await ledger.running(project_id=project.id, provider=PROVIDER)
    assert [(r.session_id, r.owner, r.started_by_call_id) for r in rows] == [
        (SESSION, "sol", "call-start")
    ]

    loaded = await dispatch(
        ToolCall(
            tool="isaac.load_model", args={"session_id": SESSION, "model_entity_id": str(root.id)}
        )
    )
    assert loaded.ok, loaded.error
    digest = _writes(calls, "load_model")[0]["graph_digest"]
    state.update({"loaded": True, "model_entity_id": str(root.id), "graph_digest": digest})
    for name, args in _loaded_args(entities).items():
        result = await dispatch(
            ToolCall(tool="isaac." + name, args={"session_id": SESSION, **args})
        )
        assert result.ok, (name, result.error)
        assert len(_writes(calls, name)) == 1, name

    stopped = await dispatch(ToolCall(tool="isaac.stop", args={"session_id": SESSION}))
    assert stopped.ok, stopped.error
    assert await ledger.running(project_id=project.id, provider=PROVIDER) == []
    assert await _confirmation_rows(maker) == []


@pytest.mark.parametrize("mode", [ActionMode.GUIDE, ActionMode.DO])
async def test_an_approval_required_preview_row_cards_an_owned_session(
    db: AsyncSession, engine: AsyncEngine, mode: ActionMode
) -> None:
    """P10 item 22: the fork's "Approval required" row (ADR-040 §5) makes an owned-session
    call card in Build and refuse in Guide; without it the call runs with no card."""
    project, _, _ = await graph(db)
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    await ledger.record_owned_start(
        project_id=project.id,
        provider=PROVIDER,
        session_id=SESSION,
        call_id=None,
        scene_ref=None,
        created_by=None,
    )
    built, native, calls, _ = tools(engine, project.id, ledger=ledger)
    native["isaac.control"].plan["preview"].append(
        {"label": APPROVAL_REQUIRED_LABEL, "before": None, "after": "the fork wants a person"}
    )
    dispatch = _parking_dispatch(mode, _registry(built), maker, project)
    args: dict[str, Any] = {"session_id": SESSION, "action": "step", "steps": 3}
    call = ToolCall(tool="isaac.control", args=args)

    result = await dispatch(call)
    assert not result.ok and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    rows = await _confirmation_rows(maker)
    if mode is ActionMode.DO:
        assert "waiting for the person to approve" in result.error.message
        assert [(r.tool, r.args) for r in rows] == [(call.tool, call.args)]
        assert any(r.get("label") == APPROVAL_REQUIRED_LABEL for r in rows[0].preview)
    else:
        assert "Guide mode can explain" in result.error.message
        assert rows == []
    assert _writes(calls, "control") == []

    # A different call on the same owned session, whose preview carries no such row: no card.
    # (The parked call itself keeps its ticket; re-sending it with a changed preview is stale.)
    native["isaac.control"].plan["preview"].pop()
    other = ToolCall(tool="isaac.control", args={"session_id": SESSION, "action": "pause"})
    assert (await dispatch(other)).ok, "a row-free preview on the same session needs no card"


@pytest.mark.parametrize("mode", [ActionMode.GUIDE, ActionMode.DO])
@pytest.mark.parametrize("name,args", [("start", {}), ("open_stage", {"stage_ref": STAGE})])
async def test_an_approval_required_row_on_a_session_start_cards_instead_of_dead_ending(
    db: AsyncSession, engine: AsyncEngine, mode: ActionMode, name: str, args: dict[str, Any]
) -> None:
    """Security review of b743b0c2: a session-creating call (owned by construction) carrying
    the label must reach a card in Build and a refusal in Guide — never an unapprovable
    refusal in `invoke`."""
    project, _, _ = await graph(db)
    maker = _maker(engine)
    built, native, calls, _ = tools(engine, project.id, ledger=SessionsLedger(maker))
    native["isaac." + name].plan["preview"].append(
        {"label": APPROVAL_REQUIRED_LABEL, "before": None, "after": "the fork wants a person"}
    )
    call = ToolCall(tool="isaac." + name, args=args)
    result = await _parking_dispatch(mode, _registry(built), maker, project)(call)
    assert not result.ok and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    rows = await _confirmation_rows(maker)
    if mode is ActionMode.DO:
        assert "waiting for the person to approve" in result.error.message
        assert [(r.tool, r.args) for r in rows] == [(call.tool, call.args)]
    else:
        assert "Guide mode can explain" in result.error.message
        assert rows == []
    assert _writes(calls, name) == []


async def test_invoke_without_ticket_refuses_when_the_preview_demands_approval(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, _, _ = await graph(db)
    ledger = SessionsLedger(_maker(engine))
    await ledger.record_owned_start(
        project_id=project.id,
        provider=PROVIDER,
        session_id=SESSION,
        call_id=None,
        scene_ref=None,
        created_by=None,
    )
    built, native, calls, _ = tools(engine, project.id, ledger=ledger)
    native["isaac.control"].plan["preview"].append(
        {"label": APPROVAL_REQUIRED_LABEL, "before": None, "after": "the fork wants a person"}
    )
    with pytest.raises(ToolException, match="confirmation"):
        await built["isaac.control"].invoke({"session_id": SESSION, "action": "step", "steps": 3})
    assert _writes(calls, "control") == []


@pytest.mark.parametrize("known", ["attached", "unknown"])
@pytest.mark.parametrize("name", ["load_model", "control"])
async def test_attached_or_unknown_session_cards_in_build_and_refuses_in_guide(
    db: AsyncSession, engine: AsyncEngine, known: str, name: str
) -> None:
    project, root, _ = await graph(db)
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    if known == "attached":
        await ledger.record_attached(
            project_id=project.id,
            provider=PROVIDER,
            session_id=SESSION,
            scene_ref=None,
            created_by=None,
        )
    built, _, calls, _ = tools(engine, project.id, ledger=ledger)
    registry = _registry(built)
    args: dict[str, Any] = {"session_id": SESSION}
    if name == "load_model":
        args["model_entity_id"] = str(root.id)
    else:
        args.update({"action": "step", "steps": 3})
    call = ToolCall(tool="isaac." + name, args=args)

    parked = await _parking_dispatch(ActionMode.DO, registry, maker, project)(call)
    assert not parked.ok and parked.error is not None
    assert parked.error.code is ToolErrorCode.UNAUTHORIZED
    assert "waiting for the person to approve" in parked.error.message
    rows = await _confirmation_rows(maker)
    assert [(r.tool, r.args) for r in rows] == [(call.tool, call.args)]

    refused = await _parking_dispatch(ActionMode.GUIDE, registry, maker, project)(call)
    assert not refused.ok and refused.error is not None
    assert "Guide mode can explain" in refused.error.message
    assert len(await _confirmation_rows(maker)) == 1, "Guide never reaches the park"
    assert _writes(calls, name) == []


async def test_forged_session_id_cards(db: AsyncSession, engine: AsyncEngine) -> None:
    project, root, _ = await graph(db)
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    await ledger.record_owned_start(
        project_id=project.id,
        provider=PROVIDER,
        session_id=SESSION,
        call_id=None,
        scene_ref=None,
        created_by=None,
    )
    built, _, calls, _ = tools(engine, project.id, ledger=ledger)
    tool = built["isaac.load_model"]
    forged = {"session_id": str(uuid.uuid4()), "model_entity_id": str(root.id)}

    assert await needs_card(tool, forged) is True
    assert await needs_card(tool, {**forged, "session_id": SESSION}) is False
    result = await build_dispatch(_registry(built), None)(
        ToolCall(tool="isaac.load_model", args=forged)
    )
    assert not result.ok and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    # The owned probe above read the fork's dry run (P10 item 22); the forged call ran nothing.
    assert _writes(calls, "load_model") == []
    assert all(name == "status" or args.get("dry_run") is True for name, args in calls)


class _BrokenLedger(SessionsLedger):
    async def is_owned(self, *, project_id: uuid.UUID, provider: str, session_id: str) -> bool:
        raise RuntimeError("ledger unreachable")


async def test_ledger_read_failure_cards(db: AsyncSession, engine: AsyncEngine) -> None:
    project, root, _ = await graph(db)
    built, _, calls, _ = tools(engine, project.id, ledger=_BrokenLedger(_maker(engine)))
    tool = built["isaac.load_model"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id)}

    assert await needs_card(tool, args) is True
    result = await build_dispatch(_registry(built), None)(
        ToolCall(tool="isaac.load_model", args=args)
    )
    assert not result.ok and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    # Defence in depth: the wrapper itself fails closed when its own hook cannot answer.
    with pytest.raises(ToolException, match="confirmation"):
        await tool.invoke(args)
    assert not calls


async def _owned(ledger: SessionsLedger, project: Project) -> None:
    await ledger.record_owned_start(
        project_id=project.id,
        provider=PROVIDER,
        session_id=SESSION,
        call_id=None,
        scene_ref=None,
        created_by=None,
    )


async def test_invoke_without_ticket_still_replans_and_refuses_on_graph_change(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, root, entities = await graph(db)
    ledger = SessionsLedger(_maker(engine))
    await _owned(ledger, project)
    built, native, calls, _ = tools(engine, project.id, ledger=ledger)
    tool = built["isaac.load_model"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id)}
    original = native["isaac.load_model"].invoke

    async def changing_preview(arguments: dict[str, Any]) -> dict[str, Any]:
        result = await original(arguments)
        if arguments.get("dry_run") is True:
            entities[0].version += 1
            await db.commit()
        return result

    monkeypatch.setattr(native["isaac.load_model"], "invoke", changing_preview)
    with pytest.raises(ToolException, match="graph changed"):
        await tool.invoke(args)
    assert [arg["dry_run"] for op, arg in calls if op == "load_model"] == [True]
    assert _writes(calls, "load_model") == []


async def test_a_parked_cards_leftover_ticket_does_not_poison_the_next_owned_call(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """`request_confirmation → _card_preview → preview()` leaves a ticket in the task's context
    when the card is parked; an owned call with other args in the same task must not trip on it."""
    project, root, entities = await graph(db)
    ledger = SessionsLedger(_maker(engine))
    await _owned(ledger, project)
    built, _, calls, state = tools(engine, project.id, ledger=ledger)
    digest = (await built["isaac.load_model"].resolver.resolve(str(root.id))).digest
    state.update({"loaded": True, "model_entity_id": str(root.id), "graph_digest": digest})
    limits = built["isaac.set_joint_limits"]
    parked_args = {
        "session_id": SESSION,
        "joint_entity_id": str(entities[3].id),
        "lower": -0.9,
        "upper": 0.9,
    }
    owned_args = {**parked_args, "lower": -0.5, "upper": 0.5}

    await limits.preview(parked_args)  # the card's preview; nobody consumes it
    assert await limits.invoke(owned_args) == {"ok": True, "session_id": SESSION}
    assert [w["lower"] for w in _writes(calls, "set_joint_limits")] == [-0.5]
    # The leftover ticket is gone; the carded args now run on ownership alone, re-planned.
    assert await limits.invoke(parked_args) == {"ok": True, "session_id": SESSION}


async def test_invoke_without_ticket_refuses_when_its_own_hook_says_card(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, root, _ = await graph(db)
    built, _, calls, _ = tools(engine, project.id)  # empty ledger: nothing is owned
    with pytest.raises(ToolException, match="confirmation"):
        await built["isaac.load_model"].invoke(
            {"session_id": SESSION, "model_entity_id": str(root.id)}
        )
    with pytest.raises(ToolException, match="confirmation"):
        await built["isaac.stop"].invoke({"session_id": SESSION})
    assert not calls, "the hook is asked before any native call"


async def test_start_records_the_requesting_user_on_the_ledger_row(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """SOLUSDEV-322 P3-T4 (security review): the ledger row carries the principal."""
    from solus_api.models import SimSession

    project, _, _ = await graph(db)
    maker = _maker(engine)
    calls: list[tuple[str, dict[str, Any]]] = []
    state = {"state": "stopped"}
    native = {"isaac." + name: Native(name, calls, state) for name in NAMES}
    built = {
        t.descriptor.name: t
        for t in build_isaac_tools(
            maker, project.id, native, ledger=SessionsLedger(maker), user_id=project.created_by
        )
    }
    assert (await built["isaac.start"].invoke({}))["ok"] is True
    async with maker() as session:
        row = (await session.scalars(select(SimSession))).one()
    assert row.created_by == project.created_by and row.owner.value == "sol"


async def test_isaac_tools_are_no_longer_owned_routines(engine: AsyncEngine) -> None:
    built, _, _, _ = tools(engine, uuid.uuid4())
    registry = _registry(built)
    for tool in built.values():
        for family in ("isaac", "onshape", "machine", "command", "bridge"):
            register_owned_routine(cast(Tool, tool), family=family)
        assert getattr(tool, "_build_authority", None) is None
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    assert await policy.prepare(ToolCall(tool="isaac.run_routine", args={})) is False


# ------------------------------------------------------ SOLUSDEV-322 P4-T2: the user's own stages


async def test_open_stage_is_owned_by_construction_and_recorded(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, _, _ = await graph(db)
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    built, _, calls, state = tools(engine, project.id, ledger=ledger)
    state.update({"state": "stopped", "session_id": None})
    tool = built["isaac.open_stage"]
    assert await needs_card(tool, {"stage_ref": STAGE}) is False

    # Guide mode too: no card is needed to open a stage Solus itself will own.
    opened = await _parking_dispatch(ActionMode.GUIDE, _registry(built), maker, project)(
        ToolCall(tool="isaac.open_stage", args={"stage_ref": STAGE}, call_id="call-open")
    )
    assert opened.ok and opened.value is not None, opened.error
    assert opened.value["session_id"] == SESSION
    rows = await ledger.running(project_id=project.id, provider=PROVIDER)
    assert [(r.session_id, r.owner, r.started_by_call_id, r.scene_ref) for r in rows] == [
        (SESSION, "sol", "call-open", STAGE)
    ], "scene_ref is the root-relative stage path"
    assert _writes(calls, "open_stage") == [{"stage_ref": STAGE, "dry_run": False}]
    assert await _confirmation_rows(maker) == []

    # Absolute, traversing or option-shaped stage paths never reach the fork.
    for bad in ("/abs/arm.usd", "../arm.usd", "-flag.usd", "a//b.usd", "a/./b.usd"):
        with pytest.raises(ToolException) as error:
            await tool.invoke({"stage_ref": bad})
        assert error.value.code == ToolErrorCode.INVALID_ARGS, bad
    # One write; every other fork call was a dry run (the direct `needs_card` probe, the Guide
    # hook, the gate hook and `_verified` each read the fork's preview for the label).
    opens = [args["dry_run"] for name, args in calls if name == "open_stage"]
    assert opens.count(False) == 1 and all(opens[:-1]), "dry runs, then the one write"
    # One owned Isaac session per project: a second open refuses before the fork is asked.
    with pytest.raises(ToolException, match="still running"):
        await tool.invoke({"stage_ref": STAGE})


async def test_find_articulations_and_read_state_are_reads(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, _, _ = await graph(db)
    maker = _maker(engine)
    built, _, calls, _ = tools(engine, project.id)  # empty ledger: nothing is owned
    reads: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
        "list_stages": ({}, {}),
        "find_articulations": ({"session_id": SESSION}, {"session_id": SESSION}),
        "read_state": (
            {"session_id": SESSION, "articulation": ARTICULATION, "camera_frame": True},
            {
                "session_id": SESSION,
                "articulation": ARTICULATION,
                "sensors": [],
                "camera_frame": True,
            },
        ),
    }
    guide = _parking_dispatch(ActionMode.GUIDE, _registry(built), maker, project)
    for name, (args, forwarded) in reads.items():
        tool = built["isaac." + name]
        assert tool.requires_complete_preview is False
        assert tool.descriptor.requires_confirmation is False
        assert await needs_card(tool, args) is False
        result = await guide(ToolCall(tool="isaac." + name, args=args))
        assert result.ok and result.value is not None and result.value["ok"] is True, name
        assert calls[-1] == (name, forwarded), "parsed arguments pass through, nothing else"
    assert not any(arg.get("dry_run") for _, arg in calls), "a read is never previewed"
    assert await _confirmation_rows(maker) == []
    for bad in ("World/arm", "/World/-x", "/World/a b", "/" + "x/" * 40 + "y"):
        with pytest.raises(ToolException) as error:
            await built["isaac.read_state"].invoke({"session_id": SESSION, "articulation": bad})
        assert error.value.code == ToolErrorCode.INVALID_ARGS, bad


async def _owned_stage(ledger: SessionsLedger, project: Project) -> None:
    await ledger.record_owned_start(
        project_id=project.id,
        provider=PROVIDER,
        session_id=SESSION,
        call_id=None,
        scene_ref=STAGE,
        created_by=None,
    )


def _sweep_args(duration_s: float = 2.0, speed: float = 0.25) -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "routine": "sweep",
        "duration_s": duration_s,
        "sweep": {
            "articulation": ARTICULATION,
            "joint": "elbow",
            "lower": -0.5,
            "upper": 0.5,
            "speed_rad_s": speed,
        },
    }


@pytest.mark.parametrize("mode", [ActionMode.DO, ActionMode.GUIDE])
async def test_spawn_at_on_owned_stage_runs_without_a_card(
    db: AsyncSession, engine: AsyncEngine, mode: ActionMode
) -> None:
    store = MemoryStore()
    project, root = await stage_graph(db, store)
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    await _owned_stage(ledger, project)
    built, _, calls, _ = tools(engine, project.id, ledger=ledger, store=store)
    dispatch = _parking_dispatch(mode, _registry(built), maker, project)
    spawn = {
        "session_id": SESSION,
        "model_entity_id": str(root.id),
        "name": "arm2",
        "pose": {"xyz": [0.1, 0, 0], "rpy": [0, 0, 0]},
    }

    spawned = await dispatch(ToolCall(tool="isaac.spawn_at", args=spawn))
    assert spawned.ok, spawned.error
    write = _writes(calls, "spawn_at")[0]
    assert write["model_sha256"] == MODEL_SHA and "model_entity_id" not in write
    assert "graph_digest" not in write, "a stage action binds the scene generation, not a model"
    assert write["expected_scene_generation"] == 0 and write["name"] == "arm2"
    assert write["pose"] == {"xyz": [0.1, 0.0, 0.0], "rpy": [0.0, 0.0, 0.0]}
    assert [name for name, _ in calls if name == "put_asset"] == [], "the asset was present"

    stepped = await dispatch(
        ToolCall(tool="isaac.control", args={"session_id": SESSION, "action": "step", "steps": 5})
    )
    assert stepped.ok, stepped.error
    assert _writes(calls, "control") == [
        {
            "session_id": SESSION,
            "dry_run": False,
            "expected_scene_generation": 0,
            "action": "step",
            "steps": 5,
        }
    ]
    swept = await dispatch(ToolCall(tool="isaac.run_routine", args=_sweep_args()))
    assert swept.ok, swept.error
    assert await _confirmation_rows(maker) == []


async def test_spawn_at_pushes_missing_assets_in_chunks_then_spawns(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    store = MemoryStore()
    project, root = await stage_graph(db, store)
    ledger = SessionsLedger(_maker(engine))
    await _owned_stage(ledger, project)
    built, _, calls, _ = tools(engine, project.id, ledger=ledger, store=store, asset_present=False)
    spawn = built["isaac.spawn_at"]
    args = {"session_id": SESSION, "model_entity_id": str(root.id), "name": "arm2"}

    rows = await spawn.preview(args)
    push_row = next(row for row in rows if row["label"] == "Model push")
    assert "3 chunk" in push_row["after"]
    assert not any(name == "put_asset" for name, _ in calls), "a preview pushes nothing"

    assert (await spawn.invoke(args))["ok"] is True
    chunks = [arg for name, arg in calls if name == "put_asset"]
    assert [c["index"] for c in chunks] == [0, 1, 2]
    assert all(c["total"] == 3 and c["sha256"] == MODEL_SHA for c in chunks)
    assert chunks[0]["manifest"] == MANIFEST and all("manifest" not in c for c in chunks[1:])
    received: dict[str, bytes] = {}
    for chunk in chunks:
        assert len(chunk["data_b64"]) <= MAX_DATA_B64 <= 96 * 1024
        raw = base64.b64decode(chunk["data_b64"], validate=True)
        assert 0 < len(raw) <= CHUNK_BYTES <= 64 * 1024
        received[chunk["path"]] = received.get(chunk["path"], b"") + raw
    assert received == FILES
    order = [(name, arg.get("dry_run", False)) for name, arg in calls]
    last_push = max(i for i, step in enumerate(order) if step == ("put_asset", False))
    assert order[last_push + 1 :] == [("status", False), ("spawn_at", True), ("spawn_at", False)]

    # Without a `put_asset` capability nothing crosses and nothing spawns.
    built, _, calls, _ = tools(
        engine, project.id, ledger=ledger, store=store, asset_present=False, put_asset=False
    )
    with pytest.raises(ToolException, match="put_asset"):
        await built["isaac.spawn_at"].invoke(args)
    assert _writes(calls, "spawn_at") == []


async def test_save_stage_cards_on_owned_stage(db: AsyncSession, engine: AsyncEngine) -> None:
    project, _, _ = await graph(db)
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    await _owned_stage(ledger, project)
    built, _, calls, _ = tools(engine, project.id, ledger=ledger)
    save = built["isaac.save_stage"]
    args = {"session_id": SESSION, "dest": "nested/arm-copy.usda"}
    assert await needs_card(save, args) is True
    with pytest.raises(ToolException, match="confirmation"):
        await save.invoke(args)  # no ticket: ownership never lets a file write through
    dispatch = _parking_dispatch(ActionMode.DO, _registry(built), maker, project)
    parked = await dispatch(ToolCall(tool="isaac.save_stage", args=args))
    assert not parked.ok and parked.error is not None
    assert parked.error.code is ToolErrorCode.UNAUTHORIZED
    assert [(r.tool, r.args) for r in await _confirmation_rows(maker)] == [
        ("isaac.save_stage", args)
    ]
    assert _writes(calls, "save_stage") == []
    # The decide path: preview (the card's ticket) then invoke.
    await save.preview(args)
    assert (await save.invoke(args))["ok"] is True
    assert _writes(calls, "save_stage") == [
        {
            "session_id": SESSION,
            "dry_run": False,
            "expected_scene_generation": 0,
            "dest": "nested/arm-copy.usda",
        }
    ]
    for bad in ("pack.usdz", "notes.txt", "/abs/x.usda", "../x.usda"):
        with pytest.raises(ToolException) as error:
            await save.invoke({"session_id": SESSION, "dest": bad})
        assert error.value.code == ToolErrorCode.INVALID_ARGS, bad


async def test_sweep_routine_bounds(db: AsyncSession, engine: AsyncEngine) -> None:
    routine = PUBLIC_MODELS["run_routine"]
    assert routine.model_validate(_sweep_args(60.0)).model_dump()["routine"] == "sweep"
    joint = str(uuid.uuid4())
    trajectory = {
        "session_id": SESSION,
        "routine": "joint_trajectory",
        "duration_s": 60.0,
        "joints": [{"joint_entity_id": joint, "lower": -0.1, "upper": 0.1}],
        "waypoints": [{"positions": [{"joint_entity_id": joint, "position_rad": 0.0}]}],
    }
    routine.model_validate(trajectory)
    invalid: list[dict[str, Any]] = [
        _sweep_args(61.0),  # the routine bound
        _sweep_args(0.5),
        _sweep_args(speed=0.26),  # the target speed cap
        _sweep_args(speed=0.0),
        {**_sweep_args(), "sweep": {**_sweep_args()["sweep"], "lower": 0.5}},  # unordered
        {**_sweep_args(), "joints": trajectory["joints"]},  # a sweep carries only its spec
        {**_sweep_args(), "sweep": {**_sweep_args()["sweep"], "joint": "-x"}},
        {**trajectory, "sweep": _sweep_args()["sweep"]},
        {**trajectory, "waypoints": []},
        {**trajectory, "duration_s": 61.0},
    ]
    for args in invalid:
        with pytest.raises(ValidationError):
            routine.model_validate(args)
    # Sensors: IMU and camera need no radius; a contact sensor still does.
    base = {
        "entity_id": joint,
        "parent_link_entity_id": str(uuid.uuid4()),
        "translation_m": [0.0, 0.0, 0.0],
        "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
    }
    assert Sensor.model_validate({**base, "kind": "imu"}).radius_m is None
    Sensor.model_validate({**base, "kind": "camera"})
    with pytest.raises(ValidationError):
        Sensor.model_validate({**base, "kind": "contact"})

    # Through the wrapper: a sweep in the owned stage binds the scene generation, no graph.
    project, _, _ = await graph(db)
    ledger = SessionsLedger(_maker(engine))
    await _owned_stage(ledger, project)
    built, _, calls, _ = tools(engine, project.id, ledger=ledger)
    assert (await built["isaac.run_routine"].invoke(_sweep_args()))["ok"] is True
    write = _writes(calls, "run_routine")[0]
    assert "graph_digest" not in write and write["expected_scene_generation"] == 0
    assert write["routine_spec"] == {
        "routine": "sweep",
        "duration_s": 2.0,
        "joints": [],
        "waypoints": [],
        "sweep": {
            "articulation": ARTICULATION,
            "joint": "elbow",
            "lower": -0.5,
            "upper": 0.5,
            "speed_rad_s": 0.25,
        },
    }
    with pytest.raises(ToolException) as error:
        await built["isaac.run_routine"].invoke(_sweep_args(61.0))
    assert error.value.code == ToolErrorCode.INVALID_ARGS


async def test_run_routine_hands_the_hook_the_verified_model(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """P5-T4 review: the routine hook is told WHICH model ran from the wrapper's own digest-
    checked graph binding (`plan.observation.graph`), never from a `model_entity_id` the
    companion echoes; a stage-bound sweep binds no model. The hook's answer is the result."""
    project, root, entities = await graph(db)
    seen: list[uuid.UUID | str | None] = []

    async def hook(
        args: dict[str, Any],
        result: dict[str, Any],
        *,
        model_entity_id: uuid.UUID | str | None = None,
    ) -> dict[str, Any]:
        seen.append(model_entity_id)
        return {**result, "run": "filed"}

    _, native, calls, state = tools(engine, project.id)
    for tool in native.values():
        tool.state = state
    maker = _maker(engine)
    ledger = SessionsLedger(maker)
    await _owned_stage(ledger, project)
    built: dict[str, Any] = {
        tool.descriptor.name: tool
        for tool in build_isaac_tools(maker, project.id, native, ledger=ledger, record_sim_run=hook)
    }
    resolved = await built["isaac.run_routine"].resolver.resolve(str(root.id))
    state.update(loaded=True, model_entity_id=str(root.id), graph_digest=resolved.digest)
    decoy = str(uuid.uuid4())
    routine = native["isaac.run_routine"]
    original = routine.invoke

    async def forged(args: dict[str, Any]) -> dict[str, Any]:
        result = await original(args)
        return {**result, "model_entity_id": decoy} if not args.get("dry_run") else result

    routine.invoke = forged  # type: ignore[method-assign]
    ids = [str(entity.id) for entity in entities[3:5]]
    trajectory = {
        "session_id": SESSION,
        "routine": "joint_trajectory",
        "duration_s": 6,
        "joints": [{"joint_entity_id": identity, "lower": -0.1, "upper": 0.1} for identity in ids],
        "waypoints": [
            {"positions": [{"joint_entity_id": identity, "position_rad": 0.05} for identity in ids]}
        ],
    }

    answered = await built["isaac.run_routine"].invoke(trajectory)
    swept = await built["isaac.run_routine"].invoke(_sweep_args())

    assert answered["run"] == "filed" and swept["run"] == "filed"
    assert seen == [str(root.id), None], "the id crosses as text; the hook parses it"
    assert len(_writes(calls, "run_routine")) == 2


async def test_every_isaac_result_strips_companion_ownership_claims(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """Reads and writes alike: `owned` / `owner` / `owned_by` from a fork never reach SOL;
    ownership is the ledger's answer, never the companion's."""
    project, _, _ = await graph(db)
    ledger = SessionsLedger(_maker(engine))
    await _owned_stage(ledger, project)
    built, native, _, _ = tools(engine, project.id, ledger=ledger)
    claims = {"owned": True, "owner": "sol", "owned_by": "sol"}
    for raw in native.values():
        real = raw.invoke

        async def claiming(args: dict[str, Any], real: Any = real) -> dict[str, Any]:
            return {**await real(args), **claims}

        raw.invoke = claiming  # type: ignore[method-assign]

    results = [
        await built["isaac.probe"].invoke({}),
        await built["isaac.status"].invoke({}),
        await built["isaac.list_stages"].invoke({}),
        await built["isaac.find_articulations"].invoke({"session_id": SESSION}),
        await built["isaac.read_state"].invoke({"session_id": SESSION}),
        await built["isaac.control"].invoke({"session_id": SESSION, "action": "pause"}),
        await built["isaac.stop"].invoke({"session_id": SESSION}),
    ]
    for result in results:
        assert not set(claims) & set(result), result
    assert await ledger.running(project_id=project.id, provider=PROVIDER) == []


#: One line, ends in a period, no absolute path: what SOL repeats to the person as it is.
SENTENCE = re.compile(r"[^\n]*\S\.")
ABSOLUTE_PATH = re.compile(r"(?<![\w.])/\w")


def assert_reason_sentence(reason: Any) -> None:
    assert isinstance(reason, str) and SENTENCE.fullmatch(reason), reason
    assert not ABSOLUTE_PATH.search(reason), reason


@pytest.mark.parametrize(
    ("code", "refusal"),
    [
        (
            "model_not_verified",
            {"ok": False, "code": "model_not_verified", "reason": "push it first"},
        ),
        (
            "isaac_operation_refused",
            {"ok": False, "code": "isaac_operation_refused", "reason": "isaac_operation_refused"},
        ),
        ("action_refused", {"ok": False, "reason": "action_refused", "scene_generation": 3}),
        ("mutation_unverified", {"ok": False, "reason": "mutation_unverified", "uncertain": True}),
        ("stage_refused", {"ok": False, "reason": "stage_refused"}),
        (
            "store_unsafe",
            {"ok": False, "code": "store_unsafe", "reason": "store /home/me/.solus is a symlink"},
        ),
        ("no_reason", {"ok": False, "code": "asset_mismatch"}),
        (
            "store_unsafe_dry_run",
            {"ok": False, "code": "store_unsafe", "reason": "store /home/me/.solus is a symlink"},
        ),
        ("bridge_offline", None),
        ("invalid_args", "invalid_args"),
        ("needs_confirmation", "needs_confirmation"),
        ("no_verified_model", "no_verified_model"),
    ],
)
async def test_every_failure_result_has_a_reason_sentence(
    db: AsyncSession,
    engine: AsyncEngine,
    code: str,
    refusal: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P7-T2: every refusal SOL can meet carries one sentence it can repeat — a companion
    refusal (`{ok: false, code?, reason?}`, bare code or not, path or not), the bridge offline,
    bad arguments, an unapproved action, a spawn with no verified model and no way to push one."""
    store = MemoryStore()
    project, root, _ = await graph(db)
    ledger = SessionsLedger(_maker(engine))
    await _owned_stage(ledger, project)
    built, native, _, _ = tools(
        engine,
        project.id,
        ledger=ledger,
        store=store,
        asset_present=False,
        put_asset=code != "no_verified_model",
    )
    spawn = {
        "session_id": SESSION,
        "model_entity_id": str(root.id),
        "name": "arm1",
        "pose": {"xyz": [0.0, 0.0, 0.0], "rpy": [0.0, 0.0, 0.0]},
    }

    async def offline(_args: dict[str, Any]) -> dict[str, Any]:
        raise ToolException("bridge offline", code=ToolErrorCode.UNAVAILABLE, retryable=True)

    async def refusing(_args: dict[str, Any]) -> dict[str, Any]:
        return dict(refusal)

    if isinstance(refusal, dict) and code.endswith("_dry_run"):
        # A carded write whose dry run the fork refuses: the fork's reason reaches SOL, path-free.
        native["isaac.save_stage"].plan = refusal
        with pytest.raises(ToolException) as error:
            await built["isaac.save_stage"].preview({"session_id": SESSION, "dest": "arm.usda"})
        assert error.value.message == "Store <path> is a symlink."
        assert_reason_sentence(error.value.message)
        return
    if isinstance(refusal, dict):
        monkeypatch.setattr(native["isaac.probe"], "invoke", refusing)
        result = await built["isaac.probe"].invoke({})
        assert result["ok"] is False and result.get("code") == refusal.get("code")
        assert_reason_sentence(result["reason"])
        return
    if refusal is None:
        monkeypatch.setattr(native["isaac.probe"], "invoke", offline)
    with pytest.raises(ToolException) as error:
        if refusal is None:
            await built["isaac.probe"].invoke({})
        elif refusal == "invalid_args":
            await built["isaac.control"].invoke({"session_id": SESSION, "action": "--bad"})
        elif refusal == "needs_confirmation":
            foreign = {"session_id": str(uuid.uuid4()), "action": "pause"}
            await built["isaac.control"].invoke(foreign)
        else:
            await built["isaac.spawn_at"].invoke(spawn)
    assert_reason_sentence(error.value.message)
    if refusal is None:
        assert error.value.code is ToolErrorCode.UNAVAILABLE and error.value.retryable
        assert "bridge offline" in error.value.message


async def test_refused_dry_run_raises_preview_refusal_with_the_fork_sentence(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """P9-T1 (scenario 6a twin): a refused Isaac dry run is a `PreviewRefusal` whose path-free
    `safe_message` `confirmations._build_preview` carries into the park's tool result."""
    store = MemoryStore()
    project, _, _ = await graph(db)
    ledger = SessionsLedger(_maker(engine))
    await _owned_stage(ledger, project)
    built, native, _, _ = tools(engine, project.id, ledger=ledger, store=store)
    native["isaac.save_stage"].plan = {
        "ok": False,
        "code": "store_unsafe",
        "reason": "store /home/me/.solus is a symlink",
    }
    with pytest.raises(PreviewRefusal) as error:
        await built["isaac.save_stage"].preview({"session_id": SESSION, "dest": "arm.usda"})
    assert error.value.safe_message == "Store <path> is a symlink."
    assert not error.value.retryable
