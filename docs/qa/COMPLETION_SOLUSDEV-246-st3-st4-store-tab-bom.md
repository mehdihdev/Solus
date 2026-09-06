# Completion Report — SOLUSDEV-246 · STORE ST3 (the Store tab) + ST4 (the BOM widget)

**Branch:** `SOLUSDEV-244-home-h3-root-preferences` (founder instruction 2026-09-06: keep working on
the branch the Home agent uses; three agent sessions shared this checkout and each committed only
its own paths; commits are prefixed `SOLUSDEV-246:`). **Status:** integrated, verified live in the
real desktop and API, both review passes remediated, ready for human review. Nothing pushed; no MR
opened.

## What was built

**ST3 — the Store tab.** Browse / detail / install / uninstall already existed (SOLUSDEV-235); this
ticket adds what was missing and corrects one wireflow: an installed widget's tab now sits AFTER the
Store behind a separator; right-click a tab → _Pin for all projects_ (an account-level pin, so the
tab shows in every project, honestly dimmed where the bundle is not installed); the detail page marks
first-party bundles and offers the pin; a widget is suggested in context (one toast into its Store
detail) when the source kind it requires connects.

**ST4 — the BOM widget.** A first-party bundle (`bom`) whose backend is in-repo: a VIEW over
canonical parts (a fingerprinted servo in CAD and the schematic is ONE row; identical part numbers
within one domain aggregate into a quantity), rows for raw materials and purchases with no design
counterpart, a lifecycle state per row (R5: planned → ordered → received → installed → retired),
supplier preferences / cost target / currency / row cap as configuration (bundle settings or the repo
`[ext.bom]` table), CSV export, and a SOL tool `bom.add_item`. Its page is rendered in-repo by the
desktop — the first first-party page — because the ADR-035 bridge cannot reach a bundle's own routes.

| Part               | Where                                                                                                                                                                                                                                                          |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pins API           | `models.UserExtensionPin`, migration `e1f2a3b4c5d6`, `routers/extensions/pins.py` (`/api/v1/users/me/extension-pins`, budget, events, catalog visibility rule), `docs/api/extensions.md` §6.5, `API.md` §2.19, `docs/schemas/extensions.md` §4.12              |
| BOM backend        | `solus_api/widgets/bom/` — `rows.py` (pure view builder, keys, CSV), `service.py` (loader, config, item/overlay writes, cap), `routes.py`, `tools.py`; bundle folder `packages/shared-types/fixtures/extension-bundles/bom/`; `docs/api/widget-bundles.md` §11 |
| Client event       | `routers/events.py`: `store.suggested` (typed payload)                                                                                                                                                                                                         |
| Desktop rail       | `extensionRail.ts` (installs ∪ pins, order, cap, `firstParty`), `useExtensionRail.ts` (pins hydrated + polled), `WorkspaceShell.tsx` (order, separator, context menu, pin-only route, first-party route, toast slug), `shellStore.ts`, `pinsStore.ts`          |
| Desktop Store      | `detail/PinButton.tsx`, `FIRST-PARTY` badge + "Runs in Solus" row (`ExtensionDetail.tsx`, `extensionLogic.ts`, `OverviewTab.tsx`), `pageview/PinnedNotInstalled.tsx`                                                                                           |
| Desktop suggestion | `suggestions.ts` (pure), `useSourceSuggestions.ts` (mounted on the Sources screen)                                                                                                                                                                             |
| Desktop BOM page   | `features/extensions/firstParty.ts` (registry), `features/bom/` — `BomScreen`, `BomTable`, `AddRowModal`, `useBom`, `bomLogic`; `lib/api/resources.bom.ts`, `resources.extensions.ts` (pins)                                                                   |
| Docs               | `docs/wireflows/store.md`, `extensions-runtime.md` §2 (rail order amended), new `docs/wireflows/bom.md`, `docs/architecture/extensions-runtime.md` §10 correction                                                                                              |

## Governing docs consulted

DECISIONS.md (ADR-012, ADR-027 incl. the ST1/ST2 amendments, ADR-032, ADR-034, ADR-035),
`docs/api/extensions.md` + `widget-bundles.md` + `API.md`, `docs/schemas/extensions.md`,
`docs/wireflows/store.md` + `extensions-runtime.md` + `widget-canvas.md`, `docs/architecture/extensions-runtime.md`,
contracts `extension-manifest`, `agent-tool` (W0-04), `action-gate`, and the ST1/ST2 completion
reports. `docs/design/SPEC.md` and `docs/design/screens/` named by the standing rules do not exist in
this repo; the documents above were used instead.

## Design decisions (Phase 1, locked in-chat 2026-09-06)

1. **First-party pages are in-repo React**, chosen over a `backend.call` bridge method: the sandboxed
   frame cannot reach `/widgets/<slug>/…`, and a proxy method would widen the community surface for a
   first-party need. The shell renders the in-repo page only for an INSTALLED entry whose PINNED
   manifest declares a first-party table (staff-only at publish) — never by slug alone.
2. **"Pin for all projects" = per-user server rows**; a pin installs nothing. A pin-only tab opens an
   honest "not installed in this project" state whose Install lands on the Store detail page.
3. **R5 lifecycle** (R5 is not in the repo): `planned → ordered → received → installed → retired`,
   free transitions; design rows default `installed`, hand-added rows `planned`.
4. **Fingerprint**: dedupe on the existing shapes (`canonical_part_id`, live `same_as` edges); the
   §2.8 scan/confirm routes remain unimplemented, so the live run seeded the servo and ran
   `scan_project` + `link_from_fingerprint` by script.

## Verification

- **API:** new suites `tests/test_pins.py` (14), `tests/bom/test_rows.py` (34), `tests/bom/test_routes.py`
  (16), `tests/bom/test_bundle_folder.py` (2), `test_events_ingest.py` +1. Isolation: team B → 404 on
  BOM reads and writes, a row key from project A never resolves in project B, pins are per user,
  viewer writes → 403. Red team: a corpus part-name payload reaches the view, the CSV and the tool
  result only as a string value and changes no tool spec. Full API suite (xdist, `--ignore=tests/corpus`
  because that suite's random parametrize broke worker collection — reported to and fixed by the
  CORPUS session in its next commit): **4 027 passed, 4 skipped** (12 min 02 s, 2026-09-06, on a
  private `SOLUS_TEST_DATABASE_URL`).
- **Desktop:** new suites for the pins store, the rail (pins), the shell (order, separator, context
  menu, pin-only tab, first-party vs community routing, toast slug, sign-out), suggestions (pure +
  hook), the BOM page / hook / logic / dialog, the pin button, the first-party badge. Full desktop
  suite: **2 852 passed, 1 timed out** (`features/graph/WorkspaceScreen.test.tsx`, untouched by this
  ticket, 5 s timeout while the API suite and Electron ran beside it; 15/15 when rerun alone);
  `typecheck:web` clean; eslint clean on every touched file (the branch's pre-existing
  `useExtensions.ts:126` error is untouched).
- **Reviews:** fresh-context code review — 0 CRITICAL/HIGH, 1 MEDIUM, 2 LOW; security review — 3 HIGH,
  5 MEDIUM, 5 LOW. Remediated in `cf65b85`: H1 one `COST_MAX` for route and tool + finite-safe reads;
  H2 cross-project key and non-member write tests; H3 red-team case; M1 pins follow the catalog's
  visibility rule and DELETE is always 204; M2 the first-party page is picked by the pinned manifest
  and shows the install row's publisher; M4 `max_items` cap on items and overlays (route and tool);
  M5 item writes answer from the row, not a rebuilt view; L4 Unicode control/format characters
  refused; L5 no module asserts; the code review's MEDIUM (tool bound) and LOW (effect deps).
  **Not changed:** M3 (reserve planned first-party ids before they ship — product decision, below);
  L1 (a team-blocked extension's pin still draws a tab; the Store then refuses the install honestly);
  L2 (refusal events are unbounded per member — pre-existing ST1 behaviour); L3 (CSV export is a read,
  open to share-only users like every project read).
- **Real run (2026-09-06, private API on :8001 + ARQ worker + Postgres/Redis, the REAL Electron app
  driven over CDP):** published the BOM bundle as staff (0.1.0, then 0.2.0 with `max_items`) →
  approved; two projects A and B; seeded A with a CAD servo + schematic U3 (both `MG996R`), R1/R2,
  C1, a camera housing and an assembly, then ran the real fingerprint pipeline (2 canonical parts, 2
  `same_as` links). Verified: **`MG996R` is ONE row** with `electrical: U3 · mechanical: Servo body`,
  R1/R2 one row qty 2, the assembly absent; a planned NEMA 17 (purchase) and a 6061-T6 plate (raw
  material, no part number) added and lifecycle-changed through the API AND the desktop select;
  overlay on the servo (received / Mouser / €8.25) with `quantity` refused (422); settings →
  `Preferred suppliers: Mouser, Digi-Key · EUR · cost target €30.00 · over target`; CSV attachment
  with formula-safe cells; `max_items = 1` → 422 "already holds 1 BOM rows"; a live SOL turn
  (`action_mode: do`) called `bom.add_item` and the Raspberry Pi row landed as `planned`. ST3: the
  rail in A reads … Team · Store · **separator** · BOM; the desktop BOM tab opens the in-repo page;
  right-click → _Pin for all projects_ → pin dot; project B shows a dimmed pinned BOM tab ("BOM — not
  installed here") whose screen offers _Install in this project_ → the Store detail (FIRST-PARTY
  badge, `Pinned for all projects`, `NEEDS EDA|CAD`); unpin from the header empties B's rail; a KiCad
  source connected in B raised **"BOM is now available · You connected an EDA tool …"** whose View
  landed on the detail with Install enabled; pins per user (the community account sees none); B's
  BOM routes 404. Screenshots in the session scratchpad (`shot-A-rail`, `shot-A-bom`, `shot-B-pinned`,
  `shot-B-store-detail`, `shot-B-toast`, `shot-A-menu`).
- **Not exercised live:** the repo `[ext.bom]` path (a synced code source with `.solus/project.toml`;
  covered by ST1's reader tests and `effective_bundle_config`), a viewer-role desktop session, the
  Store's own permissions step for BOM (the install used the API; the step is SOLUSDEV-235 code), and
  the OS save dialog for the CSV (the download is a standard blob anchor; the bytes were verified over
  the API). All are in `docs/qa/COWORK_QA_store-st3-st4.md`.

## Found by the real run, not by the suites

- The ST2 real run had left a **COMMUNITY extension under the slug `bom`** in the dev database.
  Once `bom` became an in-repo capability, the publish gate reserved the id and the staff publish
  answered `409 slug_taken`. The dev-only rows were deleted by hand (local database only). This is
  a real product gap (security review M3): slugs are claimed forever, so a first-party id must be
  reserved BEFORE Solus ships it. Recommended: a static reserved-id list checked by
  `publish_gate.first_party_problems`, and a documented staff transfer path instead of deletes.
- The community test fixtures published as `bom`; they now publish as `bom-lite` (25 tests across
  six files touched only in that literal).
- A zsh gotcha (no word-splitting of `$VAR` holding curl flags) and an Electron launch cwd gotcha
  each cost a turn; recorded in memory for later tickets.

## Decisions made under delegated judgment

- Pinned entries come first in the rail (by pin time), then the project's other installs (by
  install time); pins count toward the existing cap of 8.
- A pin of an extension with no page view still gets a tab (name + neutral glyph) that opens the
  Store detail — the extension's widget lives on the canvas; the tab is the way to it.
- The suggestion fires once per newly connected KIND, only for extensions that were not installable
  before, never on a timer; the first known source list is a baseline, never a trigger.
- `bom.add_item` is additive and reversible, so it is not confirmation-gated; its scope is bound by
  Solus code and its bound and cap match the route. The live SOL turn's prose said the change was
  "waiting for your approval" while the row had already been written — a model-phrasing wart for the
  tool's description to address in a follow-up, not a gate change.
- Design rows' `name` and `quantity` are the design's; a PATCH with either is `422`, not ignored.
- The BOM view reads at most 20 000 part rows and says `truncated: true` past that.
- Uninstall soft-deletes every `ext:bom:item` (items AND overlays); parts, canonical rows and links
  are never touched.

## Deviations and open items

- **Tier-1 wireflow amendment:** the rail order in `docs/wireflows/extensions-runtime.md` §2 (tabs
  were "directly ABOVE the Store"; the ticket puts them after it behind a separator) — amended in
  this MR, review at the MR.
- **Dev-only DB cleanup** of the community `bom` rows (above). Nothing in staging/prod was touched.
- **Full API suite** excluded `tests/corpus` (the CORPUS C2 session's suite parametrizes with a
  random uuid, so xdist workers collect different ids); reported to that session.
- The API suite's shared test database is per checkout, so with three sessions in one checkout each
  ran on its own `SOLUS_TEST_DATABASE_URL`; the Stop hook's run uses the default name.
- `useExtensions.ts:126` lint error and the H9 hook's `vitest --silent <file>` incompatibility are
  pre-existing and untouched.

## Env you must set

Nothing new beyond ST1 (`SOLUS_STAFF_USER_IDS` for the staff publisher; a shared
`SOLUS_ARTIFACT_LOCAL_ROOT` for API + worker in local dev). Databases need `alembic upgrade head`
(`e1f2a3b4c5d6` adds `user_extension_pins`; the CORPUS migration `a9c0d1e2f3b4` chains after it).
Before the first real publish of `bom` in any environment, remove or transfer any community
extension already holding that slug (M3).

## Commits

`956e04d` pins API · `0c82a01` BOM backend + bundle · `421cddb` desktop (rail, pins, suggestion,
first-party page, BOM screen), `store.suggested`, route plans, wireflows · `cf65b85` Phase 4 review
fixes + Cowork QA plan · plus this report.
