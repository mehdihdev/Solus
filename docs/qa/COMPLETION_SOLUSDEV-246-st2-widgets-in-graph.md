# Completion Report — SOLUSDEV-246 · STORE ST2: widgets in the graph

**Branch:** `SOLUSDEV-242-home-cross-project-surface` (same branch as ST1 by founder instruction;
commits prefixed `SOLUSDEV-246:`). **Status:** integrated, verified live, ready for human review.
Nothing pushed; no MR opened.

## What was built

Every installed extension — community or first-party — now has a node in the project's graph: a
`solus:widget` peer of a `solus:live_bench` node under a per-project `solus:workspace` root, all
in the new sixth domain `workspace` with origin `system`, joined by `contains` edges. Registration
is Solus code inside the install lifecycle; uninstall removes the node and every edge touching it.

| Part                 | Where                                                                                                                                                                                                                                                |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Domain `workspace`   | `models.Domain`, `solus_contracts.connector.Domain`, manifest `GRAPH_DOMAINS`, shared-types `DOMAINS` (focus, widget, first-party); migration `b3f1c2d4e5a6` recreates the `domain` CHECK on `graph_entity` and `error_solution`                     |
| Origin `system`      | ADR-027 amendment (dedicated commit `0562140`), together with the domain                                                                                                                                                                             |
| Service              | `packages/api/src/solus_api/widgets/graph_nodes.py`: ensure root / Live Bench, register (idempotent, savepoint-safe), update, unregister (node + every edge), `load_workspace_graph` (pure read), `reconcile_workspace_graph` (heal + prune, counts) |
| Lifecycle hooks      | `routers/extensions/installs.py`: install/update register, PATCH mirrors `enabled`, DELETE unregisters; `extension.install` / `extension.uninstall` carry `graph_node_id`                                                                            |
| Routes               | `GET /api/v1/projects/{id}/widgets/graph` (pure read) and `POST …/widgets/graph/reconcile` (member floor + install-write budget, `widget_bundle.graph_reconciled` event); `graph` is a reserved capability id                                        |
| Uniqueness           | Migration `d5e6f7a8b9c0`: partial unique indexes for the two singletons and one widget node per `(project, slug)`; writers adopt the winner on `IntegrityError`                                                                                      |
| SOL exclusion        | `agent/feeds.py` intersects requested domains with the non-workspace set and drops the layer even when anchored on it; `query_graph` `domains` is a closed enum; `get_entity` answers `NOT_FOUND`; RAG entity scope excludes the domain              |
| Connector guard      | `connectors/runtime.py` refuses any connector entity claiming the workspace domain (sync error, never landed); capability packages may not declare workspace kinds                                                                                   |
| Manifest storage fix | `manifest_document()` in the contract; publish stores the manifest as authored; migration `c4d5e6f7a8b9` repairs rows stored between ST1 and this fix (see "Found by the real run")                                                                  |
| Docs                 | `docs/api/widget-bundles.md` §10, `API.md` §2.18 rows, `docs/schemas/extensions.md`, `docs/architecture/extensions-runtime.md`, `docs/contracts/focus.md` + `extension-manifest.md` + `docs/extensions/manifest.md`, DECISIONS.md                    |

## Governing docs consulted

DECISIONS.md (ADR-001/027/032/035), `docs/contracts/focus.md`, `widget.md` (CTR-01),
`extension-manifest.md`, `agent-tool.md` (W0-04), `docs/api/extensions.md` + `API.md`,
`docs/schemas/extensions.md`, `docs/wireflows/store.md`, `docs/architecture/extensions-runtime.md`.
`docs/design/SPEC.md` and `docs/design/screens/` do not exist; "W5" is a Workspace-series ticket not
yet in the repo, so this ticket ends at the data and the API and is verified through the entity
routes and the Context Model list.

## Verification

- **New suites:** `test_widget_graph_nodes.py` (19), `test_widget_graph_routes.py` (7); additions to
  `test_contracts_package.py`, `test_extension_manifest_contract.py` (stored-form round trip),
  `test_extension_installs.py`, shared-types `focus.test.ts`. Isolation: team B → 404 on both
  routes; per-project singletons; the sweep never crosses projects or touches rows it did not
  write. Concurrency: four sessions racing the first registration converge on one row per kind.
- **Affected existing suites** (installs, feeds, builtin tools, get_entity, red team, retrieval,
  runtime, connectors, ST1 suites, contracts): 435 passed after the review fixes. Full API suite:
  see the line at the end of this section. Shared-types 230 passed; desktop typecheck clean and
  2608 tests passed after the domain change (desktop types `domain` as a string).
- **Reviews:** fresh-context code review — 2 HIGH (reconcile pruned installs whose manifest no
  longer parses; singletons had no uniqueness backstop), both fixed. Security review — 2 HIGH
  (the GET wrote rows without a member floor or budget; the pruner matched on kind alone), 4 MEDIUM
  (SOL exclusion steerable via `domains`/anchors/tools/RAG; duplicate singletons; connector and
  manifest could emit the domain; blocked installs shown enabled), 3 LOW — all fixed except the
  contract narrowing under MEDIUM-3 (below).
- **Real run (2026-09-06, live API + ARQ worker + Postgres/Redis, dev DB migrated to
  `d5e6f7a8b9c0`):** `GET …/widgets/graph` pure read; **install BOM (a community bundle) → a `BOM`
  node** with `domain workspace`, `origin system`, `contains` edge from the root beside Live Bench;
  `GET /entities?domain=workspace` lists all three; `POST …/graph/reconcile` is a no-op with zero
  counts on a healthy layer; the other team's user gets `404` on reconcile; disable mirrors
  `enabled: false`; **uninstall → node tombstoned, `widgets: []`, zero dangling live edges** by
  direct database query; both partial unique indexes present; no tracebacks in the API log. An
  earlier SOL turn against the project mentioned no `solus:` kind, `Workspace`, or `Live Bench`.
- **Not exercised live:** the desktop Context Model screen against this API (unit-tested;
  `domain` is a string in the renderer), the viewer-role paths (single team in the dev DB;
  route-tested), and a concurrent two-terminal install. All are in the Cowork QA file.

## Found by the real run, not by the suites

The first live install of BOM returned a 500. ST1's publish stored `manifest.model_dump()`, and
after the contract bump that dump carried the defaulted `graph`/`tools` tables, which a v1
manifest's own re-parse rejects as unknown fields; the suites only ever seeded raw fixture dicts.
Fixed by storing the manifest as authored (`manifest_document`), a repair migration
(`c4d5e6f7a8b9`), a round-trip contract test over every valid fixture, and a publish→install
end-to-end test. Recorded in `docs/contracts/extension-manifest.md` ("Stored form").

## Decisions made under delegated judgment

- The layer is absent until the first install or an explicit reconcile; the GET returns nulls
  rather than creating rows on a read (security review HIGH-1; "empty beats invented").
- A team block leaves the node in place with `blocked: true` and `enabled: false`; the layer
  reflects install rows, policy is shown as state.
- Attrs carry `slug, version, enabled, blocked, publisher, views` — nothing else, so nothing
  authored inside a bundle beyond its display name and publisher reaches the graph.
- `reconcile_workspace_graph` treats every install row as wanted even when its pinned manifest no
  longer parses, so a contract tightening can never prune a live install's node.
- The connector contract's `Domain` gains `WORKSPACE` only to mirror `models.Domain`; the sync
  landing path refuses it per item. The manifest's `GRAPH_DOMAINS` also mirrors it; capability
  discovery and the publish gate refuse workspace kinds in code. **Follow-up needing in-chat
  approval (tier-2):** narrow `GRAPH_DOMAINS`/`GraphDomain` and the connector `Domain` so the
  vocabulary itself excludes `workspace` (security review MEDIUM-3); left as-is because a contract
  edit needs approval before editing.
- `origin="linking"` was already in use and undocumented; the ADR-027 amendment records it.

## Env you must set

Nothing new beyond ST1 (`SOLUS_STAFF_USER_IDS`, shared `SOLUS_ARTIFACT_LOCAL_ROOT` in local dev).
The dev/staging/prod databases need `alembic upgrade head` (three new migrations; the CHECK
recreation on `graph_entity` takes a brief lock — schedule accordingly).

## Commits (ST2, after `110fc4c`)

`0562140` ADR-027 amendments · `acf8831` workspace domain + migration · `df20d02` graph-layer
service, hooks, route, SOL exclusion, docs · `e7448ee` docs · `7bbe018` manifest stored as
authored (real-run fix) · `b257bd8` Phase 4 fixes (read/heal split, tight matching, indexes,
unsteerable exclusion, connector guard) · plus this report and
`docs/qa/COWORK_QA_store-st2-widgets-in-graph.md`.
