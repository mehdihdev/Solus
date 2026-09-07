"""Dynamixel bus interrogator: a broadcast ping (safety PING) over the channel; every responder
is a self-asserted identity (0.92) keyed `<device ref>/<id>`; an unknown model number is
reported as a number, never guessed into a name; silence means the channel is not ours."""

from livebench.hardware.channel import Frame, TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry, Safety, interrogate
from livebench.hardware.registries import Registries
from livebench.hardware.replay import ReplayChannel
from livebench.plugins import PLUGIN_MODULES
from livebench.plugins.dynamixel.dynamixel_codec import DXL_BROADCAST_PING, dxl_ping_status_packet
from livebench.plugins.dynamixel.dynamixel_interrogator import DynamixelBusInterrogator
from solus_api.fingerprint.contract import MatchState, Modality
from solus_api.hardware.config import TransportBinding, TransportKind

IDENTITY = TransportBinding(kind=TransportKind.USB_SERIAL, binding="ABC")


class _DxlChan:
    """A USB-serial channel fake that knows the transport params it was opened with."""

    kind = TransportKind.USB_SERIAL

    def __init__(self, wire: bytes, params: dict[str, object] | None = None) -> None:
        self.identity = IDENTITY
        self.params = dict(params or {})
        self._wire = wire
        self.sent: list[Frame] = []

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        chunk, self._wire = self._wire[:max_bytes], self._wire[max_bytes:]
        return Frame(payload=chunk) if chunk else None

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


def _two_servos() -> bytes:
    return dxl_ping_status_packet(
        servo_id=3, model_number=1020, firmware=46
    ) + dxl_ping_status_packet(servo_id=7, model_number=9999, firmware=1)


def test_probe_reports_each_responder_with_bus_map_and_evidence() -> None:
    channel = _DxlChan(_two_servos(), {"baud": 1_000_000, "timeout_s": 0.05})

    result = DynamixelBusInterrogator().probe(channel, budget_s=0.2)

    assert result is not None
    assert channel.sent == [Frame(payload=DXL_BROADCAST_PING)]
    assert result.interrogator_id == "dynamixel-2" and result.driver_id == "dynamixel-2"
    assert result.params == {"baud": 1_000_000, "protocol_version": 2}
    assert [(e.protocol, e.address, e.model) for e in result.bus_map] == [
        ("dynamixel-2", "3", "XM430-W350"),
        ("dynamixel-2", "7", None),
    ]
    assert result.confidence == 0.92
    assert "2" in result.summary
    first, second = result.evidence
    assert first.modality is Modality.BUS_ENUMERATION
    assert first.state is MatchState.MATCHED and first.confidence == 0.92
    assert first.source_ref.source_connector == "dynamixel-2"
    assert first.source_ref.external_ref == "usb:ABC/3"
    assert first.evidence["matched_on"] == "model_register"
    assert first.evidence["value"] == "1020"
    assert "XM430-W350" in first.evidence["note"]
    assert second.source_ref.external_ref == "usb:ABC/7"
    assert second.evidence["value"] == "9999" and "9999" in second.evidence["note"]


def test_silent_bus_is_not_ours() -> None:
    assert DynamixelBusInterrogator().probe(_DxlChan(b""), budget_s=0.1) is None
    assert DynamixelBusInterrogator().probe(_DxlChan(b"junk" * 50), budget_s=0.1) is None


def test_params_omit_the_baud_when_the_channel_does_not_know_it() -> None:
    from livebench.hardware.replay import RecordedFrame

    channel = ReplayChannel(
        TransportKind.USB_SERIAL, IDENTITY, [RecordedFrame(at_s=0.0, payload=_two_servos())]
    )

    result = DynamixelBusInterrogator().probe(channel, budget_s=0.1)

    assert result is not None and result.params == {"protocol_version": 2}


def test_runs_under_the_detection_loop_as_a_ping_probe() -> None:
    registry = InterrogatorRegistry()
    registry.register(DynamixelBusInterrogator)
    assert registry.get("dynamixel-2").safety is Safety.PING

    results = interrogate(_DxlChan(_two_servos()), registry, budget_s=0.1)

    assert [r.interrogator_id for r in results] == ["dynamixel-2"]


def test_plugin_registers_driver_and_interrogator() -> None:
    import livebench.plugins.dynamixel as plugin

    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    plugin.register(registries)

    assert registries.drivers.get("dynamixel-2").display_name
    assert registries.interrogators.get("dynamixel-2").safety is Safety.PING
    assert "livebench.plugins.dynamixel" in PLUGIN_MODULES
