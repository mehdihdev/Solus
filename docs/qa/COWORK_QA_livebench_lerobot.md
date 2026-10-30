# Cowork QA — Live Bench with a LeRobot SO-101 pair

Covers the SOLUSDEV-319 Live Bench work: lerobot-parity Feetech reads, steadier traces, an
imported SO-101 model per arm, per-robot panels, and leader → follower teleoperation
(ADR-014 amendment 2026-10-30).

## Setup

- [ ] Solus desktop running (`pnpm dev:all`), signed in, project **lerobot so101** open.
- [ ] SO-101 follower and leader plugged in over USB (serials `5B79050331` / `5B79049974`),
      both powered. Nothing else (including `lerobot-teleoperate`) has either port open.
- [ ] Saved robots **lerobot follower** and **lerobot leader** exist with lerobot calibration
      applied (each motor named `…-shoulder_pan`, `…-gripper`, etc.).
- [ ] The follower has an imported scene model **SO-101 follower** with all six joints mapped.

## 1. Calibrated readings

1. Live Bench → **Manage connections** → **Connect** next to _lerobot follower_, then _lerobot leader_.
   - [ ] Both rows read `streaming`; 12 primary cards appear.
   - [ ] Joint cards show `deg`, gripper cards show `%` — never `tick`.
2. Close Live Bench sessions (**Stop** on both), run
   a parity check: in a terminal, read both arms with lerobot's own bus
   (`SOFollower(SO101FollowerConfig(port=…, id="lerobot_follower"))`, then
   `bus.sync_read("Present_Position")`; same for the leader).
   - [ ] Every joint matches the Live Bench value to ±0.1° (gripper ±0.1 %).
3. Move the leader slowly by hand through each joint.
   - [ ] Values change smoothly and monotonically with the motion; no jumps of hundreds of degrees.
   - [ ] Rotate the wrist roll past its end of travel and back: the value continues past the end
         (small negative overshoot), never leaps to ~2800°.

## 2. Trace steadiness

1. Hold the leader still by hand (light tremor).
   - [ ] Sparklines stay close to flat — tremor of 1–2° does not fill the card height.
2. Sweep one joint back and forth for ~5 s.
   - [ ] The sparkline shape is stable frame to frame: peaks do not wander or flicker while new
         samples arrive.

## 3. Scene model

1. With the follower streaming, look at the Scene pane.
   - [ ] The SO-101 renders as solid geometry (not just dots and lines), labelled `LIVE` and
         `MAPPING CURRENT`.
   - [ ] The pose matches the physical follower (rest pose: folded down over the base).
2. Move the follower by hand (torque off) — pan, lift, elbow, wrist, gripper in turn.
   - [ ] Each model joint moves the same direction and roughly the same amount as the real arm.
3. **Pause** → move the arm → **Resume**.
   - [ ] The model freezes while paused and catches up on resume.

## 4. Failure paths

- [ ] Start `lerobot-teleoperate` first, then connect the follower in Live Bench: the session
      ends with a disconnected state (port busy); no garbage values appear. Stop teleop, reconnect:
      streaming resumes.
- [ ] Connect the follower in Live Bench first, then start `lerobot-teleoperate`: lerobot reports
      `Resource busy`. Stopping the Live Bench session frees the port.
- [ ] Unplug the follower USB while streaming: cards go stale, the session reconnects when replugged.

## 5. Robot panels (both arms connected)

1. Connect **lerobot follower** and **lerobot leader**.
   - [ ] Two panels side by side, titled with each robot's name, each with its own scene and
         its own six cards. Order stays fixed (by name) across reloads.
   - [ ] Each scene shows only that robot's model; each model matches its arm's pose.
   - [ ] One **Live reasoning** section below the panels (not one per panel).
   - [ ] Narrow the window below 1100 px: panels stack.
2. Also start a MuJoCo demo session.
   - [ ] The demo's signals appear in the original single layout below the robot panels.

## 6. Teleoperation — start gate (explicit confirmation)

Setup: both arms connected, follower limp, leader in a different pose from the follower.

1. The **Teleoperation** bar shows Leader = lerobot leader, Follower = lerobot follower.
2. Click **Teleoperate…**.
   - [ ] The dialog names both robots and lists six joints with leader value, follower value,
         difference and ✓/✗. Values refresh about twice a second as you move the leader.
   - [ ] Any joint more than 15 deg (gripper: 20 %) apart shows ✗, the text "Move the leader
         closer to the follower's pose" appears, and **Start teleoperation** is disabled.
3. Move the leader by hand until every row is ✓.
   - [ ] **Start teleoperation** enables.
4. Pick the same robot as both leader and follower.
   - [ ] The dialog shows a blocker ("Pick two different robots") and Start stays disabled.

## 7. Teleoperation — running

1. With every row ✓, click **Start teleoperation**.
   - [ ] The follower's torque comes on without any jump; the bar reads
         "Teleoperating lerobot leader → lerobot follower · 30 Hz" with **Stop**.
   - [ ] The follower's **Release…** button is disabled; the leader's is not.
2. Move the leader slowly through each joint.
   - [ ] The follower follows each joint, same direction; both panels' models move together.
   - [ ] Move the leader past a joint's limit: the follower stops at its own limit, no buzzing.
3. Move the leader fast.
   - [ ] The follower catches up smoothly (bounded speed), no violent snap.
4. Squeeze the leader's gripper fully; the follower's gripper closes on an object without
   stalling loudly (gripper protection is lerobot's — see Known limits).

## 8. Teleoperation — stopping

- [ ] **Stop**: the follower freezes in place and keeps holding (does not drop); the bar
      reads "Stopped — follower holding pose".
- [ ] Start again (new confirmation), then unplug the **leader** USB: within ~0.1 s the
      follower freezes and holds; the bar reads stopped with reason "leader lost".
- [ ] Start again, then **Stop** the leader's session in Manage connections: teleop stops
      ("session ended"), follower holds.
- [ ] Start again, then quit Solus: the follower holds its pose after the app is gone.
- [ ] With teleop stopped, **Release…** on the follower asks "Turn off torque on lerobot
      follower? It will go limp and may fall." Confirm: the follower goes limp. Hold the arm
      first if it is not resting.

## 9. Teleoperation — permissions and isolation

- [ ] A teammate with the **viewer** role sees the running state but gets no working Start,
      Stop or Release (403).
- [ ] From a different project, the follower cannot be released or paired while it is driven
      in this one.

## Known limits

- Gripper current protection (Max_Torque_Limit 500, Protection_Current 250) is whatever
  lerobot last burned into the servo; Solus does not set it. Run lerobot once on a new arm.
- The leader shows the follower's SO-101 model (no official leader model).
- The follower's elbow can be held short of the leader's (different calibrated ranges): it
  clamps at its own limit, by design.

## Cross-feature checks

- [ ] SOL live reasoning on the bench reports "Nothing out of range" at rest; no change-point
      flood while holding the arm still.
- [ ] The _Diagnostics_ drawer still lists load and temperature per motor.
