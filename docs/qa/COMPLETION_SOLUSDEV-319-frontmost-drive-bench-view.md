# Completion report — SOLUSDEV-319: frontmost-app driving + SOL changes Live Bench

**Branch:** `SOLUSDEV-319-kicad-embedded-symbol-compare` (shared with other sessions; local commits only,
nothing pushed). **Range:** `c35378bc^..6b4d03ab`, SOLUSDEV-319 commits for this feature only.
`6b2768e8` ("keep finding entities off the graph canvas") is in the range but belongs to another session
and is **not** part of this feature. **Date:** 2026-11-01.
**QA handoff:** `docs/qa/COWORK_QA_solusdev319_frontmost_drive_bench_view.md`.

## 1. What was built

Two parts.

- **(A) Frontmost-app driving.** SOL may drive the app in front when the user summons the pill. A
  denylist compiled into `solus-input` blocks some apps. KiCad stays project-bound. Every other app is
  window-bound to the window snapshot taken at summon.
- **(B) SOL changes Live Bench.** Each project has one versioned, team-shared bench view, with derived
  signals in a closed grammar (never `eval`). SOL has bench tools with change chips and Undo.
  Confirmation cards cover deleting a derived signal, starting or stopping a session, and a single
  bounded setpoint.

### Governance and docs (tier-2 approved in-chat, tier-1 docs)

| Commit     | What                                                                                                                                                                        |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `c35378bc` | ADR-041 amendment "frontmost-app driving" and ADR-014 amendment "SOL changes Live Bench" (both 2026-10-31)                                                                  |
| `c32259f3` | ADR-041 amendment "window-bound driving without a linked workspace" (Q4)                                                                                                    |
| `f019c639` | Contract: hint-only `bench.view_changed {project_id, version, at}` live frame (R1, ADR-014 2026-10-31)                                                                      |
| `2fd73cef` | **A0** drive slice 4 docs: `sol-drive.md` §2.2, `sol-window.md` slice 4, `API-implementation.md` turn `front_app`, `bridge-protocol.md` drive args gain `pid`               |
| `d357ff80` | **B0** bench docs: `docs/api/bench-view.md`, `docs/schemas/bench-view.md`, `docs/architecture/bench-view.md`, `docs/wireflows/live-bench-view.md`, API-implementation index |
| `b53f818f` | ADR-041 amendment 2026-11-01: the denylist also covers remote-desktop/VM consoles, launchers, REPLs and imagers (Phase 4 M-1)                                               |

### Part A: drive

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

### Part B: bench

| Task     | Commit                 | Summary                                                                                                                                                                                                                                                                        |
| -------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1 (+B2) | `e70bf924`, `dbefa320` | Closed expression grammar: shared conformance vectors (`bench-expression-vectors.json`), the Python write-time authority (`livebench/view/expression.py`) and the TS live evaluator (`expression.ts`, `derivedSignals.ts`). `scanToken` is split to meet the complexity limit. |
| B3       | `b6e320c0`             | `BenchView` model and migration `a31900000001`.                                                                                                                                                                                                                                |
| B5       | `4f4ad0ec`             | Bounded single setpoint: worker move (`livebench/setpoint.py`), the API `SetpointManager`, and `GET /setpoint` + `POST /setpoint/stop`.                                                                                                                                        |
| B4       | `5857e2f6`             | `BenchViewService` (project row lock, version/409, ops + inverse ops, events), `GET/PATCH /bench/view`, the live-publisher frame, and the setpoint router wiring.                                                                                                              |
| B7       | `38e72fa9`, `66750ef5` | Live Bench renders the shared view: controls, derived editor, groups, limits, hidden list, viewer read-only. Device and robot panels follow the shared layout.                                                                                                                 |
| B5b      | `bd5d7adf`             | Feetech torque read. Teleop start stops setpoints first. Per-robot move tracking and a step-limit guard.                                                                                                                                                                       |
| B1c      | `a400e754`             | Constant derived signals: zero-ref expressions are accepted and ticked once per poll (tier-1 amendment to `bench-view.md` §4.6 and the architecture doc).                                                                                                                      |
| B6       | `802ff26c`             | SOL bench tools: `bench_view.read/update_display/upsert_derived/delete_derived`, `bench.session_start/stop`, `bench.setpoint`. Adds `sessions_shared.py` and the red-team suite.                                                                                               |
| B8       | `02a3d9d8`             | Bench view change chip with Undo in SOL turns (`BenchViewChangeCard`).                                                                                                                                                                                                         |

### Phase 4 fixes

| Task | Commit                 | Summary                                                                                                                                                                                                                                                                                                           |
| ---- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| F1   | `2b3e8f53`             | Amortised O(1) `ma`/`integ` windows (Python + TS), so derived reads cannot stall the event loop (H-1).                                                                                                                                                                                                            |
| F2a  | `6c0c16fb`             | Bench tools split into modules. Off-loop, budgeted derived reads (`latest_reason: budget                                                                                                                                                                                                                          | deadline`) (H-1). Full session-card rows for non-default config (M-2). Shared limiters (M-3). |
| F2b  | `d5f115e0`             | Best-effort setpoint stop, bounded manager state, and the step limit now tracks the measured position.                                                                                                                                                                                                            |
| F3   | `187eb82b`             | Front-app chain: an app with no window downgrades to non-drivable instead of a 422 (code-review HIGH). Shared visible-text rule (`front-app-bodies.json` fixture). The strip names the step's app. Neutral consent wording. Guide drops `front_app`. Window-bound ending sentences never carry the title or name. |
| M-1  | `b53f818f`, `6b4d03ab` | Denylist widened (ADR amendment + Swift `Policy.swift` + tests).                                                                                                                                                                                                                                                  |

## 2. Governing docs

- DECISIONS.md: ADR-041 and all its amendments, especially 2026-10-31 ×2 and 2026-11-01 (also M2/M3 and 3b XPC). ADR-014 amendments 2026-10-31 and 2026-10-30 (teleop). ADR-037, ADR-011, ADR-019/026, ADR-032.
- Architecture: `docs/architecture/sol-drive.md` §2.2 and `docs/architecture/bench-view.md`.
- API: `docs/api/bench-view.md`, plus `docs/api/API-implementation.md` (turn `front_app`).
- Schema: `docs/schemas/bench-view.md`.
- Wireflows: `docs/wireflows/sol-window.md` (slice 4) and `docs/wireflows/live-bench-view.md`.
- Contracts: `docs/contracts/live-events.md` (`bench.view_changed`), `bridge-protocol.md` addendum, `action-gate.md`.
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
- **Bench view.**
  - Per-project, team-shared and versioned: 409 when stale. Members edit; viewers are read-only.
  - Closed grammar with a bounded AST and no eval. No derived-of-derived in v1.
  - SOL applies display changes and derived upserts directly, with Undo through `inverse_ops`. Delete, session start/stop and setpoint go through the gate.
  - The setpoint card has Robot / Joint / Current value (informational) / Target (clamped). It is refused during teleop, for followers, when uncalibrated, or when `torque_off`. There is never a teleop tool.
- **Bounds.** Expression ≤ 512 chars, ≤ 64 nodes, depth ≤ 12; filter window ≤ 10 s / 2000 samples; ≤ 32 derived per project, ≤ 8 refs each.

Later decisions:

- **Q4.** Window-bound driving works without a linked workspace: ADR-041 amendment `c32259f3`.
- **R1.** The live-frame contract is hint-only `bench.view_changed`: `f019c639`.
- **Constant derived signals.** Prompted by the user's live request ("constant measurement 10"). Recorded as a tier-1 doc amendment (`bench-view.md` §4.6, architecture §2) and implemented in B1c `a400e754`. The former `no_signal` error code is removed.
- **Denylist widening (M-1).** ADR-041 amendment `b53f818f`, approved in-chat 2026-11-01. Implemented in `6b4d03ab`.

## 4. Test coverage summary

**Python.** Counts are collected tests (`uv run pytest --collect-only -q`) in the test files this
feature added or extended. Extended files include tests that existed before.

| Area                                           | File → count                                                                                                 |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Expression grammar (shared vectors)            | `test_bench_view_expression.py` 299                                                                          |
| View model / migration                         | `test_bench_view_model.py` 13                                                                                |
| View service / router / isolation / live frame | 49 / 12 / 2 / 4                                                                                              |
| Setpoint (API)                                 | `test_bench_setpoint.py` 34, `test_teleop_setpoint_stop.py` 5                                                |
| SOL bench tools                                | view 16, session 10, setpoint 14, red-team 4, common 4, hardening 22                                         |
| Confirmation gate / modes                      | `test_confirmation_stored_args.py` 12, `test_modes.py` 10                                                    |
| Drive (API)                                    | binding 34, front-app bodies 12, stored gate 6, step tool 72, executor 79, red-team 68, isolation 6, port 48 |
| SOL turn `front_app`                           | `test_sol_front_app.py` 42, `test_sol_front_app_isolation.py` 4                                              |
| Companion                                      | `test_companion_drive.py` 81, `_window.py` 39, `_outline.py` 29                                              |
| Livebench worker                               | `lb_setpoint_test.py` 34, `lb_feetech_actuator_test.py` 18                                                   |

**TypeScript (vitest).** These are static counts of `it`/`test` declarations in the new or extended
test files. The full `vitest list` was not run. `it.each` rows and the vector-driven expression
suites expand further at run time.

- **Drive (main).** frontApp 13, frontAppShape 12, driveRelay 15 + window 8, driveController 20, driveAvailability 13, companion.drive 8, companionEnv 43, solWindow.frontApp 7, solBridge.frontApp 1.
- **Pill.** DriveStrip 15, frontAppBody 4, solApi 29, solWindowStore.frontApp 2.
- **Bench renderer.**
  - Expression and derived signals: expression 10 (plus all shared vectors), expressionWindow 6, derivedSignals 15, derivedDraft 6, useDerivedSeries 3.
  - View panels and controls: BenchViewPanels 11, DerivedSignalEditor 11, ViewControls 9, ViewSignalGrid 6, viewLayout 9, viewOps 4.
  - View state and data: useBenchView 13, BenchViewContext 3, useBenchViewContextValue 2, useBenchViewEvents 2, resources.benchView 10, projectEvents 11.
  - Widgets and screens: SignalWidget 14 + view 6, signalUnits 4, DeviceBenchView 23, BenchScreen.view 2.
- **SOL chip.** BenchViewChangeCard 9, solChatItems 23, solStream 38.
- **Shared types.** bench-view 5.

**Swift** (`solus-input`): `FrontmostAppTests.swift` has 38 test functions: denylist families, every
M-1 addition, pid/window binding, the `identify` front shape and pinned denied chords. `ChordTests` has 5.

Every test file listed passed when its task was committed. The Phase 4 fix commits re-ran the affected
suites green.

## 5. Live verification evidence (2026-11-01)

These runs used the real app (`REMOTE_DEBUGGING_PORT=9333 pnpm dev:all`).

- **Exact prompt via the pill.** "add a simple measurement in live bench with the name mehdi_test which just contains the constant measurement 10".
  - SOL called `bench_view.upsert_derived` and it returned ok.
  - The `bench_views` row holds a derived `mehdi_test` with expression `"10"`.
  - The Live Bench **DERIVED** card shows **10**.
- **Unit change turn.**
  - The chip read "Bench view · Changed the unit of 1 signal · Undo".
  - Clicking Undo changed it to "Undone ✓".
  - The DB row went to version 3 with display `[]`.

Part A frontmost-app driving with real third-party apps (Arduino IDE, the denylist matrix) was verified
by the test suites only. It is left for the Cowork QA pass.

## 6. Phase 4 review outcomes

**Code review**

- **HIGH:** a drivable window-bound `front_app` with a null or 0 `window_id` (an app with only minimized windows) made the turn fail with 422. Fixed in F3 `187eb82b`: main, preload, renderer and API all downgrade it to `drivable:false, binding:null`.
- **MEDs:** fixed in F3: the shared visible-text rule and fixture, the strip naming the step's app, neutral consent wording, Guide dropping `front_app`, and sentences without the title.

**Security review**

- **H-1 (event-loop stall).** An expensive derived read on the API event loop could stall it. Fixed in F1 (amortised O(1) windows) and F2a (evaluation off the loop in a worker thread, with a work budget and a deadline; over-budget entries get `latest: null`, `latest_reason`).
- **M-1 (denylist gaps).** Fixed by ADR amendment `b53f818f` and Swift `6b4d03ab`.
- **M-2 (session card rows).** The card hid non-default config. Fixed in F2a: every non-default config field now gets a row.
- **M-3 (limiters).** Fixed in F2a: shared limiters for setpoint and teleop drives.
- **L-1:** residual. Intent stems can still be avoided with words outside upload/flash/deploy and with cross-script look-alikes. Mitigated by per-step approval, the loop system prompt and the A3 strip.
- **L-2:** accepted residual (ADR-041 2026-10-31 workspace amendment): with no linked workspace the companion's file-change watch is off, so a step cannot report "SOL saved".
- **L-4:** residual. The API does not mirror the denylist; the helper is authoritative by design (sol-drive §2.2: "the API and main never decide denial themselves").
- **L-7:** wording changed. `routers/sol.py` and API-implementation.md no longer claim front_app is "never persisted": a parked front step stores its window binding (title included) in `tool_confirmations.args` for the card. Storage unchanged.
- **L-3:** fixed (F3 187eb82b). A drivable window-bound front_app with `window_id` null/0 made the whole turn 422; every layer now downgrades it to not drivable.
- **L-5:** fixed (F3). front_app on a non-Build (Guide) turn is dropped, so the title never reaches the model.
- **L-6:** fixed (F2a 6c0c16fb). `bench_view.read` refuses `unauthorized` when the caller's live membership is gone.
- **L-8:** fixed (F2b d5f115e0). The setpoint goal stays within one step of the measured position; on `timed_out` the joint holds its measured position.
- **Post-review finding (87f413a2):** session_start card rows that are cut or cleaned now carry a sha256 digest of the full value, so two long values sharing a prefix cannot render the same row.

## 7. Deviations and open concerns

- **B6 test order.** B6 was implemented before its tests were written, so TDD order was not kept. Tests were added before the commit, and the red-team, session and setpoint suites are in `802ff26c`.
- **Module names.** Some module names (e.g. `bench_view_tools.py`, `bench_tools_common.py`, `expressionWindow.ts`) were chosen so that hook H9 maps tests to sources. They differ from the architecture doc's sketch (`ops.py`, `bench_control.py`, `viewStore.ts`).
- **Oversized files.** `agent/confirmations.py` is 824 lines, above the 800-line cap. `runtime.py`, `routers/sol.py` and `models.py` were already oversized before this work. Splitting is left as follow-up.
- **Setpoint refusal code.** At park time, the `PreviewRefusal` code is collapsed to `unavailable` in the tool error. The specific code survives in the message (`setpoint refused (<code>): …`) and in the `bench.setpoint_refused` event.
- **`GET /setpoint` after a session ends.** It returns `null` once the session ends, not the last move's terminal state.
- **Second SSE connection.** Bench view hints arrive on a second SSE connection: the renderer opens its own project-event stream for `bench.view_changed`.
- **Cross-script homoglyph residual.** Look-alikes such as a Cyrillic `а` in `аpload` are not folded by NFKC, so they pass the intent refusal. This is recorded in sol-drive §2.2.
- **Unicode version skew.** Python's tables (Unicode 15) differ from V8's and Swift's, so a title containing a newly assigned character could still be refused with a 422 by the API's visible-text rule after the desktop accepted it. Rare, but recorded.
- **Wireflow endings.** `sol-window.md` slice 4 §5 names the app in ending sentences ("FreeCAD was restarted"). The implementation and sol-drive §2.2 (F3) use the fixed phrase "the window"/"the app" so that untrusted machine text never reaches the model. The wireflow text needs a human sign-off or an update.

## 8. Open human gates

1. Helper signing: set the real team ID in `SolusInputShared.h`, raise the version floor, and complete signing and notarisation. Release driving stays blocked until this is done.
2. Ratify `integrations/mcp/drive/allowlist.yaml` (changed in A2).
3. Apply migration `a31900000001` on shared and staging DBs.
4. Push and open the MR (human only). The branch is shared with other sessions.
5. Sign off on the visible wording changes in the `sol-window.md` slice 4 endings (see §7).
6. **Add-to-graph UX decision:** either auto-load once when the listing is missing, or show a prominent button plus a disabled style.
7. Run the Cowork QA pass (needs Arduino IDE 2, the denylisted apps, and a LeRobot SO-101 or the fake robot).

## 9. H10 / validation notes (pre-existing, not caused by this feature)

- mypy reports a duplicate module `solus.roster` (`integrations/mcp/kicad/solus/roster.py` vs `integrations/mcp/code/solus/roster.py`). It comes from SOLUSDEV-321.
- The full pytest suite times out under the hook's cap (`.claude/state/last_validation.md`). The feature's suites run green when run individually.
- ESLint reports warnings only, no errors.

## 10. Open concern: dev:all watchdog shutdown (2026-11-01)

During live verification the `dev:all` watchdog shut the stack down. The API `readyz` probe failed three
times while the API was busy, and at the same time the robot window evaluator was logging that it was
over its CPU budget. The F1/F2a fixes keep SOL's derived reads off the loop. Two things still need
investigation: a busy API's readiness probe should not trigger the shutdown, and the window evaluator's
CPU use under full robot streaming needs to come down. A probe timeout or grace window, and evaluator
profiling, are candidate follow-ups.
