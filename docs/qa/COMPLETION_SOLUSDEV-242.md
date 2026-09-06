# SOLUSDEV-242 implementation record

Branch: `SOLUSDEV-242-workspace-graph-w2`. Base: `c905d28392a4512261bdc3df3ab26be2f9c929bf`.
The user approved Phase 0 and continuation on 2026-09-05. Local commit per phase;
no remote operations. Existing untracked `docs/design/` is user material and is not staged.

All four implementation phases and their live application gates are complete. Local
checkpoints: Phase 1 `52a6b06`, Phase 2 `c820825`, Phase 3 `ba4bd04`; Phase 4 is the
final commit containing this handoff. Humans retain push, MR and merge ownership.

## Governing material

Read root AGENTS.md, desktop CLAUDE.md, DECISIONS.md, `docs/design/screens/SPEC.md` §2,
the existing Workspace/.solus wireflow and API plan, graph/focus and change-signal
architecture, and `docs/contracts/focus.md`. The session-approved amendments live in
`docs/architecture/workspace-navigation.md`, `docs/api/workspace.md` and
`docs/wireflows/workspace.md`. Implementation map: `docs/CODEMAPS/workspace.md`.

## Phase 1 — navigator

- Type registry, deterministic containment forest with cycle/multiple-parent handling,
  projected cross-domain edges and real endpoints at every depth.
- At most 24 cards per page, readable fixed card dimensions, wheel/double-click/keyboard
  navigation, breadcrumbs, anchored animation and reduced-motion support.
- Centered first node, draggable surrounding roots and project-shared coordinates.
  Optimistic writes serialize first creation, preserve teammate coordinates on retry,
  prune known deletions, drain queued moves after leaving the screen and bind writes to
  the captured authentication identity.
- Complete graph snapshot cache retains the previous screen-switch behavior. Project
  detail/version and TTL validate it; mutations invalidate it; auth changes clear it.
- Shared focus includes real ancestor paths and discards late project/account replies.
  Obsolete list-summary/cache code was removed; its existing behavior tests were moved
  onto the live graph hook.
- Added layout API/model/migration and refreshed OpenAPI/desktop generated types. The
  regenerated schema also includes the already-shipped W1 routes missing from its old snapshot.

Tests were written and run RED before implementing the API, navigator, client/hooks and
focus-path integration. Review findings received regression tests before fixes: nested
nonfinite input, exact centering, stale deletion coordinates, queued drag loss, auth
boundaries, cached screen returns, and a teammate's newly added coordinates on conflict.

Verification completed on 2026-09-06:

- Desktop: 251 test files, **2613 tests passed**. Node/renderer typechecks and the
  Electron production build passed. Scoped ESLint is clean.
- Backend: **4584 passed, 3 skipped, 1 expected failure**, exit code 0. Live-provider
  opt-in tests were excluded. Changed Python Ruff/strict mypy and format checks passed.
  The companion subprocess requires the project virtual environment on PATH; its initial
  missing-MCP failure passed after that environment correction, with no code workaround.
- Scoped frontend coverage: **97.1% lines, 88.09% branches**. Layout API/router measured
  **99% coverage**; tracing used `concurrency=greenlet,thread` so SQLAlchemy-resumed lines
  were measured correctly. Layout tests include 49 validation/authorization/concurrency cases.
- Single Alembic head **a3f242b9c610**. Upgrade/downgrade/upgrade verified on the test DB;
  the additive migration was also applied to the local development DB.
- Actual renderer and API, isolated 251-entity/249-relation fixture: three-level wheel
  zoom and reversal, keyboard/breadcrumbs, both cross-link endpoint drills, real leaf
  focus/Live Bench, reduced motion, drag/reload/project isolation, and queued writes
  after screen exit all passed. Cached screen return issued zero entity/relation walks
  and no sync requests. A browser-discovered animation-origin defect was fixed and
  retested to a 0.25 px discrepancy.
- 244 children traversed on all 11 pages, repeated three times: maximum **24 cards** and
  **264 navigator DOM descendants**. 925 paging frame intervals had median/p95 **16.7 ms**,
  maximum **66.7 ms**, with two intervals over 33.4 ms. These are headless Chrome frame
  scheduling measurements on this machine, not a guarantee for every display.
- Fresh code/TypeScript review and dedicated security review passed, including Python/
  database checklists. Browser evidence: `/tmp/solus-w242-e2e-report.md` and its named
  screenshots/JSON reports. The QA browser processes were closed.

Ponytail and standalone secret/duplication scanners are unavailable in this session;
the fresh code/security reviewers performed the scoped simplification, dead-code and
security passes. No SOL tool, fingerprint or tool-knowledge invariant was weakened.
No environment file was edited. The user still performs push/MR/merge.

## Decisions exercised under the user's approval

Positions are shared per project. Every future selectable section/category/note has a
real graph identity. The server can return valid coordinates for a teammate's newer
nodes; local deletion pruning therefore uses known removals, not an incomplete local
snapshot as authority. The existing two-hop focus-query cap remains independent of
navigation depth. Existing full graph reads are retained, while rendered cards and
drawn links are bounded. The renderer adds no graph-layout dependency.

## Phase 2 — `.solus` becomes a node

Moved the existing W1 upload, Ask SOL, text, edit and remove handlers into canvas-node
controllers/composers. Removed the old panel and its layout entirely. A new project has
one centered top-level `.solus`, five persisted section children and five containment edges.
Notes/SOL/error entries now have stable graph identities; full text stays in `solus_entries`.
Artifact identities, retained bytes and direct root `references` edges are preserved.
A project-row lock serializes creation/repair/writes, and an additive migration backfills
existing projects idempotently. No HTTP route or shared contract was added.

Governing amendment: `docs/api/solus.md` now documents the section/entry identities,
containment and deletion semantics. The architecture/wireflow above still govern the flow.
Code map and Cowork QA were updated. The Add entry point is present; its service and
hardware workflows are intentionally completed in the following phases.

Changes under delegated judgment: a failed edit keeps its draft; project/account changes
remount transient action state and stale async responses are ignored. Since text entries
now delete graph data, the existing concrete confirmation dialog also covers note/SOL
removal. All graph mutations invalidate cached neighborhoods, refresh surviving selection,
and clear a deleted selection. Browser QA found Escape leaking through context menus into
canvas navigation; a scoped listener now closes the menu first and cleans up on unmount.

Verification:

- Desktop: **2621 tests in 252 files passed**, plus node/renderer typechecks and Electron
  production build. Changed-file ESLint has zero errors/warnings and formatting is clean.
- Backend API suite: **3611 passed, 4 skipped**; remaining Python suites: **983 passed,
  2 skipped, 1 expected failure**. The API suite workers loaded before a final bounded-query
  refactor; the exact final hierarchy implementation passed the focused **25-test** suite.
  Changed Python Ruff and strict mypy passed (217 checked sources/tests/migration).
- Focused UI coverage measured **98.85% lines, 88.02% branches** before the final two
  upload-scope regression tests and Escape listener. Focused backend coverage with branches
  enabled measured **96%**, using greenlet-aware tracing. Tests cover concurrency, idempotent
  migration/repair, legacy document preservation, roles, foreign references, editing/deletion,
  confirmation, stale requests, shared focus, all existing W1 menus and action failure paths.
- Single Alembic head **b6f242d8e731**, parent **a3f242b9c610**; applied and confirmed on
  the development DB. Migration/repeated migration and deleted-project cases are tested.
- Real UI created disposable project **01a074b6-a211-772a-a264-b2bf5df84306**. Sole `.solus`
  measured exactly centered (world 0,0; viewport delta 0,0). Wheel exposed all five sections.
  All section menus passed. A PDF imported through the actual file chooser became a real
  artifact node; a typed 48 V specification survived reload with the same entry/entity IDs.
  An error edited inline retained its ID and refreshed the inspector; confirmed deletion
  cleared its selected focus. Authorized API inspection confirmed the actual nodes and
  containment/reference edges. No provider/sync calls, page errors, or application/API
  failures occurred; the existing missing favicon produced one unrelated 404.
- Menu Escape was retested in the browser **three times**: first Escape closed the menu
  at depth 1, next Escape returned to overview. Evidence: `/tmp/solus-w242-p2-report.md`,
  `/tmp/solus-w242-p2-report.json`, `/tmp/solus-w242-p2-escape-report.json` and named screenshots.
- Fresh code, TypeScript/Python/database and dedicated security reviews passed; findings
  were fixed and retested. Ponytail remains unavailable, so simplification/dead-code review
  used the installed review workflow and a scoped export/reference sweep.

The user connected Onshape during this phase. Its I1 account cache has no document listing
yet; Phase 3 will load it once deliberately through I1, then retain cache-only choices.

## Phase 3 — service picker and change gates

Implementation, review and the live import/navigation/change gates are complete.

- Add lists Home accounts through I1 and initially uses cache-only document reads. Explicit
  Load/Refresh populates the shared catalog. Reopening accounts/picker and reselecting a cached
  document use retained state without network calls. Project bindings match exact accounts and
  repository/branch identities; source lists are fully paginated.
- First selection attaches/imports a document and observes its accepted job. Two Onshape documents
  produce independent `cad_document` roots; Git's repository/directory/file graph is reused. The
  additive local migration wraps legacy trees without provider requests or replacing part IDs.
- Established cloud sources require a successful change probe before ingestion. Probe failures
  preserve the last successful timestamp, remain retryable where appropriate, and never request
  exports as a fallback. Refreshed OAuth credentials reach the eventual sync.
- Payload/source flights renew their owner token during slow exports. Loss/outage cancels work;
  cleanup is bounded and cannot release a successor. Accepted busy jobs retain their selection,
  defer by 30 seconds in ARQ, and have a two-hour queue bound. Acquired work has a one-hour deadline;
  other worker tasks retain their settings.
- Existing authenticated project SSE hints refresh the graph. Initial readiness validates its
  version; reconnect catches missed changes. Each snapshot has a fresh typed transport and only
  its active read can publish cache state. Account/project generations permanently invalidate
  stale asynchronous actions even after returning to the original account/project.
- Failed imports keep visible recovery guidance on reselection. Generic linked/service selection
  reveals and focuses the actual card within a small viewport. No provider dependency was added
  to the navigator.

Governing amendments: I1 cache-only/attachment semantics in `docs/api/API.md`, corrected probe
and lease rules in `docs/architecture/change-signal-spine.md`, Workspace SSE/picker architecture,
wireflow and code map, expanded Cowork QA. OpenAPI and generated renderer types include the new
optional `cache_only` query parameters. No new shared contract, ADR, credential schema or domain.

Verification so far:

- Final desktop suite: **2652 tests in 257 files passed**. Node/renderer typechecks and Electron
  production build passed. The canonical build's generator initially failed because npm DNS was
  unavailable; the exact cached OpenAPI 7.13.0 CLI, followed by the same typecheck/build steps,
  completed successfully. No dependency or lockfile change was needed.
- Focused new UI coverage: **94.87% lines, 87.3% branches**, 180 tests; measured before the final
  card reveal geometry regression, which then passed with all navigator/full desktop tests.
- Complete final API suite: **3663 passed, 4 skipped** with branch coverage enabled. The
  changed production modules and document-root migration measured **89% combined coverage**;
  document graph/migration measured 100%. The worker registration test now accepts ARQ's
  configured function wrapper and still verifies reconciliation and hourly detector schedules.
  Logs/report: `/tmp/solus-w242-p3-backend-coverage.log` and `-coverage.json`.
- Remaining Python suites: **983 passed, 2 skipped, 1 expected failure**. Changed Python Ruff,
  formatting and strict mypy passed. Fresh code, TypeScript, Python and dedicated security reviews
  passed after fixes; reviewers independently reproduced slow-flight exclusivity and outage cleanup.
- Single Alembic head **c7f242e9a842**, parent **b6f242d8e731**; applied to local development DB.
- Actual Electron session created disposable project **01a074e0-3bb4-7317-ba53-7b653bb1f6a8**.
  One explicit I1 listing refresh loaded the connected account. Imported **ST3215 Servo v2:1**
  and **ST3215 Servo v2:2** into distinct roots under source **01a074e2-6f49-7ed5-b5cc-af5627f5114c**.
  The project has 28 real entities and 25 links, including `.solus` containment.
- Three Add/account close/reopen cycles issued **zero API requests**. Cached document reselection
  and warmed wheel navigation also issued **zero requests**. Actual hierarchy was document →
  assembly → subassembly → eight parts; selected leaf **ZK_122:1\_\_Body1** and its complete real-ID
  ancestor path persisted into Live Bench.
- At 900×670, browser QA found a selected root clipped by 14 px above and 74 px to the right.
  The generic reveal fix brings the full 224×164 card inside the viewport and preserves zero-call
  reselection. Evidence: `/tmp/solus-w242-p3-e2e-report.md`, `-report.json`, and `-reveal-fixed.png`.

The final real change gate passed after the user edited ST3215 Servo v2:1. Its microversion
changed from `03c29c0389139e762780713e` to `d4e8d342e381f9cfb5d00ded`; document 2 stayed at the same
version. The normal source-scoped WEBHOOK probe/executor was invoked as a controlled delivery:
first probe true, exactly **one connector ingestion and one actual STEP export**, five new
Countersunk Bolt entities, and all 22 previous connector entity IDs retained. A second fresh
hint returned false with no further ingestion/export. The live Electron session automatically
made one entity/relation refresh through project SSE. Evidence: `/tmp/solus-w242-p3-live-change.json`,
`-live-change.log`, `-live-change-ui.json` and `-live-change-ui.png`.

This verified the real provider detector/executor and live graph delivery, not vendor webhook
registration: connecting OAuth does not configure a webhook, and no general provider sweep was
started for this controlled test. Optional part-number metadata returned the existing API warning;
no metadata was fabricated, and geometry/containment ingestion succeeded.

## Phase 4 — Physical Robot instances

- Add → Hardware creates independent manual roots with the project name and seven real,
  separately identified category children. Inline names use optimistic entity versions.
  Root hardware-config and transport references are null placeholders. The same transaction-
  scoped creation service is the explicit future R2 hook; every call creates an instance.
- Existing planned entity mutation paths now support only manual, source-null robot roots.
  Central project membership/write roles, strict input schemas and a project row lock protect
  create/rename/delete. Connector, fingerprint, `.solus` and other manual kinds remain protected.
- Confirmed deletion soft-deletes owned containers and containment, preserves actual parts and
  unrelated edges, and exposes durable orphan history through a paginated graph query. Parts
  still owned by another live robot remain assigned. The prompt lists at most 24 parts and
  reveals real graph nodes, including parts that retain CAD containment; it survives reload.
- Project detail's graph modification timestamp catches renames with unchanged counts/source
  timestamps. Manual events publish after commit with null source/sync IDs. Focus reconciliation
  waits for the refreshed graph, clears removed category selections without 404s, and rebuilds
  surviving part ancestry through the existing navigator index.
- Account/project generation guards prevent stale writes and publications. A live test caught
  an incorrect dependency on the legacy onboarding `linked` flag; authenticated users now work
  independently of that flag. Sign-out, absent-project and stale-session guards remain enforced.
- Tier-1 API/architecture/wireflow/codemap/QA documents and generated OpenAPI/types are current.
  No migration, protected contract, ADR, transport/config schema or provider behavior was added.

Final verification:

- **2700 desktop tests in 259 files passed.** Canonical `pnpm typecheck`, scoped ESLint (no
  errors; two long test-group warnings), formatting and Electron production build passed.
  OpenAPI generation used the exact cached 7.13.0 CLI, avoiding the earlier npm DNS issue.
- **3723 distinct API tests passed**, one skipped. The parallel run covered 3682 tests;
  extension-publishing tests ran serially because their existing ZIP fixtures generate
  timestamp-dependent test IDs that can differ across pytest workers. All 41 publishing tests
  ran, plus a repeated final schema regression; no cases were omitted. The final 60 robot/live
  tests also passed after schema metadata correction. Remaining Python: **983 passed, 2 skipped,
  1 expected failure** (including all 232 companion tests).
- Final P4 UI coverage: **97.69% lines, 92.7% branches, 100% functions**, 102 focused tests.
  The new robot service has **100% statement/branch coverage**. The four touched backend
  production modules measure **83.43% combined coverage** (87.05% statements, 66.67% branches);
  uncovered branches are largely existing graph read/stream infrastructure. Coverage reports:
  `/tmp/solus-w242-p4-ui-coverage/` and `/tmp/solus-w242-p4-backend-coverage-html/`.
- Fresh code, dedicated security, TypeScript, Python and database reviews passed with findings
  fixed and retested. The review-driven fixes were stale category focus and misleading nullable
  name-default schema metadata. Database review compiled the ownership SQL and checked existing
  indexes; very large retained graph histories were not benchmarked.
- Single Alembic head **c7f242e9a842**, also verified on the running development database.
- Actual Electron created Leader `01a07517-29d4-749a-ab15-4ebba32ab489` and Follower
  `01a07517-2c10-77f7-b2ce-db346dcc8381`, with fourteen distinct category IDs. A scoped manual QA
  fixture supplied three actual parts, a secondary CAD parent and unrelated/shared edges.
  Cancel sent no DELETE. Confirm retained all three part IDs/properties/versions, removed only
  Leader and its seven categories/ownership edges, and preserved Follower and all unrelated links.
  Two unassigned parts remained visible after reload; the shared battery remained assigned.
- Both retained parts revealed fully visible cards and correct real focus; secondary CAD ancestry
  and Live Bench scope survived three repeated reload/reveal journeys. A separate DeleteProbe
  selected-category deletion cleared focus to idle/null with zero 404s. The retained-part journey
  passed again on the final focus code. No provider listing, sync or export was invoked in P4.
  Evidence: `/tmp/solus-w242-p4-live-report.md`, `.json`, `-retention.json`,
  `-selected-category-report.json` and the named screenshots. QA fixtures are explicitly manual,
  not represented as provider data.

The local API and renderer remain running with the disposable QA project available for review.
The test artifact root is `/tmp/solus-w242-artifacts`; use a durable configured artifact directory
for ongoing storage as described in the Cowork QA setup. No environment file, remote branch,
MR or main was changed. R1 part onboarding, R2 discovery and R3/R5 reference schemas remain later
feature work, as specified; the requested robot type and manual creation are complete.
