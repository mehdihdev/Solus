"""R2 Interrogator seam: the detection loop tries registered interrogators and never assumes a
servo bus; a ping or a listen is safe, commanding motion is not an interrogation."""

from typing import ClassVar

import pytest
from livebench.hardware.channel import Channel, Frame
from livebench.hardware.interrogator import (
    Interrogation,
    InterrogatorRegistry,
    Safety,
    interrogate,
)
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.config import BusMapEntry, TransportBinding, TransportKind


class _Chan:
    kind = TransportKind.USB_SERIAL

    def __init__(self) -> None:
        self.identity = TransportBinding(kind=TransportKind.USB_SERIAL, binding="ABC")
        self.flushes = 0

    def send(self, frame: Frame) -> None: ...

    def recv(self, max_bytes: int = 4096) -> Frame | None:
        return None

    def flush_input(self) -> None:
        self.flushes += 1

    def close(self) -> None: ...


def _match(ref: str, confidence: float = 0.9) -> ModalityMatch:
    return ModalityMatch(
        modality=Modality.BUS_ENUMERATION,
        source_ref=SourceRef(source_connector="bench", external_ref=ref),
        confidence=confidence,
        state=MatchState.MATCHED,
        evidence={"matched_on": "test"},
    )


class _PingBus:
    interrogator_id: ClassVar[str] = "demo-ping"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    safety: ClassVar[Safety] = Safety.PING

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        ref = channel.identity.device_ref
        return Interrogation(
            interrogator_id=self.interrogator_id,
            driver_id="demo-bus",
            params={"baud": 1_000_000},
            bus_map=[BusMapEntry(protocol="demo-bus", address="1", model="M1")],
            evidence=[_match(f"{ref}/1")],
            confidence=0.9,
            summary="one M1 at address 1",
        )


class _Silent:
    interrogator_id: ClassVar[str] = "demo-silent"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    safety: ClassVar[Safety] = Safety.LISTEN

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        return None


class _Broken:
    interrogator_id: ClassVar[str] = "demo-broken"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    safety: ClassVar[Safety] = Safety.PASSIVE

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        raise RuntimeError("boom")


class _CanOnly:
    interrogator_id: ClassVar[str] = "demo-can"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_CAN})
    safety: ClassVar[Safety] = Safety.LISTEN

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        raise AssertionError("must never run on a serial channel")


def test_interrogate_collects_only_positive_results_and_never_raises() -> None:
    registry = InterrogatorRegistry()
    for cls in (_Broken, _Silent, _PingBus, _CanOnly):
        registry.register(cls)
    channel = _Chan()
    results = interrogate(channel, registry, budget_s=0.5)
    assert [r.interrogator_id for r in results] == ["demo-ping"]
    assert results[0].bus_map[0].address == "1"
    assert results[0].evidence[0].source_ref.external_ref == "usb:ABC/1"
    assert channel.flushes >= 1  # the loop flushes stale bytes between probes


def test_registry_refuses_duplicates_and_unknown_ids() -> None:
    registry = InterrogatorRegistry()
    registry.register(_PingBus)
    with pytest.raises(ValueError):
        registry.register(_PingBus)
    with pytest.raises(KeyError):
        registry.get("nope")
    assert [c["interrogator_id"] for c in registry.catalog()] == ["demo-ping"]


def test_safety_classes_are_passive_ping_listen_only() -> None:
    assert [s.value for s in Safety] == ["passive", "ping", "listen"]


def test_an_interrogation_is_a_proposal_input_not_a_decision() -> None:
    result = _PingBus().probe(_Chan(), budget_s=0.1)
    assert result is not None
    assert 0 <= result.confidence <= 1
    assert result.driver_id == "demo-bus" and result.params == {"baud": 1_000_000}


def test_interrogator_module_names_no_vendor() -> None:
    import re
    from pathlib import Path

    import livebench.hardware.interrogator as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None
