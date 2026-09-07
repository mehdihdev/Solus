"""Bluetooth transports (R3): BLE (GATT notify/write) and Classic (RFCOMM) byte-stream
`Channel`s bound by device address, vendor-free, and honest when the stack is absent.

Both openers are BLOCKING and are only ever called off-loop (the registry opens channels from
`asyncio.to_thread`; drivers poll them the same way). The live BLE path drives an async
`bleak` client on a dedicated thread-bound event loop so the sync `Channel` shape holds; that
path is UNVERIFIED WITHOUT HARDWARE — everything above the client surface is proven on fakes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import socket
import threading
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Final, Protocol

from solus_api.hardware.config import TransportBinding, TransportKind

from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S: Final = 0.5
DEFAULT_CONNECT_TIMEOUT_S: Final = 10.0
DEFAULT_RFCOMM_CHANNEL: Final = 1
MAX_QUEUED_FRAMES: Final = 1024
_TIMEOUT_RANGE_S: Final = (0.001, 30.0)
_CONNECT_TIMEOUT_RANGE_S: Final = (0.1, 120.0)
_RFCOMM_CHANNEL_RANGE: Final = (1, 30)  # RFCOMM server channels are 1..30 by spec
_MAX_UUID_CHARS: Final = 64
_FLUSH_CHUNK: Final = 4096
_LOOP_JOIN_S: Final = 1.0


#: bleak's notify shape: (characteristic, data) — data arrives as a bytearray.
BleNotifyCallback = Callable[[object, bytes | bytearray], None]


class BleClientLike(Protocol):
    """The slice of a BLE client a channel needs (sync; the bleak facade below adapts)."""

    def start_notify(self, char: str, callback: BleNotifyCallback) -> None: ...

    def write_gatt_char(self, char: str, data: bytes) -> None: ...

    def disconnect(self) -> None: ...


class BtSocketLike(Protocol):
    """The slice of an RFCOMM socket a channel needs (injectable in tests)."""

    def settimeout(self, timeout: float | None) -> None: ...

    def sendall(self, data: bytes) -> None: ...

    def recv(self, bufsize: int) -> bytes: ...

    def close(self) -> None: ...


#: (address, validated params) → a connected client.
BleClientFactory = Callable[[str, Mapping[str, Any]], BleClientLike]
#: (address, rfcomm channel, connect timeout) → a connected socket.
BtSocketFactory = Callable[[str, int, float], BtSocketLike]


class BleChannel:
    kind = TransportKind.BLE

    def __init__(
        self,
        client: BleClientLike,
        identity: TransportBinding,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.identity = identity
        #: The transport parameters this channel was opened with (characteristics, timeouts).
        self.params: dict[str, Any] = dict(params or {})
        self.dropped = 0
        self._timeout_s = float(self.params.get("timeout_s", DEFAULT_TIMEOUT_S))
        self._tx = str(self.params["tx_characteristic"])
        self._inbox: queue.Queue[bytes] = queue.Queue(maxsize=MAX_QUEUED_FRAMES)
        self._pending = b""
        client.start_notify(str(self.params["rx_characteristic"]), self._on_notify)

    def _on_notify(self, _char: object, data: bytes | bytearray) -> None:
        if self._inbox.full():  # single producer (the client's thread): full → drop oldest
            with contextlib.suppress(queue.Empty):
                self._inbox.get_nowait()
            self.dropped += 1
            if self.dropped == 1 or self.dropped % MAX_QUEUED_FRAMES == 0:
                logger.warning(
                    "%s: BLE inbox full, dropped oldest notification (%d dropped so far)",
                    self.identity.device_ref,
                    self.dropped,
                )
        self._inbox.put_nowait(bytes(data))

    def send(self, frame: Frame) -> None:
        self.client.write_gatt_char(self._tx, frame.payload)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        if not self._pending:
            try:
                self._pending = self._inbox.get(timeout=self._timeout_s)
            except queue.Empty:
                return None
        out, self._pending = self._pending[:max_bytes], self._pending[max_bytes:]
        return Frame(payload=out)  # a byte stream splits to the caller's read size

    def flush_input(self) -> None:
        self._pending = b""
        with contextlib.suppress(queue.Empty):
            while True:
                self._inbox.get_nowait()

    def close(self) -> None:
        self.client.disconnect()


class BtClassicChannel:
    kind = TransportKind.BT_CLASSIC

    def __init__(
        self,
        sock: BtSocketLike,
        identity: TransportBinding,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        self.sock = sock
        self.identity = identity
        self.params: dict[str, Any] = dict(params or {})
        self._timeout_s = float(self.params.get("timeout_s", DEFAULT_TIMEOUT_S))
        sock.settimeout(self._timeout_s)

    def send(self, frame: Frame) -> None:
        self.sock.sendall(frame.payload)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        try:
            data = self.sock.recv(max_bytes)
        except TimeoutError:
            return None
        return Frame(payload=data) if data else None  # a closed peer is silence; send surfaces it

    def flush_input(self) -> None:
        self.sock.settimeout(0.0)
        try:
            with contextlib.suppress(OSError):  # BlockingIOError once drained
                while self.sock.recv(_FLUSH_CHUNK):
                    pass
        finally:
            self.sock.settimeout(self._timeout_s)

    def close(self) -> None:
        self.sock.close()


def _bt_bounded(
    params: Mapping[str, Any], key: str, default: float, bounds: tuple[float, float]
) -> float:
    value = float(params.get(key, default))
    if not bounds[0] <= value <= bounds[1]:
        raise ValueError(f"{key} must be between {bounds[0]} and {bounds[1]}")
    return value


def _uuid_param(params: Mapping[str, Any], key: str, *, required: bool) -> str | None:
    value = params.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not 0 < len(value) <= _MAX_UUID_CHARS:
        raise ValueError(f"{key} must be a non-empty string of at most {_MAX_UUID_CHARS} chars")
    return value


def _ble_params(params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "service_uuid": _uuid_param(params, "service_uuid", required=False),
        "rx_characteristic": _uuid_param(params, "rx_characteristic", required=True),
        "tx_characteristic": _uuid_param(params, "tx_characteristic", required=True),
        "timeout_s": _bt_bounded(params, "timeout_s", DEFAULT_TIMEOUT_S, _TIMEOUT_RANGE_S),
        "connect_timeout_s": _bt_bounded(
            params, "connect_timeout_s", DEFAULT_CONNECT_TIMEOUT_S, _CONNECT_TIMEOUT_RANGE_S
        ),
    }


class _LoopBoundBleClient:
    """Sync facade over an async client (bleak's shape) living on its own loop thread. Every
    call blocks the caller up to `timeout_s`; `disconnect` also stops and closes the loop."""

    def __init__(self, client: Any, loop: asyncio.AbstractEventLoop, *, timeout_s: float) -> None:
        self._client = client
        self._loop = loop
        self._timeout_s = timeout_s
        self._thread = threading.Thread(target=loop.run_forever, name="ble-loop", daemon=True)
        self._thread.start()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(self._timeout_s)

    def connect(self) -> None:
        self._run(self._client.connect())

    def start_notify(self, char: str, callback: BleNotifyCallback) -> None:
        self._run(self._client.start_notify(char, callback))

    def write_gatt_char(self, char: str, data: bytes) -> None:
        self._run(self._client.write_gatt_char(char, data))

    def disconnect(self) -> None:
        try:
            self._run(self._client.disconnect())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(_LOOP_JOIN_S)
            if not self._thread.is_alive():
                self._loop.close()


def _bleak_client_factory(address: str, params: Mapping[str, Any]) -> BleClientLike:
    """UNVERIFIED WITHOUT HARDWARE: the live bleak path, kept to these lines on purpose."""
    try:
        import bleak  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TransportUnavailableError(
            "bleak is not installed — BLE transport unavailable"
        ) from exc
    connect_timeout_s = float(params["connect_timeout_s"])
    client = _LoopBoundBleClient(
        bleak.BleakClient(address, timeout=connect_timeout_s),
        asyncio.new_event_loop(),
        timeout_s=connect_timeout_s,
    )
    try:
        client.connect()
    except BaseException:
        client.disconnect()
        raise
    return client


def _rfcomm_socket_factory(address: str, channel: int, connect_timeout_s: float) -> BtSocketLike:
    if not hasattr(socket, "AF_BLUETOOTH"):
        raise TransportUnavailableError(
            "this platform has no Bluetooth sockets — BT Classic transport unavailable"
        )
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(connect_timeout_s)
    try:
        sock.connect((address, channel))
    except OSError:
        sock.close()
        raise
    return sock


def open_ble(
    binding: TransportBinding,
    params: Mapping[str, Any],
    *,
    client_factory: BleClientFactory | None = None,
) -> BleChannel:
    """BLOCKING — call off-loop. Without a factory the live bleak stack is used (or refused)."""
    clean = _ble_params(params)
    client = (client_factory or _bleak_client_factory)(binding.binding, clean)
    return BleChannel(client, binding, clean)


def open_bt_classic(
    binding: TransportBinding,
    params: Mapping[str, Any],
    *,
    socket_factory: BtSocketFactory | None = None,
) -> BtClassicChannel:
    """BLOCKING — call off-loop. Connects RFCOMM `channel` on the bound address."""
    channel_no = int(_bt_bounded(params, "channel", DEFAULT_RFCOMM_CHANNEL, _RFCOMM_CHANNEL_RANGE))
    timeout_s = _bt_bounded(params, "timeout_s", DEFAULT_TIMEOUT_S, _TIMEOUT_RANGE_S)
    connect_timeout_s = _bt_bounded(
        params, "connect_timeout_s", DEFAULT_CONNECT_TIMEOUT_S, _CONNECT_TIMEOUT_RANGE_S
    )
    sock = (socket_factory or _rfcomm_socket_factory)(
        binding.binding, channel_no, connect_timeout_s
    )
    clean = {"channel": channel_no, "timeout_s": timeout_s, "connect_timeout_s": connect_timeout_s}
    return BtClassicChannel(sock, binding, clean)


def register_bluetooth(
    registry: TransportRegistry,
    *,
    client_factory: BleClientFactory | None = None,
    socket_factory: BtSocketFactory | None = None,
) -> None:
    registry.register(TransportKind.BLE, lambda b, p: open_ble(b, p, client_factory=client_factory))
    registry.register(
        TransportKind.BT_CLASSIC, lambda b, p: open_bt_classic(b, p, socket_factory=socket_factory)
    )
