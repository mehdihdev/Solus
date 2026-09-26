"""Explicit static CAD imports from scoped graph observations and normal sync exports."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any

from solus_api.core.errors import APIError
from solus_api.models import Domain, GraphEdge, GraphEntity, SolusSection
from solus_api.services.artifacts import create_artifact
from solus_api.services.solus_config import add_artifact_entry
from sqlalchemy import func, select

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
        service.session.add(
            GraphEdge(
                project_id=service.project_id,
                src_id=row.id,
                dst_id=target,
                relation_type="references",
                domain_pair="simulation<->project",
                origin="manual",
            )
        )
    return row


def status(row: GraphEntity) -> dict[str, Any]:
    return {
        "import_id": str(row.id),
        **{key: row.attrs.get(key) for key in ("status", "reason", "job_id", "model_id")},
    }


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
    normalized = {"links": links, "joints": [], "meshes": meshes, "warnings": [STATIC_REASON]}
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
        SolusSection.DOCS,
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
        service.session.add(
            GraphEdge(
                project_id=service.project_id,
                src_id=entity.id,
                dst_id=target,
                relation_type="references",
                domain_pair="simulation<->project",
                origin="manual",
            )
        )
    row.attrs = {**row.attrs, "status": "complete", "model_id": str(entity.id)}
    row.version += 1
