# widget-bundles.md — First-party bundle capabilities (SOLUSDEV-246 · STORE ST1)

**Ticket:** SOLUSDEV-246 (work carried on the `SOLUSDEV-242-home-cross-project-surface` branch by
founder decision, 2026-09-05).
**Status:** PLANNED → implemented in the same MR (tier-1 route-plan amendment, ADR-032 — the MR
review is the approval gate). Documented BEFORE the router exists per the authority hierarchy.
**Authority:** ADR-035 (extensions; §4 amended 2026-09-05 for the repo `.solus/` section) ·
ADR-031 / MCP-03 (backend code is in-repo, provenance-recorded, reviewed at the MR — never
shipped in a bundle) · ADR-027 (kinds are free strings; `origin="extension"` added 2026-09-05) ·
W0-04 `docs/contracts/agent-tool.md` (never-raises registry; `requires_confirmation`) ·
`docs/contracts/action-gate.md` (the confirmation gate) · `docs/contracts/extension-manifest.md`
schema_version 2 (`[backend]`, `[graph]`, `[tools]`) · [extensions.md](extensions.md) (the
install routes this plan hangs off) · CLAUDE.md §7.

---

## 1. Why this exists

ADR-035 keeps community extensions safe by running them **only** in a sandboxed frame. Some
capabilities cannot live there: a route that joins tenant data server-side, a SOL tool, a graph
node type. STORE ST1 adds those for **first-party bundles only**. The bundle's `extension.toml`
_declares_ them; the code that implements them is an in-repo Python package under
`packages/api/src/solus_api/widgets/<capability>/`, reviewed like any other Solus code. A bundle
zip never carries server code, and a manifest that declares these tables without a matching
in-repo package is rejected at publish.

Three properties the whole plan rests on:

1. **The manifest claims, Solus decides.** `declares_first_party(manifest)` is a claim; the
   publish validator requires the publisher to be `RequireStaff` AND `solus_api.widgets` to
   contain a capability whose id equals `extension.id` and whose declared kinds/tools are a
   superset of the manifest's. Community publishers get `422 bundle_invalid`.
2. **Everything is per project and follows the install row.** Routes answer, tools register and
   kinds are writable only while the bundle is installed, enabled and not team-blocked in the
   request's project (`extension_installs` + `team_extension_policies`, the same snapshot the
   bridge uses). Uninstall removes every trace (§5).
3. **Tools go through the W0-04 registry unchanged.** Capability tools are `InProcessTool`s named
   `<slug>.<name>`; the registry's never-raises invariant, arg validation, timeouts and the
   confirmation gate apply exactly as to `solus.*` and bridge tools. The dotted name is translated
   at the model boundary like every other dotted tool (`agent/prompt.py`).

## 2. The capability package

```
packages/api/src/solus_api/widgets/
├── __init__.py            # nothing but the docstring
├── capability.py          # WidgetCapability (frozen dataclass) + ToolBuilder protocol
├── registry.py            # discover_capabilities(): pkgutil over solus_api.widgets, loud on dups
├── publish_gate.py        # first_party_problems(): staff + matching capability, or 422
├── guard.py               # require_bundle(slug) + load_bundle_capabilities(): live installs only
├── solus_config.py        # read_bundle_config(session, project_id, slug, manifest) → dict
├── uninstall.py           # remove_bundle_traces(): kinds soft-delete, layout prune
└── fixture_bundle/        # the ST1 fixture capability (id "fixture-bundle")
    ├── __init__.py        # CAPABILITY = WidgetCapability(...)
    ├── routes.py          # APIRouter with GET /notes
    └── tools.py           # add_note / clear_notes InProcessTool builders
```

`WidgetCapability` fields: `id` (equals the manifest `extension.id`), `kinds`
(`tuple[DeclaredKind, ...]`), `tools` (`Mapping[name, ToolBuilder]`, each
`(BundleScope) -> Tool` where the scope carries `session_factory`, `project_id`, `user_id`),
`router: APIRouter | None`. Discovery mirrors CTR-01: adding a
capability is a _create_ (a new package), never an _edit_ of a shared list; a duplicate id or a
package without `CAPABILITY` raises at import time, naming both modules.

## 3. Routes — `/api/v1/projects/{project_id}/widgets/{slug}/...`

| Method | Path                                                              | Description                                                                               |
| ------ | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| ANY    | `/api/v1/projects/{project_id}/widgets/{slug}/{capability path…}` | Whatever the capability's router declares, mounted under the guard below                  |
| GET    | `/api/v1/projects/{project_id}/widgets/fixture-bundle/notes`      | Fixture: the project's `ext:fixture-bundle:note` entities, newest first (≤ 200)           |
| POST   | `/api/v1/projects/{project_id}/widgets/fixture-bundle/notes`      | Fixture write `{ text ≤ 200 }` → `201 { id, name, kind }`; proves the guard's write floor |

Conventions:

- `{slug}` follows [extensions.md](extensions.md) §3 (`^[a-z][a-z0-9-]{1,63}$` → else `422`).
  Only slugs with a discovered capability whose router is non-null are mounted; anything else is
  a plain FastAPI 404.
- **Guard** (`require_bundle(slug)`, a dependency added to every mounted router): `ProjectCtx`
  admits the caller (non-member → `404 not_found`, unchanged); then the install row for
  `(project, slug)` must exist, be `enabled`, not be team-blocked, and its **pinned** manifest
  must declare `backend.routes = true`. Any miss → `404 not_found` — the bundle simply is not
  there for this project (no oracle for install state beyond what `GET …/extensions` already
  shows a member). **Writes** (any method outside GET/HEAD/OPTIONS) additionally take the
  `member` floor (`403 forbidden` for viewers and share-only users) and the install-writes
  budget shared with the install routes (60/min/user, `429 rate_limited` + `Retry-After`) —
  enforced by the guard dependency itself, before the install lookup, so no capability handler
  ever carries auth code.
- Responses use the standard envelope; capability routers never build their own auth. The guard
  resolves `BundleContext { ctx, extension, install, manifest }` and hands it to handlers
  through an `Annotated[BundleContext, Depends(require_bundle("<slug>"))]` alias — the same cached
  dependency object the mount applies, so it resolves once per request; the install row's
  `settings` ride on `install`.
- Every guard refusal emits `widget_bundle.route_refused { slug, reason }` (ADR-011).

## 4. SOL tools and graph kinds

- `deps.get_sol_registry` loads the project's enabled, unblocked first-party installs
  (`load_bundle_capabilities(session, project_id, team_id)`) and `build_sol_registry` registers each
  capability's tools with the request's `project_id` and `user_id`. Registration is wrapped like
  the hosted-server path: a capability that fails to build logs and is skipped, never a 500.
- Tool descriptors are Solus-authored (`description_trusted=True`); a destructive tool sets
  `requires_confirmation=True` **and** carries a `consent_summary`, plus a `preview` where a
  before/after exists. The gate (`action-gate.md`) is untouched.
- Kinds land as `graph_entity.kind = "ext:<slug>:<name>"`, `origin = "extension"`,
  `source_id = NULL`, `external_ref = NULL`, `domain` from the manifest. Connector reconciliation
  sweeps never touch `origin="extension"` rows (same posture as `fingerprint`).

## 5. Uninstall — amends extensions.md §6.4

`DELETE /api/v1/projects/{project_id}/extensions/{slug}` now, in one transaction:

1. deletes the install row (settings live on it) and every `extension_storage` row;
2. **soft-deletes** every live `graph_entity` in this project whose `kind` is one of the pinned
   manifest's `ext:<slug>:<name>` kinds (and their live `graph_edge`s), `deleted_at = now()` —
   reversible per ADR-027, but gone from every read;
3. **prunes** `ext:<slug>` refs from every user's `widget_layouts` row in this project;
4. decrements `install_count`; emits `extension.uninstall` with
   `{ slug, version, storage_rows_deleted, entities_soft_deleted, layout_slots_pruned }`.

The desktop then removes `~/.solus/extensions/<slug>/<version>/` as before. The Store copy becomes
"Uninstall <name>? Its widgets, tools and the graph data it added leave this project. Its
settings are removed too." (`docs/wireflows/store.md`).

## 6. The repo `.solus/project.toml` `[ext.<slug>]` section

- The GitHub connector, when the synced tree contains `.solus/project.toml`, fetches that one
  blob (≤ 64 KiB), decodes it with `tomllib`, keeps **only** `[ext.<slug>]` tables (≤ 16 slugs
  matching the id regex, ≤ 16 keys each, scalar values only, ≤ 4 KiB per table) and lands one
  entity: `type="solus_project_toml"`, `domain=code`, `source_key=".solus/project.toml"` (not
  `solus_config` — that kind is the project's `.solus` root node from SOLUSDEV-242),
  `properties={"ext": {...}}`. A malformed or oversized file is a `SyncError`, never a raise;
  the entity is simply absent.
- `read_bundle_config(session, project_id, slug, manifest)` returns that table filtered and
  type-checked against the bundle's `[[settings.fields]]` (unknown keys dropped, wrong types
  dropped), read only from a `solus_project_toml` row with `origin = "connector"` — a same-kind row a
  bundle or user wrote is never mistaken for the repo config. `effective_bundle_config` layers
  manifest defaults ← repo table ← the install row's `settings`; the fixture's `add_note` honours
  `prefix` and `max_notes` from it. Nothing here is ever a secret (CLAUDE.md §7; ADR-034 §5).
  Red-team fixture: `injection_corpus` surface `solus_config` — a hostile value is typed data,
  changes no tool spec, and lands only as an inert prefix.
- GitLab: same shape (`code_host.solus_config_entity`), read through the raw-file endpoint and
  bounded by bytes received since GitLab's tree carries no size.

## 7. Publish validator additions (extensions.md §5.1)

New `422 bundle_invalid` problem strings, all produced in the request path so nothing is stored:

| problem                                                    | when                                                                                                                                            |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend: first-party only (publisher is not Solus staff)` | any first-party table and the caller is not `RequireStaff`                                                                                      |
| `backend.capability: no in-repo capability named <slug>`   | staff, but `solus_api.widgets` has no package with that id                                                                                      |
| `graph.kinds.N: not provided by capability <slug>`         | a declared kind the package does not define                                                                                                     |
| `tools.names.N: not provided by capability <slug>`         | a declared tool the package does not build                                                                                                      |
| `backend.routes: capability <slug> has no router`          | `routes = true` but the package exports none                                                                                                    |
| `extension.id: reserved for a Solus first-party bundle`    | a NON-first-party manifest whose id is an in-repo capability, from a non-staff publisher (slugs are claimed forever, so Solus must keep the id) |

`graph`/`tools` declared without `[backend]` are still first-party (staff + package required).
A publisher row carrying a reserved vendor name (seeded by staff) publishes only while the
account is still on `SOLUS_STAFF_USER_IDS`; afterwards every publish is `409
publisher_name_reserved` (security review M3).

## 8. Data events (ADR-011)

`widget_bundle.route_refused { slug, reason }` · `extension.uninstall` payload widened (§5) ·
`widget_bundle.tool_registered { slug, tools: N }` once per registry build that adds tools.

## 9. Security checklist (this surface)

| §7 rule                        | How                                                                                                                                                                        |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No code from untrusted bundles | Capabilities are in-repo packages; the manifest only names one; publish rejects claims without code                                                                        |
| Centralised auth               | `ProjectCtx` + `require_bundle` dependency on every mounted router; no handler does its own auth                                                                           |
| Tenant isolation               | Every query in the guard, the fixture routes, the tools and uninstall is `project_id`-scoped; an isolation test proves team A cannot read team B's notes or hit B's routes |
| Model proposes, Solus decides  | Tools ride the W0-04 registry; destructive ones set `requires_confirmation` + `consent_summary`                                                                            |
| Ingested content is data       | `[ext.<slug>]` values are typed against the settings schema and never enter a prompt unframed                                                                              |
| Rate limits                    | Install-writes budget on capability writes; SOL turns under the existing budgets                                                                                           |
| No secrets                     | `.solus/` is committed, team-visible; nothing secret is accepted from it                                                                                                   |

## 10. Widgets in the graph (STORE ST2)

Every installed extension — community or first-party — has a node in the project's graph, a peer
of Live Bench under a per-project workspace root. ADR-027 as amended 2026-09-06 (domain
`workspace`, origin `system`). Code: `packages/api/src/solus_api/widgets/graph_nodes.py`.

| kind               | one per        | name                  | attrs                                                         |
| ------------------ | -------------- | --------------------- | ------------------------------------------------------------- |
| `solus:workspace`  | project        | `Workspace`           | `{}`                                                          |
| `solus:live_bench` | project        | `Live Bench`          | `{}`                                                          |
| `solus:widget`     | install (slug) | the manifest's `name` | `{ slug, version, enabled, publisher, views: ["widget", …] }` |

Edges: `solus:workspace -[contains]-> solus:live_bench` and `-[contains]-> solus:widget`, all
`domain_pair = "workspace<->workspace"`, `origin = "system"`. Every row has `domain = workspace`,
`origin = system`, `source_id`/`external_ref` NULL.

**Lifecycle (Solus code only — a bundle never registers its own node, ADR-035):**

- `PUT …/extensions/{slug}` (install) registers the node in the install transaction and re-registers
  on a version change (name / version / views follow the new pinned manifest). `extension.install`
  carries `graph_node_id`.
- `PATCH …/extensions/{slug} { enabled }` mirrors into `attrs.enabled`.
- `DELETE …/extensions/{slug}` soft-deletes the node and **every** live edge touching it, in either
  direction and of any origin, in the same transaction as the ST1 sweep — no dangling edge, ever.
  `extension.uninstall` carries `graph_node_id`.
- Registration is idempotent per `(project, slug)`; a stale pinned manifest skips registration
  rather than failing the install.

| Method | Path                                                    | Description                                                                                                                                                                                                                                                                                                                                                                                          |
| ------ | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/projects/{project_id}/widgets/graph`           | **Pure read** of the layer: `{ root, live_bench, widgets[], edges[] }` (standard entity/relation shapes). `root`/`live_bench` are `null` until the layer exists — nothing is written on a GET, so a viewer may call it. `ProjectCtx`.                                                                                                                                                                |
| POST   | `/api/v1/projects/{project_id}/widgets/graph/reconcile` | **Heal** the layer from the install rows: backfill installs that predate ST2, refresh attrs (version, enabled, blocked), retire orphan nodes. `member` floor + the shared install-write budget (`429` + `Retry-After`). Returns the graph plus `reconciled { created, refreshed, pruned }`; emits `widget_bundle.graph_reconciled` only when something changed. `graph` is a reserved capability id. |

Rules the service (`widgets/graph_nodes.py`) enforces:

- **Only its own rows.** Every read, adopt and retire matches `kind` AND `domain = workspace` AND
  `origin = system`; a connector or manual row that happens to carry a `solus:` kind is never
  touched. Strays are retired by row (never by a slug re-lookup), including nodes with a missing
  or non-string slug.
- **Singletons are the database's.** Partial unique indexes (`uq_graph_entity_workspace_singleton`
  on `(project_id, kind)` for the root and Live Bench, `uq_graph_entity_workspace_widget_slug` on
  `(project_id, attrs->>'slug')`) make concurrent installs converge: the loser rolls back its
  savepoint and adopts the winner.
- **An install whose pinned manifest no longer parses keeps its node** — reconcile treats every
  install row as wanted, whether or not its facts can be rebuilt.
- A team block shows as `attrs.blocked = true` and forces `attrs.enabled = false`; the node stays.

**What never sees the layer — and cannot be steered into it:** SOL's graph feed INTERSECTS any
requested domains with `NON_WORKSPACE_DOMAINS` and drops workspace entities (and edges touching
them) even when one is the anchor; `query_graph`'s `domains` is a closed enum without `workspace`;
`get_entity` answers `NOT_FOUND` for a workspace node; RAG retrieval excludes the domain in its
entity scope on both the ANN and the full-text path (red-team fixture: an extension named as an
instruction never surfaces). Checkers run on that feed; fingerprinting keys on connector refs the
layer does not have; connector reconciliation is `source_id`-scoped and the sync landing path
refuses any connector entity claiming the workspace domain. The generic entity routes list the
layer (the Context Model screen shows `solus:widget · workspace`); the mutating entity routes
SOLUSDEV-242 added accept only manual Physical Robot roots and answer `409 conflict` for a
`system`-origin node (tested).
