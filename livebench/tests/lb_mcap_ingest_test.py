"""CON-03: MCAP ingest — json-encoded channels → LB-06 packets."""

import io
import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from livebench.telemetry.mcap_ingest import read_packets
from mcap.writer import Writer
from solus_api.graph.codec import to_wire
from solus_api.graph.packet import TelemetryPacket

McapMessage = tuple[str, str, int, bytes]  # (topic, message_encoding, log_time_ns, payload)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T0_NS = 1_767_225_600 * 1_000_000_000

BuildMcap = Callable[[list[McapMessage]], io.BytesIO]


# Local fixture (was livebench/tests/conftest.py — removed: a second same-named
# conftest collided with packages/api/tests/conftest.py under the merged mypy config).
@pytest.fixture
def build_mcap() -> BuildMcap:
    def _build(messages: list[McapMessage]) -> io.BytesIO:
        buf = io.BytesIO()
        writer = Writer(buf)
        writer.start()
        channel_ids: dict[tuple[str, str], int] = {}
        for topic, encoding, log_time, payload in messages:
            key = (topic, encoding)
            if key not in channel_ids:
                schema_id = writer.register_schema(name=topic, encoding="jsonschema", data=b"{}")
                channel_ids[key] = writer.register_channel(
                    topic=topic, message_encoding=encoding, schema_id=schema_id
                )
            writer.add_message(
                channel_id=channel_ids[key], log_time=log_time, publish_time=log_time, data=payload
            )
        writer.finish()
        buf.seek(0)
        return buf

    return _build


def test_reads_json_channels_in_log_time_order(build_mcap: BuildMcap) -> None:
    buf = build_mcap(
        [
            ("/imu", "json", T0_NS, b'{"ax": 0.1}'),
            ("/joints", "json", T0_NS + 500, b'{"elbow": 1.57}'),
        ]
    )

    packets = list(read_packets(buf))

    assert [p.device_id for p in packets] == ["/imu", "/joints"]
    assert packets[0].values == {"ax": 0.1}
    assert packets[1].values == {"elbow": 1.57}


def test_non_json_channels_are_skipped(build_mcap: BuildMcap) -> None:
    buf = build_mcap(
        [
            ("/proto", "protobuf", T0_NS, b"\x01\x02"),
            ("/ok", "json", T0_NS, b'{"v": 1.0}'),
        ]
    )

    packets = list(read_packets(buf))

    assert [p.device_id for p in packets] == ["/ok"]


def test_malformed_message_is_skipped_stream_survives(build_mcap: BuildMcap) -> None:
    buf = build_mcap(
        [
            ("/bad", "json", T0_NS, b"{broken"),
            ("/ok", "json", T0_NS + 1, b'{"v": 2.0}'),
        ]
    )

    packets = list(read_packets(buf))

    assert [p.device_id for p in packets] == ["/ok"]


def test_topic_filter(build_mcap: BuildMcap) -> None:
    buf = build_mcap(
        [
            ("/keep", "json", T0_NS, b'{"v": 1.0}'),
            ("/drop", "json", T0_NS + 1, b'{"v": 2.0}'),
        ]
    )

    packets = list(read_packets(buf, topics=["/keep"]))

    assert [p.device_id for p in packets] == ["/keep"]


def test_lb06_wire_messages_pass_through_with_seq_and_units(build_mcap: BuildMcap) -> None:
    original = TelemetryPacket(
        device_id="motor-1",
        timestamp=T0,
        values={"rpm": 900.0},
        seq=7,
        units={"rpm": "1/min"},
    )
    payload = json.dumps(to_wire(original)).encode()
    buf = build_mcap([("motor-1", "json", T0_NS, payload)])

    packets = list(read_packets(buf))

    assert packets == [original]


def test_validation_level_poison_mid_file_does_not_abort_ingest(build_mcap: BuildMcap) -> None:
    # Security C1: not just JSON syntax errors — a payload that parses but fails
    # packet validation (empty key) must also be skipped, not abort the file.
    buf = build_mcap(
        [
            ("/a", "json", T0_NS, b'{"v": 1.0}'),
            ("/poison", "json", T0_NS + 1, b'{"": 1.0}'),
            ("/b", "json", T0_NS + 2, b'{"v": 2.0}'),
        ]
    )

    packets = list(read_packets(buf))

    assert [p.device_id for p in packets] == ["/a", "/b"]


def test_non_seekable_stream_is_rejected(build_mcap: BuildMcap) -> None:
    # Security C2: a non-seekable stream forces the mcap library to buffer the
    # whole file in memory for log-time ordering. Refuse it loudly.
    import pytest as _pytest

    buf = build_mcap([("/a", "json", T0_NS, b'{"v": 1.0}')])

    class NonSeekable:
        def read(self, n: int = -1) -> bytes:
            return buf.read(n)

        def seekable(self) -> bool:
            return False

    with _pytest.raises(ValueError, match="seekable"):
        list(read_packets(NonSeekable()))  # type: ignore[arg-type]


def test_oversized_file_is_rejected(build_mcap: BuildMcap, monkeypatch: object) -> None:
    import pytest as _pytest

    buf = build_mcap([("/a", "json", T0_NS, b'{"v": 1.0}')])

    with _pytest.raises(ValueError, match="exceeds"):
        list(read_packets(buf, max_bytes=10))
