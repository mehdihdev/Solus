# Architecture — SOL inside the tools (SOLUSDEV-251 / INTEGRATIONS I4)

What "SOL works inside Onshape, KiCad and Fusion" means mechanically, and what each leg has
actually been verified to do against a live instance. Companion docs: `docs/api/toolkb.md`
(the SOLUSDEV-251 amendment), `docs/contracts/action-gate.md` (the approval card), ADR-031 /
ADR-035 (hosting patterns), ADR-033 (tool knowledge is global and tenant-free).

## The three shapes, one gate

| Tool | READ | OPERATION | WRITE (through the approval card) | Diff on the card |
| --- | --- | --- | --- | --- |
| **Onshape** (REST, customer OAuth; `connectors/onshape_ops.py`) | `list_documents`, `list_elements`, `get_feature_tree`, `get_variables`, … | `get_mass_properties`, `get_body_details` | `set_variable` (read-merge-write of the WHOLE table), `add_feature`, `update_feature` | the operation's own `preview` |
| **KiCad** (owned fork over the bridge; `integrations/mcp/kicad`) | `extract_project_netlist`, `get_project_structure` | `analyze_schematic_connections`, `analyze_bom` | `set_symbol_property` (byte splice, workspace-confined, atomic) | `bridge/previews.py` reads the netlist first: `R1 · Value: 4.7k → 4k7` |
| **Fusion** (Autodesk's own loopback server, ADR-031 vendor-run; `integrations/mcp/fusion`) | — | — | — | — |

Every write reaches the tool only through `confirmations.decide_confirmation`, which re-runs
the preview at approve time and refuses on divergence; `requires_confirmation` comes from the
Solus-authored allowlist or operation table, never from anything a server advertises.

## Discovery, never hardcoding

Tool lists come from `tools/list` at connect on every transport: the companion's hello carries
the fork's live inventory (gated by `bridge/allowlist.py`), the hosted FeatureScript server is
listed live and filtered by its Solus allowlist (ADR-035), Onshape REST operations are a
Solus-owned table. Fusion's allowlist is deliberately EMPTY (`tools: []`): its server is closed
source and its tool set dynamic, so the only honest fixture is a live capture
(`scripts/capture-fusion-tools.py`, which needs Fusion running with its MCP server enabled).

## Tool knowledge in the loop

The global tool-knowledge table now reaches the model and hears back from it — see the
`docs/api/toolkb.md` amendment. The mapping from a write tool to the vendor control it acts on
is data (`TOOL_CONTROLS`); the note rides the tool description as a fenced block; the outcome of
each confirmed write is a vote. This is how "tool-specific, not generic" is mechanised without a
per-tool prompt: the vendor's own documentation, admitted through the guard, is what SOL reads.

## What was verified live, per tool (this Mac, 2026-09-07)

- **KiCad — verified.** Real SOL turn (Do mode) → `kicad.set_symbol_property` parked with the
  live diff `R1 · Value: 4.7k → 4k7` (the before value read through the bridge) → approved →
  the fork answered `changed: true` → the schematic on disk carries `4k7` → a second SOL turn
  read it back through `extract_project_netlist` and answered `4k7`. `analyze_schematic_connections`
  ran on the same project. The tool-knowledge entry received the confirm vote.
  (`tests/test_live_kicad_write.py` drives the same round-trip through the fork's launcher.)
- **Onshape — see the completion report** for whether a live document was available in this
  run; `tests/test_live_onshape_write.py` is the env-gated round-trip (token, document,
  element) through the real operations layer including the whole-table merge.
- **Fusion — deferred, honestly.** No Autodesk Fusion on this Mac (only VMware Fusion);
  `capture-fusion-tools.py` fails with "could not reach the Fusion MCP server at
  http://127.0.0.1:27182/mcp" as designed. The allowlist stays empty; nothing is invented.
