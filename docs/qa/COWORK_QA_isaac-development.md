# Isaac development QA — SOLUSDEV-261

## Setup

Use the SOLUSDEV-261 development build with API, companion and desktop running.
Connect a local workspace on the same Linux aarch64 machine as the installed
Isaac 6.0.1-rc7 runtime. Install the fork's hash-locked Python dependencies and
materialize its official SO-101 cache with the pinned manifest. Do not use a
hardware board, ROS bridge, telemetry connection, or Live Bench for this QA.

Create a project-scoped graph model with `attrs.simulation_model` exactly as in
`docs/api/isaac-development.md`: eight official links, six revolute joints, a jaw
contact sensor and bottle, each bound to distinct existing entities in this
project. Model closure digest:
`a1be9138359e044a007a4981817f3a8783fca47985b424f3fa9ca3d02e12b5b9`.
Use a disposable model/workspace. Fixture UUIDs in native logs are synthetic and
are not existing authenticated project entities.

## User flows

1. [ ] Ask SOL to probe Isaac. Expect observed installation/platform readiness and
   no process launch, GPU allocation, scene creation, or approval card.
2. [ ] Ask to start Isaac. Inspect the card: exact installed runtime, owned worker,
   private headless lifecycle and resource use. Deny first; no process starts.
3. [ ] Request again and approve through the actual UI. Expect a responsive owned
   session UUID only after native startup completes. Startup failure is an observed
   runtime failure; unsupported OS is described as unavailable on that OS.
4. [ ] Ask to load the graph model. Inspect every link/joint/sensor/bottle binding,
   units, asset identity and scene replacement. Approve and verify all eight links,
   six joints and contact sensor are present through status/readback.
5. [ ] Edit shoulder_pan limits to [-1,1] radians. Check old/new values in the card;
   approve and verify exact selected-joint readback. Other joint limits stay intact.
6. [ ] Move the jaw contact sensor 0.001 m in its parent's local X frame, quaternion
   [1,0,0,0]. Inspect frame/units and approve; expect readback within 1e-6.
7. [ ] Request `grasp_bottle` with all six explicit joint ranges and exactly three
   complete approach/close/lift waypoints, duration 6 seconds. Inspect full ordered
   targets, speed/step bounds, initial positions and current limits before approval.
   Expect at most 360 fixed steps, actual joint/contact/bottle readback and honest
   grasp result. A bottle outside the jaw must report no observed grasp.
8. [ ] Request stop; deny once, then approve a fresh request. Only the companion's
   owned session exits. A separately launched user simulator remains untouched.

## Failure paths and isolation

- [ ] Cross-project model root or nested link/joint/sensor IDs refuse before native
  calls. A model cannot substitute its own graph authorization context.
- [ ] Change a graph version or scene generation after preview. Approval must go
  stale; no automatic replay or replacement card that executes silently.
- [ ] Reject booleans/numeric strings/nonfinite values, unknown keys, arbitrary
  scene/URL/script paths, missing joint phases, out-of-limit or too-fast trajectories.
- [ ] Corrupt/remove a cache file or replace it with a symlink. Preview refuses;
  no silent download, repair, import or execution.
- [ ] Force import/readback failure after a successful model load. Subsequent
  edits refuse until a successful reload; no stale model identity survives.
- [ ] Disconnect companion or cancel during a routine. Stop the owned worker within
  its deadline; an uncertain write is clearly marked and not automatically retried.
- [ ] Switch projects while a session exists. No other project can see/control the
  old session; connection-generation cleanup must close the old owned process.

## Recorded native evidence (not product approval evidence)

`tmp/integration-check-isaac/physics-current.log` recorded NativeScene load,
shoulder limits [-1,1], sensor x=0.001000000047 m and a 360-step routine. Valid
contact reading was 0 N, bottle displacement approximately 0.0000002608 m, so
`grasp_observed=false`. Gravity produced final target error on some joints; do
not claim a successful grasp or perfect tracking.
`controller.log` recorded owned-pipe startup, a complete 26-row load preview,
actual import, model-root status readback and stop. These fixtures bypassed no
product gate: they ran explicitly as developer tests outside the product path.
No hardware, Live Bench, or successful physical bottle grasp was verified.

### Final developer fixture evidence

The owned Controller → worker → native Isaac pipeline was rerun with all four mutations (load, joint limits, contact-sensor pose, finite routine). Each returned an immutable revision, and all four JSON artifacts were read back with the expected graph model ID. The owned process stopped successfully. Evidence: `tmp/integration-check-isaac/controller-final.log`. The routine truthfully reported no observed grasp and incomplete target tracking; this is execution/readback evidence, not a successful bottle-grasp claim or product approval-flow verification.

Cancellation is fail-closed: cancelling an in-flight Isaac MCP request closes its
owned controller and terminates that owned simulator. Restart/reconnect the
companion MCP session before starting another simulator; cancelling does not
automatically replay the action or reopen the controller.

## Authenticated setup acceptance — 2026-09-12 follow-up

Home → Simulation → Add SO-101 model successfully created graph model
`01a098b2-7479-7ca5-9807-773e7ff58350` in Workspace W242 Service QA through the
new bounded authenticated route. A read-only database check confirmed its
simulation domain, simulation_model kind, and persisted official asset/link/joint/
sensor/bottle bindings. The setup did not launch Isaac.

Actual SOL probe observed Linux aarch64 availability. Its initial status call
failed at the MCP structured-result boundary; this live finding is being fixed
and must be re-run before claiming status or gated simulator execution passed.

Workspace navigation also passed: SO-101 simulation model appears as a simulation
root with 16 children. Zooming into it showed all eight official links, six joints,
Jaw contact sensor and Bottle, and the inspector reported 30 connections with an
Ask SOL action. These are the actual authenticated graph entities, not fixture IDs.

The final native/companion/cloud result path now uses structured MCP data and
transport-safe, strictly validated digest display. Native routine39rows plus the
combined cloud binding row fit the40-row card without dropping facts. Verification:
86native tests,36cloud adapter tests,16template API tests; independent transport,
security/code/Python/database review passed. After the final owned-stack restart,
a real SOL `isaac.status` returned ok with the stopped session state.

The subsequent approval request stopped because Solus Billing showed -6 credits.
No start approval card was created and no simulator process was started through
this product acceptance run. Model load/edit/routine approval and round trips
remain unchecked until the user replenishes credits and approves the cards.


## Calibrated physical grasp acceptance (2026-09-13)

This began as a native fixture proof; the live SOL replay below is now complete.
The final
unmodified ToolService run saved actual readbacks, used the reviewed complete
preview, and stopped its owned process. Evidence:
`tmp/integration-check-isaac/grasp-production-accepted-preview.log`.
The bottle rose 0.0375208557 m with bottle-specific force 8.29553 N during all
120 final hold steps. `targets_reached:false` and `grasp_observed:false` remain
correct: carrying joint error exceeded 0.01 rad. Do not describe this as meeting
all grasp criteria. Clearance alone intentionally has no bottle contact.

The importer uses the pinned unmodified asset with convex decomposition and
400/20 force position drives. Material and solver experiments are not part of
the production profile. Offline FK from the official joint origins agreed with
native link world positions within approximately 0.0000001 m. No unrelated CAD
transform or hardware material property was inferred.

1. [x] Start a fresh owned Isaac session through SOL in Build. Use the existing
   project graph SO-101 model; require actual start and model-load readbacks.
2. [x] Set its moving-jaw contact sensor local translation to
   `[-0.007,-0.073,0.019]` m and quaternion `[1,0,0,0]`. These coordinates come
   from the pinned jaw mesh. Require native pose readback and revision audit.
3. [x] Execute the explicit clearance routine below. All three waypoint phases
   use the clearance column; expect no grasp, and inspect actual tracking.
4. [x] Execute the explicit approach/close/lift routine below. Require all three
   phase snapshots, bottle-specific force, retention steps, final tracking error,
   saved revision and truthful `grasp_observed`. Do not retry a failed/uncertain
   command automatically. A held bottle with failed tracking is partial proof.
5. [x] Read status, then stop and confirm the exact owned session stopped.

Live SOL replay used session `d186a720-69b7-4ccd-8add-2f4ff78581cf`. Clearance
reached all targets, with no contact/grasp. Approach/close/lift read back
37.5209 mm bottle lift, 8.29553 N bottle-specific force and 120/120 retained steps.
Strict targets/grasp flags stayed false because shoulder-pan and elbow errors
exceeded 0.01 rad. Generation 4 saved; stop then status returned stopped and null
current session. These checked integration operations do not claim a strict grasp
pass. The complete-preview row-budget fix is `e1dc8b6b`; all timing and binding
facts remain in the preview under the unchanged 40-row limit.

Both routines last 30 seconds (1,800 physics steps). Each phase moves for eight
seconds and holds for two; no extra hidden steps. Use the exact graph UUIDs below,
all six joints, and the displayed pinned lower/upper ranges. The public argument
fixture is `tmp/integration-check-isaac/product-calibrated-acceptance.json`; add the
fresh session ID to each public call, never reuse a prior session ID.

| Joint / graph entity | Range (rad) | Clearance | Approach | Close | Lift |
|---|---|---|---|---|---|
| shoulder_pan / `01a098b2-7471-7863-9f08-f81086a031b8` | (-1.91986, 1.91986) | -0.8176855045 | -0.8176847984 | -0.8176847984 | -0.8176850459 |
| shoulder_lift / `01a098b2-7472-7946-87fe-383abdf12d87` | (-1.74533, 1.74533) | -0.5436591086 | 0.0020273862 | 0.0020273862 | -0.3320995930 |
| elbow_flex / `01a098b2-7473-77fc-94f3-74a69b63ea7e` | (-1.69, 1.69) | 0.5614839302 | 1.0405839924 | 1.0405839924 | 0.9769551797 |
| wrist_flex / `01a098b2-7474-7ebb-bb60-9dc1de7ed133` | (-1.65806, 1.65806) | -0.0178163855 | -1.0426025377 | -1.0426025377 | -0.6448469398 |
| wrist_roll / `01a098b2-7475-7a2e-b4f0-e285900badf1` | (-2.74385, 2.84121) | -1.5221150116 | -1.5221150623 | -1.5221150623 | -1.5221150319 |
| gripper / `01a098b2-7476-7861-8f5e-ac6d096ed5a9` | (-0.174533, 1.74533) | 0.9000000000 | 0.9000000000 | 0.4000000000 | 0.4000000000 |

- [ ] Missing/zero bottle impulse plus unrelated force must not count as a grasp.
- [ ] One failed contact/lift step during the final hold must fail retention.
- [ ] Cancellation must stop before another step, and cannot replay the routine.
