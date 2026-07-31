"""The cloud channel: one outbound WebSocket, hello → ack → serve, redial.

Close-code policy (contract §4): 4400 stop ("update required", no redial) ·
4401 refresh the token via the token source and redial · 4403 stop (revoked)
· 4409 stop (superseded — a zombie must not fight its successor) · anything
else / network error → jittered exponential backoff redial (full jitter,
base 1 s, cap 60 s), reset after a connection that reached hello_ack.
The bearer rides the handshake `Authorization` header, NEVER the URL.
"""

import asyncio
import contextlib
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from solus_companion.config import CompanionConfig, TokenBox
from solus_companion.dispatch import Dispatcher, ToolCaller
from solus_companion.frames import (
    PROTOCOL_VERSION,
    Ack,
    ErrorIn,
    Invalid,
    Pong,
    ToolCallIn,
    Unknown,
    hello_frame,
    parse_inbound,
    ping_frame,
    status_frame,
)

logger = logging.getLogger("solus.companion.channel")

STOP_UPDATE_REQUIRED = "update required"
STOP_REVOKED = "revoked"
STOP_SUPERSEDED = "superseded"
STOP_MAX_ATTEMPTS = "max attempts"

_STOP_REASONS = {4400: STOP_UPDATE_REQUIRED, 4403: STOP_REVOKED, 4409: STOP_SUPERSEDED}
CLOSE_REAUTH = 4401

DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 60.0
DEFAULT_HELLO_TIMEOUT_SECONDS = 10.0
DEFAULT_STATUS_COALESCE_SECONDS = 1.0


class BridgeSupervisor(ToolCaller, Protocol):
    """What the channel needs from the supervisor."""

    status_changed: asyncio.Event

    def inventory(self) -> list[dict[str, Any]]: ...

    def status_snapshot(self) -> list[dict[str, Any]]: ...


@dataclass
class ChannelState:
    """Observable channel state, injectable by tests."""

    connected: bool = False
    stop_reason: str | None = None
    attempts: int = 0


@dataclass
class _Liveness:
    last_ping: float = 0.0
    last_pong: float = 0.0


async def _await_ack(ws: ClientConnection, timeout: float) -> bool:
    """Wait for hello_ack. Server `error` frames are logged and the wait
    continues — the close code that follows them drives policy. Any other
    frame first is a protocol failure (close + backoff redial)."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("no hello_ack within %.1fs", timeout)
            return False
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        frame = parse_inbound(raw)
        if isinstance(frame, Ack):
            if frame.protocol_version != PROTOCOL_VERSION:
                logger.error("server acked protocol_version %d", frame.protocol_version)
                return False
            return True
        if isinstance(frame, ErrorIn):
            logger.error("server error before ack: %s %s", frame.code, frame.message)
            continue
        logger.warning("expected hello_ack, got %s frame", type(frame).__name__)
        return False


async def _ping_loop(ws: ClientConnection, liveness: _Liveness, interval: float) -> None:
    """Send ping every interval; no pong since the last ping → half-open →
    close (which makes the receive loop raise and the channel redial)."""
    try:
        while True:
            await asyncio.sleep(interval)
            if liveness.last_ping > liveness.last_pong:
                logger.warning("no pong within %.1fs; closing half-open connection", interval)
                await ws.close()
                return
            liveness.last_ping = time.monotonic()
            await ws.send(ping_frame())
    except ConnectionClosed:
        return


async def _recv_loop(ws: ClientConnection, dispatcher: Dispatcher, liveness: _Liveness) -> None:
    while True:
        raw = await ws.recv()  # raises ConnectionClosed when the socket dies
        frame = parse_inbound(raw)
        if isinstance(frame, ToolCallIn):
            dispatcher.handle_tool_call(frame)
        elif isinstance(frame, Pong):
            liveness.last_pong = time.monotonic()
        elif isinstance(frame, ErrorIn):
            logger.error("server error: %s %s", frame.code, frame.message)
        elif isinstance(frame, Invalid):
            logger.warning("invalid frame dropped: %s", frame.reason)
        elif isinstance(frame, Unknown):
            logger.info("ignored unknown frame type %.64r", frame.type)


async def _status_loop(ws: ClientConnection, supervisor: BridgeSupervisor, coalesce: float) -> None:
    """BRG-03: one full snapshot right after hello_ack, then one per change,
    coalesced to at most one frame per `coalesce` window (latest state wins)."""
    try:
        supervisor.status_changed.clear()
        await ws.send(status_frame(supervisor.status_snapshot()))
        while True:
            await supervisor.status_changed.wait()
            await asyncio.sleep(coalesce)
            supervisor.status_changed.clear()  # after the sleep: window refreshes coalesce
            await ws.send(status_frame(supervisor.status_snapshot()))
    except ConnectionClosed:
        return


async def _serve(
    ws: ClientConnection,
    supervisor: BridgeSupervisor,
    state: ChannelState,
    ping_interval: float,
    status_coalesce: float,
) -> None:
    state.connected = True
    dispatcher = Dispatcher(supervisor, ws.send)
    liveness = _Liveness()
    pinger = asyncio.create_task(_ping_loop(ws, liveness, ping_interval))
    status_task = asyncio.create_task(_status_loop(ws, supervisor, status_coalesce))
    try:
        await _recv_loop(ws, dispatcher, liveness)
    finally:
        state.connected = False
        for task in (pinger, status_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                await task
        dispatcher.cancel_all()  # in-flight results are never sent post-disconnect


async def _connect_once(
    config: CompanionConfig,
    supervisor: BridgeSupervisor,
    token: str,
    state: ChannelState,
    hello_timeout: float,
    status_coalesce: float,
) -> tuple[str | None, bool]:
    """One dial. Returns (stop_reason | None, reached_hello_ack)."""
    reached_ack = False
    try:
        async with connect(
            config.url, additional_headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            await ws.send(
                hello_frame(
                    companion_version=config.companion_version,
                    instance_id=config.instance_id,
                    servers=supervisor.inventory(),
                )
            )
            if not await _await_ack(ws, hello_timeout):
                return None, False
            reached_ack = True
            await _serve(ws, supervisor, state, config.ping_interval, status_coalesce)
    except ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd is not None else None
        if code == CLOSE_REAUTH:
            logger.info("token rejected (4401); refreshing token and redialing")
            return None, reached_ack
        reason = _STOP_REASONS.get(code) if code is not None else None
        if reason is not None:
            logger.error("server closed the channel (%d): %s", code, reason)
        return reason, reached_ack
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("connection attempt failed: %s", type(exc).__name__)
        return None, reached_ack
    return None, reached_ack


async def run_channel(
    config: CompanionConfig,
    supervisor: BridgeSupervisor,
    *,
    state: ChannelState | None = None,
    max_attempts: int | None = None,
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
    hello_timeout: float = DEFAULT_HELLO_TIMEOUT_SECONDS,
    status_coalesce: float = DEFAULT_STATUS_COALESCE_SECONDS,
) -> ChannelState:
    """Dial, serve, redial until a STOP close code (or max_attempts, tests)."""
    channel_state = state if state is not None else ChannelState()
    consecutive_failures = 0
    while True:
        if max_attempts is not None and channel_state.attempts >= max_attempts:
            channel_state.stop_reason = STOP_MAX_ATTEMPTS
            return channel_state
        source = config.token_source
        if isinstance(source, TokenBox) and not source.get():
            # Signed out (or not yet signed in): idle, never dial blank.
            await source.available.wait()
        channel_state.attempts += 1
        token = source()
        stop_reason, reached_ack = await _connect_once(
            config, supervisor, token, channel_state, hello_timeout, status_coalesce
        )
        if stop_reason is not None:
            channel_state.stop_reason = stop_reason
            return channel_state
        consecutive_failures = 0 if reached_ack else consecutive_failures + 1
        delay = min(backoff_cap, backoff_base * (2 ** max(consecutive_failures - 1, 0)))
        await asyncio.sleep(random.uniform(0, delay))  # noqa: S311 — full jitter, not crypto
