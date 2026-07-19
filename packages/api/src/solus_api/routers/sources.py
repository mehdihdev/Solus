"""§2.5 Sources — connect, configure, sync, and inspect connected tools.

Credentials never appear in any request or response: a connect-with-token goes
straight to the secret store, and serialized sources omit secrets entirely
(CLAUDE.md §7). Syncs run as background work (ADR-005) — dispatched to ARQ when
Redis is configured, an in-process background task otherwise, or inline under
the `sync_inline` dev/test flag.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from sqlalchemy import delete, select, update

from solus_api.connectors.contracts import AuthKind, ConnectorError, Credentials
from solus_api.connectors.runtime import source_entity_count, source_entity_counts
from solus_api.connectors.worker import execute_source_sync
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import (
    ProjectCtx,
    RegistryDep,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
    SettingsDep,
    require_role,
)
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    Job,
    JobKind,
    JobStatus,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Sync,
)
from solus_api.schemas import (
    SourceCreate,
    SourceUpdate,
    serialize_source,
    serialize_sync,
)
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_add_integration

if TYPE_CHECKING:
    from fastapi import FastAPI

router = APIRouter(prefix="/api/v1/projects/{project_id}/sources")

SYNC_HISTORY_LIMIT = 50


async def _scoped_source(session: SessionDep, ctx: ProjectCtx, source_id: uuid.UUID) -> Source:
    source = await session.get(Source, source_id)
    if source is None or source.project_id != ctx.project.id:
        raise APIError(404, "not_found", "Source not found")
    return source


def _resolve_connector(registry: RegistryDep, provider: str) -> Any:
    from solus_api.connectors.registry import UnknownConnectorError

    try:
        return registry.create(provider)
    except UnknownConnectorError as exc:
        raise APIError(400, "connector_unavailable", f"No connector for '{provider}'") from exc


@router.get("")
async def list_sources(
    ctx: ProjectCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    stmt = (
        select(Source)
        .where(Source.project_id == ctx.project.id)
        .order_by(Source.created_at.desc(), Source.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(Source.created_at, Source.id, cursor))
    visible, meta = page_meta(list((await session.scalars(stmt)).all()), limit)
    counts = await source_entity_counts(session, [s.id for s in visible])
    out = [serialize_source(s, entity_count=counts.get(s.id, 0)) for s in visible]
    return envelope(out, meta=meta)


@router.post("", status_code=201)
async def connect_source(
    body: SourceCreate,
    ctx: ProjectCtx,
    session: SessionDep,
    registry: RegistryDep,
    secret_store: SecretStoreDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    await check_can_add_integration(session, ctx.user)
    provider = body.type
    connector = _resolve_connector(registry, provider)

    source = Source(
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        type=SourceType(provider),
        name=body.name,
        config={k: v for k, v in body.config.items() if not k.startswith("_")},
        status=SourceStatus.PENDING,
        created_by=ctx.user.id,
    )
    session.add(source)
    await session.flush()

    if body.token:
        if not connector.supports_token_connect:
            raise APIError(
                400,
                "token_connect_unsupported",
                f"'{provider}' must be connected via OAuth, not a token",
            )
        try:
            account = await connector.validate_credentials(Credentials(token=body.token))
        except ConnectorError as exc:
            raise APIError(400, exc.code, exc.message) from exc
        secret_ref = f"source/{source.id}/{provider}"
        await secret_store.put(secret_ref, body.token)
        source.secret_ref = secret_ref
        source.status = SourceStatus.CONNECTED
        source.account_login = account.login
        source.account_external_id = account.external_id
    elif connector.auth_kind is AuthKind.NONE:
        # Committed-export connectors (EDA family, SOLUSDEV-100/102) carry no
        # tool credential — nothing to authenticate, so the source is connected
        # on creation, labeled with the connector's synthetic identity.
        account = await connector.validate_credentials(Credentials(token=""))
        source.status = SourceStatus.CONNECTED
        source.account_login = account.login
        source.account_external_id = account.external_id

    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="source.connected",
        actor_id=ctx.user.id,
        project_id=ctx.project.id,
        domain="integrations",
        payload={"type": provider, "name": source.name},
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="source.connected",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"type": provider},
    )
    await session.commit()
    await session.refresh(source)
    return envelope(serialize_source(source))


@router.get("/{source_id}")
async def get_source(source_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    source = await _scoped_source(session, ctx, source_id)
    count = await source_entity_count(session, source.id)
    return envelope(serialize_source(source, entity_count=count))


@router.patch("/{source_id}")
async def update_source(
    body: SourceUpdate, source_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    source = await _scoped_source(session, ctx, source_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        source.name = data["name"]
    if data.get("config") is not None:
        merged = {**source.config}
        merged.update({k: v for k, v in data["config"].items() if not k.startswith("_")})
        source.config = merged
    await session.commit()
    await session.refresh(source)
    return envelope(serialize_source(source))


@router.delete("/{source_id}")
async def disconnect_source(
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    secret_store: SecretStoreDep,
    retain_entities: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    source = await _scoped_source(session, ctx, source_id)
    if source.secret_ref:
        await secret_store.delete(source.secret_ref)
    if retain_entities:
        # Orphan the graph data into manual, user-owned entities rather than
        # removing it with the source.
        await session.execute(
            update(GraphEntity)
            .where(GraphEntity.source_id == source.id)
            .values(source_id=None, origin="manual")
        )
        await session.execute(
            update(GraphEdge)
            .where(GraphEdge.source_id == source.id)
            .values(source_id=None, origin="manual")
        )
    else:
        # Explicit removal (don't rely on DB-level cascade — not enforced on
        # SQLite). Edges first to satisfy the FK ordering.
        await session.execute(delete(GraphEdge).where(GraphEdge.source_id == source.id))
        await session.execute(delete(GraphEntity).where(GraphEntity.source_id == source.id))
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="source.disconnected",
        actor_id=ctx.user.id,
        project_id=ctx.project.id,
        domain="integrations",
        payload={"type": source.type.value, "retain_entities": retain_entities},
    )
    await session.delete(source)
    await session.commit()
    return envelope({"id": source_id, "retained_entities": retain_entities})


@router.post("/{source_id}/sync", status_code=202)
async def trigger_sync(
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    registry: RegistryDep,
    response: Response,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    source = await _scoped_source(session, ctx, source_id)
    # auth-NONE connectors (committed exports) never hold a secret_ref — only
    # credentialed connectors must prove one before a sync (SOLUSDEV-100).
    needs_credentials = (
        _resolve_connector(registry, source.type.value).auth_kind is not AuthKind.NONE
    )
    if source.status == SourceStatus.PENDING or (needs_credentials and not source.secret_ref):
        raise APIError(409, "not_connected", "Source is not connected yet")
    # Debounce: don't stack a second sync while one is in flight (a cheap
    # per-source guard; per-team budget/concurrency is ADR-019). The scheduled
    # sweep only selects CONNECTED sources, so SYNCING ones are skipped there too.
    if source.status == SourceStatus.SYNCING:
        raise APIError(409, "sync_in_progress", "A sync is already running for this source")

    job = Job(
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        kind=JobKind.SYNC,
        status=JobStatus.QUEUED,
        created_by=ctx.user.id,
    )
    session.add(job)
    await session.flush()
    job_id = job.id
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="source.sync_started",
        actor_id=ctx.user.id,
        project_id=ctx.project.id,
        domain="integrations",
        payload={"source_id": str(source.id)},
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="source.sync_started",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"source_id": str(source.id)},
    )
    await session.commit()

    await _dispatch_sync(request.app, settings, background_tasks, source.id, job_id)
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return envelope({"job_id": job_id, "status": JobStatus.QUEUED.value})


@router.get("/{source_id}/syncs")
async def list_syncs(
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=SYNC_HISTORY_LIMIT)] = SYNC_HISTORY_LIMIT,
) -> dict[str, Any]:
    source = await _scoped_source(session, ctx, source_id)
    stmt = (
        select(Sync)
        .where(Sync.source_id == source.id)
        .order_by(Sync.created_at.desc(), Sync.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(Sync.created_at, Sync.id, cursor))
    visible, meta = page_meta(list((await session.scalars(stmt)).all()), limit)
    return envelope([serialize_sync(s) for s in visible], meta=meta)


@router.get("/{source_id}/syncs/{sync_id}")
async def get_sync(
    source_id: uuid.UUID, sync_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    source = await _scoped_source(session, ctx, source_id)
    sync = await session.get(Sync, sync_id)
    if sync is None or sync.source_id != source.id:
        raise APIError(404, "not_found", "Sync not found")
    return envelope(serialize_sync(sync))


@router.get("/{source_id}/repos")
async def list_repos(
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    registry: RegistryDep,
    secret_store: SecretStoreDep,
) -> dict[str, Any]:
    """Repo picker for the connect flow (GitHub). Lists repositories the
    connected account can access."""
    source = await _scoped_source(session, ctx, source_id)
    if not source.secret_ref:
        raise APIError(409, "not_connected", "Source is not connected yet")
    connector = _resolve_connector(registry, source.type.value)
    lister = getattr(connector, "list_repositories", None)
    if lister is None:
        raise APIError(400, "unsupported", "This provider does not list repositories")
    token = await secret_store.get(source.secret_ref)
    try:
        repos = await lister(Credentials(token=token))
    except ConnectorError as exc:
        raise APIError(502, exc.code, exc.message) from exc
    return envelope(repos)


# --- sync dispatch (ADR-005) ---


async def _dispatch_sync(
    app: FastAPI,
    settings: Settings,
    background_tasks: BackgroundTasks,
    source_id: uuid.UUID,
    job_id: uuid.UUID,
) -> None:
    if settings.sync_inline:
        await _run_inline(app, source_id, job_id)
        return
    if settings.redis_url:
        pool = await _arq_pool(app)
        await pool.enqueue_job("sync_source", str(source_id), str(job_id))
        return
    background_tasks.add_task(_run_inline, app, source_id, job_id)


async def _run_inline(app: FastAPI, source_id: uuid.UUID, job_id: uuid.UUID) -> None:
    await execute_source_sync(
        sessionmaker=app.state.sessionmaker,
        registry=app.state.connector_registry,
        secret_store=app.state.secret_store,
        source_id=source_id,
        job_id=job_id,
    )


async def _arq_pool(app: FastAPI) -> Any:
    pool = getattr(app.state, "arq_pool", None)
    if pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(app.state.settings.redis_url))
        app.state.arq_pool = pool
    return pool
