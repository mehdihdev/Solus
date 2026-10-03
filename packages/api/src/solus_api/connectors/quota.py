"""Provider API quota accounting (SOLUSDEV-167, ADR-019 as amended 2026-08-30).

A SECOND budget, separate from credits, because it is denominated in a unit
Solus neither buys nor can convert: a provider's own call allowance. Onshape's is
**2,500 calls per YEAR per Onshape user** — only 2xx/3xx counted, exhaustion
answers HTTP 402.

**Counted per provider ACCOUNT, not per team.** The provider meters the user, so
a team-keyed annual counter would hand one Onshape account N allowances — a team
with three projects would silently get three times the budget it has.

**The honest limit, which shapes the UI as much as the code:** the true remaining
allowance is unknowable from inside. We count only our own calls from whenever
the counter was created, so the ledger reads low for an account already partly
spent elsewhere. The only authoritative exhaustion signal is the provider's own
402 — which is why an observed one LATCHES rather than being retried past. Any
position surfaced to a user says "estimated".

**Fails open** (ADR-024: an accounting write never fails a user's request). No
Redis, or a Redis that throws, means no enforcement — the same documented policy
`orchestration/gates.py` follows. That is a real gap, not a silent one: it is
logged, and it is why the API warns at startup when Redis is absent.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, get_args
from urllib.parse import quote

logger = logging.getLogger("solus.connectors.quota")

_KEY_PREFIX = "solus:intq"

#: A year of retention plus slack, so the ledger outlives the window it counts.
_LEDGER_TTL_SECONDS = 400 * 24 * 3600
#: How long an observed 402 suppresses further spend. Long enough to stop a
#: runaway, short enough that a renewed allowance is picked up the same day.
_LATCH_TTL_SECONDS = 24 * 3600

#: Who is spending. Only a user's OWN explicit action survives the degraded band:
#: refusing a human's deliberate click to protect a budget they own is worse than
#: spending the call, whereas scheduled sweeps and agent turns can wait.
Purpose = Literal["user", "scheduled", "agent"]
_DEFERRABLE: frozenset[str] = frozenset({"scheduled", "agent"})

#: ADR-038 §4 — WHAT a call was for, recorded per call so the budget can be
#: attributed. Independent of `Purpose`, which decides admission.
CallLabel = Literal[
    "sync", "sweep", "webhook", "recovery", "agent_read", "agent_write", "picker", "connect"
]
_CALL_LABELS: tuple[str, ...] = get_args(CallLabel)

#: Whose annual pool a call is charged to, and how Onshape distributes the app.
#: A PRIVATE app's successes bill the app OWNER (one pool for every Solus user);
#: a public App Store app is exempt from the annual limit (ADR-038 §4).
Pool = Literal["owner", "user"]
Distribution = Literal["private", "app_store"]

#: Purpose -> the label a call carries when its caller did not name one.
_DEFAULT_LABEL: dict[str, CallLabel] = {
    "user": "sync",
    "scheduled": "sweep",
    "agent": "agent_read",
    "webhook": "webhook",
}

#: `X-Rate-Limit-Remaining` is a short-lived hint, not a ledger: stale quickly.
_RATE_LIMIT_TTL_SECONDS = 120
#: Warn when the provider says fewer than this many calls remain in its window.
_RATE_LIMIT_WARN_BELOW = 10
#: Anything above this is not a plausible per-window remaining count; ignore it.
_RATE_LIMIT_MAX = 100_000
_RETRY_AFTER_MAX_SECONDS = 3600.0

#: ADR-038 amendment 2: the pool latches once this many DISTINCT accounts have
#: observed a 402 inside the window.
_POOL_LATCH_ACCOUNTS = 2
#: Bound on the per-pool "402 accounts" set. The pool latches at 2, so this is
#: only a ceiling against a runaway writer.
_MAX_402_ACCOUNTS = 64


def default_label(purpose: str) -> CallLabel:
    """The label for a purpose when `ConnectorContext.label` is unset."""
    return _DEFAULT_LABEL.get(purpose, "sync")


class QuotaBlockedError(Exception):
    """Refused before the call left the process. Carries a stable code so the
    routers and the agent tool layer can map it without string-matching."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class QuotaState:
    """What we can honestly say about an account's position."""

    used: int
    allowance: int
    degraded: bool
    exhausted: bool
    #: Always True. The count starts when the counter does, never when the
    #: provider's year did, so this is a floor on our own spend and never a
    #: remaining balance. The UI must not present it as one.
    estimated: bool = True
    #: ADR-038 §4 read-out. Additive; defaults describe a plain per-account meter.
    pool: Pool = "user"
    distribution: Distribution = "private"
    #: Calls this year by `CallLabel` in the SAME pool. Aggregate only — never
    #: per-account or per-team, so an owner pool reveals no other tenant.
    by_label: dict[str, int] = field(default_factory=dict)
    #: Latest `X-Rate-Limit-Remaining` seen for the pool, if recent.
    rate_limit_remaining: int | None = None

    def readout(self) -> dict[str, Any]:
        """The additive API payload: every pre-ADR-038 field with its meaning."""
        return {
            "status": self.status,
            "used": self.used,
            "allowance": self.allowance,
            "estimated": self.estimated,
            "pool": self.pool,
            "distribution": self.distribution,
            "by_label": dict(self.by_label),
            "rate_limit_remaining": self.rate_limit_remaining,
        }

    @property
    def status(self) -> str:
        if self.exhausted:
            return "exhausted"
        return "degraded" if self.degraded else "ok"


def _year_key(provider: str, account_ref: str, year: int) -> str:
    return f"{_KEY_PREFIX}:{provider}:acct:{_segment(account_ref)}:{year}"


def _latch_key(provider: str, account_ref: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:acct:{_segment(account_ref)}:402"


def _rate_limit_key(provider: str, account_ref: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:acct:{_segment(account_ref)}:rl"


def _402_accounts_key(provider: str, pool_scope: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:acct:{_segment(pool_scope)}:402accts"


def _pools_key(provider: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:pools"


def _account_hash(account_scope: str) -> str:
    """What the 402-accounts set stores: never a raw provider account id."""
    return hashlib.sha256(account_scope.encode()).hexdigest()


async def known_pools(redis: Any | None, provider: str) -> list[str]:
    """Owner-pool scopes that have recorded a call (staff view). Fails open."""
    if redis is None:
        return []
    try:
        raw = await redis.smembers(_pools_key(provider))
    except Exception:  # noqa: BLE001
        logger.warning("could not list quota pools")
        return []
    return sorted(m.decode() if isinstance(m, bytes) else str(m) for m in raw)


def _segment(value: str) -> str:
    """A provider-supplied id cannot contain the separator and shift a key."""
    return quote(value, safe="")


class CallMeter:
    """Counts and admits outbound calls for ONE ledger — a provider account, or
    (owner pool) every account under one OAuth application. `account_ref` is the
    ledger scope either way; the caller decides what it names."""

    def __init__(
        self,
        redis: Any | None,
        *,
        provider: str,
        account_ref: str,
        year: int,
        allowance: int,
        degrade_ratio: float,
        purpose: Purpose = "user",
        pool: Pool = "user",
        distribution: Distribution = "private",
        label: CallLabel | None = None,
        account_scope: str | None = None,
    ) -> None:
        self._redis = redis
        self._provider = provider
        # An account id can be missing or empty (the column is nullable, and
        # Onshape's read-only scope can yield ""), and every such source would
        # then collide on ONE key — letting one team latch another team's 402.
        # Callers substitute a project-scoped fallback: coarser granularity than
        # a real account, but never shared across tenants.
        self._account_ref = account_ref
        self._year = year
        self._allowance = allowance
        self._degrade_ratio = degrade_ratio
        self._purpose = purpose
        self._pool = pool
        self._distribution = distribution
        self._label: CallLabel = label or default_label(purpose)
        # ADR-038 amendment: in owner mode `account_ref` names the POOL and
        # `account_scope` the calling account, which gets its own ledger, labels
        # and 402 latch. Equal or absent means one ledger (user mode).
        self._account_scope = (
            account_scope if account_scope and account_scope != account_ref else None
        )

    async def admit(self) -> None:
        """Raise `QuotaBlockedError` if this call must not be made."""
        if self._redis is None:
            return  # fail open, by policy
        try:
            if self._account_scope is not None and await self._redis.get(
                _latch_key(self._provider, self._account_scope)
            ):
                raise QuotaBlockedError(
                    "quota_exhausted",
                    "the provider reported this account's API allowance exhausted",
                )
            if await self._redis.get(self._latch_key()):
                raise QuotaBlockedError(
                    "quota_exhausted",
                    "the provider reported this account's API allowance exhausted",
                )
            raw = await self._redis.get(self._year_key())
        except QuotaBlockedError:
            raise
        except Exception:  # noqa: BLE001 — a broken meter never blocks work
            logger.warning("quota meter unavailable; admitting uncounted")
            return
        used = int(raw or 0)
        if self._distribution == "app_store":
            return  # public apps are exempt from the annual limit; only the latch bites
        if used >= self._allowance:
            raise QuotaBlockedError(
                "quota_exhausted", "this account's configured API allowance is spent"
            )
        if self._purpose in _DEFERRABLE and used >= self._allowance * self._degrade_ratio:
            raise QuotaBlockedError(
                "quota_degraded",
                "close to the provider API allowance; deferrable work is paused",
            )

    async def record(self, status_code: int) -> None:
        """Count a completed call. NEVER raises (ADR-024)."""
        redis = self._redis
        if redis is None:
            return
        if status_code == 402:
            await self._latch(redis)
            return
        # Only 2xx/3xx count — the provider's own rule. A 429 or a 404 is
        # free, which is why the retry ladders cost wall-clock, not quota.
        if not (200 <= status_code < 400):
            return
        if not await self._count(redis, self._year_key()):
            return
        await self._count_label(redis, self._label_key(self._label))
        if self._account_scope is not None:
            await self._register_pool(redis)
            account_key = _year_key(self._provider, self._account_scope, self._year)
            if await self._count(redis, account_key):
                await self._count_label(redis, f"{account_key}:{self._label}")

    async def _count(self, redis: Any, key: str) -> bool:
        try:
            if await redis.incr(key) == 1:
                await redis.expire(key, _LEDGER_TTL_SECONDS)
        except Exception:  # noqa: BLE001 — accounting never fails the request
            logger.warning("could not record a provider call against the quota ledger")
            return False
        return True

    async def _count_label(self, redis: Any, key: str) -> None:
        """Attribution only: its failure never costs the year count."""
        try:
            if await redis.incr(key) == 1:
                await redis.expire(key, _LEDGER_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            logger.warning("could not record a call label")

    async def _register_pool(self, redis: Any) -> None:
        try:
            await redis.sadd(_pools_key(self._provider), self._account_ref)
        except Exception:  # noqa: BLE001
            logger.warning("could not register the quota pool")

    async def _latch(self, redis: Any) -> None:
        """ADR-038 amendment 2: a 402 latches the calling ACCOUNT; the pool only
        once enough distinct accounts have seen one inside the window."""
        try:
            own = self._account_scope or self._account_ref
            await redis.set(_latch_key(self._provider, own), "1", ex=_LATCH_TTL_SECONDS)
            logger.warning("provider reported quota exhausted provider=%s", self._provider)
            if self._account_scope is not None:
                await self._register_pool(redis)
                await self._note_402_account(redis)
        except Exception:  # noqa: BLE001 — accounting never fails the request
            logger.warning("could not record the 402 latch")

    async def _note_402_account(self, redis: Any) -> None:
        key = _402_accounts_key(self._provider, self._account_ref)
        if await redis.scard(key) < _MAX_402_ACCOUNTS:
            await redis.sadd(key, _account_hash(self._account_scope or ""))
            if await redis.scard(key) == 1:
                await redis.expire(key, _LATCH_TTL_SECONDS)
        if await redis.scard(key) >= _POOL_LATCH_ACCOUNTS:
            await redis.set(self._latch_key(), "1", ex=_LATCH_TTL_SECONDS)
            logger.warning("owner pool latched provider=%s", self._provider)

    async def observe_rate_limit(
        self, remaining: int | None, retry_after: float | None = None
    ) -> None:
        """Remember the provider's latest `X-Rate-Limit-Remaining` for the pool.
        Header values are untrusted: anything not a plausible count is ignored.
        NEVER raises (ADR-024)."""
        if (
            isinstance(remaining, bool)
            or not isinstance(remaining, int)
            or not 0 <= remaining <= _RATE_LIMIT_MAX
        ):
            return
        if remaining < _RATE_LIMIT_WARN_BELOW:
            hint = retry_after if _plausible_retry_after(retry_after) else None
            logger.warning(
                "provider rate limit nearly spent provider=%s remaining=%d retry_after=%s",
                self._provider,
                remaining,
                hint,
            )
        if self._redis is None:
            return
        try:
            await self._redis.set(
                _rate_limit_key(self._provider, self._account_ref),
                str(remaining),
                ex=_RATE_LIMIT_TTL_SECONDS,
            )
        except Exception:  # noqa: BLE001
            logger.warning("could not record the rate-limit observation")

    async def state(self) -> QuotaState:
        """The caller's position: its OWN used/by_label (owner mode) against the
        pool's band. Pool totals are `pool_view`'s, staff-only."""
        used, pool_used, exhausted = 0, 0, False
        by_label: dict[str, int] = {}
        remaining: int | None = None
        if self._redis is not None:
            try:
                pool_used = int(await self._redis.get(self._year_key()) or 0)
                exhausted = bool(await self._redis.get(self._latch_key()))
                if self._account_scope is None:
                    used, by_label = pool_used, await self._read_labels(self._year_key())
                else:
                    account_key = _year_key(self._provider, self._account_scope, self._year)
                    used = int(await self._redis.get(account_key) or 0)
                    by_label = await self._read_labels(account_key)
                    exhausted = exhausted or bool(
                        await self._redis.get(_latch_key(self._provider, self._account_scope))
                    )
                raw = await self._redis.get(_rate_limit_key(self._provider, self._account_ref))
                remaining = int(raw) if raw is not None else None
            except Exception:  # noqa: BLE001
                logger.warning("could not read the quota ledger")
                used, pool_used, exhausted, by_label, remaining = 0, 0, False, {}, None
        public = self._distribution == "app_store"
        return QuotaState(
            used=used,
            allowance=self._allowance,
            degraded=not public and pool_used >= self._allowance * self._degrade_ratio,
            exhausted=exhausted or (not public and pool_used >= self._allowance),
            pool=self._pool,
            distribution=self._distribution,
            by_label=by_label,
            rate_limit_remaining=remaining,
        )

    async def pool_view(self) -> dict[str, Any]:
        """Pool-wide totals for STAFF (never team-facing): the pool ledger,
        labels, latch, 402-account count and rate-limit hint. Pure reads."""
        redis, pool = self._redis, self._account_ref
        used, latched, accounts, remaining = 0, False, 0, None
        by_label: dict[str, int] = {}
        if redis is not None:
            try:
                used = int(await redis.get(self._year_key()) or 0)
                latched = bool(await redis.get(self._latch_key()))
                accounts = int(await redis.scard(_402_accounts_key(self._provider, pool)))
                by_label = await self._read_labels(self._year_key())
                raw = await redis.get(_rate_limit_key(self._provider, pool))
                remaining = int(raw) if raw is not None else None
            except Exception:  # noqa: BLE001
                logger.warning("could not read the pool ledger")
                used, latched, accounts, remaining, by_label = 0, False, 0, None, {}
        return {
            "used": used,
            "allowance": self._allowance,
            "by_label": by_label,
            "latched": latched,
            "latched_accounts_count": accounts,
            "rate_limit_remaining": remaining,
            "distribution": self._distribution,
        }

    async def _read_labels(self, ledger_key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for label in _CALL_LABELS:
            count = int(await self._redis.get(f"{ledger_key}:{label}") or 0)  # type: ignore[union-attr]
            if count:
                counts[label] = count
        return counts

    def _label_key(self, label: str) -> str:
        return f"{self._year_key()}:{label}"

    def _year_key(self) -> str:
        return _year_key(self._provider, self._account_ref, self._year)

    def _latch_key(self) -> str:
        return _latch_key(self._provider, self._account_ref)


def _plausible_retry_after(value: float | None) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and 0 <= value <= _RETRY_AFTER_MAX_SECONDS
    )
