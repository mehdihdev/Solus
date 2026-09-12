"""Personal branch views over immutable connector snapshots."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.runtime import _resolve_credentials
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, RegistryDep, SecretStoreDep, SessionDep, SettingsDep
from solus_api.models import Source, SourceStatus, SourceViewSelection
from solus_api.routers.sources import _arq_pool, _scoped_source
from solus_api.services.events import emit_event
from solus_api.services.git_revisions import list_branches, validate_branch
from solus_api.services.source_revisions import (
    acquire_revision,
    get_view,
    git_connector,
    selection_for,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/sources/{source_id}")


class BranchItem(BaseModel):
    name: str
    commit: str


class RevisionsResponse(BaseModel):
    supported: bool
    kind: Literal["git_branch"] | None
    items: list[BranchItem]
    next_page: int | None


class SourceViewResponse(BaseModel):
    base_source_id: uuid.UUID
    status: Literal["default", "pending", "ready", "failed"]
    source_id: uuid.UUID
    branch: str | None
    commit: str | None
    error: str | None


class RevisionsEnvelope(BaseModel):
    data: RevisionsResponse


class SourceViewEnvelope(BaseModel):
    data: SourceViewResponse


class SourceViewPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str = Field(min_length=1, max_length=255)


def _connected(source: Source) -> None:
    if source.status in (SourceStatus.DISCONNECTED, SourceStatus.PENDING):
        raise APIError(404, "not_found", "Connected source not found")


@router.get("/revisions")
async def revisions(
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    registry: RegistryDep,
    secret_store: SecretStoreDep,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> RevisionsEnvelope:
    source = await _scoped_source(session, ctx, source_id)
    _connected(source)
    if source.type.value not in {"github", "gitlab"}:
        return RevisionsEnvelope.model_validate(
            envelope(dict(supported=False, kind=None, items=[], next_page=None))
        )
    try:
        if source.secret_ref is None:
            raise ConnectorError("invalid_credentials", "Connect the source again")
        credentials = await _resolve_credentials(secret_store, source.secret_ref)
        payload = await list_branches(
            git_connector(registry, source), credentials, str(source.config["repo"]), page=page
        )
        return RevisionsEnvelope.model_validate(envelope(payload))
    except ConnectorError as exc:
        raise APIError(
            429 if exc.code == "rate_limited" else 400,
            exc.code,
            "Branch discovery is unavailable; try again or reconnect the source.",
        ) from exc


@router.get("/view")
async def view(source_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep) -> SourceViewEnvelope:
    source = await _scoped_source(session, ctx, source_id)
    _connected(source)
    return SourceViewEnvelope.model_validate(envelope(await get_view(session, source, ctx.user.id)))


@router.put("/view", status_code=202)
async def select_view(
    source_id: uuid.UUID,
    body: SourceViewPut,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: ProjectCtx,
    session: SessionDep,
    registry: RegistryDep,
    settings: SettingsDep,
) -> SourceViewEnvelope:
    source = await _scoped_source(session, ctx, source_id, lock=True)
    _connected(source)
    try:
        git_connector(registry, source)
        validate_branch(body.branch)
    except ConnectorError as exc:
        raise APIError(400, exc.code, "This source or branch does not support selection") from exc
    selection = await selection_for(session, source, ctx.user.id)
    if (
        selection is not None
        and selection.status == "pending"
        and selection.requested_branch == body.branch
    ):
        return SourceViewEnvelope.model_validate(
            envelope(await get_view(session, source, ctx.user.id))
        )
    generation = uuid.uuid4()
    if selection is None:
        selection = SourceViewSelection(
            project_id=ctx.project.id,
            user_id=ctx.user.id,
            base_source_id=source.id,
            request_generation=generation,
            status="pending",
            requested_branch=body.branch,
        )
        session.add(selection)
    else:
        selection.request_generation = generation
        selection.requested_branch = body.branch
        selection.status = "pending"
        selection.error = None
    emit_event(
        session,
        user=ctx.user,
        event_type="source.view_selected",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"source_id": str(source.id)},
    )
    await session.commit()
    if settings.redis_url:
        try:
            pool = await _arq_pool(request.app)
            await pool.enqueue_job(
                "source_revision", str(source.id), str(ctx.user.id), str(generation)
            )
        except Exception:
            source = await _scoped_source(session, ctx, source_id, lock=True)
            latest = await selection_for(session, source, ctx.user.id)
            if latest is not None and latest.request_generation == generation:
                latest.status = "failed"
                latest.error = (
                    "Branch acquisition could not be scheduled. Your previous view is unchanged."
                )
                await session.commit()
    else:
        background_tasks.add_task(
            acquire_revision,
            sessionmaker=request.app.state.sessionmaker,
            registry=registry,
            secret_store=request.app.state.secret_store,
            source_id=source.id,
            user_id=ctx.user.id,
            generation=generation,
            hub=getattr(request.app.state, "graph_hub", None),
        )
    return SourceViewEnvelope.model_validate(envelope(await get_view(session, source, ctx.user.id)))


@router.delete("/view")
async def clear_view(
    source_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> SourceViewEnvelope:
    source = await _scoped_source(session, ctx, source_id, lock=True)
    _connected(source)
    selection = await selection_for(session, source, ctx.user.id)
    if selection is not None:
        await session.delete(selection)
        emit_event(
            session,
            user=ctx.user,
            event_type="source.view_reset",
            team_id=ctx.team.id,
            project_id=ctx.project.id,
            payload={"source_id": str(source.id)},
        )
        await session.commit()
    return SourceViewEnvelope.model_validate(envelope(await get_view(session, source, ctx.user.id)))
