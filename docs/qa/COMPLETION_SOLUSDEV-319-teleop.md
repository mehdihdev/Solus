# Completion report — SOLUSDEV-319: Live Bench robot panels + leader → follower teleoperation

Branch `SOLUSDEV-319-kicad-embedded-symbol-compare` (user's choice), commits a1664e80..HEAD,
unpushed. QA plan: `docs/qa/COWORK_QA_livebench_lerobot.md` §5–9.

## What was built

- **Per-robot panels.** Each active saved-robot session gets its own panel (its scene models +
  its cards), side by side; non-robot devices keep the original layout; live reasoning shows
  once over every robot. Sessions now carry `device.robot_entity_id`.
- **Teleoperation.** A user pairs a leader and a follower robot. A dialog previews every joint
  live and enables Start only when each is within tolerance; the follower holds its pose, then
  mirrors the leader in bounded, range-clamped steps at 30 Hz. Stop holds; Release (separate,
  confirmed) turns torque off.
- **Actuation seam.** Drivers may expose an `Actuator` (Feetech STS today) over the bus their
  polling source owns; bus exchanges are locked and writes wait for the servo's ack.

## Governing documents

- DECISIONS.md ADR-014 amendment 2026-10-30 (approved in chat, committed alone: a1664e80).
- docs/api/API-implementation.md §15 "Teleoperation amendment" (tier-1, written before code,
  updated with review fixes).
- docs/wireflows/live-bench-teleop.md (new, tier-1).

## Decisions taken in chat

Branch: stay on 319. On stop: follower holds its pose (release is a separate action). Layout:
two panels side by side. ADR text: approved as written.

## Delegated-judgment decisions

- Joints pair by bus address; tolerance 15 deg / 20 %; max step 68 ticks (~6 deg) per tick;
  three consecutive missed leader reads stop it; a single failed follower write stops it (spec).
- Previews are single-use with a 30 s TTL; one teleop per project; a physical robot can be in
  only one teleop across all projects.
- Rate limits: 240 previews/min, 60 starts+releases/min per user; Stop is never limited.
- The leader uses the follower's SO-101 model (no official leader model exists).

## Tests

livebench 764 passed (new: lb_teleop_test, lb_feetech_actuator_test, lb_actuation_test, local
bridge tests); API: test_teleop_router (29) + bench/hardware suites green on a private test DB;
desktop bench + api 615 passed. All written test-first (red runs recorded in the session).

**Hardware (real SO-101 pair):** preview refused 58–122 deg apart; after alignment, confirmed
start → follower tracked within 0.4 deg (elbow at its own limit) with no hunting; Stop held the
pose; Release went limp. Repeated after the review fixes. Not exercised on hardware: moving the
leader by hand during teleop, unplugging the leader (leader_lost) — both in the QA plan.

## Phase 4 reviews

Code + security review findings fixed (3f31b87e, 5141c036, 494555fc; earlier fc6d4439 from the
automated review): mode-mismatch pairing, untrusted calibration ranges, release/start race,
start-time stops, out-of-range first tick, failure attribution, stop waiting for in-flight
writes, rate limits, logging ids, stale previews, Stop always reachable, shared scene scope.

## Open concerns / deviations

- **SOL command path (security L4, not fixed here):** SOL's approved `curl` could reach these
  routes only under dev-bypass auth. Adding a deny pattern touches SOLUSDEV-317's human-gated
  command policy — flagged for a human.
- **Two sessions on one arm** share an actuator handle; prevented in practice by the exclusive
  serial open (flock), not by the session manager.
- **Stop event without start event** when a session ends during the start (the route returns
  404 after the loop briefly ran). Accurate, but unpaired in the data stream.
- **Gripper protection** (current/torque limits) is whatever lerobot last burned in.
- **Pre-existing flaky test:** `lb_detection_test::...micropython_sketch` compares a measured
  stream rate as an exact string (fails at 51 Hz under load); unrelated, not changed.
- **Hook H9** prints a vitest `--silent` parse error on every TS edit (known harness gap).
- The test stack runs from a detached `main` worktree (`/Users/mehdihdev/Solus-lbtest`) because
  the dev DB is on main's schema; applying many-file patches there crashed the Electron renderer
  twice (a CDP reload recovered it; a clean load is fine).
