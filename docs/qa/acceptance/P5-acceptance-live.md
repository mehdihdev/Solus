# P5 acceptance, live proof (SOLUSDEV-321 plan §3 "P5 acceptance"; dispatch legs 1–6 with fix round 1's 6(d)–(g)): in process, copy of the dev DB, no provider, no Onshape call

One harness process, `acceptance/p5_accept_live.py`, in process (httpx.ASGITransport: no listening
socket) against `solus_sol` and the branch Redis on 6390. Every `render_view` call ran inside a SOL
turn bound the way `LlmRunner.run` binds one. The vision read was answered by a counted scripted
adapter. Every other model path hit a refusing adapter, and the real adapter registry raised.
Onshape was an `httpx.MockTransport`, and the only process allowed to start was the offscreen
render child. Two earlier attempts are void, both from harness assumptions (deviation 13); their
evidence is kept. `t` below is seconds after the final run's harness was built (21:31:52.586Z).

## Verdicts

- **1. A face question on the fake arm's scene → one cached, labelled MuJoCo render: PASS.**
  `render_view {entity_id: servo 2 (joint 2), question: "which face carries the camera mount?",
show: true}` in a turn → `rendered true, view "iso", renderer "scene", cached false`. The
  question names no side, so `choose_view` picks `iso` (observation 3).
  - One render child on EGL drew it (800×600, 0.917 s). The annotated PNG is 800×626 and
    33,236 bytes, sha256 `ba2e50c1…3237`.
  - Two labels are burned in at their segmentation boxes: servo 2 (joint 2) at
    [384,120,415,344] and servo 1 (joint 1) at [380,330,419,359]. The caption band reads
    `view: iso`. Each name and the band were redrawn the annotator's way and compared with the
    PNG: 0 differing pixels.
  - ONE scripted vision read, on that same PNG. The turn's `model_calls` went 1 → 2.
  - The shown artifact `01a18993-9c83-…` fetches 200 `image/png` with the same sha.
- **2. Ask again → 0 calls, a fresh artifact per show: PASS.** `cached true`. 0 render-child
  launches, 0 renderer calls, 0 scripted reads, 0 gateway calls, `findings: []`, `model_calls`
  stays 1. A NEW `artifact_id` `01a18993-9cdd-…` (≠ leg 1's), with the same bytes; leg 1's
  artifact still fetches. The cache holds `RenderView(png, text, disagreements)` only, keyed
  `(project, None, servo 2, signal, "iso")`.
- **3. A disagreeing dimension → the graph's value shown, ONE `info` finding: PASS.**
  - Servo 2 states `geometry {length_unit mm, dimensions [120, 40, 30]}`. The scripted read
    "Servo 2 (joint 2) is about 95 mm long." comes back as "Servo 2 (joint 2) is about 120 mm (the
    graph's value; the render read 95 mm) long.". `graph_wins` is graph 120 mm against render
    95 mm. ONE finding, `01a18993-a1ba-…`: `vision_fact_disagreement`, `info`, source `sol`,
    bucket `length` (in the canonical key), evidence parsed numbers only.
  - Asked again: a cache hit, `findings: []`, count stays 1.
  - A version-only bump (2 → 3, attrs unchanged): the same change signal, still a cache hit
    (observation 2).
  - After an attribute bump (3 → 4): a new signal, one render, one read and ONE filing, on the
    same canonical row (count 1 → 2). The finding row count stays 1.
- **4. The Onshape renderer refuses above the degrade ratio: PASS. 0 MockTransport requests.**
  - The ledger was scripted through the meter's own writer to 1,750 of 2,500 (ratio 0.7). At
    1,749 it admits; at 1,750 it refuses with `quota_degraded`.
  - The ask returns `{rendered: false, view: "face:front", reason: "close to the provider API
allowance; deferrable work is paused"}`. One client was built and **0 requests** were
    recorded (observation 4: the reason does not quote the ratio).
  - The one cached live render under the ratio: NOT VERIFIED, as dispatched.
- **5. The KiCad PDF path on the committed fixture, cloud side: PASS.**
  - `tests/fixtures/render_sheet.pdf` (946 bytes, md5 `20a0dfad…c725`) came back as the flagged
    export's one uploaded artifact. It was consumed once (row soft-deleted).
  - The gate's decisions: sniffed `application/pdf`, equal to the claim, 946 bytes.
    `render_pages(pages=[1], max_pages=1)` gave page_count 1 and page 1 at 1400×1000. The
    `checked_image` gate admitted `image/png 1400×1000` twice.
  - Caption `net: SDA` / `view: sheet` (0 differing pixels). One read. The result is
    `view "sheet", renderer "kicad"`.
  - Fork side: no `kicad-cli` here; `test_pdf_export.py` 12/12 passed.
- **6. R126/R127 and fix round 1 live checks: PASS (a–g).**
  - (a) Each over-budget scene is refused at the guard before any child starts, the reason naming
    what asked:
    - the dispatch's literal `<global offwidth/offheight 16384 offsamples 64>` plus the 8192²
      texture → "the scene's `global` `offwidth` is past what a render allows (4096)";
    - `quality offsamples 64` → "(4)";
    - the texture alone → "more than the 16,777,216 texels".
    - Under the caps the child overwrites the framebuffer: 1920×1080 asked, 320×240 drawn.
    - Observation 5: `offsamples` on `<global>`.
  - (b) A teammate whose view hides servo 2 gets `not_found`: 0 renders, 0 reads, 0 artifacts.
    A, right before, still hits the warm look. Another project's member with the same id gets
    `not_found` twice (show off and on), and 0 artifacts in their project.
  - (c) `kicad.export_schematic_pdf` and `kicad.export_board_pdf` are in none of the registry,
    `model_visible`, the specs sent, or `GET /sol/tools`. `render_view` is in all four. The
    companion's two unflagged tools are model-visible.
  - (d) A two-IHDR PNG and a two-SOF JPEG handed to `consume_tool_image` → `None`, logged as "the
    image's headers disagree: 16x16 first, 9000x9000 as decoded".
  - (e) A 100×2000 pt page renders at 205×4096.
  - (f) Companion views: `cached` = [false (A), false (B), true (A)], one export per member.
    The scene view is shared: B hit A's look.
  - (g) With the scene on a source B's view hides: A's plan is the scene, B's plan is `None`, and
    B's ask returns "nothing draws this entity".
- **M3 (`FIXED_PROMPT_TOKENS`) drift: PASS.** The test's own recipe measures 12,406 (system
  prompt 1,482 + specs 10,924, 60 model-visible tools) against the default of 13,000: 594 of
  headroom, inside the 2,000 band. The test itself passed in the proxy run.

**Model calls: 5 scripted vision reads, 0 real.** The five reads were legs 1, 3 first, 3 after
the bump, 5, and 6(f) for B. Each was one `gateway.complete` reaching one `gateway.stream` (10
counted calls), all `purpose vision`, `type visual_log`, with the scripted adapter injected.
There were 5 `model call start` lines and 5 `credit_ledger` usage rows (−1 each, each with its
turn's id). Other paths: 0 refusing-adapter reaches, 0 real adapter-registry builds, 0 narration
reaches, 0 unscripted reads, 0 left in the script. **MockTransport: 0 requests.** Render
children: 5 (legs 1, 3 ×2, 6(a) a4 and a5), each exited 0 by itself; 0 spawns denied.

Ready to paste into the SDD ledger:

> P5 acceptance (live, in process, DB copy `solus_sol` at a32000000006, Redis `solus-redis-321`,
> no provider: 5 scripted vision reads, 0 refused, 0 real adapters, 5 `model call start` lines,
> 5 usage rows; egress loopback-only; 1 `.env` read refused; 5 render children, the harness's
> own, exit 0). Leg 1: `render_view` in a turn on servo 2, "which face carries the camera mount?"
> → scene renderer, view iso (the question names no side), cached false. 800×626 annotated PNG
> (`ba2e50c1…`) with servo 2 [384,120,415,344] and servo 1 [380,330,419,359] burned in; names and
> caption match a redraw at 0 differing px. One read; shown artifact `01a18993-9c83-…`. Leg 2:
> cached, 0 children / renders / reads, findings [], new artifact `01a18993-9cdd-…`. Leg 3: 120 ×
> 40 × 30 mm against a read of 95 mm → "about 120 mm (the graph's value; the render read 95 mm)",
> one info `vision_fact_disagreement` `01a18993-a1ba-…` (sol, bucket length, parsed numbers); ask
> again → cache hit, count 1; version-only bump → still a hit; attrs bump → one re-filing on the
> same row, count 2. Leg 4: ledger 1750/2500 → `quota_degraded` → `{rendered false, view
face:front, reason "close to the provider API allowance; deferrable work is paused"}`,
> MockTransport 0 requests. Leg 5: fixture PDF via the flagged export's upload → consumed once,
> `%PDF-`, page 1 1400×1000 gated, caption "net: SDA", read; fork `test_pdf_export.py` 12/12.
> 6(a) refused at the guard naming offwidth / offsamples / texels (clamp: 1920×1080 → 320×240).
> 6(b) hidden teammate and foreign project → not_found, 0 work. 6(c) the PDF exports in no model
> list, render_view in all. 6(d) two-IHDR / two-SOF → dropped, "16x16 first, 9000x9000 as
> decoded". 6(e) 205×4096. 6(f) cached [F, F, T]; the scene look is shared. 6(g) B's plan None.
> M3 measured 12,406 ≤ 13,000. Proxies: 264 passed (API), 24 passed (offscreen), 486 passed /
> 1 skipped / 1 xfailed (KiCad fork). Report: `docs/qa/acceptance/P5-acceptance-live.md.

## Run identity

| Item          | Value                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Run time      | **Final:** command 21:31:51Z → 21:32:01Z, harness 21:31:52.578Z → 21:32:00.370Z, exit 0. **Void attempt 1:** 21:26:14Z → 21:26:17Z, exit 1. **Void attempt 2:** 21:29:20Z → 21:29:25Z, exit 0, every leg failed (deviation 13). PNG read-back after the final run. **Proxies:** API 21:37:55Z → 21:39:22Z; offscreen 21:39:49Z → 21:39:54Z; KiCad fork 21:40:10Z → 21:40:19Z.                                                     |
| Branch        | `SOLUSDEV-321-sol-checker-algorithm`                                                                                                                                                                                                                                                                                                                                                                                              |
| HEAD          | `5b9c6240` before and after. `git status --short` empty throughout. `.coverage` md5 `7571ebfd2af623167baf221f5af68076` before the run and after the proxies.                                                                                                                                                                                                                                                                      |
| Database      | `solus_sol`, asserted from the server by the harness (`select current_database()`); `alembic_version` `a32000000006` (no migration on the branch since P4). Nothing applied, created or dropped.                                                                                                                                                                                                                                  |
| Redis         | `redis://127.0.0.1:6390/0`, the branch's `solus-redis-321`. dbsize 0 before void attempt 1. The final run started with the voids' 2 upload-budget keys, after I deleted void attempt 2's 4 Onshape keys by exact name. Left behind: three `solus:upload-budget:bytes:*` keys, each with its own TTL. `solus-redis-1` was not touched.                                                                                             |
| Harness       | `/home/beeboss/Solus/.superpowers/sdd/pasted-content-id-24a5-sol-precious-pillow/acceptance/p5_accept_live.py`. Raw evidence beside it: `p5_accept_live_result.json`, `.stdout`, `.stderr`, `.time`; the PNGs `p5_leg1_render.png`, `p5_leg1_annotated.png`, `p5_leg3_annotated.png`, `p5_leg5_annotated.png`, `p5_vision_input_{1..5}.png` (each image the scripted adapter was handed). Void sets: `p5_accept_live_VOID{1,2}*`. |
| PNG read-back | `acceptance/p5_png_labels.py` → `p5_png_labels.json` (and `.stdout`): no DB, no network, nothing imported from `solus_api`; run as `.venv/bin/python -I`.                                                                                                                                                                                                                                                                         |
| Commands      | Harness: `cd /home/beeboss/Solus/packages/api && PYTHONDONTWRITEBYTECODE=1 MUJOCO_GL=egl SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' timeout 900 uv run --frozen --no-sync python <harness>`. Proxies: below.                                                                                                                                       |

## Environment recipe as executed

1. **Database.** `solus_sol` held P4's leave-behind, as void attempt 1 read it: 15 users,
   21 projects, 31 memberships, 17 `credit_ledger` rows (6 of type `usage`; they predate this
   session), 268 findings, 3 scene models, 1,159 entities, 1,404 edges, 18 sources,
   17 artifacts, 14 jobs.
2. **Environment.** The harness refuses to start unless exactly `SOLUS_DATABASE_URL` and
   `SOLUS_REDIS_URL` hold the prescribed values and `MUJOCO_GL=egl`, and it re-checks the
   `SOLUS_*` set after its imports. `SOLUS_TEST_DATABASE_URL` was set only on the proxy pytest's
   command line.
3. **Settings, in code** (as P4): `Settings(_env_file=None, supabase_jwt_secret=<token_urlsafe(32)
per run>, supabase_jwt_audience="authenticated", rate limits 100_000, sync_inline=True,
fingerprint_embedding_enabled=False, artifact_local_root=<TemporaryDirectory>)`. The database
   and Redis URLs were asserted equal to the exports. Defaults were kept: `artifact_max_bytes`
   8,388,608, `artifact_ttl_seconds` 3,600, `onshape_annual_call_allowance` 2,500,
   `integration_degrade_ratio` 0.7, `onshape_quota_pool` owner, no Onshape client id, and
   `bridge_allowlist_root` = `integrations/mcp`, so the real allowlists load.
4. **App.** `create_app(settings, create_async_engine(solus_sol))` with
   `hardware_connections.owner = RuntimeOwner(<tmp>, <tmp>)`, `agent_runner =
LlmRunner(adapters=<refusing>)`, and the Narrator's `_complete` scripted (M88). The lifespan
   was not run, and no graph-changed fan-out was installed: P5 has no fan-out consumer to prove.
5. **The turn, per ask** (`P5AHarness.ask`):
   - A fresh `build_sol_registry(...)` with the arguments `deps.get_sol_registry` passes that
     reach `render_view`: sessionmaker, project, person, team, the app's bridge registry, bridge
     call cap, secret store, connector registry, sol systems, Redis, artifact store, TTL, the
     upload cap and the hub, plus a recording `scene_enqueue`.
   - `build_dispatch(registry, park)`, where `park` is the real `request_confirmation`: 22 calls,
     all `None`, since `render_view` is ungated.
   - Then the runner's own wrapping: `with_perception(with_turn(withhold_server_driven(dispatch),
turn_id), TurnBudget(turn_limits(GUIDE, STANDARD)), connectivity=False, counting=False)`.
     The round's model call is noted first, as the runner notes it, and each ask runs under
     `bind_scope(resolve_scope(project, person))`, as the request dependency binds it.
6. **Probes, recording only, never raising.** Each wraps and calls the original, by module
   attribute:

   - `livebench.sim.offscreen.render_scene_png`, `Renderers.render`,
     `render_view.annotate_render`, `vision_extract`, `vision_postcheck`, `file_disagreements`,
     `change_signal` and `create_artifact`, and `vision_postcheck.raise_finding`;
   - the bridge path: `bridge.service.consume_tool_artifact` and `sniffed_media_type`, plus
     `renderers.consume_tool_image`, `dispatch` and `render_pages`;
   - `checked_image` in `renderers`, `render_annotate` and `bridge.service`;
   - the Onshape path: `onshape_render.render_synced_view` and `_cached_collection`,
     `CallMeter.admit`, and `OnshapeConnector.http` (the MockTransport client);
   - the gateway's `stream`/`complete`; one root log handler at INFO.

   0 probe errors.

7. **Order of steps.** Void attempts 1 and 2. I deleted void attempt 2's Onshape keys (deviation
   13). The final run: seed → 6(c) → outside a turn and renders off → 1 → 2 → 6(f) scene →
   6(b) other project → 3 → 5 → 6(f) companion → 4 → 6(a) → 6(b) hidden → 6(g) → 6(d) →
   6(e) + M3 → ledger read → seeded sources disconnected → teardown. Then the PNG read-back, the
   pytest guard in its own call (empty) before each of the three proxy runs, and the proxies.

## Why no real provider was reachable

1. **Every gateway call carried harness adapters.**
   - `gateway.complete` and `gateway.stream` were wrapped as module attributes before any app was
     built.
   - A call with no adapters got the scripted vision adapter when `purpose == "vision"`, else the
     refusing one.
   - All 5 `complete` calls were `purpose vision` (adapters "scripted vision (injected)"), and
     each reached one `stream` with the caller's adapters. No call had another purpose.
2. **The real adapter registry raises.** `gateway.build_adapter_registry` was replaced by a
   function that records and raises: 0 reaches.
3. **The refusing adapters** on `app.state.agent_runner` and for any non-vision call: 0 reaches.
   The Narrator's scripted adapter: 0 reaches, and no bench session started (SessionManager
   active 0, ended 0, starting 0).
4. **No credentials.**
   - The secret store is `InMemorySecretStore`. Its one value was put by the harness for the
     seeded Onshape source's `secret_ref`, `p5-acceptance-placeholder-not-a-credential`, so the
     render path reaches its meter.
   - `secrets_key` unset, `aws_region` None, `supabase_url` None, `sentry_dsn` unset, no Onshape
     client id. The JWT secret is per run.
5. **No `.env` read.** `DotEnvSettingsSource._read_env_files` refuses and records: 1 refusal
   (`/home/beeboss/Solus/.env` at import, t −0.721; the stderr line is toolkb's ephemeral
   vote-salt notice).
6. **Egress, bind and spawn guards.**
   - Only loopback 5432/6390 may connect and only loopback names resolve. 4 attempts: connect
     127.0.0.1:5432, connect 127.0.0.1:6390, resolve localhost:5432, and `bind ('::1', 0)`
     denied (urllib3's import-time IPv6 probe, as P3 and P4).
   - The only process admitted is the render child, exactly as `render_scene_png` starts it:
     argv `['/home/beeboss/Solus/.venv/bin/python', '-I', '-m', 'livebench.sim.offscreen']`,
     env exactly `{HOME: <its private dir>, LC_ALL: C, MUJOCO_GL: egl, OPENBLAS_NUM_THREADS: 1}`,
     cwd `/tmp/solus-shot-*`. 5 launches (pids 1787523, 1787584, 1787620, 1787695, 1787726),
     each exit 0 in 0.67–0.92 s. 0 denied spawns.
7. **Onshape is a MockTransport.** `OnshapeConnector.http` returns a client whose transport
   records each request and answers 599. 1 client built in leg 4, **0 requests**.

| Count                                  | 1     | 2     | 3 (first / again / version / attrs) | 4           | 5     | 6(f) B / A again | all other asks               |
| -------------------------------------- | ----- | ----- | ----------------------------------- | ----------- | ----- | ---------------- | ---------------------------- |
| Scripted vision reads                  | **1** | 0     | 1 / 0 / 0 / 1                       | 0           | **1** | 1 / 0            | 0                            |
| `gateway.complete`                     | 1     | 0     | 1 / 0 / 0 / 1                       | 0           | 1     | 1 / 0            | 0                            |
| Render-child launches                  | 1     | **0** | 1 / 0 / 0 / 1                       | 0           | 0     | 0 / 0            | 0 (6(a) a4: 1; direct a5: 1) |
| Renderer calls                         | 1     | 0     | 1 / 0 / 0 / 1                       | 1 (refused) | 1     | 1 / 0            | 0 (6(a): 1 each, refused)    |
| Companion exports                      | 0     | 0     | 0                                   | 0           | 1     | 1 / 0            | 0                            |
| Findings raised                        | 0     | 0     | 1 / 0 / 0 / 1                       | 0           | 0     | 0                | 0                            |
| Shown artifacts                        | 1     | 1     | 0                                   | 0           | 0     | 0                | 0                            |
| Onshape requests                       | 0     | 0     | 0                                   | **0**       | 0     | 0                | 0                            |
| Turn `model_calls` (round, then after) | 1 → 2 | 1 → 1 | 1→2 / 1→1 / 1→1 / 1→2               | 1 → 1       | 1 → 2 | 1→2 / 1→1        | 1 → 1                        |

`credit_ledger` gained 8 rows in the final run: 3 `trial_grant` (A, B, C) and 5 `usage`, each −1
with `purpose vision` and role `visual_standard`, `tokens_in` 1,200 (the scripted `Usage`). Their
turn ids are leg 1 `52728376-…`, leg 3 first `c79b6d00-…`, leg 3 after the bump `e7a08683-…`,
leg 5 `b1ce37c0-…`, and B's 6(f) `de048b6b-…`. The 5 `model call start` lines read `provider=google
model=gemini-3.5-flash role=visual_standard complexity=standard type=visual_log purpose=vision
turn_id=<that turn>`: the catalog's VISUAL_LOG route, answered by the scripted adapter.

## Seed (final run; ids for the record)

People were minted as `tests/conftest.py::make_token` does, and `/users/me` provisioned them.
Teams and projects came from `POST /api/v1/teams` and `POST /api/v1/teams/{id}/projects`. B joined
P through the production invite flow: `POST /teams/{t}/invites {email, role member}` 201, then
`POST /invites/{token}/accept` 200, then B's `GET …/findings` on P 200.

| Who / what                                                                | Id                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A (owner) / team / **project P**                                          | `01a18993-94de-7a43-96e2-f4f3f9981fce` / `01a18993-9528-7040-ae56-b9f56afdfc2f` / **`01a18993-953a-7091-bc29-eb876b348bca`**                                                                                                                                                                                                                                                           |
| B (member of P's team)                                                    | `01a18993-9503-7f47-9630-6821f0f999a8`                                                                                                                                                                                                                                                                                                                                                 |
| C / team / **project Q** (another tenant)                                 | `01a18993-9511-7490-9e3f-4fb16ecdfd4b` / `01a18993-957c-7e4d-a9e5-e2b3b91ec2f8` / **`01a18993-9583-7a11-b5f0-7da3fcee431e`**                                                                                                                                                                                                                                                           |
| Fake arm robot (`seed_fake_arm`, its production writers)                  | `9d8da967-453a-4fce-9c41-681d6c0588be`                                                                                                                                                                                                                                                                                                                                                 |
| servo 1 (joint 1) · **servo 2 (joint 2)**                                 | `11247ff6-52b0-4506-bb14-e5394fdfdef7` · **`2d3c9411-d087-40de-9c77-945e05cbe6b9`** (servo 3 `6f852daf-…`, servo 4 `7e50ef98-…`, actuator 5 `d5e979be-…`, servo 6 `73ac4937-…`)                                                                                                                                                                                                        |
| **Scene model** (seeded row, deviation 1) and its file                    | `01a18993-9718-75fe-bb21-e59e62180ba7` (version 1; attrs `robot_id` = the robot, `bindings` `[{joint_1, servo 1}, {joint_2, servo 2}]`); file `01a18993-970a-7b0a-ab07-059539e48802` via `POST /artifacts` (`application/xml`, 791 bytes, retained) = `livebench/tests/lb_offscreen_test.py::FAKE_ARM_MJCF`, sha256 `7f468eb07d5eff82ab85a3bda293aea39a1dc6ba09072b08db219c251464e393` |
| KiCad source (seeded row) · net `SDA`                                     | `01a18993-971c-7e34-8ba7-c238467fc572` (`project_path /home/fake/fake_arm/fake_arm.kicad_pro`) · `01a18993-971d-7dc6-89bb-46928da08d62`                                                                                                                                                                                                                                                |
| Onshape source (seeded row) · part `bracket`                              | `01a18993-9720-72d2-8863-975e617a4b61` (`documents [d710921cf44524211bb418bd]`, account `p5-acceptance-onshape-710921cf4452`) · `01a18993-9721-7130-b180-f9418b8223a2` (`document_id d710921cf44524211bb418bd`, `element_id e44524211bb418bdafed416a`, `observed_microversion m10921cf44524211bb418bda`)                                                                               |
| 6(a) budget robot (`POST /entities`) · scenes a1–a4                       | `01a18993-a903-7fa2-813a-290b5bdaae26` · `01a18993-a918-…`, `01a18993-a970-…`, `01a18993-a9bc-…`, `01a18993-aa0d-…`                                                                                                                                                                                                                                                                    |
| 6(b) base source · snapshot (B's `SourceViewSelection` replaces the base) | `01a18993-b086-77e9-90dd-9123ff7f98df` · `01a18993-b088-7f58-a324-55325d7b86a8`                                                                                                                                                                                                                                                                                                        |

**The companions.** A and B each got an in-process `BridgeSession` (deviation 4). Its inventory was
gated by the real allowlist through `validate_inventory`, as at hello: 4 tools advertised and 4
admitted, none requiring confirmation:

```json
[
  { "name": "kicad.export_schematic_pdf", "returns_image": true },
  { "name": "kicad.export_board_pdf", "returns_image": true },
  { "name": "kicad.export_netlist", "returns_image": false },
  { "name": "kicad.list_projects", "returns_image": false }
]
```

**The Onshape listing**, as the sync caches it: written through the scoped connector's own
`_cached(_payload_key("elements", …))` (M9b's path) under
`solus:icache:onshape:p5-acceptance-onshape-710921cf4452:revision-v3-elements:d710921cf44524211bb418bd:m10921cf44524211bb418bda`
=
`{"value": [["e44524211bb418bdafed416a", "PARTSTUDIO", "bracket studio"]], "fetched_at": "2026-10-29T21:31:53.507695+00:00", …}`.

## Item 1: a face question → one cached, labelled MuJoCo render

`render_view {entity_id: 2d3c9411-… (servo 2), question: "which face carries the camera mount?",
show: true}`, turn `52728376-33a9-451c-a297-c84fcc887d51`, `ok`, 1.082 s. The value, verbatim:

```json
{
  "rendered": true,
  "view": "iso",
  "renderer": "scene",
  "cached": false,
  "read": "An isometric view of the fake arm: servo 2 (joint 2), labelled, rises from servo 1 (joint 1), which sits on a grey base. No camera mount is labelled or visible, so which face carries one cannot be read from this view.",
  "graph_wins": [],
  "findings": [],
  "note": "A vision model read this labelled render: describe it with hedges. Counts and connections come from the graph, never from a picture. Where the read gave a length the graph states differently, the graph's value is written in and an info finding was filed.",
  "artifact_id": "01a18993-9c83-7e47-a853-34ee927d9bf1",
  "uri": "/api/v1/projects/01a18993-953a-7091-bc29-eb876b348bca/artifacts/01a18993-9c83-7e47-a853-34ee927d9bf1/content",
  "media_type": "image/png",
  "title": "servo 2 (joint 2) (iso)",
  "summary": "A labelled iso render by the scene renderer."
}
```

- **The plan** (`Renderers.render`): renderer `scene`, revision
  `scene:01a18993-9718-75fe-bb21-e59e62180ba7:1`, bindings `{servo 1: joint_1, servo 2: joint_2}`.
  `labelled` holds the subject, then the robot's six contained parts.
- **The render** (`render_scene_png`): `{view iso, side null, target_joint joint_2, target_name
servo_2_joint_2, width 800, height 600}`, 791-byte scene. One child (pid 1787523, exit 0,
  0.917 s) drew 800×600, 31,560 bytes, sha256 `26bbace6…f228` (`p5_leg1_render.png`). The
  segmentation pass's bodies:

  | body              | joints    | pixel box            |
  | ----------------- | --------- | -------------------- |
  | `base`            | –         | [323, 317, 476, 451] |
  | `servo_1_joint_1` | `joint_1` | [380, 330, 419, 359] |
  | `servo_2_joint_2` | `joint_2` | [384, 120, 415, 344] |

- **The annotated PNG** (`p5_leg1_annotated.png`): 800×626, 33,236 bytes, sha256
  `ba2e50c12071f21a74ccbf7e03385a4c14e04000a438c5106c9e73a432d03237`.
  - It is byte-identical to the image the scripted adapter was handed (`p5_vision_input_1.png`)
    and to the shown artifact: `GET <uri>` as A → 200 `image/png`, 33,236 bytes, the same sha.
  - The adapter got the Solus prompt verbatim (`query == vision_extract._PROMPT`), with
    `max_tokens` 1,500 and no conversation.
- **The labels burned in, read back from the PNG's pixels** (`p5_png_labels.py`). Each name and
  the caption band were redrawn with the annotator's font, placement rule and colours on paper,
  then compared pixel for pixel. Each box ring was counted in the label ink (200, 30, 30):

  | label (as `annotate_render` was handed it) | box                                             | ring px in label ink | name redrawn vs PNG   |
  | ------------------------------------------ | ----------------------------------------------- | -------------------- | --------------------- |
  | `servo 2 (joint 2)`                        | [384, 120, 415, 344] (= its bound joint's body) | 482 / 510            | 0 of 1,036 px differ  |
  | `servo 1 (joint 1)`                        | [380, 330, 419, 359] (= its bound joint's body) | 136 / 136            | 0 of 1,036 px differ  |
  | caption band, 26 px (`2 × 6 + 14 × 1`)     | `view: iso`                                     | –                    | 0 of 20,800 px differ |

  - The 28 ring pixels of servo 2 that are not ink lie exactly where servo 1's name, drawn later
    on its own paper rectangle (x 378–451, y 316–329), crosses servo 2's two vertical edges:
    2 columns × 14 rows.
  - Servos 3, 4 and 6 and actuator 5 are labelled in the plan, but the scene has no body for
    them. So they are drawn nowhere: only an unplaced subject goes to the caption.

- **The read**: one scripted answer (`p5_vision_input_1.png`). `model call start
call_id=92018ef2-c2a8-4810-98fd-61392ce069bd provider=google model=gemini-3.5-flash
role=visual_standard complexity=standard type=visual_log purpose=vision
turn_id=52728376-33a9-451c-a297-c84fcc887d51`. The turn's `model_calls` went 1 → 2 (max 6), and
  the ledger got one usage row (−1, `tokens_in` 1,200, `tokens_out` 54).

## Item 2: ask again → 0 calls, a fresh artifact per show

The same arguments, a new turn `1108adb0-…`, `ok`, 0.019 s:

```json
{
  "rendered": true,
  "view": "iso",
  "renderer": "scene",
  "cached": true,
  "read": "An isometric view of the fake arm: servo 2 (joint 2), labelled, rises from servo 1 (joint 1), which sits on a grey base. No camera mount is labelled or visible, so which face carries one cannot be read from this view.",
  "graph_wins": [],
  "findings": [],
  "note": "…",
  "artifact_id": "01a18993-9cdd-7692-a3e0-e01885471ea9",
  "uri": "/api/v1/projects/01a18993-953a-7091-bc29-eb876b348bca/artifacts/01a18993-9cdd-7692-a3e0-e01885471ea9/content",
  "media_type": "image/png",
  "title": "servo 2 (joint 2) (iso)",
  "summary": "A labelled iso render by the scene renderer."
}
```

- 0 render-child launches, 0 `render_scene_png`, 0 `Renderers.render`, 0 scripted reads,
  0 gateway calls, 0 findings raised. The turn's `model_calls` stays 1.
- One `create_artifact` for the show: `01a18993-9cdd-…` (`source_tool render_view`, created by
  A, 33,236 bytes), a new id, not leg 1's `01a18993-9c83-…`. `GET` → 200 `image/png`, sha
  `ba2e50c1…3237`. Leg 1's artifact still fetches 200 with the same sha.
- **The cache, as the process held it** after leg 2: one look, key `["01a18993-953a-…" (project),
null (asker), "2d3c9411-…" (servo 2), "9e62ad36…7033" (change signal), "iso"]`. The value is
  `RenderView`, fields `[png, text, disagreements]`: 33,236 bytes, 217 characters, 0
  disagreements. It holds no artifact, no finding and no renderer.

## Item 3: a disagreeing dimension → the graph's value, one `info` finding

- **Seed**: servo 2's attrs were reassigned with `geometry {length_unit mm, dimensions [120.0,
40.0, 30.0]}`, version 1 → 2 (as `test_render_view._with_length` does, plus the bump).
- **First ask**: `{entity_id: servo 2, question: "How long is servo 2 (joint 2)?"}`, which gives
  the bounds view. The scripted read was "A bounds view framing servo 2 (joint 2). Servo 2 (joint 2) is about 95 mm long." Turn `c79b6d00-…`, 1.017 s, one render child, one read; `model_calls`
  1 → 2.
  - The render: `{view bounds, target_joint joint_2}`, 800×600.
  - The annotated PNG (`p5_leg3_annotated.png`) is 800×640. Its 40-px band reads `view: bounds`
    and `servo 2 (joint 2): 120 x 40 x 30 mm (graph)`: the graph's extents are burned in. The
    labels servo 2 [376,120,423,436] and servo 1 [371,412,428,458] and the band match the redraw
    at 0 differing pixels.

```json
{
  "rendered": true,
  "view": "bounds",
  "renderer": "scene",
  "cached": false,
  "read": "A bounds view framing servo 2 (joint 2). Servo 2 (joint 2) is about 120 mm (the graph's value; the render read 95 mm) long.",
  "graph_wins": [
    {
      "entity_id": "2d3c9411-d087-40de-9c77-945e05cbe6b9",
      "label": "servo 2 (joint 2)",
      "graph": { "value": 120.0, "unit": "mm" },
      "render": { "value": 95.0, "unit": "mm" }
    }
  ],
  "findings": ["01a18993-a1ba-7b6d-9482-4fbb82586a4b"],
  "note": "…"
}
```

The ONE finding, from `GET /api/v1/projects/{P}/findings?subject=<servo 2>` as A (200; the only
row):

```json
{
  "id": "01a18993-a1ba-7b6d-9482-4fbb82586a4b",
  "rule_id": "vision_fact_disagreement",
  "severity": "info",
  "source": "sol",
  "status": "open",
  "headline": "a render read servo 2 (joint 2)'s length as 95 mm; the graph states 120 mm",
  "explanation": "",
  "detail": "",
  "subjects": ["2d3c9411-d087-40de-9c77-945e05cbe6b9"],
  "evidence": {
    "view": "bounds",
    "graph": { "unit": "mm", "value": 120.0 },
    "render": { "unit": "mm", "value": 95.0 },
    "quantity": "length"
  },
  "count": 1,
  "first_seen": "2026-10-29T21:31:56.214683+00:00",
  "last_seen": "2026-10-29T21:31:56.214683+00:00",
  "matrix_cell": null,
  "domain": "electrical"
}
```

- **The raise** (`raise_finding`, probed): spec `{rule_id vision_fact_disagreement, severity info,
source sol, bucket "length", evidence {quantity, graph, render, view}}`.
  - The row's `canonical_key` is `a3245140d7c03fd0b7bcc5c2522731690508d9e5`. That equals
    `canonical_finding_key(P, <the spec with bucket "length">)`, recomputed by the harness: the
    bucket is part of the key, not an attr (as P4's item 3).
  - The evidence carries parsed numbers and the view only; the read's text never reaches it.
- **Ask again** (turn `5ee9cee1-…`, 0.016 s): `cached true`, the same read and `graph_wins`,
  `findings: []`. 0 children, renders, reads or raises. The finding stays count 1.
- **A version-only bump** (version 2 → 3, attrs unchanged): ask again (turn `085f16b7-…`) →
  `cached true`, 0 work. The probed `change_signal` is the same, `c438767e…`, before and after
  (observation 2).
- **An attribute bump** (`p5_acceptance_revision: 2` added, version 3 → 4): the change signal
  becomes `24bf32ee…`. The ask (turn `e7a08683-…`, 1.001 s) gives `cached false`: one render
  child, one read, the same read text and `graph_wins`, and `findings:
["01a18993-a1ba-7b6d-9482-4fbb82586a4b"]`.
  - That is ONE filing, landing on the same canonical row: `GET /findings` shows one row,
    `count: 2`, `last_seen 2026-10-29T21:31:57.412242+00:00`. The evidence was merged as
    `raise_finding` merges it: the same parsed fields plus `items` with both renders' numbers.
- **The dispatch's own sentence**, checked directly with no model: `vision_postcheck("The bracket
is about 95 mm long.", [servo 2's fact])` → the text unchanged, 0 disagreements. "The bracket"
  names no labelled part (deviation 2).

## Item 4: the Onshape renderer refuses above the degrade ratio

The ledger was scripted through the production writer. The harness built the meter exactly as the
render path does: `connector_registry.create_scoped("onshape", ConnectorContext(purpose "agent",
label "agent_read", account_ref …))`. It called `CallMeter.record(200)` 1,749 times, then once
more, on ledger `solus:intq:onshape:acct:p5-acceptance-onshape-710921cf4452:2026`. The pool is
`owner`, but with no application identity it stays per account, one ledger.

| step                                     | ledger (`used_before`) | allowance · ratio | `admit()`                                                                          |
| ---------------------------------------- | ---------------------- | ----------------- | ---------------------------------------------------------------------------------- |
| direct check                             | 1749                   | 2500 · 0.7        | admitted                                                                           |
| direct check                             | 1750                   | 2500 · 0.7        | `quota_degraded`: "close to the provider API allowance; deferrable work is paused" |
| the render path's own meter (in the ask) | 1750                   | 2500 · 0.7        | `quota_degraded`, the same message                                                 |

`render_view {entity_id: 01a18993-9721-… (bracket), question: "What is on the front face of the
bracket?"}` gave `ok`, 0.012 s:

```json
{
  "rendered": false,
  "view": "face:front",
  "reason": "close to the provider API allowance; deferrable work is paused"
}
```

- `Renderers.render` got renderer `onshape`, revision `onshape:44136fa3…af8a`, view `face:front`,
  and was refused with that `RenderRefusedError`.
- `render_synced_view` got `{view front, width 800, target {document_id, element_id,
observed_microversion}}` and raised `ConnectorError` code `quota_degraded`.
- `_cached_collection` read the sync's listing first, giving `partstudios`: the document was
  cached, and nothing was probed.
- **MockTransport: 1 client built, 0 requests** (`mock_transport_requests_list: []`). 0 render
  children, 0 reads.
- Afterwards the leg deleted the 4 keys it had scripted, by exact name and by its unique account
  ref: the year ledger, its `agent_read` label, the listing, and the cache index `__keys`.

## Item 5: the KiCad PDF path on the committed fixture (cloud side)

`render_view {entity_id: 01a18993-971d-… (net SDA), question: "Which sheet carries SDA?"}`, turn
`b1ce37c0-…`, `ok`, 0.132 s. Through the person's own companion (in process, deviation 4):

| step                               | what the probes recorded                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the export call                    | `dispatch(A's session, "kicad.export_schematic_pdf", {"project_path": "/home/fake/fake_arm/fake_arm.kicad_pro"})`, wire call id `538eed904ba447e3bcdf13d85d322f0f`. The companion uploaded the fixture through `POST /artifacts` as A (`source_tool kicad.export_schematic_pdf`, that `call_id`) → artifact `01a18993-a6b9-70a9-8249-42fc9b80a8c7`, and answered `{format pdf, filename, bytes 946, artifact_ref, degraded false, reason null}` |
| the fixture                        | `packages/api/tests/fixtures/render_sheet.pdf` (`test_bridge_images.SHEET`): 946 bytes, head `%PDF-1.4`, md5 `20a0dfadf3ea02d0e525936203e8c725`, sha256 `82535c17…c381`                                                                                                                                                                                                                                                                         |
| `consume_tool_artifact` (one shot) | `{artifact_id 01a18993-a6b9-…, source_tool kicad.export_schematic_pdf, tool_call_id 538eed90…, requester A}` → claimed `application/pdf`, 946 bytes, head `255044462d312e34`. Afterwards the row has `deleted_at 2026-10-29T21:31:57.505237+00:00`: consumed once                                                                                                                                                                               |
| header sniff                       | `sniffed_media_type` → `application/pdf`, equal to the claim, at most 2 MiB → `ToolImage(application/pdf, 946 bytes)`                                                                                                                                                                                                                                                                                                                           |
| page count and dims                | `render_pages(pdf, pages=[1], max_pages=1)` → `page_count 1`, page 1 at **1400×1000** (19,620-byte PNG)                                                                                                                                                                                                                                                                                                                                         |
| the image gate                     | `checked_image` at `renderers._gated` → `["image/png", 1400, 1000]` admitted; at `render_annotate._decoded` → the same                                                                                                                                                                                                                                                                                                                          |
| the caption (M162 v1)              | `annotate_render` got the label `net: SDA` with no box, and `["view: sheet"]` → annotated 1400×1040 (`p5_leg5_annotated.png`). The band reads `net: SDA` / `view: sheet`; a redraw matches at 0 of 56,000 px differing. No box is drawn                                                                                                                                                                                                         |
| the read                           | one scripted answer on that PNG (sha `9d84578e…f678`, `p5_vision_input_4.png`), `model_calls` 1 → 2                                                                                                                                                                                                                                                                                                                                             |

```json
{
  "rendered": true,
  "view": "sheet",
  "renderer": "kicad",
  "cached": false,
  "read": "A schematic sheet of the fake arm project, read for the first member; the caption names net SDA and the sheet view. Which symbols SDA joins is not traced from the picture.",
  "graph_wins": [],
  "findings": [],
  "note": "…"
}
```

**Fork side: not run here (no `kicad-cli`).** `integrations/mcp/kicad/tests/test_pdf_export.py`,
in the fork suite's proxy run: **12 cases, 12 passed**:

- `test_the_schematic_export_runs_the_pinned_cli_and_publishes_the_pdf`
- `test_the_board_export_reads_a_private_copy_with_the_fixed_layers`
- `test_without_a_cli_the_exports_degrade_with_no_artifact`
- `test_under_the_flatpak_adapter_the_exports_degrade_and_run_nothing`
- `test_a_failed_oversize_or_non_pdf_export_degrades_with_no_artifact`, with the cases
  `the-cli-fails`, `not-a-pdf`, `past-2-mib` and `nothing-written`
- `test_a_project_without_a_board_degrades_naming_it`
- `test_a_board_that_escapes_the_workspace_never_reaches_the_cli`
- `test_only_an_existing_project_file_is_exported`, with the cases `not-a-project` and `missing`

## Item 6: R126/R127 and fix round 1's live checks

### 6(a) the render budget

Each scene below is a scene model row whose file is the fake-arm text with the markup inserted
before `<worldbody>`. A asked `render_view {entity_id: <the scene>, question: "What does this scene
look like?"}` in a turn, so the view is `iso` for all of them:

| scene                                      | markup                                                                                                                                                                     | result                                                                                                                    | render children                    |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| a1, the dispatch's literal                 | `<visual><global offwidth="16384" offheight="16384" offsamples="64"/></visual><asset><texture name="big" type="2d" builtin="checker" width="8192" height="8192"/></asset>` | `{"rendered": false, "view": "iso", "reason": "the scene's \`global\` \`offwidth\` is past what a render allows (4096)"}` | **0**                              |
| a2                                         | `<visual><quality offsamples="64"/></visual>`                                                                                                                              | `… "reason": "the scene's \`quality\` \`offsamples\` is past what a render allows (4)"`                                   | **0**                              |
| a3                                         | the 8192² texture alone                                                                                                                                                    | `… "reason": "the scene's textures hold more than the 16,777,216 texels a render reads"`                                  | **0**                              |
| a4, `offsamples` where the dispatch put it | `<visual><global offsamples="64"/></visual>`                                                                                                                               | `… "reason": "the model does not compile"`                                                                                | 1 (exit 0, 0.666 s; observation 5) |

- **The tests pin refusal at the guard, and both sides of it hold live.** a1–a3 were refused in
  the parent by `render_budget_error` before any child started.
- Under the caps, the child overwrites the framebuffer (`bound_for_render`). `render_scene_png`
  was called directly, with no tool and no read, on `<global offwidth="1920" offheight="1080"/>`
  with the request 320×240 → the picture is **320×240** (PNG IHDR 320×240), from one child,
  exit 0.

### 6(b) R127: no hit, no render, for someone who may not read the subject

- **A teammate whose view hides the subject.** Built with the `SourceViewSelection` pattern of
  `tests/test_search.py`, through `tests/test_renderers.py::_hidden_base_for`: a GitHub base
  source, a snapshot, a `SourceRevision`, and B's `SourceViewSelection` with the snapshot active.
  Servo 2 was then moved onto the base source (seeded row, version unchanged).
  - A asked the leg-3 question → `cached true`, 0 work. A may still read servo 2, and the look
    is warm.
  - B asked the same with `show: true` → `{"code": "not_found", "message": "No such entity in
this project", "retryable": false}`.
  - Every counter was 0 (renders, children, reads, gateway, artifacts, findings), and
    `render_view` artifacts created by B: 0.
- **A member of another project with the same entity id.** C, in project Q, asked servo 2's id,
  with `show` false and true → both `{"code": "not_found", "message": "No such entity in this
project", "retryable": false}`, every counter 0, 0 artifacts in Q. This ran while one look of
  servo 2 was warm in the process.

### 6(c) model visibility

A's registry, with A's companion bound (admitted inventory above):

- **`registry.list()` = `model_visible(registry.list())`**, 62 names: add_solus_entry,
  analyze_rail_current, apply_sim_change, bench.cad_import_status, bench.import_cad_scene,
  bench.list_cad_sources, code.resolve_environment, delete_solus_entry, edit_solus_entry,
  extract_rulebook, get_entity, get_envelope, get_environment_divergences, get_finding,
  get_history, get_machine, get_run, get_sim_result, get_telemetry, **kicad.export_netlist**,
  **kicad.list_projects**, label_motifs, make_diagram, onshape.add_feature,
  onshape.create_circle_mate_connector, onshape.create_circle_sketch,
  onshape.create_face_mate_connector, onshape.create_fastened_mate, onshape.create_revolute_mate,
  onshape.extrude_cut, onshape.get_assembly_definition, onshape.get_body_details,
  onshape.get_feature_specs, onshape.get_feature_tree, onshape.get_mass_properties,
  onshape.get_part_bounds, onshape.get_variables, onshape.insert_part,
  onshape.inspect_assembly_geometry, onshape.list_documents, onshape.list_elements,
  onshape.list_parts, onshape.resolve_reference, onshape.restore_fastened_pose,
  onshape.set_variable, onshape.update_feature, propose_part_definition, query_graph,
  read_code_file, read_document, **render_view**, retrieve_errors, run_checkers, search_corpus,
  search_solus, search_workspace, set_hardware_config_field, simulate, solus.connect_integration,
  solus.list_integrations, solus.verify_integration, sourcing.derive_torque.
- **The specs the model is sent** (`prompt.tool_specs`, wire names with `.` → `_`): 62. The only
  names with `kicad`, `export` or `render` in them are `kicad_export_netlist`,
  `kicad_list_projects` and `render_view`.
- **`GET /api/v1/projects/{P}/sol/tools` as A** (the real `deps.get_sol_registry`) → 200, 63
  names: the same 62 plus `hardware.flash_presence` (the route binds the presence service; the
  harness registry does not, deviation 10).
- `kicad.export_schematic_pdf` / `kicad.export_board_pdf` (`kicad_export_schematic_pdf` /
  `kicad_export_board_pdf` on the wire): **in none of the four lists**. `render_view`: in all
  four.

### 6(d) bytes whose headers disagree (I1)

Each was uploaded through `POST /artifacts` as A, as the flagged export's one artifact
(`source_tool kicad.export_schematic_pdf`, its own call id). Then it was handed to
`bridge.service.consume_tool_image(spec=<A's admitted kicad.export_schematic_pdf, returns_image
true>, result=<success with that artifact_ref>)`:

| bytes (from `test_bridge_images.py`)           | `consume_tool_image` | the log line (solus.bridge.service, WARNING)                                                                                                                                    | `checked_image` directly                                                             | the artifact after                            |
| ---------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------- |
| `two_ihdr_png()`, 107 bytes (first IHDR 16×16) | `None`               | `bridge tool kicad.export_schematic_pdf image dropped (the image's headers disagree: 16x16 first, 9000x9000 as decoded): claimed 'image/png', bytes are image/png, 107 bytes`   | `ImageRefusedError: the image's headers disagree: 16x16 first, 9000x9000 as decoded` | `deleted_at` set: consumed once, then dropped |
| `two_sof_jpeg()`, 652 bytes                    | `None`               | `bridge tool kicad.export_schematic_pdf image dropped (the image's headers disagree: 16x16 first, 9000x9000 as decoded): claimed 'image/jpeg', bytes are image/jpeg, 652 bytes` | the same message                                                                     | `deleted_at` set                              |

### 6(e) a tall page (M7)

`render_pages(two_page_pdf(width=100, height=2000), pages=[1], max_pages=1)` (the
`tests/fixtures/datasheet.py` builder) → `page_count 2`, page 1 at **205×4096** (PNG IHDR 205×4096).
That is within `MAX_PAGE_HEIGHT` 4096 at the asked width of 1,400; width-only scaling would have
given 1400×28000.

### 6(f) companion-drawn views are per asker; scene views are shared (M5)

| ask                               | asker   | `cached`  | companion export                    | scripted read             |
| --------------------------------- | ------- | --------- | ----------------------------------- | ------------------------- |
| leg 5, "Which sheet carries SDA?" | A       | false     | 1 (A's session)                     | 1                         |
| the same                          | B       | **false** | 1 (B's own session, B's own upload) | 1 (B's own usage row)     |
| the same                          | A again | **true**  | 0                                   | 0                         |
| leg 1's scene look on servo 2     | B       | **true**  | –                                   | 0 (0 renders, 0 children) |

The process's cache at the end held separate sheet looks keyed by asker A
(`01a18993-94de-…`) and asker B (`01a18993-9503-…`), and the scene looks with asker `null`.

### 6(g) a scene the asker's view hides yields no plan (M6)

The scene model was moved onto the base source B's view replaces (seeded row, version unchanged).
`Renderers.plan(servo 1)` was then called under each person's bound scope:

```json
{
  "a": {
    "renderer": "scene",
    "revision": "scene:01a18993-9718-75fe-bb21-e59e62180ba7:1",
    "labelled": 6
  },
  "b": null
}
```

B's `render_view {servo 1, "which face carries the camera mount?"}` →
`{"rendered": false, "reason": "nothing draws this entity: it has no scene model and no source that
renders it"}`, every counter 0.

### Outside a turn, and renders off

- Without the turn binding (the gated dispatcher alone) → `{"code": "unavailable", "message":
"render_view runs only inside a SOL turn", "retryable": false}`.
- With `connectivity=True` (the scope planner's `exclude_renders`) → `{"rendered": false, "reason":
"connectivity comes from the graph's wires, never from pixels: no render this turn"}`.
- Both made 0 renders, 0 reads.

## M3: `FIXED_PROMPT_TOKENS`

This is the drift test's own recipe (`tests/test_sol_turn_limits.py::
test_the_default_fixed_part_tracks_what_the_runner_measures`). It builds the fully bound registry
(`FakeSolSystems`, an empty `ConnectorRegistry`, a local artifact store) and measures
`system_prompt(GUIDE, …, action_mode DO)` plus `tools_text(tool_specs(model_visible(…)))`
through the type estimator:

```json
{
  "model_visible_tools": 60,
  "system_prompt_tokens": 1482,
  "tool_spec_tokens": 10924,
  "measured": 12406,
  "FIXED_PROMPT_TOKENS": 13000,
  "headroom": 594,
  "bound_holds": true
}
```

The test prints nothing, so the value was measured by the harness the same way. The test passed
in the proxy run.

## Proxy tests (after the live run)

The pytest guard (`ps -eo pid,args | grep -E "[u]v run pytest|[p]ython -m pytest|[p]ytest -q"`)
ran in its own call before each run and printed nothing. Another session's full-suite run had been
live at the start of this session and had finished. Each run was one process, with no `--cov`.

```
cd packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2 uv run --frozen --no-sync pytest -q -rs -p no:cacheprovider tests/test_render_view.py tests/test_vision_extract.py tests/test_vision_postcheck.py tests/test_onshape_render.py tests/test_bridge_images.py tests/test_turn_context.py tests/test_stream.py tests/test_registry.py tests/test_renderers.py tests/test_render_annotate.py tests/test_sol_turn_limits.py tests/test_read_document.py tests/test_allowlist_returns_image.py tests/test_capability_hygiene.py tests/test_vendor_hygiene_api.py tests/test_model_call_sites.py tests/test_gateway_purpose.py tests/test_no_hardcoded_models.py tests/test_edge_writer_ratchet.py tests/test_token_estimator_ratchet.py tests/test_sol_runtime.py tests/test_context.py
264 passed in 83.70s (0:01:23)

cd livebench && PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q -rs -p no:cacheprovider tests/lb_offscreen_test.py
24 passed in 4.16s

cd /home/beeboss/Solus && PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -rs -p no:cacheprovider --junitxml=<acceptance>/p5_proxy_kicad.xml integrations/mcp/kicad/tests
SKIPPED [1] integrations/mcp/kicad/tests/test_installed_divider.py:173: requires opt-in installed KiCad and symbol libraries
486 passed, 1 skipped, 1 xfailed in 9.07s
```

- **The API slice.** The dispatch's 8 files, then the ratchet files: `test_capability_hygiene`,
  `test_vendor_hygiene_api`, `test_model_call_sites`, `test_gateway_purpose`,
  `test_no_hardcoded_models`, `test_edge_writer_ratchet`, `test_token_estimator_ratchet`,
  `test_sol_runtime` (the `.invoke(` ratchet and the `render_view` registration and skip), and
  `test_context` (the `.render()` ratchet).
  - Added, deviation 11: `test_renderers`, `test_render_annotate`, `test_sol_turn_limits` (M3's
    drift test), `test_read_document` (M7's pin) and `test_allowlist_returns_image`.
  - 0 skipped (`-rs` printed none), 0 failed.
- **The offscreen slice ran on the real engine, EGL.** The KiCad skip is the opt-in
  installed-KiCad test and the xfail is the known upstream round trip, both pre-existing (as in
  the P5 report).
- Logs: `acceptance/p5_proxy_pytest.log`, `p5_proxy_offscreen.log`, `p5_proxy_kicad.log` (+
  `.xml`), each with its `.time`. `.coverage` md5 unchanged, the tree clean.

## Deviations from the brief and observations

1. **The scene model row is seeded, as the tests seed it.** The production import route was
   offered the fake-arm text first.
   - It refused: `POST /api/v1/projects/{P}/bench/scene/models {robot_id, artifact_id, name,
format "mjcf"}` → **422** `{"error": {"code": "invalid_model", "message": "Model XML is
invalid, unsupported or exceeds scene limits.", "details": []}}` (observation 1).
   - The row then followed `tests/test_renderers.py::_scene_for_arm`: kind `bench_scene_model`,
     `model {joints: []}`, `robot_id`, `artifact_id`, `bindings`. The file went through
     `POST /artifacts` and is kept (`retained`).
   - Both servos are bound (joint_1 → servo 1, joint_2 → servo 2); the test binds servo 2 only.
   - The text is `livebench/tests/lb_offscreen_test.py::FAKE_ARM_MJCF`, read from that file's
     syntax tree and never executed (importing the test would spawn `ldconfig` through
     `ctypes.util`). It is the text the real engine is proven against: it has a floor and
     colours. `test_renderers.FAKE_ARM_SCENE` is the same arm without them; the API test stubs
     the renderer.
2. **Leg 3's read names the part by its label.** The post-check attributes a sentence only when it
   names exactly one labelled part, as whole words, and the fake arm has no "bracket". So the read
   says "Servo 2 (joint 2) is about 95 mm long." The dispatch's sentence, run directly, is left
   as read (item 3). The geometry and both bumps are ORM writes on the seeded part, with the attrs
   reassigned and never mutated in place.
3. **No full SOL turn with model rounds.** Each `render_view` ran under the runner's own
   composition: `with_perception(with_turn(withhold_server_driven(build_dispatch(…)), turn_id),
budget, …)`, with the round's call noted first. No turn model was called. The only model calls
   are the five scripted vision reads the legs name.
4. **Seeded rows where only a provider or a companion makes them.**
   - The KiCad and Onshape sources and their entities.
   - The Onshape listing, written through the connector's own cache path, and the placeholder
     secret.
   - B's hidden-view rows (`_hidden_base_for`).
   - The companions are in-process `BridgeSession`s whose inventory went through the real
     cloud-side gate. Each export is uploaded through the real `POST /artifacts` as its person,
     and its result delivered through `ingest_result`.
   - All 8 seeded sources (both attempts' KiCad, Onshape, base and snapshot) were set
     `disconnected` at the end, so no worker sweep takes one.
5. **The leg-4 ledger** was scripted with `CallMeter.record(200)` × 1,750 under the production
   allowance and ratio. Its 4 keys were deleted after the leg, in a `finally`.
6. **6(a)'s scenes are seeded rows.** The import route would refuse the fake-arm base anyway
   (deviation 1). Two variants were added: a4 (`offsamples` where the dispatch placed it) and a
   direct `render_scene_png` call for the clamp.
7. **6(d) called `consume_tool_image` directly**, as the dispatch says, on uploads made as the
   companion makes them. 6(e) called `render_pages` directly.
8. **M3's value was measured by the harness** with the test's own recipe, because the test prints
   nothing.
9. **B joined through the production invite routes.** No membership row was seeded.
10. **The harness registry binds no presence service.** `GET /sol/tools` binds one, so it lists
    `hardware.flash_presence` as well. `render_view` takes nothing from it.
11. **The proxy slice adds 5 files** to the dispatch's 8 plus the ratchets (listed above).
12. **`SOLUS_REDIS_URL` was exported per process as well**, as in P4's recipe: the integration
    cache, the quota meter and the frequency cap need Redis. Without it the meter fails open and
    leg 4 could not refuse.
13. **Two void attempts**, both harness assumptions. Kept as `p5_accept_live_VOID{1,2}*`.
    - **21:26:14Z**: the harness imported the scene through the route, and the route refused it
      with 422 (deviation 1, observation 1).
    - **21:29:20Z**: the harness's `park` stand-in raised instead of returning `None`. With a park
      wired, `gate_tool_call` asks `park` for every call, and the real `request_confirmation`
      answers `None` for an ungated tool (P4's harness wired that). Every ask failed before the
      tool ran: 0 renders, 0 reads.
    - Void attempt 2's leg 4 had already scripted its ledger. I deleted its 4 Onshape keys by
      exact name (year ledger at 1750, `agent_read` label, listing, `__keys` index) before the
      final run. Its sources were disconnected by its own teardown.
14. **Observations, harmless or worth a ticket, none a failure of a leg:**

    1. **No production route makes the scene P5 renders.** `livebench/scene/parser.py::_mjcf`
       (behind `POST /bench/scene/models`) requires several things the fake arm's scene does not
       state, and P5 is accepted on it:

       - `<compiler angle="radian">`;
       - an identity root pose (the fake arm's `base` sits at `pos="0 0 0.05"`);
       - an explicit `range` on every hinge;
       - box, sphere or cylinder geoms (the arm is a `capsule` with `fromto`).

       So the renderer is proven here on a seeded scene row. A scene the import parser accepts
       was not rendered live.

    2. **`change_signal` ignores the entity version.** It digests the scene's
       `scene:<id>:<version>` and each labelled entity's id, name and attrs, as sol-depth.md
       states. A version bump with the same attrs is a cache hit. The dispatch's "bumping the
       part's version (a new `change_signal`)" holds when the bump changes the attrs, which is
       what a real write does.
    3. **"Which face carries the camera mount?" names no side.** `choose_view`'s vocabulary needs
       front, back, top and the rest, so the view is `iso`, and the whole model is framed.
    4. **The degrade refusal's reason** is the meter's own sentence, "close to the provider API
       allowance; deferrable work is paused". It names neither the ratio nor the provider, and
       the tool result carries no code; the `quota_degraded` code stays on the
       `ConnectorError`.
    5. **`offsamples` on `<global>` is not capped by the guard**, which caps it on `<quality>`,
       where this engine reads it. Such a scene starts one capped child, where the engine refuses
       the attribute at compile. The reason is the generic "the model does not compile", and the
       child exits 0 in 0.67 s.
    6. **The annotation adds a caption band under a picture the gate already capped.** Here it
       added 26–40 px: 600 → 626 and 640, 1000 → 1040. The annotated PNG is Solus's own output
       and does not re-pass `checked_image`. So a page rasterised at the 4096-px cap would reach
       the vision call a band taller than 4096. This was read from `render_annotate.py`, not run.

## Not verified here

- **The one cached live Onshape render under the degrade ratio.** No Onshape call was made, as
  dispatched. `tests/test_onshape_render.py::test_one_call_per_revision_and_view_then_the_cache`
  (MockTransport) passed in the proxy run.
- **A fork-side KiCad PDF export against a native `kicad-cli`.** There is none here. The fork's
  `test_pdf_export.py` uses a fake CLI and passed 12/12.
- **A real model's vision read, and a full SOL turn with model rounds proposing `render_view`.**
  Neither was run (deviation 3). Nor was the chat's artifact card in the desktop UI
  (`ARTIFACT_TOOLS`); the shown artifact was fetched through the artifacts route.
- **A scene that the import route accepts**, rendered (observation 1). Mesh scenes are refused by
  design.

## Left behind

- **In `solus_sol`.** Counts before void attempt 1 → after the final run:

  |                  | before | after                                             |
  | ---------------- | ------ | ------------------------------------------------- |
  | users            | 15     | 24                                                |
  | projects         | 21     | 27                                                |
  | memberships      | 31     | 49                                                |
  | `credit_ledger`  | 17     | 31 (9 `trial_grant`, 5 `usage`)                   |
  | of which `usage` | 6      | 11                                                |
  | findings         | 268    | 269 (the one `vision_fact_disagreement`, count 2) |
  | scene models     | 3      | 10 (void attempt 2: 2, final: 5)                  |
  | entities         | 1,159  | 1,364                                             |
  | edges            | 1,404  | 1,659                                             |
  | sources          | 18     | 26 (8 seeded, all `disconnected`)                 |
  | artifacts        | 17     | 33                                                |
  | jobs             | 14     | 14                                                |

  - The final run's projects: P `01a18993-953a-…` and Q `01a18993-9583-…`. Void attempt 1:
    `01a1898e-71e0-…` and `01a1898e-721e-…`. Void attempt 2: `01a18991-4a61-…` and
    `01a18991-4ab5-…`.
  - The artifact rows' blobs lived in each process's temporary artifact root, removed at exit, so
    those rows point at nothing. The worker's sweep takes the expired, non-retained ones after
    the 1 h TTL. The retained scene files stay as rows.
  - The final run's scene model and servo 2 sit on the hidden base source (6(b), 6(g)).

- **Not touched:** `solus`, `solus_sol_p1`, and every `solus_test_*` except `solus_test_d7fa72c2`
  (the proxy run truncates it, as designed).
- **Redis 6390:** three `solus:upload-budget:bytes:*` keys, each with its own expiry (≤ 1 h). The
  frequency-cap and request-budget keys had expired by 21:41Z, and every Onshape key from both
  attempts was deleted. `solus-redis-1` was never touched.
- **Processes:** the 5 render children, the harness's own, exited 0 by themselves. Nothing else
  was started, stopped or killed (no `pkill`, no `pgrep -f`).
- **Files** (the git-ignored plan workspace):

  - `acceptance/p5_accept_live.py`, `p5_accept_live_result.json` with `.stdout`, `.stderr` and
    `.time`, and the two `p5_accept_live_VOID{1,2}*` sets;
  - `p5_leg1_render.png`, `p5_leg1_annotated.png`, `p5_leg3_annotated.png`,
    `p5_leg5_annotated.png` and `p5_vision_input_{1..5}.png`;
  - `p5_png_labels.py` and `.json`, `.stdout`, `.stderr`;
  - `p5_proxy_pytest.{log,time}`, `p5_proxy_offscreen.{log,time}` and
    `p5_proxy_kicad.{log,time,xml}`;
  - `reports/`: this report.

  No tracked file changed.
