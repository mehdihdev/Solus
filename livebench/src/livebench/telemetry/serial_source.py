"""Serial packet source (LB-02): newline-delimited LB-06 JSON over a direct link.

A Solus-flashed robot writes one JSON object per line: the LB-06 wire form when it
speaks the contract, any JSON object otherwise (flattened generically). Newline
framing is self-synchronizing — junk between frames costs exactly the line it
arrived on. The blocking pyserial read runs in a worker thread; the async side
consumes it cooperatively.

Direct-link identity: `trusted_identity=True` — one wire, one claimant, so the
firmware's own `device_id` is accepted (unlike bridged transports). Generic lines
get `serial:<port>` and the arrival clock.

Defensive bounds (§7): line length is capped; an over-long line is discarded to
the next newline rather than buffered without limit.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Final

import serial as pyserial
from solus_api.graph.codec import MAX_PACKET_BYTES
from solus_api.graph.packet import TelemetryPacket

from livebench.telemetry.normalize import packet_from_json_payload

logger = logging.getLogger(__name__)

#: A line is one packet plus slack; anything longer is discarded, not buffered.
DEFAULT_MAX_LINE_BYTES: Final = MAX_PACKET_BYTES + 1024

_NS_PER_US: Final = 1_000
_US_PER_S: Final = 1_000_000

_STOP: Final = object()


class SerialPacketSource:
    """LB-06 JSON lines from an open pyserial port, as an async packet stream."""

    def __init__(
        self,
        port: pyserial.Serial,
        *,
        clock: Callable[[], datetime] | None = None,
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
    ) -> None:
        self._port = port
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._max_line = max_line_bytes
        self._topic = f"serial:{port.port or 'unknown'}"
        self._closed = False
        self._pinned_device: str | None = None

    def _read_line(self) -> bytes | object:
        """Blocking read of one bounded line (worker thread). Returns _STOP at EOF/close."""
        try:
            line = self._port.readline(self._max_line)
        except (OSError, pyserial.SerialException):
            return _STOP
        if not line:
            return b"" if not self._closed else _STOP  # timeout tick vs. closed port
        if len(line) >= self._max_line and not line.endswith(b"\n"):
            # Over-long line: discard through to the next newline, keep the stream.
            logger.debug("discarding over-long serial line on %s", self._topic)
            while True:
                rest = self._port.readline(self._max_line)
                if not rest or rest.endswith(b"\n"):
                    return b""
        return line

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        while not self._closed:
            line = await asyncio.to_thread(self._read_line)
            if line is _STOP:
                return
            assert isinstance(line, bytes)
            stripped = line.strip()
            if not stripped:
                continue
            stamp = self._clock()
            log_time_ns = int(stamp.timestamp() * _US_PER_S) * _NS_PER_US
            packet = packet_from_json_payload(
                self._topic, log_time_ns, stripped, trusted_identity=True
            )
            if packet is None:
                logger.debug("skipping undecodable serial line on %s", self._topic)
                continue
            # Identity pinning (§7): the link is unauthenticated, so "one wire, one
            # claimant" is trusted only for the FIRST device_id seen. A device that
            # changes its asserted identity mid-stream is dropped — a rogue firmware
            # must not attach telemetry to an arbitrary graph entity by relabelling.
            if self._pinned_device is None:
                self._pinned_device = packet.device_id
            elif packet.device_id != self._pinned_device:
                logger.warning(
                    "serial %s: dropping packet with changed identity %r (pinned %r)",
                    self._topic,
                    packet.device_id,
                    self._pinned_device,
                )
                continue
            yield packet

    async def aclose(self) -> None:
        self._closed = True
        try:
            self._port.close()
        except (OSError, pyserial.SerialException):  # pragma: no cover - close is best-effort
            logger.debug("serial close failed on %s", self._topic)
