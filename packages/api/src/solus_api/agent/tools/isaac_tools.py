"""Project-scoped graph resolution and one-shot consent for the owned Isaac bridge."""

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.isaac_models import (
    PUBLIC_MODELS,
    JointLimits,
    Load,
    Routine,
    SensorPose,
    SimulationModel,
    Strict,
)
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import Tool, ToolException
from solus_api.bridge.tool import _diff_rows
from solus_api.graph.read_scope import current_scope
from solus_api.models import Domain, GraphEntity

_DIGEST = re.compile(r"[0-9a-f]{64}")
_TIMEOUTS = {
    "probe": 20,
    "status": 20,
    "start": 195,
    "stop": 25,
    "load_model": 165,
    "set_joint_limits": 25,
    "set_sensor_pose": 25,
    "run_routine": 55,
}
_DESCRIPTIONS = {
    "probe": "Observe installed Isaac runtime readiness without starting it.",
    "status": "Read this project’s owned Isaac session and scene state.",
    "start": "Start one owned headless Isaac session; no scene is loaded implicitly.",
    "stop": "Stop the exact owned Isaac session.",
    "load_model": "Load the explicit graph-bound model asset into the owned scene.",
    "set_joint_limits": "Set the simulated limits of one graph-bound joint in radians.",
    "set_sensor_pose": (
        "Set one graph-bound contact sensor pose in parent-link metres and wxyz quaternion."
    ),
    "run_routine": (
        "Run a bounded joint trajectory with the selected model’s explicit ranges and waypoints."
    ),
}


def _refuse(message: str = "Isaac approval is stale or unavailable.") -> ToolException:
    return ToolException(message, code=ToolErrorCode.TOOL_ERROR, retryable=False)


def _canonical(value: Any) -> str:
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise _refuse("Isaac returned invalid structured data.") from None
    if len(result.encode()) > 128 * 1024:
        raise _refuse("Isaac observation exceeds the bounded result size.")
    return result


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _display_digest(value: str) -> str:
    return ":".join(value[i : i + 16] for i in range(0, 64, 16))


def _wire_digest(value: Any) -> str:
    if isinstance(value, str):
        if _DIGEST.fullmatch(value):
            return value
        if re.fullmatch(r"(?:[0-9a-f]{16}:){3}[0-9a-f]{16}", value):
            return value.replace(":", "")
    raise _refuse("Isaac returned an invalid digest.")


def _parse(name: str, args: dict[str, Any]) -> Strict:
    try:
        return PUBLIC_MODELS[name].model_validate(args)
    except ValidationError:
        raise ToolException("Invalid Isaac arguments.", code=ToolErrorCode.INVALID_ARGS) from None


@dataclass(frozen=True)
class _Graph:
    model_id: str
    model_version: int
    model: SimulationModel
    digest: str


def _routine(parsed: Routine, graph: _Graph) -> dict[str, Any]:
    joints = {j.entity_id: j for j in graph.model.joints}
    ranges = {j.joint_entity_id: (j.lower, j.upper) for j in parsed.joints}
    if set(ranges) != set(joints):
        raise _refuse("The routine must use exactly the loaded model joints.")
    for identity, (low, high) in ranges.items():
        hard_low, hard_high = joints[identity].lower_rad, joints[identity].upper_rad
        if not hard_low <= low < high <= hard_high:
            raise _refuse("Routine range exceeds selected model limits.")
    if any(
        not ranges[p.joint_entity_id][0] <= p.position_rad <= ranges[p.joint_entity_id][1]
        for w in parsed.waypoints
        for p in w.positions
    ):
        raise _refuse("Routine target is outside its requested range.")
    return parsed.model_dump(exclude={"session_id", "dry_run"})


def _target(parsed: Strict, graph: _Graph) -> dict[str, Any]:
    native: dict[str, Any] = {}
    if isinstance(parsed, Load):
        native.update(
            {"model_entity_id": graph.model_id, "resolved_model": graph.model.model_dump()}
        )
    elif isinstance(parsed, JointLimits):
        joint = next((j for j in graph.model.joints if j.entity_id == parsed.joint_entity_id), None)
        if joint is None:
            raise _refuse("The selected joint is not bound to the loaded model.")
        low, high = joint.lower_rad, joint.upper_rad
        if not low <= parsed.lower < parsed.upper <= high:
            raise _refuse("Joint limits exceed the selected model limits.")
        native.update(
            {"entity_id": parsed.joint_entity_id, "lower": parsed.lower, "upper": parsed.upper}
        )
    elif isinstance(parsed, SensorPose):
        if parsed.sensor_entity_id not in {s.entity_id for s in graph.model.sensors}:
            raise _refuse("The selected sensor is not bound to the loaded model.")
        native.update(
            {
                "entity_id": parsed.sensor_entity_id,
                "translation_m": parsed.translation_m,
                "orientation_wxyz": parsed.orientation_wxyz,
            }
        )
    elif isinstance(parsed, Routine):
        native["routine_spec"] = _routine(parsed, graph)
    return native


class _Resolver:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID) -> None:
        self.sessions = sessions
        self.project_id = project_id
        self.scope = current_scope(project_id)

    async def resolve(self, identity: Any) -> _Graph:
        try:
            if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity:
                raise ValueError
            model_id = uuid.UUID(identity)
        except ValueError:
            raise ToolException(
                "The bound simulation model is unavailable.", code=ToolErrorCode.NOT_FOUND
            ) from None
        predicate = (
            GraphEntity.project_id == self.project_id,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.domain != Domain.WORKSPACE,
            self.scope.entity_predicate(),
        )
        async with self.sessions() as session:
            root = await session.scalar(
                select(GraphEntity).where(GraphEntity.id == model_id, *predicate)
            )
            if root is None:
                raise ToolException(
                    "The bound simulation model is unavailable.", code=ToolErrorCode.NOT_FOUND
                )
            definition = (
                root.attrs.get("simulation_model") if isinstance(root.attrs, dict) else None
            )
            if isinstance(definition, dict) and definition.get("schema_version") == 1:
                raise _refuse(
                    "Legacy simulation model: explicitly reimport a version 2 model with asset "
                    "manifest, joint topology and limits; existing graph data was not changed."
                )
            try:
                model = SimulationModel.model_validate(definition)
            except (ValidationError, AttributeError):
                raise _refuse("The graph simulation model is invalid or unsupported.") from None
            if identity in model.entity_ids():
                raise _refuse("The simulation model cannot bind itself as a component.")
            ids = [uuid.UUID(value) for value in model.entity_ids()]
            entities = list(
                (
                    await session.scalars(
                        select(GraphEntity).where(GraphEntity.id.in_(ids), *predicate)
                    )
                ).all()
            )
            if {entity.id for entity in entities} != set(ids):
                raise ToolException(
                    "A simulation binding is unavailable in this project.",
                    code=ToolErrorCode.NOT_FOUND,
                )
            # Content hashes close stale-state gaps even if a writer fails to bump
            # an optimistic version. Raw attrs never leave this process.
            versions = [
                {
                    "id": str(entity.id),
                    "version": entity.version,
                    "content": _digest(
                        {
                            "attrs": entity.attrs,
                            "name": entity.name,
                            "kind": entity.kind,
                            "domain": entity.domain.value,
                            "source_id": str(entity.source_id) if entity.source_id else None,
                        }
                    ),
                }
                for entity in [root, *entities]
            ]
            digest = _digest(
                {
                    "project_id": str(self.project_id),
                    "entities": sorted(versions, key=lambda row: row["id"]),
                    "model": model.model_dump(),
                }
            )
            return _Graph(identity, root.version, model, digest)


@dataclass(frozen=True)
class _Observation:
    native_args: dict[str, Any]
    state: dict[str, Any]
    graph: _Graph | None


@dataclass
class _Ticket:
    args: str
    snapshot: str
    consumed: bool = False


class IsaacTool:
    """The sole public wrapper; its raw bridge capability never enters the registry."""

    def __init__(self, name: str, raw: Mapping[str, Tool], resolver: _Resolver) -> None:
        self.name = name
        self.raw = raw
        self.resolver = resolver
        self.requires_complete_preview = name not in ("probe", "status")
        self._ticket: ContextVar[_Ticket | None] = ContextVar("isaac_approval", default=None)
        self._descriptor = ToolDescriptor(
            name="isaac." + name,
            description=_DESCRIPTIONS[name],
            params=PUBLIC_MODELS[name].model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=self.requires_complete_preview,
            consent_summary=_DESCRIPTIONS[name] if self.requires_complete_preview else None,
            timeout_seconds=_TIMEOUTS[name],
            files_errors=self.requires_complete_preview,
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def _clear(self) -> None:
        previous = self._ticket.get()
        if previous is not None:
            previous.consumed = True
        self._ticket.set(None)

    async def _status(self) -> dict[str, Any]:
        status = await self.raw["isaac.status"].invoke({})
        if not isinstance(status, dict) or status.get("state") not in ("running", "stopped"):
            raise _refuse("The owned Isaac session state is unavailable.")
        _canonical(status)
        status = dict(status)
        if status.get("graph_digest") is not None:
            status["graph_digest"] = _wire_digest(status["graph_digest"])
        if status["state"] == "running":
            try:
                value = status["session_id"]
                if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                    raise ValueError
                generation = status["scene_generation"]
                if type(generation) is not int or not 0 <= generation <= 1000:
                    raise ValueError
                if type(status["loaded"]) is not bool:
                    raise ValueError
            except (KeyError, ValueError):
                raise _refuse("The owned Isaac scene state is incomplete.") from None
        return status

    async def _observe(self, parsed: Strict) -> _Observation:
        state = await self._status()
        args = parsed.model_dump()
        if self.name == "start":
            return _Observation(args, state, None)
        if state["state"] != "running" or args["session_id"] != state.get("session_id"):
            raise _refuse("The selected Isaac session is no longer current.")
        if self.name == "stop":
            return _Observation(args, state, None)
        model_id = (
            parsed.model_entity_id if isinstance(parsed, Load) else state.get("model_entity_id")
        )
        graph = await self.resolver.resolve(model_id)
        if not isinstance(parsed, Load) and (
            state.get("loaded") is not True or state.get("graph_digest") != graph.digest
        ):
            raise _refuse("The loaded model no longer matches its graph snapshot.")
        native = {
            "session_id": args["session_id"],
            "dry_run": args["dry_run"],
            "graph_digest": graph.digest,
            "expected_scene_generation": state["scene_generation"],
        }
        native.update(_target(parsed, graph))
        return _Observation(native, state, graph)

    async def _plan(self, parsed: Strict) -> tuple[_Observation, list[dict[str, Any]], str]:
        observation = await self._observe(parsed)
        plan = await self.raw[self.descriptor.name].invoke(
            {**observation.native_args, "dry_run": True}
        )
        if (
            not isinstance(plan, dict)
            or plan.get("ok") is not True
            or plan.get("dry_run") is not True
        ):
            raise _refuse("Isaac did not produce a complete dry-run preview.")
        rows = _diff_rows(plan.get("preview"))
        fingerprint = _wire_digest(plan.get("fingerprint"))
        if not rows:
            raise _refuse("Isaac did not produce a complete dry-run preview.")
        binding = f"Native action fingerprint: {_display_digest(fingerprint)}"
        if observation.graph:
            graph = observation.graph
            binding += (
                f"; Graph model: {graph.model_id} / version {graph.model_version}"
                f"; Graph snapshot fingerprint: {_display_digest(graph.digest)}"
            )
        rows.append(
            {
                "label": "Graph and native action binding"
                if observation.graph
                else "Native action fingerprint",
                "before": None,
                "after": binding,
            }
        )
        if not _diff_rows(rows):
            raise _refuse("The complete Isaac preview is too large.")
        snapshot = _digest(
            {"native_args": observation.native_args, "state": observation.state, "rows": rows}
        )
        return observation, rows, snapshot

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        self._clear()
        parsed = _parse(self.name, args)
        _, rows, snapshot = await self._plan(parsed)
        self._ticket.set(_Ticket(_canonical(args), snapshot))
        return rows

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        parsed = _parse(self.name, args)
        if self.name == "probe":
            return await self.raw[self.descriptor.name].invoke({})
        if self.name == "status":
            state = await self._status()
            if state.get("loaded") is True:
                await self.resolver.resolve(state.get("model_entity_id"))
            return state
        ticket = self._ticket.get()
        was_consumed = ticket is None or ticket.consumed
        self._clear()
        if ticket is None or was_consumed or ticket.args != _canonical(args):
            raise _refuse()
        # Marked consumed above so any exception, cancellation or child-task
        # dispatch cannot replay this authorization. Save its prior state first.
        observation, _, snapshot = await self._plan(parsed)
        if snapshot != ticket.snapshot:
            raise _refuse()
        if observation.graph is not None:
            fresh = await self.resolver.resolve(observation.graph.model_id)
            if fresh.digest != observation.graph.digest:
                raise _refuse("The graph changed while Isaac was preparing the action.")
        return await self.raw[self.descriptor.name].invoke(observation.native_args)


def build_isaac_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    raw_tools: Mapping[str, Tool],
) -> list[Tool]:
    """Build only known cloud-owned wrappers; never forward an advertised schema."""
    raw = {
        name: tool
        for name, tool in raw_tools.items()
        if name.startswith("isaac.") and name[6:] in PUBLIC_MODELS
    }
    resolver = _Resolver(session_factory, project_id)
    return [
        IsaacTool(name, raw, resolver)
        for name in PUBLIC_MODELS
        if "isaac." + name in raw and (name == "probe" or "isaac.status" in raw)
    ]
