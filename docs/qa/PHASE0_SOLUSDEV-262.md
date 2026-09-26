# SOLUSDEV-262 — Phase 0 baseline

Date: 2026-09-14. Branch: `SOLUSDEV-262-livebench-robo-sol-initial`.
Starting commit: `2ffbf8b8`. Initial worktree clean. User explicitly authorized autonomous
review, implementation and local phase commits; physical actions outside the Uno exception
remain read-only. No hardware was flashed or commanded to move.

## Governing material and design review

Read root AGENTS.md, hardware-onboarding architecture, hardware wireflow, destructive-action
contract/decide route, telemetry-viz-out architecture, the 251 premerge review and 260
completion report. Consulted Arduino preparation API and existing runtime implementations.
`docs/design/SPEC.md` contains CI YAML, not the requested sections 2–5. The attached
brain-centric onboarding/W5/L1–L5/S4 request supplies the new requirements; existing documents
supply preservation/security constraints. No replacement SPEC content was invented.

Critique: category-only containment, root-owned connection attempts, missing production flash
tool, and absent scene/run surfaces make this a coordinated migration rather than a UI rename.
One host controls two separately owned arms: keep one host entity, distinct physical topology
edges, and per-robot tree projections. Do not duplicate host identity or confuse physical
connectivity with ownership. Unknown firmware state cannot be established from VID/PID alone;
no response does not prove an MCU is empty. Raw analog readings on floating pins are not proof
of attached devices. Probe evidence must retain those limits.

Suggested execution order: validate topology shape and tier-1 documents; preservation migration
and traversal; extractor adapters; presence/deployment through existing gate; W5; L1–L3;
L4–L5; S4; full verification. No protected-contract change has been shown necessary.
The user delegated routine interpretation; live-only prerequisites are recorded, not approval pauses.

## Runtime and database

Host inspection was necessary: the sandbox hides physical USB devices and host listeners.
`lsof` ran before any proposed binding. No app server was started and no pre-existing process
was stopped. API 8000 and renderer 5173 were not listening. Existing Docker services include
`solus-db-1` on 5432 and `solus-redis-1` on 6379. Other gateway/monitoring services occupy
8080, 3000, 9090 and 9835; they were left alone.

Database `solus`: revision `a26100000001`; 2,640 total graph entities. Current source has one
Alembic head, also `a26100000001`. Live nondeleted kinds include 19 physical robots, 133
robot categories, 128 hardware configs, 13 motors, 2 code repos and 5 KiCad projects.
No rows were changed. No migration was applied.

Custom-format `pg_dump` saved before any migration:
`tmp/backups/SOLUSDEV-262-phase0.dump`, 838,452 bytes, mode 0600 in ignored mode-0700 directory.
SHA-256: `d2c96ad90b871e5f799c38e76111e3721af42a7dcaf2fd32d6b70d84491768b4`.
`pg_restore -l` validated its table of contents (407 lines). This is archive validation,
not a restore rehearsal. Snapshot contents remain private and untracked. The first listing
attempt omitted Docker stdin forwarding and failed; retry with `docker exec -i` succeeded.
Environment files were not edited or printed. Host lacks standalone pg_dump/psql; container
tools supplied them. ForgeTS checkout exists; its expected top-level Simulation directory
was absent during this inspection.

## Current bench evidence

| Expected item         | Current observation                                                           | Interpretation                                                            |
| --------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Follower driver board | USB serial `5B42134331`, VID:PID `1a86:55d3`, `/dev/ttyACM0`                  | Unique serial identity; USB bridge identified, MCU unknown at enumeration |
| Its servo bus         | Existing interrogator: six STS3215 responders, addresses 1–6, confidence 0.92 | Protocol/model-register evidence, not permission for motion               |
| Leader driver board   | Historical serial `5B42135040` absent from current enumeration                | Needs connection/power check; previous report is not current evidence     |
| Uno                   | No Uno enumerated; no verified serial or VID/PID                              | No QA allowlist configured, no probe or heartbeat flash                   |
| Host                  | This checkout and ForgeTS repo accessible                                     | Host-brain graph integration is not implemented or verified               |

Existing `livebench.local.detect_devices()` reported the visible board as transport-level
“something on USB”, board class `usb_bridge`, `mcu_known=false`, confidence 0.3.
Existing `FeetechBusInterrogator` upgraded evidence to six model-register responders and read
homing offsets. The exact enumeration, calibration signature and 30 register samples are in
`SOLUSDEV-262-readonly-baseline.json`. Five sweeps read position/load/temperature for each
address. Access used unique serial resolution, exclusive open, bounded timeouts, only PING/READ,
and closed the channel in finally. No torque, goal-position, calibration or flash write occurred.
Samples are raw registers with UTC timestamps, not LB-06 ingest acceptance evidence, a motion
run, stall data, or proof of synchronized multi-sensor capture.

## Implementation inventory

| Area      | Existing implementation                                                                                                                           | Required extension                                                                                |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| R1–R5     | livebench hardware registries/detection/channel/driver/interrogator/repo_config, plugins; API hardware store/detect/library; v2 per-entity CONFIG | Brain topology, unified extraction adapters, preserve identity/config migration                   |
| Ownership | physical_robots service; hardware ownership/runtime/bindings/connections                                                                          | Category-only traversals and root connection assumptions need coordinated replacement             |
| 250 UI    | Canvas-edge PendingDeviceCards, Add Hardware panel, sidebar, explicit names and acceptance                                                        | Brain cards/tree and category filter chips                                                        |
| W5        | widgets/graph_nodes creates workspace/bench/installed-widget entities; hardware links/API/sidebar suggestions                                     | Verify root rendering; evidence-set decline memory; CAD evidence and requested attach affordances |
| 252/S4    | SOL window, global Ctrl+Space action mode, Guide/Build labels, gate-aware modes                                                                   | Wire enum still do; surface-aware Guide integration; strict execution semantics                   |
| LANE D    | GuidePanel, overlay host/session/renderer and handoff have tests                                                                                  | GuidePanel and overlayHandoff have no production callers in inventory                             |
| L1        | Active-session device panels and batched polling                                                                                                  | Brain-fed inventory and honest no-focus empty flow                                                |
| L2        | MuJoCo/Gazebo/MCAP runtime sources, simulation graph templates                                                                                    | In-tab viewer, namespaces, persisted placement, confirmed joint maps and revision updates         |
| L3        | Values, rolling charts and stale states                                                                                                           | Independent signal widgets, persisted names, unit conversion, camera/LiDAR alignment              |
| L4        | Threshold/CUSUM/gap observers, checker library                                                                                                    | Rated-part/code/CAD stall attribution and bounded narration                                       |
| L5        | MCAP ingestion/export/replay, ephemeral rings                                                                                                     | Durable run capture/snapshot, comparison, graph attribution, scrub UI                             |
| Routines  | Gated Isaac-specific run_routine                                                                                                                  | No generic bench robot routine runner                                                             |
| Flash     | Standalone callback-gated deploy/flash primitive and Arduino runner; owned Code prepare/compile                                                   | No registered production flash_device SOL tool; live decide integration must be built             |

Link suggestion persistence deduplicates pending pairs only: rejection does not currently
suppress the same evidence on the next proposal. No fix is claimed in Phase 0.

## Recorded data inventory

No tracked MCAP/bag/db3/jsonl captures were found in the inspected worktrees. LANE H fault
drills synthesize disconnect/frequency changes, not recorded stalls. The existing three-machine
MAVLink/CAN/raw-serial recordings are deterministic fixtures; classify them as fixtures despite
“recorded” naming. This session's new follower capture is real read-only baseline data, with
no induced fault. Historical 260 prose is not a replayable run.

## Baseline verification

- 32 tests passed: vendor hygiene, existing three-machine proof, servo interrogator and driver.
- Destructive dispatcher ratchet: 1 passed, 23 deselected.
- Single Alembic head: `a26100000001`.
- Sandbox fixture run stalled; stopped only that owned process. Bounded host rerun passed in 1.85s.
- No new capability extension or full-suite pass is claimed here.
- QA helper verification and final status are recorded in COMPLETION_SOLUSDEV-262.md.
