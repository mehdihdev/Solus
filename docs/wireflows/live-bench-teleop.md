# Wireflow — Live Bench robot panels and teleoperation (SOLUSDEV-319)

Governing decision: ADR-014 amendment 2026-10-30. Routes: API-implementation.md §15
"Teleoperation amendment".

## Robot panels

Each active session for a saved robot gets its own panel; two robots sit side by side
(stacked below 1100 px). A panel is the robot's scene (only that robot's imported models) above
that robot's signal cards. Sessions that are not saved robots (sim, raw serial, external devices)
keep the existing single panel below the robot panels. Panel order is stable: by robot name.

```
Live Bench                      [Pause] [● STREAMING] [Manage connections]
┌ Teleoperation ───────────────────────────────────────────────────────────┐
│ Leader [lerobot leader ▾] → Follower [lerobot follower ▾]   [Teleoperate…]│
└──────────────────────────────────────────────────────────────────────────┘
┌ lerobot follower ─────────────┐  ┌ lerobot leader ──────────────┐
│ scene (follower model)        │  │ scene (leader model)          │
│ 6 cards                       │  │ 6 cards                       │
│                    [Release…] │  │                    [Release…] │
└───────────────────────────────┘  └───────────────────────────────┘
```

The teleoperation bar appears when two or more robot sessions are active. Leader/follower
selectors default to robots whose names contain "leader" / "follower", else the first two.

## Start (explicit confirmation)

1. **Teleoperate…** opens a dialog naming both robots and a table of paired joints:
   joint, leader value, follower value, difference, ✓/✗ within tolerance. The table refreshes
   about twice a second (each refresh is a new preview).
2. Blockers (unpaired or uncalibrated joint, unsupported driver) are listed in plain words and
   **Start** stays disabled. A joint out of tolerance reads "move the leader closer to the
   follower's pose"; Start enables once every row is ✓.
3. **Start teleoperation** posts the current `preview_id` with `confirm: true`. On
   `409 teleop_not_ready` the dialog shows the fresh table; on `410` it re-previews.

## Running

The bar turns accent-coloured: "Teleoperating lerobot leader → lerobot follower · 30 Hz"
with **Stop**. Release buttons are disabled on the follower while running. Stop leaves the
follower holding its pose; the bar then reads "Stopped — follower holding pose" plus the reason
when it was not the user (leader lost, follower lost, session ended).

## Release

**Release…** on a robot panel asks "Turn off torque on <robot>? It will go limp and may fall."
Confirm posts `release` with `confirm: true`.
