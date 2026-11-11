# Isaac external execution — SOLUSDEV-261

## Runtime configuration cleanup — 2026-09-24

The machine-owned `SOLUS_ISAAC_RUNTIME` environment setting selects the installed
Isaac runtime directory. The companion explicitly passes only this setting to the
Isaac server, whose launcher preserves it through its otherwise closed environment.
It is never a tool argument or project model attribute. Missing, relative or invalid
paths report runtime unavailable; no developer-machine fallback is used. The controller
captures the configured root, validates required runtime files, and includes their
identities in its existing approval fingerprint. Its fixed worker receives the root
as an internal bootstrap argument; inherited Python/library/extension settings remain
excluded. Platform capability is observed rather than assuming ARM64 hardware.
The existing vendor API adapter still requires live validation on each supported
installation; this change does not claim Windows support for its POSIX launcher.

## Application connection status (UI Phase 4)

`GET /api/v1/projects/{project_id}/isaac/connection-status` requires centralized
project authorization. It observes only `isaac.probe({})` and `isaac.status({})`
through the existing cloud-owned Isaac wrappers and exact user/team/project bridge.
It never starts, stops, loads a model, runs physics, or changes the graph.
Each read has a six-second deadline. The per-user/project budget is 20 requests
per minute; excess returns 429. Both observations share one captured bridge session;
replacement/disconnection before completion discards all observations.

The envelope's data is `{bridge:"connected"|"unavailable",
installation:"installed"|"unknown",owned_session:"running"|"not_running"|"unknown",
streaming:"none",reason:null|"bridge_unavailable"|"capability_unavailable"|
"observation_failed"|"runtime_unverified"}`. No raw paths, logs, platform model,
fingerprints, graph IDs, or tool payloads are returned. Probe `available:true`
establishes installation; false cannot distinguish absence from unsupported or
incomplete installations and therefore remains unknown. Status describes only the
owned session, not independently launched applications. No telemetry capability
exists on this connection, so streaming is explicitly none.

The workspace simulation section offers Connect/Disconnect **status monitoring**.
Connect performs one read and polls every ten seconds after completion, with one
request in flight. Disconnect, project change, and unmount stop polling and discard
pending results; they do not stop Isaac or disconnect the shared companion.
No model/template setup is mounted in this connection flow. Graph-driven model
operations remain separate, behind their existing central gates.

## Generic model revision (schema v2)

The approved cleanup replaces the fixed robot/template and grasp routine. Model v2
contains `asset:{urdf_path,files,sha256}`, links `{entity_id,name}`, revolute joints
`{entity_id,name,parent_link_entity_id,child_link_entity_id,lower_rad,upper_rad}`,
and optional contact sensors. The asset digest is SHA-256 of sorted compact JSON
of the relative-path/hash manifest. Files reside only under the authorized linked
workspace `.solus/isaac/models/<sha256>/`; verified no-follow copies are imported
from the controller's private directory. No URL, package URI, script, extension,
plugin, transmission, Gazebo tag, DTD or entity declaration is accepted. Only
bounded declarative URDF fixed/revolute tree structures are supported. Graph
names, parent/child identities and limits must exactly match the imported URDF.
An imported stage must expose exactly one articulation; its path is discovered.

`POST /api/v1/projects/{project_id}/simulation-models` now accepts `{name,model}`
with this v2 schema and existing, live, project-scoped link/joint/sensor IDs.
It creates only the model root and containment edges atomically under the existing
verified member gate; supplied graph identities are never fabricated or renamed.
Version 1 is rejected with guidance to register explicit v2 model data, never
silently migrated. The route does not start a simulator.

The only routine is `joint_trajectory`: 1–16 ordered waypoints, each containing
exactly the model's joint IDs; 1–16 joints; 1–30 seconds at 60 Hz, up to 1800 steps,
maximum target speed 0.25 rad/s, and a 20% settling hold per segment. Each requested
range must lie inside the graph model and observed simulated limits. Results
report positions, target errors and tracking success only: no object, grasp,
gripper or contact success is inferred. Contact sensors remain optional explicit
model bindings. Stale graph/scene guards, confirmation previews and private runtime
ownership remain unchanged. Native model limits are 2–32 links and 0–4 sensors.

## Authorization, execution and evidence

All eight cloud-owned wrappers use the existing exact user/team/project bridge.
Start, stop, load, joint edits, sensor edits and routines run a complete preview
(dry run, graph digest, scene generation, runtime fingerprint) immediately before
every native call; raw companion advertisements cannot bypass that policy. Model
entities and every binding are resolved within the active project. Approval binds
graph digest, model version, scene generation and runtime fingerprint. Changes
invalidate approval; unknown versions require explicit re-registration.

### Ownership decides the card (SOLUSDEV-322 P2-T3)

The wrappers are no longer static `requires_confirmation` tools nor Build-owned
routines (`register_owned_routine` ignores them; `execution_policy` has no Isaac
list). Each carries the per-call hook `needs_confirmation(args)` consulted by the
fused dispatch and by Guide mode (`docs/contracts/action-gate.md` step 1). Whatever
the ledger says, a dry run that carries a row labelled `Approval required`
(ADR-040 §5, `dynamic_gate.APPROVAL_REQUIRED_LABEL`; P10 item 22) cards, and
`invoke` refuses an uncarded call whose verified plan carries it:

- `start` is owned by construction: the hook answers no card, and on `ok` the
  wrapper records `sim_session{provider="isaac", owner="sol", started_by_call_id}`
  in the ownership ledger (`simulation/sessions_ledger.py`) — ownership is a DB
  fact the API writes, never a companion claim.
- `stop`, `load_model`, `set_joint_limits`, `set_sensor_pose`, `run_routine`
  card unless `ledger.is_owned(project, "isaac", args.session_id)`: an attached,
  unknown, forged or ended session, a missing `session_id`, or a ledger read that
  fails is a card (fails closed). `stop` on `ok` ends the ledger row.
- `save_stage` is statically gated: writes to the user's own files always card.
- `probe`, `status`, `list_stages`, `find_articulations` and `read_state` are ungated reads.

In Guide mode a call the hook would card is refused; in Build it parks with the
preview the card shows. `invoke` treats a ticket whose args do not match the call
as absent (a parked card's leftover preview never authorizes another call); on
the absent path it asks its own hook and refuses when that says card, then runs
the same plan a card would have shown. A matching ticket is verified as before.
`routed_by_simulation` (R115) no longer forces a card for these tools: a routed
call on a Solus-owned session runs without one, on an attached one it cards.

### The user's own stages (SOLUSDEV-322 P4)

Seven more cloud-owned wrappers in `agent/tools/isaac_tools.py` (SOL-visible argument
models in `isaac_models.py`, strict and closed) front the fork's stage actions
(`docs/api/simulation.md`, `integrations/mcp/isaac/allowlist.yaml`). The fork's
`put_asset` has no public wrapper: it is the internal step of `spawn_at`. The server is
`exposure: internal` (docs/contracts/bridge-protocol.md): the owned `isaac.*` wrappers are the only
model-facing surface, and `agent/runtime.py` also drops the raw specs by server name.

| tool                 | arguments (SOL)                                                                                   | gate                      | cloud timeout |
| -------------------- | ------------------------------------------------------------------------------------------------- | ------------------------- | ------------- |
| `list_stages`        | —                                                                                                 | read                      | 25 s          |
| `open_stage`         | `stage_ref` (root-relative under `SOLUS_SIM_ROOTS`), `dry_run`                                    | owned by construction     | 130 s         |
| `find_articulations` | `session_id`                                                                                      | read                      | 35 s          |
| `spawn_at`           | `session_id`, `model_entity_id`, `name`, `pose{xyz,rpy}`, `dry_run`                               | ledger (`is_owned`)       | 300 s         |
| `read_state`         | `session_id`, `articulation?`, `sensors[]` (≤ 8 prim paths), `camera_frame`                       | read                      | 35 s          |
| `control`            | `session_id`, `action` pause/play/step/reset, `steps` 1–10000, `dry_run`                          | ledger                    | 65 s          |
| `run_routine`        | `routine: "sweep"`, `duration_s` 1–60, `sweep{articulation,joint,lower,upper,speed_rad_s ≤ 0.25}` | ledger                    | 85 s          |
| `save_stage`         | `session_id`, `dest` (root-relative `.usd/.usda/.usdc`), `dry_run`                                | static card (user's file) | 65 s          |

- `open_stage` records `sim_session{provider="isaac", owner="sol", scene_ref=<stage_ref>}`
  on `ok`; `scene_ref` is the root-relative path SOL named, never an absolute path. One
  owned Isaac session per project: a second `start`/`open_stage` refuses before the fork
  is asked, and a race on the ledger row refuses with guidance to `stop` after approval.
- Stage actions bind the scene generation `status` reported (`expected_scene_generation`),
  not a loaded graph model: `spawn_at` resolves `model_entity_id` to the project's v2
  `simulation_model` only for the files it pushes and the digest the fork spawns
  (`model_sha256`); `graph_digest` is never sent for a stage action or a sweep. The card
  still binds the graph snapshot fingerprint for `spawn_at`, and `invoke` re-resolves it
  right before the native call.
- `spawn_at` pushes the model when the fork's dry run answers
  `{ok: false, code: "model_not_verified"}` (the fork checks its store before the worker):
  the shared `agent/tools/sim_assets.ModelPush` streams `isaac.put_asset` chunks of ≤ 64 KiB
  raw (≤ 96 KiB base64) from the artifact store (`attrs.artifacts` of the model root),
  manifest on chunk 0, every byte verified against the manifest digest before it leaves;
  the fork must report `promoted`, the plan is re-run after the push and must still be the
  approved action on the same graph snapshot. The push preview ("Model push: N chunks …")
  is the card body when the companion lacks the model; nothing crosses on a preview. No
  store or no `isaac.put_asset` → refused before any chunk. `gazebo.spawn` rides the same
  helper (`SendChunk` is the wrapper's own raw capability; the helper names no simulator).
- `RoutineSpec` now carries `routine: joint_trajectory | sweep`, `duration_s ≤ 60`; a sweep
  carries exactly its `sweep` spec, a trajectory its ranges and waypoints. `Sensor.kind` is
  `contact | imu | camera`; only a contact sensor needs `radius_m`.
- Names that could reach argv or a USD path are plain identifiers (`name`, `joint`), prim
  paths are `/A/B` of identifiers (≤ 32 components), root-relative paths are plain components
  joined by `/` (no leading `/`, no `..`, no `-` prefix). Companion results are data: any
  `owned` / `owner` / `owned_by` field in a fork result is dropped before SOL sees it.
- `run_routine` hands its result to a `record_sim_run` hook that P5-T4 implements; here it
  is a no-op (`no_sim_run`).
- Isaac stays fixture-only on this branch (this host is aarch64): the fork's fixture runtime
  and the API `Native` fake; `gui_attach` is `unsupported` (no attach to the user's GUI).

Probe and status never launch or import anything. Only the owned worker accepts
bounded private pipe requests; no scripts, URLs, extension flags or public paths
are executable inputs. Stop/cancellation terminate only the owned process and
never replay a failed action. Runs stop on cancellation or timeout. Unverified
readback after a started mutation remains an uncertain outcome, never success.
Private revision artifacts preserve operation/readback evidence and graph identity.

The model importer is version-specific to the installed Isaac adapter API. Vendor
execution must be verified separately from fixture tests. Discover exactly one
articulation and map every graph joint by explicit name; limit and pose edits use
exact indices and require readback. All angles are radians, orientations wxyz.
Only UTF-8 XML is accepted, with an optional initial XML 1.0 declaration, UTF-8
encoding and standalone attribute. Comments, other processing instructions, DTDs,
unknown attributes and invalid hierarchy are refused.
Meshes are manifested relative STL files; other mesh containers require future
explicit validation support. No physics outcome is claimed from a test double.

MCP replies include text and structuredContent. Fingerprints and graph/artifact
SHA256 digests use existing display-safe chunking at the transport boundary;
normal secret redaction remains unchanged. Preview overflow is a refusal, never
truncation: large models/routines may need smaller explicitly reviewed operations.

Required tests cover multiple distinct robot structures; malformed graph bindings;
unsafe/oversized URDF and asset paths; symlink ancestors and file replacement;
unknown versions; exact waypoint identity/range/speed validation; cross-project
and cross-team denial; stale graph and scene guards; owned-process cancellation;
mutation uncertainty; and no effect from preview/probe/status. Live vendor runs
remain separate opt-in evidence on a configured installation.
