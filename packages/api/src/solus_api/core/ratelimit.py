"""Interim per-process fixed-window rate limiting (§1.4).

This satisfies the "rate limits on everything" baseline for Phase 1. The
shared Redis-backed budget/limit system (ADR-019) replaces this in Phase 5;
the header contract is stable across the swap.
"""

import hashlib
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from solus_api.core.errors import error_response

EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})
WINDOW_SECONDS = 60
MAX_TRACKED_KEYS = 10_000
#: Methods that read. Everything else is a write and draws on the (smaller)
#: write budget — SOLUSDEV-234.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client fixed-window budgets.

    Reads (`SAFE_METHODS`) and writes are SEPARATE buckets (SOLUSDEV-234): the
    desktop is a polling-heavy client whose steady-state GET volume needs a
    budget an order of magnitude above anything a human's clicks can produce,
    while the write budget is the interim burst bound on model-calling POSTs
    until ADR-019's Redis frequency cap is live — raising one must never raise
    the other. `path_limits` gives named paths their OWN bucket (with its own
    limit), fully separate from both — e.g. the MO-04 classify preview, which
    is called on every typing pause and must neither starve nor consume the
    shared allowance.
    """

    def __init__(
        self,
        app: ASGIApp,
        limit_per_minute: int,
        path_limits: dict[str, int] | None = None,
        write_limit_per_minute: int | None = None,
    ) -> None:
        super().__init__(app)
        self._limit = limit_per_minute
        self._write_limit = (
            write_limit_per_minute if write_limit_per_minute is not None else limit_per_minute
        )
        self._path_limits = dict(path_limits or {})
        self._counters: dict[str, tuple[int, int]] = {}

    @staticmethod
    def _client_key(request: Request) -> str:
        auth = request.headers.get("authorization")
        if auth:
            return hashlib.sha256(auth.encode()).hexdigest()
        host = request.client.host if request.client else "unknown"
        return f"ip:{host}"

    def _bump(self, key: str, window: int) -> int:
        stored_window, count = self._counters.get(key, (window, 0))
        if stored_window != window:
            count = 0
        count += 1
        if len(self._counters) >= MAX_TRACKED_KEYS and key not in self._counters:
            stale = [k for k, (w, _) in self._counters.items() if w != window]
            for k in stale:
                del self._counters[k]
            # A flood of unique keys inside ONE window has no stale entries to
            # shed; drop the oldest so the table stays bounded regardless.
            while len(self._counters) >= MAX_TRACKED_KEYS:
                del self._counters[next(iter(self._counters))]
        self._counters[key] = (window, count)
        return count

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        now = int(time.time())
        window = now // WINDOW_SECONDS
        path_limit = self._path_limits.get(request.url.path)
        is_write = request.method.upper() not in SAFE_METHODS
        key = self._client_key(request)
        if path_limit is not None:
            limit = path_limit
            key = f"{key}|{request.url.path}"  # separate bucket, separate budget
        elif is_write:
            limit = self._write_limit
            key = f"{key}|write"
        else:
            limit = self._limit
        count = self._bump(key, window)
        reset = (window + 1) * WINDOW_SECONDS

        response: Response
        if count > limit:
            response = error_response(429, "rate_limited", "Rate limit exceeded")
            response.headers["Retry-After"] = str(max(1, reset - now))
        else:
            response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        response.headers["X-RateLimit-Reset"] = str(reset)
        return response
