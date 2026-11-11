"""SOLUSDEV-322 P6-T2 — the generation job: a CAD import becomes a simulation model, honestly.

`run_generate_sim_model(ctx, request)` is the ARQ job (`connectors/worker.py`: `timeout=300`,
`max_tries=1`, `keep_result=0`) that `sim.generate_model` (`agent/tools/sim_generate.py`) enqueues
after the person approved its card, and that a CAD refresh re-enqueues for a model whose
`cad_microversion` moved on (`scene/cad_refresh.complete`). It only reads the graph and the scene:

1. `gather` — the robot's static CAD import (`bench_scene_model`), its placed leaves and the bounded
   twin (`scene/cad_import.twin_of`): the moving mates with their placed mate frames, the bus map,
   each moving part's limits (its hardware config, then its definition), the cached masses and the
   sensor sites;
2. `gap_report` — `{"properties": [{name, value, unit, source}], "gaps": [{name, set_in}]}`.
   Sources: `mate_frame`, `cad_mass` (the connector's cached mass properties), `mesh_mass` (a
   material density over a closed mesh), `user_config`, `definition`, `bus_map`, `mounts`. A gap
   names where to set the missing fact. The tool's preview shows exactly these rows;
3. the model — a mate becomes a MOVING joint only when its frame AND its limits are known; any other
   mate, and any part no mate moves, is a fixed attachment that keeps the CAD placement
   (`urdf_writer`). URDF, binary STL per link and, when the physics engine builds it, the compiled
   scene XML (`mjcf_compile`) land in the artifact store, retained, under a sha256 manifest;
4. the graph — one `joint` entity per moving joint (upserted by a stable reference, attrs
   REASSIGNED), then a `simulation_model` v2 through `SimulationModelService.create` with
   `origin="system"`, whose `contains` edges bind every part and joint. The same definition again
   is the same model (`status: "reused"`); a changed one is a new model beside the old.

Nothing is invented: no default mass, limit or frame. When no mate can move, the job refuses and
the report says why. It names no CAD vendor and no simulator.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.isaac_models import (
    Asset,
    Binding,
    EntityId,
    Joint,
    SimulationModel,
)
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.hardware.config import PartLimits
from solus_api.hardware.library import DefinitionError, PartDefinition, load_library
from solus_api.hardware.store import read_entity_config
from solus_api.livebench.scene.cad_import import UNKNOWN, selection, twin_of
from solus_api.livebench.scene.service import KIND as SCENE_KIND
from solus_api.livebench.scene.service import SceneService, digest
from solus_api.models import Domain, GraphEntity, Project, User
from solus_api.services.artifacts import create_artifact
from solus_api.services.events import emit_event
from solus_api.services.simulation_models import SimulationModelCreate, SimulationModelService
from solus_api.services.solus_graph import lock_project
from solus_api.simulation.mjcf_compile import MjcfCompileError, compile_mjcf
from solus_api.simulation.providers.deterministic_mech import material_with, solid_of, surface_of
from solus_api.simulation.urdf_writer import (
    GeneratedJoint,
    GeneratedLink,
    GeneratedModel,
    Inertial,
    stl_bytes,
    uniform_inertia,
    write_urdf,
)

logger = logging.getLogger("solus.simulation.model_job")

JOB: Final = "run_generate_sim_model"
EVENT: Final = "sim.model_generated"
URDF_PATH: Final = "model.urdf"
#: A link's STL path fits `mjcf_compile`'s 64-character component bound with its suffix.
_NAME_CHARS: Final = 56
MovingType = Literal["revolute", "prismatic"]
#: Enqueues one job: (job name, project id, request) → the job's id.
Enqueue = Callable[[str, str, dict[str, Any]], Awaitable[str]]
#: Where a gap is set, by what the report lacks.
FRAME_GAP: Final = (
    "the mate connector frame (attrs.mate_frame) on the mates_with edge, which the CAD connector "
    "reads from the mate's connector frame"
)
MASS_GAP: Final = (
    "the part's cached mass properties (attrs.mass_properties.mass_kg) or its material density "
    "(attrs.material.density_kg_m3) over a closed mesh; until set, the URDF gives a root or moving "
    "link a placeholder mass (the heaviest known link's, else 1 g) so the engines keep it"
)
LIMITS_GAP: Final = (
    "the moving part's hardware config limits (position_min_<unit>, position_max_<unit>) or its "
    "definition's position limits with a telemetry unit"
)
SITE_GAP: Final = "the mounts edge's attrs.position_m (metres, in the structure's frame)"
MJCF_GAP: Final = "the physics engine could not build the URDF; the URDF and meshes are stored"
#: Unit → divisor into the joint's own unit (radians, metres).
_UNITS: Final[dict[str, dict[str, float]]] = {
    "revolute": {"rad": 1.0, "deg": 180.0 / math.pi},
    "prismatic": {"m": 1.0, "mm": 1000.0, "cm": 100.0},
}
_JOINT_UNIT: Final = {"revolute": "rad", "prismatic": "m"}


class GenerateModelRequest(BaseModel):
    """The job's argument, as the tool enqueues it and the refresh hook re-enqueues it."""

    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: EntityId
    robot_id: EntityId
    name: Annotated[str, Field(min_length=1, max_length=120)]
    requested_by: EntityId
    source_entity_id: EntityId | None = None

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model name must not be blank")
        return value


class GenerateRefusedError(Exception):
    """Nothing can be generated from this graph; the message is Solus-composed."""


@dataclass(frozen=True)
class LinkFacts:
    entity: GraphEntity
    name: str
    mesh: list[float] | None
    mass: tuple[float, str] | None  # (kg, source)


@dataclass(frozen=True)
class JointFacts:
    name: str
    type: MovingType
    parent: uuid.UUID
    child: uuid.UUID
    feature_id: str | None
    frame: tuple[list[float], list[float]] | None  # (axis, origin_m), placed
    actuator: dict[str, Any] | None  # {part_entity_id, protocol, address}: the child on the bus
    limits: tuple[float, float, str] | None  # (lower, upper, source)
    skipped: str | None = None  # the tree refused it

    @property
    def moving(self) -> bool:
        return self.frame is not None and self.limits is not None and self.skipped is None


@dataclass(frozen=True)
class Gathered:
    request: GenerateModelRequest
    scene: GraphEntity
    revision: str
    links: tuple[LinkFacts, ...]
    joints: tuple[JointFacts, ...]
    sensor_sites: tuple[dict[str, Any], ...]

    @property
    def project_id(self) -> uuid.UUID:
        return uuid.UUID(self.request.project_id)


# ----------------------------------------------------------------------------------- gather


def _binding_name(text: str, taken: set[str], fallback: str) -> str:
    """A binding name (`isaac_models.Name`) and STL stem from a part's or mate's name: plain word
    characters, unique within the model."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", text)[:_NAME_CHARS].strip("_") or fallback
    if not re.match(r"[A-Za-z_]", base):
        base = f"_{base}"
    name, count = base, 1
    while name in taken:
        count += 1
        name = f"{base}_{count}"
    taken.add(name)
    return name


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def _link_mass(entity: GraphEntity, mesh: list[float] | None) -> tuple[float, str] | None:
    """The connector's cached mass, else a material density over the closed mesh, else nothing."""
    cached = entity.attrs.get("mass_properties")
    mass = _positive_number(cached.get("mass_kg")) if isinstance(cached, Mapping) else None
    if mass is not None:
        return mass, "cad_mass"
    material = material_with("density_kg_m3")(entity.attrs)
    triangles = surface_of({"vertices": mesh}) if material and mesh else None
    solid = solid_of(triangles) if triangles is not None else None
    if solid is None or material is None:
        return None
    return float(material["density_kg_m3"]) * solid.volume_m3, "mesh_mass"


def _ordered_pair(lower: object, upper: object, divisor: float) -> tuple[float, float] | None:
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (lower, upper)):
        return None
    low, high = float(lower) / divisor, float(upper) / divisor  # type: ignore[arg-type]
    return (low, high) if math.isfinite(low) and math.isfinite(high) and low < high else None


def joint_limits(
    joint_type: MovingType, config: PartLimits | None, definition: PartDefinition | None
) -> tuple[float, float, str] | None:
    """The joint's travel in its own unit (radians or metres) and where it came from: the moving
    part's hardware config (`position_min_<unit>`/`position_max_<unit>`), then its definition's
    position limits in the unit its position telemetry states; None when neither states an
    ordered pair in a unit this joint reads. A measured range is not read (nothing stores one)."""
    scales = _UNITS[joint_type]
    values = config.values if config is not None else {}
    for unit, divisor in scales.items():
        pair = _ordered_pair(
            values.get(f"position_min_{unit}"), values.get(f"position_max_{unit}"), divisor
        )
        if pair is not None:
            return (*pair, "user_config")
    limits = definition.limits if definition is not None else None
    if definition is None or limits is None:
        return None
    stated = next((t.unit for t in definition.telemetry if t.quantity == "position"), None)
    if stated is None or stated not in scales:
        return None
    pair = _ordered_pair(limits.position_min, limits.position_max, scales[stated])
    return (*pair, "definition") if pair is not None else None


async def _cad_scene(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID, source_id: str | None
) -> GraphEntity:
    """The robot's newest static CAD import, or the one over `source_id`."""
    stmt = select(GraphEntity).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind == SCENE_KIND,
        GraphEntity.origin == "manual",
        GraphEntity.deleted_at.is_(None),
        GraphEntity.attrs["robot_id"].as_string() == str(robot_id),
        GraphEntity.attrs["cad_static_import"].as_boolean().is_(True),
    )
    if source_id is not None:
        stmt = stmt.where(GraphEntity.attrs["source_entity_id"].as_string() == source_id)
    scene = await session.scalar(stmt.order_by(GraphEntity.id.desc()).limit(1))
    if scene is None:
        raise GenerateRefusedError("No CAD import exists for this robot; import its CAD first.")
    return scene


def _library_parts() -> Mapping[str, PartDefinition]:
    try:
        return load_library().parts
    except DefinitionError:
        logger.warning("part library does not load: no definition limits are read")
        return {}


async def _configured_limits(
    session: AsyncSession, project_id: uuid.UUID, part: uuid.UUID
) -> PartLimits | None:
    try:
        _, config = await read_entity_config(session, project_id, part)
    except APIError as exc:  # a config in conflict states nothing
        logger.warning("hardware config unreadable part=%s code=%s", part, exc.code)
        return None
    component = config.component if config is not None else None
    return component.limits if component is not None else None


async def _joint_facts(
    session: AsyncSession,
    candidate: Mapping[str, Any],
    links: Mapping[uuid.UUID, LinkFacts],
    by_bus: Mapping[str, dict[str, Any]],
    parts: Mapping[str, PartDefinition],
    taken: set[str],
) -> JointFacts:
    parent, child = uuid.UUID(candidate["parent"]), uuid.UUID(candidate["child"])
    child_entity = links[child].entity
    definition_id = child_entity.attrs.get("definition_id")
    joint_type: MovingType = candidate["type"]
    limits = joint_limits(
        joint_type,
        await _configured_limits(session, child_entity.project_id, child),
        parts.get(definition_id) if isinstance(definition_id, str) else None,
    )
    axis, origin = candidate["axis"], candidate["origin"]
    return JointFacts(
        name=_binding_name(str(candidate["name"]), taken, "mate"),
        type=joint_type,
        parent=parent,
        child=child,
        feature_id=candidate.get("mate_feature_id"),
        frame=(axis, origin) if axis != UNKNOWN and origin != UNKNOWN else None,
        actuator=by_bus.get(str(child)),
        limits=limits,
    )


def _mate_tree(joints: Sequence[JointFacts]) -> tuple[JointFacts, ...]:
    """One parent per child and no cycle: a later mate that breaks either is skipped, named."""
    parent_of: dict[uuid.UUID, uuid.UUID] = {}
    result = []
    for joint in joints:
        if joint.child in parent_of:
            result.append(replace(joint, skipped="its child is already attached by another mate"))
            continue
        ancestor, seen = joint.parent, {joint.child}
        while ancestor in parent_of and ancestor not in seen:
            seen.add(ancestor)
            ancestor = parent_of[ancestor]
        if ancestor == joint.child:
            result.append(replace(joint, skipped="it would close a loop of mates"))
            continue
        parent_of[joint.child] = joint.parent
        result.append(joint)
    return tuple(result)


async def gather(session: AsyncSession, request: GenerateModelRequest) -> Gathered:
    """Everything the model needs, read from the graph and the scene (module docstring).
    `GenerateRefusedError` when the robot has no CAD import; `APIError` when the CAD moved on since
    the scene's revision (a refresh must land first)."""
    project_id, robot_id = uuid.UUID(request.project_id), uuid.UUID(request.robot_id)
    service = SceneService(session, project_id, uuid.UUID(request.requested_by))
    scene = await _cad_scene(session, project_id, robot_id, request.source_entity_id)
    revision = str(scene.attrs.get("source_revision") or "")
    _, leaves = await selection(service, uuid.UUID(scene.attrs["source_entity_id"]), revision)
    twin = await twin_of(service, leaves, robot_id)
    meshes = scene.attrs.get("model", {}).get("meshes", {})
    taken: set[str] = set()
    links: dict[uuid.UUID, LinkFacts] = {}
    for leaf, _ in leaves:
        stored = meshes.get(digest(str(leaf.id)))
        mesh = stored.get("vertices") if isinstance(stored, Mapping) else None
        mesh = mesh if isinstance(mesh, list) and mesh else None
        name = _binding_name(leaf.name, taken, "link")
        links[leaf.id] = LinkFacts(leaf, name, mesh, _link_mass(leaf, mesh))
    by_bus = {entry["part_entity_id"]: entry for entry in twin["actuated"]}
    parts = _library_parts()
    joints = [
        await _joint_facts(session, candidate, links, by_bus, parts, taken)
        for candidate in twin["candidate_joints"]
    ]
    return Gathered(
        request=request,
        scene=scene,
        revision=revision,
        links=tuple(links.values()),
        joints=_mate_tree(joints),
        sensor_sites=tuple(twin["sensor_sites"]),
    )


# ------------------------------------------------------------------------------- gap report


def _fact_row(name: str, value: Any, unit: str | None, source: str) -> dict[str, Any]:
    return {"name": name, "value": value, "unit": unit, "source": source}


def _gap_row(name: str, set_in: str) -> dict[str, str]:
    return {"name": name, "set_in": set_in}


def _joint_rows(
    joint: JointFacts, properties: list[dict[str, Any]], gaps: list[dict[str, str]]
) -> None:
    if joint.frame is not None:
        value = {"axis": joint.frame[0], "origin_m": joint.frame[1]}
        properties.append(_fact_row(f"{joint.name}.frame", value, "m", "mate_frame"))
    else:
        gaps.append(_gap_row(f"{joint.name}.frame", FRAME_GAP))
    if joint.limits is not None:
        lower, upper, source = joint.limits
        unit = _JOINT_UNIT[joint.type]
        properties.append(_fact_row(f"{joint.name}.limits", [lower, upper], unit, source))
    else:
        gaps.append(_gap_row(f"{joint.name}.limits", LIMITS_GAP))
    if joint.actuator is not None:
        label = f"{joint.actuator['protocol']} {joint.actuator['address']}"
        properties.append(_fact_row(f"{joint.name}.actuated", label, None, "bus_map"))
    if joint.skipped is not None:
        gaps.append(_gap_row(f"{joint.name}.tree", f"the mates' tree: {joint.skipped}"))


def gap_report(gathered: Gathered) -> dict[str, Any]:
    """What the model will state and what it lacks (module docstring), in source order."""
    properties: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    for link in gathered.links:
        if link.mass is not None:
            properties.append(_fact_row(f"{link.name}.mass", link.mass[0], "kg", link.mass[1]))
        else:
            gaps.append(_gap_row(f"{link.name}.mass", MASS_GAP))
    for joint in gathered.joints:
        _joint_rows(joint, properties, gaps)
    names = {str(link.entity.id): link.name for link in gathered.links}
    for site in gathered.sensor_sites:
        name = f"{names.get(str(site['link']), 'link')}.sensor_site"
        if site["xyz"] == UNKNOWN:
            gaps.append(_gap_row(name, SITE_GAP))
        else:
            properties.append(_fact_row(name, site["xyz"], "m", "mounts"))
    return {"properties": properties, "gaps": gaps}


# ------------------------------------------------------------------------------------ model


def _link_inertial(link: LinkFacts) -> Inertial | None:
    if link.mass is None or link.mesh is None:
        return None
    return uniform_inertia(link.mesh, link.mass[0])


def _generated_joint(joint: JointFacts, parent: str, child: str) -> GeneratedJoint:
    if joint.moving and joint.frame is not None and joint.limits is not None:
        (axis, origin), (lower, upper, _) = joint.frame, joint.limits
        return GeneratedJoint(
            joint.name,
            joint.type,
            parent,
            child,
            (axis[0], axis[1], axis[2]),
            (origin[0], origin[1], origin[2]),
            lower,
            upper,
        )
    return GeneratedJoint(joint.name, "fixed", parent, child)


def _generated_model(gathered: Gathered) -> GeneratedModel:
    """The URDF's links and joints: moving joints as found, every other mate and every floating
    part fixed where CAD placed it."""
    names = {link.entity.id: link.name for link in gathered.links}
    links = tuple(
        GeneratedLink(
            link.name, f"meshes/{link.name}.stl" if link.mesh else None, _link_inertial(link)
        )
        for link in gathered.links
    )
    joints = [
        _generated_joint(joint, names[joint.parent], names[joint.child])
        for joint in gathered.joints
        if joint.skipped is None
    ]
    children = {joint.child for joint in gathered.joints if joint.skipped is None}
    roots = [link for link in gathered.links if link.entity.id not in children]
    taken = {joint.name for joint in joints}
    for floating in roots[1:]:
        name = _binding_name(f"{floating.name}_fixed", taken, "fixed")
        joints.append(GeneratedJoint(name, "fixed", roots[0].name, floating.name))
    model_name = _binding_name(gathered.request.name, set(), "model")
    return GeneratedModel(name=model_name, links=links, joints=tuple(joints))


def _asset_manifest(files: Mapping[str, bytes]) -> Asset:
    digests = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()
    return Asset(urdf_path=URDF_PATH, files=digests, sha256=hashlib.sha256(canonical).hexdigest())


def _model_definition(
    gathered: Gathered, asset: Asset, joint_ids: Mapping[str, uuid.UUID]
) -> SimulationModel:
    return SimulationModel(
        schema_version=2,
        asset=asset,
        links=[Binding(entity_id=str(link.entity.id), name=link.name) for link in gathered.links],
        joints=[
            Joint(
                entity_id=str(joint_ids[joint.name]),
                name=joint.name,
                parent_link_entity_id=str(joint.parent),
                child_link_entity_id=str(joint.child),
                lower_rad=joint.limits[0],
                upper_rad=joint.limits[1],
            )
            for joint in gathered.joints
            if joint.moving and joint.limits is not None
        ],
    )


def _joint_reference(gathered: Gathered, joint: JointFacts) -> str:
    key = f"{joint.parent}:{joint.child}:{joint.feature_id or joint.name}"
    return f"solus:sim-joint:{gathered.request.robot_id}:{key}"


def _joint_attrs(gathered: Gathered, joint: JointFacts) -> dict[str, Any]:
    frame, limits = joint.frame, joint.limits
    if frame is None or limits is None:  # pragma: no cover — only moving joints are minted
        raise ValueError("a joint entity needs its frame and limits")
    actuator = joint.actuator["part_entity_id"] if joint.actuator is not None else None
    return {
        "robot_id": gathered.request.robot_id,
        "type": joint.type,
        "unit": _JOINT_UNIT[joint.type],
        "mate_feature_id": joint.feature_id,
        "parent_part_id": str(joint.parent),
        "child_part_id": str(joint.child),
        "actuator_part_id": actuator,
        "axis": frame[0],
        "origin_m": frame[1],
        "lower": limits[0],
        "upper": limits[1],
        "limits_source": limits[2],
    }


async def _joint_entities(session: AsyncSession, gathered: Gathered) -> dict[str, uuid.UUID]:
    """One `joint` entity per moving joint, found again by its stable reference on a rerun; its
    attrs are reassigned when the facts moved."""
    ids: dict[str, uuid.UUID] = {}
    for joint in (j for j in gathered.joints if j.moving):
        reference, attrs = _joint_reference(gathered, joint), _joint_attrs(gathered, joint)
        row = await session.scalar(
            select(GraphEntity).where(
                GraphEntity.project_id == gathered.project_id,
                GraphEntity.kind == kinds.JOINT,
                GraphEntity.source_id.is_(None),
                GraphEntity.external_ref == reference,
                GraphEntity.deleted_at.is_(None),
            )
        )
        if row is None:
            row = GraphEntity(
                project_id=gathered.project_id,
                kind=kinds.JOINT,
                domain=Domain.SIMULATION,
                origin="system",
                name=joint.name,
                external_ref=reference,
                attrs=attrs,
            )
            session.add(row)
            await session.flush()
        elif row.attrs != attrs or row.name != joint.name:
            row.attrs, row.name, row.version = attrs, joint.name, row.version + 1
        ids[joint.name] = row.id
    return ids


# -------------------------------------------------------------------------------------- job


def _model_files(gathered: Gathered, model: GeneratedModel) -> dict[str, bytes]:
    files = {URDF_PATH: write_urdf(model)}
    for link in gathered.links:
        if link.mesh:
            files[f"meshes/{link.name}.stl"] = stl_bytes(link.mesh)
    return files


async def _store_file(
    session: AsyncSession, store: Any, gathered: Gathered, data: bytes, media_type: str
) -> str:
    artifact = await create_artifact(
        session,
        store,
        project_id=gathered.project_id,
        created_by=uuid.UUID(gathered.request.requested_by),
        data=data,
        media_type=media_type,
        source_tool="sim.generate_model",
        tool_call_id=None,
    )
    artifact.retained = True  # a model is kept, not a hand-off buffer
    return str(artifact.id)


async def _compiled_scene(files: Mapping[str, bytes], gaps: list[dict[str, str]]) -> bytes | None:
    meshes = {path: data for path, data in files.items() if path != URDF_PATH}
    try:
        return await asyncio.to_thread(compile_mjcf, files[URDF_PATH], meshes)
    except MjcfCompileError as exc:
        logger.warning("generated model did not compile: %s", exc)
        gaps.append(_gap_row("mjcf", MJCF_GAP))
        return None


async def _model_artifacts(
    session: AsyncSession,
    store: Any,
    gathered: Gathered,
    files: Mapping[str, bytes],
    gaps: list[dict[str, str]],
) -> dict[str, Any]:
    mjcf = await _compiled_scene(files, gaps)
    return {
        "urdf": await _store_file(session, store, gathered, files[URDF_PATH], "application/xml"),
        "mjcf": (
            await _store_file(session, store, gathered, mjcf, "application/xml") if mjcf else None
        ),
        "meshes": {
            path: await _store_file(session, store, gathered, data, "model/stl")
            for path, data in files.items()
            if path != URDF_PATH
        },
    }


def _model_attrs(gathered: Gathered, gaps: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "robot_id": gathered.request.robot_id,
        "scene_model_id": str(gathered.scene.id),
        "source_entity_id": gathered.scene.attrs.get("source_entity_id"),
        "cad_microversion": gathered.revision,
        "requested_by": gathered.request.requested_by,
        "gaps": gaps,
        "artifacts": None,
    }


async def _emit_generated(
    session: AsyncSession, gathered: Gathered, root: GraphEntity, joints: int
) -> None:
    user = await session.get(User, uuid.UUID(gathered.request.requested_by))
    project = await session.get(Project, gathered.project_id)
    if user is None or project is None:
        return
    emit_event(
        session,
        user=user,
        event_type=EVENT,
        team_id=project.team_id,
        project_id=gathered.project_id,
        payload={"model_id": str(root.id), "joints": joints, "gaps": len(root.attrs["gaps"])},
    )


async def _generate_model(session: AsyncSession, store: Any, gathered: Gathered) -> dict[str, Any]:
    gaps: list[dict[str, str]] = list(gap_report(gathered)["gaps"])
    if not any(joint.moving for joint in gathered.joints):
        raise GenerateRefusedError(
            "no mate can become a joint: every moving mate lacks its frame or its limits"
        )
    if not 2 <= len(gathered.links) <= 32:
        raise GenerateRefusedError("a model binds between 2 and 32 parts")
    files = _model_files(gathered, _generated_model(gathered))
    joint_ids = await _joint_entities(session, gathered)
    definition = _model_definition(gathered, _asset_manifest(files), joint_ids)
    body = SimulationModelCreate(name=gathered.request.name, model=definition)
    root, _, created = await SimulationModelService(session).create(
        gathered.project_id, body, origin="system", extra_attrs=_model_attrs(gathered, gaps)
    )
    if not created:
        root.attrs = {**root.attrs, "cad_microversion": gathered.revision, "gaps": gaps}
        root.version += 1
        await session.commit()
        return {"status": "reused", "model_id": str(root.id), "gaps": gaps, "reason": None}
    artifacts = await _model_artifacts(session, store, gathered, files, gaps)
    root.attrs = {**root.attrs, "artifacts": artifacts, "gaps": gaps}
    await _emit_generated(session, gathered, root, len(definition.joints))
    await session.commit()
    return {"status": "generated", "model_id": str(root.id), "gaps": gaps, "reason": None}


async def run_generate_sim_model(ctx: Mapping[str, Any], raw: object) -> dict[str, Any]:
    """The ARQ job (module docstring). Never raises: a refusal, a stale CAD revision or a failure is
    a status with a bounded, Solus-composed reason."""
    try:
        request = GenerateModelRequest.model_validate(raw)
    except ValueError:
        return {"status": "refused", "reason": "invalid generation request", "gaps": []}
    maker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    gaps: list[dict[str, str]] = []
    try:
        async with maker() as session:
            await lock_project(session, uuid.UUID(request.project_id))
            gathered = await gather(session, request)
            gaps = gap_report(gathered)["gaps"]
            return await _generate_model(session, ctx["artifact_store"], gathered)
    except (GenerateRefusedError, APIError) as exc:
        reason = exc.message if isinstance(exc, APIError) else str(exc)
        logger.info("model generation refused project=%s: %s", request.project_id, reason)
        return {"status": "refused", "reason": reason, "gaps": gaps}
    except Exception:
        logger.exception("model generation failed project=%s", request.project_id)
        return {"status": "failed", "reason": "model generation failed", "gaps": gaps}


# --------------------------------------------------------------------------- regeneration


def sim_job_id(job_name: str, project_id: str, request: Mapping[str, Any]) -> str:
    """`<job>:<project>:<sha1 of the request>`: the queue refuses an id still live, so one request
    never waits twice."""
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    short = hashlib.sha1(canonical.encode(), usedforsecurity=False).hexdigest()[:12]
    return f"{job_name}:{project_id}:{short}"


def pool_enqueue(pool: Any) -> Enqueue:
    """An `Enqueue` over one job pool (`enqueue_job(name, request, _job_id=...)`)."""

    async def enqueue(job_name: str, project_id: str, request: dict[str, Any]) -> str:
        job_id = sim_job_id(job_name, project_id, request)
        await pool.enqueue_job(job_name, request, _job_id=job_id)
        return job_id

    return enqueue


async def regeneration_requests(session: AsyncSession, scene: GraphEntity) -> list[dict[str, Any]]:
    """The requests that regenerate this scene's system models whose `cad_microversion` is no
    longer the scene's revision (`scene/cad_refresh.complete`). The old models stay."""
    rows = await session.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == scene.project_id,
            GraphEntity.kind == kinds.SIMULATION_MODEL,
            GraphEntity.origin == "system",
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["scene_model_id"].as_string() == str(scene.id),
        )
    )
    revision = scene.attrs.get("source_revision")
    requests: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row.attrs.get("cad_microversion") == revision or row.name in seen:
            continue
        seen.add(row.name)
        requests.append(
            {
                "project_id": str(scene.project_id),
                "robot_id": row.attrs.get("robot_id"),
                "name": row.name,
                "requested_by": row.attrs.get("requested_by"),
                "source_entity_id": row.attrs.get("source_entity_id"),
            }
        )
    return requests
