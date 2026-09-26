# COWORK QA — STORE ST3 (the Store tab) and ST4 (the BOM widget) — SOLUSDEV-246

End-to-end test plan for two features that ship together: **ST3** — installed widgets get their own
nav tab AFTER a separator following Home | Overview | Workspace | Sources | Live Bench | SOL | Team |
Store; right-click a tab → _Pin for all projects_ (otherwise a tab is per project); a widget is
suggested in context when its prerequisite connects — and **ST4** — the first-party **BOM**
widget: every part in the robot, raw materials and anything purchased, ONE row per physical part
(a fingerprinted servo in CAD and the schematic is one row), lifecycle state per row, supplier
preferences and cost target as configuration, CSV export. Written for a tester with the running
application and this file only.

## 0. Setup

1. Stack up per `docs/RUNBOOK.md` §0: `make db-up` (Postgres **and** Redis), `cd packages/api &&
uv run alembic upgrade head` (the head includes `e1f2a3b4c5d6`, the pins table), `make
seed-secrets`. Start the API **and** the ARQ worker (publish review is an ARQ job):
   ```bash
   export SOLUS_STAFF_USER_IDS=<STAFF users.id>            # see step 2; NOT in .env
   export SOLUS_ARTIFACT_LOCAL_ROOT=/tmp/solus-artifacts    # API and worker must share it
   cd packages/api && SOLUS_CORS_ORIGINS="http://localhost:5173" uv run uvicorn --factory solus_api.main:create_app --port 8001
   cd packages/api && uv run arq solus_api.worker_main.WorkerSettings
   ```
2. Two accounts: **STAFF** (publishes the BOM bundle; on `SOLUS_STAFF_USER_IDS`) and **MEMBER**
   (a second user on STAFF's team, role `member`). Mint dev tokens per RUNBOOK §1; `GET
/api/v1/users/me` once each to provision them, then put STAFF's `users.id` in
   `SOLUS_STAFF_USER_IDS` and restart the API and worker.
3. If the local catalog already has a COMMUNITY extension with slug `bom` (left by an earlier QA
   run), the publish below answers `409 slug_taken`: remove that dev-only row first (it is test data;
   see the completion report's "slug collision" note).
4. Publish the first-party BOM bundle as STAFF and wait for approval:
   ```bash
   cd packages/api/src/solus_api/extensions/bundled/bom && zip -r /tmp/bom-0.1.0.zip . -x '.*'
   curl -X POST $API/extensions/publish -H "Authorization: Bearer $STAFF" -H "Idempotency-Key: bom-1" -F "bundle=@/tmp/bom-0.1.0.zip;type=application/zip"
   curl $API/extensions/bom/versions/0.1.0/review -H "Authorization: Bearer $STAFF"   # until "approved"
   ```
5. STAFF creates two projects in the same team: **A** ("Rover A") and **B** ("Rover B").
6. Desktop: `cd apps/desktop && VITE_SUPABASE_URL= VITE_SUPABASE_ANON_KEY=
VITE_API_BASE_URL=http://127.0.0.1:8001/api/v1 npx electron-vite dev`, sign in as STAFF (dev
   bypass + a minted token per `docs/RUNBOOK.md`), open project A from Home.

Shorthands: `$API` = `http://127.0.0.1:8001/api/v1`; `ROWS` = `GET $API/projects/<P>/widgets/bom/rows`.

## 1. Rail layout and the Store (ST3)

| #   | Step                                                                                | Expected                                                                                                                                                                                            | Pass |
| --- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 1.1 | Open project A with nothing installed. Look at the rail.                            | Order top to bottom: Home, Overview, Workspace, Sources, Live Bench, SOL, Team, **Store (+)**. NO separator and no extension tabs.                                                                  | ☐    |
| 1.2 | Store › open **BOM**.                                                               | Detail shows publisher `SOLUS ✓`/`COMMUNITY` badge AND a `FIRST-PARTY` badge; header has `Pin for all projects` + a disabled `Install` with `NEEDS EDA\|CAD`; REQUIRES card lists EDA or CAD unmet. | ☐    |
| 1.3 | Overview tab › WHAT IT ADDS.                                                        | `Page: BOM`, `Permissions` ("Asks for nothing"), and `Runs in Solus (first-party)` — "backend routes · 1 graph kind · 1 SOL tool — implemented and reviewed inside Solus…".                         | ☐    |
| 1.4 | Open **Fixture Bundle** (also first-party) then any community bundle if one exists. | The community bundle has NO first-party badge or row.                                                                                                                                               | ☐    |

## 2. Install in A, absent in B, separator visible (ST3 acceptance)

| #   | Step                                                                                                                                | Expected                                                                                                                              | Pass |
| --- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 2.1 | Sources (project A) › connect a KiCad source (or `POST $API/projects/A/sources {"type":"kicad","name":"rover.kicad","config":{}}`). | The source lists as connected.                                                                                                        | ☐    |
| 2.2 | Store › BOM › `Install` › `Grant and install`.                                                                                      | `● INSTALLED`. The rail now shows, after the Store `+`: a thin **separator line**, then a **BOM** tab (its icon). Nothing else moved. | ☐    |
| 2.3 | Hover / inspect the BOM tab.                                                                                                        | Tooltip `BOM`; it is not dimmed; no accent dot (not pinned).                                                                          | ☐    |
| 2.4 | Topbar switcher › project **B**.                                                                                                    | The rail has NO BOM tab and NO separator (B has no installs, no pins).                                                                | ☐    |
| 2.5 | `GET $API/projects/B/widgets/bom/rows` as STAFF.                                                                                    | `404 not_found` — the bundle is not there for B.                                                                                      | ☐    |

## 3. Pin for all projects (ST3)

| #    | Step                                                                                                       | Expected                                                                                                                                                                                                                                          | Pass |
| ---- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 3.1  | Back in A, **right-click** the BOM tab.                                                                    | A menu titled `BOM`: `Pin for all projects` · `Open in Store`.                                                                                                                                                                                    | ☐    |
| 3.2  | Click `Pin for all projects`.                                                                              | The tab gains a small accent dot (tooltip "Pinned for all projects"). `GET $API/users/me/extension-pins` lists `bom` with `page: {label: "BOM", icon: "icon.svg"}`, `version: "0.1.0"`.                                                           | ☐    |
| 3.3  | Right-click the tab again.                                                                                 | The menu now offers `Unpin from all projects`.                                                                                                                                                                                                    | ☐    |
| 3.4  | Switch to project **B**.                                                                                   | The separator and a **BOM** tab appear, **dimmed**, tooltip `BOM — not installed here`, with the pin dot. `GET …/projects/B/extensions` still lists nothing — pinning installed nothing.                                                          | ☐    |
| 3.5  | Click the dimmed BOM tab in B.                                                                             | An honest screen: "BOM isn't installed in Rover B" · "This tab is pinned for all your projects. Install the extension here to use it in this one." · `Install in this project` · `Unpin` · `PINNED FOR ALL PROJECTS`. No extension frame, no BOM. | ☐    |
| 3.6  | `Install in this project`.                                                                                 | The Store opens on BOM's detail page (the `← Store` link is there). `Install` is disabled with `NEEDS EDA\|CAD` until B has a source; the header shows `Pinned for all projects`.                                                                 | ☐    |
| 3.7  | Click `Pinned for all projects` in the header (unpin).                                                     | The button reads `Pin for all projects`; go to Overview: B's rail has no BOM tab and no separator; `GET $API/users/me/extension-pins` → `[]`.                                                                                                     | ☐    |
| 3.8  | As MEMBER (second desktop or API): `GET $API/users/me/extension-pins`; pin `bom`; then as STAFF list pins. | MEMBER's list is independent of STAFF's (pins are per user, never shared).                                                                                                                                                                        | ☐    |
| 3.9  | `PUT $API/users/me/extension-pins/ghost`; `PUT …/extension-pins/Not_A_Slug!`.                              | `404 not_found`; `422 validation_error`.                                                                                                                                                                                                          | ☐    |
| 3.10 | Sign out on the desktop, sign in as MEMBER.                                                                | The rail shows MEMBER's pins only (STAFF's were cleared on sign-out).                                                                                                                                                                             | ☐    |
| 3.11 | Settings › Developer › load an unpacked extension with a page; right-click its tab.                        | `Pin for all projects` is disabled with "Developer registrations live on this machine only."                                                                                                                                                      | ☐    |

## 4. Suggest a widget in context (ST3)

| #   | Step                                                                                                         | Expected                                                                                                                                                                    | Pass |
| --- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 4.1 | In project **B** (no sources, BOM not installed, not pinned) open **Sources**.                               | "No tools connected yet."                                                                                                                                                   | ☐    |
| 4.2 | Connect a KiCad source (the Sources page wizard, or the API call from 2.1 against B while the page is open). | Within ~10 s a toast: **"BOM is now available"** · "You connected an EDA tool. Every part in the robot, raw materials and purchases — one row per physical part." · `View`. | ☐    |
| 4.3 | Click `View`.                                                                                                | The Store's BOM detail page; `Install` is now enabled.                                                                                                                      | ☐    |
| 4.4 | Connect a SECOND EDA source (Altium) in B.                                                                   | No toast — no NEW kind connected.                                                                                                                                           | ☐    |
| 4.5 | Install BOM in B, then connect a CAD source (Onshape).                                                       | No toast for BOM (installed); a toast only for another catalog extension that CAD newly unlocks, if any.                                                                    | ☐    |
| 4.6 | (consented user) DB: `select payload from data_events where event_type='store.suggested'`.                   | `{ slug: "bom", unlocked_by: ["eda"], candidates: N }`.                                                                                                                     | ☐    |

## 5. The BOM view — a fingerprinted servo appears once (ST4 acceptance)

Seed project A with parts the way the connectors and the fingerprint would (a scratch script over
the API package; see the completion report for the exact one): a CAD `part` "Servo body"
(`modality_hints.part_number = "MG996R"`), a schematic `component` "U3" (`part_number = "MG996R"`),
resistors R1/R2 (`RC0402FR-0710KL`), a capacitor C1 (`value = 100n`, no MPN), a CAD part "Camera
housing", and an assembly "Chassis" (`attrs.is_assembly = true`); then run
`fingerprint.ingest.scan_project` and `linking.linker.link_from_fingerprint` for A.

| #   | Step                                                                                                                                                                           | Expected                                                                                                                                                                                                                      | Pass |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 5.1 | `ROWS` for A.                                                                                                                                                                  | ONE row `MG996R` (`kind: design`, key `canonical:<uuid>`, `quantity: 1`, `state: installed`) whose `sources` list BOTH `electrical: U3` and `mechanical: Servo body`. NOT two rows.                                           | ☐    |
| 5.2 | Same response.                                                                                                                                                                 | `RC0402FR-0710KL` is ONE row with `quantity: 2` (R1 + R2); `100n` and `Camera housing` are separate `entity:` rows; **Chassis is absent** (assemblies are not parts). `totals.rows` counts exactly these; `truncated: false`. | ☐    |
| 5.3 | Desktop: click the BOM tab in A.                                                                                                                                               | The in-repo page (`BOM · by Solus`, `Export CSV`, `Add row`) — NOT a sandboxed frame. The table shows the same rows; the servo row reads `electrical: U3 · mechanical: Servo body`; every row has a `State` select.           | ☐    |
| 5.4 | Seed a CAD part and a schematic symbol that share a part-number STRING but were NOT matched by the fingerprint (e.g. hints under different, non-normalizable strings), `ROWS`. | They stay TWO rows — the BOM never merges across domains by name alone (ADR-012).                                                                                                                                             | ☐    |

## 6. Planned purchases, raw materials, lifecycle (ST4)

| #   | Step                                                                                                                                                             | Expected                                                                                                                                                                     | Pass |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 6.1 | Desktop › BOM › `+ Add row`: Name `NEMA 17 stepper`, Category Purchase, Quantity 2, Unit cost 14.5, Part number 17HS4401, Supplier StepperOnline › `Add to BOM`. | The dialog closes; a `PURCHASE` row, state **Planned**, line €/$29.00.                                                                                                       | ☐    |
| 6.2 | `+ Add row`: Name `6061-T6 plate 3 mm`, Category Raw material, Quantity 4.                                                                                       | A `RAW MATERIAL` row, Planned, no part number — a row with no design counterpart works.                                                                                      | ☐    |
| 6.3 | `+ Add row` with an empty name; then Quantity `0`; then Unit cost `-1`.                                                                                          | Inline: "Give the row a name." / "Quantity must be a whole number of at least 1." / "Unit cost must be zero or more." — the dialog stays open.                               | ☐    |
| 6.4 | Change the motor's State select to **Ordered**.                                                                                                                  | The row re-reads as Ordered; `ROWS` shows `state: ordered`.                                                                                                                  | ☐    |
| 6.5 | Change the servo (design) row's State to **Received**; `PATCH …/rows/<servo key> {"supplier":"Mouser","unit_cost":8.25}`.                                        | The design row now carries state/supplier/cost (an overlay); `quantity` is still 1.                                                                                          | ☐    |
| 6.6 | `PATCH …/rows/<servo key> {"quantity": 5}`.                                                                                                                      | `422 validation_error` — "A design row's name and quantity come from the design".                                                                                            | ☐    |
| 6.7 | Design row: no `Remove` button. Item row: `Remove` › confirm `Remove row`.                                                                                       | The item disappears; DB: the `ext:bom:item` row has `deleted_at` set (soft delete).                                                                                          | ☐    |
| 6.8 | `DELETE …/rows/<servo key>`.                                                                                                                                     | `204`; the servo row is back to `installed`, no supplier — the overlay was cleared, the part stays.                                                                          | ☐    |
| 6.9 | Ask SOL in A (Expert/`do` mode): "Add a planned purchase to the BOM: 2x Raspberry Pi 5 8GB, part number SC1112, supplier Pimoroni, unit cost 76.50."             | The turn calls `bom.add_item`; `ROWS` shows the row as `purchase`, `planned`. Asking SOL to add a part that is already in CAD gets a refusal to duplicate, not a second row. | ☐    |

## 7. Configuration and CSV (ST4)

| #   | Step                                                                                                                                      | Expected                                                                                                                                                                                                                                                            | Pass |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 7.1 | Store › BOM › Settings: Preferred suppliers `Mouser, Digi-Key`, Cost target `30`, Currency `EUR`.                                         | BOM page line: `Preferred suppliers: Mouser, Digi-Key · EUR · cost target €30.00`; totals read `… total €37.25 · over target €30.00` (with 6.1 + 6.5 in place); `ROWS.config` matches.                                                                              | ☐    |
| 7.2 | In the project's repo commit `.solus/project.toml` with `[ext.bom] currency = "GBP"` and sync the code source; clear the install setting. | `ROWS.config.currency` is `GBP` (repo table beats the manifest default; an install setting beats both).                                                                                                                                                             | ☐    |
| 7.3 | `Export CSV`.                                                                                                                             | The OS save dialog offers `bom-rover-a.csv`; the file has the header `key,kind,name,part_number,manufacturer,quantity,state,supplier,unit_cost,line_cost,sources,notes` and one line per row; the servo line's `sources` is `electrical:U3; mechanical:Servo body`. | ☐    |
| 7.4 | Add a row named `=HYPERLINK("http://x")`, export again, open in a spreadsheet.                                                            | The cell shows the text `'=HYPERLINK(...)` — never a live formula.                                                                                                                                                                                                  | ☐    |

## 8. Isolation, roles, uninstall

| #   | Step                                                                                                 | Expected                                                                                                                        | Pass |
| --- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 8.1 | A user on another team: `ROWS` for A; `PATCH …/rows/<any A key>`.                                    | `404` both — the project does not exist for them.                                                                               | ☐    |
| 8.2 | A **viewer** on A's team: `ROWS`; `POST …/rows`.                                                     | `200` (reads are open to members of any role); `403 forbidden`.                                                                 | ☐    |
| 8.3 | Install BOM in B; use an A row key in B: `PATCH $API/projects/B/widgets/bom/rows/<A key>`.           | `404` — keys never resolve across projects.                                                                                     | ☐    |
| 8.4 | Store › BOM › Disable (A).                                                                           | The BOM tab leaves A's rail (unless pinned, in which case it is a dimmed pin-only tab); `ROWS` → `404`.                         | ☐    |
| 8.5 | Store › BOM › Uninstall › confirm.                                                                   | `ROWS` → `404`; DB: every `ext:bom:item` row of A has `deleted_at`; the `part`/`component`/`canonical_part` rows are untouched. | ☐    |
| 8.6 | Team owner blocks `bom` (`PUT /teams/{team}/extensions/policies/bom {"blocked": true}`) then open A. | The tab is gone (or pin-only); the BOM routes answer `404`; the Store shows `BLOCKED`.                                          | ☐    |

## 9. Regression touchpoints

- Community extension pages (a `views.page` bundle without `[backend]`) still open in the sandboxed
  frame after the separator, and `Open in Store` from their page lands on THEIR detail page.
- Live Bench canvas, Store catalog/detail tabs, the ST1 fixture bundle's routes and tools, and the
  ST2 workspace graph (`GET …/widgets/graph` shows the BOM `solus:widget` node while installed) are
  unchanged.
- SOL never lists `ext:bom:item` rows as parts of the robot when asked about the design (they are
  `project`-domain configuration rows); `bom.add_item` appears in `GET …/sol/tools` only while BOM
  is installed and enabled.
