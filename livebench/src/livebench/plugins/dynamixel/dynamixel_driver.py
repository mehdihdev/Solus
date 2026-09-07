"""Dynamixel Protocol 2.0 driver (`dynamixel-2`): polls Present Position for every servo id in
the robot's bus map — one outstanding request at a time, so a sweep never starves the bus — and
emits `<part>.position` with the unit the part's calibration mode implies. Baud, ids, timeout
and poll rate come from the config (validated by `DynamixelParams`); the control table and the
encoder resolution from `dynamixel_definitions`."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    CalibrationMode,
    HardwareConfig,
    PartConfig,
    TransportKind,
    unit_for_mode,
)

from livebench.hardware.channel import BusPortAdapter, Channel, as_bus_port
from livebench.plugins.dynamixel.dynamixel_codec import DXL_BROADCAST_ID, dxl_read_register
from livebench.plugins.dynamixel.dynamixel_definitions import (
    DXL_DEFAULT_BAUD,
    DXL_REGISTERS,
    dxl_resolution,
)

logger = logging.getLogger(__name__)

DRIVER_ID: Final = "dynamixel-2"
_TICKS_UNIT: Final = "ticks"
#: The calibration-file keys (lerobot's) a range mode needs to turn ticks into percent.
_RANGE_KEYS: Final = ("range_min", "range_max")
_DEGREES_PER_REV: Final = 360.0
_PERCENT: Final = 100.0
_RANGE_MODES: Final = (CalibrationMode.RANGE_0_100, CalibrationMode.RANGE_M100_100)


class DynamixelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baud: int = Field(default=DXL_DEFAULT_BAUD, ge=9_600, le=4_000_000)
    timeout_s: float = Field(default=0.05, gt=0, le=5)
    poll_hz: float = Field(default=50.0, gt=0, le=200)
    protocol_version: Literal[2] = 2


@dataclass(frozen=True)
class _DxlTarget:
    servo_id: int
    signal: str
    mode: CalibrationMode | None
    ticks_per_rev: int
    range_ticks: tuple[float, float] | None


def _signal_prefix(part: PartConfig | None, address: str) -> str:
    """docs/contracts/telemetry-packet.md §2a: the configured part's channel prefix, else the
    address."""
    if part is not None and part.telemetry:
        return part.telemetry[0].name.split(".", 1)[0]
    return f"addr_{address}"


def _range_ticks(part: PartConfig | None) -> tuple[float, float] | None:
    if part is None or part.calibration is None:
        return None
    values = part.calibration.values
    if not all(key in values for key in _RANGE_KEYS):
        return None
    low, high = (float(values[key]) for key in _RANGE_KEYS)
    return (low, high) if high > low else None


def _dxl_targets(config: HardwareConfig) -> list[_DxlTarget]:
    targets: list[_DxlTarget] = []
    for entry in config.bus_map:
        if not entry.address.isdecimal() or not 0 <= int(entry.address) < DXL_BROADCAST_ID:
            continue  # hex CAN nodes, system:component ids — not a servo id on this bus
        key = str(entry.part_entity_id) if entry.part_entity_id is not None else None
        part = config.parts.get(key) if key is not None else None
        mode = part.calibration.mode if part is not None and part.calibration else None
        targets.append(
            _DxlTarget(
                servo_id=int(entry.address),
                signal=f"{_signal_prefix(part, entry.address)}.position",
                mode=mode,
                ticks_per_rev=dxl_resolution(entry.model),
                range_ticks=_range_ticks(part),
            )
        )
    return targets


def _dxl_value(ticks: int, target: _DxlTarget) -> tuple[float, str]:
    """Ticks → the part's unit: degrees about the encoder centre, percent across the calibrated
    range, else honest raw ticks (ponytail: linear needs a per-part scale the config has no
    field for yet — add it with the field)."""
    if target.mode is CalibrationMode.DEGREES:
        centre = target.ticks_per_rev // 2
        return (ticks - centre) * _DEGREES_PER_REV / target.ticks_per_rev, "deg"
    if target.mode in _RANGE_MODES and target.range_ticks is not None:
        low, high = target.range_ticks
        percent = (ticks - low) / (high - low) * _PERCENT
        if target.mode is CalibrationMode.RANGE_M100_100:
            percent = percent * 2 - _PERCENT
        return percent, unit_for_mode(target.mode) or "%"
    return float(ticks), _TICKS_UNIT


class DynamixelSource:
    """Polls the bus off-loop at `poll_hz`; one packet per sweep that got at least one answer."""

    def __init__(
        self, port: BusPortAdapter, device_id: str, targets: list[_DxlTarget], *, poll_hz: float
    ) -> None:
        self._port = port
        self._device_id = device_id
        self._targets = targets
        self._period = 1.0 / poll_hz
        self._closed = False
        self._seq = 0

    def _sweep(self) -> tuple[dict[str, float], dict[str, str]]:
        """Blocking (worker thread): one request per servo, strictly sequential."""
        values: dict[str, float] = {}
        units: dict[str, str] = {}
        register = DXL_REGISTERS["present_position"]
        for target in self._targets:
            data = dxl_read_register(self._port, target.servo_id, register)
            if data is None:
                self._port.reset_input_buffer()  # resync: whatever came back was not our reply
                continue
            value, unit = _dxl_value(int.from_bytes(data, "little", signed=True), target)
            values[target.signal] = value
            units[target.signal] = unit
        return values, units

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        loop = asyncio.get_running_loop()
        while not self._closed:
            started = loop.time()
            values, units = await asyncio.to_thread(self._sweep)
            if values:
                yield TelemetryPacket(
                    device_id=self._device_id,
                    timestamp=datetime.now(UTC),
                    values=values,
                    units=units,
                    seq=self._seq,
                )
                self._seq += 1
            await asyncio.sleep(max(0.0, self._period - (loop.time() - started)))

    async def aclose(self) -> None:
        self._closed = True
        self._port.close()


class DynamixelDriver:
    driver_id: ClassVar[str] = DRIVER_ID
    display_name: ClassVar[str] = "Dynamixel Protocol 2.0 servo bus"
    transports: ClassVar[frozenset[TransportKind]] = frozenset({TransportKind.USB_SERIAL})
    params_model: ClassVar[type[BaseModel]] = DynamixelParams

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> DynamixelSource:
        assert isinstance(params, DynamixelParams)  # the registry validated with params_model
        targets = _dxl_targets(config)
        if not targets:
            raise ValueError("the robot's bus map names no servo id for this driver")
        logger.info(
            "dynamixel-2 polling %d servo(s) on %s at %.0f Hz",
            len(targets),
            channel.identity.device_ref,
            params.poll_hz,
        )
        return DynamixelSource(
            as_bus_port(channel), channel.identity.device_ref, targets, poll_hz=params.poll_hz
        )
