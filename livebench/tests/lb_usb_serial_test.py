"""R3 USB-serial transport: bound by USB serial (resolved to the by-id alias per open), baud
and timeout from the robot's config, exclusive port, and a port path that is only ever
informational."""

from typing import Any

import pytest
from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError
from livebench.hardware.usb_serial import (
    DEFAULT_BAUD,
    DEFAULT_TIMEOUT_S,
    UsbSerialChannel,
    open_usb_serial,
    register_usb_serial,
)
from solus_api.hardware.config import TransportBinding, TransportKind
from solus_api.livebench.sessions import DeviceNotFoundError

BY_ID = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B42134331-if00"


class _FakePort:
    def __init__(self, path: str, baud: int, **kwargs: Any) -> None:
        self.path = path
        self.baud = baud
        self.kwargs = kwargs
        self.written: list[bytes] = []
        self.to_read: list[bytes] = []
        self.resets = 0
        self.closed = False

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def read(self, size: int) -> bytes:
        return self.to_read.pop(0) if self.to_read else b""

    def reset_input_buffer(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True


def _binding(serial: str = "5B42134331") -> TransportBinding:
    return TransportBinding(kind=TransportKind.USB_SERIAL, binding=serial, vid=0x1A86, pid=0x55D3)


def _resolver(
    serial: str | None,
    *,
    confirmed_device_path: str | None = None,
    vid: int | None = None,
    pid: int | None = None,
) -> str:
    if serial != "5B42134331":
        raise DeviceNotFoundError(f"no device with serial {serial!r}")
    return BY_ID


def test_open_binds_by_usb_serial_and_reads_baud_and_timeout_from_params() -> None:
    ports: list[_FakePort] = []

    def opener(path: str, baud: int, **kwargs: Any) -> _FakePort:
        port = _FakePort(path, baud, **kwargs)
        ports.append(port)
        return port

    channel = open_usb_serial(
        _binding(), {"baud": 1_000_000, "timeout_s": 0.05}, opener=opener, resolver=_resolver
    )
    assert isinstance(channel, UsbSerialChannel)
    assert channel.kind is TransportKind.USB_SERIAL
    assert ports[0].path == BY_ID and ports[0].baud == 1_000_000
    assert ports[0].kwargs == {"timeout": 0.05, "write_timeout": 0.05, "exclusive": True}
    assert channel.identity.last_seen_path == BY_ID
    assert channel.identity.device_ref == "usb:5B42134331"  # the path never enters identity


def test_defaults_apply_when_the_config_names_no_parameters() -> None:
    port_box: list[_FakePort] = []

    def opener(path: str, baud: int, **kwargs: Any) -> _FakePort:
        port_box.append(_FakePort(path, baud, **kwargs))
        return port_box[-1]

    open_usb_serial(_binding(), {}, opener=opener, resolver=_resolver)
    assert port_box[0].baud == DEFAULT_BAUD == 115200
    assert port_box[0].kwargs["timeout"] == DEFAULT_TIMEOUT_S


def test_send_recv_flush_close_delegate_to_the_port() -> None:
    port = _FakePort(BY_ID, 9600)
    channel = UsbSerialChannel(port, _binding())
    channel.send(Frame(payload=b"\x01"))
    assert port.written == [b"\x01"]
    port.to_read = [b"\xff\xff"]
    got = channel.recv(2)
    assert got is not None and got.payload == b"\xff\xff" and got.address is None
    assert channel.recv(2) is None  # silence
    channel.flush_input()
    assert port.resets == 1
    channel.close()
    assert port.closed


def test_an_unknown_serial_is_unavailable_through_the_registry() -> None:
    registry = TransportRegistry()
    register_usb_serial(
        registry, opener=lambda path, baud, **kw: _FakePort(path, baud, **kw), resolver=_resolver
    )
    with pytest.raises(TransportUnavailableError):
        registry.open(_binding("NOPE"), {})
    assert registry.kinds() == [TransportKind.USB_SERIAL]


def test_out_of_range_parameters_are_refused() -> None:
    with pytest.raises(ValueError):
        open_usb_serial(
            _binding(),
            {"baud": 10},
            opener=lambda path, baud, **kw: _FakePort(path, baud, **kw),
            resolver=_resolver,
        )


def test_usb_serial_module_names_no_vendor() -> None:
    import re
    from pathlib import Path

    import livebench.hardware.usb_serial as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None


def test_open_hands_the_binding_vid_pid_to_the_resolver() -> None:
    seen: list[tuple[str | None, int | None, int | None]] = []

    def resolver(
        serial: str | None,
        *,
        confirmed_device_path: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
    ) -> str:
        seen.append((serial, vid, pid))
        return BY_ID

    open_usb_serial(
        _binding(),
        {},
        opener=lambda path, baud, **kw: _FakePort(path, baud, **kw),
        resolver=resolver,
    )
    assert seen == [("5B42134331", 0x1A86, 0x55D3)]
