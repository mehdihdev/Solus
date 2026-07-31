"""`LiveConnection` — the streaming sibling of `Connector` (MCP-02, formalizing W0-05 §1).

The design-artifact branch (`Connector`) SYNCS committed exports into the graph; THIS branch
STREAMS live runtime data — telemetry from a real robot, sim state from Gazebo/Isaac, a Foxglove
feed. The two never mix (ADR-030 boundary clause): live runtime data flows through a
`LiveConnection`, never the `Connector` sync path, and parsing exports ≠ streaming runtime.

The contract surface is exactly four operations — `subscribe`, `on_batch`, `unsubscribe`,
`status`. Emissions are BATCH-SUMMARIZED windows: the registered callback receives completed
`TelemetryWindowSummary` objects (the W0-07 shape, reused as-is, never redefined), with raw data
only ever REFERENCED via `raw_ref: ArtifactRef`. No API on this interface exposes a per-sample /
raw firehose — that is the edge-observer principle from `docs/contracts/sol-interface.md` §4.

HARD RULE (Pattern 2): telemetry is NEVER forced through an MCP tool interface. This module
imports nothing MCP, and a `LiveConnection` must not satisfy the W0-04 `Tool` protocol —
`assert_live_connection_contract` enforces that mechanically.

Telemetry is UNTRUSTED input to the model layer (ADR-029, CLAUDE.md §7): every string a summary
carries is data to be analyzed downstream, never instructions to follow.
"""

from __future__ import annotations

import abc
import enum
import uuid
from collections.abc import Awaitable, Callable
from typing import ClassVar

from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary

#: The consumer's delivery seam: called once per COMPLETED window with its summary.
BatchCallback = Callable[[TelemetryWindowSummary], Awaitable[None]]


class LiveStatus(enum.StrEnum):
    """Where a live connection is in its lifecycle. Fixed by Solus code, never by stream data."""

    DISCONNECTED = "disconnected"  # no live link to the runtime source
    CONNECTED = "connected"  # link established / subscriptions active, no windows flowing yet
    STREAMING = "streaming"  # completed windows are being delivered


class LiveConnection(abc.ABC):
    """A live runtime source. The DISTINCT sibling of `Connector` — no `sync`, no
    `detect_changes`; it streams, it does not ingest design artifacts (ADR-030).

    Implementations connect to a runtime source (serial, ROS, a sim), batch raw samples into
    windows per the subscription's `TelemetryWindow` spec, and deliver each completed
    `TelemetryWindowSummary` to the subscription's registered callback. Credentials, when a real
    source needs them, arrive exactly as in W0-05: a `secret_ref` resolved through the secret
    store — never plaintext config (CLAUDE.md §7).
    """

    #: Roster identity, mirroring `Connector.provider` (e.g. "ros", "foxglove", "serial").
    provider: ClassVar[str]

    @abc.abstractmethod
    async def subscribe(self, window: TelemetryWindow) -> str:
        """Start a subscription batching the stream per `window`; returns an opaque handle."""

    @abc.abstractmethod
    def on_batch(self, handle: str, callback: BatchCallback) -> None:
        """Register `callback` for the subscription's completed windows. One callback per
        handle — registering again replaces it (want two consumers? make two subscriptions).
        Raises `KeyError` for an unknown handle."""

    @abc.abstractmethod
    async def unsubscribe(self, handle: str) -> None:
        """Stop the subscription: no delivery to its callback after this returns.
        Raises `KeyError` for an unknown handle."""

    @abc.abstractmethod
    def status(self) -> LiveStatus:
        """The connection's current lifecycle state. Delivery implies `STREAMING`."""


class NoopLiveConnection(LiveConnection):
    """The roster placeholder and conformance target: connects to nothing, accepts
    subscriptions, emits nothing on its own. Tests drive delivery via `feed`."""

    provider: ClassVar[str] = "noop"

    def __init__(self) -> None:
        self._subscriptions: dict[str, TelemetryWindow] = {}
        self._callbacks: dict[str, BatchCallback] = {}
        self._status = LiveStatus.DISCONNECTED

    async def subscribe(self, window: TelemetryWindow) -> str:
        handle = uuid.uuid4().hex
        self._subscriptions[handle] = window
        self._status = LiveStatus.CONNECTED
        return handle

    def on_batch(self, handle: str, callback: BatchCallback) -> None:
        if handle not in self._subscriptions:
            raise KeyError(handle)
        self._callbacks[handle] = callback

    async def unsubscribe(self, handle: str) -> None:
        del self._subscriptions[handle]  # KeyError on unknown handle, per the contract
        self._callbacks.pop(handle, None)
        if not self._subscriptions:
            self._status = LiveStatus.DISCONNECTED

    def status(self) -> LiveStatus:
        return self._status

    async def feed(self, summary: TelemetryWindowSummary) -> None:
        """TEST-ONLY injection of a completed window: delivers `summary` to every active
        subscription's callback, so tests and the conformance suite can prove delivery.
        Real implementations produce windows from their stream — they do not expose this."""
        # ponytail: no per-window signal filtering — the no-op delivers to all subscriptions;
        # real implementations window/filter per each subscription's TelemetryWindow spec.
        delivered = False
        for handle in list(self._subscriptions):
            callback = self._callbacks.get(handle)
            if callback is not None:
                await callback(summary)
                delivered = True
        if delivered:
            self._status = LiveStatus.STREAMING
