"""ODrive CAN driver (`odrive-can`): a LISTEN source — it never transmits — that receives
CANSimple frames off-loop, decodes them by node and emits `<part>.position|velocity|current|
voltage` packets keyed by the adapter's device ref. Nodes are named from the config's bus map
(`0x10` → the configured part's channel prefix) or by address when unnamed."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import HardwareConfig, TransportKind

from livebench.hardware.channel import Channel, Frame
from livebench.plugins.odrive.odrive_codec import decode_odrive_frame
from livebench.plugins.odrive.odrive_definitions import (
    ODRIVE_DEFAULT_BITRATE,
    ODRIVE_MAX_NODE,
    ODRIVE_SIGNALS,
    ODRIVE_UNITS,
)

logger = logging.getLogger(__name__)

DRIVER_ID: Final = "odrive-can"


class OdriveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bitrate: int = Field(default=ODRIVE_DEFAULT_BITRATE, ge=10_000, le=1_000_000)
    timeout_s: float = Field(default=0.1, gt=0, le=5)


def _odrive_prefixes(config: HardwareConfig) -> dict[int, str]:
    """Node → signal prefix (telemetry-packet.md §2a): the configured part's first channel
    prefix when the bus map names one, else nothing (the source falls back to the address)."""
    prefixes: dict[int, str] = {}
    for entry in config.bus_map:
        try:
            node = int(entry.address, 16)
        except ValueError:
            continue  # a servo id or a system:component pair — not a CAN node
        key = str(entry.part_entity_id) if entry.part_entity_id is not None else None
        part = config.parts.get(key) if key is not None else None
        if 0 <= node <= ODRIVE_MAX_NODE and part is not None and part.telemetry:
            prefixes[node] = part.telemetry[0].name.split(".", 1)[0]
    return prefixes


class OdriveSource:
    """Receives off-loop; one packet per decoded frame. Silence (`recv` → None) is not an
    event, and a frame that is not ours costs nothing."""

    def __init__(self, channel: Channel, prefixes: dict[int, str]) -> None:
        self._channel = channel
        self._device_id = channel.identity.device_ref
        self._prefixes = prefixes
        self._closed = False
        self._seq = 0

    def _packet_of(self, frame: Frame) -> TelemetryPacket | None:
        if frame.address is None:
            return None
        try:
            arbitration_id = int(frame.address, 16)
        except ValueError:
            return None
        reading = decode_odrive_frame(arbitration_id, frame.payload)
        if reading is None:
            return None
        prefix = self._prefixes.get(reading.node) or f"addr_0x{reading.node:02x}"
        values: dict[str, float] = {}
        units: dict[str, str] = {}
        for field, value in reading.fields.items():
            quantity = ODRIVE_SIGNALS.get(field)
            if quantity is None:
                continue
            values[f"{prefix}.{quantity}"] = value
            units[f"{prefix}.{quantity}"] = ODRIVE_UNITS[quantity]
        if not values:
            return None
        packet = TelemetryPacket(
            device_id=self._device_id,
            timestamp=datetime.now(UTC),
            values=values,
            units=units,
            seq=self._seq,
        )
        self._seq += 1
        return packet

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        while not self._closed:
            frame = await asyncio.to_thread(self._channel.recv)
            if frame is None:
                continue
            packet = self._packet_of(frame)
            if packet is not None:
                yield packet

    async def aclose(self) -> None:
        self._closed = True
        self._channel.close()


class OdriveCanDriver:
    driver_id: ClassVar[str] = DRIVER_ID
    display_name: ClassVar[str] = "ODrive CAN (CANSimple) axes"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_CAN})
    params_model: ClassVar[type[BaseModel]] = OdriveParams

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> OdriveSource:
        assert isinstance(params, OdriveParams)  # the registry validated with params_model
        prefixes = _odrive_prefixes(config)
        logger.info(
            "odrive-can listening on %s (%d named node(s))",
            channel.identity.device_ref,
            len(prefixes),
        )
        return OdriveSource(channel, prefixes)
