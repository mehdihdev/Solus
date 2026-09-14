"""Account authority and race-safe OAuth lifecycle for hosted add-ons."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.tools.remote_mcp import RemoteAuthError, RemoteMCPSpec
from solus_api.connectors import hosted_oauth
from solus_api.connectors.secrets import SecretStore
from solus_api.core.errors import APIError
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    OAuthState,
    Source,
    User,
    ensure_utc,
    utcnow,
)
from solus_api.services.events import emit_event


async def connected_account(
    session: AsyncSession,
    connection_id: uuid.UUID,
    spec: RemoteMCPSpec,
    *,
    owner_id: uuid.UUID | None = None,
    lock: bool = False,
) -> AccountConnection:
    query = select(AccountConnection).where(AccountConnection.id == connection_id)
    if lock:
        query = query.with_for_update()
    connection = await session.scalar(query.execution_options(populate_existing=True))
    if (
        connection is None
        or connection.status is not ConnectionStatus.CONNECTED
        or not connection.secret_ref
        or (owner_id is not None and connection.user_id != owner_id)
    ):
        raise APIError(404, "not_found", "Connected account not found")
    if connection.provider is not spec.source_type:
        raise APIError(400, "wrong_source_type", "This add-on does not support this account")
    return connection


async def source_account(
    session: AsyncSession,
    source: Source,
    spec: RemoteMCPSpec,
    *,
    owner_id: uuid.UUID | None = None,
) -> AccountConnection | None:
    if source.connection_id is None:
        return None
    return await connected_account(session, source.connection_id, spec, owner_id=owner_id)


async def consume_state(
    session: AsyncSession,
    *,
    state: str,
    user_id: uuid.UUID,
    server: str,
    connection_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
) -> tuple[str, str]:
    """Commit an atomic claim before remote I/O; concurrent replays lose it."""
    record = (
        await session.execute(
            delete(OAuthState)
            .where(
                OAuthState.state == state,
                OAuthState.user_id == user_id,
                OAuthState.provider == f"hosted:{server}",
                OAuthState.connection_id == connection_id,
                OAuthState.source_id == source_id,
            )
            .returning(OAuthState.code_verifier, OAuthState.redirect_uri, OAuthState.expires_at)
        )
    ).one_or_none()
    await session.commit()
    if record is None:
        raise APIError(404, "invalid_state", "Unknown or expired sign-in")
    if ensure_utc(record.expires_at) < utcnow() or not record.code_verifier:
        raise APIError(400, "expired_state", "This sign-in expired; start it again")
    return record.code_verifier, record.redirect_uri


async def start(
    session: AsyncSession,
    user: User,
    connection: AccountConnection,
    spec: RemoteMCPSpec,
    secret_store: SecretStore,
) -> dict[str, Any]:
    from solus_api.routers.hosted import STATE_TTL_MINUTES

    redirect_uri = hosted_oauth.registered_redirect_uri(spec)
    try:
        client = await hosted_oauth.ensure_client(secret_store, spec, redirect_uri=redirect_uri)
    except RemoteAuthError as exc:
        raise APIError(502, exc.code, exc.message) from exc
    connection = await connected_account(session, connection.id, spec, owner_id=user.id, lock=True)
    state = secrets.token_urlsafe(32)
    verifier, challenge = hosted_oauth.new_pkce()
    session.add(
        OAuthState(
            state=state,
            provider=f"hosted:{spec.name}",
            connection_id=connection.id,
            user_id=user.id,
            redirect_uri=redirect_uri,
            code_verifier=verifier,
            expires_at=utcnow() + timedelta(minutes=STATE_TTL_MINUTES),
        )
    )
    emit_event(
        session,
        user=user,
        event_type="connection.hosted_oauth_started",
        payload={"server": spec.name},
    )
    await session.commit()
    return {
        "authorize_url": hosted_oauth.authorize_url(
            spec, client, state=state, code_challenge=challenge, redirect_uri=redirect_uri
        ),
        "state": state,
        "redirect_uri": redirect_uri,
        "notice": spec.connect_notice,
    }


async def probe(
    session: AsyncSession,
    user: User,
    connection: AccountConnection,
    spec: RemoteMCPSpec,
    secret_store: SecretStore,
) -> dict[str, Any]:
    from solus_api.routers.hosted import _record_probe

    # The lock also fences token refresh performed by the probe from revoke.
    connection = await connected_account(session, connection.id, spec, owner_id=user.id, lock=True)
    return await _record_probe(session, connection, spec, secret_store)


async def exchange(
    session: AsyncSession,
    user: User,
    connection: AccountConnection,
    spec: RemoteMCPSpec,
    secret_store: SecretStore,
    *,
    state: str,
    code: str,
) -> dict[str, Any]:
    from solus_api.routers.hosted import _record_probe

    connection_id = connection.id
    verifier, redirect_uri = await consume_state(
        session,
        state=state,
        user_id=user.id,
        server=spec.name,
        connection_id=connection_id,
    )
    try:
        client = await hosted_oauth.ensure_client(secret_store, spec, redirect_uri=redirect_uri)
        token = await hosted_oauth.exchange_code(
            spec, client, code=code, code_verifier=verifier, redirect_uri=redirect_uri
        )
    except RemoteAuthError as exc:
        raise APIError(400, exc.code, exc.message) from exc
    # No grant may land if revoke won while the token endpoint was in flight.
    connection = await connected_account(session, connection_id, spec, owner_id=user.id, lock=True)
    await secret_store.put(
        hosted_oauth.token_secret_ref(connection.secret_ref or "", spec.name), token.to_json()
    )
    emit_event(
        session, user=user, event_type="connection.hosted_connected", payload={"server": spec.name}
    )
    return await _record_probe(session, connection, spec, secret_store)
