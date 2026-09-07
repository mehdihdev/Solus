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
from solus_api.connectors.hosted_oauth import hosted_refs
from solus_api.connectors.registry import Purpose
from solus_api.connectors.runtime import (
    refresh_secret_ref,
    source_entity_count,
    source_entity_counts,
)
from solus_api.connectors.worker import execute_source_sync
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import (
    IntegrationCacheDep,
    ProjectCtx,
    RegistryDep,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
    SettingsDep,
    require_role,
)
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
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
    DocumentAdd,
    SourceCreate,
    SourceUpdate,
    serialize_source,
    serialize_sync,
)
from solus_api.services.activity import record_activity
from solus_api.services.connections import (
    account_ref_for,
    bind_to_account,
    delete_legacy_family_if_retired,
    is_connection_owned,
    list_documents,
    owned_connection,
    reusable_source,
    sweep_after_commit,
)
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_add_integration

if TYPE_CHECKING:
    from fastapi import FastAPI

router = APIRouter(prefix="/api/v1/projects/{project_id}/sources")

SYNC_HISTORY_LIMIT = 50


async def _scoped_source(
    session: SessionDep, ctx: ProjectCtx, source_id: uuid.UUID, *, lock: bool = False
) -> Source:
    stmt = select(Source).where(Source.id == source_id, Source.project_id == ctx.project.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    source = await session.scalar(stmt)
    if source is None or source.project_id != ctx.project.id:
        raise APIError(404, "not_found", "Source not found")
    return source


def _resolve_connector(
    registry: RegistryDep,
    provider: str,
    *,
    source: Source | None = None,
    ctx: Any = None,
    purpose: Purpose = "user",
) -> Any:
    """A connector for a route, METERED whenever we know whose quota it spends.

    SOLUSDEV-167. This used to call `registry.create()` unconditionally, which
    returns the plain factory — no `CallMeter`. So the document picker, which
    walks up to 10 quota-counted pages per invocation, spent an ANNUAL allowance
    entirely unmetered and unlatched: a 402 could not even stop it. An opt-in
    meter that most construction sites skip is not a budget, so the default here
    is now scoped-and-metered, and the unmetered path has to be asked for.

    `create_scoped` falls back to the plain factory for providers with no scoped
    registration, so this is safe for every provider.
    """
    from solus_api.connectors.registry import ConnectorContext, UnknownConnectorError

    try:
        if source is not None and ctx is not None:
            return registry.create_scoped(
                provider,
                ConnectorContext(
                    project_id=ctx.project.id,
                    team_id=ctx.team.id,
                    acting_user_id=ctx.user.id,
                    account_ref=account_ref_for(source),
                    purpose=purpose,
                ),
            )
        # Pre-source paths only (OAuth exchange, credential validation): there is
        # no Source row yet, so there is no account to charge.
        return registry.create(provider)
    except UnknownConnectorError as exc:
        raise APIError(400, "connector_unavailable", f"No connector for '{provider}'") from exc


async def _quota_states(request: Request, sources: list[Source]) -> dict[uuid.UUID, Any]:
    """Provider-quota position per source, for the list view (SOLUSDEV-167).

    Best-effort by construction: a source with no metered provider, or a missing
    Redis, simply has no entry and the payload omits the block — a quota field
    that silently reported "ok" because the ledger was unreachable would be worse
    than no field at all.
    """
    from solus_api.connectors.registry import ConnectorContext, _onshape_meter

    settings = request.app.state.settings
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return {}
    states: dict[uuid.UUID, Any] = {}
    for source in sources:
        if source.type is not SourceType.ONSHAPE:
            continue
        meter = _onshape_meter(
            settings,
            redis,
            ConnectorContext(
                project_id=source.project_id,
                team_id=source.team_id,
                account_ref=source.account_external_id,
            ),
        )
        states[source.id] = await meter.state()
    return states


@router.get("")
async def list_sources(
    request: Request,
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
    quotas = await _quota_states(request, visible)
    out = [
        serialize_source(s, entity_count=counts.get(s.id, 0), quota=quotas.get(s.id))
        for s in visible
    ]
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
    provider = body.type
    _refuse_local(provider)
    connector = _resolve_connector(registry, provider)
    if body.connection_id and body.token:
        raise APIError(400, "validation_error", "Pass a connection_id or a token, not both")

    source: Source | None = None
    connection: AccountConnection | None = None
    if body.connection_id:
        connection = await _bindable_connection(session, ctx, provider, body.connection_id)
        source = await reusable_source(
            session,
            ctx.project,
            SourceType(provider),
            connector,
            connection=connection,
            config=body.config,
        )
        if source is not None and source.connection_id == connection.id:
            return envelope(serialize_source(source))
    reused = source is not None
    if source is None:
        await check_can_add_integration(session, ctx.user)
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

    if connection is not None:
        # A reused legacy/PAT row retires its own token family (SOLUSDEV-242 MEDIUM-1).
        bind_to_account(source, connection, preserve_state=reused)
    elif body.token:
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
    await _sweep_if_bound(connection, session, secret_store, ctx.user)
    await session.refresh(source)
    return envelope(serialize_source(source))


def _refuse_local(provider: str) -> None:
    """SOLUSDEV-249: `/local-folder` is the ONE creator of `local` sources, so
    one-source-per-(project, machine) holds."""
    if provider == SourceType.LOCAL.value:
        raise APIError(
            400, "use_local_folder_route", "Link a local folder via /local-folder instead"
        )


async def _sweep_if_bound(
    connection: object | None, session: SessionDep, secret_store: SecretStoreDep, user: Any
) -> None:
    """SOLUSDEV-242 H2: after a connection-bound connect commits, retire the
    legacy token family the bind superseded (no-op for token connects)."""
    if connection is not None:
        await sweep_after_commit(session, secret_store, user)


async def _bindable_connection(
    session: SessionDep, ctx: ProjectCtx, provider: str, connection_id: str
) -> AccountConnection:
    """SOLUSDEV-241: the account the CALLER authorized on Home, checked before a
    project is attached to it. Owner-only by construction — `owned_connection`
    answers 404 for anyone else's grant, membership notwithstanding."""
    connection = await owned_connection(session, ctx.user, _connection_uuid(connection_id))
    if connection.provider.value != provider:
        raise APIError(
            400, "connection_mismatch", f"That account is a {connection.provider.value} account"
        )
    if connection.status is not ConnectionStatus.CONNECTED or not connection.secret_ref:
        raise APIError(409, "not_connected", "That account is not connected")
    return connection


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
    source = await _scoped_source(session, ctx, source_id, lock=True)
    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        source.name = data["name"]
    if data.get("config") is not None:
        # A `local` source's config is its machine/user binding (SOLUSDEV-249):
        # only /local-folder writes it (security review M3).
        _refuse_local(source.type.value)
        merged = {**source.config}
        # `access` is a GRANT fact, mirrored from the connection at bind time —
        # never a setting a member may patch in (security review M4).
        merged.update(
            {k: v for k, v in data["config"].items() if not k.startswith("_") and k != "access"}
        )
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
    # SOLUSDEV-241: a connection-owned ref is the ACCOUNT's credential, shared
    # by every project bound to it. Disconnecting one project must not revoke
    # the others; only `DELETE /users/me/connections/{id}` deletes that family.
    # A family this source retired but the sweep had not yet deleted goes now
    # — the row is about to lose the id it is derived from (SOLUSDEV-242).
    await delete_legacy_family_if_retired(secret_store, source)
    if source.secret_ref and not is_connection_owned(source.secret_ref):
        await secret_store.delete(source.secret_ref)
        # The OAuth refresh token lives under its own ref (SOLUS-CAD-01) and
        # outlives the access token unless it is deleted here. Leaving it would
        # let Solus keep minting access tokens against the user's documents
        # after they believe they revoked us. `delete` no-ops when absent.
        await secret_store.delete(refresh_secret_ref(source.secret_ref))
        # SOLUSDEV-168: a hosted add-on (FeatureScript) holds its OWN customer
        # token under a ref derived from this one. "Disconnecting Solus must not
        # unsubscribe them" is not the same as "Solus keeps a live OAuth2Write
        # grant on their documents after they revoked us" — the app stays
        # enabled on their account; our ability to act as them does not.
        for hosted_ref in hosted_refs(source.secret_ref):
            await secret_store.delete(hosted_ref)
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
    _require_syncable(source, registry)
    job_id = await enqueue_sync(
        session,
        ctx,
        source,
        request,
        background_tasks,
        settings,
        response,
        inline_only=source.type is SourceType.LOCAL,
    )
    return envelope({"job_id": job_id, "status": JobStatus.QUEUED.value})


def _require_syncable(
    source: Source, registry: RegistryDep, *, allow_in_progress: bool = False
) -> None:
    # auth-NONE connectors (committed exports) never hold a secret_ref — only
    # credentialed connectors must prove one before a sync (SOLUSDEV-100).
    needs_credentials = (
        _resolve_connector(registry, source.type.value).auth_kind is not AuthKind.NONE
    )
    if source.status in (SourceStatus.PENDING, SourceStatus.DISCONNECTED) or (
        needs_credentials and not source.secret_ref
    ):
        raise APIError(409, "not_connected", "Source is not connected yet")
    # Debounce: don't stack a second sync while one is in flight (a cheap
    # per-source guard; per-team budget/concurrency is ADR-019). The scheduled
    # sweep only selects CONNECTED sources, so SYNCING ones are skipped there too.
    if source.status == SourceStatus.SYNCING and not allow_in_progress:
        raise APIError(409, "sync_in_progress", "A sync is already running for this source")


async def enqueue_sync(
    session: SessionDep,
    ctx: ProjectCtx,
    source: Source,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings,
    response: Response,
    *,
    inline_only: bool = False,
) -> uuid.UUID:
    """Record the job + activity, commit, dispatch (ADR-005), set Location.

    `inline_only` (SOLUSDEV-249): a `local` source is scanned over the bridge,
    which lives in THIS process — never hand it to ARQ."""
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

    await _dispatch_sync(
        request.app,
        settings,
        background_tasks,
        source.id,
        job_id,
        acting_user_id=ctx.user.id,
        inline_only=inline_only,
    )
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return job_id


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


@router.get("/{source_id}/selectable")
async def list_selectable(
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    registry: RegistryDep,
    secret_store: SecretStoreDep,
    cache: IntegrationCacheDep,
    refresh: Annotated[bool, Query()] = False,
    cache_only: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """What this connected source can be pointed at: repositories, CAD documents,
    …. One generic picker route, so a new connector becomes pickable by
    implementing `list_selectable` — no route and no frontend change.

    SOLUSDEV-241: served from the integration cache, keyed on the ACCOUNT — so
    Home's listing, this project's picker and a teammate's picker on another
    project bound to the same account cost ONE provider walk between them.
    `refresh=true` spends again; nothing else does.
    """
    # A refresh costs up to 10 quota-counted provider calls, so the route keeps
    # the MEMBER floor its sibling routes have. Without it the lowest-privilege
    # principal in the system could drain an annual allowance in minutes.
    require_role(ctx, Role.MEMBER)
    source = await _scoped_source(session, ctx, source_id)
    if not source.secret_ref:
        raise APIError(409, "not_connected", "Source is not connected yet")
    connector = _resolve_connector(registry, source.type.value, source=source, ctx=ctx)
    fetched = await list_documents(
        cache,
        connector=connector,
        secret_store=secret_store,
        secret_ref=source.secret_ref,
        provider=source.type.value,
        account_ref=account_ref_for(source),
        refresh=refresh,
        cache_only=cache_only,
    )
    return envelope(
        fetched.value, meta={"cached": fetched.cached, "fetched_at": fetched.fetched_at}
    )


# --- per-project documents (SOLUSDEV-241 / I1) ---


def _tracked_key(registry: RegistryDep, source: Source) -> str:
    """The config key a multi-selection connector tracks its items under. A
    connector that declares anything else has no document list to edit."""
    selection = getattr(_resolve_connector(registry, source.type.value), "selection", None)
    if not isinstance(selection, dict) or selection.get("mode") != "multi":
        raise APIError(400, "unsupported", "This source does not track a document list")
    return str(selection["config_key"])


def _tracked_ids(source: Source, key: str) -> list[str]:
    raw = source.config.get(key, [])
    return [v for v in raw if isinstance(v, str)] if isinstance(raw, list) else []


def _validate_tracked(registry: RegistryDep, source: Source, ids: list[str]) -> None:
    """The CONNECTOR's own rule decides what an id may look like: a duck-typed
    `validate_selection`, resolved exactly as `list_selectable` is, so the next
    multi-selection connector is validated without a router edit. Onshape's is
    the same `tracked_document_ids` gate the SOL tools refuse on — one
    definition, no second, weaker one. Malformed is a 400, never stored."""
    validate = getattr(_resolve_connector(registry, source.type.value), "validate_selection", None)
    if validate is None:
        return
    try:
        validate(ids)
    except ConnectorError as exc:
        raise APIError(400, exc.code, exc.message) from exc


def _connection_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(404, "not_found", "Connection not found") from exc


@router.post("/{source_id}/documents")
async def add_document(
    body: DocumentAdd,
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    registry: RegistryDep,
    response: Response,
) -> dict[str, Any]:
    """Track one more of the account's documents in THIS project, and sync so
    it is ingested. 202 with the job when the selection moved; 200 `unchanged`
    when it was already tracked — nothing to spend on."""
    require_role(ctx, Role.MEMBER)
    source = await _scoped_source(session, ctx, source_id, lock=True)
    key = _tracked_key(registry, source)
    current = _tracked_ids(source, key)
    if body.id in current:
        response.status_code = 200
        return envelope({"job_id": None, "status": "unchanged", "source": serialize_source(source)})
    wanted = [*current, body.id]
    _validate_tracked(registry, source, wanted)
    _require_syncable(source, registry, allow_in_progress=True)
    source.config = {**source.config, key: wanted}
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="source.document_added",
        actor_id=ctx.user.id,
        project_id=ctx.project.id,
        domain="integrations",
        payload={"source_id": str(source.id), "document_id": body.id},
    )
    job_id = await enqueue_sync(session, ctx, source, request, background_tasks, settings, response)
    await session.refresh(source)
    response.status_code = 202
    return envelope(
        {"job_id": job_id, "status": JobStatus.QUEUED.value, "source": serialize_source(source)}
    )


@router.delete("/{source_id}/documents/{document_id}")
async def remove_document(
    source_id: uuid.UUID,
    document_id: str,
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    registry: RegistryDep,
    response: Response,
) -> dict[str, Any]:
    """Stop tracking a document in THIS project. The sync that follows reconciles
    its entities away (soft-delete); other projects tracking it are untouched."""
    require_role(ctx, Role.MEMBER)
    source = await _scoped_source(session, ctx, source_id, lock=True)
    key = _tracked_key(registry, source)
    current = _tracked_ids(source, key)
    if document_id not in current:
        raise APIError(404, "not_found", "That document is not tracked by this project")
    _require_syncable(source, registry, allow_in_progress=True)
    source.config = {**source.config, key: [d for d in current if d != document_id]}
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="source.document_removed",
        actor_id=ctx.user.id,
        project_id=ctx.project.id,
        domain="integrations",
        payload={"source_id": str(source.id), "document_id": document_id},
    )
    job_id = await enqueue_sync(session, ctx, source, request, background_tasks, settings, response)
    await session.refresh(source)
    response.status_code = 202
    return envelope(
        {"job_id": job_id, "status": JobStatus.QUEUED.value, "source": serialize_source(source)}
    )


# --- sync dispatch (ADR-005) ---


async def _dispatch_sync(
    app: FastAPI,
    settings: Settings,
    background_tasks: BackgroundTasks,
    source_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    acting_user_id: uuid.UUID,
    inline_only: bool = False,
) -> None:
    # F3 (SOLUSDEV-100 T4b): the manual trigger's requesting user threads
    # through to `execute_source_sync` — the ONE call-site edit the EDA
    # family's live-bridge acquirer needs to resolve its scope.
    if settings.sync_inline:
        await _run_inline(app, source_id, job_id, acting_user_id=acting_user_id)
        return
    if inline_only:
        background_tasks.add_task(
            _run_inline, app, source_id, job_id, acting_user_id=acting_user_id
        )
        return
    if settings.redis_url:
        pool = await _arq_pool(app)
        await pool.enqueue_job("sync_source", str(source_id), str(job_id), str(acting_user_id))
        return
    background_tasks.add_task(_run_inline, app, source_id, job_id, acting_user_id=acting_user_id)


async def _run_inline(
    app: FastAPI, source_id: uuid.UUID, job_id: uuid.UUID, *, acting_user_id: uuid.UUID
) -> None:
    await execute_source_sync(
        sessionmaker=app.state.sessionmaker,
        registry=app.state.connector_registry,
        secret_store=app.state.secret_store,
        source_id=source_id,
        job_id=job_id,
        acting_user_id=acting_user_id,
        store=getattr(app.state, "integration_store", None),
        hub=getattr(app.state, "graph_hub", None),
    )


async def _arq_pool(app: FastAPI) -> Any:
    pool = getattr(app.state, "arq_pool", None)
    if pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(app.state.settings.redis_url))
        app.state.arq_pool = pool
    return pool
