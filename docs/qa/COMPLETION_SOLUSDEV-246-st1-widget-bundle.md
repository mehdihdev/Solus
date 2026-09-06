# Completion Report — SOLUSDEV-246 · STORE ST1: the widget bundle

**Branch:** `SOLUSDEV-242-home-cross-project-surface` (founder decision 2026-09-05: the unmerged
Home work there is needed; commits are prefixed `SOLUSDEV-246:`). **Status:** integrated, verified,
ready for human review. Nothing pushed; no MR opened.

## What was built

A first-party **widget bundle**: one `extension.toml` (schema_version 2) declaring all five parts —
a page (UI tab), backend routes, a graph node type, SOL tools, and the repo `.solus/project.toml`
`[ext.<id>]` section — plus the loader behaviour that installs it, gates it, and removes it without
a trace. Design decisions were locked in-chat on 2026-09-05 (Phase 1) and the plan approved before
code (Phase 2).

| Part                 | Where                                                                                                                                                                                                                             |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Manifest v2 (tier-2) | `packages/contracts/python/solus_contracts/extension_manifest.py`, `packages/shared-types/src/extension-manifest{,-first-party}.ts`, 6 new shared fixtures, `docs/contracts/extension-manifest.md`, `docs/extensions/manifest.md` |
| Capability framework | `packages/api/src/solus_api/widgets/` — `capability`, `registry` (pkgutil discovery, loud on duplicates), `publish_gate`, `guard` (install/enable/block/routes + member floor + shared write budget), `solus_config`, `uninstall` |
| Routes               | `routers/widgets.py` mounts each capability at `/api/v1/projects/{project_id}/widgets/<id>/…`; plan `docs/api/widget-bundles.md`, index `docs/api/API.md` §2.18                                                                   |
| SOL tools            | `deps.get_sol_registry` → `load_bundle_capabilities` → `build_sol_registry(bundle_capabilities=…)`; `InProcessTool`s named `<id>.<name>` through the untouched W0-04 registry                                                     |
| Publish gate         | `routers/extensions/publish.py`: first-party tables need staff + a matching in-repo package; capability ids reserved; staff may seed (and must remain staff to use) a reserved publisher name                                     |
| Uninstall            | `routers/extensions/installs.py` DELETE: install + storage rows, soft-delete of the bundle's kinds and edges, `ext:<slug>` layout slots pruned for every user; payload widened                                                    |
| `.solus` section     | GitHub and GitLab connectors read `.solus/project.toml` (bounded) → one `solus_config` entity; `effective_bundle_config` layers manifest ← repo ← install settings                                                                |
| Fixture bundle       | `packages/shared-types/fixtures/extension-bundles/fixture-bundle/` (zip source) + `solus_api/widgets/fixture_bundle/` (kind `note`, tools `add_note` / gated `clear_notes`, `GET`/`POST /notes`)                                  |
| Desktop              | Manifest fixtures gain the defaulted v2 tables; Store uninstall copy; loader test for the fixture folder. No new UI: "tab" = the existing `views.page` rail entry                                                                 |
| Governance           | ADR-035 §4 amendment and ADR-027 `origin="extension"` (approved in-chat, dedicated commit `01fe794`)                                                                                                                              |

## Governing docs consulted

DECISIONS.md (ADR-027/031/034/035, ADR-032 two-tier), `docs/architecture/extensions-runtime.md`,
`docs/architecture/solus-folder.md`, `docs/api/extensions.md` + `API.md`, `docs/schemas/extensions.md`,
`docs/wireflows/store.md` + `widget-canvas.md`, contracts `extension-manifest`, `widget` (CTR-01),
`agent-tool` (W0-04), `action-gate`, MCP-03's completion report and `integrations/mcp/README.md`.
`docs/design/SPEC.md` and `docs/design/screens/` named by the standing rules do not exist in this
repo; the documents above were used instead.

## Verification

- **Contract:** Python 48 + TS 53 manifest tests; `_fields.json` regenerated; v1 fixtures unchanged.
- **API:** new suites `test_widget_bundles.py` (23), `test_widget_bundle_routes.py` (14),
  `test_fixture_bundle_folder.py` (2), `test_solus_config_parse.py` (5); additions to the GitHub,
  GitLab, publish, installs and red-team suites. Isolation tests: team B → 404 on routes, tools bound
  to their project, sweep never crosses projects. Full API suite: see the final line of this section.
- **Desktop:** 2608 tests, typecheck clean. Pre-existing lint errors remain in files this ticket
  did not touch (`useExtensions.ts:126`, `GraphScreen.tsx`, `useGraphSummary.ts`, `useGuide.ts`,
  onboarding, overlay, project) — on the branch before this work.
- **Ruff/mypy:** clean over `packages/api` and `packages/contracts` (two pre-existing
  `ruff format` drifts in `test_bench_router.py` / `test_embeddings.py` untouched).
- **Reviews:** fresh-context code review (1 HIGH → fixed: GitLab read now streams under the cap)
  and security review (2 HIGH, 4 MEDIUM, 8 LOW → H1, H2, M1–M4, L1–L4, L6 fixed in `2cf788b`;
  L5, L7, L8 accepted, see below).
- **Real run (2026-09-06, live API + ARQ worker + Postgres/Redis, live Anthropic turns):**
  community publish → `422 backend: first-party only`; staff publish → `202`, review `approved` by
  the worker; install `201`; `GET /sol/tools` lists `fixture-bundle.add_note` and the gated
  `fixture-bundle.clear_notes`; a **real SOL turn called `fixture-bundle.add_note`** and the note
  appeared on `GET …/widgets/fixture-bundle/notes`; the Guide-mode clear was refused by the
  existing SOLX-01 rule; the Do-mode clear **parked a confirmation** with the Solus-authored summary
  and a `1 → 0` preview; approval ran it (`cleared: 1`), replay refused (single use); `POST /notes`
  `201` as owner, `404` from another team; community squat of the id → `422 reserved`; uninstall
  `204` → route `404`, tools gone, the teammate-free layout pruned, and the database showed every
  note soft-deleted with zero install/storage rows.
- **Not exercised live:** the desktop Store/page UI against this API (unit-tested: the loader
  accepts the fixture folder; the page bundle is static and follows the documented bridge
  handshake), and a real GitHub/GitLab sync of a repo carrying `.solus/project.toml` (respx-tested
  on both connectors). Both are in the Cowork QA file.

## Decisions made under delegated judgment

- `schema_version = 2` reports as `ok` on the desktop (tables parsed, ignored by the renderer); `3`
  is `newer`. v1 treats the tables as unknown fields.
- Capability tools are named `<id>.<name>` (dotted, like `solus.*`); the existing model-boundary
  translation handles them. `_register_bundle_tools` enforces the name as an invariant.
- The first-party gate returns `422 bundle_invalid` details (not a new error code) so the Store's
  existing error mapping applies; capability-id squatting is likewise a `422` detail.
- **Behaviour change:** a publisher row carrying a reserved vendor name publishes only while its
  account is on `SOLUS_STAFF_USER_IDS` (security review M3). The previous test asserting
  "pre-existing reserved-name rows keep publishing" was rewritten to the new rule.
- Uninstall soft-deletes the bundle's kinds (ADR-027, reversible) rather than hard-deleting.
- `read_bundle_config` only trusts `origin="connector"` rows; the `[ext]` values reach model context
  through the existing `redact_value` + data fence, with a new red-team payload (`inj-solus-01`).
- The GitLab raw-file read is bounded while streaming (no size in GitLab's tree); GitHub refuses
  when the tree omits a size (fail closed).

## Deviations and open items

- **Branch:** work lives on the SOLUSDEV-242 branch by founder instruction, not a SOLUSDEV-246 branch.
- **Env you must set (never edited by me):** `SOLUS_STAFF_USER_IDS=<uuid,…>` for whoever publishes
  first-party bundles; `SOLUS_ARTIFACT_LOCAL_ROOT` shared by the API and the ARQ worker in local dev
  (otherwise the review job cannot read the bundle the API stored). Redis + the ARQ worker must run
  for a publish to be approved.
- **Accepted LOWs:** L5 (one `widget_bundle.route_refused` event per refused request — consent-gated
  and rate-limited; sample later if noisy), L7 (`add_note` text stored verbatim within the 200-char
  schema bound; redacted and fenced on read), L8 (`bridge.js` posts to `"*"` — copied from the
  published getting-started snippet; the frame origin is opaque by design, so a doc-level fix is a
  follow-up for the extensions docs).
- **Pre-existing debt noticed, not touched:** desktop lint errors listed above; two Python files
  with `ruff format` drift.
- **Follow-ups suggested:** (1) a `.solus/project.toml` editor or validator in the desktop (Ticket B
  proper); (2) a `users.is_staff` column replacing the env list if first-party publishing becomes
  routine; (3) `Retry-After` on the install routes is already present — the guard now shares the
  same limiter, so a Redis-backed limiter (artifacts.md §4.5 caveat) would cover both at once.

## Commits (`5a44254..HEAD`)

`01fe794` ADR amendments · `c9fc675` contract v2 + docs + route plan · `f1e8d9d` capability
framework, fixture backend, routes, SOL registration · `a053867` GitHub `.solus` landing ·
`5b541c0` fixture folder, GitLab, Store copy, docs · `ba4a77f` route-plan shapes · `78d4c1c` GitLab
streaming bound (review HIGH) · `2cf788b` Phase 4 security fixes · `754915c` docs for the fixes ·
plus this report and `docs/qa/COWORK_QA_store-st1-widget-bundle.md`.
