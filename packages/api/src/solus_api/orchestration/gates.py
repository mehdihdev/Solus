"""MO-03 pre-flight gates — run BEFORE the model call (gateway order:
frequency cap → spend/trial gate → provider call → post-call debit).

Two DIFFERENT blocks with two DIFFERENT user messages, by design:

- Frequency cap (`check_frequency_cap`): flat per-user anti-abuse insurance
  (runaway agent loops), Redis-backed sliding window. Blocking is TRANSIENT —
  "too many requests, try again in a moment" — the user can simply retry after
  the window. Same limit for every plan; it is abuse protection, not a plan
  feature. FAILS CLOSED (SOLUSDEV-321): Redis unconfigured, erroring, or slower
  than `REDIS_TIMEOUT_SECONDS` hands the same check to a per-process
  `_LocalFrequencyWindow`, so the limit still holds — per API process rather
  than fleet-wide — and a Redis outage neither takes down model calls nor
  waves callers through. Every call admitted through Redis is mirrored into
  that window, so an outage that starts mid-window starts from this process's
  own history, not from zero. One warning per process per cause; refusals are
  recorded with `limiter: "redis" | "local"`. HONEST LIMITS: (1) the Redis path
  (ZREMRANGEBYSCORE → ZCARD → ZADD) is not atomic, so a concurrent burst
  through a healthy Redis is NOT bounded by the limit — callers each read a
  count under it before any of them records; one atomic MULTI/EVAL script
  would fix that (not implemented). The local window is atomic on the event
  loop, so a burst on it admits exactly the limit. (2) The two windows
  disagree across a flap: calls recorded locally during an outage are
  invisible to Redis once it returns, and a Redis that comes back empty has
  forgotten earlier calls, so recovery can admit up to about twice the limit.
  (3) The DB-backed spend gate bounds SEQUENTIAL damage only (pre-flight read,
  debit lands post-call), so a concurrent burst can overshoot the trial cap by
  every call the frequency cap admits in it. Atomic at-debit cap enforcement +
  a concurrency red-team test are route-exposure work (see gateway.py deferral
  list).
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
TrialExpiredError / InsufficientCreditsError → 402.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from sqlalchemy import select

from solus_api.billing.development import session_development_unlimited
from solus_api.billing.entitlements import is_academic_expired, is_local_access_expired
from solus_api.models import (
    CreditLedger,
    CreditTxnType,
    Subscription,
    SubscriptionStatus,
    User,
)
from solus_api.orchestration.cost import account_spend, has_sufficient_credits
from solus_api.services.events import emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.orchestration.config import LimitsConfig

logger = logging.getLogger("solus.orchestration.gates")

UPGRADE_URL = "/settings/billing"
_FREQ_KEY_PREFIX = "solus:freqcap:"
# One check's whole Redis interaction must finish inside this, or the local window answers
# instead: a stopped Redis would otherwise stall each check for the client's 5 s connect timeout
# per command. ponytail: no circuit breaker — every check retries Redis, so a hung Redis costs
# each call up to this long; add a half-open breaker if outages become routine.
REDIS_TIMEOUT_SECONDS = 0.25
# Users the local window remembers before the least recently active one is forgotten.
_LOCAL_WINDOW_MAX_USERS = 4096


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


class TrialExpiredError(RuntimeError):
    """A local trial ran past its end date (SOLUSDEV-236) — choosing a plan is the
    way forward. Mapped to 402 `trial_expired` by the route layer."""

    def __init__(self, ends_at: datetime | None) -> None:
        self.ends_at = ends_at
        self.upgrade_url = UPGRADE_URL
        super().__init__(f"Free trial ended — choose a plan to continue: {UPGRADE_URL}")


class AcademicExpiredError(TrialExpiredError):
    """An Academic plan ran past its end date (ADR-042) — verifying again (or choosing a
    plan) is the way forward. A TrialExpiredError so every existing 402 path handles it;
    the SOL route maps it to its own `academic_expired` code."""

    def __init__(self, ends_at: datetime | None) -> None:
        super().__init__(ends_at)
        self.args = (
            f"Academic plan ended — verify your academic email again in Billing: {UPGRADE_URL}",
        )


class InsufficientCreditsError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(f"Not enough credits for this call — top up or upgrade: {UPGRADE_URL}")


# ponytail: per-process window — Redis is the shared one; with Redis down the cap is per API
# process. Calls Redis admits are mirrored here, so an outage that starts mid-window still
# refuses the 21st call; the recovery direction (calls recorded here during an outage are
# invisible to Redis once it returns) can still admit up to twice the limit across a flap, and
# LRU eviction behind 4,096 more recently active users resets that user's count. Add a shared
# fallback only if Redis outages become routine.
class _LocalFrequencyWindow:
    """The sliding window the cap falls back to whenever Redis cannot answer.

    Same shape as the Redis sorted set — call timestamps per user, pruned to the window — held
    in memory and LRU-bounded, so untrusted high-cardinality user ids cannot grow it without
    limit. Every method is synchronous with no await inside, so check-then-record is atomic
    on the event loop."""

    def __init__(self) -> None:
        self._calls: OrderedDict[uuid.UUID, deque[float]] = OrderedDict()

    def count(self, user_id: uuid.UUID, now: float, window: float) -> int:
        """Calls by `user_id` inside the window ending at `now`; expired ones are dropped."""
        calls = self._calls.get(user_id)
        if calls is None:
            return 0
        while calls and calls[0] <= now - window:  # inclusive edge, as Redis ZREMRANGEBYSCORE
            calls.popleft()
        if not calls:
            del self._calls[user_id]  # an idle user holds no slot
            return 0
        self._calls.move_to_end(user_id)
        return len(calls)

    def record(self, user_id: uuid.UUID, now: float) -> None:
        self._calls.setdefault(user_id, deque()).append(now)
        self._calls.move_to_end(user_id)
        if len(self._calls) > _LOCAL_WINDOW_MAX_USERS:
            self._calls.popitem(last=False)

    def oldest(self, user_id: uuid.UUID) -> float | None:
        calls = self._calls.get(user_id)
        return calls[0] if calls else None


_local_window = _LocalFrequencyWindow()
# Causes already warned about in this process: one warning per cause, never one per call.
_warned_causes: set[str] = set()


def _warn_local_once(cause: str, user_id: uuid.UUID, *, exc_info: bool = False) -> None:
    if cause in _warned_causes:
        return
    _warned_causes.add(cause)
    logger.warning(
        "frequency cap is running on the local per-process window (%s): the limit holds per "
        "API process, not fleet-wide, until redis answers again user_id=%s",
        cause,
        user_id,
        exc_info=exc_info,
    )


async def _redis_oldest(redis: RedisLike, key: str) -> float | None:
    try:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        return float(oldest[0][1]) if oldest else None
    except Exception:
        return None  # already over the limit; a broken read or reply never unblocks


async def _redis_count_and_record(
    redis: RedisLike, user_id: uuid.UUID, ts: float, window: int, limit: int
) -> tuple[int, float | None]:
    """The whole Redis side of one check, so a single timeout bounds all of it: drop expired
    calls, count, then read the oldest call (at/over the limit) or record this one (under it)."""
    key = f"{_FREQ_KEY_PREFIX}{user_id}"
    await redis.zremrangebyscore(key, 0, ts - window)
    count = await redis.zcard(key)
    if count >= limit:
        return count, await _redis_oldest(redis, key)
    await redis.zadd(key, {uuid.uuid4().hex: ts})
    await redis.expire(key, window)
    return count, None


def _local_count_and_record(
    user_id: uuid.UUID, ts: float, window: int, limit: int
) -> tuple[int, float | None]:
    count = _local_window.count(user_id, ts, window)
    if count >= limit:
        return count, _local_window.oldest(user_id)
    _local_window.record(user_id, ts)
    return count, None


async def _count_and_record(
    redis: RedisLike | None, user_id: uuid.UUID, ts: float, window: int, limit: int
) -> tuple[int, float | None, Literal["redis", "local"]]:
    """(calls in the window, oldest call, which limiter answered); records this call when under
    the limit. Redis answers when it can inside REDIS_TIMEOUT_SECONDS; otherwise the local
    window does, so the cap never lifts because Redis is absent, erroring or slow. Every call
    Redis admits is also mirrored into the local window (its own verdict is ignored), so an
    outage that starts mid-window starts from this process's history, not from zero."""
    if redis is None:
        _warn_local_once("redis_missing", user_id)
    else:
        try:
            count, oldest = await asyncio.wait_for(
                _redis_count_and_record(redis, user_id, ts, window, limit),
                timeout=REDIS_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            _warn_local_once("redis_slow", user_id)
        except Exception:  # CancelledError is a BaseException: an outer cancel still propagates
            _warn_local_once("redis_error", user_id, exc_info=True)
        else:
            if count < limit:  # admitted: mirror it (via count(), which prunes), verdict ignored
                _local_count_and_record(user_id, ts, window, limit)
            return count, oldest, "redis"
    count, oldest = _local_count_and_record(user_id, ts, window, limit)
    return count, oldest, "local"


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
    FAILS CLOSED: with Redis absent, erroring or slower than `REDIS_TIMEOUT_SECONDS`, the
    per-process `_LocalFrequencyWindow` answers instead (see the module docstring).
    Deterministic given `now` (tests inject it)."""
    ts = time.time() if now is None else now
    window, limit = limits.frequency_window_seconds, limits.max_calls_per_minute
    count, oldest_ts, limiter = await _count_and_record(redis, user_id, ts, window, limit)
    if count < limit:
        return
    # No readable oldest call means a full window: a broken read never unblocks early.
    retry_after = max(1, math.ceil((ts if oldest_ts is None else oldest_ts) + window - ts))
    logger.info(
        "frequency cap blocked user_id=%s count=%d limit=%d retry_after=%ds limiter=%s",
        user_id,
        count,
        limit,
        retry_after,
        limiter,
    )
    if session is not None:
        await _emit_block_event(
            session,
            user_id,
            reason="frequency_cap",
            detail={"retry_after": retry_after, "limiter": limiter},
        )
    raise FrequencyCapExceededError(retry_after)


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
    if sub is not None:
        await _assert_trial_not_expired(sub, user_id, session)
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


async def _assert_trial_not_expired(
    sub: Subscription, user_id: uuid.UUID, session: AsyncSession
) -> None:
    """SOLUSDEV-236 / ADR-024: an expired LOCAL trial refuses metered calls, unless the
    user's own ledger holds a PURCHASE and the balance covers one credit (the
    proposed purchased-credit unlock). A purchase with an empty balance is still
    `trial_expired`, not `insufficient_credits`: the account remains an expired trial."""
    if not is_local_access_expired(sub):
        return
    academic = is_academic_expired(sub)
    purchased = await session.scalar(
        select(CreditLedger.id)
        .where(CreditLedger.user_id == user_id, CreditLedger.type == CreditTxnType.PURCHASE)
        .limit(1)
    )
    if purchased is not None and await has_sufficient_credits(user_id, 1, session=session):
        return
    ends_at = sub.expires_at
    reason = "academic_expired" if academic else "trial_expired"
    logger.info("%s blocked user_id=%s ends_at=%s", reason, user_id, ends_at)
    await _emit_block_event(
        session,
        user_id,
        reason=reason,
        detail={"ends_at": ends_at.isoformat() if ends_at else None},
    )
    raise AcademicExpiredError(ends_at) if academic else TrialExpiredError(ends_at)


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
