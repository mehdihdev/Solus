"""The consolidated MO-03 transient-retry loop (SYS-05).

Pins the exact policy both `gateway` and `embeddings` previously carried as
copies: exponential backoff doubling from `retry_backoff_seconds`, at most
`retry_max_attempts` total tries, ONLY `ProviderTransientError` retried.
"""

from __future__ import annotations

import pytest
from solus_api.orchestration.config import LimitsConfig
from solus_api.orchestration.providers import ProviderError, ProviderTransientError
from solus_api.orchestration.retry import CircuitBreaker, CircuitOpenError, retry_transient


def _limits(attempts: int = 3, backoff: float = 0.5) -> LimitsConfig:
    return LimitsConfig(retry_max_attempts=attempts, retry_backoff_seconds=backoff)


class _Recorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


async def test_first_try_success_never_sleeps() -> None:
    recorder = _Recorder()

    async def attempt() -> str:
        return "ok"

    result = await retry_transient(
        attempt, limits=_limits(), label="p/m", call_id="c1", sleep=recorder.sleep
    )
    assert result == "ok" and recorder.delays == []


async def test_transient_failures_back_off_exponentially_then_succeed() -> None:
    recorder = _Recorder()
    outcomes: list[Exception | str] = [
        ProviderTransientError("429"),
        ProviderTransientError("429"),
        "ok",
    ]

    async def attempt() -> str:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    result = await retry_transient(
        attempt, limits=_limits(attempts=3), label="p/m", call_id="c2", sleep=recorder.sleep
    )
    assert result == "ok"
    assert recorder.delays == [0.5, 1.0]  # doubles per retry


async def test_retries_exhausted_raises_transient_with_attempt_count() -> None:
    recorder = _Recorder()

    async def attempt() -> str:
        raise ProviderTransientError("overloaded")

    with pytest.raises(ProviderTransientError, match="retries exhausted after 2 attempts"):
        await retry_transient(
            attempt, limits=_limits(attempts=2), label="p/m", call_id="c3", sleep=recorder.sleep
        )
    assert recorder.delays == [0.5]


async def test_non_transient_errors_propagate_immediately() -> None:
    recorder = _Recorder()

    async def attempt() -> str:
        raise ProviderError("bad request")

    with pytest.raises(ProviderError, match="bad request"):
        await retry_transient(
            attempt, limits=_limits(), label="p/m", call_id="c4", sleep=recorder.sleep
        )
    assert recorder.delays == []


# --- per-provider circuit breaker (SYS-05 executor hardening) -------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_breaker_opens_after_consecutive_failures_and_success_resets() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=30.0, clock=clock)
    breaker.record_failure("anthropic")
    breaker.check("anthropic")  # 1 < 2 — still closed
    breaker.record_success("anthropic")
    breaker.record_failure("anthropic")
    breaker.check("anthropic")  # success reset the streak
    breaker.record_failure("anthropic")
    with pytest.raises(CircuitOpenError, match="anthropic"):
        breaker.check("anthropic")
    breaker.check("openai")  # per-key: another provider is unaffected


def test_breaker_half_opens_after_cooldown_and_reopens_on_probe_failure() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30.0, clock=clock)
    breaker.record_failure("anthropic")
    with pytest.raises(CircuitOpenError):
        breaker.check("anthropic")
    clock.now += 31.0
    breaker.check("anthropic")  # half-open: one probe allowed
    breaker.record_failure("anthropic")
    with pytest.raises(CircuitOpenError):
        breaker.check("anthropic")  # probe failed — open again, full cooldown
    breaker.record_success("anthropic")
    breaker.check("anthropic")  # probe success closes fully


def test_half_open_admits_exactly_one_probe() -> None:
    """SEC M4: `check` CONSUMES the probe slot — concurrent callers arriving in the
    half-open window fail fast while the single probe is in flight."""
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30.0, clock=clock)
    breaker.record_failure("anthropic")
    clock.now += 31.0
    breaker.check("anthropic")  # the ONE probe
    with pytest.raises(CircuitOpenError):
        breaker.check("anthropic")  # a concurrent second caller fails fast
    breaker.record_success("anthropic")
    breaker.check("anthropic")  # probe succeeded — closed for everyone


def test_stale_failures_decay_outside_the_window() -> None:
    """SEC M4: a slow drip of failures over hours must never open the circuit —
    only `failure_threshold` failures INSIDE the rolling window count."""
    clock = _Clock()
    breaker = CircuitBreaker(
        failure_threshold=2, cooldown_seconds=30.0, failure_window_seconds=60.0, clock=clock
    )
    breaker.record_failure("anthropic")
    clock.now += 61.0  # the first failure is now stale
    breaker.record_failure("anthropic")
    breaker.check("anthropic")  # 1 fresh failure < 2 — still closed
    clock.now += 10.0
    breaker.record_failure("anthropic")
    with pytest.raises(CircuitOpenError):
        breaker.check("anthropic")  # 2 inside the window — open


async def test_retry_transient_fails_fast_when_the_circuit_is_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30.0, clock=_Clock())
    breaker.record_failure("anthropic")
    calls = 0

    async def attempt() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    recorder = _Recorder()
    with pytest.raises(CircuitOpenError):
        await retry_transient(
            attempt,
            limits=_limits(),
            label="anthropic/claude",
            call_id="c5",
            sleep=recorder.sleep,
            breaker=breaker,
            breaker_key="anthropic",
        )
    assert calls == 0  # failed fast — the provider was never touched


async def test_retry_transient_feeds_the_breaker_both_ways() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0, clock=clock)
    outcomes: list[Exception | str] = [ProviderTransientError("429"), "ok"]

    async def attempt() -> str:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    recorder = _Recorder()
    result = await retry_transient(
        attempt,
        limits=_limits(),
        label="anthropic/claude",
        call_id="c6",
        sleep=recorder.sleep,
        breaker=breaker,
        breaker_key="anthropic",
    )
    assert result == "ok"
    breaker.record_failure("anthropic")
    breaker.record_failure("anthropic")
    breaker.check("anthropic")  # the mid-retry success reset the streak: 2 < 3
