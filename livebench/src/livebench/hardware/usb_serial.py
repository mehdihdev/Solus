"""USB-serial transport (R3): a byte-stream `Channel` bound by USB serial number.

The binding is the USB serial; the tty path is resolved from it on EVERY open through the
`/dev/serial/by-id` alias (which embeds the serial), so a reconnect after re-enumeration
reopens the same physical device, never whatever inherited its old tty number. Baud and
timeout come from the robot's config; the port is opened exclusively (one master per bus).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol

import serial as pyserial
from solus_api.hardware.config import TransportBinding, TransportKind

from livebench.hardware.channel import Frame, TransportRegistry
from livebench.local import resolve_serial_device

DEFAULT_BAUD: Final = 115200
DEFAULT_TIMEOUT_S: Final = 0.1
_BAUD_RANGE: Final = (300, 3_000_000)
_TIMEOUT_RANGE_S: Final = (0.001, 5.0)


class SerialPortLike(Protocol):
    """The slice of pyserial a channel needs (injectable in tests)."""

    def write(self, data: bytes) -> int | None: ...

    def read(self, size: int) -> bytes: ...

    def reset_input_buffer(self) -> None: ...

    def close(self) -> None: ...


PortOpener = Callable[..., SerialPortLike]
Resolver = Callable[..., str]


class UsbSerialChannel:
    kind = TransportKind.USB_SERIAL

    def __init__(
        self,
        port: SerialPortLike,
        identity: TransportBinding,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        self.port = port
        self.identity = identity
        #: The transport parameters this channel was opened with (baud, timeout_s) — an
        #: interrogator reports them so a proposal's config records the baud that answered.
        self.params: dict[str, Any] = dict(params or {})

    def send(self, frame: Frame) -> None:
        self.port.write(frame.payload)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        data = self.port.read(max_bytes)
        return Frame(payload=data) if data else None

    def flush_input(self) -> None:
        self.port.reset_input_buffer()

    def close(self) -> None:
        self.port.close()


def _bounded(
    params: Mapping[str, Any], key: str, default: float, bounds: tuple[float, float]
) -> float:
    value = float(params.get(key, default))
    if not bounds[0] <= value <= bounds[1]:
        raise ValueError(f"{key} must be between {bounds[0]} and {bounds[1]}")
    return value


def open_usb_serial(
    binding: TransportBinding,
    params: Mapping[str, Any],
    *,
    opener: PortOpener = pyserial.Serial,
    resolver: Resolver = resolve_serial_device,
) -> UsbSerialChannel:
    baud = int(_bounded(params, "baud", DEFAULT_BAUD, _BAUD_RANGE))
    timeout = _bounded(params, "timeout_s", DEFAULT_TIMEOUT_S, _TIMEOUT_RANGE_S)
    confirmed = params.get("confirmed_device_path")
    path = resolver(
        binding.binding,
        confirmed_device_path=confirmed if isinstance(confirmed, str) else None,
        vid=binding.vid,  # a port binding must still front the bound device
        pid=binding.pid,
    )
    port = opener(path, baud, timeout=timeout, write_timeout=timeout, exclusive=True)
    return UsbSerialChannel(
        port,
        binding.model_copy(update={"last_seen_path": path}),
        {"baud": baud, "timeout_s": timeout},
    )


def register_usb_serial(
    registry: TransportRegistry,
    *,
    opener: PortOpener = pyserial.Serial,
    resolver: Resolver = resolve_serial_device,
) -> None:
    registry.register(
        TransportKind.USB_SERIAL,
        lambda binding, params: open_usb_serial(binding, params, opener=opener, resolver=resolver),
    )
