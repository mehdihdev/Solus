# Completion report — SOLUSDEV-319: frontmost-app driving

**Branch:** `SOLUSDEV-319-kicad-embedded-symbol-compare` (shared with other sessions; local commits only,
nothing pushed). **Range:** `c35378bc^..6b4d03ab`, SOLUSDEV-319 commits for this feature only.
`6b2768e8` ("keep finding entities off the graph canvas") is in the range but belongs to another session
and is **not** part of this feature. **Date:** 2026-11-01.
**QA handoff:** `docs/qa/COWORK_QA_solusdev319_frontmost_drive_bench_view.md`.

> **Moved 2026-11-03:** Part B, "SOL changes Live Bench" (bench view, derived signals, setpoint, SOL
> bench tools, ADR-014 2026-10-31, contract `bench.view_changed`, migration `a31900000001`), moved to
> branch `SOLUSDEV-322-live-bench-lerobot-teleop` with the LeRobot/teleop work, and is reverted here.
> See `docs/qa/COMPLETION_SOLUSDEV-322-live-bench.md` on that branch. The gate commit `709d576c` stays
> on both branches. This report now covers drive only.

## 1. What was built

- **Frontmost-app driving.** SOL may drive the app in front when the user summons the pill. A
  denylist compiled into `solus-input` blocks some apps. KiCad stays project-bound. Every other app is
  window-bound to the window snapshot taken at summon.

### Governance and docs (tier-2 approved in-chat, tier-1 docs)

| Commit     | What                                                                                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `c35378bc` | ADR-041 amendment "frontmost-app driving" (2026-10-31); its ADR-014 paragraph moved to SOLUSDEV-322                                                           |
| `c32259f3` | ADR-041 amendment "window-bound driving without a linked workspace" (Q4)                                                                                      |
| `2fd73cef` | **A0** drive slice 4 docs: `sol-drive.md` §2.2, `sol-window.md` slice 4, `API-implementation.md` turn `front_app`, `bridge-protocol.md` drive args gain `pid` |
| `b53f818f` | ADR-041 amendment 2026-11-01: the denylist also covers remote-desktop/VM consoles, launchers, REPLs and imagers (Phase 4 M-1)                                 |

### Drive

| Task | Commit     | Summary                                                                                                                                                                                                                                                                                                                       |
| ---- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A1   | `c1bab2f9` | `solus-input` (Swift): `DeniedApps` denylist with exact and family matching. `ProjectBoundApps` (KiCad) replaces `DrivableApps`. `--within` is now optional. `--pid` and window-bound binding checks. New `identify` `front` shape. Pinned `DeniedChords` (save/close/quit/print). New `app_denied` and `pid_mismatch` codes. |
| A2   | `24189b8e` | Companion: drive is advertised without a workspace. `pid` added on capture/act. The bound-document save watch (`save_watch.py`). `documentDir`/`title` are kept local.                                                                                                                                                        |
| A3   | `1cc93460` | Desktop main: front-app summon snapshot (250 ms cap; Solus keeps the previous snapshot), the window-bound relay rule (`window_mismatch`) and preload/renderer shape checks.                                                                                                                                                   |
| A3b  | `1fa17434` | Companion env/spawn: the companion drives with no linked workspace.                                                                                                                                                                                                                                                           |
| A4b  | `11e5adf4` | API `drive.step`: front-app window binding (`binding.py`), the executor bind loop (`relaunched`/`window_mismatch`/`app_denied`/`not_in_front`), intent refusal, and the hostile window-title red-team fixture.                                                                                                                |
| G1   | `709d576c` | Confirmation gate stores Solus-derived args. Informational card rows are excluded from the divergence key. Guide refuses direct bench writes (`modes.py`).                                                                                                                                                                    |
| A4a  | `4f23b96a` | SOL turn carries `front_app` (nonce-fenced data block). The prompt orders routes API → `machine.write_file` → `drive.step`. Adds `sol.front_app_attached`.                                                                                                                                                                    |
| S1   | `40a973a6` | Drive hardening: Finder denied, window titles stay local, NFKC/casefold intent refusal with a visible-text rule, `stored_params` gate.                                                                                                                                                                                        |
| A5   | `787e705c` | Pill sends the front-app snapshot on Build turns. The strip reads `DRIVING <APP>`.                                                                                                                                                                                                                                            |

### Phase 4 fixes

| Task | Commit                 | Summary                                                                                                                                                                                                                                                                                                           |
| ---- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F3   | `187eb82b`             | Front-app chain: an app with no window downgrades to non-drivable instead of a 422 (code-review HIGH). Shared visible-text rule (`front-app-bodies.json` fixture). The strip names the step's app. Neutral consent wording. Guide drops `front_app`. Window-bound ending sentences never carry the title or name. |
| M-1  | `b53f818f`, `6b4d03ab` | Denylist widened (ADR amendment + Swift `Policy.swift` + tests).                                                                                                                                                                                                                                                  |

## 2. Governing docs

- DECISIONS.md: ADR-041 and all its amendments, especially 2026-10-31 ×2 and 2026-11-01 (also M2/M3 and 3b XPC). ADR-037, ADR-011, ADR-019/026, ADR-032.
- Architecture: `docs/architecture/sol-drive.md` §2.2.
- API: `docs/api/API-implementation.md` (turn `front_app`).
- Wireflows: `docs/wireflows/sol-window.md` (slice 4).
- Contracts: `bridge-protocol.md` addendum, `action-gate.md`.
- Plan: `.claude/state/plan-319-frontmost-bench.md`.

## 3. Human decisions recorded in-chat

From the plan (2026-10-31):

- **Denylist, not allowlist.** It covers terminals/shells, password managers + Keychain Access, System Settings, mail/messaging, web browsers and Solus itself.
- **Project-bound apps.** Only KiCad is project-bound. It keeps the working-folder binding and the linked-workspace requirement.
- **Window-bound apps.**
  - The binding is the summon snapshot (bundle id + pid + window id), re-verified before every `drive.step`.
  - The card shows App, Window (escaped) and "SOL will see this window".
  - Nothing is captured before confirm.
  - A relaunch or a different window ends the session.
- **Denied chords.** Save, close, quit and print are denied for window-bound apps, and pinned explicitly.
- **Intent refusal.** The executor refuses intents that mention upload/flash/deploy. The in-window button case is recorded as a residual.
- **`front_app` scope.** It is sent only while driving is available. A denied app is sent as bundle id + name + `drivable:false`. The prompt orders routes API → workspace files → drive.

Later decisions:

- **Q4.** Window-bound driving works without a linked workspace: ADR-041 amendment `c32259f3`.
- **Denylist widening (M-1).** ADR-041 amendment `b53f818f`, approved in-chat 2026-11-01. Implemented in `6b4d03ab`.

## 4. Test coverage summary

**Python.** Counts are collected tests (`uv run pytest --collect-only -q`) in the test files this
feature added or extended. Extended files include tests that existed before.

| Area                      | File → count                                                                                                 |
| ------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Confirmation gate / modes | `test_confirmation_stored_args.py` 12, `test_modes.py` 10                                                    |
| Drive (API)               | binding 34, front-app bodies 12, stored gate 6, step tool 72, executor 79, red-team 68, isolation 6, port 48 |
| SOL turn `front_app`      | `test_sol_front_app.py` 42, `test_sol_front_app_isolation.py` 4                                              |
| Companion                 | `test_companion_drive.py` 81, `_window.py` 39, `_outline.py` 29                                              |

**TypeScript (vitest).** These are static counts of `it`/`test` declarations in the new or extended
test files. The full `vitest list` was not run. `it.each` rows expand further at run time.

- **Drive (main).** frontApp 13, frontAppShape 12, driveRelay 15 + window 8, driveController 20, driveAvailability 13, companion.drive 8, companionEnv 43, solWindow.frontApp 7, solBridge.frontApp 1.
- **Pill.** DriveStrip 15, frontAppBody 4, solApi 29, solWindowStore.frontApp 2.

**Swift** (`solus-input`): `FrontmostAppTests.swift` has 38 test functions: denylist families, every
M-1 addition, pid/window binding, the `identify` front shape and pinned denied chords. `ChordTests` has 5.

Every test file listed passed when its task was committed. The Phase 4 fix commits re-ran the affected
suites green.

## 5. Live verification evidence (2026-11-01)

Frontmost-app driving with real third-party apps (Arduino IDE, the denylist matrix) was verified
by the test suites only. It is left for the Cowork QA pass.

## 6. Phase 4 review outcomes

**Code review**

- **HIGH:** a drivable window-bound `front_app` with a null or 0 `window_id` (an app with only minimized windows) made the turn fail with 422. Fixed in F3 `187eb82b`: main, preload, renderer and API all downgrade it to `drivable:false, binding:null`.
- **MEDs:** fixed in F3: the shared visible-text rule and fixture, the strip naming the step's app, neutral consent wording, Guide dropping `front_app`, and sentences without the title.

**Security review**

- **M-1 (denylist gaps).** Fixed by ADR amendment `b53f818f` and Swift `6b4d03ab`.
- **L-1:** residual. Intent stems can still be avoided with words outside upload/flash/deploy and with cross-script look-alikes. Mitigated by per-step approval, the loop system prompt and the A3 strip.
- **L-2:** accepted residual (ADR-041 2026-10-31 workspace amendment): with no linked workspace the companion's file-change watch is off, so a step cannot report "SOL saved".
- **L-4:** residual. The API does not mirror the denylist; the helper is authoritative by design (sol-drive §2.2: "the API and main never decide denial themselves").
- **L-7:** wording changed. `routers/sol.py` and API-implementation.md no longer claim front_app is "never persisted": a parked front step stores its window binding (title included) in `tool_confirmations.args` for the card. Storage unchanged.
- **L-3:** fixed (F3 187eb82b). A drivable window-bound front_app with `window_id` null/0 made the whole turn 422; every layer now downgrades it to not drivable.
- **L-5:** fixed (F3). front_app on a non-Build (Guide) turn is dropped, so the title never reaches the model.

## 7. Deviations and open concerns

- **Oversized files.** `agent/confirmations.py` is 824 lines, above the 800-line cap. `runtime.py`, `routers/sol.py` and `models.py` were already oversized before this work. Splitting is left as follow-up.
- **Cross-script homoglyph residual.** Look-alikes such as a Cyrillic `а` in `аpload` are not folded by NFKC, so they pass the intent refusal. This is recorded in sol-drive §2.2.
- **Unicode version skew.** Python's tables (Unicode 15) differ from V8's and Swift's, so a title containing a newly assigned character could still be refused with a 422 by the API's visible-text rule after the desktop accepted it. Rare, but recorded.
- **Wireflow endings.** `sol-window.md` slice 4 §5 names the app in ending sentences ("FreeCAD was restarted"). The implementation and sol-drive §2.2 (F3) use the fixed phrase "the window"/"the app" so that untrusted machine text never reaches the model. The wireflow text needs a human sign-off or an update.

## 8. Open human gates

1. Helper signing: set the real team ID in `SolusInputShared.h`, raise the version floor, and complete signing and notarisation. Release driving stays blocked until this is done.
2. Ratify `integrations/mcp/drive/allowlist.yaml` (changed in A2).
3. Push and open the MR (human only). The branch is shared with other sessions.
4. Sign off on the visible wording changes in the `sol-window.md` slice 4 endings (see §7).
5. **Add-to-graph UX decision:** either auto-load once when the listing is missing, or show a prominent button plus a disabled style.
6. Run the Cowork QA pass (needs Arduino IDE 2 and the denylisted apps).

## 9. H10 / validation notes (pre-existing, not caused by this feature)

- mypy reports a duplicate module `solus.roster` (`integrations/mcp/kicad/solus/roster.py` vs `integrations/mcp/code/solus/roster.py`). It comes from SOLUSDEV-321.
- The full pytest suite times out under the hook's cap (`.claude/state/last_validation.md`). The feature's suites run green when run individually.
- ESLint reports warnings only, no errors.
