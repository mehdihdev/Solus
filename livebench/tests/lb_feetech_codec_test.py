"""Feetech STS/SCS wire codec + half-duplex bus exchange (SOLUSDEV-248 port of SOLUSDEV-73).

Golden frames were captured live from a LeRobot SO-10x arm (CH343 bridge, six STS servos,
1 Mbaud) on 2026-08-16 and are kept VERBATIM. `FeetechFakeChannel` is the scripted bus every
Feetech test drives: silent until asked, answers per servo id, behind the `Channel` seam.
"""

import re
from pathlib import Path

from livebench.hardware.channel import Frame, as_bus_port
from livebench.plugins.feetech.feetech_codec import FeetechBus, FeetechCodec, FeetechServo
from livebench.plugins.feetech.feetech_definitions import (
    CONTROL_TABLE_BY_PROTOCOL,
    FEETECH_BAUDS,
    FEETECH_MODELS,
    FEETECH_RESOLUTION,
    STS_CONTROL_TABLE,
)
from solus_api.hardware.config import TransportBinding, TransportKind

_PING, _READ = 0x01, 0x02
_REG_MODEL, _REG_POSITION, _REG_LOAD, _REG_TEMPERATURE = 0x03, 0x38, 0x3C, 0x3F
_REG_HOMING = 0x1F


def _feetech_status(servo_id: int, params: bytes) -> bytes:
    body = bytes([servo_id, len(params) + 2, 0x00, *params])
    return b"\xff\xff" + body + bytes([~sum(body) & 0xFF])


class FeetechFakeChannel:
    """Request-response servo bus behind the Channel seam: silent until asked, answers per id."""

    kind = TransportKind.USB_SERIAL

    def __init__(
        self,
        positions: dict[int, int],
        *,
        models: dict[int, int] | None = None,
        loads: dict[int, int] | None = None,
        temps: dict[int, int] | None = None,
        homing: dict[int, int] | None = None,
        preload: bytes = b"",
        binding: str = "5B42134331",
        params: dict[str, object] | None = None,
        byteorder: str = "little",
    ) -> None:
        self.byteorder = byteorder  # "big" for an SCS (protocol 1) bus
        self.identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding=binding)
        self.params: dict[str, object] = (
            {"baud": 1_000_000, "timeout_s": 0.05} if params is None else params
        )
        self.positions = dict(positions)  # id → ticks; a missing id never replies
        self.models = dict(models or {})
        self.loads = dict(loads or {})
        self.temps = dict(temps or {})
        self.homing = dict(homing or {})  # raw sign-magnitude register values
        self._pending = preload  # bytes already queued (a stale reply, noise)
        self.sent: list[bytes] = []
        self.flushes = 0
        self.closed = False
        self.fail = False

    def _registers(self, address: int) -> dict[int, int] | None:
        return {
            _REG_POSITION: self.positions,
            _REG_MODEL: self.models,
            _REG_LOAD: self.loads,
            _REG_TEMPERATURE: self.temps,
            _REG_HOMING: self.homing,
        }.get(address)

    def send(self, frame: Frame) -> None:
        if self.fail:
            raise OSError("bus gone")
        data = frame.payload
        self.sent.append(data)
        servo_id, instruction = data[2], data[4]
        if servo_id not in self.positions:
            return
        if instruction == _PING:
            self._pending += _feetech_status(servo_id, b"")
        elif instruction == _READ:
            registers = self._registers(data[5])
            if registers is not None and servo_id in registers:
                value = registers[servo_id].to_bytes(data[6], self.byteorder)  # type: ignore[arg-type]
                self._pending += _feetech_status(servo_id, value)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        out, self._pending = self._pending[:max_bytes], self._pending[max_bytes:]
        return Frame(payload=out) if out else None

    def flush_input(self) -> None:
        self.flushes += 1
        self._pending = b""

    def close(self) -> None:
        self.closed = True


# ── frames (goldens, verbatim) ───────────────────────────────────────────────────

codec = FeetechCodec()


def test_ping_frame_matches_live_capture() -> None:
    assert codec.ping(1) == bytes.fromhex("ffff010201fb")
    assert codec.ping(6) == bytes.fromhex("ffff060201f6")


def test_read_position_frame() -> None:
    # READ(0x02) of present-position register 0x38, 2 bytes.
    assert codec.read_position(1) == bytes.fromhex("ffff0104023802be")


def test_read_model_frame() -> None:
    # READ(0x02) of the model-number register 0x03, 2 bytes: body 01 04 02 03 02, chk 0xF3.
    assert codec.read_model(1) == bytes.fromhex("ffff0104020302f3")


def test_write_frames_match_the_sts_wire() -> None:
    # WRITE(0x03) Goal_Position (0x2A) ticks 2047 = 0x07FF little-endian.
    assert codec.write_goal_position(1, 2047) == bytes.fromhex("ffff0105032aff07c6")
    # WRITE(0x03) Torque_Enable (0x28) on/off.
    assert codec.write_torque(1, enabled=True) == bytes.fromhex("ffff0104032801ce")
    assert codec.write_torque(1, enabled=False) == bytes.fromhex("ffff0104032800cf")


def test_scs_protocol_swaps_word_order_only() -> None:
    scs = FeetechCodec(protocol_version=1)
    assert scs.write_goal_position(1, 2047)[5:8] == bytes([0x2A, 0x07, 0xFF])
    assert scs.unword(bytes([0x08, 0x00])) == 2048 and codec.unword(bytes([0x00, 0x08])) == 2048
    assert scs.table is CONTROL_TABLE_BY_PROTOCOL[1] and codec.table is STS_CONTROL_TABLE


# ── replies ──────────────────────────────────────────────────────────────────────


def test_parse_reply_accepts_live_ping_status() -> None:
    # Captured reply from servo id 1: error byte 0x00, no params.
    assert FeetechCodec.parse_reply(bytes.fromhex("ffff010200fc"), servo_id=1) == b""


def test_parse_reply_extracts_position_params() -> None:
    # id 1, len 4 (err + 2 params + chk), err 0, ticks 2048 = 0x0800 little-endian.
    reply = bytes.fromhex("ffff0104000008f2")
    assert FeetechCodec.parse_reply(reply, servo_id=1) == bytes([0x00, 0x08])


def test_parse_reply_skips_leading_junk() -> None:
    junk = b"\x00\xff" + bytes.fromhex("ffff010200fc")
    assert FeetechCodec.parse_reply(junk, servo_id=1) == b""


def test_parse_reply_rejects_bad_checksum_wrong_id_and_error_status() -> None:
    parse = FeetechCodec.parse_reply
    assert parse(bytes.fromhex("ffff010200fb"), servo_id=1) is None  # bad checksum
    assert parse(bytes.fromhex("ffff020200fb"), servo_id=1) is None  # id 2, wanted 1
    # Hardware error flagged (err=0x04): position params are not trustworthy.
    assert parse(bytes.fromhex("ffff0104040008ee"), servo_id=1) is None
    assert parse(b"", servo_id=1) is None
    assert parse(bytes.fromhex("ffff0105"), servo_id=1) is None  # truncated


# ── ticks ↔ degrees ──────────────────────────────────────────────────────────────


def test_ticks_to_degrees_centres_at_2047() -> None:
    # lerobot's homing convention centres at int(4095/2) == 2047 (its Homing_Offset burn
    # makes the calibration pose READ 2047), so an exact digital twin shares that centre.
    to_deg = FeetechCodec.ticks_to_degrees
    assert to_deg(2047, ticks_per_rev=4096, center=2047) == 0.0
    assert to_deg(2047 + 1024, ticks_per_rev=4096, center=2047) == 90.0
    assert to_deg(0, ticks_per_rev=4096, center=2047) == -2047 * 360.0 / 4096
    assert to_deg(512, ticks_per_rev=2048, center=1024) == -90.0


def test_degrees_to_ticks_inverts_and_clamps() -> None:
    to_ticks, to_deg = FeetechCodec.degrees_to_ticks, FeetechCodec.ticks_to_degrees
    knobs = {"ticks_per_rev": 4096, "center": 2047}
    assert to_ticks(0.0, **knobs) == 2047
    assert to_ticks(90.0, **knobs) == 3071
    assert to_ticks(to_deg(1234, **knobs), **knobs) == 1234  # exact round-trip
    assert to_ticks(400.0, **knobs) == 4095  # clamped to the register range
    assert to_ticks(-400.0, **knobs) == 0


# ── definitions ──────────────────────────────────────────────────────────────────


def test_part_number_maps_known_models_and_reports_raw_unknowns() -> None:
    assert FeetechServo(1, 777).part_number == "STS3215"
    assert FeetechServo(1, 2825).part_number == "STS3250"
    assert FeetechServo(1, 54321).part_number is None
    assert FeetechServo(1, None).part_number is None
    assert FEETECH_MODELS[11272] == "SM8512BL" and FEETECH_RESOLUTION["SCS0009"] == 1024
    assert FEETECH_BAUDS[0] == 1_000_000 and FEETECH_BAUDS[4] == 115_200


# ── discovery over a scripted bus ────────────────────────────────────────────────


def test_discover_reports_id_and_model_for_every_responder() -> None:
    channel = FeetechFakeChannel(
        dict.fromkeys(range(1, 7), 0), models=dict.fromkeys(range(1, 7), 777)
    )
    servos = FeetechBus(as_bus_port(channel)).discover(range(1, 13))
    assert servos == [FeetechServo(i, 777) for i in range(1, 7)]
    assert channel.flushes >= 12  # flush BEFORE every ask: half-duplex, stale bytes never answer


def test_discover_keeps_a_servo_whose_model_read_fails() -> None:
    # Presence is bus truth; the model is evidence, not a requirement.
    channel = FeetechFakeChannel({1: 0, 3: 0}, models={1: 777})
    assert FeetechBus(as_bus_port(channel)).discover(range(1, 5)) == [
        FeetechServo(1, 777),
        FeetechServo(3, None),
    ]


def test_discover_ids_and_empty_bus() -> None:
    assert FeetechBus(as_bus_port(FeetechFakeChannel({1: 0, 2: 0, 6: 0}))).discover_ids() == [
        1,
        2,
        6,
    ]
    assert FeetechBus(as_bus_port(FeetechFakeChannel({}))).discover() == []


def test_discover_stops_at_the_deadline() -> None:
    channel = FeetechFakeChannel(dict.fromkeys(range(1, 7), 0))
    assert FeetechBus(as_bus_port(channel)).discover(deadline=0.0) == []
    assert channel.sent == []


def test_read_register_tolerates_garbage_and_short_replies() -> None:
    channel = FeetechFakeChannel({1: 2048}, preload=b"\xff\xff\x01\x04\x00\x99")
    bus = FeetechBus(as_bus_port(channel))
    assert bus.read_register(1, "Present_Position") == 2048  # stale junk flushed, fresh read wins
    assert bus.read_register(2, "Present_Position") is None  # silent servo
    assert bus.read_register(1, "Present_Load") is None  # servo answers nothing for this register


# ── vendor hygiene ratchet ───────────────────────────────────────────────────────


def test_vendor_strings_live_only_under_plugins_and_definitions() -> None:
    root = Path(__file__).resolve().parents[2]
    trees = [root / "livebench/src/livebench", root / "packages/api/src/solus_api/hardware"]
    vendor = re.compile(r"\b(feetech|sts3215|sts3250|sm8512bl|scs0009|so-?10x)\b", re.IGNORECASE)
    offenders = sorted(
        str(path.relative_to(root))
        for tree in trees
        for path in tree.rglob("*.py")
        if not {"plugins", "definitions"} & set(path.parts) and vendor.search(path.read_text())
    )
    assert offenders == []
