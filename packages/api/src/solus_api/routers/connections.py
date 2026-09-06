"""§2.1 Connections — the signed-in user's ACCOUNT-scoped grants (SOLUSDEV-241 / I1).

Home (H2) binds an account once; Workspace (W2) attaches projects to it through
`POST /projects/{id}/sources` with a `connection_id`. Everything here is
owner-only: a connection belongs to the user who authorized it, and someone
else's connection is indistinguishable from a missing one (404, §7).

The document listing is served from the integration cache — zero provider
calls after the first — and moves only on an explicit `refresh` or a webhook
doorbell. A refresh spends the account's quota, so it is metered like the
picker and gated on a verified user.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from solus_api.connectors.registry import ConnectorContext, UnknownConnectorError
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    CurrentUser,
    IntegrationCacheDep,
    RegistryDep,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
)
from solus_api.models import ConnectionStatus, Project
from solus_api.schemas import AdoptRequest, serialize_connection, serialize_legacy_connection
from solus_api.services.activity import record_activity
from solus_api.services.connections import (
    account_ref_for,
    claim_legacy_sources,
    claimable_connections,
    connection_projects,
    legacy_sources,
    list_documents,
    list_live_connections,
    named_legacy_sources,
    owned_connection,
    revoke_connection,
    sweep_after_commit,
)
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/users/me/connections")


@router.get("")
async def list_connections(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    connections = await list_live_connections(session, user)
    projects = await connection_projects(session, [c.id for c in connections])
    return envelope([serialize_connection(c, projects.get(c.id)) for c in connections])


@router.get("/legacy")
async def list_legacy(
    user: CurrentUser, session: SessionDep, registry: RegistryDep
) -> dict[str, Any]:
    """The caller's project-scoped grants from before account-level connections
    that are not yet at account scope (SOLUSDEV-242 / H2). Home lists them as
    "sign in once to move it" — or, when the caller already holds the proving
    grant, offers the confirmed move. Nothing here is a usable grant."""
    rows = await legacy_sources(session, registry, user)
    names: dict[uuid.UUID, str] = {}
    if rows:
        found = await session.execute(
            select(Project.id, Project.name).where(Project.id.in_({r.project_id for r in rows}))
        )
        names = {project_id: name for project_id, name in found.all()}
    proving = await claimable_connections(session, user, rows)
    groups: dict[tuple[str, str], list[Any]] = {}
    for source in rows:
        key = (source.type.value, source.account_external_id or f"source:{source.id}")
        groups.setdefault(key, []).append(source)
    return envelope(
        [
            serialize_legacy_connection(
                provider,
                sources[0].account_login,
                sources,
                names,
                next((proving[s.id].id for s in sources if s.id in proving), None),
            )
            for (provider, _), sources in groups.items()
        ]
    )


@router.post("/adopt")
async def adopt(
    body: AdoptRequest,
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    registry: RegistryDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    """Move the NAMED legacy grants to the caller's account (SOLUSDEV-242 / H2)
    — explicit and confirmed by the caller, only for an account they have
    PROVED with a CONNECTED connection of their own, only in live projects they
    are a non-viewer member of. The source mirrors the grant (no copied secret,
    the project keeps syncing); nothing widens without `confirm_access`. The
    project-owned token family is swept after the commit."""
    wanted = set(body.source_ids)
    legacy = await named_legacy_sources(session, registry, user, wanted)
    proving = await claimable_connections(session, user, legacy)
    by_connection: dict[uuid.UUID, set[uuid.UUID]] = {}
    for source in legacy:
        connection = proving.get(source.id)
        if connection is not None:
            by_connection.setdefault(connection.id, set()).add(source.id)
    adopted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for connection in await list_live_connections(session, user):
        ids = by_connection.get(connection.id)
        if not ids:
            continue
        claimed, rejected = await claim_legacy_sources(
            session, registry, user, connection, ids, confirm_access=body.confirm_access
        )
        skipped.extend(rejected)
        for source in claimed:
            record_activity(
                session,
                team_id=source.team_id,
                activity_type="connection.adopted",
                actor_id=user.id,
                project_id=source.project_id,
                domain="integrations",
                payload={"provider": connection.provider.value},
            )
            adopted.append(
                {
                    "connection_id": connection.id,
                    "provider": connection.provider.value,
                    "source_id": source.id,
                    "project_id": source.project_id,
                }
            )
    # Every requested id is accounted for — including one whose grant was
    # revoked between the listing and the locked claim (code review).
    accounted = {a["source_id"] for a in adopted} | {x["source_id"] for x in skipped}
    skipped.extend(
        {"source_id": sid, "project_id": None, "reason": "not_claimable"}
        for sid in sorted(wanted - accounted, key=str)
    )
    if adopted:
        emit_event(
            session,
            user=user,
            event_type="connection.adopted",
            payload={"sources": len(adopted), "skipped": len(skipped)},
        )
    await session.commit()
    await sweep_after_commit(session, secret_store, user)
    return envelope({"adopted": adopted, "skipped": skipped})


@router.get("/{connection_id}")
async def get_connection(
    connection_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    connection = await owned_connection(session, user, connection_id)
    projects = await connection_projects(session, [connection.id])
    return envelope(serialize_connection(connection, projects.get(connection.id)))


@router.delete("/{connection_id}")
async def revoke(
    connection_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    cache: IntegrationCacheDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    """Revoke the grant. Every source bound to it, in EVERY project, is
    disconnected — the honest consequence of the token being gone, and what the
    app's confirmation says before the user clicks."""
    connection = await owned_connection(session, user, connection_id)
    affected = await connection_projects(session, [connection.id])
    disconnected = await revoke_connection(session, secret_store, connection, cache)
    for project in affected.get(connection.id, []):
        record_activity(
            session,
            team_id=project["team_id"],
            activity_type="connection.revoked",
            actor_id=user.id,
            project_id=project["project_id"],
            domain="integrations",
            payload={"provider": connection.provider.value},
        )
    emit_event(
        session,
        user=user,
        event_type="connection.revoked",
        payload={"provider": connection.provider.value, "disconnected_sources": disconnected},
    )
    await session.commit()
    return envelope({"id": connection_id, "disconnected_sources": disconnected})


@router.get("/{connection_id}/documents")
async def documents(
    connection_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    registry: RegistryDep,
    secret_store: SecretStoreDep,
    cache: IntegrationCacheDep,
    _verified: RequireVerified,
    refresh: Annotated[bool, Query()] = False,
    cache_only: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """What the account can reach: documents for a CAD tool, repositories for a
    code host. Served from the cache; `refresh=true` asks the provider again."""
    connection = await owned_connection(session, user, connection_id)
    if connection.status is not ConnectionStatus.CONNECTED or not connection.secret_ref:
        raise APIError(409, "not_connected", "This account is not connected")
    provider = connection.provider.value
    account_ref = account_ref_for(connection)
    try:
        connector = registry.create_scoped(
            provider, ConnectorContext(acting_user_id=user.id, account_ref=account_ref)
        )
    except UnknownConnectorError as exc:
        raise APIError(400, "connector_unavailable", f"No connector for '{provider}'") from exc
    fetched = await list_documents(
        cache,
        connector=connector,
        secret_store=secret_store,
        secret_ref=connection.secret_ref,
        provider=provider,
        account_ref=account_ref,
        refresh=refresh,
        cache_only=cache_only,
    )
    return envelope(
        fetched.value, meta={"cached": fetched.cached, "fetched_at": fetched.fetched_at}
    )
