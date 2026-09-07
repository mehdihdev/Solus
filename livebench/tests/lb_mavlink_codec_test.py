"""Hand-rolled MAVLink v2 framing: X25 CRC with crc_extra, trailing-zero truncation and the
zero-padding decode, and a parser that treats device bytes as untrusted — junk, a bad checksum
or an unknown id cost a frame, never the stream, and the buffer is bounded."""

import json
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from livebench.plugins.mavlink.mavlink_codec import (
    MAX_BUFFER_BYTES,
    MavlinkMessage,
    MavlinkParser,
    crc_x25,
    encode_mavlink,
)
from livebench.plugins.mavlink.mavlink_definitions import (
    ATTITUDE,
    HEARTBEAT,
    MESSAGES,
    SERVO_OUTPUT_RAW,
    MavlinkMessageDef,
)

HEARTBEAT_FIELDS = {
    "custom_mode": 0x00030000,
    "type": 2,
    "autopilot": 12,
    "base_mode": 0x81,
    "system_status": 4,
    "mavlink_version": 3,
}
SERVO_FIELDS = {"time_usec": 1_000_000, "servo1_raw": 1100, "servo4_raw": 1900}


def test_crc_x25_matches_the_crc16_mcrf4xx_check_value() -> None:
    assert crc_x25(b"123456789") == 0x6F91
    assert crc_x25(b"") == 0xFFFF
    assert crc_x25(b"123456789", 50) != crc_x25(b"123456789", 39)  # crc_extra is accumulated


def test_encode_decode_round_trip_for_every_definition() -> None:
    frames = [
        encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=7, system_id=1, component_id=1),
        encode_mavlink(ATTITUDE, {"time_boot_ms": 12, "roll": 0.5}, seq=8, system_id=1),
        encode_mavlink(SERVO_OUTPUT_RAW, SERVO_FIELDS, seq=9, system_id=1),
    ]
    messages = MavlinkParser().feed(b"".join(frames))
    assert [m.msg_id for m in messages] == [0, 30, 36]
    heartbeat, attitude, servo = messages
    assert heartbeat == MavlinkMessage(
        msg_id=0, seq=7, system_id=1, component_id=1, fields=HEARTBEAT_FIELDS
    )
    assert attitude.fields["roll"] == 0.5 and attitude.fields["yawspeed"] == 0.0
    assert servo.fields["servo1_raw"] == 1100 and servo.fields["servo16_raw"] == 0


def test_v2_truncates_trailing_zeros_and_the_decoder_pads_them_back() -> None:
    frame = encode_mavlink(SERVO_OUTPUT_RAW, SERVO_FIELDS, seq=0, system_id=1)
    assert frame[1] == 4 + 4 * 2  # payload ends at servo4; port and servo5..16 are truncated
    assert frame[0] == 0xFD and len(frame) == 10 + frame[1] + 2
    (servo,) = MavlinkParser().feed(frame)
    assert servo.fields["port"] == 0 and servo.fields["servo9_raw"] == 0
    empty = encode_mavlink(ATTITUDE, {}, seq=0, system_id=1)
    assert empty[1] == 1  # a payload is never truncated to nothing


def test_a_mutated_byte_is_rejected_and_the_next_frame_still_decodes() -> None:
    good = encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=1, system_id=1)
    corrupt = bytearray(good)
    corrupt[12] ^= 0x10  # a payload byte
    messages = MavlinkParser().feed(bytes(corrupt) + good)
    assert [m.seq for m in messages] == [1]
    assert MavlinkParser().feed(good[:-1] + bytes([good[-1] ^ 1])) == []  # crc byte itself


def test_parser_resyncs_on_junk_and_across_split_frames() -> None:
    good = encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=3, system_id=1)
    parser = MavlinkParser()
    assert parser.feed(b"junk\x00" + good[:5]) == []  # noise, then the head of a frame
    assert [m.seq for m in parser.feed(good[5:])] == [3]
    assert parser.feed(b"\x00" * 3) == []
    # A stray STX that claims a known id fails its checksum and costs exactly one byte.
    stray = b"\xfd" + b"\x00" * 9
    assert [m.seq for m in MavlinkParser().feed(stray + good)] == [3]


def test_unknown_message_ids_are_skipped_by_their_declared_length() -> None:
    unknown = MavlinkMessageDef(msg_id=999, name="X", crc_extra=1, fields=(("a", "I"),))
    frame = encode_mavlink(unknown, {"a": 0xFD}, seq=0, system_id=1)  # an STX inside its payload
    good = encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=4, system_id=1)
    assert [m.seq for m in MavlinkParser().feed(frame + good)] == [4]
    assert 999 not in MESSAGES


def test_signed_frames_are_skipped_whole_and_the_buffer_is_bounded() -> None:
    parser = MavlinkParser()
    signed = bytearray(encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=5, system_id=1))
    signed[2] = 0x01  # incompat_flags: signed → 13 more bytes we do not verify
    good = encode_mavlink(HEARTBEAT, HEARTBEAT_FIELDS, seq=6, system_id=1)
    assert [m.seq for m in parser.feed(bytes(signed) + b"\x00" * 13 + good)] == [6]
    assert parser.feed(b"\xfd" + b"\xff" * (3 * MAX_BUFFER_BYTES)) == []
    assert parser.buffered <= MAX_BUFFER_BYTES
    assert [m.seq for m in parser.feed(good)] == [6]


def test_a_longer_dialect_payload_is_read_up_to_the_known_length() -> None:
    longer = MavlinkMessageDef(
        msg_id=0, name="HEARTBEAT", crc_extra=50, fields=(*HEARTBEAT.fields, ("extra", "I"))
    )
    frame = encode_mavlink(longer, {**HEARTBEAT_FIELDS, "extra": 0x01010101}, seq=0, system_id=1)
    assert frame[1] == HEARTBEAT.length + struct.calcsize("I")
    (message,) = MavlinkParser().feed(frame)
    assert message.fields == HEARTBEAT_FIELDS


# --- The recorded PX4 quadrotor fixture: generated here, deterministically, by the encoder. ---

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mavlink_px4_quadrotor.json"
_PEER = "192.168.4.1:14550"
_ROLL_CYCLE = (0.0, 0.1, 0.2, 0.1, 0.0, -0.1, -0.2, -0.1)  # a slow triangle roll, period 0.8 s
_ROLL_RATE = (1.0, 1.0, -1.0, -1.0, -1.0, -1.0, 1.0, 1.0)
_SERVO_BASE_US = (1100, 1400, 1600, 1900)


def _mavlink_fixture() -> dict[str, Any]:
    """~3 s at 10 Hz: HEARTBEAT (PX4, quadrotor) at 1 Hz, ATTITUDE and SERVO_OUTPUT_RAW at 10 Hz,
    one datagram per message, from a single peer."""
    frames: list[dict[str, Any]] = []
    seq = 0

    def emit(t: float, defn: MavlinkMessageDef, fields: Mapping[str, int | float]) -> None:
        nonlocal seq
        frame = encode_mavlink(defn, fields, seq=seq, system_id=1, component_id=1)
        frames.append({"t": round(t, 1), "hex": frame.hex(), "address": _PEER})
        seq += 1

    for i in range(30):
        t = i / 10
        if i % 10 == 0:
            emit(t, HEARTBEAT, HEARTBEAT_FIELDS)
        boot_ms = 100_000 + i * 100
        emit(
            t,
            ATTITUDE,
            {
                "time_boot_ms": boot_ms,
                "roll": _ROLL_CYCLE[i % 8],
                "pitch": 0.0,
                "yaw": 1.5,
                "rollspeed": _ROLL_RATE[i % 8],
            },
        )
        emit(
            t,
            SERVO_OUTPUT_RAW,
            {
                "time_usec": boot_ms * 1000,
                **{
                    f"servo{n}_raw": base + 10 * (i % 5) for n, base in enumerate(_SERVO_BASE_US, 1)
                },
            },
        )
    return {"transport": "wifi", "binding": "aa:bb:cc:dd:ee:ff", "frames": frames}


def test_golden_bytes_of_the_first_heartbeat_frame() -> None:
    # STX · len 9 · flags 0 0 · seq 0 · sys 1 · comp 1 · msgid 0 · custom_mode 0x30000 LE ·
    # type 2 · autopilot 12 · base_mode 0x81 · status 4 · version 3 · crc 0x06B3 LE
    golden = "fd09000000010100000000000300020c810403b306"
    assert _mavlink_fixture()["frames"][0]["hex"] == golden
    (heartbeat,) = MavlinkParser().feed(bytes.fromhex(golden))
    assert heartbeat.fields == HEARTBEAT_FIELDS and heartbeat.system_id == 1


def test_fixture_on_disk_matches_the_generator() -> None:
    assert json.loads(FIXTURE_PATH.read_text()) == _mavlink_fixture()


if __name__ == "__main__":  # regenerate: uv run --no-sync python <this file>
    FIXTURE_PATH.write_text(json.dumps(_mavlink_fixture(), indent=1) + "\n")
