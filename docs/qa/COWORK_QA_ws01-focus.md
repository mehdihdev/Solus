# COWORK QA — WS-01 Shared-Focus Engine + Widget Contract (SOLUSDEV-191)

> **Read this first.** WS-01 ships the _engine_, not a screen. The widget **canvas** is WS-03 and
> is explicitly not in this wave, so the two widgets built here are mounted only in tests — there
> is no new UI to click in the running app. Live Bench and the Context Model screen look exactly
> as they did.
>
> What IS user-testable is the new **API route**, and it can be exercised against a real project
> end-to-end (Flow 2). The rest is developer-level verification. If you expected a click-through,
> the correct outcome is "N/A until WS-03", not "fail".

## Setup

- [ ] `make db-up`, then `pnpm dev:api`. `pnpm dev:desktop` only for Flow 5.
- [ ] Signed in and onboarded, with **a project that has a synced source** — the graph must have
      entities and relations or every flow below returns an empty neighbourhood. Connect GitHub and
      run a sync (see `COWORK_QA_connector-framework-github.md`).
- [ ] A dev JWT for curl (see `docs/api/API-implementation.md` §1 "Minting a dev JWT").
- [ ] If `uv` warns `VIRTUAL_ENV=... does not match`, prefix commands with `unset VIRTUAL_ENV &&`.
- [ ] **Do not run two pytest suites at once in the same checkout** — they share a database and
      will produce spurious failures. (`packages/api/tests/conftest.py` explains why.)

Export for convenience: `P=<project_id>`, `T=<jwt>`, `A=http://127.0.0.1:8000/api/v1`.

---

## Flow 1 — The traversal is correct and bounded

1. `cd packages/api && uv run pytest tests/test_neighborhood.py -q`
   - [ ] **Expected:** 25 passed. These cover depth bounds, undirected traversal, cycles, soft
         deletes, filters, truncation, the induced subgraph, and cross-project isolation.
2. `uv run pytest tests/test_entities.py -q`
   - [ ] **Expected:** 14 passed (route + auth + tenant isolation, including the confused-deputy case).

## Flow 2 — The focus-scope read, against a real project

3. Pick a real entity id: `curl -s "$A/projects/$P/entities?limit=5" -H "Authorization: Bearer $T" | jq '.data[] | {id, name, type}'`
   - [ ] **Expected:** real entities from your synced source. Note one id as `E`.
4. `curl -s "$A/projects/$P/graph?root=$E&depth=1" -H "Authorization: Bearer $T" | jq '{entities: (.data.entities|length), edges: (.data.edges|length), truncated: .data.truncated}'`
   - [ ] **Expected:** `entities` ≥ 1 (the focused entity is always present, even with no
         neighbours), `truncated: false`.
5. **The focused entity is always in its own neighbourhood:**
   `curl -s "$A/projects/$P/graph?root=$E&depth=0" -H "Authorization: Bearer $T" | jq '.data.entities|length, .data.edges|length'`
   - [ ] **Expected:** `1` and `0`.
6. **No edge dangles** — every edge endpoint must be a returned entity:
   ```
   curl -s "$A/projects/$P/graph?root=$E&depth=2" -H "Authorization: Bearer $T" | jq '
     .data as $d | ($d.entities|map(.id)) as $ids |
     ($d.edges|map(select((.from_entity_id|IN($ids[])|not) or (.to_entity_id|IN($ids[])|not)))|length)'
   ```
   - [ ] **Expected:** `0`. Any other number is a bug — a widget would render a broken reference.
7. **Depth widens the neighbourhood, and is capped:** compare `depth=1` vs `depth=2` entity counts
   (depth 2 ≥ depth 1), then `curl -s -o /dev/null -w '%{http_code}\n' "$A/projects/$P/graph?root=$E&depth=3" -H "Authorization: Bearer $T"`
   - [ ] **Expected:** `422`. Depth is bounded by the route, not by convention.
8. **Truncation is reported, never silent:**
   `curl -s "$A/projects/$P/graph?root=$E&depth=2&limit=1" -H "Authorization: Bearer $T" | jq '.data.truncated, (.data.entities|length)'`
   - [ ] **Expected:** `true` and `1`.
9. **Filters narrow the view:** `...&relation_types=does_not_exist`
   - [ ] **Expected:** only the focused entity, `edges: []`.

## Flow 3 — Authorization and tenant isolation (security)

10. No token: `curl -s -o /dev/null -w '%{http_code}\n' "$A/projects/$P/graph?root=$E"`
    - [ ] **Expected:** `401`.
11. Unknown root: `curl ... "?root=00000000-0000-0000-0000-000000000000"`
    - [ ] **Expected:** `404`.
12. **A second user who is not a member** of the project (sign up a second account, get its JWT):
    `curl -s -o /dev/null -w '%{http_code}\n' "$A/projects/$P/graph?root=$E" -H "Authorization: Bearer $T2"`
    - [ ] **Expected:** `404`, **not** `403`. A 403 would confirm the project exists — an existence
          oracle for another team's data.
13. **An entity id from project A used against project B** (create a second project, `P2`):
    `curl -s -o /dev/null -w '%{http_code}\n' "$A/projects/$P2/graph?root=$E" -H "Authorization: Bearer $T"`
    - [ ] **Expected:** `404`. The neighbourhood must never cross a project boundary.

## Flow 4 — The focus engine and the widget contract

14. `npx vitest related --run apps/desktop/src/renderer/src/features/workspace/focusStore.ts`
    - [ ] **Expected:** 19 passed.
15. `npx vitest related --run apps/desktop/src/renderer/src/features/workspace/widgets/WidgetHost.tsx`
    - [ ] **Expected:** 9 passed. This is the acceptance criterion in executable form: two widgets,
          one shared focus, selecting in one re-scopes the other.
16. **"Focus changes are cheap" — the tests that prove it.** Confirm these named tests pass:
    - [ ] `costs ONE request per selection no matter how many widgets are mounted`
    - [ ] `does not refetch when returning to an entity already visited`
    - [ ] `serves a cached focus without passing through a loading state` (no spinner, no remount)
17. **Prove the widget contract is the only thing a widget needs.** Confirm neither reference widget
    imports the store:
    `grep -L "focusStore" apps/desktop/src/renderer/src/features/workspace/widgets/*Widget.tsx`
    - [ ] **Expected:** both widget files listed (i.e. neither contains `focusStore`). Only
          `WidgetHost.tsx` touches it.

## Flow 5 — Nothing else broke

18. `cd packages/api && uv run pytest -q` (~5 min, run it alone)
    - [ ] **Expected:** 1327 passed, 3 skipped. (Prior to this deliverable: 1292 passed, 3 skipped.)
19. `npx vitest run` from the repo root
    - [ ] **Expected:** 716 passed across 101 files, 0 failed.
20. `make lint` and `make typecheck`
    - [ ] **Expected:** ruff clean, mypy clean, tsc clean, eslint **0 errors** (22 pre-existing
          `max-lines-per-function` warnings in unrelated files are expected).
21. `pnpm dev:desktop` — open the app, click through Context Model / Live Bench / SOL / Settings.
    - [ ] **Expected:** completely unchanged. WS-01 adds no UI. This step is a regression check.

## Edge cases / failure paths

- [ ] **Focus with no project selected** is a no-op — an entity id is meaningless without a project
      scope, and guessing one would be a cross-tenant read.
- [ ] **A failed fetch is not cached** — a transient network failure must not become a permanently
      empty neighbourhood. Re-focusing retries.
- [ ] **Switching projects drops the cache**, not just the focus. Otherwise the next project could
      render the previous one's entities.
- [ ] **`setDepth(5)` throws** client-side rather than making a request the server would 422.
- [ ] **Truncation is surfaced in the UI**, not just in the payload (`truncated-notice`).
- [ ] **An entity with no relations** still focuses successfully, showing itself alone.

## Cross-feature interactions to verify

- [ ] **`/entities` and `/relations` still behave** — same serialization keys, unchanged
      pagination (`tests/test_entities.py` covers both old and new).
- [ ] **SOL is unaffected** — `main.py` still binds `FakeSolSystems`; this deliverable deliberately
      does **not** swap it (that needs the other three `SolSystems` methods, i.e. SYS-01..05).
      `uv run pytest tests/test_sol_interface.py tests/test_sol_runtime.py -q` passes.
- [ ] **LB-06 untouched** — `uv run pytest tests/test_codec.py tests/test_telemetry_corpus.py -q` passes.

## Known gaps (do not raise as bugs)

- No widget canvas, no layout, no drag/resize — **WS-03**.
- No focus bar or traversal breadcrumb, no back/forward — **WS-02**.
- No saved layouts and no `arrange_workspace` SOL tool; `requestSolAction` is routed to the host
  and is a deliberate no-op when unhandled — **WS-04**.
- The real `SolSystems.get_graph_context` is not wired; `to_graph_context` proves the adapter but
  `main.py` still serves the fake — **SYS-01..05**.
- `docs/wireflows/` is empty, so this contract fixes the data seam only and takes no position on
  layout or visual design (flagged per CLAUDE.md §136).
