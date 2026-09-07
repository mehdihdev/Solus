"""Dynamixel bus interrogator (safety PING): one Protocol 2.0 broadcast ping — a presence request
no servo interprets as a command — and every responder's model register becomes bus-enumeration
evidence at the CTR-08 cap (0.92). It names the PART, never the joint it drives."""

from __future__ import annotations

from typing import Any, ClassVar, Final

from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.config import BusMapEntry, TransportKind, part_ref

from livebench.hardware.channel import Channel, as_bus_port
from livebench.hardware.interrogator import Interrogation, Safety
from livebench.plugins.dynamixel.dynamixel_codec import DxlPingReply, dynamixel_broadcast_ping
from livebench.plugins.dynamixel.dynamixel_definitions import DXL_MODELS, DXL_PROTOCOL_VERSION
from livebench.plugins.dynamixel.dynamixel_driver import DRIVER_ID

BUS_ENUMERATION_CONFIDENCE: Final = 0.92
_PART_NOT_JOINT: Final = (
    "identifies the PART, not which joint it drives — the motor-to-joint link goes "
    "through human confirmation (RBT-03)"
)


def _dxl_evidence(device_ref: str, reply: DxlPingReply) -> ModalityMatch:
    part = DXL_MODELS.get(reply.model_number, f"model {reply.model_number}")
    return ModalityMatch(
        modality=Modality.BUS_ENUMERATION,
        source_ref=SourceRef(
            source_connector=DRIVER_ID,
            external_ref=part_ref(device_ref, str(reply.servo_id)),
        ),
        confidence=BUS_ENUMERATION_CONFIDENCE,
        state=MatchState.MATCHED,
        evidence={
            "matched_on": "model_register",
            "value": str(reply.model_number),
            "note": (
                f"Dynamixel model register {reply.model_number} = {part}, fw v{reply.firmware}; "
                f"the device asserts its own identity. {_PART_NOT_JOINT}"
            ),
        },
    )


class DynamixelBusInterrogator:
    interrogator_id: ClassVar[str] = DRIVER_ID
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    safety: ClassVar[Safety] = Safety.PING

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        replies = dynamixel_broadcast_ping(as_bus_port(channel), budget_s=budget_s)
        if not replies:
            return None  # silence: not a Protocol 2.0 bus (or nothing powered on it)
        params: dict[str, Any] = {"protocol_version": DXL_PROTOCOL_VERSION}
        baud = getattr(channel, "params", {}).get("baud")
        if baud is not None:
            params["baud"] = baud  # the baud that answered is the baud the config records
        device_ref = channel.identity.device_ref
        ids = ", ".join(str(reply.servo_id) for reply in replies)
        return Interrogation(
            interrogator_id=self.interrogator_id,
            driver_id=DRIVER_ID,
            params=params,
            bus_map=[
                BusMapEntry(
                    protocol=DRIVER_ID,
                    address=str(reply.servo_id),
                    model=DXL_MODELS.get(reply.model_number),  # unknown stays None, never a guess
                )
                for reply in replies
            ],
            evidence=[_dxl_evidence(device_ref, reply) for reply in replies],
            confidence=BUS_ENUMERATION_CONFIDENCE,
            summary=f"{len(replies)} Dynamixel servo(s) answered the broadcast ping: ids {ids}",
        )
