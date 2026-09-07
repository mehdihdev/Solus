"""R3 network transport: a UDP `Channel` for the WiFi and Ethernet bindings — bound on a listen
port from the config, datagrams in with their peer address, sends to the configured endpoint or
the last peer, vendor-free."""

import re
from pathlib import Path
from typing import Any

import pytest
from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError
from livebench.hardware.network import (
    DEFAULT_LISTEN_PORT,
    DEFAULT_TIMEOUT_S,
    UdpChannel,
    open_udp,
    register_udp,
)
from solus_api.hardware.config import TransportBinding, TransportKind

PEER = ("192.168.4.1", 14550)


class _FakeUdpSocket:
    def __init__(self) -> None:
        self.bound: tuple[str, int] | None = None
        self.timeout: float | None = None
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.inbox: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def bind(self, address: tuple[str, int]) -> None:
        if address[1] == 1:
            raise OSError("address already in use")
        self.bound = address

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.sent.append((data, address))
        return len(data)

    def recvfrom(self, bufsize: int) -> tuple[bytes, Any]:
        if not self.inbox:
            raise TimeoutError if self.timeout else BlockingIOError
        data, peer = self.inbox.pop(0)
        return data[:bufsize], peer

    def close(self) -> None:
        self.closed = True


def _wifi(binding: str = "aa:bb:cc:dd:ee:ff") -> TransportBinding:
    return TransportBinding(kind=TransportKind.WIFI, binding=binding)


def _open(params: dict[str, Any], binding: TransportBinding | None = None) -> tuple[Any, Any]:
    sockets: list[_FakeUdpSocket] = []

    def factory() -> _FakeUdpSocket:
        sockets.append(_FakeUdpSocket())
        return sockets[-1]

    channel = open_udp(binding or _wifi(), params, socket_factory=factory)
    return channel, sockets[0]


def test_open_binds_the_listen_port_and_reports_its_parameters() -> None:
    channel, sock = _open({"listen_port": 14551, "timeout_s": 0.05, "system_id": 1})
    assert isinstance(channel, UdpChannel)
    assert channel.kind is TransportKind.WIFI and channel.identity.device_ref.startswith("ip:")
    assert sock.bound == ("0.0.0.0", 14551) and sock.timeout == 0.05
    assert channel.params == {"listen_port": 14551, "timeout_s": 0.05}  # driver keys ignored


def test_defaults_apply_and_ethernet_keeps_its_own_kind() -> None:
    channel, sock = _open({}, TransportBinding(kind=TransportKind.ETHERNET, binding="10.0.0.9"))
    assert channel.kind is TransportKind.ETHERNET
    assert sock.bound == ("0.0.0.0", DEFAULT_LISTEN_PORT) and sock.timeout == DEFAULT_TIMEOUT_S


def test_recv_returns_the_datagram_with_its_peer_and_none_on_timeout() -> None:
    channel, sock = _open({})
    sock.inbox.append((b"\xfd\x09", PEER))
    assert channel.recv() == Frame(payload=b"\xfd\x09", address="192.168.4.1:14550")
    assert channel.recv() is None


def test_send_goes_to_the_endpoint_the_frame_address_or_the_last_peer() -> None:
    channel, sock = _open({})
    with pytest.raises(TransportUnavailableError):
        channel.send(Frame(payload=b"x"))  # nobody has spoken yet and no endpoint is configured
    sock.inbox.append((b"hb", PEER))
    channel.recv()
    channel.send(Frame(payload=b"a"))
    channel.send(Frame(payload=b"b", address="10.0.0.2:14560"))
    assert sock.sent == [(b"a", PEER), (b"b", ("10.0.0.2", 14560))]

    fixed, fixed_sock = _open({"endpoint": "udp://192.168.4.7:14555"})
    fixed_sock.inbox.append((b"hb", PEER))
    fixed.recv()
    fixed.send(Frame(payload=b"c"))
    assert fixed_sock.sent == [(b"c", ("192.168.4.7", 14555))]
    assert fixed.params["endpoint"] == "udp://192.168.4.7:14555"


def test_flush_drains_pending_datagrams_and_close_closes_the_socket() -> None:
    channel, sock = _open({"timeout_s": 0.3})
    sock.inbox.extend([(b"1", PEER), (b"2", PEER)])
    channel.flush_input()
    assert sock.inbox == [] and sock.timeout == 0.3  # the timeout is restored after draining
    channel.close()
    assert sock.closed


def test_bad_parameters_and_a_busy_port_are_refused() -> None:
    for params in ({"listen_port": 0}, {"listen_port": 70000}, {"timeout_s": 0}):
        with pytest.raises(ValueError):
            _open(params)
    with pytest.raises(ValueError):
        _open({"endpoint": "tcp://1.2.3.4:5"})
    with pytest.raises(ValueError):
        _open({"endpoint": "udp://1.2.3.4"})
    with pytest.raises(OSError):
        _open({"listen_port": 1})  # the fake refuses port 1; the registry wraps it


def test_register_udp_covers_wifi_and_ethernet_and_the_registry_wraps_failures() -> None:
    registry = TransportRegistry()
    register_udp(registry, socket_factory=_FakeUdpSocket)
    assert set(registry.kinds()) == {TransportKind.WIFI, TransportKind.ETHERNET}
    channel = registry.open(_wifi(), {"listen_port": 14550})
    assert isinstance(channel, UdpChannel)
    with pytest.raises(TransportUnavailableError):
        registry.open(_wifi(), {"listen_port": 1})


def test_network_module_names_no_vendor() -> None:
    import livebench.hardware.network as module

    source = Path(module.__file__).read_text().lower()
    vendors = r"\b(feetech|dynamixel|lerobot|sts3215|px4|ardupilot|pixhawk|odrive|mavlink)\b"
    assert re.search(vendors, source) is None
