"""KiCad content sniffing and refusal guidance (SOLUSDEV-252, W0-08 §5.2/§5.2a).

Format is detected from CONTENT, never from a file extension — at this layer
there is none (the export arrives as text on a config key or from a live
acquirer). The two netlist formats and the board file are accepted; a raw
`.kicad_sch` or `.kicad_pro` is refused, not half-parsed (§5.2: a schematic
carries no pin-level connectivity without KiCad's own netlister), with guidance
naming the two accepted routes. Also home to the one shared step every
S-expression consumer needs: read the root list or raise the stable
`export_invalid` `ConnectorError`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final, Literal

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.kicad_sexpr import Sexp, SExprSyntaxError, parse_sexpr, string_at

type KicadFormat = Literal["xml_netlist", "sexpr_netlist", "pcb", "schematic", "project", "unknown"]
type ExpectedKind = Literal["netlist", "board"]

#: Stable error code for "right tool, wrong file" (shared with the XML path).
FORMAT_UNSUPPORTED: Final = "export_format_unsupported"

_LEADING: Final = "﻿ \t\r\n"
_HEAD_ATOM: Final = re.compile(r"\(\s*([A-Za-z_]+)")
_SEXPR_ROOTS: Final[dict[str, KicadFormat]] = {
    "export": "sexpr_netlist",
    "kicad_pcb": "pcb",
    "kicad_sch": "schematic",
}
#: A `.kicad_pro` is JSON; its identifying keys sit near the top of the file.
_PROJECT_SNIFF_CHARS: Final = 4096
_PROJECT_HINTS: Final = ("kicad_pro", "meta")

_NETLIST_ROUTES: Final = (
    "Export a netlist from KiCad (File → Export → Netlist, any format, or "
    "`kicad-cli sch export netlist`) or provide the .kicad_pcb board file."
)
_MESSAGES: Final[dict[KicadFormat, str]] = {
    "schematic": (
        "kicad: a .kicad_sch schematic can't be read directly yet (no pin-level "
        "connectivity without KiCad's own netlister). " + _NETLIST_ROUTES
    ),
    "project": (
        "kicad: a .kicad_pro project file holds settings, not the design. Export a "
        "netlist from KiCad (File → Export → Netlist, any format) or provide the "
        ".kicad_pcb board file."
    ),
    "unknown": (
        "kicad: unrecognized file — expected a KiCad netlist (XML or S-expression) "
        "or a .kicad_pcb board file."
    ),
}
_BOARD_AS_NETLIST: Final = (
    "kicad: this is a .kicad_pcb board file; supply it as the board, not as the netlist export."
)
_NETLIST_AS_BOARD: Final = (
    "kicad: expected a .kicad_pcb board file but received a netlist; "
    "supply it as the netlist export."
)


def detect_kicad_format(text: str) -> KicadFormat:
    """Sniff which KiCad artifact *text* is from its opening bytes.

    A UTF-8 BOM and leading whitespace are ignored. `<` is reported as an XML
    netlist optimistically — the XML parser still validates the root.
    """
    head = text.lstrip(_LEADING)
    if head.startswith("("):
        match = _HEAD_ATOM.match(head)
        return _SEXPR_ROOTS.get(match.group(1), "unknown") if match else "unknown"
    if head.startswith("<"):
        return "xml_netlist"
    if head.startswith("{"):
        window = head[:_PROJECT_SNIFF_CHARS]
        return "project" if any(hint in window for hint in _PROJECT_HINTS) else "unknown"
    return "unknown"


def refuse_unsupported(fmt: KicadFormat, *, expected: ExpectedKind) -> ConnectorError:
    """The `export_format_unsupported` error for content of format *fmt* handed
    to the parser that expected a *expected* ("netlist" or "board")."""
    if fmt == "pcb" and expected == "netlist":
        message = _BOARD_AS_NETLIST
    elif fmt in ("xml_netlist", "sexpr_netlist") and expected == "board":
        message = _NETLIST_AS_BOARD
    else:
        message = _MESSAGES.get(fmt, _MESSAGES["unknown"])
    return ConnectorError(FORMAT_UNSUPPORTED, message)


def read_sexpr_root(
    text: str,
    *,
    prune: Callable[[str, int], bool],
    expected_head: str,
    kind: str,
) -> tuple[Sexp, ...]:
    """Parse an S-expression document whose root must be `(<expected_head> …)`.

    Malformed text and tripped resource guards become
    `ConnectorError("export_invalid")`, as does a wrong root — the whole
    document is unusable, so the sync fails with a stable reason rather than
    producing a silently empty graph.
    """
    try:
        # `detect_kicad_format` ignores a BOM and leading whitespace, so the
        # reader must too — otherwise a correctly-sniffed, perfectly valid
        # Windows-authored export dies as "content outside the root list" (S6).
        root = parse_sexpr(text.lstrip(_LEADING), prune=prune)
    except SExprSyntaxError as exc:
        raise ConnectorError(
            "export_invalid", f"kicad: not a well-formed S-expression ({exc})"
        ) from exc
    if string_at(root, 0) != expected_head:
        raise ConnectorError(
            "export_invalid", f"kicad: not a {kind} (expected ({expected_head} …) root)"
        )
    return root
