"""Feetech STS/SCS servo bus as a `ProtocolDriver`: a POLLING `PacketSource`.

The bus is request-response half-duplex — servos transmit nothing unsolicited — so the driver
polls Present_Position per configured address at `poll_hz`, off-loop, one request outstanding
(a sweep never starves the bus). Every 10th sweep also reads load and temperature. Addresses,
part names and calibration come from the robot's HardwareConfig; register maps and resolutions
from `feetech_definitions`; baud/timeouts from the driver params (the transport consumes them).

A servo that stops answering costs that sample only; a lost link ends the iteration so the
reconnect loop heals it. Packets are keyed by the channel identity (`usb:<serial>`), never a tty.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    BusMapEntry,
    CalibrationMode,
    HardwareConfig,
    PartConfig,
    TransportKind,
    unit_for_mode,
)

from livebench.hardware.channel import Channel, as_bus_port
from livebench.plugins.feetech.feetech_codec import FeetechBus, FeetechCodec
from livebench.plugins.feetech.feetech_definitions import (
    DEFAULT_BAUD,
    DEFAULT_CANDIDATE_IDS,
    DEFAULT_RESOLUTION,
    DEFAULT_TIMEOUT_S,
    FEETECH_RESOLUTION,
    LOAD_DIRECTION_BIT,
    LOAD_MAGNITUDE_MASK,
    LOAD_PERCENT_PER_UNIT,
    MAX_SERVO_ID,
)

logger = logging.getLogger(__name__)

_DEFAULT_POLL_HZ: Final = 30.0
_MAX_POLL_HZ: Final = 200.0
#: Load and temperature ride every N-th sweep — health, not motion, needs no 30 Hz.
_HEALTH_EVERY_N_SWEEPS: Final = 10
_TICK_UNIT: Final = "tick"


class FeetechParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baud: int = Field(default=DEFAULT_BAUD, ge=9600, le=1_000_000)
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, gt=0, le=1)
    protocol_version: Literal[0, 1] = 0
    poll_hz: float = Field(default=_DEFAULT_POLL_HZ, gt=0, le=_MAX_POLL_HZ)
    #: Calibration knobs — real servos carry gearing and offsets a nominal model can't see.
    ticks_per_rev: int | None = Field(default=None, ge=2, le=0xFFFF)
    center: int | None = Field(default=None, ge=0, le=0xFFFF)


@dataclass(frozen=True)
class _FeetechJoint:
    """One polled address with its signal prefix and calibration."""

    servo_id: int
    prefix: str
    resolution: int
    center: int
    mode: CalibrationMode | None
    span: tuple[float, float] | None  # range_min..range_max for percent modes

    def position(self, ticks: int) -> tuple[float, str]:
        """The part's calibration owns the conversion (the repo's convention, not ours):
        with a calibrated range, degrees are measured from the range midpoint over
        `resolution - 1` and percent modes clamp into the range; without one, degrees fall
        back to the configured centre."""
        unit = unit_for_mode(self.mode) or _TICK_UNIT
        if self.mode is CalibrationMode.DEGREES:
            if self.span is not None:
                low, high = self.span
                return (ticks - (low + high) / 2) * 360.0 / (self.resolution - 1), unit
            return (
                FeetechCodec.ticks_to_degrees(
                    ticks, ticks_per_rev=self.resolution, center=self.center
                ),
                unit,
            )
        if self.mode in (CalibrationMode.RANGE_0_100, CalibrationMode.RANGE_M100_100) and (
            self.span is not None
        ):
            low, high = self.span
            fraction = (min(high, max(low, ticks)) - low) / (high - low)
            if self.mode is CalibrationMode.RANGE_M100_100:
                return fraction * 200.0 - 100.0, unit
            return fraction * 100.0, unit
        return float(ticks), _TICK_UNIT


def _span(part: PartConfig | None) -> tuple[float, float] | None:
    values = part.calibration.values if part is not None and part.calibration else {}
    low, high = values.get("range_min"), values.get("range_max")
    if low is None or high is None or high <= low:
        return None
    return float(low), float(high)


def _joint(
    servo_id: int, entry: BusMapEntry | None, part: PartConfig | None, params: FeetechParams
) -> _FeetechJoint:
    model = entry.model if entry is not None else None
    resolution = params.ticks_per_rev or FEETECH_RESOLUTION.get(model or "", DEFAULT_RESOLUTION)
    named = part is not None and bool(part.telemetry)
    prefix = part.telemetry[0].name.split(".")[0] if named and part else f"addr_{servo_id}"
    return _FeetechJoint(
        servo_id=servo_id,
        prefix=prefix,
        resolution=resolution,
        # lerobot's homing burn puts the calibration pose at int((res - 1) / 2) == 2047.
        center=params.center if params.center is not None else resolution // 2 - 1,
        mode=part.calibration.mode if part is not None and part.calibration else None,
        span=_span(part),
    )


def _servo_id(entry: BusMapEntry) -> int:
    if not entry.address.isdigit() or int(entry.address) > MAX_SERVO_ID:
        raise ValueError(f"bus_map address {entry.address!r} is not a servo id (0..{MAX_SERVO_ID})")
    return int(entry.address)


class FeetechPacketSource:
    """Polls present position per configured address and yields LB-06 packets."""

    def __init__(
        self,
        bus: FeetechBus,
        *,
        device_id: str,
        joints: Sequence[_FeetechJoint],
        poll_hz: float,
        seq: Iterator[int],
    ) -> None:
        self._bus = bus
        self._device_id = device_id
        self._joints = list(joints)
        self._period = 1.0 / poll_hz
        self._seq = seq
        self._closed = False

    def _health(self, joint: _FeetechJoint) -> dict[str, tuple[float, str]]:
        out: dict[str, tuple[float, str]] = {}
        load = self._bus.read_register(joint.servo_id, "Present_Load")
        if load is not None:
            sign = -1.0 if load & LOAD_DIRECTION_BIT else 1.0
            out[f"{joint.prefix}.load"] = (
                sign * (load & LOAD_MAGNITUDE_MASK) * LOAD_PERCENT_PER_UNIT,
                "%",
            )
        temperature = self._bus.read_register(joint.servo_id, "Present_Temperature")
        if temperature is not None:
            out[f"{joint.prefix}.temperature"] = (float(temperature), "degC")
        return out

    def _sweep(self, with_health: bool) -> dict[str, tuple[float, str]]:
        """One sequential pass over the bus (worker thread — every read blocks)."""
        readings: dict[str, tuple[float, str]] = {}
        for joint in self._joints:
            ticks = self._bus.read_register(joint.servo_id, "Present_Position")
            if ticks is None:
                continue  # one silent/garbled servo costs one sample, not the sweep
            readings[f"{joint.prefix}.position"] = joint.position(ticks)
            if with_health:
                readings.update(self._health(joint))
        return readings

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        for sweep in itertools.count():
            if self._closed:
                return
            started = time.monotonic()
            try:
                readings = await asyncio.to_thread(self._sweep, sweep % _HEALTH_EVERY_N_SWEEPS == 0)
            except OSError:
                return  # link lost (or closed mid-sweep) — end; ReconnectingSource heals
            if readings:
                yield TelemetryPacket(
                    device_id=self._device_id,
                    timestamp=datetime.now(tz=UTC),
                    values={name: value for name, (value, _) in readings.items()},
                    seq=next(self._seq),
                    units={name: unit for name, (_, unit) in readings.items()},
                )
            await asyncio.sleep(max(0.0, self._period - (time.monotonic() - started)))

    async def aclose(self) -> None:
        self._closed = True  # bookkeeping before the close unblocks the sweep
        try:
            self._bus.close()
        except OSError:  # pragma: no cover - best-effort
            logger.debug("feetech close failed for %s", self._device_id)


class FeetechStsDriver:
    driver_id: ClassVar[str] = "feetech-sts"
    display_name: ClassVar[str] = "Feetech STS/SCS servo bus"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    params_model: ClassVar[type[BaseModel]] = FeetechParams

    def __init__(self) -> None:
        #: Per-device monotonic `seq` (packet.py contract): survives reconnect incarnations.
        self._seqs: dict[str, Iterator[int]] = {}

    def open(
        self, channel: Channel, params: BaseModel, config: HardwareConfig
    ) -> FeetechPacketSource:
        if not isinstance(params, FeetechParams):
            raise TypeError(f"{self.driver_id} expects FeetechParams, got {type(params).__name__}")
        device_id = channel.identity.device_ref
        bus = FeetechBus(as_bus_port(channel), FeetechCodec(params.protocol_version))
        entries: dict[int, BusMapEntry | None] = {
            _servo_id(e): e for e in config.bus_map if e.protocol == self.driver_id
        }
        if not entries:
            ids = bus.discover_ids(DEFAULT_CANDIDATE_IDS)
            logger.info(
                "%s: no bus_map for %s; discovered servo ids %s", self.driver_id, device_id, ids
            )
            if not ids:
                raise LookupError(
                    f"no Feetech servos answered on {device_id} (ids {DEFAULT_CANDIDATE_IDS.start}"
                    f"–{DEFAULT_CANDIDATE_IDS.stop - 1}); check servo power, baud and protocol"
                )
            entries = dict.fromkeys(ids)
        joints = [
            _joint(servo_id, entry, self._part(config, entry), params)
            for servo_id, entry in entries.items()
        ]
        return FeetechPacketSource(
            bus,
            device_id=device_id,
            joints=joints,
            poll_hz=params.poll_hz,
            seq=self._seqs.setdefault(device_id, itertools.count()),
        )

    @staticmethod
    def _part(config: HardwareConfig, entry: BusMapEntry | None) -> PartConfig | None:
        if entry is None or entry.part_entity_id is None:
            return None
        return config.parts.get(str(entry.part_entity_id))
