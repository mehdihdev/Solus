"""Supervision of vendored MCP servers as PERSISTENT stdio sessions.

Unlike the cloud's `MCPTool` (per-call sessions), local desktop servers hold
state, so each server gets one long-lived `ClientSession` held open by an
`AsyncExitStack`. anyio cancel scopes must enter and exit in the same task,
so each handle runs an owner task that opens the stack, parks on a stop
event, and unwinds the stack itself.

Secret hygiene: children see ONLY {PATH, HOME} plus the launch spec's
declared env — never the companion's full environment. Tool calls carry NO
companion-side timeout; the cloud owns timeouts (contract §5).
"""

import asyncio
import contextlib
import enum
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, Tool

from solus_companion.config import ServerLaunch, is_loopback_url

logger = logging.getLogger("solus.companion.supervisor")

MAX_CONSECUTIVE_FAILURES = 3
RESTART_BACKOFF_BASE_SECONDS = 0.2
RESTART_BACKOFF_CAP_SECONDS = 2.0
LAUNCH_TIMEOUT_SECONDS = 30.0
DEFAULT_PING_TIMEOUT_SECONDS = 5.0
STATUS_DETAIL_CAP = 512  # §6 hygiene: short detail, matches the cloud's cap


class ServerState(enum.Enum):
    NOT_LAUNCHED = "not_launched"
    LAUNCHING = "launching"
    READY = "ready"
    FAILED = "failed"


class UnknownToolError(Exception):
    """The composed server/tool name matches nothing we supervise."""


class ServerUnavailableError(Exception):
    """The server is down and a restart attempt did not bring it back."""


def child_env(
    declared: Mapping[str, str],
    passthrough: Sequence[str] = (),
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """PATH/HOME, the names the fork DECLARED it may inherit, then the values
    Solus SETS — in that order, so a hostile ambient value cannot redirect a
    fork's interpreter. Everything else in the companion's environment stays
    out (secret hygiene)."""
    ambient = os.environ if source is None else source
    env = {key: ambient[key] for key in ("PATH", "HOME") if key in ambient}
    env.update({key: ambient[key] for key in passthrough if key in ambient})
    env.update(declared)
    return env


def _loopback_transport(url: str) -> Any:
    """Streamable-HTTP to a VENDOR-RUN server on this machine (CAD-02).

    Autodesk prohibits hosting or multiplexing a licensed Fusion seat, so Solus
    connects to the customer's own local instance as a local client. The URL was
    already pinned to loopback at discovery (`config.is_loopback_url`); it is
    re-checked here because this is the line that actually opens a socket.
    """
    from mcp.client.streamable_http import streamablehttp_client

    if not is_loopback_url(url):  # pragma: no cover - discovery refuses first
        raise ValueError(f"refusing a non-loopback MCP url: {url}")
    return streamablehttp_client(url)


def _tool_payload(tool: Tool) -> dict[str, Any]:
    """One hello-inventory entry, VERBATIM from list_tools (the cloud gates)."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
        "output_schema": tool.outputSchema,
    }


class ServerHandle:
    """One supervised server: an owner task holding the persistent session."""

    def __init__(self, launch: ServerLaunch, notify: Callable[[], None]) -> None:
        self.launch = launch
        self.state = ServerState.NOT_LAUNCHED
        self.detail: str | None = None
        self.changed_at = datetime.now(UTC)
        self.active_calls = 0
        self.session: ClientSession | None = None
        self.tools: tuple[dict[str, Any], ...] = ()
        self.tool_names: frozenset[str] = frozenset()
        self.failures = 0
        self._notify = notify
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # H1 review: serializes start/stop/restart — concurrent revives must
        # never race two owner tasks (orphaned subprocess, clobbered session).
        self._lifecycle = asyncio.Lock()

    def _set_state(self, state: ServerState, detail: str | None = None) -> None:
        if state is self.state and detail == self.detail:
            return
        self.state = state
        self.detail = detail[:STATUS_DETAIL_CAP] if detail is not None else None
        self.changed_at = datetime.now(UTC)
        self._notify()

    def note_detail(self, detail: str | None) -> None:
        """Update the surfaced status detail WITHOUT a state transition —
        MCP-05 license acks ride the existing status frames this way. The
        §6 detail cap in `_set_state` applies."""
        self._set_state(self.state, detail)

    def begin_call(self) -> None:
        self.active_calls += 1
        if self.active_calls == 1 and self.state is ServerState.READY:
            self.changed_at = datetime.now(UTC)  # ready → busy edge
            self._notify()

    def end_call(self) -> None:
        self.active_calls -= 1
        if self.active_calls == 0 and self.state is ServerState.READY:
            self.changed_at = datetime.now(UTC)  # busy → ready edge
            self._notify()

    def status_entry(self) -> dict[str, Any]:
        """One wire `ServerStatus` entry (BRG-03). Busy is PER-SERVER: session
        up with ≥1 in-flight call; internal FAILED maps to wire "error"."""
        if self.state is ServerState.FAILED:
            state = "error"
        elif self.state is ServerState.READY and self.active_calls > 0:
            state = "busy"
        else:
            state = self.state.value
        return {
            "name": self.launch.name,
            "state": state,
            "detail": self.detail,
            "updated_at": self.changed_at.isoformat(),
        }

    async def _own(self, started: asyncio.Event, stop: asyncio.Event) -> None:
        """Owner task: enter transport+session, park, unwind — all one task."""
        try:
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(self._transport())
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listing = await session.list_tools()
                self.tools = tuple(_tool_payload(tool) for tool in listing.tools)
                self.tool_names = frozenset(tool.name for tool in listing.tools)
                self.session = session
                self._set_state(ServerState.READY)
                started.set()
                await stop.wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("server %r session ended abnormally", self.launch.name)
        finally:
            self.session = None
            if self.state is ServerState.READY:
                self._set_state(ServerState.NOT_LAUNCHED)
            started.set()

    def _transport(self) -> Any:
        """stdio for a vendored fork, streamable-http for a vendor-run server.
        Exactly one is configured; discovery guarantees it."""
        if self.launch.url is not None:
            return _loopback_transport(self.launch.url)
        return stdio_client(
            StdioServerParameters(
                command=str(self.launch.command),
                args=list(self.launch.args),
                env=child_env(dict(self.launch.env), self.launch.env_passthrough),
                cwd=str(self.launch.cwd) if self.launch.cwd else None,
            )
        )

    async def start(self) -> bool:
        async with self._lifecycle:
            return await self._start_locked()

    async def _start_locked(self) -> bool:
        self._set_state(ServerState.LAUNCHING)
        self._stop = asyncio.Event()
        started = asyncio.Event()
        self._task = asyncio.create_task(self._own(started, self._stop))
        try:
            await asyncio.wait_for(started.wait(), timeout=LAUNCH_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.error("server %r did not become ready; cancelling launch", self.launch.name)
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self.state is ServerState.READY:
            self.failures = 0
            return True
        self.failures += 1
        if self.failures >= MAX_CONSECUTIVE_FAILURES:
            # §6 hygiene: short, no tracebacks/env/paths — the operator log
            # above has the details, the wire gets only this.
            self._set_state(
                ServerState.FAILED,
                detail=f"failed to start after {self.failures} consecutive attempts",
            )
        else:
            self._set_state(ServerState.NOT_LAUNCHED)
        logger.error(
            "server %r failed to start (%d consecutive failures)", self.launch.name, self.failures
        )
        return False

    async def stop(self) -> None:
        async with self._lifecycle:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._task = None
        self.session = None
        if self.state is not ServerState.FAILED:
            self._set_state(ServerState.NOT_LAUNCHED)

    async def restart(self) -> bool:
        """Stop, back off a little if we've been failing, start again."""
        async with self._lifecycle:
            return await self._restart_locked()

    async def _restart_locked(self) -> bool:
        await self._stop_locked()
        if self.failures:
            delay = min(
                RESTART_BACKOFF_BASE_SECONDS * (2 ** (self.failures - 1)),
                RESTART_BACKOFF_CAP_SECONDS,
            )
            await asyncio.sleep(delay)
        return await self._start_locked()

    async def ensure_session(self, *, dead: ClientSession | None) -> ClientSession | None:
        """Serialized revive. `dead` is the session the caller just failed on
        (None if it had none). If a concurrent revive already replaced it while
        we waited for the lock, reuse the live session instead of restarting
        the server a second time."""
        async with self._lifecycle:
            if self.session is not None and self.session is not dead:
                return self.session
            await self._restart_locked()
            return self.session


class Supervisor:
    """Launches, health-checks, and dispatches to the vendored servers."""

    def __init__(
        self,
        servers: Sequence[ServerLaunch],
        *,
        ping_timeout: float = DEFAULT_PING_TIMEOUT_SECONDS,
    ) -> None:
        self.status_changed = asyncio.Event()
        self._handles: dict[str, ServerHandle] = {
            launch.name: ServerHandle(launch, self.status_changed.set) for launch in servers
        }
        self._ping_timeout = ping_timeout

    @property
    def handles(self) -> dict[str, ServerHandle]:
        return self._handles

    async def start_all(self) -> None:
        for handle in self._handles.values():
            await handle.start()

    def inventory(self) -> list[dict[str, Any]]:
        """The hello `servers` payload — cached tool listings, verbatim."""
        return [
            {"server": handle.launch.name, "tools": list(handle.tools)}
            for handle in self._handles.values()
            if handle.state is ServerState.READY
        ]

    def status_snapshot(self) -> list[dict[str, Any]]:
        """FULL BRG-03 snapshot of every known server — never a delta."""
        return [handle.status_entry() for handle in self._handles.values()]

    async def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> CallToolResult:
        """Forward one call; ONE restart attempt if the session is dead."""
        handle = self._handles.get(server)
        if handle is None or (handle.tool_names and tool not in handle.tool_names):
            raise UnknownToolError(f"unknown tool {server}.{tool}")
        handle.begin_call()
        try:
            return await self._call_on(handle, server, tool, args)
        finally:
            handle.end_call()

    async def _call_on(
        self, handle: ServerHandle, server: str, tool: str, args: dict[str, Any]
    ) -> CallToolResult:
        session = handle.session
        if session is None:
            session = await self._revive(handle, dead=None)
            if tool not in handle.tool_names:
                raise UnknownToolError(f"unknown tool {server}.{tool}")
            return await session.call_tool(tool, args)
        try:
            return await session.call_tool(tool, args)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("server %r call failed; attempting one restart", server)
            fresh = await self._revive(handle, dead=session)
            return await fresh.call_tool(tool, args)

    async def _revive(self, handle: ServerHandle, *, dead: ClientSession | None) -> ClientSession:
        session = await handle.ensure_session(dead=dead)
        if session is None:
            raise ServerUnavailableError(f"server {handle.launch.name!r} is unavailable")
        return session

    async def ping_once(self, server: str) -> bool:
        handle = self._handles.get(server)
        return handle is not None and await self._ping(handle)

    async def _ping(self, handle: ServerHandle) -> bool:
        session = handle.session
        if session is None:
            return False
        try:
            await asyncio.wait_for(session.send_ping(), timeout=self._ping_timeout)
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            return False

    async def ensure_healthy(self) -> None:
        """Periodic health pass: ping each server; restart the dead ones."""
        for handle in self._handles.values():
            if handle.state is ServerState.FAILED:
                continue
            session = handle.session
            if session is not None and await self._ping(handle):
                continue
            logger.warning("server %r unhealthy; restarting", handle.launch.name)
            await handle.ensure_session(dead=session)  # reuses a concurrent revive

    def note_license_ack(
        self, server: str, ok: bool, stored: Sequence[str], error: str | None
    ) -> None:
        """MCP-05: surface a cloud `credential_ack` on the server's status
        entry (key NAMES only — no secret value ever reaches this function).
        The next status frame carries it to the cloud's read surface."""
        handle = self._handles.get(server)
        if handle is None:
            logger.info("license ack for unsupervised server %r ignored", server)
            return
        if ok:
            names = ", ".join(stored)
            detail = f"license stored ({names})" if names else "license stored"
        else:
            detail = f"license not stored: {error or 'unknown error'}"
        handle.note_detail(detail)

    async def stop_all(self) -> None:
        """Unwind every session; the SDK SIGTERMs the children on exit."""
        for handle in self._handles.values():
            await handle.stop()
