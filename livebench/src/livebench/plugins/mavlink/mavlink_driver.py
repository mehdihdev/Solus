"""MAVLink telemetry driver: v2 frames from an autopilot (PX4, ArduPilot) over UDP or a serial
radio become LB-06 packets keyed by the channel identity.

ATTITUDE → `<part>.roll|pitch|yaw` (rad) and `.rollspeed|pitchspeed|yawspeed` (rad/s);
SERVO_OUTPUT_RAW → `<part>.output` (us) for every nonzero output; HEARTBEAT →
`<part>.system_status`. `<part>` is the configured part's signal prefix when the bus map names
one for the address (`sysid:compid`, `servo:<n>`), else the natural prefix (`attitude`,
`motor_<n>`, `heartbeat`). System id, heartbeat timeout and the transport's own keys come from
the config; the wire layouts from `mavlink_definitions`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    CalibrationMode,
    HardwareConfig,
    TransportKind,
    unit_for_mode,
)

from livebench.hardware.channel import Channel, Frame
from livebench.plugins.mavlink.mavlink_codec import MavlinkMessage, MavlinkParser
from livebench.plugins.mavlink.mavlink_definitions import (
    ATTITUDE,
    HEARTBEAT,
    MAX_SERVO_OUTPUTS,
    SERVO_OUTPUT_RAW,
)

logger = logging.getLogger(__name__)

DRIVER_ID: Final = "mavlink"
_ANGLES: Final = ("roll", "pitch", "yaw")
_RATES: Final = ("rollspeed", "pitchspeed", "yawspeed")

Signal = tuple[str, float, str | None]  # name, value, unit
Prefix = tuple[str, CalibrationMode | None]


class MavlinkParams(BaseModel):
    """Driver parameters, plus the transport keys that ride the same config bag (the baud of a
    serial radio, the UDP listen port) — the driver model validates the whole bag."""

    model_config = ConfigDict(extra="forbid")
    system_id: int = Field(default=1, ge=1, le=255)
    component_id: int = Field(default=1, ge=1, le=255)
    protocol_version: Literal[2] = 2
    heartbeat_timeout_s: float = Field(default=3.0, gt=0, le=60)
    baud: int | None = Field(default=None, ge=300, le=3_000_000)
    timeout_s: float | None = Field(default=None, gt=0, le=5)
    listen_port: int | None = Field(default=None, ge=1, le=65535)
    endpoint: str | None = Field(default=None, max_length=256)


def _mavlink_prefixes(config: HardwareConfig) -> dict[str, Prefix]:
    """Bus address → (the named part's signal prefix, its calibration mode)."""
    prefixes: dict[str, Prefix] = {}
    for entry in config.bus_map:
        part = config.parts.get(str(entry.part_entity_id)) if entry.part_entity_id else None
        if entry.protocol != DRIVER_ID or part is None or not part.telemetry:
            continue
        mode = part.calibration.mode if part.calibration else None
        prefixes[entry.address] = (part.telemetry[0].name.split(".", 1)[0], mode)
    return prefixes


class MavlinkSource:
    """Reads the channel off-loop, feeds the parser, yields one packet per decoded message."""

    def __init__(
        self,
        channel: Channel,
        params: MavlinkParams,
        config: HardwareConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._channel = channel
        self._params = params
        self._clock = clock
        self._device_id = channel.identity.device_ref
        self._prefixes = _mavlink_prefixes(config)
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        parser = MavlinkParser()
        timeout = self._params.heartbeat_timeout_s
        deadline = self._clock() + timeout
        while not self._closed:
            frame = await asyncio.to_thread(self._recv)
            for message in parser.feed(frame.payload) if frame else ():
                if message.system_id != self._params.system_id:
                    continue
                if message.msg_id == HEARTBEAT.msg_id:
                    deadline = self._clock() + timeout
                packet = self._packet(message)
                if packet is not None:
                    yield packet
            if self._clock() > deadline:
                logger.warning(
                    "%s: no heartbeat from system %d within %.1fs",
                    self._device_id,
                    self._params.system_id,
                    timeout,
                )
                return

    async def aclose(self) -> None:
        self._closed = True
        self._channel.close()

    def _recv(self) -> Frame | None:
        try:
            return self._channel.recv()
        except OSError as exc:  # the link died under us: end the stream, reconnect heals it
            logger.warning("%s: link read failed: %s", self._device_id, type(exc).__name__)
            self._closed = True
            return None

    def _prefix(self, address: str, natural: str) -> Prefix:
        return self._prefixes.get(address, (natural, None))

    def _signals(self, message: MavlinkMessage) -> Iterator[Signal]:
        address = f"{message.system_id}:{message.component_id}"
        fields = message.fields
        if message.msg_id == ATTITUDE.msg_id:
            prefix, mode = self._prefix(address, "attitude")
            degrees = mode is CalibrationMode.DEGREES
            angle_unit = unit_for_mode(mode) if degrees else "rad"
            for quantity in _ANGLES:
                value = float(fields[quantity])
                yield f"{prefix}.{quantity}", math.degrees(value) if degrees else value, angle_unit
            for quantity in _RATES:
                value = float(fields[quantity])
                unit = f"{angle_unit}/s"
                yield f"{prefix}.{quantity}", math.degrees(value) if degrees else value, unit
        elif message.msg_id == SERVO_OUTPUT_RAW.msg_id:
            for n in range(1, MAX_SERVO_OUTPUTS + 1):
                value = fields[f"servo{n}_raw"]
                if value:
                    prefix, _ = self._prefix(f"servo:{n}", f"motor_{n}")
                    yield f"{prefix}.output", float(value), "us"
        elif message.msg_id == HEARTBEAT.msg_id:
            prefix, _ = self._prefix(address, "heartbeat")
            yield f"{prefix}.system_status", float(fields["system_status"]), None

    def _packet(self, message: MavlinkMessage) -> TelemetryPacket | None:
        signals = list(self._signals(message))
        values = {name: value for name, value, _ in signals if math.isfinite(value)}
        if not values:
            return None
        units = {name: unit for name, _, unit in signals if unit and name in values}
        try:
            return TelemetryPacket(
                device_id=self._device_id, timestamp=datetime.now(UTC), values=values, units=units
            )
        except ValidationError as exc:  # a name too long for the packet: one sample, not the stream
            logger.debug("%s: dropping message %d: %s", self._device_id, message.msg_id, exc)
            return None


class MavlinkDriver:
    driver_id: ClassVar[str] = DRIVER_ID
    display_name: ClassVar[str] = "MAVLink autopilot link"
    transports: ClassVar[frozenset[TransportKind]] = frozenset(
        {TransportKind.WIFI, TransportKind.ETHERNET, TransportKind.USB_SERIAL}
    )
    params_model: ClassVar[type[BaseModel]] = MavlinkParams

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> MavlinkSource:
        if not isinstance(params, MavlinkParams):
            raise TypeError(f"{DRIVER_ID} expects MavlinkParams, got {type(params).__name__}")
        return MavlinkSource(channel, params, config)
