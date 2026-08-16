"""SYS-05 perf: a bounded, TTL'd semantic cache for the retrieval feeds.

Sits inside `DbSolSystems` — the one chokepoint both `build_context` and the
SYS-03 tools flow through. An EXACT hit (checked first, no embedding needed)
skips the embed round-trip and the retrieval query; a SEMANTIC hit skips the
retrieval query. Tenant-keyed: every entry belongs to exactly one
`(project_id, kind)` — the caller folds k + filter shape into `kind` — and
neither the exact- nor the similarity-path can cross that boundary
(CLAUDE.md §7).

TTL over invalidation, deliberately: graph and error writes happen in the ARQ
worker process, invisible to an API-process cache, so a short TTL is the only
honest staleness bound available here.
Observability logs identifiers and counters only — never query text (§7).

# ponytail: in-process OrderedDict, linear similarity scan over ≤max_entries;
# Redis + pub/sub invalidation when multi-process serving needs it.
"""

from __future__ import annotations

import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

logger = logging.getLogger("solus.agent.perf")

DEFAULT_TTL_SECONDS = 120.0
DEFAULT_MAX_ENTRIES = 256
DEFAULT_SIMILARITY_THRESHOLD = 0.95
#: Entries examined per similarity lookup (newest first). Bounds the synchronous
#: CPU a lookup can burn on the event loop — a full 256×1536-d scan measured
#: ~25 ms, which a busy tenant could impose on every other tenant's turn.
MAX_SIMILARITY_SCAN = 64


def _normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def _vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


@dataclass
class _CacheEntry:
    embedding: list[float] | None
    norm: float  # precomputed ‖embedding‖ so a lookup never recomputes it
    value: Any
    stored_at: float


class SemanticCache:
    """Exact hits on normalized text are free; with a query embedding,
    near-duplicates (cosine >= threshold, same project AND kind) also hit.
    LRU-bounded at `max_entries`; entries expire after `ttl_seconds`.
    `clock` is injectable so TTL tests are deterministic."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._threshold = similarity_threshold
        self._clock = clock
        self._entries: OrderedDict[tuple[UUID, str, str], _CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def lookup(
        self,
        project_id: UUID,
        kind: str,
        text: str,
        embedding: list[float] | None = None,
    ) -> Any | None:
        now = self._clock()
        self._evict_expired(now)
        key = (project_id, kind, _normalize_query(text))
        entry = self._entries.get(key)
        if entry is not None:
            return self._hit(key, entry, now, mode="exact", similarity=1.0)
        if embedding is not None:
            query_norm = _vector_norm(embedding)
            examined = 0
            # Newest-first (LRU order), bounded: recency is the best relevance
            # proxy we have, and the cap keeps event-loop CPU bounded (M2).
            for other_key, other in reversed(self._entries.items()):
                if (
                    other_key[0] != project_id  # tenant boundary — never crossed
                    or other_key[1] != kind  # kind carries k + filter shape too
                    or other.embedding is None
                    or len(other.embedding) != len(embedding)
                ):
                    continue
                examined += 1
                if examined > MAX_SIMILARITY_SCAN:
                    break
                denominator = query_norm * other.norm
                if not denominator:
                    continue
                dot = sum(x * y for x, y in zip(embedding, other.embedding, strict=True))
                similarity = dot / denominator
                if similarity >= self._threshold:
                    return self._hit(other_key, other, now, mode="semantic", similarity=similarity)
        self._misses += 1
        return None

    def store(
        self,
        project_id: UUID,
        kind: str,
        text: str,
        embedding: list[float] | None,
        value: Any,
    ) -> None:
        key = (project_id, kind, _normalize_query(text))
        norm = _vector_norm(embedding) if embedding is not None else 0.0
        self._entries[key] = _CacheEntry(embedding, norm, value, self._clock())
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def stats(self) -> dict[str, float]:
        total = self._hits + self._misses
        return {
            "hits": float(self._hits),
            "misses": float(self._misses),
            "entries": float(len(self._entries)),
            "hit_rate": (self._hits / total) if total else 0.0,
        }

    def _hit(
        self,
        key: tuple[UUID, str, str],
        entry: _CacheEntry,
        now: float,
        *,
        mode: str,
        similarity: float,
    ) -> Any:
        self._entries.move_to_end(key)
        self._hits += 1
        # Identifiers and counters only — the query text never enters a log line.
        logger.info(
            "semantic cache hit kind=%s project=%s mode=%s similarity=%.3f age_s=%.1f "
            "hits=%d misses=%d",
            key[1],
            key[0],
            mode,
            similarity,
            now - entry.stored_at,
            self._hits,
            self._misses,
        )
        return entry.value

    def _evict_expired(self, now: float) -> None:
        expired = [
            key for key, entry in self._entries.items() if now - entry.stored_at >= self._ttl
        ]
        for key in expired:
            del self._entries[key]
