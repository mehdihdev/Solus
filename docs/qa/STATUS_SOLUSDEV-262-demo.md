# SOLUSDEV-262 demo status — 2026-09-16

The standalone controller folder is created and linked. The complete five-step
live demo is **not yet accepted**.

## Delivered

- Created the clean Solus `demo` project and, with user approval, raised only its
  local development account's project allowance from 3 to 10.
- Pulled the local LeRobot reference to commit
  `4aaff99be4a1d81568c08c8f0296b41b40c99ec4`. Created `/home/beeboss/demo`
  outside the Solus repository with a small controller, actual source-derived
  joint declarations, existing calibration copies, isolated dependencies, tests
  and a README. User linked it through the native picker; Python/KiCad graph
  nodes are verified.
- Added explicit primary-versus-diagnostic signal metadata, source-authorized
  repository evidence, honest normalization/calibration handling, reconnect
  cleanup, and a per-conversation confirmation preference.
- Preserved exported KiCad pin functions, refusing ambiguous declarations and
  unproven wiring relationships.
- Added graph-backed connected CAD imports and SOL tools, full static transforms,
  revision-aware refresh, and a Scene picker with scoped cancellable polling.
  Normal Onshape sync completed with 45 real entities; picker visibility is
  verified. No guessed kinematics or accepted live mapping.
- Added upload previews and strict build/device checks. Security review found
  the CLI cannot receive exclusive serial ownership; public execution therefore
  fails closed before opening hardware. Automatic upload is unfinished.
- Fixed `pnpm dev:all` defaults: with Redis, remote syncs use the worker while
  Local/KiCad/Altium retain the API's bridge through background tasks. Explicit
  shell overrides remain intact. Local bridge work is still interrupted by an
  API reload; remote imports are independent of it.
- Restored the account's existing development credit exemption after explicit
  user approval. SOL shows Unlimited (development). No manual ledger adjustment
  or purchase. The already-approved publisher/artifact configuration is loaded
  in the running API.

## Evidence and verification

- Final API collection: **7,244 passed, 6 skipped**. Every one of 7,250 final
  collected test IDs is accounted for across JUnit results in
  `/tmp/solus-demo-api-results.xml` and
  `/tmp/solus-demo-api-remaining-results.xml`. Initial outdated fixture/roster
  expectations were fixed without weakening assertions. Timestamp-bearing ZIP
  parameters now have stable IDs for parallel collection.
- Live Bench: **713 passed**.
- Desktop: full suite ran; socket/process tests required an unsandboxed rerun
  (**37 passed**). Final source-panel/composer checks: **42 passed**. Scene
  checks: **51 passed**. Desktop type checking passes.
- Controller: **18 hardware-free tests passed**. Fresh code/Python/security
  reviews corrected raw-position clamping, USB identity checks and per-motor
  stop cleanup. A later read-only hardware check confirms both saved calibrations match
  their motors; natural resting positions may remain outside calibrated bounds. No motion, calibration writes or flash.
- Upload: **27 tests passed** for safe previews/refusal and isolated internal
  helpers. This does not prove live flashing; public execution is disabled.
- Launcher/source dispatch: **60 tests passed**, with separate security and
  code-review passes. CAD import/registry security: **17 tests passed**, including
  foreign-team POST refusal without queueing.
- Changed-file ESLint and Ruff pass. Mypy passed all 32 changed API/Live Bench
  modules in its combined run; later source-dispatch code also passed its scoped
  mypy check. Full desktop ESLint remains non-green in files outside this diff;
  the specialized TypeScript reviewer withheld full approval at that gate.
  General code/security reviewers completed the scoped semantic reviews.

## Remaining live gates

1. User completed calibration: `boss_arm` leader and `bee_arm` follower now
   match hardware. Corrected roles: leader USB `5B42134331`, follower USB
   `5B42135040`. Current natural resting positions can lie outside calibrated
   limits; motion still refuses these. User accepted sensitivity; no range widening.
2. Controller and schematic reads were approved. Testing exposed lost approved
   result history and false-positive filename redaction; fixes are under review.
   Truncated historical evidence is not sufficient for whole-file replacement.
3. Hardware-source file authorization, role/config acceptance, a saved robot,
   and the live 12-primary-signal demonstration remain to be completed in demo.
4. Generate proposed sensor wiring for the user to build, then verify it; review
   and approve file changes; resolve the
   uploader's exclusive-descriptor requirement before any automatic flash.
   Neither of the two physical sensor channels has been demonstrated.
5. Import the chosen CAD into a confirmed robot and verify refresh/live mapping
   where actual joint evidence exists. Current geometry is available; a live
   robot scene is not yet accepted.

Broader five-step polish such as recursive provider folders, real provider account
labels and the complete graph interaction acceptance has not been certified by
this pass. Do not interpret focused tests as full demo acceptance.

## Governing material and workflow

Followed the supplied five-step demo packet, the hardware/code/local-machine
architecture and route plans, bench-scene API plan, KiCad and Onshape development
plans, and hardware/SOL wireflows. Tier-1 docs were amended for source evidence,
CAD import/polling, approval preference, upload refusal, projection version and
provider dispatch. No ADR, shared contract, AGENTS, hook or environment-file
changes were made. No commits, pushes or merge requests were created.

The Ponytail plugin and named `.Codex/commands` files were unavailable; reviews,
verification tools and available skills were used directly. The runnable QA
handoff is `docs/qa/COWORK_QA_SOLUSDEV-262-demo.md`.

## External-controller telemetry continuation (2026-09-16)

Added generic authenticated background HTTP publisher and server-time bounded external-device
discovery. Live Bench merges received device IDs with session IDs without opening serial ports
or inventing sessions. The standalone controller publishes its existing normalized readings
optionally; `observe` reads raw encoder counts without torque/goal/calibration writes. It uses
`encoder_count`/`tick`, distinct from normalized `position`/`%`. Publisher failures never alter
control commands. Environment bearer authentication remains required; no token was extracted or
authentication bypassed. The new live 12-channel path is not yet physically demonstrated.

Library: 72 tests, 94% publisher coverage. Discovery: 27 API tests; frontend: 26 focused tests
and web types. Standalone: 22 tests. Scoped general, Python and security review passed.
Tier-1 architecture/API/wireflow docs amended for external HTTP producers. Full five-step demo
acceptance remains open, including approved graph configurations, publisher sign-in, schematic
approval/ERC, physical sensor response and firmware upload ownership.

Follow-up TypeScript review: scoped ESLint, hook tests and both desktop typechecks pass.
The specialized reviewer stops at the existing global lint gate (96 errors, 13 warnings);
no full-branch TypeScript approval is claimed. Generated OpenAPI and desktop types updated.
SOL has begun a proposed FSR/USB schematic in `hardware/proposed_fsr_usb_wiring.kicad_sch`
in the linked demo folder. This is proposed wiring, not a claim the user installed it.
The native KiCad executable is absent, so an actual KiCad ERC pass is still unavailable.

### User wiring correction

The user has no external 10 kΩ resistor. The earlier partially written
`proposed_fsr_usb_wiring.kicad_sch` is superseded and is NOT a wiring guide.
The revised proposal is FSR402 between Uno A0 and GND, with firmware enabling
A0 INPUT_PULLUP. The internal pull-up is not an external component and its exact
resistance is unknown. Raw ADC counts should decrease under pressure; no calibrated
force unit is asserted. SOL was asked to prepare a new `proposed_fsr_pullup_wiring.kicad_sch`
with Confirm every change enabled. No wiring, firmware flash or ERC pass is claimed.

Final user clarification: TWO FSR402 sensors total, one per follower-gripper finger.
Proposed independent channels: finger1 A0–GND and finger2 A1–GND, both INPUT_PULLUP.
No external resistor and no sensor on the leader. The one-sensor pending preview was
rejected as superseded; SOL is preparing `proposed_dual_fsr_pullup_wiring.kicad_sch`.
The updated API has been restarted: readiness 200, unauthenticated discovery 401.

The dual-FSR proposal is visible in SOL with a persisted sheet-creation preview awaiting
user approval; it is not yet a completed schematic. Updated live acceptance target is
14 primary channels (12 joints + 2 separate sensor readings), replacing the original
13-channel single-sensor target. No authenticated physical publish or firmware flash yet.

## Earlier continuation checkpoint (superseded below)

- User reports both follower-finger FSR402 sensors wired. Intended connections
  are A0–GND and A1–GND with independent internal pull-ups; physical sensor
  response remains unverified. No firmware has been flashed.
- Actual `boss_arm` / `bee_arm` calibration files were compared byte-for-byte
  with the demo calibration copies. Both match. Two calibration documents
  appear in the graph; native local-source grants remain a separate prerequisite.
- Hardware → Local configuration and calibration now exposes Choose local file
  directly. The sidebar and Live Bench use existing Solus theme tokens, shared
  buttons, and consistent inputs/focus states. Focused tests and web types pass;
  scoped code review found no actionable issue. Native picker verification is pending.
- A real KiCad 10 runtime is available. The new dual-FSR schematic has verified
  A0/A1/GND net connectivity. Latest real ERC reports four issues: ground power metadata
  and three off-grid placements. SOL completed the final unused-pin marker. No ERC pass
  is claimed. Older single-sensor/10 kΩ drafts remain superseded.
- Interactive `solus_login.py` is installed in the external demo folder; it uses
  hidden terminal password input and an ephemeral normal user session. Standalone
  hardware-free tests: 35 passed. No authenticated physical publish yet.
- Full demo acceptance remains open: local grants and robot confirmation,
  schematic completion, sensor firmware/integration, exclusive upload, live
  14-channel telemetry, and the CAD scene.

### Native Hardware panel crash

The user reproduced a fully blank native window after opening Add → Hardware.
Electron logged React's maximum update depth error. The ambient and Add-panel
DevicesFound consumers independently loaded native source lists, producing
conflicting pending/ready keys and repeatedly resetting their shared proposal
store. Browser-only checks did not exercise this native path.

The source hook now shares one authorized snapshot/request per project/session
revision. Token/user/status changes invalidate it; old responses cannot publish
into a new scope. A regression test failed before the fix; 50 hardware tests and
both desktop type checks now pass. Scoped security review passes. Corrected native
app relaunched; user confirmed Add → Hardware stays visible after the fix.

## Verified continuation — 2026-09-16

- All four native file grants now exist for the demo controller and calibration
  files. No further picker action is required for those files.
- The final dual-FSR schematic passes real KiCad ERC with zero violations.
  Both A0/A1 sensor nets and shared ground were checked in the exported netlist.
  The ERC power flag is excluded from the physical BOM/board. Operator edits
  finished the annotations/grid alignment; these were not all completed by SOL.
- SOL created the actual dual-FSR sketch through a reviewed file action and
  successfully compiled it for `arduino:avr:uno`. Retained build:
  `bf8fe0b7-45c8-5164-9dcc-0ec4ccc8dcb1`. Compilation is not upload evidence.
- Both robot identities are saved. Live Bench displayed all 12 raw joint
  channels. After stopping both sessions, the standalone read-only check verified
  both saved calibrations against the hardware: leader serial `5B42134331` on
  ACM1, follower `5B42135040` on ACM0. All 12 per-motor configurations were then
  saved through the versioned UI with real joint signal names, saved calibration
  values and the already-authorized opaque source references. Edits are correctly
  attributed to the reviewing user action, not fabricated parser provenance.
- Restarted saved-robot sessions use the controller's percent normalization.
  Follower's six named calibrated position channels were verified in Live Bench.
  Physical part graph names still use the detected Motor-N labels.
- Recorded and replayed `Demo calibrated follower — read-only`: **3,480 packets,
  zero dropped**, completed. Analysis correctly reports insufficient evidence
  for a stall diagnosis instead of inventing a cause. No motor motion commanded.
- Installed independently reviewed dual-FSR host reader and optional controller/
  login flags in the external demo folder, preserving backups. Hardware-free
  validation: 67 tests and 21 subtests; no physical ADC response verified yet.
- Fixed the widget's wrong exact-robot telemetry query. It now uses authorized
  descendant/device feeds, rejects obsolete focus/account responses, and shows
  errors honestly. Actual follower widget now receives live samples. Initial
  focused suite: 47 tests, scoped lint and renderer types pass. Global desktop
  lint remains non-green (96 pre-existing errors); no full-branch approval.
- CAD import failure was reproduced from cached source bytes: fixed-detail
  tessellation exceeded the model triangle cap. Reviewed bounded adaptation
  retains all 19 leaves, 35,390 triangles and a 6,457,415-byte normalized model,
  within unchanged resource caps. Focused CAD suite: 37 tests pass. Live import
  acceptance now passes: the actual connected Onshape model renders in the running
  Live Bench. The scene explicitly reports NO LIVE MAPPING, so static import is
  not represented as verified joint animation.
- Final widget freshness follow-up: 53 focused tests, lint and renderer types pass;
  independent reviewer reran 20 affected tests. Actual focused follower widget
  displays current repo names without stale Motor-N channels. Both saved arm
  sessions were restored after the API restart, with all twelve channels verified.
  Future/invalid timestamps cannot produce LIVE status; valid past stale samples
  remain available with an honest stale state.

The complete demo is still **not passed**. Firmware upload remains deliberately
unavailable because the pinned uploader reopens the serial path and cannot retain
the exclusive descriptor. Do not bypass that refusal. A reviewed uploader/toolchain
change or a separately supervised Arduino IDE upload is needed before physical
two-sensor/14-channel acceptance. Authenticated standalone mirroring, physical
teleoperation, CAD live mapping, and the remaining original acceptance cases are
not implied by the checks above.

## Telemetry responsiveness continuation — 2026-09-16

The user clarified that SOL should write the `.ino` in the linked demo folder and
they will upload it with Arduino IDE. That tool-based write and compilation were
already verified; SOL now provides the manual-upload handoff in its demo chat.
Exclusive automatic flashing is no longer a prerequisite for this demo path.

The reported slow/disappearing telemetry has multiple verified causes: 2.5-second
UI polling, anomaly requests blocking publication of readings, removal of cards
after an eight-second data gap, and a duplicated `/api/v1` discovery prefix.
Additionally, kernel logs show repeated physical leader USB disconnects. The user
confirmed only Solus was connected while moving the leader by hand; host port
ownership confirmed a single API process. Physical USB reliability remains distinct
from the UI bug and must not be claimed fixed by a renderer change.

Implementation follows ADR-005, `docs/architecture/hardware-onboarding.md`,
`docs/architecture/telemetry-viz-out.md`, the realtime section of `docs/api/API.md`,
and the existing hardware/widget wireflows. The tier-1 API amendment specifies the
already planned session WebSocket's bounded authentication/read-only frames,
heartbeat, reauthorization and fallback behavior. It adds no motor control.
Frontend, backend and independent security/code review have disjoint assignments.
Hardware-free driver/reconnect regression verification: 26 tests passed.
Verification completed for this software slice:

- Backend stream/telemetry/session suite: 62 tests passed; scoped mypy/Ruff/format
  passed. Renderer bench/widget suite: 214 tests passed, scoped ESLint and types
  passed. Exact-origin CSP follow-up: 21 tests and full desktop typechecks passed.
- Independent fresh code/security review passed after fixing malformed authentication,
  bounds, cleanup, permission masking and heartbeat edge cases.
- Restarted the local API and desktop. Actual `/ws/v1/bench/sessions/...` connections
  for both saved arms were accepted. Live Bench displayed all twelve calibrated
  channels without periodic-update fallback. Focused follower widget showed LIVE DATA
  through the same shared transport; CAD remained rendered.
- Live request inspection after navigation/focus changes: four device-recent
  initialization/projection reads, zero duplicate-prefix errors and zero runtime
  errors. The subsequent steady-state interval had zero device-recent HTTP reads,
  zero session socket reopens and zero runtime errors. Twenty DOM-backed chart
  reads over 135 ms observed three distinct chart states with no missing chart.
  This demonstrates prompt rendering, not a physical-motion latency benchmark.
- Browser CSP initially blocked WS while permitting HTTP. The correction adds only
  the exact configured WS(S) counterpart; no wildcard relaxation. The actual served
  document now includes both permitted API origins.

Manual movement feedback and physical USB reliability remain pending. No motion or
firmware upload was initiated by this continuation. The complete 14-channel sensor
demo is still not certified; the user will flash the SOL-authored sketch separately.

## 2026-09-16 screenshot pack; smoothing reverted

Saved 15 real application captures and an index in demo-screenshots. At the user's request,
removed the subsequent display smoothing increment, its controls/rounding/chart-range changes,
and associated ordering changes. Earlier WebSocket streaming, discovery and stale retention
work remains. The latest not-yet-deployed stale-remount experiment was withdrawn as well.

During diagnosis of missing signals, restarted the two saved-robot read-only telemetry
sessions. The OS log confirms repeated leader USB disconnects/descriptor errors; software
reconnection does not establish that the physical fault is fixed. Stale channels can disappear
on remount because the WebSocket window excludes samples older than eight seconds; this
separate recovery defect remains open. No new API restart or hardware motion occurred.
