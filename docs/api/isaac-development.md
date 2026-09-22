# Isaac external execution — SOLUSDEV-261

**Status: implementation plan approved by root, 2026-09-12; live verification pending.**

This plan implements the approved 2026-09-12 ADR-014 amendment through the existing
Pattern-1 authenticated project bridge and central confirmation gate. Governing
documents are `DECISIONS.md` ADR-014/031, `docs/contracts/agent-tool.md`,
`docs/contracts/action-gate.md`, `docs/contracts/bridge-protocol.md`, and
`integrations/mcp/README.md`. Root must reconcile the companion diagram in
`docs/architecture/local-machine-actions.md` with this owned Isaac server
before implementation. This document changes no shared contract or route.

Isaac is an external installed application. This slice controls one owned local
simulation, loads the pinned official SO-101 model with graph entity bindings, changes its simulated joint
limits or contact sensor pose, and runs one bounded routine. It does not introduce Live
Bench endpoints, telemetry, ROS, device discovery, serial access, flashing,
training, arbitrary scripts, or an executable scene import interface.

## Observed runtime and capability claims

Read-only inspection found this development installation:

`/home/beeboss/isaacsim/IsaacSim/_build/linux-aarch64/release`

Its `VERSION` is `6.0.1-rc.7+main.0.98701505.local`. `python.sh` exists; its bundled
interpreter resolves into the installation's Packman cache. The launcher inherits
`PYTHONEXE`, `PYTHONPATH`, library/preload variables, and shell arguments unless
its caller removes them. Merely finding the launcher is not proof of a usable GPU,
successful startup, working physics, or a controllable session.

Installed source provides `isaacsim.core.experimental.utils.stage`,
`isaacsim.core.experimental.prims.Articulation`, and `XformPrim`. Older
`isaacsim.core.api` / `isaacsim.core.prims` modules remain in `extsDeprecated`.
The adapter must choose and test one version-specific implementation; it must not
silently switch implementations after an action fails. Angular articulation
limits/targets use radians; the USD implementation converts to degrees.
`set_local_poses` accepts quaternion order `wxyz`. Vendor APIs can broadcast values
when indices are omitted: the owned adapter must always select exactly the resolved
articulation and DOF/prim, and verify the resulting target set.

The existing `livebench/src/livebench/sim/isaac_direct.py` is a separate telemetry
producer. It is not the controller and is not launched by these tools.

## Ownership and transport

Proposed implementation location: `integrations/mcp/isaac/`, with an owned
`bin/launch`, `solus/server.py`, `roster.py`, `models.py`, `runtime.py`, `worker.py`,
`scene.py`, `routines.py`, `allowlist.yaml`, private dependency lock, provenance,
and security-review records following the existing fork packaging rules. The
NVIDIA installation remains external; do not vendor its runtime or accept license
terms automatically. Human signature fields remain human-owned.

The lightweight MCP server is supervised by the existing companion. Only an
approved `start` invokes the pinned Isaac interpreter with the fixed owned
`worker.py` entry point. The worker imports Isaac after startup; module import,
inventory discovery, and `probe` must not initialize a simulator or touch GPU
resources. No caller can select an interpreter, executable, extension, script,
environment variable, process ID, host, port, or launch argument.

Use private inherited pipes for bounded request/reply frames between the MCP
server and worker. No TCP listener or separately addressable HTTP controller.
Frames are JSON objects, maximum 128 KiB, strict schema, one outstanding operation,
monotonic sequence, and an opaque per-process session generation. Both ends reject
unknown operations, extra fields, stale generation, and unexpected replies. Kit
logs go to separate bounded output streams, never the control channel.

The normal bridge is still the only cloud transport. No telemetry frame changes.
The cloud registry must install an owned Isaac adapter that resolves graph scope
before invoking the underlying bridge tool; it must not expose a second raw
`BridgeTool` for the same operations. Native inventory cannot supply authorization
policy or modify the cloud-visible schema.

## Strict public tool inputs

All inputs use strict Pydantic models with `extra="forbid"`, including actual MCP
argument validation before coercion. UUID fields use canonical UUID text. Numeric
fields reject booleans, nonfinite values, and coerced strings. Digests are SHA-256;
display them as four colon-separated 16-hex chunks through the existing redactor.
The API derives user/team/project/machine context from the authenticated bridge.
No public input contains those authorization fields.

| Composed name | Input | Confirmation / local deadline |
| --- | --- | --- |
| `isaac.probe` | `{}` | No / 5 s; filesystem observations only |
| `isaac.status` | `{}` | No / 5 s; bounded owned-session state |
| `isaac.start` | `{dry_run?:false}` | Yes / 180 s |
| `isaac.stop` | `{session_id:UUID,dry_run?:false}` | Yes / 10 s |
| `isaac.load_model` | `{session_id:UUID,model_entity_id:UUID,dry_run?:false}` | Yes / 150 s |
| `isaac.set_joint_limits` | `{session_id:UUID,joint_entity_id:UUID,lower:number,upper:number,dry_run?:false}` | Yes / 10 s |
| `isaac.set_sensor_pose` | `{session_id:UUID,sensor_entity_id:UUID,translation_m:[number,number,number],orientation_wxyz:[number,number,number,number],dry_run?:false}` | Yes / 10 s |
| `isaac.run_routine` | `{session_id:UUID,routine:"grasp_bottle",waypoints:[{phase:"approach"|"close"|"lift",positions:[{joint_entity_id:UUID,position_rad:number}]}],joints:[{joint_entity_id:UUID,lower:number,upper:number}],duration_s:number,dry_run?:false}` | Yes / 40 s |

Cloud deadlines add at most 15 seconds for bounded cleanup (start: 195 seconds;
load: 165 seconds; stop: 20 seconds; edits: 25 seconds; routine: 55 seconds).
Every mutating name belongs to the cloud-owned complete-preview/dry-run policy.
Read status contains no source files, arbitrary logs, images, or device telemetry.
It returns the session ID, lifecycle state, scene fingerprint, bound model entity,
and last finite operation outcome, all within the existing tool-result limit.

## Pinned SO-101 model and graph bindings

Root approved this exact tier-1 schema on 2026-09-12. The public load_model input
still contains only the graph model entity ID. The cloud adapter resolves
`entity.attrs.simulation_model` and every nested entity using centralized project
scope, then sends the strict resolved model and version snapshot to the companion.

```text
{schema_version:1, asset:"so101_new_calib_v1", asset_sha256:64hex,
 links:[{entity_id:UUID,name:exact_pinned_link_name}],
 joints:[{entity_id:UUID,name:exact_pinned_joint_name}],
 sensors:[{entity_id:UUID,parent_link_entity_id:UUID,kind:"contact",
           translation_m:[x,y,z],orientation_wxyz:[w,x,y,z],radius_m:number}],
 bottle:{entity_id:UUID,translation_m:[x,y,z],radius_m:number,
         height_m:number,mass_kg:number}}
```

All eight links and six revolute joints must be bound exactly once. All entity IDs
are unique, including bottle and sensors. Sensor parents must be bound links.
Quaternions are finite, unit length within 1e-6; inputs are never silently normalized.
Translations are SI metres in [-10,10]; sensor radius 0.001–0.05 m; bottle radius
0.01–0.1 m, height 0.03–0.4 m, mass 0.01–2 kg. At most four contact sensors.
No unknown keys, booleans as numbers, nonfinite values, or numeric strings.

The official source is TheRobotStudio/SO-ARM100, revision
`eecbe3e0a9ebb23e25ad7b2759b03884c6660903`,
`Simulation/SO101/so101_new_calib.urdf` and its thirteen referenced STL files.
Preserve Apache-2.0 license and a digest manifest for the complete closure.
The asset represents new-calibration joint zeros. Gripper angles remain radians,
not LeRobot's 0–100 scale. Official topology, inertia, and limits are retained.

Native import accepts only this reviewed complete closure, copied into an owned
private directory after regular-file/no-follow digest checks. No caller-selected
URDF/USD, external mesh references, package paths, scripts, extensions, textures,
Nucleus URLs, or arbitrary importer options. Vendor importer outputs remain private.
No runtime asset downloads or package installation. The importer is the installed
Isaac 6.0 `URDFImporter(URDFImporterConfig(...)).import_urdf()` API; older command
names are absent from this installed source and must not be assumed available.
Contact authoring uses installed `isaacsim.sensors.experimental.physics`.

Preview and execution re-resolve graph versions and native scene generation. Any
change invalidates approval. Prim bindings are derived from verified imported
names and IDs; exact single-target operations only, never wildcard selectors.

## Runtime configuration and process lifetime

The reviewed installation root is an application-owned configuration constant for
this development slice, not a workspace file or inherited environment override.
Probe resolves and reports the known launcher/interpreter/version. Before execution,
validate installation paths against an explicitly reviewed root/dependency set
(the bundled Python symlink requires its exact Packman target), regular executable
files, and a captured trusted runtime manifest. Changed runtime identity invalidates
the start preview; do not reuse the Arduino resolver or permit arbitrary PATH search.

Construct a closed child environment. Remove inherited Python/Conda/venv, shell,
preload/library-path, proxy, ROS, cloud credential, and simulator extension settings.
Set only fixed runtime-required directories, fixed locale, isolated HOME/cache/temp,
and an explicitly reviewed GPU driver configuration. No automatic pip/extensions
installation, remote asset downloads, update checks, credential inheritance,
network listener, ROS bridge, or telemetry extension. `python.sh` is usable only
through this fixed owned environment and fixed argv; caller shell fragments never
reach it. Enumerate the required values in the implementation review.

Use one headless session on this machine, owned by this companion generation and
its authenticated project. A second session returns `operation_busy`; never attach
to or stop a simulator the user launched independently. The in-memory session
record holds process handle/start identity, random session UUID, workspace identity,
root model binding, scene generation, and scene fingerprint. No auth token is passed
to Isaac. A process label or PID alone is not proof of ownership.

Startup does not return success until the worker reports initialized application
and a responsive bounded status exchange. No scene is loaded implicitly. Shutdown,
project/credential change, companion disconnect, and worker protocol violation
cancel the current action, request graceful stop, then terminate the owned process
group after five seconds. Never automatically restart or replay a mutation.

One operation runs at a time under an owned lock. Check cancellation between steps
and during startup waits; continue enforcing deadlines after stdout/stderr close.
Bound each log stream to 1 MiB captured bytes and return at most 8 KiB redacted tails
with truncation flags. Limit controller queues to one request and one reply.
GPU/resource feasibility is verified during the explicit startup test; a failure is
reported as the observed runtime/driver failure, not an invented OS incompatibility.
No test in ordinary CI starts Isaac or allocates GPU resources.

## Plans, edits, persistence, and routine semantics

All actions return a side-effect-free dry-run object
`{ok:true,dry_run:true,preview:DiffRow[],fingerprint:string}`. Keep the existing
40-row/400-character field limits; refuse an unrenderable plan instead of truncating
consent. Start preview names runtime version/identity, headless mode, process/resource
ownership and exact logical argv/configuration. Load preview includes every bound link,
joint, contact sensor, and bottle with units and graph identity, scene replacement, and snapshot digest.
No arbitrary compressed blob or hash-only substitute for the model details.

Mutation previews show bound session, scene generation/digest, graph versions,
target entity and derived prim, complete old/new values with frame/units, output
destination, and operation fingerprint. They are re-read at approval and locally
immediately before execution. The native controller enforces the same expected
scene generation and state; it cannot treat a UUID from an old session as current.

Loading replaces only this owned scene after successful validation. Edits target
exactly one resolved joint or contact sensor; no wildcard matching or implicit bulk update.
After an edit, read back the exact selected USD/physics values and unchanged target
inventory before declaring success. Do not mutate the user's manufacturing CAD,
hardware limits, or calibration through a simulator edit.

Persist only the generated model plus approved simulator overrides under a private,
fixed `.solus/isaac/` directory inside the linked workspace. No caller-selected output
path. Use regular-file/no-follow descriptor confinement, bounded files, process-shared
locking, and atomic no-clobber revision publication. Store schema version, bound graph
snapshot, official asset digest, operation, before/after state and content digests.
Limit one artifact to 128 KiB and one session to 32 revisions; refuse exhaustion,
never delete arbitrary existing files or overwrite an unknown revision. Probe and
status never create or repair this directory. Editing a simulation does not rewrite
graph facts; its graph provenance remains the verified source snapshot. Existing
confirmation/result records provide the project-scoped audit of applied overrides.

`grasp_bottle` is the named routine for this slice. Input includes the six
joint entity IDs and explicit lower/upper bounds in radians, plus exactly three
ordered waypoints: approach, close, lift. Each waypoint contains exactly all six
joint IDs and finite `position_rad` values. Duration is 1–30 seconds, at fixed
1/60 second physics steps (maximum 1,800). Requested ranges must fit the current
simulated limits and pinned URDF limits. Every target must fit the requested
range; interpolation starts at observed current positions. Maximum target speed
is 0.25 rad/s. Each phase reserves its final 20% of steps for a stationary
settling hold, inside the declared duration and 1,800-step cap. Validate speed
against the remaining interpolation time. Reject trajectories too fast for it.

The pinned force position drives use stiffness 400 Nm/rad and damping
20 Nm·s/rad. The vendor convex-decomposition importer preserves the gripper
concavities; the previous 50/5 settings showed measurable steady gravity sag.
Return finite pose/contact snapshots after each of the three phases to distinguish
approach collision, closure failure, and retention failure.
Commands use position drives, never teleport joints or attach the bottle to the
gripper. Read back actual joint positions, contact validity/force, and bottle pose.
Report `grasp_observed` only when final joint error is at most 0.01 rad and
every step of the final hold has valid jaw contact specifically with the owned
bottle (raw body identities), bottle-specific force above 0.01 N, and bottle lift
at least 0.02 m. Bottle force sums only matching raw contact impulse magnitudes
divided by the fixed physics step; unrelated aggregate sensor force is reported
separately and cannot satisfy the criterion. Joint tracking is checked at the final step.
Return observed retention steps and required hold steps; incidental contact or
a transient lift does not establish retention. Completing a command sequence
is not a successful grasp. A failed
grasp is an honest finite outcome. No telemetry stream or hardware verification.
Cancellation and timeout stop stepping the owned scene; no automatic replay.

## Outcomes and verification

Boundary refusals are sanitized MCP errors with stable reasons: `runtime_unavailable`,
`unsupported_runtime`, `workspace_unavailable`, `model_unavailable`, `invalid_arguments`,
`model_invalid`, `stale_state`, `operation_busy`, `resource_limit`, `preview_too_large`.
Unsupported-platform text follows the product convention “Isaac not available on
<OS>/<architecture>”; installed-but-failed startup retains its specific cause.

Successful writes return `ok:true`, session/scene identities, the verified operation,
readback, and bounded artifact identity. If execution began but readback/publication
is inconclusive, return `ok:false,started:true,uncertain:true` and no success claim;
show that the simulator may have changed and do not retry automatically. A subsequent
status/readback may reconcile facts but grants no permission to rerun the action.
Optional audit persistence failure must not transform an observed applied change
into a claim that nothing happened. Use existing Error filing and confirmation
events rather than new generic activity or telemetry messages.

Required automated tests cover strict MCP coercion/extras; source and nested graph
isolation; absence of raw adapter bypass; unknown/missing graph model refusal;
cycles, duplicate IDs, invalid units/quaternions and oversized models; no foreign
file/URL/script/extension imports; runtime replacement and environment poisoning;
stale graph/scene/generation at approval and execution; exact-index single-target
mutations; output limits, hanging startup and closed-pipe cancellation; ownership
of stop/cleanup; atomic artifact publication; failed readback; and no action on
probe/status/dry-run. Exercise existing central gate denial and no-preview refusal.

The explicitly opt-in local test uses newly created graph fixture entities and a
disposable linked workspace. First start one empty headless session, then load the pinned
SO-101 model and bottle; verify one limit edit and contact sensor transform;
run a bounded grasp trajectory and report actual contact/positions/bottle outcome; stop and confirm process exit.
No physical device or Live Bench service participates. Record fixture-only tests,
actual vendor execution, and product confirmation tests as separate evidence.

## Implementation order and evidence

Root approved the pinned SO-101/contact sensor/grasp_bottle schema above. Build
strict models and bounded trajectory tests first, then isolated runtime and native
scene, then root-owned cloud resolver/bridge registration. Complete preview and
project authorization remain mandatory product gates. Separate native fixture
execution evidence from product approval evidence. No live completion claim yet.

### Request cancellation

An in-flight SDK request cancellation closes the exact owned controller, signals
its cancellation event, and performs bounded owned-process termination. The MCP
controller remains closed after cancellation; a companion MCP session restart is
required before another explicit start. No cancelled operation is replayed.

### Bounded project template creation (SOLUSDEV-261)

`POST /api/v1/projects/{project_id}/simulation-models` accepts exactly
`{template:"so101_new_calib_v1"}`. Central verified-user/project authorization and
member role are required. It creates a manual source-null simulation-domain model
root, eight links, six joints, one jaw contact sensor and one bottle, using only
server-generated UUIDv7 identities and reviewed pinned template facts. No provider
source is fabricated; no imported entity is modified. No simulator starts.

Creation holds the project row lock and commits all 17 entities, root containment,
joint-to-link connections and sensor attachment atomically. Repeated requests
return the intact existing instance; malformed or partially missing existing
instances return 409 `simulation_model_conflict` without repair or duplication.
The response envelope contains `{model:<serialized entity>,bindings:<validated
SimulationModel>,created:boolean}`; HTTP 201 for creation and 200 for reuse.
Created instances emit `simulation.model_created` and committed `graph.changed`
(null source/sync IDs); reuse emits neither. The fixed initial sensor pose and
bottle placement are template defaults, not claims of measured hardware state or
successful grasp. The official revision and asset manifest digest remain attached
as provenance. General graph/configuration edits remain unavailable through this
route.

### MCP result transport

The native SDK returns both text and `structuredContent`; the companion's existing
mapper forwards the latter. Declared digest fields (`fingerprint`, `graph_digest`,
`runtime_fingerprint`, artifact `sha256`) use four lowercase 16-hex chunks separated
by colons on this boundary. The cloud accepts only exact lowercase SHA-256 or this
exact chunked form and normalizes internally before integrity comparisons. Other
fields retain normal secret redaction. No redaction policy is relaxed.

Approval previews retain every native row and add one bounded binding row containing
the native fingerprint and, for graph actions, graph model ID/version and graph
digest. A 39-row native routine therefore fits the existing 40-row card without
truncating either the native facts or the authorization binding.
