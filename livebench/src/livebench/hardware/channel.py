"""The transport seam (R3): a `Channel` moves frames; it does not know the protocol.

USB serial can carry a servo bus, an autopilot link or a printf; a CAN adapter carries
arbitration-id frames; a UDP socket carries datagrams. Each transport opens a channel keyed by
its binding identity (USB serial, adapter serial, BT address, MAC/IP — never a tty path) and a
`ProtocolDriver` or `Interrogator` plugin interprets what flows through it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from solus_api.hardware.config import TransportBinding, TransportKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Frame:
    """One unit on the wire. `address` is the transport's own addressing (a CAN arbitration
    id, a UDP peer) and is None on a plain byte stream."""

    payload: bytes
    address: str | None = None


class Channel(Protocol):
    """An open transport. `recv` returns None on timeout — silence is data, not an error."""

    kind: TransportKind
    identity: TransportBinding

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None: ...

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


class TransportUnavailableError(RuntimeError):
    """The transport cannot open this identity here (absent, busy, or not installed)."""


Opener = Callable[[TransportBinding, Mapping[str, Any]], Channel]

#: Keys in `protocol.params` that address the TRANSPORT (which port, which socket) rather
#: than the protocol; drivers never see them, so a driver's strict params model stays strict.
TRANSPORT_ONLY_PARAM_KEYS: frozenset[str] = frozenset(
    {"confirmed_device_path", "listen_port", "endpoint", "interface", "channel"}
)


class TransportRegistry:
    """Transport kind → opener. Transports register here; nothing imports one by name."""

    def __init__(self) -> None:
        self._openers: dict[TransportKind, Opener] = {}

    def register(self, kind: TransportKind, opener: Opener) -> None:
        if kind in self._openers:
            raise ValueError(f"transport {kind.value} is already registered")
        self._openers[kind] = opener

    def kinds(self) -> list[TransportKind]:
        return list(self._openers)

    def open(self, binding: TransportBinding, params: Mapping[str, Any]) -> Channel:
        opener = self._openers.get(binding.kind)
        if opener is None:
            raise TransportUnavailableError(
                f"no transport for {binding.device_ref} ({binding.kind.value})"
            )
        try:
            return opener(binding, dict(params))
        except TransportUnavailableError:
            raise
        except Exception as exc:
            raise TransportUnavailableError(
                f"{binding.device_ref}: {type(exc).__name__}: {exc}"
            ) from exc


class BusPortAdapter:
    """Request-response byte calls (`write`/`read(size)`/`reset_input_buffer`) over a
    `Channel`, for codecs written against a serial-port shape."""

    def __init__(self, channel: Channel) -> None:
        self._channel = channel
        self._pending = b""

    def write(self, data: bytes) -> int | None:
        self._channel.send(Frame(payload=data))
        return len(data)

    def read(self, size: int) -> bytes:
        while len(self._pending) < size:
            frame = self._channel.recv(size - len(self._pending))
            if frame is None:
                break
            self._pending += frame.payload
        out, self._pending = self._pending[:size], self._pending[size:]
        return out

    def reset_input_buffer(self) -> None:
        self._pending = b""
        self._channel.flush_input()

    def close(self) -> None:
        self._channel.close()


def as_bus_port(channel: Channel) -> BusPortAdapter:
    return BusPortAdapter(channel)
