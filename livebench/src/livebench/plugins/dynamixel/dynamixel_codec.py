"""Dynamixel Protocol 2.0 framing — moved from `recognition/passive.py` (SOLUSDEV-248) so the
shared detection code names no vendor. Implemented directly over the port (≈40 lines incl. CRC)
rather than pulling the vendor SDK; the golden frames from the ROBOTIS e-manual pin it in tests.

Device input is untrusted (CLAUDE.md §7): reads are byte- and time-bounded, every packet's CRC
is verified, and a malformed reply is skipped — nothing here raises on bus bytes.
"""

from __future__ import annotations

import time
from typing import Final, NamedTuple, Protocol

from livebench.plugins.dynamixel.dynamixel_definitions import DxlRegister

DXL_HEADER: Final = b"\xff\xff\xfd\x00"
DXL_BROADCAST_ID: Final = 0xFE
DXL_INSTRUCTION_PING: Final = 0x01
DXL_INSTRUCTION_READ: Final = 0x02
DXL_INSTRUCTION_STATUS: Final = 0x55
#: header(4) id(1) len(2) instruction(1) error(1) … crc(2): a status packet's bytes around params.
DXL_STATUS_OVERHEAD: Final = 11
DXL_READ_BUDGET: Final = 4096  # a bus answers in tens of bytes; anything more is noise
_PING_CHUNK: Final = 256
_ERROR_RESULT_MASK: Final = 0x7F  # bit 7 is the hardware-alert flag; the low bits are the result


class DxlPort(Protocol):
    """Request-response bytes (the `BusPortAdapter` shape; injectable in tests)."""

    def write(self, data: bytes) -> int | None: ...

    def read(self, size: int) -> bytes: ...


class DxlStatus(NamedTuple):
    servo_id: int
    error: int
    params: bytes


class DxlPingReply(NamedTuple):
    servo_id: int
    model_number: int
    firmware: int


def dxl_crc(data: bytes) -> int:
    """ROBOTIS CRC-16 (poly 0x8005, init 0) — pinned by the spec's golden ping frame."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x8005 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc


def dxl_frame(device_id: int, instruction: int, params: bytes = b"") -> bytes:
    length = len(params) + 3  # instruction + crc(2)
    body = DXL_HEADER + bytes([device_id, length & 0xFF, length >> 8, instruction]) + params
    crc = dxl_crc(body)
    return body + bytes([crc & 0xFF, crc >> 8])


#: The broadcast ping, byte-for-byte per the Protocol 2.0 spec (ends 0x31 0x42).
DXL_BROADCAST_PING: Final = dxl_frame(DXL_BROADCAST_ID, DXL_INSTRUCTION_PING)


def dxl_status_packet(servo_id: int, params: bytes, *, error: int = 0) -> bytes:
    """A well-formed status packet — fixture builder for bus replies."""
    return dxl_frame(servo_id, DXL_INSTRUCTION_STATUS, bytes([error]) + params)


def dxl_ping_status_packet(*, servo_id: int, model_number: int, firmware: int) -> bytes:
    return dxl_status_packet(servo_id, bytes([model_number & 0xFF, model_number >> 8, firmware]))


def parse_dxl_status(buffer: bytes) -> list[DxlStatus]:
    """Every valid status packet in `buffer`; junk and CRC failures are skipped, never raised."""
    results: list[DxlStatus] = []
    i = 0
    while (start := buffer.find(DXL_HEADER, i)) != -1:
        header_end = start + len(DXL_HEADER)
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
        instruction_at = len(DXL_HEADER) + 3
        if dxl_crc(packet[:-2]) != crc or packet[instruction_at] != DXL_INSTRUCTION_STATUS:
            i = start + 1
            continue
        error, params = packet[instruction_at + 1], packet[instruction_at + 2 : -2]
        results.append(DxlStatus(servo_id, error, params))
        i = end
    return results


def parse_dxl_ping(buffer: bytes) -> list[DxlPingReply]:
    """(servo_id, model_number, firmware) per valid ping status packet."""
    return [
        DxlPingReply(status.servo_id, status.params[0] | (status.params[1] << 8), status.params[2])
        for status in parse_dxl_status(buffer)
        if len(status.params) >= 3
    ]


def _read_until_silence(port: DxlPort, *, budget_s: float | None) -> bytes:
    deadline = None if budget_s is None else time.monotonic() + budget_s
    buffer = b""
    while len(buffer) < DXL_READ_BUDGET:
        if deadline is not None and time.monotonic() >= deadline:
            break
        chunk = port.read(_PING_CHUNK)
        if not chunk:
            break
        buffer += chunk
    return buffer


def dynamixel_broadcast_ping(port: DxlPort, *, budget_s: float | None = None) -> list[DxlPingReply]:
    """Broadcast-ping the bus and collect every responder (id, model register, firmware)."""
    port.write(DXL_BROADCAST_PING)
    return parse_dxl_ping(_read_until_silence(port, budget_s=budget_s))


def dxl_read_request(servo_id: int, register: DxlRegister) -> bytes:
    """READ (0x02) of `register`: address and size ride little-endian, 2 bytes each."""
    address, size = register
    params = bytes([address & 0xFF, address >> 8, size & 0xFF, size >> 8])
    return dxl_frame(servo_id, DXL_INSTRUCTION_READ, params)


def dxl_read_register(port: DxlPort, servo_id: int, register: DxlRegister) -> bytes | None:
    """One READ round trip: the register's bytes, or None when the reply is missing, from
    another servo, the wrong size, or a failed result (one lost sample; the caller keeps going).
    A hardware-alert flag (bit 7) still carries valid data and is not a failure."""
    port.write(dxl_read_request(servo_id, register))
    reply = port.read(DXL_STATUS_OVERHEAD + register.size)
    for status in parse_dxl_status(reply):
        if (
            status.servo_id == servo_id
            and len(status.params) == register.size
            and not status.error & _ERROR_RESULT_MASK
        ):
            return status.params
    return None
