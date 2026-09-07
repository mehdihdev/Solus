"""The `raw-lines` driver: a bare board printing numbers — `0.12,0.30,1.57,…` per line — with
no protocol to recognise. The channel names are the user's: the config's bus map gives a
column index → part, and the part's first telemetry channel names the signal (its unit, or the
one its calibration mode implies); an unnamed column is `ch<i>.value` with no unit."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import AsyncIterator, Callable, Mapping
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ValidationError
from solus_api.graph.packet import MAX_SIGNALS_PER_PACKET, TelemetryPacket
from solus_api.hardware.config import HardwareConfig, TransportKind, unit_for_mode

from livebench.hardware.channel import Channel
from livebench.plugins.lb06.lb06_driver import LINE_TRANSPORTS
from livebench.plugins.lb06.lb06_lines import LineReader, LineTransportParams
from livebench.telemetry.normalize import timestamp_from_ns

logger = logging.getLogger(__name__)

Separator = Literal["auto", ",", " ", "\t"]
Column = tuple[str, str | None]  # (signal name, unit)

_AUTO_SPLIT: Final = re.compile(r"[,\s]+")


class RawLinesParams(LineTransportParams):
    separator: Separator = "auto"


def _parse_floats(line: bytes, separator: Separator) -> list[float] | None:
    """The line's numbers, or None when any field is not a finite number."""
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError:
        return None
    if separator == "auto":
        fields = _AUTO_SPLIT.split(text.strip(", \t"))
    elif separator == " ":
        fields = text.split()
    else:
        fields = text.strip(separator).split(separator)
    try:
        values = [float(field) for field in fields]
    except ValueError:
        return None
    return values if values and all(math.isfinite(value) for value in values) else None


def _raw_columns(config: HardwareConfig) -> dict[int, Column]:
    """Column index → (name, unit) from the bus map and the parts it names."""
    columns: dict[int, Column] = {}
    for entry in config.bus_map:
        part = config.parts.get(str(entry.part_entity_id))
        if part is None or not part.telemetry or not entry.address.isdigit():
            continue
        channel = part.telemetry[0]
        mode = part.calibration.mode if part.calibration else None
        columns[int(entry.address)] = (channel.name, channel.unit or unit_for_mode(mode))
    return columns


class RawLinesSource:
    def __init__(
        self,
        channel: Channel,
        *,
        separator: Separator,
        columns: Mapping[int, Column],
        clock: Callable[[], int] = time.time_ns,
    ) -> None:
        self._channel = channel
        self._reader = LineReader(channel)
        self._topic = channel.identity.device_ref
        self._separator = separator
        self._columns = dict(columns)
        self._clock = clock
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        while not self._closed:
            line = await asyncio.to_thread(self._reader.read_line)
            if line is None:
                continue
            numbers = _parse_floats(line, self._separator)
            if numbers is None:
                logger.debug("%s: skipping a non-numeric line", self._topic)
                continue
            packet = self._packet(numbers[:MAX_SIGNALS_PER_PACKET])
            if packet is not None:
                yield packet

    def _packet(self, numbers: list[float]) -> TelemetryPacket | None:
        values: dict[str, float] = {}
        units: dict[str, str] = {}
        for index, value in enumerate(numbers):
            name, unit = self._columns.get(index, (f"ch{index}.value", None))
            values[name] = value
            if unit:
                units[name] = unit
        try:
            return TelemetryPacket(
                device_id=self._topic,
                timestamp=timestamp_from_ns(self._clock()),
                values=values,
                units=units,
            )
        except ValidationError:
            logger.debug("%s: skipping a line the packet validator refused", self._topic)
            return None

    async def aclose(self) -> None:
        self._closed = True
        self._channel.close()


class RawLinesDriver:
    driver_id: ClassVar[str] = "raw-lines"
    display_name: ClassVar[str] = "Raw numeric lines (user-named channels)"
    transports: ClassVar[frozenset[TransportKind]] = LINE_TRANSPORTS
    params_model: ClassVar[type[BaseModel]] = RawLinesParams

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> RawLinesSource:
        assert isinstance(params, RawLinesParams)  # the registry validated with params_model
        return RawLinesSource(channel, separator=params.separator, columns=_raw_columns(config))
