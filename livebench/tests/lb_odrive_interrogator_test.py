"""ODrive CAN interrogator (safety LISTEN): receive for the budget, every heartbeat node becomes a
bus-map entry (`0x10`, model None — the heartbeat carries no model) with bus-enumeration
evidence at 0.92; silence means the channel is not ours."""

from pathlib import Path

from livebench.hardware.channel import Frame, TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry, Safety, interrogate
from livebench.hardware.registries import Registries
from livebench.hardware.replay import ReplayChannel, load_recording
from livebench.plugins import PLUGIN_MODULES
from livebench.plugins.odrive.odrive_codec import odrive_pack_pair
from livebench.plugins.odrive.odrive_interrogator import OdriveCanInterrogator
from solus_api.fingerprint.contract import MatchState, Modality
from solus_api.hardware.config import TransportBinding, TransportKind

FIXTURE = Path(__file__).parent / "fixtures" / "can_odrive_base.json"
IDENTITY = TransportBinding(kind=TransportKind.USB_CAN, binding="ODRV-3F2A-CAN0")


class _CanChan:
    """A CAN channel fake that knows the transport params it was opened with."""

    kind = TransportKind.USB_CAN

    def __init__(self, frames: list[Frame], params: dict[str, object] | None = None) -> None:
        self.identity = IDENTITY
        self.params = dict(params or {})
        self._frames = list(frames)

    def send(self, frame: Frame) -> None:
        raise AssertionError("a listener never transmits")

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return self._frames.pop(0) if self._frames else None

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


def test_probe_reports_each_heartbeat_node_from_the_fixture() -> None:
    recording = load_recording(FIXTURE)
    channel = ReplayChannel(TransportKind.USB_CAN, IDENTITY, recording.frames)

    result = OdriveCanInterrogator().probe(channel, budget_s=0.05)

    assert result is not None
    assert result.interrogator_id == "odrive-can" and result.driver_id == "odrive-can"
    assert result.params == {}  # a replay channel does not know its bitrate
    assert [(e.protocol, e.address, e.model) for e in result.bus_map] == [
        ("odrive-can", "0x10", None),
        ("odrive-can", "0x11", None),
    ]
    assert result.confidence == 0.92 and "0x10" in result.summary
    first, second = result.evidence
    assert first.modality is Modality.BUS_ENUMERATION
    assert first.state is MatchState.MATCHED and first.confidence == 0.92
    assert first.source_ref.source_connector == "odrive-can"
    assert first.source_ref.external_ref == "can:ODRV-3F2A-CAN0/0x10"
    assert second.source_ref.external_ref == "can:ODRV-3F2A-CAN0/0x11"
    assert first.evidence["matched_on"] == "can_heartbeat" and first.evidence["value"] == "16"
    assert "no model" in first.evidence["note"].lower()


def test_params_carry_the_bitrate_the_channel_was_opened_with() -> None:
    heartbeat = Frame(payload=bytes.fromhex("0000000008000100"), address="0x221")
    channel = _CanChan([heartbeat], {"bitrate": 500_000, "interface": "socketcan"})

    result = OdriveCanInterrogator().probe(channel, budget_s=0.02)

    assert result is not None and result.params == {"bitrate": 500_000}
    assert [e.address for e in result.bus_map] == ["0x11"]


def test_a_bus_without_heartbeats_is_not_ours() -> None:
    encoder_only = [Frame(payload=odrive_pack_pair(0.0, 1.5), address="0x209")]
    assert OdriveCanInterrogator().probe(_CanChan(encoder_only), budget_s=0.02) is None
    assert OdriveCanInterrogator().probe(_CanChan([]), budget_s=0.02) is None
    junk = [Frame(payload=b"\x00" * 8, address="zz"), Frame(payload=b"\x00" * 8)]
    assert OdriveCanInterrogator().probe(_CanChan(junk), budget_s=0.02) is None


def test_runs_under_the_detection_loop_as_a_listen_probe() -> None:
    registry = InterrogatorRegistry()
    registry.register(OdriveCanInterrogator)
    assert registry.get("odrive-can").safety is Safety.LISTEN
    heartbeat = Frame(payload=bytes.fromhex("0000000008000100"), address="0x201")

    results = interrogate(_CanChan([heartbeat]), registry, budget_s=0.02)

    assert [r.interrogator_id for r in results] == ["odrive-can"]


def test_plugin_registers_driver_and_interrogator_but_no_transport() -> None:
    import livebench.plugins.odrive as plugin

    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    plugin.register(registries)

    assert registries.drivers.get("odrive-can").display_name
    assert registries.interrogators.get("odrive-can").safety is Safety.LISTEN
    assert registries.transports.kinds() == []  # USB-CAN is a shared transport, wired centrally
    assert "livebench.plugins.odrive" in PLUGIN_MODULES
