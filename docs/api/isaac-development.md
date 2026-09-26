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
Start, stop, load, joint edits, sensor edits and routines require complete central
confirmation previews; raw companion advertisements cannot bypass that policy.
Model entities and every binding are resolved within the active project. Approval
binds graph digest, model version, scene generation and runtime fingerprint.
Changes invalidate approval; unknown versions require explicit re-registration.

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
