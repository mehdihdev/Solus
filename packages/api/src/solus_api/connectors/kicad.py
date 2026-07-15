"""The KiCad connector (SOLUSDEV-100, SOLUS-EDA-01) — parse-export.

KiCad's committed export is the XML netlist (W0-08 §5.2, the electrical PRIMARY).
It parses into the shared electrical graph shape via the EDA family
(`EdaExportConnector`): components + first-class `net` nodes + intra-source
`connected_to` edges, with the fingerprint channels (`part_number` from an MPN
custom field, `schematic_symbol_name`, `datasheet_ref`) on `modality_hints`.

This connector is therefore tiny by design — it is {a format parser} + {the
shared EDA family base}. The only deferred piece is LIVE export ACQUISITION
(pulling the committed file from the linked repo at a ref), which the family
base stubs behind `config['export']` with a clear v1 marker
(`EdaExportConnector._read_export`).

v1 limitations (flagged): XML netlist only (design review Q2) — the S-expr
`.net` is rejected with re-export guidance rather than half-parsed.
"""

from __future__ import annotations

from typing import ClassVar

from solus_api.connectors.eda import EdaExportConnector, Netlist
from solus_api.connectors.kicad_netlist import parse_kicad_netlist


class KicadConnector(EdaExportConnector):
    """Committed-KiCad-export connector. Parses the XML netlist; live repo
    acquisition is the family's scaffolded post-launch stub (module docstring)."""

    provider: ClassVar[str] = "kicad"
    #: v1 scaffold: the committed XML netlist CONTENT (live repo acquisition is
    #: stubbed in the family base for post-launch — SOLUSDEV-100).
    config_fields: ClassVar[tuple[str, ...]] = ("export",)

    def parse(self, text: str) -> Netlist:
        return parse_kicad_netlist(text)
