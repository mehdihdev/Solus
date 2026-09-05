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
    Membership,
    Project,
    Role,
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
#: SOLUSDEV-242 (H2): the project-owned secret refs a claimed source retired,
#: kept on the source until they are actually deleted (after commit) so a
#: failed delete is retried rather than leaking a live token forever.
RETIRED_REFS_KEY = "retired_secret_refs"


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
    if access:
        connection.config = {**connection.config, "access": access}
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


# --------------------------------------------------------------- claiming legacy grants (H2)
#
# A source connected before I1 owns its token under a `source/…` ref and has no
# connection row. Moving it to ACCOUNT scope needs PROOF of whose account the
# token is — and `Source.created_by` is not that proof: the pre-I1 "switch
# account" path let any teammate complete a handshake on a row someone else
# created, so the row's creator and the token's owner can differ (security
# review C1). The only proof Solus holds is a handshake the caller completed:
# a CONNECTED connection whose `account_external_id` the provider vouched for.
#
# So a legacy source is CLAIMED, never adopted blind: when the caller's proven
# account matches the source's account, the source binds to that grant (and
# keeps syncing on it); otherwise the source keeps its own token, Home lists it
# as "sign in once to move it", and the claim happens when that sign-in lands.
# Nothing is copied — the source mirrors an existing grant — so no secret is
# ever written without a row that owns it, and nothing is widened: a source
# whose recorded access differs from the grant's is left alone and reported.


def _live_member_projects() -> Any:
    """Sources the caller may act on: a LIVE, non-viewer membership in the
    source's team and a project that still exists (security review C2)."""
    return (
        select(Source.id)
        .join(Project, Project.id == Source.project_id)
        .join(
            Membership,
            (Membership.team_id == Source.team_id) & (Membership.deleted_at.is_(None)),
        )
        .where(Project.deleted_at.is_(None), Membership.role != Role.VIEWER)
    )


def _own_token_sources(user: User) -> Any:
    """Unbound sources holding their own token for this caller's live projects."""
    return (
        select(Source)
        .where(
            Source.connection_id.is_(None),
            Source.secret_ref.is_not(None),
            Source.status.in_((SourceStatus.CONNECTED, SourceStatus.ERROR, SourceStatus.SYNCING)),
            Source.id.in_(_live_member_projects().where(Membership.user_id == user.id)),
        )
        .order_by(Source.created_at, Source.id)
    )


def _is_oauth_source(registry: ConnectorRegistry, source: Source) -> bool:
    if is_connection_owned(source.secret_ref):
        return False
    try:
        connector = registry.create(source.type.value)
    except UnknownConnectorError:
        return False
    return isinstance(connector, OAuthConnector)


async def legacy_sources(
    session: AsyncSession, registry: ConnectorRegistry, user: User
) -> list[Source]:
    """What Home lists as "sign in once to move it": the caller's OWN legacy
    grants by the only hint available (`created_by`), in projects the caller
    is a live member of. A hint decides what is SHOWN, never what is moved."""
    rows = (
        await session.scalars(_own_token_sources(user).where(Source.created_by == user.id))
    ).all()
    return [s for s in rows if _is_oauth_source(registry, s)]


def _access_of(row: AccountConnection | Source) -> str | None:
    access = row.config.get("access") if isinstance(row.config, dict) else None
    return access if isinstance(access, str) and access else None


async def claim_legacy_sources(
    session: AsyncSession,
    registry: ConnectorRegistry,
    user: User,
    connection: AccountConnection,
) -> tuple[list[Source], list[dict[str, Any]]]:
    """Bind every legacy source for the account `connection` PROVED to the
    connection — no sign-in, no copy, nothing widened.

    Returns (claimed, skipped). Skipped carries a reason: `access_mismatch` when
    both the source and the grant recorded an access mode and they differ —
    binding would silently widen (or break) that project, so the user must
    change it deliberately. The retired project-owned refs are recorded on the
    source; `sweep_retired_secrets` deletes them after the caller's commit.
    """
    if (
        connection.status is not ConnectionStatus.CONNECTED
        or not connection.secret_ref
        or not connection.account_external_id
    ):
        return [], []
    candidates = (
        await session.scalars(
            _own_token_sources(user)
            .where(
                Source.type == connection.provider,
                Source.account_external_id == connection.account_external_id,
            )
            # Serialise concurrent claims (two Home loads) on the same rows.
            .with_for_update()
        )
    ).all()
    claimed: list[Source] = []
    skipped: list[dict[str, Any]] = []
    grant_access = _access_of(connection)
    for source in candidates:
        if not _is_oauth_source(registry, source):
            continue
        source_access = _access_of(source)
        if source_access and grant_access and source_access != grant_access:
            skipped.append(
                {
                    "source_id": source.id,
                    "project_id": source.project_id,
                    "reason": "access_mismatch",
                }
            )
            continue
        old_ref = source.secret_ref
        assert old_ref is not None  # filtered by the query
        retired = [old_ref, refresh_secret_ref(old_ref), *hosted_refs(old_ref)]
        bind_source(source, connection)
        source.config = {**source.config, RETIRED_REFS_KEY: retired}
        claimed.append(source)
    if claimed:
        await session.flush()
    return claimed, skipped


async def sweep_retired_secrets(
    session: AsyncSession, secret_store: SecretStore, user: User
) -> int:
    """AFTER commit: delete the project-owned token copies that claims retired.
    Durable — the refs live on the source until the delete succeeds, so a
    failed delete is retried on the next call instead of leaking a live token.
    Best effort per ref; returns how many were removed."""
    rows = (
        await session.scalars(
            select(Source)
            .join(AccountConnection, AccountConnection.id == Source.connection_id)
            .where(AccountConnection.user_id == user.id)
        )
    ).all()
    removed = 0
    for source in rows:
        refs = source.config.get(RETIRED_REFS_KEY) if isinstance(source.config, dict) else None
        if not refs:
            continue
        remaining: list[str] = []
        for ref in refs:
            try:
                await secret_store.delete(ref)
                removed += 1
            except SecretNotFoundError:
                continue
            except Exception:  # noqa: BLE001 - a store outage must not lose the retry list
                remaining.append(ref)
        config = {k: v for k, v in source.config.items() if k != RETIRED_REFS_KEY}
        source.config = {**config, RETIRED_REFS_KEY: remaining} if remaining else config
    if rows:
        await session.commit()
    return removed


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
