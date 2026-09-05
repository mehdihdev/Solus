"""The integration cache (SOLUSDEV-241 / I1) — what a provider already told us.

The change-signal spine (`docs/architecture/change-signal-spine.md`) fixed the
posture: the graph is the source of truth and refreshing is the only thing
allowed to spend a provider's quota. This module is the READ side of that
posture. Three kinds of entry, one key discipline:

* **listing** — an account's documents/repositories, as the picker shows them.
  Served from here after the first fetch; refreshed only on an explicit
  `refresh` or a webhook doorbell. There is no timer.
* **signal** — a document's current change token (Onshape microversion) plus
  whatever was fetched IN ORDER to read it (the workspace id). Each entry
  records when it was observed; a reader says how stale it may be. A human's
  sync trusts it for the sweep interval, the sweep for a few minutes (so two
  projects tracking one document cost one probe per sweep), a webhook never.
* **payload** — an expensive read keyed by the change token: the element list,
  a STEP export, part metadata. A change makes every derived key unreachable,
  so there is no invalidation code at all (the spine's design, now built).

**Keys carry the ACCOUNT, never a project or a source.** `httpcache.py` records
why `team_id` and `source_id` are both wrong; the account is the identity the
credentials prove, and it is what lets two projects — or two teammates — share
one fetch. A hit is only ever served to a caller that resolved that account's
credentials, so an entry can never cross accounts.

**Never cached here:** anything inside a confirmable operation (the action gate
re-runs previews on purpose), and any 401 (the credential-refresh path keys off
it). Neither is offered as a key kind, by construction.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from solus_api.connectors.httpcache import CacheStore, release_flight, single_flight

logger = logging.getLogger("solus.connectors.integration_cache")

_PREFIX = "solus:ic"
#: How long one fetch may hold the flight for a key before losers fetch too.
_FETCH_FLIGHT_SECONDS = 60

DEFAULT_LISTING_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_SIGNAL_TTL_SECONDS = 3600
DEFAULT_PAYLOAD_TTL_SECONDS = 30 * 24 * 3600
#: Above this a payload is fetched and used but NOT stored: the STEP parse
#: limit is 64 MiB and a Redis value that size is a liability, not a cache.
DEFAULT_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024


def _segment(value: str) -> str:
    """One key segment. Quoted so a provider-supplied id can never contain the
    separator and alias another entry."""
    return quote(value, safe="")


@dataclass(frozen=True)
class Fetched[T]:
    value: T
    #: True when served from the cache; False when this call paid for it.
    cached: bool
    #: When the value was actually read from the provider (ISO-8601, UTC).
    fetched_at: str


class IntegrationCache:
    def __init__(
        self,
        store: CacheStore,
        *,
        listing_ttl_seconds: int = DEFAULT_LISTING_TTL_SECONDS,
        signal_ttl_seconds: int = DEFAULT_SIGNAL_TTL_SECONDS,
        payload_ttl_seconds: int = DEFAULT_PAYLOAD_TTL_SECONDS,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self.listing_ttl_seconds = listing_ttl_seconds
        self.signal_ttl_seconds = signal_ttl_seconds
        self.payload_ttl_seconds = payload_ttl_seconds
        self._max_payload_bytes = max_payload_bytes
        self._clock = clock

    # ------------------------------------------------------------- keys

    @staticmethod
    def account_key(provider: str, account_ref: str) -> str:
        return f"{_PREFIX}:{_segment(provider)}:{_segment(account_ref)}"

    @classmethod
    def listing_key(cls, provider: str, account_ref: str) -> str:
        return f"{cls.account_key(provider, account_ref)}:listing"

    @classmethod
    def signal_key(cls, provider: str, account_ref: str, item: str) -> str:
        return f"{cls.account_key(provider, account_ref)}:signal:{_segment(item)}"

    @classmethod
    def payload_key(
        cls, provider: str, account_ref: str, item: str, version: str, kind: str, *parts: str
    ) -> str:
        tail = ":".join(_segment(part) for part in (kind, item, version, *parts))
        return f"{cls.account_key(provider, account_ref)}:{tail}"

    # ------------------------------------------------------------- raw

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=UTC).isoformat()

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._store.get(key)
        except Exception:  # noqa: BLE001 — a broken cache is a miss, never an outage
            logger.warning("integration cache read failed for %s", key)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            logger.warning("integration cache held malformed JSON at %s; dropping", key)
            await self.invalidate(key)
            return None

    async def put(self, key: str, value: Any, ttl_seconds: int) -> bool:
        """Store `value`. False when it was too large to keep — the caller
        still has the value; only the NEXT reader pays again."""
        try:
            encoded = json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError):
            logger.warning("integration cache refused a non-JSON value at %s", key)
            return False
        if len(encoded.encode("utf-8")) > self._max_payload_bytes:
            logger.info("integration cache skipped an oversize payload at %s", key)
            return False
        try:
            await self._store.set(key, encoded, ttl_seconds)
        except Exception:  # noqa: BLE001
            logger.warning("integration cache write failed for %s", key)
            return False
        return True

    async def invalidate(self, key: str) -> None:
        try:
            await self._store.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("integration cache invalidate failed for %s", key)

    # ------------------------------------------------------------- fetch-through

    async def fetch[T](
        self,
        key: str,
        *,
        ttl_seconds: int,
        fetch: Callable[[], Awaitable[T]],
        refresh: bool = False,
    ) -> Fetched[T]:
        """Serve `key` from the cache, or pay once and store it.

        Single-flight across processes: N concurrent misses collapse to one
        upstream call, and the losers read what the winner stored. `refresh`
        bypasses the read but still stores, so an explicit "refresh" is what
        moves the entry — never a timer.
        """
        if not refresh:
            hit = await self._stored(key)
            if hit is not None:
                return hit
        flight = f"{key}:flight"
        await single_flight(self._store, flight, ttl_seconds=_FETCH_FLIGHT_SECONDS)
        try:
            if not refresh:
                hit = await self._stored(key)
                if hit is not None:
                    return hit
            value = await fetch()
            fetched_at = self._now_iso()
            await self.put(key, {"value": value, "fetched_at": fetched_at}, ttl_seconds)
            return Fetched(value, False, fetched_at)
        finally:
            await release_flight(self._store, flight)

    async def _stored(self, key: str) -> Fetched[Any] | None:
        entry = await self.get(key)
        if isinstance(entry, dict) and "value" in entry and "fetched_at" in entry:
            return Fetched(entry["value"], True, str(entry["fetched_at"]))
        return None

    # ------------------------------------------------------------- signals

    async def signal(self, key: str, *, max_age_seconds: float | None) -> dict[str, Any] | None:
        """The recorded change signal, if it is young enough to trust.

        `None` for `max_age_seconds` means "never trust a recorded one" — the
        webhook posture: a doorbell rang, so ask the provider.
        """
        if max_age_seconds is None:
            return None
        entry = await self.get(key)
        if not isinstance(entry, dict):
            return None
        if not self.is_fresh(entry.get("observed_at"), max_age_seconds=max_age_seconds):
            return None
        return entry

    def is_fresh(self, observed_at: Any, *, max_age_seconds: float | None) -> bool:
        """Whether a signal observed at `observed_at` may still be trusted by a
        reader allowing `max_age_seconds` (`None`: never). For callers that
        already hold the entry, so one read serves both shape and freshness."""
        if max_age_seconds is None or not isinstance(observed_at, int | float):
            return False
        return self._clock() - observed_at <= max_age_seconds

    async def record_signal(self, key: str, payload: dict[str, Any]) -> None:
        await self.put(
            key, {**payload, "observed_at": self._clock()}, ttl_seconds=self.signal_ttl_seconds
        )


__all__ = [
    "DEFAULT_LISTING_TTL_SECONDS",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "DEFAULT_PAYLOAD_TTL_SECONDS",
    "DEFAULT_SIGNAL_TTL_SECONDS",
    "Fetched",
    "IntegrationCache",
]
