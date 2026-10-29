# Cowork QA — SOLUSDEV-319 drive slice 3 (desktop setting, strip, outline, packaged helper)

Spec: `docs/architecture/sol-drive.md` §5 (and §2 caller check, §3 outline geometry). Decisions:
DECISIONS.md ADR-041 and its amendments (H1, M2/M3, and 2026-10-28 XPC, which superseded the
2026-10-27 caller check). Slice 3b has its own file: `COWORK_QA_SOLUSDEV-319-drive-slice3b.md`. Earlier
flows:
`COWORK_QA_SOLUSDEV-319-drive-slice2.md` (1–23) still apply; run them with the setting below instead of
environment variables.

## Setup

- [ ] macOS 14+, KiCad 10 installed, a Solus account signed in, the API running with the drive tool
      allowlisted (`integrations/mcp/drive/allowlist.yaml` ratified by a human).
- [ ] **Dev build:** `cd apps/desktop/native/solus-input && swift build` (debug — unsigned mode), then
      `pnpm dev:all`. The grants then belong to whatever launched the app (Terminal / the IDE).
- [ ] **Packaged build (flows 13–14):** see the slice 3b QA file. Flows 1–12 and 15–16 run on the dev
      build.
- [ ] Two Solus projects, A and B, each linked to a folder on this Mac (Project → Link folder). A copy of
      `solus_sample` inside A's folder for KiCad.

## Flows

1. **Default off.** Settings › SOL shows "SOL can use your mouse and keyboard", switch off. In the pill, ask
   SOL to add a resistor in KiCad. Expected: SOL does not offer a drive step (the companion advertises no
   drive tools).
2. **Turn on.** Flip the switch. Expected: the companion restarts once (bridge pill blinks offline/online);
   the row stays on after reopening Settings and after an app restart (`~/.solus/config.json` `sol.drive`).
3. **Permission rows.** With Accessibility or Screen Recording not granted to the helper, expected: the row
   shows "Permission needed"; Settings › Needs attention shows "SolusInput needs permission" naming the
   missing permission(s). Click "Ask macOS for permission". Expected: macOS shows its prompt(s) for the
   helper (packaged: SolusInput; dev: the launching app). Grant, return to Settings: the card clears.
4. **Development tag.** Dev build: a muted "Development build" tag on the row. Packaged: no tag.
5. **No folder.** Unlink project A's folder. Expected: switch disabled, "Link this project to a folder on
   this computer first." Relink: available again, and the companion restarts.
6. **Nested folders (security).** Link project B to a folder INSIDE A's folder. Expected for both A and B:
   switch disabled with the nested-folder sentence; the companion runs without drive (SOL offers no drive
   step even if the setting was on). Move B's link back out: available again for both, without restarting
   the app.
7. **Equal folders.** Link B to exactly A's folder. Expected: same as 6.
8. **Sibling names.** Link A to `…/board` and B to `…/board-v2`. Expected: both available (not nested).
9. **Strip.** Approve a drive step. Expected: under the card, `DRIVING KICAD · STARTING`, then
   `DRIVING KICAD · STEP k OF N` with a progress bar advancing per action; no typed text or coordinates
   shown. When the step ends the strip disappears.
10. **Outline.** During the step, a thin amber outline hugs the OUTSIDE of the KiCad window on all four
    sides, follows the window if it changes size between actions, never covers KiCad (SOL's clicks are not
    refused `occluded` because of it), and cannot be clicked (clicks pass through). It disappears when the
    step ends.
11. **Stop.** During a step click Stop. Expected: the strip reads `DRIVING KICAD · STOPPING…` (Stop
    disabled), the outline stays until the step ends at its next action as "paused — you took over", then
    both vanish. Repeat with Esc and with moving the mouse: same ending.
12. **Hotkeys quiet.** During a step, SOL's own typing never opens a second SOL pill or circle mode. After the
    step (≥ 0.5 s), double-tap Ctrl opens SOL as usual.
13. **Packaged fails closed.** Superseded — see the slice 3b QA file (flows 1–4).
14. **Grants land on the helper.** Superseded — see the slice 3b QA file (flow 6).
15. **Safety timeout.** Force-quit the renderer mid-step (or kill the API). Expected: the outline clears by
    itself within 150 s.
16. **Turn off.** Flip the switch off. Expected: the companion restarts; SOL offers no drive step.

## Edge cases

- [ ] Non-macOS (Linux/Windows build): row disabled, "Only on macOS for now."
- [ ] Debug helper not built: row disabled, "The input helper is missing from this install."
- [ ] Companion crash during a step: outline clears (bounds dropped when the child exits).
- [ ] From the SOL pill's devtools, `window.solus.sol.setDrive(true)` returns null and the setting stays off
      (only the main window can give consent).
- [ ] `--within` refusal: debug `solus-input identify --within "$HOME"` answers `usage`.
- [ ] `SOLUS_COMPANION_DRIVE=1` set in the shell that launches the app with the setting off: driving stays
      off (the setting is the consent).

## Result

| Flow | Pass/Fail | Notes |
| ---- | --------- | ----- |
| 1–16 |           |       |
