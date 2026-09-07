"""The Interrogator seam (R2): the detection loop tries registered interrogators over an open
channel and collects what each can honestly say. It never assumes a servo bus.

Safety classes: `passive` (reads nothing that was not already there), `ping` (a presence
request that no device interprets as a command), `listen` (receive only). Commanding motion is
not an interrogation — that stays behind the confirmation gate (RBT-04).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from solus_api.fingerprint.contract import ModalityMatch
from solus_api.hardware.config import BusMapEntry, TransportKind

from livebench.hardware.channel import Channel

logger = logging.getLogger(__name__)


class Safety(enum.StrEnum):
    PASSIVE = "passive"
    PING = "ping"
    LISTEN = "listen"


@dataclass(frozen=True)
class Interrogation:
    """What one interrogator learned: evidence for the fingerprint seam, a bus map, and the
    driver + parameters that would speak to it. An input to a proposal, never a decision."""

    interrogator_id: str
    driver_id: str | None
    params: dict[str, Any]
    bus_map: list[BusMapEntry]
    evidence: list[ModalityMatch]
    confidence: float
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


class Interrogator(Protocol):
    interrogator_id: ClassVar[str]
    transports: ClassVar[frozenset[TransportKind]]
    safety: ClassVar[Safety]

    def probe(self, channel: Channel, *, budget_s: float) -> Interrogation | None:
        """Probe within `budget_s` seconds; None when this channel is not ours."""
        ...


class InterrogatorRegistry:
    def __init__(self) -> None:
        self._interrogators: dict[str, Interrogator] = {}

    def register(self, interrogator_cls: type[Interrogator]) -> None:
        interrogator = interrogator_cls()
        if interrogator.interrogator_id in self._interrogators:
            raise ValueError(f"interrogator {interrogator.interrogator_id} is already registered")
        Safety(interrogator.safety)  # a class outside passive/ping/listen cannot register
        self._interrogators[interrogator.interrogator_id] = interrogator

    def get(self, interrogator_id: str) -> Interrogator:
        return self._interrogators[interrogator_id]  # KeyError: unknown

    def for_transport(self, kind: TransportKind) -> list[Interrogator]:
        return [i for i in self._interrogators.values() if kind in i.transports]

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "interrogator_id": i.interrogator_id,
                "transports": sorted(kind.value for kind in i.transports),
                "safety": i.safety.value,
            }
            for i in self._interrogators.values()
        ]


def interrogate(
    channel: Channel, registry: InterrogatorRegistry, *, budget_s: float
) -> list[Interrogation]:
    """Run every interrogator that rides this channel's transport, in registration order.
    A probe that raises is skipped — the loop never dies on one plugin's fault."""
    results: list[Interrogation] = []
    for interrogator in registry.for_transport(channel.kind):
        channel.flush_input()  # a previous probe's stale bytes must not answer this one
        try:
            result = interrogator.probe(channel, budget_s=budget_s)
        except Exception as exc:
            logger.warning(
                "interrogator %s failed on %s: %s",
                interrogator.interrogator_id,
                channel.identity.device_ref,
                type(exc).__name__,
            )
            continue
        if result is not None:
            results.append(result)
    return results
