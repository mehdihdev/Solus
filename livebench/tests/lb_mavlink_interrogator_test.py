"""MAVLink heartbeat interrogator: listen-only; a HEARTBEAT within the budget names the
autopilot and vehicle, SERVO_OUTPUT_RAW counts the live actuator outputs, silence is None."""

from pathlib import Path
from typing import Any

from livebench.hardware.channel import Frame
from livebench.hardware.interrogator import InterrogatorRegistry, Safety, interrogate
from livebench.hardware.replay import ReplayChannel, load_recording
from livebench.plugins.mavlink.mavlink_codec import encode_mavlink
from livebench.plugins.mavlink.mavlink_definitions import HEARTBEAT
from livebench.plugins.mavlink.mavlink_interrogator import MavlinkHeartbeatInterrogator
from solus_api.fingerprint.contract import MatchState, Modality
from solus_api.hardware.config import TransportBinding, TransportKind

FIXTURE = Path(__file__).parent / "fixtures" / "mavlink_px4_quadrotor.json"


class _FrameChan:
    kind = TransportKind.USB_SERIAL

    def __init__(self, frames: list[bytes], params: dict[str, Any] | None = None) -> None:
        self.identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="5B42")
        self.frames = list(frames)
        self.params = params or {}

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return Frame(payload=self.frames.pop(0)) if self.frames else None

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


def test_probe_on_the_fixture_finds_a_px4_quadrotor_with_four_actuator_outputs() -> None:
    recording = load_recording(FIXTURE)
    channel = ReplayChannel(recording.identity.kind, recording.identity, recording.frames)
    registry = InterrogatorRegistry()
    registry.register(MavlinkHeartbeatInterrogator)
    (result,) = interrogate(channel, registry, budget_s=0.5)
    assert result.interrogator_id == "mavlink-heartbeat" and result.driver_id == "mavlink"
    assert result.params == {"system_id": 1, "component_id": 1, "protocol_version": 2}
    assert [(e.address, e.model) for e in result.bus_map] == [
        ("1:1", "PX4 autopilot"),
        *((f"servo:{n}", None) for n in (1, 2, 3, 4)),
    ]
    assert all(e.protocol == "mavlink" for e in result.bus_map)
    (evidence,) = result.evidence
    assert evidence.modality is Modality.BUS_ENUMERATION and evidence.state is MatchState.MATCHED
    assert evidence.confidence == 0.92 == result.confidence
    assert evidence.source_ref.source_connector == "mavlink"
    assert evidence.source_ref.external_ref == "ip:aa:bb:cc:dd:ee:ff/1:1"
    assert evidence.evidence["matched_on"] == "mavlink_heartbeat"
    assert evidence.evidence["value"] == "quadrotor"
    assert result.summary == "PX4 autopilot, quadrotor, 4 actuator outputs"
    assert result.details == {"vehicle_type": "quadrotor", "autopilot": "PX4"}
    assert MavlinkHeartbeatInterrogator.safety is Safety.LISTEN
    assert channel.sent == []  # listen-only: nothing was written to the link


def test_silence_within_the_budget_is_none() -> None:
    assert MavlinkHeartbeatInterrogator().probe(_FrameChan([]), budget_s=0.02) is None
    junk = _FrameChan([b"\xfd\x09not a frame at all"])
    assert MavlinkHeartbeatInterrogator().probe(junk, budget_s=0.02) is None


def test_unknown_codes_are_not_guessed_and_transport_params_are_carried() -> None:
    fields = {"type": 99, "autopilot": 8, "system_status": 3}
    frame = encode_mavlink(HEARTBEAT, fields, seq=0, system_id=7, component_id=1)
    channel = _FrameChan([frame], {"baud": 57600, "timeout_s": 0.1})
    result = MavlinkHeartbeatInterrogator().probe(channel, budget_s=0.05)
    assert result is not None
    assert result.params == {
        "baud": 57600,
        "timeout_s": 0.1,
        "system_id": 7,
        "component_id": 1,
        "protocol_version": 2,
    }
    assert result.bus_map[0].model is None and result.bus_map[0].address == "7:1"
    assert result.evidence[0].source_ref.external_ref == "usb:5B42/7:1"
    assert result.evidence[0].evidence["value"] is None
    assert result.summary == "unknown autopilot, unknown vehicle type, 0 actuator outputs"
    assert result.details == {"vehicle_type": None, "autopilot": None}
