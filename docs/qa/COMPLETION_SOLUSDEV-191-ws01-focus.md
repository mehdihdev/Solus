# Completion Report — SOLUSDEV-191 / SOLUS-WS-01: Shared-focus engine + widget contract

**Branch:** `SOLUSDEV-191/ws01-focus`, branched from and merged into
`SOLUSDEV-63-linking+livebench`. Commits `7a3bf60` (implementation), `7272109` (code review),
`c3e5aa8` (security review).
**Status:** implemented, tests green, type-checked, reviewed twice, integrated on the feature
branch. Not pushed; no MR opened.

---

## The cycle, and how it was broken

WS-01 listed WS-03 as a dependency; WS-03 listed WS-01. The deadlock was never real — what each
side needed from the other was **the contract between them**, not the other's implementation.
`widget.contract.ts` is that seam: WS-01 builds against it, WS-03 will build against it, neither
against the other. Same resolution shape as BRG-01/BRG-02.

**Proposed for Jira: a new `SOLUS-WS-00: Widget framework contract`** under epic SOLUSDEV-63, with
WS-01's deps → (W0-01, W0-07, WS-00) and WS-03's → (WS-00) only. Not written — awaiting approval.

## What was built

|                                                |                                                                    |
| ---------------------------------------------- | ------------------------------------------------------------------ |
| `graph/neighborhood.py`                        | **new** — the one canonical bounded traversal + `to_graph_context` |
| `routers/entities.py`                          | `GET /projects/{id}/graph` (`get_subgraph`)                        |
| `docs/api/API.md`                              | **restored** (see below)                                           |
| `widget.contract.ts`                           | **new** — the seam; `WIDGET_CONTRACT_VERSION = 1`                  |
| `focusStore.ts`                                | **new** — one focused entity, broadcast to every widget            |
| `widgets/WidgetHost.tsx` + 2 reference widgets | **new** — the only place a widget meets the store                  |
| `lib/api/resources.ts`                         | `getGraphNeighborhood` + `Relation`/`Neighborhood` types           |
| `docs/contracts/widget-contract.md`            | **new** — normative contract (tier-1, ADR-032)                     |

**+58 tests** (25 traversal, 14 route, 19 store, 9 widget, 2 client).

## One traversal, not two

The ticket's risk was building a focus-scope query that later disagrees with SOL's view of the
graph. So `load_neighborhood` returns **ORM rows**, and its two consumers adapt:

- the route serializes with the existing `serialize_entity`/`serialize_relation`, so the frontend
  has **one** entity type rather than a widget-specific copy;
- `to_graph_context` produces W0-07's `GraphContext{entities, edges, truncated}` — **zero new
  contract types** — so a real `SolSystems.get_graph_context` is a thin adapter, not a second
  traversal.

Iterated frontier, not a recursive CTE: ADR-027 defers deep traversal, and `src_id`/`dst_id` are
each already indexed. Undirected, because focus asks what an entity relates to, not which way an
edge points. The result is the **induced** subgraph — one closing query guarantees no edge dangles
_and_ picks up edges between neighbours, without which two parts wired to each other render as
unrelated.

## The route was already blessed

`GET /projects/{project_id}/graph?root=&depth=&entity_types=&relation_types=` was planned in
`docs/api/API.md` §2.4 at SOLUSDEV-2 and never implemented. Built as planned rather than invented.

**And `docs/api/API.md` — authority level 3 — had been deleted from the tree.** Commit `d4fa914`
("Solusdev 72 shared dev models") removed it, apparently accidentally: nothing referenced the
removal and ~40 source comments still cite it. It was absent from `main` and every branch since.
Restored verbatim from `d4fa914^` (462 lines) with `GET /graph` marked implemented and a
restoration note distinguishing plan-of-record from what exists. **Worth a human glance** — it may
have been deleted deliberately for a reason not recorded anywhere.

## "Focus changes are cheap", proven rather than asserted

One fetch per selection, shared by every widget; a per-(project, entity, depth) cache; and a cached
focus deliberately never passes through `loading` — no spinner, no remount, just new props. Three
named tests assert exactly this, by counting calls:

- `costs ONE request per selection no matter how many widgets are mounted`
- `does not refetch when returning to an entity already visited`
- `serves a cached focus without passing through a loading state`

Plus the acceptance criterion itself: `re-scopes BOTH widgets when the focus changes in ONE of
them`. Zustand's own `subscribe` is the broadcast — no event bus, because a second notification
channel is a second thing that can desynchronise.

## Deviations from the plan (called out, per §6)

1. **The widget contract's types are hand-written, not generated.** The plan said to type them from
   the generated `lib/api/schema.ts`. That does not work: the repo's routes return
   `dict[str, Any]`, so `openapi-typescript` emits nothing usable. The contract instead reuses
   `Entity`/`Relation` from `resources.ts` — which is the _actual_ house convention (that file
   hand-writes every type and says so). Same single-definition goal, real mechanism.
2. **`FakeSolSystems` is NOT swapped** at `main.py:91`, as planned. It needs the other three
   `SolSystems` methods real (SYS-01..05) and would degrade SOL chat today. `to_graph_context` +
   its test prove the adapter; wiring is the follow-up.

## Verification

- `uv run pytest -q` → **1327 passed, 3 skipped** (before this deliverable: 1292/3 → **+35**).
- `npx vitest run` → **716 passed, 101 files**.
- `ruff` clean · `mypy packages/api/src packages/api/tests` clean, **232 files** · `tsc` clean ·
  `eslint` **0 errors** (22 pre-existing warnings in unrelated files).

## Review findings and resolutions

### Security review — verdict **FAIL**: 3 CRITICAL, 3 HIGH, 5 MEDIUM, 2 LOW. All actioned.

Every finding was measured against a real Postgres, not reasoned about.

**The three CRITICALs were one root cause: the traversal capped its OUTPUT but never its WORK.**

| #      | Finding                                                                                                                                                                                                                                                                                                                                                                       | Resolution                                                                                                                                                 |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1     | `select(GraphEntity)` hydrated the **1536-float `embedding`** for every candidate, with `max_entities` applied in Python _after_: **1.3 GiB RSS / 3.0s for 20k rows** (46 MiB / 0.3s deferred). Neither consumer wants that column. Reachable by a customer clicking the `:repo` node of a 20k-file monorepo — at 120 req/min per token, a cross-tenant availability failure. | `defer(embedding, raiseload=True)` + `LIMIT` in SQL. `raiseload` makes a future accidental access loud rather than expensive.                              |
| C2     | The `IN (...)` id list was unbounded → a node with ≥32,767 edges blew asyncpg's bind-parameter cap → `InterfaceError` → **500, recurring forever for that node**.                                                                                                                                                                                                             | Discovery is edge-capped and ordered; the candidate list is sliced far below the limit.                                                                    |
| C3     | Edges were never capped. A 500-clique returned **124,750 edges (43 MB)** while reporting **`truncated: false`** — the exact lie the flag exists to prevent, and what the widget's "showing part of this" notice reads.                                                                                                                                                        | `EDGES_PER_ENTITY` cap; the cap sets `truncated`.                                                                                                          |
| H1     | **`clearProject` was documented, tested, and called by nothing.** The cache survived project switch _and_ sign-out, so on a shared workstation the next user could read the previous tenant's entity names/kinds/properties from renderer memory — no request, no authorization check.                                                                                        | Wired into `openProject`, `switchProject`, `onSignOut`; cache now **project-keyed** so a missed reset degrades to a cache miss, not a cross-tenant render. |
| H2     | `SolActionRequest.kind` was a free string the host forwarded verbatim, while both the contract and the host comment claimed "Solus code decides".                                                                                                                                                                                                                             | Closed union `SOL_ACTION_KINDS`, enforced **at runtime** in `WidgetHost` — the TS type is erased, and WS-04 makes these requests model-influenced (§7).    |
| H3     | No route test for the realistic confused-deputy case (member of _both_ projects, root from the other). Code was correct; §7 fails a missing isolation test anyway.                                                                                                                                                                                                            | Added, asserting a 404 **byte-identical** to an unknown id.                                                                                                |
| M1     | `setDepth` changed the cache key without refetching → widgets rendered "0 entities" with `status: ready`. An empty graph shown as the whole truth.                                                                                                                                                                                                                            | `setDepth` refetches.                                                                                                                                      |
| M2     | No in-flight dedup — dragging through a neighbour list fired one traversal per click.                                                                                                                                                                                                                                                                                         | Dedup by cache key.                                                                                                                                        |
| M5     | The `ORDER BY` sorted rows carrying the embedding.                                                                                                                                                                                                                                                                                                                            | Resolved by C1.                                                                                                                                            |
| L1, L2 | Un-encoded `projectId` interpolation (pre-existing file-wide pattern, server-issued UUID); no dedicated rate bucket for an expensive read.                                                                                                                                                                                                                                    | Noted; L2 recommended once this endpoint is mounted in the UI.                                                                                             |

**Deferred deliberately, not dropped:** **M4** — no DB constraint makes a cross-project edge
_unrepresentable_ (three independent FKs). The traversal's defence-in-depth holds and the reviewer
could not construct a leak through it, but the invariant lives in application code. The fix is a
composite-FK migration and belongs in its own ticket. **M3** — `attrs`/`properties` is unbounded at
ingest; it becomes a token-budget concern (ADR-019) when `get_graph_context` is really wired.

**Verified clean by the security review:** tenant isolation in every query (including that
`_adjacent_ids`' raw ids are only ever re-scoped, and that `truncated` is computed only from
post-scope quantities so it is not a count oracle); route auth and 404-not-403 with identical
bodies; SQL injection (three payloads fired through both CSV filters); secrets; frontend HTML
injection (React escapes; the repo's only `dangerouslySetInnerHTML` is compile-time SVG);
prompt-injection surface (`to_graph_context` is a DTO adapter, and today's only consumer emits
counts).

### Code review — verdict WARNING: 1 HIGH, 2 MEDIUM, 3 LOW. All actioned.

- **HIGH, reproduced:** a late _rejection_ for an abandoned focus clobbered a later successful one.
  The success path guarded on "is this still focused"; the catch path did not, so a slow failure
  for A painted an error over B's valid neighbourhood. Same guard + a regression test driving the
  real interleaving.
- **MEDIUM:** truncation was non-deterministic (no `ORDER BY`) — a capped view could shuffle on
  refresh. Found independently and fixed before the review landed; now pinned by a three-identical-
  runs test.
- **MEDIUM:** the documented "a filtered-out node is not a stepping stone" semantics had coverage
  only at depth 1, where it is untestable. Added the depth-2 case, plus `entity_types` end-to-end
  through the route.
- **LOW:** removed a `useMemo` in `WidgetHost` that could never skip a recompute (zustand returns a
  fresh object per `set`) — decoration, not optimisation. Named the real fix (a selector) for when
  widget count makes it matter.

Verified correct by the reviewer and needing no change: induced-subgraph completeness under
filters, `EntityRead.model_validate` on ORM rows, absence of N+1, and the route's `limit` semantics
(which differ from sibling routes' page-size `limit` — but that is what the locked API.md specifies).

## Flags for the human

1. **`docs/api/API.md` was restored from a commit that deleted it without explanation.** Please
   confirm the deletion was accidental. If it was deliberate, the restore should be reverted and
   ~40 code comments citing it need updating instead.
2. **No wireflow governs this UI.** `docs/wireflows/` and `docs/architecture/` are empty
   (`.gitkeep` only). Per CLAUDE.md §136 this is flagged rather than improvised around: the
   contract fixes the **data seam only** and takes no position on layout or visual design. When
   wireflows land they win and this doc is reconciled in the same MR.
3. **M4 (composite FK) wants its own ticket** — recorded above so it is not lost.
4. Standing from Deliverable 1 and still open: the **"monotonic timestamp" reinterpretation** in
   LB-06 awaits your ratification.

## Docs amended (tier-1, ADR-032)

`docs/api/API.md` (restored + §2.4 marked implemented) · `docs/api/API-implementation.md` (new §12)
· `docs/contracts/widget-contract.md` (new).

## Unblocked by this

**WS-03** (canvas — builds against the contract), **WS-02** (focus bar/breadcrumb — subscribes to
the store), **WS-04** (saved layouts + `arrange_workspace`), and **IMP-01**, whose bounded traversal
this is.

## Cowork QA

`docs/qa/COWORK_QA_ws01-focus.md`. Note for the tester: WS-01 adds **no UI** (the canvas is WS-03),
so the widgets are exercised in tests while the new **API route** is exercised end-to-end against a
real project with curl. The file says so up front.
