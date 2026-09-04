"""The one lazy `app.state` limiter factory for the extension routers
(SOLUSDEV-235 Phase 4 REV-HIGH; docs/api/extensions.md §12).

Four routers used to each re-implement "get the `FixedWindowLimiter` off
`app.state`, or create it". One factory keeps the semantics in one place:
per-process, created on first use (so `main.create_app` needs no wiring), the
FIRST creation's window wins, and a foreign object on the attr is replaced
rather than trusted. The artifacts.md §4.5 caveats (per-instance counters;
Redis when multi-instance) apply exactly as before.
"""

from __future__ import annotations

from typing import Any

from fastapi import Response

from solus_api.core.errors import error_response
from solus_api.services.artifacts import FixedWindowLimiter


def get_or_create_limiter(app_state: Any, attr: str, window_seconds: int) -> FixedWindowLimiter:
    """The `FixedWindowLimiter` stored on `app_state.<attr>`, created with
    `window_seconds` on first use. Idempotent; the attr is a singleton."""
    limiter = getattr(app_state, attr, None)
    if not isinstance(limiter, FixedWindowLimiter):
        limiter = FixedWindowLimiter(window_seconds=window_seconds)
        setattr(app_state, attr, limiter)
    return limiter


def rate_limited_response(message: str, retry_after_seconds: int) -> Response:
    """§12: `429 rate_limited` + `Retry-After` — the same envelope on every route."""
    resp = error_response(429, "rate_limited", message)
    resp.headers["Retry-After"] = str(retry_after_seconds)
    return resp


__all__ = ["get_or_create_limiter", "rate_limited_response"]
