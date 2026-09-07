"""MAVLink heartbeat interrogator (listen-only): an autopilot announces itself once a second.
A HEARTBEAT within the budget names the autopilot and vehicle class; SERVO_OUTPUT_RAW frames
heard meanwhile count the live actuator outputs. Nothing is written to the link."""

from __future__ import annotations

import time
from typing import Any, ClassVar, Final

from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.config import BusMapEntry, TransportKind, part_ref

from livebench.hardware.channel import Channel
from livebench.hardware.interrogator import Interrogation, Safety
from livebench.plugins.mavlink.mavlink_codec import MavlinkMessage, MavlinkParser
from livebench.plugins.mavlink.mavlink_definitions import (
    HEARTBEAT,
    MAV_AUTOPILOT_NAMES,
    MAV_TYPE_NAMES,
    MAX_SERVO_OUTPUTS,
    SERVO_OUTPUT_RAW,
)
from livebench.plugins.mavlink.mavlink_driver import DRIVER_ID

#: A heard heartbeat is bus-enumerated evidence — the CTR-08 ceiling for that tier.
HEARTBEAT_CONFIDENCE: Final = 0.92


def _listen(channel: Channel, budget_s: float) -> tuple[MavlinkMessage | None, set[int]]:
    """The first HEARTBEAT and the nonzero servo outputs of its system, within the budget."""
    parser = MavlinkParser()
    heartbeat: MavlinkMessage | None = None
    servos: set[int] = set()
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        frame = channel.recv()
        if frame is None:
            if heartbeat is not None and servos:
                break  # a quiet tick after both were heard: nothing more to learn cheaply
            continue
        for message in parser.feed(frame.payload):
            if message.msg_id == HEARTBEAT.msg_id and heartbeat is None:
                heartbeat = message
            elif message.msg_id == SERVO_OUTPUT_RAW.msg_id and heartbeat is not None:
                if message.system_id == heartbeat.system_id:
                    outputs = range(1, MAX_SERVO_OUTPUTS + 1)
                    servos |= {n for n in outputs if message.fields[f"servo{n}_raw"]}
    return heartbeat, servos


class MavlinkHeartbeatInterrogator:
    interrogator_id: ClassVar[str] = "mavlink-heartbeat"
    transports: ClassVar[frozenset[TransportKind]] = frozenset(
        {TransportKind.WIFI, TransportKind.ETHERNET, TransportKind.USB_SERIAL}
    )
    safety: ClassVar[Safety] = Safety.LISTEN

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        heartbeat, servos = _listen(channel, budget_s)
        if heartbeat is None:
            return None
        autopilot = MAV_AUTOPILOT_NAMES.get(int(heartbeat.fields["autopilot"]))
        vehicle = MAV_TYPE_NAMES.get(int(heartbeat.fields["type"]))
        address = f"{heartbeat.system_id}:{heartbeat.component_id}"
        transport_params: dict[str, Any] = dict(getattr(channel, "params", {}))
        evidence = ModalityMatch(
            modality=Modality.BUS_ENUMERATION,
            source_ref=SourceRef(
                source_connector=DRIVER_ID,
                external_ref=part_ref(channel.identity.device_ref, address),
            ),
            confidence=HEARTBEAT_CONFIDENCE,
            state=MatchState.MATCHED,
            evidence={
                "matched_on": "mavlink_heartbeat",
                "value": vehicle,
                "note": (
                    f"MAV_AUTOPILOT {heartbeat.fields['autopilot']}, "
                    f"MAV_TYPE {heartbeat.fields['type']}, {len(servos)} nonzero servo outputs"
                ),
            },
        )
        return Interrogation(
            interrogator_id=self.interrogator_id,
            driver_id=DRIVER_ID,
            params={
                **transport_params,
                "system_id": heartbeat.system_id,
                "component_id": heartbeat.component_id,
                "protocol_version": 2,
            },
            bus_map=[
                BusMapEntry(
                    protocol=DRIVER_ID,
                    address=address,
                    model=f"{autopilot} autopilot" if autopilot else None,
                ),
                *(BusMapEntry(protocol=DRIVER_ID, address=f"servo:{n}") for n in sorted(servos)),
            ],
            evidence=[evidence],
            confidence=HEARTBEAT_CONFIDENCE,
            summary=(
                f"{autopilot or 'unknown'} autopilot, {vehicle or 'unknown vehicle type'}, "
                f"{len(servos)} actuator outputs"
            ),
            details={"vehicle_type": vehicle, "autopilot": autopilot},
        )
