# Wireflow — Live Bench shared view, derived signals and SOL bench changes (SOLUSDEV-319)

Governing decision: ADR-014 amendment 2026-10-31. Routes: [bench-view.md](../api/bench-view.md).
Extends [live-bench-teleop.md](live-bench-teleop.md) (robot panels and teleoperation are
unchanged). Every name, expression, plot group and window title shown here is team- or
model-authored data: rendered as escaped text, never as HTML or markdown.

## Layout

```
Live Bench                      [Pause] [● STREAMING] [View ▾] [Manage connections]
┌ Pinned ──────────────────────────────────────────────────────────────────┐
│ [Lift error  3.1 deg ▁▂▃]  [shoulder_lift.position  0.42 rad ▁▃▅]         │
└──────────────────────────────────────────────────────────────────────────┘
┌ lerobot follower ─────────────┐  ┌ Derived ─────────────────────────────┐
│ scene                         │  │ Lift error   3.1 deg      [⋯]         │
│ ┌ Shoulder (group) ────────┐  │  │ Grip load    —  (no data)  [⋯]        │
│ │ lift.position ── goal ── │  │  │ [+ Derived signal]                    │
│ └──────────────────────────┘  │  └──────────────────────────────────────┘
│ cards…        [Release…]      │
└───────────────────────────────┘
Hidden signals (3) ▸
```

- **Pinned** strip appears when at least one target is pinned; pinned cards sort by `order`.
- **Plot groups** render as one chart per group inside the panel of the group's first member,
  each member a line with its own legend entry; members keep their own unit when convertible.
- **Derived** panel lists every derived signal; a derived signal whose inputs are not streaming
  reads "— (no data)".
- **Hidden signals (n)** expands to a list with **Show** per row.

## 1. Display settings (member)

Each signal card and derived row has a **⋯** menu: **Pin / Unpin**, **Hide**, **Unit ▸** (only
units in the packet unit's family, as today), **Axis range…** (min / max inputs; "Auto" clears),
**Plot group ▸** (existing groups, **New group…**, **None**). Cards can be dragged to reorder
within the pinned strip or a panel; a drop sends one PATCH with the new `order` of each moved card.

1. The change applies optimistically; the PATCH carries the view version the client holds.
2. Success: the local version becomes the returned one. A small **Undo** toast stays 6 s and sends
   the returned `inverse_ops` (`undo: true`).
3. Validation refusals (too many groups, more than 8 in a group) show inline under the menu with
   the server's sentence and the card reverts.
4. The team view's unit replaces the earlier per-user unit choice; a user's local display name
   (rename) stays personal and is not shared.

## 2. Derived-signal editor (member)

**+ Derived signal** or **⋯ → Edit** opens a side sheet:

```
┌ Derived signal ───────────────────────────────────────┐
│ Name   [Lift error                ]                    │
│ Unit   [deg      ]                                     │
│ Expression                                             │
│ ┌────────────────────────────────────────────────────┐ │
│ │ sig("usb:5A7A/3", "shoulder_lift.goal")            │ │
│ │   - sig("usb:5A7A/3", "shoulder_lift.positon")     │ │
│ │                            ^^^^^^^^^^^^^^^^^^^^^^  │ │
│ └────────────────────────────────────────────────────┘ │
│ ⚠ No data yet for this signal (it may not be streaming)│
│ 23 / 64 nodes · 2 / 8 signals        [Insert signal ▾] │
│ Preview  ▁▂▃▅▃▂  3.1 deg                               │
│                              [Cancel]  [Save]          │
└────────────────────────────────────────────────────────┘
```

1. **Insert signal ▾** lists the streaming signals of this project (device and signal) and inserts
   a correctly quoted `sig("…", "…")` at the cursor; functions are offered the same way.
2. As the user types, the renderer's own parser (same grammar, same codes) underlines the span at
   the error position and shows the fixed sentence for its code (e.g. "Unknown function", "Too
   deep — at most 12 levels"). Save stays enabled; the server is the authority.
3. The live preview evaluates the draft on the streams already in memory; NaN shows as a gap.
4. **Save** sends `upsert_derived`. A 422 `expression_error` underlines the server's position and
   keeps the sheet open with the text intact; `duplicate_name` marks the Name field.
5. **⋯ → Delete** asks "Delete ‹name›? Charts that use it lose it." and sends `delete_derived`;
   the Undo toast restores it under the same id with its display settings.

## 3. A teammate edits the view

1. A `bench.view_changed` frame with a newer version arrives on the project stream; the renderer
   refetches `GET /view` and re-renders in place (no toast, no scroll jump). Frames with a version
   the client already has are ignored, so the user's own writes do not refetch.
2. If the derived editor is open on a signal the teammate changed or deleted, the sheet shows a
   banner "Changed by a teammate — Reload / Keep editing". Reload replaces the draft with the
   teammate's version; Keep editing keeps the draft, and its Save then gets 409 and follows §4.2.
3. After a stream reconnect (`ready` frame) the view is refetched unconditionally.

## 4. 409 conflict

1. A display gesture (pin, hide, unit, range, group, reorder) that gets 409 refetches the view and
   retries once with the same `set_display` patch on the new version (the patch sets absolute
   values, so it is safe to reapply); a second 409 reverts and shows "Bench view changed — try
   again".
2. A derived save or delete never auto-retries: the sheet stays open with the user's text and
   reads "A teammate changed the bench view. Reload to see it, then save again." with **Reload**.
3. An Undo that gets 409 is not retried (§5.3).

## 5. SOL changes the view

1. In a SOL turn, a direct view change (`bench_view.update_display`, `bench_view.upsert_derived`)
   renders as a **change chip** under the message:

   ```
   ⚙ Bench view · Created derived signal "Lift error"            [Undo]
   ```

   The Live Bench updates through the normal frame (§3); the chip text is Solus-composed.

2. **Undo** sends the chip's `inverse_ops` with its `version` and `undo: true`. Success turns the
   chip into "Undone".
3. 409: the chip reads "View changed since — Undo unavailable" and the button disables; nothing is
   written. Undo is likewise unavailable to a viewer.
4. In Guide mode SOL proposes instead of changing ("I'd pin these two signals…"); no chip.

## 6. SOL confirmation cards

All use the standard confirmation card (action-gate.md): one card per parked action, Solus-written
summary, rows, **Approve** / **Reject**, expired/stale/rejected states as for every card.

- **Delete derived signal** — rows Derived signal, Expression, Shown in.
- **Start session** — rows Action, Source, Mode, Robot/Device/Simulator, Window. Approval starts
  the session exactly as **Manage connections** would; the robot panel appears.
- **Stop session** — rows Action, Session, Provider.

## 7. Setpoint card

```
┌ SOL wants to move one joint ───────────────────────────────┐
│ Robot          lerobot follower                             │
│ Joint          shoulder_lift.position                       │
│ Current value  12.4 deg                                     │
│ Target         95.0 deg (requested 120.0 deg, clamped to    │
│                calibrated range)                            │
│ Motion         One move, at most 6 deg per tick; ends at    │
│                the target or after 5 s                      │
│                                     [Reject]  [Approve]     │
└─────────────────────────────────────────────────────────────┘
```

1. The clamp note appears only when the request was outside the calibrated range.
2. Current value refreshes nowhere on the card (it is the value at park time) and a change in it
   does not make the card stale; a change in the Target row (recalibration) does: "look again".
3. **Approve**: the robot panel shows "Moving shoulder_lift.position → 95.0 deg" with **Stop**
   (sends `POST /setpoint/stop`, never disabled), then "Reached", "Timed out after 5 s — holding"
   or "Stopped — holding". The joint never goes limp.
4. Refusals (at proposal or at approval) show as SOL's tool result in plain words, one per code:
   teleop_active "Teleoperation is running — stop it first"; follower "This robot is a teleop
   follower"; uncalibrated "This joint is not calibrated"; torque_off "Torque is off on this
   robot — hold it first"; not_connected "The robot is not connected"; unavailable "Robot control
   is only available in the desktop app's local bench"; in_flight "A move is already running on
   this robot".
5. The teleoperation bar's **Teleoperate…** stays usable; starting teleoperation stops an
   in-flight setpoint move first.

## 8. Viewer

A viewer sees the shared view (pins, hidden list, groups, units, ranges, derived signals and their
values) but every ⋯ menu shows only **Copy expression** (derived) and the Unit/Range/Group items are
absent; drag is off; **+ Derived signal**, Edit, Delete and Undo are hidden. SOL's write tools are
refused for a viewer (`unauthorized`) and its cards never appear.
