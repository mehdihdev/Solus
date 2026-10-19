"""Bounded complete-line command observations; never split credential text."""

import asyncio
import codecs
import json
import queue
import time
from collections.abc import Callable
from contextvars import ContextVar
from threading import Event
from typing import Any

OutputCallback = Callable[[str, str], None]
OUTPUT_CALLBACK: ContextVar[OutputCallback | None] = ContextVar("code_output", default=None)
CANCEL_EVENT: ContextVar[Event | None] = ContextVar("code_cancel", default=None)
#: Lines one execution may emit, and the frames the companion relays (it stops at 255).
MAX_LINES = 16384
MAX_FRAMES = 256
MAX_BYTES = 256 * 1024
MAX_LINE = 2048
#: Lines waiting for the publisher; LineOutput's own caps keep it from filling.
MAX_PENDING = MAX_LINES
PUBLISH_SECONDS = 0.25
#: The server waits 5 s for the publisher after the tool returns; finish inside it.
DRAIN_SECONDS = 4.0
TRUNCATED = "[command output truncated]\n"
SUPPRESSED = "[oversized output line suppressed]\n"
MARKERS = frozenset({TRUNCATED, SUPPRESSED})


class LineOutput:
    """One execution's bounded decoder, line buffers and shared output budget."""

    def __init__(self, callback: OutputCallback | None) -> None:
        self.callback = callback
        self.decoders = {
            name: codecs.getincrementaldecoder("utf-8")("replace") for name in ("stdout", "stderr")
        }
        self.pending = {"stdout": "", "stderr": ""}
        self.discard = {"stdout": False, "stderr": False}
        self.chunks = 0
        self.size = 0

    def _emit(self, stream: str, text: str) -> None:
        if self.callback is None:
            return
        size = len(text.encode("utf-8"))
        capped = self.chunks >= MAX_LINES - 1 or self.size + size > MAX_BYTES - len(TRUNCATED)
        try:
            self.callback(stream, TRUNCATED if capped else text)
        except Exception:  # observation transport must not alter or replay execution
            self.callback = None
            return
        self.chunks += 1
        self.size += size
        if capped:
            self.callback = None

    def feed(self, stream: str, data: bytes) -> None:
        if self.callback is None:
            return
        text = self.decoders[stream].decode(data)
        for char in text:
            if self.discard[stream]:
                continue
            self.pending[stream] += char
            if len(self.pending[stream]) > MAX_LINE:
                self.pending[stream] = ""
                self.discard[stream] = True
                self._emit(stream, SUPPRESSED)
            elif char == "\n":
                self._emit(stream, self.pending[stream])
                self.pending[stream] = ""

    def suppress(self, stream: str) -> None:
        """Drop incomplete context when an observation budget or deadline is reached."""
        self.pending[stream] = ""
        if not self.discard[stream]:
            self.discard[stream] = True
            self._emit(stream, TRUNCATED)

    def finish(self) -> None:
        for stream, decoder in self.decoders.items():
            remainder = decoder.decode(b"", final=True)
            if remainder:
                self.feed(stream, remainder.encode("utf-8"))
            if self.pending[stream] and not self.discard[stream]:
                self._emit(stream, self.pending[stream])
            self.pending[stream] = ""


class AsyncOutput:
    """Bounded thread-to-request handoff; network backpressure never delays process timeout.

    Complete lines of one stream are packed into frames of at most MAX_LINE chars (the
    companion relays one frame per ~0.21 s), so a burst is not lost to pacing. Markers
    travel alone so the companion can flag them. Truncation is reported only when a real
    cap is hit: the pending bound, the frame count, or the post-exit drain window."""

    def __init__(self, context: Any) -> None:
        self.context = context
        self.cancelled = Event()
        self.finished = Event()
        self.overflow = Event()
        self.pending: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=MAX_PENDING)
        self.carry: tuple[str, str] | None = None
        self.sequence = 0

    def output(self, stream: str, text: str) -> None:
        if self.cancelled.is_set() or self.overflow.is_set():
            return
        try:
            self.pending.put_nowait((stream, text))
        except queue.Full:
            self.overflow.set()

    def _next(self) -> tuple[str, str] | None:
        item, self.carry = self.carry, None
        if item is not None:
            return item
        try:
            return self.pending.get_nowait()
        except queue.Empty:
            return None

    def _frame(self, stream: str, text: str) -> str:
        """`text` plus every following line of the same stream that still fits."""
        if text in MARKERS:
            return text
        while (item := self._next()) is not None:
            if item[0] != stream or item[1] in MARKERS or len(text) + len(item[1]) > MAX_LINE:
                self.carry = item
                break
            text += item[1]
        return text

    async def _send(self, stream: str, text: str) -> None:
        self.sequence += 1
        await self.context.report_progress(
            self.sequence,
            message=json.dumps({"stream": stream, "text": text}, ensure_ascii=False),
        )

    async def publish(self) -> None:
        deadline: float | None = None
        while not self.cancelled.is_set():
            if self.finished.is_set() and deadline is None:
                deadline = time.monotonic() + DRAIN_SECONDS
            item = self._next()
            if item is None:
                if deadline is not None:
                    if self.overflow.is_set():
                        await self._send("stdout", TRUNCATED)
                    return
                await asyncio.sleep(0.025)
                continue
            out_of_time = deadline is not None and time.monotonic() > deadline
            if self.sequence >= MAX_FRAMES - 1 or out_of_time:
                await self._send("stdout", TRUNCATED)
                return
            await self._send(item[0], self._frame(*item))
            await asyncio.sleep(PUBLISH_SECONDS)
