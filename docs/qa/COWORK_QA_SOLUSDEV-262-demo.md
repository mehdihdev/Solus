# SOLUSDEV-262 — live demo verification

## Current setup and limits (2026-09-15)

Use the local development account and project `demo`
(`01a0a765-9fcf-7752-8cdf-f807c3133490`). The user authorized increasing only this
account's local project allowance from 3 to 10; no purchase or billing change.
The native folder picker has authorized `/home/beeboss/demo`, outside Solus.
Its graph contains local-folder, Python-code and sample-KiCad nodes.
LeRobot reference is `/home/beeboss/lerobot`, upstream commit
`4aaff99be4a1d81568c08c8f0296b41b40c99ec4`.

The external controller uses USB serial identities, never fixed tty assignments:
leader `5B42134331`, follower `5B42135040`. Last checked ports were ACM1 and ACM0,
respectively; always resolve the serial at runtime. User completed `boss_arm` and `bee_arm`
calibrations; refreshed copies match both six-motor buses. Natural resting positions can
fall outside the recorded range. User accepts sensitivity but bounds remain enforced.
No agent-commanded motion or firmware flash has been performed.
The user reports both follower-finger sensors wired; actual ADC response remains unverified.
The account's existing local development credit exemption is active; SOL displays
Unlimited (development). No manual billing-ledger adjustment was made and no credits were purchased.
SOL file reads have been approved. Verify approved results survive continuation as
bounded untrusted evidence, without granting new file access or replaying actions.

API and worker use persistent artifacts at `tmp/solus262-artifacts`. A previous
inline Onshape import was interrupted by the development launcher stopping. Its
specific abandoned job was marked failed and a normal manual sync completed:
45 real CAD entities are present and the Scene picker lists the actual assemblies.
A scene model is still not imported: no physical robot has been confirmed in demo.
The account is near its Onshape call threshold; do not bypass its quota policy.

## Standalone controller

- [ ] In a terminal, `cd /home/beeboss/demo` and run
  `.venv/bin/python -m unittest -v`. Expect all hardware-free tests to pass.
- [ ] Disconnect other controllers/Live Bench sessions, support the arms, and run
  `.venv/bin/python teleop.py check`. Expect both identities, six raw tick values
  each, and matching calibration. A changed calibration must refuse with
  exact differing limits; no writes are permitted.
- [ ] After supervised calibration is verified, run
  `.venv/bin/python teleop.py run --duration 10` with the user present. Move the
  leader gently. Expect follower tracking, bounded command increments, then
  torque release. No software check guarantees physical force or speed limits.
- [ ] Ctrl+C must attempt torque release on every follower motor. A failed motor
  must not prevent attempts on remaining motors; release failures are explicit
  and exit nonzero. Support the arm before stopping; keep power cutoff accessible.
- [ ] Occupied port, changed USB identity, missing motor, non-position mode,
  incomplete/nonfinite/out-of-range samples, or mismatched calibration refuse.
  Never perform hazardous physical disconnection solely to test a failure path;
  mocked regression tests cover these cases.

## Graph and hardware setup

- [ ] Home shows `demo`; Local folder shows `/home/beeboss/demo` in the native app.
  Workspace shows the Python and sample-KiCad nodes. The sample is not proof of
  any newly wired sensor.
- [ ] Hardware setup explicitly authorizes `leader.json` and `follower.json` from
  that folder through native source selection. Proposed names/IDs derive from
  those source declarations; changing source bytes before confirmation refuses.
- [ ] Confirm each physical role once. Both arms expose motor addresses 1–6.
  USB reordering preserves role; never assume tty numbering stays fixed.
- [ ] Bench displays six primary position channels per arm. Diagnostics are
  separate and collapsible; diagnostic anomalies remain visible. Unknown units
  remain unknown; a normalization declaration alone is not calibration evidence.
- [ ] Simulated reconnect factory failures retry; cancellation closes resources.
  Confirm accepting one actor's local source cannot grant another actor access.

## SOL, schematic and firmware

- [ ] Enable **Confirm every change** before a SOL Build request. The toggle is
  disabled while streaming, persists across pane navigation, and resets with a
  new conversation/account. Every required approval remains a real approval card.
- [ ] Request a sensor wiring proposal. Require exact graph component IDs,
  connected-to net edges and exported physical-pin/function evidence. A0/A1
  mismatch, conflicting exported pin names, disconnected or foreign-project
  entities must refuse. Never invent physical wiring from intent.
- [ ] Review separate firmware/controller file previews and approve only intended
  changes. Rejecting leaves the files unchanged; changing evidence before approval
  must invalidate the proposal.
- [ ] Firmware upload preview states observed device identity, selected Uno
  profile, source/build digests and unknown prior firmware. Execution currently
  refuses `device_ownership_unavailable` before opening the device: a CLI that
  reopens a tty cannot yet receive the required exclusive serial lease. This is
  an unfinished demo gate. No automated flash acceptance is claimed.
- [ ] Only after an independently supervised valid firmware upload and real
  sensor wiring, check firmware-declared sensor discovery and physical response.
  Require two independently observed raw ADC channels; no fabricated measurements.

## CAD scene

- [ ] Sync the selected actual Onshape source once through its normal pipeline.
  Reopening/reselecting cached content must not create extra exports.
- [ ] In Live Bench → Scene → Spawn, select a saved robot and **Connected CAD**
  assembly/part with a visible revision. Import must be explicit; no revision or
  no robot disables import. Empty source list explains the missing prerequisite.
- [ ] Pending status polls only the local project API. Status retry does not POST
  a second import. Switching robot/project/account invalidates stale responses.
- [ ] A complete import displays actual bounded geometry and full transforms.
  Missing joints give an explicit static model explanation, not guessed motion.
  Missing geometry/transforms refuse rather than substituting bounding boxes.
- [ ] A later source revision refresh preserves model identity and updates the
  geometry/transforms/digest. Live motion requires confirmed valid joint mapping.
- [ ] Cross-project robot/source/import IDs refuse. Existing local URDF/MJCF and
  leaf CAD-binding flows retain their behavior.

## Outstanding acceptance

The complete five-step demo is not yet passed: external publisher authentication, physical
sensor response, native configuration grants, exclusive firmware upload, and live CAD/motion
acceptance remain. Full desktop lint also reports failures outside this task's
scoped checks; do not label the branch fully approved based on focused tests.

## External owner / Live Bench coexistence

- [ ] Sign in as the project member and supply a valid access token to the external process
  as `SOLUS_TOKEN`, never in command arguments or source. There is no app token-export UI yet.
- [ ] Stop direct arm sessions; ensure no other controller owns the ports. Run
  `.venv/bin/python teleop.py observe --duration 20 --fps 10 --solus-project 01a0a765-9fcf-7752-8cdf-f807c3133490`
  from `/home/beeboss/demo`. Expect 12 actual encoder-count signals with `tick` units, no motion.
- [ ] Live Bench discovers received streams despite zero direct arm sessions. A confirmed
  matching graph mapping yields accepted packets; unconfirmed identities remain unresolved.
- [ ] Stop observer: discovery expires within 15 seconds plus a polling interval.
- [ ] With arm positions inside verified ranges, user-supervised teleoperation with the same
  `--solus-project` option copies existing normalized readings (`%`); no second process opens USB.
- [ ] Server offline, expired token or slow HTTP only affects telemetry counters; it neither
  blocks nor changes controller motor commands. Exercise transport faults using mocks.
- [ ] Switch account/project: no old IDs or values appear. Session-backed feeds remain visible
  if discovery fails. Sessionless streams are not represented as controllable/recordable sessions.

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

## Sidebar and local-file verification

- [ ] In the native desktop app, Workspace → Add → Hardware shows Local
  configuration and calibration directly, without opening Unassigned parts.
- [ ] Choose local file links each actual demo configuration and calibration file.
  Uploaded project documents alone do not confer local filesystem access.
- [ ] Verify checks current bytes; changing a file requires relinking/review.
  Canceling the picker does not create a source. Switching project/account cannot
  expose the previous account's sources or apply an old picker result.
- [ ] At narrow and wide window sizes, sidebar controls and Live Bench inputs
  remain readable, keyboard focus is visible, and disabled controls stay disabled.
- [ ] Check the real saved `boss_arm` and `bee_arm` calibration bytes match the
  copies selected for the corresponding USB serial identities.

The earlier schematic and compilation checkpoints above are superseded by the
2026-09-16 verification below. Two sensors are reported wired; actual upload and
physical ADC response remain pending. Full acceptance requires 14 independent channels.

### Native multi-surface regression

- [ ] In the native app with devices visible in the graph's ambient device rail,
  open Add → Hardware. Both device lists must render without blanking the window
  or logging Maximum update depth exceeded.
- [ ] Delay the native source list in a test harness; opening the second list
  must share the first list's pending/ready state and not start another probe.
- [ ] Dismiss a device in one surface; the other reflects the dismissal.
- [ ] Relink/verify a source or change account/project while a list is pending.
  Only fresh authorized source references may enter subsequent proposals.

## Verified continuation — 2026-09-16

- [x] All four native local-file grants exist. Calibration copies match the saved
  `boss_arm` and `bee_arm` files. Twelve graph motor configurations now contain
  those calibration values, source references and repo joint names.
- [x] Both saved robots stream simultaneously: leader serial `5B42134331`,
  follower serial `5B42135040`. Twelve named joint channels use normalized `%`.
  These read-only checks did not command motion or widen calibration limits.
- [x] Run `Demo calibrated follower — read-only` completed with 3,480 packets,
  zero dropped, and verified playback of six named follower channels.
- [x] `hardware/proposed_dual_fsr_pullup_wiring.kicad_sch` passes real KiCad
  10.0.6 ERC with zero violations. Netlist verifies independent A0/GND and
  A1/GND FSR channels; no external resistor or calibrated force claim.
- [x] SOL compiled `firmware/dual_fsr/dual_fsr.ino` after review of its actual
  approval preview. Build `bf8fe0b7-45c8-5164-9dcc-0ec4ccc8dcb1` retained the
  application HEX. This is compilation evidence, not flash evidence.
- [x] Actual connected CAD import of `SO_5DOF_ARM100_08k` at revision
  `741a055158f64b2b962e5ab5` renders in Live Bench. Adaptive tessellation retains
  all 19 leaves within the existing limits. UI correctly says NO LIVE MAPPING;
  this static geometry is not proof of verified joint animation.
- [ ] Select Follower in Workspace, then open Live Bench. Widget should display
  current named channels; retained stale Motor-N samples must not replace them.
  Stop streaming and wait beyond eight seconds: stale data must not claim LIVE.
  Simulate retrieval failure: widget must report unavailable, not an empty success.
- [ ] Before using external LeRobot, stop BOTH saved robot sessions in Manage
  connections. Exactly one process must own each arm port. Do not duplicate serial
  readers; external telemetry uses the controller's existing readings.
- [ ] Upload the reviewed sketch through the documented supervised Arduino IDE
  route, or finish and review exclusive-descriptor upload support. Current SOL
  upload deliberately refuses `device_ownership_unavailable`; do not bypass it.
- [ ] Use the external controller's optional paired `--fsr-port` and
  `--fsr-location` arguments with the verified Uno identity. Its strict reader
  accepts only bounded dual_fsr/version-1 packets and counts 0–1023. Secure login
  forwards these options without putting credentials in arguments or files.
- [ ] Press each follower sensor separately. Verify two independent raw-count
  channels change in the expected direction, alongside twelve joint channels.
  Test disconnect, malformed frames and reconnection without changing motor commands.
- [ ] With user supervision and verified ranges, test leader-to-follower motion.
  This physical motion test and the complete 14-channel acceptance remain unpassed.

Focused software verification: sensor integration 67 tests plus 21 subtests;
widget/main-pane suite 53 tests, scoped lint and renderer typecheck; adaptive CAD
37 tests with scoped lint/type checks. Fresh reviews passed for these scoped changes.
This does not claim the entire mixed feature branch passes its global quality gate.

## Telemetry responsiveness and manual firmware handoff

- [x] SOL's existing demo conversation contains successful `machine.write_file`
  and actual compile receipts for `firmware/dual_fsr/dual_fsr.ino`. A follow-up
  handoff now names Arduino Uno, A0/A1 internal pull-ups, 115200 baud and closing
  Serial Monitor. The user uploads in Arduino IDE; automatic upload is outside
  this demo's current acceptance path.
- [x] Connect both saved arms and open Live Bench. Each session uses the documented
  authenticated WebSocket; the main pane, embedded widget and scene share its
  samples. Readings should not wait for a 2.5-second poll or anomaly request.
  Live check: both session sockets accepted, twelve channels visible, focused
  follower widget LIVE, no steady-state telemetry HTTP reads/reopens/errors.
  Chart DOM changed three times over a 135 ms observation; movement latency is
  separately user-verified below.
- [ ] Move the leader by hand with no second controller. Record sample-to-display
  delay and confirm the follower and leader remain distinct. No automated motion
  is necessary for this check.
- [ ] Interrupt the leader USB connection. Its established six cards stay visible
  with stale/disconnected state; old readings must not be described as live.
  Follower readings continue. Reconnect the same serial identity and verify recovery.
- [ ] Delay/fail anomaly requests and external-device discovery independently.
  Current readings still render; known scoped inventory survives transient errors.
- [ ] Reorder discovery IDs without changing membership. Selection and charts do
  not reset. Change account/project: prior device data disappears immediately.
- [ ] Expired or foreign-project WebSocket authentication yields no data. Slow
  consumers cannot stall acquisition or accumulate an unbounded queue. Disconnect
  closes resources; reconnect never duplicates the serial reader.
- [ ] If WebSocket transport is unavailable, fallback is visible and established
  stale channels remain. No credential appears in a WebSocket URL or application log.

Runtime diagnosis: host kernel logged repeated USB disconnect/re-enumeration of
leader serial `5B42134331` around 01:59–02:04 on 2026-09-16. The user confirmed
manual movement with only Solus connected; a host port-owner check found only the
API process on both arm ports. UI stability fixes do not establish a repaired cable,
connector, USB power supply or other physical cause.
