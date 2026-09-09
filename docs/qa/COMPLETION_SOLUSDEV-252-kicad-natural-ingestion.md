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
| Phase 4 hardening (backend)              | control characters, BOM round-trip, quoted-head pruning, node-cap memory ceiling, dense-8-MiB acceptance, message/byte budgets, bounded labels, lazy findings, separate-then-combined cursor, shared builders |
| Phase 4 hardening (API boundary)         | `test_sources.py` — neither bulk key echoed on list/detail/PATCH, cross-team 404s, over-cap `board` refused at POST and PATCH, at-cap accepted |
| Phase 4 hardening (desktop)              | failed read settles retryably, cancelled-during-failed-read stays quiet, no-project honesty, count cap refuses before any read, head-atom boundary parity |

Subset runs during the build: parsers 111 passed, connector 119 passed. After the Phase 4
fixes: backend unit subset 189 passed, connector/sources/integration subset 86 passed, desktop
255 passed on the touched files.

## Verification

| Gate                                    | Result                                                                 |
| --------------------------------------- | ---------------------------------------------------------------------- |
| ruff (all 20 changed `.py`)             | clean                                                                  |
| ruff format                             | clean (588 files)                                                      |
| mypy (`uv run mypy packages/api/src`)   | clean — 279 source files                                               |
| Full backend suite (private DB)         | 6418 passed, 8 skipped, 1 xfailed                                      |
| eslint (changed `.ts`/`.tsx`)           | 0 errors, 8 `max-lines-per-function` warnings (test blocks; `useConnectWizard` was already over on `main`) |
| tsc `--noEmit` (`apps/desktop`)         | clean                                                                  |
| vitest (full desktop suite)             | 3369 passed across 306 files                                           |

The pre-existing cryptography/openai `INTERNAL ERROR` lines mypy prints are unrelated to this
diff and reproduce on `main`.

## Phase 4 review and the fixes it forced

Four review passes ran on the integrated diff. The security pass returned **FAIL** with three
HIGH and six MEDIUM findings, every one verified by executing the built package against
adversarial input. Per CLAUDE.md §5, all of them were fixed before handoff — nothing was
noted and skipped. Commits `83f6cb9` (desktop) and `21ca29f` (backend).

| ID  | Severity | Finding                                                                                          | Fix                                                                                                              |
| --- | -------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| S1  | HIGH     | `board` missing from `_BULK_CONFIG_KEYS`, so up to 8 MiB of board content echoed by every `/sources` read | `board` added; a KiCad source's config now echoes neither input (`test_sources.py`)                              |
| S2  | HIGH     | Mismatch messages interpolated unbounded ingested strings — measured 13.36 MiB persisted, longest message 140,065 chars | values clipped to `VALUE_LIMIT` (96) before interpolation; `ErrorRecorder` gained `MESSAGE_LIMIT` (512) and a 64 KiB aggregate budget |
| S3  | HIGH     | `prune` consulted only for bare-atom heads while `children()` matches quoted heads → `("components" …)` bypassed pruning; 8 MiB → ~102 MB peak | `prune` sees any string head; unread heads pruned at any depth; node cap 2M → 1M, calibrated by measurement      |
| S4  | MEDIUM   | NUL/C0 control characters accepted, then rejected by Postgres — opaque sync failure that logged bound parameters (design content) | refused up front with the offset; `\t`, `\n`, `\r` stay legal                                                     |
| S5  | MEDIUM   | 8 MiB bound enforced only at sync time, so a 200 MB `board` was stored first                     | `SourceCreate`/`SourceUpdate` bound the bulk keys → 422 at the boundary; desktop caps the pick count before reading |
| S6  | MEDIUM   | Sniffer ignored a BOM, reader did not — a valid BOM-prefixed export was refused with a wrong reason | `read_sexpr_root` strips the BOM the sniffer already ignored (also raised by the code review as its only HIGH)    |
| S7  | MEDIUM   | Unbounded `SyncError.item` in `build_graph`'s net-node path (60,006-char item measured)          | wrapped in `label`                                                                                               |
| S8  | MEDIUM   | All findings materialized before the 200 cap applied                                             | findings are lazy descriptors; only kept ones render, the overflow is counted                                     |
| T1  | HIGH     | A rejected `file.text()` escaped `pickFiles` as an unhandled rejection and left the tile stuck   | read wrapped; friendly copy; attempt settles retryably                                                            |
| T2  | MEDIUM   | `projectId!` rested on a `scope` invariant living in a sibling file                              | explicit local check                                                                                             |
| S9  | LOW      | `\x1e` cursor separator claimed an invariant that does not hold                                  | each side hashed separately, then combined                                                                       |
| L2  | LOW      | Desktop sniffer used `startsWith` where the API matches the head atom on a boundary              | renderer mirrors the API rule                                                                                    |
| C1  | LOW      | `KicadConnector.parse()` unreachable from `sync()`                                               | documented as the abstract-contract/conformance entry point                                                       |
| P1  | MEDIUM   | ~50 duplicated lines between the XML and S-expression component/net loops                        | shared `build_components`/`build_nets` over per-format records; each reader only walks its tree                    |
| P2  | LOW      | Two guards not marked `Final`                                                                    | marked, with a note that tests monkeypatch them                                                                   |

**One correction to the S3 write-up.** The finding described the quoted-head gap as letting
content "bypass pruning yet still parse as real data", which reads like smuggling. Verified
after the fix: a quoted section head parses *identically* to the bare form
(`("components" …)` == `(components …)`), so quoting never granted an attacker a landing place
the plain syntax did not already offer. The real and only impact was MEMORY — a quoted
`("design" …)` at a prunable position was materialized instead of skipped. That is what the fix
closes, by making `prune` and `children()` agree on what a head is: a ~2 MB block at a prunable
position now costs 0.0 MB peak whether its head is quoted or bare.

**Node-cap calibration (S3), measured 2026-09-09.** The cap has to sit between two hard
numbers, so both were measured rather than guessed:

| Input                                                     | Nodes    | Peak     |
| --------------------------------------------------------- | -------- | -------- |
| Committed 21.7 KB fixture netlist                         | 1,244    | —        |
| Dense legitimate 8 MiB netlist (real `kicad-cli` density)  | 676,956  | 32.8 MB  |
| Adversarial 8 MiB of 2-char atoms at a legal position      | guard trips | 49.1 MB |

`MAX_SEXPR_NODES = 1_000_000` therefore parses the densest legitimate file with ~1.5×
headroom while capping one parse near 49 MB, so the worker's worst case
(`max_jobs = 4` × 2 parses) is a few hundred MB instead of the ~800 MB the old 2M cap allowed.

One deliberate deviation: the desktop task did not add a summed-`file.size` check on top of the
per-file cap and the count cap, because with count ≤ max and every file ≤ 8 MiB the sum can
never exceed the product — the branch would be unreachable code. The memory bound the finding
asked for still holds (≤ 16 MB read for KiCad, ≤ 8 MB elsewhere).

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
6. **Mismatch cap layering**: the reconciler caps at 200 findings, `build_graph` at 100
   `SyncError`s, and `ErrorRecorder` now also at 64 KiB total — whichever binds first wins.
   The outer caps are defense in depth, deliberately kept.
7. **A subagent died on the account's monthly spend limit** part-way through the backend fix
   pass, after it had written the failing tests but before any source change. The
   orchestrator finished those fixes directly. Nothing was left half-applied, but it is worth
   knowing that the review-fix phase of this ticket was the expensive part.
8. **Mismatch reporting order under the cap.** Findings are emitted refdes-first, then field
   differences, then connectivity. Pairing a netlist with an unrelated board therefore fills
   the 200-finding budget with "placed on board but not in netlist" and crowds out the value
   and pin findings. That ordering puts the loudest signal first, which is the right default,
   but if a balanced sample is ever wanted, interleaving the three generators in `_bounded` is
   a contained follow-up.
9. **Two residual, harmless sniffer divergences** between the renderer and the API: the
   renderer requires the quoted `"kicad_pro"`/`"meta"` keys where the API looks for the bare
   words, so `{"metadata": …}` is a project file to the API and `unknown` to the wizard. The
   wizard is the stricter of the two, so the user always gets the API's answer or a refusal —
   never a silent wrong route.

## Final verification

- **Full backend suite, pre-fix (private DB):** 6396 passed, 8 skipped, 1 xfailed (25m 44s).
- **Full backend suite, post-fix (private DB):** 6418 passed, 8 skipped, 1 xfailed (20m 45s).
  The first post-fix run had ONE failure — `test_context.py::test_no_production_code_uses_bare_render`,
  a repo-wide text guard that forbids prompt assembly's method name anywhere in production
  code. The S8 fix had introduced a method with that name in the reconciler. Fixed by renaming
  the method (`a223b07`); the guard was left strict and untouched.
- **Full desktop suite:** 306 files, 3369 tests, all passing.
- **Phase 4 reviews:** code review WARNING → its one HIGH (BOM) fixed; python review APPROVE
  with one MEDIUM (duplication) → fixed; typescript review WARNING → both findings fixed;
  security review FAIL (3 HIGH, 6 MEDIUM) → all fixed, with tests naming each finding.
- **Handoff state:** feature branch `SOLUSDEV-252-kicad-natural-ingestion`, 8 local commits,
  clean working tree, nothing pushed, no MR opened. The push, the MR and the merge are human
  actions (ADR-021).
- **Ownership manifests** under `.claude/state/ownership/` for this ticket were removed after
  the work merged into the feature branch.
