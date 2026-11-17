# Hardware ownership and onboarding route plan

**Last updated:** 2026-11-16 (SOLUSDEV-326 brain list; hardware not yet in the graph, §1a; device memory, "Not now", a declined device offer and `GET /expected`, and the plug-in inspection, §4; one session opener, §6). **Status:** integrated SOLUSDEV-251/252/250 route plan for
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
manual Physical Robot root, which contains the part directly (SOLUSDEV-326). **Ownership rule:**
a part is owned when one live manual (source-less) `contains` edge runs from a live manual
`physical_robot` root to it; every ownership read uses this one rule. A manual part also
records its robot in `attrs.robot_id`; provider facts are never rewritten. Robot category
nodes are retired (migration a32600000001) and are never a parent: a category id is 404. Parent
assignment changes manual `contains` edges only. It does not move provider containment,
transfer a transport, or change graph/configuration IDs. Arbitrary ownership nesting is
outside this cycle.

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
  config?: ConfigDraft | null
}
```

Names are trimmed, nonblank and at most 512 characters. There is no project-name, model-name or
library-name default. A robot cannot have a parent through this route. A part may omit
`parent_id` and remain unassigned; with a robot `parent_id` the robot contains it. No hardware
body takes a `category` (SOLUSDEV-326 P2 removed the field P1 accepted and ignored): one is an
unknown field, 422. `ConfigDraft` has the v2 fields with `entity_id` omitted (unknown if
supplied); the server allocates the UUID and adds it before full v2 validation. `component`
may be omitted/null.

The response is `{entity: Entity, config_entry_id: UUID|null, config_version: integer,
parent_id: UUID|null, ownership_version: integer}`. No config yields null/0. A robot creates its
root only. A part creates no robot root.
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
The creation digest still covers the retired field as `category: null`, so a key minted before
SOLUSDEV-326 P2 by a body without one replays rather than conflicting.

## 1a. Hardware not yet in the graph (SOLUSDEV-326)

Hardware SOL onboards may stay out of the workspace graph until its onboarder adds it. Two attrs
say so (no column): `in_graph: false` (absent means in the graph) and `onboarded_by: <user id>`.
They sit on the robot root, the manual (source-less) parts it contains, the topology nodes
derived for it alone (its brains and buses, its accepted evidence nodes) and the config nodes of
all of these. A manual part no robot contains carries its own. The reviewed host brain and bus,
shared by every robot on that machine, never carry them; neither do connector-owned entities.

**Who sees it.** Hardware out of the graph is visible to its onboarder only. Every read made in
a person's scope applies this rule through the read scope's viewer
(`GraphReadScope.viewer_id`, set for every request and SOL turn). That covers entities,
relations, subgraphs and the canvas snapshot; search, including a `.solus` CONFIG entry whose
configured entity is hidden; and SOL's context: neighborhood, anchors, retrieval (its semantic
cache is keyed by viewer), telemetry (the `get_telemetry` tool and the context's telemetry
section leave out a hidden entity's signals) and the project card, which lists a hidden robot on
its onboarder's card only. It covers Live Bench: focus and stream frames, and the project-wide
routes — `/bench/sessions` leaves out a session whose robot is hidden (its detail and stop are
404), `/bench/recent/{entity_id}` is 404, and `/bench/summary`, `/bench/telemetry-devices`,
`/bench/events` and `/bench/device-recent` leave out what lands on a hidden entity. A bench
run is seen by whoever sees its robot: `/bench/runs` leaves out a hidden robot's run, every route
naming one (detail, compare, findings, narrate, baseline, pin, stop) and SOL's `get_run` are 404,
the run's saved manifest is the 404 of an unknown artifact (`/artifacts/{id}` and its
`/content`), and the `.solus` document its finished run was filed as is left out of `.solus` and
search
([bench-runs](bench-runs.md)). And it covers the hardware reads (`/parts`, `/unassigned`,
`/robots/{id}/topology` and its nodes, `/robots/{id}/config`, `/entities/{id}/config`,
`/suggestions`) and the BOM widget (`/widgets/bom/rows` and `export.csv`; an edit is an overlay
every
member reads, so a row only hardware out of the graph holds is 409 to edit, and a delete names
only a row in the caller's view). The stored
`constraints/budgets` entry is every member's, so its mass and cost lines count only hardware in
the graph, whoever's change triggered the recompute. For anyone else, a hidden robot or part is a
404 on the hardware and entity
routes that name it, in the path or in the body (an attach's `entity_ids`, a config's bus-map
`part_entity_id`), and as a bench focus, read or write, exactly like an unknown id. A robot's
topology leaves out a node the reader cannot see. A config names only parts everyone who can see
it can see, so no config read needs a filter. The writers hold that: a part out of the graph that
its onboarder wires into hardware in the graph joins the graph with the write (it keeps its
onboarder; one `hardware.added_to_graph` per part), and so does what its own config wires, all the
way down. Only the part's onboarder can make it join, whatever the read scope. Wired into
hardware out of the graph, it must have that hardware's onboarder. Anything else is 409
`conflict` naming no part ("This wires hardware a teammate hasn't added to the graph yet. Ask
them to add it to the graph first."), reachable only in the system view. And
hardware stays in the graph while a config someone else can see names one of its parts (`PUT
…/graph` below). The driver input a session opens with is never filtered. A connector's part never
carries the
keys, but the hidden robot that contains one is still its onboarder's: for anyone else `/parts`
lists that part with `parent_id: null`, and changing its parent is 404 (never a 409 that names
the robot). A suggestion whose robot the caller cannot see is left out of the list and of the
device and CAD propose responses, and deciding it is 404.
The onboarder sees their hardware everywhere except on the Workspace canvas
([workspace-navigation](../architecture/workspace-navigation.md)).

**What keeps working.** Telemetry resolution never filters by viewer, and its cache is not keyed
by one. A bench session's pump, tap and window evaluator run in the system view, whoever started
the session, and so do a run capture's checkpoints. Findings, runs and Live Bench sessions
keep working on hidden hardware. Accepted residue: findings and activity rows about hidden parts
stay readable by teammates; hardware stays hidden if its onboarder leaves the project (no admin
restore path); a refusal to take a part out can tell its onboarder that a teammate's
hardware out of the graph is wired to it, never which; and a hidden run's sensor files (the
artifacts its manifest references) stay readable by id to members, though their ids reach only
the uploader and the hidden manifest.

**Who writes the keys.** Solus alone. The creators that onboarding uses take them from Solus
callers, never from a request body; the default is in the graph with no onboarder. A part
created on a robot (a sourcing candidate selected into it included) takes the robot's keys. An
existing part attached to or moved onto a robot in the graph keeps its own onboarder, never the
robot's, so putting a teammate's part on your robot never makes it yours; if it was out of the
graph it joins, with what its config wires. On a robot out of the graph it takes the robot's
keys, which hides it: only the part's own onboarder may do that, and never while a config
someone else can see names it: 409
`conflict` saying what to do ("Add <robot> to the graph first, then put <part> on it.", or
"Remove it from <robot>'s wiring first."), before anything is written. A part out of the graph
wired into hardware in the graph joins the graph (above). A config node takes its subject's,
and `sync_topology` stamps the robot's own nodes. A bench run takes its robot's keys at every save,
and so does the `.solus` document a
finished run is filed as. A part taken off a robot keeps what it had. The generic routes
(`POST`/`PATCH /entities`, `POST /hardware/entities`) refuse `in_graph`/`onboarded_by` as
unknown fields (422). A connector sync keeps them, and a connector's own properties can neither
set nor clear them.

| Method | Path                          | Request / result                                                    |
| ------ | ----------------------------- | ------------------------------------------------------------------- |
| PUT    | `/entities/{entity_id}/graph` | `{in_graph: boolean}` → `{entity: Entity, in_graph, updated}`; 200. |

The body is strict (a non-boolean or an unknown field is 422). The route needs the member role
(a viewer gets 403) and a verified email (403); a non-member gets 404. The entity must be
visible to the caller, else 404. It must be a live manual robot root or a manual part that no
robot contains. A robot's part is 409 `conflict` (it moves with its robot), and so is a
connector-owned entity. A robot moves together with its own hardware, as listed above, and with
its bench runs and their `.solus` documents. Adding never changes a part's onboarder: a part on
the robot keeps its own, and one out of the graph joins only as the caller's (409 otherwise).
Either way the project's environment spec is recomputed with the same commit. Only the recorded
onboarder takes hardware out: anyone else gets 403 `forbidden` ("Only the person who onboarded this
hardware can take it out of
the graph."), hardware nobody onboarded included, which therefore stays in the graph. A robot
holding a part someone else onboarded (or nobody did) stays in: 409 `conflict`, "<part> on
<robot> isn't yours to take out of the graph. Take it off <robot> first." Hardware stays in
while a config someone else can see names one of its parts (an in-graph robot's, or one
out of the graph that another member onboarded; its own robot's config moves with it): 409
`conflict`, "<part> is wired into <robot>, which is in the graph, so it has to stay in the
graph. Remove it from <robot>'s wiring first.", or, for hardware the caller cannot see, "<part>
is wired into a teammate's hardware that isn't in the graph yet. Ask them to remove it from
their wiring, or to add their hardware to the graph, first." `updated` counts the entities whose
keys changed, with the shared topology it restamps and the wired parts it adds; a request that
changes nothing returns 0 and emits nothing. Otherwise one data
event is written with the commit: `hardware.added_to_graph` or `hardware.removed_from_graph`
`{entity_id, kind: robot|part, count}`. One `graph.changed` (`entities_updated = count`) follows
the commit. SOL's tool (P2) calls the same `hardware.in_graph.set_in_graph` service.

A machine's `devices`, `dismissed` and `recent_commands` are its owner's alone: the entity
serializer leaves them out for anyone else, and no model-facing read carries them. The device
list (§4) tells each caller only their own "Not now" and, to the owner alone, when a device was
last seen.

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
conflict detail. A part the caller cannot see is the 404 of an unknown part, and a part out of the
graph wired into a subject in the graph joins the graph with the write (§1a). Imported
subjects receive a Solus-owned relation; only manual subjects may carry a `hardware_config_ref`
convenience attribute.

```text
HardwareConfigV2:
  schema_version: 2
  entity_id: UUID
  component?: PartConfig | null
  identity: [BrainIdentity]                  # ≤16, default []; SOLUSDEV-326
  bus_map: [{protocol, address, part_entity_id?, model?, brain?}]
  disambiguated_by?: "user"
  provenance: {dotted_path: {by: library|repo|user|sol|detected, source?}}

BrainIdentity:
  kind: host | mcu | onboard                 # default host
  binding?: {kind, binding, vid?, pid?}      # no last_seen_path; absent until bound
  via?: device_ref                           # another brain of this config
  protocol?: {driver_id, params}             # this brain's driver
```

A config lists its brains (SOLUSDEV-326). Bound brains have unique device refs; `via` names
another brain of the config and never loops. A bus row's `brain` is the device ref of the brain
it sits behind; null means the only brain and is 422 when there are several. Endpoints are
unique per (brain, protocol, address), so the same address on two brains is allowed. A body or
stored payload in the pre-326 shape (one `identity` object, a top-level `protocol`) is accepted
and read as the list (`[{kind: host, binding, protocol}]`, `[]` when it named neither), its
provenance paths moved with it; a list `identity` next to a top-level `protocol` is 422. GET
returns the list.

The stored v2 model is `EntityHardwareConfig`; the existing `HardwareConfig` v1 remains an
explicit runtime/legacy adapter type with exactly one identity: the legacy robot GET returns the
first brain's identity and protocol with every bus row (rows name their brain when there are
several), and drivers receive one v1 document per brain. The API-local models implement the shape and bounds in
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
version: nonnegative integer}` (no `category` since SOLUSDEV-326 P2). A parent ID is a live
manual robot root (anything else, a retired category included, is 404).
Compare expected current parent and entity version under lock; mismatch is 409
`ownership_conflict` with current parent/version. Null detaches. Return `{entity: Entity, parent_id: UUID|null,
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
connector-sourced parts (current eligible kinds: part, component, cad_part, assembly) that no
robot owns (§1 ownership rule). Provider containment does not hide an unassigned part. `all`
also includes assigned parts. No source account-wide catalog is returned.

Keep the existing compatibility routes while the renderer migrates:

| Method  | Path                                           | Compatibility behavior                                                                                                                                                                                                                |
| ------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET/PUT | `/robots/{robot_id}/config`                    | Resolve the same authoritative subject/config; GET is read-only. Legacy v1 output may be assembled; no second stored aggregate. PUT merges its one identity into the robot's brains by device ref and never drops one (SOLUSDEV-326). |
| POST    | `/robots/{robot_id}/parts`                     | Required user name, specs/lifecycle (no category); the robot contains the new part.                                                                                                                                                   |
| POST    | `/robots/{robot_id}/parts/{part_id}/lifecycle` | Update the part-owned component through the versioned config service; preserve identity/edges.                                                                                                                                        |
| GET     | `/unassigned?limit=&cursor=`                   | Alias for the unified unassigned query, including manual/retained parts.                                                                                                                                                              |
| POST    | `/robots/{robot_id}/parts/attach`              | Existing 1–64 IDs (no category); preserve part configs. IDs this robot owns skip; another robot's are 409.                                                                                                                            |

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
overwrite a newer authoritative frame or survive a project/account generation change. Each
project hears a list once per change; one that subscribes between changes hears it at its next
tick. An enumerated USB serial no binding can hold (whitespace, `/`, over 128 characters) is
treated as absent, so that device falls back to its port position (or to no binding) and never
blanks the list (SOLUSDEV-326).

**Device memory and "Not now" (SOLUSDEV-326).** The local API's machine node in the project —
`machine:<companion id>`, the companion identity of the host it runs on — remembers what it saw:
`attrs.devices` rows `{device_ref, identity_basis, headline, last_seen, present, state?}` (at most
64, most recent first; never a path). The watcher writes them when the list changes (the devices
present and those that just left are stamped with the change's time), never as a
`graph.changed`. A device that leaves keeps its row, so "Last seen 2 days ago" stays true.
`present` is whether the device is in the full list of that change — never inferred from what was
seen leaving, so a device unplugged while the API was down reads not present after the first
change it sees; a device notice (`MessageCreate.notice`, docs/api/API-implementation.md) asks it. `attrs.dismissed` maps a member's
id to the device refs they said "Not now" to (at most 64 each, oldest out). It survives app
restarts, unplugging, replugging and the companion registering the machine again, and only the
member's own DELETE clears it ("+ Add hardware" offers dismissed devices again). A machine the
project has not registered, or a host with no companion identity, remembers nothing.

**The plug-in path (SOLUSDEV-326 P2-T6).** A device that arrives is inspected before anyone
asks, and no model is called. When the watcher writes a change, every remembered device that is
plugged in now, bound by nothing the machine's owner may see (the holder `bound_to` below would
show them; hardware a teammate keeps out of the graph does not count, §1a) and not on the machine
owner's "Not now" list is owed an inspection, provided the owner reads the project's stream on
this machine at that moment: an inspection is the owner's alone, so a teammate's subscription or
an unregistered machine starts none. The row's `state` becomes `inspecting`; the API then runs the
same service as `hardware.inspect_device` (§4 "SOL's hardware tools": 0.5 s budget, the owner's
authorized sources, one `hardware.inspected` event) as the owner, one device at a time and outside
the tick, and writes `inspected`, `busy` (409 `device_busy`: someone holds the port) or `unknown`
(not listened to: opening the port would restart a board that was already running — that stays
SOL's approval card —, the device left, or the runner failed). An arrival can wait its turn behind
another's listen: the owner's "Not now" list is read again right before its port would open, and
a device dismissed in that wait is not opened, and the `inspecting` it waited under is cleared
(its `state` is null again, never left reading as still being identified). The readers are sent the
list again when it settles. A row keeps its `state` while the device stays plugged in; one that
leaves and comes back starts without one and is inspected again — a result heard before the
replug is never written onto the new arrival, which is inspected at the next tick. Nothing is
retried otherwise, except an `inspecting` left behind by a process that stopped or by a result
that could not be recorded (owed again at the next tick). The machine's owner is the member
whose canonical id `attrs.owner_user_id` stores exactly (`read_scope.owns_machine`'s rule): any
other spelling is nobody, so nothing is inspected. The inspection is kept like any other
(`inspection_id`, 30 minutes, at most 64) for the owner in that project. A device held only by
hardware the owner may not see is therefore inspected and reads exactly like one nothing holds
(`bound_to` null, the same `state`, an `inspection_id` in `hardware.list_devices`); adding it
later meets the bind refusal of §5, which names no holder.

Each `GET /detected` row, and each row of the watcher's frame, carries four annotations filled
by the API for its reader (the local runtime never supplies them):

- `bound_to: UUID | null`: the robot or part that binds the device. That is a holder a bind
  refuses (§5): the subject of the live config whose binding edge binds it (a board bound by its
  connection alone counts), or a robot whose stored brain names it with no binding edge (a
  config backfilled by revision a26000000002); else a part whose `external_ref` is the device
  ref. It is null when the reader may not see that hardware (§1a) or nothing binds the device.
- `dismissed: boolean`: whether THIS reader said "Not now" to it.
- `last_seen: string | null`: when this machine last saw it, for the machine's owner only (null
  for anyone else, or with no memory).
- `state: "inspecting" | "inspected" | "busy" | "unknown" | null`: the plug-in inspection of it,
  for the machine's owner only (null for anyone else, or when none was owed: the owner said "Not
  now", was not reading here, or may see what binds it — never because of hardware hidden from
  them).

The frame is per reader: every local subscriber of the project stream receives the frame built for
the person its subscription names. A pre-ADR-037 queue that names no one gets the in-graph view
with no dismissals and no memory.

| Method | Path                  | Request / result                                                      |
| ------ | --------------------- | --------------------------------------------------------------------- |
| POST   | `/devices/dismissals` | `{device_ref}` → `{dismissed: [device_ref]}`, the caller's list; 200. |
| DELETE | `/devices/dismissals` | Clears the caller's list → `{dismissed: []}`; 200.                    |

`device_ref` matches the device-ref grammar (`<transport>:<binding>`, at most 160 characters); an
unknown field is 422. Both routes need the member role (a viewer gets 403, a non-member 404,
no token 401) and act on the caller's own list on THIS API's machine: no local runner is 503
`source_unavailable`; a host with no companion identity, or a machine this project never
registered, is 409 `machine_unknown`. Data events: `hardware.device_dismissed {device_ref}` and
`hardware.dismissals_cleared {count}`. Neither publishes a live frame; the response is the
caller's list.

**Declining a device offer is "Not now" (SOLUSDEV-326 P3 amendment).** When the decide route
(`POST /sol/confirmations/{id}`, body still `{decision}` and nothing else) REJECTS a parked
`hardware.inspect_device`, `hardware.add_parts` or `hardware.add_connection` row, the device its
STORED arguments name (`device_ref`, or `proposal.device_ref`; the device-ref grammar, at most 160
characters) joins the caller's own "Not now" list on this API's machine through the same service
as `POST /devices/dismissals`, with the same `hardware.device_dismissed {device_ref}` event. Each
of the three tools says which device its stored call was about (a duck-typed, pure
`declined_device(stored_args)`, read like `needs_confirmation`); no other tool has one, so no other
card dismisses anything. It is best effort and runs in a savepoint of the decision's transaction:
a caller below the member role, no local runner, a host with no companion identity, a machine
this project never registered, or any failure records nothing more, logs ids only and never
changes the decision or its response. Approving, an expired card and a card already decided
dismiss nothing. Editing a card's field dismisses nothing either: an edit never reaches the
decide route — it is the person's answer turn (`MessageCreate.answer` with the card's id,
`choice: 0` and the new value as `text`; docs/api/API-implementation.md), which expires the card
undecided, so the device is offered again and no `hardware.device_dismissed` is logged.

**Described, not seen yet (SOLUSDEV-326 P3 amendment).**

| Method | Path        | Result                                                                      |
| ------ | ----------- | --------------------------------------------------------------------------- |
| GET    | `/expected` | `{data: {expected: [{name, what, robot_id, source}], sources, more}}`; 200. |

The Hardware page's "Described in your workspace, not seen yet" rows, from the one service
`hardware.expected_parts` reads (`hardware/expected_parts.py`): the planned (or partless) bus-map
rows of the caller's visible robots (library slots too), then `sensor_msgs/*` ROS topics, sketches
that include libraries and MCU symbols (`MCU_*` libraries).

- `name` / `what`: a planned row is its part's name (else its model, else `<protocol> <address>`)
  and its model (else `<protocol> <address>`); a topic is its name and message type; a sketch is
  its name and `uses <libraries>`; a symbol is its reference and its value (else its symbol).
- `robot_id`: the robot a planned row belongs to; `null` for what code and schematics describe.
- `source`: where the workspace says it — the robot's name for a planned row; a sketch's file
  name; otherwise the connected source's name, else `ROS code` / `sketch` / `schematic`.
- `sources`: the distinct `source` labels in row order, at most 8, for the collapsed row.
- `more`: rows left out of `expected`, which carries at most 64 (each kind is read 64 at most).

Every string is the workspace's own text and untrusted: one printable line of at most 80
characters, rendered as text. Any project member reads it, a viewer too (a non-member gets 404,
no token 401), always as themselves (§1a): a robot a teammate keeps out of the graph gives no
row, no `sources` label and nothing in `more`, and a planned row naming a part the caller may not
see is left out. It opens no port, needs no local runner, writes nothing and emits no event.

### SOL's hardware tools (SOLUSDEV-326 P2)

SOL reaches these services through in-process tools, not routes
(`agent/tools/hardware_onboarding.py`). They are registered for a turn bound to a person, and only
on an API that may watch its machine's devices: a local runner and `app_env` not `production`
(`device_watch.watcher_wanted`). A hosted API offers none, and SOL's system prompt then says
"Hardware tools run only on a local Solus API; this API is hosted". The prompt's sentence that a
graph write parks a card is said only when the card tools below are in the turn's registry; with
the reads alone (no live hub) it says adding hardware to the workspace is not available on this
API. Every read runs as the
requesting member through their bound read scope, so §1a holds: hardware a teammate keeps out of
the graph never appears, and a binding holder the member may not see is not named. Each tool has a
one-line `working` phrase for the `tool_call` frame, Solus's own words beside the next card. It
names a model value only when the tool's schema admits it, and then as one code chip
(`agent/cards.chip`): `inspect_device` names a ref its pattern admits (otherwise "the device"),
`read_evidence` names its source in fixed words and `search_library` names no query. Every answer
fits the prompt's result cap: rows left out are counted in `more`. A service's refusal reaches the
model as `not_found` (404), `unavailable` (409, 503), `invalid_args` only when the service says the
request itself was invalid (`validation_error`), and otherwise `tool_error`: a file the runner
cannot parse is never the model's arguments to fix.

| Tool (no card)            | Answers                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hardware.list_devices`   | `GET /detected`'s rows for the caller (no port opened) as `{device_ref, headline, level, identity_basis, state, bound_to, last_seen, inspection_id}`; `state` is `new`, `bound`, `dismissed`, `unidentified` or, for the machine's owner only, `gone` (memory).                                                                                                                                                                                                                     |
| `hardware.inspect_device` | `{device_ref}` → `{inspection_id, device_ref, headline, level, tone, summary, driver_id, identity_basis, stream, repo_matches, question, port_repair, rows: [{id, address, model, function, from}], more}, heard_s_ago?}`.                                                                                                                                                                                                                                                          |
| `hardware.expected_parts` | `{robot_id?}` → `{expected}`: planned (or partless) bus-map rows of robots the caller may see (library slots too), MCU symbols (`MCU_*` libraries), `sensor_msgs/*` ROS topics and the libraries sketches include; with `robot_id`, that robot's rows only.                                                                                                                                                                                                                         |
| `hardware.list_parts`     | `{robot_id?}` → `{robots: [{id, name, in_graph, device_ref, connection}], parts: [{id, name, kind, robot_id, in_graph, device_ref}], complete}` (`ownership.list_parts`, at most 100 parts).                                                                                                                                                                                                                                                                                        |
| `hardware.read_evidence`  | `{source: firmware \| host_config, robot_id, brain_id, source_ref}` → the extraction's rows, notes and `proposal_digest` (`TopologyProposalService.propose`, read-only); without `source_ref`, the caller's authorized `{source_ref, suffix}`, listed from their local state with no file opened (one that moved or changed is still listed; reading it refuses). `{source: cad, part_id}` → the CAD link's candidate robot or null (`cad_association`, which files no suggestion). |
| `hardware.search_library` | `{q, kind?, limit?}` → the library's hits `{kind, id, name, manufacturer, summary}`.                                                                                                                                                                                                                                                                                                                                                                                                |

`hardware.inspect_device` interrogates with the 0.5 s budget, as the caller in this project (their
own session's port is listened to), with every source the caller authorized here
(`LocalHardwareSources.source_refs`, at most 32; one that moved or changed is left out, and so is
one the runner's parsers reject: the runner parses each source alone before the port opens, so a
file it cannot parse never fails an inspection, nor comes after an approved restart). Its tool
timeout is 45 s, above the proposal's own 30 s wait. It writes nothing to the graph and files no
link suggestion: the proposal, bound repo configs excluded, is kept in-process for the caller
under a fresh `inspection_id` (30 minutes, at most 64 kept) for a later card to stamp. The plug-in's
inspection of a device (above) answers the caller's first call for it, once: while it is the
caller's newest inspection of the device, is under 120 s old and has answered no call, the tool
returns it with `heard_s_ago` (whole seconds since it was heard) and opens no port (so no restart
card either) — the turn a device notice starts reaches its first card in two model calls. Every
other call listens, including a second one moments later ("check again" after powering a bus) and
any call after one the tool made itself. A busy
device is `device_busy`, and the tool says busy. Listening is free unless opening the port would
restart a running board (docs/architecture/hardware-onboarding.md "Serial owner"); then its
per-call `needs_confirmation` hook parks an approval card — "Approve: restart the board to listen",
"This restarts the board to listen to it: `<device_ref>`", "Restart and listen" / "Not now",
`resumes` true — and approval runs the stored call. A parked call is stamped
`restart_approved: true` (`stored_args`; stored-only, so a model that sends it gets
`invalid_args`), and only a call carrying it may restart a board: a call the gate let through on
the plug-in's inspection, which another turn then spent or which passed 120 s before it ran, is
refused `unauthorized`, retryable ("Listening now restarts the board; call
hardware.inspect_device again so the person can approve it."), with no port opened — the next
call parks the card. The ref is the device's own serial, so it is
one code chip with its own backticks removed (`agent/cards.chip`): it cannot close the chip and
write words outside it. Data event: `hardware.inspected` per
inspection (§7).

**SOL's hardware card tools (SOLUSDEV-326 P2-T5).** Six writes, each behind a card
(`agent/tools/hardware_cards.py`, `hardware_graph_cards.py`), registered beside the reads when the
turn's registry also has the app's live hub to publish through (`register_hardware_tools(hub=)`,
from `deps.get_sol_registry`). Each is gated statically (`requires_confirmation`, a complete
preview), resumes SOL after any decision (`card_resumes`), is never an owned routine and is on no
auto-run list, so Build never runs one by itself. Each acts as the requesting member through their
bound read scope: a robot, part, CAD body or library robot the member cannot see is refused like an
unknown id (`not_found`), before anything parks.

The card is an **offer** — these write the graph, never the hardware — in Solus's words, built from
the STORED arguments alone. When the call parks, `stored_args` (awaited, bounded like a preview)
normalizes the model's arguments, refuses what it cannot do with what to do instead (nothing
parks), and stamps beside them `shown`: what the card says, read now as the member (an existing
robot's name and whether it is in the graph, the parts evidence rows name, the link targets, the
library definition, what moves with a robot). `add_parts` and `add_connection` also stamp the
member's whole inspection (`proposal`), so approval never listens to the device again: it only
checks the device is still enumerated (else `not_found`, nothing written). `apply_evidence` reads
the member's authorized file once, when it parks (the digest and row indexes are checked then),
and stamps each kept row as the file said it (`evidence`); its preview never reads the file again,
and evidence that changed before approval is refused by the write, which proposes again and
compares the digest (`unavailable`, nothing written — the card is not stale). The model can never
send `shown`, `proposal` or `evidence` (unknown arguments, `invalid_args`). The preview renders
rows from the stored arguments after re-reading `shown` from Solus's own state — never the local
runner or a file — and refuses when it changed ("What this card shows has changed since it was shown. Nothing was applied; ask
again."), so a decision goes stale only when what the card says stopped being true. A card's
`field` mirrors the name it would write (shown only: an edit is the person's answer turn —
`MessageCreate.answer {question_id: <the card>, choice: 0, text: <the new value>}`,
docs/api/API-implementation.md — which expires the card without deciding it and never changes
the stored arguments; the decision body still takes a decision alone).

| Tool (parks an offer card)   | Arguments → what approval runs                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Card (title · primary)                                                                                                   |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `hardware.add_parts`         | `{inspection_id, target: {kind: new, name} \| {kind: existing, robot_id} \| {kind: none, name}, rows?: [{row_id, name?}] (default every row, at most 32), repo_config_id?}` → the inspection's rows as parts of a new robot out of the graph for the member, or of an existing robot (the parts take its keys), through `detection_service.confirm_inspected` (`confirm_proposal`; no session starts). When a repo config is used — the one `repo_config_id` names, or the inspection's only match — the write binds it to the device and takes part names and calibration from it, so the preview has a "Repo config" row (its label and calibration source) and the card body names it: two calls that differ only in the config show different cards. `kind: none` is a board streaming lines only: ONE part out of the graph, `external_ref` its device ref, one telemetry channel per picked column named from the evidence (the person's name, the stream's, the row's, else `ch<column>.value`), its connection in its own config (`detection_service.add_inspected_board`, the reviewed creator). | "Add 2 parts as a new robot" / "… to your robot" / "Add this board as a part" · Add                                      |
| `hardware.add_connection`    | `{inspection_id, target: new \| existing}` → a USB serial device nothing was identified on as a plain connection of the robot (`connection_only`); the enumerated identity must still match the inspection. A device other hardware already holds is refused before a card (`unavailable`, from a 409): "This device is already connected to <name>" when the caller may see the holder, else "… to a teammate's hardware that isn't in the graph yet", naming nothing (§1a).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | "Firmware and protocol are unknown" · Add as a connection                                                                |
| `hardware.apply_evidence`    | `{source: firmware \| host_config, robot_id, brain_id, source_ref, proposal_digest, rows: [{row_index, name, entity_id?}]}` (as `read_evidence` answered) → `TopologyAcceptanceService.confirm`, its operation id derived from the rows and digest. Each row is kept once, under a name no other kept row has (else refused, nothing parked). Changed evidence is refused.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | "Add 1 row of evidence to the robot" · Add                                                                               |
| `hardware.link_part`         | `{part_id, targets: [{entity_id, relation?: commands \| reads}]}` (at most 16) → a manual `same_as` from the hardware part to its CAD body or schematic component, or `commands`/`reads` from a code site (file, module, sketch) to the part (`write_edge`, confidence 1, `user_confirmed` evidence). A target not found (or not the member's to see), hardware, another kind, or a code site with no relation is named on the card and skipped: the result is `{linked, skipped}`. All skipped is refused.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | "Link this part to 2 design nodes" · Link                                                                                |
| `hardware.import_definition` | `{definition_id, robot_id?, name?}` → a platform as a new robot out of the graph for the member (`import_platform`), or a part into a robot they can see (`import_part_into_robot`; it takes the robot's keys).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | "Add a new robot from the library" / "Add a library part to your robot" · Add                                            |
| `hardware.set_in_graph`      | `{entity_id, in_graph}` → `in_graph.set_in_graph`, the route's own service (§1a). Already where asked, or taking out what someone else onboarded (`unauthorized`), is refused before a card. The card says what moves: the robot's parts, wiring nodes (the wiring it shares with other robots included, when adding) and bench runs, and — when adding — names the member's parts on other hardware that join the graph because the configs of what moves wire them (`in_graph.wired_hidden`, the closure `admit_wired` applies; a "Wired part on other hardware" row each, so a part wired later makes the card stale). A wired part that is not the member's to add is refused before a card, naming nothing.                                                                                                                                                                                                                                                                                                                                                                                          | "Add this robot to the workspace graph" · Add to workspace graph; "Take this robot out of the graph" · Remove from graph |

Every card's secondary is "Not now" and it carries a receipt for "Done so far" (`<robot>: 2 parts
added`). A text longer than the contract's bound (a 132-character device ref beside three part
names, a repo config and the port note) is cut to it, ending "…" and never through a code chip,
so a card tool's call always parks with its card (`agent/cards.fitted`). Guide mode adds one sentence (`more`). Data events reuse the routes' names:
`hardware.robot_confirmed` (add_parts and add_connection), `hardware.entity_created` (a lone
board), `hardware.extraction_confirmed`, `hardware.library_imported` and
`hardware.suggestion_created`, `hardware.added_to_graph` / `hardware.removed_from_graph` (written
by `set_in_graph` itself); link_part writes `hardware.part_linked {part_id, linked, skipped}`. A
write that changed the graph publishes one `graph.changed` after its commit.

The current stable-device `POST /propose` retains `{repo_root?: null}` for compatibility;
any non-null value is 422 before path inspection. It uses bounded device interrogation and
current project evidence. The selected sources are parsed before any port opens: one the parsers
reject is 422 `invalid_source`, with nothing listened to. Interrogation opens the port once and
re-rates it per candidate baud.
A device something else holds (a session, an inspection, an upload, another program) is
`409 device_busy` (§7), never a "no protocol recognised" proposal (SOLUSDEV-326; see
docs/architecture/hardware-onboarding.md "Serial owner"). There is no registry-absent unconfined
fallback. Proposal fields include summary/headline/tone, accepted-row evidence, optional stream
metadata, repo match choices and disambiguation. These remain evidence, not permission to fetch
private paths or replace saved calibration. Source tokens resolve only after explicit private
relinking.

Current `POST /confirm` retains `{target: {kind: "new", name?} | {kind: "existing", robot_id},
accepted: [{row_id, function_name?}], repo_config_id?, repo_root?: null,
start_session?: boolean, window_seconds?}`. A row names no category (SOLUSDEV-326 P2; one is
422): an unnamed row is named from the proposal, `<robot>-Motor-<address>` on a bus and
`address <address>` on a line stream, and the robot contains every accepted part directly
(SOLUSDEV-326). The inline UI supplies a nonblank user name for a
new robot and shows proposed rows before Add accepts them. It preserves existing entities and
writes independent v2 configs; no mutable part-config copy is stored on the robot. Unknown
accepted rows or unresolved config choices are refused. The bounded proposal cache can avoid
repeating interrogation, but confirm still validates current device presence: propose, unplug,
confirm within the cache lifetime returns `404 device_not_found` without creating a robot.
An already-bound device conflicts rather than creating another robot. The 409 names the robot
that holds the device's rows (`… is already part of robot <id> …`), or that a connection-only
confirm aimed at another robot finds holding the device (`Connection already belongs to robot
<id>`), only when the caller may see that robot and part (§1a); otherwise it says "other
hardware in this project". A bind refused under an accepted suggestion (§5, `bind_error`) follows
the same rule.

### Asynchronous session start (SOLUSDEV-260)

The confirmation request commits the robot, per-entity v2 configurations and a
`properties.connection` object before returning 201. Existing response keys remain;
when session start is requested `session_id` and `session_error` initially remain
null. The connection object is `{managed_by: "local_runtime", runtime_id: UUID, attempt_id: UUID,
status: "connecting", session_id: null, error: null}`. Its terminal status is
`connected`, `failed` or `disconnected`, with a session UUID only after successful
opening and a portable, path-free error when appropriate. With `start_session:false`,
no new connection attempt is scheduled. A connected robot of several brains (SOLUSDEV-326) also
carries `brains: [{device_ref, status: connected|unreachable, error}]` in brain order; a
one-brain robot's object keeps exactly the keys above. The coordinator opens through the same
shared opener as the bench route (§6), so a robot confirmed on another machine fails with
"This robot runs on another machine; connect it there."

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
`{kind:"new", entity_kind:"robot"|"part", name, parent_id?}` or
`{kind:"existing", entity_id, version}`. Each accepted row identifies `row_id`, and either a
required trimmed `name` for a new part or an existing in-project `entity_id` and expected version;
function suggestions are optional review inputs (robot categories are retired, SOLUSDEV-326).
Every newly materialized part, including library children, has a user-entered name. `accepted`
may be empty when saving context
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
service, supersedes sibling rows only after commit, and leaves prior config intact. A device
the robot does not have yet joins it as another brain (SOLUSDEV-326); a device another live
config in the project already binds (another robot's brains, a lone part's board) is refused
before anything is written, and a bind refused at any later step is rolled back. Either way
the decision stays `accepted` with `bound: false` and a `bind_error`, and the robot's config,
version and bindings are unchanged.

Retain library search/preview and `/library/platforms/{id}/import`, `/library/parts/{id}/import`.
A part import requires its user-entered `name`, accepts optional `parent_id`, and may remain
unassigned. Platform import requires the robot `name` and a name for every materialized
part, keyed by its definition row; reject missing/blank names. Both use Idempotency-Key and the
same creation transaction. Definition/model labels are preview data, not defaults for names.
Definitions remain curated data; vendor-specific parsing remains in plugins. Library imports
may produce link suggestions but do not auto-bind a detected device.

September 15 UI compatibility increment: the existing part import accepts optional `robot_id`
and `name`, retaining existing robot-targeted callers. Omitting `robot_id` requires an explicit
nonblank `name` and UUID `Idempotency-Key`; it creates one unassigned part and its independent
v2 component config with library provenance, without creating a robot. Replays return the same
entity/config IDs; changed input under the same key returns 409. Unknown fields remain rejected.
A `category` is one of them since SOLUSDEV-326 P2 (422); the replay digest still carries the
definition's own category, which P1 keyed it on for a body naming none, so a key minted before
P2 replays. A robot-targeted import adds a part the robot contains directly. The response remains
`{entity, config_entry_id}`. The full platform-child naming extension above is separate.

## 6. Bench session extension

Under `/api/v1/projects/{project_id}`, `POST /bench/sessions` accepts real-mode
`config: {provider:"hardware", entity_id:UUID}` for a saved connection owner, including a
controller/gateway part. Existing `{provider:"robot", robot_entity_id}` stays compatible.
Resolve and validate the owner's config plus referenced component configs before passing the
existing single-identity input to drivers; validate protocol parameters with the driver schema.
**One opener (SOLUSDEV-326).** Three start paths open a hardware subject the same way
(`hardware/local_runtime.py`): this route (`robot` and `hardware`), the confirm-and-connect
coordinator (§4) and the session an accepted device suggestion starts (§5).

1. **Host check.** A robot whose host was confirmed (`attrs.host_machine_id`) opens only on that
   machine. Anywhere else the route returns 409 `host_mismatch`, and the other two paths report
   the failure without opening anything.
2. **Brains.** The config is projected into one v1 document per brain (that brain's bus rows
   only, no `brain` key). The entry's private port hint applies to the first brain only; brains
   2..N get none.
3. **Opening.** Each brain this host can reach is opened. A brain with no device bound, no
   driver, or one reached through another computer (`via`) is not opened here. A brain that
   fails to prepare or open (for example 404 device_not_found) does not fail the session. These
   brains are listed on the session as `device.unreachable: [{device_ref, error}]` in brain order,
   with portable messages. If no brain opens, the session does not start and the first brain's
   error is returned (a one-brain robot behaves exactly as before).
4. **One session.** A robot is one session over all its brains: one cap slot, one tap, one
   window evaluator. The session's `device` names the first brain it prepared.

A part bound on its own (the `hardware` provider with a part) streams its own channels: its
component joins the driver input as a part keyed by itself. The session names the part as
`robot_entity_id`, so who may see the session follows the part, but no robot window evaluator
runs. Its config's first bound brain becomes the part's `external_ref` when the part has none (a
lone detected board is keyed by its device ref), so what the board streams resolves to it.
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

A part on two brains (SOLUSDEV-326) is reached at two keys, `<brain A>/<address>` and
`<brain B>/<address>`. `sync_topology` records both on the part as `attrs.ref_aliases`, and a real
session's resolution reads them beside `external_ref` in one query (an `external_ref` hit wins).
A part on one brain has no aliases and resolves exactly as before.

`GET /bench/device-recent` series and the bench stream's frame series may carry the channel's
`display` (plot|angle|orientation|video|scan|points|state|text; absent means plot) and `range`
`{min,max}` beside `display_role`. They come from the robot's config, through the robot
connection's `channel_display` device fact, keyed like the roles and read only for a device this
project's active session observed. Two sessions that disagree leave the channel undeclared. The
desktop chart spans at least `range`, converted into the unit it shows; a reading outside the
range widens the chart and is never hidden. A range is display only, never a motion bound.

## 7. Events and errors

Keep existing meaningful config/part/lifecycle/suggestion/proposal/import events; add
`hardware.entity_created {entity_id,kind,parent_id}`, `hardware.parent_changed
{part_id,previous_parent_id,parent_id,version}` and config version to config updates;
`hardware.added_to_graph` / `hardware.removed_from_graph` `{entity_id,kind,count}` (§1a);
`hardware.device_dismissed {device_ref}` / `hardware.dismissals_cleared {count}` (§4);
`hardware.inspected {device_ref, inspection_id, level, rows, repo_matches}` per SOL inspection
(§4, SOL's hardware tools); `hardware.part_linked {part_id, linked, skipped}` per approved
`hardware.link_part` (§4, SOL's hardware card tools). Emit saved and connection outcomes
separately. Events contain
IDs/counts/typed outcomes, never raw local paths, calibration contents, credentials or another
project's session details.

| HTTP        | Code                                                        | Meaning                                                                            |
| ----------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 401/403/404 | unauthorized / forbidden / not_found                        | Existing centralized auth and no-existence-leak behavior.                          |
| 409         | config_conflict / ownership_conflict / idempotency_conflict | Stale precondition or reused key with different operation.                         |
| 409         | config_upgrade_required / proposal_changed                  | Legacy write needs review or material proposal evidence changed.                   |
| 409         | device_busy / device_ambiguous                              | Endpoint leased or identity cannot safely resolve.                                 |
| 409         | machine_unknown                                             | This API's host has no companion identity or is not registered in the project.     |
| 422         | validation_error                                            | Unknown fields, invalid reference/name/provenance/bounds or absent precondition.   |
| 403         | device_permission_denied                                    | Authorized project, but local OS access was denied; distinguish from role failure. |
| 404         | device_not_found                                            | Current attachment disappeared; saved context remains.                             |
| 503         | source_unavailable                                          | Required local runner is unavailable.                                              |

`device_busy` (SOLUSDEV-326) comes from the local runner's serial owner: one holder per device.
It is raised by `POST /detected/{device_ref}/propose` and confirm's re-interrogation, a bench
session start (`serial`, `robot`, `hardware`) and the connect coordinator (its connection error
reads "The device is already in use."), and a presence flash. `details` is
`[{device_ref, holder}]`: `holder` is `session|interrogation|upload` only when the holder and the
caller are the same member of the same project, and `null` otherwise: for a teammate's holder
(their session or flash may be on hardware kept out of the graph and hidden from the caller,
§1a), another project's, or another program's. Sessions and a presence flash claim for their
project and the requesting member. Propose and confirm's re-interrogation pass no project or
member yet, so their `holder` is always `null`, and their interrogation is never named to
anyone. SOL's `hardware.inspect_device` passes both, so the caller's own holder is named to
them. A refused flash wrote nothing: its plan returns to `prepared` with outcome `unchanged`.

Unsupported protocol or missing calibration blocks the requested operation with a typed setup
reason; it does not prohibit saving hardware context. Model/compatibility/simulation actions
retain their existing budgets and confirmation gates; no motion/flashing is part of discovery.

## SOLUSDEV-262 — physical topology (implementation in progress)

`GET /robots/{robot_id}/topology` reads the project's live manual robot topology without writes.
Use centralized ProjectCtx. Wrong-project, deleted or absent robot returns 404. The response is
an envelope containing `{robot_id, nodes, edges, roots}`. Nodes reference live graph entity IDs,
with name, hardware role (brain/bus/device/part), optional brain kind (host/mcu/onboard), optional
category, known channel/software/presence facts, bounded evidence and an optional measured
`clock`. The parts the robot contains join the nodes; `category` is only a legacy label read back
(the re-pointed edge's `attrs.category`, else a manual part's own) and is never written
(SOLUSDEV-326). Edges reference node IDs and carry their known protocol/address. Unknown facts
are null/absent, never guessed. Roots are entry node IDs in the robot's projection. Imported
parts retain their original graph identity. The envelope is
`{data: {robot_id, nodes, edges, roots}}`. Node keys are `id`, `name`, `role`, `brain_kind`,
`category`, `channel`, `software`, `presence`, `evidence` (`by`, `source`) and `clock`
(`{offset_ms, jitter_ms, measured_at, method}` or null). Edge keys are `id`, `source`, `target`,
`protocol`, and `address`. The renderer imports generated `RobotTopology` aliases from the
checked-in OpenAPI schema and validates responses at runtime, including a present `clock`.

**A DAG (SOLUSDEV-326).** A node may have several parents: a part may sit under two brains (bus
rows on two brains), and a brain may be reached two ways (a `via` brain and a reviewed host).
The read refuses only a cycle (409 `topology_conflict`). A node's evidence is merged across all
its parent edges, deduplicated and capped at 32. The reviewed host facts (`software`,
`brain_kind`) are also merged across all its parents; per key, the first stated value in edge-id
order wins. The renderer draws a shared node once, under its first parent, with a cross-link for
each other parent. The same part twice on ONE brain is still ambiguous: a config write that
would derive it is refused with 409 `topology_conflict`. On a one-brain config, a row that leaves
its brain implicit and a row that names the brain are on the same brain.

**Brain kinds come from the config's identity items.** `sync_topology` runs with every robot
config write and derives one `hardware_brain` per bound item. Every bound brain's node id is
`uuid5(project, "hardware_topology_v1:endpoint:" + device_ref)`, whatever its kind, so ids stay
stable when a kind changes. An `mcu` item's node has `brain_kind` `mcu` and an `onboard` item's
has `onboard` (a robot computer, keyed on its binding). A `host` item is a host-driven endpoint
(the upgraded pre-326 default): it has no kind of its own, and it sits under the reviewed host
brain when one is attached. The config never mints a host node. Host nodes keep their own id,
`uuid5(project, "hardware_host_topology_v1:host:" + machine_id)`, and come only from the
reviewed host routes below. An item's `via` derives one `hardware_connected_to` edge from that
brain to this one, with the `via` leaf's provenance as evidence. Bus nodes are per
(brain, protocol). An unbound item derives no node. A config item's kind outranks a host
declaration (`endpoint_brain_kind`).

The onboard writer `topology.upsert_onboard_brain` (for P6's survey) writes the robot computer's
`onboard` identity item into the stored config, or replaces the same device's item. Rows the
config left implicit then name their brain. The config write derives the node. The writer then
records `facts` (`clock`, `software`) on the node, where every resync keeps them, because a sync
merges its own facts over the node's attrs. An unchanged item writes no config version. The
item's `via` may name any other brain of the config, whether the item is new or replaces one.
Nothing is written when the result would not validate. An unknown, self or circular `via`, a
malformed device ref, a 17th brain or an oversize document is 422 `validation_error` with the
reason. A robot whose only brain is unbound and owns implicit rows is 409 `config_conflict`
until that brain is bound.
`topology.clock_source(topology, part, device_stamped=, endpoint=)` names the brain whose clock
stamps a part's data (see `docs/contracts/telemetry-packet.md` §3).

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

**Per endpoint (SOLUSDEV-326).** A robot may have several USB brains on one host. An attach is
scoped to its `endpoint_id`. The robot → host and host → USB edges are shared, and each records
the set of endpoints it serves (`attrs.endpoint_ids`; pre-326 rows hold one `endpoint_id`, which
is still read). A second endpoint's confirm joins the same host and USB bus and keeps the first
endpoint's wire. Re-attaching an endpoint, to the same or another host, releases only that
endpoint's edges. A shared edge that still serves another endpoint is kept, pruned to the
endpoints it still serves. Config resync keeps a host edge while any endpoint it serves is still
a brain of the robot, and prunes the rest.

**`endpoint_brain_kind`.** This optional field is an explicit `mcu` declaration, recorded on the
USB → endpoint edge as overlay `brain_kind`. A later confirm that declares nothing keeps the
earlier declaration. A kind the config already states is never copied into the overlay. On read,
the config item's kind (`mcu`/`onboard`) wins. The declaration shows for a `host` item, which
states no kind.
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
ownership before upload; device-in-use fails before upload. Since SOLUSDEV-326 the upload also holds
the serial owner for its whole run, claiming for the plan's project and the requesting member, and
a device in use is `409 device_busy` (§7); a failed identity or wiring re-check stays
`409 presence_in_use`. The uploader re-resolves immediately before opening. Successful result
marks flashed; pre-write
failure unchanged; interrupted/error write unknown. No automatic resume or retry of an unknown
flash. Existing central approval log records decision; scoped presence event records
IDs/status/digests only. Serialless QA autoapproval remains forbidden. The initial provider is
local dev only; cloud exposes no local flash capability.

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
