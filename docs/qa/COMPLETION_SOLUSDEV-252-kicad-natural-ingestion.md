# Completion report — SOLUSDEV-252: KiCad natural ingestion

**Branch:** `SOLUSDEV-252-kicad-natural-ingestion` (from `main` @ `3a90ab6`). Six local
commits, nothing pushed, no MR opened (humans do both).
**Handoff QA:** [`COWORK_QA_kicad-natural-ingestion.md`](COWORK_QA_kicad-natural-ingestion.md).
**Date:** 2026-09-08.

## What was asked

A user exporting a netlist from KiCad the natural way (Export Netlist dialog, or `kicad-cli sch
export netlist` with no `--format`) got: _"kicad: the S-expression netlist is not supported in
v1; re-export as XML with `kicad-cli sch export netlist --format kicadxml`"_. The ask: make
ingestion natural — accept what KiCad emits by default, and let users drop schematics or PCB
designs in.

## Design review outcome (Phase 1, answered in-chat 2026-09-08)

| Question                             | Decision                                                                                    |
| ------------------------------------ | ------------------------------------------------------------------------------------------- |
| Scope                                | **Both**: S-expression netlist AND `.kicad_pcb` board file, one ticket                      |
| Raw `.kicad_sch` without a companion | **Reject with guidance** (never components-only ingestion; nets are what the checkers need) |
| Contract amendment (tier-2)          | **Approved as written** — four amendments to `docs/contracts/metadata-extraction.md`        |
| Board vs netlist disagreement        | **One KiCad source, both files; netlist authoritative; mismatches surfaced as SyncErrors**  |
| Ticket                               | **Reuse SOLUSDEV-252** (human instruction, "for today")                                     |

Root cause confirmed against KiCad 10.0.1: `kicad-cli sch export netlist --format` defaults to
`kicadsexpr`. The S-expression export carries the same schema as the XML one (verified by
exporting the committed fixture schematic), so parity is an invariant, not a best effort.

## What was built

1. **Contract** (`541fd4d`): §2 KiCad row, §5.2 obtain/format wording + the schematic refusal
   rule, new §5.2a board-file row with the reconciliation law, §6.3 owned reader replaces the
   `kinparse` suggestion.
2. **Parsers** (`68f0f8a`, `packages/api/src/solus_api/connectors/`):
   - `kicad_sexpr.py` — owned, stdlib-only, iterative S-expression reader; `MAX_SEXPR_DEPTH=64`,
     `MAX_SEXPR_NODES=2_000_000`; `prune(head, depth)` skips sublists by paren-balanced scan
     without allocating. Timing probe: 7.5 MiB dense netlist ≈ 1.3 s, 9.4 MiB board ≈ 1.0 s.
   - `kicad_formats.py` — `detect_kicad_format` (content, never extension) and
     `refuse_unsupported` (the five guidance messages).
   - `kicad_netlist.py` — now the dispatcher; `kicad_netlist_sexpr.py` mirrors the XML mapping
     line-for-line; `kicad_pcb.py` implements §5.2a (KiCad 8+ `property` and ≤7 `fp_text`).
3. **Connector** (`68a87d5`): `KicadConnector` reads `config.export` (netlist, either format,
   live acquirer first) and/or `config.board`; `kicad_reconcile.py` applies §5.2a (netlist
   authoritative, board adds `layer`, mismatches → `SyncError`s labeled by refdes, capped at
   200); `config_fields = ("export", "board")`; cursor hash covers both inputs. `eda.py` split
   minimally (`_select_export` / `_inline_text`), Altium unchanged.
4. **Desktop** (`4754e9b`, `apps/desktop/.../onboarding/`): `kicadFiles.ts` (classify +
   assemble), multi-select picker for KiCad only (`.xml,.net,.kicad_pcb`), content-sniffed
   routing to `export`/`board`, instant guidance for `.kicad_sch`/`.kicad_pro` BEFORE any
   source is created, tile copy and wireflow row updated.
5. **Docs** (`b824781`): `kicad-parsing` skill (both formats, board, reconciliation, the
   KiCad-10 net-name quirk), Cowork QA plan, stale XML-only wording in two older QA files.

## Governing docs consulted

DECISIONS.md (ADR-021, ADR-030, ADR-031, ADR-032); `docs/contracts/metadata-extraction.md`
§2/§2.1/§3/§5.2/§5.3/§6.3; `docs/api/API.md` (sources routes — no route change needed;
`config` is a free dict validated by the connector); `docs/wireflows/sources-connect-wizard.md`
(file-pick step only; row updated); `apps/desktop/CLAUDE.md`; `.claude/skills/kicad-parsing`.

## Test coverage summary

| Area                                     | Tests                                                                                                          |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| S-expression reader                      | `test_kicad_sexpr.py` — escapes, prune, limits, malformed                                                      |
| Format detection + refusal messages      | `test_kicad_formats.py`                                                                                        |
| S-expr netlist parity (synthetic + REAL) | `test_kicad_netlist_sexpr.py` — `parse(XML) == parse(S-expr)`; real kicad-cli 10 export vs committed 9.0.4 XML |
| Board parser                             | `test_kicad_pcb.py` — §5.2a mapping, ≤7/8+ syntaxes, pruned noise, smuggling, refusals                         |
| Dispatcher + refusals                    | `test_kicad_netlist.py`                                                                                        |
| Reconciliation                           | `test_kicad_reconcile.py` (31) — every §5.2a rule, `/` normalization, 200 cap, immutability                    |
| Connector                                | `test_kicad_connector.py` (17), `test_kicad_acquisition_fallback.py`, `test_eda.py`, `test_registry.py`        |
| HTTP end-to-end                          | `test_kicad_ingest_e2e.py` — cross-format invariant through the real route; board-only                         |
| Desktop                                  | 5 onboarding test files (94 tests) + 2 call-site tests; vitest related run: 308 passed                         |

Parser subset: 111 passed. Connector subset: 119 passed. Full API suite and Phase 4 review
results: see "Verification" below.

## Verification

- ruff: clean on all 20 changed `.py` files. mypy: clean (`uv run mypy packages/api/src`
  — "no issues found"; the pre-existing cryptography/openai INTERNAL ERROR noise is unrelated).
- eslint: 0 errors, 8 `max-lines-per-function` warnings (test `describe` blocks and
  `useConnectWizard`, which was already over the limit on `main`). tsc `--noEmit` for
  `apps/desktop`: clean. vitest related: 308 passed.
- Full `uv run pytest -q`: _filled in at handoff — see the final section._
- Phase 4 subagent passes (code-reviewer, security-reviewer, python-reviewer,
  typescript-reviewer): _filled in at handoff — see the final section._

## Decisions made under delegated judgment

- **Owned S-expression reader instead of `kinparse`** — no new dependency on untrusted input;
  bounded depth/node count; contract §6.3 amended accordingly (approved).
- **`prune` also skips each netlist component's `(units …)` sublist** — never read, bulk of a
  large netlist's nodes.
- **Board parser emits only nets with ≥1 pad node**; pad-only net names come after
  header-ordered nets; `layer`/`description` only when present; `~` footprint falls back to the
  lib id.
- **Reconciler adds the board `layer` to netlist components** (corroborating metadata,
  identity untouched); board-only refdes are reported, not added, when a netlist is present.
- **SyncError item relabeling**: `build_graph` files all parser warnings under item `"parse"`;
  the connector relabels reconciliation mismatches to the refdes/pin/net subject so "why is R1
  flagged?" is answerable from the sync record.
- **Cursor**: kept the `content_sha` key; value is now `sha(netlist + "\x1e" + board)`.
  **Side effect:** existing netlist-only KiCad sources see exactly one spurious
  `detect_changes == True` after deploy (one extra full sync).
- **KiCad-10 net-name prefix**: local-label nets are `/SDA` in 10.x vs `SDA` in 9.x. Graph
  keeps names verbatim (never renamed); the reconciler and the cross-format tests normalize
  ONE leading `/` for comparison only.
- **Desktop**: provider-specific copy/accept/multiple live in `kicadFiles.ts`; assembly errors
  settle the attempt so closing the wizard keeps a retryable error state; `EdaExportFile` moved
  to the leaf module and re-exported.
- **`project_path` not added to KiCad `config_fields`** — a pre-existing, separately-tracked
  gap (`mcp_acquire.py`, `test_registry.py` comment); out of scope here.

## Deviations and open concerns (read these)

1. **Two branches under one ticket.** `SOLUSDEV-252-sim-sources` (INTEGRATIONS I5, unmerged)
   already exists; per the human's instruction this work reused SOLUSDEV-252 on a second branch
   from `main`. Branch discipline (one ticket = one branch, ADR-021) is violated knowingly.
   Recommendation: file a dedicated ticket and rename the branch/MR before merge, or accept
   the exception explicitly in the MR description.
2. **Root CLAUDE.md map is stale**: it lists `packages/api/CLAUDE.md`, which does not exist.
   Tier-2 file — not edited; flagging for a human.
3. **Raw `.kicad_sch` remains refused by design.** The zero-export experience (link the project
   folder → companion runs `kicad-cli` locally → netlist acquired over the bridge) is the
   natural next ticket: the fork's `export_netlist` tool and the local-folder KiCad project
   detection both exist and are not yet wired together.
4. **Board files are inline-only** (no live acquisition tool); 8 MiB cap applies per file.
5. **Hook observations (not bypassed):** H9's "new source file with no test" check uses
   `git ls-files`, so freshly written (untracked) test files are invisible to it — false
   positives during TDD; H9's pytest runs use the shared default test DB and collided once
   with a subagent run (a transient `0 == 1001` on the large-fixture e2e test that passes on a
   private DB). Consider a per-invocation `SOLUS_TEST_DATABASE_URL` in the hook.
6. **Mismatch cap layering**: the reconciler caps at 200 warnings, `build_graph` at 100
   `SyncError`s — the second cap wins today; the first is defense in depth if the recorder
   cap ever rises.

## Final verification (filled at handoff)

_See the end of this file after the full-suite and review passes complete._
