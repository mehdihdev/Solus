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

**Never cached here:** mutable target state inside a confirmable operation, or
any failed fetch including 401 (credential refresh depends on that failure). The
approved ADR-019/035 amendment permits immutable donor/specification reads keyed
by account and a freshly verified revision; `onshape_read_cache.py` provides that
restricted default-configuration entrypoint. Approval still refreshes target state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from solus_api.connectors.httpcache import CacheStore, release_flight, run_in_flight, single_flight

logger = logging.getLogger("solus.connectors.integration_cache")

#: Its OWN prefix — `httpcache.py` owns `solus:ic:sync:…` for sync single-flight,
#: and a provider literally named `sync` must not collide with it.
_PREFIX = "solus:icache"
#: Lease lifetime; waiters must still acquire their own claim before fetching.
_FETCH_FLIGHT_SECONDS = 60
#: Per-account key index (for `invalidate_account`), bounded so a runaway
#: producer cannot grow one JSON list without limit.
_INDEX_SUFFIX = ":__keys"
_INDEX_MAX_KEYS = 5000
_INDEX_TTL_SECONDS = 60 * 24 * 3600

DEFAULT_LISTING_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_SIGNAL_TTL_SECONDS = 3600
DEFAULT_PAYLOAD_TTL_SECONDS = 30 * 24 * 3600
#: Above this a payload is fetched and used but NOT stored: the STEP parse
#: limit is 64 MiB and a Redis value that size is a liability, not a cache.
DEFAULT_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
#: An explicit `refresh` inside this window after the last provider walk is
#: served from the cache anyway: a refresh button (or a script holding one
#: down) can spend at most one walk per window per ACCOUNT, however many
#: principals share the grant.
DEFAULT_LISTING_REFRESH_COOLDOWN_SECONDS = 60


def _describe(key: str) -> str:
    """A key for LOGS: its kind plus a digest, never the account or document id
    it carries (customer metadata stays out of log lines)."""
    parts = key.split(":")
    kind = parts[4] if len(parts) > 4 else "?"
    return f"{kind}#{hashlib.sha256(key.encode()).hexdigest()[:12]}"


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
        listing_refresh_cooldown_seconds: int = DEFAULT_LISTING_REFRESH_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self.listing_ttl_seconds = listing_ttl_seconds
        self.signal_ttl_seconds = signal_ttl_seconds
        self.payload_ttl_seconds = payload_ttl_seconds
        self.listing_refresh_cooldown_seconds = listing_refresh_cooldown_seconds
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

    @staticmethod
    def _iso(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._store.get(key)
        except Exception:  # noqa: BLE001 — a broken cache is a miss, never an outage
            logger.warning("integration cache read failed for %s", _describe(key))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            logger.warning("integration cache held malformed JSON at %s; dropping", _describe(key))
            await self.invalidate(key)
            return None

    async def put(self, key: str, value: Any, ttl_seconds: int) -> bool:
        """Store `value`. False when it was too large to keep — the caller
        still has the value; only the NEXT reader pays again."""
        if _obviously_oversize(value, self._max_payload_bytes):
            # Decided BEFORE encoding: a 64 MiB STEP export must not be
            # JSON-encoded and re-encoded just to be thrown away.
            logger.info("integration cache skipped an oversize payload at %s", _describe(key))
            return False
        try:
            encoded = json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError):
            logger.warning("integration cache refused a non-JSON value at %s", _describe(key))
            return False
        if len(encoded.encode("utf-8")) > self._max_payload_bytes:
            logger.info("integration cache skipped an oversize payload at %s", _describe(key))
            return False
        try:
            await self._store.set(key, encoded, ttl_seconds)
        except Exception:  # noqa: BLE001
            logger.warning("integration cache write failed for %s", _describe(key))
            return False
        await self._index(key)
        return True

    async def _index(self, key: str) -> None:
        """Remember `key` under its account, so `invalidate_account` can find
        it. Best-effort: a lost index entry costs retention, never correctness."""
        account = _account_of(key)
        if account is None:
            return
        index_key = account + _INDEX_SUFFIX
        try:
            raw = await self._store.get(index_key)
            keys: list[str] = json.loads(raw) if raw else []
            if key in keys:
                return
            keys = [*keys[-(_INDEX_MAX_KEYS - 1) :], key]
            await self._store.set(index_key, json.dumps(keys), _INDEX_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            logger.warning("integration cache could not index %s", _describe(key))

    async def invalidate_account(self, provider: str, account_ref: str) -> int:
        """Drop everything cached for one account — on revoke and on account
        deletion, so derived copies of a customer's CAD do not outlive the
        grant. Returns how many entries were removed."""
        account = self.account_key(provider, account_ref)
        index_key = account + _INDEX_SUFFIX
        try:
            raw = await self._store.get(index_key)
        except Exception:  # noqa: BLE001
            logger.warning("integration cache could not read the index for an account")
            return 0
        keys: list[str] = json.loads(raw) if raw else []
        for key in keys:
            await self.invalidate(key)
        await self.invalidate(index_key)
        return len(keys)

    async def invalidate(self, key: str) -> None:
        try:
            await self._store.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("integration cache invalidate failed for %s", _describe(key))

    async def cached_listing(
        self, provider: str, account_ref: str
    ) -> Fetched[list[dict[str, Any]]] | None:
        """Read a validated I1 listing without invoking a fetch or credentials."""
        hit = await self._stored(self.listing_key(provider, account_ref), float("inf"))
        if hit is None or not isinstance(hit.value, list):
            return None
        for item in hit.value:
            if (
                not isinstance(item, dict)
                or not all(
                    isinstance(item.get(field), str) and item[field] for field in ("id", "name")
                )
                or ("config" in item and not isinstance(item["config"], dict))
            ):
                return None
        return hit

    # ------------------------------------------------------------- fetch-through

    async def fetch[T](
        self,
        key: str,
        *,
        ttl_seconds: int,
        fetch: Callable[[], Awaitable[T]],
        refresh: bool = False,
        min_age_seconds: float = 0,
    ) -> Fetched[T]:
        """Serve `key` from the cache, or pay once and store it.

        Single-flight across processes: N concurrent misses collapse to one
        upstream call, and the losers read what the winner stored. `refresh`
        bypasses the read but still stores, so an explicit "refresh" is what
        moves the entry — never a timer. `min_age_seconds` is the refresh
        COOLDOWN: a refresh that finds an entry younger than that is served the
        entry, so N refreshes inside the window — from N principals sharing
        one grant — cost one provider walk, not N.
        """
        # A refresh accepts only an entry younger than the cooldown; a plain
        # read accepts any entry the store still holds.
        window = min_age_seconds if refresh else float("inf")
        hit = await self._stored(key, window)
        if hit is not None:
            return hit
        flight = f"{key}:flight"
        owner = await single_flight(self._store, flight, ttl_seconds=_FETCH_FLIGHT_SECONDS)

        async def fetch_owned() -> Fetched[T]:
            hit = await self._stored(key, window)
            if hit is not None:
                return hit
            value = await fetch()
            fetched_ts = self._clock()
            fetched_at = self._iso(fetched_ts)
            await self.put(
                key,
                {"value": value, "fetched_at": fetched_at, "fetched_ts": fetched_ts},
                ttl_seconds,
            )
            return Fetched(value, False, fetched_at)

        try:
            return await run_in_flight(
                self._store, flight, owner, ttl_seconds=_FETCH_FLIGHT_SECONDS, run=fetch_owned
            )
        finally:
            await release_flight(self._store, flight, owner)

    async def _stored(self, key: str, max_age_seconds: float) -> Fetched[Any] | None:
        """The stored entry when it exists and is no older than `max_age_seconds`
        (`inf`: any age; `0`: the refresh posture with no cooldown)."""
        if max_age_seconds <= 0:
            return None
        entry = await self.get(key)
        if not (isinstance(entry, dict) and "value" in entry and "fetched_at" in entry):
            return None
        fetched_at = entry["fetched_at"]
        if not isinstance(fetched_at, str):
            return None
        try:
            datetime.fromisoformat(fetched_at)
        except ValueError:
            return None
        fetched_ts = entry.get("fetched_ts")
        if max_age_seconds != float("inf"):
            if not isinstance(fetched_ts, int | float):
                return None
            if self._clock() - fetched_ts > max_age_seconds:
                return None
        return Fetched(entry["value"], True, str(entry["fetched_at"]))

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


def _account_of(key: str) -> str | None:
    """`solus:icache:{provider}:{account}` for any key of this cache, else None."""
    parts = key.split(":")
    if len(parts) < 4 or ":".join(parts[:2]) != _PREFIX:
        return None
    return ":".join(parts[:4])


def _obviously_oversize(value: Any, limit: int) -> bool:
    """Cheap pre-check for the one shape that gets big — a text payload."""
    return isinstance(value, str) and len(value) > limit


__all__ = [
    "DEFAULT_LISTING_TTL_SECONDS",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "DEFAULT_PAYLOAD_TTL_SECONDS",
    "DEFAULT_SIGNAL_TTL_SECONDS",
    "Fetched",
    "IntegrationCache",
]
