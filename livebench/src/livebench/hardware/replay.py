"""A `Channel` over recorded frames (R3 / Phase 6): a capture opens through the same
transport → driver path as live hardware, so drivers and interrogators are proven on fixtures
without a device on the bench. Recorded bytes are the truth; `send` is kept for assertions."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from solus_api.hardware.config import TransportBinding, TransportKind

from livebench.hardware.channel import Frame, Opener

MAX_RECORDED_FRAMES: Final = 100_000
MAX_FRAME_BYTES: Final = 64 * 1024


@dataclass(frozen=True)
class RecordedFrame:
    at_s: float
    payload: bytes
    address: str | None = None


@dataclass(frozen=True)
class Recording:
    identity: TransportBinding
    frames: list[RecordedFrame]


class ReplayChannel:
    def __init__(
        self,
        kind: TransportKind,
        identity: TransportBinding,
        frames: Sequence[RecordedFrame],
        *,
        realtime: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.kind = kind
        self.identity = identity
        self.sent: list[Frame] = []
        self.closed = False
        self._frames = list(frames)
        self._index = 0
        self._pending = b""
        self._realtime = realtime
        self._clock = clock
        self._sleep = sleep
        self._started_at: float | None = None
        self._base_t = self._frames[0].at_s if self._frames else 0.0

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        if self._pending:
            return self._take(max_bytes)
        if self._index >= len(self._frames):
            return None  # end of the recording is silence, as on a real link
        frame = self._frames[self._index]
        self._index += 1
        if self._realtime:
            self._wait_until(frame.at_s)
        if frame.address is None and len(frame.payload) > max_bytes:
            self._pending = frame.payload  # a byte stream splits to the caller's read size
            return self._take(max_bytes)
        return Frame(payload=frame.payload, address=frame.address)

    def _take(self, size: int) -> Frame:
        out, self._pending = self._pending[:size], self._pending[size:]
        return Frame(payload=out)

    def _wait_until(self, at_s: float) -> None:
        if self._started_at is None:
            self._started_at = self._clock()
        due = self._started_at + (at_s - self._base_t)
        now = self._clock()
        if due > now:
            self._sleep(due - now)

    def flush_input(self) -> None:
        return None  # recorded bytes are the truth; nothing is stale

    def close(self) -> None:
        self.closed = True


def load_recording(path: Path) -> Recording:
    """`{"transport", "binding", "frames": [{"t", "hex", "address"?}]}` with bounds."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("a recording is a JSON object")
    identity = TransportBinding(kind=TransportKind(raw["transport"]), binding=str(raw["binding"]))
    items = raw.get("frames")
    if not isinstance(items, list) or len(items) > MAX_RECORDED_FRAMES:
        raise ValueError(f"frames must be a list of at most {MAX_RECORDED_FRAMES}")
    frames: list[RecordedFrame] = []
    for item in items:
        payload = bytes.fromhex(str(item["hex"]))  # ValueError on anything but hex
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError(f"a frame is at most {MAX_FRAME_BYTES} bytes")
        address = item.get("address")
        frames.append(
            RecordedFrame(
                at_s=float(item["t"]),
                payload=payload,
                address=address if isinstance(address, str) else None,
            )
        )
    return Recording(identity=identity, frames=frames)


def replay_opener(recording: Recording, *, realtime: bool = False) -> Opener:
    """An opener for the recorded transport kind — register it in place of the live one."""

    def opener(binding: TransportBinding, params: object) -> ReplayChannel:
        return ReplayChannel(recording.identity.kind, binding, recording.frames, realtime=realtime)

    return opener
