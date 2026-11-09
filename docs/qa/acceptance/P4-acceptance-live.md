# P4 acceptance, live proof (SOLUSDEV-321 plan §3 "P4 acceptance"; dispatch items 1–5, the twin-compare leg, the pre-check leg and the single-source ladder check): in process, ONE ARQ worker, copy of the dev DB

`t` below is seconds after the leg's harness was built (each leg has its own zero, about 1 s after
its process started). Worker events are placed by wall time. Three harness legs and one worker ran:

- **arq-park** (`sync_inline=False`, NO consumer yet): items 1–3 on a fresh project, a CAD-leaf copy
  of variant (b), the rung-3 mesh checks QUEUED, the CAD import card PARKED.
- **the ONE worker** (`p4_worker.py`, pid 353971), started after the park: it ran the two queued
  mesh checks, so a simulation landed between the park and the approval.
- **arq-approve** (`sync_inline=False`, worker up): the card approved through the gate, item 4 read
  back, the worker's runs read.
- **inline** (`sync_inline=True`, no worker): items 1–4 again, the in-process matrix job (R97), the
  CAD card with a simulation landing in between (the mesh job called in process the way the worker
  calls it), the forced pre-check failures, the flash card at 50 rows, the twin compare. Two earlier
  inline attempts are void (harness bugs; deviation 7) and kept as evidence.

## Verdicts

- **1. Variant (a), 15 % of yield, stops at rung 1 and says so: PASS (both legs).**
  - How it was called: SOL's `simulate` itself, in process, through the registry and gated
    dispatcher a turn gets (`build_sol_registry(user_id, team_id, systems, graph_hub,
    enqueue_sim, scene_enqueue)` + `build_dispatch(registry, park)`), under a minted user with the
    person's read scope bound. No SOL turn (a turn needs a model) and no `should_simulate`
    shortcut: the tool needs no turn.
  - `deterministic_mech` ran once: `yield_fraction` **0.15000000000000002**, `stress_mpa`
    41.400000000000006 MPa. The result has `verdict: "stops"` and no `climb`; nothing was
    enqueued for it. The text the person's reply is built from (the tool's `reason`):
    **"yield_fraction is at 15% of its limit at rung 1: with margin, the ladder stops here"**.
  - The ladder proposes nothing for (a): every matrix run (worker, in-process job, dry runs) judged
    it `pass` — "bracket (15 % of yield)'s simulated stress is 15% of its yield (41.4 MPa) at rung 1:
    with margin under it" — and no proposal names it.
- **2. Variant (b), 85 %, escalates; the stress estimate AND the mesh check run: PASS (ARQ leg; the
  mesh check ran in the WORKER).**
  - Rung 1 (in process): `deterministic_mech:cantilever_bending+mesh_mass+mesh_com`, stress 234.6
    MPa, `yield_fraction` 0.8500000000000002 → `verdict: "climbs"` ("yield_fraction is at 85% of its
    limit at rung 1: inside its 0.8 band") → `climb: {decision: queued, rung: 3, provider:
    mesh_interference, job_id: run_mesh_sim:01a1881f-509c-7edd-a052-c82f7f254074:90439291b67d}`.
  - Rung 3 (worker pid 353971, `run_mesh_sim` → `run_and_record` → `QueuedMeshCheck`): `sim_result`
    `01a18820-8906-7365-b561-44c69d241efa`, solver **`mesh_interference:mesh_interference+cantilever_bending`**
    (the numpy check as landed; trimesh is not installed and not used), `interference_mm` 0.0,
    `stress_mpa` 234.6, `yield_fraction` 0.85. Both results' `leaves_out` are pasted under item 2.
  - Inline (no queue): the same rung-1 run, and `climb: {decision: not_available, rung: 3, provider:
    mesh_interference, reason: "no job queue on this server: rung 3 runs only as its bounded job,
    never in a SOL request"}`.
- **3. Variant (c), no material: PASS (both legs).** `MissingInputs.missing` = `[{name: material,
  set_in: "the part's `material` attr: {name, yield_mpa}"}]`, `covered` = the centre of mass only.
  The first `simulate` answers `ask` (and records `attrs.sim_asked = {yield_fraction: [material]}`);
  the second answers `missing_input` and raises the finding **live, through `raise_finding`, by
  `simulate`'s own path**: "could not simulate yield_fraction for bracket (no material): material
  unknown; set it in the part's `material` attr: {name, yield_mpa}". Provider `run()` calls for (c):
  **0 and 0** (one `can_answer` each).
- **4. The run's facts: PASS.** The `sim_result` of (a) is `kind sim_result`, `domain simulation`,
  `origin system`, with `solver`, `inputs{name: {value, source}}` and `leaves_out`; a
  `verified_by` edge from the bracket carries `{kind: "sim", ref, detail: <solver>}`
  (`EvidenceKind.SIM`); `attrs.expected[q] = {value, unit, sim_result_id}` on the part;
  `graph.changed` was published right after the commit and the fan-out's `EnvelopeCache.invalidate`
  dropped a cached envelope of the project; P2-T1's envelope reports `bounds_source {"nominal":
  "sim"}` (confidence 0.8) for `yield_fraction` and `stress_mpa`; `FactStore.expected` returns the
  value; `run_matrix(dry_run=True)` shows `bracket_strength_at_joint` judging it (`pass` for (a),
  `inconclusive` for (b)). One expectation could not be met literally: **no fan-out log line exists
  for a successful invalidation** (deviation 9); the probe and the cache index read are the evidence.
- **5. Rung-3 jobs against real binaries: NOT VERIFIED here, as the dispatch foresaw.** No ngspice
  and no `kicad-cli` on this host (`SOLUS_NGSPICE_BIN` unset → "not available on this machine").
  MuJoCo imports, but the fake arm has no MJCF scene model (`tests/fixtures/fake_arm.py` seeds
  none), so `run_mujoco_sim` had no fake-arm model to take and was not run live. The proofs are
  `tests/test_mujoco_job.py` (23 functions; in the proxy slice, none skipped, so its engine test ran
  against MuJoCo in its child) and the fork's `integrations/mcp/kicad/tests/test_spice_export.py`
  (7 functions; not run here).
- **Compare leg (R117): PASS.** `POST /bench/runs/compare` with `sim_result_id` → 200,
  `expected_source "sim"`, `evidence.sim_control "electrical_or_mechanical"` with `reason: null`,
  `simulation_gap: true`, one residual (`samples 256`, the bound). Without `sim_result_id` → 200,
  byte-for-byte `jsonable_encoder(analysis.compare(stored, stored))` (sha256 `c40aad3c…4c54` both),
  no `evidence`. Another project's `sim_result` and a part's id → **404 `not_found`**. 0 provider
  `run()`, 0 model calls.
- **Pre-check leg (R99, R116, R118): PASS.** The parked CAD card carries one "Simulate first" row
  (≤ 8 rows, ≤ 500 chars) naming `yield_fraction` and rung 3. After the worker's rung-3 run landed,
  the approval re-preview had no such row and the gate did **not** refuse it as stale
  (`_diverged → false`, status `approved`, the import ran). The same with the in-process landing.
  The flash card at 50 rows carries **0** pre-check rows (`room 0`) and parks; a small flash card
  carries 1. A pre-check forced to raise, and one forced past its timeout, each left the card
  parked with exactly its 4 own rows ("simulation pre-check skipped" logged).
- **Ladder single source (Minor 8): PASS.** Every card or pre-check line agrees with `simulate`'s
  answer on the same subject: rung 3, `mesh_interference`, available when queued (`queued`) and
  "; no job queue runs it here" when not (`not_available`). Table under its section.
- **R97, the runner's proposals stay data: PASS.** The in-process matrix job logged `proposals=1`
  and called `can_answer` once, `run()` never; the worker's first matrix run had 2 proposals, 2
  `can_answer`, 0 `run()`.
- **`apply_sim_change`: not exercised live, as dispatched** (it needs a SOL turn's card); its
  tests are the proof (not in this proxy slice; deviation 14).

**Model calls: 0** in every process: 0 scripted narrations, 0 refusing-adapter reaches, 0 calls
through the gateway's `stream`/`complete`, 0 `model call start` lines, 0 new `credit_ledger` usage
rows. Provider `run()` calls, all closed-form or the numpy mesh check, in process: arq-park 3
(`deterministic_mech` for a, b, leaf), worker 2 mesh checks, arq-approve 0, inline 4
`deterministic_mech` + 1 in-process mesh job.

Ready to paste into the SDD ledger:

> P4 acceptance (live, in process, DB copy `solus_sol` at a32000000006, Redis `solus-redis-321`, no
> provider: 0 scripted, 0 refused, 0 gateway calls, 0 `model call start` lines, 0 usage rows,
> egress loopback-only, every `.env` read refused in harness and worker). Item 1: `simulate` (registry +
> gated dispatcher, no turn) on (a) → deterministic_mech yield_fraction 0.15, verdict stops, "yield_fraction is at
> 15% of its limit at rung 1: with margin, the ladder stops here", no proposal anywhere. Item 2:
> (b) rung 1 0.85 → climbs → `run_mesh_sim:<p>:90439291b67d` queued → worker pid 353971 recorded
> rung 3 `01a18820-8906-…` solver `mesh_interference:mesh_interference+cantilever_bending`,
> interference 0.0 (numpy); inline: climb not_available. Item 3: (c) ask then missing_input,
> finding `simulation_missing_input` "…material unknown; set it in the part's `material` attr",
> run() 0/0. Item 4: sim_result kind/domain/origin + full provenance + verified_by {kind sim} +
> attrs.expected; graph.changed → EnvelopeCache.invalidate dropped the cached key (no success log
> line exists); envelope bounds_source {nominal: sim} 0.8; FactStore.expected; dry run judges
> pass/inconclusive. Item 5: NOT VERIFIED (no ngspice/kicad-cli; no fake-arm MJCF); tests are the
> proof. Compare (R117): evidence electrical_or_mechanical, gap true, residuals 256 samples;
> plain = compare(stored, stored) byte-for-byte; foreign/part id → 404. Pre-check: CAD card 4+1
> rows; approved after the worker's rung 3 landed (R118, not stale); flash at 50 rows → 0
> pre-check rows, parked; forced raise/timeout → parked with own 4 rows. Single source: lines and
> `simulate` agree (queued / not_available). R97: proposals data only (can_answer, never run).
> Proxies: 408 passed in 157.40s (one process). Report: `docs/qa/acceptance/P4-acceptance-live.md.

## Run identity

| Item | Value |
| --- | --- |
| Run time | **arq-park:** command 14:45:14Z → 14:45:28Z, harness 14:45:15.646Z → 14:45:27.420Z, exit 0. **Worker:** started 14:46:35Z, ready 14:46:35.89Z, SIGTERM 14:48:51Z. **arq-approve:** command 14:47:52Z → 14:47:55Z, harness 14:47:53.915Z → 14:47:54.564Z, exit 0. **inline:** command 14:54:47Z → 14:55:02Z, harness 14:54:48.645Z → 14:55:01.960Z, exit 0. Void inline attempts: 14:49:42Z → 14:49:57Z and 14:53:04Z → 14:53:19Z (deviation 7). Proxies 14:56:43Z → 14:59:24Z. |
| Branch | `SOLUSDEV-321-sol-checker-algorithm` |
| HEAD | `df318e1d` before and after. `git status --short` empty throughout; `.coverage` md5 `7571ebfd2af623167baf221f5af68076` before the run and after the proxies. |
| Database | `solus_sol`, asserted from the server by every leg (`select current_database()`); `alembic_version` read `a32000000006` in every leg. No migration exists on the branch since the merge base, so that is head. Nothing was applied, created or dropped. |
| Redis | `redis://127.0.0.1:6390/0`, the branch's `solus-redis-321`. dbsize 0 before the run; `lsof -i :6390` listed 0 lines before the worker started. `solus-redis-1` was not touched. MONITOR (`docker exec solus-redis-321 timeout 900 redis-cli monitor`) ran 14:44:57Z → its own 900 s timeout, 1231 lines (the last 8 are my own key and TTL checks), `p4_redis_monitor_arq.log`. |
| Worker | Python pid **353971** (the consumer), parent uv pid 353890 (recorded in `p4_worker_arq.uvpid`). "Starting worker for 19 functions"; it consumed the two mesh jobs queued 79.16 s before. `kill -TERM 353971` at 14:48:51Z: "shutdown on SIGTERM ◆ 18 jobs complete ◆ 0 failed ◆ 0 retries ◆ 0 ongoing to cancel"; both pids gone within 1 s; the background command exited 0. |
| Harness | `/home/beeboss/Solus/.superpowers/sdd/pasted-content-id-24a5-sol-precious-pillow/acceptance/p4_accept_live.py` (legs `arq-park`, `arq-approve`, `inline`), raw evidence beside it as `p4_accept_live_<leg>_result.json` and `.stdout`/`.stderr`/`.time`. |
| Worker wrapper | `…/acceptance/p4_worker.py` (as P3's: the bare `arq` command would read the root `.env`). Evidence: `p4_worker_arq.log` (arq's own), `p4_worker_events_arq.jsonl` (133 events), `p4_worker_result_arq.json`. |
| Commands | Harness: `cd /home/beeboss/Solus/packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' uv run --frozen --no-sync python <harness> arq-park\|arq-approve\|inline`. Worker: the same two variables through `env`, `uv run --frozen --no-sync python <wrapper> arq`, in the background with its shell pid (then `exec`'d uv) written first. |

## Environment recipe as executed

1. **Database.** `solus_sol` held P3's leave-behind: 11 users, 13 projects, 13 `credit_ledger`
   rows, 120 findings, 0 `sim_result`s, 661 entities, 916 edges, 11 sources, 14 jobs, 0 artifacts,
   0 `tool_confirmations`. Before the worker started I checked the tables its crons drain:
   `artifacts`, `cad_purge_requests`, `stripe_cancel_requests`, `github_webhook_deliveries`,
   `pending_credit_debits`: all 0. The ARQ legs ran before the inline leg, so no artifact existed
   while a worker ran.
2. **Environment.** The two variables were exported per process on the command line only; both
   scripts refuse to start unless exactly those two `SOLUS_*` names hold the prescribed values, and
   the harness re-checks the set after its imports. `SOLUS_TEST_DATABASE_URL` was set only on the
   proxy pytest command line.
3. **Settings, in code** (as P3): `Settings(_env_file=None, supabase_jwt_secret=<token_urlsafe(32)
   per run>, supabase_jwt_audience="authenticated", rate limits 100_000, sync_inline=<inline only>,
   fingerprint_embedding_enabled=False, artifact_local_root=<TemporaryDirectory>)`; the database and
   Redis URLs asserted equal to the exports. `jobs_queued(settings)` was True in the ARQ legs and
   False inline. The worker's `Settings` is a subclass filling the same values with
   `sync_inline=False`.
4. **App.** `create_app(settings, create_async_engine(solus_sol))`, `hardware_connections.owner =
   RuntimeOwner(<tmp>, <tmp>)`, the fan-out installed exactly as `main.py`'s lifespan does
   (`GraphChangedFanout(graph_changed_callbacks(sessionmaker, enqueue=main._enqueue_budgets_job(app)
   if queued else None, store=integration_store, envelopes=envelope_cache))`; callbacks:
   BudgetTrigger, ProjectCardCache.invalidate, the envelope cache's invalidate, the matrix trigger).
   The lifespan was not run, as in P2/P3. In the ARQ legs `app.state.arq_pool` was made first with
   the `create_pool` `routers/sources._arq_pool` makes, so the fan-out's and
   `deps.create_sim_enqueue`'s enqueues were recorded.
5. **Probes, recording only, never raising** (each wraps and calls the original): `LiveHub.publish_to`
   (graph.changed frames), `GraphChangedFanout.__call__`, the inline budgets and matrix jobs (each
   job's task labels its own records), `checker_trigger.run_matrix` (the report, its `proposals`
   and both P4 rules' results), `budgets.store_budgets`, `record_sim_result` (both the
   `sim_facts` and the `simulate` bindings), `EnvelopeCache.invalidate` (with the project's cache
   index read before and after), `precheck_rows` (the CAD and flash tools' bindings),
   `confirmations._diverged` (shown vs current rows), `run`/`can_answer` on `ClosedForm`,
   `NgspiceProvider`, `RigidBodyTrajectory`, `ExternalTarget` and `QueuedMeshCheck`, the
   gateway's `stream`/`complete`, the harness pool's `enqueue_job`; one root log handler at INFO.
   The worker wrapper adds `ArqRedis.enqueue_job`, `run_and_record` and the same provider, matrix,
   budget, fan-out, record and gateway probes. 0 probe errors anywhere.
6. **Order of steps.** MONITOR → pytest guard → arq-park (no consumer: `arq:queue:health-check`
   absent, no worker events file) → the drained-tables and port checks → the worker (wait for
   ready) → pytest guard → arq-approve → SIGTERM to pid 353971 → pytest guard → inline (three
   attempts) → pytest guard in its own call → the proxies. The worker window, 14:46:35Z–14:48:51Z,
   avoided the :00, :05, :15, :30 and :45 crons; the every-minute crons ran and all returned 0
   (`purge_cad_accounts` 3, `cancel_stripe_subscriptions` 3, `sweep_artifacts` 2,
   `reconcile_credit_debits` 2, `recover_onshape_hints` 2 enqueues).

## Why no real provider was reachable

1. **The Narrator's `complete` is scripted (M88) and no bench session started**: 0 calls; at
   shutdown the SessionManager held `_active` 0, `_ended` 0, `_starting` 0 in every leg.
2. **Refusing adapters on `app.state.agent_runner`** (anthropic, google, openai): 0 reaches.
3. **Counted gateway**: `gateway.stream` and `gateway.complete` were wrapped (module attributes)
   before any app was built, in the harness and the worker: 0 calls. 0 `model call start` lines.
4. **No credentials**: `secrets_key` unset, `aws_region` None, `supabase_url` None, `sentry_dsn`
   unset, `ngspice_bin` None; `InMemorySecretStore` asserted in the harness and observed in the
   worker; the JWT secret is per run; the CAD sources' `secret_ref` names no secret.
5. **No `.env` read**: `DotEnvSettingsSource._read_env_files` refuses and records — 1 refusal per
   harness process (`/home/beeboss/Solus/.env` from `toolkb/sharing._ToolkbSettings` at import,
   t ≈ −0.17), 0 in the worker. One exception outside the legs: deviation 10.
6. **Egress, bind and spawn guard** in the harness and the worker: only loopback 5432/6390 connect,
   only loopback names resolve. Attempts: arq-park 7, arq-approve 9, inline 13, worker 15; the only
   denial in each is `bind ('::1', 0)`, urllib3's import-time IPv6 probe (as P3). **Spawns 0,
   listens 0** everywhere (the mesh check is numpy in process; no rung-3 child was started).

| Count | arq-park | worker | arq-approve | inline |
| --- | --- | --- | --- | --- |
| Scripted narration calls | **0** | – | 0 | 0 |
| Refusing-adapter reaches | **0** | – | 0 | 0 |
| Gateway `stream`/`complete` calls | **0** | 0 | 0 | 0 |
| `model call start` lines | **0** | 0 | 0 | 0 |
| Provider `run()` (layer `ClosedForm.run`) | 3 | 2 | 0 | 5 |
| Provider `can_answer()` | 9 | 2 | 0 | 16 |
| `.env` reads refused | 1 | 0 | 1 | 1 |
| ERROR log lines | 0 | 0 | 0 | 0 |

`credit_ledger` gained 4 rows over the whole run, all `trial_grant` (one per minted person: arq,
the two void inline attempts, inline); 0 `usage` rows since 14:44Z.

## Seed (fresh per leg, nothing reused)

Every person was minted as `tests/conftest.py::make_token` does; `/users/me` provisioned them and
`POST /api/v1/teams` + `POST /api/v1/teams/{id}/projects` made their projects. The three brackets
came from `tests/fixtures/sim_bracket.py::seed_brackets(db, project)` — one OCP tessellation per
process: **0.434 s** (arq-park, 14:45:16.57Z) and **0.401 s** (inline, 14:54:49.54Z), 36 triangles /
324 floats, `CacheInfo(hits=3, misses=1)` after. Attrs as the fixture states them (`fake: true` on
each): section rect [30, 5] mm; load 207 N (a, c) / 1173 N (b) at 0.025 m; material `fake-6061`
yield 276 MPa, 2700 kg/m³ (a, b; none for c). Robots via `POST /entities {type: physical_robot}`.

Seeded rows (no route makes them without a provider): each CAD leaf is
`tests/test_simulate.py::_cad_leaf`'s shape carrying `bracket_attrs("b")`, under an ONSHAPE
`Source` row whose `secret_ref` names no secret; the compare scene model binding is
`_shoulder`'s; the routine trajectory is `_routine_sim`'s result through `record_sim_result`.

| Leg | Person / team / project | Brackets a · b · c | Robot | CAD source · leaf |
| --- | --- | --- | --- | --- |
| arq | `01a1881f-506f-7d1c-9140-1e2b49104914` / `01a1881f-508d-77ae-8812-66dbd2a540f5` / **`01a1881f-509c-7edd-a052-c82f7f254074`** | `01a1881f-5288-71d4-a781-a449b7720d1f` · `01a1881f-5289-7c0e-9b13-ec91e9f8d594` · `01a1881f-528a-7b23-bd1a-9e09c4fa8698` | `01a1881f-52a5-7bf8-9dd1-3f0642abc6d8` | `01a1881f-52ba-7e15-804b-49d762ce2571` · `01a1881f-52bd-7ec5-96e6-acfa52905a4c` |
| inline | `01a18828-0eb0-7dcf-9b70-c8973ce45c5f` / `01a18828-0ede-7e6c-8225-8cdbfecc67a5` / **`01a18828-0ef5-77c3-8b4e-15aa1928c3a1`** | `01a18828-10c0-7faf-b013-57f35d6ee196` · `01a18828-10c1-703a-853c-8deb38527a99` · `01a18828-10c2-7887-8c42-ef2029efafca` | `01a18828-10d1-7190-9308-482b20684b79` | `01a18828-3bc1-7a9a-aed2-39103c2e2021` · leaf one `01a18828-3bc4-7b6f-8b9a-4529055c9505`; `01a18828-3bd1-79d8-8679-1d1fd04bbbc3` · leaf two `01a18828-3bd3-7cc7-b154-279a979cadd2` |

Results: arq `sim_result`s a `01a1881f-52f9-7c21-af79-fdb2610960d9`, b rung 1
`01a1881f-532b-757a-875b-b3cb61be16d0`, b rung 3 `01a18820-8906-7365-b561-44c69d241efa`, leaf rung
1 `01a1881f-534b-7dc4-85a1-6158d0d40600`, leaf rung 3 `01a18820-88d9-762f-85b9-e1c97ab2393f`; (c)'s
finding `01a1881f-531b-70c4-b843-20968b96b020`; card `01a1881f-539c-7381-bd8e-8af07a84a65a`. Inline:
a `01a18828-111c-7996-a157-bbe286f157c3`, b `01a18828-1144-7ace-aa2d-201714baf5df`, (c)'s finding
`01a18828-116b-741a-9bef-b03635ab4baa`, leaf one rung 1 `01a18828-3be8-717b-8d23-c958895712d0` and
rung 3 `01a18828-3c43-7924-8ce8-6b352f86fbad`, leaf two rung 1 `01a18828-3cba-7d77-aaf0-1d4940694809`.

## Item 1: variant (a) stops at rung 1 and says so

`simulate {question: {subject_id: <a>, quantity: yield_fraction}}`, arq-park, `ok: true`, 0.033 s,
provider `run()` 1, `can_answer` 1, model calls 0. The value, verbatim:

```json
{
 "decision": "ran",
 "rung": 1,
 "provider": "deterministic_mech",
 "reason": "yield_fraction is at 15% of its limit at rung 1: with margin, the ladder stops here",
 "alternatives": ["mesh_interference"],
 "sim_result_id": "01a1881f-52f9-7c21-af79-fdb2610960d9",
 "values": {
  "stress_mpa": {"value": 41.400000000000006, "unit": "MPa"},
  "yield_fraction": {"value": 0.15000000000000002, "unit": null},
  "mass_kg": {"value": 0.009136800000000002, "unit": "kg"},
  "com_x_m": {"value": 0.014943262411347517, "unit": "m"},
  "com_y_m": {"value": 0.01, "unit": "m"},
  "com_z_m": {"value": 0.0034645390070922, "unit": "m"}
 },
 "inputs": {"load": "known", "section": "known", "material": "known", "moment_nm": "derived",
            "second_moment_mm4": "derived", "extreme_fibre_mm": "derived", "mesh": "known",
            "volume_m3": "derived"},
 "leaves_out": ["shear and axial stress", "stress concentrations at holes and fillets",
                "dynamic loads and fatigue", "buckling", "temperature",
                "section changes along the member", "voids, fasteners and coatings the mesh omits",
                "non-uniform density",
                "solids in the mesh that overlap or cross (only that its surface is closed is checked)",
                "curved faces approximated by flat triangles (the mesh's volume is a little off)"],
 "verdict": "stops"
}
```

- No `climb` key and no enqueue labelled for (a). Inline gave the same reason, verdict and values
  (`sim_result` `01a18828-111c-…`).
- The ladder's proposals are empty for (a): the worker's two matrix runs proposed only (b) and the
  leaf, then nothing; the inline job and dry run proposed only (b). Every bracket result for (a):
  `pass`, "bracket (15 % of yield)'s simulated stress is 15% of its yield (41.4 MPa) at rung 1: with
  margin under it", evidence `{quantity yield_fraction, value 0.15000000000000002, limit 1.0,
  comparator "<=", unit null, sim_result_id 01a1881f-52f9-…, rung 1, stress_mpa 41.400000000000006}`.

## Item 2: variant (b) escalates; the stress estimate and the mesh check run

arq-park `simulate` on (b): `ok`, 0.025 s, `run()` 1, `can_answer` 2. Same values block as (a) with
`stress_mpa` 234.60000000000005, `yield_fraction` 0.8500000000000002 and `moment_nm` 29.325; then:

```json
 "reason": "yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band",
 "verdict": "climbs",
 "climb": {
  "decision": "queued",
  "rung": 3,
  "provider": "mesh_interference",
  "reason": "yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band",
  "alternatives": [],
  "job_id": "run_mesh_sim:01a1881f-509c-7edd-a052-c82f7f254074:90439291b67d",
  "next": "the job records its own result: read it with get_sim_result once it lands"
 }
```

- **Enqueue** (harness pool, t 1.063): `run_mesh_sim`, `_job_id` = that stable id, accepted; the
  request's facts are `{mesh, load, section, material}`, `requested_by` the person.
- **Worker** (events, wall-relative): `run_and_record` start 0.031 → `QueuedMeshCheck.run` →
  `ClosedForm.run` (mesh_interference, 2 ms) → "sim result recorded project=01a1881f-509c-… subject=01a1881f-5289-… rung=3 sim_result=01a18820-8906-7365-b561-44c69d241efa"
  → graph.changed (worker host) `{entities_created 1, entities_updated 1, relations_created 1}` →
  status `{"status": "recorded", "sim_result_id": "01a18820-8906-…"}` at 0.176. arq: "← run_mesh_sim:…:90439291b67d ● {'status': 'recorded', 'sim_result_id': '01a18820-8906-7365-b561-44c69d241efa'}" in 0.15 s.
- **Both results, read back from the rows** (arq-approve):

| | rung 1 `01a1881f-532b-757a-875b-b3cb61be16d0` | rung 3 `01a18820-8906-7365-b561-44c69d241efa` |
| --- | --- | --- |
| `provenance.solver` | `deterministic_mech:cantilever_bending+mesh_mass+mesh_com` | `mesh_interference:mesh_interference+cantilever_bending` |
| values | stress_mpa 234.60000000000005 MPa, yield_fraction 0.8500000000000002, mass_kg 0.0091368, com 14.943 / 10 / 3.465 mm | stress_mpa 234.60000000000005 MPa, yield_fraction 0.8500000000000002, interference_mm 0.0 mm |
| inputs (source) | load, mesh `{triangles: 36}`, section, material: known; moment_nm 29.325, second_moment_mm4 312.5, extreme_fibre_mm 2.5, volume_m3: derived | load, mesh `{bodies: 3, pose_sets: 1, triangles: 36}`, section, material: known; probes 0, edge_face_tests 0, interfering_pairs [], moment_nm, second_moment_mm4, extreme_fibre_mm: derived |
| created_by | the person | the person (the request's `requested_by`) |

rung 1 `leaves_out`: `["shear and axial stress", "stress concentrations at holes and fillets",
"dynamic loads and fatigue", "buckling", "temperature", "section changes along the member",
"voids, fasteners and coatings the mesh omits", "non-uniform density", "solids in the mesh that
overlap or cross (only that its surface is closed is checked)", "curved faces approximated by flat
triangles (the mesh's volume is a little off)"]`.

rung 3 `leaves_out`: `["the depth is the shortest distance either body's bounding box must move
along an axis to clear the other's: an upper bound on how far they interpenetrate", "contact
without interpenetration: bodies that only touch do not interfere", "clearance between bodies that
do not touch", "poses between the stated pose sets: a joint range is checked only where it is
sampled", "a body that intersects itself (pieces of one mesh that share an edge are one body)",
"deformation under load", "shear and axial stress", "stress concentrations at holes and fillets",
"dynamic loads and fatigue", "buckling", "temperature", "section changes along the member"]`.

- `get_sim_result` on the rung-3 id (through the gated dispatcher, arq-approve) returned its rows:
  `{"id":"01a18820-8906-…","name":"interference_mm, stress_mpa, yield_fraction — bracket (85 % of yield)","subject_id":"01a1881f-5289-…","rung":3,"solver":"mesh_interference:mesh_interference+cantilever_bending",…}`, then each value, each `leaves_out` line and each input.
- After rung 3 the bracket rule reads `inconclusive` "bracket (85 % of yield)'s simulated stress is
  85% of its yield (234.6 MPa) at rung 3: inside the ladder's 0.8 band, unresolved: no higher rung
  computes it", and `interference_through_range` `pass` "bracket (85 % of yield)'s bodies clear each
  other in the poses simulated at rung 3".

## Item 3: variant (c), no material: `missing_input` names the field, nothing runs

`DeterministicMech().can_answer(SimQuestion(quantity="yield_fraction", facts=bracket_attrs("c")))`
(`p4_missing_inputs_c.txt`):

```json
{"missing": [{"name": "material", "set_in": "the part's `material` attr: {name, yield_mpa}"}],
 "derivable": [], "covered": ["com_x_m", "com_y_m", "com_z_m"]}
```

The two `simulate` calls on (c), arq-park (inline identical):

```json
{"decision": "ask", "rung": 1, "provider": "deterministic_mech", "reason": "the person asked for it",
 "alternatives": ["mesh_interference"],
 "missing": [{"name": "material", "set_in": "the part's `material` attr: {name, yield_mpa}"}],
 "next": "ask the person for these inputs: this question is not asked again"}
```

```json
{"decision": "missing_input", "rung": 1, "provider": "deterministic_mech", "reason": "the person asked for it",
 "alternatives": ["mesh_interference"],
 "missing": [{"name": "material", "set_in": "the part's `material` attr: {name, yield_mpa}"}],
 "finding_id": "01a1881f-531b-70c4-b843-20968b96b020"}
```

- Provider `run()` 0 and 0, `can_answer` 1 and 1, model calls 0; no `sim_result` for (c); its
  `attrs.expected` absent; `attrs.sim_asked` = `{"yield_fraction": ["material"]}` (version 1 → 2).
- The finding, raised live by `simulate`'s `missing_input` path through `raise_finding` (row
  `01a1881f-531b-…`, kind `finding`, entity domain `mechanical`, origin `system`):

```json
{"rule_id": "simulation_missing_input", "severity": "info", "source": "simulation",
 "headline": "could not simulate yield_fraction for bracket (no material): material unknown; set it in the part's `material` attr: {name, yield_mpa}",
 "subjects": ["01a1881f-528a-7b23-bd1a-9e09c4fa8698"],
 "evidence": {"rung": 1, "target": "deterministic_mech",
              "missing": [{"name": "material", "set_in": "the part's `material` attr: {name, yield_mpa}"}],
              "quantity": "yield_fraction"},
 "count": 1, "status": "open"}
```

The `bucket` (`yield_fraction`) is part of the canonical key (`graph/findings.py:83`), not an attr.

## Item 4: the facts the run leaves

**The `sim_result` of (a)** (arq; read from the row):

```json
{"id": "01a1881f-52f9-7c21-af79-fdb2610960d9", "project_id": "01a1881f-509c-7edd-a052-c82f7f254074",
 "kind": "sim_result", "domain": "simulation", "origin": "system",
 "name": "com_x_m, com_y_m, com_z_m, mass_kg, stress_mpa, yield_fraction — bracket (15 % of yield)",
 "version": 1, "created_at": "2026-10-29T14:45:16.665151+00:00",
 "attrs": {"rung": 1, "subject_id": "01a1881f-5288-71d4-a781-a449b7720d1f",
  "created_by": "01a1881f-506f-7d1c-9140-1e2b49104914",
  "values": {"com_x_m": {"unit": "m", "value": 0.014943262411347517}, "com_y_m": {"unit": "m", "value": 0.01},
             "com_z_m": {"unit": "m", "value": 0.0034645390070922}, "mass_kg": {"unit": "kg", "value": 0.009136800000000002},
             "stress_mpa": {"unit": "MPa", "value": 41.400000000000006}, "yield_fraction": {"unit": null, "value": 0.15000000000000002}},
  "provenance": {"solver": "deterministic_mech:cantilever_bending+mesh_mass+mesh_com",
   "inputs": {"load": {"value": {"arm_m": 0.025, "force_n": 207.0}, "source": "known"},
              "mesh": {"value": {"triangles": 36}, "source": "known"},
              "section": {"value": {"shape": "rect", "dims_mm": [30.0, 5.0]}, "source": "known"},
              "material": {"value": {"name": "fake-6061", "yield_mpa": 276.0, "density_kg_m3": 2700.0}, "source": "known"},
              "moment_nm": {"value": 5.175000000000001, "source": "derived"},
              "volume_m3": {"value": 3.384000000000001e-06, "source": "derived"},
              "extreme_fibre_mm": {"value": 2.5, "source": "derived"},
              "second_moment_mm4": {"value": 312.5, "source": "derived"}},
   "leaves_out": ["shear and axial stress", "stress concentrations at holes and fillets", "dynamic loads and fatigue",
                  "buckling", "temperature", "section changes along the member",
                  "voids, fasteners and coatings the mesh omits", "non-uniform density",
                  "solids in the mesh that overlap or cross (only that its surface is closed is checked)",
                  "curved faces approximated by flat triangles (the mesh's volume is a little off)"]}}}
```

**Its `verified_by` edge** (the only edge into it):

```json
{"id": "01a1881f-52fb-789f-ad9d-48f973c6a67e", "src_id": "01a1881f-5288-71d4-a781-a449b7720d1f",
 "dst_id": "01a1881f-52f9-7c21-af79-fdb2610960d9", "relation_type": "verified_by", "origin": "system",
 "confidence": 1.0, "domain_pair": "mechanical<->simulation",
 "attrs": {"evidence": [{"ref": "01a1881f-52f9-7c21-af79-fdb2610960d9", "kind": "sim",
                         "detail": "deterministic_mech:cantilever_bending+mesh_mass+mesh_com"}],
           "created_by": "01a1881f-506f-7d1c-9140-1e2b49104914"}}
```

(`EvidenceKind.SIM == "sim"`, `RelationType.VERIFIED_BY == "verified_by"`, solus_contracts.)

**`attrs.expected` on the bracket**: (a) (version 1 → 2): every quantity `{value, unit,
sim_result_id: "01a1881f-52f9-…"}`, e.g. `"yield_fraction": {"unit": null, "value":
0.15000000000000002, "sim_result_id": "01a1881f-52f9-7c21-af79-fdb2610960d9"}`. (b) after both runs
(version 3): `stress_mpa`, `yield_fraction` and `interference_mm` name the rung-3 result
`01a18820-8906-…`; `mass_kg` and the centre keep the rung-1 `01a1881f-532b-…` (the writer merges,
per quantity).

**graph.changed after the write, and the envelope cache** (inline; the fan-out runs in this process):

| t | what |
| --- | --- |
| 0.970 | `simulate.record_sim_result` (a) entered |
| 0.984 | log `sim result recorded project=01a18828-0ef5-77c3-8b4e-15aa1928c3a1 subject=01a18828-10c0-7faf-b013-57f35d6ee196 rung=1 sim_result=01a18828-111c-7996-a157-bbe286f157c3` (after the commit) |
| 0.984 | graph.changed published through the app's hub `{entities_created 1, entities_updated 1, entities_deleted 0, relations_created 1, relations_deleted 0}`, `at 2026-10-29T14:54:49.638565+00:00`; fan-out 0.984 → 0.987; `EnvelopeCache.invalidate` 0.985 → 0.987 (index empty: nothing cached yet) |
| ~1.0 | (a)'s `yield_fraction` envelope built from the rows and put in `app.state.envelope_cache` under `solus:envelope:01a18828-0ef5-77c3-8b4e-15aa1928c3a1:01a18828-10c0-7faf-b013-57f35d6ee196:yield_fraction:-:-:-` (as the window evaluator puts one); read back: cached `true`, index = that key |
| 1.019 | (b)'s record: graph.changed `{1, 1, 0, 1, 0}`; `EnvelopeCache.invalidate` 1.020 → 1.022: index before `[<the key above>]`, after `[]` |
| after | `cache.get(key)` → `None`, index `[]`; rebuilt from the rows: the same envelope |
| 6.057 | the fan-out's budgets trigger: `budgets project=01a18828-0ef5-… mass=unknown cost=unknown` |
| 11.214 | the fan-out's matrix trigger: `matrix run project=01a18828-0ef5-… rules=37 annotated=0 skipped=0 raised=0 infos=36 resolved=0 motifs=0 notes=0 truncated=False proposals=1` |

No log line marks a successful invalidation: `GraphChangedFanout` and `EnvelopeCache.invalidate`
log only failures ("graph.changed callback … failed", "envelope cache invalidation failed …"), and
there were 0 of those (deviation 9). Every recorded run in the inline leg published through the
app's own hub (`hub_is_app_hub: true` on all 8 records).

**P2-T1's envelope** (`load_envelope_inputs` + `build_envelope`, arq-approve):

```json
{"part_id": "01a1881f-5288-71d4-a781-a449b7720d1f", "quantity": "yield_fraction", "unit": null,
 "nominal": {"lo": 0.15000000000000002, "hi": 0.15000000000000002}, "warn": null, "limit": null,
 "expected_hz": null, "bounds_source": {"nominal": "sim"}, "confidence": 0.8}
```

and `stress_mpa`: `unit "MPa"`, `nominal {lo 41.400000000000006, hi 41.400000000000006}`,
`bounds_source {"nominal": "sim"}`, confidence 0.8. For (b): nominal 0.8500000000000002 and
234.60000000000005 (the rung-3 values), `bounds_source {"nominal": "sim"}`.

**P3-T1's `FactStore.expected`** (over the part's one-hop neighbourhood): (a) `yield_fraction`
`ExpectedValue(value 0.15000000000000002, unit None, sim_result_id "01a1881f-52f9-…")`, `stress_mpa`
`(41.400000000000006, "MPa", "01a1881f-52f9-…")`; (b) `(0.8500000000000002, None, "01a18820-8906-…")`;
`FactStore.simulation.band("yield_fraction")` 0.8.

**`run_matrix(dry_run=True)`** (arq-approve, 0 `run()`, 0 `can_answer`, proposals `[]`):
`bracket_strength_at_joint` → (a) `pass` (rung 1, sim_result `01a1881f-52f9-…`), (b) and the leaf
`inconclusive` at rung 3 ("…unresolved: no higher rung computes it", sim_results `01a18820-8906-…`,
`01a18820-88d9-…`). Inline dry run (0.011 s, 0 `run()`, 1 `can_answer`): (a) `pass`, (b)
`inconclusive` at rung 1 "…which a higher rung settles", one proposal (b, rung 3,
`mesh_interference`, `available false`, `decision run`).

## Item 5: the rung-3 jobs against real binaries

- **ngspice**: not on PATH; `settings.ngspice_bin` None in every process, so `spice_transient`
  reports "not available on this machine". Not run.
- **MuJoCo**: importable (`importlib.util.find_spec("mujoco")`), but `run_mujoco_sim` needs the
  scene model as MJCF text and the fake arm has none (`tests/fixtures/fake_arm.py` seeds no
  `bench_scene_model`; no fake-arm MJCF exists in the repo). So it was not run live and no
  derived-current provenance is pasted. The scripted proof, `tests/test_mujoco_job.py` (23
  functions), ran in the proxy slice with no skip, so its engine test
  (`test_derived_current_marked_derived_or_skips_without_mujoco`) ran against MuJoCo in its child.
- **`kicad.export_spice_netlist`**: no `kicad-cli` here; proven by its fork tests only,
  `integrations/mcp/kicad/tests/test_spice_export.py` (7 functions), not run in this session.

## The twin compare (R117)

Project P `01a18828-3f78-7178-a46a-d271c5a40063` (the inline person's): robot
`01a18828-3faf-7852-8ac7-d535c3aa207a`; the shoulder made through `POST
/hardware/robots/{robot}/parts {name shoulder, category actuators}` (201) →
`01a18828-3fc4-7cbe-80ec-85b708a938b1`; the scene model `01a18828-403e-7ba6-9ce5-6aeaccd2df6f`
binding joint `shoulder` to it (seeded as `_shoulder` does); the rung-3 trajectory `sim_result`
`01a18828-4043-706f-bd28-e6be876792fd` of the robot, recorded through `record_sim_result` as
`_routine_sim` does (no provider call).

- The stalled run (`_stalled_run`'s manifest: shoulder held at 0 deg at 2.5 A against a 2 A rating
  while 90 deg is commanded, 10 packets from 2026-10-29T00:00:00Z) was uploaded through `POST
  /artifacts` (201, `artifact_id 01a18828-4059-7566-b20f-f046873717b5`, 2490 bytes) and imported
  through `POST /bench/runs/import {robot_id, artifact_id, name "Shoulder routine (stalled)",
  origin recorded}` → 201 run `50075a8c-2cb1-42f4-ae7b-63fc68cff021`, `packet_count 10`.
- `POST /api/v1/projects/01a18828-3f78-…/bench/runs/compare {baseline_id: <run>, candidate_id: <run>,
  sim_result_id: 01a18828-4043-…}` → **200**, keys `clamp_attributions, config_changes, divergences,
  evidence, expected_source, finding_deltas, insufficient, source_snapshots_changed`;
  `expected_source "sim"`, `source_snapshots_changed false`. The `evidence` block, verbatim:

```json
{
  "sim_result_id": "01a18828-4043-706f-bd28-e6be876792fd",
  "real_passed": false,
  "sim_passed": true,
  "task_passed": false,
  "sim_control": "electrical_or_mechanical",
  "reason": null,
  "simulation_gap": true,
  "residuals": {
    "01a18828-3fc4-7cbe-80ec-85b708a938b1": {
      "status": "unattributed",
      "parameter": null,
      "explained": {
        "mass": 0.767,
        "limit": 0.997,
        "sensor_offset": 0.749,
        "contact": 0.997
      },
      "estimate": {
        "mass": {
          "tau_s": 2.25
        },
        "limit": {
          "side": "upper",
          "at": 2.647059
        },
        "sensor_offset": {
          "offset": -45.0
        },
        "contact": {
          "at_s": 0.132353
        }
      },
      "residual_rms": 52.012442,
      "samples": 256
    }
  }
}
```

- Without `sim_result_id` → **200**, `expected_source "baseline_run"`, no `evidence`; its canonical
  JSON equals `jsonable_encoder(analysis.compare(stored, stored))` of the run as `store.load` reads it
  (sha256 `c40aad3cfa3b8a3dc7bee22d2850177971227c6b4e4200d377f808dac4453c54` both); its key set is the
  twin response's minus `evidence`.
- `sim_result_id` of project Q (`01a18828-4105-7831-8344-0c70f2183130`, the same person's other
  project) → **404** `{"error": {"code": "not_found", "message": "Simulation result not found",
  "details": []}}`; the shoulder part's id → **404**, the same body.
- Provider `run()` 0, model calls 0 in the whole compare phase.

## The pre-check leg (R99, R116, R118)

**The CAD import card parked on a variant whose bracket rule is `inconclusive`** (arq-park: the CAD
leaf carries `bracket_attrs("b")`; its rung-1 run recorded 0.85 and queued rung 3). Dispatched
`bench.import_cad_scene {robot_id, source_entity_id: <leaf>, expected_revision: r1}` → parked
`01a1881f-539c-7381-bd8e-8af07a84a65a`, 5 rows; the pre-check ran with `room 46`, 0.041 s, 0
`run()`, 1 `can_answer`:

```json
[{"label": "Robot", "before": null, "after": "P4 acceptance robot (arq)"},
 {"label": "CAD source", "before": null, "after": "CAD bracket (85 % of yield)"},
 {"label": "Source revision", "before": null, "after": "r1"},
 {"label": "Geometry", "before": null, "after": "1 measured CAD occurrences. CAD contains no verified motion-joint definitions; this model is static."},
 {"label": "Simulate first", "before": null, "after": "CAD bracket (85 % of yield): yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band. Simulate yield_fraction at rung 3 with mesh_interference first"}]
```

One "Simulate first" row (of at most 8), 161 characters (under 500), naming the quantity and rung 3.

**Approved after a simulation landed in between** (the worker's rung-3 run of the leaf,
`01a18820-88d9-…`, at 14:46:36Z; approval 14:47:54Z through `decide_confirmation` with a registry
rebuilt for the request). The re-preview's pre-check returned `[]` (rung 3: no higher rung), and the
gate's `_diverged`, probed:

```json
{"shown":   [Robot, CAD source, Source revision, Geometry, {"label": "Simulate first", "after": "CAD bracket (85 % of yield): yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band. Simulate yield_fraction at rung 3 with mesh_interference first"}],
 "current": [Robot, CAD source, Source revision, Geometry],
 "diverged": false}
```

(the four shared rows are identical in both, with the `after`s above). Result `ok: true`,
confirmation `approved`, value `{"import_id": "01a18821-bb3c-7fdf-9eed-95e1b287f961", "status":
"pending", "reason": "CAD contains no verified motion-joint definitions; this model is static.",
"job_id": "c9bc9c4e-d2ed-434d-95b7-fc88ad32efc8", "model_id": null}` (the job id is the recording
stand-in's; deviation 3). Inline, the same with the mesh job called in process between park
`01a18828-3c30-…` and approval: status `recorded` (`01a18828-3c43-…`), `diverged: false`, approved,
import `01a18828-3c9b-7d8f-84f6-4ada90c46ca8`.

**A forced pre-check failure leaves the card parked with its other rows** (inline, leaf two,
`bracket_attrs("b")` at rung 1): fault-injected in the harness process (deviation 8):

| Park | Confirmation | Rows | Labels | Logged |
| --- | --- | --- | --- | --- |
| `build_fact_store` raising | `01a18828-3ce1-77f3-abf2-a2f222c18e05` | 4 | Robot, CAD source, Source revision, Geometry | `simulation pre-check skipped project=01a18828-0ef5-…` (`RuntimeError: p4 acceptance: a forced pre-check failure (the fact store)`) |
| `PRECHECK_TIMEOUT_SECONDS` 0.0005 | `01a18828-3d07-75e1-979f-ef18a5f2ee4d` | 4 | the same | the same line (`TimeoutError`) |
| healthy (control) | `01a18828-3d4d-7748-a606-0377ed7bb8eb` | 5 | the same + Simulate first | – |

All three were then rejected. A `touched` id of another project, pre-checked directly
(`precheck_rows` under project P on the inline project's (b)): `[]`, no "skipped" line; the inline
project's own pre-check of (b) gives its line.

**The flash card** (`hardware.flash_presence`, R116; inline): robot
`01a18828-3dd8-77b5-9c86-b37fbf89e331` with a USB-serial config (`PUT …/hardware/robots/{robot}/config`
200) and (b)'s rung-1 result recorded onto it (`01a18828-3e55-…`, as
`test_firmware_presence._near_its_yield` does), so its bracket rule is inconclusive. The presence
provider is an in-process stand-in (it compiles nothing, validates against no device, refuses to
upload); both cards were parked through `request_confirmation` and then rejected.

| Card | Firmware | Own rows | Parked rows | Pre-check `room` | "Simulate first" rows | Confirmation |
| --- | --- | --- | --- | --- | --- | --- |
| small | 38 chars | 5 | 6 | 45 | 1: "P4 acceptance flash robot: yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band. Simulate yield_fraction at rung 3 with mesh_interference first; it needs load, section, material; no job queue runs it here" | `01a18828-3ee2-74f1-8c08-5b65becbdd0c` |
| full | 23,000 chars (46 chunks) | 50 | **50** | **0** | **0** | `01a18828-3f5b-7aab-8f7d-425fbf00c745` (parked, not refused) |

## Ladder single source (Minor 8) and R97

| Leg | Subject | The card's / pre-check's line | `simulate`'s answer on that subject |
| --- | --- | --- | --- |
| arq | CAD leaf | "…Simulate yield_fraction at rung 3 with mesh_interference first" (no suffix: available) | `climb {decision queued, rung 3, provider mesh_interference, job_id run_mesh_sim:…:e035d4674cda}` |
| arq | bracket (b) | "bracket (85 % of yield): yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band. Simulate yield_fraction at rung 3 with mesh_interference first" | `climb {queued, 3, mesh_interference, …:90439291b67d}` |
| arq, after rung 3 | (b), the leaf | `[]` | the bracket rule: "unresolved: no higher rung computes it" |
| inline | bracket (b) | "…first; no job queue runs it here" | `climb {not_available, 3, mesh_interference, "no job queue on this server: rung 3 runs only as its bounded job, never in a SOL request"}` |
| inline | CAD leaf one | "…first; no job queue runs it here" | `climb {not_available, 3, mesh_interference}` |

R97: the runner's proposals stay data on `MatrixReport.proposals`:

- inline in-process matrix job (t 11.028 → 11.227, 0.187 s): `proposals` = one, `{trigger rule,
  subject (b), quantity yield_fraction, rung 3, target mesh_interference, available false, decision
  run, reason "yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band", remember_as
  "simulate yield_fraction with mesh_interference"}`; provider calls during the job: 1
  `ClosedForm.can_answer` (mesh_interference, yield_fraction), **0 `run()`**.
- worker: the first matrix run (queued by the API's fan-out, run concurrently with the mesh jobs; its
  read at +0.113 s preceded their commits at +0.156/+0.176) had `proposals=2` (b and the leaf, rung 3,
  `available true`, `decision run`), 2 `can_answer`, 0 `run()`; the worker's own fan-out re-ran it
  10 s later: `proposals=0`, no provider call ("matrix run … infos=0 resolved=1 … proposals=0").

## Proxy tests (after the live runs)

The guard ran in its own call (no pytest running; no worker running). One process, from
`packages/api`, 14:56:43Z → 14:59:24Z:

```
PYTHONDONTWRITEBYTECODE=1 SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2 uv run --frozen --no-sync pytest -q -rs -p no:cacheprovider tests/test_sim_ladder.py tests/test_sim_facts.py tests/test_deterministic_mech.py tests/test_mesh_interference.py tests/test_spice_deck.py tests/test_ngspice_provider.py tests/test_mujoco_job.py tests/test_simulate.py tests/test_sim_control_wiring.py tests/test_envelopes.py tests/test_matrix_runner.py tests/test_runs_compare_twin.py tests/test_firmware_presence.py tests/test_mesh_job.py tests/test_confirmations.py::test_only_the_effect_rows_can_make_a_card_stale
408 passed in 157.40s (0:02:37)
```

- The dispatch's 11 files hold 171 test functions (sim_ladder 13, sim_facts 6, deterministic_mech
  23, mesh_interference 15, spice_deck 11, ngspice_provider 12, mujoco_job 23, simulate 17,
  sim_control_wiring 9, envelopes 14, matrix_runner 28). Added for the P4-T5 legs (deviation 12):
  runs_compare_twin 3, firmware_presence 7, mesh_job 4, and the R118 gate test (1 function, 3
  cases). Parametrisation expands the 186 functions to 408.
- 0 skipped, 0 failed, 0 errors (`-rs` printed no skip line). No `--cov`; `.coverage` md5 unchanged;
  the tree stayed clean. Log: `acceptance/p4_proxy_pytest.log`.

## Deviations from the brief and observations

1. **`simulate` was called through the registry and gated dispatcher, not a SOL route or turn.** A
   turn needs a model; the tool does not. `build_sol_registry` gets what `deps.get_sol_registry`
   passes that matters here (person, team, systems, the app's hub, `create_sim_enqueue(app)` when
   `jobs_queued`), and each call runs under `bind_scope(resolve_scope(...))`. No `should_simulate`
   shortcut was needed.
2. **The ARQ leg was split in two processes around the worker start** (arq-park before any consumer,
   arq-approve after it ran), so the parked card's simulation landed between park and approval
   deterministically. The approval is a later request with a rebuilt registry, as the decide route
   does.
3. **The CAD import was approved through `decide_confirmation`** (the gate function the decide route
   calls), with the registry's `scene_enqueue` replaced by a recording stand-in. The route's
   `create_scene_enqueue` would queue a sync of the CAD source, a provider call. Each approved import
   (`01a18821-bb3c-…`, `01a18828-3c9b-…`, and one per void attempt) is left `pending` with a
   `job_id` that names no job.
4. **Seeded rows** where only a provider makes them: ONSHAPE `Source` rows (`secret_ref` names no
   secret) and their CAD leaves; the compare scene binding; the routine trajectory result and the
   flash robot's result through `record_sim_result` (the one system writer), as the tests do. Each
   seeded source was set `disconnected` at the end of its leg, so no later worker's sweep takes one
   for a live CAD source.
5. **A finding about the compare helper, not a product defect.** `test_runs_compare_twin._stalled_run`
   files its run through `store.save`; its free-standing shoulder part cannot go through `POST
   /bench/runs/import`, whose reference check holds each part to the robot (404 "Part does not belong
   to this robot", void attempt 1). Made through `POST /hardware/robots/{robot}/parts`, the same
   manifest imports.
6. **Project Q sits in project P's team**: a trial person holds 2 teams (`PLAN_LIMITS` BASIC
   `max_teams 2`; `POST /teams` answered 409 in void attempt 2).
7. **Two void inline attempts**, both harness bugs: 14:49:42Z (deviation 5) and 14:53:04Z (deviation
   6). Kept as `p4_accept_live_inline_VOID*`. Everything before their failure points behaved as the
   final attempt did. Their rows stay in `solus_sol` (left behind); their four seeded sources were
   disconnected by the next attempt.
8. **The forced pre-check failures are fault injections** in the harness process
   (`simulate.build_fact_store` raising; `simulate.PRECHECK_TIMEOUT_SECONDS = 0.0005`), each restored
   after its park. The dispatch's example, a `touched` id of another project, cannot be produced
   through the tools' arguments (the CAD tool derives `touched` from its own validated selection);
   it is shown as a direct `precheck_rows` call instead (`[]`, no error).
9. **No fan-out log line exists for a successful envelope invalidation** (item 4): the modules log
   failures only. The `EnvelopeCache.invalidate` probe and the cache index read before and after are
   the evidence, beside the fan-out's other consumers' own lines (budgets +5 s, matrix +10 s).
10. **One process outside the guards.** The `MissingInputs` print for (c) (`p4_missing_inputs_c.txt`)
    ran without the dotenv guard. Its imports load `toolkb/sharing._ToolkbSettings`, which may open
    the root `.env` for the vote salt (it found none, as its stderr line says). Nothing was printed,
    logged or used from it; that process opened no database or network connection.
11. **The flash cards were parked and rejected, never approved**: nothing was uploaded, and the
    stand-in provider would refuse an upload.
12. **The proxy slice adds four entries** to the dispatch's eleven, for the P4-T5 legs.
13. **The harness's `credit_ledger` usage count used a wrong column** (`kind`; the column is `type`),
    so it reads "unreadable" in the JSONs; counted afterwards with psql: 0 `usage` rows since 14:44Z.
14. **`tests/test_apply_sim_change.py` is not in the proxy slice** (it was green in P4-T5's covering
    slices; the dispatch names it as the proof for the third tool).
15. **Observations, harmless.**
    - The bracket's three bodies (plate and two pegs) touch: 0 edge-face tests, 0 probes,
      `interference_mm` 0.0, so `interference_through_range` passes.
    - At rung 3 `bracket_strength_at_joint` stays `inconclusive` ("unresolved: no higher rung computes
      it"): no shipped target computes `yield_fraction` above rung 3.
    - The robot's flash line ends "it needs load, section, material": the replayed result sits on a
      robot that states no bracket facts, so the ladder's decision is `ask`.
    - The worker's first matrix run raised 36 standing infos on the arq robot; the second resolved
      one (`interference_through_range`'s unknown, once `interference_mm` existed).

## Not verified here

- **Rung 3 against real binaries** (item 5): ngspice and `kicad-cli` are absent; MuJoCo is present
  but there is no fake-arm MJCF scene model, so `run_mujoco_sim` did not run live.
- **`apply_sim_change` live** (needs a SOL turn's card): its tests are the proof.
- **The decide route and the real scene enqueue**: the approval ran through `decide_confirmation`
  directly (deviation 3); the CAD import's queued sync and tessellation did not run.
- **A Sim-mode bench capture as a twin, and the Runs view's compare affordance**: deferred (M152,
  M153); the twin here is built from a `sim_result` through the route's `sim_result_id`.

## Left behind

- **In `solus_sol`**:
  - before the run: 11 users, 13 projects, 13 `credit_ledger`, 120 findings, 0 `sim_result`s, 661
    entities, 916 edges, 11 sources, 14 jobs, 0 artifacts, 0 `tool_confirmations`;
  - after: **15 users, 21 projects, 17 `credit_ledger` (4 new, all `trial_grant`), 268 findings, 27
    `sim_result`s, 1159 entities, 1404 edges, 18 sources (7 seeded, all `disconnected`), 14 jobs, 17
    artifacts, 19 `tool_confirmations` (0 pending)**;
  - the legs' projects: arq `01a1881f-509c-…`; inline `01a18828-0ef5-…`, P `01a18828-3f78-…`, Q
    `01a18828-40b6-…`; void attempt 1 `01a18823-68c8-…` and `01a18823-99ee-…`; void attempt 2
    `01a18826-7b8b-…` and `01a18826-ad03-…`;
  - three pending CAD imports naming no job (deviation 3) and one per void attempt;
  - the 17 artifact rows' blobs lived in the harnesses' temporary artifact roots, removed at exit, so
    those rows point at nothing; the worker's `sweep_artifacts` will take them after their 1 h TTL.
- **Not touched**: `solus`, `solus_sol_p1`, every `solus_test_*` except `solus_test_d7fa72c2` (the
  proxy run truncates it as designed).
- **Redis 6390**: dbsize 0 after the worker stopped (arq's cron progress markers expired on their
  own); now 3 keys, `solus:upload-budget:bytes:498134:<team>` from the three compare uploads, each
  with its own expiry (1.8–1.9 h left at 14:59Z). `solus-redis-1` was never touched.
- **Processes**: exactly one worker consumer ran (pid 353971, uv 353890), stopped by its own pid with
  rc 0. The MONITOR capture ended on its own timeout. Nothing else was started, stopped or killed.
- **Files** (git-ignored plan workspace): `acceptance/p4_accept_live.py`, `p4_worker.py`,
  `p4_accept_live_{arq-park,arq-approve,inline}_result.json` with `.stdout`/`.stderr`/`.time`, the two
  `p4_accept_live_inline_VOID*` sets, `p4_worker_arq.log`, `p4_worker_events_arq.jsonl`,
  `p4_worker_result_arq.json`, `p4_worker_arq.{uvpid,started,stopped}`, `p4_redis_monitor_arq.log`,
  `p4_missing_inputs_c.txt`, `p4_proxy_pytest.{log,time}`; `reports/`: this report. No tracked file
  changed.
