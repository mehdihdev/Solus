# P8-T3 Run the product for real (SOLUSDEV-322 plan §6 "Run the product for real")

HEAD before `fa370f38bf55df01e66adeed839bf4ded67afc9f` (branch `SOLUSDEV-322-sim-integrations`); the after-SHA is the commit that adds this file. No source file changed in this task.
Run 2026-11-09 ≈20:10Z → 20:19Z (15:10 → 15:19 local, UTC−5) on Ubuntu 24.04 aarch64. `$S` = `/tmp/claude-1000/-home-beeboss-Solus/0cf72a70-f130-49d2-9959-8bce1bad168f/scratchpad/p8t3` (scratch, not committed: raw logs, the driver scripts, the artifact store).

**Model calls: 0 scripted, 0 real.** No SOL chat turn ran here: no provider key was loaded, and P8-T1 (`P8-sim-acceptance.md`) covers the turns in process with scripted adapters. Counts: `model call start` lines in `api1.log`, `api2.log`, `worker.log` = **0 / 0 / 0**. `credit_ledger` rows on `solus_sim` since 20:10Z = **4, all `trial_grant`** (one per synthetic user this run created), **0 `usage`**. Startup log, both API runs: `SecretStore provider refs present: none` (in-memory store, `SOLUS_SECRETS_BACKEND=memory`), so a real provider call could not have been made.
No hardware and no device socket were touched. The only external network calls were `make mcp-forks` (the hash-verified pip install) and `docker run redis:7` (the image was already local).

## Verdicts

| Step                                     | Verdict                                                             | Summary                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Ports                                 | **VERIFIED**                                                        | `lsof -i :8030 -i :6391` → nothing, rc 1, before every bind and again after teardown.                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| 2. Migrations on `solus_sim`             | **VERIFIED**                                                        | `a32100000001` → `upgrade head` → `a32200000003 (head)` → `downgrade -3` → `a32100000001` → `upgrade head` → `a32200000003 (head)`; one head. `sim_session` table, `uq_sim_session_live` and `ix_graph_entity_sim_aliases` are present after the round trip.                                                                                                                                                                                                                                                                                  |
| 3. Redis                                 | **VERIFIED**                                                        | `solus-redis-322` started on :6391. The first `redis-cli ping` was refused (container still starting); the retry returned `PONG`. Removed at the end.                                                                                                                                                                                                                                                                                                                                                                                         |
| 4. API + ARQ worker                      | **VERIFIED**                                                        | API on :8030 (uv pid 407016 / uvicorn 407124; restarted later as 417735 / 417829). Worker uv pid 407954 / arq 408047, `Starting worker for 21 functions … cron:prune_sim_runs_job`. No human-only value was needed for this run; the warnings are listed below.                                                                                                                                                                                                                                                                               |
| 5. `make mcp-forks` + launcher           | **VERIFIED**                                                        | `gazebo` (and `isaac`, whose lock stamp had changed) materialized with hashes checked, in 3.7 s. Stamp = `sha256(requirements.lock.txt)` = `287b6986…`. `bin/launch` exits **78** in all three cases tested (both vars unset, `SOLUS_MCP_WORKSPACE` unset, `SOLUS_MCP_PYTHON` unset). With both set and the Harmonic env: `initialize` → `solus-gazebo 1.29.0`, `tools/list` → **13 tools**, and `probe` → `gz 8.15.0 Harmonic`.                                                                                                              |
| 6a. `GET /bench/sources`                 | **PARTIAL (finding F1)**                                            | With `SOLUS_GAZEBO_PATH` set and **no gz on PATH**, the gazebo row says `available: false, "Gazebo is not installed (no gz, ign or gzserver CLI on PATH)"`. After restarting the API with `/opt/ros/jazzy/opt/gz_tools_vendor/bin` **on PATH**, it says `available: true, "Gazebo detected (gz family)"`. The family is named, but the row is driven by `PATH` and ignores `SOLUS_GAZEBO_PATH`.                                                                                                                                               |
| 6b. Machines upsert → `attrs.simulators` | **VERIFIED (through a bridge test client, not the real companion)** | A WS client advertising only `machine.tool_versions` answered with real version lines from this host. Results: `{"gazebo": {"family": "gz", "version": "8.15.0"}, "nvidia_smi": true, …}`. With gzserver only: `classic 11.15.1`. With none: `gazebo: null`.                                                                                                                                                                                                                                                                                  |
| 6c. `POST /bench/runs/{id}/pin`          | **VERIFIED except 409 (NOT REACHED)**                               | A run was imported through `POST /bench/runs/import` (201, `origin synthetic`). Pin → 200 `pinned: true`. Pin again → 200 (idempotent). Unknown run → 404 `Run not found`. No token → 401. Another tenant → 404 `Project not found`. **409 `run_active` could not be reached over HTTP**, because a `running` run needs a live capture on an active bench session whose device matches the robot's accepted identity, and that means hardware or onboarding. Only `tests/test_sim_runs.py::test_pin_route_marks_and_is_idempotent` covers it. |
| 6d. `GET /api/v1/openapi.json`           | **PARTIAL (finding F2)**                                            | `GazeboSimConfig.family` = `enum ["classic","ignition","gz"] \| null` ✔. **`RunSummary` is not in the OpenAPI at all**, because the runs routes declare `dict[str, Any]` envelopes (the pin 200 schema is `{"type":"object","additionalProperties":true}`). So `origin: "sim"` cannot appear there. The live spec equals the committed `packages/api/openapi.json` (215 paths, 190 schemas, both equal).                                                                                                                                     |
| 7. `prune_sim_runs_job` through ARQ      | **VERIFIED**                                                        | `enqueue_job("cron:prune_sim_runs_job", _job_id="p8t3-prune-sim-runs")` → worker: `15:17:50: 0.46s → cron:prune_sim_runs_job()` / `0.01s ← cron:prune_sim_runs_job ● 0`. That is 0 payloads dropped, which is expected because `solus_sim` holds no sim-origin runs.                                                                                                                                                                                                                                                                          |
| 8. Teardown                              | **VERIFIED**                                                        | API and worker were stopped with `kill -TERM <uv pid>`. The worker reported `shutdown on SIGTERM ◆ 22 jobs complete ◆ 0 failed ◆ 0 retries`. `docker rm -f solus-redis-322` was run, and no ports were left bound. `solus-db-1` and `solus-redis-1` are untouched and still Up. `solus_sim` is left at `a32200000003`.                                                                                                                                                                                                                        |

## Findings (not fixed here; this task changes no source)

- **F1. `GET /bench/sources` ignores `SOLUS_GAZEBO_PATH`.** `livebench/src/livebench/local.py:162 _gazebo_family_on_path` uses `shutil.which` on the API process's `PATH` (`_GAZEBO_FAMILY_BINARIES` gz/ign/gzserver/gazebo). The fork and the companion resolve binaries only through `SOLUS_GAZEBO_PATH` (plan §2). As a result, an API host configured exactly as §7 says (`SOLUS_GAZEBO_PATH=/opt/ros/jazzy/opt/gz_tools_vendor/bin`, no ROS shell) reports "Gazebo is not installed". The comment at `local.py:132` says this row only names the family and that SOL's driveable family comes from the machine's `simulators` attr (6b), so this does not gate SOL. It is still a wrong user-visible sentence. A human or P1 owner should decide whether this probe should read `SOLUS_GAZEBO_PATH` first.
- **F2. `RunSummary.origin` (`Literal["live","recorded","synthetic","sim"]`, `livebench/runs/models.py:137`) is not in the OpenAPI.** The runs router returns `dict[str, Any]` envelopes, so no `RunSummary` component is generated. The desktop `schema.ts` has 0 `RunSummary` hits. The `sim` origin is visible only at runtime: the pin response carries `"origin": "synthetic"`, and a sim run would carry `"sim"`. The plan's §2 note ("`make gen-openapi` whenever … `RunSummary.origin`") therefore produced no diff. Typing the runs responses is a route change for the Live Bench branch, not this one.
- Observation: the `isaac` sources row says "Isaac Sim detected — stream live via the Isaac direct script…" on this aarch64 host because `~/isaacsim/IsaacSim` exists as a directory (`DEFAULT_ISAAC_ROOT = Path.home()/"isaacsim"`). Isaac cannot run here (x86_64 only), so the sentence overstates the situation. Recorded only.

## 1. Ports

```text
$ lsof -i :8030 -i :6391
lsof rc=1            # nothing bound (also re-checked immediately before the API bind)
```

## 2. Migrations (`$S/alembic.log`, `$S/db_shape.log`)

```text
$ cd packages/api && SOLUS_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_sim uv run alembic current
a32100000001
$ … alembic upgrade head          # real 0m0.635s
$ … alembic current
a32200000003 (head)
$ … alembic downgrade -3
$ … alembic current
a32100000001
$ … alembic upgrade head
$ … alembic current
a32200000003 (head)
$ … alembic heads
a32200000003 (head)

$ docker exec solus-db-1 psql -U solus -d solus_sim -c '\d sim_session'
 project_id uuid not null · provider varchar(32) not null · session_id varchar(128) not null · owner varchar(32) not null
 started_by_call_id varchar(128) · scene_ref varchar(512) · started_at timestamptz not null · ended_at timestamptz
 created_by uuid · id uuid not null · scene_name varchar(128)          # ← a32200000003
Indexes: sim_session_pkey · ix_sim_session_project_provider_ended (project_id, provider, ended_at)
         uq_sim_session_live UNIQUE (project_id, provider, session_id) WHERE ended_at IS NULL
Check:   sim_session_owner CHECK (owner IN ('sol','user'))
FKs:     created_by → users(id) ON DELETE SET NULL · project_id → projects(id) ON DELETE CASCADE
$ … select indexname from pg_indexes where indexname='ix_graph_entity_sim_aliases'   → 1 row   # ← a32200000002
$ … select version_num from alembic_version → a32200000003
```

Alembic printed no `Running upgrade` lines. The migration env runs without an INFO logging config, so the revision trail above is the evidence.

## 3. Redis (`$S/redis.log`)

```text
$ docker run -d --name solus-redis-322 -p 6391:6379 redis:7
1b5f3141096cc4855b97288d55bedb59651231c03eca153e4dbb560c18d7414a
$ docker exec solus-redis-322 redis-cli ping
Could not connect to Redis at 127.0.0.1:6379: Connection refused     # first try, container starting
PONG
solus-redis-322 redis:7 Up Less than a second 0.0.0.0:6391->6379/tcp
```

## 4. API and worker (`$S/api1.log`, `$S/api2.log`, `$S/worker.log`)

The command is the repo's own (`Makefile:20`, `package.json dev:api`, `scripts/dev-all.sh:251`). `solus_api.main` exposes no module-level `app`, so the task's `solus_api.main:app` became `--factory solus_api.main:create_app`, without `--reload`:

```text
cd packages/api && uv run --no-sync uvicorn --factory solus_api.main:create_app --host 127.0.0.1 --port 8030
cd packages/api && uv run --no-sync arq solus_api.worker_main.WorkerSettings </dev/null
```

Each process got its own env (`$S/run_env.sh`, sourced inside the child; nothing was exported to the shell). `Settings` also reads the root `.env` (`env_file=REPO_ROOT/.env`), and these process values override it:

| Variable                                                                                 | Value                                                                                                                | Why                                                                                                                                   |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `SOLUS_DATABASE_URL`                                                                     | `postgresql+asyncpg://solus:solus@localhost:5432/solus_sim`                                                          | task                                                                                                                                  |
| `SOLUS_REDIS_URL`                                                                        | `redis://localhost:6391/0`                                                                                           | task                                                                                                                                  |
| `SOLUS_SUPABASE_JWT_SECRET`                                                              | `dummy-jwt-signing-value-tests-only`                                                                                 | the test suite's placeholder signing value (`tests/conftest.py:119 TEST_JWT_SECRET`), not a real secret; the `.env` one is never used |
| `SOLUS_SUPABASE_URL`                                                                     | empty                                                                                                                | no JWKS fetch (no external call); HS256 only                                                                                          |
| `SOLUS_SECRETS_BACKEND`                                                                  | `memory`                                                                                                             | no Fernet/AWS store, so no provider keys can be read and a real model call is impossible                                              |
| `SOLUS_SYNC_INLINE`                                                                      | `false`                                                                                                              | the API fans out to ARQ                                                                                                               |
| `SOLUS_AUTO_CREATE_TABLES`                                                               | `false`                                                                                                              | alembic stays the schema authority on `solus_sim`                                                                                     |
| `SOLUS_FINGERPRINT_{LLM,EMBEDDING,VISION}_ENABLED`                                       | `false`                                                                                                              | no model use from syncs                                                                                                               |
| `SOLUS_ARTIFACT_LOCAL_ROOT`                                                              | `$S/artifacts`                                                                                                       | local artifact store for the run import                                                                                               |
| `SOLUS_PUBLIC_API_BASE_URL`                                                              | `http://127.0.0.1:8030`                                                                                              |                                                                                                                                       |
| `SOLUS_GAZEBO_PATH`                                                                      | `/opt/ros/jazzy/opt/gz_tools_vendor/bin`                                                                             | §7 value                                                                                                                              |
| `SOLUS_SIM_ROOTS`                                                                        | `/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds`                                                           | §7 value                                                                                                                              |
| `GZ_CONFIG_PATH`, `GZ_SIM_SYSTEM_PLUGIN_PATH`, `GZ_SIM_RESOURCE_PATH`, `LD_LIBRARY_PATH` | from `bash -lc 'source /opt/ros/jazzy/setup.bash; env'`                                                              | Harmonic env                                                                                                                          |
| `PATH`                                                                                   | run 1: the shell PATH **minus every `/opt/ros*` entry**; run 2: `/opt/ros/jazzy/opt/gz_tools_vendor/bin:` + the same | F1                                                                                                                                    |

```text
api1  uv 407016 → uvicorn 407124   INFO: Uvicorn running on http://127.0.0.1:8030
worker uv 407954 → arq 408047      15:15:18: Starting worker for 21 functions: source_revision, sync_source, …, cron:prune_github_deliveries, cron:prune_sim_runs_job
                                   15:15:18: redis_version=7.4.11 mem_usage=1.07M clients_connected=2 db_keys=0
api2  uv 417735 → uvicorn 417829   (restart for F1, gz dir on PATH)
GET /health → 200; GET /api/v1/openapi.json → 200 (GET /openapi.json → 404: the spec lives under /api/v1)
```

Startup warnings name values that **a human sets for a shared environment**. None of them was needed for this run, and none was invented:

- `SOLUS_TOOLKB_VOTE_SALT unset — using an ephemeral per-process salt`
- `No secret store configured (SOLUS_SECRETS_KEY / SOLUS_AWS_REGION unset) — using in-memory store` (forced here on purpose)
- `SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY unset — account deletion will not revoke Supabase sessions`
- `BOM Store listing unavailable: configure SOLUS_FIRST_PARTY_PUBLISHER_ID and … SOLUS_STAFF_USER_IDS`
- `SecretStore ref '{anthropic,brave,google,openai}_api_key' missing — SOL turns … will fail with ProviderCredentialsMissingError; run make seed-secrets`, followed by `SecretStore provider refs present: none`

The machine PUTs in step 6 triggered the API's own fan-out to the worker (`sync_inline=false`):

```text
15:17:22: 0.48s → recompute_budgets:01a1c1f5-38db-…:recompute_budgets('01a1c1f5-38db-749e-bfba-c3577432b164')
15:17:22: 0.05s ← recompute_budgets:…:recompute_budgets ●
15:17:27: 0.49s → run_matrix_checkers:01a1c1f5-38db-…:run_matrix_checkers('01a1c1f5-38db-749e-bfba-c3577432b164')
15:17:27: 0.10s ← run_matrix_checkers:…:run_matrix_checkers ●
```

The worker's minute crons also ran (`cancel_stripe_subscriptions`, `purge_cad_accounts`, `reconcile_credit_debits`, `recover_onshape_hints`, `sweep_artifacts`). Each one finished `● 0` in ≤ 0.04 s.

## 5. `make mcp-forks` and the launcher (`$S/mcp-forks.log`, `$S/launch78.log`, `$S/mcp_probe.log`)

```text
$ make mcp-forks
bash scripts/install-mcp-forks.sh
[mcp-forks] altium: up to date
[mcp-forks] code: up to date
[mcp-forks] gazebo: materializing integrations/mcp/gazebo/.venv (python3.12, hash-verified)…
[mcp-forks] isaac: materializing integrations/mcp/isaac/.venv (python3.12, hash-verified)…
[mcp-forks] kicad: up to date
[mcp-forks] local: up to date
[mcp-forks] brave: up to date
[mcp-forks] done — 2 installed, 5 unchanged/skipped.
real 0m3.689s
$ cat integrations/mcp/gazebo/.venv/.solus-lock-sha256 ; sha256sum integrations/mcp/gazebo/requirements.lock.txt
287b69862cc698601f0dff61ad8031400ba9a051c909c6de79e1d13433a219c8
287b69862cc698601f0dff61ad8031400ba9a051c909c6de79e1d13433a219c8  integrations/mcp/gazebo/requirements.lock.txt
$ git status --short          # .venv is ignored; only the pre-existing untracked REPO_STATE file
?? docs/qa/REPO_STATE_ONBOARDING_BENCH_SIM_2026-11-08.md

$ env -i integrations/mcp/gazebo/bin/launch </dev/null                                          → rc=78
$ env -i SOLUS_MCP_PYTHON=$PWD/integrations/mcp/gazebo/.venv/bin/python3 bin/launch </dev/null    → rc=78   (no WORKSPACE)
$ env -i SOLUS_MCP_WORKSPACE=$S/ws bin/launch </dev/null                                         → rc=78   (no PYTHON)
```

With `SOLUS_MCP_PYTHON=integrations/mcp/gazebo/.venv/bin/python3`, `SOLUS_MCP_WORKSPACE=$S/ws`, `SOLUS_GAZEBO_PATH`, `SOLUS_SIM_ROOTS` and the four Harmonic variables, `$S/mcp_probe.py` spawns `bin/launch` with exactly that env (argv list, no shell). It speaks newline-delimited JSON-RPC over stdio:

```text
pid 404884
initialize -> {"protocolVersion": "2025-06-18", "serverInfo": {"name": "solus-gazebo", "version": "1.29.0"}}
tools/list -> 13 tools
   probe list_worlds open_world attach list_models spawn joint_state set_joint_targets control run_routine stop save_world put_asset
tools/call probe -> {"ok": true, "families": [{"name": "gz", "version": "8.15.0", "distro": "Harmonic"}],
   "capabilities": {"list_worlds": true, "running_worlds": "gz service -l", …, "save_world": true,
   "python_binding": "gz.transport (system python only)"}, "gui_attach": false, "running_worlds": [], "sessions": [], "roots": 1}
elapsed_s 2.34
server exit on stdin EOF rc 0
stderr tail: (empty)
```

## 6. HTTP against the live API (`$S/http_drive.py` → `$S/http_drive.log`, `$S/cross_tenant.log`, `$S/sources2.log`)

The token is minted the way `tests/conftest.py:make_token` mints one: HS256, `aud=authenticated`, 1 h expiry, the placeholder signing value. It is minted for a **new synthetic identity** (`sub` = fresh uuid4, `email` = `p8t3-<8 hex>@example.invalid`), never a real user's. `GET /users/me` auto-provisions the user, then `POST /teams` and `POST /teams/{id}/projects` create the team and project. Project `01a1c1f5-38db-749e-bfba-c3577432b164`, robot `01a1c1f5-3c9e-7328-a090-ca36cc75ac77`, run `ccfa7b1b-99bf-40cd-9467-bab890c81cce`.

### 6a. Bench sources

```text
# api1: SOLUS_GAZEBO_PATH set, no /opt/ros on PATH
GET /bench/sources -> 200
   {"kind": "mujoco", "available": true, "reason": null}
   {"kind": "gazebo", "available": false, "reason": "Gazebo is not installed (no `gz`, `ign` or `gzserver` CLI on PATH)"}
   {"kind": "isaac", "available": false, "reason": "Isaac Sim detected — stream live via the Isaac direct script, or replay an MCAP recording"}
   {"kind": "mcap-replay", "available": false, "reason": "bench_data_root is not configured on this server"}
   unauthenticated -> 401
# api2: same env + /opt/ros/jazzy/opt/gz_tools_vendor/bin on PATH
GET /bench/sources -> 200
   {"kind": "gazebo", "available": true, "reason": "Gazebo detected (gz family)"}
```

### 6b. Machines upsert → derived `simulators`

`PUT …/members/me/machines/{companion_id}` takes only `{hostname, os, arch}` (`MachineIn`, `extra="forbid"`). The `tool_versions` map comes **from the live bridge session** whose `companion_instance_id == companion_id`, through a `machine.tool_versions` tool call (`routers/machines.py:99-113`, `routers/local_folder.py:_live_session`). So the driver opens `ws://127.0.0.1:8030/api/v1/projects/{P}/bridge` with the same bearer token and sends the hello `{"protocol_version":1,"companion_version":"0.1.0","companion_instance_id":<companion_id>,"servers":[{"server":"machine","tools":[{"name":"tool_versions",…}]}]}`. It answers the server's `tool_call` with a `tool_result`. The version lines are this host's real output, produced by the companion's `VERSION_ARGV` for each binary: `gz sim --versions`, `gzserver --version` (classic env) and `nvidia-smi --version`, keeping the first non-empty line. This is a protocol test client. **The real `solus_companion` was not launched** (it would start every vendored fork and write its instance file under `~/.solus`).

```text
bridge hello -> {"type":"hello_ack","data":{"protocol_version":1}}
bridge <- {"type":"tool_call","data":{"tool":"machine.tool_versions","args":{},"call_id":"dd5ae0b2750b478faef40fc6ac61ec69"}}
bridge -> {"call_id": "dd5a…", "ok": true, "value": {"tool_versions": {"gz": "8.15.0", "gzserver": "Gazebo multi-robot simulator, version 11.15.1", "nvidia-smi": "NVIDIA-SMI version  : 580.178.04", "python3": "Python 3.12.3"}}}
PUT machines/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa -> 200
  attrs.tool_versions = {"gz": "8.15.0", "gzserver": "Gazebo multi-robot simulator, version 11.15.1", "nvidia-smi": "NVIDIA-SMI version  : 580.178.04", "python3": "Python 3.12.3"}
  attrs.simulators    = {"gazebo": {"family": "gz", "version": "8.15.0"}, "nvidia_smi": true, "ngspice": null}
PUT machines/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb -> 200          # gzserver only
  attrs.simulators    = {"gazebo": {"family": "classic", "version": "11.15.1"}, "nvidia_smi": false, "ngspice": null}
PUT machines/cccccccccccccccccccccccccccccccc -> 200          # python3 only, os darwin
  attrs.simulators    = {"gazebo": null, "nvidia_smi": false, "ngspice": null}

API log: bridge session 8e121753… bound: … instance=cccccccccccccccccccccccccccccccc tools=1
         machine put project=01a1c1f5-38db-… companion=cccc… bridge=True tool_versions=True environment=False
```

The first driver run (`$S/http_drive_run1_driverbug.log`, project `01a1c1f5-07f3-…`) sent `companion_instance_id: "p8t3-driver"`. That does not equal the path's companion id, so the API logged `bridge=False tool_versions=False`, made no tool call, and stored `tool_versions: {}`, `simulators.gazebo: null`. That is correct behaviour for a PUT naming a machine with no live session. The bug was in the driver, which was fixed and rerun above.

### 6c. Runs: import, pin, refusals

```text
POST /artifacts (multipart run.json, 733 B) -> 201 {"artifact_id":"01a1c1f5-3cc5-…","storage":"local",…}
POST /bench/runs/import {robot_id, artifact_id, name "P8-T3 synthetic", origin "synthetic"}
   -> 201 {"id":"ccfa7b1b-…","origin":"synthetic","status":"completed","packet_count":3,…}
POST /bench/runs/ccfa7b1b-…/pin            -> 200 {…,"origin":"synthetic","status":"completed","baseline":false,"pinned":true}
POST /bench/runs/ccfa7b1b-…/pin (again)    -> 200 {…"pinned":true}                     # idempotent
POST /bench/runs/a4edb580-…/pin (unknown)  -> 404 {"error":{"code":"not_found","message":"Run not found"}}
POST /bench/runs/ccfa7b1b-…/pin (no token) -> 401 {"error":{"code":"unauthorized","message":"Missing bearer token"}}
POST /bench/runs (start, unknown session)  -> 404 {"error":{"code":"not_found","message":"Session not found"}}
GET  /bench/runs                           -> 200 [('ccfa7b1b-…', 'synthetic', 'completed', True)]
# second synthetic user (no membership):
other user POST pin          -> 404 {"error":{"code":"not_found","message":"Project not found"}}
other user GET run           -> 404 …"Project not found"
other user GET bench/sources -> 404 …"Project not found"
API log: run pinned project=01a1c1f5-38db-… run=ccfa7b1b-… (×2)
```

**409 `run_active` was not reached** (see the verdict table). `POST /bench/runs` only creates `running` runs from an active bench session, and the snapshot then requires the session's device to be one of the robot's accepted identities (`runs/snapshot.py:142-147`).

### 6d. OpenAPI (`$S/openapi_live.json`)

```text
GazeboSimConfig.family = {"anyOf": [{"type": "string", "enum": ["classic", "ignition", "gz"]}, {"type": "null"}], "title": "Family"}
RunSummary.origin      = null            # no RunSummary component (F2); no schema has an origin enum containing "sim"
pin path present       = True            # 200 schema: {"type":"object","additionalProperties":true,…}
live vs committed packages/api/openapi.json: paths 215/215, schemas 190/190, paths equal True, schemas equal True
```

## 7. `prune_sim_runs_job` once through ARQ (`$S/enqueue_prune.py`, `$S/enqueue_prune.log`)

```text
$ cd packages/api && uv run --no-sync python $S/enqueue_prune.py
enqueued p8t3-prune-sim-runs
arq.jobs.ResultNotFound: Not waiting for job result because the job is not in queue. Is the worker function configured to keep result?
worker.log:
15:17:50:   0.46s → cron:prune_sim_runs_job()
15:17:50:   0.01s ← cron:prune_sim_runs_job ● 0
```

The job ran in the worker and returned `0` (payloads dropped). `solus_sim` holds one run entity, the synthetic one above, which is pinned and not sim-origin, so 0 is the expected answer. The script's `job.result()` raised only because the job had already finished and ARQ kept no result for it. The worker log line is the evidence.

## 8. Teardown (`$S/teardown.log`)

```text
$ kill -TERM 417735   (api2 uv)   → uvicorn 417829: "Application shutdown complete. Finished server process [417829]"
$ kill -TERM 407954   (worker uv) → "15:18:37: shutdown on SIGTERM ◆ 22 jobs complete ◆ 0 failed ◆ 0 retries ◆ 0 ongoing to cancel"
  (api1 uv 407016 / uvicorn 407124 stopped the same way before the restart: "Finished server process [407124]")
$ ps -p 407016,407124,417735,417829,407954,408047 → none
$ docker rm -f solus-redis-322 → solus-redis-322 ; docker ps -a --filter name=solus-redis-322 → (none)
$ lsof -i :8030 -i :6391 → rc=1
solus-db-1 Up 19 hours (healthy) · solus-redis-1 Up 19 hours (healthy)       # untouched
```

`solus_sim` stays at `a32200000003`. It now also holds this run's synthetic rows: 4 users `p8t3-*@example.invalid` with their trial-grant ledger rows, 3 teams and projects, 3 machine nodes, 1 robot, 1 pinned synthetic run, and 2 artifacts under `$S/artifacts`. These rows are evidence only and were not cleaned up.

## Deviations

1. The API was started with `--factory solus_api.main:create_app`, the repo's form, because there is no module-level `app`.
2. Step 6b used a bridge protocol test client in place of the real companion. The version lines are real output from this host.
3. 409 for the pin route was not exercised over HTTP; the reason is given above.
4. The API was started twice: once without gz on PATH and once with it, to show F1.
5. `make mcp-forks` also rebuilt `integrations/mcp/isaac/.venv`, because its lock stamp had changed.
