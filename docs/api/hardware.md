# Hardware ownership and onboarding route plan

**Last updated:** 2026-09-11. **Status:** integrated SOLUSDEV-251/252/250 route plan for
SOLUSDEV-260. Explicitly labeled SOLUSDEV-253/256 sections remain approved future design,
not a claim that observation routes or the full two-screen redesign have shipped.
**Authority:** ADR-034 amendment 2026-09-07, ADR-025/027/012/031;
[architecture](../architecture/hardware-onboarding.md),
[wireflow](../wireflows/hardware-onboarding.md), [storage](../schemas/hardware-config.md).
Project `.solus`: [solus.md](solus.md); robots/layout: [workspace.md](workspace.md).

Paths below are under `/api/v1/projects/{project_id}/hardware` unless stated otherwise. Use
centralized `ProjectCtx`; non-members receive 404, unauthenticated requests 401, writes by a
viewer/share-only user 403. Every referenced entity/config/parent/source must belong to this
project and be live where required. Unknown request fields return 422. Writes emit structured
events after their transaction commits; provider-owned identity, attributes and containment
cannot be changed through these routes.

## 1. Per-entity ownership and creation (SOLUSDEV-251)

A robot or part belongs to its project. A part can be unassigned. The optional parent is a live
manual Physical Robot or one of its explicitly owned category nodes. Parent assignment changes
manual `contains` edges only. It does not move provider containment, transfer a transport, or
change graph/configuration IDs. Arbitrary ownership nesting is outside this cycle.

| Method | Path                                              | Request / result                                                      |
| ------ | ------------------------------------------------- | --------------------------------------------------------------------- |
| POST   | `/entities`                                       | Create one robot or part atomically with optional configuration; 201. |
| GET    | `/entities/{entity_id}/config`                    | Read configuration without creating it; 200, including absence.       |
| PUT    | `/entities/{entity_id}/config`                    | Versioned full replacement or first configuration; 200.               |
| PATCH  | `/parts/{part_id}/parent`                         | Atomic attach, reassign or detach; 200.                               |
| GET    | `/parts?ownership=unassigned\|all&limit=&cursor=` | Project-visible eligible parts and their current ownership; 200.      |

`POST /entities` requires `Idempotency-Key: <UUID>` and this strict body:

```text
{
  kind: "robot" | "part",
  name: string,
  parent_id?: UUID | null,
  category?: sensors | actuators | controllers | end_effectors | power | structure | wiring,
  config?: ConfigDraft | null
}
```

Names are trimmed, nonblank and at most 512 characters. There is no project-name, model-name or
library-name default. A robot cannot have a parent/category through this route. A part may omit
both and remain unassigned; a robot parent requires a category to select its actual category. A
category parent determines its robot/category and a contradictory category is 422. A category
without a parent remains classification for an unassigned part, not a hidden robot creation.
`ConfigDraft` has the v2 fields with `entity_id` omitted (unknown if supplied); the server
allocates the UUID and adds it before full v2 validation. `component` may be omitted/null.

The response is `{entity: Entity, config_entry_id: UUID|null, config_version: integer,
parent_id: UUID|null, ownership_version: integer}`. No config yields null/0. A robot creates the
existing seven real category entities atomically. A part creates no robot or category root.
`ownership_version` is the entity's existing integer version, incremented on ownership changes;
concurrent entity edits therefore invalidate a stale assignment as well.

Creation and reviewed confirmation use an operation record scoped to `(project_id, user_id,
idempotency_key)`. The digest covers operation type, route target, normalized validated payload
and relevant reviewed revision. Repeating the same request returns the originally saved IDs
and response (201 for creation); a different payload under the same key is 409
`idempotency_conflict`. Lock/unique enforcement prevents duplicate first submissions. Records
expire after 24 hours; clients retain the saved IDs and use connection retry after success,
not creation replay after expiration. The record and graph/config writes commit in one
transaction; failed validation or rollback leaves neither a success record nor partial nodes.
The same key in another authorized account/project is independent. Do not reuse billing tables.

## 2. Hardware configuration (SOLUSDEV-251)

`GET /entities/{id}/config` returns `{entry_id: UUID|null, entity_id: UUID, version: integer,
config: HardwareConfigV2|null}`. An eligible live subject with no active config returns nulls
and version 0. A wrong-project/deleted/unsupported subject is 404. GET does not create a CONFIG
entry or graph edge and cannot recreate a deleted config.

`PUT /entities/{id}/config` takes `{config: HardwareConfigV2}` and required
`If-Match: <nonnegative integer>` (`0` means first write). The subject in the document must
match the path. Missing/malformed preconditions are 422. Under one transaction, validate subject,
all part references and field provenance, compare the version, then create/update the entry and
its manual `configures` relation. Return the GET shape with version incremented. A stale version
or concurrent first write returns 409 `config_conflict` with `current_version` and bounded
conflict detail. Imported subjects receive a Solus-owned relation; only manual subjects may
carry a `hardware_config_ref` convenience attribute.

```text
HardwareConfigV2:
  schema_version: 2
  entity_id: UUID
  component?: PartConfig | null
  identity?: {kind, binding, vid?, pid?}     # no last_seen_path
  protocol?: {driver_id, params}
  bus_map: [{protocol, address, part_entity_id?, model?}]
  disambiguated_by?: "user"
  provenance: {dotted_path: {by: library|repo|user|sol|detected, source?}}
```

The stored v2 model is `EntityHardwareConfig`; the existing `HardwareConfig` v1 remains an
explicit runtime/legacy adapter type. The API-local models implement the shape and bounds in
[hardware-config.md](../schemas/hardware-config.md). Each subject owns its component calibration,
limits, telemetry, firmware and lifecycle. Connection identity/protocol/bus mappings belong to
its connection owner, which can be a robot, controller or gateway part. Runtime assembly reads
referenced part configs into the existing driver input at the hardware boundary; this is not
another persisted aggregate. A name/part/config can be saved without a driver, device,
calibration, CAD, ROS or simulator. Absent capabilities remain unknown.

Operational values require provenance. Observed evidence never silently overwrites a saved user
decision. Portable references and verified calibration values may be shared; absolute paths,
port hints and credentials may not. Private references are resolved only through the approved
[hardware local-state contract](../contracts/local-state.md). Changed source bytes require
explicit review/relink; automatic proposal parsing remains later work. Unit modes must be resolved from evidence: degrees → deg,
range_0_100/range_m100_100 → %, linear → mm, raw/unknown → no guessed physical unit.

## 3. Assignment, retention and compatibility routes (SOLUSDEV-251)

`PATCH /parts/{id}/parent` takes `{parent_id: UUID|null, expected_parent_id: UUID|null,
version: nonnegative integer, category?: category-key}`. Parent IDs identify the actual category
when assigned (a robot ID is accepted as desired parent with its category). Compare expected
current parent and entity version under lock; mismatch is 409 `ownership_conflict` with current
parent/version. Null detaches. Return `{entity: Entity, parent_id: UUID|null,
ownership_version: integer}`. Reassignment preserves config entry/value/provenance, source ID,
external_ref, canonical links, coordinates and unrelated relations. Mappings from a previous
connection owner are disabled or require explicit review before reuse; assignment never silently
transfers an endpoint. The same target is a no-op after valid precondition checks. Derived manual `binds` edges run
from CONFIG nodes to parts with `{device_ref,address,protocol,config_version,enabled,
disabled_reason?}`. Assignment sets stale edges disabled with ownership_changed; explicit
versioned config PUT rebuilds/re-enables reviewed bindings. Runtime/resolver reads validate
scope/current version and enabled state. Invalidate relevant caches only after commit.

The parts list uses existing Entity pagination, default limit 50, maximum 100. Each row includes
`parent_id` and `ownership_version`. `unassigned` includes live eligible manual, retained and
connector-sourced parts (current eligible kinds: part, component, cad_part, assembly) without a
live manual robot/category owner. Provider containment does not hide an unassigned part. `all`
also includes assigned parts. No source account-wide catalog is returned.

Keep the existing compatibility routes while the renderer migrates:

| Method  | Path                                           | Compatibility behavior                                                                                                          |
| ------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| GET/PUT | `/robots/{robot_id}/config`                    | Resolve the same authoritative subject/config; GET is read-only. Legacy v1 output may be assembled; no second stored aggregate. |
| POST    | `/robots/{robot_id}/parts`                     | Required user name, category/specs/lifecycle; delegate to per-entity creation and assignment.                                   |
| POST    | `/robots/{robot_id}/parts/{part_id}/lifecycle` | Update the part-owned component through the versioned config service; preserve identity/edges.                                  |
| GET     | `/unassigned?limit=&cursor=`                   | Alias for the unified unassigned query, including manual/retained parts.                                                        |
| POST    | `/robots/{robot_id}/parts/attach`              | Existing 1–64 IDs/category; preserve existing part configs. Already attached IDs skip; conflicting ownership returns 409.       |

Legacy writes preserve v2-only owner/part fields through the reviewed compatibility adapter.
The current unversioned compatibility PUT remains supported where translation is unambiguous;
lossy or disabled-binding round trips return 409 `config_upgrade_required`. Production CONFIG
editing uses the v2 expected-version route. Existing
robot removal continues to retain parts; their config entries survive independently. CONFIG
deletion removes its manual binding relations, invalidates resolver caches, and cannot make GET
create a replacement. The UI confirms the concrete affected configuration/bindings first.

## 4. Detection, confirmation and recovery

### Current device routes and inline workflow (SOLUSDEV-250/260)

Retain `GET /detected`, `POST /detected/{device_ref}/propose` and
`POST /detected/{device_ref}/confirm` for stable identity compatibility. The device-ref prefixes
are usb, can, ble, bt, ip, ros2. A portable stable ref is `<transport>:<binding>`; a part endpoint
is `<device_ref>/<address>`. Neither a path nor a vendor/driver is identity. Imported
`external_ref` is never rewritten for telemetry; resolve validated manual config bindings first
and reject ambiguity using the existing project-scoped resolver interface.

`GET /detected` returns the bounded `DetectedDeviceOut` rows: nullable `device_ref` and
identity, transport, level, board/board_class, mcu_known, confidence/evidence, ambiguity,
headline and `identity_basis: serial|port_position|none`. Protocol/platform capability is
reported only when supported by actual proposal evidence, never inferred from a USB bridge.
A serial-less device with topology position uses `usb:port-<location>`; this identifies the
port, not the board. Cards and sidebar say: “no serial number — identity is tied to this USB
port; keep it plugged in here”. Missing serial and location yields no binding and cannot be
proposed. A move requires new selection; ambiguous resolution does not choose a device.

The API-owned `DeviceWatcher` performs lightweight local enumeration at about 1 Hz while
subscribed and publishes full `hardware.devices_changed` lists on the existing project stream
using local-only delivery, never Redis. A readiness GET seeds the list; a delayed seed cannot
overwrite a newer authoritative frame or survive a project/account generation change.

The current stable-device `POST /propose` retains `{repo_root?: null}` for compatibility;
any non-null value is 422 before path inspection. It uses bounded device interrogation and
current project evidence. There is no registry-absent unconfined fallback. Proposal fields
include summary/headline/tone, accepted-row evidence, optional stream metadata, repo match
choices and disambiguation. These remain evidence, not permission to fetch private paths or
replace saved calibration. Source tokens resolve only after explicit private relinking.

Current `POST /confirm` retains `{target: {kind: "new", name?} | {kind: "existing", robot_id},
accepted: [{row_id, function_name?, category?}], repo_config_id?, repo_root?: null,
start_session?: boolean, window_seconds?}`. The inline UI supplies a nonblank user name for a
new robot and shows proposed rows before Add accepts them. It preserves existing entities and
writes independent v2 configs; no mutable part-config copy is stored on the robot. Unknown
accepted rows or unresolved config choices are refused. The bounded proposal cache can avoid
repeating interrogation, but confirm still validates current device presence: propose, unplug,
confirm within the cache lifetime returns `404 device_not_found` without creating a robot.
An already-bound device conflicts rather than creating another robot.

### Asynchronous session start (SOLUSDEV-260)

The confirmation request commits the robot, per-entity v2 configurations and a
`properties.connection` object before returning 201. Existing response keys remain;
when session start is requested `session_id` and `session_error` initially remain
null. The connection object is `{managed_by: "local_runtime", runtime_id: UUID, attempt_id: UUID,
status: "connecting", session_id: null, error: null}`. Its terminal status is
`connected`, `failed` or `disconnected`, with a session UUID only after successful
opening and a portable, path-free error when appropriate. With `start_session:false`,
no new connection attempt is scheduled.

An application-owned coordinator performs opening with a fresh database session,
using the authenticated project/account and the current versioned configurations
and private local-source resolver. It checks the attempt, live ownership and
participating configuration versions before opening and before accepting completion.
A stale completion is closed. Deletion cancels pending work and closes its session;
shutdown drains the coordinator before closing SessionManager and the graph hub.
Deleting a robot with an active connection owned by another runtime returns 409;
the connection must be stopped in its owning runtime first. This API never claims
to have stopped hardware controlled by a different process.
Startup reconciles only connection metadata whose `managed_by: local_runtime`
and `runtime_id` match this API runtime's private persisted identity. The identity
is scoped to this checkout and protected by an exclusive lifetime lock; a second
process cannot reconcile the first process's active sessions. Matching prior
in-memory sessions become `disconnected`. Foreign or legacy metadata without a
matching runtime identity is untouched. The identity is API-owned, never supplied
by a browser or companion message. Recovery never deletes hardware/configuration.

State changes update the robot and publish the existing project-scoped
`graph.changed` event; no second SSE protocol is introduced. The frontend treats
this event as authoritative invalidation even if timestamp-derived graph versions
compare equal. Confirmation timing covers commit and response preparation, excluding
background opening. A cached proposal still requires cheap current-device presence
validation; missing-device confirmation is refused without creating a robot.

Raw `repo_root` request paths remain refused under the Phase3 privacy rule. The
merge must not restore legacy unconfined registry fallback or treat a request path
as file-picker authorization.

The current response remains `{robot: Entity, part_ids, config_entry_id, session_id,
session_error}`. A successful save is independent of session availability. Retry uses the
saved owner through the bench route; receiving-data status requires actual packets. The
confirmation-to-node target is well under 500 ms, measured separately from connection opening.

### Later observation/review expansion (SOLUSDEV-253/256)

The following generation/revision routes and body shapes are approved future work. They do
not replace the current stable-device compatibility schema merely because this plan lists them.

New observation routes support serial-less and duplicate-serial devices:
`POST /observations/{observation_id}/propose` and
`POST /observations/{observation_id}/confirm`. Observation IDs are opaque UUIDs issued by the
local runner. Enumeration returns rows immediately with `{observation_id, generation,
device_ref: string|null, transport, identity, level, protocol?, platform?, sessions, status?}`;
identity/evidence retains the existing staged transport/board/protocol/platform fields. Generation
is a positive integer for this attachment. Serial-less/duplicate-device selection expires after
detachment or generation change and cannot grant durable reconnect consent.

Propose body: `{generation, source_refs?: UUID[], context_entity_ids?: UUID[]}` (at most 32 of
each). References must be authorized for this project/account; no arbitrary `repo_root` file
permission is accepted from a remote request. An already linked checkout is resolved by the
trusted local runner. Use bounded project graph/config/artifact evidence and plugin parsers;
cache immutable parse results by digest. Return the existing evidence/row/disambiguation fields
plus `{observation_id, generation, revision, config_versions}`. `revision` is an opaque bounded
server-produced review token identifying material observation/config/source evidence. Every
row has a stable proposal row ID; model/function suggestions are separate from user names.

Confirm requires `Idempotency-Key` and `{generation, revision, target, accepted,
repo_config_id?, start_session?, window_seconds?}`. Target is
`{kind:"new", entity_kind:"robot"|"part", name, parent_id?, category?}` or
`{kind:"existing", entity_id, version}`. Each accepted row identifies `row_id`, and either a
required trimmed `name` for a new part or an existing in-project `entity_id` and expected version;
category/function suggestions are optional review inputs. Every newly materialized part,
including library children, has a user-entered name. `accepted` may be empty when saving context
without an operational bus. `start_session` defaults false; the UI chooses Add versus Add and
connect explicitly.

Confirm rechecks authorization, observation generation, pertinent current identity/accepted
addresses/models, ownership and config/source revisions. Material changes return 409
`proposal_changed` with the revised review, never silent acceptance. Fresh verification has an
overall deadline; it need not repeat unrelated scans. More than one plausible config prompts
one focused question; no answer is inferred from option ordering. A compatible existing entity
is reconciled without deleting prior component configs or creating duplicate hardware.

Graph/config/operation records commit before optional connection. Response:
`{entity, part_ids, config_entry_id, config_version, saved:true, session_id?, session_error?}`.
A connection failure does not undo the saved node. Retry uses its saved owner ID through the
bench route. Saved, connectable, session-open and receiving-data are separate states; a ping
never marks parts live or invents position channels. Only demonstrated capabilities create
channels, and actual packets establish receiving-data status.

Lightweight enumeration remains separate from interrogation. Subscribe to OS changes where
supported, otherwise poll at a bounded rate while Hardware is open. A runner-owned machine-wide
endpoint lease covers probing, raw serial, sessions and reconnect. Active sessions are never
interrupted to probe; another project receives only generic busy information. Overall deadlines,
cooperative cancellation and close/release must complete before a successor opens the endpoint.
Old account/project/generation results are discarded. Typed busy/permission/missing-runner/
unsupported/ambiguous/disconnected states retain the naming draft and offer inline recovery.

## 5. Link suggestions and library

Existing compatibility library routes remain available to the inline Search flow. The stricter
per-materialized-child naming and idempotent import requirements below remain the approved
253/256 extension; do not infer their implementation from a successful legacy import.

Retain `GET /suggestions?status=pending` and `POST /suggestions/{id}/accept|reject`.
Rows keep `{id, subject_ref, subject_kind, candidate_robot_id, confidence, tier, evidence,
reason, status, created_at, decided_at}`. CTR-08 bands remain bus ≤0.92, firmware ≤0.55,
telemetry-shape ≤0.30. Multiple plausible robots produce multiple suggestions; nothing
is auto-accepted. Acceptance delegates to the same reviewed, versioned save-before-connect
service, supersedes sibling rows only after commit, and leaves prior config intact.

Retain library search/preview and `/library/platforms/{id}/import`, `/library/parts/{id}/import`.
A part import requires its user-entered `name`, accepts optional `parent_id`/category, and may
remain unassigned. Platform import requires the robot `name` and a name for every materialized
part, keyed by its definition row; reject missing/blank names. Both use Idempotency-Key and the
same creation transaction. Definition/model labels are preview data, not defaults for names.
Definitions remain curated data; vendor-specific parsing remains in plugins. Library imports
may produce link suggestions but do not auto-bind a detected device.

September 15 UI compatibility increment: the existing part import accepts optional `robot_id`
and `name`, retaining existing robot-targeted callers. Omitting `robot_id` requires an explicit
nonblank `name` and UUID `Idempotency-Key`; it creates one unassigned part and its independent
v2 component config with library provenance, without creating a robot. Replays return the same
entity/config IDs; changed input under the same key returns 409. Unknown fields remain rejected.
Optional `category` overrides the definition's category. The response remains
`{entity, config_entry_id}`. The full platform-child naming extension above is separate.

## 6. Bench session extension

Under `/api/v1/projects/{project_id}`, `POST /bench/sessions` accepts real-mode
`config: {provider:"hardware", entity_id:UUID}` for a saved connection owner, including a
controller/gateway part. Existing `{provider:"robot", robot_entity_id}` stays compatible.
Resolve and validate the owner's config plus referenced component configs before passing the
existing aggregate input to drivers; validate protocol parameters with the driver schema.
Raw serial and its existing optional generic driver_id/driver_params remain supported. The
later 253/256 lease design coordinates all endpoint opens; this merge does not claim that
expanded lease implementation. Cloud absence remains 503 `source_unavailable`.

The local session boundary verifies portable calibration source references against the
authenticated project's/account's private hardware state before opening a device. Missing or
invalid authorization returns 422 `relink_required`; changed bytes return 409 `source_changed`.
Relinking does not replace stored calibration values. Private USB serial hints reach only the
local driver input, never session responses; they are not confirmed-port permission. Other
transports do not receive a saved hint as a channel selector. Driver errors use portable
messages and type-only logging. A retired or inconsistent CONFIG graph identity cannot supply
runtime values; inconsistent live history returns 409 `config_conflict` without repairing it on GET.

The retained `repo_root` compatibility request field is not file-read authority: non-null values
return 422 without inspecting the path. The bounded parser/proposal flow accepts only explicitly
authorized `source_refs`, as detailed below; calibration values still require verified local
evidence and do not follow from a repository normalization declaration alone.

The unchanged telemetry packet uses per-part endpoint keys derived from configured bus bindings.
Signals not claimed by a validated unique part remain unresolved; do not select the first
ambiguous target. Invalidate positive resolver caches after binding/config/ownership/deletion
changes. No shared TelemetryPacket, LiveConnection, PacketSource or Focus contract changes.

## 7. Events and errors

Keep existing meaningful config/part/lifecycle/suggestion/proposal/import events; add
`hardware.entity_created {entity_id,kind,parent_id}`, `hardware.parent_changed
{part_id,previous_parent_id,parent_id,version}` and config version to config updates. Emit saved
and connection outcomes separately. Events contain IDs/counts/typed outcomes, never raw local
paths, calibration contents, credentials or another project's session details.

| HTTP        | Code                                                        | Meaning                                                                            |
| ----------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 401/403/404 | unauthorized / forbidden / not_found                        | Existing centralized auth and no-existence-leak behavior.                          |
| 409         | config_conflict / ownership_conflict / idempotency_conflict | Stale precondition or reused key with different operation.                         |
| 409         | config_upgrade_required / proposal_changed                  | Legacy write needs review or material proposal evidence changed.                   |
| 409         | device_busy / device_ambiguous                              | Endpoint leased or identity cannot safely resolve.                                 |
| 422         | validation_error                                            | Unknown fields, invalid reference/name/provenance/bounds or absent precondition.   |
| 403         | device_permission_denied                                    | Authorized project, but local OS access was denied; distinguish from role failure. |
| 404         | device_not_found                                            | Current attachment disappeared; saved context remains.                             |
| 503         | source_unavailable                                          | Required local runner is unavailable.                                              |

Unsupported protocol or missing calibration blocks the requested operation with a typed setup
reason; it does not prohibit saving hardware context. Model/compatibility/simulation actions
retain their existing budgets and confirmation gates; no motion/flashing is part of discovery.

## SOLUSDEV-262 — physical topology (implementation in progress)

`GET /robots/{robot_id}/topology` reads the project's live manual robot topology without writes.
Use centralized ProjectCtx. Wrong-project, deleted or absent robot returns 404. The response is
an envelope containing `{robot_id, nodes, edges, roots}`. Nodes reference live graph entity IDs,
with name, hardware role (brain/bus/device/part), optional brain kind (host/mcu/onboard), optional
category, known channel/software/presence facts and bounded evidence. Edges reference node IDs
and carry their known protocol/address. Unknown facts are null/absent, never guessed. Roots are
entry node IDs in the robot's projection. Imported parts retain their original graph identity.
The envelope is `{data: {robot_id, nodes, edges, roots}}`. Node keys are `id`, `name`, `role`,
`brain_kind`, `category`, `channel`, `software`, `presence`, and `evidence` (`by`, `source`).
Edge keys are `id`, `source`, `target`, `protocol`, and `address`. The renderer imports generated
`RobotTopology` aliases from the checked-in OpenAPI schema and validates responses at runtime.

This endpoint does not enumerate or open ports, create missing topology, mutate CONFIG, or
resolve ambiguous ownership. Stored legacy evidence is transformed by a snapshot-backed data
migration, and accepted new hardware writes maintain topology in their existing transaction.
Category records may remain as compatibility ownership storage, but are not topology nodes.
Runtime adapters consume the same preserved config/binding facts; a visual parent is never
permission to operate a device. Source extraction and manual changes remain reviewed proposals.

### SOLUSDEV-262 — declined link evidence

Rejected device/part-to-robot suggestions stay rejected for the same project, subject kind,
subject reference, target robot and canonical evidence set. Evidence ordering and duplicate
records do not make a new set. A changed evidence set may create a new proposal; neither
confidence display, regenerated reason wording nor a repeated scan reopens the old proposal.
Pending suggestions remain deduplicated. Persistence and decisions share the existing project
lock so concurrent rediscovery/decline cannot recreate a dismissed suggestion. No automatic
attachment or new route is introduced.

### SOLUSDEV-262 — reviewed local host topology

Two member-only, verified-user routes under `/robots/{robot_id}/topology/host`:

- `POST /propose`: body `{endpoint_id, machine_id, local_source_id, software_entity_id?,
  endpoint_brain_kind?}` where IDs are UUIDs, machine_id is bounded opaque identity, and
  endpoint_brain_kind is optional `mcu` (an explicit user declaration, not a USB inference).
  Returns `{data:{proposal_digest, host_name, endpoint_id, machine_id, local_source_id,
  software_entity_id, endpoint_brain_kind, topology, notes}}`. Topology previews the proposed
  host/USB nesting without writes. Digest binds current graph/config/source evidence and inputs.
- `POST /confirm`: same body plus `proposal_digest`, with UUID `Idempotency-Key`. Recompute all
  authority and evidence within the project lock, reject changed evidence with409
  `proposal_changed`, then persist and return `{data:RobotTopology}`. Use the existing 24-hour
  account/project-scoped hardware operation ledger. A replay performs no new mutation.

The exact caller user/team/project bridge session must match machine_id and the active,
caller-owned LOCAL source (its machine_id and user_id must also match). The source's canonical
local clone must exist. Optional software must be that local clone/folder or a same-source local code/file entity.
Remote code-host repositories are references, not the running control software. This association
is a user declaration of local control software, not proof of a running process. The local hardware provider must read its fixed,
private companion identity without creating files and match the session before associating its
currently enumerated USB endpoint. Missing provider/identity, cloud-only execution, stale source,
wrong endpoint or another user's source refuses; client machine_id alone grants no authority.

Host IDs are project+machine scoped; USB bus and existing endpoint IDs are stable. Persist
reviewed host edges separately from CONFIG-derived edges so config resync preserves the
association when its endpoint remains valid and removes stale connectivity when it changes.
No CONFIG subjects, calibration or runtime ownership changes. Shared hosts retain one identity;
per-robot software declarations must not overwrite another robot's evidence. MCU kind is only
set from explicit accepted declaration or exact board evidence. Host presence reports only
what is verified, never assumes the loop shim is installed. Emit graph change and a bounded
hardware topology confirmation event. No hardware writes are authorized by either route.

### SOLUSDEV-262 — authorized extraction review

`POST /robots/{robot_id}/topology/extraction/propose` accepts strict body
`{brain_id: UUID, source_ref: "source:<UUID>", source_kind: "firmware" | "host_config"}`.
Require centralized project membership, member role and verified user. The live brain must
belong to the requested robot projection. Resolve the reference from the caller's private
hardware-source state through the local runner; never accept paths or expand to a parent folder.

Return `{data: {robot_id, brain_id, source_ref, proposal_digest, extraction}}`, where extraction
is the bounded internal TopologyExtraction shape. Its source namespace is server-generated.
Digest binds project/account, robot/brain identity and versions, opaque source reference, verified
content digest, extraction kind and canonical evidence. Recheck scope and bytes after parsing;
stale evidence refuses. Absolute file paths and path-bearing port/calibration fields are not
returned, logged or emitted. No graph, CONFIG, calibration, operation-ledger or hardware writes.

Use existing portable failures: 404 not_found, 409 source_changed/proposal_changed, 422
relink_required/validation_error and 503 source_unavailable. Unsupported kinds/formats refuse;
successful empty extraction is distinct from invalid or unavailable input. There is no generic
extraction-confirm route in this slice.

### SOLUSDEV-262 explicit extraction acceptance

POST `/api/v1/projects/{project_id}/hardware/robots/{robot_id}/topology/extraction/confirm`
uses centralized ProjectCtx + verified member and the same authorized one-file acquisition as
propose. Strict request extends ExtractionRequest with proposal_digest, operation_id(UUID),
selections:[{row_index:int>=0,name:string1..120,entity_id?:UUID}] (1..256). Each index is unique.
Recompute source bytes and proposal under the project lock; mismatch409. Referenced retained
entity must belong to this robot's current topology and project. No auto-assignment from names.
A new selection creates a nonoperational evidence node; explicit retained identity adds evidence
without replacing it. Source evidence never silently changes CONFIG/calibration or starts I/O.
Store reviewed rows and typed evidence-only graph relations to the scoped brain, with exact source
namespace/digest and user provenance. Canonical operation replay returns the same IDs; changed
body with reused operation ID409. Response {robot_id,brain_id,proposal_digest,entity_ids,created}.
Emit identifier-only scoped graph event after commit. Empty extraction is displayed, not accepted
as invented devices. CONFIG projection resync preserves independently reviewed evidence nodes.

Presence preparers are provider-owned internal capabilities (not client-supplied executables).
Their immutable result carries source UTF-8, firmware bytes, source/binary SHA256, bounded profile
and observed connection identity. Preparing is side-effect-free on hardware; applying is exposed
only as a registered confirmation-required SOL tool. Initial API/brain-card integration is added
against these concrete preparers, not a placeholder flash acknowledgement.

### SOLUSDEV-262 local presence preparation and gated flash

Provisioned onboard companion fixture/runtime seam: `POST /api/v1/projects/{project_id}/hardware/companion-deployments/prepare`
accepts only `{target_id:UUID,artifact_id:UUID}` and requires a verified project member.
Returns 201 `{plan_id,target_id,artifact_id,artifact_sha256,target_version,status:prepared}`.
It is unavailable (503) unless the desktop/local host explicitly supplies a scoped deployment
service factory; the cloud/default application never opens SSH. The provider resolves the target
for the current project/user; request bodies cannot specify hosts, paths, credentials or commands.
Only retained, caller-owned, project-scoped offline bundle artifacts from a trusted bundle builder
are eligible. A system graph plan binds the creator, target version, host authority and byte digest.
Registered `hardware.deploy_companion({plan_id})` requires complete central confirmation. Preview
includes target, instance, version, bundle digest, prerequisite service enrollment and restart.
Execution revalidates all authority, persists uncertainty before remote work, and requires a fresh
authenticated companion handshake before success. Attempted plans never retry automatically.
The initial provider requires `/usr/local/libexec/solus-companion-deploy.py`, a pre-enrolled
`solus-companion.service`, and private `~/.solus/companion-deploy` state. Bare-target bootstrap and
live SSH are deferred; injected SSH/helper fixtures establish only software behavior.

Existing-firmware integration uses a separately selected authorized LOCAL source and an exact
existing `.ino` path from its manifest. The offer displays include/setup/loop telemetry snippets
for explicit numeric variables, channel names, units and existing baud. It requests a complete
machine-file diff with `force_confirmation:true`; it never treats a hardware `source:<UUID>`
reference or a connected remote repository as a machine workspace grant. Serial conflicts,
ambiguous anchors or inaccessible source files refuse the offer; no flash or loop execution follows.

The presence base `/api/v1/projects/{project_id}/hardware/robots/{robot_id}/brains/{brain_id}/presence`
also supports a reviewed wiring workflow. All routes require a verified project member:

- `POST /wiring/propose`: `{profile_id,mode:typed|schematic|probe,wiring?:[{channel,pin,kind:analog_input|digital_input}],source_id?:UUID,run_id?:UUID}`.
  At most 16 declared inputs; typed mode requires explicit declarations. Schematic mode reads
  only a visible project electrical source; probe mode reads only a retained project run for
  this robot/device. Source and run observations remain evidence, never guessed drivers.
  Returns `{proposal_id,digest,profile_id,mode,wiring,observations:[{detail,confidence}],unresolved,status:proposed}`.
- `POST /wiring/{proposal_id}/accept`: `{digest}` rechecks the same actor, target CONFIG,
  source/run evidence and proposal digest. Returns `{proposal_id,digest,status:accepted}`.
  Acceptance persists graph evidence attached to the brain; no transport opens and no CONFIG
  part or pin ownership is invented. Stale evidence returns 409; inaccessible evidence returns 404.
- Existing `/prepare` adds `kind:topology` and `wiring_proposal_id:UUID`. That kind requires
  a current accepted proposal, revalidated during compile and again at flash confirmation.
  Supported inputs generate named readings; an explicitly accepted empty proposal generates
  heartbeat only. Unsupported/I2C observations remain unresolved, never fabricated devices.

Provider profiles own pin validation: Uno A0–A5, Nano A0–A7, digital D2–D13. Serial pins,
duplicate channels/pins and output modes are refused. Firmware supports bounded status queries
and input telemetry, with no actuation. Probe analog values cannot establish attached hardware;
zero I2C responders cannot establish empty wiring. The erase preview always warns that a linked
repository may contain the existing sketch. A reference repository is not local control code.

`GET /api/v1/projects/{project_id}/hardware/presence/profiles` returns bounded installed provider
profiles with display labels and availability; verified member only. `POST /hardware/robots/
{robot_id}/brains/{brain_id}/presence/prepare` accepts {profile_id,kind:heartbeat|probe,channel}
(strict bounded fields). It resolves the brain's accepted connection, captures current enumerated
USB identity, refuses boards with incompatible vendor profile or accepted actuator bus, and
compiles without device writes. Returns {plan_id,source,source_sha256,binary_sha256,target,profile,
status:prepared}; source/binary artifacts are retained, plan graph node references robot/brain.
Unavailable compiler/profile returns explicit503; no fake prepared record. No native paths accepted.

Registered tool `hardware.flash_presence` accepts only {plan_id:UUID}, requires_confirmation=true.
Registry is rebuilt through get_sol_registry with requesting user/project, artifact store and the
local provider. No raw registry invocation route is added. Preview reads the exact retained source/
binary digests and fresh target snapshot; includes full source, binary SHA256, profile, target,
erase warning. Source/private plan creation identity is checked. Decision revalidates plan status,
artifact bytes, graph binding and USB identity, and obtains machine-wide exclusive advisory serial
ownership before upload; device-in-use fails before upload. The uploader re-resolves immediately
before opening. Successful result marks flashed; pre-write failure unchanged; interrupted/error
write unknown. No automatic resume or retry of an unknown flash. Existing central approval log
records decision; scoped presence event records IDs/status/digests only. Serialless QA autoapproval
remains forbidden. The initial provider is local dev only; cloud exposes no local flash capability.

Transport-only MCU acceptance: the existing detection confirm request adds explicit
`connection_only:true` (defaultfalse). Only a freshly revalidated USB identity with no recognized
driver/rows is eligible. Accepted rows must be empty. Persist identity + an empty nonoperational
CONFIG and topology; firmware/protocol stays unknown and no session starts. This explicit action
lets an unprogrammed MCU reach the presence preparation card without inventing a driver. Existing
robot/identity conflicts and project operation replay safeguards apply; it never replaces an
operational configuration or flashes hardware. UI labels this action Add MCU connection and
shows the existing firmware-unknown warning.

### SOLUSDEV-262 retained-part rediscovery

When a device binding is missing, an exact retained part identity may support a rebind suggestion
without requiring every observed bus address to have been accepted previously. A candidate must
have one unambiguous canonical robot owner, membership in that owner's retained CONFIG, and a
matching fresh device reference and bus address. Names, model similarity and unmatched addresses
are not identity evidence. Acceptance preserves the existing partial part/calibration map and does
not create parts for other responding addresses. Conflicting owner evidence produces no suggestion.

### Explicit CAD/part link review

`POST /hardware/parts/{part_id}/suggestions` requires verified project membership with member
role. It accepts no body and returns the existing bounded suggestion list envelope. It recomputes
only confirmed canonical/same-identity graph evidence from the unassigned source part to one
canonically owned robot part; names and shape similarity alone yield no suggestion. Foreign or
missing parts return 404. Existing decline evidence memory applies. Existing suggestion accept
revalidates the exact association and delegates to the normal part-attachment transaction; stale,
ambiguous or conflicting ownership returns a non-mutating refusal. No hardware session starts.
# Demo acceptance follow-up: authorized repo proposal evidence

### Schematic input evidence

In schematic mode each nonempty wiring row also identifies `component_entity_id`
and `connected_entity_id`, two distinct visible components in the selected source.
Both must have connector-owned `connected_to` edges to the same net. The selected
component edge must explicitly identify the requested logical pin, either in
`pins` itself or its exported `pin_functions` mapping (physical pin number to
declared logical function). Names, net labels, profiles and model suggestions are
not evidence of a pin assignment. Missing, ambiguous or mismatched evidence refuses
with `409 wiring_unproven`. Typed/probe modes cannot claim schematic component IDs.
The complete graph snapshot continues to bind acceptance and later compilation;
changed connectivity requires fresh review. Empty wiring remains a truthful empty
proposal. KiCad XML and S-expression exports preserve optional `pinfunction`
observations on these edges without inferring omitted names.

Stable-device propose and confirm accept optional `source_refs: string[]` (maximum 32,
unique opaque `source:<UUID>` references). Every reference is read through
`LocalHardwareSources` using the authenticated account and project, only on an installed
local runner. Raw `repo_root` remains rejected. Propose parses bounded verified UTF-8
bytes through registered private parser capabilities; no repository code executes and
no adjacent file or external calibration cache is read. Unknown runtime normalization
remains unknown. Matches retain opaque source provenance and content-bound identities.

Confirm revalidates all supplied source grants and content digests before reusing a
proposal. Proposal cache identity includes account, project, device and the evidence
snapshot; a different account, revoked grant or changed source cannot accept cached
repo names. A stale or missing source requires relinking/review, never a silent fallback.
The desktop supplies references from its account/project hardware source picker, never
local paths; source changes invalidate pending proposals. Existing requests without
source references retain wire-only behavior. Choosing a repo role is explicit and binds
to stable device identity, never its current tty path.
