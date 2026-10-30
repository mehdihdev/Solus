# Cowork QA — Live Bench with a LeRobot SO-101 pair

Covers the SOLUSDEV-319 Live Bench fixes: lerobot-parity Feetech reads, steadier traces, and an
imported SO-101 model that moves with the follower arm.

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

## Cross-feature checks

- [ ] SOL live reasoning on the bench reports "Nothing out of range" at rest; no change-point
      flood while holding the arm still.
- [ ] The _Diagnostics_ drawer still lists load and temperature per motor.
