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
return 422 without inspecting the path. The bounded parser/proposal expansion remains a later
task; verified shared calibration values can be used after explicit local relinking now.

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
