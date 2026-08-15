"""RBT-01: passive identification — honest about exactly what the wire can say."""

import os

import pytest
from livebench.recognition.passive import (
    DXL_BROADCAST_PING,
    BoardClass,
    StreamShape,
    characterize_stream,
    dynamixel_broadcast_ping,
    identify_odrive_heartbeats,
    identify_port,
    resolve_board,
)
from solus_api.fingerprint.contract import MatchState, Modality


class TestUsbEnumeration:
    def test_known_mcu_board_resolves_with_bus_confidence(self) -> None:
        identity = identify_port(device="/dev/ttyACM1", vid=0x16C0, pid=0x0483, serial="12345")

        assert identity.board is not None
        assert "Teensy" in identity.board.name
        assert identity.board.kind is BoardClass.MCU_BOARD
        match = identity.evidence
        assert match.modality is Modality.BUS_ENUMERATION
        assert match.state is MatchState.MATCHED
        assert 0.8 <= match.confidence <= 0.92
        assert match.source_ref.external_ref == "/dev/ttyACM1/16c0:0483"

    def test_usb_bridge_identifies_the_bridge_and_says_mcu_unknown(self) -> None:
        # The CH343 case: the bridge chip has identity; whatever MCU sits behind
        # it does NOT — and this layer must never guess.
        identity = identify_port(device="/dev/ttyACM0", vid=0x1A86, pid=0x55D3, serial="5B42")

        assert identity.board is not None
        assert identity.board.kind is BoardClass.USB_BRIDGE
        assert identity.mcu_known is False
        assert "unknown" in identity.evidence.evidence["note"].lower()
        assert identity.evidence.state is MatchState.LOW_CONFIDENCE

    def test_unknown_vid_pid_reports_unknown_not_a_guess(self) -> None:
        identity = identify_port(device="/dev/ttyUSB9", vid=0xDEAD, pid=0xBEEF, serial=None)

        assert identity.board is None
        assert identity.mcu_known is False
        assert identity.evidence.state is MatchState.LOW_CONFIDENCE
        assert identity.evidence.confidence <= 0.1
        assert "unknown" in identity.evidence.evidence["note"].lower()

    def test_resolve_board_table_is_keyed_by_vid_pid(self) -> None:
        assert resolve_board(0x1A86, 0x55D3) is not None
        assert resolve_board(0x0000, 0x0000) is None


class TestDynamixelPing:
    def test_broadcast_ping_frame_matches_the_documented_bytes(self) -> None:
        # Golden bytes from the ROBOTIS Protocol 2.0 spec — proves the CRC16 too.
        assert DXL_BROADCAST_PING == bytes.fromhex("fffffd00fe03000131 42".replace(" ", ""))

    def test_enumerates_responding_servos_with_model_names(self) -> None:
        from livebench.recognition.passive import _dxl_status_packet

        wire = _dxl_status_packet(servo_id=3, model_number=1020, firmware=46)
        wire += _dxl_status_packet(servo_id=7, model_number=1190, firmware=52)

        class FakePort:
            port: str | None = "/dev/ttyUSB0"
            written: list[bytes] = []

            def write(self, data: bytes) -> int:
                self.written.append(data)
                return len(data)

            def read(self, size: int) -> bytes:
                nonlocal wire
                chunk, wire = wire[:size], wire[size:]
                return chunk

        findings = dynamixel_broadcast_ping(FakePort())

        assert FakePort.written == [DXL_BROADCAST_PING]
        assert len(findings) == 2
        first = findings[0]
        assert first.modality is Modality.BUS_ENUMERATION
        assert first.state is MatchState.MATCHED
        assert first.confidence == 0.92
        assert first.source_ref.external_ref == "/dev/ttyUSB0/id:3"
        assert first.evidence["value"] == "1020"
        assert "XM430-W350" in first.evidence["note"]

    def test_silent_bus_returns_empty_never_errors(self) -> None:
        class DeadPort:
            port: str | None = "/dev/ttyUSB0"

            def write(self, data: bytes) -> int:
                return len(data)

            def read(self, size: int) -> bytes:
                return b""

        assert dynamixel_broadcast_ping(DeadPort()) == []

    def test_garbage_on_the_bus_is_not_an_error(self) -> None:
        class NoisyPort:
            port: str | None = "/dev/ttyUSB0"
            _junk = b"\xff\x00\x12garbage" * 10

            def write(self, data: bytes) -> int:
                return len(data)

            def read(self, size: int) -> bytes:
                chunk, self._junk = self._junk[:size], self._junk[size:]
                return chunk

        assert dynamixel_broadcast_ping(NoisyPort()) == []


class TestOdriveHeartbeats:
    def test_heartbeats_identify_nodes(self) -> None:
        frames = [
            (0x021, b"\x00\x00\x00\x00\x08\x00\x00\x00"),  # node 1, heartbeat (cmd 0x01)
            (0x041, b"\x00\x00\x00\x00\x08\x00\x00\x00"),  # node 2
            (0x022, b"\x00\x00"),  # node 1, some other command — ignored
        ]

        findings = identify_odrive_heartbeats(frames, interface="can0")

        refs = [f.source_ref.external_ref for f in findings]
        assert refs == ["can0/node:1", "can0/node:2"]
        assert all(f.state is MatchState.MATCHED for f in findings)
        assert all(f.confidence == 0.92 for f in findings)

    def test_no_heartbeats_returns_empty(self) -> None:
        assert identify_odrive_heartbeats([(0x123, b"\x01")], interface="can0") == []


class TestStreamShape:
    def test_json_lines_stream_characterized(self) -> None:
        samples = [(i * 0.01, b'{"a": %d.5, "b": -2.0, "c": 100}' % i) for i in range(50)]

        shape = characterize_stream(samples, port_name="/dev/ttyACM0", baud=115200)

        assert isinstance(shape, StreamShape)
        assert shape.framing == "json-lines"
        assert shape.channel_count == 3
        assert shape.update_hz == pytest.approx(100.0, rel=0.05)
        assert shape.baud == 115200
        assert shape.channel_ranges["b"] == (-2.0, -2.0)
        evidence = shape.evidence
        assert evidence.modality is Modality.TELEMETRY_CHANNEL
        assert evidence.state is MatchState.LOW_CONFIDENCE
        assert evidence.confidence <= 0.30  # shape constrains, it does not identify

    def test_csv_stream_characterized(self) -> None:
        samples = [(i * 0.02, b"1.5,-2.0,3.7") for i in range(30)]

        shape = characterize_stream(samples, port_name="/dev/ttyUSB1", baud=9600)

        assert shape.framing == "csv"
        assert shape.channel_count == 3
        assert shape.update_hz == pytest.approx(50.0, rel=0.05)

    def test_binary_or_silent_stream_is_a_valid_result_not_an_error(self) -> None:
        binary = characterize_stream(
            [(0.0, b"\x00\x01\x82\xff"), (0.1, b"\x99\x88")], port_name="/dev/x", baud=115200
        )
        silent = characterize_stream([], port_name="/dev/x", baud=115200)

        assert binary.framing == "binary"
        assert binary.channel_count == 0
        assert silent.framing == "silent"
        assert silent.update_hz == 0.0


@pytest.mark.skipif(not os.path.exists("/dev/serial/by-id"), reason="no serial hardware attached")
def test_live_enumeration_reports_the_real_ch343_as_bridge_with_unknown_mcu() -> None:
    """The live honest-unknown case on this bench: enumeration only, no port open."""
    from livebench.recognition.passive import enumerate_usb_serial

    identities = enumerate_usb_serial()

    ch343 = [i for i in identities if i.vid == 0x1A86 and i.pid == 0x55D3]
    assert ch343, "the CH343 bridge on this bench should enumerate"
    assert ch343[0].board is not None
    assert ch343[0].board.kind is BoardClass.USB_BRIDGE
    assert ch343[0].mcu_known is False
