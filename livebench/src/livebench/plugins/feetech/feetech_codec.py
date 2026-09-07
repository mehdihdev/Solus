"""Feetech STS/SCS wire codec and the one-request-outstanding bus exchange.

Protocol (Dynamixel-1.0 style): frame `FF FF id len instr params… chk`, chk =
`~sum(id..params) & 0xFF`; a status reply is `FF FF id len err params… chk`. Protocol version 0
(STS/SMS) carries 16-bit words little-endian, version 1 (SCS) big-endian — the only difference
this codec knows about. Golden frames pinned in the tests were captured live from an SO-10x arm.

Device replies are untrusted input (§7): reads are bounded to the reply size, checksums verified,
error-flagged replies discarded; a malformed reply is `None`, never an exception.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from livebench.plugins.feetech.feetech_definitions import (
    CONTROL_TABLE_BY_PROTOCOL,
    DEFAULT_CANDIDATE_IDS,
    FEETECH_MODELS,
    HOMING_OFFSET_SIGN_BIT,
    FeetechRegister,
)

logger = logging.getLogger(__name__)

_HEADER: Final = b"\xff\xff"
_INSTR_PING: Final = 0x01
_INSTR_READ: Final = 0x02
_INSTR_WRITE: Final = 0x03
#: header(2) + id + len + err + chk — a status reply carrying no params.
_STATUS_OVERHEAD: Final = 6


class FeetechBusPort(Protocol):
    """The request-response slice of a port (`BusPortAdapter`, or a test fake)."""

    def write(self, data: bytes) -> int | None: ...

    def read(self, size: int) -> bytes: ...

    def reset_input_buffer(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class FeetechCodec:
    """Frames in, params out, for one protocol version (word order + control table)."""

    protocol_version: int = 0

    @property
    def table(self) -> dict[str, FeetechRegister]:
        return CONTROL_TABLE_BY_PROTOCOL[self.protocol_version]

    @property
    def _byteorder(self) -> Literal["big", "little"]:
        return "big" if self.protocol_version == 1 else "little"

    def word(self, value: int) -> bytes:
        return (value & 0xFFFF).to_bytes(2, self._byteorder)

    @staticmethod
    def homing_offset(raw: int) -> int:
        """Signed Homing_Offset from its sign-magnitude register value."""
        magnitude = raw & (HOMING_OFFSET_SIGN_BIT - 1)
        return -magnitude if raw & HOMING_OFFSET_SIGN_BIT else magnitude

    def unword(self, data: bytes) -> int:
        return int.from_bytes(data[:2], self._byteorder)

    @staticmethod
    def frame(servo_id: int, instruction: int, params: bytes = b"") -> bytes:
        body = bytes([servo_id, len(params) + 2, instruction, *params])
        return _HEADER + body + bytes([~sum(body) & 0xFF])

    def ping(self, servo_id: int) -> bytes:
        return self.frame(servo_id, _INSTR_PING)

    def read(self, servo_id: int, register: FeetechRegister) -> bytes:
        return self.frame(servo_id, _INSTR_READ, bytes([register.address, register.size]))

    def write(self, servo_id: int, register: FeetechRegister, value: int) -> bytes:
        payload = self.word(value) if register.size == 2 else bytes([value & 0xFF])
        return self.frame(servo_id, _INSTR_WRITE, bytes([register.address]) + payload)

    def read_position(self, servo_id: int) -> bytes:
        return self.read(servo_id, self.table["Present_Position"])

    def read_model(self, servo_id: int) -> bytes:
        return self.read(servo_id, self.table["Model_Number"])

    def write_goal_position(self, servo_id: int, ticks: int) -> bytes:
        return self.write(servo_id, self.table["Goal_Position"], ticks)

    def write_torque(self, servo_id: int, *, enabled: bool) -> bytes:
        return self.write(servo_id, self.table["Torque_Enable"], int(enabled))

    @staticmethod
    def parse_reply(data: bytes, *, servo_id: int) -> bytes | None:
        """Status params from `data`, or None. Skips junk; rejects a bad checksum, another
        servo's reply, or a reply flagging a hardware error."""
        marker = _HEADER + bytes([servo_id])
        i = data.find(marker)
        while i != -1:
            if len(data) >= i + 4:
                length = data[i + 3]
                end = i + 4 + length
                if length >= 2 and len(data) >= end:
                    body = data[i + 2 : end - 1]
                    if (~sum(body) & 0xFF) == data[end - 1]:
                        error = data[i + 4]
                        if error == 0:
                            return bytes(data[i + 5 : end - 1])
                        logger.debug("servo %d flags hardware error 0x%02x", servo_id, error)
                        return None
            i = data.find(marker, i + 1)
        return None

    @staticmethod
    def ticks_to_degrees(ticks: int, *, ticks_per_rev: int, center: int) -> float:
        return (ticks - center) * 360.0 / ticks_per_rev

    @staticmethod
    def degrees_to_ticks(degrees: float, *, ticks_per_rev: int, center: int) -> int:
        """Inverse of `ticks_to_degrees`, clamped into the register range — a wild command can
        only ever pin at an end stop, never wrap or overflow."""
        ticks = round(degrees * ticks_per_rev / 360.0 + center)
        return min(max(ticks, 0), ticks_per_rev - 1)


@dataclass(frozen=True)
class FeetechServo:
    """One discovered servo: bus presence is truth; the model is evidence."""

    servo_id: int
    model_number: int | None

    @property
    def part_number(self) -> str | None:
        return None if self.model_number is None else FEETECH_MODELS.get(self.model_number)


class FeetechBus:
    """One master on one half-duplex bus: a single request outstanding, ever."""

    def __init__(self, port: FeetechBusPort, codec: FeetechCodec | None = None) -> None:
        self._port = port
        self.codec = codec or FeetechCodec()

    def transact(self, servo_id: int, frame: bytes, reply_len: int) -> bytes | None:
        """Flush BEFORE asking: the bus is strictly request-response, so anything already queued
        (noise, a stale frame from a prior slip) is by definition not the answer to THIS
        request — accepting it would serve seconds-old positions as fresh readings."""
        self._port.reset_input_buffer()
        self._port.write(frame)
        return self.codec.parse_reply(self._port.read(reply_len), servo_id=servo_id)

    def ping(self, servo_id: int) -> bool:
        return self.transact(servo_id, self.codec.ping(servo_id), _STATUS_OVERHEAD) is not None

    def read_register(self, servo_id: int, name: str) -> int | None:
        """One control-table register as an int, or None (silent servo, bad reply)."""
        register = self.codec.table[name]
        reply_len = _STATUS_OVERHEAD + register.size
        params = self.transact(servo_id, self.codec.read(servo_id, register), reply_len)
        if params is None or len(params) < register.size:
            return None
        return self.codec.unword(params) if register.size == 2 else params[0]

    def discover(
        self,
        candidate_ids: Iterable[int] = DEFAULT_CANDIDATE_IDS,
        *,
        deadline: float | None = None,
    ) -> list[FeetechServo]:
        """Ping-responders plus their model register, in scan order, until `deadline`
        (`time.monotonic`). A servo whose model read fails is still discovered."""
        servos: list[FeetechServo] = []
        for servo_id in candidate_ids:
            if deadline is not None and time.monotonic() > deadline:
                break
            if self.ping(servo_id):
                servos.append(FeetechServo(servo_id, self.read_register(servo_id, "Model_Number")))
        return servos

    def discover_ids(self, candidate_ids: Iterable[int] = DEFAULT_CANDIDATE_IDS) -> list[int]:
        return [servo.servo_id for servo in self.discover(candidate_ids)]

    def close(self) -> None:
        self._port.close()
