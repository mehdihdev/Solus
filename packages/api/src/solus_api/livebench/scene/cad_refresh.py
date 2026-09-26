"""Scene geometry follows successful source acquisition, never another provider export."""

from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from solus_api.connectors.step_tessellation import MAX_BYTES, MAX_TRIANGLES, tessellate_isolated
from solus_api.core.errors import APIError
from solus_api.graph.live import graph_changed_frame
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    Domain,
    GraphEdge,
    GraphEntity,
    JobStatus,
    Project,
    SolusSection,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    utcnow,
)
from solus_api.services.artifacts import create_artifact
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_config import add_artifact_entry
from solus_api.storage import ArtifactStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .service import KIND, SceneService

_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")


def target_of(entity: GraphEntity) -> tuple[str, str, str, str]:
    attrs = entity.attrs
    document, element, revision = (
        attrs.get(key) for key in ("document_id", "element_id", "observed_microversion")
    )
    if (
        entity.kind != "part"
        or entity.domain != Domain.MECHANICAL
        or entity.source_id is None
        or attrs.get("is_assembly") is not False
        or not all(
            isinstance(value, str) and _ID.fullmatch(value)
            for value in (document, element, revision)
        )
    ):
        raise APIError(422, "invalid_cad_source", "Choose an unambiguous synced CAD leaf.")
    prefix = f"{document}:{element}:"
    ref = entity.external_ref or ""
    if not ref.startswith(prefix) or not ref[len(prefix) :] or len(ref) > 2178:
        raise APIError(422, "invalid_cad_source", "CAD occurrence identity is unavailable.")
    return str(document), str(element), str(revision), ref[len(prefix) :]


async def eligible(service: SceneService, identity: uuid.UUID) -> GraphEntity:
    entity = await service.entity(identity)
    target_of(entity)
    source = await service.session.scalar(
        select(Source).where(
            Source.id == entity.source_id,
            Source.project_id == service.project_id,
            Source.type == SourceType.ONSHAPE,
            Source.status.in_((SourceStatus.CONNECTED, SourceStatus.SYNCING)),
            Source.revision_base_source_id.is_(None),
        )
    )
    if source is None or not source.secret_ref:
        raise APIError(404, "not_found", "CAD source not found")
    from solus_api.connectors.onshape import tracked_document_ids

    if target_of(entity)[0] not in tracked_document_ids(source.config):
        raise APIError(404, "not_found", "CAD source not found")
    if source.connection_id is not None:
        account = await service.session.get(
            AccountConnection, source.connection_id, populate_existing=True
        )
        if (
            account is None
            or account.status != ConnectionStatus.CONNECTED
            or account.provider != SourceType.ONSHAPE
            or account.secret_ref != source.secret_ref
        ):
            raise APIError(404, "not_found", "CAD source not found")
    return entity


async def source_options(
    service: SceneService, *, include_assemblies: bool = False
) -> list[dict[str, str]]:
    from solus_api.graph.read_scope import resolve_scope

    scope = await resolve_scope(service.session, service.project_id, service.user_id)
    rows = await service.session.scalars(
        select(GraphEntity)
        .join(Source, GraphEntity.source_id == Source.id)
        .where(
            scope.entity_predicate(),
            GraphEntity.deleted_at.is_(None),
            GraphEntity.kind == "part",
            GraphEntity.domain == Domain.MECHANICAL,
            Source.project_id == service.project_id,
            Source.type == SourceType.ONSHAPE,
            Source.status.in_((SourceStatus.CONNECTED, SourceStatus.SYNCING)),
            Source.secret_ref.is_not(None),
        )
        .order_by(GraphEntity.name, GraphEntity.id)
        .limit(128)
    )
    result = []
    for row in rows:
        if row.attrs.get("is_assembly") is True and not include_assemblies:
            continue
        try:
            if row.attrs.get("is_assembly") is True:
                from .cad_import import selection

                revision = str(row.attrs.get("observed_microversion", ""))
                await selection(service, row.id, revision)
            else:
                await eligible(service, row.id)
                _, _, revision, _ = target_of(row)
        except APIError:
            continue
        result.append({"id": str(row.id), "name": row.name, "observed_microversion": revision})
    return result


@dataclass
class ExportCapture:
    targets: set[tuple[str, str]]
    exports: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    error: str | None = None

    def observe(self, document: str, element: str, revision: str, content: str) -> None:
        key = (document, element)
        if key not in self.targets or self.error:
            return
        previous = self.exports.get(key)
        if previous is not None and previous != (revision, content):
            self.error = "revision_changed"
            self.exports.clear()
            return
        if (
            sum(len(item[1].encode()) for target, item in self.exports.items() if target != key)
            + len(content.encode())
            > MAX_BYTES
        ):
            self.error = "geometry_too_large"
            self.exports.clear()
            return
        self.exports[key] = (revision, content)


@dataclass(frozen=True)
class ModelCapture:
    identity: uuid.UUID
    version: int
    bindings: list[dict[str, Any]]
    user_id: uuid.UUID


@dataclass
class RefreshPlan:
    source_id: uuid.UUID
    project_id: uuid.UUID
    capture: ExportCapture
    models: list[ModelCapture]
    force: bool = False
    imports: list[uuid.UUID] = field(default_factory=list)


async def prepare(session: AsyncSession, source_id: uuid.UUID) -> RefreshPlan:
    source = await session.get(Source, source_id)
    if source is None:
        raise ValueError("Source missing")
    targets: set[tuple[str, str]] = set()
    models = []
    force = False
    rows = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == source.project_id,
            GraphEntity.kind == KIND,
            GraphEntity.origin == "manual",
            GraphEntity.source_id.is_(None),
            GraphEntity.deleted_at.is_(None),
        )
        .limit(32)
    )
    for row in rows:
        bindings = row.attrs.get("cad_bindings", [])
        if not bindings or row.attrs.get("cad_source_id") != str(source_id):
            continue
        try:
            user_id = uuid.UUID(row.attrs["cad_bound_by"])
        except (ValueError, KeyError, TypeError):
            continue
        for binding in bindings:
            try:
                identity = uuid.UUID(binding["source_entity_id"])
            except (ValueError, KeyError, TypeError):
                continue
            entity = await session.scalar(
                select(GraphEntity).where(
                    GraphEntity.id == identity,
                    GraphEntity.project_id == source.project_id,
                    GraphEntity.source_id == source_id,
                    GraphEntity.deleted_at.is_(None),
                )
            )
            if entity is not None:
                try:
                    document, element, _, _ = target_of(entity)
                except APIError:
                    continue
                targets.add((document, element))
        models.append(ModelCapture(row.id, row.version, copy.deepcopy(bindings), user_id))
        force = force or row.attrs.get("refresh_status") == "queued"
    imports = await pending_imports(session, source.project_id, source_id, targets)
    return RefreshPlan(
        source_id,
        source.project_id,
        ExportCapture(targets),
        models,
        force or bool(imports),
        imports,
    )


async def pending_imports(
    session: AsyncSession,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    targets: set[tuple[str, str]],
) -> list[uuid.UUID]:
    from .cad_import import IMPORT_KIND

    imports: list[uuid.UUID] = []
    pending = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == IMPORT_KIND,
            GraphEntity.origin == "manual",
            GraphEntity.source_id.is_(None),
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["status"].as_string() == "pending",
            GraphEntity.attrs["cad_source_id"].as_string() == str(source_id),
        )
        .limit(32)
    )
    for row in pending:
        root = await session.get(GraphEntity, uuid.UUID(row.attrs["source_entity_id"]))
        if root is not None and root.source_id == source_id:
            targets.add(
                (str(root.attrs.get("document_id", "")), str(root.attrs.get("element_id", "")))
            )
            imports.append(row.id)
    return imports


async def _replacement(
    session: AsyncSession, plan: RefreshPlan, model: ModelCapture
) -> tuple[GraphEntity, dict[str, Any], list[tuple[str, str, str, str]]]:
    entity = await session.scalar(
        select(GraphEntity)
        .where(
            GraphEntity.id == model.identity,
            GraphEntity.project_id == plan.project_id,
            GraphEntity.kind == KIND,
            GraphEntity.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if (
        entity is None
        or entity.version != model.version
        or entity.attrs.get("cad_bindings") != model.bindings
    ):
        raise APIError(409, "scene_changed", "Scene changed during CAD refresh")
    resolved = []
    service = SceneService(session, plan.project_id, model.user_id)
    for binding in model.bindings:
        source_entity = await eligible(service, uuid.UUID(binding["source_entity_id"]))
        if source_entity.source_id != plan.source_id:
            raise ValueError("Source association changed")
        document, element, revision, key = target_of(source_entity)
        export = plan.capture.exports.get((document, element))
        if export is None or export[0] != revision:
            raise ValueError("CAD revision unavailable")
        resolved.append((binding["mesh_key"], document, element, key))
    return entity, copy.deepcopy(entity.attrs), resolved


async def _mesh_updates(
    session: AsyncSession, plan: RefreshPlan, model: ModelCapture
) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    _, _, resolved = await _replacement(session, plan, model)
    groups: dict[tuple[str, str], list[str]] = {}
    for _, document, element, key in resolved:
        keys = groups.setdefault((document, element), [])
        if key not in keys:
            keys.append(key)
    parsed = {}
    revisions = {}
    for target, keys in groups.items():
        revision, content = plan.capture.exports[target]
        parsed[target] = await tessellate_isolated(content, keys)
        revisions[target] = revision
    return {
        mesh_key: parsed[(document, element)][key] for mesh_key, document, element, key in resolved
    }, revisions


async def reconcile_source(
    session: AsyncSession,
    plan: RefreshPlan,
    model: ModelCapture,
    attrs: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    from .cad_import import selection, transform_mesh
    from .service import digest

    source_identity = attrs.get("source_entity_id")
    if source_identity:
        service = SceneService(session, plan.project_id, model.user_id)
        source_entity = await service.entity(uuid.UUID(source_identity))
        if source_entity.source_id != plan.source_id:
            raise ValueError("CAD source association changed")
        revision = str(source_entity.attrs.get("observed_microversion", ""))
        if attrs.get("cad_static_import"):
            _, leaves = await selection(service, source_entity.id, revision)
            transforms = {str(leaf.id): matrix for leaf, matrix in leaves}
            if set(transforms) != {b["source_entity_id"] for b in attrs["cad_bindings"]}:
                raise ValueError("CAD assembly occurrences changed; reimport required")
            for binding in attrs["cad_bindings"]:
                key = binding["mesh_key"]
                updates[key] = transform_mesh(updates[key], transforms[binding["source_entity_id"]])
        attrs["source_digest"] = digest([source_entity.version, source_entity.attrs])
        attrs["source_revision"] = revision


async def refresh_model(
    maker: async_sessionmaker[AsyncSession],
    store: ArtifactStore,
    plan: RefreshPlan,
    model: ModelCapture,
) -> None:
    async with maker() as session:
        updates, revisions = await _mesh_updates(session, plan, model)
        # Same transaction key as apply_sync_result: no source revision can commit
        # between the final graph recheck and persisted geometry.
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"sync:{plan.source_id}", 0)))
        )
        await session.scalar(
            select(Source)
            .where(Source.id == plan.source_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        await session.scalar(select(Project).where(Project.id == plan.project_id).with_for_update())
        entity, attrs, resolved = await _replacement(session, plan, model)
        # Re-read source after native parsing, under the same lock used by scene edits.
        for _, document, element, _ in resolved:
            if plan.capture.exports[(document, element)][0] != revisions[(document, element)]:
                raise ValueError("CAD revision changed")

        await reconcile_source(session, plan, model, attrs, updates)
        normalized = attrs["model"]
        normalized["meshes"].update(updates)
        for link in normalized["links"]:
            for visual in link["visuals"]:
                if visual.get("mesh_key") in updates:
                    visual["scale"] = [1, 1, 1]  # OCCT geometry is normalized to metres.
        count = sum(
            len(normalized["meshes"][visual["mesh_key"]]["vertices"])
            for link in normalized["links"]
            for visual in link["visuals"]
            if visual.get("mesh_key") in normalized["meshes"]
        )
        data = json.dumps(normalized, allow_nan=False).encode()
        if count > MAX_TRIANGLES * 9 or len(data) > MAX_BYTES:
            raise ValueError("Geometry exceeds scene limits")
        artifact = await create_artifact(
            session,
            store,
            project_id=plan.project_id,
            created_by=model.user_id,
            data=data,
            media_type="application/json",
            source_tool="bench.cad_geometry",
            tool_call_id=None,
        )
        entry = await add_artifact_entry(
            session,
            plan.project_id,
            SolusSection.DOCS,
            artifact_id=artifact.id,
            name=f"{entity.name} CAD geometry",
            created_by=model.user_id,
        )
        session.add(
            GraphEdge(
                project_id=plan.project_id,
                src_id=entity.id,
                dst_id=entry.entity_id,
                relation_type="references",
                domain_pair="simulation<->project",
                origin="manual",
            )
        )
        for binding, (_, document, element, _) in zip(attrs["cad_bindings"], resolved, strict=True):
            binding["observed_microversion"] = revisions[(document, element)]
        attrs.update(
            refresh_status="current", refresh_error=None, geometry_artifact_id=str(artifact.id)
        )
        entity.attrs, entity.version = attrs, entity.version + 1
        await session.commit()


async def _error(
    maker: async_sessionmaker[AsyncSession], plan: RefreshPlan, model: ModelCapture, code: str
) -> None:
    async with maker() as session:
        await session.scalar(select(Project).where(Project.id == plan.project_id).with_for_update())
        entity = await session.scalar(
            select(GraphEntity).where(
                GraphEntity.id == model.identity,
                GraphEntity.project_id == plan.project_id,
                GraphEntity.deleted_at.is_(None),
            )
        )
        if entity is None or entity.version != model.version:
            return
        entity.attrs = {**entity.attrs, "refresh_status": "error", "refresh_error": code}
        entity.version += 1
        await session.commit()


async def complete(
    maker: async_sessionmaker[AsyncSession],
    store: ArtifactStore | None,
    plan: RefreshPlan,
    sync_id: uuid.UUID | None,
    hub: Any | None,
) -> None:
    if not plan.models and not plan.imports:
        return
    async with maker() as session:
        sync = await session.get(Sync, sync_id) if sync_id else None
        succeeded = (
            sync is not None
            and sync.source_id == plan.source_id
            and sync.project_id == plan.project_id
            and sync.status == JobStatus.SUCCEEDED
        )
    await complete_imports(maker, store, plan, succeeded)
    for model in plan.models:
        try:
            if not succeeded or plan.capture.error or store is None:
                raise ValueError("CAD refresh unavailable")
            if not plan.capture.exports and not plan.force:
                continue  # unchanged authoritative sync
            await refresh_model(maker, store, plan, model)
        except APIError as error:
            if error.code != "scene_changed":
                await _error(maker, plan, model, "source_unavailable")
        except Exception:
            await _error(maker, plan, model, plan.capture.error or "geometry_refresh_failed")
    if hub is not None:
        try:
            await hub.publish(
                plan.project_id,
                graph_changed_frame(
                    project_id=plan.project_id,
                    source_id=plan.source_id,
                    sync_id=sync_id,
                    counts=GraphChangeCounts(entities_updated=len(plan.models) + len(plan.imports)),
                    at=utcnow().isoformat(),
                ),
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "CAD geometry fanout failed project=%s", plan.project_id
            )


async def complete_imports(
    maker: async_sessionmaker[AsyncSession],
    store: ArtifactStore | None,
    plan: RefreshPlan,
    succeeded: bool,
) -> None:
    from solus_api.connectors.step_tessellation import CadGeometryError

    from .cad_import import materialize

    for identity in plan.imports:
        async with maker() as session:
            row = await session.scalar(
                select(GraphEntity).where(
                    GraphEntity.id == identity,
                    GraphEntity.project_id == plan.project_id,
                    GraphEntity.deleted_at.is_(None),
                )
            )
            if row is None or row.attrs.get("status") != "pending":
                continue
            try:
                if not succeeded or plan.capture.error or store is None:
                    raise ValueError("CAD import source acquisition failed")
                service = SceneService(session, plan.project_id, uuid.UUID(row.attrs["created_by"]))
                await materialize(service, row, plan.capture.exports, store)
                await session.commit()
            except Exception as error:
                safe_reason = (
                    "CAD geometry exceeds the bounded display limits."
                    if isinstance(error, CadGeometryError)
                    else None
                )
                await session.rollback()
                row = await session.get(GraphEntity, identity)
                if row is not None:
                    row.attrs = {
                        **row.attrs,
                        "status": "error",
                        "reason": plan.capture.error
                        or safe_reason
                        or "CAD geometry could not be imported from the exact source revision.",
                    }
                    row.version += 1
                    await session.commit()


async def output_status(service: SceneService, attrs: dict[str, Any]) -> str:
    status = attrs.get("refresh_status", "current")
    if status in ("queued", "error"):
        return str(status)
    for binding in attrs.get("cad_bindings", []):
        try:
            source = await eligible(service, uuid.UUID(binding["source_entity_id"]))
            if target_of(source)[2] != binding.get("observed_microversion"):
                return "stale"
        except (APIError, ValueError, KeyError):
            return "stale"
    return "current"
