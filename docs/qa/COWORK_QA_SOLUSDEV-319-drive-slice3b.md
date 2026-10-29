# Cowork QA — SOLUSDEV-319 drive slice 3b (helper as an XPC agent)

Spec: `docs/architecture/sol-drive.md` §2.1 (agent), §3 (companion relay), §5 (packaging, main and the
agent, the companion environment, bundle seal). Decisions: DECISIONS.md ADR-041 amendment 2026-10-28
(XPC), which supersedes the C1 and 3b transport. Slice 3's flows (`COWORK_QA_SOLUSDEV-319-drive-slice3.md`
1–12, 15–16) still apply on a dev build.

## Setup

- [ ] macOS 14+, KiCad 10, a Solus account, the API with the drive allowlist ratified.
- [ ] **Unsigned packaged build:** `make desktop-mac` (builds the helper bundle, the XPC module, the
      companion, then the app). Install in /Applications. The team ID is still the placeholder, so flows
      1–4 check that everything fails closed.
- [ ] **Signed packaged build (flows 5–14):** a human sets the real team ID in
      `apps/desktop/native/solus-input/Sources/SolusInputShared/include/SolusInputShared.h`, raises the
      `CFBundleVersion` floor there to this build's version, and builds with `SOLUS_SIGN_IDENTITY`,
      `SOLUS_TEAM_ID` and notarisation. Install in /Applications.
- [ ] A Solus project linked to a folder holding a copy of `solus_sample`.

## Flows

1. **Placeholder fails closed (unsigned).** Turn on "SOL can use your mouse and keyboard". Expected: the
   row is unavailable with the bundle sentence ("This copy of Solus has been changed since it was signed…"),
   because the bundle check fails without a team ID; SOL offers no drive step.
2. **Agent refuses to start (unsigned).** From Terminal:
   `/Applications/Solus.app/Contents/Resources/SolusInput.app/Contents/MacOS/solus-input serve`. Expected:
   it exits with status 1 (its own signature fails).
3. **Release helper has no argv path.** `…/solus-input identify --within /tmp`. Expected: a `usage` reply
   with `"unsignedDev":false`, nothing captured.
4. **Fuses.** `npx @electron/fuses read --app /Applications/Solus.app`. Expected: RunAsNode,
   NodeOptions and NodeCliInspect disabled; embedded ASAR integrity validation and OnlyLoadAppFromAsar
   enabled.
5. **Registration.** Signed build: turn the setting on. Expected: macOS may show a Login Items
   notification for SolusInput; if Settings shows "Needs approval", click "Open Login Items", allow
   SolusInput, return — the card clears. Turn the setting off: SolusInput disappears from Login Items.
6. **Grants land on the helper.** Grant from the Needs-attention card. Expected: System Settings › Privacy
   & Security › Accessibility and Screen Recording list **SolusInput**, never Solus.
7. **A drive step end to end.** Approve "add a resistor" in KiCad. Expected: the A3 strip advances, KiCad
   is driven, the step ends `done` (or `saved` if SOL saved).
8. **Stop and cancel.** During a step, click Stop. Expected: `STOPPING…`, then the step ends "paused — you
   took over" at its next action; no click lands after the strip clears.
9. **Permission check during a step.** While a step runs, switch to Settings (it refreshes the permission
   rows). Expected: the step keeps running; the rows update when it finishes or within a few seconds.
10. **Idle exit.** Wait 2 minutes with no step, then run one. Expected: `ps aux | grep solus-input` shows
    no agent while idle; the step still works (launchd starts the agent on demand).
11. **Only Solus.app may talk to it.** From Terminal run any XPC client for
    `com.solusforge.solus.input.agent` (a developer can use a small Swift script). Expected: the connection
    is invalidated; nothing is captured or posted.
12. **Modified copy refused.** `cp -R /Applications/Solus.app ~/Desktop/SolusCopy.app`, change one byte in
    `Contents/Resources/companion/solus-companion/_internal/base_library.zip`, launch the copy (quit the
    installed one first). Expected: the drive row shows the bundle sentence; no drive step is offered.
13. **No debug switches.** `open -a /Applications/Solus.app --args --remote-debugging-port=9222` (and,
    separately, `--inspect`, `--renderer-cmd-prefix=/bin/echo`, `--foo`). Expected: Solus exits at once.
    `open solus://…` (any app link) still starts it.
14. **Environment ignored.** Quit Solus;
    `SOLUS_COMPANION_URL=ws://127.0.0.1:1 PYTHONINSPECT=1 /Applications/Solus.app/Contents/MacOS/Solus`.
    Expected: the bridge still connects to the real API; no Python prompt appears.

## Edge cases

- [ ] A drive request whose `--within` is not the project's linked folder (dev: edit the companion to send
      one) gets `usage` and never reaches the agent.
- [ ] Two drive calls at once from the companion: the second gets `usage` ("one drive call at a time").
- [ ] Behind a corporate HTTPS proxy, the packaged companion cannot reach the API (known limitation —
      proxy variables are not passed through; `apps/desktop/docs/companion-packaging.md`).

## Result

| Flow | Pass/Fail | Notes |
| ---- | --------- | ----- |
| 1–14 |           |       |
