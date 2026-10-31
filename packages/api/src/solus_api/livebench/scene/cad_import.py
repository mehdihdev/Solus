"""Explicit static CAD imports from scoped graph observations and normal sync exports.

A CAD import's scene model is static (`joints: []`): the graph holds no mate frame. Beside it rides
the bounded twin (`twin_of`, SOLUSDEV-321 P4-T4): the moving mates as candidate joints with their
axis unknown, the robot's bus map as the actuated set, definition limits, sensor sites, and what
it cannot state (the mate frame, the masses). It names no CAD vendor.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import ValidationError
from solus_api.core.errors import APIError
from solus_api.graph.edges import write_edge
from solus_api.hardware.config import BusMapEntry
from solus_api.hardware.library import DefinitionError, Library, PartDefinition, load_library
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.livebench.scene.part_bindings import finite_number
from solus_api.models import Domain, GraphEdge, GraphEntity, SolusSection
from solus_api.services.artifacts import create_artifact
from solus_api.services.solus_config import add_artifact_entry
from solus_api.simulation.providers.deterministic_robot import MATE_FRAME
from solus_contracts.relations import CANDIDATE_THRESHOLD, EdgeOrigin, RelationType
from sqlalchemy import func, or_, select

from .service import KIND, SceneService, digest

IMPORT_KIND = "bench_scene_cad_import"
STATIC_REASON = "CAD contains no verified motion-joint definitions; this model is static."


def rigid_matrix(value: Any) -> list[float]:
    if not isinstance(value, dict) or value.get("length_unit") != "mm":
        raise ValueError("CAD transform evidence is unavailable")
    matrix = value.get("matrix")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 16
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or abs(v) > 1e9
            for v in matrix
        )
        or matrix[12:] != [0, 0, 0, 1]
    ):
        raise ValueError("CAD transform is invalid")
    for row in range(3):
        for other in range(3):
            dot = sum(matrix[row * 4 + c] * matrix[other * 4 + c] for c in range(3))
            if abs(dot - (1 if row == other else 0)) > 1e-6:
                raise ValueError("CAD transform is not rigid")
    a, b, c, _, d, e, f, _, g, h, i, *_ = matrix
    if abs(a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g) - 1) > 1e-6:
        raise ValueError("CAD transform reflects geometry")
    return [float(v) for v in matrix]


def compose(parent: list[float], child: list[float]) -> list[float]:
    return [
        sum(parent[r * 4 + k] * child[k * 4 + c] for k in range(4))
        for r in range(4)
        for c in range(4)
    ]


def transform_mesh(mesh: dict[str, Any], matrix: list[float]) -> dict[str, Any]:
    vertices = mesh["vertices"]
    result: list[float] = []
    for index in range(0, len(vertices), 3):
        point = vertices[index : index + 3]
        result.extend(
            sum(matrix[r * 4 + c] * point[c] for c in range(3)) + matrix[r * 4 + 3] / 1000
            for r in range(3)
        )
    if any(not math.isfinite(value) or abs(value) > 1e6 for value in result):
        raise ValueError("CAD placed geometry exceeds coordinate limits")
    return {"vertices": result}


async def children(service: SceneService, parent: GraphEntity) -> list[GraphEntity]:
    edges = list(
        await service.session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == service.project_id,
                GraphEdge.dst_id == parent.id,
                GraphEdge.relation_type == "part_of",
                GraphEdge.deleted_at.is_(None),
            )
            .limit(513)
        )
    )
    if not edges:
        raise ValueError("CAD assembly has no visible descendants")
    result = []
    for edge in edges:
        child = await service.entity(edge.src_id)
        if not (child.external_ref or "").startswith(f"{parent.external_ref}/"):
            raise ValueError("CAD occurrence hierarchy does not match source evidence")
        parents = list(
            await service.session.scalars(
                select(GraphEdge.id)
                .where(
                    GraphEdge.project_id == service.project_id,
                    GraphEdge.src_id == child.id,
                    GraphEdge.relation_type == "part_of",
                    GraphEdge.deleted_at.is_(None),
                )
                .limit(2)
            )
        )
        if len(parents) != 1:
            raise ValueError("CAD occurrence has ambiguous parents")
        result.append(child)
    return result


def validate_root(root: GraphEntity, revision: str) -> None:
    if root.attrs.get("observed_microversion") != revision:
        raise APIError(409, "source_changed", "CAD revision changed; choose the current source.")
    if root.source_id is None or root.kind != "part" or root.domain != Domain.MECHANICAL:
        raise APIError(422, "invalid_cad_source", "Choose a synced CAD source.")


async def selection(
    service: SceneService, identity: uuid.UUID, revision: str
) -> tuple[GraphEntity, list[tuple[GraphEntity, list[float]]]]:
    from .cad_refresh import eligible

    root = await service.entity(identity)
    validate_root(root, revision)
    leaves = []
    seen: set[uuid.UUID] = set()

    async def walk(node: GraphEntity, parent: list[float] | None) -> None:
        if node.id in seen or len(seen) >= 512:
            raise ValueError("CAD occurrence hierarchy is cyclic or too large")
        seen.add(node.id)
        if node.source_id != root.source_id or any(
            node.attrs.get(key) != root.attrs.get(key)
            for key in ("document_id", "element_id", "observed_microversion")
        ):
            raise ValueError("CAD occurrence belongs to a different revision")
        matrix = rigid_matrix(node.attrs.get("parent_transform"))
        if parent is not None:
            matrix = compose(parent, matrix)
        if node.attrs.get("is_assembly") is False:
            await eligible(service, node.id)
            leaves.append((node, matrix))
            if len(leaves) > 128:
                raise ValueError("CAD import exceeds 128 leaves")
            return
        if node.attrs.get("is_assembly") is not True:
            raise ValueError("CAD occurrence type is unavailable")
        for child in await children(service, node):
            await walk(child, matrix)

    try:
        await walk(root, None)
    except ValueError as error:
        raise APIError(422, "invalid_cad_source", str(error)) from None
    return root, leaves


async def propose(
    service: SceneService, robot_id: uuid.UUID, source_id: uuid.UUID, revision: str
) -> GraphEntity:
    await service.lock()
    await service.entity(robot_id, "physical_robot")
    root, _ = await selection(service, source_id, revision)
    rows = await service.session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == service.project_id,
            GraphEntity.kind == IMPORT_KIND,
            GraphEntity.origin == "manual",
            GraphEntity.source_id.is_(None),
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["status"].as_string() == "pending",
        )
        .limit(32)
    )
    pending = list(rows)
    for row in pending:
        if all(
            row.attrs.get(k) == v
            for k, v in {
                "robot_id": str(robot_id),
                "source_entity_id": str(source_id),
                "expected_revision": revision,
            }.items()
        ):
            return row
    if len(pending) >= 32:
        raise APIError(409, "scene_queue_full", "Wait for pending CAD imports to complete.")
    if len(await service.all()) >= 32:
        raise APIError(409, "scene_full", "The scene supports at most 32 models.")
    row = GraphEntity(
        project_id=service.project_id,
        domain=Domain.SIMULATION,
        kind=IMPORT_KIND,
        origin="manual",
        name=f"Import {root.name}"[:120],
        attrs={
            "robot_id": str(robot_id),
            "source_entity_id": str(source_id),
            "expected_revision": revision,
            "cad_source_id": str(root.source_id),
            "created_by": str(service.user_id),
            "status": "pending",
            "reason": STATIC_REASON,
            "job_id": None,
            "model_id": None,
        },
    )
    service.session.add(row)
    await service.session.flush()
    for target in (robot_id, source_id):
        await _references(service, row.id, target)
    return row


async def _references(service: SceneService, src_id: uuid.UUID, dst_id: uuid.UUID) -> None:
    await write_edge(
        service.session,
        project_id=service.project_id,
        src_id=src_id,
        dst_id=dst_id,
        relation_type="references",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=service.user_id,
    )


def status(row: GraphEntity) -> dict[str, Any]:
    return {
        "import_id": str(row.id),
        **{key: row.attrs.get(key) for key in ("status", "reason", "job_id", "model_id")},
    }


#: The moving CAD mate types (`mates_with` `attrs.mate_type`, any case) and the joint each could be.
MOVING_MATES: Final = {"REVOLUTE": "revolute", "SLIDER": "prismatic"}
#: The most candidate joints, and the most sensor sites, one twin lists.
MAX_CANDIDATES: Final = 128
UNKNOWN: Final = "unknown"
#: What every twin lacks: a cached mass property is never read through a live call (M138).
MASS: Final = FactNeed(
    name="mass",
    set_in="each link's mass properties as the CAD connector caches them; none are read yet",
)
MATE_FRAME_WARNING: Final = (
    "Moving CAD mates are listed as candidate joints without their mate frame (axis, origin); "
    "the model stays static."
)
MASS_WARNING: Final = "Link masses are unknown: no cached CAD mass properties are read."
BUS_WARNING: Final = "The robot's bus map did not resolve, so no joint is marked actuated."
LIBRARY_WARNING: Final = "The part library does not load, so no joint limits are read."


async def twin_of(
    service: SceneService,
    leaves: Sequence[tuple[GraphEntity, list[float]]],
    robot_id: uuid.UUID,
    *,
    library: Library | None = None,
) -> dict[str, Any]:
    """The bounded twin of an import's placed leaves (docs/api/simulation.md §9; R92, R113): what
    the graph says about how they move and what they carry, and what it cannot say, named. It only
    reads: the scene model `materialize` writes carries it.

    - `candidate_joints`: each revolute or slider `mates_with` between two leaves, its axis and
      origin unknown (the mate frame is not in the graph), at most `MAX_CANDIDATES`;
    - `actuated`: the robot's bus map. A candidate is actuated when either part is on it, and its
      `limits` are then that part's definition limits, whose unit no definition states;
    - `sensor_sites`: each `mounts` edge from a leaf, at the position it carries, else unknown;
    - `masses`: none, and `missing` and `warnings` say so. Candidate edges are proposals, never
      facts, and are skipped. `library` defaults to the curated part library."""
    entities = {leaf.id: leaf for leaf, _ in leaves}
    warnings: list[str] = []
    bus = await _bus_map(service, robot_id, warnings)
    by_part = {entry.part_entity_id: entry for entry in bus if entry.part_entity_id is not None}
    parts = _part_definitions(library, warnings) if by_part else {}
    joints = await _candidate_joints(service, entities, by_part, parts, warnings)
    warnings.append(MASS_WARNING)
    lacking = ((MATE_FRAME,) if joints else ()) + (MASS,)
    return {
        "candidate_joints": joints,
        "actuated": [_actuator(entry) for entry in bus],
        "sensor_sites": await _sensor_sites(service, {leaf.id: m for leaf, m in leaves}),
        "masses": {},
        "missing": [need.model_dump() for need in lacking],
        "warnings": warnings,
    }


async def _bus_map(
    service: SceneService, robot_id: uuid.UUID, warnings: list[str]
) -> list[BusMapEntry]:
    """The robot's bus-mapped parts, in bus order; none, with a warning, when its config does not
    resolve."""
    try:
        config = await resolve_runtime_config(service.session, service.project_id, robot_id)
    except (APIError, ValidationError):
        warnings.append(BUS_WARNING)
        return []
    return [entry for entry in config.bus_map if entry.part_entity_id is not None]


def _part_definitions(library: Library | None, warnings: list[str]) -> Mapping[str, PartDefinition]:
    try:
        return (library if library is not None else load_library()).parts
    except DefinitionError:
        warnings.append(LIBRARY_WARNING)
        return {}


def _fact_edges() -> Any:
    """A live edge that is a fact: an inferred edge below the candidate threshold is a proposal."""
    return or_(
        GraphEdge.origin != EdgeOrigin.INFERRED.value,
        GraphEdge.confidence >= CANDIDATE_THRESHOLD,
    )


async def _candidate_joints(
    service: SceneService,
    entities: Mapping[uuid.UUID, GraphEntity],
    bus: Mapping[uuid.UUID, BusMapEntry],
    parts: Mapping[str, PartDefinition],
    warnings: list[str],
) -> list[dict[str, Any]]:
    ids = list(entities)
    rows = list(
        await service.session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == service.project_id,
                GraphEdge.relation_type == RelationType.MATES_WITH.value,
                GraphEdge.deleted_at.is_(None),
                GraphEdge.src_id.in_(ids),
                GraphEdge.dst_id.in_(ids),
                func.upper(GraphEdge.attrs["mate_type"].as_string()).in_(list(MOVING_MATES)),
                _fact_edges(),
            )
            .order_by(GraphEdge.attrs["feature_id"].as_string(), GraphEdge.id)
            .limit(MAX_CANDIDATES + 1)
        )
    )
    if len(rows) > MAX_CANDIDATES:
        warnings.append(f"Only the first {MAX_CANDIDATES} moving CAD mates are listed.")
    if rows:
        warnings.append(MATE_FRAME_WARNING)
    return [_candidate(edge, entities, bus, parts) for edge in rows[:MAX_CANDIDATES]]


def _candidate(
    edge: GraphEdge,
    entities: Mapping[uuid.UUID, GraphEntity],
    bus: Mapping[uuid.UUID, BusMapEntry],
    parts: Mapping[str, PartDefinition],
) -> dict[str, Any]:
    feature = edge.attrs.get("feature_id")
    named = feature[:64] if isinstance(feature, str) and feature else None
    driver = next((part for part in (edge.dst_id, edge.src_id) if part in bus), None)
    return {
        "name": named or f"mate-{edge.id.hex[:12]}",
        "type": MOVING_MATES[str(edge.attrs.get("mate_type")).upper()],
        "parent": str(edge.src_id),
        "child": str(edge.dst_id),
        "axis": UNKNOWN,
        "origin": UNKNOWN,
        "mate_feature_id": named,
        "actuated": driver is not None,
        "actuator": _actuator(bus[driver]) if driver is not None else None,
        "limits": _definition_limits(entities[driver], parts) if driver is not None else None,
    }


def _actuator(entry: BusMapEntry) -> dict[str, Any]:
    return {
        "part_entity_id": str(entry.part_entity_id),
        "protocol": entry.protocol,
        "address": entry.address,
    }


def _definition_limits(
    entity: GraphEntity, parts: Mapping[str, PartDefinition]
) -> dict[str, Any] | None:
    """The actuating part's definition position limits, as stated. A definition states no unit, so
    they never become a joint's `lower`/`upper` (radians or metres)."""
    did = entity.attrs.get("definition_id")
    definition = parts.get(did) if isinstance(did, str) else None
    limits = definition.limits if definition is not None else None
    if limits is None or limits.position_min is None or limits.position_max is None:
        return None
    return {
        "lower": limits.position_min,
        "upper": limits.position_max,
        "unit": None,
        "source": "definition",
    }


async def _sensor_sites(
    service: SceneService, placed: Mapping[uuid.UUID, list[float]]
) -> list[dict[str, Any]]:
    rows = await service.session.scalars(
        select(GraphEdge)
        .where(
            GraphEdge.project_id == service.project_id,
            GraphEdge.relation_type == RelationType.MOUNTS.value,
            GraphEdge.deleted_at.is_(None),
            GraphEdge.src_id.in_(list(placed)),
            _fact_edges(),
        )
        .order_by(GraphEdge.created_at, GraphEdge.id)
        .limit(MAX_CANDIDATES)
    )
    return [_sensor_site(edge, placed[edge.src_id]) for edge in rows]


def _sensor_site(edge: GraphEdge, matrix: list[float]) -> dict[str, Any]:
    """Where a `mounts` edge puts its device: `attrs.position_m` (metres, in the structure's own
    frame) placed by the structure's transform, or unknown when the edge carries no position."""
    raw = edge.attrs.get("position_m")
    point = [finite_number(v) for v in raw] if isinstance(raw, list) and len(raw) == 3 else []
    xyz: Any = UNKNOWN
    if len(point) == 3 and None not in point:
        try:
            xyz = transform_mesh({"vertices": point}, matrix)["vertices"]
        except ValueError:  # placed past the coordinate bound: no site is stated
            xyz = UNKNOWN
    return {"device_entity_id": str(edge.dst_id), "link": str(edge.src_id), "xyz": xyz}


async def materialize(
    service: SceneService,
    row: GraphEntity,
    exports: dict[tuple[str, str], tuple[str, str]],
    store: Any,
) -> None:
    from solus_api.connectors.step_tessellation import MAX_BYTES, MAX_TRIANGLES, tessellate_isolated

    from .cad_refresh import target_of

    root, leaves = await selection(
        service, uuid.UUID(row.attrs["source_entity_id"]), row.attrs["expected_revision"]
    )
    document, element, revision, _ = target_of(leaves[0][0])
    export = exports.get((document, element))
    if export is None or export[0] != revision:
        raise ValueError("Exact CAD export is unavailable")
    local = await tessellate_isolated(export[1], [target_of(leaf)[3] for leaf, _ in leaves])
    # Share the sync lock: no revision may commit between recheck and geometry commit.
    await service.session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"sync:{root.source_id}", 0)))
    )
    await service.lock()
    await service.session.refresh(row)
    if row.attrs.get("status") != "pending":
        return
    root, leaves = await selection(service, root.id, revision)
    await service.entity(uuid.UUID(row.attrs["robot_id"]), "physical_robot")
    if len(await service.all()) >= 32:
        raise ValueError("Scene already has 32 models")
    meshes, links, bindings = {}, [], []
    for leaf, matrix in leaves:
        key = digest(str(leaf.id))
        meshes[key] = transform_mesh(local[target_of(leaf)[3]], matrix)
        links.append(
            {
                "name": str(leaf.id),
                "visuals": [
                    {
                        "kind": "mesh",
                        "size": [],
                        "mesh_key": key,
                        "scale": [1, 1, 1],
                        "xyz": [0, 0, 0],
                        "rpy": [0, 0, 0],
                        "reference": str(leaf.id),
                    }
                ],
            }
        )
        bindings.append(
            {"mesh_key": key, "source_entity_id": str(leaf.id), "observed_microversion": revision}
        )
    # R92: the twin rides this model. `joints` stays empty: no mate frame is in the graph.
    twin = await twin_of(service, leaves, uuid.UUID(row.attrs["robot_id"]))
    normalized = {
        "links": links,
        "joints": [],
        "meshes": meshes,
        **twin,
        "warnings": [STATIC_REASON, *twin["warnings"]],
    }
    data = json.dumps(normalized, allow_nan=False).encode()
    if (
        len(data) > MAX_BYTES
        or sum(len(m["vertices"]) for m in meshes.values()) > MAX_TRIANGLES * 9
    ):
        raise ValueError("CAD scene geometry exceeds limits")
    artifact = await create_artifact(
        service.session,
        store,
        project_id=service.project_id,
        created_by=service.user_id,
        data=data,
        media_type="application/json",
        source_tool="bench.cad_import",
        tool_call_id=None,
    )
    entry = await add_artifact_entry(
        service.session,
        service.project_id,
        SolusSection.DOCUMENTATION,
        subsection="guides",
        artifact_id=artifact.id,
        name=f"{root.name} CAD geometry"[:120],
        created_by=service.user_id,
    )
    entity = GraphEntity(
        project_id=service.project_id,
        domain=Domain.SIMULATION,
        kind=KIND,
        origin="manual",
        name=root.name[:120],
        attrs={
            "robot_id": row.attrs["robot_id"],
            "artifact_id": str(artifact.id),
            "source_entity_id": str(root.id),
            "source_revision": revision,
            "source_digest": digest([root.version, root.attrs]),
            "model": normalized,
            "bindings": [],
            "config_digest": None,
            "cad_bindings": bindings,
            "cad_source_id": str(root.source_id),
            "cad_bound_by": str(service.user_id),
            "cad_static_import": True,
            "refresh_status": "current",
            "refresh_error": None,
        },
    )
    service.session.add(entity)
    await service.session.flush()
    for target in {root.id, uuid.UUID(row.attrs["robot_id"]), entry.entity_id}:
        if target is not None:  # attached by add_artifact_entry
            await _references(service, entity.id, target)
    row.attrs = {**row.attrs, "status": "complete", "model_id": str(entity.id)}
    row.version += 1
