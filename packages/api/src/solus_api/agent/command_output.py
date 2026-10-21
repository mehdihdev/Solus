"""Ephemeral command progress, scoped to an owned confirmation; no authority."""

import re
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from solus_api.agent.tools.untrusted import redact_text

Stream = Literal["stdout", "stderr"]
#: Tools whose approved execution streams incremental output (SOLUSDEV-261/317).
STREAMING_TOOLS: Final = frozenset({"code.run", "code.test", "code.exec"})


class OutputSink(Protocol):
    def append(self, stream: Stream, text: str) -> None: ...
    def truncate(self) -> None: ...


current_output: ContextVar[OutputSink | None] = ContextVar("command_output", default=None)
Key = tuple[UUID, UUID, UUID]  # project, owner, confirmation
_INCOMPLETE_SECRET = re.compile(
    r"(?:token|secret|passw(?:or)?d|api[_-]?key|authorization|cookie|private[_-]?key|credential)"
    r"[A-Za-z0-9_-]*\s*[=:]\s*(?:(?:Bearer|Basic)\s*)?$",
    re.IGNORECASE,
)


@dataclass
class OutputBuffer:
    chunks: list[dict[str, Any]] = field(default_factory=list)
    size: int = 0
    complete: bool = False
    truncated: bool = False
    pending: dict[Stream, str] = field(default_factory=dict)
    discarding: set[Stream] = field(default_factory=set)

    def truncate(self) -> None:
        self.truncated = True
        self.pending.clear()
        self.discarding.update({"stdout", "stderr"})

    def append(self, stream: Stream, text: str) -> None:
        if self.complete:
            return
        for fragment in text.splitlines(keepends=True):
            if stream not in self.discarding:
                line = self.pending.get(stream, "") + fragment
                if len(line) > 2048:
                    self.pending.pop(stream, None)
                    self.discarding.add(stream)
                    self.truncated = True
                elif fragment.endswith(("\n", "\r")):
                    if _INCOMPLETE_SECRET.search(line):
                        self.pending[stream] = line
                    else:
                        self.pending.pop(stream, None)
                        self._emit(stream, line)
                else:
                    self.pending[stream] = line

    def _emit(self, stream: Stream, text: str) -> None:
        safe = redact_text(text)
        for start in range(0, len(safe), 2048):
            chunk = safe[start : start + 2048]
            size = len(chunk.encode())
            if len(self.chunks) >= 256 or self.size + size > 262144:
                self.truncated = True
                return
            self.size += size
            self.chunks.append({"sequence": len(self.chunks) + 1, "stream": stream, "text": chunk})

    def finish(self) -> None:
        for stream, text in self.pending.items():
            self._emit(stream, text)
        self.pending.clear()
        self.complete = True


class OutputStore:
    """Single-instance bounded cache, mirroring the existing bridge registry seam."""

    def __init__(
        self, *, clock: Callable[[], float] = monotonic, ttl: float = 900, capacity: int = 64
    ) -> None:
        self.clock, self.ttl, self.capacity = clock, ttl, capacity
        self.items: dict[Key, tuple[float, OutputBuffer]] = {}

    def _prune(self) -> None:
        now = self.clock()
        self.items = {key: item for key, item in self.items.items() if now - item[0] < self.ttl}

    def start(self, key: Key) -> OutputBuffer:
        self._prune()
        if key in self.items:
            return self.items[key][1]
        if len(self.items) >= self.capacity:
            self.items.pop(next(iter(self.items)))
        buffer = OutputBuffer()
        self.items[key] = (self.clock(), buffer)
        return buffer

    def read(self, key: Key, cursor: int) -> dict[str, Any]:
        self._prune()
        item = self.items.get(key)
        if item is None:
            return {"chunks": [], "cursor": cursor, "complete": False, "truncated": False}
        buffer = item[1]
        return {
            "chunks": buffer.chunks[cursor:],
            "cursor": max(cursor, len(buffer.chunks)),
            "complete": buffer.complete,
            "truncated": buffer.truncated,
        }


output_store = OutputStore()
