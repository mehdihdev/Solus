"""Bounded complete-line command observations; never split credential text."""

import asyncio
import codecs
import json
import queue
from collections.abc import Callable
from contextvars import ContextVar
from threading import Event
from typing import Any

OutputCallback = Callable[[str, str], None]
OUTPUT_CALLBACK: ContextVar[OutputCallback | None] = ContextVar("code_output", default=None)
CANCEL_EVENT: ContextVar[Event | None] = ContextVar("code_cancel", default=None)
MAX_CHUNKS = 256
MAX_BYTES = 256 * 1024
MAX_LINE = 2048
TRUNCATED = "[command output truncated]\n"
SUPPRESSED = "[oversized output line suppressed]\n"


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
        capped = self.chunks >= MAX_CHUNKS - 1 or self.size + size > MAX_BYTES - len(TRUNCATED)
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
    """Bounded thread-to-request handoff; network backpressure never delays process timeout."""

    def __init__(self, context: Any) -> None:
        self.context = context
        self.cancelled = Event()
        self.finished = Event()
        self.overflow = Event()
        self.pending: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=16)

    def output(self, stream: str, text: str) -> None:
        if self.cancelled.is_set() or self.overflow.is_set():
            return
        try:
            self.pending.put_nowait((stream, text))
        except queue.Full:
            self.overflow.set()

    async def publish(self) -> None:
        sequence = 0
        while not self.cancelled.is_set():
            try:
                stream, text = self.pending.get_nowait()
            except queue.Empty:
                if self.finished.is_set():
                    if self.overflow.is_set():
                        await self.context.report_progress(
                            sequence + 1,
                            message=json.dumps(
                                {
                                    "stream": "stdout",
                                    "text": TRUNCATED,
                                }
                            ),
                        )
                    return
                await asyncio.sleep(0.025)
                continue
            sequence += 1
            await self.context.report_progress(
                sequence, message=json.dumps({"stream": stream, "text": text})
            )
            await asyncio.sleep(0.25)
