"""`extensions.ratelimit` — the ONE lazy `app.state` limiter factory every
extension router shares (SOLUSDEV-235 Phase 4 REV-HIGH)."""

from __future__ import annotations

from types import SimpleNamespace

from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.services.artifacts import FixedWindowLimiter


def test_get_or_create_limiter_creates_once_and_reuses_the_same_instance() -> None:
    state = SimpleNamespace()

    first = get_or_create_limiter(state, "ext_limiter", 60)
    second = get_or_create_limiter(state, "ext_limiter", 3_600)

    assert isinstance(first, FixedWindowLimiter)
    assert first is second, "the window of the FIRST creation wins; the attr is a singleton"
    assert state.ext_limiter is first
    assert first.bump("u") == 1 and second.bump("u") == 2


def test_get_or_create_limiter_replaces_a_foreign_object_on_the_attr() -> None:
    state = SimpleNamespace(ext_limiter="not a limiter")
    limiter = get_or_create_limiter(state, "ext_limiter", 60)
    assert isinstance(limiter, FixedWindowLimiter)
    assert state.ext_limiter is limiter


def test_distinct_attrs_are_distinct_limiters() -> None:
    state = SimpleNamespace()
    a = get_or_create_limiter(state, "a", 60)
    b = get_or_create_limiter(state, "b", 60)
    assert a is not b


def test_rate_limited_response_is_429_with_retry_after() -> None:
    resp = rate_limited_response("slow down", 60)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    assert b"rate_limited" in resp.body
