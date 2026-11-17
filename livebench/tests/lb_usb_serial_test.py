"""R3 USB-serial transport: bound by USB serial (resolved to the by-id alias per open), baud
and timeout from the robot's config, exclusive port, and a port path that is only ever
informational. SOLUSDEV-326: every open claims the device from the serial owner (one holder;
busy is a typed error), and a rate change re-rates the open port instead of reopening it."""

from typing import Any

import pytest
from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError
from livebench.hardware.serial_owner import (
    Claimant,
    PortListener,
    SerialOwner,
    claiming,
    current_claimant,
)
from livebench.hardware.usb_serial import (
    DEFAULT_BAUD,
    DEFAULT_TIMEOUT_S,
    UsbSerialChannel,
    open_usb_serial,
    register_usb_serial,
)
from solus_api.hardware.config import TransportBinding, TransportKind
from solus_api.livebench.sessions import DeviceBusyError, DeviceNotFoundError

BY_ID = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B42134331-if00"


class _FakePort:
    def __init__(self, path: str, baud: int, **kwargs: Any) -> None:
        self.path = path
        self.baud = baud
        self.baudrate = baud
        self.kwargs = kwargs
        self.written: list[bytes] = []
        self.to_read: list[bytes] = []
        self.resets = 0
        self.closed = False

    def write(self, data: bytes, /) -> int:
        self.written.append(data)
        return len(data)

    def read(self, size: int = 1, /) -> bytes:
        return self.to_read.pop(0) if self.to_read else b""

    def readline(self, size: int | None = -1, /) -> bytes:
        return self.read()

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


class _Opener:
    """Records every port it opens."""

    def __init__(self) -> None:
        self.ports: list[_FakePort] = []

    def __call__(self, path: str, baud: int, **kwargs: Any) -> _FakePort:
        self.ports.append(_FakePort(path, baud, **kwargs))
        return self.ports[-1]


def _open(
    params: dict[str, Any], opener: _Opener, owner: SerialOwner | None = None
) -> UsbSerialChannel:
    return open_usb_serial(
        _binding(), params, opener=opener, resolver=_resolver, owner=owner or SerialOwner()
    )


def test_open_binds_by_usb_serial_and_reads_baud_and_timeout_from_params() -> None:
    opener = _Opener()
    channel = _open({"baud": 1_000_000, "timeout_s": 0.05}, opener)
    assert isinstance(channel, UsbSerialChannel)
    assert channel.kind is TransportKind.USB_SERIAL
    assert opener.ports[0].path == BY_ID and opener.ports[0].baud == 1_000_000
    assert opener.ports[0].kwargs == {"timeout": 0.05, "write_timeout": 0.05, "exclusive": True}
    assert channel.identity.last_seen_path == BY_ID
    assert channel.identity.device_ref == "usb:5B42134331"  # the path never enters identity


def test_defaults_apply_when_the_config_names_no_parameters() -> None:
    opener = _Opener()
    _open({}, opener)
    assert opener.ports[0].baud == DEFAULT_BAUD == 115200
    assert opener.ports[0].kwargs["timeout"] == DEFAULT_TIMEOUT_S


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
    register_usb_serial(registry, opener=_Opener(), resolver=_resolver, owner=SerialOwner())
    with pytest.raises(TransportUnavailableError):
        registry.open(_binding("NOPE"), {})
    assert registry.kinds() == [TransportKind.USB_SERIAL]


def test_out_of_range_parameters_are_refused() -> None:
    with pytest.raises(ValueError):
        _open({"baud": 10}, _Opener())


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

    open_usb_serial(_binding(), {}, opener=_Opener(), resolver=resolver, owner=SerialOwner())
    assert seen == [("5B42134331", 0x1A86, 0x55D3)]


# ── SOLUSDEV-326: the serial owner, and a rate change without a reopen ──


def test_a_held_device_is_busy_through_the_registry_until_its_channel_closes() -> None:
    opener, owner = _Opener(), SerialOwner()
    registry = TransportRegistry()
    register_usb_serial(registry, opener=opener, resolver=_resolver, owner=owner)
    with claiming(Claimant("session", "p1", "alice")):
        first = registry.open(_binding(), {})
        with pytest.raises(DeviceBusyError) as busy:  # typed, never wrapped as "unavailable"
            registry.open(_binding(), {})
    assert (busy.value.device_ref, busy.value.holder) == ("usb:5B42134331", "session")
    assert len(opener.ports) == 1  # the busy open never touched the port
    first.close()
    registry.open(_binding(), {}).close()
    assert len(opener.ports) == 2


def test_an_interrogation_listens_on_its_own_members_session_channel() -> None:
    opener, owner = _Opener(), SerialOwner()
    with claiming(Claimant("session", "p1", "alice")):
        session = _open({"baud": 57_600}, opener, owner)
    with claiming(Claimant("interrogation", "p1", "alice")):
        probe = _open({"baud": 1_000_000}, opener, owner)
    assert isinstance(probe.port, PortListener) and len(opener.ports) == 1
    assert probe.params["baud"] == 57_600  # it hears the session at the session's rate
    opener.ports[0].to_read = [b"1,2\n"]
    received = session.recv()
    assert received is not None and received.payload == b"1,2\n"
    heard = probe.recv()
    assert heard is not None and heard.payload == b"1,2\n"
    probe.close()
    session.close()


def test_open_parameters_never_carry_a_claim() -> None:
    """The claim is set by Solus code around the open, never read from a config's parameters: a
    stored config naming an interrogation of the holding session's own member and project is
    still a session's open, so it is busy — never a listener on that session's stream."""
    opener, owner = _Opener(), SerialOwner()
    with claiming(Claimant("session", "p1", "alice")):
        session = _open({"baud": 57_600}, opener, owner)
    forged = {
        "purpose": "interrogation",
        "scope": "p1",
        "member": "alice",
        "claimant": "interrogation",
    }
    with pytest.raises(DeviceBusyError):
        _open(forged, opener, owner)
    assert len(opener.ports) == 1
    assert current_claimant() == Claimant()  # outside `claiming`, every open is a session's
    session.close()


def test_retune_re_rates_the_open_port_and_never_reopens_it() -> None:
    opener, owner = _Opener(), SerialOwner()
    channel = _open({"baud": 1_000_000}, opener, owner)
    assert channel.retune(115_200) == 115_200
    assert opener.ports[0].baudrate == 115_200 and channel.params["baud"] == 115_200
    assert len(opener.ports) == 1
    channel.close()
    with claiming(Claimant("session", "p1", "alice")):
        session = _open({"baud": 9600}, opener, owner)
    with claiming(Claimant("interrogation", "p1", "alice")):
        listened = _open({}, opener, owner)
    assert listened.retune(250_000) == 9600  # a session's port keeps the session's rate
    assert opener.ports[-1].baudrate == 9600 and len(opener.ports) == 2
    listened.close()
    session.close()
