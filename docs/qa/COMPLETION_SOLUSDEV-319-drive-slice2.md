# Completion note — SOLUSDEV-319 follow-up, ADR-041 drive slice 2 (API side)

Branch `SOLUSDEV-319-kicad-embedded-symbol-compare` (kept there at the human's request). Nothing pushed.

Commits:

- 539e2621: ADR-041 amendment, helper alone holds grants
- 3e14754b: ADR-041 amendment, 120 s wall-clock and toolset mapping
- 0c3c7d4f: `exposure: internal`
- 3fb42847: companion wiring, fetch-once, draft allowlist
- 73c697e0: action mapping
- 07a3b664: gateway computer-use round
- 01120cfd: `drive.step` and the loop
- 20902f71: red-team
- 4953d3bf: docs
- 203b21a9, 2c5be872: review fixes
- plus this handoff

## Built

- **`exposure: internal`.** A new allowlist field (`bridge/allowlist.py`) lets a server's tools be accepted from the companion but registered in no agent tool set (`agent/runtime._internal_only`, which also absorbs the old isaac and `read_code_file` skips).
- **Companion.** `drive` is now a built-in beside `machine`, driven by the environment. Drive captures are staged fetch-once with a 60 s expiry.
- **Draft allowlist.** `integrations/mcp/drive/allowlist.yaml` is a DRAFT with `exposure: internal`, plus a README.
- **The drive package** (`agent/drive/`):
  - `actions.py`: computer toolset to vocabulary mapping; out-of-vocabulary members disabled; never raises.
  - `port.py`: untrusted helper replies, normalised codes, 30 s per call.
  - `executor.py`: bind, loop, budgets and time cuts.
  - `tool.py`: `drive.step` — its card, the visible-only intent (NFC, no hidden/combining characters), events, progress, the lease and cancellation handling.
  - `wiring.py`: binds everything to the requesting user's own session.
- **Model path.** `orchestration/gateway.computer_use` calls `providers.AnthropicAdapter.computer_use`:
  - Opus 5.5, effort high, `computer_toolset_20260801`, one action per call;
  - the assistant content is replayed verbatim; prompt caching is on;
  - the frequency cap, spend gate, retry with circuit breaker, and debit all apply.
  - The new catalog role is `computer_use` (`models.yaml`).
- **Settings.** `drive_max_actions` (15), `drive_max_seconds` (120) and `drive_max_input_tokens` (400k).
- **Docs.** `docs/architecture/sol-drive.md` §3–4 rewritten as built; `docs/contracts/bridge-protocol.md` has the internal-exposure note.

## Decisions taken in-chat

- Budget T is wall-clock time, 120 s, including model time. This is an ADR-041 amendment.
- The loop runs on Claude Opus 5.5.
- Progress reuses the command-output channel instead of new stream events.

## Decisions under delegated judgment

- **Bind at execution, not at card time.** While the card waits, the pill is in front, not KiCad. The step waits up to 5 s for KiCad.
- **The card is built from the arguments only, so it is deterministic.** Anything the card would display differently is refused rather than run: redacted text, invisible characters, double spaces, `<` or `>`.
- **A fresh capture rides each action's result** (one round per action).
- **Unsupported proposals cost an action.**
- **Server-side refusal fallbacks are not enabled.** A refusal ends the step ("SOL declined"), which is the safe result for a pointer loop. A fallback model may not support the toolset.

## Verification

- API drive tests: 169 passed, in seven files:
  - `test_drive_actions.py`
  - `test_drive_model.py`
  - `test_drive_executor.py`
  - `test_drive_port.py`
  - `test_drive_step_tool.py`
  - `test_drive_redteam.py`
  - `test_drive_isolation.py`
- Bridge exposure tests pass.
- Affected suites: 1155 passed (runtime, registry, confirmations, SOL, bridge, config, providers, gateway, MCP hygiene).
- Companion suite: 425 passed.
- ruff, ruff format and mypy are clean on every touched file.
- Full API suite: one failure, `tests/corpus/test_corpus_router.py::test_a_second_team_reads_the_same_corpus`. It passes alone; this is the known shared-test-DB interference from concurrent agent runs, and the test is unrelated to this diff.
- Not run live: no real model call and no real drive step. That is the hardware/Cowork pass, `docs/qa/COWORK_QA_SOLUSDEV-319-drive-slice2.md`.
- Phase 4:
  - The code review gave WARN: three mediums and six lows. All are fixed, except L5 (flooring when converting pixels to points), which is documented.
  - The security review gave FAIL on two highs, H1 (invisible-Unicode intent) and H2 (missing isolation tests). Both are fixed, as are M1, M4, M5 and L1–L5.
  - The security re-review found a new CRITICAL introduced by the caching fix: cache reads and writes were not counted, so cached input went unbilled and escaped the token cap. Fixed in 2c5be872: cache reads and writes now count in `tokens_in`, with writes at 1.25×. The lease is now keyed on the user alone.
  - An automated review flagged Hangul filler characters passing `isprintable()`. Fixed: intents must now be NFC, with no hidden or combining characters.
  - Writes are billed at 1.25× through the token count, because the catalog has no cache-write price. A dedicated `price_cache_write` is a billing (ADR-024) follow-up.

## Open — needs a human

1. **Ratify `integrations/mcp/drive/allowlist.yaml`** (integrations/mcp/CLAUDE.md rule 2). Until it is merged, nothing loads it.
2. ~~Project binding (security M2)~~ and 3. ~~In-window Save, Plot and Export clicks (security M3)~~ are
   **settled**; see "Follow-up: M2/M3" below. Still open from that work: the nested-folder rule (slice 3)
   and the hardware checks (QA flows 17–23).
3. **Frequency cap (code review M3).** The drive loop shares the per-user cap (20 calls/min) with SOL chat. A fresh capture per action brings a full step to about 16 rounds, but a fast step plus chat can still hit `rate_limited`. Options: a separate cap for the `computer_use` role, or accept it.
4. **Data-event contract (security L6).** The `drive.*` event types should be added to the event schema in `packages/contracts/` (tier-2).
5. **Multi-instance lease.** `drive_lease` is process-local, like the in-memory bridge registry. It needs a Redis `SET NX` lease before the API scales out.
6. **Long request (security L7).** A step runs inside the decide HTTP request for up to about 3 minutes, holding a DB session. This is the same model as 317's `code.exec`. Moving it to a job is a design change.
7. **Per-team disable flag (ADR-041 consequence).** It doesn't exist yet. Slice 3 adds the setting.
8. **Hooks.**
   - The H9 hook ran an unrelated vendored test, `integrations/mcp/altium/upstream/tests/design/test_executor.py`, for `executor.py` edits because the file names match.
   - The H8 hook's shared `dmypy` daemon crashed with INTERNAL ERRORs inside the anthropic and cryptography packages. Plain mypy was clean. I restarted the daemon once.
   - Both are flagged; I did not edit any hook.

## Follow-up: M2/M3 settled (2026-10-26)

Decisions, in-chat: bind each step to the linked workspace through the helper's cwd check, and accept an
in-window Save as an in-step effect that ends the step. ADR-041 amendment fd97630f, approved against its
concrete text.

Probe on this Mac (KiCad 10.0): neither window exposes an `AXDocument` value; the title has no path
("solus_sample — Schematic Editor"); the process cwd (`proc_pidinfo`, no grant needed) is the project
folder; the Schematic Editor's toolbars are not exposed to Accessibility at all. That last point rules out
an AX denylist for the Save button.

Commits:

- fd97630f: ADR-041 amendment
- f74c849f, 3725db3d: `solus-input --within`, plus a re-check before every posted event
- cec5541f, 9c33a1d2: companion workspace binding and the saved-design check
- 6192a3d8: API `outside_workspace`, the `saved` outcome, sentences
- bc2edde1: review fixes

Built:

- **Helper.** Every command takes `--within WS`, which is required, must be absolute and resolved, and
  cannot be `/`.
  - identify hides a KiCad working elsewhere (`outsideWorkspace: true`, app and window null).
  - capture and act refuse `outside_workspace`.
  - Paths are compared as bytes.
- **Companion.**
  - **Workspace.** No linked workspace means drive is not advertised. The workspace goes first in
    every helper call.
  - **Saved-design baseline.** It is taken at identify and cleared at the start of every identify.
    It covers design suffixes only, symlinks are followed, and `.history/` and `_autosave-` are skipped.
    It fails closed past 10,000 entries.
  - **Act.** An act refuses `not_bound` or `design_saved`, and a failed act that saved first reports
    `design_saved`.
  - **Acts and captures.** Both carry `designSaved`.
- **API.**
  - The new codes are known.
  - A step binding a KiCad from another project ends as `refused/outside_workspace` before any capture.
  - Any `designSaved` ends the step as `saved`.
  - Before reporting `done`, the step takes one last capture when any action ran.

Verification:

- Swift: 44 XCTest.
- Companion: 440 passed.
- API drive and exposure suites: 194 passed.
- ruff, ruff format and mypy are clean.
- Not run live: the drive flows themselves. Hardware QA flows 17–23 are in
  `COWORK_QA_SOLUSDEV-319-drive-slice2.md`.

Phase 4:

- **Code review: APPROVE.**
  - Fixed:
    - a save made by a failed act was lost;
    - a late write wasn't caught by the capture or the final check;
    - the mid-step "nothing done" sentence;
    - a stale baseline;
    - a dead branch.
  - Left as is:
    - a refused act still counts toward "N actions", the same as every other refusal;
    - `saved` surfaces as a `ToolException`, like every other unfinished outcome.
- **Security review: PASS.**
  - Fixed: M2 (the late save) and L2 (NFC/NFD).
  - L3: the save check now skips only `.git`, `node_modules`, `.history` and `solus-artifacts`.
  - L1: the same-process residual is documented, including the window-title leak.
  - M1 (nested linked folders) is deferred to slice 3, where the desktop first sets
    `SOLUS_COMPANION_DRIVE`. The rule is written in sol-drive.md §5. Today driving is only enabled by
    hand through the environment.
- **Automated hook review.**
  - Its proposal to bind to `AXDocument` doesn't work: KiCad exposes no `AXDocument` value.
  - A cwd re-check before every event was added.
  - The fail-open scan and the over-broad dot-dir skip are fixed.
