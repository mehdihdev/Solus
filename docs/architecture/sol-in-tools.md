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

SOLUSDEV-261 sync clarification: a STEP translation refusal does not prove that
the entire document is unusable. The connector may omit geometry for a tab only
after a successful, schema-valid API read positively establishes an empty Part
Studio part list or an empty Assembly instance list. Unknown, malformed, or
nonempty responses preserve the export failure and leave the prior graph intact.
Empty tabs contribute no mechanical geometry; the selected document root remains.

The global tool-knowledge table now reaches the model and hears back from it — see the
`docs/api/toolkb.md` amendment. The mapping from a write tool to the vendor control it acts on
is data (`TOOL_CONTROLS`); the note rides the tool description as a fenced block; the outcome of
each confirmed write is a vote. This is how "tool-specific, not generic" is mechanised without a
per-tool prompt: the vendor's own documentation, admitted through the guard, is what SOL reads.

SOLUSDEV-261 also maps schematic symbol, wire, label and no-connect tools to the
official KiCad action controls. Published default shortcuts travel inside the same
bounded data note. The installed KiCad10 action definitions are imported through
the existing guarded importer; unclassifiable actions are skipped. Onshape's
existing `>=1.0 <2.0` note identity is a repository compatibility convention, not
evidence of a vendor SaaS release. Current SOL note loading is version-unfiltered.

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

## SOLUSDEV-262 — surface-aware Guide integration

The SOL window mounts the existing TU09 guide task picker/panel in Guide mode. Trusted
application metadata selects scriptable, browser or native presentation; KB control placement
is not a host-surface classification. Scriptable tasks show commands as instructions only;
browser tasks stay in-app; native tasks may explicitly hand off to TU10 if supported, otherwise
retain the side panel. Capture uses the existing consented capture path only. Missing/version-thin
knowledge says it is uncertain; no guessed control coordinates or implicit capture. Mode,
account, project or task change cancels stale guides and overlay handoffs.

Guide permits read-only context inspection and never dispatches a mutation. Build keeps guide/do
wire compatibility and existing confirmation admission. The S4 hole fixture uses the gated
onshape.add_feature path and proves actual diff → explicit decision → write. It does not claim
that separately authorized SOLUSDEV-261 routine-policy actions have been revoked. Attachment
shortcut semantics prevail: Ctrl+Space toggles mode; existing summon shortcut stays unchanged.

Native Guide target discovery is main-process read-only and sender-authenticated. On X11 it
uses pinned xprop/xwininfo argument arrays with time/output bounds, an exact normalized
WM_CLASS allowlist, exactly one matching window, and positive bounded on-display geometry.
Scope generations invalidate late lookups across account/project changes. Missing tools,
unsupported platforms or ambiguous windows fall back to the side panel. Renderer text cannot
select arbitrary processes, commands or target geometry; discovery does not capture pixels.
