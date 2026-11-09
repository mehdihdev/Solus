"""A Channel over recorded frames: how a MAVLink capture, a CAN capture or a raw serial dump
opens through the SAME transport → driver path as live hardware (Phase 6 (a))."""

import json
from pathlib import Path
from typing import Any

import pytest
from livebench.hardware.channel import Frame
from livebench.hardware.replay import (
    MAX_RECORDED_FRAMES,
    QUIET_READ_SECONDS,
    RecordedFrame,
    ReplayChannel,
    load_recording,
    replay_opener,
)
from solus_api.hardware.config import TransportBinding, TransportKind


def _identity() -> TransportBinding:
    return TransportBinding(kind=TransportKind.USB_CAN, binding="REC-1")


def test_recv_returns_frames_in_order_then_silence() -> None:
    frames = [
        RecordedFrame(at_s=0.0, payload=b"\x01", address="0x201"),
        RecordedFrame(at_s=0.1, payload=b"\x02", address="0x202"),
    ]
    channel = ReplayChannel(TransportKind.USB_CAN, _identity(), frames)
    assert channel.kind is TransportKind.USB_CAN
    first = channel.recv()
    second = channel.recv()
    assert first == Frame(payload=b"\x01", address="0x201")
    assert second == Frame(payload=b"\x02", address="0x202")
    assert channel.recv() is None
    channel.close()
    assert channel.closed


def test_byte_stream_frames_split_to_the_requested_size() -> None:
    frames = [RecordedFrame(at_s=0.0, payload=b"abcdef")]
    channel = ReplayChannel(TransportKind.USB_SERIAL, _identity(), frames)
    assert channel.recv(4) == Frame(payload=b"abcd")
    assert channel.recv(4) == Frame(payload=b"ef")
    assert channel.recv(4) is None


def test_sent_frames_are_kept_for_assertions_and_flush_is_harmless() -> None:
    channel = ReplayChannel(TransportKind.USB_SERIAL, _identity(), [])
    channel.send(Frame(payload=b"ping"))
    channel.flush_input()
    assert channel.sent == [Frame(payload=b"ping")]


def test_realtime_replay_waits_for_the_recorded_gap() -> None:
    slept: list[float] = []
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    frames = [
        RecordedFrame(at_s=0.0, payload=b"a"),
        RecordedFrame(at_s=0.5, payload=b"b"),
    ]
    channel = ReplayChannel(
        TransportKind.USB_SERIAL, _identity(), frames, realtime=True, clock=clock, sleep=sleep
    )
    channel.recv()
    channel.recv()
    assert slept == pytest.approx([0.5])


@pytest.mark.parametrize("realtime", [True, False], ids=["paced", "fast"])
def test_a_replay_that_has_ended_waits_like_a_quiet_link_in_either_mode(realtime: bool) -> None:
    """A live link with nothing to say blocks for its read timeout; a replay that has ended does
    the same, paced or fast, so the pump that polls it idles instead of spinning on a thread hop
    (a fast replay that answered silence at once cost a pump 0.8 of a core, SOLUSDEV-321)."""
    slept: list[float] = []
    frames = [RecordedFrame(at_s=0.0, payload=b"a")]
    channel = ReplayChannel(
        TransportKind.USB_SERIAL,
        _identity(),
        frames,
        realtime=realtime,
        clock=lambda: 0.0,
        sleep=slept.append,
    )

    assert channel.recv() == Frame(payload=b"a")
    assert slept == []  # a frame is handed over at once; the first is due when the replay starts
    assert channel.recv() is None and channel.recv() is None

    assert slept == [QUIET_READ_SECONDS, QUIET_READ_SECONDS]


def test_load_recording_is_unbounded_without_a_cap_and_exact_at_one(tmp_path: Path) -> None:
    text = json.dumps({"transport": "usb_serial", "binding": "X", "frames": []})
    path = tmp_path / "capture.json"
    path.write_text(text)

    assert load_recording(path).frames == []
    assert load_recording(path, max_bytes=len(text)).frames == []
    with pytest.raises(ValueError, match="at most"):
        load_recording(path, max_bytes=len(text) - 1)


def test_load_recording_reads_once_and_only_one_byte_past_its_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file grown past the cap after it was checked is refused without being read whole, and
    the refusal names no path."""
    path = tmp_path / "secret-place.json"
    path.write_bytes(b" " * 10_000 + b'{"transport": "usb_serial", "binding": "X", "frames": []}')
    sizes: list[int] = []
    real_open = Path.open

    class Counted:
        def __init__(self, handle: Any) -> None:
            self._handle = handle

        def read(self, size: int = -1) -> bytes:
            sizes.append(size)
            data: bytes = self._handle.read(size)
            return data

        def __enter__(self) -> "Counted":
            return self

        def __exit__(self, *exc: object) -> None:
            self._handle.close()

    monkeypatch.setattr(Path, "open", lambda self, *a, **k: Counted(real_open(self, *a, **k)))

    with pytest.raises(ValueError, match="at most 4096 bytes") as refused:
        load_recording(path, max_bytes=4096)

    assert sizes == [4097]
    assert "secret-place" not in str(refused.value) and str(tmp_path) not in str(refused.value)


def test_load_recording_reads_hex_frames_and_bounds_them(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    path.write_text(
        json.dumps(
            {
                "transport": "usb_can",
                "binding": "REC-1",
                "frames": [
                    {"t": 0.0, "hex": "0102", "address": "0x201"},
                    {"t": 0.25, "hex": "ff"},
                ],
            }
        )
    )
    recording = load_recording(path)
    assert recording.identity.device_ref == "can:REC-1"
    assert recording.frames == [
        RecordedFrame(at_s=0.0, payload=b"\x01\x02", address="0x201"),
        RecordedFrame(at_s=0.25, payload=b"\xff", address=None),
    ]
    too_many = {
        "transport": "usb_serial",
        "binding": "X",
        "frames": [{"t": 0, "hex": "00"}] * (MAX_RECORDED_FRAMES + 1),
    }
    path.write_text(json.dumps(too_many))
    with pytest.raises(ValueError):
        load_recording(path)
    path.write_text(
        json.dumps({"transport": "usb_serial", "binding": "X", "frames": [{"t": 0, "hex": "zz"}]})
    )
    with pytest.raises(ValueError):
        load_recording(path)


def test_replay_opener_registers_as_the_recorded_transport(tmp_path: Path) -> None:
    from livebench.hardware.channel import TransportRegistry

    path = tmp_path / "capture.json"
    path.write_text(
        json.dumps({"transport": "wifi", "binding": "aa:bb", "frames": [{"t": 0, "hex": "fd"}]})
    )
    recording = load_recording(path)
    registry = TransportRegistry()
    registry.register(TransportKind.WIFI, replay_opener(recording))
    channel = registry.open(recording.identity, {})
    assert channel.identity.device_ref == "ip:aa:bb"
    got = channel.recv()
    assert got is not None and got.payload == b"\xfd"
