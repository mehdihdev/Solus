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

import logging
from dataclasses import dataclass
from typing import Any, Literal
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

    @property
    def status(self) -> str:
        if self.exhausted:
            return "exhausted"
        return "degraded" if self.degraded else "ok"


def _year_key(provider: str, account_ref: str, year: int) -> str:
    return f"{_KEY_PREFIX}:{provider}:acct:{_segment(account_ref)}:{year}"


def _latch_key(provider: str, account_ref: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:acct:{_segment(account_ref)}:402"


def _segment(value: str) -> str:
    """A provider-supplied id cannot contain the separator and shift a key."""
    return quote(value, safe="")


class CallMeter:
    """Counts and admits outbound calls for ONE provider account."""

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

    async def admit(self) -> None:
        """Raise `QuotaBlockedError` if this call must not be made."""
        if self._redis is None:
            return  # fail open, by policy
        try:
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
        try:
            if status_code == 402:
                await redis.set(self._latch_key(), "1", ex=_LATCH_TTL_SECONDS)
                logger.warning("provider reported quota exhausted provider=%s", self._provider)
                return
            # Only 2xx/3xx count — the provider's own rule. A 429 or a 404 is
            # free, which is why the retry ladders cost wall-clock, not quota.
            if not (200 <= status_code < 400):
                return
            key = self._year_key()
            used = await redis.incr(key)
            if used == 1:
                await redis.expire(key, _LEDGER_TTL_SECONDS)
        except Exception:  # noqa: BLE001 — accounting never fails the request
            logger.warning("could not record a provider call against the quota ledger")

    async def state(self) -> QuotaState:
        used, exhausted = 0, False
        if self._redis is not None:
            try:
                used = int(await self._redis.get(self._year_key()) or 0)
                exhausted = bool(await self._redis.get(self._latch_key()))
            except Exception:  # noqa: BLE001
                logger.warning("could not read the quota ledger")
        return QuotaState(
            used=used,
            allowance=self._allowance,
            degraded=used >= self._allowance * self._degrade_ratio,
            exhausted=exhausted or used >= self._allowance,
        )

    def _year_key(self) -> str:
        return _year_key(self._provider, self._account_ref, self._year)

    def _latch_key(self) -> str:
        return _latch_key(self._provider, self._account_ref)
