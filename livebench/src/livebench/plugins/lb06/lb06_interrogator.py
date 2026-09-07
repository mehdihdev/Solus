"""The `serial-framing` interrogator: listen for the budget on a serial-shaped channel and say
which LINE driver would speak the stream — LB-06 lines, plain JSON lines or CSV floats.

Classification is the shared `characterize_stream` (recognition/passive.py). Telemetry shape
CONSTRAINS, it does not identify (CTR-08): the evidence is that stream-shape match, the
confidence never exceeds 0.30, and nothing is ever written to the device.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar, Final

from pydantic import ValidationError
from solus_api.hardware.config import BusMapEntry, TransportKind

from livebench.hardware.channel import Channel
from livebench.hardware.interrogator import Interrogation, Safety
from livebench.plugins.lb06.lb06_driver import LINE_TRANSPORTS
from livebench.plugins.lb06.lb06_lines import LineReader
from livebench.recognition.passive import StreamShape, characterize_stream

#: The CTR-08 telemetry-shape band, whatever the characterizer reports.
MAX_SHAPE_CONFIDENCE: Final = 0.30
#: Bounds the probe's memory; plenty to measure a rate at any plausible line frequency.
MAX_PROBE_LINES: Final = 4096

Sample = tuple[float, bytes]
Proposal = tuple[str, list[str], str]  # (driver_id, channel addresses, summary)


def _lb06_channels(samples: Sequence[Sample]) -> list[str] | None:
    """The `values` channel names when the JSON lines carry the LB-06 shape (`device_id` +
    `values`), None when they are plain JSON."""
    names: dict[str, None] = {}
    objects = shaped = 0
    for _at, line in samples:
        if not line.startswith(b"{"):
            continue
        try:
            parsed = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(parsed, dict):
            continue
        objects += 1
        values = parsed.get("values")
        if "device_id" in parsed and isinstance(values, dict):
            shaped += 1
            names.update(dict.fromkeys(str(key) for key in values))
    return list(names) if shaped * 2 > objects else None


def _proposal(shape: StreamShape, samples: Sequence[Sample]) -> Proposal | None:
    rate = f"{shape.update_hz:.0f} Hz"
    if shape.framing == "csv":
        count = shape.channel_count
        addresses = [str(index) for index in range(count)]
        summary = f"{count} float channels at {rate}, no protocol recognised — name them?"
        return "raw-lines", addresses, summary
    if shape.framing != "json-lines":
        return None
    lb06 = _lb06_channels(samples)
    if lb06 is not None:
        return "lb06", lb06, f"Solus LB-06 telemetry, {len(lb06)} channels at {rate}"
    names = list(shape.channel_ranges)
    return "json-lines", names, f"plain JSON lines, {len(names)} numeric channels at {rate}"


def _channel_baud(channel: Channel) -> int:
    params: Mapping[str, Any] = getattr(channel, "params", None) or {}
    baud = params.get("baud")
    return baud if isinstance(baud, int) and not isinstance(baud, bool) else 0


class SerialFramingInterrogator:
    interrogator_id: ClassVar[str] = "serial-framing"
    transports: ClassVar[frozenset[TransportKind]] = LINE_TRANSPORTS
    safety: ClassVar[Safety] = Safety.LISTEN

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        samples = self._listen(channel, budget_s)
        baud = _channel_baud(channel)
        shape = characterize_stream(samples, port_name=channel.identity.device_ref, baud=baud)
        proposal = _proposal(shape, samples)
        if proposal is None:
            return None
        driver_id, addresses, summary = proposal
        bus_map: list[BusMapEntry] = []
        for address in addresses:
            try:
                bus_map.append(BusMapEntry(protocol=driver_id, address=address))
            except ValidationError:
                continue  # a key that is not a bus address cannot be mapped to a part
        return Interrogation(
            interrogator_id=self.interrogator_id,
            driver_id=driver_id,
            params={"baud": baud} if baud else {},
            bus_map=bus_map,
            evidence=[shape.evidence],
            confidence=min(MAX_SHAPE_CONFIDENCE, shape.evidence.confidence),
            summary=summary,
            details={
                "framing": shape.framing,
                "channel_count": len(addresses),
                "update_hz": shape.update_hz,
            },
        )

    def _listen(self, channel: Channel, budget_s: float) -> list[Sample]:
        reader = LineReader(channel, clock=self._clock)
        deadline = self._clock() + budget_s
        samples: list[Sample] = []
        while len(samples) < MAX_PROBE_LINES and self._clock() < deadline:
            line = reader.read_line(deadline=deadline)
            if line is not None:
                samples.append((self._clock(), line))
        return samples
