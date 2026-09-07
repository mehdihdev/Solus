"""Dynamixel Protocol 2.0 codec (moved out of recognition/passive.py, SOLUSDEV-248): framing,
CRC, the broadcast ping, READ of a register, and status parsing that survives junk. Golden
bytes come from the ROBOTIS Protocol 2.0 e-manual examples."""

from livebench.plugins.dynamixel.dynamixel_codec import (
    DXL_BROADCAST_PING,
    DXL_READ_BUDGET,
    DxlPingReply,
    dxl_crc,
    dxl_frame,
    dxl_ping_status_packet,
    dxl_read_register,
    dxl_read_request,
    dxl_status_packet,
    dynamixel_broadcast_ping,
    parse_dxl_ping,
    parse_dxl_status,
)
from livebench.plugins.dynamixel.dynamixel_definitions import DXL_REGISTERS

#: e-manual: read 4 bytes of Present Position (132) from ID 1, and the reply (position 166).
READ_PRESENT_POSITION_ID1 = bytes.fromhex("fffffd0001070002840004001d15")
READ_STATUS_ID1_166 = bytes.fromhex("fffffd000108005500a60000008cc0")
PRESENT_POSITION = DXL_REGISTERS["present_position"]


class _FakeDxlPort:
    def __init__(self, wire: bytes) -> None:
        self.wire = wire
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def read(self, size: int) -> bytes:
        chunk, self.wire = self.wire[:size], self.wire[size:]
        return chunk


class _EndlessZeros:
    def write(self, data: bytes) -> int:
        return len(data)

    def read(self, size: int) -> bytes:
        return b"\x00" * size


class TestDynamixelPing:
    def test_broadcast_ping_frame_matches_the_documented_bytes(self) -> None:
        # Golden bytes from the ROBOTIS Protocol 2.0 spec — proves the CRC16 too.
        assert DXL_BROADCAST_PING == bytes.fromhex("fffffd00fe0300013142")
        assert dxl_frame(0xFE, 0x01) == DXL_BROADCAST_PING
        assert dxl_crc(DXL_BROADCAST_PING[:-2]) == 0x4231

    def test_enumerates_responding_servos(self) -> None:
        wire = dxl_ping_status_packet(servo_id=3, model_number=1020, firmware=46)
        wire += dxl_ping_status_packet(servo_id=7, model_number=1190, firmware=52)
        port = _FakeDxlPort(wire)

        replies = dynamixel_broadcast_ping(port)

        assert port.written == [DXL_BROADCAST_PING]
        assert replies == [DxlPingReply(3, 1020, 46), DxlPingReply(7, 1190, 52)]

    def test_silent_bus_returns_empty_never_errors(self) -> None:
        assert dynamixel_broadcast_ping(_FakeDxlPort(b"")) == []

    def test_garbage_on_the_bus_is_not_an_error(self) -> None:
        assert dynamixel_broadcast_ping(_FakeDxlPort(b"\xff\x00\x12garbage" * 10)) == []

    def test_a_corrupt_crc_is_skipped_and_the_next_packet_still_parses(self) -> None:
        bad = bytearray(dxl_ping_status_packet(servo_id=3, model_number=1020, firmware=46))
        bad[-1] ^= 0xFF
        good = dxl_ping_status_packet(servo_id=4, model_number=350, firmware=1)

        assert parse_dxl_ping(bytes(bad) + good) == [DxlPingReply(4, 350, 1)]

    def test_an_endless_stream_is_bounded_by_the_read_budget(self) -> None:
        assert dynamixel_broadcast_ping(_EndlessZeros()) == []
        assert DXL_READ_BUDGET <= 4096

    def test_budget_seconds_stops_the_read_loop(self) -> None:
        port = _FakeDxlPort(dxl_ping_status_packet(servo_id=3, model_number=1020, firmware=46))
        assert dynamixel_broadcast_ping(port, budget_s=0.0) == []


class TestDynamixelRead:
    def test_read_request_matches_the_documented_bytes(self) -> None:
        assert dxl_read_request(1, PRESENT_POSITION) == READ_PRESENT_POSITION_ID1

    def test_read_status_parses_the_documented_reply(self) -> None:
        statuses = parse_dxl_status(READ_STATUS_ID1_166)

        assert len(statuses) == 1
        assert statuses[0].servo_id == 1 and statuses[0].error == 0
        assert int.from_bytes(statuses[0].params, "little", signed=True) == 166

    def test_read_register_round_trip(self) -> None:
        port = _FakeDxlPort(READ_STATUS_ID1_166)

        data = dxl_read_register(port, 1, PRESENT_POSITION)

        assert port.written == [READ_PRESENT_POSITION_ID1]
        assert data == b"\xa6\x00\x00\x00"

    def test_read_register_rejects_the_wrong_servo_size_or_a_failed_result(self) -> None:
        payload = b"\xa6\x00\x00\x00"
        other_servo = dxl_status_packet(2, payload)
        short = dxl_status_packet(1, payload[:2])
        failed = dxl_status_packet(1, payload, error=0x07)
        alert_only = dxl_status_packet(1, payload, error=0x80)

        assert dxl_read_register(_FakeDxlPort(other_servo), 1, PRESENT_POSITION) is None
        assert dxl_read_register(_FakeDxlPort(short), 1, PRESENT_POSITION) is None
        assert dxl_read_register(_FakeDxlPort(failed), 1, PRESENT_POSITION) is None
        assert dxl_read_register(_FakeDxlPort(b""), 1, PRESENT_POSITION) is None
        assert dxl_read_register(_FakeDxlPort(alert_only), 1, PRESENT_POSITION) == payload
