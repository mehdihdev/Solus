"""UDP network transport (R3): a datagram `Channel` for the WiFi and Ethernet bindings.

The binding is the peer's MAC or IP; the socket listens on `listen_port` for whatever the
machine streams at us and answers to the configured `endpoint` (or, absent one, the last peer
that spoke). Port and timeout come from the robot's config. Datagrams are untrusted: a read is
bounded by `max_bytes` and silence is `None`, never an error.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from solus_api.hardware.config import TransportBinding, TransportKind

from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError

DEFAULT_LISTEN_PORT: Final = 14550
DEFAULT_TIMEOUT_S: Final = 0.2
#: A telemetry listener binds every interface: the peer picks which one it reaches us on.
LISTEN_HOST: Final = "0.0.0.0"  # noqa: S104
MAX_FLUSH_DATAGRAMS: Final = 1024
UDP_KINDS: Final = (TransportKind.WIFI, TransportKind.ETHERNET)


class UdpSocketLike(Protocol):
    """The slice of a datagram socket a channel needs (injectable in tests)."""

    def bind(self, address: tuple[str, int]) -> None: ...

    def settimeout(self, timeout: float | None) -> None: ...

    def sendto(self, data: bytes, address: tuple[str, int]) -> int: ...

    def recvfrom(self, bufsize: int) -> tuple[bytes, Any]: ...

    def close(self) -> None: ...


SocketFactory = Callable[[], UdpSocketLike]


class UdpParams(BaseModel):
    """The transport's own keys; driver keys ride the same config bag and are ignored here."""

    model_config = ConfigDict(extra="ignore")
    endpoint: str | None = Field(default=None, max_length=256)
    listen_port: int = Field(default=DEFAULT_LISTEN_PORT, ge=1, le=65535)
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, gt=0, le=5)


def _parse_udp_endpoint(value: str) -> tuple[str, int]:
    parts = urlsplit(value)
    if parts.scheme != "udp" or not parts.hostname or parts.port is None:
        raise ValueError(f"endpoint must be udp://host:port, got {value!r}")
    return parts.hostname, parts.port


def _default_udp_socket() -> UdpSocketLike:
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


class UdpChannel:
    def __init__(
        self,
        sock: UdpSocketLike,
        identity: TransportBinding,
        params: UdpParams,
    ) -> None:
        self.kind = identity.kind
        self.identity = identity
        self.params: dict[str, Any] = params.model_dump(exclude_none=True)
        self._sock = sock
        self._timeout = params.timeout_s
        self._endpoint = _parse_udp_endpoint(params.endpoint) if params.endpoint else None
        self._last_peer: tuple[str, int] | None = None

    def send(self, frame: Frame) -> None:
        if frame.address is not None:
            host, _, port = frame.address.rpartition(":")
            peer: tuple[str, int] | None = (host, int(port))
        else:
            peer = self._endpoint or self._last_peer
        if peer is None:
            raise TransportUnavailableError(
                f"{self.identity.device_ref}: no endpoint configured and no peer heard yet"
            )
        self._sock.sendto(frame.payload, peer)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        try:
            data, peer = self._sock.recvfrom(max_bytes)
        except TimeoutError:
            return None
        self._last_peer = (str(peer[0]), int(peer[1]))
        return Frame(payload=data, address=f"{self._last_peer[0]}:{self._last_peer[1]}")

    def flush_input(self) -> None:
        self._sock.settimeout(0.0)
        try:
            for _ in range(MAX_FLUSH_DATAGRAMS):
                self._sock.recvfrom(65535)
        except OSError:
            pass  # BlockingIOError/TimeoutError: drained
        finally:
            self._sock.settimeout(self._timeout)

    def close(self) -> None:
        self._sock.close()


def open_udp(
    binding: TransportBinding,
    params: Mapping[str, Any],
    *,
    socket_factory: SocketFactory | None = None,
) -> UdpChannel:
    if binding.kind not in UDP_KINDS:
        raise ValueError(f"{binding.kind.value} is not a UDP transport")
    udp = UdpParams.model_validate(dict(params))
    if udp.endpoint:
        _parse_udp_endpoint(udp.endpoint)  # refuse a bad endpoint before a socket exists
    sock = (socket_factory or _default_udp_socket)()
    try:
        sock.bind((LISTEN_HOST, udp.listen_port))
        sock.settimeout(udp.timeout_s)
    except Exception:
        sock.close()
        raise
    return UdpChannel(sock, binding, udp)


def register_udp(
    registry: TransportRegistry, *, socket_factory: SocketFactory | None = None
) -> None:
    for kind in UDP_KINDS:
        registry.register(
            kind, lambda binding, params: open_udp(binding, params, socket_factory=socket_factory)
        )
