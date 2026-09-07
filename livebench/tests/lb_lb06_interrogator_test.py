"""The framing interrogator: listen for the budget, characterize the stream through the shared
`characterize_stream`, and propose the line driver that speaks it — at shape confidence only."""

import re
from pathlib import Path

import pytest
from livebench.hardware.interrogator import Interrogation, InterrogatorRegistry, Safety
from livebench.hardware.replay import RecordedFrame, ReplayChannel, load_recording
from livebench.plugins.lb06.lb06_interrogator import SerialFramingInterrogator
from solus_api.fingerprint.contract import Modality
from solus_api.hardware.config import TransportBinding, TransportKind

FIXTURES = Path(__file__).with_name("fixtures")
PLUGINS = Path(__file__).parents[1] / "src" / "livebench" / "plugins"
VENDOR_WORDS = re.compile(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b")


class _Clock:
    """Advances a hair on every read and jumps on sleep, so a realtime replay and the
    interrogator's arrival stamps share one deterministic timeline."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1e-5
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _channel(
    frames: list[RecordedFrame], clock: _Clock, *, params: dict[str, object] | None = None
) -> ReplayChannel:
    identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="ARDUINO-NANO-7F31")
    channel = ReplayChannel(
        TransportKind.USB_SERIAL, identity, frames, realtime=True, clock=clock, sleep=clock.sleep
    )
    if params is not None:
        channel.params = params  # type: ignore[attr-defined]
    return channel


def _lines(*lines: bytes) -> list[RecordedFrame]:
    return [RecordedFrame(at_s=i * 0.01, payload=line) for i, line in enumerate(lines)]


def _probe(frames: list[RecordedFrame], **params: object) -> Interrogation | None:
    clock = _Clock()
    channel = _channel(frames, clock, params=params or None)
    result = SerialFramingInterrogator(clock=clock).probe(channel, budget_s=0.5)
    assert channel.sent == []  # listen-only: nothing is ever written to the device
    return result


def test_class_attributes_and_registration() -> None:
    registry = InterrogatorRegistry()
    registry.register(SerialFramingInterrogator)
    assert registry.for_transport(TransportKind.BLE)[0].interrogator_id == "serial-framing"
    assert SerialFramingInterrogator.safety is Safety.LISTEN


def test_csv_floats_propose_raw_lines_with_column_addresses_and_an_honest_summary() -> None:
    recording = load_recording(FIXTURES / "serial_arduino_rover.json")
    result = _probe(recording.frames, baud=115200, timeout_s=0.1)
    assert result is not None
    assert result.driver_id == "raw-lines" and result.params == {"baud": 115200}
    assert [(e.protocol, e.address, e.model) for e in result.bus_map] == [
        ("raw-lines", str(i), None) for i in range(6)
    ]
    assert result.details["framing"] == "csv" and result.details["channel_count"] == 6
    assert result.details["update_hz"] == pytest.approx(100.0, rel=0.05)
    assert result.summary == "6 float channels at 100 Hz, no protocol recognised — name them?"
    (evidence,) = result.evidence
    assert evidence.modality is Modality.TELEMETRY_CHANNEL
    assert evidence.confidence <= 0.30 and result.confidence <= 0.30
    assert evidence.source_ref.external_ref == "usb:ARDUINO-NANO-7F31"


def test_lb06_shaped_json_lines_propose_the_lb06_driver_keyed_by_value_names() -> None:
    recording = load_recording(FIXTURES / "serial_lb06_lines.json")
    result = _probe(recording.frames)
    assert result is not None
    assert result.driver_id == "lb06" and result.params == {}  # baud unknown: not invented
    assert sorted(e.address for e in result.bus_map) == [
        "battery.voltage",
        "left.velocity",
        "right.velocity",
    ]
    assert all(e.protocol == "lb06" and e.model is None for e in result.bus_map)
    assert result.details == {
        "framing": "json-lines",
        "channel_count": 3,
        "update_hz": pytest.approx(100.0, rel=0.05),
    }
    assert "LB-06" in result.summary and "3 channels" in result.summary


def test_plain_json_lines_propose_json_lines_with_key_addresses() -> None:
    line = b'{"volts": 12.%d, "amps": 0.5, "mode": "run"}\n'
    frames = _lines(*[line % (i % 10) for i in range(20)])
    result = _probe(frames)
    assert result is not None
    assert result.driver_id == "json-lines"
    assert sorted(e.address for e in result.bus_map) == ["amps", "volts"]  # numeric keys only
    assert result.confidence <= 0.30


@pytest.mark.parametrize(
    "frames",
    [
        [],
        _lines(b"\x00\x01\x82\xff\n", b"\x99\x88\x00\n"),
        _lines(b"boot ok\n", b"hello world\n"),
        [RecordedFrame(at_s=0.0, payload=b"\x00\x01\x82\xff")],  # binary, no newline ever
    ],
)
def test_silence_binary_and_text_are_not_ours(frames: list[RecordedFrame]) -> None:
    assert _probe(frames) is None


def test_a_key_that_is_not_a_valid_bus_address_is_skipped_not_fatal() -> None:
    frames = _lines(*[b'{"ok": 1, "has space": 2, "%s": 3}\n' % (b"k" * 80) for _ in range(10)])
    result = _probe(frames)
    assert result is not None
    assert [e.address for e in result.bus_map] == ["ok"]


def test_the_probe_is_bounded_by_the_budget_not_the_stream() -> None:
    frames = _lines(*[b"1,2,3\n"] * 500)
    clock = _Clock()
    channel = _channel(frames, clock)
    result = SerialFramingInterrogator(clock=clock).probe(channel, budget_s=0.2)
    assert result is not None and channel._index < 100


def test_serial_format_plugins_name_no_vendor() -> None:
    files = [
        path for name in ("lb06", "jsonlines", "raw") for path in (PLUGINS / name).rglob("*.py")
    ]
    assert len(files) >= 8
    for path in files:
        assert VENDOR_WORDS.search(path.read_text().lower()) is None, path
    for path in FIXTURES.glob("serial_*.json"):
        assert VENDOR_WORDS.search(path.read_text().lower()) is None, path
