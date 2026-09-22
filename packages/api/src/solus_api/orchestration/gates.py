"""MO-03 pre-flight gates — run BEFORE the model call (gateway order:
frequency cap → spend/trial gate → provider call → post-call debit).

Two DIFFERENT blocks with two DIFFERENT user messages, by design:

- Frequency cap (`check_frequency_cap`): flat per-user anti-abuse insurance
  (runaway agent loops), Redis-backed sliding window. Blocking is TRANSIENT —
  "too many requests, try again in a moment" — the user can simply retry after
  the window. Same limit for every plan; it is abuse protection, not a plan
  feature. Redis down/unconfigured/erroring → FAIL-OPEN with a loud structured
  warning (confirmed policy): a Redis blip must never take down all model
  calls. NOTE the honest limit: while failed open, the DB-backed spend gate
  bounds SEQUENTIAL damage only (pre-flight read, debit lands post-call) — a
  concurrent burst can overshoot the trial cap unboundedly. Atomic at-debit cap
  enforcement + a concurrency red-team test are route-exposure work (see
  gateway.py deferral list).
- Spend gate (`assert_can_spend`): TRIALING users are blocked at the
  configurable `limits.trial_credit_cap` with an UPGRADE call-to-action; paid
  users are gated on their cached credit balance instead. The check is
  pre-flight (cost is unknown until tokens_out exists), so MINOR OVERSHOOT IS
  BY DESIGN (Q9): block when spend is already at/over the cap, bill the actual
  cost after. No cost pre-authorization/estimation.

Blocks are recorded to the data-collection system (§7 abuse detection) on a
best-effort, consent-gated basis — never letting the event write break or
delay the block itself.

Errors are orchestration-native (no HTTP coupling); the future route layer
maps FrequencyCapExceededError → 429 and TrialCapReachedError /
InsufficientCreditsError → 402.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select

from solus_api.billing.development import session_development_unlimited
from solus_api.models import Subscription, SubscriptionStatus, User
from solus_api.orchestration.cost import account_spend, has_sufficient_credits
from solus_api.services.events import emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.orchestration.config import LimitsConfig

logger = logging.getLogger("solus.orchestration.gates")

UPGRADE_URL = "/settings/billing"
_FREQ_KEY_PREFIX = "solus:freqcap:"


class RedisLike(Protocol):
    """The five sorted-set commands the sliding window needs (redis.asyncio
    satisfies this; tests use a tiny fake)."""

    async def zremrangebyscore(self, key: str, low: float, high: float) -> int: ...
    async def zcard(self, key: str) -> int: ...
    async def zadd(self, key: str, mapping: dict[str, float]) -> int: ...
    async def expire(self, key: str, seconds: int) -> bool: ...
    async def zrange(
        self, key: str, start: int, stop: int, withscores: bool = ...
    ) -> list[Any]: ...


class FrequencyCapExceededError(RuntimeError):
    """TRANSIENT 429-style block — retry after the window, no action needed."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Too many requests — try again in a moment (about {retry_after_seconds}s)."
        )


class TrialCapReachedError(RuntimeError):
    """The trial allowance is spent — upgrading is the way forward."""

    def __init__(self, cap: int, spend: int) -> None:
        self.cap = cap
        self.spend = spend
        self.upgrade_url = UPGRADE_URL
        super().__init__(
            f"Free trial usage limit reached ({spend}/{cap} credits) — "
            f"upgrade to continue: {UPGRADE_URL}"
        )


class InsufficientCreditsError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(f"Not enough credits for this call — top up or upgrade: {UPGRADE_URL}")


async def check_frequency_cap(
    user_id: uuid.UUID,
    *,
    redis: RedisLike | None,
    limits: LimitsConfig,
    now: float | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Sliding-window frequency gate: at most `limits.max_calls_per_minute` calls
    per `limits.frequency_window_seconds` window per user. Raises
    FrequencyCapExceededError when at/over; otherwise records this call.
    Deterministic given `now` (tests inject it)."""
    if redis is None:
        logger.warning(
            "frequency cap SKIPPED — no redis configured, fail-open by policy user_id=%s",
            user_id,
        )
        return
    ts = time.time() if now is None else now
    window = limits.frequency_window_seconds
    key = f"{_FREQ_KEY_PREFIX}{user_id}"
    try:
        await redis.zremrangebyscore(key, 0, ts - window)
        count = await redis.zcard(key)
    except Exception:
        # Uniform policy: a broken limiter never takes down model calls —
        # same fail-open as redis=None, whether Redis is absent or erroring.
        logger.warning(
            "frequency cap SKIPPED — redis unavailable, fail-open by policy user_id=%s",
            user_id,
            exc_info=True,
        )
        return
    if count >= limits.max_calls_per_minute:
        try:
            oldest = await redis.zrange(key, 0, 0, withscores=True)
            oldest_ts = float(oldest[0][1]) if oldest else ts
        except Exception:
            oldest_ts = ts  # already over the limit; a broken read never unblocks
        retry_after = max(1, math.ceil(oldest_ts + window - ts))
        logger.info(
            "frequency cap blocked user_id=%s count=%d limit=%d retry_after=%ds",
            user_id,
            count,
            limits.max_calls_per_minute,
            retry_after,
        )
        if session is not None:
            await _emit_block_event(
                session, user_id, reason="frequency_cap", detail={"retry_after": retry_after}
            )
        raise FrequencyCapExceededError(retry_after)
    try:
        await redis.zadd(key, {uuid.uuid4().hex: ts})
        await redis.expire(key, window)
    except Exception:
        logger.warning(
            "frequency cap could not record this call — redis unavailable, "
            "fail-open by policy user_id=%s",
            user_id,
            exc_info=True,
        )


async def assert_can_spend(
    user_id: uuid.UUID, *, session: AsyncSession, limits: LimitsConfig
) -> None:
    """Spend/trial pre-flight gate (see module docstring for the policy split).

    TRIALING → block when trial spend (account_spend, all-time == trial spend in
    v1) is already at/over `limits.trial_credit_cap`. Any other status — or no
    subscription at all — → block unless the cached balance covers at least one
    credit (has_sufficient_credits; no cost estimation per Q9)."""
    if session_development_unlimited(session, user_id):
        return
    sub = await session.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id, Subscription.deleted_at.is_(None)
        )
    )
    if sub is not None and sub.status == SubscriptionStatus.TRIALING:
        spend = await account_spend(user_id, session=session)
        if spend >= limits.trial_credit_cap:
            logger.info(
                "trial cap blocked user_id=%s spend=%d cap=%d",
                user_id,
                spend,
                limits.trial_credit_cap,
            )
            await _emit_block_event(
                session,
                user_id,
                reason="trial_cap_reached",
                detail={"spend": spend, "cap": limits.trial_credit_cap},
            )
            raise TrialCapReachedError(limits.trial_credit_cap, spend)
        return
    if not await has_sufficient_credits(user_id, 1, session=session):
        logger.info("insufficient credits blocked user_id=%s", user_id)
        await _emit_block_event(session, user_id, reason="insufficient_credits", detail={})
        raise InsufficientCreditsError()


async def _emit_block_event(
    session: AsyncSession, user_id: uuid.UUID, *, reason: str, detail: dict[str, Any]
) -> None:
    """Best-effort §7 abuse-detection event — consent-gated inside emit_event;
    never lets the accounting of a block break the block.

    NOTE (route-exposure radar): the commit below persists the event because a
    blocked request's session is otherwise discarded — but it also commits any
    OTHER pending work on the caller's session. Fine today (pre-flight runs
    before any caller writes; no route passes a dirty session); revisit if a
    future endpoint does session work before calling the gateway."""
    try:
        user = await session.get(User, user_id)
        if user is None:
            return
        emit_event(
            session,
            user=user,
            event_type="orchestration.blocked",
            payload={"reason": reason, **detail},
        )
        await session.commit()
    except Exception:  # pragma: no cover - best-effort by design
        logger.debug("block event emit failed (ignored) user_id=%s reason=%s", user_id, reason)
