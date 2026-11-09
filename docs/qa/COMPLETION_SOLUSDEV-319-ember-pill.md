# Completion report — SOLUSDEV-319: SOL Ember Pill

Branch `SOLUSDEV-319-kicad-embedded-symbol-compare` (kept on the ticket branch at the human's request;
other agents commit here too). Commits: b9278a1f, 95ca4057, 7be65eb6, 4094bf70, 42dbd037, 106f3fb9,
3150c10d, 875c1fee, plus this handoff commit. Nothing pushed.

## What was built

Design "SOL Quick Summon" variant A (canvas: https://claude.ai/artifact/7QPcuF5D8Qu7UKGXsRBGmh).

- **Main** — `main/sol-window/pillGeometry.ts` (pure placement: at the cursor, flip above, clamp; grow
  upward with the bottom fixed; shift aside rather than cover the summon point). `solWindow.ts`:
  frameless, transparent, always-on-top, skip-taskbar, all-workspaces window; `toggle` (double-tap Ctrl
  and the summon chord), hide on blur unless busy, re-summon re-places a hidden window. New invokes
  `sol:resize` / `sol:set-busy` / `sol:hide`, accepted only from the pill's own webContents top frame.
  The pin (`sol:set-always-on-top`, `SolState.alwaysOnTop`) and saved geometry were removed.
- **Renderer** — `Composer.tsx` (moved out of `SolChat.tsx`, one state + send path, `ColumnForm` /
  `PillForm` layouts), `SolChat` `pill` layout, `SolWindow.tsx` (height via ResizeObserver, Esc,
  busy), `PlanCard.tsx`.

## Governing docs

`docs/wireflows/sol-window.md` and `docs/architecture/sol-window.md` (both amended, tier-1, "SOLUSDEV-319
Ember Pill" sections); DECISIONS.md ADR-040 (read: it limits synthetic input, which is why pointer
control is out of scope); CLAUDE.md §7 (approval guarantee).

## Decisions taken in-chat (Phase 1)

- Scope: UI now; "SOL drives the app" (pointer control) is a separate ticket needing an ADR that
  supersedes ADR-040 §2 and its own architecture doc.
- Build mode is the one that acts; a plan is approved once; the pill grows upward; it opens at the
  pointer; it hides on blur but never while busy; extras live in the panel; stay on the 319 branch.

## Delegated-judgment decisions

- "One approve" is implemented as sequential per-confirmation decisions, never a batch endpoint, so
  every step keeps its staleness re-check (SOLUSDEV-168). Run arms only when SOL has finished answering
  and every step has been on screen (Phase 4 security H1).
- In the pill every non-command approval goes into the plan card (a single one is a one-step plan) so
  the card never swaps out mid-run; command cards keep their own card; the page keeps per-card UI.
- The routing indicator shows in the pill footer only while there is text to route. The panel has no
  header (New chat / history stay on the SOL page).
- Busy = streaming, the latest turn's parked approvals, or a running plan.

## Verification

- Desktop suite: 531 files / 5,629 tests green; `pnpm typecheck` clean; ESLint 0 errors (no warnings in
  touched files; `startSol` length warning predates this work).
- New/updated tests: `pillGeometry.test.ts`, `solWindow.test.ts`, `solBridge.test.ts`,
  `solSettings.test.ts`, `SolWindow.test.tsx`, `PlanCard.test.tsx` (16).
- Real app (Electron via CDP): pill summoned over other apps, frameless and transparent, existing
  conversation in the panel; hide → re-summon verified (visibility hidden → visible + focused).
  Blur-hide and the plan run were not exercised live (the plan needs real parked KiCad writes) — on
  the Cowork QA list.
- Phase 4: code review APPROVE (3 medium fixed); security review FAIL → fixed (H1 visibility gating,
  M1 verbatim values + tool name, L1 refused marking, L2 top-frame gate, L3 busy scope).

## Open concerns

- The plan card approves several steps with one click by design; the gating above is the mitigation.
  Worth a human look against CTR-03.
- Hook H9's `--silent` flag noise and its false "no test file" on `pillGeometry.ts` (the test exists)
  — flagged, not edited.
- Follow-up ticket: free-form pointer/keyboard control ("SOL drives the app").

QA: `docs/qa/COWORK_QA_SOLUSDEV-319-ember-pill.md`.
