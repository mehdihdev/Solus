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
from solus_api.models import ConnectionStatus
from solus_api.schemas import serialize_connection
from solus_api.services.activity import record_activity
from solus_api.services.connections import (
    account_ref_for,
    adopt_legacy_sources,
    connection_projects,
    delete_retired_secrets,
    list_documents,
    list_live_connections,
    owned_connection,
    revoke_connection,
)
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/users/me/connections")


@router.get("")
async def list_connections(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    connections = await list_live_connections(session, user)
    projects = await connection_projects(session, [c.id for c in connections])
    return envelope([serialize_connection(c, projects.get(c.id)) for c in connections])


@router.post("/adopt")
async def adopt(
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    registry: RegistryDep,
) -> dict[str, Any]:
    """Move the caller's project-scoped OAuth grants to account scope
    (SOLUSDEV-242 / HOME H2) — no sign-in, no widened scope. Idempotent; Home
    calls it before listing. The project-owned token copies are deleted only
    after the commit, so a failure leaves every project exactly as it was."""
    adopted, retired = await adopt_legacy_sources(session, secret_store, registry, user)
    for item in adopted:
        record_activity(
            session,
            team_id=item["team_id"],
            activity_type="connection.adopted",
            actor_id=user.id,
            project_id=item["project_id"],
            domain="integrations",
            payload={"provider": item["provider"]},
        )
    if adopted:
        emit_event(
            session,
            user=user,
            event_type="connection.adopted",
            payload={
                "sources": len(adopted),
                "connections": len({str(a["connection_id"]) for a in adopted}),
                "needs_reauth": sum(1 for a in adopted if a["needs_reauth"]),
            },
        )
    await session.commit()
    await delete_retired_secrets(secret_store, retired)
    return envelope(
        {
            "adopted": [
                {
                    "connection_id": item["connection_id"],
                    "provider": item["provider"],
                    "source_id": item["source_id"],
                    "project_id": item["project_id"],
                    "needs_reauth": item["needs_reauth"],
                }
                for item in adopted
            ]
        }
    )


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
    )
    return envelope(
        fetched.value, meta={"cached": fetched.cached, "fetched_at": fetched.fetched_at}
    )
