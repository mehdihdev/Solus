"""The KiCad connector (SOLUSDEV-100 / SOLUSDEV-252, SOLUS-EDA-01).

A KiCad source ingests up to two committed design inputs, both untrusted text
under the family's 8 MiB bound (CLAUDE.md §7; contract §2.1 invariant 4):

* `config["export"]` — a KiCad netlist in EITHER format, content-detected:
  the XML netlist (`--format kicadxml`) or the default S-expression `.net`
  (W0-08 §5.2). Identical field mapping either way, so the fingerprint
  channels (`part_number` from an MPN custom field, `schematic_symbol_name`
  from libsource, `datasheet_ref`) flow the same. A live `ExportAcquirer`
  (bridge/MCP export, SOLUSDEV-100 T4a) is tried first when injected and the
  family base falls back to the inline text on decline/failure
  (`EdaExportConnector._select_export`).
* `config["board"]` — a `.kicad_pcb` board file (§5.2a): footprints →
  components (no `schematic_symbol_name`, by design), pads → net memberships.
  Inline only in v1 — no live acquisition tool exists for it.

At least one must be present. With both, `kicad_reconcile` applies §5.2a: the
netlist is authoritative for identity and connectivity, the board corroborates
(layer), and every disagreement is a per-item `SyncError` — never merged
silently. A board-only source uses the board as its connectivity source.

A raw `.kicad_sch`/`.kicad_pro` — or a board handed in as the netlist and vice
versa — is refused with `export_format_unsupported` and guidance naming the
accepted routes (`kicad_formats`); a schematic is never half-parsed into a
components-only graph (§5.2). The change-detection hash covers both texts.
"""

from __future__ import annotations

from typing import ClassVar, Final

from solus_api.connectors.contracts import ConnectorError, SyncContext, SyncError, SyncResult
from solus_api.connectors.eda import EdaExportConnector, Netlist, build_graph
from solus_api.connectors.export_common import content_sha as _content_sha
from solus_api.connectors.kicad_netlist import parse_kicad_netlist
from solus_api.connectors.kicad_pcb import parse_kicad_pcb
from solus_api.connectors.kicad_reconcile import mismatch_item, reconcile_kicad

#: The `SyncContext.config` key the `.kicad_pcb` board text arrives on (§5.2a).
BOARD_CONFIG_KEY: Final = "board"

#: Joins the two input texts for the content hash. A control character no
#: KiCad file contains, so `(netlist, board)` pairs can never collide by
#: shifting bytes across the boundary; an absent side contributes "".
_HASH_SEPARATOR: Final = "\x1e"

_NO_INPUT_MESSAGE: Final = (
    "kicad: no design input — supply a netlist export on config['export'] (KiCad XML "
    "or S-expression; or via the live acquirer) and/or a .kicad_pcb board file on "
    "config['board']."
)


class KicadConnector(EdaExportConnector):
    """Committed-KiCad connector: netlist export and/or board file → the shared
    electrical graph (module docstring; contract §5.2/§5.2a)."""

    provider: ClassVar[str] = "kicad"
    #: The two design inputs. `export` rides the family's acquisition chain;
    #: `board` is inline only (§5.2a). `project_path` (live acquisition of the
    #: netlist, as Altium advertises) is still owed by a later ticket.
    config_fields: ClassVar[tuple[str, ...]] = ("export", BOARD_CONFIG_KEY)

    def parse(self, text: str) -> Netlist:
        """The family's single-export entry point: the netlist (either format)."""
        return parse_kicad_netlist(text)

    async def sync(self, ctx: SyncContext) -> SyncResult:
        netlist_text, board_text = await self._read_inputs(ctx)
        # Each parser's refusal propagates unchanged — a board handed in as the
        # netlist yields the "supply it as the board" guidance, and vice versa.
        netlist = parse_kicad_netlist(netlist_text) if netlist_text is not None else None
        board = parse_kicad_pcb(board_text) if board_text is not None else None
        entities, relations, errors = build_graph(reconcile_kicad(netlist, board))
        return SyncResult(
            entities=entities,
            relations=relations,
            cursor={"content_sha": _content_sha(_combined(netlist_text, board_text))},
            errors=[_relabel(error) for error in errors],
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        # Re-parse-and-diff (W0-05 §7) over BOTH inputs (§5.2a). On any
        # acquisition failure, be safe and let a full sync decide.
        try:
            netlist_text, board_text = await self._read_inputs(ctx)
        except ConnectorError:
            return True
        return _content_sha(_combined(netlist_text, board_text)) != ctx.cursor.get("content_sha")

    async def _read_inputs(self, ctx: SyncContext) -> tuple[str | None, str | None]:
        """`(netlist_text, board_text)` — the acquisition chain for the netlist,
        inline only for the board; raises `export_unavailable` when neither exists."""
        netlist_text = await self._select_export(ctx)
        board_text = self._inline_text(ctx, BOARD_CONFIG_KEY)
        if netlist_text is None and board_text is None:
            raise ConnectorError("export_unavailable", _NO_INPUT_MESSAGE)
        return netlist_text, board_text


def _combined(netlist_text: str | None, board_text: str | None) -> str:
    return f"{netlist_text or ''}{_HASH_SEPARATOR}{board_text or ''}"


def _relabel(error: SyncError) -> SyncError:
    """`build_graph` files every parser warning under `parse`; a reconciliation
    finding is about ONE part or net, so label it that way (§5.2a per-item)."""
    item = mismatch_item(error.message)
    return error if item is None else SyncError(item=item, message=error.message)
