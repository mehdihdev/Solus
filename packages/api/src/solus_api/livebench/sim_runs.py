"""Sim runs (SOLUSDEV-322 P5): what a simulated session shares with a real one.

P5-T3 — `robot_of_part`: the live Physical Robot a resolved part belongs to, so a sim session
binds to the robot its packets describe and runs the same window evaluator a real session does.
The lookup walks ownership upward in the shape of `scene/cad_import.children`, bounded, and
believes a root only once `hardware/store.robot_root` confirms it is live.

P5-T4 — `record_sim_run`: a routine's joint readback becomes a Run (`origin="sim"`) on the robot
the model is bound to — `simulation_model.attrs.robot_id`, else the robot above any joint the
provider's aliases resolve to (`sim.map_to_parts`) — and a rung-4 `sim_result` on that robot:
the largest final target error in radians, with the provider, family, version, model hash, scene
and routine as its provenance. No robot: nothing is recorded and the reason says so (empty beats
invented). `sim_run_hook` is the shape the owned simulator wrappers call it through.

Shared code: `provider` is a string the wrappers pass; this module names no simulator.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from pydantic import JsonValue, ValidationError
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.core.errors import APIError
from solus_api.graph.live import LiveHub
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DbEntityResolver
from solus_api.hardware.store import ROBOT_KIND, robot_root
from solus_api.livebench.runs.models import PartEvidence, RunManifest, RunSummary, SimRunInfo
from solus_api.livebench.runs.store import new_record, save
from solus_api.models import GraphEdge, GraphEntity, utcnow
from solus_api.simulation.sessions_ledger import SessionsLedger, SimSessionRecord
from solus_api.simulation.sim_capability import SimInput, SimProvenance, SimResult, SimValue
from solus_api.simulation.sim_facts import record_sim_result
from solus_api.storage.artifact_store import ArtifactStore

logger = logging.getLogger("solus.livebench.sim_runs")

#: The relations a part reaches its robot through: hardware ownership (`contains`, parent -> child,
#: directly or through a category node) and CAD assembly membership (`part_of`, child -> parent,
#: as connectors/mechanical.py writes it and scene/cad_import.children reads it).
CONTAINS, PART_OF = "contains", "part_of"
MAX_DEPTH = 6
MAX_PARENTS = 16

RobotLookup = Callable[[uuid.UUID, uuid.UUID], Awaitable[uuid.UUID | None]]


async def _parents(
    db: AsyncSession, project_id: uuid.UUID, children: Sequence[uuid.UUID]
) -> list[GraphEntity]:
    parent = case((GraphEdge.relation_type == PART_OF, GraphEdge.dst_id), else_=GraphEdge.src_id)
    parent_ids = select(parent).where(
        GraphEdge.project_id == project_id,
        or_(
            (GraphEdge.relation_type == CONTAINS) & GraphEdge.dst_id.in_(children),
            (GraphEdge.relation_type == PART_OF) & GraphEdge.src_id.in_(children),
        ),
        GraphEdge.deleted_at.is_(None),
    )
    rows = await db.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.id.in_(parent_ids),
            GraphEntity.deleted_at.is_(None),
        )
        .limit(MAX_PARENTS)
    )
    return list(rows)


async def robot_of_part(
    session: AsyncSession, project_id: uuid.UUID, part_id: uuid.UUID
) -> uuid.UUID | None:
    """The one live robot root above `part_id` in this project; None when there is none, when two
    robots claim the part, or when the root is not a live manual robot."""
    seen, frontier, roots = {part_id}, [part_id], set[uuid.UUID]()
    for _ in range(MAX_DEPTH):
        found = await _parents(session, project_id, frontier)
        parents = [row for row in found if row.id not in seen]
        if not parents:
            break
        seen.update(row.id for row in parents)
        roots.update(row.id for row in parents if row.kind == ROBOT_KIND)
        frontier = [row.id for row in parents if row.kind != ROBOT_KIND]
        if not frontier:
            break
    if len(roots) != 1:
        return None
    (robot,) = roots
    try:
        await robot_root(session, project_id, robot)
    except APIError:
        return None
    return robot


def part_robot_lookup(sessionmaker: async_sessionmaker[AsyncSession]) -> RobotLookup:
    """`robot_of_part` on a session of its own — what the session manager is handed."""

    async def lookup(project_id: uuid.UUID, part_id: uuid.UUID) -> uuid.UUID | None:
        async with sessionmaker() as db:
            return await robot_of_part(db, project_id, part_id)

    return lookup


# ------------------------------------------------------------------------ P5-T4 sim runs

#: Readback samples one run keeps at most (a manifest holds 10 000 packets).
MAX_SIM_SAMPLES = 4096
NO_ROBOT = "no robot is bound to this model; map joints first"
NO_TARGET = "no joint had a target to read back against"
Sessions = async_sessionmaker[AsyncSession]
#: A companion-reported family or version is one solver WORD, or it is "unknown": neither the
#: run manifest nor `SimProvenance.solver` carries free text from a fork.
_SOLVER_WORD = re.compile(r"^[0-9A-Za-z.+-]{1,64}$")


def _solver_word(value: str | None) -> str | None:
    if value is None:
        return None
    return value if _SOLVER_WORD.fullmatch(value) else "unknown"


@dataclass(frozen=True)
class JointSample:
    """One joint reading of a routine. `device_id` is the joint as the provider names it on
    the wire — the alias `sim.map_to_parts` wrote (§1.4: `<world>/<model>/<joint>` for a world,
    the joint entity id for a graph-bound model) — `joint` the signal prefix, `t_s` the sample's
    time in the provider's clock (made relative here), `target` the position it was last
    commanded to when the readback says."""

    device_id: str
    joint: str
    t_s: float
    position: float
    velocity: float | None = None
    target: float | None = None


@dataclass(frozen=True)
class SimRunOutcome:
    run_id: uuid.UUID | None
    sim_result_id: uuid.UUID | None
    reason: str | None = None


async def record_sim_run(
    sessions: Sessions,
    hub: LiveHub,
    store: ArtifactStore,
    *,
    project_id: uuid.UUID,
    provider: str,
    family: str | None,
    version: str | None,
    model_entity_id: uuid.UUID | None,
    scene_ref: str | None,
    routine_args: Mapping[str, Any],
    samples: Sequence[JointSample],
    created_by: uuid.UUID | None,
) -> SimRunOutcome:
    """Module docstring. The Run is filed first (through `runs/store.save`, like a capture); the
    rung-4 fact goes through `record_sim_result`. Each refusal is a reason, not an exception."""
    kept = list(samples)[:MAX_SIM_SAMPLES]
    if created_by is None:
        return SimRunOutcome(None, None, "no user to file the run as")
    if not kept:
        return SimRunOutcome(None, None, "the routine returned no joint readback")
    resolver = DbEntityResolver(sessions)
    parts: dict[str, uuid.UUID] = {}
    for device_id in sorted({sample.device_id for sample in kept}):
        found = await resolver.resolve(project_id, device_id, source=provider)
        if found is not None:
            parts[device_id] = found
    async with sessions() as session:
        robot, model_sha256 = await _model(session, project_id, model_entity_id)
        robot = robot or await _robot_of_parts(session, project_id, parts.values())
        if robot is None:
            return SimRunOutcome(None, None, NO_ROBOT)
        info_of = SimRunInfo(
            provider=provider,
            family=_solver_word(family),
            version=_solver_word(version),
            model_sha256=model_sha256,
            scene_ref=scene_ref,
            routine=dict(routine_args),
        )
        names = await _names(session, project_id, parts.values())
        info, manifest = _manifest(robot, info_of, kept, parts, names)
        entity = new_record(project_id, info, created_by)
        session.add(entity)
        await session.flush()
        await save(session, store, entity, info, manifest, created_by, final=True)
    sim_id, reason = await _fact(sessions, hub, project_id, robot, info_of, kept, created_by)
    logger.info(
        "sim run recorded project=%s run=%s robot=%s provider=%s sim_result=%s",
        project_id,
        info.id,
        robot,
        provider,
        sim_id,
    )
    return SimRunOutcome(info.id, sim_id, reason)


async def _model(
    session: AsyncSession, project_id: uuid.UUID, model_entity_id: uuid.UUID | None
) -> tuple[uuid.UUID | None, str | None]:
    """The robot a generated model is bound to (`attrs.robot_id`, confirmed live) and its
    asset hash; nothing from a model that is not live in this project."""
    if model_entity_id is None:
        return None, None
    attrs = await session.scalar(
        select(GraphEntity.attrs).where(
            GraphEntity.id == model_entity_id,
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
        )
    )
    if not isinstance(attrs, dict):
        return None, None
    definition = attrs.get("simulation_model")
    asset = definition.get("asset") if isinstance(definition, dict) else None
    sha = asset.get("sha256") if isinstance(asset, dict) else None
    try:
        robot = uuid.UUID(str(attrs.get("robot_id")))
        await robot_root(session, project_id, robot)
    except (ValueError, APIError):
        return None, sha if isinstance(sha, str) else None
    return robot, sha if isinstance(sha, str) else None


async def _robot_of_parts(
    session: AsyncSession, project_id: uuid.UUID, parts: Iterable[uuid.UUID]
) -> uuid.UUID | None:
    for part in parts:
        robot = await robot_of_part(session, project_id, part)
        if robot is not None:
            return robot
    return None


async def _names(
    session: AsyncSession, project_id: uuid.UUID, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    rows = await session.execute(
        select(GraphEntity.id, GraphEntity.name).where(
            GraphEntity.project_id == project_id, GraphEntity.id.in_(list(ids))
        )
    )
    return {row.id: row.name for row in rows}


def _manifest(
    robot: uuid.UUID,
    sim: SimRunInfo,
    samples: Sequence[JointSample],
    parts: Mapping[str, uuid.UUID],
    names: Mapping[uuid.UUID, str],
) -> tuple[RunSummary, RunManifest]:
    """One packet per sample (§1.4 naming: `<joint>.position` rad, `<joint>.velocity` rad/s)
    on the provider's clock made relative to the first sample; one part per resolved device."""
    ended = utcnow()
    base = min(sample.t_s for sample in samples)
    span = max(sample.t_s for sample in samples) - base
    started = ended - timedelta(seconds=span)
    packets = [
        TelemetryPacket(
            device_id=sample.device_id,
            timestamp=started + timedelta(seconds=sample.t_s - base),
            values=_values(sample),
            units={
                name: ("rad/s" if name.endswith(".velocity") else "rad") for name in _values(sample)
            },
        )
        for sample in samples
    ]
    joint_of = {sample.device_id: sample.joint for sample in samples}
    evidence, seen = [], set[uuid.UUID]()
    for device_id, entity_id in parts.items():
        if entity_id in seen:
            continue
        seen.add(entity_id)
        evidence.append(
            PartEvidence(
                entity_id=entity_id,
                name=names.get(entity_id) or device_id,
                device_id=device_id,
                position_signal=f"{joint_of[device_id]}.position",
                position_unit="rad",
            )
        )
    manifest = RunManifest(
        robot_id=robot, started_at=started, packets=packets, parts=evidence, sim=sim
    )
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=robot,
        name=f"{sim.provider} {sim.routine.get('routine', 'routine')}"[:120],
        origin="sim",
        status="completed",
        started_at=started,
        ended_at=ended,
        packet_count=len(packets),
    )
    return info, manifest


_UNITS = {"position": "rad", "velocity": "rad/s"}


def _values(sample: JointSample) -> dict[str, float]:
    values = {f"{sample.joint}.position": sample.position}
    if sample.velocity is not None:
        values[f"{sample.joint}.velocity"] = sample.velocity
    return values


async def _fact(
    sessions: Sessions,
    hub: LiveHub,
    project_id: uuid.UUID,
    robot: uuid.UUID,
    sim: SimRunInfo,
    samples: Sequence[JointSample],
    created_by: uuid.UUID,
) -> tuple[uuid.UUID | None, str | None]:
    """The rung-4 fact (§1.1-11): `joint_trajectory` = the largest |final - target| over the
    joints the readback gives a target for; the provenance names the solver and the inputs."""
    last = {sample.joint: sample for sample in samples if sample.target is not None}
    if not last:
        return None, NO_TARGET
    per_joint: dict[str, JsonValue] = {
        joint: {
            "target": sample.target,
            "final": sample.position,
            "error": abs(sample.position - (sample.target or 0.0)),
        }
        for joint, sample in last.items()
    }
    worst = max(abs(s.position - (s.target or 0.0)) for s in last.values())
    result = SimResult(
        values={"joint_trajectory": SimValue(value=worst, unit="rad")},
        provenance=SimProvenance(
            solver=" ".join(word for word in (sim.provider, sim.family, sim.version) if word),
            inputs={
                "model_sha256": SimInput(value=sim.model_sha256, source="known"),
                "scene_ref": SimInput(value=sim.scene_ref, source="known"),
                "routine": SimInput(value=sim.routine, source="known"),
                "joints": SimInput(value=per_joint, source="known"),
            },
            leaves_out=(
                f"{sim.provider} integrates its model of the robot, not the hardware: motor "
                "electrical behaviour, backlash, compliance and sensor noise are not simulated",
            ),
        ),
    )
    try:
        sim_id = await record_sim_result(
            sessions,
            hub,
            project_id=project_id,
            subject_id=robot,
            rung=4,
            result=result,
            created_by=created_by,
        )
    except APIError as exc:
        return None, f"not recorded: {exc.code}"
    return sim_id, None


# ------------------------------------------------------- the owned wrappers' routine hook


@dataclass(frozen=True)
class RoutineReadback:
    """What a wrapper read out of its companion's `run_routine` result (untrusted data, parsed
    by the wrapper's own Strict models before it reaches here)."""

    samples: Sequence[JointSample]
    family: str | None = None
    version: str | None = None


class RoutineReader(Protocol):
    """Turns a companion's `run_routine` result into samples. `session` is the ledger row of
    the session the routine ran in (None when the ledger has none): what the API itself knows
    about the scene, so a reader keys its samples from the request and the ledger, never from
    names the companion's result carries. Raises `ValidationError` or `ValueError` on a result
    it cannot read or refuses."""

    def __call__(
        self,
        args: dict[str, Any],
        result: dict[str, Any],
        *,
        session: SimSessionRecord | None = None,
    ) -> RoutineReadback: ...


class SimRunHook(Protocol):
    """`model_entity_id` is the model the WRAPPER verified against its graph digest before the
    native call (None for a stage-bound routine) — the companion's result never names it. It
    may cross as uuid text: the hook parses it inside its never-raises boundary."""

    def __call__(
        self,
        args: dict[str, Any],
        result: dict[str, Any],
        *,
        model_entity_id: uuid.UUID | str | None = None,
    ) -> Awaitable[dict[str, Any] | None]: ...


UNREADABLE = "the routine readback was not understood"
NOT_FILED = "the run could not be filed"
#: The call's own plumbing, never an input of the routine.
_NOT_INPUTS = frozenset({"session_id", "dry_run"})


def sim_run_hook(
    sessions: Sessions,
    hub: LiveHub,
    store: ArtifactStore,
    ledger: SessionsLedger,
    *,
    project_id: uuid.UUID,
    provider: str,
    user_id: uuid.UUID | None,
    reader: RoutineReader,
) -> SimRunHook:
    """The `record_sim_run` hook an owned wrapper calls after a routine ran `ok`: `reader`
    turns the companion's result into samples (handed the session's ledger row, so the scene it
    keys by is the API's, never the companion's), the wrapper names the verified model it ran on
    (`model_entity_id`), the ledger supplies the session's `scene_ref`,
    and the answer is written INTO the result (`run`, `sim_result_id`, `run_reason`) — the
    routine ran, so a filing problem is reported there, never raised."""

    async def record(
        args: dict[str, Any],
        result: dict[str, Any],
        *,
        model_entity_id: uuid.UUID | str | None = None,
    ) -> dict[str, Any]:
        session_id = args.get("session_id")
        try:
            rows = await ledger.running(project_id=project_id, provider=provider)
        except Exception:  # noqa: BLE001 — the routine ran; filing it is reported, never raised
            logger.exception("%s sim run not filed project=%s", provider, project_id)
            return {**result, "run": None, "sim_result_id": None, "run_reason": NOT_FILED}
        session = next((r for r in rows if r.session_id == session_id), None)
        try:
            read = reader(args, result, session=session)
        except (ValidationError, ValueError, TypeError):
            logger.warning("%s routine readback not understood project=%s", provider, project_id)
            return {**result, "run": None, "sim_result_id": None, "run_reason": UNREADABLE}
        try:
            outcome = await record_sim_run(
                sessions,
                hub,
                store,
                project_id=project_id,
                provider=provider,
                family=read.family,
                version=read.version,
                model_entity_id=(
                    uuid.UUID(str(model_entity_id)) if model_entity_id is not None else None
                ),
                scene_ref=session.scene_ref if session else None,
                routine_args={k: v for k, v in args.items() if k not in _NOT_INPUTS},
                samples=read.samples,
                created_by=user_id,
            )
        except Exception:  # noqa: BLE001 — the routine ran; filing it is reported, never raised
            logger.exception("%s sim run not filed project=%s", provider, project_id)
            return {**result, "run": None, "sim_result_id": None, "run_reason": NOT_FILED}
        return {
            **result,
            "run": str(outcome.run_id) if outcome.run_id else None,
            "sim_result_id": str(outcome.sim_result_id) if outcome.sim_result_id else None,
            "run_reason": outcome.reason,
        }

    return record
