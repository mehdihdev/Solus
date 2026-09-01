"""Cycle-windowed credit usage (SOLUSDEV-233 — API.md §2.14 `/users/me/usage`).

The always-visible meter (ADR-018) is credit-denominated: `used this cycle` is
the sum of USAGE debits inside the current window, read from the append-only
ledger. `CreditBalance.spent_total` deliberately stays all-time (the trial-cap
semantics `orchestration/cost.account_spend` documents); this module owns the
windowed view instead of changing that.

The cycle is the monthly anniversary window anchored at the subscription's
creation (day-of-month clamped for short months). Without a subscription the
window is the UTC calendar month — honest, and stable for trial users.
"""

import calendar
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import CreditLedger, CreditTxnType


def _shift_months(anchor: datetime, months: int) -> datetime:
    """The anchor moved by whole months, day-of-month clamped (Jan 31 → Feb 28)."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def cycle_window(anchor: datetime, now: datetime) -> tuple[datetime, datetime]:
    """[start, end) of the anniversary cycle containing `now`."""
    months = (now.year - anchor.year) * 12 + (now.month - anchor.month)
    start = _shift_months(anchor, months)
    if start > now:
        months -= 1
        start = _shift_months(anchor, months)
    return start, _shift_months(anchor, months + 1)


def calendar_month_window(now: datetime) -> tuple[datetime, datetime]:
    """[start, end) of the current UTC calendar month — the no-subscription fallback."""
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    next_month = _shift_months(start.replace(day=1), 1)
    return start, next_month


async def cycle_spend(
    session: AsyncSession, user_id: uuid.UUID, *, since: datetime, until: datetime
) -> int:
    """Credits consumed by USAGE debits inside the window, as a positive number.

    A ledger scan bounded by (user, window) — the meter is a per-request read on
    a user-indexed table, not a hot loop; `spent_total` stays the O(1) all-time
    answer for the trial cap.
    """
    total = await session.scalar(
        select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
            CreditLedger.user_id == user_id,
            CreditLedger.type == CreditTxnType.USAGE,
            CreditLedger.created_at >= since,
            CreditLedger.created_at < until,
        )
    )
    return -int(total or 0)
