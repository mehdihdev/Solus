# Workspace navigation API

**Last updated:** 2026-09-07. Approved amendments for SOLUSDEV-251/254 extend
SOLUSDEV-242. Target design; completion reports record implementation status.

Authority: `docs/architecture/workspace-navigation.md`, API.md §2.4, ADR-025/027.
Additive tier-1 route plan, approved direction from the combined Workspace request.
All routes use `/api/v1/projects/{project_id}`, the standard envelope and ProjectCtx.
Non-members receive 404; writes require MEMBER (viewer receives 403).

## Phase 1 — project-shared node positions

`GET /workspace-layout` returns `{version: 0, positions: {}}` until the first save.
Thereafter it returns `{version: integer, positions: {<entity UUID>: {x, y}}}`.
Coordinates use the navigator's world space with its center at (0,0).
Only live entities in this project are returned.

`PUT /workspace-layout` receives `{version, positions}` with the same shape. Unknown
fields are rejected, version is a nonnegative integer, and each x/y is finite and
between -100000 and 100000. At most 5000 positions may be submitted. Every entity ID
must name a live entity in this project (404 otherwise). The map replaces the saved
map after optimistic version comparison; stale version returns 409 `conflict` without
overwriting anyone's coordinates. The response includes the incremented version.
The project row is locked during a save, including first creation, so concurrent first
writes cannot both succeed. Storage is a project-owned `workspace_layouts` row with
project FK cascade, JSONB positions and integer version. This is separate from the
per-user widget layout and from connector entity properties.

Successful writes emit `workspace.layout_updated` with position count and version,
not entity content. This route never calls a provider or triggers synchronization.

## Existing graph reads

The navigator consumes paginated `GET /entities` and `GET /relations`, and selection
uses the existing `GET /graph?root=...&depth=1`. Navigation uses a retained complete
snapshot, rendering at most 24 cards per level; it does not increase graph traversal
depth or read from providers. Project detail validates the snapshot on a screen return,
with a five-minute TTL and explicit invalidation after graph mutations.

### Approved canvas/layout amendment (SOLUSDEV-254)

Initial generated positions are persisted once. A subsequent import adds only missing real
entity UUIDs; it does not rewrite earlier defaults. A pending save retains later moved-node
changes; stale-version recovery combines the user's changed positions with the latest server
layout only after explicit conflict resolution. Arrange/reset remains a user action. Ordinary
scroll/pinch/camera state does not call this route until an actual layout move needs saving.

If movable account group headers are implemented, extend the same GET/PUT payload with
`groups: {<group key>: {x,y}}` (default `{}`, maximum 256), separate from `positions` and under
the same version. Group keys are server-derived from provider plus proven provider account
identity, or distinct connection/source fallback where identity is unavailable. Validate every
key against project-visible source metadata; reject unknown/cross-project groups with 404. They
are never entity UUIDs and cannot be sent as Focus/entity IDs. Coordinates retain the existing
finite/range checks. Do not invent graph entities to persist header placement. This extension
must be reflected in the schema/model migration and generated clients before use.

### Integration display metadata (SOLUSDEV-254)

Existing connection/source responses add optional `account_name: string|null` alongside the
unchanged account_login/provider external identity. Persist a supplied AccountInfo.name from
the existing authorized provider response and mirror it to project sources; no extra provider
request/OAuth scope is implied. Missing names use an honest renderer fallback. Group by proven
identity, never the name. Owner-only connection catalogs continue to populate Add, while
project-scoped source metadata provides attached teammate groups without exposing their private
account-wide listings. Exact source attachment identity/matching remains unchanged.

## Phase 4 — Physical Robot instances

These implement the previously planned entity mutation paths in API.md §2.4 for
one supported manual subtype. Generic manual CRUD remains deferred. Existing
entity serialization and response envelopes apply; no new graph schema is needed.

- `POST /entities`: `{type: "physical_robot", name: string}` → 201 with the
  created root entity. Names are required, trimmed, nonblank and at most 512
  characters; unknown fields are rejected. Project/model names are not defaults.
  Each call atomically creates a new root, seven distinct `robot_category`
  entities, and seven manual `contains` edges. Categories use `category` keys
  `sensors`, `actuators`, `controllers`, `end_effectors`, `power`, `structure`,
  `wiring`, plus `robot_id` in properties. Containers have domain `project`.
  Root references may initially be null. Configurations are created and versioned
  through the hardware routes; clients cannot write convenience references directly.
- `PATCH /entities/{entity_id}`: `{name: string}` → updated root entity. Requires
  `If-Match: <integer version>`; names follow the creation validation.
- `DELETE /entities/{entity_id}`: requires the same `If-Match`; after concrete UI
  confirmation, returns `{deleted_entity_id, retained_part_ids: UUID[]}`. It
  soft-deletes the root, explicitly owned categories and containment edges only.
  Actual parts, their identity/properties, independent CONFIG entry IDs/values/provenance
  and unrelated relationships survive. Disable stale connection bindings; do not transfer
  endpoints automatically or recreate retained-part configs with defaults.
- `GET /entities?orphaned_from_robot=true`: existing paginated entity payload,
  limited to live parts formerly owned through a deleted manual robot/category
  containment edge and not owned by another live robot. This retained evidence
  makes the prompt persistent across reloads. Service containment does not hide
  an orphan from this read. Part properties are never rewritten to flag orphans.

Mutation requires centralized ProjectCtx and MEMBER role. A foreign, deleted or
unknown entity returns 404. Connector/fingerprint entities, `.solus` nodes and
other manual kinds return 409 for these mutations. Allow only roots whose kind
is `physical_robot`, origin is exactly `manual`, and source_id is null. Lock the
live project, reread the entity, and compare its version before writes. Missing
or malformed If-Match returns 422; a stale version returns 409 `conflict` with
the current version/name. Successful mutations increment the root version.

`PhysicalRobotService.create` is the transaction-scoped robot/category creation hook used by
manual and reviewed hardware creation. Every accepted operation creates an independent
instance with the required supplied name; the outer hardware service handles idempotency.
It does not call providers or commit. New generic hardware creation, part configuration,
assignment and unified retained/unassigned reads use [hardware.md](hardware.md) §§1–3. Existing
robot routes remain compatibility adapters; they cannot restore implicit/default naming or
robot-owned copies of part config.

Project detail adds `graph_updated_at: ISO timestamp | null`, the greatest graph
entity/edge modification time including soft-deleted rows. Snapshot validation
includes this stamp so a rename invalidates cached names even with equal counts.
After commit, manual mutations publish existing `graph.changed` hints with
`source_id: null`, `sync_id: null` and advisory counts. Metadata-only creation,
rename and removal events are recorded; names and part contents are omitted.
