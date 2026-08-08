"""The Altium connector (SOLUSDEV-102, SOLUS-EDA-03) — parse-export, scaffolded.

Altium is proprietary, so v1 does NOT integrate with the running tool. It parses
a **committed Altium export** (the Protel netlist — native and simplest, W0-08
§5.4) into the shared electrical graph shape, exactly mirroring the EDA family
(`EdaExportConnector`): components + first-class `net` nodes + intra-source
`connected_to` edges.

This connector is therefore tiny by design — it is {a format parser} + {the
shared EDA family base}. Everything real (parse, map, the full W0-05 interface,
conformance) lives here and is tested. Live export ACQUISITION (an injected
`ExportAcquirer` — e.g. a bridge/MCP export call, or a future direct Altium
tool integration, SOLUSDEV-100 T4a) is tried first when configured; the
family base falls back to inline `config['export']` on decline/failure either
way (`EdaExportConnector._read_export`). Wiring a concrete acquirer into this
connector at construction is a later ticket (this base stays zero-arg
constructible by default).

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
    #: `export` — the committed Protel netlist CONTENT, sufficient on its own
    #: (§2.1 invariant 3). `project_path` — additive, read by the injected
    #: `BridgeExportAcquirer` (mcp_acquire.py) to locate the project on the
    #: companion machine for live acquisition; absent, the live path declines
    #: cleanly and the inline export proceeds unchanged (SOLUSDEV-102 ALT-8).
    config_fields: ClassVar[tuple[str, ...]] = ("export", "project_path")

    def parse(self, text: str) -> Netlist:
        return parse_protel_netlist(text)
