"""Pure Protel netlist emission for the Solus-authored `export_netlist` tool
(SOLUSDEV-102 ALT-6).

Builds exactly the text the cloud parser
(`solus_api.connectors.protel_netlist.parse_protel_netlist`) consumes:
`[` / designator / footprint / comment / `]` component blocks and `(` /
net-name / `DESIGNATOR-PIN` node lines / `)` net blocks — every token on its
own line, structural delimiters alone on theirs. This module never imports
solus_api (the overlay runs standalone on customer machines); the round-trip
equivalence is pinned by tests/test_overlay_export_netlist.py, which imports
the real parser.

Untrusted-input posture (CLAUDE.md §7): every field value originates in the
customer's Altium project — designators, comments, footprints, and net names
are attacker-influencable DATA. Invariants:

* **No forgery.** The parser recognizes structure only when a WHOLE line
  (after `str.strip()`) equals a delimiter, so forgery requires minting a
  line. Every character `str.splitlines()` treats as a line boundary is
  neutralized to a space, collapsing an embedded ``"\\n]\\n("`` into one
  inert data line. A field whose entire neutralized value IS a delimiter has
  no inert spelling on its own line — the emitter refuses outright.
* **No silent identity corruption.** Node lines split on the FIRST ``-``;
  a node designator containing ``-`` would mis-parse into another
  component's identity. Refused, never guessed.
* **Bounded output.** Component/net/node counts and the total emitted size
  are capped; past a cap the emitter refuses with a stable reason instead of
  producing an unbounded artifact.

Refusals raise `ProtelEmitRefusalError` carrying a stable `.reason`; the tool
layer (`solus/netlist_export.py`) maps them into its degraded envelope — this
module stays pure (data in, text out, no I/O, no hidden state).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Every character `str.splitlines()` treats as a line boundary — the exact
#: set the cloud parser splits on, so neutralizing these is sufficient to
#: keep any field value on a single line.
_LINE_BOUNDARY_CHARS = "\n\r\v\f\x1c\x1d\x1e\x85  "
_NEUTRALIZE_TABLE = str.maketrans(dict.fromkeys(_LINE_BOUNDARY_CHARS, " "))

_STRUCTURAL_DELIMITERS = frozenset({"[", "]", "(", ")"})

#: Placeholder for an empty footprint when a comment follows it — the parser
#: is positional (line 2 = footprint, line 3 = comment) and drops blank
#: lines, so the slot must be occupied to keep the comment in its place.
_EMPTY_FIELD_PLACEHOLDER = "*"

#: Bounds. Data volume caps, not correctness limits: a real board sits far
#: below all four; an adversarial payload is refused, never emitted.
MAX_COMPONENTS = 20_000
MAX_NETS = 20_000
MAX_NODES = 200_000
OUTPUT_MAX_BYTES = 4 * 1024 * 1024

REASON_CONTENT_UNREPRESENTABLE = "netlist_content_unrepresentable"
REASON_BOUNDS_EXCEEDED = "netlist_bounds_exceeded"


@dataclass(frozen=True)
class ProtelComponent:
    """One `[ … ]` block: designator plus optional footprint/comment."""

    designator: str
    footprint: str = ""
    comment: str = ""


@dataclass(frozen=True)
class ProtelNet:
    """One `( … )` block: net name plus (designator, pin) nodes."""

    name: str
    nodes: tuple[tuple[str, str], ...] = ()


class ProtelEmitRefusalError(Exception):
    """Raised instead of emitting unrepresentable or unbounded content.

    `reason` is one of the stable module-level REASON_* strings the tool
    layer surfaces verbatim in its degraded envelope."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def _neutralized(value: str) -> str:
    """*value* flattened onto a single inert line.

    Line-boundary characters become spaces and whitespace runs collapse to
    one space (so "\\r\\n" and "\\n" neutralize identically); the result is
    stripped (the parser strips every line anyway). A value whose entirety
    is a structural delimiter is refused — emitted on its own line it WOULD
    be structure."""
    flat = " ".join(value.translate(_NEUTRALIZE_TABLE).split())
    if flat in _STRUCTURAL_DELIMITERS:
        raise ProtelEmitRefusalError(
            REASON_CONTENT_UNREPRESENTABLE,
            f"field value is a bare Protel structural delimiter: {flat!r}",
        )
    return flat


def _component_lines(component: ProtelComponent) -> list[str]:
    designator = _neutralized(component.designator)
    if not designator:
        return []
    footprint = _neutralized(component.footprint)
    comment = _neutralized(component.comment)
    lines = ["[", designator]
    if footprint or comment:
        lines.append(footprint or _EMPTY_FIELD_PLACEHOLDER)
    if comment:
        lines.append(comment)
    lines.append("]")
    return lines


def _node_line(designator: str, pin: str) -> str | None:
    flat_designator = _neutralized(designator)
    flat_pin = _neutralized(pin)
    if not flat_designator or not flat_pin:
        return None
    if "-" in flat_designator:
        raise ProtelEmitRefusalError(
            REASON_CONTENT_UNREPRESENTABLE,
            f"node designator contains '-', which the Protel node line cannot "
            f"represent without corrupting identity: {flat_designator!r}",
        )
    return f"{flat_designator}-{flat_pin}"


def emit_protel_netlist(components: Iterable[ProtelComponent], nets: Iterable[ProtelNet]) -> str:
    """The Protel netlist text for *components* and *nets*.

    Raises `ProtelEmitRefusalError` (stable `.reason`) on unrepresentable field
    values or exceeded bounds; otherwise the returned text is guaranteed to
    be at most `OUTPUT_MAX_BYTES` and to round-trip through the cloud parser
    with every field value as data."""
    component_list = list(components)
    net_list = list(nets)
    if len(component_list) > MAX_COMPONENTS:
        raise ProtelEmitRefusalError(
            REASON_BOUNDS_EXCEEDED, f"component count exceeds {MAX_COMPONENTS}"
        )
    if len(net_list) > MAX_NETS:
        raise ProtelEmitRefusalError(REASON_BOUNDS_EXCEEDED, f"net count exceeds {MAX_NETS}")

    lines: list[str] = []
    for component in component_list:
        lines.extend(_component_lines(component))

    node_total = 0
    for net in net_list:
        name = _neutralized(net.name)
        if not name:
            continue
        node_lines: list[str] = []
        for designator, pin in net.nodes:
            node = _node_line(designator, pin)
            if node is not None:
                node_lines.append(node)
        node_total += len(node_lines)
        if node_total > MAX_NODES:
            raise ProtelEmitRefusalError(
                REASON_BOUNDS_EXCEEDED, f"total node count exceeds {MAX_NODES}"
            )
        lines.append("(")
        lines.append(name)
        lines.extend(node_lines)
        lines.append(")")

    text = "\n".join(lines) + "\n" if lines else ""
    if len(text.encode("utf-8")) > OUTPUT_MAX_BYTES:
        raise ProtelEmitRefusalError(
            REASON_BOUNDS_EXCEEDED, f"emitted netlist exceeds {OUTPUT_MAX_BYTES} bytes"
        )
    return text
