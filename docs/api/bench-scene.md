# SOLUSDEV-262 — client kinematic scene

## Initial graph-backed CAD import (demo follow-up)

GET `/cad-sources?include_assemblies=true` includes eligible assemblies for initial
imports; the default remains leaf-only for existing mesh bindings.

POST `/cad-imports` accepts strict `{robot_id,source_entity_id,expected_revision}`.
Verified project members only; source and all selected descendants must be visible
in the same project/source/document/element/revision. The selected entity may be
an assembly or leaf. Bounded 128 leaves; cycles/ambiguous occurrences refuse.
Returns202 `{import_id,status,job_id}`. GET `/cad-imports/{id}` returns the scoped
status, reason and resulting `model_id` when complete. No local/remote paths or
caller-supplied geometry are accepted. An import request is explicit; it never
starts robot motion or confirms joint mappings.

The existing source sync/cache boundary obtains the exact STEP export; no second
provider export or independent polling loop. Cached bytes are account-scoped and
revision-bound. A cache miss queues the existing authorized source acquisition;
provider allowance failures remain explicit. Heavy tessellation runs in the
existing bounded isolated worker. CAD display tessellation tries at most three
linear/angular tolerances (0.1mm/0.5rad, 0.4mm/0.8rad, 2mm/1.5rad), retaining every
selected occurrence and exact transforms. The 50,000-triangle and 8MiB limits,
25-second wall deadline and 20-second CPU limit apply across the complete job,
including retries. Mesh output targets at most 6MiB to reserve serialization
headroom for transformed coordinates and normalized metadata; final placed output
still must fit 8MiB. Exhaustion reports a safe bounded-display-limit reason;
no partial geometry is accepted. Pending imports and resulting scene models are
graph-backed, with project-scoped refresh events after commit. Repeated pending
requests for the same selection reuse the pending import.

STEP projection preserves full parent-relative rigid transforms in addition to
legacy millimetre translations. Import composes these transforms and converts
translation/vertices to metres exactly once. Missing transform evidence refuses;
bounding boxes or guessed identity rotations are never substituted. Bump the
projection marker so cached source exports can rebuild old graph observations.
Each leaf keeps its exact occurrence/source binding for ordinary CAD refresh.

Initial geometry has zero movable joints unless verified semantic joint evidence
exists in the graph. Static output explicitly states that CAD contains no verified
motion-joint definitions. No name matching or fabricated kinematics. Retain the
normalized geometry as a scoped artifact and reuse the existing scene model,
placement and mapping services. Successful later refresh reconciles transforms,
source revision and digest while preserving model identity and valid mappings;
failure preserves prior geometry with a visible stale reason.

SOL may list eligible sources, propose this import through the existing central
manual approval gate, and read its status using registered in-process scene tools.
The preview names the selected graph source/robot/revision and static limitation.
The Bench scene pane exposes the same source import and progress/status using these
routes. No shared contract, bridge frame, arbitrary export endpoint or physics
executor is added.

Governing SPEC §4 / attachment L2, sol-artifacts, telemetry-viz-out, widget-canvas.
This adds generic imported models beside (not replacing) the separately reviewed single
simulation template. No physics server or runtime motion is started.

All routes `/api/v1/projects/{project_id}/bench/scene`, centralized ProjectCtx and verified
member. Foreign/deleted robots, model nodes, sources and artifacts return404.
- GET /models → envelope {models:[...]}, maximum32 models per project.
- POST /models → {robot_id,artifact_id,name(1..120),format:urdf|mjcf,
  source_entity_id?:UUID, source_revision?:string(1..128)} →201 model.
  Explicitly uploaded bounded XML only; retain file through existing .solus docs filing;
  create bench_scene_model graph node and references robot/document/source edges.
- PUT /models/{id} → same import payload plus expected_version:positiveint →200 replacement,
  preserving identity and display pose, clearing mappings if joint structure or source changes;
  concurrent version mismatch409. Updates use explicitly reimported revision, no guessed remote path.
- PUT /models/{id}/mapping → {expected_version,bindings:[{joint,part_entity_id,
  device_id,signal,unit:rad|deg|m,scale:finite,offset:finite}]} →200 model.
  Explicit user confirmation. Verify accepted part belongs to the selected robot and device
  mapping still matches current CONFIG; no matching based on similar names. Bounded128 unique
  joints; reject fixed joints, duplicate part/signal bindings and incompatible unit/dimension.

Model response id,robot_id,name,version,artifact_id,source_entity_id/revision,source_current,
normalized model(links, joints, visual primitives, warnings), bindings. Jointless model remains
visible with reason; stale source/config invalidates live binding until reimport/reconfirmation.
XML: <=1MiB, <=128 links/joints, <=512 visuals, bounded depth/numbers/names. Reject DTD,
entities, includes, plugin/code, malformed cycles/duplicate names/missing links, unknown moving
joint types or ambiguous defaults. URDF fixed/revolute/continuous/prismatic; MJCF nested bodies
with hinge/slide and explicit coordinates. Mesh references are inert: never fetch URL/file/package
paths; surface missing mesh geometry and render joint/link structure honestly. Assets require
separate explicit artifact association before loading; primitive geometry is directly supported.
Model parsing runs off request event loop. Emit scoped identifier-only mutation events and graph
refresh after commit. Read never creates graph records. No change to packages/contracts.

### Explicit STL artifact association
Import/reimport optionally includes `meshes:[{reference:string(1..512),artifact_id:UUID}]`
(maximum64, unique exact reference). URDF references match `mesh.filename` exactly; MJCF
geometry names resolve only through that XML's asset mesh declarations and their `file`.
No basename inference, URI fetching or filesystem resolution. Each artifact is independently
project/account checked, bounded, validated, and retained in .solus docs. Total XML plus mesh
input <=8MiB and <=50,000 triangles per model. Parser work remains off the event loop.
Normalized `model.meshes` maps opaque SHA256 keys to `{vertices:number[]}` (nonindexed triangle
xyz coordinates). Mesh visuals add `mesh_key:string|null` and positive finite `scale:[x,y,z]`.
Normalized serialized output <=8MiB. Missing association keeps explicit unavailable geometry;
unused, duplicate, malformed or excessive supplied references are rejected. Source-current
means the source entity/version/attributes and accepted CONFIG snapshot still match; a changed
source requires reimport, a changed CONFIG requires mapping reconfirmation.

## Source-linked CAD geometry refresh (SOLUSDEV-262)

GET `/bench/scene/cad-sources` returns bounded eligible project CAD leaf entities with opaque
IDs, display names and observed microversion. PUT `/bench/scene/models/{id}/cad-bindings` accepts
strict {expected_version,bindings:[{mesh_key,source_entity_id}]} (unique existing mesh keys,
project-visible unambiguous CAD leaves). Verified member only, tenant404, optimistic conflict409.
Returns202 {model,refresh_status,job_id}; queues existing normal source sync for initial capture.
Subsequent successful webhook/sweep syncs refresh bound meshes from that sync's exact STEP
export, without a second export or independent polling loop. Model response includes bounded
per-binding observed microversion and refresh_status. A failed sync/ambiguous occurrence/missing
OCCT/oversized geometry preserves previous mesh with an explicit stale/error state. Geometry
updates preserve scene model ID, placement key, link/joint structure and still-valid confirmed
mappings. No inferred motion or name-based source association.
