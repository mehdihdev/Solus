"""CON-03: viz-out — LB-06 packets → Foxglove-consumable MCAP, and the round trip."""

import io
from datetime import UTC, datetime, timedelta

from livebench.telemetry.mcap_export import write_packets
from livebench.telemetry.mcap_ingest import read_packets
from mcap.reader import make_reader
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_export_then_read_round_trips() -> None:
    packets = [
        TelemetryPacket(
            device_id="motor-1",
            timestamp=T0 + timedelta(seconds=i),
            values={"rpm": 100.0 * i},
            seq=i,
        )
        for i in range(1, 4)
    ] + [TelemetryPacket(device_id="imu", timestamp=T0, values={"ax": 0.5}, units={"ax": "m/s^2"})]
    buf = io.BytesIO()

    written = write_packets(buf, packets)
    buf.seek(0)
    read_back = list(read_packets(buf))

    assert written == 4
    assert sorted(read_back, key=lambda p: (p.device_id, p.seq or 0)) == sorted(
        packets, key=lambda p: (p.device_id, p.seq or 0)
    )


def test_export_writes_one_json_channel_per_device() -> None:
    packets = [
        TelemetryPacket(device_id="a", timestamp=T0, values={"v": 1.0}),
        TelemetryPacket(device_id="b", timestamp=T0, values={"v": 2.0}),
        TelemetryPacket(device_id="a", timestamp=T0 + timedelta(seconds=1), values={"v": 3.0}),
    ]
    buf = io.BytesIO()
    write_packets(buf, packets)
    buf.seek(0)

    summary = make_reader(buf).get_summary()
    assert summary is not None
    channels = {c.topic: c.message_encoding for c in summary.channels.values()}

    assert channels == {"a": "json", "b": "json"}


def test_export_of_nothing_writes_a_valid_empty_file() -> None:
    buf = io.BytesIO()

    written = write_packets(buf, [])
    buf.seek(0)

    assert written == 0
    assert list(read_packets(buf)) == []
