"""Account-scoped connections (SOLUSDEV-241 / I1) — the service layer.

OAuth binds at ACCOUNT scope: the grant is one `AccountConnection` row owned by
the user who authorized, and a project attaches to it through a `Source` that
MIRRORS the connection's secret ref. Everything that resolves credentials
therefore keeps reading `Source.secret_ref`; what changes is who OWNS the
secret, and that ownership rule lives here in one place:

* `connection/{id}/{provider}` refs are the connection's. A source disconnect
  or a project teardown leaves them alone (`is_connection_owned`); revoking the
  connection deletes them and disconnects every bound source.
* every other ref is the source's own, deleted with the source as before.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import (
    AccountInfo,
    Connector,
    ConnectorError,
    Credentials,
    OAuthConnector,
)
from solus_api.connectors.hosted_oauth import hosted_refs
from solus_api.connectors.integration_cache import Fetched, IntegrationCache
from solus_api.connectors.registry import ConnectorRegistry, UnknownConnectorError
from solus_api.connectors.runtime import (
    call_with_refresh,
    connector_error_payload,
    refresh_secret_ref,
    resolve_credentials,
)
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.core.errors import APIError
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
    User,
    ensure_utc,
    utcnow,
)


class StaleHandshakeError(Exception):
    """A completion arrived for a connection that already completed. The state
    that carried it was minted before another state for the same pending row
    finished, and honouring it would re-point a CONNECTED account at whatever
    account the browser happened to authorize second."""


CONNECTION_REF_PREFIX = "connection/"
#: A PENDING connection older than this is a handshake nobody finished; it is
#: neither listed nor reused, and the next start mints a fresh one.
PENDING_CONNECTION_TTL = timedelta(minutes=10)
#: `config` keys the H2 surface reads (SOLUSDEV-242): where the grant came
#: from, and why it still asks for a sign-in. Never secret material.
ORIGIN_KEY = "origin"
NEEDS_REAUTH_KEY = "needs_reauth"
#: The legacy source never recorded which access mode its token was granted
#: (pre SOLUS-ONS-A2), so Solus cannot say what it may do — only a fresh consent
#: can. The token keeps working meanwhile; nothing is widened silently.
REAUTH_ACCESS_UNKNOWN = "access_unknown"


def connection_secret_ref(connection_id: uuid.UUID, provider: str) -> str:
    """THE one definition of where a connection's credential lives. The refresh
    token (`runtime.refresh_secret_ref`) and hosted add-on grants
    (`hosted_oauth.token_secret_ref`) derive from it, so a source that mirrors
    this ref inherits the whole family."""
    return f"{CONNECTION_REF_PREFIX}{connection_id}/{provider}"


def is_connection_owned(secret_ref: str | None) -> bool:
    return bool(secret_ref) and str(secret_ref).startswith(CONNECTION_REF_PREFIX)


def account_ref_for(row: AccountConnection | Source) -> str:
    """The identity the integration cache keys on. The provider's account id when
    the grant proved one; otherwise the row itself, so an unidentified account can
    never share entries with another."""
    if row.account_external_id:
        return row.account_external_id
    prefix = "connection" if isinstance(row, AccountConnection) else "source"
    return f"{prefix}:{row.id}"


# --------------------------------------------------------------- lookup


async def owned_connection(
    session: AsyncSession, user: User, connection_id: uuid.UUID
) -> AccountConnection:
    """The caller's own, live connection — or 404. Someone else's connection is
    indistinguishable from a missing one (no existence leak, §7)."""
    connection = await session.get(AccountConnection, connection_id)
    if (
        connection is None
        or connection.user_id != user.id
        or connection.status is ConnectionStatus.REVOKED
    ):
        raise APIError(404, "not_found", "Connection not found")
    return connection


async def list_live_connections(session: AsyncSession, user: User) -> list[AccountConnection]:
    """The user's accounts as Home shows them. A PENDING row is handshake
    scaffolding, not an account, and a REVOKED one is history — neither lists."""
    return list(
        (
            await session.scalars(
                select(AccountConnection)
                .where(
                    AccountConnection.user_id == user.id,
                    AccountConnection.status.in_(
                        (ConnectionStatus.CONNECTED, ConnectionStatus.ERROR)
                    ),
                )
                .order_by(AccountConnection.created_at, AccountConnection.id)
            )
        ).all()
    )


async def connection_projects(
    session: AsyncSession, connection_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Which projects use each connection — for "used in N projects" and for the
    revoke confirmation, which must say what it is about to disconnect."""
    if not connection_ids:
        return {}
    rows = (
        await session.execute(
            select(Source.connection_id, Project.id, Project.name, Project.team_id)
            .join(Project, Project.id == Source.project_id)
            .where(
                Source.connection_id.in_(connection_ids),
                Source.status != SourceStatus.DISCONNECTED,
                Project.deleted_at.is_(None),
            )
            .order_by(Source.created_at, Source.id)
        )
    ).all()
    out: dict[uuid.UUID, list[dict[str, Any]]] = {cid: [] for cid in connection_ids}
    for connection_id, project_id, name, team_id in rows:
        out[connection_id].append({"project_id": project_id, "name": name, "team_id": team_id})
    return out


# --------------------------------------------------------------- the handshake


async def pending_connection(
    session: AsyncSession, user: User, provider: SourceType
) -> AccountConnection:
    """The PENDING connection an oauth/start attaches its state to. A recent,
    unfinished attempt is reused so retries do not pile up rows."""
    cutoff = utcnow() - PENDING_CONNECTION_TTL
    existing = (
        await session.scalars(
            select(AccountConnection)
            .where(
                AccountConnection.user_id == user.id,
                AccountConnection.provider == provider,
                AccountConnection.status == ConnectionStatus.PENDING,
            )
            .order_by(AccountConnection.created_at.desc())
            .limit(1)
        )
    ).first()
    if existing is not None and ensure_utc(existing.created_at) >= cutoff:
        return existing
    # A failed attempt that never proved an identity is a retry target, not a
    # second row on Home.
    failed = (
        await session.scalars(
            select(AccountConnection)
            .where(
                AccountConnection.user_id == user.id,
                AccountConnection.provider == provider,
                AccountConnection.status == ConnectionStatus.ERROR,
                AccountConnection.account_external_id.is_(None),
            )
            .order_by(AccountConnection.created_at.desc())
            .limit(1)
        )
    ).first()
    if failed is not None:
        failed.status = ConnectionStatus.PENDING
        failed.last_error = None
        await session.flush()
        return failed
    connection = AccountConnection(
        user_id=user.id, provider=provider, status=ConnectionStatus.PENDING
    )
    session.add(connection)
    await session.flush()
    return connection


async def complete_connection(
    session: AsyncSession,
    secret_store: SecretStore,
    pending: AccountConnection,
    *,
    provider: str,
    creds: Credentials,
    account: AccountInfo,
    access: str | None,
) -> AccountConnection:
    """Land a finished handshake on the account it proved.

    Re-authorizing an account the user already connected must NOT mint a second
    row: the sources bound to the first one mirror ITS ref, so the rotated token
    is written under that ref and the pending row is discarded. Any other
    outcome would strand every project on a token the provider just replaced.

    Two invariants hold the identity still (security review C1):

    * only a PENDING row may complete — a state whose row already completed is
      a superseded handshake and is refused, never allowed to overwrite the
      account a bound source already mirrors;
    * every source bound to the landing row is re-mirrored from it, so a
      mirror can never diverge from its connection by construction.
    """
    if pending.status is not ConnectionStatus.PENDING:
        raise StaleHandshakeError(str(pending.id))
    existing = (
        await session.scalars(
            select(AccountConnection).where(
                AccountConnection.user_id == pending.user_id,
                AccountConnection.provider == pending.provider,
                AccountConnection.account_external_id == account.external_id,
                AccountConnection.status != ConnectionStatus.REVOKED,
                AccountConnection.id != pending.id,
            )
        )
    ).first()
    connection = existing if existing is not None else pending
    if existing is not None:
        await session.delete(pending)
    secret_ref = connection_secret_ref(connection.id, provider)
    await secret_store.put(secret_ref, creds.token)
    if creds.refresh_token:
        await secret_store.put(refresh_secret_ref(secret_ref), creds.refresh_token)
    connection.secret_ref = secret_ref
    connection.status = ConnectionStatus.CONNECTED
    connection.account_login = account.login
    connection.account_external_id = account.external_id
    connection.last_error = None
    # A finished handshake IS the re-consent a migrated grant may have asked
    # for (SOLUSDEV-242 / H2): the flag clears, and the chosen access is the
    # recorded one.
    config = {k: v for k, v in connection.config.items() if k != NEEDS_REAUTH_KEY}
    connection.config = {**config, "access": access} if access else config
    await session.flush()
    await remirror_sources(session, connection)
    return connection


async def remirror_sources(session: AsyncSession, connection: AccountConnection) -> None:
    """Every source bound to `connection` carries exactly its ref and identity."""
    bound = (
        await session.scalars(select(Source).where(Source.connection_id == connection.id))
    ).all()
    for source in bound:
        bind_source(source, connection)
    if bound:
        await session.flush()


def record_connection_failure(connection: AccountConnection, exc: ConnectorError) -> None:
    connection.status = ConnectionStatus.ERROR
    connection.last_error = connector_error_payload(exc)


# --------------------------------------------------------------- binding


def bind_source(source: Source, connection: AccountConnection) -> None:
    """Attach a project source to an account. The source MIRRORS the connection's
    ref and identity so every existing credential path is unchanged."""
    source.connection_id = connection.id
    source.secret_ref = connection.secret_ref
    source.account_login = connection.account_login
    source.account_external_id = connection.account_external_id
    source.status = SourceStatus.CONNECTED
    source.last_error = None
    access = connection.config.get("access") if isinstance(connection.config, dict) else None
    if access:
        source.config = {**source.config, "access": access}


async def reusable_source(
    session: AsyncSession, project: Project, source_type: SourceType, connector: Connector
) -> Source | None:
    """The source a (re)connect should REUSE in this project, or None for a new one.

    Whether a second source is meaningful is the CONNECTOR's business, read from
    the `selection` it declares: account-level (`multi` — Onshape and every CAD
    tool after it) means one source per provider per project, so reuse it —
    which doubles as "switch account". Item-level (`single` — a code host names
    ONE repository) legitimately has several. No selection: create every time.
    """
    selection = getattr(connector, "selection", None)
    if not isinstance(selection, dict) or selection.get("mode") != "multi":
        return None
    return (
        await session.scalars(
            select(Source)
            .where(
                Source.project_id == project.id,
                Source.type == source_type,
                Source.status != SourceStatus.DISCONNECTED,
            )
            .order_by(Source.created_at)
            .limit(1)
        )
    ).first()


# --------------------------------------------------------------- revocation


async def delete_connection_secrets(
    secret_store: SecretStore, connection: AccountConnection
) -> None:
    """Every credential the grant owns: the access token, its refresh token, and
    any hosted add-on token derived from the same ref. Shared by revoke and by
    account deletion so neither can leave a live grant behind."""
    ref = connection.secret_ref
    if not ref:
        return
    await secret_store.delete(ref)
    await secret_store.delete(refresh_secret_ref(ref))
    for hosted_ref in hosted_refs(ref):
        await secret_store.delete(hosted_ref)


async def revoke_connection(
    session: AsyncSession,
    secret_store: SecretStore,
    connection: AccountConnection,
    cache: IntegrationCache | None = None,
) -> int:
    """Revoke the grant: delete its secrets, mark it REVOKED, disconnect every
    source bound to it in every project, and drop the account's cached
    listings/exports (derived copies of the customer's CAD must not outlive the
    grant). Returns how many sources were cut off."""
    await delete_connection_secrets(secret_store, connection)
    if cache is not None:
        await cache.invalidate_account(connection.provider.value, account_ref_for(connection))
    bound = (
        await session.scalars(select(Source).where(Source.connection_id == connection.id))
    ).all()
    for source in bound:
        source.status = SourceStatus.DISCONNECTED
        source.secret_ref = None
        source.connection_id = None
        source.last_error = {"code": "connection_revoked", "message": "The account was revoked"}
    connection.status = ConnectionStatus.REVOKED
    connection.secret_ref = None
    await session.flush()
    return len(bound)


# --------------------------------------------------------------- adoption (H2)


async def _existing_live_connection(
    session: AsyncSession, user: User, provider: SourceType, external_id: str | None
) -> AccountConnection | None:
    if not external_id:
        return None
    return (
        await session.scalars(
            select(AccountConnection).where(
                AccountConnection.user_id == user.id,
                AccountConnection.provider == provider,
                AccountConnection.account_external_id == external_id,
                AccountConnection.status != ConnectionStatus.REVOKED,
            )
        )
    ).first()


async def _legacy_oauth_sources(
    session: AsyncSession, registry: ConnectorRegistry, user: User
) -> list[Source]:
    """The caller's own project-scoped OAuth grants: sources that carry their own
    token (a `source/…` ref, no connection) for a provider whose connector is
    OAuth. Token-connected (PAT) sources use the same ref shape, so the connector
    alone cannot tell them apart — but a PAT is a personal token the user chose
    to give ONE project, and it is adopted too: it is still the user's
    account-wide credential for that provider."""
    rows = (
        await session.scalars(
            select(Source)
            .where(
                Source.created_by == user.id,
                Source.connection_id.is_(None),
                Source.secret_ref.is_not(None),
                Source.status.in_(
                    (SourceStatus.CONNECTED, SourceStatus.ERROR, SourceStatus.SYNCING)
                ),
            )
            .order_by(Source.created_at, Source.id)
        )
    ).all()
    adoptable: list[Source] = []
    for source in rows:
        if is_connection_owned(source.secret_ref):
            continue
        try:
            connector = registry.create(source.type.value)
        except UnknownConnectorError:
            continue
        if isinstance(connector, OAuthConnector):
            adoptable.append(source)
    return adoptable


async def _copy_secret_family(
    secret_store: SecretStore, old_ref: str, new_ref: str
) -> list[str] | None:
    """Copy the access token, its refresh token and any hosted add-on grants
    from the source's ref family to the connection's. Returns the OLD refs that
    now hold duplicates (for the caller to delete AFTER commit), or None when
    the access token itself is missing — nothing to move, nothing to adopt."""
    try:
        token = await secret_store.get(old_ref)
    except SecretNotFoundError:
        return None
    await secret_store.put(new_ref, token)
    moved = [old_ref]
    try:
        refresh = await secret_store.get(refresh_secret_ref(old_ref))
    except SecretNotFoundError:
        refresh = None
    if refresh is not None:
        await secret_store.put(refresh_secret_ref(new_ref), refresh)
        moved.append(refresh_secret_ref(old_ref))
    for old_hosted, new_hosted in zip(hosted_refs(old_ref), hosted_refs(new_ref), strict=True):
        try:
            grant = await secret_store.get(old_hosted)
        except SecretNotFoundError:
            continue
        await secret_store.put(new_hosted, grant)
        moved.append(old_hosted)
    return moved


async def adopt_legacy_sources(
    session: AsyncSession,
    secret_store: SecretStore,
    registry: ConnectorRegistry,
    user: User,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Move the caller's project-scoped OAuth grants to ACCOUNT scope
    (SOLUSDEV-242 / HOME H2) without a sign-in.

    For each legacy source the caller authorized, the stored token is copied
    to a connection the source then MIRRORS (`bind_source`), so every credential
    path is unchanged and the project keeps syncing. An account the caller has
    since connected on Home is reused — the source lands on that grant rather
    than minting a second row for the same account. Nothing is widened: the
    connection records the access mode the source recorded, and when the source
    never recorded one the connection is flagged `needs_reauth=access_unknown`
    and Home says so; the token keeps working until the user re-consents.

    Idempotent. Returns what was adopted and the OLD secret refs, which the
    caller deletes only AFTER its commit — a failed commit must leave the
    project's own token exactly where it was.
    """
    adopted: list[dict[str, Any]] = []
    old_refs: list[str] = []
    for source in await _legacy_oauth_sources(session, registry, user):
        provider = source.type.value
        assert source.secret_ref is not None  # filtered above
        existing = await _existing_live_connection(
            session, user, source.type, source.account_external_id
        )
        if existing is not None and existing.secret_ref:
            connection = existing
            # The account's CURRENT grant wins; the project's own copy is retired.
            old_refs.append(source.secret_ref)
            old_refs.append(refresh_secret_ref(source.secret_ref))
            old_refs.extend(hosted_refs(source.secret_ref))
        else:
            access = source.config.get("access") if isinstance(source.config, dict) else None
            config: dict[str, Any] = {ORIGIN_KEY: "migrated"}
            if isinstance(access, str) and access:
                config["access"] = access
            else:
                config[NEEDS_REAUTH_KEY] = REAUTH_ACCESS_UNKNOWN
            connection = existing or AccountConnection(
                user_id=user.id,
                provider=source.type,
                status=ConnectionStatus.CONNECTED,
                account_login=source.account_login,
                account_external_id=source.account_external_id,
                config=config,
            )
            if existing is None:
                session.add(connection)
                await session.flush()
            new_ref = connection_secret_ref(connection.id, provider)
            moved = await _copy_secret_family(secret_store, source.secret_ref, new_ref)
            if moved is None:
                # No token to move: the source is already broken and its own
                # page says so. Leave it; do not mint an empty grant.
                if existing is None:
                    await session.delete(connection)
                    await session.flush()
                continue
            connection.secret_ref = new_ref
            connection.status = ConnectionStatus.CONNECTED
            connection.last_error = None
            old_refs.extend(moved)
        bind_source(source, connection)
        adopted.append(
            {
                "connection_id": connection.id,
                "provider": provider,
                "source_id": source.id,
                "project_id": source.project_id,
                "team_id": source.team_id,
                "needs_reauth": connection.config.get(NEEDS_REAUTH_KEY),
            }
        )
    if adopted:
        await session.flush()
    return adopted, old_refs


async def delete_retired_secrets(secret_store: SecretStore, refs: list[str]) -> None:
    """Best effort, AFTER commit: drop the project-owned copies adoption retired.
    A ref that was never there is not an error."""
    for ref in refs:
        try:
            await secret_store.delete(ref)
        except SecretNotFoundError:
            continue


# --------------------------------------------------------------- the listing


async def list_documents(
    cache: IntegrationCache,
    *,
    connector: Connector,
    secret_store: SecretStore,
    secret_ref: str,
    provider: str,
    account_ref: str,
    refresh: bool = False,
) -> Fetched[list[dict[str, Any]]]:
    """An account's selectable documents/repositories, from the cache.

    Costs zero provider calls after the first: the listing is refreshed only by
    an explicit `refresh` or a webhook doorbell (`invalidate_listing`), never by
    a timer. The fetch goes through the credential-refresh path, so an expired
    access token refreshes rather than 502s.
    """
    lister: Callable[[Credentials], Awaitable[list[dict[str, Any]]]] | None = getattr(
        connector, "list_selectable", None
    )
    if lister is None:
        raise APIError(400, "unsupported", "This provider has nothing to select")

    async def fetch() -> list[dict[str, Any]]:
        credentials = await resolve_credentials(secret_store, secret_ref)
        try:
            return await call_with_refresh(
                connector=connector,
                credentials=credentials,
                secret_store=secret_store,
                secret_ref=secret_ref,
                run=lister,
            )
        except ConnectorError as exc:
            raise APIError(502, exc.code, exc.message) from exc

    return await cache.fetch(
        cache.listing_key(provider, account_ref),
        ttl_seconds=cache.listing_ttl_seconds,
        fetch=fetch,
        refresh=refresh,
        # The refresh cooldown: one walk per window per ACCOUNT, whoever asks.
        min_age_seconds=cache.listing_refresh_cooldown_seconds,
    )


async def invalidate_listing(cache: IntegrationCache, *, provider: str, account_ref: str) -> None:
    await cache.invalidate(cache.listing_key(provider, account_ref))
