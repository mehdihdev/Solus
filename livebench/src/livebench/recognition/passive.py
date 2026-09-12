"""Passive robot identification (RBT-01) — shared, vendor-free detection.

What the wire can genuinely say, and NOTHING more:

* **USB/serial enumeration** — VID/PID against the maintained board table
  (`livebench.definitions.usb_boards`, the one shared place a board product is named). A
  known MCU board identifies itself; a USB-serial **bridge** identifies only the bridge —
  the MCU behind it is reported UNKNOWN, never guessed. An unknown VID/PID reports unknown.
* **Stream shape** — framing, channel count, ranges, update rate. Shape CONSTRAINS,
  it does not identify: the evidence it emits is capped at low confidence and the
  note says so, mirroring the CTR-08 worked example (`hardware_modalities.json`).

Self-describing buses (a servo bus answering a broadcast ping, CAN nodes announcing
themselves by heartbeat) are interrogated by the vendor plugins under `livebench.plugins`
through the Interrogator seam (`hardware/interrogator.py`); nothing here names a product.

Every finding is a real `ModalityMatch` (CTR-08) so RBT-05 persists it through the
fingerprint seam with no translation. All probes degrade gracefully: silence, junk,
and unknown hardware produce valid results, never exceptions.
"""

import json
import logging
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef

from livebench.definitions.usb_boards import BOARD_TABLE, Board, BoardClass

__all__ = [
    "BOARD_TABLE",
    "BindingBasis",
    "Board",
    "BoardClass",
    "PortIdentity",
    "PORT_BINDING_PREFIX",
    "StreamShape",
    "binding_key",
    "binding_of",
    "characterize_stream",
    "enumerate_usb_serial",
    "identify_port",
    "resolve_board",
]

logger = logging.getLogger(__name__)

# ── USB/serial enumeration ──────────────────────────────────────────────────────

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
    #: USB topology position (`3-1.4.2`) — the honest fallback binding for a device that
    #: carries no serial number. It identifies the PORT, so a move is a new device.
    location: str | None = None


PORT_BINDING_PREFIX: Final = "port-"
BindingBasis = Literal["serial", "port_position", "none"]


def binding_of(identity: PortIdentity) -> tuple[str | None, BindingBasis]:
    """The transport binding this device can honestly carry, and which branch produced it:
    its USB serial, else its USB port position as `port-<location>` (identity from the port —
    a move is a new device), else nothing. A device-supplied serial is untrusted (§7): one
    that claims the `port-` prefix can never mint a port key and is treated as absent."""
    if identity.serial and not identity.serial.startswith(PORT_BINDING_PREFIX):
        return identity.serial, "serial"
    if identity.location:
        return f"{PORT_BINDING_PREFIX}{identity.location}", "port_position"
    return None, "none"


def binding_key(identity: PortIdentity) -> str | None:
    return binding_of(identity)[0]


def _location_of(raw: str | None) -> str | None:
    """`3-1.4.1.1.3:1.0` → `3-1.4.1.1.3` (the text before the interface suffix)."""
    return raw.split(":", 1)[0] or None if raw else None


def resolve_board(vid: int, pid: int) -> Board | None:
    return BOARD_TABLE.get((vid, pid))


def identify_port(
    *, device: str, vid: int, pid: int, serial: str | None, location: str | None = None
) -> PortIdentity:
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
        return PortIdentity(device, vid, pid, serial, None, False, match, location)
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
        return PortIdentity(device, vid, pid, serial, board, False, match, location)
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
    return PortIdentity(device, vid, pid, serial, board, True, match, location)


def enumerate_usb_serial() -> list[PortIdentity]:
    """Enumerate real ports (no port is opened — enumeration is side-effect free)."""
    from serial.tools import list_ports

    identities: list[PortIdentity] = []
    for port in list_ports.comports():
        if port.vid is None or port.pid is None:
            continue  # not USB (platform serial); nothing to claim
        identities.append(
            identify_port(
                device=port.device,
                vid=port.vid,
                pid=port.pid,
                serial=port.serial_number,
                location=_location_of(port.location),
            )
        )
    return identities


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
