# Completion note — SOLUSDEV-319 follow-up, ADR-041 drive slice 1

Branch `SOLUSDEV-319-kicad-embedded-symbol-compare` (kept there at the human's request). Commits:
9e008cda (architecture), c4ca6e8e, f95c3b1a, cff0a27e, d506276d (helper), f5d052ce, 5c92c11a, 501d107c
(companion), plus this handoff. Nothing pushed.

## Built

- `docs/architecture/sol-drive.md` — the three-part design (local helper, companion `drive` builtin,
  API `drive.step` loop), slices, and the slice-2 bridge note.
- `apps/desktop/native/solus-input/` — Swift helper: `identify`, `capture` (ScreenCaptureKit, single
  window), `act` (click/move/drag/scroll/key/type/wait) with every ADR-041 §5 check in the pure
  `SolusInputCore` (34 XCTests).
- `packages/companion/src/solus_companion/drive/` — `DriveServer` builtin running the pinned helper
  (46 tests). **Not wired** into the companion's builtins and **no** `integrations/mcp/drive/allowlist.yaml`
  — the API auto-loads every allowlist and would expose `drive.act` to the agent (slice 2 adds an
  internal-only exposure first).

## Decisions taken in-chat

Anthropic computer-use model for the loop; the three-part architecture; stay on the 319 branch; this
slice first.

## Verification

- `swift test` 34/34; companion suite 419 passed (drive 46, warnings-as-errors clean); ruff, ruff
  format, mypy clean on the new Python.
- Live, non-invasive: `identify` against the real window server (non-drivable app → no identity/title),
  hit-test logic against real windows, refusals (`app_not_allowed`, `chord_denied` for `cmd+q`/`cmd+v`,
  `not_trusted`), companion → real helper end to end. **No input was posted to the machine**; capture of
  a KiCad window, posting, the kill switch and stuck-button release are on the hardware QA list
  (`docs/qa/COWORK_QA_SOLUSDEV-319-drive-slice1.md`).
- Phase 4: automated reviewer (3 + 1 findings, fixed), code review (APPROVE; 4 medium fixed), security
  review (FAIL → H2 and all mediums fixed in code; H1 is architectural, below).

## Open — needs a human

1. **Security H1 (architectural):** the OS grants would belong to Solus.app (responsible process), so
   every child of the app could bypass the helper. Resolution designed in sol-drive.md §1/§5: ship the
   helper as its own signed `LSUIElement` app holding the grants, launched with responsibility
   disclaimed, verifying its caller's signature. Proposed ADR-041 amendment text is in the chat for
   approval (tier-2). Signing identities / notarisation are human.
2. Hook H9 noise (`--silent`) and its false "no test file" flag — unchanged, flagged before.
