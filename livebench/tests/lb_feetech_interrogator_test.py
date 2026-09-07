"""Feetech bus interrogator (SOLUSDEV-248 R2): a ping sweep is an interrogation; commanding
motion is not. Evidence is CTR-08 BUS_ENUMERATION at ≤ 0.92; unknown models stay numbers."""

from lb_feetech_codec_test import FeetechFakeChannel
from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry, Safety, interrogate
from livebench.hardware.registries import Registries
from livebench.plugins.feetech import register
from livebench.plugins.feetech.feetech_interrogator import FeetechBusInterrogator
from solus_api.fingerprint.contract import MatchState, Modality
from solus_api.hardware.config import TransportKind

_ARM = dict.fromkeys(range(1, 7), 2047)


def test_six_servos_become_a_bus_map_with_evidence_per_servo() -> None:
    channel = FeetechFakeChannel(_ARM, models=dict.fromkeys(range(1, 7), 777))
    result = FeetechBusInterrogator().probe(channel, budget_s=1.0)
    assert result is not None
    assert result.interrogator_id == "feetech-bus" and result.driver_id == "feetech-sts"
    assert result.params == {"baud": 1_000_000, "protocol_version": 0}
    assert [(e.protocol, e.address, e.model) for e in result.bus_map] == [
        ("feetech-sts", str(i), "STS3215") for i in range(1, 7)
    ]
    assert len(result.evidence) == 6 and result.confidence == 0.92
    match = result.evidence[0]
    assert match.modality is Modality.BUS_ENUMERATION and match.state is MatchState.MATCHED
    assert match.source_ref.source_connector == "feetech-sts"
    assert match.source_ref.external_ref == "usb:5B42134331/1"
    assert match.confidence == 0.92
    assert match.evidence["matched_on"] == "model_register" and match.evidence["value"] == "777"
    assert "STS3215" in match.evidence["note"]
    assert result.summary == "6 servos on a serial servo bus (ids 1–6, STS3215)"


def test_silence_is_not_ours() -> None:
    assert FeetechBusInterrogator().probe(FeetechFakeChannel({}), budget_s=0.5) is None


def test_zero_budget_asks_nothing() -> None:
    channel = FeetechFakeChannel(_ARM)
    assert FeetechBusInterrogator().probe(channel, budget_s=0.0) is None
    assert channel.sent == []


def test_unknown_model_and_unknown_baud_are_reported_not_guessed() -> None:
    channel = FeetechFakeChannel({4: 0, 7: 0}, models={4: 54321}, params={})
    result = FeetechBusInterrogator().probe(channel, budget_s=1.0)
    assert result is not None
    assert result.params == {"protocol_version": 0}  # the channel did not say its baud
    assert [e.model for e in result.bus_map] == [None, None]
    known, silent = result.evidence
    assert known.evidence["value"] == "54321" and "not in" in known.evidence["note"]
    assert silent.evidence["value"] is None and "did not answer" in silent.evidence["note"]
    assert result.summary == "2 servos on a serial servo bus (ids 4, 7, model 54321, model unknown)"


def test_one_servo_summary_is_singular() -> None:
    result = FeetechBusInterrogator().probe(
        FeetechFakeChannel({3: 0}, models={3: 777}), budget_s=1.0
    )
    assert result is not None
    assert result.summary == "1 servo on a serial servo bus (id 3, STS3215)"


def test_a_probe_never_writes_to_the_bus() -> None:
    channel = FeetechFakeChannel(_ARM)
    FeetechBusInterrogator().probe(channel, budget_s=1.0)
    assert channel.sent and {frame[4] for frame in channel.sent} <= {0x01, 0x02}  # ping, read


def test_register_wires_the_plugin_into_the_shared_seams() -> None:
    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    register(registries)
    assert registries.drivers.get("feetech-sts").driver_id == "feetech-sts"
    interrogator = registries.interrogators.get("feetech-bus")
    assert interrogator.safety is Safety.PING
    assert interrogator.transports == frozenset({TransportKind.USB_SERIAL})
    channel = FeetechFakeChannel(_ARM, models=dict.fromkeys(range(1, 7), 777))
    (result,) = interrogate(channel, registries.interrogators, budget_s=0.5)
    assert len(result.bus_map) == 6 and result.driver_id == "feetech-sts"


def test_burned_homing_offsets_become_the_calibration_signature() -> None:
    """One more register per servo tells two wire-identical arms apart: the offsets each
    arm's calibration burned into its servos, decoded from sign-magnitude."""
    channel = FeetechFakeChannel(
        {1: 2047, 2: 2761}, models={1: 777, 2: 777}, homing={1: 1964, 2: 0x800 | 589}
    )
    result = FeetechBusInterrogator().probe(channel, budget_s=0.2)
    assert result is not None
    assert result.details == {
        "calibration_signature": {"1": {"homing_offset": 1964}, "2": {"homing_offset": -589}}
    }


def test_a_bus_without_readable_offsets_carries_no_signature() -> None:
    channel = FeetechFakeChannel({1: 2047}, models={1: 777})
    result = FeetechBusInterrogator().probe(channel, budget_s=0.2)
    assert result is not None and result.details == {}
