"""Verified-member scene imports and confirmed mapping; no hardware operations."""

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, RequireVerified, SessionDep, SettingsDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.models import GraphEntity, Role, utcnow
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts
from sqlalchemy import select

from .schemas import CadBindings, CadImport, ImportModel, Mapping, ReplaceModel
from .service import SceneService

router = APIRouter(prefix="/api/v1/projects/{project_id}/bench/scene")


async def finish(
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    service: SceneService,
    entity: GraphEntity,
    event: str,
) -> dict[str, Any]:
    result = await service.output(entity)
    emit_event(
        session,
        user=ctx.user,
        event_type=event,
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"model_id": str(entity.id)},
    )
    await session.commit()
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(entities_updated=1),
            at=utcnow().isoformat(),
        ),
    )
    return envelope(result)


@router.get("/models")
async def list_models(
    ctx: ProjectCtx, session: SessionDep, _verified: RequireVerified
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = SceneService(session, ctx.project.id, ctx.user.id)
    return envelope({"models": [await service.output(entity) for entity in await service.all()]})


@router.post("/models", status_code=201)
async def import_model(
    body: ImportModel,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = SceneService(session, ctx.project.id, ctx.user.id)
    entity = await service.import_model(
        body, request.app.state.artifact_store, settings.artifact_ttl_seconds
    )
    return await finish(request, ctx, session, service, entity, "bench.scene_imported")


@router.put("/models/{model_id}")
async def replace_model(
    model_id: uuid.UUID,
    body: ReplaceModel,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = SceneService(session, ctx.project.id, ctx.user.id)
    entity = await service.import_model(
        body,
        request.app.state.artifact_store,
        settings.artifact_ttl_seconds,
        model_id,
        body.expected_version,
    )
    return await finish(request, ctx, session, service, entity, "bench.scene_reimported")


@router.put("/models/{model_id}/mapping")
async def map_model(
    model_id: uuid.UUID,
    body: Mapping,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = SceneService(session, ctx.project.id, ctx.user.id)
    entity = await service.mapping(model_id, body)
    return await finish(request, ctx, session, service, entity, "bench.scene_mapping_confirmed")


@router.get("/cad-sources")
async def cad_sources(
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
    include_assemblies: bool = False,
) -> dict[str, Any]:
    from .cad_refresh import source_options

    require_role(ctx, Role.MEMBER)
    return envelope(
        {
            "sources": await source_options(
                SceneService(session, ctx.project.id, ctx.user.id),
                include_assemblies=include_assemblies,
            )
        }
    )


@router.put("/models/{model_id}/cad-bindings", status_code=202)
async def bind_cad(
    model_id: uuid.UUID,
    body: CadBindings,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    from solus_api.models import GraphEdge, Source
    from solus_api.routers.sources import enqueue_sync

    from .cad_refresh import eligible

    require_role(ctx, Role.MEMBER)
    service = SceneService(session, ctx.project.id, ctx.user.id)
    await service.lock()
    entity = await service.entity(model_id, "bench_scene_model")
    if entity.version != body.expected_version:
        raise APIError(409, "version_conflict", "Scene changed; reload before linking CAD.")
    if len({binding.mesh_key for binding in body.bindings}) != len(body.bindings):
        raise APIError(422, "invalid_cad_binding", "Each mesh can have only one CAD source.")
    targets = []
    for binding in body.bindings:
        if binding.mesh_key not in entity.attrs["model"].get("meshes", {}):
            raise APIError(422, "invalid_cad_binding", "Choose an existing model mesh.")
        targets.append(await eligible(service, binding.source_entity_id))
    source_ids = {target.source_id for target in targets}
    if len(source_ids) > 1:
        raise APIError(422, "invalid_cad_binding", "Choose CAD leaves from one connected source.")
    attrs = {
        **entity.attrs,
        "cad_bindings": [
            {**binding.model_dump(mode="json"), "observed_microversion": None}
            for binding in body.bindings
        ],
        "cad_bound_by": str(ctx.user.id),
        "cad_source_id": str(next(iter(source_ids))) if source_ids else None,
        "refresh_status": "queued" if targets else "current",
        "refresh_error": None,
    }
    entity.attrs, entity.version = attrs, entity.version + 1
    old_edges = await session.scalars(
        select(GraphEdge).where(
            GraphEdge.project_id == ctx.project.id,
            GraphEdge.src_id == entity.id,
            GraphEdge.relation_type == "cad_visual_for",
            GraphEdge.origin == "manual",
        )
    )
    for edge in old_edges:
        await session.delete(edge)
    session.add_all(
        [
            GraphEdge(
                project_id=ctx.project.id,
                src_id=entity.id,
                dst_id=target.id,
                relation_type="cad_visual_for",
                domain_pair="simulation<->mechanical",
                origin="manual",
            )
            for target in {target.id: target for target in targets}.values()
        ]
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="bench.scene_cad_bound",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"model_id": str(entity.id), "binding_count": len(targets)},
    )
    await session.flush()
    job_id = None
    if source_ids:
        source = await session.get(Source, next(iter(source_ids)))
        assert source is not None
        job_id = await enqueue_sync(
            session, ctx, source, request, background_tasks, settings, response
        )
        await session.refresh(entity)
    else:
        await session.commit()
    return envelope(
        {
            "model": await service.output(entity),
            "refresh_status": entity.attrs["refresh_status"],
            "job_id": str(job_id) if job_id else None,
        }
    )


@router.post("/cad-imports", status_code=202)
async def import_cad(
    body: "CadImport",
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    from solus_api.models import Source
    from solus_api.routers.sources import enqueue_sync

    from .cad_import import propose, status

    require_role(ctx, Role.MEMBER)
    service = SceneService(session, ctx.project.id, ctx.user.id)
    row = await propose(service, body.robot_id, body.source_entity_id, body.expected_revision)
    if row.attrs.get("job_id") is None:
        source = await session.scalar(
            select(Source).where(
                Source.id == uuid.UUID(row.attrs["cad_source_id"]),
                Source.project_id == ctx.project.id,
                Source.team_id == ctx.team.id,
            )
        )
        if source is None:
            raise APIError(404, "not_found", "CAD source not found")
        job_id = await enqueue_sync(
            session, ctx, source, request, background_tasks, settings, response
        )
        await session.refresh(row)
        row.attrs = {**row.attrs, "job_id": str(job_id)}
        emit_event(
            session,
            user=ctx.user,
            event_type="bench.scene_cad_import_requested",
            team_id=ctx.team.id,
            project_id=ctx.project.id,
            payload={"import_id": str(row.id)},
        )
        await session.commit()
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(entities_created=1),
                at=utcnow().isoformat(),
            ),
        )
    return envelope(status(row))


@router.get("/cad-imports/{import_id}")
async def cad_import_status(
    import_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep, _verified: RequireVerified
) -> dict[str, Any]:
    from .cad_import import IMPORT_KIND, status

    require_role(ctx, Role.MEMBER)
    row = await SceneService(session, ctx.project.id, ctx.user.id).entity(import_id, IMPORT_KIND)
    return envelope(status(row))
