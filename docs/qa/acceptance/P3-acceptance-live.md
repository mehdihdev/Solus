# P3 acceptance, live proof (SOLUSDEV-321 plan §3 "P3 acceptance", items 1–5, ruling R66): in process, both sync modes, ONE ARQ worker, copy of the dev DB

`t` below is seconds after the leg's harness was built (each leg has its own zero, about 1 s after
its process started). Worker events are placed on the same clock by wall time. Three legs ran: the
**inline** leg (`sync_inline=True`, items 1–5), the **ARQ** leg (`sync_inline=False` with the ONE
worker consumer, items 1, 3, 4) and a **supplementary ARQ** leg in which the worker itself runs the
syncs (item 4's worker-side enqueue; deviation 2).

## Verdicts

- **1. Goal sketch → `commanded_range_vs_joint_limit` fails on the `commands` edge, with status and
  time on the edge (seeded path, R66): ✅ in all three legs.**
  - The real `firmware_edges.infer`, over the five accepted review rows of `bus_sketch_goal.ino`,
    wrote ONE `commands` edge from the sketch's code entity to servo 3: confidence 0.8, origin
    `inferred`, `commanded = {min 200, max 200, unit deg, min_ref = max_ref = "bus_sketch_goal.ino:13"}`
    (infer: created 1, updated 1, skipped 0).
  - The first matrix run after the first sync wrote its `checker_results`. Read through
    `GET /entities/{sketch}/relations?direction=out&type=commands` (200), the item is
    `{rule_id commanded_range_vs_joint_limit, status fail, severity warning, message "the code commands 200 deg at bus_sketch_goal.ino:13, past the part's -150 to 150 deg position limit (from its config)", at 2026-10-28T14:40:41.955595Z}`.
    In the ARQ leg the worker wrote the same item, at 14:48:47.406490Z. The `at` did not move on
    the two later runs (m1).
  - The EdgePanel renders it as `commanded_range_vs_joint_limit · failed · warning`, then the
    message, then `2026-10-28 14:40 UTC` (`EdgePanel.test.tsx`: 6 passed).
  - There is one checker finding (warning, `software->mechanical`, subjects [sketch code, servo 3]).
  - **The companion-scan form (a local-folder sync of `bus_sketch_goal.ino`) is UNVERIFIED (M104).**
- **2. Divider fixture → `attrs.motifs` carries `divider_adc`, and `sample_rate_vs_adc_settling`
  fails above 5·RC: ✅.**
  - `divider_adc` (confidence 0.9) sits on R1, R2, C1, U1 and net `/VSENSE`. `decoupling_at_pin`
    (0.9) sits on C2, U1, `+3V3` and `GND`, so 8 holders were written.
  - At 100 Hz the rule fails: R1‖R2 = 50 kΩ, C1 = 100 nF, τ = 5 ms, so 5τ = **25 ms > the 10 ms**
    sample period. The fail is on the `reads` edge's `checker_results` (warning) and is raised as a
    checker finding.
  - The 10 Hz control passes (25 ms < 100 ms) and raises no finding.
  - **`proximity_pair` answers `unknown_input(pcb_positions)`: the fixture is a netlist only, with
    no `.kicad_pcb`, so it carries no positions, and 2b cannot be reached from it.**
- **3. A rule with no fact → exactly one standing info per (rule, entity), naming the field and
  `set_in`; a new signal bumps `count` with no new node; an unchanged signal bumps nothing; six
  `COMMANDED` items: ✅ in all three legs.**
  - There are 36 standing infos after the first sync, at most **1** per (rule, first subject).
    35 sit on the robot and 1 on `fw/fake_arm.ino`. All 36 headlines name the field and
    `set in <set_in>`, and `evidence.missing` = `[{name, set_in}]`.
  - The second sync moved the signal from `…14:40:31.902152` to `…14:40:42.898330`. The same **36
    ids** came back, with count 1 → **2** and version 1 → 2, and the run raised 36 infos.
  - The robot's rename (no sync, so the signal was unchanged) left count at **2** and version at 2.
    The run raised **0** infos (M110).
  - Each of the fake arm's six goal-less `commands` edges carries exactly **one** item, an
    `unknown_input` naming `commanded`. They fold into one info on `fw/fake_arm.ino` with
    `evidence.edges = 6`.
- **4. The budget trigger fires through the fan-out after a sync in both modes; both jobs
  re-enqueue under their stable ids (`keep_result=0`); the budgets CONFIG `config_version` bumps:
  ✅.** Read deviation 1 for where an ARQ-mode KiCad sync runs.
  - **Inline.** - 3 `graph.changed` events (sync 1, sync 2, the rename) gave 3 fan-out calls. - In process (enqueue=None) that ran `recompute_budgets` ×3 (+5.26–5.40 s after each change)
    and `run_matrix_checkers` ×3 (+10.09–10.43 s). - The CONFIG went none → **v1** after sync 1 → **v2** after sync 2 (`0 of 12` → `0 of 13 parts
massed`) → v2 after the rename (no budget value moved).
  - **ARQ** (worker pid 3709285).
    - The KiCad sync stays in the API process by design, so the API's fan-out enqueued
      `recompute_budgets:01a182fc-02ac-7a1c-adc7-aa40650ef547` and
      `run_matrix_checkers:01a182fc-02ac-7a1c-adc7-aa40650ef547` **3× each**, and all 6 were
      accepted.
    - The worker ran all 6 (`→`/`←` lines below). The CONFIG went v1 → v2 → v2.
  - **Supplementary ARQ** (worker pid 3749776).
    - The worker ran both syncs and published `graph.changed` itself. **Its own** fan-out
      (`connectors/worker.py:1233-1234`) enqueued both stable ids after each sync, 4 accepted.
    - The API enqueued them after the rename, 2 more accepted. The CONFIG went v1 → v2 → v2.
  - **`keep_result=0`.**
    - The registered functions have `keep_result_s` 0 for both jobs (timeouts 300 / 120, 1 try).
    - Redis MONITOR saw 23 + 15 `EXISTS arq:job:<id> arq:result:<id>` checks and **0** result-key
      writes. Completion is `DEL arq:in-progress:<id> arq:retry:<id> arq:job:<id>`.
    - No `arq:result:*` key was left after any leg.
- **5. SOL's `run_checkers` answers from a dry run and persists nothing; `/code-environment`
  still reports `python_pin_conflict`: ✅.**
  - On the arm project, anchored on [sketch code, servo 3], it returned the
    `commanded_range_vs_joint_limit` warning in 0.048 s.
  - On the linked folder, anchored on its 4 requirements, it returned `package_version_conflict`
    (critical, torch `==2.3.0` vs `==2.1.0`).
  - In both, the findings count and digest were identical before and after (37/37 and 1/1), and so
    were the `checker_results` (7 edges / 7 items, and 0). No matrix run and no trigger timer
    happened during either call.
  - `GET /code-environment` gave 200 with `conflicts = [python_pin_conflict, critical, torch]`,
    `requirements.count 4`, `split true`.

`MatrixReport` per run. Every run had 37 rules, truncated False, edges_skipped 0 and motifs_skipped 0:

| Run                                 | read entities / edges | results (status)   | annotated | fails raised | infos raised | resolved | motifs written | notes | run_matrix s          |
| ----------------------------------- | --------------------- | ------------------ | --------- | ------------ | ------------ | -------- | -------------- | ----- | --------------------- |
| arm, sync 1 (inline / ARQ / suppl.) | 56 / 40               | unknown 41, fail 1 | 7         | 1            | 36           | 0        | 8              | 0     | 0.209 / 0.229 / 0.237 |
| arm, sync 2                         | 57 / 47               | unknown 41, fail 1 | 0         | 1            | 36           | 0        | 9              | 0     | 0.201 / 0.234 / 0.149 |
| arm, rename (no sync)               | 57 / 47               | unknown 41, fail 1 | 0         | 1            | **0**        | 0        | 0              | 0     | 0.045 / 0.069 / 0.032 |
| divider 100 Hz (inline)             | 11 / 14               | unknown 36, fail 1 | 1         | 1            | 0            | 0        | 8              | 36    | 0.044                 |
| divider 10 Hz (inline)              | 11 / 14               | unknown 36, pass 1 | 1         | 0            | 0            | 0        | 8              | 36    | 0.029                 |
| linked folder (inline)              | 29 / 0                | unknown 36, fail 1 | 0         | 1            | 0            | 0        | 0              | 36    | 0.031                 |

Ready to paste into the SDD ledger:

> P3 acceptance (live, in process, DB copy `solus_sol` at a32000000006, Redis `solus-redis-321`, no
> provider: refusing SOL adapters 0 reaches, scripted narrator 0 calls, 0 `model call start` lines,
> egress loopback-only in the harness and the worker, every `.env` read refused). Item 1 (seeded,
> R66): `firmware_edges.infer` → `commands` sketch→servo 3 @0.8 with commanded {200,200,deg,
> bus_sketch_goal.ino:13} → first matrix run → edge item `fail/warning`, "the code commands 200 deg
> at bus_sketch_goal.ino:13, past the part's -150 to 150 deg position limit (from its config)",
> at 14:40:41.955595Z (inline) / 14:48:47.406490Z (worker), plus 1 checker finding; companion-scan
> form UNVERIFIED (M104). Item 2: `divider_adc` on R1/R2/C1/U1/`/VSENSE`; 100 Hz fails (5τ 25 ms >
> 10 ms), 10 Hz passes; `proximity_pair` unknown (no positions in the fixture). Item 3: 36 standing
> infos, max 1 per (rule, entity); second sync count 1→2 same 36 ids (infos_raised 36); rename count
> stays 2 (infos_raised 0); six COMMANDED items, one info edges=6. Item 4: inline fan-out 3× → both
> jobs in process 3×; ARQ: API enqueues `recompute_budgets:<p>` / `run_matrix_checkers:<p>` 3× each,
> all accepted, worker pid 3709285 ran 6 (KiCad syncs are API-side by design,
> routers/sources.py:604-605); supplementary: the worker's own fan-out enqueued both ids after each
> of its 2 syncs, all accepted, worker pid 3749776; budgets CONFIG none→v1→v2→v2 in every leg; 0
> result keys. Item 5: dry-run `run_checkers` → commanded_range warning / package_version_conflict
> critical, findings+checker_results digests unchanged; `/code-environment` → python_pin_conflict.
> MatrixReport (arm): 56/40 read, annotated 7, raised 1, infos 36, motifs 8, 0.21–0.24 s; then
> 57/47, 0, 1, 36, 9; then 57/47, 0, 1, 0, 0. Proxies: 135 passed in 97.96s (API, one process); 6
> passed (EdgePanel). Report: `docs/qa/acceptance/P3-acceptance-live.md.

## Run identity

| Item                 | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Run time             | **Inline:** command 14:40:29Z → 14:41:16Z, harness 14:40:30.849Z → 14:41:15.664Z, exit 0. **ARQ:** command 14:48:34Z → 14:49:10Z, harness 14:48:35.854Z → 14:49:10.242Z, exit 0. **Supplementary ARQ:** command 15:06:00Z → 15:06:37Z, harness 15:06:01.499Z → 15:06:36.506Z, exit 0. A first inline attempt (14:36:13Z → 14:37:00Z) is void (deviation 4).                                                                                                                                           |
| Branch               | `SOLUSDEV-321-sol-checker-algorithm`                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| HEAD at run time     | `b357a009` before and after every leg. `git status --short` was empty throughout, and `.coverage` md5 was `7571ebfd2af623167baf221f5af68076` before and after every leg and the proxies.                                                                                                                                                                                                                                                                                                              |
| Database             | `solus_sol`, asserted from the server side by every leg (`select current_database()` = `solus_sol`).                                                                                                                                                                                                                                                                                                                                                                                                  |
| Alembic revision     | `alembic current` gave `a32000000006 (head) (mergepoint)` and `alembic heads` gave `a32000000006 (head)`. Nothing was applied. Each leg read `alembic_version` = `a32000000006`.                                                                                                                                                                                                                                                                                                                      |
| Redis                | `redis://127.0.0.1:6390/0`, this branch's `solus-redis-321`. `docker exec solus-redis-321 redis-cli ping` returned `PONG`. `lsof -i :6390` listed 0 lines before each worker start. `dbsize` was 0 before the ARQ leg and 0 after each worker stopped. `solus-redis-1` was not touched.                                                                                                                                                                                                               |
| ARQ-leg worker       | Python pid **3709285** (the consumer), parent uv pid 3709201. Started 14:48:12Z; "Starting worker for 16 functions" and ready at 14:48:13Z. `kill -TERM 3709285` at 14:51:05Z: "shutdown on SIGTERM ◆ 23 jobs complete ◆ 0 failed ◆ 0 retries ◆ 0 ongoing to cancel", exit rc 0 at 14:51:05Z. Both pids were gone 1 s later.                                                                                                                                                                          |
| Supplementary worker | Python pid **3749776**, parent uv 3749689. Started 15:05:45Z, ready 15:05:46Z. `kill -TERM 3749776` at 15:06:46Z: "15 jobs complete ◆ 0 failed ◆ 0 retries", exit rc 0 at 15:06:47Z. Both pids gone.                                                                                                                                                                                                                                                                                                  |
| Harness              | `/home/beeboss/Solus/.superpowers/sdd/pasted-content-id-24a5-sol-precious-pillow/acceptance/p3_accept_live.py`, legs `inline`, `arq` and `arq-worker-sync`. Raw evidence is beside it: `p3_accept_live_<leg>_result.json`, every log line, probe record, snapshot and egress attempt.                                                                                                                                                                                                                 |
| Worker wrapper       | `…/acceptance/p3_worker.py` (deviation 1). Its evidence: `p3_worker_<leg>.log` (arq's own output), `p3_worker_events_<leg>.jsonl`, `p3_worker_result_<leg>.json`.                                                                                                                                                                                                                                                                                                                                     |
| Commands             | Harness: `cd /home/beeboss/Solus/packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' uv run --frozen --no-sync python <harness> inline\|arq\|arq-worker-sync`. Worker: the same two variables, `uv run --frozen --no-sync python <wrapper>`, started in the background with its uv pid written to a file. MONITOR: `docker exec solus-redis-321 timeout <300–420> redis-cli monitor`. |

## Environment recipe as executed

1. **Database.**
   - `solus_sol` already existed; nothing was created, dumped or migrated.
   - At the start it held 3 users, 3 projects, 9 `credit_ledger` rows, 6 findings, 217 entities, 270
     edges, 1 source (an Onshape source with no pending webhook generation) and 4 jobs: P2's leave-behind.
   - Before starting a worker I checked every table its crons drain (`artifacts`, `cad_purge_requests`,
     `stripe_cancel_requests`, `github_webhook_deliveries`, `pending_credit_debits`). All were 0.
2. **Environment.**
   - The two variables were exported per process, on the command line only; the interactive shell
     held 0 `SOLUS_*` names.
   - Both scripts refuse to start unless the process holds exactly the two prescribed variables.
   - The harness re-checks the `SOLUS_*` set after its imports (deviation 5: the tests' `conftest`
     would strip them).
   - `SOLUS_TEST_DATABASE_URL` was set only on the proxy pytest command line.
3. **Settings, in code.**
   - The harness built `Settings(_env_file=None, supabase_jwt_secret=<secrets.token_urlsafe(32) per
run>, supabase_jwt_audience="authenticated", rate_limit_per_minute=100_000,
write_rate_limit_per_minute=100_000, sync_inline=<True inline, False otherwise>,
fingerprint_embedding_enabled=False, artifact_local_root=<TemporaryDirectory>)`.
   - `database_url` and `redis_url` were asserted equal to the two exports.
   - The worker's `Settings` is a subclass that fills the same values, with `sync_inline=False`
     (deviation 1).
4. **App.**
   - `create_app(settings, create_async_engine(solus_sol))`, then
     `hardware_connections.owner = RuntimeOwner(<tmp>, <tmp>)`, as in P2.
   - The fan-out is installed exactly as `main.py`'s lifespan does:
     `GraphChangedFanout(graph_changed_callbacks(sessionmaker=…, enqueue=main._enqueue_budgets_job(app)
if redis_url and not sync_inline else None, store=integration_store, envelopes=envelope_cache))`.
     The callbacks are BudgetTrigger, ProjectCardCache.invalidate, EnvelopeCache.invalidate and
     BudgetTrigger.
   - The lifespan itself was not run, as in P2. In the ARQ legs, `app.state.arq_pool` was created up
     front with the same `create_pool(RedisSettings.from_dsn(…))` that `routers/sources._arq_pool`
     makes, so its enqueues could be recorded.
5. **Probes, recording only.** Each is a wrapper that calls the original, and its recording is
   best-effort and never raises (deviation 4):
   - `LiveHub.publish_to` (`graph.changed` frames) and `GraphChangedFanout.__call__`;
   - the inline jobs `budgets.recompute_budgets` and `checker_trigger.run_matrix_checkers`;
   - `checker_trigger.run_matrix` (the `MatrixReport`, every rule's results and the run time) and
     `matrix_runner._project_graph` (the read's entities, edges and truncated);
   - `budgets.store_budgets` (config_version and lines);
   - `routers.sources.execute_source_sync`;
   - the harness pool's `enqueue_job`; in the worker, `ArqRedis.enqueue_job`,
     `connectors.worker.execute_source_sync` and the same matrix, budget and fan-out probes;
   - one root handler at INFO in each process (sqlalchemy, asyncio and httpcore raised to WARNING).
6. **Order of steps.**
   - The inline leg ran with no worker.
   - For the ARQ leg: MONITOR, then the worker (wait for ready), then the pytest guard, then the
     harness, then SIGTERM to the worker pid.
   - The API proxies ran with no worker, then the desktop proxy.
   - The supplementary leg ran in the next cron-free window, following the same sequence.
   - Each worker window avoided HH:00, :05, :15, :30 and :45, the marks of its hourly and quarter-hour
     crons (`scheduled_change_detection`, `reconcile_stripe_subscriptions`, `expire_comps`). The
     every-minute crons ran 17 + 15 times; every one returned 0.

## Why no real provider was reachable (five independent layers)

1. **The Narrator's `complete` is scripted (M88) AND no bench session started.**
   - In every leg, `functools.partial(solus_api.orchestration.gateway.complete, adapters=['anthropic', 'google', 'openai'])`
     points every catalog provider at a scripted adapter. It was reached **0** times.
   - At shutdown the SessionManager held `_active` 0, `_ended` 0 and `_starting` 0, in all legs.
2. **Refusing adapters on `app.state.agent_runner`** (all three providers): reached **0** times.
   P3 makes no SOL turn. `label_motifs` and `extract_rulebook` were NOT exercised live: they need a
   turn with a model. The item 5 registry, built without a user or a secret store, lists neither.
   Their scripted tests ran in the proxy process (9 + 4 test functions).
3. **No credentials in either process.**
   - `secrets_key` unset, `aws_region` None, `supabase_url` None, `sentry_dsn` unset.
   - The secret store is `InMemorySecretStore`: asserted in the harness, observed in the worker.
   - `fingerprint_embedding_enabled` is False. The JWT secret is generated per run, and no key was
     seeded, read or printed.
4. **No `.env` read (new since P2).** Before any Solus import, pydantic-settings'
   `DotEnvSettingsSource._read_env_files` was wrapped to record the request and return `{}`.
   - **Refused reads:** harness 1 per leg, all `/home/beeboss/Solus/.env` from
     `toolkb/sharing._ToolkbSettings` at import (t ≈ −0.17). Worker 0.
   - The worker's settings never consult a file.
5. **Egress, bind and spawn guard in the harness AND the worker.**
   - Only `127.0.0.1`/`::1` on 5432 and 6390 may connect, and only loopback names may resolve. Every
     attempt is listed in the raw JSON. Both event loops were `asyncio.unix_events._UnixSelectorEventLoop`.
   - **Inline harness:** 5 attempts, 4 allowed (`resolve localhost:5432`, `connect 127.0.0.1:5432`,
     `connect 127.0.0.1:6390` ×2).
   - **ARQ harness:** 6 attempts, 5 allowed. **Supplementary harness:** 5 attempts, 4 allowed.
   - **Workers:** 13 and 12 attempts. Every allowed attempt was loopback 5432 or 6390.
   - **Denied: exactly one per process, `bind ('::1', 0)`.** It is urllib3's import-time IPv6
     probe (`urllib3/util/connection.py:137 HAS_IPV6 = _has_ipv6("::1")` → `:127 sock.bind((host, 0))`),
     which catches the error and sets `HAS_IPV6 = False`.
     - It fired during the harness's imports (t ≈ −0.62).
     - In each worker it fired inside the first `recompute_budgets` run (t = 6.628, between that
       job's → at 6.465 and ← at 6.718), when the budgets cost line's lazy
       `solus_api.widgets.bom.service` import first loads urllib3.
     - It was attributed in an import-only process (no DB, no Redis), which printed that stack.
     - It is not egress, and no port was bound.
   - **Spawns 0, listens 0, everywhere.**

| Count                        | Inline | ARQ (harness / worker) | Supplementary (harness / worker) |
| ---------------------------- | ------ | ---------------------- | -------------------------------- |
| Scripted narration calls     | **0**  | 0 / –                  | 0 / –                            |
| Refusing-adapter reaches     | **0**  | 0 / –                  | 0 / –                            |
| `model call start` lines     | **0**  | 0 / 0                  | 0 / 0                            |
| `credit_ledger` `usage` rows | 0      | 0                      | 0                                |
| `.env` reads refused         | 1      | 1 / 0                  | 1 / 0                            |
| ERROR log lines              | 0      | 0 / 0                  | 0 / 0                            |

The only new `credit_ledger` rows are one `trial_grant` per leg user, from `/users/me` provisioning:
9 → 13 rows over the whole run, including the void attempt.

## Seed (fresh per leg, nothing reused)

Every leg minted a token as `tests/conftest.py::make_token` does. `/users/me` provisioned the user,
and `POST /api/v1/teams` plus `POST /api/v1/teams/{id}/projects` made its team and project.

The fake arm came from `fixtures/fake_arm.py::seed_fake_arm(db, project, user_id=None)`: 6 manual
`commands` edges from `fw/fake_arm.ino` with no goal, and a bus map of addresses 1–6 → parts 1–6
with ±150 deg limits from config.

The R66 seeded path follows. The helpers are copies of `test_inference_firmware_edges.py::seed_code_file`
and `test_firmware_edges.py::_accept`; those test modules themselves import `conftest`, which strips
`SOLUS_*` at import (deviation 5).

- A `code_file` named `bus_sketch_goal.ino` with `attrs.path = "bus_sketch_goal.ino"`.
- `extract_firmware_bytes(<the fixture>, suffix=".ino", source_ref="bus_sketch_goal.ino")` →
  `firmware_topology(...)` produced 5 rows. Each was accepted as
  `TopologyAcceptanceService.confirm` stores one: a `hardware_evidence_for` edge brain → evidence
  node, `managed_by hardware_extraction_evidence_v1`, `attrs.row` = the row. The rows:
  - `bus_begin` `Wire` at `:9`;
  - `analog_read` `A0` at `:15`;
  - **`goal_call` `setGoalPositionDeg`, address 3, `value 200.0`, at `bus_sketch_goal.ino:13`**;
  - `goal_call` `setGoalPositionDeg`, address 3, value null, at `:16`;
  - `library_include` `Wire.h` at `:4`.
- The real `firmware_edges.infer(db, project)`: created 1, updated 1, skipped 0, candidates 0.
- A KiCad source through `POST /sources` `{type: kicad, config: {export: kicad_divider_adc.net}}`:
  201, `connected` on creation (auth NONE). The second sync's netlist is the same plus C3 (10 µF on
  +3V3/GND), parsed with no errors before use, and was set through `PATCH /sources/{id}` (200).

| Leg           | User / team / project                                                                                                 | Fake arm robot · code file                                                                                                       | Sketch code · its `commands` edge                                               | KiCad source                           | Sync jobs                            | Budgets CONFIG                         |
| ------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------ | -------------------------------------- |
| inline        | `01a182f4-9bc0-7f27-a56d-f97de409123e` / `…-9beb-7943-926e-65f223b51d4e` / **`01a182f4-9bfe-759b-8379-7d48bd6b9b80`** | `e13a8c38-e702-4e52-ab00-43affca1463b` · `e32bd280-f790-484f-b5b6-8f7822a97f14` (servo 3 `622d2cb9-8d20-4626-8695-336e0d10a5c4`) | `01a182f4-9d84-7dee-b523-39aefd1fe220` · `01a182f4-9da1-7526-909f-40dd50ba6322` | `01a182f4-9dc5-7182-a0bd-42836ae4ceb1` | `01a182f4-9e12-…`, `01a182f4-c920-…` | `01a182f4-b247-725e-9b95-a0d64000fa23` |
| ARQ           | `01a182fc-0265-…` / `01a182fc-0296-…` / **`01a182fc-02ac-7a1c-adc7-aa40650ef547`**                                    | `14c3655a-a9a0-418c-a3c5-ad5c7ab7d375` · `2da7d3a1-28c5-4bee-9740-5e11a83bb29c`                                                  | `01a182fc-043e-7e76-8256-b650da72c96e` · `01a182fc-045f-774a-abc1-2e265d004c63` | `01a182fc-0484-7c65-b465-52d1dcbb02df` | `01a182fc-04cb-…`, `01a182fc-316c-…` | `01a182fc-1b3a-7e0a-8856-33942237f783` |
| supplementary | `01a1830b-f6e8-…` / `01a1830b-f716-…` / **`01a1830b-f725-7e03-a233-f2645abee940`**                                    | `668f71aa-ecff-4095-b0d0-df4bc204b5a8` · `e1d1d212-3d53-4efb-aa95-8a0f425fb550`                                                  | `01a1830b-f8d8-77b6-8706-f43dad6cc44b` · `01a1830b-f8ed-773e-8081-9063fbb7add5` | `01a1830b-f904-78fb-aeaf-d037769e2a07` | `01a1830b-f94c-…`, `01a1830c-26f3-…` | `01a1830c-1082-7ced-91cb-f9349384cb48` |

The inline leg also made the item 2 and item 5 projects:

- divider 100 Hz `01a182f5-1ddf-7206-a9bd-3227578858b1`;
- divider 10 Hz `01a182f5-1e68-7812-83c5-348a33f77d42`;
- the linked folder `01a182f5-1f1f-732e-8155-4eef1d187774`, for the inline leg's user.

## Item 1: goal sketch → matrix result on the edge (seeded path, R66)

The sketch's `commands` edge, as `GET /api/v1/projects/{p}/entities/{sketch}/relations?direction=out&type=commands`
returned it (200, one relation), inline:

| Snapshot         | t      | relation                                     | `properties.commanded`                                                                                 | `properties.checker_results` |
| ---------------- | ------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------- |
| before sync 1    | 0.882  | `01a182f4-9da1-…` → servo 3, 0.8, `inferred` | `{min 200.0, max 200.0, unit deg, min_ref "bus_sketch_goal.ino:13", max_ref "bus_sketch_goal.ino:13"}` | absent (null)                |
| after sync 1     | 11.874 | same                                         | same                                                                                                   | the item below               |
| after sync 2     | 22.865 | same                                         | same                                                                                                   | the same item, same `at`     |
| after the rename | 33.601 | same                                         | same                                                                                                   | the same item, same `at`     |

```json
{
  "at": "2026-10-28T14:40:41.955595Z",
  "status": "fail",
  "message": "the code commands 200 deg at bus_sketch_goal.ino:13, past the part's -150 to 150 deg position limit (from its config)",
  "rule_id": "commanded_range_vs_joint_limit",
  "evidence": {
    "unit": "deg",
    "code_ref": "bus_sketch_goal.ino:13",
    "limit_hi": 150.0,
    "limit_lo": -150.0,
    "limit_unit": "deg",
    "limit_source": "config",
    "commanded_max": 200.0,
    "commanded_min": 200.0
  },
  "severity": "warning"
}
```

- **ARQ leg.** The same body on `01a182fc-045f-…`, `at 2026-10-28T14:48:47.406490Z`, written by the
  worker's `run_matrix_checkers` run.
- **Supplementary leg.** `at 2026-10-28T15:06:13.260797Z`.
- **The run that wrote it** (inline, t = 11.061 → 11.270): read 56 entities and 40 edges. Its
  `commanded_range_vs_joint_limit` results:
  - six `unknown_input` naming `commanded`, one on each `fw/fake_arm.ino` → part edge;
  - one `fail`, with edge_ref (sketch code, servo 3, commands).
- **The finding.** `01a182f4-c5f4-79dd-8416-0e20cdcb6946`: `commanded_range_vs_joint_limit`,
  warning, open, source `checker`, `matrix_cell software->mechanical`, subjects [sketch code,
  servo 3]. The headline is the message, and the evidence keys are `code_ref`, `commanded_max`,
  `commanded_min`, `limit_hi`, `limit_lo`, `limit_source`, `limit_unit` and `unit`.
  - Its count was 1 after sync 1, 2 after sync 2 and 3 after the rename: a fail is raised once a
    run, and M110 governs infos only.
  - ARQ finding `01a182fc-2e3a-7176-a370-dfee7bdec9aa`; supplementary `01a1830c-239c-7bcc-9fc8-44799b334fad`.

| Assertion                                                                                                  | Observed                                                                                                                                                                                                       |            |
| ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| the code entity carries its path; the accepted row's `source_ref` is `<path>:<line>` with the goal literal | `attrs.path` `bus_sketch_goal.ino`; row `{address "3", provenance[0].source_ref "bus_sketch_goal.ino:13", entity_ref setGoalPositionDeg, detail.value 200.0}`                                                  | ✅         |
| the real `firmware_edges.infer` writes the `commands` edge with `commanded`                                | one edge sketch → servo 3 (bus address 3), 0.8, `commanded {200, 200, deg, :13, :13}`                                                                                                                          | ✅         |
| `run_matrix` (the job through the real trigger)                                                            | the matrix job ran 10.43 s after the sync's `graph.changed` (inline), and in the worker in both ARQ legs                                                                                                       | ✅         |
| `commanded_range_vs_joint_limit` FAILS on that edge (±150 limit)                                           | `fail`, warning, `commanded_max 200.0` vs `limit_hi 150.0`, `limit_source config`                                                                                                                              | ✅         |
| the edge's `checker_results` item has status, severity, message and `at`, read through the route           | as above, via `/entities/{id}/relations` (200)                                                                                                                                                                 | ✅         |
| the EdgePanel shows status and time                                                                        | the shape `EdgePanel.tsx` renders: `rowLabel` `commanded_range_vs_joint_limit · failed · warning`, `<time>` `2026-10-28 14:40 UTC`; proxy `EdgePanel.test.tsx` ("status and at render, pass collapses") passed | ✅ (proxy) |
| the companion-scan form (local-folder sync of `bus_sketch_goal.ino`)                                       | **UNVERIFIED (M104):** local proposal rows carry opaque `source:<uuid>` refs and sketch entities are per directory                                                                                             | —          |

## Item 2: divider fixture → `divider_adc`, and `sample_rate_vs_adc_settling` above 5·RC

The seed is `tests/fixtures/matrix_divider.py::seed_divider(db, loop_rate_hz=…)`. It syncs
`kicad_divider_adc.net` through the schematic connector's real mapping (`build_graph` +
`apply_sync_result`), adds a code entity with `loop_rate_hz`, and adds the confirmed `reads` edge
onto R2 (pin `A0`).

The run is `checker_trigger.run_matrix_checkers({"sessionmaker": app.state.sessionmaker}, project)`,
the job itself, in its own session with its own commit. The routes were read with a token minted for
the fixture's own user.

**100 Hz** (`01a182f5-1ddf-…`, job 0.047 s, read 11 entities / 14 edges, `motifs_written 8`):

```json
{
  "status": "fail",
  "severity": "warning",
  "subjects": ["code_file:fw/divider.ino", "component:R2"],
  "edge_ref": ["code_file:fw/divider.ino", "component:R2", "reads"],
  "message": "the code samples this input every 10 ms (100 Hz), but its RC settles in 5·RC = 25 ms: it reads the input before it has settled",
  "evidence": {
    "r_ohm": 50000.0,
    "c_f": 1e-7,
    "tau_s": 0.005,
    "settle_s": 0.025,
    "sample_period_s": 0.01,
    "loop_rate_hz": 100.0,
    "net_id": "01a182f5-1dee-738d-bac5-32cf8068e9b0"
  }
}
```

- **The `reads` edge** `01a182f5-1dff-7091-9cce-0281880c30e1`, read through
  `GET /entities/{code}/relations?direction=out&type=reads` (200). Its `checker_results` is one
  item: `{rule_id sample_rate_vs_adc_settling, status fail, severity warning, message (as above),
evidence (as above), at 2026-10-28T14:41:04.552367Z}`. Before the run it had none.
- **The finding** `01a182f5-1e2f-7ce8-96b3-cd771364eec0`: `sample_rate_vs_adc_settling`, warning,
  open, source `checker`, `software->electrical`, subjects [code, R2], count 1.
- **`attrs.motifs`, read from the rows:**
  - `divider_adc` (confidence 0.9), members [R1, R2, C1, U1, net `/VSENSE`], is on **R1, R2, C1, U1
    and `/VSENSE`**;
  - `decoupling_at_pin` (0.9), members [C2, U1, `+3V3`, `GND`], is on C2, U1, `+3V3` and `GND`;
  - before the run, no entity had `attrs.motifs`.
- **No robot in the project.** The 36 project-wide unknowns are report `notes`, with no info finding
  (R61).

**10 Hz control** (`01a182f5-1e68-…`, job 0.032 s):

- `pass`, info: "the input settles in 5·RC = 25 ms, within the code's 100 ms sample period"
  (`sample_period_s 0.1`).
- The edge item is `pass`, at `14:41:04.668332Z`. No finding was raised, and the same 8 motif holders
  were written.

| Assertion                                                      | Observed                                                                                                                                                           |                        |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------- |
| `attrs.motifs` carries `divider_adc` on the net and components | on R1, R2, C1, U1 and net `/VSENSE` (5 members), 0.9                                                                                                               | ✅                     |
| the FactStore's `rc_settling_s` comes from the motif           | τ = (R1‖R2)·C1 = 50 kΩ · 100 nF = 5 ms; `settle_s` 0.025                                                                                                           | ✅                     |
| `sample_rate_vs_adc_settling` FAILS above 5·RC                 | at 100 Hz, 10 ms < 25 ms → fail, warning, on the edge and as a finding                                                                                             | ✅                     |
| the same read passes once the period exceeds 5·RC              | at 10 Hz, 100 ms > 25 ms → pass                                                                                                                                    | ✅                     |
| (2b) `proximity_pair`, if the fixture carries positions        | **the fixture carries none** (netlist only, no `.kicad_pcb`): `unknown_input(pcb_positions)`, "set it in the board-layout connector's footprint positions (P3-T4)" | not reachable (stated) |

The KiCad source in the arm projects is the same netlist through the real connector route. There
the matrix job wrote the same motifs on its members (8 holders after sync 1, 9 after sync 2, when C3
adds a second `decoupling_at_pin`). Those projects have no confirmed `reads` edge, so
`sample_rate_vs_adc_settling` answers a relation gap (`reads`) there.

## Item 3: a rule with no fact → one standing info per (rule, entity); the signal; six `COMMANDED`

The arm project is the subject. Standing infos are findings with `severity info`, `source
checker` and `evidence.missing`, read from the rows. The route `GET /findings?status=open&limit=100`
returned 37 open (36 infos + 1 fail) after each sync, with `has_next false`.

| Snapshot                   | Standing infos          | Max per (rule, first subject) | `count`   | `version` | `evidence.signal` (the KiCad source)                    | That run's `infos_raised` |
| -------------------------- | ----------------------- | ----------------------------- | --------- | --------- | ------------------------------------------------------- | ------------------------- |
| before sync 1              | 0                       | –                             | –         | –         | –                                                       | –                         |
| after sync 1               | **36**                  | **1**                         | 1 ×36     | 1 ×36     | `{01a182f4-9dc5-…: "2026-10-28T14:40:31.902152+00:00"}` | 36                        |
| after sync 2 (new signal)  | 36, **the same 36 ids** | 1                             | **2** ×36 | 2 ×36     | `{…: "2026-10-28T14:40:42.898330+00:00"}`               | 36                        |
| after the rename (no sync) | 36, the same ids        | 1                             | **2** ×36 | 2 ×36     | unchanged (`…14:40:42.898330`)                          | **0**                     |

The ARQ and supplementary legs gave the same table: 36 / 1 / 1 → 2 → 2, identical ids, and
`infos_raised` 36, 36, 0. Every info has `bucket` null, `source` checker, and `matrix_cell` across
all nine cells: m→s 5, m→m 5, s→e 4, s→m 4, e→e 4, e→m 4, m→e 4, s→s 3, e→s 3.

**The 36 infos (rule | subject | count after the rename | `evidence.missing[].name` | `edges`):**

```
commanded_range_vs_joint_limit | code_file:fw/fake_arm.ino | 2 | commanded | 6
— on physical_robot "Fake arm", all count 2, edges 0:
board_mass_into_com board_mass_g · bracket_strength_at_joint material · brownout_is_uncommanded_reboot brownout_v
bus_bandwidth_caps_loop_rate bus_bitrate_hz · cable_length_voltage_drop cable_length_m
commanded_current_vs_driver_supply commanded_current_a · config_protocol_mismatch firmware_protocol
connector_clearance connector_keepout_mm · driver_heat_into_mount dissipation_w · duty_cycle_vs_thermal_rating duty_cycle
enclosure_thermal_derating enclosure_ambient_c · fastener_engagement thread_engagement_mm · gains_vs_resonance resonance_hz
gear_ratio_backlash_into_scaling gear_backlash_deg · harness_through_joint harness_route · interference_through_range interference_mm
joint_limit_vs_code_constant limits · link_length_vs_kinematic_model link_lengths_m · load_torque_current_into_sizing load_torque_nm
loop_rate_latency loop_latency_s · mass_inertia_into_gains link_inertia · module_contract_mismatch module_interfaces
pin_capability_vs_firmware_use definitions · pin_in_code_vs_wiring reads · power_budget powers · proximity_pair pcb_positions
pwm_frequency_vs_driver pwm_frequency_hz · return_path_over_split plane_splits · sample_rate_vs_adc_settling reads
sensor_mount_offset_into_calibration sensor_mount_pose · speed_accel_vs_structural_load structural_load_n · tolerance_stack tolerances
torque_constant_times_current_vs_load torque_constant_nm_per_a · trace_width_vs_current trace_width_mm · wall_too_thin wall_thickness_mm
```

The 37th registered rule, `package_version_conflict`, returned no result here. The project holds an
`environment/divergences` CONFIG (from the fake arm's seed) with no machine, and no requirement file
pins anything. So it judged nothing and lacked nothing.

The code file's info is inline id `01a182f4-c623-7339-8b37-8b281b815643` (ARQ `01a182fc-2e69-…`,
supplementary `01a1830c-23c3-…`). Its headline:

```
could not check commanded_range_vs_joint_limit: commanded unknown for fw/fake_arm.ino; set it in a literal goal in the firmware call that commands the part (`write*` / `setGoal*` / `setTarget*(address, value)`), accepted from its hardware review row
```

The six goal-less edges (`fw/fake_arm.ino` → parts 1–6, confidence 1.0, no `commanded` key), after
sync 1 and in all three legs, each had `checker_results` = exactly one item:

```json
{
  "at": "2026-10-28T14:40:41.955595Z",
  "status": "unknown_input",
  "rule_id": "commanded_range_vs_joint_limit",
  "severity": "info",
  "message": "could not check commanded_range_vs_joint_limit: commanded unknown; set it in a literal goal in the firmware call that commands the part (`write*` / `setGoal*` / `setTarget*(address, value)`), accepted from its hardware review row",
  "evidence": {
    "missing": {
      "name": "commanded",
      "set_in": "a literal goal in the firmware call that commands the part (`write*` / `setGoal*` / `setTarget*(address, value)`), accepted from its hardware review row"
    }
  }
}
```

| Assertion                                                                        | Observed                                                                                                             |     |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --- |
| exactly one standing info per (rule, entity)                                     | 36 infos for 36 distinct (rule, first subject), in every leg and snapshot                                            | ✅  |
| the info names the field and `set_in`                                            | 36 of 36 headlines contain `<field> unknown for <entity>; set it in <set_in>`; `evidence.missing = [{name, set_in}]` | ✅  |
| a second graph change with a NEW signal bumps `count`, not a new node            | same 36 ids, count 1 → 2, version 1 → 2, `infos_raised 36`                                                           | ✅  |
| an unchanged signal bumps nothing (M110)                                         | after the rename, count 2 → 2, version 2 → 2, `infos_raised 0`                                                       | ✅  |
| the fake arm's six goal-less `commands` edges each carry exactly one `COMMANDED` | 6 of 6 edges have one item, `unknown_input`, `missing.name commanded`; one info on the code file with `edges 6`      | ✅  |

## Item 4: the budget trigger through the fan-out, both sync modes, stable ids, config_version

**Inline** (`sync_inline=True`, enqueue=None):

| Change (t)           | `graph.changed` published here (counts)             | Fan-out  | `recompute_budgets` (in process) | `run_matrix_checkers` (in process) | CONFIG after                                                        |
| -------------------- | --------------------------------------------------- | -------- | -------------------------------- | ---------------------------------- | ------------------------------------------------------------------- |
| sync 1 (1.058)       | sync `01a182f4-9e2e-…`, entities +10, relations +13 | t 1.059  | t 6.060 → 6.092 (+5.40 s)        | t 11.061 → 11.282 (+10.43 s)       | **v1** (`0 of 12 parts massed`, `0 of 12 rows priced`)              |
| sync 2 (12.046)      | sync `01a182f4-c934-…`, +1, updated 8, relations +2 | t 12.046 | t 17.048 → 17.086                | t 22.048 → 22.262                  | **v2** (`0 of 13 …`)                                                |
| rename (22.983)      | no source; updated 1                                | t 22.985 | t 27.986 → 28.025                | t 32.989 → 33.046                  | v2 (`computed_at` refreshed, `updated_at` 14:40:58.871, no version) |
| folder link (34.134) | local sync, +6 / +5                                 | t 34.135 | t 39.136 → 39.166                | t 44.137 → 44.170                  | folder project v1                                                   |

**ARQ** (`sync_inline=False`, ONE worker, pid 3709285). Each harness enqueue (`main._enqueue_budgets_job(app)`, `_job_id=FANOUT_JOB_IDS[...]`) was run by the worker:

| t      | host | function              | `_job_id`                                                  | accepted | worker `→` / `←` (arq's log) |
| ------ | ---- | --------------------- | ---------------------------------------------------------- | -------- | ---------------------------- |
| 6.091  | API  | `recompute_budgets`   | `recompute_budgets:01a182fc-02ac-7a1c-adc7-aa40650ef547`   | ✅       | 10:48:42 → … ← ● (0.25 s)    |
| 11.092 | API  | `run_matrix_checkers` | `run_matrix_checkers:01a182fc-02ac-7a1c-adc7-aa40650ef547` | ✅       | 10:48:47 → … ← ● (0.24 s)    |
| 17.443 | API  | `recompute_budgets`   | same id                                                    | ✅       | 10:48:53 (0.04 s)            |
| 22.445 | API  | `run_matrix_checkers` | same id                                                    | ✅       | 10:48:58 (0.24 s)            |
| 28.515 | API  | `recompute_budgets`   | same id                                                    | ✅       | 10:49:04 (0.03 s)            |
| 33.516 | API  | `run_matrix_checkers` | same id                                                    | ✅       | 10:49:09 (0.08 s)            |

arq's log stamps are host-local (UTC−4): 10:48:42 is 14:48:42Z.

- **Budgets.** The worker's `store_budgets` gave config_version **1** (t 6.705), **2** (17.552) and
  2 (28.604), on entry `01a182fc-1b3a-…`.
- **Matrix.** The worker's `MatrixReport`s are in the table under the verdicts.
- **Where the sync ran.** Both KiCad syncs ran in the API process (harness probe: sync ids
  `01a182fc-04e4-…`, `01a182fc-3176-…`; the worker ran 0 syncs). Deviation 1 explains why.

**Supplementary ARQ** (the worker runs the syncs, pid 3749776). The worker host's own enqueues:

| t      | host          | function                                                | `_job_id`                                                  | accepted                                                          |
| ------ | ------------- | ------------------------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------- |
| 0.940  | API (harness) | `sync_source(source, job 01a1830b-f94c-…, user)`        | (arq id `8413f17c…`)                                       | ✅ → worker `sync_source ● '01a1830b-fa20-…'` at t 1.32           |
| 1.318  | **worker**    | publishes `graph.changed` (+10 / +13), its fan-out runs | –                                                          | –                                                                 |
| 6.321  | **worker**    | `recompute_budgets`                                     | `recompute_budgets:01a1830b-f725-7e03-a233-f2645abee940`   | ✅ → v1                                                           |
| 11.322 | **worker**    | `run_matrix_checkers`                                   | `run_matrix_checkers:01a1830b-f725-7e03-a233-f2645abee940` | ✅ → annotated 7, infos 36                                        |
| 12.626 | API           | `sync_source` (job `01a1830c-26f3-…`)                   | (arq id `4783c5c6…`)                                       | ✅ → worker sync, `graph.changed` (+1 / updated 8 / +2) at 12.812 |
| 17.816 | **worker**    | `recompute_budgets`                                     | same stable id                                             | ✅ → v2                                                           |
| 22.821 | **worker**    | `run_matrix_checkers`                                   | same stable id                                             | ✅ → infos 36 (count 2)                                           |
| 29.132 | API (rename)  | `recompute_budgets`                                     | same stable id                                             | ✅ → v2                                                           |
| 34.133 | API (rename)  | `run_matrix_checkers`                                   | same stable id                                             | ✅ → infos 0                                                      |

The Redis MONITOR confirms it from the server side. The stable-id `PSETEX arq:job:<id>` writes came
from the worker's own connections (client ports 59170 and 37126) at 15:06:07, :12, :19 and :24, and
from the harness's connection (59180) at 15:06:30 and :35.

**`keep_result=0`.** As registered in `build_worker_settings` (read in the worker):

- `run_matrix_checkers` `{keep_result_s 0, timeout_s 300, max_tries 1}`;
- `recompute_budgets` `{0, 120, 1}`;
- `sync_source` `{0, 3660, 241}`.

The MONITOR logs bear this out:

- **Enqueue.** `WATCH arq:job:<id>`, then `EXISTS arq:job:<id> arq:result:<id>`, then `PSETEX
arq:job:<id>` and `ZADD arq:queue`.
- **Completion.** `DEL arq:in-progress:<id> arq:retry:<id> arq:job:<id>`.
- **Result keys.** Every `arq:result` mention is one of those `EXISTS` checks (23 in the ARQ leg, 15
  in the supplementary one), and there are **0** `PSETEX`/`SET` of a result key.
- **Afterwards.** No `arq:result:*` key existed after any leg. Redis `dbsize` was 0 after each
  worker stopped.

| Assertion                                                         | Observed                                                                                                                                            |     |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| the budget trigger fires through the fan-out after a sync, inline | 3 changes → 3 fan-out calls → 3 `recompute_budgets` + 3 `run_matrix_checkers` in process                                                            | ✅  |
| … in the ARQ mode, with the worker consumer                       | the API's fan-out enqueued both jobs after each change; the ONE worker ran all 6 (and all 6 in the supplementary leg)                               | ✅  |
| both jobs re-enqueue under their own stable ids (R46)             | `recompute_budgets:<p>` and `run_matrix_checkers:<p>` each accepted 3× in a row under the same id, from the API and (supplementary) the worker host | ✅  |
| `keep_result=0`                                                   | registered 0 for both; 0 result-key writes; no `arq:result:*` key                                                                                   | ✅  |
| the budgets CONFIG `config_version` bumps after the sync          | none → 1 after sync 1, 1 → **2** after sync 2 (C3 added), in all three legs; unchanged (2) after the no-budget rename                               | ✅  |

**The `matrix` / `window` / `budget` log lines.** No `window` line exists: no bench session ran.
The inline lines:

```
6.079 INFO solus.services.budgets | budgets project=01a182f4-9bfe-759b-8379-7d48bd6b9b80 mass=unknown cost=unknown
11.183 INFO solus.graph.findings | finding raised project=01a182f4-9bfe-759b-8379-7d48bd6b9b80 rule=power_budget      (power_budget's standing info being created; R60 keeps its fails off findings)
11.27 INFO solus.checkers.matrix_runner | matrix run project=01a182f4-9bfe-… rules=37 annotated=7 skipped=0 raised=1 infos=36 resolved=0 motifs=8 notes=0 truncated=False
17.074 INFO solus.services.budgets | budgets project=01a182f4-9bfe-… mass=unknown cost=unknown
22.248 INFO solus.checkers.matrix_runner | matrix run project=01a182f4-9bfe-… rules=37 annotated=0 skipped=0 raised=1 infos=36 resolved=0 motifs=9 notes=0 truncated=False
28.011 INFO solus.services.budgets | budgets project=01a182f4-9bfe-… mass=unknown cost=unknown
33.033 INFO solus.checkers.matrix_runner | matrix run project=01a182f4-9bfe-… rules=37 annotated=0 skipped=0 raised=1 infos=0 resolved=0 motifs=0 notes=0 truncated=False
33.724 INFO solus.checkers.matrix_runner | matrix run project=01a182f5-1ddf-… rules=37 annotated=1 skipped=0 raised=1 infos=0 resolved=0 motifs=8 notes=36 truncated=False   (divider 100 Hz)
33.826 INFO solus.checkers.matrix_runner | matrix run project=01a182f5-1e68-… rules=37 annotated=1 skipped=0 raised=0 infos=0 resolved=0 motifs=8 notes=36 truncated=False   (divider 10 Hz)
39.164 INFO solus.services.budgets | budgets project=01a182f5-1f1f-… mass=unknown cost=unknown
44.168 INFO solus.checkers.matrix_runner | matrix run project=01a182f5-1f1f-… rules=37 annotated=0 skipped=0 raised=1 infos=0 resolved=0 motifs=0 notes=36 truncated=False   (linked folder)
```

The ARQ leg's worker lines:

```
6.705 INFO solus.services.budgets | budgets project=01a182fc-02ac-7a1c-adc7-aa40650ef547 mass=unknown cost=unknown
11.719 INFO solus.checkers.matrix_runner | matrix run project=01a182fc-02ac-… rules=37 annotated=7 skipped=0 raised=1 infos=36 resolved=0 motifs=8 notes=0 truncated=False
17.552 INFO solus.services.budgets | budgets project=01a182fc-02ac-… mass=unknown cost=unknown
22.789 INFO solus.checkers.matrix_runner | matrix run project=01a182fc-02ac-… rules=37 annotated=0 skipped=0 raised=1 infos=36 resolved=0 motifs=9 notes=0 truncated=False
28.603 INFO solus.services.budgets | budgets project=01a182fc-02ac-… mass=unknown cost=unknown
33.691 INFO solus.checkers.matrix_runner | matrix run project=01a182fc-02ac-… rules=37 annotated=0 skipped=0 raised=1 infos=0 resolved=0 motifs=0 notes=0 truncated=False
```

The supplementary worker logged the same six lines, for project `01a1830b-f725-…`, at t 6.884,
11.905, 18.246, 23.398, 29.311 and 34.349. No matrix cap line and no "not kept" line appeared
anywhere: no run was truncated and none skipped an edge or a motif holder.

**Per-leg timings** (t; the change → the job done):

| Leg           | Harness wall | Sync 1: request · job ok · budgets / matrix done  | Sync 2                                      | Rename                    |
| ------------- | ------------ | ------------------------------------------------- | ------------------------------------------- | ------------------------- |
| inline        | 44.8 s       | 0.895: 0.165 s · 1.063 · +5.398 / +10.426         | 11.911: 0.136 s · 12.048 · +5.369 / +10.396 | 22.961 · +5.261 / +10.091 |
| ARQ           | 34.4 s       | 0.942: 0.149 s · 1.093 · +5.792 / +10.834         | 12.366: 0.079 s · 12.446 · +5.330 / +10.578 | 23.486 · +5.272 / +10.315 |
| supplementary | 35.0 s       | 0.935 enqueue · 1.353 (worker) · +6.063 / +11.102 | 12.623 · 12.833 · +5.669 / +10.913          | 24.103 · +5.289 / +10.336 |

The budgets store took 0.019–0.026 s inline. The matrix job took 0.057–0.221 s in process, and
0.08–0.25 s in the worker by arq's `←` times.

## Item 5: SOL's `run_checkers` dry run persists nothing; `/code-environment` still reports `python_pin_conflict`

The tool ran through `build_sol_registry(app.state.sessionmaker, project, systems=app.state.sol_systems)`
and `build_dispatch(registry, None)`: the gated dispatcher a turn gets. The registry listed
`analyze_rail_current, get_entity, get_telemetry, query_graph, retrieve_errors, run_checkers`. Both
calls were made after every debounced job had finished: both triggers' timers were 0 before and
after.

| Call                                        | Result                       | Warnings                                                                                                                                                                                         | Findings before → after                         | `checker_results` before → after                        | Matrix runs during the call |
| ------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------- | ------------------------------------------------------- | --------------------------- |
| arm project, anchors [sketch code, servo 3] | ok, 0.048 s, truncated false | `commanded_range_vs_joint_limit`, warning, [sketch code, servo 3], the edge's message                                                                                                            | 37 → 37, digest `99307b1a…cda` = `99307b1a…cda` | 7 edges / 7 items → 7 / 7, digest `a51a1cf2…df4` = same | 0                           |
| linked folder, anchors its 4 requirements   | ok, 0.026 s                  | `package_version_conflict`, **critical**, "'torch' is pinned differently across isaac/requirements.txt, requirements.txt — one environment cannot satisfy both.", [torch ==2.3.0, torch ==2.1.0] | 1 → 1, digest `04989367…4ad` = same             | 0 → 0                                                   | 0                           |

The folder project's one finding is the matrix JOB's: `01a182f5-470a-70c5-8eea-e63a89d89757`,
`package_version_conflict`, critical, count 1. The job ran 10 s after the link's sync and before
the tool call, so the tool added nothing.

The linked folder was made with `POST /local-folder` `{machine_id <random 32 hex>, machine_name
p3-bench, folder_name rover-fw}` (201, `connected`). Its companion is an in-process copy of
`tests/test_code_environment.py`'s `FakeCompanion`, answering the scan and the probe with no socket
(deviation 5). It lands 4 `python_requirement` entities: torch `==2.3.0`, gymnasium `>=0.29`,
torch `==2.1.0` and numpy.

`GET /api/v1/projects/{p}/code-environment?machine_id=…` returned 200:

```json
{
  "bridge": { "connected": true, "code_server": true },
  "requirements": {
    "count": 4,
    "files": ["isaac/requirements.txt", "requirements.txt"]
  },
  "conflicts": [
    {
      "checker_id": "python_pin_conflict",
      "severity": "critical",
      "domains": ["code"],
      "message": "'torch' is pinned differently across isaac/requirements.txt, requirements.txt — one environment cannot satisfy both.",
      "evidence": {
        "package": "torch",
        "pins": [
          { "source_file": "isaac/requirements.txt", "specifier": "==2.1.0" },
          { "source_file": "requirements.txt", "specifier": "==2.3.0" }
        ]
      },
      "entity_ids": [
        "01a182f5-1f8b-7d41-ae27-91edbff821a3",
        "01a182f5-1f89-7c13-8044-ca3edc7d4395"
      ],
      "suggested_area": "split the environments: one virtual environment per requirement file that pins this package"
    }
  ],
  "split": true
}
```

`probe` is the fake companion's canned probe.

| Assertion                                                                | Observed                                                                                                                                       |     |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| `run_checkers` answers from a dry run of the matrix (R64)                | the matrix warning on its slice (`commanded_range_vs_joint_limit`; `package_version_conflict`), with no `run_matrix` call during the tool call | ✅  |
| it persists nothing                                                      | findings and `checker_results` counts and sha256 digests identical before and after, in both projects                                          | ✅  |
| the legacy `/code-environment` still reports `python_pin_conflict` (R51) | `conflicts[0].checker_id = python_pin_conflict`, critical, torch                                                                               | ✅  |

## Proxy tests (after the live runs)

The guard ran in its own call each time (no pytest running, no worker running). The API proxies ran
in ONE process from `packages/api`, 14:54:04Z → 14:55:45Z:

```
PYTHONDONTWRITEBYTECODE=1 SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2 uv run --frozen --no-sync pytest -q -p no:cacheprovider tests/test_matrix_runner.py tests/test_checker_trigger.py tests/test_firmware_edges.py tests/test_netlist_motifs.py tests/test_sample_rate_vs_adc.py tests/test_annotate_edge.py tests/test_checker_graphs.py tests/test_matrix_registry.py tests/test_label_motifs.py tests/test_rulebook_tools.py
135 passed in 97.96s (0:01:37)
```

- All ten named files exist, and none was dropped.
- They hold 76 test functions: matrix_runner 25, checker_trigger 6, firmware_edges 4,
  netlist_motifs 13, sample_rate_vs_adc 3, annotate_edge 6, checker_graphs 3, matrix_registry 3,
  label_motifs 9, rulebook_tools 4. Parametrisation expands them to the 135 collected.
- The run used no `--cov`. `.coverage` md5 stayed `7571ebfd2af623167baf221f5af68076`, and the tree
  stayed clean.

The desktop proxy ran from the repo root as `pnpm --filter @solus/desktop exec vitest run src/renderer/src/features/graph/sidebar/EdgePanel.test.tsx`:

```
 ✓ src/renderer/src/features/graph/sidebar/EdgePanel.test.tsx (6 tests) 219ms
 Test Files  1 passed (1)
      Tests  6 passed (6)
```

It includes "status and at render, pass collapses" and "unknown_input shows could not check".

## Deviations from the brief and observations

1. **The worker ran under a guarded wrapper, not the bare `arq` command.**
   - **Why.** The literal command builds its settings with a bare `Settings()`. That call loads the
     root `.env`: `supabase_jwt_secret` is required, and the two exported variables cannot supply
     it. So the literal command must read a secret, and the hard rules forbid that.
   - **Risk.** Reading the root `.env` could also point the worker's every-minute
     `sweep_artifacts` and `purge_cad_accounts` crons at real dev directories, against the copied
     rows.
   - **What the wrapper does** (`p3_worker.py`):
     - the same two-variable refusal, egress, spawn and dotenv guards as the harness;
     - `solus_api.core.config.Settings` becomes a subclass filling the in-code values (as
       `test_checker_trigger._start_worker` substitutes its settings);
     - recording-only probes;
     - then arq's own CLI on the unchanged `solus_api.worker_main.WorkerSettings`
       (`cli.main(["solus_api.worker_main.WorkerSettings"])`).
   - **What it leaves the same.** The same 16 functions and crons, `_on_startup` and `keep_result`
     run.
   - **One recording-only change.** The root logger is set to INFO, so the worker's own
     `budgets …` / `matrix run …` lines are emitted (arq configures only its own logger).
2. **Where an ARQ-mode KiCad sync runs (a finding, not a defect).**
   - `enqueue_sync` forces `inline_only` for LOCAL, KICAD and ALTIUM sources (routers/sources.py:604-605:
     "Bridge-backed local/KiCad/Altium acquisition lives in THIS process"). So with
     `sync_inline=False` the sync is an API background task, never an ARQ job.
   - The `graph.changed` is then published by the API, and its fan-out (`main.py:255`) enqueues both
     jobs for the worker.
   - That is the ARQ leg as run. It is also the path the plan's §5 step 5 takes: its `.ino` sync is
     a LOCAL source.
   - The worker host's own enqueue (`connectors/worker.py:1233-1234`) fires only for a sync the
     worker runs. Every such provider (github, gitlab, onshape, ros) needs the network.
   - The supplementary leg therefore enqueued the `sync_source` job that `_dispatch_sync` enqueues
     for a queued provider (routers/sources.py:834), for the KiCad source, with the Job row
     `enqueue_sync` records.
   - The API never does this for KiCad. Everything after the enqueue is the worker's real path.
3. **Fails count per run.** The `commanded_range_vs_joint_limit` fail's count rose 1 → 2 → 3 (one
   raise per run, m5). M110's "nothing without a new signal" applies to standing infos only, and
   those held at 2.
4. **Two void attempts, kept as evidence.**
   - **(a) The first inline run** (14:36:13Z → 14:37:00Z, `p3_accept_live_inline_VOID_result.json`).
     - My `run_matrix` probe read `EdgeRef.relation`, which does not exist (the field is
       `relation_type`). That raised inside the job after each run's writes.
     - `run_matrix_checkers` caught it ("matrix run failed project=…", 5 times) and rolled the
       session back. Only the folder project's run, with no edge result, committed.
     - The fix was the field name, plus every probe's recording made best-effort. The rerun logged
       0 probe errors and 0 ERROR lines.
     - That attempt left 4 projects in `solus_sol` (below). No tracked file was involved.
   - **(b) The first worker start** (14:45:31Z, `p3_worker_IMPORT_FAILED.log`).
     - The wrapper had replaced `Settings` with a plain function, and
       `billing/development.py`'s runtime annotation `Settings | None` raised `TypeError` at import.
     - The worker exited 1 before running anything: 0 events, no job.
     - The fix was the subclass (deviation 1).
5. **The harness copies two seeding helpers and the fake companion** rather than importing
   `test_firmware_edges`, `test_inference_firmware_edges` and `test_code_environment`. Those import
   `tests/conftest.py`, whose import-time `_strip_ambient_solus_env()` deletes every `SOLUS_*`
   variable; `Settings` would then default to the live `solus` DB. The harness also re-checks the
   `SOLUS_*` set after its imports.
6. **The dotenv guard is new since P2.** P2's harness imported `toolkb/sharing.py`, whose
   `_ToolkbSettings()` reads the root `.env` at import. It found no salt, as P2's stderr line says.
   Here that read is refused and recorded (1 per harness process), and the same stderr line appears.
7. **The pytest command** adds `--frozen --no-sync` and `PYTHONDONTWRITEBYTECODE=1` (P1/P2
   precedent), so the venv, `uv.lock` and the tree cannot be touched.
8. **Observations, harmless.**
   - The one "finding raised … rule=power_budget" line per first run is that rule's standing info
     (missing `powers`), not a fail. There are no `powers` edges, and R60 keeps its fails off
     findings.
   - `infer` reports "updated 1" alongside "created 1": both goal rows for address 3 write the one
     edge.
   - The robot's labels in the raw JSON show its renamed name ("Fake arm (renamed by the P3
     acceptance)"); the infos' stored headlines keep "Fake arm", since they were not re-raised (M110).
   - `/users/me` has no `sol_mode` key (as in P2).
   - The every-minute crons ran 17 times in the ARQ worker and 15 in the supplementary one. Every
     run returned 0.

## Not verified here

- **The companion-scan form of item 1 (M104).** That is a local-folder sync of
  `bus_sketch_goal.ino`, its proposal rows and the accept route. Local proposal rows carry opaque
  `source:<uuid>` refs, and sketch entities are per directory. Ruled out of this run by R66.
- **The EdgePanel in the running desktop app.** Only its vitest proxy ran. The rendered row above is
  the component's own formatting applied to the route body.
- **`label_motifs` and `extract_rulebook` live** (a SOL turn with a model). They are proven by their
  scripted tests only, all in the 135.
- **`proximity_pair` judging from positions (2b).** The divider fixture carries no board, so no
  positions. P3-T4's `test_electrical_electrical.py` proximity tests cover it, but they are not in
  this proxy list and did not run here.
- **A credentialed sync running in the worker.** Not reachable without a provider. The supplementary
  leg ran the worker's sync path on a KiCad source instead.

## Left behind

- **In `solus_sol`:**
  - **Before my first run:** 3 users, 3 projects, 9 `credit_ledger` rows, 6 findings, 217 entities,
    270 edges, 1 source, 4 jobs, 25 `.solus` entries.
  - **After the void inline attempt:** 6 / 7 / 10 / 7 / 326 / 433 / 5 / 7.
  - **After the three legs:** **11 users, 13 projects, 13 `credit_ledger` rows (each new one a
    `trial_grant`), 120 findings, 661 entities, 916 edges, 11 sources, 14 jobs, 71 `.solus` entries.**
  - **The void attempt's projects:**
    - `01a182f0-b4e8-7672-ba52-fd423a13fbd8`: the fake arm, the sketch, a KiCad source and a budgets
      CONFIG at v2; its matrix writes were rolled back;
    - the dividers `01a182f1-38bf-…` and `01a182f1-390c-…`, with matrix writes rolled back;
    - the folder `01a182f1-39a7-…`, with 1 finding.
  - **The legs' projects:** the arm projects of the three legs, the two dividers and the folder, as
    in the seed table.
- **Not touched:**
  - `solus`, the live dev DB;
  - `solus_sol_p1`;
  - every `solus_test_*` database except `solus_test_d7fa72c2`, the proxy run, which TRUNCATEs it
    as designed.
- **Redis 6390.** `dbsize` was 0 after each worker stopped; the last check was at 15:09:22Z.
  `solus-redis-1` was never touched.
- **Processes.**
  - Exactly two worker consumers ran, one per ARQ leg, each stopped by its own pid (3709285 and 3749776) with rc 0. Their uv parents exited with them.
  - The three `docker exec … timeout <s> redis-cli monitor` captures ended on their own timeouts.
  - Nothing else was started, stopped or killed.
  - One process outlives the run and is not mine to stop: `dmypy run -- …/acceptance/p3_worker.py`
    (pid 3661198, started 14:29:20Z, now parented to `systemd --user`). The repository's H8
    post-edit hook launched this mypy daemon when the wrapper was first written; it was left
    running.
- **Files.** All are in the git-ignored plan workspace:
  - `acceptance/`: `p3_accept_live.py`, `p3_worker.py`, `p3_accept_live_{inline,arq,arq-worker-sync}_result.json`
    and `.stderr`, the void inline JSON, `p3_worker_{arq,worker_sync}.log`,
    `p3_worker_events_{arq,worker_sync}.jsonl`, `p3_worker_result_{arq,worker_sync}.json`,
    `p3_worker_IMPORT_FAILED.log` and `p3_redis_monitor{,_arq,_worker_sync}.log`;
  - `reports/`: this report.
  - No tracked file changed.
