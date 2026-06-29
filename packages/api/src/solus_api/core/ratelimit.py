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


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, limit_per_minute: int) -> None:
        super().__init__(app)
        self._limit = limit_per_minute
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
        self._counters[key] = (window, count)
        return count

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        now = int(time.time())
        window = now // WINDOW_SECONDS
        count = self._bump(self._client_key(request), window)
        reset = (window + 1) * WINDOW_SECONDS

        response: Response
        if count > self._limit:
            response = error_response(429, "rate_limited", "Rate limit exceeded")
            response.headers["Retry-After"] = str(max(1, reset - now))
        else:
            response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self._limit - count))
        response.headers["X-RateLimit-Reset"] = str(reset)
        return response
