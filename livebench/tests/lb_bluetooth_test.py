"""R3 Bluetooth transports: BLE notify/write over an injected client with a bounded inbox,
Classic RFCOMM over an injected socket, and an honest `TransportUnavailableError` when the
stack (bleak, AF_BLUETOOTH) is absent. No radio is touched here."""

import asyncio
import logging
import socket
import sys
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from livebench.hardware.bluetooth import (
    DEFAULT_RFCOMM_CHANNEL,
    DEFAULT_TIMEOUT_S,
    MAX_QUEUED_FRAMES,
    BleChannel,
    BleNotifyCallback,
    BtClassicChannel,
    _LoopBoundBleClient,
    open_ble,
    open_bt_classic,
    register_bluetooth,
)
from livebench.hardware.channel import Frame, TransportRegistry, TransportUnavailableError
from solus_api.hardware.config import TransportBinding, TransportKind

BLE_ADDR = "AA:BB:CC:DD:EE:01"
BT_ADDR = "AA:BB:CC:DD:EE:02"
BLE_PARAMS = {"rx_characteristic": "rx-uuid", "tx_characteristic": "tx-uuid", "timeout_s": 0.01}


class _FakeBleClient:
    def __init__(self) -> None:
        self.notify: dict[str, BleNotifyCallback] = {}
        self.written: list[tuple[str, bytes]] = []
        self.disconnected = False

    def start_notify(self, char: str, callback: BleNotifyCallback) -> None:
        self.notify[char] = callback

    def write_gatt_char(self, char: str, data: bytes) -> None:
        self.written.append((char, bytes(data)))

    def disconnect(self) -> None:
        self.disconnected = True

    def push(self, data: bytes) -> None:
        self.notify["rx-uuid"](object(), bytearray(data))  # bleak hands a bytearray


class _FakeBtSocket:
    def __init__(self) -> None:
        self.to_read: list[bytes | BaseException] = []
        self.sent: list[bytes] = []
        self.timeouts: list[float | None] = []
        self.closed = False

    def settimeout(self, timeout: float | None) -> None:
        self.timeouts.append(timeout)

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, bufsize: int) -> bytes:
        if not self.to_read:
            raise BlockingIOError if self.timeouts[-1] == 0.0 else TimeoutError
        item = self.to_read.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item[:bufsize]

    def close(self) -> None:
        self.closed = True


def _ble_binding() -> TransportBinding:
    return TransportBinding(kind=TransportKind.BLE, binding=BLE_ADDR)


def _bt_binding() -> TransportBinding:
    return TransportBinding(kind=TransportKind.BT_CLASSIC, binding=BT_ADDR)


def _open_fake_ble(params: Mapping[str, Any] = BLE_PARAMS) -> tuple[_FakeBleClient, BleChannel]:
    client = _FakeBleClient()
    channel = open_ble(_ble_binding(), params, client_factory=lambda address, p: client)
    return client, channel


# --- BLE ---------------------------------------------------------------------------------


def test_ble_notifications_are_received_in_order_and_silence_is_none() -> None:
    client, channel = _open_fake_ble()
    assert channel.kind is TransportKind.BLE
    assert channel.identity.device_ref == f"ble:{BLE_ADDR}"
    assert list(client.notify) == ["rx-uuid"]  # subscribed on the notify characteristic
    client.push(b"\x01")
    client.push(b"\x02\x03")
    first, second = channel.recv(), channel.recv()
    assert first is not None and first.payload == b"\x01" and first.address is None
    assert second is not None and second.payload == b"\x02\x03"
    assert channel.recv() is None  # timeout → None, never an exception


def test_ble_inbox_is_bounded_and_drops_the_oldest_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, channel = _open_fake_ble()
    with caplog.at_level(logging.WARNING, logger="livebench.hardware.bluetooth"):
        for i in range(MAX_QUEUED_FRAMES + 3):
            client.push(i.to_bytes(2, "big"))
    got = channel.recv()
    assert got is not None and got.payload == (3).to_bytes(2, "big")
    assert channel.dropped == 3
    assert any("dropp" in record.message for record in caplog.records)
    assert f"ble:{BLE_ADDR}" in caplog.text


def test_ble_recv_splits_a_notification_to_the_callers_read_size() -> None:
    client, channel = _open_fake_ble()
    client.push(b"abcdef")
    head, tail = channel.recv(4), channel.recv(4)
    assert head is not None and head.payload == b"abcd"
    assert tail is not None and tail.payload == b"ef"
    assert channel.recv(4) is None


def test_ble_send_writes_the_tx_characteristic_flush_clears_close_disconnects() -> None:
    client, channel = _open_fake_ble()
    channel.send(Frame(payload=b"\xff\xff\x01"))
    assert client.written == [("tx-uuid", b"\xff\xff\x01")]
    client.push(b"stale")
    client.push(b"stale")
    channel.flush_input()
    assert channel.recv() is None
    channel.close()
    assert client.disconnected


def test_open_ble_normalises_params_and_records_them_on_the_channel() -> None:
    client, channel = _open_fake_ble({**BLE_PARAMS, "service_uuid": "svc-uuid"})
    assert channel.params == {
        "service_uuid": "svc-uuid",
        "rx_characteristic": "rx-uuid",
        "tx_characteristic": "tx-uuid",
        "timeout_s": 0.01,
        "connect_timeout_s": 10.0,
    }
    _, defaulted = _open_fake_ble({"rx_characteristic": "rx-uuid", "tx_characteristic": "tx-uuid"})
    assert defaulted.params["timeout_s"] == DEFAULT_TIMEOUT_S == 0.5
    assert defaulted.params["service_uuid"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"tx_characteristic": "tx-uuid"},  # no notify characteristic
        {"rx_characteristic": "rx-uuid"},  # no write characteristic
        {**BLE_PARAMS, "rx_characteristic": "x" * 200},  # unbounded uuid string
        {**BLE_PARAMS, "timeout_s": 0},
        {**BLE_PARAMS, "connect_timeout_s": 10_000},
    ],
)
def test_open_ble_refuses_malformed_params(params: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _open_fake_ble(params)


def test_open_ble_without_bleak_is_unavailable_with_an_honest_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "bleak", None)  # `import bleak` raises ImportError
    with pytest.raises(TransportUnavailableError) as excinfo:
        open_ble(_ble_binding(), BLE_PARAMS)
    assert str(excinfo.value) == "bleak is not installed — BLE transport unavailable"


def test_loop_bound_facade_drives_an_async_client_from_sync_code() -> None:
    calls: list[tuple[str, Any]] = []

    class _AsyncClient:
        async def connect(self) -> None:
            calls.append(("connect", None))

        async def start_notify(self, char: str, callback: Callable[..., None]) -> None:
            calls.append(("start_notify", char))
            callback(object(), bytearray(b"hi"))

        async def write_gatt_char(self, char: str, data: bytes) -> None:
            calls.append(("write", (char, bytes(data))))

        async def disconnect(self) -> None:
            calls.append(("disconnect", None))

    loop = asyncio.new_event_loop()
    client = _LoopBoundBleClient(_AsyncClient(), loop, timeout_s=2.0)
    client.connect()
    received: list[bytes] = []
    client.start_notify("rx", lambda _c, data: received.append(bytes(data)))
    client.write_gatt_char("tx", b"\x01")
    client.disconnect()
    assert calls == [
        ("connect", None),
        ("start_notify", "rx"),
        ("write", ("tx", b"\x01")),
        ("disconnect", None),
    ]
    assert received == [b"hi"]
    assert loop.is_closed()  # the loop thread is stopped and the loop released


# --- Bluetooth Classic (RFCOMM) ----------------------------------------------------------


def test_bt_classic_recv_send_timeout_flush_close_over_a_socket() -> None:
    sock = _FakeBtSocket()
    channel = open_bt_classic(
        _bt_binding(), {"timeout_s": 0.02}, socket_factory=lambda address, ch, t: sock
    )
    assert channel.kind is TransportKind.BT_CLASSIC
    assert channel.identity.device_ref == f"bt:{BT_ADDR}"
    assert sock.timeouts == [0.02]  # the I/O timeout from params
    channel.send(Frame(payload=b"\x01\x02"))
    assert sock.sent == [b"\x01\x02"]
    sock.to_read = [b"\xaa\xbb\xcc"]
    got = channel.recv(2)
    assert got is not None and got.payload == b"\xaa\xbb"
    assert channel.recv() is None  # socket timeout → silence
    sock.to_read = [b""]
    assert channel.recv() is None  # a closed peer reads as silence too
    sock.to_read = [b"stale", b"stale"]
    channel.flush_input()
    assert sock.to_read == [] and sock.timeouts[-2:] == [0.0, 0.02]
    channel.close()
    assert sock.closed


def test_open_bt_classic_defaults_and_bounds() -> None:
    seen: list[tuple[str, int, float]] = []

    def factory(address: str, channel: int, connect_timeout_s: float) -> _FakeBtSocket:
        seen.append((address, channel, connect_timeout_s))
        return _FakeBtSocket()

    channel = open_bt_classic(_bt_binding(), {}, socket_factory=factory)
    assert seen == [(BT_ADDR, DEFAULT_RFCOMM_CHANNEL, 10.0)] and DEFAULT_RFCOMM_CHANNEL == 1
    assert channel.params == {
        "channel": 1,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "connect_timeout_s": 10.0,
    }
    assert isinstance(channel, BtClassicChannel)
    for bad in ({"channel": 0}, {"channel": 99}, {"timeout_s": -1}):
        with pytest.raises(ValueError):
            open_bt_classic(_bt_binding(), bad, socket_factory=factory)


def test_open_bt_classic_without_bluetooth_sockets_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(socket, "AF_BLUETOOTH", raising=False)
    with pytest.raises(TransportUnavailableError) as excinfo:
        open_bt_classic(_bt_binding(), {})
    assert "BT Classic transport unavailable" in str(excinfo.value)


# --- registry ----------------------------------------------------------------------------


def test_register_bluetooth_registers_both_kinds_through_the_factories() -> None:
    registry = TransportRegistry()
    register_bluetooth(
        registry,
        client_factory=lambda address, p: _FakeBleClient(),
        socket_factory=lambda address, ch, t: _FakeBtSocket(),
    )
    assert set(registry.kinds()) == {TransportKind.BLE, TransportKind.BT_CLASSIC}
    assert isinstance(registry.open(_ble_binding(), BLE_PARAMS), BleChannel)
    assert isinstance(registry.open(_bt_binding(), {}), BtClassicChannel)
    with pytest.raises(TransportUnavailableError):  # a factory failure surfaces as unavailable
        registry.open(_ble_binding(), {})


def test_bluetooth_module_names_no_vendor() -> None:
    import re
    from pathlib import Path

    import livebench.hardware.bluetooth as module

    source = Path(module.__file__).read_text().lower()
    vendors = r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink|nordic|myactuator)\b"
    assert re.search(vendors, source) is None
    assert re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", source) is None  # no baked-in service UUIDs
