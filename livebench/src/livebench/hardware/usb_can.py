"""USB-CAN transport (R3): arbitration-id frames over a python-can bus, bound by adapter
identity. A `Frame.address` is the hex arbitration id (`"0x201"`); the payload is the data
field. Interface, channel, bitrate and timeout come from the robot's config (bounded here);
the bus object is injectable so drivers and interrogators are proven without an adapter.

python-can is optional: it is imported inside `open_usb_can`, and its absence surfaces as
`TransportUnavailableError` — never a silent fake.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import BaseModel, Field
from solus_api.hardware.config import TransportBinding, TransportKind

from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError

DEFAULT_INTERFACE: Final = "socketcan"
DEFAULT_CHANNEL: Final = "can0"
DEFAULT_BITRATE: Final = 250_000
DEFAULT_TIMEOUT_S: Final = 0.1
MAX_STANDARD_ID: Final = 0x7FF  # 11-bit; anything above rides an extended (29-bit) frame
MAX_CAN_PAYLOAD: Final = 64  # CAN FD ceiling; device input is bounded before it goes anywhere
MAX_FLUSH_FRAMES: Final = 1024  # a flooded bus must not turn a flush into a hang


class UsbCanParams(BaseModel):
    """Transport parameters; driver parameters riding in the same dict are ignored."""

    interface: str = Field(default=DEFAULT_INTERFACE, min_length=1, max_length=32)
    channel: str | None = Field(default=None, min_length=1, max_length=128)
    bitrate: int = Field(default=DEFAULT_BITRATE, ge=10_000, le=1_000_000)
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, gt=0, le=5)


class CanBusLike(Protocol):
    """The slice of `can.BusABC` a channel needs (injectable in tests)."""

    def send(self, msg: Any) -> None: ...

    def recv(self, timeout: float | None = None) -> Any: ...

    def shutdown(self) -> None: ...


BusFactory = Callable[..., CanBusLike]
MessageFactory = Callable[..., Any]


@dataclass(frozen=True)
class _UsbCanMessage:
    """`can.Message`'s shape for an injected bus (the real one is used when python-can loads)."""

    arbitration_id: int
    data: bytes
    is_extended_id: bool


class UsbCanChannel:
    kind = TransportKind.USB_CAN

    def __init__(
        self,
        bus: CanBusLike,
        identity: TransportBinding,
        params: Mapping[str, Any],
        *,
        message_factory: MessageFactory = _UsbCanMessage,
    ) -> None:
        self.bus = bus
        self.identity = identity
        #: The transport parameters this channel was opened with — an interrogator reports the
        #: bitrate so a proposal's config records the one that heard the bus.
        self.params: dict[str, Any] = dict(params)
        self._timeout = float(params["timeout_s"])
        self._message = message_factory

    def send(self, frame: Frame) -> None:
        if frame.address is None:
            raise ValueError("a CAN frame needs an arbitration id in Frame.address")
        arbitration_id = int(frame.address, 16)
        self.bus.send(
            self._message(
                arbitration_id=arbitration_id,
                data=frame.payload,
                is_extended_id=arbitration_id > MAX_STANDARD_ID,
            )
        )

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        msg = self.bus.recv(self._timeout)
        if msg is None:
            return None
        payload = bytes(msg.data)[: min(max_bytes, MAX_CAN_PAYLOAD)]
        return Frame(payload=payload, address=f"0x{int(msg.arbitration_id):03x}")

    def flush_input(self) -> None:
        for _ in range(MAX_FLUSH_FRAMES):
            if self.bus.recv(0) is None:
                return

    def close(self) -> None:
        self.bus.shutdown()


def open_usb_can(
    binding: TransportBinding,
    params: Mapping[str, Any],
    *,
    bus_factory: BusFactory | None = None,
) -> UsbCanChannel:
    settings = UsbCanParams.model_validate(dict(params))
    message_factory: MessageFactory = _UsbCanMessage
    if bus_factory is None:
        try:
            can = importlib.import_module("can")
        except ImportError:
            raise TransportUnavailableError("python-can is not installed") from None
        bus_factory, message_factory = can.Bus, can.Message
    channel_name = settings.channel or binding.last_seen_path or DEFAULT_CHANNEL
    bus = bus_factory(interface=settings.interface, channel=channel_name, bitrate=settings.bitrate)
    return UsbCanChannel(
        bus,
        binding.model_copy(update={"last_seen_path": channel_name}),
        {
            "interface": settings.interface,
            "channel": channel_name,
            "bitrate": settings.bitrate,
            "timeout_s": settings.timeout_s,
        },
        message_factory=message_factory,
    )


def register_usb_can(registry: TransportRegistry, *, bus_factory: BusFactory | None = None) -> None:
    registry.register(
        TransportKind.USB_CAN,
        lambda binding, params: open_usb_can(binding, params, bus_factory=bus_factory),
    )
