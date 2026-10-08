"""Cancel a deleted account's Stripe subscriptions, built to never be lost (SOLUSDEV-313).

Same shape as `services/cad_purge.py`: the duty is a DATABASE RECORD.

1. `enqueue_stripe_cancel` runs inside the account-deletion transaction and inserts (or
   re-arms) a `StripeCancelRequest` holding only Stripe ids. It does not commit.
2. After the commit the request path calls `run_stripe_cancels_after_commit`: a bounded,
   best-effort inline attempt (optionally scoped to the just-enqueued customers) that never
   raises (the deletion already succeeded).
3. Whatever is still due is retried with exponential backoff by the worker cron and at API
   startup (`run_startup_stripe_cancels`).

Business rule: on account deletion every subscription is canceled IMMEDIATELY with a FINAL
invoice and NO proration. The Stripe Customer is never deleted.

The row is a CUSTOMER tombstone: the run lists the customer's subscriptions in Stripe and
cancels EVERY non-terminal one (the stored subscription id is only a hint, so a re-arm for a
different subscription can never orphan the first). It is RETAINED after success
(`completed_at`) as the deleted-customer marker (`is_tombstoned_customer`) the webhook path
uses to cancel a subscription created for an already-deleted customer (the late-checkout
race). Re-enqueueing re-arms the row.

Locking: a run CLAIMS due rows (`FOR UPDATE SKIP LOCKED`), leases them by pushing
`next_attempt_at` out by `LEASE_SECONDS`, and COMMITS before any Stripe call. Each outcome is
then recorded in its own short transaction. A crash mid-call leaves the lease, so the row is
retried after it elapses (the Stripe idempotency keys make that safe).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing.stripe_gateway import CancelMode, CancelResult, StripeOperationError
from solus_api.models import StripeCancelRequest

logger = logging.getLogger("solus.services.stripe_cancel")

BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600
#: A non-retryable Stripe refusal will not fix itself soon; keep it visible but quiet.
TERMINAL_BACKOFF_SECONDS = 24 * 3600
#: Rows claimed per run. BATCH * ROW_TIMEOUT_SECONDS (250s) stays inside ARQ's 300s job timeout.
BATCH = 5
#: Upper bound on ONE row's Stripe work (list + every cancel).
ROW_TIMEOUT_SECONDS = 50.0
#: How long a claimed row is hidden from other runners; must exceed ROW_TIMEOUT_SECONDS. A
#: crash mid-call is retried once this elapses.
LEASE_SECONDS = 120
#: The inline attempt after a commit must not hold the user's response hostage.
INLINE_TIMEOUT_SECONDS = 15.0

_CUSTOMER_ID_RE = re.compile(r"cus_[A-Za-z0-9]{1,64}")
_SUBSCRIPTION_ID_RE = re.compile(r"sub_[A-Za-z0-9]{1,64}")
_IMMEDIATE: CancelMode = "immediate"


class CancelGateway(Protocol):
    """The slice of `StripeGateway` this service needs (real and fake both satisfy it)."""

    async def list_customer_subscriptions(self, customer_id: str) -> list[str]: ...

    async def cancel_subscription(
        self,
        sub_id: str,
        *,
        mode: CancelMode,
        invoice_now: bool,
        prorate: bool,
        audit_action_id: str,
        actor: str | None,
    ) -> CancelResult: ...


@dataclass(frozen=True)
class CancelRunSummary:
    """What one run did. `attempted == completed + failed`."""

    completed: int = 0
    failed: int = 0

    @property
    def attempted(self) -> int:
        return self.completed + self.failed


@dataclass(frozen=True)
class _Claim:
    """A leased row, copied out so no ORM state is touched while Stripe is called."""

    row_id: uuid.UUID
    customer_id: str
    hint: str | None


def _check(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid Stripe {label} id")
    return value


def _backoff_seconds(attempts: int) -> int:
    return int(min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_MAX_SECONDS))


def _idempotency_id(row_id: uuid.UUID, subscription_id: str) -> str:
    """Stable per (row, subscription): a retry replays the same Stripe request, another
    subscription gets its own. 36 chars, within the gateway's 64-char token."""
    digest = hashlib.sha256(f"{row_id.hex}:{subscription_id}".encode()).hexdigest()
    return f"acctdel-{digest[:28]}"


async def enqueue_stripe_cancel(
    session: AsyncSession,
    *,
    customer_id: str,
    subscription_id: str | None,
    now: datetime | None = None,
) -> StripeCancelRequest:
    """Record the duty in the caller's transaction (flush only, never commits).

    One row per customer. An existing COMPLETED row is re-armed (attempts reset, due now);
    an existing PENDING row keeps its attempts and backoff (a re-arm must not defeat the
    backoff). The subscription id is a hint only: the run cancels every live subscription
    of the customer."""
    _check(customer_id, _CUSTOMER_ID_RE, "customer")
    if subscription_id is not None:
        _check(subscription_id, _SUBSCRIPTION_ID_RE, "subscription")
    stamp = now or datetime.now(UTC)
    insert = pg_insert(StripeCancelRequest).values(
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        attempts=0,
        next_attempt_at=stamp,
        completed_at=None,
        created_at=stamp,
    )
    pending = StripeCancelRequest.completed_at.is_(None)
    upsert = insert.on_conflict_do_update(
        index_elements=[StripeCancelRequest.stripe_customer_id],
        set_={
            "stripe_subscription_id": func.coalesce(
                insert.excluded.stripe_subscription_id,
                StripeCancelRequest.stripe_subscription_id,
            ),
            "attempts": case((pending, StripeCancelRequest.attempts), else_=0),
            "next_attempt_at": case((pending, StripeCancelRequest.next_attempt_at), else_=stamp),
            "completed_at": None,
        },
    ).returning(StripeCancelRequest)
    row = await session.scalar(upsert, execution_options={"populate_existing": True})
    if row is None:  # pragma: no cover — an upsert always returns its row
        raise RuntimeError("stripe cancel upsert returned no row")
    return row


async def is_tombstoned_customer(session: AsyncSession, customer_id: str) -> bool:
    """True once the customer's account was deleted (row exists, complete or not)."""
    found = await session.scalar(
        select(StripeCancelRequest.id).where(StripeCancelRequest.stripe_customer_id == customer_id)
    )
    return found is not None


async def _claim_due(
    session: AsyncSession, stamp: datetime, limit: int, customer_ids: Collection[str] | None
) -> list[_Claim]:
    """Lock due rows, lease them and COMMIT, so no row lock outlives this function."""
    query = (
        select(StripeCancelRequest)
        .where(
            StripeCancelRequest.next_attempt_at <= stamp,
            StripeCancelRequest.completed_at.is_(None),
        )
        .order_by(StripeCancelRequest.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if customer_ids is not None:
        query = query.where(StripeCancelRequest.stripe_customer_id.in_(list(customer_ids)))
    rows = (await session.scalars(query)).all()
    claims = [_Claim(row.id, row.stripe_customer_id, row.stripe_subscription_id) for row in rows]
    leased_until = stamp + timedelta(seconds=LEASE_SECONDS)
    for row in rows:
        row.next_attempt_at = leased_until
    await session.commit()
    return claims


async def _cancel_customer(claim: _Claim, gateway: CancelGateway) -> None:
    """Cancel every live subscription of the customer (plus the hint). Every target is
    attempted; the first failure is raised afterwards so the row is retried."""
    targets = await gateway.list_customer_subscriptions(claim.customer_id)
    if claim.hint is not None and claim.hint not in targets:
        targets = [*targets, claim.hint]
    first_error: Exception | None = None
    for subscription_id in targets:
        try:
            await gateway.cancel_subscription(
                subscription_id,
                mode=_IMMEDIATE,
                invoice_now=True,
                prorate=False,
                audit_action_id=_idempotency_id(claim.row_id, subscription_id),
                actor=None,
            )
        except Exception as exc:  # noqa: BLE001 — keep going; the row is retried below
            first_error = first_error or exc
    if first_error is not None:
        raise first_error


def _record_failure(row: StripeCancelRequest, exc: Exception, stamp: datetime) -> None:
    row.attempts += 1
    terminal = isinstance(exc, StripeOperationError) and not exc.retryable
    delay = TERMINAL_BACKOFF_SECONDS if terminal else _backoff_seconds(row.attempts)
    row.next_attempt_at = stamp + timedelta(seconds=delay)
    # Never the message or traceback of an unknown error (it could echo request data, keys or
    # ids): the type name, plus the allow-listed code/status of a typed Stripe error.
    detail = type(exc).__name__
    if isinstance(exc, StripeOperationError):
        detail = f"{detail} code={exc.code} http_status={exc.http_status}"
    log = logger.error if terminal else logger.warning
    log(
        "Stripe cancel failed for customer %s (row %s, attempt %d, %s%s); next try in %ds",
        row.stripe_customer_id,
        row.id,
        row.attempts,
        detail,
        ", NON-RETRYABLE, needs an operator" if terminal else "",
        delay,
    )


async def _record_outcome(
    session: AsyncSession, claim: _Claim, error: Exception | None, stamp: datetime
) -> None:
    """One short transaction per row (re-selected by id, committed immediately)."""
    row = await session.scalar(
        select(StripeCancelRequest)
        .where(StripeCancelRequest.id == claim.row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:  # pragma: no cover — rows are never deleted
        await session.rollback()
        return
    if error is not None:
        _record_failure(row, error, stamp)
    elif row.stripe_subscription_id != claim.hint:
        # Re-armed for a new subscription while Stripe was being called: the listing may
        # predate it, so leave the row open and due now.
        row.next_attempt_at = stamp
    else:
        row.completed_at = stamp
    await session.commit()


async def _run_claim(claim: _Claim, gateway: CancelGateway) -> Exception | None:
    try:
        async with asyncio.timeout(ROW_TIMEOUT_SECONDS):
            await _cancel_customer(claim, gateway)
    except Exception as exc:  # noqa: BLE001 — retried with backoff; the row is the safety net
        return exc
    return None


async def run_due_stripe_cancels(
    session: AsyncSession,
    gateway: CancelGateway,
    *,
    now: datetime | None = None,
    limit: int = BATCH,
    customer_ids: Collection[str] | None = None,
) -> CancelRunSummary:
    """Run every due, uncompleted row (optionally only these customers), once.

    Claims and leases rows, commits, then calls Stripe with NO lock held and records each
    row's outcome in its own transaction. A failing row backs off and is retried; Stripe
    errors never escape. Safe under concurrent runners (`SKIP LOCKED` + the lease)."""
    stamp = now or datetime.now(UTC)
    claims = await _claim_due(session, stamp, limit, customer_ids)
    completed = failed = 0
    for claim in claims:
        error = await _run_claim(claim, gateway)
        await _record_outcome(session, claim, error, stamp)
        if error is None:
            completed += 1
        else:
            failed += 1
    return CancelRunSummary(completed=completed, failed=failed)


async def run_stripe_cancels_after_commit(
    session: AsyncSession,
    gateway: CancelGateway | None,
    *,
    timeout_seconds: float = INLINE_TIMEOUT_SECONDS,
    customer_ids: Collection[str] | None = None,
) -> None:
    """The inline attempt after a deleting commit: bounded, and never raises.

    `customer_ids` scopes the run to the just-enqueued customers (an empty collection runs
    nothing); None drains the whole due queue."""
    if gateway is None or (customer_ids is not None and not customer_ids):
        return
    try:
        async with asyncio.timeout(timeout_seconds):
            await run_due_stripe_cancels(session, gateway, customer_ids=customer_ids)
    except Exception:  # noqa: BLE001 — the deletion already succeeded; the row retries
        logger.warning("inline Stripe cancel did not finish; it will be retried", exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("could not roll back after a failed inline Stripe cancel")


async def run_startup_stripe_cancels(
    sessionmaker: Callable[[], AsyncSession], gateway: CancelGateway | None
) -> None:
    """API start: drain whatever was due while no process was running. Never raises."""
    if gateway is None:
        return
    try:
        async with sessionmaker() as session:
            await run_stripe_cancels_after_commit(session, gateway)
    except Exception:  # noqa: BLE001
        logger.warning("startup Stripe cancel could not run", exc_info=True)
