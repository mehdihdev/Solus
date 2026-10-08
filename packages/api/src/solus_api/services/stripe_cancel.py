"""Cancel a deleted account's Stripe subscription, built to never be lost (SOLUSDEV-313).

Same shape as `services/cad_purge.py`: the duty is a DATABASE RECORD.

1. `enqueue_stripe_cancel` runs inside the account-deletion transaction and inserts (or
   re-arms) a `StripeCancelRequest` holding only Stripe ids. It does not commit.
2. After the commit the request path calls `run_stripe_cancels_after_commit`: a bounded,
   best-effort inline attempt that never raises (the deletion already succeeded).
3. Whatever is still due is retried with exponential backoff by the worker cron and at API
   startup (`run_startup_stripe_cancels`).

Business rule: on account deletion the subscription is canceled IMMEDIATELY with a FINAL
invoice and NO proration. The Stripe Customer is never deleted.

The row is RETAINED after success (`completed_at`): it is the deleted-customer tombstone
(`is_tombstoned_customer`) the webhook path uses to cancel a subscription created for an
already-deleted customer (the late-checkout race). Re-enqueueing re-arms the row.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing.stripe_gateway import CancelMode, CancelResult, StripeOperationError
from solus_api.models import StripeCancelRequest

logger = logging.getLogger("solus.services.stripe_cancel")

BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600
#: A non-retryable Stripe refusal will not fix itself soon; keep it visible but quiet.
TERMINAL_BACKOFF_SECONDS = 24 * 3600
#: Rows per run, so one run (and its row locks) stays short.
BATCH = 10
#: Bound on one Stripe call, so a hung connection cannot pin the row locks.
CALL_TIMEOUT_SECONDS = 30.0
#: The inline attempt after a commit must not hold the user's response hostage.
INLINE_TIMEOUT_SECONDS = 15.0

_CUSTOMER_ID_RE = re.compile(r"cus_[A-Za-z0-9]{1,64}")
_SUBSCRIPTION_ID_RE = re.compile(r"sub_[A-Za-z0-9]{1,64}")
_IMMEDIATE: CancelMode = "immediate"


class _CancelGateway(Protocol):
    """The slice of `StripeGateway` this service needs (real and fake both satisfy it)."""

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


def _check(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid Stripe {label} id")
    return value


def _backoff_seconds(attempts: int) -> int:
    return int(min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_MAX_SECONDS))


def _idempotency_id(row: StripeCancelRequest, subscription_id: str) -> str:
    """Stable per (row, subscription): a retry replays the same Stripe request, a re-arm for
    a different subscription gets a new one. 36 chars, within the gateway's 64-char token."""
    digest = hashlib.sha256(f"{row.id.hex}:{subscription_id}".encode()).hexdigest()
    return f"acctdel-{digest[:28]}"


async def enqueue_stripe_cancel(
    session: AsyncSession,
    *,
    customer_id: str,
    subscription_id: str | None,
    now: datetime | None = None,
) -> StripeCancelRequest:
    """Record the duty in the caller's transaction (flush only, never commits).

    One row per customer: an existing row is re-armed (not-completed, attempts reset, due
    now) and keeps its known subscription id unless a new one is given."""
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
    upsert = insert.on_conflict_do_update(
        index_elements=[StripeCancelRequest.stripe_customer_id],
        set_={
            "stripe_subscription_id": func.coalesce(
                insert.excluded.stripe_subscription_id,
                StripeCancelRequest.stripe_subscription_id,
            ),
            "attempts": 0,
            "next_attempt_at": stamp,
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


async def _cancel_one(
    row: StripeCancelRequest, subscription_id: str, gateway: _CancelGateway
) -> None:
    async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
        await gateway.cancel_subscription(
            subscription_id,
            mode=_IMMEDIATE,
            invoice_now=True,
            prorate=False,
            audit_action_id=_idempotency_id(row, subscription_id),
            actor=None,
        )


def _record_failure(row: StripeCancelRequest, exc: Exception, stamp: datetime) -> None:
    row.attempts += 1
    terminal = isinstance(exc, StripeOperationError) and not exc.retryable
    delay = TERMINAL_BACKOFF_SECONDS if terminal else _backoff_seconds(row.attempts)
    row.next_attempt_at = stamp + timedelta(seconds=delay)
    # Never the exception text of an unknown error (could echo request data): type only.
    logger.log(
        logging.ERROR,
        "Stripe cancel failed for customer %s (row %s, attempt %d, %s); next try in %ds",
        row.stripe_customer_id,
        row.id,
        row.attempts,
        "NON-RETRYABLE, needs an operator" if terminal else type(exc).__name__,
        delay,
        exc_info=exc if not terminal else None,
    )


async def run_due_stripe_cancels(
    session: AsyncSession,
    gateway: _CancelGateway,
    *,
    now: datetime | None = None,
    limit: int = BATCH,
) -> CancelRunSummary:
    """Run every due, uncompleted row that has a subscription id, once.

    A failing row backs off and is retried; Stripe errors never escape. Safe under
    concurrent runners (`SKIP LOCKED`; Stripe idempotency covers a crash after the call)."""
    stamp = now or datetime.now(UTC)
    rows = (
        await session.scalars(
            select(StripeCancelRequest)
            .where(
                StripeCancelRequest.next_attempt_at <= stamp,
                StripeCancelRequest.completed_at.is_(None),
                StripeCancelRequest.stripe_subscription_id.is_not(None),
            )
            .order_by(StripeCancelRequest.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    completed = failed = 0
    for row in rows:
        subscription_id = row.stripe_subscription_id
        if subscription_id is None:  # pragma: no cover — filtered by the query
            continue
        try:
            await _cancel_one(row, subscription_id, gateway)
        except Exception as exc:  # noqa: BLE001 — retried with backoff; the row is the safety net
            _record_failure(row, exc, stamp)
            failed += 1
            continue
        row.completed_at = stamp
        completed += 1
    await session.commit()
    return CancelRunSummary(completed=completed, failed=failed)


async def run_stripe_cancels_after_commit(
    session: AsyncSession,
    gateway: _CancelGateway | None,
    *,
    timeout_seconds: float = INLINE_TIMEOUT_SECONDS,
) -> None:
    """The inline attempt after a deleting commit: bounded, and never raises."""
    if gateway is None:
        return
    try:
        async with asyncio.timeout(timeout_seconds):
            await run_due_stripe_cancels(session, gateway)
    except Exception:  # noqa: BLE001 — the deletion already succeeded; the row retries
        logger.warning("inline Stripe cancel did not finish; it will be retried", exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("could not roll back after a failed inline Stripe cancel")


async def run_startup_stripe_cancels(
    sessionmaker: Callable[[], AsyncSession], gateway: _CancelGateway | None
) -> None:
    """API start: drain whatever was due while no process was running. Never raises."""
    if gateway is None:
        return
    try:
        async with sessionmaker() as session:
            await run_stripe_cancels_after_commit(session, gateway)
    except Exception:  # noqa: BLE001
        logger.warning("startup Stripe cancel could not run", exc_info=True)
