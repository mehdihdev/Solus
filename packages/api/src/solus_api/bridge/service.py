"""Transport-free channel logic: dispatch, result ingress, supersede, limits.

Delivery is at-most-once (contract §5): a tool_call is written once to the live
socket; socket death fails every in-flight call fast and retryably — retry
belongs to SOL via the W0-04 `retryable` flag, never to the wire. Timeouts are
owned by `ToolRegistry.invoke`'s asyncio.wait_for — nothing here re-times.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolCall, ToolResult
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.frames import redact_text, redact_value, tool_call_frame
from solus_api.bridge.registry import BridgeSession
from solus_api.models import User
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.bridge.service")

SUPERSEDED_EVENT = "bridge.session_superseded"


async def dispatch(
    session: BridgeSession, tool_name: str, args: dict[str, object], *, call_cap_bytes: int
) -> ToolResult:
    """Send one tool_call and await its (already-redacted) result.

    Raises ToolException for: overflow (immediate, retryable), oversize args
    (permanent), send failure / disconnect / supersede (retryable). The wire
    call_id is minted HERE — the registry never forwards SOL's call_id into
    `tool.invoke`, so the two id spaces are separate by construction.
    """
    if session.entered >= session.max_inflight * 2:
        # max_inflight running + max_inflight queued; beyond that fail fast
        # (contract §7 loop-guard: bounded outstanding work).
        raise ToolException("bridge busy", retryable=True)
    call = ToolCall(tool=tool_name, args=dict(args))
    frame = tool_call_frame(call)
    if len(frame.encode()) > call_cap_bytes:
        raise ToolException(f"tool call for {tool_name!r} exceeds the size cap", retryable=False)
    session.entered += 1
    try:
        async with session.slots:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[ToolResult] = loop.create_future()
            session.inflight[call.call_id] = future
            try:
                try:
                    await session.send(frame)
                except Exception as exc:
                    raise ToolException("bridge disconnected", retryable=True) from exc
                return await future
            finally:
                # Timeout-cancellation or completion: a late result for this id
                # is then dropped as unknown (contract §5).
                session.inflight.pop(call.call_id, None)
    finally:
        session.entered -= 1


def ingest_result(session: BridgeSession, result: ToolResult) -> None:
    """Deliver a companion result to its waiting dispatcher. Unknown, foreign,
    or already-answered call_ids are dropped + logged (replay defense, §5);
    first result wins. `value` is redacted BEFORE it can reach a consumer."""
    future = session.inflight.pop(result.call_id, None)
    if future is None or future.done():
        logger.warning(
            "bridge session %s dropped result for unknown call_id %.64s",
            session.session_id,
            result.call_id,
        )
        return
    if result.ok and result.value is not None:
        result = ToolResult.success(result.call_id, redact_value(result.value))
    elif result.error is not None:
        # SEC-M3: the error channel feeds model context/persistence too —
        # redact it exactly like values.
        result = ToolResult.failure(
            result.call_id,
            result.error.model_copy(update={"message": redact_text(result.error.message)}),
        )
    future.set_result(result)


def fail_inflight(session: BridgeSession, message: str) -> None:
    """Resolve every pending dispatcher with a retryable failure (§5)."""
    pending = list(session.inflight.values())
    session.inflight.clear()
    for future in pending:
        if not future.done():
            future.set_exception(ToolException(message, retryable=True))


async def supersede(
    old: BridgeSession,
    new: BridgeSession,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The §3 single-active-session sequence: close the old socket 4409, fail
    its in-flight calls fast, and emit the stolen-JWT tripwire event carrying
    BOTH instance ids."""
    from solus_api.bridge.frames import CLOSE_SUPERSEDED

    fail_inflight(old, "bridge session superseded")
    try:
        await old.close(CLOSE_SUPERSEDED)
    except Exception:  # the old socket may already be dead — that is fine
        logger.debug("bridge session %s close after supersede failed", old.session_id)
    async with sessionmaker() as db:
        user = await db.get(User, new.user_id)
        if user is None:  # pragma: no cover — scope was verified at bind
            return
        emit_event(
            db,
            user=user,
            event_type=SUPERSEDED_EVENT,
            team_id=new.team_id,
            project_id=new.project_id,
            payload={
                "old_companion_instance_id": old.companion_instance_id,
                "new_companion_instance_id": new.companion_instance_id,
                "old_session_id": old.session_id,
                "new_session_id": new.session_id,
            },
        )
        await db.commit()


@dataclass
class TokenBucket:
    """Per-session message-rate bucket (contract §7): `rate`/s sustained with
    `burst` headroom. WS scope never passes the HTTP RateLimitMiddleware, so
    the handler carries its own bucket."""

    rate: float
    burst: int
    tokens: float = field(default=0.0)
    updated: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.tokens = float(self.burst)
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(float(self.burst), self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


class ConnectRateLimiter:
    """Fixed-window per-key connect-attempt limiter (contract §7), bounded in
    tracked keys like core/ratelimit.py. Key = user id (post-auth)."""

    _MAX_TRACKED = 10_000
    _WINDOW_SECONDS = 60.0

    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._counts: dict[str, tuple[float, int]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start, count = self._counts.get(key, (now, 0))
        if now - window_start >= self._WINDOW_SECONDS:
            window_start, count = now, 0
        if count >= self._limit:
            self._counts[key] = (window_start, count)
            return False
        if len(self._counts) >= self._MAX_TRACKED and key not in self._counts:
            self._counts.clear()  # ponytail: crude reset at the bound, like core/ratelimit
        self._counts[key] = (window_start, count + 1)
        return True
