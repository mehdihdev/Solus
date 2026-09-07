"""ODrive CANSimple codec (heartbeat parsing moved out of recognition/passive.py, SOLUSDEV-248):
arbitration id = node << 5 | cmd; heartbeats name nodes; encoder, Iq and bus-voltage frames
decode to float32-LE pairs; anything else is silently not ours."""

import math
import struct

from livebench.plugins.odrive.odrive_codec import (
    OdriveReading,
    decode_odrive_frame,
    odrive_arbitration_id,
    odrive_heartbeat_nodes,
    odrive_pack_pair,
    odrive_split_id,
)

HEARTBEAT = b"\x00\x00\x00\x00\x08\x00\x00\x00"


class TestOdriveHeartbeats:
    def test_heartbeats_identify_nodes(self) -> None:
        frames = [
            (0x021, HEARTBEAT),  # node 1, heartbeat (cmd 0x01)
            (0x041, HEARTBEAT),  # node 2
            (0x022, b"\x00\x00"),  # node 1, some other command — ignored
            (0x041, HEARTBEAT),  # node 2 again — one node, once
        ]

        assert odrive_heartbeat_nodes(frames) == [1, 2]

    def test_no_heartbeats_returns_empty(self) -> None:
        assert odrive_heartbeat_nodes([(0x123, b"\x01")]) == []
        assert odrive_heartbeat_nodes([(0x021, b"\x00\x00\x00")]) == []  # a short heartbeat

    def test_arbitration_id_round_trip(self) -> None:
        assert odrive_arbitration_id(0x10, 0x01) == 0x201
        assert odrive_split_id(0x201) == (0x10, 0x01)
        assert odrive_split_id(0x229) == (0x11, 0x09)


class TestOdriveDecoders:
    def test_encoder_estimates(self) -> None:
        reading = decode_odrive_frame(0x209, odrive_pack_pair(3.25, 1.5))

        assert reading == OdriveReading(0x10, 0x09, {"pos_estimate": 3.25, "vel_estimate": 1.5})

    def test_get_iq(self) -> None:
        reading = decode_odrive_frame(0x214, odrive_pack_pair(2.0, 1.9))

        assert reading is not None and reading.node == 0x10
        assert reading.fields["iq_setpoint"] == 2.0
        assert math.isclose(reading.fields["iq_measured"], 1.9, rel_tol=1e-6)

    def test_bus_voltage_current(self) -> None:
        reading = decode_odrive_frame(0x237, odrive_pack_pair(24.1, 1.2))

        assert reading is not None and reading.node == 0x11 and reading.cmd == 0x17
        assert math.isclose(reading.fields["bus_voltage"], 24.1, rel_tol=1e-6)
        assert math.isclose(reading.fields["bus_current"], 1.2, rel_tol=1e-6)

    def test_other_commands_short_frames_and_bad_nodes_are_not_readings(self) -> None:
        assert decode_odrive_frame(0x201, HEARTBEAT) is None  # a heartbeat carries no signal
        assert decode_odrive_frame(0x20B, odrive_pack_pair(1.0, 2.0)) is None  # cmd 0x0b
        assert decode_odrive_frame(0x209, b"\x00\x00\x00") is None
        assert decode_odrive_frame(0x1FE9, odrive_pack_pair(1.0, 2.0)) is None  # node 0xff

    def test_non_finite_floats_are_dropped_field_by_field(self) -> None:
        reading = decode_odrive_frame(0x209, struct.pack("<ff", math.nan, 1.5))

        assert reading == OdriveReading(0x10, 0x09, {"vel_estimate": 1.5})
        assert decode_odrive_frame(0x209, struct.pack("<ff", math.inf, math.nan)) is None
