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

import logging
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
from solus_api.connectors.secrets import SecretStore
from solus_api.core.errors import APIError
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    Membership,
    MembershipStatus,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    User,
    ensure_utc,
    utcnow,
)

logger = logging.getLogger("solus.connections")


class StaleHandshakeError(Exception):
    """A completion arrived for a connection that already completed. The state
    that carried it was minted before another state for the same pending row
    finished, and honouring it would re-point a CONNECTED account at whatever
    account the browser happened to authorize second."""


CONNECTION_REF_PREFIX = "connection/"
#: A PENDING connection older than this is a handshake nobody finished; it is
#: neither listed nor reused, and the next start mints a fresh one.
PENDING_CONNECTION_TTL = timedelta(minutes=10)
#: SOLUSDEV-242 (H2): a claimed source still has its OLD project-owned token
#: family to delete. The marker is an underscore key — never patchable, never
#: serialized (routers/sources.py, schemas.serialize_source) — and it names NO
#: ref: the family is derived from the source's own id, so nothing a member
#: writes can ever point the sweep at another secret (security review C-NEW-1).
RETIRE_MARKER_KEY = "_legacy_secrets_retire"
#: Sources swept per call: the remainder is the next call's work (documented
#: retry semantics), so an outage spanning many claims never makes one
#: request pay for all of them.
SWEEP_BATCH = 200
#: Hosted add-on state the source recorded for a grant that the sweep deletes
#: (agent/tools/hosted_tools.py STATE_KEY / INVENTORY_KEY): stale after a move.
_HOSTED_STATE_KEYS = ("hosted", "_hosted")


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
            select(
                Source.connection_id, Project.id, Project.name, Project.team_id, Source.last_error
            )
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
    for connection_id, project_id, name, team_id, last_error in rows:
        # SOLUSDEV-244 (H4): the source's last sync error code rides along so
        # health can tell "the provider rejected this grant" from "healthy".
        code = last_error.get("code") if isinstance(last_error, dict) else None
        out[connection_id].append(
            {"project_id": project_id, "name": name, "team_id": team_id, "error_code": code}
        )
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


def bind_source(
    source: Source, connection: AccountConnection, *, preserve_state: bool = False
) -> None:
    """Attach a project source to an account. The source MIRRORS the connection's
    ref and identity so every existing credential path is unchanged."""
    source.connection_id = connection.id
    source.secret_ref = connection.secret_ref
    source.account_login = connection.account_login
    source.account_external_id = connection.account_external_id
    if not preserve_state:
        source.status = SourceStatus.CONNECTED
        source.last_error = None
    access = connection.config.get("access") if isinstance(connection.config, dict) else None
    if access:
        source.config = {**source.config, "access": access}


async def reusable_source(
    session: AsyncSession,
    project: Project,
    source_type: SourceType,
    connector: Connector,
    *,
    connection: AccountConnection | None = None,
    config: dict[str, Any] | None = None,
    pending_user_id: uuid.UUID | None = None,
) -> Source | None:
    """Reuse only the same grant and repository selection; never switch accounts.

    A legacy unbound source may be adopted when its known provider identity
    matches. Before an OAuth exchange the account is unknown, so nothing is
    safely reusable. Project locking serializes concurrent first attachments.
    """
    selection = getattr(connector, "selection", None)
    if connection is None:
        # An unfinished handshake has proved no account and carries no grant.
        # Reusing only that same user's empty scaffolding is safe; a completed
        # source is never a "switch account" target at OAuth start.
        if (
            pending_user_id is None
            or not isinstance(selection, dict)
            or selection.get("mode") != "multi"
        ):
            return None
        await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
        pending: Source | None = await session.scalar(
            select(Source)
            .where(
                Source.project_id == project.id,
                Source.type == source_type,
                Source.created_by == pending_user_id,
                Source.status == SourceStatus.PENDING,
                Source.connection_id.is_(None),
                Source.account_external_id.is_(None),
                Source.secret_ref.is_(None),
            )
            .order_by(Source.created_at, Source.id)
            .limit(1)
            .with_for_update()
        )
        return pending
    if not isinstance(selection, dict) or selection.get("mode") not in ("multi", "single"):
        return None
    await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    candidates = (
        await session.scalars(
            select(Source)
            .where(
                Source.project_id == project.id,
                Source.type == source_type,
                Source.status != SourceStatus.DISCONNECTED,
            )
            .order_by(Source.created_at, Source.id)
            .with_for_update()
        )
    ).all()
    for source in candidates:
        same_account = source.connection_id == connection.id or (
            source.connection_id is None
            and bool(connection.account_external_id)
            and source.account_external_id == connection.account_external_id
        )
        if not same_account:
            continue
        if selection.get("mode") == "single":
            key = str(selection["config_key"])
            desired = config or {}
            if not desired.get(key) or source.config.get(key) != desired.get(key):
                continue
            # A configured branch is part of repository identity too.
            if source.config.get("branch") != desired.get("branch"):
                continue
        return source
    return None


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
# So a legacy source is CLAIMED, never adopted blind, and only on the user's
# explicit, confirmed request naming the sources (security review H-NEW-1):
# Home lists the source as "sign in once to move it" until the caller holds a
# matching grant, then as "move to your account" with a confirmation that names
# the projects and the grant. Nothing is copied — the source mirrors the
# existing grant — and nothing is widened: a mismatch in recorded access is
# refused, and a grant wider than the source ever recorded needs the caller's
# explicit acceptance in the same request.


def _live_member_projects() -> Any:
    """Sources the caller may act on: an ACTIVE, live, non-viewer membership in
    the source's OWN team and a project that still exists (security review C2)."""
    return (
        select(Source.id)
        .join(Project, Project.id == Source.project_id)
        .join(
            Membership,
            (Membership.team_id == Source.team_id) & (Membership.deleted_at.is_(None)),
        )
        .where(
            Project.deleted_at.is_(None),
            Membership.role != Role.VIEWER,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )


def _own_token_sources(user: User) -> Any:
    """Unbound sources holding their own token in the caller's live projects. A
    SYNCING source is left alone: a worker is holding that token right now."""
    return (
        select(Source)
        .where(
            Source.connection_id.is_(None),
            Source.secret_ref.is_not(None),
            Source.status.in_((SourceStatus.CONNECTED, SourceStatus.ERROR)),
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
    """What Home lists: the caller's OWN legacy grants by the only hint available
    (`created_by`), in projects the caller is a live member of. A hint decides
    what is SHOWN, never what is moved."""
    rows = (
        await session.scalars(_own_token_sources(user).where(Source.created_by == user.id))
    ).all()
    return [s for s in rows if _is_oauth_source(registry, s)]


async def named_legacy_sources(
    session: AsyncSession, registry: ConnectorRegistry, user: User, source_ids: set[uuid.UUID]
) -> list[Source]:
    """The legacy sources a move REQUEST names, among every own-token source in
    the caller's live projects — not only the ones the caller created: the
    proof of the account is the handshake, membership is the reach, and the
    creator hint only decides what Home shows."""
    if not source_ids:
        return []
    rows = (await session.scalars(_own_token_sources(user).where(Source.id.in_(source_ids)))).all()
    return [s for s in rows if _is_oauth_source(registry, s)]


async def claimable_connections(
    session: AsyncSession, user: User, sources: list[Source]
) -> dict[uuid.UUID, AccountConnection]:
    """For each legacy source, the caller's CONNECTED grant that PROVES its
    account (same provider, same provider-vouched external id), if any."""
    if not sources:
        return {}
    live = (
        await session.scalars(
            select(AccountConnection).where(
                AccountConnection.user_id == user.id,
                AccountConnection.status == ConnectionStatus.CONNECTED,
                AccountConnection.secret_ref.is_not(None),
                AccountConnection.account_external_id.is_not(None),
            )
        )
    ).all()
    by_identity = {(c.provider, c.account_external_id): c for c in live}
    return {
        s.id: by_identity[(s.type, s.account_external_id)]
        for s in sources
        if (s.type, s.account_external_id) in by_identity
    }


def _access_of(row: AccountConnection | Source) -> str | None:
    access = row.config.get("access") if isinstance(row.config, dict) else None
    return access if isinstance(access, str) and access else None


def legacy_secret_family(source: Source) -> list[str]:
    """The project-owned refs a pre-I1 source held: DERIVED from its id, never
    read from anywhere a member can write."""
    ref = f"source/{source.id}/{source.type.value}"
    return [ref, refresh_secret_ref(ref), *hosted_refs(ref)]


def retire_legacy_family(source: Source) -> None:
    """Mark a source whose OWN token family is now unreferenced (it mirrors a
    grant from here on) for the post-commit sweep, and drop the hosted add-on
    state that rode that family — those grants go with it."""
    config = {k: v for k, v in source.config.items() if k not in _HOSTED_STATE_KEYS}
    source.config = {**config, RETIRE_MARKER_KEY: True}


def bind_to_account(
    source: Source, connection: AccountConnection, *, preserve_state: bool = False
) -> None:
    """Attach a project source to the caller's account grant — THE way a source
    that may hold its own token is re-pointed. A reused pre-I1 or PAT row
    mirrors the grant from here on: its old family is unreferenced and is
    swept after the commit, never left live in the store (SOLUSDEV-242)."""
    if source.secret_ref and not is_connection_owned(source.secret_ref):
        retire_legacy_family(source)
    bind_source(source, connection, preserve_state=preserve_state)


def _claim_rejection(source: Source, grant_access: str | None, confirm_access: bool) -> str | None:
    """Why a source must NOT bind to this grant, or None. Nothing widens
    silently: a recorded mismatch is refused outright; a grant wider than the
    source ever recorded needs the caller's explicit acceptance."""
    source_access = _access_of(source)
    if source_access and grant_access and source_access != grant_access:
        return "access_mismatch"
    if not source_access and grant_access == "write" and not confirm_access:
        return "access_unknown"
    return None


async def claim_legacy_sources(
    session: AsyncSession,
    registry: ConnectorRegistry,
    user: User,
    connection: AccountConnection,
    source_ids: set[uuid.UUID],
    *,
    confirm_access: bool = False,
) -> tuple[list[Source], list[dict[str, Any]]]:
    """Bind the named legacy sources for the account `connection` PROVED to it —
    no sign-in, no copy, nothing widened, nothing the caller did not name.

    The grant is re-read FOR UPDATE inside this transaction (a revoke racing
    the claim must not leave a project on a deleted ref — security review
    M-NEW-2), and the sources are locked FOR UPDATE so concurrent claims
    serialise. Returns (claimed, skipped-with-reason). The old project-owned
    token family is marked for the post-commit sweep.
    """
    if not source_ids:
        return [], []
    locked = (
        await session.scalars(
            # `populate_existing`: the caller's snapshot of this row is already in
            # the session's identity map, and a plain re-select would hand it back
            # with STALE attributes — locked, but the status never re-read.
            select(AccountConnection)
            .where(AccountConnection.id == connection.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()
    if (
        locked is None
        or locked.user_id != user.id
        or locked.status is not ConnectionStatus.CONNECTED
        or not locked.secret_ref
        or not locked.account_external_id
    ):
        return [], []
    candidates = (
        await session.scalars(
            _own_token_sources(user)
            .where(
                Source.id.in_(source_ids),
                Source.type == locked.provider,
                Source.account_external_id == locked.account_external_id,
            )
            .with_for_update()
        )
    ).all()
    claimed: list[Source] = []
    skipped: list[dict[str, Any]] = []
    grant_access = _access_of(locked)
    for source in candidates:
        if not _is_oauth_source(registry, source):
            continue
        reason = _claim_rejection(source, grant_access, confirm_access)
        if reason:
            skipped.append(
                {"source_id": source.id, "project_id": source.project_id, "reason": reason}
            )
            continue
        bind_source(source, locked)
        retire_legacy_family(source)
        claimed.append(source)
    if claimed:
        await session.flush()
    return claimed, skipped


async def delete_legacy_family_if_retired(secret_store: SecretStore, source: Source) -> None:
    """A source torn down (disconnect, project teardown) while its retired
    family was still owed: delete the family now, or it is orphaned live with
    nothing left to derive it from (security review M-NEW-2)."""
    if not (isinstance(source.config, dict) and source.config.get(RETIRE_MARKER_KEY)):
        return
    for ref in legacy_secret_family(source):
        await secret_store.delete(ref)


async def sweep_retired_secrets(
    session: AsyncSession, secret_store: SecretStore, user: User
) -> int:
    """AFTER the caller's commit: delete the project-owned token families that
    claims retired, for sources in the caller's live teams. The refs are
    DERIVED from each source's id (never stored, never client-influenced) and
    the marker survives a store outage, so a failed delete is retried on the
    next sweep instead of leaking a live token — including after a revoke,
    which does not touch the marker. Returns how many sources were swept; the
    caller commits."""
    rows = (
        await session.scalars(
            select(Source)
            .where(
                Source.id.in_(_live_member_projects().where(Membership.user_id == user.id)),
                Source.config[RETIRE_MARKER_KEY].as_boolean().is_(True),
            )
            .order_by(Source.updated_at, Source.id)
            .limit(SWEEP_BATCH)
        )
    ).all()
    swept = 0
    for source in rows:
        try:
            for ref in legacy_secret_family(source):
                await secret_store.delete(ref)  # a no-op when absent
        except Exception:  # noqa: BLE001 - a store outage keeps the marker for the retry
            logger.warning("retired-secret sweep deferred source=%s", source.id, exc_info=True)
            continue
        source.config = {k: v for k, v in source.config.items() if k != RETIRE_MARKER_KEY}
        swept += 1
    if swept:
        await session.flush()
    return swept


async def sweep_after_commit(session: AsyncSession, secret_store: SecretStore, user: User) -> None:
    """Run the retirement sweep AFTER the caller's commit — best effort, never a
    500 on top of a committed claim: a failed sweep is the next call's work."""
    try:
        if await sweep_retired_secrets(session, secret_store, user):
            await session.commit()
    except Exception:  # noqa: BLE001 - logged, retried next time
        logger.warning("retired-secret sweep deferred user=%s", user.id, exc_info=True)
        await session.rollback()


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
    cache_only: bool = False,
) -> Fetched[list[dict[str, Any]]]:
    """An account's selectable documents/repositories, from the cache.

    Costs zero provider calls after the first: the listing is refreshed only by
    an explicit `refresh` or a webhook doorbell (`invalidate_listing`), never by
    a timer. The fetch goes through the credential-refresh path, so an expired
    access token refreshes rather than 502s.
    """
    if cache_only:
        if refresh:
            raise APIError(422, "validation_error", "cache_only and refresh cannot be combined")
        hit = await cache.cached_listing(provider, account_ref)
        if hit is None:
            raise APIError(
                409, "listing_not_cached", "Load documents to populate the account listing"
            )
        return hit

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
