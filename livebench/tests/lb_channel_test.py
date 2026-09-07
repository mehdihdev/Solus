"""R3 transport seam (docs/architecture/hardware-onboarding.md): a `Channel` carries frames
for ANY protocol; the transport layer never knows what the bytes mean."""

from collections.abc import Mapping
from typing import Any

import pytest
from livebench.hardware.channel import (
    Channel,
    Frame,
    TransportRegistry,
    TransportUnavailableError,
    as_bus_port,
)
from solus_api.hardware.config import TransportBinding, TransportKind


class _LoopbackChannel:
    """A Channel that echoes what it is sent — enough to prove the seam."""

    kind = TransportKind.USB_SERIAL

    def __init__(self, identity: TransportBinding) -> None:
        self.identity = identity
        self.inbox: list[Frame] = []
        self.closed = False
        self.flushed = 0

    def send(self, frame: Frame) -> None:
        self.inbox.append(frame)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return self.inbox.pop(0) if self.inbox else None

    def flush_input(self) -> None:
        self.flushed += 1
        self.inbox.clear()

    def close(self) -> None:
        self.closed = True


def _binding(serial: str = "5B42134331") -> TransportBinding:
    return TransportBinding(kind=TransportKind.USB_SERIAL, binding=serial)


def test_frame_is_payload_plus_optional_address() -> None:
    frame = Frame(payload=b"\xff\xff\x01\x02\x01\xfb")
    assert frame.address is None and frame.payload.startswith(b"\xff")
    can = Frame(payload=b"\x00" * 8, address="0x201")
    assert can.address == "0x201"


def test_a_loopback_satisfies_the_channel_protocol() -> None:
    channel: Channel = _LoopbackChannel(_binding())
    channel.send(Frame(payload=b"hi"))
    received = channel.recv()
    assert received is not None and received.payload == b"hi"
    assert channel.recv() is None  # timeout → None, never an exception
    assert channel.identity.device_ref == "usb:5B42134331"


def test_registry_opens_by_transport_kind_and_refuses_unknown_kinds() -> None:
    registry = TransportRegistry()
    opened: list[tuple[TransportBinding, Mapping[str, Any]]] = []

    def opener(binding: TransportBinding, params: Mapping[str, Any]) -> Channel:
        opened.append((binding, params))
        return _LoopbackChannel(binding)

    registry.register(TransportKind.USB_SERIAL, opener)
    channel = registry.open(_binding(), {"baud": 1_000_000})
    assert isinstance(channel, _LoopbackChannel)
    assert opened == [(_binding(), {"baud": 1_000_000})]
    with pytest.raises(TransportUnavailableError):
        registry.open(TransportBinding(kind=TransportKind.BLE, binding="AA:BB"), {})
    assert registry.kinds() == [TransportKind.USB_SERIAL]


def test_registry_refuses_double_registration() -> None:
    registry = TransportRegistry()
    registry.register(TransportKind.USB_SERIAL, lambda b, p: _LoopbackChannel(b))
    with pytest.raises(ValueError):
        registry.register(TransportKind.USB_SERIAL, lambda b, p: _LoopbackChannel(b))


def test_an_opener_that_cannot_open_surfaces_as_unavailable() -> None:
    registry = TransportRegistry()

    def broken(binding: TransportBinding, params: Mapping[str, Any]) -> Channel:
        raise OSError("no such device")

    registry.register(TransportKind.USB_SERIAL, broken)
    with pytest.raises(TransportUnavailableError) as excinfo:
        registry.open(_binding(), {})
    assert "usb:5B42134331" in str(excinfo.value)


def test_as_bus_port_adapts_a_channel_to_request_response_byte_calls() -> None:
    channel = _LoopbackChannel(_binding())
    port = as_bus_port(channel)
    assert port.write(b"\x01\x02") == 2
    assert port.read(8) == b"\x01\x02"
    assert port.read(8) == b""  # silence is empty bytes, as pyserial reports it
    port.reset_input_buffer()
    assert channel.flushed == 1
    port.close()
    assert channel.closed


def test_channel_module_names_no_vendor() -> None:
    import re
    from pathlib import Path

    import livebench.hardware.channel as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None
