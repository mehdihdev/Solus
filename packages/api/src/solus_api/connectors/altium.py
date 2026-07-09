"""The Altium connector (SOLUSDEV-102, SOLUS-EDA-03) — parse-export, scaffolded.

Altium is proprietary, so v1 does NOT integrate with the running tool. It parses
a **committed Altium export** (the Protel netlist — native and simplest, W0-08
§5.4) into the shared electrical graph shape, exactly mirroring the EDA family
(`EdaExportConnector`): components + first-class `net` nodes + intra-source
`connected_to` edges.

This connector is therefore tiny by design — it is {a format parser} + {the
shared EDA family base}. Everything real (parse, map, the full W0-05 interface,
conformance) lives here and is tested; the only deferred piece is LIVE export
ACQUISITION (pulling the committed file from the linked repo at a ref, or any
direct Altium tool integration), which the family base stubs behind
`config['export']` with a clear v1 marker (`EdaExportConnector._read_export`).

v1 limitations (flagged): only the Protel netlist format (SPICE/orcadpcb2 exports
are a later extension), and stock Protel has no native MPN field (W0-08 §5.4), so
`modality_hints.part_number` is empty until a comment-field/ActiveBOM mapping is
added.
"""

from __future__ import annotations

from typing import ClassVar

from solus_api.connectors.eda import EdaExportConnector, Netlist
from solus_api.connectors.protel_netlist import parse_protel_netlist


class AltiumConnector(EdaExportConnector):
    """Committed-Altium-export connector. Parses the Protel netlist; the live
    proprietary path is a scaffolded post-launch stub (see module docstring)."""

    provider: ClassVar[str] = "altium"
    #: v1 scaffold: the committed Protel netlist CONTENT (live repo/tool
    #: acquisition is stubbed in the family base for post-launch — SOLUSDEV-102).
    config_fields: ClassVar[tuple[str, ...]] = ("export",)

    def parse(self, text: str) -> Netlist:
        return parse_protel_netlist(text)
