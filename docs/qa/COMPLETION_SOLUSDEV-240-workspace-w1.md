# Completion report — SOLUSDEV-240 · WORKSPACE W1

**Branch:** `SOLUSDEV-240-graph-workspace` (local commits only; humans push, open and merge the MR).
**Built:** 2026-09-05. **QA file:** `docs/qa/COWORK_QA_SOLUSDEV-240.md`.

## What was built

1. **Rename** — the Context Model screen is **Workspace** in the rail, View menu, Overview tile
   and `data-screen-label`; route id `graph` → `workspace`. The `features/graph/` directory,
   `graphCache`, the `graph.*` extension namespace and the SOL context section kind `graph` are
   untouched (contracts, not UI).
2. **Project `.solus`** — created with every project (`create_project`) as a `graph_entity`
   (`kind=solus_config`, `domain=project`, `origin=manual`, name `.solus`); pre-existing projects
   self-heal on the first `GET /projects/{id}/solus`. Five sections: Hardware configs, Project
   details, Error logging, Documentation, Code environment (`solus_entries` table).
3. **Panel** — a 290px left rail in Workspace: five section cards with honest counts/`EMPTY`, the
   `AUTO + YOU` chip on Error logging, entry rows by kind, and one right-click menu with the same
   three actions on every section: **Import files…**, **Ask SOL to find…**, **Type it**. Entries
   offer Edit/Delete (files confirm first, since a graph node goes with them).
4. **Imports are graph nodes** — the desktop uploads through the existing `POST …/artifacts`,
   then files the id: the artifact is marked `retained` (exempt from the TTL sweep and one-shot
   consumption), wrapped in a `document` node (`domain=project`) edged `.solus →references→
document`, so `load_neighborhood` (focus, Impact) reaches it. Typed text is **not** a node.
5. **Error logging is user-editable, SOL can write** — the ungated `add_solus_entry(section,
text)` builtin (author `sol`, `created_by` = requesting user) is registered per request; the
   system prompt tells SOL to file a source-naming result when asked to find something for a
   section, and to file nothing when it finds nothing. **S5 (automatic error filing) is a later
   ticket** per the in-chat decision.

## Governing docs

Read: DECISIONS.md ADR-025/027/032/034, `docs/architecture/solus-folder.md`,
`docs/contracts/local-state.md`, `docs/contracts/focus.md`, `docs/api/API.md` §2.3/§2.4/§5,
`docs/api/artifacts.md`, `docs/wireflows/project-topbar.md`, `apps/desktop/CLAUDE.md`, and the
design reference `docs/ui-reference/app/v4/workspace.jsx` (`docs/design/` does not exist).

Written/amended (tier-1, direct): `docs/api/solus.md` (new route plan), `docs/api/API.md` (§2.3
pointer row, §5 route rename), `docs/api/artifacts.md` (retained exception), new
`docs/wireflows/workspace.md`, status notes in `docs/architecture/solus-folder.md` and
`docs/contracts/local-state.md`.

Tier-2 (approved in-chat before editing, ADR-032; dedicated commit): DECISIONS.md ADR-027
amendment (`project` domain) and ADR-034 amendment (server-stored project layer);
`packages/contracts/python/solus_contracts/connector.py` `Domain.PROJECT`; `@solus/shared-types`
`DOMAINS` (focus.ts, widget.ts); `docs/contracts/focus.md`.

## Decisions taken at the Phase 1 gate (human answers)

| Question                  | Answer                                                                                                                                                          |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Storage home for `.solus` | Server-stored, DB-backed (ADR-034 amended). Repo TOML Tickets B–E remain the later connector feeder.                                                            |
| Graph domain              | Add `project` (ADR-027 amended).                                                                                                                                |
| S5                        | Separate later ticket; this ticket ships the tool so SOL _can_ write.                                                                                           |
| Ask SOL to find           | Desktop sends a chat turn `Find for .solus › <label>: <query>`; SOL files via `add_solus_entry`; the panel refetches and says so honestly if nothing was filed. |

## Delegated-judgement decisions

- `origin="manual"` (the existing user-editable value) rather than a new `declared` value.
- `.solus` panel is a **left** rail (the inspector already owns the right one).
- Typed text is not a graph node; only imported files are.
- The first write builtin is **not confirmation-gated**: an append-only, bounded, team-editable
  project note is none of CLAUDE.md §7's destructive classes. Stated in the module docstring.
- The entity list re-walks after a document node is added/removed (`useGraphSummary(revision)`);
  otherwise the cached list predates the import.
- Empty-state honesty: a fresh project now has one entity; the canvas says "An empty project — on
  purpose" instead of pretending the graph is populated, while the list still shows `.solus`.
- `tests/test_entities.py` count updated 3 → 4 (the project's own node) — intended behaviour.

## Tests (TDD; written first)

- Backend: `tests/test_solus_config.py` (creation, GET + self-heal, text entry, artifact filing →
  node + edge + retained + reachable via `GET /graph`, foreign/unknown artifact 404, validation
  422/404, edit/delete cascade, 401, cross-team 404, viewer 403, sweep skips retained),
  `tests/test_solus_entry.py` (descriptor ungated + scope-free, real write as `sol`, bad input →
  `ok=False`, never raises). Contract parity `tests/test_contracts_package.py` passes with the new
  domain.
- Desktop: `ContextMenu.test.tsx`, `useSolusConfig.test.ts`, `SolusPanel.test.tsx` (five EMPTY
  sections, kinds, identical menu, Type it, Import + size cap, Ask SOL both branches, streaming
  guard, edit/delete, confirm-on-file, offline), `WorkspaceScreen.test.tsx` (panel mounted,
  only-`.solus` empty copy), rename assertions in AppRoutes/WorkspaceShell/ProjectOverview tests.
- Full desktop suite: **252 files / 2759 tests pass**.
- API suite (run in slices — the whole suite exceeds the 600 s tool ceiling; memory
  `solus-h10-gate-timeout`): every slice passed except assertions that counted graph entities
  (`test_entities.py`, `test_projects.py`), updated for the project's own `.solus` node. Batch
  runs also produced teardown deadlocks between the conftest `TRUNCATE` and a connection holding
  `activities`/`teams`/`projects`/`sources` — none of this ticket's tables; every affected file
  passes in isolation (`test_projects/test_reason/test_reconciliation/test_retrieval/test_runtime`:
  71 passed; `test_extension_team_policy` 45 passed; `test_kicad_ingest_e2e` + `toolkb/test_kicad`
  19 passed; `test_sources` 13 passed; files t–z 267 passed; files a–o ~1000 passed in one
  slice), so this is a pre-existing timing interaction after a first failure, not a regression.
  Flagged for a human; not touched. Postgres log names the partner statement: an
  `INSERT INTO activities` (record_activity) still running when the next teardown's TRUNCATE fires.
- Lint: root `eslint.config.mjs` clean on every touched file; `ruff` + `mypy` clean.

## Verification — the product was run for real

API on `127.0.0.1:8000` against the dev DB (migrated to `b7e2d4a9c1f0`), renderer at
`:5173`, driven through Playwright with the dev user's minted session:

1. Created project **W1 Acceptance Rover** → `.solus` node present in DB (`solus_config ·
project · manual`).
2. Rail reads **Workspace**; panel shows five `EMPTY` sections; entity list shows `.solus`.
3. Right-click Project details → **Import files…** → `FSAE Rules 2027.pdf`: `POST /artifacts`
   201 → `POST /solus/details/entries` 201; DB shows `retained=t`, a `document · project`
   node, a `references` edge; toast "Imported …"; the document appears in the entity list;
   focusing `.solus` shows "2 connections" with the PDF in Neighbors.
4. **Type it** → spec text persisted (`kind=text`, `author=user`).
5. **Full reload** → both entries and the document node still present.
6. **Delete** on a duplicate import → confirm modal → entry, node and artifact soft-deleted; list
   refreshed.
7. **Ask SOL to find** (real Anthropic turn, ~14 s) over the PDF: SOL used
   `solus.list_integrations` and `retrieve_errors`, found nothing it could reach, filed nothing;
   panel toast "SOL answered but filed nothing". No tool-naming 400s.
8. **Ask SOL to find** for the connectable integrations: SOL called `add_solus_entry → ok`; the row
   appeared under Code environment as `filed by SOL`; toast "Filed to .solus › Code environment".

## Open concerns / deviations

- **SOL cannot read imported file bytes.** `ArtifactRef` byte-fetch is deliberately inert
  (W0-04 posture), so "Ask SOL to find … in the imported PDF" honestly files nothing. Giving SOL
  a scoped, size-capped reader for retained `.solus` documents is a follow-up ticket.
- **S5** (SOL auto-files errors it diagnoses into Error logging) is deferred per the gate answer.
- Impact's BFS walks every edge, so a `document` node can surface as an impact node when a
  document is the focus — accepted (honest edge, low blast radius).
- The rate limiter and TTL sweep are unchanged; retained artifacts simply never expire until
  their entry is deleted. Storage growth is bounded only by the per-team upload byte budget.
- `packages/api/.env` carries a stale `SOLUS_SUPABASE_JWT_SECRET`; the API reads the **root**
  `.env`. Not touched (standing rule), flagged for a human.
- `docs/ui-reference/` (the design export) and `.playwright-mcp/` are untracked and left alone.
- H9's `vitest run --silent <file>` harness gap fired on every desktop edit (known; verified with
  `npx vitest related --run`).

## Environment values you must set

None new. `ANTHROPIC_API_KEY` (already in the root `.env`) is needed for the Ask SOL flows.
