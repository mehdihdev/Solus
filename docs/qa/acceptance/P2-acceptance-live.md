# P2 acceptance, live proof (SOLUSDEV-321 plan §3 "P2 acceptance", items 1–6): in process, real-time replay, scripted narration, copy of the dev DB

All times below are `t` = seconds after `POST /bench/sessions` returned 201 (t = 0 ≈ 22:38:12.14Z). The recording's event clock starts at 2026-10-25T00:00:00Z; "event s" is seconds into the recording.

## Verdicts

- **1. Stall within 2 s, one finding, blame and causes: ✅ on 10 of 11 assertions, ❌ on 1.**
  - ✅ At the 8 s poll there is exactly one open finding whose primary subject is servo 3: `tracking_error_stall`, critical. The only other finding is the bus's `rail_sag_correlated`.
  - ✅ It was raised 1.0 s of event time after the 5.0 s onset (evidence window 5.00 → 6.00 event s) and committed at t = 6.33.
  - ✅ `current_a` 2.804 > `bound` 2.0, with `bounds_source` = `config`.
  - ✅ Subjects are servo 3, bus, brain. `code_site` is `fw/fake_arm.ino` line 13, from the `commands` edge. Causes rank `mechanical_load`, `software_command`, `actuator`.
  - ❌ `evidence.also` is `["current_over_rating"]` on all five raises; `time_to_limit` never folds in. Under the shipped rule, `time_to_limit` fires on the current only for windows ending between 6.40 and 6.95 event s. This run's windows ended at about 6.25 and about 7.30–7.40 event s, on either side of that band (details in item 1).
- **2. 60 s gives one node per condition, count rising (R12): ✅ on the ruling, ❌ on two literal numbers.**
  - ✅ 6 findings for 6 distinct (rule, primary subject) pairs. For every finding, `count` equals the number of ticks that raised it.
  - ✅ `temp_trend_to_limit` rose 1 → 36, once in every tick from tick 21 to tick 56.
  - ❌ The stall rose 1 → **5** (ticks 6–10, then still for 46 ticks), not the brief's 1 → 4.
  - ❌ `sensor_frozen` reached **27** over 28 ticks. It missed tick 30, where the shipped budget skipped 4 rule runs.
- **3. Five distinct findings in 40 s, one narration call: ✅.**
  - Five distinct findings were raised by t = 31.24 (the sixth, the servo 2 stall, came at t = 41.15).
  - The live session made exactly **1** scripted narration call: 1 `model call start … purpose=narration turn_id=None` line at t = 16.359, and **1** `credit_ledger` `usage` row with `attrs.purpose = "narration"` (−3 credits, the session owner, no `turn_id`).
  - The call came 10.03 s after the first finding was heard.
  - It wrote `explanation` and `causes_ranked` on both findings of its batch (`detail` empty). The stall's `finding.updated` frame came at t = 16.391; its version went to 6 against a count of 5.
  - Four findings heard later waited behind the 60 s interval (earliest flush t = 76.36). Refusing-adapter reaches: **0**.
- **4. A non-grounded number is rejected: ✅.** A second scripted batch (run after the live counts were taken, 1 more call) put `not grounded: The motor would need 37.5 A to clear it.` into `detail`. Only the grounded sentence stayed in `explanation`, and the headline was unchanged. Calling `grounded_numbers` directly on that sentence gives `False`.
- **5. Dismiss creates nothing, Resolve creates one `errors` entry: ✅.**
  - Dismiss: 200, `dismissed` until +24 h. `.solus` stayed at 0 `errors` entries and every section count was unchanged; graph stayed at 45 entities / 83 edges.
  - Resolve with a note: 200, `resolved`. `.solus` `errors` went 0 → **1**, and that entry's id equals the route's `entry_id`. The desktop proxy passed (27 tests).
- **6. Live proof: ✅**, with the deviations above. Narration calls: 1 live (plus 1 for item 4). Rule time per window: median **35.0 ms**, p95 60.1 ms, max 60.2 ms over 56 windows (budget 60 ms; 4 windows over, 21 rule runs skipped).

Ready to paste into the SDD ledger:

> P2 acceptance (live, in-process, DB copy `solus_sol` at a32000000006, real-time replay of serial_fake_arm_stall.json through POST /bench/sessions, shipped evaluator/budget/narrator timers, scripted narration via partial(gateway.complete, adapters=…), egress limited to Postgres/Redis): findings over time 0 → 2 at t 6.33 (stall@servo 3 critical + rail_sag@bus) → 3 at 20.27 (time_to_limit@3) → 4 at 22.50 (temp_trend@3) → 5 at 31.24 (sensor_frozen@actuator 5) → 6 at 41.15 (stall@servo 2); polls 8/25/45/62 s = 2/4/6/6 open. Servo-3 finding 01a17f83-ad3d-71c2-8970-735cff94db3e: evidence keys also, bound, bounds_source, causes, code_site, commanded, current_a, current_unit, error, items, limit, position, robot_id, samples, session_id, tolerance, unit, warn, warn_source, window_end, window_seconds, window_start. current 2.804 A vs bound 2.0 (config), raised 1.0 s after onset, subjects servo 3/bus/brain, code_site fw/fake_arm.ino:13, causes mechanical_load > software_command > actuator; also = [current_over_rating] only (time_to_limit's current forecast fires only for windows ending 6.40–6.95 s; this run's ended ≈6.25/7.30). Counts per condition: stall@3 1→5, sag 1, ttl 2, temp_trend 1→36, frozen 1→27 (one gap, at the one tick whose budget cut a rule), stall@2 1→5. Narration: 1 call at t 16.36 (10.03 s after the first finding), batch = stall@3 + sag, credit_ledger usage row purpose=narration, −3 credits, call_id b3254681-110f-4858-880b-2cff960971f9, user = session owner, no turn_id; 4 later findings held by the 60 s interval; refusing adapters 0. Rule time per window median 35.0 ms, max 60.2 ms (budget 60), 21 runs skipped in 3 ticks. Item 4: detail `not grounded: The motor would need 37.5 A to clear it.` (second scripted batch, +1 call, −2 credits). Dismiss: 0 errors entries; Resolve with note: exactly 1. Proxies: 81 passed (API, one process), 27 passed (desktop). Report: `docs/qa/acceptance/P2-acceptance-live.md.

## Run identity

| Item                | Value                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Run time            | 2026-10-27T22:38:09Z to 22:39:16Z (command), harness 22:38:11.252Z to 22:39:15.562Z, exit 0                                                                                                                                                                                                                                                                                                               |
| Branch              | `SOLUSDEV-321-sol-checker-algorithm`                                                                                                                                                                                                                                                                                                                                                                      |
| HEAD at run time    | `c0e868b5` before and after the run. `git status --short` was empty before and after; `.coverage` md5 was `7571ebfd2af623167baf221f5af68076` before and after.                                                                                                                                                                                                                                            |
| Database            | `solus_sol` (the dev-DB copy P1 made). Asserted from the server side: `select current_database()` = `solus_sol`.                                                                                                                                                                                                                                                                                          |
| Alembic revision    | `a32000000006`: `alembic current` gave `a32000000006 (head) (mergepoint)` and `alembic heads` gave `a32000000006 (head)`. Nothing applied. The harness itself read `alembic_version` = `a32000000006`.                                                                                                                                                                                                    |
| Redis               | `redis://127.0.0.1:6390/0`, the branch container `solus-redis-321` (`redis-cli ping` returned `PONG`)                                                                                                                                                                                                                                                                                                     |
| Entry used          | `POST /api/v1/projects/{project_id}/bench/sessions` with `{mode: real, config: {provider: replay, recording: "serial_fake_arm_stall.json", driver_id: "lb06", robot_entity_id, realtime: true}}`. It ran in process through `httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings, engine)))`, with no listening socket. The app lifespan was not run, as in the tests' `app` fixture. |
| Harness             | `/home/beeboss/Solus/.superpowers/sdd/pasted-content-id-24a5-sol-precious-pillow/acceptance/p2_accept_live.py`. Raw evidence is beside it in `p2_accept_live_result.json` (393 KB): every log line, tick, window, hear, live frame, poll body and ledger row.                                                                                                                                             |
| Command that ran it | `cd /home/beeboss/Solus/packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' uv run --frozen --no-sync python /home/beeboss/Solus/.superpowers/sdd/pasted-content-id-24a5-sol-precious-pillow/acceptance/p2_accept_live.py`                                                                |

## Environment recipe as executed

1. **Database.** `solus_sol` already existed (P1 created it); nothing was created, dumped or migrated. Baseline as read by the harness: 2 users, 6 `credit_ledger` rows, 0 findings. Docker showed `solus-db-1` and `solus-redis-321` up. Neither was started, stopped or touched beyond these connections.
2. **Environment.** The two variables were exported per process, on the command line only; the interactive shell held 0 `SOLUS_*` names (`env | grep -c ^SOLUS_` gave 0). The harness refuses to start unless the process holds exactly `SOLUS_DATABASE_URL` and `SOLUS_REDIS_URL` with the prescribed values. `SOLUS_TEST_DATABASE_URL` was set only on the later pytest command line.
3. **Alembic.** Run from `packages/api` with `SOLUS_DATABASE_URL` inline as `uv run --frozen --no-sync alembic current` / `heads`. Results are in the table above.
4. **Settings, in code:**
   - `Settings(_env_file=None, supabase_jwt_secret=<secrets.token_urlsafe(32), per run>, supabase_jwt_audience="authenticated", rate_limit_per_minute=100_000, write_rate_limit_per_minute=100_000, sync_inline=True, bench_replay_root=Path("/home/beeboss/Solus/livebench/tests/fixtures"), fingerprint_embedding_enabled=False, artifact_local_root=<a TemporaryDirectory removed at exit>)`.
   - `database_url` and `redis_url` resolved from the two exported variables (asserted equal), and `app_env` = `dev`.
5. **App.** `create_app(settings=settings, engine=create_async_engine(solus_sol))`, as `tests/conftest.py::app` builds it. Then:
   - `hardware_connections.owner = RuntimeOwner(home=<tmp>, location=<tmp>)`, as the fixture does, so nothing under `~/.solus` was touched.
   - `agent_runner = LlmRunner(adapters={anthropic, google, openai: refusing})`.
   - Before any session (M88): `app.state.narrator._complete = functools.partial(solus_api.orchestration.gateway.complete, adapters={anthropic, google, openai: scripted})`. The recorded value was `functools.partial(solus_api.orchestration.gateway.complete, adapters=['anthropic', 'google', 'openai'])`. The narrator's timers were the shipped ones: `debounce 10.0 s`, `interval 60.0 s`.
6. **Probes.** These record only; each is an instance-attribute wrapper that calls the original:
   - the session manager's evaluator factory, which wraps the built evaluator's `tick` and `_evaluate`;
   - the narrator's `hear`;
   - the telemetry plumbing's `ingest`;
   - one root logging handler at INFO (sqlalchemy, asyncio and httpcore raised to WARNING);
   - one Redis subscriber on the project's channel `solus:live:project:<project>`, which saw every live frame.
7. **Order of steps.**
   - Pytest guard in its own call (no pytest running). Then the harness, one process, about 67 s.
   - The session was stopped through its route at t = 61.000 (`aclose_all` at shutdown found nothing active). The shipped narrator was then closed, as the app's shutdown does.
   - Then the item-4 batch, Dismiss and Resolve.
   - After the harness: the pytest guard again, the API proxies in one pytest process, then the desktop vitest.

## Why no real provider was reachable (four independent layers)

1. **Scripted narration adapter, through the real gateway (M88).**
   - Every provider the catalog can route to (`anthropic`, `google`, `openai`) maps to the scripted adapter. Narration's `complexity=standard type=general` routed to `provider=openai model=gpt-5.6-sol role=openai_standard`.
   - The gateway's own path ran: the frequency cap on Redis, the spend gate on the DB, `model call start` / `model call done`, and the debit that wrote the ledger row.
   - **Scripted calls: 1 in the live session** (t = 16.365), plus 1 in the item-4 batch run after the live counts were taken (t = 62.130).
2. **Refusing adapters on `app.state.agent_runner`** (all three providers): **reached 0 times**. P2 makes no SOL turn.
3. **No credentials in the process.**
   - `_env_file=None`; `secrets_key` unset, `aws_region` None, `supabase_url` None, `sentry_dsn` unset.
   - `type(app.state.secret_store) == InMemorySecretStore` was asserted, and the app logged `No secret store configured (SOLUS_SECRETS_KEY / SOLUS_AWS_REGION unset) — using in-memory store.`
   - `fingerprint_embedding_enabled = False`. No key was seeded, read or printed, and the JWT secret was generated per run.
4. **Egress, bind and spawn guard.**
   - `socket.socket.connect`/`connect_ex`/`sendto`/`bind`/`listen`, `socket.getaddrinfo`, `subprocess.Popen.__init__` and `os.fork`/`forkpty`/`posix_spawn`/`posix_spawnp`/`system` were wrapped before anything was imported except `os`, `socket`, `subprocess`, `sys`, `time`, `typing` and `collections.abc`.
   - Only `127.0.0.1`/`::1` on ports 5432 and 6390 may connect, and only `localhost`/loopback may be resolved. Every attempt is listed in the raw JSON. The loop was `asyncio.unix_events._UnixSelectorEventLoop`, so every connect passes the wrapper.
   - **Observed: 8 attempts.** 7 were allowed: `resolve localhost:5432` ×2, `connect 127.0.0.1:5432` ×2 and `connect 127.0.0.1:6390` ×3 (the app's client and the harness's subscriber).
   - **1 was denied:** `bind ('::1', 0)` at t = −1.51, during imports, before the first DB connection. It is urllib3's import-time IPv6 probe (`urllib3/util/connection.py:137 HAS_IPV6 = _has_ipv6("::1")` → `:127 sock.bind((host, 0))`), which catches the error and sets `HAS_IPV6 = False`. It was attributed in a separate import-only process with the same denial (no DB, no Redis), which printed that stack. It is not egress, and no port was bound.
   - **Spawn attempts: 0. Listen attempts: 0.**

Counts asked for:

| Count                                                            | Live session       | Whole run (after the item-4 batch) |
| ---------------------------------------------------------------- | ------------------ | ---------------------------------- |
| Scripted narration calls                                         | **1**              | 2                                  |
| Refusing-adapter reaches                                         | **0**              | 0                                  |
| `model call start … purpose=narration` lines                     | **1** (t = 16.359) | 2 (+ t = 62.127)                   |
| `credit_ledger` `usage` rows with `attrs.purpose == "narration"` | **1** (−3)         | 2 (+ −2)                           |

## Seed (fresh, nothing reused)

- **User** `01a17f83-9285-7c61-aa48-e6421e8dae50`.
  - Its token was minted as `tests/conftest.py::make_token` does. `/users/me` provisioned the user and its one-time `trial_grant` of 1000.
  - The user is in Guide mode: the narration system text carried `Guide mode`. The `/users/me` body has no `sol_mode` key.
- **Team** `01a17f83-92b2-7d09-811b-d5bb21c79f1e` and **project** `01a17f83-92c2-7208-b4d5-522de1d6bbf2`, created through `POST /api/v1/teams` and `POST /api/v1/teams/{id}/projects`.
- **Fake arm** via `tests/fixtures/fake_arm.py::seed_fake_arm(db, project_id, user_id=None)`:
  - robot `2fde6f15-72aa-4e0d-bf5b-b0c9720d4c90`, brain `98da27eb-d322-4ea4-968e-d3bb81415af7`, bus `724895b8-f3bd-4deb-8530-760a5f451776`, code_file `80a186da-387c-496f-a0ac-796849deaf47`;
  - parts 1..6: `bc8a0541-ca87-4ea0-963d-9176b99010df`, `cde89550-a705-4da9-ad11-b55dfc1faaf7`, `9a01dd6e-65d3-459e-9ee2-0c9d6fb67fa4` (servo 3), `e250ab87-e057-435b-8897-7bb9a73371f5`, `50009041-6d65-4320-8e24-1972e5294bfe` (actuator 5), `b755e653-b494-4148-8dac-2d06228f2c7e`.
- **Session** `e6e09b71-2a00-4e6c-af11-2a91b3b07035`.
  - `POST` gave 201 in 0.041 s: `provider replay`, `mode real`, `status active`, `label "Replay serial_fake_arm_stall.json as Fake arm"`, `device {device_ref: usb:FAKE-ARM-0001, driver_id: lb06, replay: true}`, `robot_entity_id` = the robot.
  - The evaluator the shipped factory built has `cpu_budget_ms 20`, `cpu_budget_ms_per_part 10`, `tick_seconds 1.0` and 17 rules. Its `on_raised` is bound to the owner.
- **Pacing (real time).**
  - The first packet was ingested at t = 0.020 (event 0.00 s).
  - Event 10/20/30/40/50 s arrived at t = 9.999/19.999/30.003/40.033/49.999.
  - The last packet arrived at t = 59.95 (event 59.95 s). 7200 packets in all, every one resolved; the session counts at the stop were `{ingested: 7200, unresolved: 0}`.

## Item 1: stall within 2 s, one finding, blame and causes

The 8 s poll was `GET /api/v1/projects/{p}/findings?status=open&robot=2fde6f15-…` at t = 8.000: 200, 2 open, `meta {limit: 100, has_next: false}`. The session reported `active, {ingested: 966, unresolved: 0}`.

```
tracking_error_stall | primary subject servo 3 | critical | count 2 | open
rail_sag_correlated  | primary subject bus     | warning  | count 1 | open
```

The servo-3 finding at its first raise was tick 6, committed at t = 6.331, version 1, count 1. Its first-raise evidence (`causes` listed separately below) was:

```json
{
  "also": ["current_over_rating"],
  "unit": "deg",
  "warn": 1.6,
  "bound": 2.0,
  "error": 45.034,
  "limit": 2.0,
  "samples": 21,
  "position": 30.015,
  "robot_id": "2fde6f15-72aa-4e0d-bf5b-b0c9720d4c90",
  "code_site": {
    "line": 13,
    "path": "fw/fake_arm.ino",
    "entity_id": "80a186da-387c-496f-a0ac-796849deaf47",
    "source_id": null
  },
  "commanded": 75.0,
  "current_a": 2.804,
  "tolerance": 0.5,
  "session_id": "e6e09b71-2a00-4e6c-af11-2a91b3b07035",
  "window_end": "2026-10-25T00:00:06+00:00",
  "warn_source": "derived",
  "current_unit": "A",
  "window_start": "2026-10-25T00:00:05+00:00",
  "bounds_source": "config",
  "window_seconds": 1.0
}
```

Headline: `servo 3 (joint 3) stalls at 30.02 deg against a 75.0 deg command, drawing 2.804 A (rating 2.0 A)`. The causes' kinds and order were the same at the first raise and at the t = 62 read. The texts below are the latest raise's, as `GET /findings/{id}` returned them:

1. `mechanical_load`, for "the position held within 0.5 deg for 1.0 s while drawing 2.417 A".
2. `software_command`, for "the 75.0 deg command stays 45.02 deg from the held position", against "the 75.0 deg command is inside the -150.0 to 150.0 deg limit".
3. `actuator`, for "drawing 2.417 A at a standstill fits a jam inside the actuator as well".

| Assertion                                                                                          | Observed                                                                                                                                                                               |     |
| -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| packets reach the arm's parts before anything else                                                 | 966 ingested, 0 unresolved at t = 8.0; 7200/0 at the stop                                                                                                                              | ✅  |
| exactly one open finding whose primary subject is servo 3, at ~8 s                                 | 1 (the other open one is the bus's `rail_sag_correlated`, warning)                                                                                                                     | ✅  |
| rule, severity, status                                                                             | `tracking_error_stall`, critical, open                                                                                                                                                 | ✅  |
| within 2 s                                                                                         | evidence window_end 6.00 − onset 5.00 = **1.00 s** of event time. Wall: committed t = 6.33, the onset reached the process at t ≈ 5.02, so 1.31 s.                                      | ✅  |
| current vs rating, source `config`                                                                 | `current_a` 2.804 > `bound` 2.0 (`limit` 2.0), `bounds_source` = `config`                                                                                                              | ✅  |
| other rules on servo 3 fold into `evidence.also` (expected `current_over_rating`, `time_to_limit`) | `["current_over_rating"]` on all 5 raises; `time_to_limit` absent                                                                                                                      | ❌  |
| the bus and brain among the subjects                                                               | `subjects` = [servo 3 `9a01dd6e…`, bus `724895b8…`, brain `98da27eb…`] exactly                                                                                                         | ✅  |
| `evidence.code_site` from the `commands` edge                                                      | `{entity_id: code_file 80a186da…, source_id: null, path: fw/fake_arm.ino, line: 13}` (seed edge `fw/fake_arm.ino:13` for part 3)                                                       | ✅  |
| `evidence.causes` ranked                                                                           | kinds `[mechanical_load, software_command, actuator]`                                                                                                                                  | ✅  |
| `robot_id` and `session_id` in the evidence                                                        | the robot and this session                                                                                                                                                             | ✅  |
| the bus's sag at the same tick                                                                     | `rail_sag_correlated` on the bus, tick 6, t = 6.33, warning, evidence window 1.25 → 6.25 event s, `current_a` 2.804, correlation −0.687, voltage drop 0.323 V, scope `rail`, 5 sharers | ✅  |

**Why `time_to_limit` did not fold in.** These are numbers, not guesses. The shipped `prediction_rules.trend_of`, with its constants (10 s fit, at least 10 samples over at least 5 s, r² ≥ 0.5, the line under the 2.0 A rating), was run offline over the recording's `servo3.current`.

- The current forecast fires only for windows ending **6.40–6.95 event s**:
  - at 6.35 the line is at 1.604 A with r² 0.496 (no hit);
  - at 6.40 it is at 1.643 A with r² 0.508 (hit);
  - at 6.95 it is at 1.985 A with r² 0.613 (hit);
  - at 7.00 it is at 2.011 A, already over the rating (no hit).
- The test's integer grid ends a window at 6.95, inside the band, which is why `test_replayed_stall_…` sees `also == [current_over_rating, time_to_limit]`.
- In real time this run's ticks fell at t = 6.214 and 7.331. Their windows ended about 6.25 event s (line 1.519 A, r² 0.473) and about 7.30–7.40 event s (line 2.153–2.196 A, over the rating), straddling the band.
- With a mean tick period of 1.088 s and a band 0.55 s wide, roughly half of real-time runs would fold it in. That is an estimate, not a measurement.

## Item 2: 60 s gives one node per condition, count rising (R12)

| Condition (rule @ primary subject)                  | First tick, t | Ticks that raised it | Final count | Gaps    |
| --------------------------------------------------- | ------------- | -------------------- | ----------- | ------- |
| `tracking_error_stall` @ servo 3                    | 6, t = 6.33   | 6, 7, 8, 9, 10       | 5           | none    |
| `rail_sag_correlated` @ bus                         | 6, t = 6.33   | 6                    | 1           | none    |
| `time_to_limit` @ servo 3                           | 19, t = 20.27 | 19, 20               | 2           | none    |
| `temp_trend_to_limit` @ servo 3                     | 21, t = 22.50 | 21 … 56, every tick  | 36          | none    |
| `sensor_frozen` @ actuator 5 (the test's "servo 5") | 29, t = 31.24 | 29, 31 … 56          | 27          | tick 30 |
| `tracking_error_stall` @ servo 2                    | 38, t = 41.15 | 38, 39, 40, 41, 42   | 5           | none    |

Counts at the four polls, from `GET /findings?status=open&robot=` with the DB's `version` alongside:

| Poll (t)                | Open | stall@3 (count/version) | sag@bus | ttl@3 | temp_trend@3 | frozen@5 | stall@2 | Session ingested |
| ----------------------- | ---- | ----------------------- | ------- | ----- | ------------ | -------- | ------- | ---------------- |
| 8.000                   | 2    | 2 / 2                   | 1 / 1   |       |              |          |         | 966              |
| 25.000                  | 4    | 5 / 6                   | 1 / 2   | 2 / 2 | 3 / 3        |          |         | 3006             |
| 45.000                  | 6    | 5 / 6                   | 1 / 2   | 2 / 2 | 21 / 21      | 12 / 12  | 4 / 4   | 5406             |
| 62.001 (after the stop) | 6    | 5 / 6                   | 1 / 2   | 2 / 2 | 36 / 36      | 27 / 27  | 5 / 5   | 7200 (ended)     |

| Assertion                                                            | Observed                                                                                                |     |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | --- |
| one node per condition, not one per tick                             | 6 findings, 6 distinct (rule, primary subject); each id kept its own node for the minute                | ✅  |
| a raise per tick, no more                                            | `count` equals the number of raising ticks for all 6. There were 56 ticks with exactly one window each. | ✅  |
| the stall rises a tick at a time, then holds still                   | 1 → 5 over ticks 6–10, then unchanged for 46 ticks                                                      | ✅  |
| the stall 1 → 4 (R12's wording)                                      | **1 → 5**                                                                                               | ❌  |
| the thermal condition rises to the end of the minute                 | `temp_trend_to_limit` 1 → 36, in every tick from 21 to 56                                               | ✅  |
| the frozen condition rises to the end of the minute                  | `sensor_frozen` 1 → 27 over ticks 29–56, so it reached the end                                          | ✅  |
| the frozen condition rises one more every tick                       | missed tick 30 (27 raises in 28 ticks)                                                                  | ❌  |
| `stream_gap` absent (stopped at 61.000, 1.05 s after the last frame) | no `stream_gap` finding                                                                                 | ✅  |

The stall's five raises have evidence windows 5.00→6.00, 5.30→6.30, 6.40→7.40, 7.50→8.50 and 8.55→9.55 event s, so five real-time windows overlapped the 5 s stall (5.0–10.0 s). The test's integer grid gives four: windows end at 6.95, 7.95, 8.95 and 9.95, and the 5.95 window is too early for the 1 s hold. The rise-then-hold shape is the same; the number depends on where the ticks fall. The servo 2 stall shows the same five.

The frozen gap lines up with the shipped budget. Tick 30's window took 60.1 ms against a 60 ms budget: 16 of the 17 rules ran whole, and 4 rule runs were skipped, logged as `window evaluator over its cpu budget of 60 ms: skipped 4 rule runs …` at t = 32.34. It is the only tick between 29 and 56 in which a rule was cut, and the only one in which `sensor_frozen` was not raised. The next tick raised it again. The harness did not record which rule was cut, so "its run for actuator 5 was among the 4 skipped" is an inference. It matches the "a tick late at most" behaviour that `test_five_distinct_findings_inside_40s` allows.

## Item 3: five distinct findings in 40 s, one narration call

Timeline:

| t                          | What                                                                                                                                                                                                                      |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6.330                      | first `hear`: [stall@servo 3, rail_sag@bus], owner = the seeded user, robot = the robot (43 hears in all, one per raising tick)                                                                                           |
| 7.41 … 10.64               | four more hears, all the stall's id (re-raises)                                                                                                                                                                           |
| 16.359                     | `model call start call_id=b3254681-110f-4858-880b-2cff960971f9 provider=openai model=gpt-5.6-sol role=openai_standard complexity=standard type=general purpose=narration turn_id=None`                                    |
| 16.365                     | scripted adapter answers. `model call done call_id=b3254681-110f-4858-880b-2cff960971f9 provider=openai model=gpt-5.6-sol role=openai_standard tokens_in=2511 tokens_cached_in=0 tokens_out=95 duration_ms=6`             |
| 16.384 / 16.389            | `finding annotated … finding=01a17f83-ad3d-…` (the stall) and `… finding=01a17f83-ad4a-…` (the sag)                                                                                                                       |
| 16.391                     | `finding narration wrote 2 findings robot=2fde6f15-72aa-4e0d-bf5b-b0c9720d4c90`. The stall's `finding.updated` frame arrives on `solus:live:project:<p>`; its count last moved at 10.64, so this is the explanation fill. |
| 20.27, 22.50, 31.24, 41.15 | `time_to_limit`@3, `temp_trend_to_limit`@3, `sensor_frozen`@5 and `tracking_error_stall`@2 are heard; no call follows                                                                                                     |
| 62.036                     | live counts snapshot: 1 call, 1 `model call start` line, 0 refusing reaches                                                                                                                                               |
| ~62.04                     | the narrator is closed with its queue: 4 ids, task armed, `called_at` t = 16.359, so the earliest next flush is **t = 76.359**                                                                                            |

What the scripted adapter received:

- `query` was the fenced block. The fence was `<<<SOLUS-DATA 7414a7a2a9006d37 kind=robot_findin…` / `<<<END-SOLUS-DATA 7414a7a2a9006d37>>>`.
- The conversation had 1 message and 0 tools. The system text said `Guide mode`; `max_tokens` was 4096 and `reasoning_effort` was `medium`.
- The packet had the keys `envelopes`, `errors`, `findings` and `graph`, and was 8,831 characters against the 32,000 cap. It held 24 envelopes (6 parts × current/position/temperature/voltage), 13 graph edges and 0 prior errors.
- The findings, in packet order, were `tracking_error_stall` / critical / `servo 3 (joint 3)` / count 5 and `rail_sag_correlated` / warning / `fake bus` / count 1.

The adapter replied:

```json
[
  {
    "explanation": "servo 3 (joint 3) is flagged by tracking_error_stall, raised 5 times so far. It draws 2.417 A while the evidence holds.",
    "causes_ranked": ["mechanical_load", "software_command", "actuator"]
  },
  {
    "explanation": "fake bus is flagged by rail_sag_correlated, raised 1 times so far. It draws 2.804 A while the evidence holds.",
    "causes_ranked": ["electrical_supply"]
  }
]
```

`GET /api/v1/projects/{p}/findings/01a17f83-ad3d-71c2-8970-735cff94db3e` at t = 62.034 returned 200 (evidence omitted, shown under item 1):

```json
{
  "id": "01a17f83-ad3d-71c2-8970-735cff94db3e",
  "rule_id": "tracking_error_stall",
  "severity": "critical",
  "source": "observer",
  "status": "open",
  "headline": "servo 3 (joint 3) stalls at 30.02 deg against a 75.0 deg command, drawing 2.417 A (rating 2.0 A)",
  "explanation": "servo 3 (joint 3) is flagged by tracking_error_stall, raised 5 times so far. It draws 2.417 A while the evidence holds.",
  "detail": "",
  "causes_ranked": ["mechanical_load", "software_command", "actuator"],
  "robot_id": "2fde6f15-72aa-4e0d-bf5b-b0c9720d4c90",
  "subjects": [
    "9a01dd6e-65d3-459e-9ee2-0c9d6fb67fa4",
    "724895b8-f3bd-4deb-8530-760a5f451776",
    "98da27eb-d322-4ea4-968e-d3bb81415af7"
  ],
  "count": 5,
  "first_seen": "2026-10-27T22:38:18.426454+00:00",
  "last_seen": "2026-10-27T22:38:22.760439+00:00",
  "matrix_cell": "software->mechanical",
  "domain": "electrical",
  "dismissed_until": null,
  "created_at": "2026-10-27T22:38:18.429895Z",
  "updated_at": "2026-10-27T22:38:28.524899Z",
  "subject_entities": [
    { "id": "9a01dd6e-…", "kind": "part", "name": "servo 3 (joint 3)" },
    { "id": "724895b8-…", "kind": "hardware_bus", "name": "fake bus" },
    { "id": "98da27eb-…", "kind": "hardware_brain", "name": "fake brain" }
  ]
}
```

`FindingOut` carries no `version`, so the DB was read alongside: version **6** at count 5. At the 8 s poll it was version 2 at count 2. Each raise bumps the version once, and the narration's `annotate_finding` bumped it once more. The sag went from version 1 to 2 at count 1.

The `credit_ledger` rows for the session owner at t = 62.036:

```json
{"type": "trial_grant", "amount": 1000, "balance_after": 1000, "key": "trial-grant:01a17f83-9285-7c61-aa48-e6421e8dae50", "attrs": {"reason": "trial_grant"}}
{"type": "usage", "amount": -3, "balance_after": 997, "key": "b3254681-110f-4858-880b-2cff960971f9",
 "attrs": {"role": "openai_standard", "call_id": "b3254681-110f-4858-880b-2cff960971f9", "purpose": "narration", "tokens_in": 2511, "model_name": "gpt-5.6-sol", "tokens_out": 95},
 "user_id": "01a17f83-9285-7c61-aa48-e6421e8dae50", "created_at": "2026-10-27T22:38:28.509171+00:00"}
```

The global `credit_ledger` count went 6 → 7 (the trial grant at provisioning) → 8 (this row).

| Assertion                                                             | Observed                                                                                                                                                                    |     |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| five distinct findings inside 40 s                                    | five by t = 31.24 (2 at 6.33, 3 at 20.27, 4 at 22.50, 5 at 31.24); the sixth at 41.15                                                                                       | ✅  |
| each by its deadline in the scenario, a tick late at most (`TOLD_BY`) | evidence end (event s) against the deadline: stall@3 6.00 ≤ 7, sag 6.25 ≤ 7, ttl 20.20 vs 20 (+0.20), temp_trend 22.40 vs 22 (+0.40), frozen 31.15 ≤ 32, stall@2 41.00 ≤ 42 | ✅  |
| one narration call for those five (by 40 s)                           | 1 scripted call (t = 16.365); still 1 at t = 45 and t = 62                                                                                                                  | ✅  |
| one `model call start … purpose=narration` line                       | 1 in the live session, `turn_id=None`                                                                                                                                       | ✅  |
| one `purpose=narration` ledger row                                    | 1 `usage` row, −3 credits, `call_id` equal to the log line's, no `turn_id` key                                                                                              | ✅  |
| billed to the owner identity                                          | `user_id` = the session owner (the user who started the session), `turn_id` None                                                                                            | ✅  |
| shipped debounce                                                      | call 10.029 s after the first hear                                                                                                                                          | ✅  |
| shipped interval holds the rest                                       | 4 ids heard after the call stay queued; earliest flush t = 76.36 (the debounce alone would have flushed at ≈30.3)                                                           | ✅  |
| `explanation` and `causes_ranked` land on the batch                   | both findings: explanation 119 and 109 characters, `causes_ranked` a permutation of their evidence's cause kinds, `detail` ""                                               | ✅  |
| `finding.updated` observable                                          | the frame at t = 16.391; version 6 = count 5 + 1; explanation non-empty on `GET /findings/{id}`                                                                             | ✅  |
| no "reply unusable" warning                                           | the narration logger wrote only the 2 INFO "wrote" lines                                                                                                                    | ✅  |
| refusing adapters reached                                             | 0                                                                                                                                                                           | ✅  |

Live frames on the project channel numbered 84: 6 `finding.raised`, 75 `finding.updated`, 1 `finding.resolved` and 2 `graph.changed` (Dismiss and Resolve). The servo-3 stall's frames were raised 6.331; updated 7.41, 8.503, 9.577 and 10.639 (counts); updated 16.391 (narration); resolved 62.4.

## Item 4: a non-grounded number is rejected (R27/R28)

This was a second scripted batch, run after the live counts were snapshotted and the shipped narrator closed. It used the same class (`Narrator`) on the app's sessionmaker, secret store and Redis, with test-scale timers (debounce 0.05 s, interval 0.6 s). It went through `functools.partial(gateway.complete, adapters=<the same scripted adapter, an "ungrounded" reply>)`. It heard the first two open, un-narrated, non-info findings: `sensor_frozen`@actuator 5 and `temp_trend_to_limit`@servo 3. This made one call at t = 62.130 (`model call start … purpose=narration turn_id=None`, `tokens_in=1457 tokens_out=117`). The ledger row was −2, `call_id 31bc226e-27df-463f-adc7-6d53e4ac220c`, and the packet was 4,616 characters.

The scripted reply for the first finding (the second is the same, for `temp_trend_to_limit`):

```json
{
  "explanation": "actuator 5 (joint 5) is flagged by sensor_frozen. The motor would need 37.5 A to clear it.",
  "headline": "actuator 5 (joint 5) needs attention (sensor_frozen)",
  "causes_ranked": ["actuator", "electrical_supply"]
}
```

Read back through `GET /findings/{id}`, both returned 200:

```json
{"rule_id": "sensor_frozen", "severity": "warning",
 "headline": "actuator 5 (joint 5) position reads exactly 49.83 deg for 600 samples while its command moves 20.0 deg",
 "explanation": "actuator 5 (joint 5) is flagged by sensor_frozen.",
 "detail": "suggested headline: actuator 5 (joint 5) needs attention (sensor_frozen)\nnot grounded: The motor would need 37.5 A to clear it.",
 "causes_ranked": ["actuator", "electrical_supply"]}
{"rule_id": "temp_trend_to_limit", "severity": "warning",
 "headline": "servo 3 (joint 3) temperature 67.99 degC rising 0.1807 degC/s: at the 70.0 degC limit in about 2 s",
 "explanation": "servo 3 (joint 3) is flagged by temp_trend_to_limit.",
 "detail": "suggested headline: servo 3 (joint 3) needs attention (temp_trend_to_limit)\nnot grounded: The motor would need 37.5 A to clear it.",
 "causes_ranked": ["mechanical_load", "actuator"]}
```

Calling the shipped `grounded_numbers` directly, on the packets the scripted adapter received:

- `grounded_numbers("The motor would need 37.5 A to clear it.", <item-4 packet>)` is **False**.
- `grounded_numbers("actuator 5 (joint 5) is flagged by sensor_frozen.", …)` is True, and so is the `temp_trend_to_limit` sentence.
- From the live batch, `grounded_numbers("It draws 2.417 A while the evidence holds.", <live packet>)` and `"It draws 2.804 A …"` are both True. That is why the live batch's `detail` is empty.

| Assertion                                                                        | Observed                                                                           |     |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --- |
| the sentence with an ungrounded number moves to `detail`, marked `not grounded:` | the `not grounded: The motor would need 37.5 A to clear it.` line on both findings | ✅  |
| the grounded sentences are the explanation                                       | only the first sentence each                                                       | ✅  |
| a proposed headline goes to `detail`, never over the headline                    | the `suggested headline: …` line; the stored headline is the rule's                | ✅  |
| grounded numbers with units survive (live batch)                                 | "2.417 A", "2.804 A" and the bare counts were kept, `detail` ""                    | ✅  |

## Item 5: Dismiss creates nothing, Resolve creates one `errors` entry (C3)

| Step                                                                 | Route and status                             | `.solus` section counts (errors)                                                           | Graph (entities/edges) |
| -------------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------ | ---------------------- |
| before                                                               | `GET /solus` 200                             | goals 0, constraints 0, documentation 0, **errors 0**, environment 9, members 0, history 0 | 45 / 83                |
| Dismiss the bus's `rail_sag_correlated` (`01a17f83-ad4a-…`), no body | `POST /findings/{id}/dismiss` **200**        | identical, **errors 0**                                                                    | 45 / 83                |
| Resolve the servo-3 stall with a note                                | `POST /findings/{id}/resolve {note}` **200** | **errors 1**, the rest identical                                                           | 46 / 84                |

- The Dismiss response had `status: dismissed` and `dismissed_until: 2026-10-28T22:39:14.470356+00:00` (24 h). `GET /findings/{id}` afterwards showed `dismissed`, and the explanation was kept.
- The Resolve response had `status: resolved`, `entry_id: 01a17f84-885f-7017-85d9-5b1ef53cdbc3`, `fixed_by_edge_id: null` (no `fix_ref` was sent) and `count 5`. `GET /findings/{id}` afterwards showed `resolved`, with the explanation and `causes_ranked` kept.
- The one `errors` entry read back through `GET /api/v1/projects/{p}/solus`:

```json
{
  "id": "01a17f84-885f-7017-85d9-5b1ef53cdbc3",
  "section": "errors",
  "subsection": null,
  "kind": "text",
  "author": "user",
  "text": "Resolved tracking_error_stall: servo 3 (joint 3) stalls at 30.02 deg against a 75.0 deg command, drawing 2.417 A (rating 2.0 A)\n\nFix: Re-seated the servo 3 horn and confirmed the firmware stall timeout (P2 acceptance).",
  "entity_id": "01a17f84-8860-7b58-b225-3c6c2de136d1",
  "payload": {
    "count": 5,
    "status": "resolved",
    "fix_ref": null,
    "entity_id": "9a01dd6e-65d3-459e-9ee2-0c9d6fb67fa4",
    "last_seen": "2026-10-27T22:38:22.760439Z",
    "dedupe_key": "d2e0a7e1651e24d272cbbb632ef52f9ef5da2a45",
    "first_seen": "2026-10-27T22:38:18.426454Z",
    "machine_id": null
  },
  "created_by": "01a17f83-9285-7c61-aa48-e6421e8dae50",
  "created_at": "2026-10-27T22:39:14.527338Z"
}
```

Resolve's +1 entity and +1 edge are that entry's `solus_error` node and its `contains` edge from the "Error logging" section node; there is no `fixed_by` edge. Both were read with psql.

| Assertion                                                                                                                | Observed                                                                                                                                                            |     |
| ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| Dismiss writes no `.solus` entry                                                                                         | every section count unchanged, errors 0 → 0, graph 45/83 → 45/83                                                                                                    | ✅  |
| Resolve with a note creates exactly one `errors` entry, server-side                                                      | errors 0 → 1. The entry id equals `entry_id`; the text is `Resolved <rule>: <headline>\n\nFix: <note>`; the `ErrorMeta` payload blames servo 3 with status resolved | ✅  |
| desktop: Dismiss writes no `.solus` entry; Resolve is `resolveFinding` with no client write; File is one `addSolusEntry` | `findingActions.test.ts` (7) passed in the desktop proxy below                                                                                                      | ✅  |

## Item 6: the live proof, summarised

- **Finding count over time:**
  - by tick: 0 → 2 at t = 6.33 → 3 at 20.27 → 4 at 22.50 → 5 at 31.24 → 6 at 41.15;
  - at the polls: 2 open at 8 s, 4 at 25 s, 6 at 45 s, 6 at 62 s;
  - 13 of 56 ticks raised nothing (ticks 1–5 and 11–18).
- **The servo-3 finding's evidence keys at t = 62:** `also`, `bound`, `bounds_source`, `causes`, `code_site`, `commanded`, `current_a`, `current_unit`, `error`, `items` (5 raises), `limit`, `position`, `robot_id`, `samples`, `session_id`, `tolerance`, `unit`, `warn`, `warn_source`, `window_end`, `window_seconds`, `window_start`. The first raise had the same keys without `items`.
- **`credit_ledger` rows with `attrs.purpose == "narration"`:**
  - one from the live session: `usage −3`, `call_id b3254681-110f-4858-880b-2cff960971f9`, `tokens 2511/95`, `gpt-5.6-sol` / `openai_standard`;
  - one from the item-4 batch: `usage −2`, `call_id 31bc226e-27df-463f-adc7-6d53e4ac220c`, `tokens 1457/117`.
  - The final balance is 995. Neither row has a `turn_id`.
- **The vendor regex** over the seed, the generator and `livebench/findings/**` passed as `tests/test_stall_replay.py::test_fixture_and_shared_code_carry_no_vendor_name`, in the proxy run below.

### The per-window rule time line and every `window evaluator` / `finding narration` line

Production code logs no per-window time line; it logs only over-budget warnings. The harness timed each `_evaluate` call (one per window) and wrote this line at the end:

```
rule time per window (live, real time, shipped budget), 6 parts over a context of up to 30 s: median 35.0 ms, p95 60.1 ms, max 60.2 ms over 56 windows in 56 ticks; windows over budget 4; skipped rule runs 21 (the shipped per-window budget for 6 parts is 60 ms)
```

- The per-window time grows with the context: 1.7, 2.7, 3.6, 9.4, 12.5, 16.3, 17.1, 19.5, 20.9 ms over ticks 1–9, then about 35–38 ms. The mean is 33.4 ms and the minimum 1.7 ms. The budget was 60 ms in every window (6 parts from the first tick).
- Windows at or over the budget: tick 30 (60.1 ms, 4 skipped), tick 40 (60.1 ms, 0 skipped), tick 43 (60.2 ms, 6 skipped) and tick 48 (60.1 ms, 11 skipped).
- The time is the wall time of `_evaluate`. The replay pump runs in threads of the same process.
- Cadence: 56 ticks between t = 0.999 and t = 60.815. Periods ran from 1.020 to 1.181 s with a mean of 1.088 s; each tick took 19–180 ms. The ticker sleeps a full period after each tick, as its own comment says.

```
32.340 WARNING solus.livebench.findings.window_evaluator | window evaluator over its cpu budget of 60 ms: skipped 4 rule runs project=01a17f83-92c2-7208-b4d5-522de1d6bbf2 session=e6e09b71-2a00-4e6c-af11-2a91b3b07035
46.661 WARNING solus.livebench.findings.window_evaluator | window evaluator over its cpu budget of 60 ms: skipped 6 rule runs project=01a17f83-92c2-7208-b4d5-522de1d6bbf2 session=e6e09b71-2a00-4e6c-af11-2a91b3b07035
52.146 WARNING solus.livebench.findings.window_evaluator | window evaluator over its cpu budget of 60 ms: skipped 11 rule runs project=01a17f83-92c2-7208-b4d5-522de1d6bbf2 session=e6e09b71-2a00-4e6c-af11-2a91b3b07035
16.359 INFO solus.orchestration.gateway | model call start call_id=b3254681-110f-4858-880b-2cff960971f9 provider=openai model=gpt-5.6-sol role=openai_standard complexity=standard type=general purpose=narration turn_id=None
16.365 INFO solus.orchestration.gateway | model call done call_id=b3254681-110f-4858-880b-2cff960971f9 provider=openai model=gpt-5.6-sol role=openai_standard tokens_in=2511 tokens_cached_in=0 tokens_out=95 duration_ms=6
16.391 INFO solus.agent.finding_narration | finding narration wrote 2 findings robot=2fde6f15-72aa-4e0d-bf5b-b0c9720d4c90
62.127 INFO solus.orchestration.gateway | model call start call_id=31bc226e-27df-463f-adc7-6d53e4ac220c provider=openai model=gpt-5.6-sol role=openai_standard complexity=standard type=general purpose=narration turn_id=None   (item-4 batch)
62.130 INFO solus.orchestration.gateway | model call done call_id=31bc226e-27df-463f-adc7-6d53e4ac220c provider=openai model=gpt-5.6-sol role=openai_standard tokens_in=1457 tokens_cached_in=0 tokens_out=117 duration_ms=3   (item-4 batch)
62.159 INFO solus.agent.finding_narration | finding narration wrote 2 findings robot=2fde6f15-72aa-4e0d-bf5b-b0c9720d4c90   (item-4 batch)
```

There were no other lines from either logger: no tick failures, no dropped samples, no rule failures, no narration warnings. INFO-and-above lines by logger: httpx 25, p2.accept 1, solus.agent.finding_narration 2, solus.auth.admin 1, solus.connectors.secrets 1, solus.events 4, solus.graph.findings 12, solus.graph.inference 7, solus.livebench.findings.window_evaluator 3, solus.main 1, solus.orchestration.gateway 4, solus.services.environment_divergence 7, solus.services.environment_spec 7, solus_api.livebench.sessions 1.

## Proxy tests (after the live run)

Each guard ran in its own call (no pytest running). The API proxies ran in ONE process from `packages/api`, 22:45:25Z to 22:47:12Z:

```
PYTHONDONTWRITEBYTECODE=1 SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2 uv run --frozen --no-sync pytest -q -p no:cacheprovider tests/test_stall_replay.py tests/test_finding_narration.py tests/test_window_evaluator.py tests/test_sim_control.py tests/test_runs_findings.py tests/test_make_diagram_edges.py tests/test_findings.py
81 passed in 103.01s (0:01:43)
```

- The run used no `--cov`. `.coverage` md5 was `7571ebfd2af623167baf221f5af68076` before and after, and the tree was clean.
- The named proxies are all in the run:
  - `test_stall_replay.py::test_replayed_stall_raises_one_finding_within_2s_with_blame_and_causes`, `::test_sixty_seconds_is_one_node_count_rising`, `::test_five_distinct_findings_inside_40s` and `::test_fixture_and_shared_code_carry_no_vendor_name`;
  - `test_window_evaluator.py::test_one_session_one_node_count_rising`;
  - `test_finding_narration.py::test_five_findings_in_40s_one_call`, `::test_non_grounded_number_moved_to_detail` and `::test_grounding_compares_numbers_with_units_not_substrings`;
  - `test_findings.py::test_resolve_files_one_errors_entry_and_fixed_by_edge_then_reopens_on_raise`.

The desktop proxy ran from the repo root as `pnpm --filter @solus/desktop exec vitest run src/renderer/src/features/bench/findings`:

```
 ✓ src/renderer/src/features/bench/findings/findingActions.test.ts (7 tests)
 ✓ src/renderer/src/features/bench/findings/FindingCard.test.tsx (6 tests)
 ✓ src/renderer/src/features/bench/findings/FindingsPane.test.tsx (7 tests)
 ✓ src/renderer/src/features/bench/findings/useRobotFindings.test.ts (7 tests)
 Test Files  4 passed (4)
      Tests  27 passed (27)
```

One React `act(...)` warning went to stderr from `FindingsPane.test.tsx > FindingsPane live reads > refetches on the findings live key through the one stream it mounts`. The test passes.

## Deviations from the brief and observations

1. **`evidence.also` lacks `time_to_limit` (item 1, ❌).** The cause is the real-time window phase against the 0.55 s band in which the shipped current forecast can fire (6.40–6.95 event s); see item 1. This is not a defect in the fold: `coalesce` folded what fired (`current_over_rating`). If the acceptance needs `time_to_limit` in `also` every run, that needs a ruling. The options are to accept either fold, to widen the forecast's window, or to make the generator's current ramp gentler.
2. **The stall's count is 1 → 5, not 1 → 4 (item 2, ❌ literal / ✅ R12).** It is the same window-phase effect: five 1 s real-time windows overlapped the 5 s stall. The servo 2 stall also counted 5.
3. **`sensor_frozen` has one gap at tick 30 (item 2).** That tick is the only one in its span in which the shipped budget cut a rule: 4 runs were skipped in a 60.1 ms window, and the next tick raised it again. Which rule was cut was not recorded, so the link is an inference. In 56 windows there were 4 at or over 60 ms and 21 skipped rule runs (in 3 ticks); the median was 35.0 ms.
4. **Cadence.** The "1 Hz" evaluator ran 56 ticks in 60.8 s (mean period 1.088 s), because the ticker sleeps a full period after each tick.
5. **The ledger row exists.** The dispatch expected a 0-credit scripted call with no row until P8. The scripted adapter reported usage estimated from the text (about four characters a token: 2511 in, 95 out), so `compute_call_credits` (which rounds up) billed 3 credits and the gateway's debit wrote the one `purpose=narration` row the plan names. A `Usage(0, 0)` reply would have written none.
6. **Two narration calls over the whole run.**
   - The live session made exactly 1.
   - The item-4 ungrounded batch added 1 (+1 `model call start` line, +1 ledger row of −2). That batch was deliberately run after the live counts were taken, through a second `Narrator` with test-scale timers.
   - The shipped narrator was closed at about t = 62 with 4 ids pending; its second flush (due at t ≥ 76.36) never ran.
7. **`realtime: true` and the replay root in code.** The brief's item 6 text says `realtime: false` with `SOLUS_BENCH_REPLAY_ROOT=…`. Per the dispatch, the run used `realtime: true`, and `bench_replay_root` was passed as a Settings field; a third `SOLUS_*` variable would break the two-variable rule.
8. **`version` is not on `FindingOut`.** The bumped version was read from `graph_entity.version` alongside `GET /findings/{id}`.
9. **The pytest command.** It appended `tests/test_findings.py` (the brief's proxy 5, API half) to the same single process. It also added `--frozen --no-sync` and `PYTHONDONTWRITEBYTECODE=1`, so the shared `.venv`, `uv.lock` and the tree could not be touched (P1's precedent).
10. **Instrumentation is recording only.**
    - The wrappers are instance attributes that call the originals: the evaluator's `tick`/`_evaluate`, the narrator's `hear`, the plumbing's `ingest` and the session manager's factory.
    - The rule time is wall time around `_evaluate`.
    - Two extra loopback Redis connections were opened: the subscriber, and one more pooled connection.
11. **The harness had to satisfy the repository's post-write hooks** (ruff and mypy strict on any `.py` written through the editor). Its top-level names carry a `p2a` prefix, because H6 refuses a top-level name that exists anywhere in the repo.
12. **Observations, harmless:**
    - The denied urllib3 IPv6 bind probe (layer 4).
    - `SOLUS_TOOLKB_VOTE_SALT unset — using an ephemeral per-process salt …` printed to stderr at import, outside logging.
    - `/users/me` has no `sol_mode` key.
    - The bus's sag finding names servo 3 as its second subject, which is why the robot-filtered route returns it.
    - The P2-T7 review's R32 notes on make_diagram were not exercised here.

## Not verified here

- The real-provider session (Q2), and whether a real model writes grounded prose. By design there is no key and no provider.
- The Findings pane in the running desktop app; only its vitest proxies ran. `finding.updated` was observed on the Redis channel, not in a client.
- The 402/429 narration path. The owner had trial credits, and the frequency cap allowed both calls. Proxy `test_402_skips_once_logged` covers it and passed.
- How often a real-time run folds `time_to_limit` into the stall. The "about half" figure is arithmetic on the band and the tick period, not a measurement over several runs.

## Left behind

- **In `solus_sol`:**
  - the harness user (3 users, previously 2) and its team and project;
  - the fake arm: 45 entities and 83 edges in the project, 46/84 after the resolve;
  - the 6 findings (1 resolved, 1 dismissed, 4 open);
  - one `.solus` errors entry and 9 environment entries from the seed;
  - 3 `credit_ledger` rows (trial grant, −3, −2), so 9 globally, previously 6.
- **Not touched:** `solus` (the live dev DB), `solus_sol_p1` and every `solus_test_*` database except `solus_test_d7fa72c2` (the pytest run, which TRUNCATEs it as designed). No process, container or session other than the harness's own was stopped or killed.
- **Redis 6390.** The app wrote 25 `solus:envelope:<project>:…` cache keys, which had TTLs. They had all expired by 22:48:21Z (`dbsize` 0). The frequency-cap entries had also expired.
- **Files.** Only the harness, its JSON and this report, all in the git-ignored plan workspace. No tracked file changed.
