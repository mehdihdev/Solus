"""Newline framing over any `Channel` (SOLUSDEV-248 R3), shared by the line drivers (`lb06`,
`json-lines`, `raw-lines`) and the framing interrogator.

Newline framing is self-synchronising: junk between lines costs exactly the line it arrived on.
Device bytes are untrusted (CLAUDE.md §7): a line longer than `max_line_bytes` is discarded
through to the next newline, never buffered without limit. Reads block; callers run off-loop.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from solus_api.graph.codec import MAX_PACKET_BYTES

from livebench.hardware.channel import Channel

logger = logging.getLogger(__name__)

#: A line is one packet plus slack; anything longer is discarded, not buffered.
MAX_LINE_BYTES: Final = MAX_PACKET_BYTES + 1024
_RECV_BYTES: Final = 4096


class LineTransportParams(BaseModel):
    """What a line driver takes from `protocol.params`: the serial-shaped transport's own baud
    and read timeout. The transport opens with them; the driver only validates them, and
    `None` means the transport's default."""

    model_config = ConfigDict(extra="forbid")

    baud: int | None = Field(default=None, ge=300, le=3_000_000)
    timeout_s: float | None = Field(default=None, ge=0.001, le=5.0)


class LineReader:
    """Complete lines from a channel's byte stream, bounded and junk-tolerant."""

    def __init__(
        self,
        channel: Channel,
        *,
        max_line_bytes: int = MAX_LINE_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._channel = channel
        self._max = max_line_bytes
        self._clock = clock
        self._buffer = b""
        self._discarding = False

    def read_line(self, *, deadline: float | None = None) -> bytes | None:
        """One complete line without its newline, or None on a silent tick (the channel's
        read timeout) or once `deadline` (a `time.monotonic()` instant) has passed — a stream
        that never sends a newline cannot hold a caller past its budget. A link error propagates."""
        while (line := self._pop_line()) is None:
            if deadline is not None and self._clock() >= deadline:
                return None
            frame = self._channel.recv(_RECV_BYTES)
            if frame is None:
                return None
            self._buffer += frame.payload
        return line

    def _pop_line(self) -> bytes | None:
        while (end := self._buffer.find(b"\n")) != -1:
            line, self._buffer = self._buffer[:end], self._buffer[end + 1 :]
            if self._discarding:
                self._discarding = False  # the tail of an over-long line goes with it
                continue
            stripped = line.strip()
            if stripped:
                return stripped
        if len(self._buffer) > self._max:
            logger.debug("%s: discarding an over-long line", self._channel.identity.device_ref)
            self._buffer = b""
            self._discarding = True
        return None
