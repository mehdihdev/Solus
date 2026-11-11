"""Project-scoped graph resolution and per-call consent for the owned Isaac bridge.

SOLUSDEV-322 P2-T3: the gate is the ownership ledger, not a static flag. An action inside a
session Solus itself started (`start`/`open_stage` recorded `owner="sol"`) needs no card; the
same action inside any other session — attached, unknown, forged, or one the ledger cannot
answer for — does. `invoke` keeps the complete preview (`_plan`) immediately before every native
call whether a card's ticket approved it or ownership let it through, and refuses on its own
when its hook says card, so the tool is never reachable uncarded even if a dispatcher forgets
the hook.

SOLUSDEV-322 P4-T2: the user's own stages. `open_stage` is owned by construction and records
the root-relative `stage_ref` as the ledger's `scene_ref`; `spawn_at` binds a graph model and
pushes its files through the shared `sim_assets.ModelPush` when the fork reports them absent;
`control` and a `sweep` routine are scene-generation-bound stage actions; `save_stage` (a write
into the user's own file) always cards. Companion results are data: ownership claims a fork
returns are stripped from every result.
"""

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.dynamic_gate import approval_required, current_call_id
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.isaac_models import (
    PUBLIC_MODELS,
    READ_ONLY,
    EntityId,
    JointLimits,
    Load,
    Number,
    Routine,
    SensorPose,
    SimulationModel,
    SpawnAt,
    Strict,
    Sweep,
)
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.sim_assets import (
    ModelPush,
    consent_row,
    model_not_verified,
    reaching,
    refusal_sentence,
    without_claims,
)
from solus_api.agent.tools.tool import Tool, ToolException
from solus_api.bridge.tool import _diff_rows
from solus_api.graph.read_scope import current_scope
from solus_api.livebench.sim_runs import JointSample, RoutineReadback, SimRunHook
from solus_api.models import Domain, GraphEntity
from solus_api.simulation.sessions_ledger import (
    OwnedSessionRunningError,
    SessionsLedger,
    SimSessionRecord,
)
from solus_api.storage.artifact_store import ArtifactStore

logger = logging.getLogger("solus.agent.isaac_tools")

PROVIDER = "isaac"
PUT_ASSET: Final = "isaac.put_asset"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_READ_ONLY = READ_ONLY
#: Owned by construction: the call CREATES the Solus-owned session the ledger then records.
_OWNED_BY_CONSTRUCTION = frozenset({"start", "open_stage"})
#: Writes to the user's own files always card.
_STATIC_GATED = frozenset({"save_stage"})
#: Actions inside the user's own stage: bound to the scene generation, not to a loaded graph
#: model (`spawn_at` binds one for its files only; a `sweep` routine joins them at parse time).
_STAGE_ACTIONS = frozenset({"spawn_at", "control", "save_stage"})
#: Cloud bounds exceed the fork's allowlist bounds so the cloud never reports TIMEOUT while the
#: companion keeps running; `spawn_at` covers the chunk push (~32 round trips for a 2 MiB model).
_TIMEOUTS = {
    "probe": 20,
    "status": 20,
    "start": 195,
    "stop": 25,
    "load_model": 165,
    "set_joint_limits": 25,
    "set_sensor_pose": 25,
    "run_routine": 85,
    "list_stages": 25,
    "open_stage": 130,
    "find_articulations": 35,
    "spawn_at": 300,
    "read_state": 35,
    "control": 65,
    "save_stage": 65,
}
_DESCRIPTIONS = {
    "probe": "Observe installed Isaac runtime readiness when sim.available asks or before a start.",
    "status": (
        "Read this project’s owned Isaac session and scene state when you need to know what is "
        "loaded."
    ),
    "start": (
        "Start one owned headless Isaac session when no stage or scene of the user's is wanted."
    ),
    "stop": "Stop the exact owned Isaac session when its work is done.",
    "load_model": (
        "Load the explicit graph-bound model asset into the owned scene when it holds no model yet."
    ),
    "set_joint_limits": (
        "Set the simulated limits of one graph-bound joint in radians when a limit must be tried."
    ),
    "set_sensor_pose": (
        "Set one graph-bound contact sensor pose in parent-link metres and wxyz quaternion when a "
        "sensor placement is in question."
    ),
    "run_routine": (
        "Run a bounded joint trajectory on the loaded graph model, or a bounded sweep of one "
        "joint of an articulation in the open stage, when a motion needs physical readback."
    ),
    "list_stages": (
        "List the user's USD stage files under the sim roots when choosing which stage to open; "
        "launches nothing."
    ),
    "open_stage": (
        "Start one owned headless Isaac session on one of the user's own stage files when the "
        "question is about that stage."
    ),
    "find_articulations": (
        "Read every articulation root in the owned session's stage when the robot inside it must "
        "be located."
    ),
    "spawn_at": (
        "Insert a graph-bound Solus simulation model at a pose into the open stage when the stage "
        "lacks the robot."
    ),
    "read_state": (
        "Read joint, IMU, contact and camera state of the owned session when a value is asked for."
    ),
    "control": (
        "Pause, play, step or reset physics inside the owned Isaac session when time itself must "
        "move."
    ),
    "save_stage": (
        "Write the open stage back into one of the user's own stage files when the person asks to "
        "keep the changes."
    ),
}

#: The routine hook: SOL's args, the fork's result and the model this wrapper verified in, the
#: result to answer with out (None keeps the fork's result as it is).
RecordSimRun = SimRunHook
#: The fork steps physics at 60 Hz (`scene.run`, `scene.run_sweep`: one target per step).
_PHYSICS_HZ: Final = 60.0


async def no_sim_run(
    args: dict[str, Any], result: dict[str, Any], *, model_entity_id: uuid.UUID | str | None = None
) -> None:
    """The hook of a scope without a graph hub or artifact store: a routine records no Run."""


class _Lenient(BaseModel):
    """A field set read out of the fork's result; the rest of the companion's data is ignored,
    never believed."""

    model_config = ConfigDict(extra="ignore")


class _Waypoint(_Lenient):
    step: Annotated[int, Field(ge=0, le=10**6)]
    positions_rad: dict[EntityId, Number] = Field(default_factory=dict, max_length=16)


class _Trajectory(_Lenient):
    steps: Annotated[int, Field(ge=0, le=10**6)] = 0
    waypoints: list[_Waypoint] = Field(default_factory=list, max_length=64)
    target_errors_rad: dict[EntityId, Number] = Field(default_factory=dict, max_length=16)
    positions_rad: dict[EntityId, Number] = Field(default_factory=dict, max_length=16)


class _SweepSample(_Lenient):
    step: Annotated[int, Field(ge=0, le=10**6)]
    position_rad: Number


class _SweepReadback(_Lenient):
    steps: Annotated[int, Field(ge=0, le=10**6)] = 0
    final_position_rad: Number
    samples: list[_SweepSample] = Field(default_factory=list, max_length=4096)


class _RoutineResult(_Lenient):
    readback: dict[str, Any]


def isaac_routine_readback(
    args: dict[str, Any], result: dict[str, Any], *, session: SimSessionRecord | None = None
) -> RoutineReadback:
    """`sim_run_hook`'s reader (`session`, the ledger row, is unused: nothing here is keyed by a
    scene name). A joint trajectory's readback is keyed by graph joint entity id
    (`device_id` and signal prefix alike; the id is what `sim.map_to_parts` aliases), its final
    target recovered as position minus error; only the joints the REQUEST drives are kept — a
    joint the companion adds is dropped from the waypoints, the final positions and the target
    errors alike, so it never chooses the robot a run lands on. A sweep is one joint of the
    user's articulation, named `<articulation>/<joint>`; the fork reports no target for it.
    Which model ran is the wrapper's verified binding, never a field of the result. Raises
    `ValidationError` on a request or result it cannot read."""
    request = Routine.model_validate(args)
    read = _RoutineResult.model_validate(result)
    if request.sweep is not None:
        return RoutineReadback(_sweep_samples(request.sweep, read.readback))
    return RoutineReadback(_trajectory_samples(read.readback, _requested_joints(request)))


def _requested_joints(request: Routine) -> frozenset[str]:
    """The joints SOL asked the trajectory to drive: `joints[]` and every waypoint position."""
    return frozenset(j.joint_entity_id for j in request.joints) | frozenset(
        p.joint_entity_id for w in request.waypoints for p in w.positions
    )


def _trajectory_samples(readback: dict[str, Any], joints: frozenset[str]) -> list[JointSample]:
    read = _Trajectory.model_validate(readback)
    samples = [
        JointSample(joint, joint, waypoint.step / _PHYSICS_HZ, position)
        for waypoint in read.waypoints
        for joint, position in waypoint.positions_rad.items()
        if joint in joints
    ]
    final_t = max([read.steps, *(w.step for w in read.waypoints)]) / _PHYSICS_HZ
    for joint, position in read.positions_rad.items():
        if joint not in joints:
            continue
        error = read.target_errors_rad.get(joint)
        target = None if error is None else position - error
        samples.append(JointSample(joint, joint, final_t, position, None, target))
    return samples


def _sweep_samples(sweep: Sweep, readback: dict[str, Any]) -> list[JointSample]:
    read = _SweepReadback.model_validate(readback)
    device_id, joint = f"{sweep.articulation}/{sweep.joint}", sweep.joint
    samples = [
        JointSample(device_id, joint, sample.step / _PHYSICS_HZ, sample.position_rad)
        for sample in read.samples
    ]
    final_t = max([read.steps, *(s.step for s in read.samples)]) / _PHYSICS_HZ
    samples.append(JointSample(device_id, joint, final_t, read.final_position_rad))
    return samples


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


def _is_stage_action(name: str, parsed: Strict) -> bool:
    return name in _STAGE_ACTIONS or (isinstance(parsed, Routine) and parsed.routine == "sweep")


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


@dataclass(frozen=True)
class _Plan:
    observation: _Observation
    rows: list[dict[str, Any]]
    snapshot: str
    push: bool  # the fork lacks the bound model's files; `invoke` pushes them first


@dataclass
class _Ticket:
    args: str
    snapshot: str
    consumed: bool = False


class IsaacTool:
    """The sole public wrapper; its raw bridge capability never enters the registry."""

    def __init__(
        self,
        name: str,
        raw: Mapping[str, Tool],
        resolver: _Resolver,
        ledger: SessionsLedger,
        push: ModelPush,
        *,
        user_id: uuid.UUID | None = None,
        record_sim_run: RecordSimRun = no_sim_run,
    ) -> None:
        self.name = name
        self.raw = raw
        self.resolver = resolver
        self.ledger = ledger
        self.push = push
        self.user_id = user_id  # the principal a ledger row names (`created_by`)
        self.record_sim_run = record_sim_run
        self.requires_complete_preview = name not in _READ_ONLY
        self._ticket: ContextVar[_Ticket | None] = ContextVar("isaac_approval", default=None)
        self._descriptor = ToolDescriptor(
            name="isaac." + name,
            description=_DESCRIPTIONS[name],
            params=PUBLIC_MODELS[name].model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=name in _STATIC_GATED,
            consent_summary=_DESCRIPTIONS[name] if self.requires_complete_preview else None,
            timeout_seconds=_TIMEOUTS[name],
            files_errors=self.requires_complete_preview,
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    async def needs_confirmation(self, args: dict[str, Any]) -> bool:
        """The per-call gate hook (`agent/dynamic_gate.py`): card unless the ledger proves the
        session Solus-owned — and even then when the fork's own dry run carries an "Approval
        required" row (ADR-040 §5; P10 item 22), which can only make a call stricter. Raises
        propagate — `needs_card` fails closed on them."""
        if await self._ownership_card(args):
            return True
        # Every tool with a dry run, `start`/`open_stage` included: a labelled plan must reach
        # a card here, never an unapprovable refusal in `invoke`.
        return self.name not in _READ_ONLY and await self._label_card(args)

    async def _ownership_card(self, args: dict[str, Any]) -> bool:
        if self.name in _STATIC_GATED:
            return True
        if self.name in _READ_ONLY | _OWNED_BY_CONSTRUCTION:
            return False
        session_id = args.get("session_id")
        if not isinstance(session_id, str):
            return True
        return not await self.ledger.is_owned(
            project_id=self.resolver.project_id, provider=PROVIDER, session_id=session_id
        )

    async def _label_card(self, args: dict[str, Any]) -> bool:
        """The fork's dry run, read for the label only. A plan that fails here fails the same
        way in `_verified`, where it refuses the call; nothing runs either way."""
        try:
            plan = await self._plan(_parse(self.name, args))
        except ToolException:
            return False
        return approval_required(plan.rows)

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
        status = without_claims(status)
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

    async def _stage_native(
        self, parsed: Strict, args: dict[str, Any]
    ) -> tuple[dict[str, Any], _Graph | None]:
        """A stage action binds the scene generation, never a loaded graph model; `spawn_at`
        resolves its graph model for the files it pushes and the digest the fork spawns."""
        rest = {key: value for key, value in args.items() if key not in ("session_id", "dry_run")}
        if isinstance(parsed, SpawnAt):
            graph = await self.resolver.resolve(rest.pop("model_entity_id"))
            return {**rest, "model_sha256": graph.model.asset.sha256}, graph
        if isinstance(parsed, Routine):
            return {"routine_spec": rest}, None
        return rest, None

    async def _observe(self, parsed: Strict) -> _Observation:
        state = await self._status()
        args = parsed.model_dump()
        if self.name in _OWNED_BY_CONSTRUCTION:
            return _Observation(args, state, None)
        if state["state"] != "running" or args["session_id"] != state.get("session_id"):
            raise _refuse("The selected Isaac session is no longer current.")
        if self.name == "stop":
            return _Observation(args, state, None)
        native = {
            "session_id": args["session_id"],
            "dry_run": args["dry_run"],
            "expected_scene_generation": state["scene_generation"],
        }
        if _is_stage_action(self.name, parsed):
            extra, graph = await self._stage_native(parsed, args)
            return _Observation({**native, **extra}, state, graph)
        model_id = (
            parsed.model_entity_id if isinstance(parsed, Load) else state.get("model_entity_id")
        )
        graph = await self.resolver.resolve(model_id)
        if not isinstance(parsed, Load) and (
            state.get("loaded") is not True or state.get("graph_digest") != graph.digest
        ):
            raise _refuse("The loaded model no longer matches its graph snapshot.")
        native["graph_digest"] = graph.digest
        native.update(_target(parsed, graph))
        return _Observation(native, state, graph)

    async def _refuse_second_owned(self) -> None:
        count = await self.ledger.owned_running_count(
            project_id=self.resolver.project_id, provider=PROVIDER
        )
        if count:
            raise _refuse(
                "An Isaac session Solus started is still running in this project; stop it first."
            )

    @staticmethod
    def _consent_rows(plan: Any) -> tuple[list[dict[str, Any]], str]:
        """The fork's dry-run preview as consent rows, or a refusal: no complete preview, no
        action. A refused dry run (`store_unsafe`, `stage_refused`) carries the fork's reason as
        a `PreviewRefusal`: the one preview failure `_build_preview` carries into the tool result.
        """
        if isinstance(plan, dict) and plan.get("ok") is False:
            raise PreviewRefusal(refusal_sentence(plan), code=ToolErrorCode.TOOL_ERROR)
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
        return rows, fingerprint

    async def _plan(self, parsed: Strict) -> _Plan:
        observation = await self._observe(parsed)
        if self.name in _OWNED_BY_CONSTRUCTION:
            await self._refuse_second_owned()
        plan = await self.raw[self.descriptor.name].invoke(
            {**observation.native_args, "dry_run": True}
        )
        graph = observation.graph
        push = graph is not None and self.name == "spawn_at" and model_not_verified(plan)
        if push and graph is not None:
            rows, fingerprint = await self.push.preview(graph, observation.native_args)
        else:
            rows, fingerprint = self._consent_rows(plan)
        binding = f"Native action fingerprint: {_display_digest(fingerprint)}"
        if graph is not None:
            binding += (
                f"; Graph model: {graph.model_id} / version {graph.model_version}"
                f"; Graph snapshot fingerprint: {_display_digest(graph.digest)}"
            )
        label = "Graph and native action binding" if graph else "Native action fingerprint"
        rows.append(consent_row(label, binding))
        if not _diff_rows(rows):
            raise _refuse("The complete Isaac preview is too large.")
        snapshot = _digest(
            {"native_args": observation.native_args, "state": observation.state, "rows": rows}
        )
        return _Plan(observation, rows, snapshot, push)

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        self._clear()
        parsed = _parse(self.name, args)
        plan = await reaching(self._plan(parsed))
        self._ticket.set(_Ticket(_canonical(args), plan.snapshot))
        return plan.rows

    async def _read(self, parsed: Strict) -> dict[str, Any]:
        if self.name == "status":
            state = await self._status()
            if state.get("loaded") is True:
                await self.resolver.resolve(state.get("model_entity_id"))
            return state
        native = parsed.model_dump() if self.name not in ("probe", "list_stages") else {}
        result = await self.raw[self.descriptor.name].invoke(native)
        return without_claims(result) if isinstance(result, dict) else result

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        return await reaching(self._invoke(args))

    async def _invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        parsed = _parse(self.name, args)
        if self.name in _READ_ONLY:
            return await self._read(parsed)
        ticket = await self._authorize(args)
        # The ticket (if any) is marked consumed so any exception, cancellation or
        # child-task dispatch cannot replay it. The complete plan runs right before
        # the native call on BOTH paths: approved card, or owned session.
        plan = await self._verified(parsed, ticket)
        if ticket is None and approval_required(plan.rows):
            raise _refuse("This Isaac action needs confirmation; it was not approved.")
        result = await self.raw[self.descriptor.name].invoke(plan.observation.native_args)
        result = without_claims(result) if isinstance(result, dict) else result
        answered = await self._record(args, result, plan.observation.graph)
        return answered if isinstance(answered, dict) else result

    async def _verified(self, parsed: Strict, ticket: _Ticket | None) -> _Plan:
        plan = await self._plan(parsed)
        if ticket is not None and plan.snapshot != ticket.snapshot:
            raise _refuse()
        graph = plan.observation.graph
        if graph is None:
            return plan
        fresh = await self.resolver.resolve(graph.model_id)
        if fresh.digest != graph.digest:
            raise _refuse("The graph changed while Isaac was preparing the action.")
        if not plan.push:
            return plan
        put = self.raw.get(PUT_ASSET)
        await self.push.send(graph, put.invoke if put else None)
        pushed = await self._plan(parsed)  # the fork's own preview, now that it holds it
        # The push window is long (≤ 300 s): the re-plan must still be the approved action —
        # same native args (so the same model sha) on the same graph snapshot.
        if (
            pushed.observation.native_args != plan.observation.native_args
            or pushed.observation.graph is None
            or pushed.observation.graph.digest != graph.digest
        ):
            raise _refuse("The graph changed while Isaac was preparing the action.")
        if pushed.push:
            raise _refuse("The companion did not accept the pushed model.")
        return pushed

    async def _authorize(self, args: dict[str, Any]) -> _Ticket | None:
        """A fresh ticket whose args match this call, or None when ownership must let it
        through. A parked card's leftover ticket (other args) never poisons the next call."""
        ticket = self._ticket.get()
        was_consumed = ticket is None or ticket.consumed
        self._clear()
        if ticket is not None and not was_consumed and ticket.args == _canonical(args):
            return ticket
        try:
            card = await self._ownership_card(args)  # the label is read off the verified plan
        except Exception:
            logger.warning("isaac ownership read failed for %s; refusing", self.descriptor.name)
            card = True
        if card:
            raise _refuse("This Isaac action needs confirmation; it was not approved.")
        return None

    async def _record(
        self, args: dict[str, Any], result: Any, graph: _Graph | None
    ) -> dict[str, Any] | None:
        """Ownership is a DB fact written by this wrapper only after the native call said ok;
        a SOL-supplied dry run changes nothing, so it records nothing. A routine's hook may
        answer with the result to return (the Run it filed); it is told the model this call
        verified (`graph`, None for a stage-bound sweep), never one the companion names."""
        if args.get("dry_run") is True:
            return None
        if not isinstance(result, dict) or result.get("ok") is not True:
            return None
        if self.name == "stop":
            await self.ledger.end_session(
                project_id=self.resolver.project_id,
                provider=PROVIDER,
                session_id=args["session_id"],
            )
        elif self.name == "run_routine":
            # The id crosses as text; the hook parses it inside its never-raises boundary.
            model = graph.model_id if graph is not None else None
            return await self.record_sim_run(args, result, model_entity_id=model)
        elif self.name in _OWNED_BY_CONSTRUCTION:
            await self._record_owned(args, result)
        return None

    async def _record_owned(self, args: dict[str, Any], result: dict[str, Any]) -> None:
        session_id = result.get("session_id")
        try:
            session_id = _parse("stop", {"session_id": session_id}).model_dump()["session_id"]
        except ToolException:
            logger.warning("isaac %s returned no session id; nothing is owned", self.name)
            return
        try:
            await self.ledger.record_owned_start(
                project_id=self.resolver.project_id,
                provider=PROVIDER,
                session_id=session_id,
                call_id=current_call_id.get(),
                # Root-relative by the Strict model; never an absolute path.
                scene_ref=args.get("stage_ref") if self.name == "open_stage" else None,
                created_by=self.user_id,
            )
        except OwnedSessionRunningError:
            logger.warning(
                "isaac %s raced an owned session project=%s", self.name, self.resolver.project_id
            )
            raise _refuse(
                "An Isaac session Solus started is still running in this project; the new one is "
                "not owned — stop it with isaac.stop after approval."
            ) from None


def build_isaac_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    raw_tools: Mapping[str, Tool],
    *,
    ledger: SessionsLedger,
    artifacts: ArtifactStore | None = None,
    user_id: uuid.UUID | None = None,
    record_sim_run: RecordSimRun | None = None,
) -> list[Tool]:
    """Build only known cloud-owned wrappers; never forward an advertised schema. `put_asset`
    stays internal to `spawn_at`."""
    raw = {
        name: tool
        for name, tool in raw_tools.items()
        if name.startswith("isaac.") and (name[6:] in PUBLIC_MODELS or name == PUT_ASSET)
    }
    resolver = _Resolver(session_factory, project_id)
    push = ModelPush(session_factory, project_id, artifacts)
    return [
        IsaacTool(
            name,
            raw,
            resolver,
            ledger,
            push,
            user_id=user_id,
            record_sim_run=record_sim_run or no_sim_run,
        )
        for name in PUBLIC_MODELS
        if "isaac." + name in raw and (name == "probe" or "isaac.status" in raw)
    ]
