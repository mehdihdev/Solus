"""Feetech bus interrogator (R2): a ping sweep over ids 1–12, then the model register of every
responder. Safety `ping` — no servo interprets a PING or a READ as a command; motion stays behind
the confirmation gate. Evidence is CTR-08 BUS_ENUMERATION at the ≤ 0.92 band; an unknown model
number is reported as a number, never guessed into a part name."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, ClassVar, Final

from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.config import BusMapEntry, TransportKind, part_ref

from livebench.hardware.channel import Channel, as_bus_port
from livebench.hardware.interrogator import Interrogation, Safety
from livebench.plugins.feetech.feetech_codec import FeetechBus, FeetechCodec, FeetechServo
from livebench.plugins.feetech.feetech_definitions import DEFAULT_CANDIDATE_IDS
from livebench.plugins.feetech.feetech_driver import FeetechStsDriver

#: CTR-08 band for bus-enumerated evidence (hardware-onboarding.md §Link suggestions).
_BUS_CONFIDENCE: Final = 0.92
_DEFAULT_PROTOCOL_VERSION: Final = 0


def _note(servo: FeetechServo) -> str:
    if servo.model_number is None:
        return "answered a ping; the model register did not answer"
    if servo.part_number is None:
        return f"model number {servo.model_number} is not in the Solus table"
    return f"model register names an {servo.part_number}"


def _model_label(servo: FeetechServo) -> str:
    if servo.part_number is not None:
        return servo.part_number
    return "model unknown" if servo.model_number is None else f"model {servo.model_number}"


def _ids_label(ids: Sequence[int]) -> str:
    if len(ids) == 1:
        return f"id {ids[0]}"
    if ids[-1] - ids[0] == len(ids) - 1:
        return f"ids {ids[0]}–{ids[-1]}"
    return "ids " + ", ".join(str(i) for i in ids)


class FeetechBusInterrogator:
    interrogator_id: ClassVar[str] = "feetech-bus"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    safety: ClassVar[Safety] = Safety.PING

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        bus = FeetechBus(as_bus_port(channel))
        servos = bus.discover(DEFAULT_CANDIDATE_IDS, deadline=time.monotonic() + budget_s)
        if not servos:
            return None
        device_ref = channel.identity.device_ref
        driver_id = FeetechStsDriver.driver_id
        transport_params: dict[str, Any] = dict(getattr(channel, "params", None) or {})
        params: dict[str, Any] = {"protocol_version": _DEFAULT_PROTOCOL_VERSION}
        if transport_params.get("baud") is not None:
            params["baud"] = transport_params["baud"]
        ids = [servo.servo_id for servo in servos]
        models = ", ".join(sorted({_model_label(servo) for servo in servos}))
        plural = "" if len(servos) == 1 else "s"
        summary = f"{len(servos)} servo{plural} on a serial servo bus ({_ids_label(ids)}, {models})"
        # The burned homing offsets are this arm's calibration signature: two wire-identical
        # arms differ only here, and it is readable with one more register per servo.
        signature: dict[str, dict[str, int]] = {}
        for servo in servos:
            raw = bus.read_register(servo.servo_id, "Homing_Offset")
            if raw is not None:
                signature[str(servo.servo_id)] = {"homing_offset": FeetechCodec.homing_offset(raw)}
        return Interrogation(
            interrogator_id=self.interrogator_id,
            driver_id=driver_id,
            params=params,
            bus_map=[
                BusMapEntry(protocol=driver_id, address=str(s.servo_id), model=s.part_number)
                for s in servos
            ],
            evidence=[self._evidence(device_ref, driver_id, servo) for servo in servos],
            confidence=_BUS_CONFIDENCE,
            summary=summary,
            details={"calibration_signature": signature} if signature else {},
        )

    @staticmethod
    def _evidence(device_ref: str, driver_id: str, servo: FeetechServo) -> ModalityMatch:
        return ModalityMatch(
            modality=Modality.BUS_ENUMERATION,
            source_ref=SourceRef(
                source_connector=driver_id,
                external_ref=part_ref(device_ref, str(servo.servo_id)),
            ),
            confidence=_BUS_CONFIDENCE,
            state=MatchState.MATCHED,
            evidence={
                "matched_on": "model_register",
                "value": None if servo.model_number is None else str(servo.model_number),
                "note": _note(servo),
            },
        )
