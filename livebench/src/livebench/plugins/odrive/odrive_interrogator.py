"""ODrive CAN interrogator (safety LISTEN): receive for the budget and let the heartbeats speak.
Every node that announces itself becomes a bus-map entry with bus-enumeration evidence at the
CTR-08 cap (0.92). The heartbeat carries no model number, so the model is left unset — never
guessed from the display table."""

from __future__ import annotations

import time
from typing import Any, ClassVar, Final

from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.config import BusMapEntry, TransportKind, part_ref

from livebench.hardware.channel import Channel
from livebench.hardware.interrogator import Interrogation, Safety
from livebench.plugins.odrive.odrive_codec import odrive_heartbeat_nodes
from livebench.plugins.odrive.odrive_driver import DRIVER_ID

BUS_ENUMERATION_CONFIDENCE: Final = 0.92
MAX_LISTEN_FRAMES: Final = 4096  # a chatty bus fills this in well under a budget; enough to hear
_PART_NOT_JOINT: Final = (
    "identifies the PART, not which wheel or joint it drives — the motor-to-joint link goes "
    "through human confirmation (RBT-03)"
)


def _odrive_listen(channel: Channel, budget_s: float) -> list[tuple[int, bytes]]:
    """(arbitration id, data) for every frame heard within the budget; silence keeps
    listening (a heartbeat comes every 100 ms), junk addresses are skipped."""
    deadline = time.monotonic() + budget_s
    frames: list[tuple[int, bytes]] = []
    while time.monotonic() < deadline and len(frames) < MAX_LISTEN_FRAMES:
        frame = channel.recv()
        if frame is None or frame.address is None:
            continue
        try:
            frames.append((int(frame.address, 16), frame.payload))
        except ValueError:
            continue
    return frames


def _odrive_evidence(device_ref: str, address: str, node: int) -> ModalityMatch:
    return ModalityMatch(
        modality=Modality.BUS_ENUMERATION,
        source_ref=SourceRef(
            source_connector=DRIVER_ID, external_ref=part_ref(device_ref, address)
        ),
        confidence=BUS_ENUMERATION_CONFIDENCE,
        state=MatchState.MATCHED,
        evidence={
            "matched_on": "can_heartbeat",
            "value": str(node),
            "note": (
                f"ODrive axis node {node} ({address}) announces itself on CAN (heartbeat 0x01); "
                f"the heartbeat carries no model number, so the model is left unset. "
                f"{_PART_NOT_JOINT}"
            ),
        },
    )


class OdriveCanInterrogator:
    interrogator_id: ClassVar[str] = DRIVER_ID
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_CAN})
    safety: ClassVar[Safety] = Safety.LISTEN

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        nodes = odrive_heartbeat_nodes(_odrive_listen(channel, budget_s))
        if not nodes:
            return None  # no heartbeat within the budget: not an ODrive bus (or nothing powered)
        params: dict[str, Any] = {}
        bitrate = getattr(channel, "params", {}).get("bitrate")
        if bitrate is not None:
            params["bitrate"] = bitrate  # the bitrate that heard the bus is the one to record
        device_ref = channel.identity.device_ref
        addresses = [f"0x{node:02x}" for node in nodes]
        return Interrogation(
            interrogator_id=self.interrogator_id,
            driver_id=DRIVER_ID,
            params=params,
            bus_map=[BusMapEntry(protocol=DRIVER_ID, address=a, model=None) for a in addresses],
            evidence=[
                _odrive_evidence(device_ref, address, node)
                for address, node in zip(addresses, nodes, strict=True)
            ],
            confidence=BUS_ENUMERATION_CONFIDENCE,
            summary=f"{len(nodes)} ODrive axis node(s) heard on CAN: {', '.join(addresses)}",
        )
