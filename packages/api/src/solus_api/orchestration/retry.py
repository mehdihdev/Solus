"""The ONE transient-retry loop for provider calls (SYS-05 executor hardening).

`gateway._GatedStream._start` and `embeddings._call_with_retry` carried two
copies of the same MO-03 exponential backoff; this module is the single
implementation both delegate to. The attempt callable owns its own cleanup
(the gateway closes its inner generator before re-raising a transient), so
this loop never needs to know what an attempt is made of.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from solus_api.orchestration.providers import ProviderTransientError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from solus_api.orchestration.config import LimitsConfig

logger = logging.getLogger("solus.orchestration.retry")

# Bound interactive waiting; longer provider deadlines defer instead of retrying early.
MAX_RETRY_WAIT_SECONDS = 30.0


class CircuitOpenError(ProviderTransientError):
    """The provider's circuit is open — failing fast instead of calling it.
    Subclasses `ProviderTransientError` so every existing handler keeps its
    posture: embeds degrade to no-signal, SOL turns surface a masked, retryable
    failure. Nothing upstream needs to learn a new exception."""


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    opened_at: float = 0.0
    last_failure_at: float = 0.0


class CircuitBreaker:
    """Per-key (provider) circuit breaker (SYS-05, closing gateway.py's named gap).

    OPEN after `failure_threshold` transient failures inside a rolling
    `failure_window_seconds` (stale failures decay — a slow drip over hours
    never opens the circuit); while open, `check` fails fast with
    `CircuitOpenError`. After `cooldown_seconds` the circuit is HALF-OPEN and
    `check` CONSUMES the single probe slot (re-arming the open window), so
    exactly one concurrent caller reaches the provider — a success closes the
    circuit, a failure re-opens it. Single-event-loop state, no locks;
    per-process by design (each API/worker process protects itself)."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        failure_window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._window = failure_window_seconds
        self._clock = clock
        self._states: dict[str, _BreakerState] = {}
        self._retry_deadlines: dict[str, float] = {}

    def defer(self, key: str, delay: float) -> float:
        deadline = max(self._retry_deadlines.get(key, 0.0), self._clock() + delay)
        self._retry_deadlines[key] = deadline
        return deadline

    def remaining_delay(self, key: str) -> float:
        return max(0.0, self._retry_deadlines.get(key, 0.0) - self._clock())

    def check(self, key: str, *, own_deadline: float | None = None) -> None:
        deadline = self._retry_deadlines.get(key, 0.0)
        remaining = self.remaining_delay(key)
        if remaining > 0 and deadline != own_deadline:
            raise CircuitOpenError(
                f"provider '{key}' cooling down; retry later",
                retry_after_seconds=remaining,
            )
        state = self._states.get(key)
        if state is None or state.consecutive_failures < self._threshold:
            return
        now = self._clock()
        elapsed = now - state.opened_at
        if elapsed >= self._cooldown:
            # Half-open: CONSUME the probe slot by re-arming the open window, so
            # concurrent callers fail fast while exactly one probe is in flight.
            # The probe's own record_success/record_failure decides what's next.
            state.opened_at = now
            return
        raise CircuitOpenError(
            f"provider '{key}' circuit open after {state.consecutive_failures} "
            f"transient failures; failing fast for {self._cooldown - elapsed:.1f}s more",
            retry_after_seconds=max(remaining, self._cooldown - elapsed),
        )

    def record_success(self, key: str) -> None:
        self._states.pop(key, None)

    def record_failure(self, key: str) -> None:
        state = self._states.setdefault(key, _BreakerState())
        now = self._clock()
        if state.last_failure_at and now - state.last_failure_at > self._window:
            # Rolling window: stale failures decay instead of accumulating forever
            # (a drip of one failure an hour must never open the circuit).
            state.consecutive_failures = 0
        state.last_failure_at = now
        state.consecutive_failures += 1
        if state.consecutive_failures >= self._threshold:
            if state.consecutive_failures == self._threshold:
                logger.warning(
                    "circuit OPEN key=%s failures=%d cooldown_s=%.1f",
                    key,
                    state.consecutive_failures,
                    self._cooldown,
                )
            state.opened_at = now

    def reset(self) -> None:
        """Test hygiene seam (conftest) — production never calls this."""
        self._states.clear()
        self._retry_deadlines.clear()


#: The process-wide default breaker every provider call path shares: one
#: provider melting down trips ONE circuit for streaming and embeddings alike.
DEFAULT_BREAKER = CircuitBreaker()


async def retry_transient[T](
    attempt: Callable[[], Awaitable[T]],
    *,
    limits: LimitsConfig,
    label: str,
    call_id: str,
    sleep: Callable[[float], Awaitable[object]],
    breaker: CircuitBreaker | None = None,
    breaker_key: str | None = None,
) -> T:
    """Run `attempt` under the MO-03 transient policy: exponential backoff
    with jitter, honoring provider minimum waits; at most `retry_max_attempts` total
    tries, only `ProviderTransientError` retried — everything else propagates
    untouched. `label` is "provider/model" for messages; `sleep` is the
    caller's patchable seam so existing tests keep recording delays.

    The circuit breaker (default: the process-wide `DEFAULT_BREAKER`, keyed by
    `breaker_key` — pass the provider name) is consulted before the first try
    and before every retry, so a melted-down provider fails fast instead of
    burning the whole backoff schedule; `CircuitOpenError` IS transient, so
    callers' postures are unchanged."""
    active_breaker = breaker if breaker is not None else DEFAULT_BREAKER
    key = breaker_key if breaker_key is not None else label
    attempt_number = 1
    own_deadline: float | None = None
    while True:
        active_breaker.check(key, own_deadline=own_deadline)
        try:
            result = await attempt()
        except ProviderTransientError as exc:
            active_breaker.record_failure(key)
            base = min(
                MAX_RETRY_WAIT_SECONDS, limits.retry_backoff_seconds * (2 ** (attempt_number - 1))
            )
            delay = exc.retry_after_seconds
            if delay is None:
                delay = min(MAX_RETRY_WAIT_SECONDS, base + random.uniform(0, base))  # noqa: S311 — scheduling jitter
            own_deadline = active_breaker.defer(key, delay)
            delay = max(delay, active_breaker.remaining_delay(key))
            if attempt_number >= limits.retry_max_attempts:
                raise ProviderTransientError(
                    f"{label} is rate-limiting or overloaded; retries exhausted "
                    f"after {attempt_number} attempts",
                    retry_after_seconds=delay,
                ) from exc
            active_breaker.check(key, own_deadline=own_deadline)
            if delay > MAX_RETRY_WAIT_SECONDS:
                raise ProviderTransientError(
                    f"{label} requested a longer cooldown; retry later",
                    retry_after_seconds=delay,
                ) from exc

            logger.info(
                "transient provider error; retrying call_id=%s label=%s attempt=%d/%d delay=%.2fs",
                call_id,
                label,
                attempt_number,
                limits.retry_max_attempts,
                delay,
            )
            await sleep(delay)
            attempt_number += 1
        else:
            active_breaker.record_success(key)
            return result
