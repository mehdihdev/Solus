"""Protel-netlist parser (SOLUSDEV-102, W0-08 §5.4/§6.3).

Altium's recommended committed export is the Protel netlist — the native, simplest
format, parseable with a small stdlib state machine (no third-party dep, no eval,
no subprocess). It has two block kinds:

    [                     (                    <- net block
    U1        component   NET_NAME
    SOIC-8    footprint   U1-8   Designator-Pin
    LM358     comment     R1-1
                          )
    ]

`[ … ]` = a component (designator, footprint, comment/value); `( … )` = a net
(name then `Designator-Pin` nodes). Output is the shared EDA netlist IR
(`eda.Netlist`) the whole electrical family maps from.

Lenient by design: unterminated blocks and malformed node lines are skipped, not
raised, so one bad line never fails a whole sync. Ingested text is untrusted DATA
(CLAUDE.md §7) — never interpreted, only scanned line by line.
"""

from __future__ import annotations

from solus_api.connectors.eda import Component, Net, Netlist, Node

_COMPONENT_OPEN = "["
_COMPONENT_CLOSE = "]"
_NET_OPEN = "("
_NET_CLOSE = ")"


def parse_protel_netlist(text: str) -> Netlist:
    """Parse Protel netlist text into the shared EDA IR. Never raises on content.

    Lenient: unterminated, reopened, and empty blocks are skipped — but the count
    of skipped blocks is surfaced on `Netlist.warnings` so a partial parse is
    visible on the sync record, not a silent smaller-than-expected graph.
    """
    components: list[Component] = []
    nets: list[Net] = []
    state: str | None = None  # None | "component" | "net"
    buffer: list[str] = []
    dropped = 0

    for raw in text.splitlines():
        line = raw.strip()
        if state is None:
            if line == _COMPONENT_OPEN:
                state, buffer = "component", []
            elif line == _NET_OPEN:
                state, buffer = "net", []
            continue

        closer = _COMPONENT_CLOSE if state == "component" else _NET_CLOSE
        if line == closer:
            if not _emit(state, buffer, components, nets):
                dropped += 1  # empty block
            state, buffer = None, []
        elif line in (_COMPONENT_OPEN, _NET_OPEN):
            # A new opener before the current block closed: the current block is
            # malformed/unterminated — drop it and start the new one.
            dropped += 1
            state = "component" if line == _COMPONENT_OPEN else "net"
            buffer = []
        elif line:
            buffer.append(line)
    if state is not None:
        dropped += 1  # a block still open at EOF is unterminated

    warnings = (f"skipped {dropped} malformed or empty block(s)",) if dropped else ()
    return Netlist(components=tuple(components), nets=tuple(nets), warnings=warnings)


def _emit(
    state: str,
    buffer: list[str],
    components: list[Component],
    nets: list[Net],
) -> bool:
    """Append the parsed block; return False if it was empty (nothing emitted)."""
    if state == "component":
        component = _component(buffer)
        if component is not None:
            components.append(component)
            return True
        return False
    net = _net(buffer)
    if net is not None:
        nets.append(net)
        return True
    return False


def _component(buffer: list[str]) -> Component | None:
    if not buffer:
        return None
    return Component(
        designator=buffer[0],
        footprint=buffer[1] if len(buffer) > 1 else None,
        value=buffer[2] if len(buffer) > 2 else None,
    )


def _net(buffer: list[str]) -> Net | None:
    if not buffer:
        return None
    name, *node_lines = buffer
    nodes: list[Node] = []
    for entry in node_lines:
        designator, dash, pin = entry.partition("-")
        if dash and designator and pin:
            nodes.append(Node(designator=designator, pin=pin))
    return Net(name=name, nodes=tuple(nodes))
