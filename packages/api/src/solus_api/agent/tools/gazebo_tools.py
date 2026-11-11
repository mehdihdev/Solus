"""The owned `gazebo.*` wrappers (SOLUSDEV-322 P3-T4): per-call consent by ownership, graph-bound
models, verified chunks across the bridge.

Mirrors `isaac_tools.py`: the raw `gazebo.*` bridge tools never enter the registry; one
`GazeboTool` per public name parses SOL's arguments strictly, asks the ownership ledger whether
this concrete call needs a card (`needs_confirmation`, read by `agent/dynamic_gate.py`), runs the
fork's complete dry-run preview immediately before every native call, and writes the ledger —
ownership is a DB fact this wrapper records after the native call said ok, never a companion
claim (`owned`/`owner` fields in a fork result are dropped).

`spawn` binds a graph `simulation_model` (v2) and pushes its files when the companion reports
the model absent, through the shared `sim_assets.ModelPush` (P4-T2): `put_asset` chunks of
≤ 64 KiB raw read from the artifact store and verified against the manifest before they leave.
`run_routine` hands its result to the `record_sim_run` hook (`livebench/sim_runs.py:sim_run_hook`
over `gazebo_routine_readback`, P5-T4): the readback becomes a Run and a rung-4 fact, and the
hook answers inside the result (`run`, `sim_result_id`, `run_reason`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.dynamic_gate import approval_required, current_call_id
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.gazebo_models import (
    PUBLIC_MODELS,
    READ_ONLY,
    WRITERS,
    Attach,
    FamilyName,
    Finite,
    GzSession,
    Name,
    RunRoutine,
    Spawn,
)
from solus_api.agent.tools.isaac_models import Strict
from solus_api.agent.tools.isaac_tools import (  # the shared v2 model resolver and ticket shape
    _display_digest,
    _Graph,
    _Resolver,
    _Ticket,
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
from solus_api.livebench.sim_runs import JointSample, RoutineReadback
from solus_api.simulation.sessions_ledger import (
    OwnedSessionRunningError,
    SessionsLedger,
    SimSessionRecord,
)
from solus_api.storage.artifact_store import ArtifactStore

logger = logging.getLogger("solus.agent.gazebo_tools")

PROVIDER: Final = "gazebo"
PUT_ASSET: Final = "gazebo.put_asset"
_DIGEST = re.compile(r"[0-9a-f]{64}")
#: Owned by construction: the call CREATES the Solus-owned session the ledger then records.
_OWNED_BY_CONSTRUCTION: Final = frozenset({"open_world"})
#: Writes to the user's own files always card.
_STATIC_GATED: Final = frozenset({"save_world"})
_UNGATED: Final = READ_ONLY | _OWNED_BY_CONSTRUCTION | {"attach"}
_ATTACHED_STOP: Final = (
    "This world was started by you, not by Solus; stop it from where you started it."
)
#: Cloud bounds exceed the fork's allowlist bounds so the cloud never reports TIMEOUT while the
#: companion keeps running; `spawn` covers the chunk push (~32 round trips for a 2 MiB model).
_TIMEOUTS: Final = {
    "probe": 25,
    "list_worlds": 25,
    "open_world": 130,
    "attach": 25,
    "list_models": 25,
    "spawn": 300,
    "joint_state": 35,
    "set_joint_targets": 25,
    "control": 65,
    "run_routine": 100,
    "stop": 35,
    "save_world": 35,
}
_DESCRIPTIONS: Final = {
    "probe": (
        "Report which Gazebo families are installed on the user's machine when sim.available asks "
        "or before a start."
    ),
    "list_worlds": (
        "List the user's Gazebo world files under the sim roots and the worlds running now when "
        "choosing a world."
    ),
    "open_world": (
        "Start one Solus-owned Gazebo server on one of the user's world files when the question "
        "is about that world."
    ),
    "attach": (
        "Register a Gazebo world the user started themselves when they point at it (read-only; "
        "actions card)."
    ),
    "list_models": (
        "Read models, links and joints of one registered Gazebo world when the robot inside it "
        "must be located."
    ),
    "spawn": (
        "Insert a graph-bound Solus simulation model into a registered Gazebo world when the "
        "world lacks the robot."
    ),
    "joint_state": (
        "Read a bounded window of joint positions and velocities (radians) when a value is asked "
        "for."
    ),
    "set_joint_targets": (
        "Set joint position targets (radians) inside a registered Gazebo world when a pose must "
        "be tried."
    ),
    "control": "Pause, play, step or reset one registered Gazebo world when time itself must move.",
    "run_routine": (
        "Run a finite joint routine in Gazebo with readback of the final error when a motion "
        "needs checking."
    ),
    "stop": "Stop the Gazebo server Solus itself started when its work is done.",
    "save_world": (
        "Write the running Gazebo world back into one of the user's own files when the person "
        "asks to keep it."
    ),
}

#: The routine hook: native args and the fork's result in, the result to answer with out (None
#: keeps the fork's result as it is).
RecordSimRun = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any] | None]]


async def no_sim_run(args: dict[str, Any], result: dict[str, Any]) -> None:
    """The hook of a scope without a graph hub or artifact store: a routine records no Run."""


class _GzJointResult(Strict):
    target: Finite | None = None
    final: Finite | None = None
    error: Finite | None = None


class _GzSample(Strict):
    joint: Name
    position: Finite | None = None
    velocity: Finite | None = None
    sim_time_s: Finite | None = None


class _GzRoutineResult(BaseModel):
    """The fields of the fork's `run_routine` result the run recorder reads; the rest of the
    companion's data is ignored, never believed. `model` is read only to be checked against
    the request; the result's `world` is never read."""

    model_config = ConfigDict(extra="ignore")

    model: Name
    family: FamilyName | None = None
    version: str | None = Field(default=None, max_length=64)
    per_joint: dict[Name, _GzJointResult] = Field(default_factory=dict, max_length=64)
    samples: list[_GzSample] = Field(default_factory=list, max_length=4096)


def _requested_joints(request: RunRoutine) -> frozenset[str]:
    """The joints SOL asked the routine to drive: the sweep's one, else `joints`, else every
    joint a waypoint positions."""
    if request.sweep is not None:
        return frozenset({request.sweep.joint})
    if request.joints:
        return frozenset(request.joints)
    return frozenset(j for w in request.waypoints or () for j in w.positions)


def gazebo_routine_readback(
    args: dict[str, Any], result: dict[str, Any], *, session: SimSessionRecord | None = None
) -> RoutineReadback:
    """`sim_run_hook`'s reader: one `JointSample` per finite position, named
    `<world>/<model>/<joint>` as the telemetry source names it, with the joint's last target
    from `per_joint`. The binding is the API's: the world is the ledger row's `scene_name`
    (recorded when the session started), the model is the REQUEST's, and only the joints the
    request asked for are kept — a result naming another model is refused, a world the ledger
    does not know refuses the filing, a foreign joint is dropped. Raises `ValidationError` or
    `ValueError` on a result it cannot read or refuses."""
    request = RunRoutine.model_validate(args)
    read = _GzRoutineResult.model_validate(result)
    world = session.scene_name if session is not None else None
    if world is None:
        raise ValueError("the ledger knows no world name for this session")
    if read.model != request.model:
        raise ValueError("the routine result names a model other than the requested one")
    joints = _requested_joints(request)
    samples = [
        JointSample(
            device_id=f"{world}/{request.model}/{sample.joint}",
            joint=sample.joint,
            t_s=sample.sim_time_s if sample.sim_time_s is not None else index * 0.1,
            position=sample.position,
            velocity=sample.velocity,
            target=read.per_joint[sample.joint].target if sample.joint in read.per_joint else None,
        )
        for index, sample in enumerate(read.samples)
        if sample.position is not None and sample.joint in joints
    ]
    return RoutineReadback(samples, family=read.family, version=read.version)


def _gz_refuse(message: str = "Gazebo approval is stale or unavailable.") -> ToolException:
    return ToolException(message, code=ToolErrorCode.TOOL_ERROR, retryable=False)


def _gz_canonical(value: Any) -> str:
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise _gz_refuse("Gazebo returned invalid structured data.") from None
    if len(result.encode()) > 128 * 1024:
        raise _gz_refuse("Gazebo observation exceeds the bounded result size.")
    return result


def _gz_digest(value: Any) -> str:
    return hashlib.sha256(_gz_canonical(value).encode()).hexdigest()


def _gz_wire_digest(value: Any) -> str:
    if isinstance(value, str):
        if _DIGEST.fullmatch(value):
            return value
        if re.fullmatch(r"(?:[0-9a-f]{16}:){3}[0-9a-f]{16}", value):
            return value.replace(":", "")
    raise _gz_refuse("Gazebo returned an invalid digest.")


def _gz_parse(name: str, args: dict[str, Any]) -> Strict:
    try:
        return PUBLIC_MODELS[name].model_validate(args)
    except ValidationError:
        raise ToolException("Invalid Gazebo arguments.", code=ToolErrorCode.INVALID_ARGS) from None


def _world_name_of(result: Mapping[str, Any]) -> str | None:
    """The world name an `open_world` result reports, only when it is identifier-shaped."""
    try:
        return Attach.model_validate({"family": "gz", "world": result.get("world")}).world
    except ValidationError:
        return None


def _consent_rows(plan: Any) -> tuple[list[dict[str, Any]], str]:
    """The fork's dry-run preview as consent rows, or a refusal: no complete preview, no action.
    A refused dry run (`unsupported_on` for `save_world` on Classic) carries the fork's reason as
    a `PreviewRefusal`: the one preview failure `_build_preview` carries into the tool result."""
    if isinstance(plan, dict) and plan.get("ok") is False:
        raise PreviewRefusal(refusal_sentence(plan), code=ToolErrorCode.TOOL_ERROR)
    if not isinstance(plan, dict) or plan.get("ok") is not True or plan.get("dry_run") is not True:
        raise _gz_refuse("Gazebo did not produce a complete dry-run preview.")
    rows = _diff_rows(plan.get("preview"))
    if not rows:
        raise _gz_refuse("Gazebo did not produce a complete dry-run preview.")
    return rows, _gz_wire_digest(plan.get("fingerprint"))


@dataclass(frozen=True)
class _GzPlan:
    native: dict[str, Any]
    rows: list[dict[str, Any]]
    snapshot: str
    graph: _Graph | None
    push: bool


def _same_action(fresh: _GzPlan, approved: _GzPlan) -> bool:
    return (
        fresh.native == approved.native
        and fresh.graph is not None
        and approved.graph is not None
        and fresh.graph.digest == approved.graph.digest
    )


class GazeboTool:
    """The sole public wrapper; its raw bridge capability never enters the registry."""

    def __init__(
        self,
        name: str,
        raw: Mapping[str, Tool],
        resolver: _Resolver,
        ledger: SessionsLedger,
        push: ModelPush,
        *,
        user_id: uuid.UUID | None,
        record_sim_run: RecordSimRun,
    ) -> None:
        self.name = name
        self.raw = raw
        self.resolver = resolver
        self.ledger = ledger
        self.push = push
        self.user_id = user_id
        self.record_sim_run = record_sim_run
        self.requires_complete_preview = name in WRITERS
        self._ticket: ContextVar[_Ticket | None] = ContextVar("gazebo_approval", default=None)
        self._descriptor = ToolDescriptor(
            name=PROVIDER + "." + name,
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

    async def _attached(self, session_id: str) -> bool:
        """Known to the ledger as a world the user started (an attach row, live)."""
        rows = await self.ledger.running(project_id=self.resolver.project_id, provider=PROVIDER)
        return any(r.session_id == session_id and r.owner == "user" for r in rows)

    async def needs_confirmation(self, args: dict[str, Any]) -> bool:
        """The per-call gate hook (`agent/dynamic_gate.py`): card unless the ledger proves the
        session Solus-owned — and even then when the fork's own dry run carries an "Approval
        required" row (ADR-040 §5; P10 item 22), which can only make a call stricter. Raises
        propagate — `needs_card` fails closed on them. `stop` of a world the user started is
        refused by `invoke` itself, never carded."""
        if await self._ownership_card(args):
            return True
        # Every tool with a dry run, the session-creating ones included: a labelled plan
        # must reach a card here, never an unapprovable refusal in `invoke`.
        return self.name not in READ_ONLY | {"attach"} and await self._label_card(args)

    async def _ownership_card(self, args: dict[str, Any]) -> bool:
        if self.name in _STATIC_GATED:
            return True
        if self.name in _UNGATED:
            return False
        session_id = args.get("session_id")
        if not isinstance(session_id, str):
            return True
        if await self.ledger.is_owned(
            project_id=self.resolver.project_id, provider=PROVIDER, session_id=session_id
        ):
            return False
        return not (self.name == "stop" and await self._attached(session_id))

    async def _label_card(self, args: dict[str, Any]) -> bool:
        """The fork's dry run, read for the label only. A plan that fails here fails the same
        way in `_verified`, where it refuses the call; nothing runs either way."""
        try:
            plan = await self._plan(_gz_parse(self.name, args))
        except ToolException:
            return False
        return approval_required(plan.rows)

    def _clear(self) -> None:
        previous = self._ticket.get()
        if previous is not None:
            previous.consumed = True
        self._ticket.set(None)

    async def _native_args(self, parsed: Strict) -> tuple[dict[str, Any], _Graph | None]:
        native = parsed.model_dump()
        if not isinstance(parsed, Spawn):
            return native, None
        graph = await self.resolver.resolve(native.pop("model_entity_id"))
        native["model_sha256"] = graph.model.asset.sha256
        return native, graph

    async def _refuse_second_owned(self) -> None:
        count = await self.ledger.owned_running_count(
            project_id=self.resolver.project_id, provider=PROVIDER
        )
        if count:
            raise _gz_refuse(
                "A Gazebo world Solus started is still running in this project; stop it first."
            )

    async def _plan(self, parsed: Strict) -> _GzPlan:
        native, graph = await self._native_args(parsed)
        if self.name == "open_world":
            await self._refuse_second_owned()
        if self.name == "stop" and await self._attached(native["session_id"]):
            raise _gz_refuse(_ATTACHED_STOP)
        plan = await self.raw[self.descriptor.name].invoke({**native, "dry_run": True})
        push = graph is not None and model_not_verified(plan)
        if push and graph is not None:
            rows, fingerprint = await self.push.preview(graph, native)
        else:
            rows, fingerprint = _consent_rows(plan)
        binding = f"Native action fingerprint: {_display_digest(fingerprint)}"
        if graph is not None:
            binding += (
                f"; Graph model: {graph.model_id} / version {graph.model_version}"
                f"; Graph snapshot fingerprint: {_display_digest(graph.digest)}"
            )
        label = "Graph and native action binding" if graph else "Native action fingerprint"
        rows.append(consent_row(label, binding))
        if not _diff_rows(rows):
            raise _gz_refuse("The complete Gazebo preview is too large.")
        snapshot = _gz_digest({"native_args": native, "rows": rows})
        return _GzPlan(native, rows, snapshot, graph, push)

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        self._clear()
        plan = await reaching(self._plan(_gz_parse(self.name, args)))
        self._ticket.set(_Ticket(_gz_canonical(args), plan.snapshot))
        return plan.rows

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        return await reaching(self._invoke(args))

    async def _invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        parsed = _gz_parse(self.name, args)
        native = parsed.model_dump()
        if self.name in READ_ONLY:
            return without_claims(await self.raw[self.descriptor.name].invoke(native))
        if self.name == "attach":
            answer = await self.raw[self.descriptor.name].invoke(native)
            return await self._record(native, without_claims(answer))
        ticket = await self._authorize(args)
        # The ticket (if any) is marked consumed so any exception, cancellation or child-task
        # dispatch cannot replay it. The complete plan runs right before the native call on BOTH
        # paths: approved card, or owned session — and on the owned path the plan's own
        # "Approval required" row refuses (the hook would have carded it).
        plan = await self._verified(parsed, ticket)
        if ticket is None and approval_required(plan.rows):
            raise _gz_refuse("This Gazebo action needs confirmation; it was not approved.")
        result = without_claims(await self.raw[self.descriptor.name].invoke(plan.native))
        return await self._record(native, result)

    async def _verified(self, parsed: Strict, ticket: _Ticket | None) -> _GzPlan:
        plan = await self._plan(parsed)
        if ticket is not None and plan.snapshot != ticket.snapshot:
            raise _gz_refuse()
        if plan.graph is not None:
            fresh = await self.resolver.resolve(plan.graph.model_id)
            if fresh.digest != plan.graph.digest:
                raise _gz_refuse("The graph changed while Gazebo was preparing the action.")
            if plan.push:
                put = self.raw.get(PUT_ASSET)
                await self.push.send(plan.graph, put.invoke if put else None)
                approved = plan
                plan = await self._plan(parsed)  # the fork's own preview, now that it holds it
                # The push window is long (≤ 300 s): the re-plan must still be the approved
                # action — same native args (so the same model sha) on the same graph snapshot.
                if not _same_action(plan, approved):
                    raise _gz_refuse("The graph changed while Gazebo was preparing the action.")
                if plan.push:
                    raise _gz_refuse("The companion did not accept the pushed model.")
        return plan

    async def _authorize(self, args: dict[str, Any]) -> _Ticket | None:
        """A fresh ticket whose args match this call, or None when ownership must let it
        through. A parked card's leftover ticket (other args) never poisons the next call."""
        ticket = self._ticket.get()
        was_consumed = ticket is None or ticket.consumed
        self._clear()
        if ticket is not None and not was_consumed and ticket.args == _gz_canonical(args):
            return ticket
        try:
            card = await self._ownership_card(args)  # the label is read off the verified plan
        except Exception:
            logger.warning("gazebo ownership read failed for %s; refusing", self.descriptor.name)
            card = True
        if card:
            raise _gz_refuse("This Gazebo action needs confirmation; it was not approved.")
        return None

    @staticmethod
    def _session_id_of(result: Mapping[str, Any]) -> str | None:
        try:
            return GzSession.model_validate({"session_id": result.get("session_id")}).session_id
        except ValidationError:
            return None

    async def _record(self, native: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Ownership is a DB fact written by this wrapper only after the native call said ok;
        the companion's own claims were stripped by `without_claims` before this point. A
        SOL-supplied dry run is answered by the fork's preview and changes nothing, so it
        records nothing."""
        if native.get("dry_run") is True:
            return result
        if not isinstance(result, dict) or result.get("ok") is not True:
            return result
        if self.name == "stop":
            await self.ledger.end_session(
                project_id=self.resolver.project_id,
                provider=PROVIDER,
                session_id=native["session_id"],
            )
        elif self.name == "run_routine":
            answered = await self.record_sim_run(native, result)
            return answered if isinstance(answered, dict) else result
        elif self.name in _OWNED_BY_CONSTRUCTION or self.name == "attach":
            session_id = self._session_id_of(result)
            if session_id is None:
                logger.warning("gazebo %s returned no session id; nothing is recorded", self.name)
                return result
            record = await self._ledger_row(native, session_id, result)
            return {**result, "owner": record.owner}
        return result

    async def _ledger_row(
        self, native: dict[str, Any], session_id: str, result: Mapping[str, Any]
    ) -> SimSessionRecord:
        """The row also fixes the world NAME a later routine readback is keyed by: the request's
        for an attach; for an owned start the name the fork resolved from the user's file at
        this moment (an identifier or nothing — never re-read from a later result)."""
        project_id = self.resolver.project_id
        if self.name == "attach":
            return await self.ledger.record_attached(
                project_id=project_id,
                provider=PROVIDER,
                session_id=session_id,
                scene_ref=native["world"],
                scene_name=native["world"],
                created_by=self.user_id,
            )
        try:
            return await self.ledger.record_owned_start(
                project_id=project_id,
                provider=PROVIDER,
                session_id=session_id,
                call_id=current_call_id.get(),
                scene_ref=native["world_ref"],
                scene_name=_world_name_of(result),
                created_by=self.user_id,
            )
        except OwnedSessionRunningError:
            logger.warning("gazebo open_world raced an owned session project=%s", project_id)
            raise _gz_refuse(
                "A Gazebo world Solus started is still running in this project; the new one is "
                "not owned — stop it with gazebo.stop after approval."
            ) from None


def build_gazebo_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    raw_tools: Mapping[str, Tool],
    *,
    ledger: SessionsLedger,
    artifacts: ArtifactStore | None,
    user_id: uuid.UUID | None = None,
    record_sim_run: RecordSimRun | None = None,
) -> list[Tool]:
    """Build only known cloud-owned wrappers; never forward an advertised schema. `put_asset`
    stays internal to `spawn`."""
    raw = {
        name: tool
        for name, tool in raw_tools.items()
        if name.startswith(PROVIDER + ".") and (name[7:] in PUBLIC_MODELS or name == PUT_ASSET)
    }
    resolver = _Resolver(session_factory, project_id)
    push = ModelPush(session_factory, project_id, artifacts)
    return [
        GazeboTool(
            name,
            raw,
            resolver,
            ledger,
            push,
            user_id=user_id,
            record_sim_run=record_sim_run or no_sim_run,
        )
        for name in PUBLIC_MODELS
        if PROVIDER + "." + name in raw
    ]
