"""The `lb06` driver: a Solus-flashed board's own telemetry, one LB-06 JSON line per packet,
over any serial-shaped transport (USB serial, Bluetooth classic, BLE).

Decoding is `packet_from_json_payload`, the shared choke point — never a second decoder. On a
direct link the firmware's own `device_id` is trusted (one wire, one claimant) but PINNED: the
first identity seen wins unless one is pinned up front, and a relabel mid-stream is dropped
with a warning. The driver pins the channel's device_ref, so the pin survives a reconnect —
every incarnation opens from the same config identity, and a Solus-flashed board's firmware
`device_id` IS that device_ref by convention.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import ClassVar, Final

from pydantic import BaseModel
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import HardwareConfig, TransportKind

from livebench.hardware.channel import Channel
from livebench.plugins.lb06.lb06_lines import LineReader, LineTransportParams
from livebench.telemetry.normalize import packet_from_json_payload

logger = logging.getLogger(__name__)

#: The serial-shaped transports every line driver rides.
LINE_TRANSPORTS: Final[frozenset[TransportKind]] = frozenset(
    {TransportKind.USB_SERIAL, TransportKind.BT_CLASSIC, TransportKind.BLE}
)


class Lb06Source:
    """JSON lines from a channel as an async packet stream; the blocking reads run off-loop.
    `trusted_identity=False` is the plain-JSON posture: the device_ref is always the identity."""

    def __init__(
        self,
        channel: Channel,
        *,
        trusted_identity: bool = True,
        pinned_device_id: str | None = None,
        clock: Callable[[], int] = time.time_ns,
    ) -> None:
        self._channel = channel
        self._reader = LineReader(channel)
        self._topic = channel.identity.device_ref
        self._trusted = trusted_identity
        self._pinned = pinned_device_id
        self._clock = clock
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        while not self._closed:
            line = await asyncio.to_thread(self._reader.read_line)
            if line is None:
                continue
            packet = packet_from_json_payload(
                self._topic, self._clock(), line, trusted_identity=self._trusted
            )
            if packet is None:
                logger.debug("%s: skipping an undecodable line", self._topic)
                continue
            if self._pinned is None:
                self._pinned = packet.device_id
            elif packet.device_id != self._pinned:
                logger.warning(
                    "%s: dropping a packet relabelled %.64r (pinned %.64r)",
                    self._topic,
                    packet.device_id,
                    self._pinned,
                )
                continue
            yield packet

    async def aclose(self) -> None:
        self._closed = True
        self._channel.close()


class Lb06Driver:
    driver_id: ClassVar[str] = "lb06"
    display_name: ClassVar[str] = "Solus telemetry (LB-06 lines)"
    transports: ClassVar[frozenset[TransportKind]] = LINE_TRANSPORTS
    params_model: ClassVar[type[BaseModel]] = LineTransportParams

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> Lb06Source:
        return Lb06Source(channel, pinned_device_id=channel.identity.device_ref)
