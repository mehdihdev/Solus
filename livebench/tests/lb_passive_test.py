"""RBT-01: passive identification — honest about exactly what the wire can say. Vendor probes
(servo-bus ping, CAN heartbeats) live in their plugins; this module stays vendor-free."""

import os
import re
from pathlib import Path

import pytest
from livebench.recognition.passive import (
    BOARD_TABLE,
    BoardClass,
    StreamShape,
    characterize_stream,
    identify_port,
    resolve_board,
)
from solus_api.fingerprint.contract import MatchState, Modality

VENDOR_WORDS = re.compile(
    r"\b(teensy|pjrc|arduino|espressif|esp32|adafruit|raspberry|rp2040|wch|ch343|ch340|ch9102"
    r"|silicon labs|cp210x?|ftdi|ft232|prolific|pl2303|dynamixel|robotis|odrive|feetech"
    r"|sts3215|lerobot|mavlink|px4)\b"
)


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

    def test_board_table_is_data_from_the_definitions_package(self) -> None:
        from livebench.definitions import usb_boards

        assert BOARD_TABLE is usb_boards.BOARD_TABLE
        assert all(isinstance(board.kind, BoardClass) for board in BOARD_TABLE.values())


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


def test_passive_module_names_no_vendor_or_product() -> None:
    """Shared detection code: the vendor probes moved to plugins, the board table to
    definitions — nothing product-specific may remain here (hardware-onboarding.md ratchet)."""
    import livebench.recognition.passive as module

    source = Path(module.__file__).read_text().lower()
    assert VENDOR_WORDS.search(source) is None


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


class TestPortLocation:
    def test_location_is_the_usb_topology_before_the_interface_suffix(self) -> None:
        from livebench.recognition.passive import _location_of

        assert _location_of("3-1.4.1.1.3:1.0") == "3-1.4.1.1.3"
        assert _location_of("3-1.2") == "3-1.2"
        assert _location_of(None) is None and _location_of("") is None

    def test_identify_port_carries_the_location(self) -> None:
        identity = identify_port(
            device="/dev/ttyUSB0", vid=0x1A86, pid=0x7523, serial=None, location="3-1.2"
        )
        assert identity.location == "3-1.2"
        assert identify_port(device="/dev/x", vid=1, pid=2, serial="S").location is None


class TestBindingOf:
    def test_a_device_supplied_serial_can_never_mint_a_port_key(self) -> None:
        from livebench.recognition.passive import binding_key, binding_of

        forged = identify_port(device="/dev/x", vid=1, pid=2, serial="port-3-1.2", location="3-1.9")
        assert binding_of(forged) == ("port-3-1.9", "port_position")
        assert binding_key(forged) == "port-3-1.9"
        homeless = identify_port(device="/dev/x", vid=1, pid=2, serial="port-x")
        assert binding_of(homeless) == (None, "none")
        assert binding_key(homeless) is None

    def test_binding_of_names_the_branch_that_produced_the_key(self) -> None:
        from livebench.recognition.passive import binding_of

        assert binding_of(identify_port(device="/dev/x", vid=1, pid=2, serial="S1")) == (
            "S1",
            "serial",
        )
        at_port = identify_port(device="/dev/x", vid=1, pid=2, serial=None, location="3-1.2")
        assert binding_of(at_port) == ("port-3-1.2", "port_position")
