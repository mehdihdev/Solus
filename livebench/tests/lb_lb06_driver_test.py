"""LB-06 lines driver: a Solus-flashed board's JSON lines through the transport → driver path,
identity pinned to the channel's device_ref so the pin survives a reconnect."""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

from livebench.hardware.channel import Channel, Frame, TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.hardware.replay import RecordedFrame, ReplayChannel, load_recording
from livebench.plugins import load_all
from livebench.plugins.lb06.lb06_driver import Lb06Driver, Lb06Source
from livebench.telemetry.reconnect import ReconnectingSource
from livebench.telemetry.stream_live import PacketSource
from solus_api.graph.codec import encode_json
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    HardwareConfig,
    ProtocolBinding,
    TransportBinding,
    TransportKind,
)

FIXTURES = Path(__file__).with_name("fixtures")
BINDING = "ARDUINO-NANO-7F31"
REF = f"usb:{BINDING}"


def _identity(binding: str = BINDING) -> TransportBinding:
    return TransportBinding(kind=TransportKind.USB_SERIAL, binding=binding)


def _config(driver_id: str = "lb06", **params: object) -> HardwareConfig:
    return HardwareConfig(
        robot_entity_id=uuid.uuid4(),
        identity=_identity(),
        protocol=ProtocolBinding(driver_id=driver_id, params=params),  # type: ignore[arg-type]
        provenance={"identity": {"by": "detected"}, "protocol": {"by": "user"}},  # type: ignore[dict-item]
    )


def _replay(*lines: bytes, binding: str = BINDING) -> ReplayChannel:
    frames = [RecordedFrame(at_s=i * 0.01, payload=line) for i, line in enumerate(lines)]
    return ReplayChannel(TransportKind.USB_SERIAL, _identity(binding), frames)


def _wire(device_id: str, seq: int, **values: float) -> bytes:
    from datetime import UTC, datetime

    packet = TelemetryPacket(
        device_id=device_id, timestamp=datetime(2026, 1, 1, tzinfo=UTC), values=values, seq=seq
    )
    return encode_json(packet).encode() + b"\n"


async def _take(source: PacketSource, count: int) -> list[TelemetryPacket]:
    out: list[TelemetryPacket] = []
    async for packet in source:
        out.append(packet)
        if len(out) == count:
            break
    await source.aclose()
    return out


def test_register_adds_the_driver_and_the_framing_interrogator() -> None:
    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    assert load_all(registries, modules=("livebench.plugins.lb06",)) == ["livebench.plugins.lb06"]
    driver = registries.drivers.get("lb06")
    assert driver.display_name == "Solus telemetry (LB-06 lines)"
    assert driver.transports == {
        TransportKind.USB_SERIAL,
        TransportKind.BT_CLASSIC,
        TransportKind.BLE,
    }
    assert registries.interrogators.get("serial-framing").safety == "listen"


async def test_the_fixture_decodes_through_the_registry_with_wire_time_seq_and_units() -> None:
    registry = DriverRegistry()
    registry.register(Lb06Driver)
    recording = load_recording(FIXTURES / "serial_lb06_lines.json")
    channel = ReplayChannel(TransportKind.USB_SERIAL, recording.identity, recording.frames)
    source = registry.open_source(_config(baud=115200, timeout_s=0.1), channel)
    packets = await _take(source, 100)
    assert {p.device_id for p in packets} == {REF}
    assert [p.seq for p in packets] == list(range(100))
    assert set(packets[0].values) == {"left.velocity", "right.velocity", "battery.voltage"}
    assert packets[0].units["battery.voltage"] == "V"
    assert packets[1].timestamp - packets[0].timestamp == timedelta(milliseconds=10)
    assert channel.closed and channel.sent == []  # listen-only; aclose closes the channel


async def test_garbage_and_oversized_lines_cost_one_sample_never_the_stream() -> None:
    channel = _replay(
        _wire(REF, 1, a=1.0),
        b"not json at all\n",
        b'{"ts_us": "nope", "device_id": "' + REF.encode() + b'", "values": {"a": 1}}\n',
        b"{" + b"x" * (70 * 1024) + b"}\n",
        _wire(REF, 2, a=2.0),
    )
    packets = await _take(Lb06Driver().open(channel, Lb06Driver.params_model(), _config()), 2)
    assert [p.seq for p in packets] == [1, 2]


async def test_first_identity_wins_when_no_pin_is_given_and_a_relabel_is_dropped() -> None:
    channel = _replay(
        _wire("motor-1", 1, rpm=1.0), _wire("bms-main", 2, volts=48.0), _wire("motor-1", 3, rpm=2.0)
    )
    packets = await _take(Lb06Source(channel), 2)
    assert [(p.device_id, p.seq) for p in packets] == [("motor-1", 1), ("motor-1", 3)]


class _DroppingChannel:
    """A replay whose link dies after its frames: the reconnect loop must reopen it."""

    kind = TransportKind.USB_SERIAL

    def __init__(self, inner: ReplayChannel) -> None:
        self._inner = inner
        self.identity = inner.identity

    def send(self, frame: Frame) -> None:
        self._inner.send(frame)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        frame = self._inner.recv(max_bytes)
        if frame is None:
            raise OSError("link dropped")
        return frame

    def flush_input(self) -> None: ...

    def close(self) -> None:
        self._inner.close()


async def test_the_pin_is_the_device_ref_so_a_reconnect_cannot_relabel_the_stream() -> None:
    incarnations: list[Channel] = [
        _DroppingChannel(_replay(_wire(REF, 1, a=1.0))),
        _DroppingChannel(_replay(_wire("impostor", 2, a=9.0), _wire(REF, 3, a=3.0))),
    ]
    driver = Lb06Driver()

    def factory() -> PacketSource:
        return driver.open(incarnations.pop(0), Lb06Driver.params_model(), _config())

    async def no_sleep(_: float) -> None:
        return None

    packets = await _take(ReconnectingSource(factory, sleep=no_sleep), 2)
    assert [(p.device_id, p.seq) for p in packets] == [(REF, 1), (REF, 3)]


async def test_a_link_error_propagates_so_the_reconnect_loop_can_heal_it() -> None:
    source = Lb06Source(_DroppingChannel(_replay(_wire(REF, 1, a=1.0))))
    seen: list[int | None] = []
    try:
        async for packet in source:
            seen.append(packet.seq)
    except OSError:
        pass
    assert seen == [1]


async def test_aiter_protocol_shape() -> None:
    source: PacketSource = Lb06Source(_replay(_wire(REF, 1, a=1.0)))
    iterator: AsyncIterator[TelemetryPacket] = source.__aiter__()
    assert (await iterator.__anext__()).seq == 1
    await source.aclose()
