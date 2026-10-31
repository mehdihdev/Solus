# SOLUSDEV-262 — bounded runs and graph-grounded findings

Authority: SPEC§4, attached Phase4, ADR-014/017/026, telemetry-viz-out and sol-artifacts.
Routes under /api/v1/projects/{project_id}/bench; centralized ProjectCtx. All actions require
member role and verified identity. Unknown/foreign run/artifact/robot/session is404.

- POST /runs: {robot_id:UUID, session_id:UUID, name:string1..120}. Start capture from an active
  matching project robot session.201 envelope run summary. No motion or session start.
- POST /runs/{run_id}/stop: finish idempotently and file retained manifest;200 summary.
- GET /runs: bounded list (limit1..50,cursor optional), current project only. Newest creation first, with UUID as the timestamp tie-breaker. The UUID cursor resolves a current-project run; missing, foreign, deleted or unrelated cursors return 404.
- GET /runs/{run_id}: immutable manifest for completed run or explicit running/interrupted state.
- POST /runs/import: {robot_id:UUID, artifact_id:UUID, name:string1..120, origin:recorded|synthetic}.
  Read bounded uploaded run manifest; validate IDs/units/counts; never native paths.201summary.
- POST /runs/compare: {baseline_id:UUID,candidate_id:UUID,sim_result_id?:UUID};200 deterministic
  comparison, same project and robot identity, aligned elapsed time and compatible units. No
  modelrequired. `sim_result_id` (optional; amended in P4-T5 fix 1, R117) names a trajectory
  simulation of the routine: the twin's run built from it replaces the baseline, which is resolved
  but not compared (see "Comparing against a simulation"); one that is not a live `sim_result` of
  this project under the person's read scope is 404 `not_found`.
- GET /runs/{run_id}/findings:200 evidence-grounded cards and explicit insufficiency reasons.
- POST /runs/{run_id}/narrate: optional batched cheap-tier narration through existing metered
  gateway (TRIVIAL/GENERAL); no finding creation or altered numeric evidence; deterministic
  fallback when unavailable. Existingbudget/rate/auth checks apply.

Run summaries include id, robot/session IDs, name, origin(live|recorded|synthetic), status
(running|completed|truncated|interrupted), start/end timestamps, packetcount/dropcount, artifact
reference when filed, and `baseline` (see Baseline).
Manifests schema_version1 contain captured timestamped numeric packets,
sensor artifact references with timestamps, accepted part/device mapping and CONFIG/source/code/
CAD revision snapshots. Require finite values, bounded identifiers/strings, strict unknown-field
rejection, at most10000packets/10000sensor references and8MiB serialized manifest, at most4active
runs perproject. Bounds terminate visibly as truncated; never silently call a partial capture whole.

Capture subscribes to the shared ingest seam before recent-buffer reduction. Work perpacket is
bounded; serialize/persist off request/ingest hotpaths in owned bounded tasks. Start persists a
graph run record. Checkpoints persist captured progress periodically; process loss surfaces
interrupted status and exact lastpersisted count, never completed. Stop creates immutable artifact
and uses existing .solus filing to retain it; no global TTL change. Audit identifiers/countsonly.

Analysis uses measured current, observed position, commanded target and explicit graph rating/
configured range. Load-percent is neveramperes; absent current/rating/command yields insufficient
evidence ratherthan inventedstall. Findings name acceptedpart, code/CAD context only when
snapshotted, and numerical evidence. Comparison separates config/source changes from observed
signaldivergence and asserts clampattribution only when supported. Imported recordings remain
user-declaredrecorded orsynthetic, notverifiedlive. Modeloutput isboundeduntrustedprose and cannot
change deterministicfindings, identities, numbers, scope or execute actions.

## Baseline

- POST /runs/{run_id}/baseline: no body. Marks the run as its robot's baseline (`attrs.baseline`),
  the run whose measured percentiles become the learned bounds of the part envelopes
  (`livebench/findings/envelopes.py`). One baseline per robot: marking a run unmarks the robot's
  previous baseline, and marking the baseline again changes nothing. 200 run summary. Same auth as
  every run route (member, verified identity); an unknown, foreign or deleted run is 404, and a run
  still running is 409 `run_active` (stop it first: a checkpoint rewrites the run record).
- Every run read (the list, GET /runs/{run_id}, this route, the `get_run` tool) carries
  `baseline: bool`, true for the run its robot's envelopes are learned from. It is read from the
  record's `attrs.baseline`; the saved summary never carries it.

## Findings on a run (SOLUSDEV-321 P2-T7)

- **The manifest's `findings`.** An optional list, `[]` by default, so every manifest recorded
  before it still loads; GET /runs/{run_id} serves it with the rest of the manifest. At most 64
  entries, each a graph finding (docs/api/findings.md) that the run's bench session raised while
  the run captured:

  ```text
  {finding_id, rule_id (1..128), subjects (sorted ids, at most 64),
   severity (info | warning | critical), count (>= 1), first_seen, last_seen}
  ```

- **What a capture records.** Each checkpoint and the final stop record the findings where:

  - `evidence.session_id` is the run's session;
  - `last_seen >= started_at`;
  - `first_seen <= ended_at`, or now while the run is still capturing.

  A finding counts whatever its status is now; one dismissed or resolved since was still raised
  during the run.

- **How they are read.** Through `list_findings` on the run's robot, every status, newest first.
  A status stops at the page whose last row was touched before the run began, since a finding's
  `last_seen` never runs ahead of its `updated_at`.
- **Bounds.** The packet budget keeps 32 KiB back for findings. A run whose findings outgrow what
  is left, or number more than 64, keeps the most recently seen that fit, and the trim is logged.
- **Imports.** An imported run has no bench session and records none. An imported manifest's
  findings must name this project's finding and subject ids: anything else is 404, like every other
  reference.
- **Compare's `finding_deltas`.** POST /runs/compare adds:

  ```text
  finding_deltas: [{rule_id, subjects, change: new | cleared | persisting, severity,
                    baseline: {finding_id, count} | null,
                    candidate: {finding_id, count} | null}]
  ```

  - Findings match on `rule_id` and the sorted `subjects`, never the id: a finding's id belongs to
    one bench session, so one condition seen in both runs is two ids.
  - `new` means only the candidate saw it, `cleared` only the baseline, `persisting` both.
  - The order is new, then cleared, then persisting, then rule and subjects.
  - `severity` is the candidate's when it has the finding.

- **Compare's `expected_source`.** `baseline_run | definition | sim`: what the candidate is
  compared against. It is `sim` when the baseline is a twin's run (below), and `baseline_run`
  otherwise. `definition` is for comparing against a part definition, which nothing does yet.

## The simulation as the control (SOLUSDEV-321 P4-T5)

A run whose snapshots carry a `sim_result` (a `RevisionSnapshot` of kind `sim_result` naming the
result's id) is the twin's run of its routine. An imported run carries one like any other snapshot,
and the import's reference check holds it to a live `sim_result` of this project: a marker naming
any other entity is 404 (P4-T5 fix 1). The marker names a simulation, not a source, so
`source_snapshots_changed` compares the two runs' snapshots without it. When exactly one of the two
runs compared is the twin's, POST /runs/compare adds `evidence`, reading the other, the real one,
against it. Two real runs, or two twins, have no real run to read against a twin, and compare's
result keeps its shape. It reads only what the two manifests hold and calls no provider (R98):

```text
evidence: {sim_result_id, real_passed, sim_passed, task_passed,
           sim_control: electrical_or_mechanical | software | policy_or_perception | consistent | null,
           reason: null | <why there is no label>, simulation_gap: bool,
           residuals: {<part id>: <residual_attribution's result>}}
```

- **A run passed or failed.** It failed when it shows a stall (the run's own findings) or raised a
  warning or critical finding. It passed when the stall check judged a part of it and it did
  neither. Otherwise it says nothing (`null`), and there is no label: `reason` names which run said
  nothing.
- **The task.** `task_passed` is whether every commanded part ends within its unit's tolerance of
  its command (rad 0.01, deg 0.5, m 0.001). A run that passed had a part judged, so its task is
  known.
- **The label** is `classify_sim_control(real_passed, sim_passed, task_passed)`
  (`livebench/findings/sim_control.py`). Read it with the gap (M80): `simulation_gap` is
  `simulation_gap(real_passed, sim_passed, sim_covers_fault)`, and the twin covers the fault when
  the same stall check judged, in the twin's run, a part that stalled in the real one. A raised
  finding is never counted as modelled, since the manifest does not say what it read.
  `electrical_or_mechanical` beside a gap is a twin that models the fault and missed it: suspect
  its model first, and the residuals say what in it. A twin that failed where the robot passed is
  its own model being off, never a fault label: `consistent` or `policy_or_perception` with
  `sim_passed: false` beside it.
- **The residuals.** Each part both runs observed, in one position unit, judged by
  `residual_attribution` with the twin's positions as the expected motion and the real run's as
  the observed (below).

### Comparing against a simulation (amended in P4-T5 fix 1, R117)

POST /runs/compare with `sim_result_id` reads that one entity: a live `sim_result` of this project
under the person's read scope, which is also the kind check (another project's id, or an entity of
another kind, is 404 `not_found`). The baseline is resolved as without it (a run of this project,
not still recording) and then **replaced** by the twin's run built from the simulation: it is not
compared, so its robot is not checked against the candidate's (amended in P4-T5 fix 2, R120). The
candidate, the real run, is read against the twin as above, so `expected_source` is `sim` and
`evidence` names that `sim_result_id`. Without `sim_result_id`, compare answers exactly as before.
`compare` itself is unchanged (R98): the twin is built first, by the pure
`livebench/runs/analysis.py:twin_run(sim_result_attrs, real, joint_of, sim_result_id=)`:

- **What it lays out.** A rung-3 trajectory `sim_result` records the routine
  (`provenance.inputs.trajectory`, `{joints, points: [{t, positions}]}`), the motion it simulated
  (`expected_trajectory`, `{t, positions: {joint: [...]}}`) and the current it expects
  (`expected_current_a`, `{joint: [...]}`). Each part of the real run that the project's scenes
  bind to a joint (`livebench/scene/part_bindings.py:scene_joint_for_part`) gets, at each recorded
  sample from the real run's start, that joint's position, its expected current (A) and the
  routine's command linearly interpolated (as the simulated actuators follow it), under the
  part's own position, current and command signals, in its own position unit (`rad` to `deg`).
- **What it leaves out.** A part bound to no joint the simulation recorded, whose position unit
  does not convert from the joint's (a slide in `m` is no joint in `deg`), or whose recording is
  malformed. A simulation that is no routine's recording lays out no part, and the evidence then
  says the twin's run states nothing. A stored shape is never trusted: at most 256 samples within
  an hour are read, and a twin carries at most `MAX_PACKETS // 256` (39) parts.
- **What it carries.** The real run's robot, start and snapshots, and the `sim_result` marker;
  no findings and no sensors.
- **Deferred.** The Runs view does not yet offer "compare against the simulation", and a Sim-mode
  bench capture is not a twin: making one would need a "simulated telemetry" marker, never an
  invented `sim_result` (M152).

## Residual against a simulation (SOLUSDEV-321 P4-T4)

`livebench/runs/analysis.py` judges what a run measured against what a `sim_result` expected: the
`expected_trajectory` the trajectory job records (`provenance.inputs.expected_trajectory`,
`{t, positions: {joint: [...]}}`, docs/api/simulation.md §7). It is pure and deterministic, and
it calls no model. `compare` judges each part a real run shares with its routine's twin this way
(P4-T5, "The simulation as the control").

- **`residual_attribution(expected_t, expected, observed_t, observed)`** judges one joint. Both
  series are resampled onto `RESIDUAL_SAMPLES` (256) points of the time they share, so the work is
  bounded whatever the rates. The residual is observed minus expected, in the trajectory's unit.
- **The grid.** Each parameter's forward model is tried at `GRID_STEPS` (33) values over the
  expected motion:

  | Parameter       | Model of the measured motion                                                     | Grid                                                 |
  | --------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------- |
  | `mass`          | a first-order lag of tau: a heavier or lighter link than the model's tracks late | tau from a thousandth to half the motion, log-spaced |
  | `limit`         | a clip, as a ceiling and as a floor                                              | levels inside the expected range                     |
  | `sensor_offset` | a constant shift                                                                 | over the residual's own reach                        |
  | `contact`       | the motion held where it was from a moment on                                    | moments inside the shared time                       |

- **The attribution.** Each parameter's best try is scored by the share of the residual's energy
  it explains. The best parameter is named when it explains at least `ATTRIBUTION_MIN` (0.8) and
  leads the next by `ATTRIBUTION_MARGIN` (0.1). A residual of two causes at once is then
  `unattributed`, never forced onto one, and ties go to the parameter listed first.
- **The result**: `{status: attributed | unattributed | consistent | insufficient, parameter,
explained: {parameter: share}, estimate: {parameter: the best try}, residual_rms, samples}`. It is
  `consistent` when the residual's RMS is within `CONSISTENT_FRACTION` (a hundredth) of the expected
  motion's span. It is `insufficient`, with the reason, when the series share no time, a series has
  fewer than 8 samples, a sample is not a finite number, the times do not increase, or there are not
  as many times as values.
- **`run_positions(run, part)`** reads a part's measured positions from a run manifest: seconds
  since the run started, and each position converted to the part's own position unit. A packet
  without the position, or in a unit that does not convert, is skipped.

## Replay provider (dev only)

`POST /sessions` (docs/api/API-implementation.md §15) takes one more real-mode provider, so the
Live Bench pane and the robot session's window evaluator (docs/api/findings.md §5) can be driven
from a recorded capture with no hardware. It is a development tool: it reads a file from the
server's disk, so it is off until `Settings.bench_replay_root` (env `SOLUS_BENCH_REPLAY_ROOT`,
unset by default and in every deployed environment) names the directory the captures live in.
The root is server-wide, as `bench_data_root` is: every project on this server can replay every
capture under it, as one of its own robots that has the capture's transport identity. There is no
UI for it, and `GET /sources` does not list it.

    {"mode": "real", "config": {"provider": "replay", "recording": "serial_fake_arm_stall.json",
      "driver_id": "lb06", "robot_entity_id": "<uuid>", "realtime": true, "window_seconds": 1.0}}

- `recording`, 1 to 4096 printable characters: a path under the replay root, relative to it or
  absolute. It is resolved (symlinks followed) and must lie inside the resolved root, name a
  `.json` regular file of at most 32 MiB, and read as `livebench.hardware.replay.load_recording`
  does: `{transport, binding, frames: [{t, hex}]}`, at most 100,000 frames of 64 KiB. The size is
  checked at the route, and the runner's read is bounded by the same cap (the route hands it
  over as `max_bytes`), so a file grown after the check is refused, not read whole.
- `driver_id` (`[a-z0-9][a-z0-9._-]{0,63}`): the driver the capture is decoded with. It replaces
  the robot's configured protocol for this session, with that driver's default parameters.
- `robot_entity_id`: the project's Physical Robot the capture is replayed as. Its config supplies
  the transport identity, bus map and parts, so the capture's lines reach the robot's parts
  exactly as a live robot's would (part routing, the session tap, the evaluator). The capture
  must have been recorded from the robot's own transport identity: another device's recording is
  refused, never relabelled onto this robot's parts.
- `realtime` (default true): frames are paced by their recorded `t`; false hands them over as
  fast as they are read, and the server's in-memory buffer keeps only the last 512 samples a
  channel (about 25 s at 20 Hz), so a long capture replayed that way is judged on its tail:
  false is for short captures and for tests, which release a capture in slices.
  `window_seconds` as for every provider.
- The capture opens on a scratch transport registry of its own, with reconnect off: it never
  touches the process-wide transports and a replay does not restart itself. When the capture
  ends, in either mode, the session stays active and silent, as a live link with nothing to say
  does: the channel then waits one quiet read (50 ms) for every read, so the session polls it
  about 20 times a second, and `stream_gap` is told about a second later. Stop it as any session.
- The session record is `provider: "replay"`, `mode: "real"`, `robot_entity_id`, and a `device`
  of `{device_ref, driver_id, replay: true}`: no `serial_number`, `device_path` or `baud` field.
  `device_ref` is `usb:<serial>`, but the desktop matches a session to a physical device row by
  `device_path` or `serial_number`, so a replay is not taken for the device it was recorded from.
- Errors, in the order they are checked: `503 source_unavailable` with no runner or with the
  replay root unset (for every body); `404 not_found` for a robot that is not a live Physical
  Robot of this project, another team's included; `422 validation_error` for a path that escapes
  the root (`..`, a symlink out), that cannot be resolved (an embedded NUL, a symlink loop), is
  not a `.json` file, is not a regular file (missing, a directory, a pipe) or is over the size
  cap, and for a robot whose config names no transport identity; `409 too_many_sessions` as for
  every provider (the session cap is checked before anything is opened); then the runner's own
  refusals as it opens the capture, each a `422 validation_error` with a fixed message that
  never echoes the file's text or its place on the server: a capture recorded from another
  device, an unknown driver, a capture that does not parse or is over the size cap when it is
  read, and a path that is no longer its own resolved path (a swap after the route's check; a
  symlink loop swapped in is the same answer). Any other failure to open is
  `503 source_unavailable`; the route logs it with `logger.exception` (the exception's message
  and traceback, as for every provider), whereas the replay path's own refusals log the
  exception's type only. Client errors are 422 here, as for every bench-session validation;
  there is no 400.
- The path confinement is the one `mcap-replay` uses for `bench_data_root` (same checks, same
  words); an unusable path is now a 422 there too, where it was an unhandled error.
- Data event: `bench.session_started` with `provider: "replay"`.

The acceptance capture, `livebench/tests/fixtures/serial_fake_arm_stall.json`, is one synthetic
six-servo arm (the fake arm of `packages/api/tests/fixtures/fake_arm.py`, no vendor named)
generated by `make_fake_arm_stall.py` beside it. A minute at 20 Hz, five channels a servo:
servo 3 stalls at 5 s (position held, command away, current over the rating by 6 s), the shared
rail sags at that peak, servo 3 runs hot from 10 s toward its limit, servo 5's position sensor
freezes at 30 s, and servo 2 stalls at 40 s.
