"""The `json-lines` driver: any JSON object per line, numeric leaves flattened into signals.
Not a Solus producer, so the device_ref is always the identity — an LB-06-shaped line that
asserts another `device_id` is dropped by the shared decoder's spoofing guard."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel
from solus_api.hardware.config import HardwareConfig, TransportKind

from livebench.hardware.channel import Channel
from livebench.plugins.lb06.lb06_driver import LINE_TRANSPORTS, Lb06Source
from livebench.plugins.lb06.lb06_lines import LineTransportParams


class JsonLinesDriver:
    driver_id: ClassVar[str] = "json-lines"
    display_name: ClassVar[str] = "JSON lines"
    transports: ClassVar[frozenset[TransportKind]] = LINE_TRANSPORTS
    params_model: ClassVar[type[BaseModel]] = LineTransportParams

    def open(self, channel: Channel, params: BaseModel, config: HardwareConfig) -> Lb06Source:
        return Lb06Source(channel, trusted_identity=False)
