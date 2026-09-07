"""R2 detection loop: enumerate → identify → interrogate (via the registry, at candidate
transport parameters) → propose. A proposal, never a decision; two matching repo configs are a
question, never a guess."""

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from livebench.hardware.channel import Channel, Frame, TransportRegistry, TransportUnavailableError
from livebench.hardware.detection import (
    DetectedDevice,
    Proposal,
    enumerate_devices,
    interrogate_device,
    propose,
)
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import Interrogation, InterrogatorRegistry, Safety
from livebench.hardware.registries import Registries
from livebench.hardware.repo_config import RepoConfigMatch, RepoPartDecl
from livebench.local import LocalDevice
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
