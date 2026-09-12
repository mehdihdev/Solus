"""The diagram data model — frozen, JSON-shaped, renderer-agnostic."""

from dataclasses import dataclass, field

#: The stub a wire lands on when the graph does not name the pin. Never a guess.
UNKNOWN_PIN = "?"


@dataclass(frozen=True)
class DiagramPin:
    name: str
    known: bool
    net: str | None = None  # the net (or firmware role) the pin is on, when recorded


@dataclass(frozen=True)
class DiagramNode:
    id: str
    label: str
    kind: str  # the graph entity kind, or "bus" for a config bus line
    pins: tuple[DiagramPin, ...] = ()


@dataclass(frozen=True)
class DiagramWire:
    from_node: str
    from_pin: str  # "" when the endpoint has no pin concept (a net / bus line)
    to_node: str
    to_pin: str
    label: str
    known: bool  # False when any endpoint pin is the UNKNOWN_PIN stub


@dataclass(frozen=True)
class Diagram:
    nodes: tuple[DiagramNode, ...] = ()
    wires: tuple[DiagramWire, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def unknown_pins(self) -> list[str]:
        """`<node label>: <wire label>` for every stubbed endpoint — what the tool reports."""
        labels = {n.id: n.label for n in self.nodes}
        out: list[str] = []
        for w in self.wires:
            if w.from_pin == UNKNOWN_PIN:
                out.append(f"{labels.get(w.from_node, w.from_node)}: {w.label}")
            if w.to_pin == UNKNOWN_PIN:
                out.append(f"{labels.get(w.to_node, w.to_node)}: {w.label}")
        return out
