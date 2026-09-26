"""Bounded session-local adaptation of the existing statistical change observer.

A change point reports a signal distribution shift, never a physical fault or
rating breach. Session ownership prevents baselines crossing reconnects/tenants.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from solus_api.graph.packet import TelemetryPacket

from livebench.anomaly.observers import CusumObserver


@dataclass
class _Signal:
    observer: CusumObserver
    unit: str | None
    timestamp: datetime
    seq: int | None


class SessionObservers:
    def __init__(self, max_signals: int = 128) -> None:
        if not 1 <= max_signals <= 256:
            raise ValueError("max_signals must be between 1 and 256")
        self._limit = max_signals
        self._signals: dict[tuple[str, str], _Signal] = {}

    def add(self, packet: TelemetryPacket) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for signal, value in packet.values.items():
            if not math.isfinite(value):
                continue
            key = (packet.device_id, signal)
            state = self._signals.get(key)
            unit = packet.units.get(signal)
            if state is not None and self._out_of_order(state, packet):
                continue
            if state is None:
                if len(self._signals) >= self._limit:
                    continue
                state = _Signal(CusumObserver(signal), unit, packet.timestamp, packet.seq)
                self._signals[key] = state
            elif state.unit != unit:
                state.observer = CusumObserver(signal)
                state.unit = unit
            state.timestamp, state.seq = packet.timestamp, packet.seq
            try:
                detected = state.observer.add(packet)
            except (ArithmeticError, ValueError):
                # Finite input can overflow CUSUM intermediate arithmetic. Reset
                # this signal only; telemetry ingest must remain available.
                state.observer = CusumObserver(signal)
                continue
            for event in detected:
                if all(
                    not isinstance(v, (float, int)) or math.isfinite(v)
                    for v in event.detail.values()
                ):
                    events.append(event.model_dump(mode="json"))
        return events

    @staticmethod
    def _out_of_order(state: _Signal, packet: TelemetryPacket) -> bool:
        if state.seq is not None and packet.seq is not None:
            return packet.seq <= state.seq
        return packet.timestamp <= state.timestamp
