# SOLUSDEV-242 execution plan

User approved Phase 0 and continuation through phases on 2026-09-05. Base:
`c905d28392a4512261bdc3df3ab26be2f9c929bf`, branch
`SOLUSDEV-242-workspace-graph-w2`. Existing untracked `docs/design/` is user material.

## 1. Task decomposition

| ID        | Task                | Scope and contracts                                                             | Size |
| --------- | ------------------- | ------------------------------------------------------------------------------- | ---- |
| P1-api    | Shared graph layout | `docs/api/workspace.md`, ProjectCtx, versioned coordinates                      | M    |
| P1-canvas | Zoom engine         | Registry, bounded containment forest, links, animated accessible navigation     | L    |
| P1-root   | Wiring              | Typed graph reads, layout persistence, shared focus path, Workspace integration | M    |
| P2        | `.solus`            | Real section/note identities, reuse existing actions, remove panel              | L    |
| P3        | Service Add         | I1 cached accounts/listing, first select, document hierarchy, change-only sync  | L    |
| P4        | Physical Robot      | Independent instances/categories, rename, safe orphaning, R2 hook               | L    |
| Review    | Verification        | Fresh code/security and language reviews, UI, suites, QA report                 | L    |

## 2. Dependency graph

Approved architecture/API → P1-api and P1-canvas and P1-root. All P1 work →
integrated gate/review/commit → P2 → gate/review/commit → P3 → gate/review/commit →
P4 → full verification/QA/commit. Later phases do not begin implementation early.

## 3. Sequential vs parallel

P1-api owns Python; P1-canvas owns only a new navigation directory; P1-root owns
the client/focus integration. They share only the stable API and the component
props sent in the worker assignment. Everything within P2–P4 touching the same
graph files is sequenced. Reviewer work is read-only and parallel where slots allow.

## 4. Execution mode

Bounded in-process workers for P1-api/P1-canvas. Root integrates and owns later
phase orchestration. No worktree or branch switch, no remote operations.

## 5. Ownership

Manifests are written before implementation to `.Codex/state/ownership/` per
AGENTS.md and mirrored to the actual H12 path `.claude/state/ownership/`.

- P1-api: `packages/api/src/solus_api/models.py`, `main.py`,
  `services/workspace_layout.py`, `routers/workspace_layout.py`,
  `packages/api/tests/test_workspace_layout.py`, one `*solusdev_242_workspace_layout.py` migration.
- P1-canvas: `apps/desktop/src/renderer/src/features/graph/navigation/` (including tests).
- P1-root: graph integration files outside navigation; workspace focus store/adapter;
  `lib/api/workspace.ts` and its tests; `lib/api/resources.ts`; workspace screen tests;
  governing architecture/API/wireflow and QA documents; ownership manifests.
- Later phase manifests will assign exact paths before their workers begin.

## 6. Test-first targets

P1-api: default/save/read, stale/racing writes, isolation, viewer/unauthenticated,
invalid IDs/coordinates/oversize, deleted-node pruning, event and migration.
P1-canvas: 3-level in/out, leaf selection, cyclic/multiple containment parents,
cross-domain links projected at each level, 243+ nodes capped to 24 cards, drag,
keyboard, reduced motion and no provider dependency.
P1-root: focus trail reaches shared widgets; cross-project/stale async replies;
layout loading/saving/conflict/error/project switch; graph relation pagination.
P2: creation/backfill/import/typed/error persistence and real graph edges; no panel.
P3: two documents, separate projects, cached reopen/selection/zoom zero calls,
one ingestion per changed signal, source-specific hierarchy.
P4: independent children/rename, safe confirmed deletion retaining visible parts.

## 7. Risks and flags

Existing API graph neighborhood cap remains 2. Selectable navigation containers
must have real entity IDs. No protected contracts, ADRs, harness or environment
files are edited. Graph writes remain manual-only and scoped. Provider calls
are reserved for the explicit service-ingestion verification; no background
provider sweeps are launched casually. Local artifacts require a persistent
root for durable storage; root `.env` is not edited. The user connected Onshape during P2; its live account cache is still empty.
P3 will populate it once through an explicit I1 listing refresh, then retain that
listing without provider calls on dropdown reopen. Ponytail is not available in the exposed tools;
reviewers perform the bounded simplification pass and this limitation is reported.

## Phase 2 execution detail

Phase 1 checkpoint: `52a6b06`; all gates passed. Stable seam: existing `.solus` HTTP
payloads remain; every entry now has a real entity ID. Section nodes identify themselves
through `type=solus_section` and `properties.section`; entry nodes use
`properties.solus_entry_id`. Complete text remains in the existing entry payload.

- P2-api owns `services/solus_config.py`, new `services/solus_graph.py`,
  `routers/solus_config.py`, `models.py` only if a metadata comment needs updating,
  one `*solusdev_242_solus_graph.py` data migration, and API tests affected by the
  now-real section/entry graph entities. Tests first for creation, idempotent legacy
  backfill, containment/Impact, note editing/deletion, artifact identity/bytes,
  concurrency and tenant boundaries. It may not change unrelated behavior tests.
- P2-ui (root) owns the existing panel/actions/hook/client types and Workspace wiring,
  navigation card content/menus where necessary, desktop tests, and tier-1 docs.
  Extract the existing handlers and composers; remove SolusPanel and its obsolete
  layout, migrate its behavior tests onto real nodes. Verify import/type/error editing
  and same focus/graph-refresh behavior in the running product.

P2-api and P2-ui run in parallel against that fixed seam; neither changes the other's
files. All P2 work then joins code/security review, suites, real UI, and a local commit.
The Add panel's service and hardware implementations remain sequenced into P3/P4.

## Phase 3 execution detail

Phase 2 checkpoint: `c820825`; browser gate and reviewed fixes passed. Root read the I1 API
rows, connector contract, change-signal spine and Workspace wireflow; the Phase 3 API/spine
amendments above settle cache-only reads, exact binding and change-only ingestion.

- P3-api owns I1 listing/binding routers/services, connector cache/flight and change gate,
  Onshape document-root output/local backfill, the matching data migration, and API tests.
  Its internal sequence is cache-only API and identity-safe attachment → real document
  hierarchy → strict probe/flight handling → integration/contract regression. Tests first.
  It does not edit client types, renderer files, docs, shared contracts or environment files.
- P3-ui (root) owns `features/graph/`, `lib/api/resources.ts` and its tests/generated schema,
  and tier-1 docs. It builds against the unchanged I1 success payloads plus `cache_only` and
  `listing_not_cached`: retained account/listing state, guarded first attachment/job observation,
  zero-request reopen/reselection, provider-root focus, and visible errors.

Backend and frontend have disjoint files and a fixed HTTP seam, so run in parallel. Backend
cache/flight/attachment changes share unstable helpers and remain one sequential worker unit.
After integration, fresh code/security reviews, suites and actual connected-Onshape checks
precede the local Phase 3 commit. No provider listing or sync runs as a side effect of coding.

## Phase 4 read-only preparation

While the Phase 3 external-edit gate is pending, an explorer audited existing manual graph
surfaces without changing implementation. API.md §2.4 plans entity mutations but the current
router implements reads only. Existing GraphEntity/GraphEdge tables support manual kinds,
JSONB references, independent IDs and optimistic versions; no migration or contract change is
expected. Phase 4 implementation still begins after the Phase 3 gate/checkpoint.

Planned seam: a transaction-scoped PhysicalRobotService creates a new instance and seven
independently identified category children every time. The manual endpoint and later R2 call
that same service; it is not a per-project ensure/singleton. Root references remain null-only
(`hardware_config_ref`, `transport_refs`) until R5/R3 contracts exist. Containers use the existing
project domain; parts retain their original domains and ownership.

Before code, amend the planned entity POST/PATCH/DELETE payloads for this narrowly supported
manual subtype, including If-Match rename/delete conflict semantics. Preserve connector,
fingerprint and `.solus` ownership boundaries. Deletion targets explicitly owned containers and
containment edges, retaining actual parts and unrelated edges. Persistent orphan discovery can
read retained soft-deleted robot ownership edges; never modify connector part properties to mark
orphans. A selected orphan remains discoverable even when it also has CAD/service containment.

Manual rename needs an authoritative graph modification stamp in project detail/cache validation,
since counts and source timestamps do not change. Manual graph events must use a documented null
source rather than inventing a Source, and publish after commit. Exact worker ownership and
unit/integration/browser fixtures will be recorded before implementation; test nonempty retained
parts, not only empty categories, for the deletion gate.

## Phase 4 execution detail

Phase 3 checkpoint: `ba4bd04`; both real Onshape documents and the user's real edit
passed the browser gate. The fixed HTTP seam is now in `docs/api/workspace.md`.

- P4-api owns `services/physical_robots.py`, `routers/entities.py`,
  `routers/projects.py`, `graph/live.py`, and focused API robot/live tests. It
  implements the documented narrow mutations, durable orphan query, graph stamp
  and after-commit hints. No migration or protected contract edit is expected.
- P4-ui (root) owns renderer `features/graph/`, typed robot client and tests,
  `lib/api/resources.ts`, generated OpenAPI/schema, and tier-1 docs. It composes
  Hardware creation, inline rename, confirmed removal, and bounded persistent
  orphan listing/reveal into the existing navigator.

API and UI run as in-process parallel work against that fixed seam; file sets
are disjoint. Tests precede implementation. Both join before fresh code/security
and language review, complete regression suites, real two-robot/nonempty-part
deletion and reload checks, QA report, and the final local phase commit.
