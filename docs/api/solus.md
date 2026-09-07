# solus.md — The project-level `.solus` route plan

**Ticket:** SOLUSDEV-240 (WORKSPACE W1), branch `SOLUSDEV-240-graph-workspace`.
**Status:** IMPLEMENTED with the ticket (tier-1 route plan, ADR-032 — the MR review is the
approval gate).
**Authority:** DECISIONS.md ADR-034 (amendment 2026-09-05: the server-stored project layer),
ADR-027 (amendment 2026-09-05: the `project` domain), ADR-025 (project scoping), CLAUDE.md §7
(tenant isolation, uploads, ingested text is data). Upload semantics: [artifacts.md](artifacts.md).
**Wireflow:** `docs/wireflows/workspace.md`.

## 1. What it is

Every project gets a `.solus` at creation: one `graph_entity` (`kind="solus_config"`,
`domain="project"`, `origin="manual"`, name `.solus`) and five sections of entries:

| key        | label            |
| ---------- | ---------------- |
| `hardware` | Hardware configs |
| `details`  | Project details  |
| `errors`   | Error logging    |
| `docs`     | Documentation    |
| `code`     | Code environment |

The `.solus` is **configuration, not a second store for graph facts** — parts live in the graph;
their configs live here. An imported file is an `artifacts` row marked `retained` (exempt from the
TTL sweep) wrapped in a `document` graph node (`domain="project"`) that hangs off the `.solus`
node through a `references` edge, so Impact and the focus engine reach it through the one
traversal.

### SOLUSDEV-242 Phase 2 amendment

The approved Workspace spec replaces the separate panel with real navigation nodes.
Each project has five `solus_section` entities (`domain="project"`, `origin="manual"`),
with `properties.section` equal to the stable key above and a `.solus → section`
`contains` edge. Every live entry has an `entity_id`: imported artifacts retain their
existing `document` identities; text/SOL entries use `solus_note`, or `solus_error` in
the errors section. Entry-node properties carry `solus_entry_id` and `section`;
the complete text remains in `solus_entries`. A short text-derived display name is
allowed, but the node is not a second authoritative text store. Editing updates that
display name and preserves entity identity.

Every entry has a `section → entry` `contains` edge. Existing `.solus → document`
`references` edges remain so Impact retains its direct traversal. Root, section and
entry creation is serialized per project and idempotent. Project creation installs
the hierarchy. A data migration backfills existing projects and live entries without
replacing their IDs, artifact retention, or bytes; GET self-healing remains a fallback.
No additional HTTP route or shared contract is introduced. GET's shape is unchanged;
text/SOL entries now return their real `entity_id` instead of null. Existing limits,
authorization, events and SOL never-raises/confirmation behavior remain authoritative.

Delete removes the entry's graph identity and edges for every entry kind; only an
artifact entry deletes stored bytes. Deleting any entry cannot remove its section or
another entry. The renderer reuses W1 handlers on section/entry context menus, refreshes
the graph after all mutations, and removes the panel implementation completely.

All routes resolve through `ProjectCtx` (non-member → **404**, no existence leak). Reads need a
resolvable project; writes need the `member` role (viewer/share-only → `403`).

| Method | Path                                                     | Purpose                                 | Success |
| ------ | -------------------------------------------------------- | --------------------------------------- | ------- |
| GET    | `/api/v1/projects/{project_id}/solus`                    | The node id + every section's entries   | `200`   |
| POST   | `/api/v1/projects/{project_id}/solus/{section}/entries`  | File typed text or an uploaded artifact | `201`   |
| PATCH  | `/api/v1/projects/{project_id}/solus/entries/{entry_id}` | Edit a text/SOL entry                   | `200`   |
| DELETE | `/api/v1/projects/{project_id}/solus/entries/{entry_id}` | Remove an entry (and its document node) | `204`   |

## 2. GET — read

Also **self-heals**: a project created before this ticket has no node; the first read creates it.

```json
{
  "data": {
    "entity_id": "019f9a01-…",
    "sections": {
      "hardware": [],
      "details": [
        {
          "id": "019f9a02-…",
          "section": "details",
          "kind": "artifact",
          "author": "user",
          "text": null,
          "name": "FSAE Rules 2027.pdf",
          "artifact_id": "019f9a00-…",
          "entity_id": "019f9a03-…",
          "media_type": "application/pdf",
          "size_bytes": 2748812,
          "created_by": "019ebe5b-…",
          "created_at": "2026-09-05T10:12:44.101Z",
          "updated_at": "2026-09-05T10:12:44.101Z"
        },
        {
          "id": "…",
          "section": "details",
          "kind": "text",
          "author": "user",
          "text": "48 V bus",
          "name": null,
          "artifact_id": null,
          "entity_id": "019f9a04-…",
          "media_type": null,
          "size_bytes": null,
          "created_by": "…",
          "created_at": "…",
          "updated_at": "…"
        }
      ],
      "errors": [],
      "docs": [],
      "code": []
    }
  }
}
```

`kind` is `text` (typed by a person), `sol` (filed by SOL via `add_solus_entry`, `author: "sol"`),
`artifact` (an imported file), or `config` (a Physical Robot's hardware configuration —
SOLUSDEV-248). Entries are in creation order.

### SOLUSDEV-248 amendment — `config` entries (ADR-034 amendment 2026-09-06)

A `hardware` entry of kind `config` carries `payload`: the robot's `HardwareConfig` document,
validated by its Pydantic model on every write (`docs/api/hardware.md` §2). Every other kind
returns `payload: null`. One entry exists per Physical Robot; it is created on the first
`GET /hardware/robots/{robot_id}/config` and referenced from the robot root's
`properties.hardware_config_ref`. Its graph identity is a `hardware_config` node under the
Hardware section with a `configures` edge to the robot. Config entries are written only through
the hardware routes — `POST /solus/hardware/entries` still accepts `text` and `artifact` only, and
`PATCH` on a config entry is `409 conflict`. Deleting one removes the entry and its node; the
next hardware read recreates an empty config.

## 3. POST `/{section}/entries` — file (member+)

Body is one of two shapes, discriminated by `kind`; unknown fields → `422`; unknown `{section}` →
`404`.

```json
{ "kind": "text", "text": "Spec: 48 V accumulator, 600 A fuse" }
```

`text` is stripped, non-blank, ≤ **4000** characters. A section holds at most **500** live entries
(`422` beyond).

```json
{
  "kind": "artifact",
  "artifact_id": "019f9a00-…",
  "name": "FSAE Rules 2027.pdf"
}
```

The client first uploads the bytes through the existing `POST …/artifacts` (artifacts.md §2,
all its caps and limiters apply), then files the returned `artifact_id` here. The artifact must
be live, unconsumed, and belong to **this** project — anything else is `404`. Filing sets
`artifacts.retained = true`, creates the `document` node (attrs: `artifact_id`, `media_type`,
`size_bytes`, `filename`, `section`) and the `.solus → document` `references` edge, and returns
the entry (`201`). `name` (≤255) is the node's display name; the `ArtifactRef` carries none.

## 4. PATCH `/entries/{entry_id}` — edit (member+)

```json
{ "text": "Spec: 48 V accumulator, 600 A fuse (rev B)" }
```

Text and SOL entries only. An artifact entry → `409 conflict` (remove and re-import instead).

## 5. DELETE `/entries/{entry_id}` — remove (member+)

Soft-deletes the entry, its graph node and every edge touching it. For an artifact entry,
it also soft-deletes the artifact row and removes the bytes from the store. `204`; a second
delete → `404`.

## 6. The SOL tool — `add_solus_entry`

Registered per request in `build_sol_registry` when a user is bound. Params
`{section: enum(5), text ≤4000}`, `additionalProperties: false`, **no scope fields** — project
and user are bound by Solus code. **Not confirmation-gated**: it appends one bounded,
project-scoped, team-editable note, none of CLAUDE.md §7's destructive classes. Rows carry
`author: "sol"`, `created_by` = the requesting user. Bad section/text → `ToolResult(ok=false,
invalid_args)`; the registry's never-raises invariant is untouched. The system prompt tells SOL to
file a short, source-naming result with it when asked to find something for a section, and to
file nothing when it finds nothing. Automatic error filing (S5) is a later ticket.

## 7. Events

`solus.entry_added {entry_id, section, kind}` · `solus.entry_updated {entry_id}` ·
`solus.entry_deleted {entry_id, section, kind, removed_document}` — plus the upload's own
`artifact.uploaded`.

## 8. Error catalogue

| HTTP | `error.code`       | Where                                                                       |
| ---- | ------------------ | --------------------------------------------------------------------------- |
| 401  | `unauthorized`     | missing/invalid JWT                                                         |
| 403  | `forbidden`        | write as viewer / share-only user                                           |
| 404  | `not_found`        | non-member project; unknown section; unknown/foreign/dead artifact or entry |
| 409  | `conflict`         | PATCH on an artifact entry                                                  |
| 422  | `validation_error` | blank/over-long text, unknown fields, wrong fields for `kind`, full section |
