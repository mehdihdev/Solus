# Completion report — SOLUSDEV-251 · INTEGRATIONS I4 — SOL working inside the tools

Branch `SOLUSDEV-251-sol-in-tools`, **stacked on `SOLUSDEV-249-local-folders`** (merge I2 first:
I4 needs I2's bridge hello cap — with a linked workspace the Altium + KiCad inventories overflow
the old 16 KiB control cap and no companion could connect at all). Not pushed; no MR opened.

## What was built

- **KiCad write preview over the bridge** (`bridge/previews.py`, injected by
  `runtime._register_bridge_tools` through `_bridge_reader`): a companion write tool had no
  `preview`, so its approval card showed argument rows. `kicad.set_symbol_property` now reads the
  schematic's netlist through the same live session first and renders
  `R1 · Value: <current> → <new>` (`before: None` when the read declines — never a guess). The
  gate's re-run-at-approve divergence check applies unchanged.
- **Tool knowledge in the loop** (`agent/tools/knowledge.py`; ADR-033): the vendor-documented
  UI control each write tool acts on is data (`TOOL_CONTROLS`); a PUBLISHED entry reaches the
  model as one nonce-fenced `tool_knowledge` block on that tool's description (SOL route), and
  the outcome of every confirmed write becomes a confirm/reject vote on that control through the
  only tool-knowledge write path (`confirmations.decide_confirmation` → `toolkb.feedback`).
  Per-tool success semantics: a KiCad write that answers `changed: false` with a reason is a
  rejection even though the result is `ok`.
- **Seed**: `scripts/seed-toolkb-mcp-controls.py` admits the three controls (KiCad Symbol
  Properties; Onshape Variable Table — "writing replaces the table, send everything back";
  Onshape Feature list) through the guard's docs path; catalogs list the ids.
- **Onshape**: the operations layer already had reads, `get_mass_properties`, and gated writes
  with real previews and the whole-table read-merge-write for `set_variable` (verified by
  reading `onshape_ops.py:520`). No code change; `tests/test_live_onshape_write.py` is the
  env-gated round-trip through that layer.
- **Fusion**: no tools, by design — the allowlist stays `tools: []` until a live `tools/list`
  capture. `scripts/capture-fusion-tools.py` runs and fails honestly here.

## Governing docs

`docs/contracts/action-gate.md`, `docs/contracts/agent-tool.md`, `docs/contracts/bridge-protocol.md`,
`docs/contracts/tool-knowledge.md`, `docs/api/toolkb.md` (+ SOLUSDEV-251 amendment),
`docs/architecture/sol-in-tools.md` (new), DECISIONS.md ADR-010/031/033/035.
`docs/design/SPEC.md` is a copy of the CI file and `docs/design/screens/` does not exist — noted.

## Verified live, per tool (this Mac, real API :8001 + real Electron + real companion + forks)

- **KiCad — verified end to end.** READ: `extract_project_netlist` (SOL's own read-back turn and
  the live test). OPERATION: `analyze_schematic_connections` on the same project. WRITE: a real
  SOL turn in Do mode parked `kicad.set_symbol_property` with the live diff
  `R1 · Value: 4.7k → 4k7` (before read through the bridge); approve → the fork answered
  `changed: true, old_value 4.7k, new_value 4k7`; the schematic on disk carries `4k7`; a second SOL
  turn read it back and answered `4k7`. The `kicad.eeschema.edit_symbol_properties` entry received
  the confirm vote. `tests/test_live_kicad_write.py` (`-m live`) drives read → analyse → write →
  read-back through the fork's launcher and asserts the file changed in exactly one property.
- **Onshape — NOT run live in this session.** Mehdi chose to sign in via the desktop; at commit
  time no Onshape account had been connected on this Mac (the Home card still read "Onshape ·
  Not connected"), so the write round-trip was not exercised against a document. What IS
  verified: the operations layer's reads, `get_mass_properties`, the gated writes with real
  previews and the whole-table read-merge-write (`onshape_ops.py:520`), by reading and by the
  existing unit suites; `tests/test_live_onshape_write.py` is ready to run the moment
  `SOLUS_LIVE_ONSHAPE_TOKEN/_DOCUMENT/_ELEMENT` are set, and the scratchpad SOL script
  (list → variables → mass properties → `set_variable` via the approval card → read-back) runs
  the same through real SOL turns once an account is connected. Reported as unverified live,
  not as done.
- **Fusion — deferred honestly.** No Autodesk Fusion on this Mac (only VMware Fusion); the
  capture script answers "could not reach the Fusion MCP server at http://127.0.0.1:27182/mcp".
  Procedure for a machine with Fusion: enable Preferences › General › API › Fusion MCP Server,
  run `uv run python scripts/capture-fusion-tools.py`, classify every advertised tool into
  `integrations/mcp/fusion/allowlist.yaml` (human-ratified, `requires_confirmation` Solus-authored
  per tool), then a read/operate/write round-trip like KiCad's. Nothing invented.

## Found in the live run

- The I2 live edit had appended a junction form AFTER the schematic's root form; the fork's
  splice refused (`reference_not_found`, its honest bucket for an unparseable file) while the
  upstream regex netlist parser still read the file. Correct behaviour; the file was restored.
- That refusal exposed a bug in the first cut of outcome feedback (an `ok` result with
  `changed: false` counted as a confirm) — fixed with `write_succeeded` and a test.
- `SOLUS_TOOLKB_VOTE_SALT` unset makes the same voter count twice across an API restart (the
  documented warning) — report it as a value to set.

## Phase 4 review findings (all fixed before handoff)

Code review (1 HIGH, 1 MEDIUM): the post-write vote block committed outside any guard → the
whole feedback step is now best-effort in its own helper (logs, rolls back, returns the result
that already landed), with a test that forces the failure. Security review (1 CRITICAL, 3 HIGH,
5 MEDIUM): notes were selected by recency → now only PUBLISHED, docs-path, vendor-docs entries
above a confidence floor (a sybil-confirmed community row can never ride the prompt; candidates
are never read; a version range that excludes the connected version yields nothing); a transport
failure cast a global REJECT → votes now abstain on unavailable/timeout/unauthorized and reject
only on a tool-reported refusal; the note sat inside the vendor description's fence → it now
rides its own `knowledge_note` descriptor field rendered as a separate fenced block
(`docs/contracts/agent-tool.md` amended); the preview read skipped the BYO license preflight and
accepted model-chosen escapes → the reader carries the server's preflight and `..`/absolute
paths are refused before any dispatch; vote events now carry team/project. Red-team fixture
added (`test_red_team_note_reaches_the_model_only_inside_a_fence`). Deferred with reason: a
per-turn cache for the four note queries (milliseconds today); the connected KiCad version is
not yet in the bridge hello, so notes are version-filtered only when a caller supplies one.

## Decisions under delegated judgment

- Notes attach where descriptors are handed to the model (the SOL route), not in the registry —
  the registry stays I/O-free and the never-raises invariant untouched.
- The preview read is bounded (8 s) and uses only the caller's own session; a decline shows
  `before: None`.
- Fusion and Onshape live legs report exactly what ran; no fixtures were invented.

## Tests

`tests/test_previews.py` (7 incl. registration + gate end to end), `tests/test_knowledge.py` (4),
`tests/test_confirmations.py` (+1 outcome feedback), `tests/test_live_kicad_write.py` (live, ran
green here), `tests/test_live_onshape_write.py` (live, env-gated). Full API suite
(`-m 'not live'`): 4499 passed, 1 skipped (18 min).

## Values a human must set

- `SOLUS_TOOLKB_VOTE_SALT` (any random string) so tool-knowledge votes de-duplicate across
  restarts. Run `uv run python scripts/seed-toolkb-mcp-controls.py` once per database.
- For the Onshape live test: `SOLUS_LIVE_ONSHAPE_TOKEN`, `_DOCUMENT`, `_ELEMENT`
  (optionally `_VARIABLE`).

## Humans must decide

- `integrations/mcp/fusion/allowlist.yaml` stays empty until a live capture is classified.
- The three seeded tool-knowledge entries are vendor-doc facts; curation sign-off per TU-06.
