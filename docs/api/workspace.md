# Workspace navigation API — SOLUSDEV-242

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

Subsequent phases amend this plan before adding node mutation or cache-only surfaces.

## Phase 4 — Physical Robot instances

These implement the previously planned entity mutation paths in API.md §2.4 for
one supported manual subtype. Generic manual CRUD remains deferred. Existing
entity serialization and response envelopes apply; no new graph schema is needed.

- `POST /entities`: `{type: "physical_robot", name?: string}` → 201 with the
  created root entity. An omitted name uses the project's name. Explicit names
  are trimmed, nonblank and at most 512 characters; unknown fields are rejected.
  Each call atomically creates a new root, seven distinct `robot_category`
  entities, and seven manual `contains` edges. Categories use `category` keys
  `sensors`, `actuators`, `controllers`, `end_effectors`, `power`, `structure`,
  `wiring`, plus `robot_id` in properties. Containers have domain `project`.
  Root properties contain `hardware_config_ref: null` and `transport_refs: null`;
  these references cannot yet be supplied or edited by the client.
- `PATCH /entities/{entity_id}`: `{name: string}` → updated root entity. Requires
  `If-Match: <integer version>`; names follow the creation validation.
- `DELETE /entities/{entity_id}`: requires the same `If-Match`; after concrete UI
  confirmation, returns `{deleted_entity_id, retained_part_ids: UUID[]}`. It
  soft-deletes the root, explicitly owned categories and containment edges only.
  Actual parts, their identity/properties and unrelated relationships survive.
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

`PhysicalRobotService.create(project_id, name=None)` is the transaction-scoped
creation hook for later R2 hardware detection. Every invocation creates an
instance; it is not a project singleton. It does not call providers or commit.

Project detail adds `graph_updated_at: ISO timestamp | null`, the greatest graph
entity/edge modification time including soft-deleted rows. Snapshot validation
includes this stamp so a rename invalidates cached names even with equal counts.
After commit, manual mutations publish existing `graph.changed` hints with
`source_id: null`, `sync_id: null` and advisory counts. Metadata-only creation,
rename and removal events are recorded; names and part contents are omitted.
