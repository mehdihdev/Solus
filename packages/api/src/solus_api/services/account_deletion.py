"""Account deletion (SOLUSDEV-82 cascade, SOLUSDEV-313 Stripe + ownership transfers).

`AccountDeletionService.delete_account` is the one implementation of "remove this user and
everything only they owned". Two callers share it: the self-service `DELETE /users/me`
(never passes `ownership_transfers`) and the SOLUSDEV-314 staff app (may pass them).

TRUST BOUNDARY: the service trusts its caller. It performs no authentication or
authorization of who asked for the deletion; the staff caller must authorize the staff
member before calling. `ownership_transfers` must never be read from a self-delete
request body.

Ordering (all in ONE transaction until the commit): validate transfers, sole-owner
blockers, emit `user.deleted`, leave/cascade each team, forfeit credits, revoke account
connections, tombstone the identity, enqueue the durable Stripe cancel, delete the user,
commit. After the commit, best-effort and never blocking: CAD purge, inline Stripe cancel,
Supabase auth-user delete.

Stripe: the subscription is canceled immediately with a final invoice and no proration (see
`services/stripe_cancel.py`); the Stripe Customer is never deleted. The duty is a database
row written in the deletion's transaction, so a rollback drops it and a commit keeps it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.hosted_oauth import hosted_refs
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.runtime import refresh_secret_ref
from solus_api.connectors.secrets import SecretStore
from solus_api.graph.live_publisher import (
    queue_account_removed,
    queue_member_removed,
    queue_project_removed,
    queue_source_removed,
    queue_team_removed,
)
from solus_api.models import (
    AccountConnection,
    Activity,
    ConnectionStatus,
    CreditBalance,
    CreditLedger,
    CreditTxnType,
    DeletedAccount,
    GraphEdge,
    GraphEntity,
    Invite,
    Job,
    Membership,
    Notification,
    NotificationType,
    OAuthState,
    Project,
    Role,
    Source,
    Subscription,
    SubscriptionStatus,
    Sync,
    Team,
    TeamKind,
    User,
)
from solus_api.services.cad_purge import run_cad_purges_after_commit
from solus_api.services.connections import (
    delete_legacy_family_if_retired,
    is_connection_owned,
    revoke_connection,
    schedule_legacy_grant_purge,
)
from solus_api.services.events import emit_event
from solus_api.services.notifications import notify_team
from solus_api.services.stripe_cancel import (
    _CancelGateway,
    enqueue_stripe_cancel,
    run_stripe_cancels_after_commit,
)

logger = logging.getLogger("solus.services.account_deletion")

OWNERSHIP_TRANSFER_REQUIRED = "ownership_transfer_required"


class AuthUserRemover(Protocol):
    """The slice of `SupabaseAdmin` the service needs (best-effort, never raises)."""

    async def delete_user(self, supabase_user_id: str) -> bool: ...


# ------------------------------------------------------------------ errors
class AccountDeletionError(Exception):
    """Base of the typed, stable-coded failures of a deletion. Raised BEFORE any write."""

    code = "account_deletion_error"


class OwnershipTransferRequired(AccountDeletionError):  # noqa: N818
    """The user solely owns teams that still have other members and no (valid) transfer
    covers them. `team_ids` are exactly those teams, oldest first."""

    code = OWNERSHIP_TRANSFER_REQUIRED

    def __init__(self, team_ids: Sequence[uuid.UUID]) -> None:
        super().__init__("Transfer ownership of your teams before deleting your account")
        self.team_ids: list[uuid.UUID] = list(team_ids)


class InvalidOwnershipTransfer(AccountDeletionError):  # noqa: N818
    """One `ownership_transfers` entry cannot be applied. `code` is one of
    transfer_team_not_found, transfer_personal_team, transfer_not_owner,
    transfer_target_not_found, transfer_target_is_self, transfer_target_not_member."""

    def __init__(self, code: str, team_id: uuid.UUID, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.team_id = team_id
        self.reason = reason


# ------------------------------------------------------------------ team reads
async def team_memberships(session: AsyncSession, user: User) -> list[tuple[Team, Membership]]:
    """The user's live memberships with their teams, oldest team first."""
    rows = await session.execute(
        select(Team, Membership)
        .join(Membership, Membership.team_id == Team.id)
        .where(Membership.user_id == user.id, Membership.deleted_at.is_(None))
        .order_by(Team.created_at)
    )
    return [(team, membership) for team, membership in rows.all()]


async def live_members(session: AsyncSession, team_id: uuid.UUID) -> list[Membership]:
    """Live (non-soft-deleted) members of a team — the set that counts for the
    sole-owner guard and the leave-vs-cascade decision (SOLUSDEV-82 sec review M1)."""
    rows = await session.scalars(
        select(Membership).where(Membership.team_id == team_id, Membership.deleted_at.is_(None))
    )
    return list(rows.all())


async def sole_owner_blockers(session: AsyncSession, user: User) -> list[uuid.UUID]:
    """Teams the user solely owns that still have other members."""
    blockers: list[uuid.UUID] = []
    for team, membership in await team_memberships(session, user):
        if membership.role is not Role.OWNER:
            continue
        members = await live_members(session, team.id)
        owners = [m for m in members if m.role is Role.OWNER]
        if len(owners) == 1 and len(members) > 1:
            blockers.append(team.id)
    return blockers


# ------------------------------------------------------------------ cascades
async def _delete_source_secrets(
    secret_store: SecretStore, rows: Sequence[Source], refs: Sequence[str | None]
) -> None:
    """The credentials each torn-down source owns (never a connection's shared ones)."""
    # Families retired by a move but not yet swept go with the rows
    # (SOLUSDEV-242) — after this, nothing could derive them.
    for owed in rows:
        await delete_legacy_family_if_retired(secret_store, owed)
    for ref in refs:
        # SOLUSDEV-241: a connection-owned ref is the account's, shared by
        # every project bound to it — the connection's own lifecycle deletes
        # it (revoke / account deletion), never a project teardown.
        if ref and not is_connection_owned(ref):
            await secret_store.delete(ref)
            # The OAuth refresh token has its own ref (SOLUS-CAD-01); without
            # this, deleting an account would leave a live grant against the
            # user's GitLab/Onshape data. `delete` no-ops when absent.
            await secret_store.delete(refresh_secret_ref(ref))
            # SOLUSDEV-168: hosted add-on grants hang off the same ref.
            # Deleting an account must not leave a live FeatureScript
            # OAuth2Write token against the user's Onshape documents.
            for hosted_ref in hosted_refs(ref):
                await secret_store.delete(hosted_ref)


async def delete_projects_cascade(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    secret_store: SecretStore | None = None,
    cache: IntegrationCache | None = None,
) -> None:
    """Remove projects and everything hanging off them — jobs plus the graph
    tables (sources/entities/relations/syncs, SOLUSDEV-103) and their stored
    credentials. Explicit, not FK-cascade (portable across PG/SQLite)."""
    if not project_ids:
        return
    rows = (await session.scalars(select(Source).where(Source.project_id.in_(project_ids)))).all()
    sources = [(row.id, row.secret_ref) for row in rows]
    if cache is not None:
        # ADR-038 §1: legacy per-source grants die with their rows, and so must the CAD
        # derived through them (the caller runs the purge after its commit).
        await schedule_legacy_grant_purge(
            session, cache, rows, deleting_ids={row.id for row in rows}
        )
    # Bulk deletes below bypass ORM events, so the live hints are queued by hand
    # (ADR-037 §3) — published only if the caller's transaction commits.
    for owed in rows:
        queue_source_removed(session, project_id=owed.project_id, source_id=owed.id)
    for project_id, team_id in (
        await session.execute(
            select(Project.id, Project.team_id).where(Project.id.in_(project_ids))
        )
    ).all():
        queue_project_removed(session, team_id=team_id, project_id=project_id)
    if secret_store is not None:
        await _delete_source_secrets(secret_store, rows, [ref for _sid, ref in sources])
    source_ids = [sid for sid, _ref in sources]
    if source_ids:
        await session.execute(delete(OAuthState).where(OAuthState.source_id.in_(source_ids)))
    await session.execute(delete(Sync).where(Sync.project_id.in_(project_ids)))
    await session.execute(delete(GraphEdge).where(GraphEdge.project_id.in_(project_ids)))
    await session.execute(delete(GraphEntity).where(GraphEntity.project_id.in_(project_ids)))
    await session.execute(delete(Source).where(Source.project_id.in_(project_ids)))
    await session.execute(delete(Job).where(Job.project_id.in_(project_ids)))
    await session.execute(delete(Project).where(Project.id.in_(project_ids)))


async def delete_team_cascade(
    session: AsyncSession,
    team_id: uuid.UUID,
    secret_store: SecretStore | None = None,
    cache: IntegrationCache | None = None,
) -> None:
    """Explicit cascade (portable across PG/SQLite FK enforcement)."""
    project_ids = list(
        (await session.scalars(select(Project.id).where(Project.team_id == team_id))).all()
    )
    await delete_projects_cascade(session, project_ids, secret_store, cache)
    for member_id in (
        await session.scalars(
            select(Membership.user_id).where(
                Membership.team_id == team_id, Membership.deleted_at.is_(None)
            )
        )
    ).all():
        queue_member_removed(session, team_id=team_id, user_id=member_id)
    queue_team_removed(session, team_id=team_id)
    await session.execute(delete(Activity).where(Activity.team_id == team_id))
    await session.execute(delete(Invite).where(Invite.team_id == team_id))
    await session.execute(delete(Membership).where(Membership.team_id == team_id))
    await session.execute(delete(Team).where(Team.id == team_id))


async def forfeit_credits(session: AsyncSession, user: User) -> None:
    """Forfeit the user's credits on deletion (ADR-024). The append-only ledger is
    preserved (its user_id is nulled by the FK on delete); a forfeiture ADJUSTMENT
    entry records the zeroing, retaining the user id in `attrs`. The cached balance
    row is removed."""
    balance = await session.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    current = balance.balance if balance is not None else 0
    if current:
        session.add(
            CreditLedger(
                user_id=user.id,
                amount=-current,
                type=CreditTxnType.ADJUSTMENT,
                balance_after=0,
                attrs={"reason": "account_deleted", "user_id": str(user.id)},
            )
        )
    if balance is not None:
        await session.delete(balance)


# ------------------------------------------------------------------ service
class AccountDeletionService:
    """Deletes one user's account. Construct per request/operation (holds a session)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        secret_store: SecretStore,
        supabase_admin: AuthUserRemover,
        cache: IntegrationCache,
        gateway: _CancelGateway | None,
    ) -> None:
        self._session = session
        self._secret_store = secret_store
        self._supabase_admin = supabase_admin
        self._cache = cache
        self._gateway = gateway

    async def delete_account(
        self,
        user: User,
        *,
        ownership_transfers: Mapping[uuid.UUID, uuid.UUID] | None = None,
    ) -> None:
        """Delete `user` and commit. Raises `InvalidOwnershipTransfer` /
        `OwnershipTransferRequired` before any write (the caller's session is untouched
        apart from reads)."""
        transfers = dict(ownership_transfers or {})
        await self._validate_transfers(user, transfers)
        blockers = [
            team_id
            for team_id in await sole_owner_blockers(self._session, user)
            if team_id not in transfers
        ]
        if blockers:
            raise OwnershipTransferRequired(blockers)
        await self._apply_transfers(transfers)
        await self._cascade(user)
        supabase_user_id = user.supabase_user_id
        await self._session.commit()
        await self._after_commit(supabase_user_id)

    # -- ownership transfers
    async def _validate_transfers(
        self, user: User, transfers: Mapping[uuid.UUID, uuid.UUID]
    ) -> None:
        for team_id, target_id in transfers.items():
            team = await self._session.get(Team, team_id)
            if team is None or team.deleted_at is not None:
                raise InvalidOwnershipTransfer(
                    "transfer_team_not_found", team_id, "The team does not exist."
                )
            if team.kind is TeamKind.PERSONAL:
                raise InvalidOwnershipTransfer(
                    "transfer_personal_team", team_id, "A personal team cannot be transferred."
                )
            owner_row = await self._live_membership(team_id, user.id)
            if owner_row is None or owner_row.role is not Role.OWNER:
                raise InvalidOwnershipTransfer(
                    "transfer_not_owner", team_id, "The user does not own this team."
                )
            if target_id == user.id:
                raise InvalidOwnershipTransfer(
                    "transfer_target_is_self", team_id, "Ownership cannot go to the deleted user."
                )
            if await self._session.get(User, target_id) is None:
                raise InvalidOwnershipTransfer(
                    "transfer_target_not_found", team_id, "The new owner does not exist."
                )
            if await self._live_membership(team_id, target_id) is None:
                raise InvalidOwnershipTransfer(
                    "transfer_target_not_member", team_id, "The new owner is not a team member."
                )

    async def _live_membership(self, team_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        row: Membership | None = await self._session.scalar(
            select(Membership).where(
                Membership.team_id == team_id,
                Membership.user_id == user_id,
                Membership.deleted_at.is_(None),
            )
        )
        return row

    async def _apply_transfers(self, transfers: Mapping[uuid.UUID, uuid.UUID]) -> None:
        """Promote each (already validated) target. The recipient is an existing member, so
        no team-count plan limit (`max_teams`) is affected by receiving ownership."""
        for team_id, target_id in transfers.items():
            target = await self._live_membership(team_id, target_id)
            if target is not None and target.role is not Role.OWNER:
                target.role = Role.OWNER
                logger.info(
                    "ownership transferred during account deletion team=%s new_owner=%s",
                    team_id,
                    target_id,
                )
        await self._session.flush()

    # -- the cascade
    async def _cascade(self, user: User) -> None:
        session = self._session
        display = user.display_name or user.email.split("@")[0] or "A teammate"
        emit_event(session, user=user, event_type="user.deleted")
        for team, _membership in await team_memberships(session, user):
            members = await live_members(session, team.id)
            if len(members) == 1:
                await delete_team_cascade(session, team.id, self._secret_store, self._cache)
            else:
                # Let the remaining members know a teammate left before we drop the row.
                await notify_team(
                    session,
                    team_id=team.id,
                    notification_type=NotificationType.MEMBER_LEFT,
                    title=f"{display} left {team.name}",
                    exclude_user_id=user.id,
                    attrs={"team_id": str(team.id)},
                )
                await session.execute(
                    delete(Membership).where(
                        Membership.team_id == team.id, Membership.user_id == user.id
                    )
                )
                queue_member_removed(session, team_id=team.id, user_id=user.id)
        await forfeit_credits(session, user)
        await self._revoke_account_connections(user)
        # Tombstone the identity so a still-valid token cannot re-provision (durable delete).
        session.add(DeletedAccount(supabase_user_id=user.supabase_user_id))
        await session.execute(delete(Notification).where(Notification.user_id == user.id))
        await self._enqueue_stripe_cancels(user)
        await session.execute(delete(User).where(User.id == user.id))
        queue_account_removed(session, user_id=user.id)

    async def _revoke_account_connections(self, user: User) -> None:
        # SOLUSDEV-241: the account-scoped grants are the USER's, not any team's, so
        # no team cascade reaches them. REVOKE each one before the row goes: the
        # secrets are deleted, the account's cache is dropped, and every source
        # bound to it — including sources in teams that survive this user — is
        # disconnected rather than left CONNECTED on a dangling ref.
        for connection in (
            await self._session.scalars(
                select(AccountConnection).where(
                    AccountConnection.user_id == user.id,
                    AccountConnection.status != ConnectionStatus.REVOKED,
                )
            )
        ).all():
            await revoke_connection(self._session, self._secret_store, connection, self._cache)

    async def _enqueue_stripe_cancels(self, user: User) -> None:
        """Record the cancel duty in THIS transaction, before `delete(User)` cascades the
        subscription rows away. One request per Stripe customer; a customer-only request
        (no subscription id) is the tombstone for a checkout still in flight."""
        rows = await self._session.scalars(
            select(Subscription).where(
                Subscription.user_id == user.id, Subscription.stripe_customer_id.is_not(None)
            )
        )
        by_customer: dict[str, str | None] = {}
        for row in rows.all():
            customer_id = row.stripe_customer_id
            if customer_id is None:  # pragma: no cover — filtered in SQL
                continue
            live = (
                row.stripe_subscription_id
                if row.status is not SubscriptionStatus.CANCELED
                else None
            )
            by_customer[customer_id] = live or by_customer.get(customer_id)
        for customer_id, subscription_id in by_customer.items():
            await enqueue_stripe_cancel(
                self._session, customer_id=customer_id, subscription_id=subscription_id
            )

    # -- after the commit (best-effort, never blocking)
    async def _after_commit(self, supabase_user_id: str) -> None:
        # ADR-038 §1: purge the durable CAD of every grant this deletion ended (best-effort
        # here; the committed purge records are retried by the worker / next request).
        await run_cad_purges_after_commit(self._session, self._cache.durable_store)
        # SOLUSDEV-313: cancel the Stripe subscription (bounded, never raises; the durable
        # row is retried by the worker / API start when Stripe is down or unconfigured).
        await run_stripe_cancels_after_commit(self._session, self._gateway)
        # Best-effort remote revoke AFTER the local commit: kills the Supabase session /
        # auth user. A failure here is logged, not fatal — the tombstone already blocks
        # re-provision and local data is gone.
        await self._supabase_admin.delete_user(supabase_user_id)
