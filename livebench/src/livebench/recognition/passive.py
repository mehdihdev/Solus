"""Passive robot identification (RBT-01) — three independent probes, no ROS assumed.

What the wire can genuinely say, and NOTHING more:

* **USB/serial enumeration** — VID/PID against a maintained board table. A known MCU
  board (Teensy, Uno) identifies itself; a USB-serial **bridge** (CH343, CP2102,
  FT232) identifies only the bridge — the MCU behind it is reported UNKNOWN, never
  guessed. An unknown VID/PID reports unknown.
* **Self-describing buses** — a Dynamixel Protocol-2.0 broadcast ping returns each
  servo's ID and model register; ODrive CAN nodes announce themselves via heartbeat.
  The ONLY case where identity is readable off the wire — and even then it names the
  PART, not the joint it drives (that link is RBT-03/04's, via human confirmation).
* **Stream shape** — framing, channel count, ranges, update rate. Shape CONSTRAINS,
  it does not identify: the evidence it emits is capped at low confidence and the
  note says so, mirroring the CTR-08 worked example (`hardware_modalities.json`).

Every finding is a real `ModalityMatch` (CTR-08) so RBT-05 persists it through the
fingerprint seam with no translation. All probes degrade gracefully: silence, junk,
and unknown hardware produce valid results, never exceptions.

The Dynamixel framing is implemented directly over the port (≈40 lines incl. CRC)
rather than pulling the vendor SDK for one broadcast ping; the golden frame bytes
from the ROBOTIS spec pin the implementation in tests.
"""

import enum
import json
import logging
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef

logger = logging.getLogger(__name__)

# ── USB/serial enumeration ──────────────────────────────────────────────────────


class BoardClass(enum.StrEnum):
    MCU_BOARD = "mcu_board"  # the USB identity IS the board (Teensy, Uno, ESP32-S3 native)
    USB_BRIDGE = "usb_bridge"  # a serial front-end; says nothing about what's behind it


@dataclass(frozen=True)
class Board:
    name: str
    kind: BoardClass


#: Maintained VID:PID table. Curated, not exhaustive — anything absent reports
#: unknown, which is the honest answer. Grows as boards are met in the field.
BOARD_TABLE: Final[dict[tuple[int, int], Board]] = {
    # MCU boards with native USB identity
    (0x16C0, 0x0483): Board("Teensy (PJRC) 3.x/4.x USB serial", BoardClass.MCU_BOARD),
    (0x2341, 0x0043): Board("Arduino Uno R3", BoardClass.MCU_BOARD),
    (0x2341, 0x8036): Board("Arduino Leonardo", BoardClass.MCU_BOARD),
    (0x2341, 0x0042): Board("Arduino Mega 2560", BoardClass.MCU_BOARD),
    (0x303A, 0x1001): Board("Espressif ESP32-S3 native USB", BoardClass.MCU_BOARD),
    (0x239A, 0x80F4): Board("Adafruit Feather RP2040", BoardClass.MCU_BOARD),
    (0x2E8A, 0x0005): Board("Raspberry Pi Pico (RP2040, MicroPython)", BoardClass.MCU_BOARD),
    # USB-UART bridges — the chip is known; the MCU behind it is NOT
    (0x1A86, 0x55D3): Board("WCH CH343/CH9102 USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x1A86, 0x7523): Board("WCH CH340 USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x10C4, 0xEA60): Board("Silicon Labs CP210x USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x0403, 0x6001): Board("FTDI FT232R USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x0403, 0x6014): Board("FTDI FT232H USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x067B, 0x2303): Board("Prolific PL2303 USB-serial bridge", BoardClass.USB_BRIDGE),
}

_PART_NOT_JOINT: Final = (
    "identifies the PART, not which joint it drives — the motor-to-joint link goes "
    "through human confirmation (RBT-03)"
)


@dataclass(frozen=True)
class PortIdentity:
    """One serial port's honest identity claim."""

    device: str
    vid: int
    pid: int
    serial: str | None
    board: Board | None
    mcu_known: bool
    evidence: ModalityMatch


def resolve_board(vid: int, pid: int) -> Board | None:
    return BOARD_TABLE.get((vid, pid))


def identify_port(*, device: str, vid: int, pid: int, serial: str | None) -> PortIdentity:
    board = resolve_board(vid, pid)
    ref = SourceRef(source_connector="usb", external_ref=f"{device}/{vid:04x}:{pid:04x}")
    if board is None:
        match = ModalityMatch(
            modality=Modality.BUS_ENUMERATION,
            source_ref=ref,
            confidence=0.05,
            state=MatchState.LOW_CONFIDENCE,
            evidence={
                "matched_on": "usb_vid_pid",
                "value": f"{vid:04x}:{pid:04x}",
                "note": "unknown VID/PID — reported as unknown, never guessed",
            },
        )
        return PortIdentity(device, vid, pid, serial, None, False, match)
    if board.kind is BoardClass.USB_BRIDGE:
        match = ModalityMatch(
            modality=Modality.BUS_ENUMERATION,
            source_ref=ref,
            confidence=0.30,
            state=MatchState.LOW_CONFIDENCE,
            evidence={
                "matched_on": "usb_vid_pid",
                "value": f"{vid:04x}:{pid:04x}",
                "note": (
                    f"{board.name}: the bridge chip is identified, but the MCU behind "
                    "it is unknown — a bridge carries no identity for what it fronts"
                ),
            },
        )
        return PortIdentity(device, vid, pid, serial, board, False, match)
    match = ModalityMatch(
        modality=Modality.BUS_ENUMERATION,
        source_ref=ref,
        confidence=0.85,
        state=MatchState.MATCHED,
        evidence={
            "matched_on": "usb_vid_pid",
            "value": f"{vid:04x}:{pid:04x}",
            "note": f"{board.name}; {_PART_NOT_JOINT}",
        },
    )
    return PortIdentity(device, vid, pid, serial, board, True, match)


def enumerate_usb_serial() -> list[PortIdentity]:
    """Enumerate real ports (no port is opened — enumeration is side-effect free)."""
    from serial.tools import list_ports

    identities: list[PortIdentity] = []
    for port in list_ports.comports():
        if port.vid is None or port.pid is None:
            continue  # not USB (platform serial); nothing to claim
        identities.append(
            identify_port(device=port.device, vid=port.vid, pid=port.pid, serial=port.serial_number)
        )
    return identities


# ── Dynamixel Protocol 2.0 broadcast ping ───────────────────────────────────────


class SerialLike(Protocol):
    """The slice of pyserial this probe needs (injectable in tests)."""

    port: str | None

    def write(self, data: bytes) -> int | None: ...

    def read(self, size: int) -> bytes: ...


_DXL_HEADER: Final = b"\xff\xff\xfd\x00"
_DXL_STATUS_INSTRUCTION: Final = 0x55
_DXL_READ_BUDGET: Final = 4096  # a bus answers in tens of bytes; anything more is noise

#: Dynamixel model-number register → part number (curated; unknown numbers stay numeric).
DXL_MODELS: Final[dict[int, str]] = {
    1020: "XM430-W350",
    1190: "XL330-M288",
    1200: "XC330-M288",
    1060: "XL430-W250",
    1120: "XM540-W270",
    350: "XL320",
}


def _dxl_crc(data: bytes) -> int:
    """ROBOTIS CRC-16 (poly 0x8005, init 0) — pinned by the spec's golden ping frame."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x8005 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc


def _dxl_frame(device_id: int, instruction: int, params: bytes = b"") -> bytes:
    length = len(params) + 3  # instruction + crc(2)
    body = _DXL_HEADER + bytes([device_id, length & 0xFF, length >> 8, instruction]) + params
    crc = _dxl_crc(body)
    return body + bytes([crc & 0xFF, crc >> 8])


#: The broadcast ping, byte-for-byte per the Protocol 2.0 spec (ends 0x31 0x42).
DXL_BROADCAST_PING: Final = _dxl_frame(0xFE, 0x01)


def _dxl_status_packet(*, servo_id: int, model_number: int, firmware: int) -> bytes:
    """A well-formed ping status packet — test/fixture builder for bus responses."""
    params = bytes([0x00, model_number & 0xFF, model_number >> 8, firmware])  # err + payload
    return _dxl_frame(servo_id, _DXL_STATUS_INSTRUCTION, params)


def _parse_dxl_status(buffer: bytes) -> list[tuple[int, int, int]]:
    """(servo_id, model_number, firmware) per valid status packet; junk is skipped."""
    results: list[tuple[int, int, int]] = []
    i = 0
    while (start := buffer.find(_DXL_HEADER, i)) != -1:
        header_end = start + len(_DXL_HEADER)
        if len(buffer) < header_end + 3:
            break
        servo_id = buffer[header_end]
        length = buffer[header_end + 1] | (buffer[header_end + 2] << 8)
        end = header_end + 3 + length
        if length < 4 or len(buffer) < end:
            i = start + 1
            continue
        packet = buffer[start:end]
        crc = packet[-1] << 8 | packet[-2]
        # Packet-relative layout: header(4) id(1) len(2) instruction(1) error(1) params… crc(2)
        instruction_at = len(_DXL_HEADER) + 3
        if _dxl_crc(packet[:-2]) != crc or packet[instruction_at] != _DXL_STATUS_INSTRUCTION:
            i = start + 1
            continue
        params = packet[instruction_at + 2 : -2]  # after instruction + error byte
        if len(params) >= 3:
            results.append((servo_id, params[0] | (params[1] << 8), params[2]))
        i = end
    return results


def dynamixel_broadcast_ping(port: SerialLike) -> list[ModalityMatch]:
    """Broadcast-ping the bus; every responder is a self-asserted identity (0.92)."""
    port.write(DXL_BROADCAST_PING)
    buffer = b""
    while len(buffer) < _DXL_READ_BUDGET:
        chunk = port.read(256)
        if not chunk:
            break
        buffer += chunk
    findings: list[ModalityMatch] = []
    port_name = port.port or "serial"
    for servo_id, model_number, firmware in _parse_dxl_status(buffer):
        part = DXL_MODELS.get(model_number, f"model {model_number}")
        findings.append(
            ModalityMatch(
                modality=Modality.BUS_ENUMERATION,
                source_ref=SourceRef(
                    source_connector="dynamixel", external_ref=f"{port_name}/id:{servo_id}"
                ),
                confidence=0.92,
                state=MatchState.MATCHED,
                evidence={
                    "matched_on": "model_register",
                    "value": str(model_number),
                    "note": (
                        f"Dynamixel model register {model_number} = {part}, fw v{firmware}; "
                        f"the device asserts its own identity. {_PART_NOT_JOINT}"
                    ),
                },
            )
        )
    return findings


# ── CAN self-announcement (ODrive) ──────────────────────────────────────────────

_ODRIVE_HEARTBEAT_CMD: Final = 0x01


def identify_odrive_heartbeats(
    frames: Iterable[tuple[int, bytes]], *, interface: str
) -> list[ModalityMatch]:
    """ODrive nodes announce themselves: heartbeat frames (cmd 0x01) name the node."""
    nodes: set[int] = set()
    for arbitration_id, data in frames:
        if arbitration_id & 0x1F == _ODRIVE_HEARTBEAT_CMD and len(data) >= 8:
            nodes.add(arbitration_id >> 5)
    return [
        ModalityMatch(
            modality=Modality.BUS_ENUMERATION,
            source_ref=SourceRef(source_connector="can", external_ref=f"{interface}/node:{node}"),
            confidence=0.92,
            state=MatchState.MATCHED,
            evidence={
                "matched_on": "odrive_heartbeat",
                "value": str(node),
                "note": f"ODrive axis node {node} announces itself on CAN; {_PART_NOT_JOINT}",
            },
        )
        for node in sorted(nodes)
    ]


# ── Stream shape ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StreamShape:
    """What a stream LOOKS like — deliberately not who it is."""

    port_name: str
    baud: int
    framing: str  # json-lines | csv | text | binary | silent
    channel_count: int
    channel_ranges: dict[str, tuple[float, float]]
    update_hz: float
    evidence: ModalityMatch


def _channels_of(line: bytes) -> dict[str, float] | None:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
        if not isinstance(parsed, dict):
            return None
        out = {
            str(k): float(v)
            for k, v in parsed.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
        }
        return out or None
    try:
        values = [float(f) for f in text.split(",")]
    except ValueError:
        return None
    return {f"ch{i}": v for i, v in enumerate(values) if math.isfinite(v)} or None


def characterize_stream(
    samples: Sequence[tuple[float, bytes]], *, port_name: str, baud: int
) -> StreamShape:
    """Offline characterization of (arrival_seconds, line) samples at a known baud.

    Always returns a valid, useful result: a silent or binary stream is a finding,
    not an error — and the emitted evidence is capped low, because shape constrains
    without identifying (the CTR-08 ambiguous example's rule).
    """
    framings: list[str] = []
    ranges: dict[str, tuple[float, float]] = {}
    for _t, line in samples:
        channels = _channels_of(line)
        if channels is None:
            framings.append("binary" if any(b > 0x7E or b < 0x09 for b in line) else "text")
            continue
        framings.append("json-lines" if line.strip().startswith(b"{") else "csv")
        for name, value in channels.items():
            low, high = ranges.get(name, (value, value))
            ranges[name] = (min(low, value), max(high, value))

    if not samples:
        framing = "silent"
    else:
        framing = statistics.mode(framings) if framings else "silent"
    deltas = [b - a for (a, _), (b, _) in zip(samples, samples[1:], strict=False)]
    positive = [d for d in deltas if d > 0]
    update_hz = 1.0 / statistics.median(positive) if positive else 0.0

    shape_value = f"{len(ranges)}ch@{update_hz:.0f}Hz/{framing}"
    evidence = ModalityMatch(
        modality=Modality.TELEMETRY_CHANNEL,
        source_ref=SourceRef(source_connector="serial", external_ref=port_name),
        confidence=0.25,
        state=MatchState.LOW_CONFIDENCE,
        evidence={
            "matched_on": "stream_shape",
            "value": shape_value,
            "note": (
                "channel shape constrains, it does not identify — stays unlinked "
                "pending human confirmation"
            ),
        },
    )
    return StreamShape(
        port_name=port_name,
        baud=baud,
        framing=framing,
        channel_count=len(ranges),
        channel_ranges=ranges,
        update_hz=update_hz,
        evidence=evidence,
    )
