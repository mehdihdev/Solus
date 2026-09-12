# solus.md — The project-level `.solus` route plan

**Last updated:** 2026-09-10. Tier-1 route plan (ADR-032), integrating the
SOLUSDEV-240/242 foundation, 251 hardware ownership, 255 graph context, and 252 SOL
artifacts and CODE environment records. Environment execution belongs to I3.
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
`artifact` (an imported file), or `config` (a physical entity's hardware configuration
or a CODE environment record). Entries are in creation order.

### CONFIG entries (SOLUSDEV-251; ADR-034 amendment 2026-09-07)

A `hardware` entry of kind `config` carries the validated physical subject's schema-2 payload;
other kinds return payload null. There is at most one active CONFIG per configured entity,
including a standalone part. `configured_entity_id` and `config_version` identify its subject
and write version. Its `hardware_config` graph node has a manual `configures` edge to the real
subject. Only manual subjects may carry a convenience hardware_config_ref attribute; imported
provider attributes/identity are untouched. See [hardware.md](hardware.md) and
[hardware-config.md](../schemas/hardware-config.md) for exact bounds, migration and concurrency.

Hardware routes alone create/update HARDWARE CONFIG payloads. Generic POST accepts
text/artifact and CODE environment records (§2.1); PATCH on CONFIG returns 409. Hardware GET is read-only and returns honest absence.
Deleting a CONFIG removes its entry/node/manual configures and derived binding edges, updates
only permissible manual convenience references, and invalidates relevant resolver caches after
commit. It never deletes the configured subject/part or recreates empty configuration on read.
The UI's concrete confirmation explains affected connection bindings and loss of configuration.
Robot deletion retains independent part CONFIG entries, values and provenance.

### 2.1 SOLUSDEV-252 amendment — `code` section config entries

CODE records use the existing `solus_note` graph kind with `section: code` and their
entry ID. They never use `hardware_config` nodes or `configures` edges. Deleting a
record removes that graph identity and its links; it does not remove or execute
anything in the environment on the computer.

A `code` entry of kind `config` is one **code environment** — the interpreter, packages and host a
project runs on. `payload` is a `CodeEnvironment` document, validated on every write
(`services/code_env.py`; `extra="forbid"`):

```json
{
  "schema_version": 1,
  "type": "venv",
  "name": "robot-venv",
  "path": "/home/dev/robot/.venv",
  "interpreter": "/home/dev/robot/.venv/bin/python",
  "image": null,
  "packages": [{ "name": "numpy", "version": "2.1.0" }, { "name": "pyserial", "version": null }],
  "detected_on": { "os": "linux", "arch": "x86_64" },
  "provenance": "detected",
  "captured_at": "2026-09-07T10:00:00Z"
}
```

`detected_on` is nullable when the authenticated I3 probe does not report host
OS/architecture. Capture time records when the API observed the result; missing
interpreter or package facts are never synthesized.

`type` ∈ `venv | conda | docker | system | pyenv`; `image` is for `docker`; `packages` ≤ **500**;
`provenance` ∈ `detected | user | sol` (who captured it — the companion, a person, or SOL).
`text` is the environment's `name`. **One entry per (`type`, `path` or `name`)**: filing the same
environment again updates that entry in place (same `id`), so a re-detection never duplicates.
CONFIG payload validation is dispatched by **section** (`validate_config_payload`): `hardware` →
`EntityHardwareConfig` (schema 2, hardware routes only), `code` → `CodeEnvironment`; other sections hold
no config entries (`422`). `PATCH` on any config entry stays `409`. Stored records are
project-scoped observations. I3 commands select a confined workspace-relative environment
path; a stored record never grants permission to execute an arbitrary path.

## 3. POST `/{section}/entries` — file (member+)

Body is one of three shapes, discriminated by `kind`; unknown fields → `422`; unknown `{section}` →
`404`.
Text/artifact shapes may include optional `context_entity_id: UUID`.

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

```json
{ "kind": "config", "payload": { "schema_version": 1, "type": "venv", "name": "robot-venv", "…": "…" } }
```

`code` section only (SOLUSDEV-252, §2.1): a bad document → `422` naming the first failing field;
`config` into any other section → `422`. An upsert — the same (`type`, `path`/`name`) returns the
existing entry updated, still `201`.

### Optional graph context (SOLUSDEV-255)

For text/artifact creation, `context_entity_id` identifies a live real entity in this project.
Unknown/foreign/deleted context is 404 with no partial entry, retained artifact or edge mutation.
The existing entry transaction adds a manual `references` edge from context entity to the new
entry graph node alongside the normal section containment. It does not modify source-owned
identity, attributes, text or containment. Omission preserves existing behavior. The entry
response adds `context_entity_id: UUID|null`; existing GET includes it by resolving this manual
context relation. No duplicate authoritative context text or new document store is introduced.

The renderer uploads first using existing artifact checks, then files with the selected section
and optional context. A failed upload creates no context link; an unfiled artifact keeps existing
TTL behavior. Notes/imports remain accessible through `.solus` and the selected entity's
relationships. All existing 8 MiB artifact, 4000-character text and 500-live-entry bounds remain.
Entry deletion removes its touching manual context edges as part of existing graph cleanup;
it does not delete the context entity or another entry. The section selection/default is visible
in the inspector composer; no hidden provider content edit occurs.

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
`{section: enum(5), text ≤4000, context_entity_id?: UUID}`, `additionalProperties: false`,
**no scope fields** — project
and user are bound by Solus code. **Not confirmation-gated**: it appends one bounded,
project-scoped, team-editable note, none of CLAUDE.md §7's destructive classes. Rows carry
`author: "sol"`, `created_by` = the requesting user. Bad section/text → `ToolResult(ok=false,
invalid_args)`; the registry's never-raises invariant is untouched. The system prompt tells SOL to
file a short, source-naming result with it when asked to find something for a section, and to
file nothing when it finds nothing. The optional context undergoes the same live in-project
reference validation as HTTP entry creation; it cannot change bound project/user authorization.
Invalid/foreign context returns a bounded failed ToolResult, preserving the registry's never-raises
contract. Graph selection never calls this tool automatically. Explicit inspector Ask SOL uses
existing MessageCreate.mentions/project conversation, Guide/Expert, budgets, action admission
and concrete confirmations. Automatic error filing (S5) is a later ticket.

### 6.1 SOLUSDEV-252 — gated write tools (`agent/tools/solus_tools.py`)

Registered alongside `add_solus_entry` via `register_solus_write_tools(registry,
session_factory=…, store=…, project_id=…, user_id=…, fetch_environments=…)`. All are **confirmation-gated**
(`requires_confirmation: true`, a Solus-authored `consent_summary`) and carry a `preview` so the
card shows the exact edit (docs/contracts/action-gate.md); nothing runs before approval, and a
preview that changed by decision time is STALE. Scope is bound by Solus code; a foreign or dead id
is `not_found` (no existence oracle); every failure is `ToolResult(ok=false)`.

| tool                        | params                                                             | preview rows                                                                   |
| --------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| `edit_solus_entry`          | `{entry_id, text ≤4000}`                                           | `Entry: <current text (≤500)> → <new text>`; artifact/config entry → `invalid_args` |
| `delete_solus_entry`        | `{entry_id}`                                                       | `Entry: <text or file name> → null`; an artifact entry's bytes are removed too |
| `set_hardware_config_field` | `{robot_entity_id, path (dotted), value (scalar)}`                 | `<path>: <current or "(unset)"> → <value>`                                     |
| `link_environment`          | `{name}` — the workspace environment observed by I3            | observed `type` / `name` / `packages` / `interpreter` / `path` / `python` |

`link_environment` records one of this machine's code environments as a `code`-section CONFIG
entry (`services/code_env.py`, §2.1) with `author: "sol"`. The model supplies **only the name**:
available facts are read back through the companion's `code.probe_environment` at link time.
Missing host/interpreter facts remain null. Truncated inventory is unavailable, and a name
the machine does not report is `not_found` rather than an empty entry. Linking the same
environment again updates the entry in place (identity is `(type, path or name)`), which is how a
package installed after the first link shows up. It is registered **only when a companion is
connected** — with no machine there is nothing to link, and a tool that could only answer "no
machine" is worse than an absent one.

`set_hardware_config_field` writes directly through versioned `put_entity_config`, so `EntityHardwareConfig`
validation and the node version bump apply; `provenance[path] = {by: "sol", source: "sol turn"}`.
Only the leaf may be new — the containing group must exist (no conjured parts or buses), a list
index must exist, a group cannot be replaced by a scalar, and `schema_version`,
`robot_entity_id`, `entity_id`, `provenance` are never settable (all `invalid_args`).
Legacy `firmware.*` and `parts.<owned-part-UUID>.*` paths resolve to the appropriate
per-entity component document; no compatibility split or aggregate rewrite occurs.
The preview includes configuration version. A request-local snapshot of subject,
entry and versions is revalidated under the project lock before the versioned
write; missing or changed snapshots are refused, including changes after the
final approval preview.

### 6.2 Environment execution and Error logging

I3's `code` server is the sole environment executor: `create_environment`, `install`,
`run` and `test` all use the existing confirmation gate. The exact plan is shown in
bounded rows; failed or oversized plans are refused. A one-use snapshot is compared
with the plan immediately before dispatch, so a changed command requires approval
again. Successful create/install re-probes the exact target and updates its CODE
record with provenance `sol`. If observation fails, the command outcome remains
available with an explicit recording-unavailable status; no inventory is invented.

The companion's built-in `machine` server (`integrations/mcp/machine/allowlist.yaml`)
retains only gated `read_file` and `write_file`. Entries carry
`files_errors: true` where a failure is worth a ledger row: when such a call fails, the runner
files it into this project's **`errors`** section automatically — command or edit, bounded output,
the entity it was about, timestamp; `author: "sol"`, editable and deletable like any entry. Secret
values never appear in a filed error (names only; `redact_text` on the way in).

**Failure means both kinds.** The call itself failing (`ok=false`) and a call that was delivered
fine and reported a failed run — a non-zero `exit_code`, or `timed_out` (`errors_filing.run_failure`).
A `ModuleNotFoundError` comes back as a perfectly ok bridge result carrying `exit_code: 1`, and that
is precisely the failure Error logging exists to catch; the filed row reads
`Error [tool_error]: exit 1. <stderr tail>`.

## 7. Events

`solus.entry_added {entry_id, section, kind, context_entity_id?}` · `solus.entry_updated {entry_id}` ·
`solus.entry_deleted {entry_id, section, kind, removed_document}` — plus the upload's own
`artifact.uploaded`.

## 8. Error catalogue

| HTTP | `error.code`       | Where                                                                       |
| ---- | ------------------ | --------------------------------------------------------------------------- |
| 401  | `unauthorized`     | missing/invalid JWT                                                         |
| 403  | `forbidden`        | write as viewer / share-only user                                           |
| 404  | `not_found`        | non-member project; unknown section; unknown/foreign/dead artifact, entry or context |
| 409  | `conflict`         | PATCH on an artifact or config entry                                        |
| 422  | `validation_error` | blank/over-long text, unknown fields, wrong fields for `kind`, full section, bad or misplaced config payload |
