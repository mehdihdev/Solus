"""The line reader the three line-based drivers and the framing interrogator share: newline
framing over any Channel, bounded (an over-long line is discarded, never buffered) and
junk-tolerant."""

from pathlib import Path

import pytest
from livebench.hardware.replay import RecordedFrame, ReplayChannel, load_recording
from livebench.plugins.lb06.lb06_lines import (
    MAX_LINE_BYTES,
    LineReader,
    LineTransportParams,
)
from pydantic import ValidationError
from solus_api.graph.codec import MAX_PACKET_BYTES
from solus_api.hardware.config import TransportBinding, TransportKind

FIXTURES = Path(__file__).with_name("fixtures")


def _replay(*chunks: bytes) -> ReplayChannel:
    identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="ABC")
    frames = [RecordedFrame(at_s=i * 0.01, payload=c) for i, c in enumerate(chunks)]
    return ReplayChannel(TransportKind.USB_SERIAL, identity, frames)


def test_reassembles_lines_split_across_frames_and_splits_merged_ones() -> None:
    reader = LineReader(_replay(b"ab", b"c\r\nde", b"f\n\n  \ng\nh"))
    assert reader.read_line() == b"abc"
    assert reader.read_line() == b"def"
    assert reader.read_line() == b"g"  # blank and whitespace-only lines are skipped
    assert reader.read_line() is None  # "h" has no newline yet: silence, not a line


def test_over_long_line_is_discarded_to_the_next_newline_never_buffered() -> None:
    reader = LineReader(_replay(b"x" * 6, b"x" * 6, b"xx\nok\n"), max_line_bytes=8)
    assert reader.read_line() == b"ok"
    assert MAX_LINE_BYTES == MAX_PACKET_BYTES + 1024


def test_silence_returns_none_and_the_stream_resumes_after_it() -> None:
    identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="ABC")
    channel = ReplayChannel(TransportKind.USB_SERIAL, identity, [])
    reader = LineReader(channel)
    assert reader.read_line() is None
    channel._frames.append(RecordedFrame(at_s=0.0, payload=b"late\n"))
    assert reader.read_line() == b"late"


def test_the_arduino_fixture_reassembles_into_one_hundred_six_column_lines() -> None:
    recording = load_recording(FIXTURES / "serial_arduino_rover.json")
    assert len(recording.frames) != 100  # split and merged frames prove reassembly
    channel = ReplayChannel(TransportKind.USB_SERIAL, recording.identity, recording.frames)
    reader = LineReader(channel)
    lines = []
    while (line := reader.read_line()) is not None:
        lines.append(line)
    assert len(lines) == 100
    assert all(len(line.split(b",")) == 6 for line in lines)


def test_line_transport_params_are_bounded_and_refuse_unknown_keys() -> None:
    params = LineTransportParams.model_validate({"baud": 115200, "timeout_s": 0.05})
    assert params.baud == 115200 and params.timeout_s == 0.05
    assert LineTransportParams().baud is None
    with pytest.raises(ValidationError):
        LineTransportParams.model_validate({"baud": 10})
    with pytest.raises(ValidationError):
        LineTransportParams.model_validate({"timeout_s": 60})
    with pytest.raises(ValidationError):
        LineTransportParams.model_validate({"servo_id": 1})
