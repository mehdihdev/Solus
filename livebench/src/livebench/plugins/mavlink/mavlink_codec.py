"""MAVLink v2 framing, hand-rolled (pymavlink is LGPL).

Frame: STX 0xFD · payload_len · incompat_flags · compat_flags · seq · sysid · compid ·
msgid u24 LE · payload · crc u16 LE. The checksum is CRC-16/MCRF4XX (the "X25" CRC) over
payload_len..payload with the message's crc_extra byte accumulated last. v2 truncates trailing
zero payload bytes; the decoder pads them back to the definition's full length, which is also
how a v1-length SERVO_OUTPUT_RAW (no servo9..16) decodes.

Device bytes are untrusted (CLAUDE.md §7): the parser resyncs byte-wise on a bad checksum,
skips unknown ids by their declared length, and keeps at most `MAX_BUFFER_BYTES`.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from livebench.plugins.mavlink.mavlink_definitions import MESSAGES, MavlinkMessageDef

STX: Final = 0xFD
HEADER_LEN: Final = 10  # STX through msgid
CRC_LEN: Final = 2
SIGNATURE_LEN: Final = 13
INCOMPAT_SIGNED: Final = 0x01
MAX_BUFFER_BYTES: Final = 4096
_MSGID_SLICE: Final = slice(7, 10)


def crc_x25(data: bytes, crc_extra: int | None = None) -> int:
    """CRC-16/MCRF4XX: init 0xFFFF, reflected poly 0x8408; check("123456789") == 0x6F91."""
    crc = 0xFFFF
    for byte in data if crc_extra is None else data + bytes([crc_extra]):
        tmp = (byte ^ (crc & 0xFF)) & 0xFF
        tmp ^= (tmp << 4) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


@dataclass(frozen=True)
class MavlinkMessage:
    msg_id: int
    seq: int
    system_id: int
    component_id: int
    fields: Mapping[str, int | float]


def encode_mavlink(
    defn: MavlinkMessageDef,
    fields: Mapping[str, int | float],
    *,
    seq: int,
    system_id: int,
    component_id: int = 1,
) -> bytes:
    """One unsigned v2 frame; absent fields are zero, trailing zeros are truncated."""
    payload = struct.pack(defn.wire_format, *(fields.get(name, 0) for name, _ in defn.fields))
    payload = payload.rstrip(b"\x00") or b"\x00"
    body = (
        bytes([len(payload), 0, 0, seq & 0xFF, system_id, component_id])
        + defn.msg_id.to_bytes(3, "little")
        + payload
    )
    return bytes([STX]) + body + crc_x25(body, defn.crc_extra).to_bytes(2, "little")


class MavlinkParser:
    """Stateful byte-stream parser: `feed` returns every complete, checksum-valid message."""

    def __init__(
        self,
        *,
        messages: Mapping[int, MavlinkMessageDef] = MESSAGES,
        max_buffer: int = MAX_BUFFER_BYTES,
    ) -> None:
        self._messages = messages
        self._max_buffer = max_buffer
        self._buffer = bytearray()

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> list[MavlinkMessage]:
        self._buffer += data
        if len(self._buffer) > self._max_buffer:
            del self._buffer[: len(self._buffer) - self._max_buffer]  # newest bytes win
        out: list[MavlinkMessage] = []
        while self._sync():
            frame_len = self._frame_length()
            if frame_len is None:
                break
            frame = bytes(self._buffer[:frame_len])
            defn = self._definition(frame)
            if defn is not None and not self._checksum_ok(frame, defn):
                del self._buffer[:1]  # the length byte is untrusted now: resync byte-wise
                continue
            if defn is not None:
                out.append(self._unpack(frame, defn))
            del self._buffer[:frame_len]  # unknown ids and signed frames skip whole
        return out

    def _sync(self) -> bool:
        """Drop bytes up to the next STX; True when a header could be complete."""
        start = self._buffer.find(STX)
        if start < 0:
            self._buffer.clear()
            return False
        del self._buffer[:start]
        return len(self._buffer) >= HEADER_LEN

    def _frame_length(self) -> int | None:
        signed = self._buffer[2] & INCOMPAT_SIGNED
        total = HEADER_LEN + self._buffer[1] + CRC_LEN + (SIGNATURE_LEN if signed else 0)
        return total if len(self._buffer) >= total else None

    def _definition(self, frame: bytes) -> MavlinkMessageDef | None:
        if frame[2] & INCOMPAT_SIGNED:
            return None  # signatures are not verified here; a signed frame is skipped whole
        return self._messages.get(int.from_bytes(frame[_MSGID_SLICE], "little"))

    @staticmethod
    def _checksum_ok(frame: bytes, defn: MavlinkMessageDef) -> bool:
        body_end = HEADER_LEN + frame[1]
        expected = int.from_bytes(frame[body_end : body_end + CRC_LEN], "little")
        return crc_x25(frame[1:body_end], defn.crc_extra) == expected

    @staticmethod
    def _unpack(frame: bytes, defn: MavlinkMessageDef) -> MavlinkMessage:
        payload = frame[HEADER_LEN : HEADER_LEN + frame[1]]
        values = struct.unpack(defn.wire_format, payload.ljust(defn.length, b"\x00")[: defn.length])
        return MavlinkMessage(
            msg_id=defn.msg_id,
            seq=frame[4],
            system_id=frame[5],
            component_id=frame[6],
            fields=dict(zip((name for name, _ in defn.fields), values, strict=True)),
        )
