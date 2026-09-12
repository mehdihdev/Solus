"""R2 detection loop: enumerate → identify → interrogate (via the registry, at candidate
transport parameters) → propose. A proposal, never a decision; two matching repo configs are a
question, never a guess."""

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

import pytest
from livebench.hardware.channel import Channel, Frame, TransportRegistry, TransportUnavailableError
from livebench.hardware.detection import (
    DEFAULT_CANDIDATE_PARAMS,
    DetectedDevice,
    Proposal,
    enumerate_devices,
    headline_for,
    interrogate_device,
    propose,
    tone_for,
)
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import Interrogation, InterrogatorRegistry, Safety
from livebench.hardware.registries import Registries
from livebench.hardware.replay import ReplayChannel, load_recording
from livebench.hardware.repo_config import (
    RepoConfigMatch,
    RepoParserRegistry,
    RepoPartDecl,
    match_configs,
    scan_repo,
)
from livebench.local import LocalDevice, list_devices
from livebench.plugins import load_all
from livebench.recognition.passive import identify_port
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.config import BusMapEntry, TransportBinding, TransportKind, part_ref


class _Chan:
    kind = TransportKind.USB_SERIAL

    def __init__(self, identity: TransportBinding, params: Mapping[str, Any]) -> None:
        self.identity = identity
        self.params = dict(params)
        self.closed = False

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return None

    def flush_input(self) -> None: ...

    def close(self) -> None:
        self.closed = True


def _bus_evidence(ref: str) -> ModalityMatch:
    return ModalityMatch(
        modality=Modality.BUS_ENUMERATION,
        source_ref=SourceRef(source_connector="demo-bus", external_ref=ref),
        confidence=0.92,
        state=MatchState.MATCHED,
        evidence={"matched_on": "model_register", "value": "M1"},
    )


class _BusAt1M:
    """Answers only when the channel was opened at 1 Mbaud — like a real servo bus."""

    interrogator_id: ClassVar[str] = "demo-bus"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    safety: ClassVar[Safety] = Safety.PING

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        if getattr(channel, "params", {}).get("baud") != 1_000_000:
            return None
        ref = channel.identity.device_ref
        return Interrogation(
            interrogator_id=self.interrogator_id,
            driver_id="demo-bus",
            params={"protocol_version": 0},
            bus_map=[
                BusMapEntry(protocol="demo-bus", address="1", model="M1"),
                BusMapEntry(protocol="demo-bus", address="2", model="M1"),
            ],
            evidence=[_bus_evidence(part_ref(ref, "1")), _bus_evidence(part_ref(ref, "2"))],
            confidence=0.92,
            summary="2 servos on a serial servo bus (ids 1–2, M1)",
        )


def _detection_registries(opened: list[_Chan], *, busy: bool = False) -> Registries:
    transports = TransportRegistry()

    def opener(binding: TransportBinding, params: Mapping[str, Any]) -> Channel:
        if busy:
            raise TransportUnavailableError("port busy")
        channel = _Chan(binding, params)
        opened.append(channel)
        return channel

    transports.register(TransportKind.USB_SERIAL, opener)
    interrogators = InterrogatorRegistry()
    interrogators.register(_BusAt1M)
    return Registries(transports, DriverRegistry(), interrogators)


CH343 = identify_port(device="/dev/ttyACM0", vid=0x1A86, pid=0x55D3, serial="5B42134331")
TEENSY = identify_port(device="/dev/ttyACM1", vid=0x16C0, pid=0x0483, serial="TEENSY-1")
NO_SERIAL = identify_port(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001, serial=None)


def test_enumerate_reports_each_device_at_its_honest_level() -> None:
    devices = enumerate_devices(
        list_devices=lambda: [
            LocalDevice(CH343, "/dev/serial/by-id/usb-1a86-5B42134331", False),
            LocalDevice(TEENSY, None, False),
            LocalDevice(NO_SERIAL, None, True),
        ]
    )
    bridge, mcu, anonymous = devices
    assert bridge.device_ref == "usb:5B42134331" and bridge.level == "transport"
    assert bridge.mcu_known is False and bridge.board_class == "usb_bridge"
    assert bridge.identity is not None
    assert bridge.identity.last_seen_path == "/dev/serial/by-id/usb-1a86-5B42134331"
    assert mcu.level == "board" and mcu.mcu_known is True and mcu.board is not None
    assert anonymous.device_ref is None and anonymous.ambiguous is True
    assert all(isinstance(d, DetectedDevice) for d in devices)


def test_interrogate_tries_candidate_params_and_stops_at_the_first_answer() -> None:
    opened: list[_Chan] = []
    identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B42134331")
    results = interrogate_device(
        identity,
        registries=_detection_registries(opened),
        candidate_params=({"baud": 115200}, {"baud": 1_000_000}, {"baud": 9600}),
        budget_s=0.05,
    )
    assert [c.params["baud"] for c in opened] == [115200, 1_000_000]
    assert all(c.closed for c in opened)
    assert len(results) == 1 and results[0].params["baud"] == 1_000_000
    assert results[0].bus_map[0].address == "1"


def test_interrogate_reports_nothing_when_the_port_is_busy_or_silent() -> None:
    identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B42134331")
    assert (
        interrogate_device(identity, registries=_detection_registries([], busy=True), budget_s=0.05)
        == []
    )
    opened: list[_Chan] = []
    silent = interrogate_device(
        identity,
        registries=_detection_registries(opened),
        candidate_params=({"baud": 9600},),
        budget_s=0.05,
    )
    assert silent == [] and all(c.closed for c in opened)


def _bridge_device() -> DetectedDevice:
    return enumerate_devices(
        list_devices=lambda: [LocalDevice(CH343, "/dev/serial/by-id/x", False)]
    )[0]


def _bus_interrogation() -> Interrogation:
    identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B42134331")
    results = interrogate_device(
        identity,
        registries=_detection_registries([]),
        candidate_params=({"baud": 1_000_000},),
        budget_s=0.05,
    )
    assert results
    return results[0]


def _repo_match(
    config_id: str, names: tuple[str, str], calibration: str | None = None
) -> RepoConfigMatch:
    return RepoConfigMatch(
        config_id=config_id,
        parser_id="test",
        label=config_id,
        source=f"/repo/{config_id}.py",
        protocol_hint="demo-bus",
        parts=[
            RepoPartDecl(name=names[0], address="1", model="M1", calibration_source=calibration),
            RepoPartDecl(name=names[1], address="2", model="M1", calibration_source=calibration),
        ],
        calibration_source=calibration,
    )


def test_propose_without_repo_names_addresses_honestly() -> None:
    proposal = propose(_bridge_device(), [_bus_interrogation()], repo_matches=[])
    assert isinstance(proposal, Proposal)
    assert proposal.device_ref == "usb:5B42134331"
    assert proposal.driver_id == "demo-bus" and proposal.params["baud"] == 1_000_000
    assert [r.address for r in proposal.rows] == ["1", "2"]
    assert all(r.proposed_function is None for r in proposal.rows)
    assert proposal.rows[0].id == "usb:5B42134331/1"
    assert proposal.disambiguation is None
    assert "2 servos" in proposal.summary
    assert proposal.level == "protocol"


def test_propose_with_one_repo_match_names_the_parts_with_repo_provenance() -> None:
    follower = _repo_match("follower", ("shoulder_pan", "shoulder_lift"), "/cal/follower.json")
    proposal = propose(_bridge_device(), [_bus_interrogation()], repo_matches=[follower])
    assert [r.proposed_function for r in proposal.rows] == ["shoulder_pan", "shoulder_lift"]
    assert all(r.provenance == "repo" for r in proposal.rows)
    assert proposal.repo_matches[0].config_id == "follower"
    assert proposal.disambiguation is None
    assert "your repo says 1 is shoulder_pan" in proposal.summary
    assert "/cal/follower.json" in proposal.summary


def test_propose_with_two_repo_matches_asks_once_and_names_only_what_they_agree_on() -> None:
    leader = _repo_match("leader", ("shoulder_pan", "shoulder_lift"))
    follower = _repo_match("follower", ("shoulder_pan", "elbow"))
    proposal = propose(_bridge_device(), [_bus_interrogation()], repo_matches=[leader, follower])
    assert proposal.disambiguation is not None
    assert proposal.disambiguation.options == ["leader", "follower"]
    assert "Two configs" in proposal.disambiguation.question
    assert [r.proposed_function for r in proposal.rows] == ["shoulder_pan", None]


def test_a_calibration_signature_favours_the_config_it_matches_but_still_asks() -> None:
    """Two wire-identical arms: the parts' burned calibration is the one thing that tells
    them apart. It orders and annotates the question; it never answers it."""
    burned = dataclasses.replace(
        _bus_interrogation(),
        details={
            "calibration_signature": {"1": {"homing_offset": 1964}, "2": {"homing_offset": 508}}
        },
    )
    leader = dataclasses.replace(
        _repo_match("leader", ("shoulder_pan", "shoulder_lift")),
        parts=[
            RepoPartDecl(
                name="shoulder_pan", address="1", model="M1", calibration={"homing_offset": 1964}
            ),
            RepoPartDecl(
                name="shoulder_lift", address="2", model="M1", calibration={"homing_offset": 508}
            ),
        ],
    )
    follower = dataclasses.replace(
        _repo_match("follower", ("shoulder_pan", "shoulder_lift")),
        parts=[
            RepoPartDecl(
                name="shoulder_pan", address="1", model="M1", calibration={"homing_offset": -2043}
            ),
            RepoPartDecl(
                name="shoulder_lift", address="2", model="M1", calibration={"homing_offset": -1619}
            ),
        ],
    )
    proposal = propose(_bridge_device(), [burned], repo_matches=[follower, leader])
    assert proposal.disambiguation is not None
    assert proposal.disambiguation.favoured == ["leader"]
    assert proposal.disambiguation.options == ["leader", "follower"]  # favoured first, still asked
    assert "burned calibration matches leader" in proposal.disambiguation.question
    unmarked = propose(_bridge_device(), [_bus_interrogation()], repo_matches=[follower, leader])
    assert unmarked.disambiguation is not None and unmarked.disambiguation.favoured == []


def test_propose_with_no_interrogation_stays_at_the_transport_level() -> None:
    proposal = propose(_bridge_device(), [], repo_matches=[])
    assert proposal.level == "transport" and proposal.driver_id is None
    assert proposal.rows == []
    assert "no protocol recognised" in proposal.summary


def test_detection_module_names_no_vendor() -> None:
    import re

    import livebench.hardware.detection as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None


# ── SOLUSDEV-250 Phase 2: inference past the bridge ─────────────────────────────


def _device(vid: int, pid: int) -> DetectedDevice:
    identity = identify_port(device="/dev/ttyX", vid=vid, pid=pid, serial="S1")
    return enumerate_devices(list_devices=lambda: [LocalDevice(identity, None, False)])[0]


def _line_interrogation() -> Interrogation:
    """A shape-only answer: the framing interrogator recognised a line stream."""
    return dataclasses.replace(
        _bus_interrogation(),
        driver_id="raw-lines",
        confidence=0.25,
        summary="4 float channels at 50 Hz, no protocol recognised — name them?",
        details={"framing": "csv", "channel_count": 4, "update_hz": 50.0},
    )


@pytest.mark.parametrize(
    ("vid", "pid", "answer", "expected"),
    [
        (0x303A, 0x1001, "none", "an ESP32"),
        (0x2341, 0x0043, "none", "Arduino Uno R3"),
        (0x2341, 0xBEEF, "none", "an Arduino"),
        (0x1A86, 0x7523, "line", "Arduino-class board on USB"),
        (0x1A86, 0x7523, "bus", "something on USB"),  # a servo bus says nothing about its bridge
        (0x1A86, 0x7523, "none", "something on USB"),
        (0xDEAD, 0xBEEF, "line", "Arduino-class board on USB"),
        (0xDEAD, 0xBEEF, "bus", "something on USB"),
        (0xDEAD, 0xBEEF, "none", "something on USB"),
    ],
)
def test_headline_for_names_what_the_wire_can_honestly_claim(
    vid: int, pid: int, answer: str, expected: str
) -> None:
    best = {"none": None, "line": _line_interrogation(), "bus": _bus_interrogation()}[answer]
    assert headline_for(_device(vid, pid), best) == expected


def test_enumerate_sets_the_headline_without_a_stream() -> None:
    assert _device(0x1A86, 0x7523).headline == "something on USB"
    assert _device(0x303A, 0x1001).headline == "an ESP32"


def test_tone_follows_confidence_and_repo_agreement() -> None:
    best = _bus_interrogation()  # 0.92
    assert tone_for(None, []) == "something"
    assert tone_for(best, []) == "looks_like"
    weak = dataclasses.replace(best, confidence=0.25)
    assert tone_for(weak, []) == "something"
    assert tone_for(weak, [_repo_match("cfg", ("a", "b"))]) == "probably"
    assert tone_for(dataclasses.replace(best, confidence=0.6), []) == "probably"


def test_candidate_bauds_try_the_servo_bus_first_and_include_250k() -> None:
    assert [p["baud"] for p in DEFAULT_CANDIDATE_PARAMS] == [
        1_000_000,
        115_200,
        250_000,
        57_600,
        9_600,
    ]


def test_enumerate_binds_a_serial_less_device_to_its_port_position() -> None:
    at_port = identify_port(
        device="/dev/ttyUSB3", vid=0x1A86, pid=0x7523, serial=None, location="3-1.2"
    )
    nowhere = identify_port(device="/dev/ttyUSB9", vid=0x1A86, pid=0x7523, serial=None)
    devices = enumerate_devices(
        list_devices=lambda: list_devices(identities=[at_port, CH343, nowhere])
    )
    port, serial, anonymous = devices
    assert port.device_ref == "usb:port-3-1.2" and port.identity_basis == "port_position"
    assert port.ambiguous is False and port.identity is not None
    assert serial.identity_basis == "serial"
    assert anonymous.device_ref is None and anonymous.identity_basis == "none"
    twin = dataclasses.replace(at_port, device="/dev/ttyUSB4")
    twins = enumerate_devices(list_devices=lambda: list_devices(identities=[at_port, twin]))
    assert all(d.ambiguous for d in twins)


def test_a_bus_behind_a_bridge_keeps_its_plugin_summary_and_no_board_guess() -> None:
    proposal = propose(_bridge_device(), [_bus_interrogation()], repo_matches=[])
    assert proposal.stream is None and proposal.tone == "looks_like"
    assert proposal.headline == "something on USB"  # a servo bus says nothing about its bridge
    assert proposal.summary.startswith("2 servos on a serial servo bus")
    assert proposal.identity_basis == "serial"
    assert all(r.evidence for r in proposal.rows)


def test_a_line_stream_without_a_repo_match_is_honest_and_row_evidence_is_never_empty() -> None:
    proposal = propose(_bridge_device(), [_line_interrogation()], repo_matches=[])
    assert proposal.headline == "Arduino-class board on USB" and proposal.tone == "something"
    assert proposal.stream is not None and proposal.stream.channel_count == 4
    assert proposal.stream.channel_names is None
    assert proposal.summary == "Arduino-class board on USB · 4 channels at 50 Hz"
    assert all(r.evidence for r in proposal.rows)


def test_no_interrogation_still_carries_headline_tone_and_basis() -> None:
    proposal = propose(_bridge_device(), [], repo_matches=[])
    assert proposal.headline == "something on USB" and proposal.tone == "something"
    assert proposal.stream is None and proposal.identity_basis == "serial"
    assert "unknown" not in proposal.summary.lower()


# ── the fixture twin: a recorded four-column stream + the user's sketch ─────────

FIXTURES = Path(__file__).with_name("fixtures")


@pytest.fixture(scope="module")
def four_channel_run() -> tuple[DetectedDevice, list[Interrogation]]:
    """Drive the recording through the real plugin set (a realtime replay stands in for the
    serial port) and enumerate the serial-less bridge it came from by port position."""
    recording = load_recording(FIXTURES / "serial_bridge_four_channels.json")

    def open_recording(binding: TransportBinding, params: Mapping[str, Any]) -> ReplayChannel:
        channel = ReplayChannel(recording.identity.kind, binding, recording.frames, realtime=True)
        channel.params = dict(params)  # type: ignore[attr-defined]
        return channel

    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    registries.transports.register(TransportKind.USB_SERIAL, open_recording)
    load_all(registries)
    bridge = identify_port(
        device="/dev/ttyUSB3", vid=0x1A86, pid=0x7523, serial=None, location="3-1.2"
    )
    device = enumerate_devices(list_devices=lambda: list_devices(identities=[bridge]))[0]
    assert device.identity is not None and device.device_ref == recording.identity.device_ref
    interrogations = interrogate_device(
        device.identity,
        registries=registries,
        candidate_params=({"baud": 115200},),
        budget_s=0.7,
    )
    return device, interrogations


def _sketch_matches(sketch_dir: str, interrogations: list[Interrogation]) -> list[RepoConfigMatch]:
    registry = RepoParserRegistry()
    load_all(Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry(), registry))
    best = max(interrogations, key=lambda i: i.confidence)
    return match_configs(best.bus_map, scan_repo(FIXTURES / sketch_dir, registry))


def test_the_fixture_twin_names_the_stream_from_the_micropython_sketch(
    four_channel_run: tuple[DetectedDevice, list[Interrogation]],
) -> None:
    device, interrogations = four_channel_run
    proposal = propose(
        device, interrogations, repo_matches=_sketch_matches("sketch_micropython", interrogations)
    )
    assert proposal.headline == "Arduino-class board on USB"
    assert proposal.stream is not None
    assert proposal.stream.channel_count == 4
    assert proposal.stream.update_hz == pytest.approx(50.0, rel=0.10)
    assert proposal.stream.channel_names == ["motor_l", "motor_r", "dist", "batt"]
    assert proposal.stream.declared_hz == pytest.approx(50.0)
    assert proposal.tone == "probably"
    assert proposal.identity_basis == "port_position"
    assert proposal.summary == (
        "Arduino-class board on USB · 4 channels at 50 Hz · your sketch names them "
        "motor_l, motor_r, dist, batt at your sketch's rate"
    )
    assert [r.proposed_function for r in proposal.rows] == ["motor_l", "motor_r", "dist", "batt"]
    assert all(r.provenance == "repo" and r.evidence for r in proposal.rows)


def test_the_fixture_twin_names_the_stream_from_the_arduino_sketch(
    four_channel_run: tuple[DetectedDevice, list[Interrogation]],
) -> None:
    device, interrogations = four_channel_run
    proposal = propose(
        device, interrogations, repo_matches=_sketch_matches("sketch_arduino", interrogations)
    )
    assert proposal.stream is not None
    assert proposal.stream.channel_names == ["motorL", "motorR", "dist", "batt"]
    assert "your sketch names them motorL, motorR, dist, batt" in proposal.summary


# ── review fixes: forged port serials, wide streams, flagged print order, clipped text ──


def test_enumerate_never_lets_a_device_supplied_serial_forge_a_port_binding() -> None:
    forged = identify_port(
        device="/dev/ttyUSB5", vid=0x1A86, pid=0x7523, serial="port-3-1.2", location="3-1.9"
    )
    homeless = identify_port(device="/dev/ttyUSB6", vid=0x1A86, pid=0x7523, serial="port-x")
    at_port, none = enumerate_devices(
        list_devices=lambda: list_devices(identities=[forged, homeless])
    )
    assert at_port.device_ref == "usb:port-3-1.9" and at_port.identity_basis == "port_position"
    assert none.device_ref is None and none.identity_basis == "none"


def test_a_wide_stream_is_clamped_on_the_wire_and_the_summary_keeps_the_true_count() -> None:
    from livebench.local import _proposal_wire
    from solus_api.hardware.detect import ProposalOut

    wide = dataclasses.replace(
        _line_interrogation(),
        bus_map=[BusMapEntry(protocol="raw-lines", address=str(i), model=None) for i in range(200)],
        details={"framing": "csv", "channel_count": 200, "update_hz": 50.0},
    )
    sketch = RepoConfigMatch(
        config_id="sketch:big.ino",
        parser_id="sketch-print-order",
        label="big.ino",
        source="/repo/big.ino",
        protocol_hint="raw-lines",
        parts=[RepoPartDecl(name=f"ch{i}", address=str(i)) for i in range(200)],
        names_by_print_order=True,
    )
    proposal = propose(_bridge_device(), [wide], repo_matches=[sketch])
    assert proposal.stream is not None and proposal.stream.channel_count == 64
    assert proposal.stream.channel_names is not None
    assert len(proposal.stream.channel_names) == 64
    assert "200 channels at 50 Hz (showing 64)" in proposal.summary
    assert len(proposal.summary) <= 1024
    ProposalOut.model_validate(_proposal_wire(proposal))  # the API accepts it as sent


def test_the_print_order_clause_follows_the_flag_not_the_config_id_prefix() -> None:
    flagged = dataclasses.replace(_repo_match("cfg", ("a", "b")), names_by_print_order=True)
    summary = propose(_bridge_device(), [_line_interrogation()], repo_matches=[flagged]).summary
    assert "your sketch names them a, b" in summary
    unflagged = _repo_match("sketch:cfg", ("a", "b"))
    summary = propose(_bridge_device(), [_line_interrogation()], repo_matches=[unflagged]).summary
    assert "matches your sketch:cfg config" in summary


def test_repo_derived_fragments_in_the_summary_are_clipped() -> None:
    long_name, long_label, long_source = "n" * 200, "x" * 200, "/cal/" + "c" * 200
    match = _repo_match(long_label, (long_name, "b"), long_source)
    summary = propose(_bridge_device(), [_bus_interrogation()], repo_matches=[match]).summary
    for fragment in (long_label, long_name, long_source):
        assert fragment not in summary
        assert fragment[:63] + "…" in summary
