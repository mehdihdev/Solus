# Completion report — SOLUSDEV-246 · STORE ST5: Sourcing, one engine for two doors

**Branch:** `SOLUSDEV-244-home-h3-root-preferences` (shared with the HOME and CORPUS sessions; every
commit below was made by explicit path, nothing pushed, no MR opened).
**Commits:** `d3a9879` (API: engine, routes, migration, tool) · `27bae77` (desktop panel + two doors +
docs) · `d460b8d` (live-run engine fixes) · `b0dd95b` (live-run UI fixes + lint split) · `27f8fb3`
(review fixes + Cowork QA) · this report.
**Cowork QA:** `docs/qa/COWORK_QA_store-st5-sourcing.md`.

## What was built

One sourcing engine behind two doors:

- **Workspace › Add › Hardware › Find a sourced part** (`door: workspace`) — the same panel the BOM uses,
  defaulting to _From CAD_: pick an assembly, **Derive torque from geometry** (Solus arithmetic over
  placements and masses; massless parts are named and can be given a mass), find candidates, compare,
  select into a robot category → a manual `part` with `lifecycle: planned` and a `contains` edge.
- **BOM › Find compatible parts** (`door: bom`) — _Describe_: text, load/arm, protocol, voltage; the
  selected part lands in the project and the BOM refreshes with it as PLANNED.
- **Engine** (`packages/api/src/solus_api/sourcing/`): `torque.py` (pure), `rules.py` (deterministic
  compliance/style filter: excluded suppliers, certifications, max voltage, protocols, preferred),
  `candidates.py` (fenced prompt, tolerant parser, grounded-or-labelled), `service.py` (assembly read,
  rules layers, selection), `engine.py` (never-raises job), `worker.py` (ARQ), `tools.py` (SOL tool
  `sourcing.derive_torque`).
- **Routes** `/api/v1/projects/{id}/sourcing`: `GET/PUT rules`, `POST torque`, `POST/GET requests`,
  `GET requests/{id}`, `POST requests/{id}/select` — `docs/api/sourcing.md`, `API.md` §2.21.
- **Schema**: `sourcing_requests` + `jobs.kind = sourcing` (`f0a1b2c3d4e5`) — `docs/schemas/sourcing.md`.
- **Wireflows**: `docs/wireflows/sourcing.md`; amendments to `workspace.md` (Hardware panel) and
  `bom.md` (header button).

## Governing docs

DECISIONS.md ADR-027 (graph), ADR-017/018/019/024 (metering), ADR-025 (roles), ADR-035 (`[ext.<id>]`
repo tables), CLAUDE.md §7; `docs/api/API.md` §1 conventions; the route plan, wireflow and schema doc
above were written before the code (tier-1, reviewed at the MR). The standing rules name
`docs/design/SPEC.md` and `docs/design/screens/`, which do not exist in this repository; the real
governing docs above were used instead.

## Acceptance — verified live in the real Electron app against a private API (:8001) + ARQ worker

| Criterion                                                      | Result                                                                                                                                                                                                                                                                  |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Derive torque from a real assembly                             | "Arm assembly" (Arm link 0.6 kg @ 300 mm, Gripper 0.4 kg @ 450 mm, Camera no mass @ 420 mm) → **5.30 N·m** (static 3.53 × 1.5), `unknown: [Camera]`; with Camera 0.1 kg → **5.91 N·m**. Screenshot `shot-ST5-torque.png`.                                               |
| Select a motor; planned in Workspace and BOM                   | AK70-10 selected into "Actuators / motors" from the panel → manual `part`, `lifecycle: planned`, `contains` edge from the category (DB-verified), BOM row `AK70-10 · planned · qty 1 · T-Motor Store`. Screenshots `shot-ST5-selected.png`, `shot-ST5-bom-planned.png`. |
| A compliance rule excludes a supplier with the reason visible  | Rule `MyActuator: Vendor failed the lab compliance audit (no export paperwork)` → "EXCLUDED BY THIS PROJECT'S RULES · RMD-X8 Pro CAN Actuator · Supplier 'MyActuator Official Store' is excluded: …" in the panel; a protocol rule excluded a CAN-FD part the same way. |
| Every recommendation states what it optimises for and gives up | Required fields; a candidate without them is dropped at parse. Visible on every column.                                                                                                                                                                                 |
| Grounding                                                      | CITED candidates carry an https source (host shown); UNVERIFIED ones carry no price and no stock (nulled server-side).                                                                                                                                                  |
| SOL tool                                                       | Live SOL turn: `sourcing.derive_torque` called with `assembly_name: "Arm assembly"` and answered with the same numbers as the route.                                                                                                                                    |

Live runs consumed real model calls (`claude-sonnet-5`), 8 requests in total.

## What the live run caught (and would not have been caught by the suites)

1. **Claude 5 thinking consumed the whole 3000-token output cap** — the gateway returned an empty
   string after 3000 billed output tokens. Fixed: 12 000-token cap + parser salvages a truncated array
   - zero-candidate diagnostics in the log.
2. **Telling the model the excluded suppliers hid the exclusion**: it simply never proposed them. Fixed:
   excluded suppliers are withheld from the prompt and applied after parsing, so the reason is visible.
3. **SOL could not call the torque tool** because it only accepted an entity id and the agent only knew
   the name. Fixed: `assembly_name` resolves inside the project; an unknown name lists the assemblies.
4. UI: the tall panel had no internal scroll; the searching line lower-cased "N·m"; the category
   defaulted to the first category (Wiring) instead of Actuators.

## Review outcomes (fresh-context code review + security review, all findings fixed in `27f8fb3`)

- Code review HIGH — sub-assembly children were silently dropped from the torque: now counted when
  they carry a rolled-up mass + placement, else NAMED in `unknown` (test added).
- Code review MEDIUM — `/requests` accepted an empty ask and spent a metered call: 422 at the boundary.
- Security H1 — `part_class` reached the instruction head of the prompt: removed; every caller field
  is fenced (test asserts the head is clean).
- Security H2 — cross-project tests used random ids: real foreign assembly and category now 404
  byte-identically to a ghost id, with nothing created.
- Security M1 — a request whose creator was deleted would run ungated: `unknown_requester`, no call.
- Security M2 — ARQ retries / re-delivery could buy a second model call: idempotent `run_request`,
  `max_tries=1`, 480 s timeout.
- Security M3 — unbounded `preferences` dict persisted: typed four-section body, extras dropped.
- Security M4 — 300 chars of model text at WARNING: now shape/size/digest at WARNING, head at DEBUG.
- Security L1/L3/L4 — `/torque` shares the 10/min budget; a failed dispatch settles the request as
  `dispatch_failed`; every model-chosen link shows its destination host.
- Not done (LOW, noted): the per-process 10/min limiter (documented parity gap shared with the
  extension routers); `defaultCategory` ignores `part_class` (user-correctable before selecting).

## Tests

- API: `tests/sourcing/` (torque, rules, candidates, routes incl. isolation, budget, engine failure
  modes, SOL tool by id and by name) + BOM row additions — **see the suite lines at the end**.
- Desktop: `features/sourcing/*` (logic, hook, modal, compare, rules editor), door tests in
  `BomScreen.test.tsx` and `usePhysicalRobots.test.tsx`.
- Red-team: the prompt-fencing tests (`test_the_prompt_fences_every_untrusted_input…`,
  `test_the_part_class_never_reaches_the_instruction_head`) and the parser's drop rules.

## Decisions under delegated judgement

- Rules live in two layers: the repo's `.solus` `[ext.sourcing]` table (read from the connector row)
  under a project-level `sourcing_rules` manual entity written by `PUT /rules` — no bundle settings
  exist for a core feature, and the wireflow needed an in-panel editor.
- The selected part's domain follows the category (sensors/controllers/power/wiring → electrical, else
  mechanical); with no category (BOM door) it is mechanical.
- Masses come from the graph (`mass_kg` / `mass`) or a caller override map; lever arm is the
  horizontal distance from the pivot to the child's placement (edge attr `placement`, mm).
- The BOM's design-row reader now shows a MANUAL part's own lifecycle/supplier/cost/quantity when no
  overlay exists, so a sourced part reads PLANNED without a second write.
- Dev `.env` runs jobs inline (`SOLUS_SYNC_INLINE=true`); production uses the ARQ function.

## Values the human must set / do

- Nothing new in `.env`. The dev database needed `alembic upgrade head` for `sourcing_requests` —
  note that starting the API before the migration lets `create_all` create the table first and the
  migration then fails on DuplicateTable (drop the empty table, upgrade).
- Provider key in the SecretStore (already seeded locally) for live sourcing.

## Known gaps / unverified

- The Workspace canvas rendering of the planned part under its category was verified through the API
  and the database edge, and through the BOM tab in the app; the graph canvas itself was not
  screenshotted.
- Real Onshape-connected assemblies (mass properties from the connector) were not available locally;
  the assembly was seeded by script with the same attrs the connector writes.
- The peer's report of `test_registry_lists_only_the_reference_tool` failing was caused by this
  ticket registering the tool for every registry; it is now registered with the user-scoped feature
  tools and the test passes.

## Suite results (final code, `27f8fb3`)

| Suite | Result |
| --- | --- |
| API full suite, private database `solus_test_st34` (`uv run pytest -q`) | **4238 passed, 5 skipped** in 23 min (slow: three sessions' suites shared the local Postgres; per-test TRUNCATE waits on fsync) |
| Desktop full suite (`npx vitest run`) | **2903 passed, 1 failed** — `widgets/livebench/LiveBenchWidget.test.tsx` "shows tiles, a chart, and a data-derived stream state" (a timing assertion untouched by this ticket, last changed in `ae8fe02`); it passes when run alone, a load-induced flake |
| Lint / types | ruff + mypy clean on the sourcing modules and tests; eslint + `pnpm typecheck` clean on the desktop |

The H10 Stop gate's own full-suite run timed out during this session (pytest-timeout while eight
pytest processes from three sessions shared one Postgres); the private run above is the evidence
for this branch. The remaining eslint output on the gate is max-lines WARNINGS in HOME-session files,
not errors.
