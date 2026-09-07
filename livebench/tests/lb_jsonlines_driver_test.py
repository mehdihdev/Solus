"""JSON-lines driver: any JSON object per line, flattened; the device_ref is always the identity
(a line asserting another device_id is dropped — the bridged-transport spoofing guard)."""

import uuid

from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.hardware.replay import RecordedFrame, ReplayChannel
from livebench.plugins import load_all
from livebench.plugins.jsonlines.jsonlines_driver import JsonLinesDriver
from livebench.telemetry.stream_live import PacketSource
from solus_api.graph.codec import encode_json
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    HardwareConfig,
    ProtocolBinding,
    TransportBinding,
    TransportKind,
)

REF = "bt:AA-BB-CC"


def _config(**params: object) -> HardwareConfig:
    return HardwareConfig(
        robot_entity_id=uuid.uuid4(),
        identity=TransportBinding(kind=TransportKind.BT_CLASSIC, binding="AA-BB-CC"),
        protocol=ProtocolBinding(driver_id="json-lines", params=params),  # type: ignore[arg-type]
        provenance={"identity": {"by": "detected"}, "protocol": {"by": "user"}},  # type: ignore[dict-item]
    )


def _replay(*lines: bytes) -> ReplayChannel:
    identity = TransportBinding(kind=TransportKind.BT_CLASSIC, binding="AA-BB-CC")
    frames = [RecordedFrame(at_s=i * 0.01, payload=line) for i, line in enumerate(lines)]
    return ReplayChannel(TransportKind.BT_CLASSIC, identity, frames)


async def _take(source: PacketSource, count: int) -> list[TelemetryPacket]:
    out: list[TelemetryPacket] = []
    async for packet in source:
        out.append(packet)
        if len(out) == count:
            break
    await source.aclose()
    return out


def test_register_adds_the_driver() -> None:
    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    load_all(registries, modules=("livebench.plugins.jsonlines",))
    driver = registries.drivers.get("json-lines")
    assert driver.display_name == "JSON lines"
    assert TransportKind.BT_CLASSIC in driver.transports


async def test_lines_flatten_to_the_device_ref_with_arrival_time() -> None:
    registry = DriverRegistry()
    registry.register(JsonLinesDriver)
    channel = _replay(
        b'{"imu": {"ax": 0.5, "ay": -0.25}, "mode": "run", "ok": true}\n',
        b"garbage\n",
        b'{"volt": 12.1}\n',
    )
    packets = await _take(registry.open_source(_config(baud=9600), channel), 2)
    assert [p.device_id for p in packets] == [REF, REF]
    # strings and bools are not signals
    assert packets[0].values == {"imu.ax": 0.5, "imu.ay": -0.25}
    assert packets[1].values == {"volt": 12.1}
    assert packets[0].timestamp.tzinfo is not None and packets[0].seq is None


async def test_an_lb06_line_claiming_another_identity_is_dropped_but_its_own_decodes() -> None:
    from datetime import UTC, datetime

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    own = TelemetryPacket(device_id=REF, timestamp=t0, values={"a": 1.0}, seq=7)
    other = TelemetryPacket(device_id="usb:OTHER", timestamp=t0, values={"a": 9.0}, seq=8)
    channel = _replay(
        encode_json(other).encode() + b"\n",
        encode_json(own).encode() + b"\n",
        b'{"b": 2}\n',
    )
    driver = JsonLinesDriver()
    packets = await _take(driver.open(channel, driver.params_model(), _config()), 2)
    assert [(p.device_id, p.seq) for p in packets] == [(REF, 7), (REF, None)]
