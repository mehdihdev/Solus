"""R3 USB-CAN transport: arbitration-id frames over a python-can bus, bound by adapter identity;
interface/channel/bitrate/timeout from the robot's config with bounds; honest about a missing
python-can; injectable bus for tests. Shared code — names no vendor."""

import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError
from livebench.hardware.usb_can import UsbCanChannel, open_usb_can, register_usb_can
from solus_api.hardware.config import TransportBinding, TransportKind


class _Msg(NamedTuple):
    arbitration_id: int
    data: bytes


class _FakeCanBus:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.sent: list[Any] = []
        self.inbox: list[_Msg] = []
        self.recv_timeouts: list[float | None] = []
        self.shut = False

    def send(self, msg: Any) -> None:
        self.sent.append(msg)

    def recv(self, timeout: float | None = None) -> _Msg | None:
        self.recv_timeouts.append(timeout)
        return self.inbox.pop(0) if self.inbox else None

    def shutdown(self) -> None:
        self.shut = True


def _binding(path: str | None = "can1") -> TransportBinding:
    return TransportBinding(
        kind=TransportKind.USB_CAN, binding="ODRV-3F2A-CAN0", last_seen_path=path
    )


def _factory(buses: list[_FakeCanBus]) -> Any:
    def make(**kwargs: Any) -> _FakeCanBus:
        buses.append(_FakeCanBus(**kwargs))
        return buses[-1]

    return make


def test_open_defaults_and_binds_by_adapter_identity() -> None:
    buses: list[_FakeCanBus] = []

    channel = open_usb_can(_binding(), {}, bus_factory=_factory(buses))

    assert isinstance(channel, UsbCanChannel) and channel.kind is TransportKind.USB_CAN
    assert buses[0].kwargs == {"interface": "socketcan", "channel": "can1", "bitrate": 250_000}
    assert channel.params == {
        "interface": "socketcan",
        "channel": "can1",
        "bitrate": 250_000,
        "timeout_s": 0.1,
    }
    assert channel.identity.device_ref == "can:ODRV-3F2A-CAN0"
    assert channel.identity.last_seen_path == "can1"


def test_channel_defaults_to_can0_without_a_remembered_path() -> None:
    buses: list[_FakeCanBus] = []
    open_usb_can(_binding(None), {}, bus_factory=_factory(buses))
    assert buses[0].kwargs["channel"] == "can0"


def test_params_override_are_bounded_and_ignore_driver_params() -> None:
    buses: list[_FakeCanBus] = []
    params = {
        "interface": "pcan",
        "channel": "PCAN_USBBUS1",
        "bitrate": 500_000,
        "timeout_s": 0.02,
        "baud": 1_000_000,  # a driver parameter riding along in the same dict
    }

    channel = open_usb_can(_binding(), params, bus_factory=_factory(buses))

    assert buses[0].kwargs == {"interface": "pcan", "channel": "PCAN_USBBUS1", "bitrate": 500_000}
    assert channel.params["timeout_s"] == 0.02 and "baud" not in channel.params
    for bad in ({"bitrate": 5_000}, {"bitrate": 2_000_000}, {"timeout_s": 0}, {"interface": ""}):
        with pytest.raises(ValueError):
            open_usb_can(_binding(), bad, bus_factory=_factory(buses))


def test_send_recv_flush_and_close() -> None:
    buses: list[_FakeCanBus] = []
    channel = open_usb_can(_binding(), {}, bus_factory=_factory(buses))
    bus = buses[0]

    channel.send(Frame(payload=b"\x01\x02", address="0x201"))
    channel.send(Frame(payload=b"\x03", address="0x12345"))
    with pytest.raises(ValueError):
        channel.send(Frame(payload=b"\x00"))  # a CAN frame needs an arbitration id

    assert (bus.sent[0].arbitration_id, bus.sent[0].data) == (0x201, b"\x01\x02")
    assert bus.sent[0].is_extended_id is False
    assert bus.sent[1].is_extended_id is True  # above 11 bits

    bus.inbox = [_Msg(0x209, b"\x00" * 8)]
    assert channel.recv() == Frame(payload=b"\x00" * 8, address="0x209")
    assert channel.recv() is None  # timeout is silence, not an error
    assert bus.recv_timeouts == [0.1, 0.1]

    bus.inbox = [_Msg(0x201, b"\x01"), _Msg(0x201, b"\x02"), _Msg(0x201, b"\x03")]
    channel.flush_input()
    assert bus.inbox == [] and channel.recv() is None

    channel.close()
    assert bus.shut


def test_without_python_can_the_transport_is_honestly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "can", None)
    with pytest.raises(TransportUnavailableError, match="python-can is not installed"):
        open_usb_can(_binding(), {})


def test_register_usb_can_opens_through_the_registry() -> None:
    buses: list[_FakeCanBus] = []
    registry = TransportRegistry()
    register_usb_can(registry, bus_factory=_factory(buses))

    channel = registry.open(_binding(), {"bitrate": 500_000})

    assert registry.kinds() == [TransportKind.USB_CAN]
    assert isinstance(channel, UsbCanChannel) and buses[0].kwargs["bitrate"] == 500_000
    with pytest.raises(TransportUnavailableError):
        registry.open(_binding(), {"bitrate": 1})


def test_shared_transport_and_detection_code_name_no_vendor() -> None:
    """The vendor-hygiene ratchet for this task's shared files: product names live only under
    `livebench/plugins/` and `livebench/definitions/`."""
    import livebench.hardware.usb_can as usb_can
    import livebench.recognition.passive as passive

    vendor_words = re.compile(
        r"\b(odrive|dynamixel|robotis|feetech|lerobot|sts3215|px4|mavlink|teensy|arduino"
        r"|espressif|adafruit|ftdi|prolific|wch|ch343|cp210x?|pl2303|socketcan_vendor)\b"
    )
    for module in (usb_can, passive):
        assert module.__file__ is not None
        assert vendor_words.search(Path(module.__file__).read_text().lower()) is None
