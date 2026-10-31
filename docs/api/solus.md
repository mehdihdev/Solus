# solus.md — The project-level `.solus` route plan

**Last updated:** 2026-10-17 (SOLUSDEV-320: the seven-section tree with subsections, typed
payloads per section, error dedupe, goals/constraints/members/history). Tier-1 route plan
(ADR-032), integrating the SOLUSDEV-240/242 foundation, 251 hardware ownership, 255 graph
context, 252 SOL artifacts and CODE environment records. Environment execution belongs to I3.
**Authority:** DECISIONS.md ADR-034 (amendments 2026-09-05/06/07; the SOLUSDEV-320 amendment
text is proposed in `docs/qa/COMPLETION_SOLUSDEV-320-graph-workspace.md`), ADR-027 (the
`project` domain), ADR-025 (project scoping), CLAUDE.md §7 (tenant isolation, uploads, ingested
text is data). Upload semantics: [artifacts.md](artifacts.md). **Wireflow:** `docs/wireflows/workspace.md`.

## 1. What it is

Every project gets a `.solus` at creation: one `graph_entity` (`kind="solus_config"`,
`domain="project"`, `origin="manual"`, name `.solus`) and seven sections of entries, each with
an optional subsection:

| key             | label         | subsections (`subsection` column, String(32))                            |
| --------------- | ------------- | ------------------------------------------------------------------------ |
| `goals`         | Goals         | free slug per subsystem (`^[a-z0-9][a-z0-9-]{0,31}$`), default `general` |
| `constraints`   | Constraints   | `rules` · `compliance` · `style` · `budgets`                             |
| `documentation` | Documentation | `datasheets` · `guides` · `references` · `decisions`                     |
| `errors`        | Error logging | none                                                                     |
| `environment`   | Environment   | `spec` · `hardware` · `software` · `divergences`                         |
| `members`       | Members       | `<user id>` as 32-hex (`uuid.hex`)                                       |
| `history`       | History       | none — a view over `activities` (§9); owns no rows                       |

Until SOLUSDEV-320 the sections were `hardware`, `details`, `errors`, `docs`, `code`. Migration
`a32000000003` moves every row: `hardware → environment/hardware`, `code → environment/software`,
`docs → documentation/guides`, `details → goals/general`, `errors` unchanged; row counts per old
section are asserted equal before and after. The old names answer 404 afterwards.

The `.solus` is **configuration, not a second store for graph facts** — parts live in the graph;
their configs live here. An imported file is an `artifacts` row marked `retained` (exempt from the
TTL sweep) wrapped in a `document` graph node (`domain="project"`) that hangs off the `.solus`
node through a `references` edge, so Impact and the focus engine reach it through the one
traversal.

### Graph identities (SOLUSDEV-242, extended by 320)

Each project has seven `solus_section` entities (`domain="project"`, `origin="manual"`,
`attrs.section` = the key) under a `.solus → section` `contains` edge, created lazily by
`services/solus_graph.py:SolusGraph.ensure()` from `SECTION_TREE`. A section with fixed
subsections gets one `solus_subsection` node per subsection (`attrs {section, subsection}`),
`section → subsection` `contains`, also lazily; free-slug subsections (goals, members) get
their node on first entry. Every live entry has an `entity_id`: imported artifacts keep their
`document` identity; hardware CONFIG entries use `hardware_config`; text/SOL entries use
`solus_note`, or `solus_error` in `errors`, `solus_goal` in `goals`, `solus_constraint` in
`constraints`. Entry-node attrs carry `solus_entry_id`, `section` and `subsection`; the complete
text remains in `solus_entries`. Entries hang off their subsection node when they have one,
else off the section node. The 2026-10-17 data migration soft-deletes the four retired section
nodes and their `contains` edges; `ensure()` rebuilds the tree on the next read.

Delete removes the entry's graph identity and edges for every entry kind; only an
artifact entry deletes stored bytes. Deleting any entry cannot remove its section or
another entry. The renderer reuses W1 handlers on section/subsection/entry context menus,
refreshes the graph after all mutations, and removes the panel implementation completely.

All routes resolve through `ProjectCtx` (non-member → **404**, no existence leak). Reads need a
resolvable project; writes need the `member` role (viewer/share-only → `403`).

| Method | Path                                                             | Purpose                                           | Success |
| ------ | ---------------------------------------------------------------- | ------------------------------------------------- | ------- |
| GET    | `/api/v1/projects/{project_id}/solus`                            | The node id + every section's entries             | `200`   |
| POST   | `/api/v1/projects/{project_id}/solus/{section}/entries`          | File typed text, an uploaded artifact or a config | `201`   |
| PATCH  | `/api/v1/projects/{project_id}/solus/entries/{entry_id}`         | Edit a text/SOL entry                             | `200`   |
| PATCH  | `/api/v1/projects/{project_id}/solus/entries/{entry_id}/payload` | Set a TEXT entry's typed metadata (§3.2)          | `200`   |
| DELETE | `/api/v1/projects/{project_id}/solus/entries/{entry_id}`         | Remove an entry (and its document node)           | `204`   |

## 2. GET — read

Also **self-heals**: a project created before this ticket has no node; the first read creates it.
`sections` is keyed by the seven section keys; every entry carries `subsection` (null when the
section has none) and `payload` (null unless the entry carries typed metadata or a config).

```json
{
  "data": {
    "entity_id": "019f9a01-…",
    "sections": {
      "goals": [
        {
          "id": "…",
          "section": "goals",
          "subsection": "general",
          "kind": "text",
          "author": "user",
          "text": "48 V bus",
          "name": null,
          "artifact_id": null,
          "entity_id": "019f9a04-…",
          "payload": {
            "status": "open",
            "owner": null,
            "linked_conversation_ids": [],
            "linked_entity_ids": [],
            "linked_run_ids": []
          },
          "media_type": null,
          "size_bytes": null,
          "created_by": "…",
          "created_at": "…",
          "updated_at": "…"
        }
      ],
      "constraints": [],
      "documentation": [
        {
          "id": "019f9a02-…",
          "section": "documentation",
          "subsection": "guides",
          "kind": "artifact",
          "author": "user",
          "text": null,
          "name": "FSAE Rules 2027.pdf",
          "artifact_id": "019f9a00-…",
          "entity_id": "019f9a03-…",
          "payload": null,
          "media_type": "application/pdf",
          "size_bytes": 2748812,
          "created_by": "019ebe5b-…",
          "created_at": "2026-09-05T10:12:44.101Z",
          "updated_at": "2026-09-05T10:12:44.101Z"
        }
      ],
      "errors": [],
      "environment": [],
      "members": [],
      "history": []
    }
  }
}
```

`kind` is `text` (typed by a person), `sol` (filed by SOL via `add_solus_entry`, `author: "sol"`),
`artifact` (an imported file), or `config` (a validated document, §2.2). Entries are in creation order.

### 2.1 Payload models per (section, subsection)

CONFIG payloads are validated by `services/solus_config.py:validate_config_payload(section,
subsection, payload)`; TEXT metadata by `services/solus_payloads.py:validate_entry_payload`.
Every model is `extra="forbid"`; anything else is `422` naming the first failing field.

| section / subsection                   | kind     | model                       | written by                                                                                                                                                                      |
| -------------------------------------- | -------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `environment/hardware`                 | config   | `EntityHardwareConfig`      | hardware routes only (schema 2, `configured_entity_id`)                                                                                                                         |
| `environment/software`                 | config   | `CodeEnvironment`           | POST, `link_environment`, machine population (`configured_entity_id = machine`, `author: "system"`, `detected_on` = the PUT's os/arch; an unchanged probe is not a new version) |
| `environment/spec`                     | config   | `EnvironmentSpec`           | `services/environment_spec.py` (system; `configured_entity_id` = the `.solus` root)                                                                                             |
| `environment/divergences`              | config   | `EnvironmentDivergencesDoc` | `services/environment_divergence.py` (system; `configured_entity_id` = the cell's `solus_subsection` node)                                                                      |
| `members/<uid hex>`                    | config   | `MemberPreferences`         | `PUT /members/me/preferences` (`configured_entity_id` = the member node)                                                                                                        |
| `constraints/budgets`                  | config   | `Budgets`                   | `services/budgets.py` (system)                                                                                                                                                  |
| `goals/*`                              | text     | `GoalMeta`                  | PATCH …/payload                                                                                                                                                                 |
| `constraints/{rules,compliance,style}` | text     | `ConstraintMeta` (optional) | PATCH …/payload                                                                                                                                                                 |
| `errors`                               | text/sol | `ErrorMeta`                 | `agent/errors_filing.py`, `resolve_finding`, PATCH                                                                                                                              |

```text
GoalMeta        {status: open|met|dropped = open, owner: UUID|null, linked_conversation_ids: [UUID], linked_entity_ids: [UUID], linked_run_ids: [UUID]}
ConstraintMeta  {quantity?: str, limit?: number, unit?: str, comparator?: "<"|"<="|"="|">="|">", scope_entity_ids: [UUID], source_entry_id: UUID|null,
                 excluded_suppliers: [str ≤ 80] (≤ 32), required_certifications: [str ≤ 80] (≤ 32)}   # the quantified bound is all-or-none (half of it is 422); the two lists feed sourcing from `compliance` entries
Budgets         {schema_version: 1, computed_at, budgets: [{name: "power:<rail>"|"mass"|"cost", current: number|null, limit: number|null, unit, source: str, status: ok|exceeded|unknown}]}
ErrorMeta       {entity_id: UUID|null, machine_id: UUID|null, dedupe_key: sha1 hex, count: int ≥ 1, status: open|resolved|recurring, fix_ref: UUID|null, first_seen, last_seen}
MemberPreferences {schema_version: 1, shared: {codeStyle?: str, mechanical?: str, electrical?: str, documentation?: str, unitsStandards?: str}}   # each shared section as its text (≤ 32 KiB together, else 422); only the sections the user flagged shared; freeText never
EnvironmentSpec   {schema_version: 1, computed_at, packages: [{name, ecosystem, specifier: str|null, required_by: [entity id], source: manifest|config}], tools: []}   # from live depends_on/requires edges (candidates skipped); specifier transcribed, never guessed; tools empty until the graph records any
EnvironmentDivergencesDoc {schema_version: 1, computed_at, spec_entry_id, machines: [{machine_id, hostname, causes: [{cause: missing|version_drift|platform_build|extra, items: [{name, expected, actual, detail?}]}]}]}
```

`GET /api/v1/projects/{project_id}/environment/divergences` (any member, `200`) returns the
stored `EnvironmentDivergencesDoc`, computed on first read (a share-only reader with no team
role gets the computed document; nothing is stored for them); it is recomputed after every
sync, hardware config save and machine PUT (`services/environment_divergence.py`, guarded —
never fails the write). Only what a machine's `environment/software` CONFIG shows is compared
(python pins; npm/ros requirements are never reported missing); a machine without a CONFIG
has no causes; `platform_build` is a pin that holds but carries a local build tag (`+cu121`);
`extra` is reported only against a spec that names at least one python package.

`PUT /api/v1/projects/{project_id}/members/me/preferences` (member+, `200`, the entry) stores
the body above as the ONE `members/<uid.hex>` CONFIG; a second PUT replaces it in place
(same id, `config_version` +1). `PUT …/members/me/machines/{companion_id}` (findings.md)
additionally dispatches `machine.tool_versions` (→ `attrs.tool_versions`, replaced, version
bumped only on change; keys limited to the companion's fixed binary list, each line cut at
`from` with every absolute path redacted to `<path>` on both sides) and
`code.probe_environment` (→ the machine's `environment/software` CONFIG) over the caller's
live bridge, both through the 10 s probe cache; without a bridge or the tools the PUT stores
the body only and never fails.

`PATCH …/payload` on a goal mirrors `linked_run_ids` as `verified_by` goal → `bench_run` edges
(manual, 1.0, evidence `{kind: run, ref: <run id>}`, `created_by` the caller): a run no longer
listed retires its edge, a re-listed one revives it, and a run id that is not a live
`bench_run` of THIS project is `422` with nothing written. A `status` change records
`goal.status_changed` (`entity_ids` = [the goal node], `why_ref` = the first
`linked_conversation_ids` entry, payload `{entry_id, from, to}`). A `compliance` entry's
`excluded_suppliers` / `required_certifications` are added (first occurrence wins,
case-insensitive, capped at 32) to `GET …/sourcing/rules` on top of the repo table and the
project document; the exclusion reason shown is the entry's first line. Budgets
(`services/budgets.py`): one `power:<rail>` line per net named by the live `powers` edges
(`attrs.nets`; sink draw = part definition `limits.current_a` / `stall_current_a` or attr
`current_draw_a`, supply rating = `limits.current_a` or attr `current_max_a`), `mass` in kg
(definition `mass_g`, attrs `mass_kg` / `weight_kg` / `mass`; a part with no mass makes the
sum a lower bound → `unknown` unless already over), `cost` from the BOM totals. Mass and cost
limits come from a quantified constraint on any live constraints entry (`quantity` `mass` /
`cost`, comparator `<` or `<=`; `g`/`kg` converted) — never from a guess. `exceeded` raises
one `budget_exceeded` finding (`source: checker`, `bucket` = the budget name, subjects = the
rail's supplies or the `.solus` root); a repeat counts it, a later `ok` never resolves it.
Recomputed 5 s (debounced per project) after any published `graph.changed` frame — the ARQ
job `recompute_budgets` when a queue exists, inline otherwise — and stored as the one
`constraints/budgets` CONFIG bound to that cell's `solus_subsection` node.

### 2.2 CONFIG entries (SOLUSDEV-251; ADR-034 amendment 2026-09-07)

An `environment/hardware` entry of kind `config` carries the validated physical subject's
schema-2 payload. There is at most one active CONFIG per configured entity, including a standalone
part or a machine node. `configured_entity_id` and `config_version` identify its subject and write
version. Its `hardware_config` graph node has a manual `configures` edge to the real subject. Only
manual subjects may carry a convenience hardware_config_ref attribute; imported provider
attributes/identity are untouched. See [hardware.md](hardware.md) and
[hardware-config.md](../schemas/hardware-config.md) for exact bounds, migration and concurrency.

Hardware routes alone create/update HARDWARE CONFIG payloads. Generic POST accepts
text/artifact and `environment/software` records (§2.3); PATCH on CONFIG returns 409. Hardware
GET is read-only and returns honest absence. Deleting a CONFIG removes its entry/node/manual
configures and derived binding edges, updates only permissible manual convenience references, and
invalidates relevant resolver caches after commit. It never deletes the configured subject/part or
recreates empty configuration on read. The UI's concrete confirmation explains affected connection
bindings and loss of configuration. Robot deletion retains independent part CONFIG entries, values
and provenance.

The 500-live-entries cap is per section; entity-bound CONFIG rows (`configured_entity_id` set) do
not count toward it, because they are bounded by the entities they configure.

### 2.3 `environment/software` config entries (SOLUSDEV-252 amendment, moved from `code`)

CODE records use the existing `solus_note` graph kind with `section: environment`,
`subsection: software` and their entry ID. They never use `hardware_config` nodes or `configures` edges. Deleting a
record removes that graph identity and its links; it does not remove or execute
anything in the environment on the computer.

An `environment/software` entry of kind `config` is one **code environment** — the interpreter, packages and host a
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
  "packages": [
    { "name": "numpy", "version": "2.1.0" },
    { "name": "pyserial", "version": null }
  ],
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
CONFIG payload validation is dispatched by **(section, subsection)** (`validate_config_payload`, §2.1);
other cells hold no config entries (`422`). `PATCH` on any config entry stays `409`. Stored records are
project-scoped observations. I3 commands select a confined workspace-relative environment
path; a stored record never grants permission to execute an arbitrary path.

## 3. POST `/{section}/entries` — file (member+)

Body is one of three shapes, discriminated by `kind`; unknown fields → `422`; unknown or retired
`{section}` → `404`; `history` and `members` → `422` (history owns no rows; member preferences
have their own route). Every shape may carry `subsection` (validated per §1; `422` when the
section has fixed subsections and the value is not one of them, or when `errors` is given one;
omitted on a fixed-vocabulary section → `null`, and the entry hangs off the section node;
defaulted to `general` for goals). Text/artifact shapes may include optional
`context_entity_id: UUID`.

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
{
  "kind": "config",
  "payload": {
    "schema_version": 1,
    "type": "venv",
    "name": "robot-venv",
    "…": "…"
  }
}
```

`environment/software` only through this route (SOLUSDEV-252, §2.3): a bad document → `422`
naming the first failing field; `config` into any other cell → `422`. An upsert — the same (`type`, `path`/`name`) returns the
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

### 3.2 PATCH `/entries/{entry_id}/payload` — typed metadata (member+)

`{payload: object}` for a TEXT/SOL entry in `goals`, `constraints/{rules,compliance,style}` or
`errors`, validated by the model in §2.1 (`422` otherwise, including a cell whose model is system-written such as
`constraints/budgets`; config and artifact entries → `409`). Replaces the whole payload. Goal link
changes rewrite the goal's `verified_by` edges (P5-T5). Every successful patch publishes a
`graph.changed` frame, so a mass/cost limit edit recomputes `constraints/budgets` (P5-T6).

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
`{section: enum(7), subsection?: str, text ≤4000, context_entity_id?: UUID}`, `additionalProperties: false`,
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

| tool                        | params                                              | preview rows                                                                        |
| --------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `edit_solus_entry`          | `{entry_id, text ≤4000}`                            | `Entry: <current text (≤500)> → <new text>`; artifact/config entry → `invalid_args` |
| `delete_solus_entry`        | `{entry_id}`                                        | `Entry: <text or file name> → null`; an artifact entry's bytes are removed too      |
| `set_hardware_config_field` | `{robot_entity_id, path (dotted), value (scalar)}`  | `<path>: <current or "(unset)"> → <value>`                                          |
| `link_environment`          | `{name}` — the workspace environment observed by I3 | observed `type` / `name` / `packages` / `interpreter` / `path` / `python`           |

`link_environment` records one of this machine's code environments as an
`environment/software` CONFIG entry (`services/code_env.py`, §2.3) with `author: "sol"`. The model supplies **only the name**:
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

**Dedupe (SOLUSDEV-320).** `agent/errors_filing.py` keys every filing on
`sha1(tool, redacted command, error code)` stored in `payload.dedupe_key` (`ErrorMeta`). An open
entry with the same key gets `count += 1` and a new `last_seen` instead of a new row (and emits
`solus.entry_updated`); a resolved one becomes `recurring`. `machine_id` is null until a filing
knows its machine (P5).

**Failure means both kinds.** The call itself failing (`ok=false`) and a call that was delivered
fine and reported a failed run — a non-zero `exit_code`, or `timed_out` (`errors_filing.run_failure`).
A `ModuleNotFoundError` comes back as a perfectly ok bridge result carrying `exit_code: 1`, and that
is precisely the failure Error logging exists to catch; the filed row reads
`Error [tool_error]: exit 1. <stderr tail>`.

### 6.3 SOLUSDEV-321 P3-T4 — `extract_rulebook` and `label_motifs`

Two **ungated** SOL tools. Solus code binds each to the project and the requesting user. Their
model calls are metered as that user, and attributed to the SOL turn they run in: the runner binds
the turn's id (`agent/turn_context.py`), so the ledger rows carry it, and its perception, so each
call is noted on the turn's own budget first (`PerceptionTurn.take_model_call`, M122): it counts
against `max_model_calls` and never spends the closing round's call. A rulebook page read past
that budget is not made (the read stops with its budget note); a labelling call past it is refused
`UNAVAILABLE`, nothing labelled. Neither tool takes a scope field, and every failure is
`ToolResult(ok=false)`.

| tool               | params                                               | registered when                                           |
| ------------------ | ---------------------------------------------------- | --------------------------------------------------------- |
| `extract_rulebook` | `{entry_id, pages?}` (`pages` as in `read_document`) | a user, the artifact store and the secret store are bound |
| `label_motifs`     | `{}`                                                 | a user and the secret store are bound                     |

**`extract_rulebook` writes nothing.**

- **What it reads.** An artifact entry of this project: a rulebook PDF, filed in any section. It
  goes through `read_document`'s extractor: at most 12 pages rendered, and one metered vision call
  a page (`purpose: "extract"`). An unknown or foreign entry is `not_found`, and a text entry is
  `invalid_args`.
- **What it returns.** Candidate rows `{payload, text, page, quote}`, with
  `section: "constraints"` and `subsection: "rules"` saying where they go. It returns as many
  rows as fit the result whole, under its 16,000-character cap as the prompt layer encodes it.
  `notes` counts the rows that did not fit.
  - A row exists only for a proposal that states one finite number, a unit and one bound.
  - `payload` is a whole `ConstraintMeta` (§2.1) whose `source_entry_id` is the rulebook entry.
- **How a candidate becomes a constraint.** Only through the existing routes: the person files
  its `text` in `constraints` with `subsection: "rules"` (§3), then sets its `payload` (§3.2). The
  tool creates no entry and changes no payload.

**`label_motifs` writes only labels.**

- **When it runs.** Only inside a SOL turn; outside one it is `unavailable`. It takes the
  project's netlist motifs that the matrix job left at confidence 0.7 or below and that no label
  names yet, at most 6 a call (docs/contracts/checker-interface.md, netlist motifs). It reads
  their holders 200 at a time, oldest first, until 6 wait or the 5,000 the job can hold have been
  read. So labelled holders never hide a later candidate.
- **The call.** One light-tier call (`purpose: "motif"`, the turn's id) labels them, with the
  parts fenced as data. A label outside the closed set (`divider_adc`, `rc_on_input`,
  `decoupling_at_pin`, `h_bridge`, `level_shifter`, `unknown`) is dropped and counted, as is one
  for a candidate it was not offered.
- **What it writes.** A kept label goes on each member's `attrs.motif_labels`, with
  `labelled_by: "model"` and the turn id. It never touches `attrs.motifs` or any `.solus` entry,
  and no check reads a label.
- **What it reports.** `labelled` lists a candidate only when at least one member kept its label.
  The member rows another writer held are counted in `notes`.

### 6.4 SOLUSDEV-321 P5 — `render_view`

One **ungated** SOL tool (`agent/vision/render_view.py`; the architecture is
`docs/architecture/sol-depth.md`, "Perception"). Solus code binds it to the project and the
requesting user; it takes no scope field. It is registered in `build_sol_registry` when a user,
their team, the secret store and the artifact store are bound, so a bare registry still lists only
`get_entity`. It runs only inside a SOL turn (outside one it is `unavailable`); its timeout is
120 s, its result cap 6,000 characters, and every failure is `ToolResult(ok=false)`. A companion
tool flagged `returns_image` (the KiCad PDF exports) is never offered to the model: only this tool
reaches it.

| param       | type                   | meaning                                                                    |
| ----------- | ---------------------- | -------------------------------------------------------------------------- |
| `entity_id` | UUID                   | a live entity this user may read here; any other id is `not_found`         |
| `question`  | string, 1–300 chars    | picks ONE view: a face, the part's bounds, the sheet, the board, isometric |
| `show`      | boolean, default false | true only when the person asked to see the picture (the model is told so)  |

- **Declined, not failed.** `{rendered: false, reason}` when the turn is about connectivity or
  counts (the scope planner's `exclude_renders` / `counting`: those come from the graph), when
  nothing renders the entity (no scene model, and its source's connector declares no
  `Capability.RENDER`), or when its renderer refuses (no companion, an unflagged export tool, an
  artifact store capped under 2 MiB, a degraded export, a scene the guard refuses, the Onshape
  quota past its degrade ratio, no cached revision). A refusal also names the `view`.
- **What it returns.** `{rendered: true, view, renderer, cached, read, graph_wins, findings, note}`.
  `read` is the one vision read of the labelled render, with every length the graph states
  differently replaced by the graph's value (`graph_wins` lists each, with both numbers).
  `findings` names the `vision_fact_disagreement` info findings this ask filed: one per (entity,
  `length`) per render. A cached answer (`cached: true`) cost no render, no model call and no
  finding, so its `findings` is empty. The cache is reached only after the subject is read in the
  requesting user's scope, and it holds values only, never an artifact or a finding (R127). A
  companion-drawn view (a sheet or board the user's own companion exports) is cached for that user
  alone; scene and connector views are shared within the project.
- **Showing.** With `show: true`, the annotated PNG is stored as a fresh artifact of this project
  for the requesting user, on every ask, a cached one's included (`image/png`, the artifacts
  route's TTL). The result carries `artifact_id`, `uri`, `media_type`, `title` and `summary`; the
  chat shows it as a card (`ARTIFACT_TOOLS`). Without it, no artifact is made and no pixels leave
  the server.
- **Model calls.** At most one per render (`purpose: "vision"`, `type: VISUAL_LOG`, the turn's id),
  metered as the requesting user and counted against the turn's `max_model_calls`. It never spends
  the turn's closing round's call: when only that one is left, `read` says the budget is spent.

### 6.5 SOLUSDEV-321 P6 — `firmware_recipe`

One **ungated** SOL tool (`agent/firmware_recipe.py`) that writes nothing itself: it returns the
complete new firmware file for one board, and the write goes through `machine.write_file`'s card.
Solus code binds it to the project and the requesting user. It is registered in
`build_sol_registry` when a user, their team, the secret store and the owned `machine.write_file`
(the person's companion advertises it) are all bound, and it runs only inside a SOL turn.

| param      | type                | meaning                                                        |
| ---------- | ------------------- | -------------------------------------------------------------- |
| `board_id` | UUID                | a `hardware_brain` this user may read here; any other id fails |
| `path`     | string, 1–400 chars | the workspace file to write, relative to the linked folder     |

- **The topology** is read under the requesting user's scope (two bounded neighbourhood reads,
  through `to_graph_context`): the board, the robots and parts its buses reach, the confirmed
  `commands` / `reads` edges into those parts (the code lines they cite and any stated
  `commanded` fact), the board definition's `pins[].capabilities`, and each part's telemetry
  channels from its robot's runtime config. At most 64 of each go to the model.
- **The path is decided before anything is read (R138).** When the topology names the board's
  firmware (the code files its `commands` / `reads` edges come from), `path` must be one of them;
  any other is refused (`unauthorized`) with one message that does not say whether the file
  exists ("The graph does not name `<path>` as this board's firmware; named: …"), and nothing is
  read. A named file is read through the owned write's dry run with empty content
  (`MachineWriteTool.current_text`): nothing is written and no card is parked, and a file past a
  card's ceiling, or one that sensitive-data filtering masked, is refused. When the topology names
  no firmware for the board yet, the file is new: nothing is read, existing or not, the current
  file is `null`, and the write's card shows whatever it would replace.
- **One model call** (`purpose: "answer"`, `type: CODE`, the turn's id), metered as the requesting
  user and counted against the turn's `max_model_calls`, never its closing round's. The
  instruction is the Solus constant `FIRMWARE_RECIPE`. The facts follow as fenced data blocks:
  `topology`, `pins`, `telemetry_library` (the SolusTelemetry API and the channels),
  `current_file` (whole, never cut) and `code_style`, the turn's `Code style` preference, which
  the runner binds (`PerceptionTurn.code_style`). The reply is one fenced block or plain text.
- **The card ceiling.** A write card shows `CARD_ROWS` (40) rows of `ROW_CHARS` (400) characters:
  the file and fingerprint rows, then one row per 400-character chunk of the longer side. A reply
  past it is refused, naming the ceiling, and nothing is proposed.
- **What it returns.** `{path, content, card_rows, next}`, where `next` says to call
  `machine.write_file` with exactly that path and content.
- **The card is forced.** The recipe routes its turn to `machine.write_file`
  (`routed_by_firmware`), a term of `BuildExecutionPolicy.prepare`'s predicate: in that turn the
  write keeps its card even in Build mode, since the person asked for firmware, not for a write.
- **The event** `sol.firmware_recipe.prepared {card_rows, commands, pins, channels}` carries counts
  only.

## 7. Events

`solus.entry_added {entry_id, section, subsection, kind, context_entity_id?}` · `solus.entry_updated {entry_id}` ·
`solus.entry_deleted {entry_id, section, kind, removed_document}` — plus the upload's own
`artifact.uploaded`.

## 8. Error catalogue

| HTTP | `error.code`       | Where                                                                                                                                                                   |
| ---- | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 401  | `unauthorized`     | missing/invalid JWT                                                                                                                                                     |
| 403  | `forbidden`        | write as viewer / share-only user                                                                                                                                       |
| 404  | `not_found`        | non-member project; unknown or retired section; unknown/foreign/dead artifact, entry or context                                                                         |
| 409  | `conflict`         | PATCH on an artifact or config entry; payload PATCH on a config entry                                                                                                   |
| 422  | `validation_error` | blank/over-long text, unknown fields, wrong fields for `kind`, bad subsection, POST into `history`/`members`, full section, bad or misplaced config payload or metadata |

## 9. History (SOLUSDEV-320)

The `history` section owns no rows. Its node renders
`GET /api/v1/projects/{project_id}/history?since=&entity=&domain=&actor=&cursor=&limit=`
(any member; non-member `404`) — the project's `activities`, newest first, each row
`{id, type, domain, actor_id, project_id, payload, entity_ids, why_ref, created_at}`
(`entity_ids`: JSONB array of graph entity ids as strings; `why_ref`: a conversation id,
decision entry id, finding id or fix entity id, ≤ 128 chars). Filters narrow within the
project: `since` (ISO datetime, a naive value is UTC), `entity` (`entity_ids @> '["<id>"]'`,
GIN `jsonb_path_ops`), `domain`, `actor`; `limit` 1–200 (default 50) with the §1.4 cursor
envelope (`meta.limit`, `has_next`, `next_cursor`; a malformed cursor is `400`). The team
feed (`/teams/{id}/activity`) serializes the same two new fields. Migration
`a32000000005` adds the columns and the `(project_id, created_at)` index.

| type                               | emitter                                                                                                                                                                        | `entity_ids`                                                                                                       | `why_ref`                 | payload                                                                                                                             |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `sync.completed`                   | `connectors/runtime._commit_success` (every successful sync)                                                                                                                   | the source's root entity (`code_repo` / `local_clone` / `local_folder` / `cad_document` / `design_export`) or `[]` | —                         | `{source_id, sync_id, entities_created, entities_updated, relations_created, relations_deleted, errors}`; `domain` by source family |
| `topology.confirmed`               | `TopologyAcceptanceService.confirm` (not on replay)                                                                                                                            | `[robot, brain, *reviewed rows]`                                                                                   | —                         | `{robot_id, operation_id, created}`                                                                                                 |
| `host.confirmed`                   | `HostTopologyService.confirm` (not on replay)                                                                                                                                  | `[robot, endpoint, software?]`                                                                                     | —                         | `{robot_id, machine_id}`                                                                                                            |
| `edge.confirmed` / `edge.declined` | `POST …/edges/{id}/confirm` / `decline`                                                                                                                                        | `[src, dst]`                                                                                                       | —                         | `{edge_id, relation_type, reason}`                                                                                                  |
| `firmware.flashed`                 | `agent/tools/flash_history.record_tool_history`, called from the runner's post-dispatch hook and `confirmations.decide_confirmation` — a clean, executed `code.arduino_upload` | the entity the call named, when this project's                                                                     | —                         | `{tool, port}`                                                                                                                      |
| `config.bumped`                    | `hardware/store.put_entity_config` (every saved version)                                                                                                                       | `[subject]`                                                                                                        | —                         | `{entry_id, config_version}`                                                                                                        |
| `finding.resolved`                 | `graph/findings.resolve_finding`                                                                                                                                               | `[finding, *subjects]`                                                                                             | the `fix_ref`             | `{finding_id, rule_id, entry_id}`                                                                                                   |
| `goal.status_changed`              | `PATCH …/solus/entries/{id}/payload` (§2.1)                                                                                                                                    | `[goal node]`                                                                                                      | first linked conversation | `{entry_id, from, to}`                                                                                                              |

The `team.activity` live frame is derived from every inserted row as before.
