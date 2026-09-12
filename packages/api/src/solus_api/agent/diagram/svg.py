"""`Diagram` → SVG string. Deterministic layout: controllers/boards left, nets and
buses in the middle, parts right; stable sort by label. Text is XML-escaped; there
are no scripts, no foreignObject, no external references — a viewer can inline it.
"""

from __future__ import annotations

from typing import Final
from xml.sax.saxutils import escape, quoteattr

from solus_api.agent.diagram.model import Diagram, DiagramNode

#: Hard ceiling on the rendered document; build.MAX_NODES/MAX_WIRES keep us far under it.
MAX_SVG_BYTES: Final = 200_000
CONTROLLER_KINDS: Final = frozenset(
    {"physical_robot", "board", "controller", "microcontroller", "mcu", "computer", "sbc"}
)
LINE_KINDS: Final = frozenset({"net", "bus"})

_W, _HEAD, _ROW, _GAP, _PAD = 200, 26, 16, 24, 40
_COLS: Final = (_PAD, _PAD + _W + 160, _PAD + 2 * (_W + 160))
_STYLE: Final = (
    "text{font:11px sans-serif;fill:#222}.title{font-size:14px;font-weight:bold}"
    ".node{fill:#fff;stroke:#333;stroke-width:1.2}.line{fill:#eef;stroke:#557}"
    ".wire{stroke:#2a6;stroke-width:1.5;fill:none}.wire.unknown{stroke:#c53;stroke-dasharray:5 4}"
    ".pin.unknown{fill:#c53;font-style:italic}.note{fill:#555}"
)


def _column(node: DiagramNode) -> int:
    if node.kind in CONTROLLER_KINDS:
        return 0
    return 1 if node.kind in LINE_KINDS else 2


def _height(node: DiagramNode) -> int:
    return _HEAD + _ROW * max(1, len(node.pins))


def _place(diagram: Diagram) -> dict[str, tuple[int, int, int]]:
    """node id → (x, y, height); each column stacks in the diagram's (label-sorted) order."""
    y = [_PAD + 30] * 3
    out: dict[str, tuple[int, int, int]] = {}
    for node in sorted(diagram.nodes, key=lambda n: (n.label.lower(), n.id)):
        col = _column(node)
        out[node.id] = (_COLS[col], y[col], _height(node))
        y[col] += _height(node) + _GAP
    return out


def _pin_y(node: DiagramNode, pin: str, y: int) -> int:
    names = [p.name for p in node.pins]
    row = names.index(pin) if pin in names else 0
    return y + _HEAD + _ROW * row + _ROW // 2


def _node_svg(node: DiagramNode, x: int, y: int, h: int) -> list[str]:
    cls = "node line" if node.kind in LINE_KINDS else "node"
    parts = [
        f'<rect class="{cls}" x="{x}" y="{y}" width="{_W}" height="{h}" rx="4"/>',
        f'<text x="{x + 8}" y="{y + 17}" font-weight="bold">{escape(node.label)}</text>',
        f'<text x="{x + _W - 8}" y="{y + 17}" text-anchor="end" class="note">'
        f"{escape(node.kind)}</text>",
    ]
    for i, pin in enumerate(node.pins):
        cls = "pin" if pin.known else "pin unknown"
        label = pin.name if pin.known else "unknown pin"
        py = y + _HEAD + _ROW * i + 12
        parts.append(f'<text class="{cls}" x="{x + 8}" y="{py}">{escape(label)}</text>')
        if pin.net:
            parts.append(
                f'<text class="note" x="{x + _W - 8}" y="{py}" text-anchor="end">'
                f"{escape(pin.net)}</text>"
            )
    return parts


def render_svg(diagram: Diagram, *, title: str) -> str:
    nodes = {n.id: n for n in diagram.nodes}
    placed = _place(diagram)
    body: list[str] = []
    for node in diagram.nodes:
        x, y, h = placed[node.id]
        body.extend(_node_svg(node, x, y, h))
    for w in diagram.wires:
        if w.from_node not in placed or w.to_node not in placed:
            continue
        ax, ay, _ = placed[w.from_node]
        bx, by, _ = placed[w.to_node]
        left, right = (ax, bx) if ax <= bx else (bx, ax)
        y1 = _pin_y(nodes[w.from_node], w.from_pin, ay)
        y2 = _pin_y(nodes[w.to_node], w.to_pin, by)
        if ax > bx:
            y1, y2 = y2, y1
        x1, x2 = left + _W, right
        if ax == bx:  # same column: hook around the right edge
            x1, x2 = left + _W, right + _W
        mid = (x1 + x2) // 2
        cls = "wire" if w.known else "wire unknown"
        body.append(
            f'<path class="{cls}" d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}"/>'
            f'<text class="note" x="{mid}" y="{(y1 + y2) // 2 - 3}" text-anchor="middle">'
            f"{escape(w.label)}</text>"
        )
    bottom = max((y + h for _, y, h in placed.values()), default=_PAD + 30) + _GAP
    legend = [
        f'<text class="title" x="{_PAD}" y="{_PAD}">{escape(title)}</text>',
        f'<text x="{_PAD}" y="{bottom}" font-weight="bold">Legend</text>',
        f'<path class="wire" d="M{_PAD},{bottom + 14} h40"/>'
        f'<text x="{_PAD + 48}" y="{bottom + 18}">pin recorded in the graph</text>',
        f'<path class="wire unknown" d="M{_PAD},{bottom + 30} h40"/>'
        f'<text x="{_PAD + 48}" y="{bottom + 34}">unknown pin (not recorded)</text>',
    ]
    ny = bottom + 54
    for note in diagram.notes:
        legend.append(f'<text class="note" x="{_PAD}" y="{ny}">{escape(note)}</text>')
        ny += _ROW
    width, height = _COLS[2] + _W + _PAD, ny + _PAD
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label={quoteattr(title)}>'
        f"<style>{_STYLE}</style>{''.join(legend)}{''.join(body)}</svg>"
    )
    if len(svg.encode()) > MAX_SVG_BYTES:  # pragma: no cover — build bounds make this unreachable
        raise ValueError(f"diagram exceeds {MAX_SVG_BYTES} bytes")
    return svg
