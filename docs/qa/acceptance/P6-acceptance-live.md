# P6 acceptance, live proof (SOLUSDEV-321 plan §3 "P6 acceptance"; dispatch legs 1–7 with "P6 as landed" and "After fix round 1"): in process, copy of the dev DB, no provider, this host's `/opt/ros/jazzy`

One harness process, `acceptance/p6_accept_live.py`, in process (httpx.ASGITransport: no listening
socket) against `solus_sol` and the branch Redis on 6390. The companions are in-process bridge
sessions whose hello inventory is exactly what each server advertises (`acceptance/p6_inventory.json`,
built by `p6_inventory.py` from the local and code forks' own FastMCP servers and the companion's
builtin MachineServer), gated by the real allowlist. Every answer is the fork's (or the builtin's)
own function, called in process, encoded by the companion's frame encoder (`tool_result_ok` /
`map_result`) and parsed by the cloud's `parse_frame` before `ingest_result`. The leg-4 reads ran
the real `/opt/ros/jazzy/bin/ros2` through the code fork's Landlock sandbox. No ROS node was
started. Every model call reached the real gateway with a counted harness adapter; the real adapter
registry raised. Two earlier attempts are void (deviation 10). `t` below is seconds after the final
run's harness was built (07:01:22.077Z).

## Verdicts

- **1. `ros2_ws` through the local-folder connector → nodes and topics under the repo node,
  `publishes`/`subscribes` at 0.9: PASS.**
  - Driven as a companion scan arrives: `POST /api/v1/projects/{P1}/local-folder` → 201, the
    inline sync dispatched `local.scan_folder` to A's companion, which answered with the local
    fork's own `scan_folder(fixtures/ros2_ws)` (its `ros` built by `collect_ros_packages`), 7,219 B
    as the companion's frame encodes it.
  - Landed under the clone `ros2_ws` (`local_folder`) by `contains` (connector, 1.0):
    `ros_node /robot/talker` `01a18b9c-fda3-7c8c-b9c3-17ec05aab3dc`, `ros_node /listener`
    `01a18b9c-fda2-78b5-a7c2-98b5cbc4b88a`, `ros_topic /robot/chatter`
    `01a18b9c-fda4-7fc4-89d4-9930a1d82fe2` (`type std_msgs/msg/String`).
  - `publishes` `01a18b9c-fe17-7d55-850e-361071ff83fa` /robot/talker → /robot/chatter and
    `subscribes` `01a18b9c-fe16-7765-8b00-3147a71f6dff` /listener → /robot/chatter: both
    `inferred`, 0.9, evidence `config` with `ref` `src/talker_py/launch/talker.launch.py:11` and
    `src/listener_py/launch/listener.launch.xml:3` (each launch file's `Node(`/`<node` line).
    `ros_edges.infer`: created 2.
  - Re-sync through the route: `local.folder_digest` only, "sync skipped (unchanged)", the graph
    identical. Forced re-sync (the worker's `execute_source_sync(force=True)`): one scan, `ros_edges`
    created 0, skipped 2, the graph identical (same ids, versions, confidences, evidence). No
    duplicate edge by `(src_id, dst_id, relation)` (SQL below).
  - Fix round 1: `executable="talker.py"` lands `/robot/script_talker` (executable `talker.py`, no
    topics); `executable="tal ker"` lands nothing. A re-sync whose scan has no ROS package
    tombstones the ROS rows and retires both inferred edges (`ros_edges retired=2`).
- **2. `plain_repo` shows nothing ROS: PASS.** The fork's scan has `ros: []` (present and empty,
  not absent); the cloud's `FolderScan.ros` is `[]`. The graph gains `local_folder plain_repo` and
  `python_code` only: 0 `ros_*` rows, 0 `publishes`/`subscribes` edges.
- **2/7. The ROS frame budget with non-ASCII text: PASS.** Four packages whose launch files carry
  15,561 characters (30,921 B of UTF-8, `é` ×15,360). The fork kept `pkg_a`, `pkg_b` whole and
  `pkg_c` as its manifest only, `incomplete: true`; `pkg_d` was dropped. `ros` encoded 186,812 B ≤
  `ROS_FRAME_BUDGET_BYTES` 262,144; the whole answer 189,123 B ≤ the cloud's 1,048,576. The
  companion logged "ros part cut at its frame budget after 3 packages". The rest landed:
  `local_folder bulky_ws`, `python_code`, `/node_a`, `/node_b`, `/status`, and two `publishes`
  edges at 0.9.
- **3. `module_contract_mismatch` fires on `policy_mismatch`: PASS** (two results, observation 3).
  - Path: the code-content path (a GitHub source, `read_software` through `CodeContentReader` over
    an `httpx.MockTransport`). The local scan states no module interfaces (0 rows): it ships ROS
    texts only.
  - FactStore `module_interfaces`: `config/controller.yaml:4` controller inputs 7;
    `config/policy.yaml:5` policy outputs 6 (checkpoint recorded, never opened);
    `envs/arm_env.py:12` policy outputs 6.
  - `run_matrix` → `["fail", "fail"]`, WARNING, "`config/policy.yaml`'s action space is 6 wide but
    `config/controller.yaml` takes 7 inputs" and the same for `envs/arm_env.py`. Each evidence is
    `{policy_ref, action_dim 6, controller_ref config/controller.yaml:4, input_dim 7}`: the
    controller ref is the `joints:` line. 2 findings raised.
  - Arm (6) + gripper (1) `controllers.yaml` beside a 6-wide policy → exactly ONE `unknown_input`,
    `policy and controller pairing`, subjects (policy file, controllers file); no fail, no pass.
  - `plain_repo` on a code host → one `unknown_input` (`module_interfaces`), no fail, no finding.
- **4. `code.ros2_nodes` with this host's `/opt/ros/jazzy` system profile: PASS.**
  - The profile was captured the way the fork captures (`tool_profile_capture`'s calls): 12
    variables, 5 of the 26 judged ones present (AMENT_PREFIX_PATH, CMAKE_PREFIX_PATH,
    LD_LIBRARY_PATH, PATH, PYTHONPATH), none naming the folder. `program_scope`: **system**.
  - The fork's `ros2_nodes`/`ros2_topics`, in process, real `ros2` (fixed argv, `--no-daemon`)
    inside Landlock (abi8), cwd a fresh empty `/tmp/solus-ros2-*`. Live list: nodes `[]`; topics
    `/parameter_events [rcl_interfaces/msg/ParameterEvent]`, `/rosout [rcl_interfaces/msg/Log]`.
  - Through the cloud wrapper the same reads raised nothing: entity/edge counts 32/36 before and
    after, identical rows. `_ros2_daemon`: 0 before and 0 after every one of the 4 real runs, and 0
    on the host before and after the harness and after the proxies.
  - No ROS node runs here, so the matching bump was driven through the fork's own `Runner` seam
    with a scripted stdout (deviation 2).
    - `/robot/talker` raised `01a18b9c-fe17-…` 0.9 → 1.0 through `annotate_edge` (+`bus_enumeration`
      "ros2 node list", "seen live: /robot/talker"; origin stays `inferred`).
    - `/robot/chatter [std_msgs/msg/String]` raised the listener's edge 0.9 → 1.0.
    - `/ghost` and `/ghost_topic` created nothing: 32/36 rows before and after, no `ghost` row.
  - Refusals:
    - The workspace-overlay profile and the `PYTHONUSERBASE=<folder>/.local` profile are each
      refused "the profile reaches the linked folder (a workspace overlay): use code.exec", with
      0 spawns.
    - No profile, and an unknown one, answer "ros2 not available: capture a ROS profile first".
  - A 16,422 B listing cut to 16 KiB never answers its first line `/arm/x`. `confirm_live` raises
    0 for ungrammatical spellings of real names. Another project's listing of the same names
    raises nothing in P1.
- **5. Firmware recipe on the fake arm's board: PASS.**
  - In ONE Build turn: `firmware_recipe {board_id: fake brain, path: fw/fake_arm.ino}` → `{path,
    content, card_rows 3, next}`, read through the owned write's dry run. Then the
    `machine.write_file` it proposes: the Build policy's decision is `false` (forced card), and the
    gate parked a `pending` card `01a18b9d-2459-7b45-b1dd-bb17f91002ac` with the full diff rows.
  - The same owned write in a Build turn no recipe routed: decision `true` (Build would run it
    itself; not executed).
  - A 16,4xx-character reply → "The new file would take 43 card rows; a write card shows 40 rows of
    400 characters. Nothing was proposed."
  - An out-of-topology path → "The graph does not name fw/other.ino as this board's firmware;
    named: fw/fake_arm.ino." Identical with the file present and absent, and the companion
    received no frame for either.
  - Another project's board → "board_id names no board in this project."
  - Writes: the companion received 5 `machine.write_file` frames, all `dry_run: true`, 0 writes;
    `fw/fake_arm.ino` sha256 `8fa8af93…fc66` before and after; 1 file before and after.
- **6. Expertise: PASS** (the sweep's order after detection: NOT VERIFIED live, proxy pins).
  - Only the four levels land on the member node: A in P1 after the local sync gets
    `{"expertise": {control, electronics, mechanical, software: "working"}, "display_name": …}`, no
    other key. `compute_expertise(P1, A)` gives the same.
  - Recompute after a code-source sync: the `sync ok` line and the `sync.completed` activity row,
    then `store_expertise` for the source's creator.
  - `expert` needs questions (m6): E's 12 `.py` files (software signal 10) → `working`. After three
    software questions through the SOL route, the next code sync → software `expert`.
  - The override changes the SOL prompt by exactly one line (line 18 of 20):
    "By domain: be terse and skip basics in software (expert)." → "By domain: explain fundamentals
    and define terms in control (novice); explain fundamentals and define terms in software
    (novice)." 0 model calls: the first tier answered.
  - Both narration prompts end "… By domain: be terse and skip basics in software (expert)." after
    their mode note.
  - The member gate (R139): H, removed through `DELETE /teams/{t}/members/{H}` (204), is not
    listed by `_members_due()`. The sweep's step `_recompute_one` returns 0 and H's attrs keep the
    same value and `updated_at`.
- **7. Ratchets: PASS.** `grep -rniE "gym|hydra|torch|lerobot|stable.?baselines|ros2_control"
  packages/api/src/solus_api/software` → no output, exit 1. `tests/test_vendor_hygiene_api.py`,
  `test_capability_hygiene.py` and `test_model_call_sites.py` passed in the proxy slice. A
  `credentials/config.py` and an `apikey.py` planted beside the talker's node are neither in the
  ROS payload nor read by its reader; `talker.py` ships (observation 2).

**Model calls: 4 scripted, 0 real, 0 refused.** The calls were the recipe's two asks (leg 5), the
finding narration and the runs narration (leg 6). Each was one `gateway.complete` reaching one
`gateway.stream`: 8 counted calls, 4 `model call start` lines and 4 `credit_ledger` usage rows. 0
refusing-adapter reaches, 0 real adapter-registry builds, 0 unscripted reaches, nothing left in
either script. The dispatch heading reads "0 model calls"; legs 5 and 6 need one reply per ask by
design (deviation 1). **`_ros2_daemon`: 0 before, 0 after.** Children: 7, all the code fork's
Landlock helper (3 profile captures, 2 `node list`, 2 `topic list`), each exit 0. 0 spawns denied.

Ready to paste into the SDD ledger:

> P6 acceptance (live, in process, DB copy `solus_sol` at a32000000006, Redis `solus-redis-321`,
> no provider: 4 scripted model calls (recipe ×2, narration ×2), 0 real, 0 refused, 4 `model call
> start` lines, 4 usage rows; egress loopback-only; 1 `.env` read refused; 7 Landlock children of
> the code fork, exit 0; `_ros2_daemon` 0 → 0; no ROS node started). Leg 1: the local fork's
> `scan_folder` over `fixtures/ros2_ws` through `POST /local-folder` → `/robot/talker`, `/listener`,
> `/robot/chatter` under the clone; `publishes`/`subscribes` inferred 0.9, `config` refs
> `talker.launch.py:11` / `listener.launch.xml:3`. Route re-sync skipped (digest), forced re-sync
> skipped 2, graph identical, no duplicate by id. `talker.py` lands, `tal ker` does not; a ROS-less
> re-sync retires 2. Leg 2: `ros: []`, nothing ROS. 2/7: four é packages → 2 whole + 1 manifest
> (incomplete) + 1 dropped, 186,812 B encoded, 189,123 B frame, the rest landed. Leg 3 (code-content
> path): 2 fails 6 vs 7, controller ref `controller.yaml:4`; arm+gripper → one `unknown_input`
> (pairing), no fail; plain → `unknown_input`. Leg 4: the `/opt/ros/jazzy` profile judged system
> (26 variables); live nodes `[]`, topics `/parameter_events`, `/rosout`; nothing raised. A
> scripted listing through the fork's runner seam raised the talker and listener edges 0.9 → 1.0;
> `/ghost` created nothing. Both overlays, `PYTHONUSERBASE` included, refused "use code.exec" with
> 0 spawns; no profile → "ros2 not available"; the cut listing drops `/arm/x`; neutral cwd
> `/tmp/solus-ros2-*`. Leg 5: forced card (policy `false`; unrouted `true`), pending card with full
> rows, 43 > 40 rows refused, unnamed path refused uniformly with 0 frames, 5 dry runs, 0 writes.
> Leg 6: four levels only; repo-only → `working`, + questions → `expert`; the override changes one
> prompt line; both narrations carry the register; a removed member is not listed and is not
> written. Leg 7: framework grep empty. Proxies: 400 passed (API), 251 passed (local fork),
> 1332 passed / 16 skipped / 2 failed, the pre-existing pair (code fork). Report:
> `docs/qa/acceptance/P6-acceptance-live.md.

## Run identity

| Item          | Value |
| ------------- | ----- |
| Run time      | **Final:** command 07:01:20.703Z → 07:01:46.421Z, harness 07:01:22.069Z → 07:01:45.623Z, exit 0. **Void attempt 1:** 06:58:41Z → 06:58:43Z, exit 1, refused at import (deviation 10). **Void attempt 2:** 07:00:29Z → 07:00:32Z, exit 1, seed refused by the free plan's team cap (deviation 10). **Proxies:** API 07:07:24Z → 07:09:23Z; local fork 07:09:52Z → 07:09:53Z; code fork 07:10:08Z → 07:10:46Z. |
| Branch        | `SOLUSDEV-321-sol-checker-algorithm` |
| HEAD          | `e9c902a9` before and after. `git status --short` empty throughout. `.coverage` md5 `7571ebfd2af623167baf221f5af68076` before the run and after the proxies. |
| Database      | `solus_sol`, asserted from the server by the harness (`select current_database()`); `alembic_version` `a32000000006`, the branch head (no migration since P4). Nothing applied, created or dropped. |
| Redis         | `redis://127.0.0.1:6390/0`, the branch's `solus-redis-321`; dbsize 0 before void attempt 1. `solus-redis-1` was not touched. |
| Host ROS      | `/opt/ros/jazzy` (`ros2` 958 B script, root-owned), aarch64. Landlock `landlock-abi8` available. No `_ros2_daemon`, no `ros2`, no `talker`/`listener` process before the run (`acceptance/p6_procs_before.json`). |
| Harness       | `/home/beeboss/Solus/.superpowers/sdd/pasted-content-id-24a5-sol-precious-pillow/acceptance/p6_accept_live.py`. Raw evidence beside it: `p6_accept_live_result.json`, `.stdout`, `.stderr`, `.time`; `p6_inventory.py` → `p6_inventory.json` (+`.stdout`, `.stderr`); `p6_procs.py` → `p6_procs_{before,after,after_proxies}.json`; `p6_before.txt`; `p6_leg7_framework_grep.{stdout,stderr,exit}`; void sets `p6_accept_live_VOID{1,2}*`; the scratch home `p6_home/`. |
| Commands      | Inventory: `cd packages/api && PYTHONDONTWRITEBYTECODE=1 uv run --frozen --no-sync python -I <acceptance>/p6_inventory.py`. Harness: `cd packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' timeout 900 uv run --frozen --no-sync python <harness>`. Proxies: below. |

## Environment recipe as executed

1. **Database.** `solus_sol` held P5's leave-behind as void attempt 1 found it: 24 users,
   27 projects, 49 memberships, 31 `credit_ledger` rows (11 `usage`), 269 findings, 1 member node,
   0 ROS rows, 1,364 entities, 1,659 edges, 26 sources, 33 artifacts, 14 jobs, 19 tool
   confirmations, 13 conversation turns.
2. **Environment.** The harness refuses to start unless exactly `SOLUS_DATABASE_URL` and
   `SOLUS_REDIS_URL` hold the prescribed values, and it re-checks the `SOLUS_*` set after its
   imports. That re-check is what stopped void attempt 1. `SOLUS_TEST_DATABASE_URL` was set only
   on the API proxy pytest's command line.
3. **Settings, in code** (as P4/P5): `Settings(_env_file=None, supabase_jwt_secret=<token_urlsafe(32)
   per run>, supabase_jwt_audience="authenticated", rate limits 100_000, sync_inline=True,
   fingerprint_embedding_enabled=False, artifact_local_root=<TemporaryDirectory>)`.
   - The database and Redis URLs were asserted equal to the exports.
   - Defaults were kept: `bridge_tool_result_max_bytes` 1,048,576, `bridge_control_frame_max_bytes`
     16,384, `bridge_tool_call_max_bytes` 262,144, and `bridge_allowlist_root`
     `/home/beeboss/Solus/integrations/mcp`, so the real allowlists load.
   - As loaded: `local.scan_folder`/`folder_digest` and `code.ros2_nodes`/`ros2_topics` are
     unconfirmed; `code.profile_capture` and `machine.write_file` are confirmation-gated.
4. **App.** `create_app(settings, create_async_engine(solus_sol))`, with
   `hardware_connections.owner = RuntimeOwner(<tmp>, <tmp>)`, `agent_runner =
   LlmRunner(adapters=<refusing>)`, and the Narrator's `_complete =
   partial(gateway.complete, adapters=<scripted narration>)` (M88). The lifespan was not run.
5. **The companions** (`P6ACompanion`): one in-process `BridgeSession` per person and project.
   - The hello inventory is `p6_inventory.json`, verbatim: each server's own `list_tools()`
     (FastMCP for the forks, `MachineServer.inventory()` for the builtin), gated by
     `validate_inventory` against the real allowlist.
   - Each `tool_call` frame is answered by the server's own function, called in process:
     - `local.scan_folder` → `local_solus.scan.scan_folder(root, tools=tools_installed())`, as the
       fork's `tool_scan_folder` does;
     - `local.folder_digest` → `folder_digest(root)`;
     - `code.ros2_nodes`/`ros2_topics` → `code_solus.ros2_reads.ros2_nodes|ros2_topics(root,
       profile)`;
     - `machine.write_file` → `MachineServer(workspace).call_tool(...)`.
   - Each answer is encoded with the companion's `tool_result_ok` / `dispatch.map_result`, then
     parsed by the cloud's `parse_frame(raw, control_cap, tool_result_cap)` and handed to
     `ingest_result`, the WebSocket handler's own path for a `tool_result`. 19 frames, 19
     `InboundFrame`s, 0 violations, 0 handler errors.
   - Both forks load under unique package names (`local_solus`, `code_solus`), as their own tests
     load them.
6. **The code fork's home.** For leg 4, `HOME` pointed at `acceptance/p6_home` (holding `.ros/`).
   - The captured profiles landed at `p6_home/.solus/code-profiles/0a6c4b921fe6be05/`.
   - Each real `ros2` logged there: `p6_home/.ros/log/python3_<pid>_<ts>.log` for pids 3798047,
     3798180, 3798223, 3798368, exactly the four spawned children.
   - The person's own `~/.ros` and `~/.solus` were not touched. `~/.solus/code-profiles` still
     does not exist.
7. **Probes, recording only, never raising.** Each wraps and calls the original, by module
   attribute: `local_folder.derive_local_graph` (the scan as the cloud validated it),
   `ros_edges.infer`, `ros_edges.confirm_live`, `ros_edges.annotate_edge`, `code_solus.ros2_reads.
   execute_plan`, `matrix_runner.build_fact_store`, `prompt.system_prompt`,
   `expertise.store_expertise`, `BuildExecutionPolicy.prepare`, `local_solus.ros._read`, the
   gateway's `stream`/`complete`, and one root log handler at INFO. 0 probe errors.
8. **Order of steps.** Void attempts 1 and 2. The final run: seed → 7(a) planted credentials → 1 →
   1 variants and the ROS-less re-sync → 2 → 2b → 4 → 3 → 5 → 6 → ledger read → every source this
   run created set `disconnected` → teardown. Then the /proc check, then the pytest guard in its
   own call (empty) before each of the three proxy runs, and the proxies.

## Why no real provider was reachable

1. **Every gateway call carried harness adapters.**
   - `gateway.complete` and `gateway.stream` were wrapped as module attributes before any app was
     built, and the runs narration's by-name `complete` was pointed at the wrapper.
   - A call with no adapters got the scripted answer adapter for `purpose == "answer"`, the
     scripted narration adapter for `purpose == "narration"`, else the refusing one.
   - The 4 `complete` calls:
     - two `answer` calls (the recipe, type `code`, injected);
     - the finding narration (the Narrator's own scripted adapters);
     - the runs narration (injected).
   - Each reached one `stream` with those adapters.
2. **The real adapter registry raises.** `gateway.build_adapter_registry` was replaced by a
   function that records and raises: 0 reaches.
3. **The refusing adapters** (the runner's, and any other call's): 0 reaches. The two SOL turns
   whose prompts leg 6 reads were answered by the first tier with no model call. The six question
   turns ran on the in-tree model-free `ScaffoldRunner` (deviation 6).
4. **No credentials.**
   - The secret store is `InMemorySecretStore`. Its values were put by the harness for the four
     seeded GitHub sources' `secret_ref`: `p6-acceptance-placeholder-not-a-credential`.
   - `secrets_key` unset, `aws_region` None, `supabase_url` None, `sentry_dsn` unset. The JWT secret
     is per run.
5. **No `.env` read.** `DotEnvSettingsSource._read_env_files` refuses and records: 1 refusal
   (`/home/beeboss/Solus/.env` at import, t −0.704; the stderr line is toolkb's ephemeral
   vote-salt notice).
6. **Egress, bind and spawn guards.**
   - In process, only loopback 5432/6390 may connect and only loopback names resolve. There were
     7 attempts: `bind ('::1', 0)` denied (urllib3's import-time IPv6 probe, as P3–P5), resolve
     `localhost:5432` ×2, connect `127.0.0.1:5432` ×2, connect `127.0.0.1:6390` ×2.
   - The only processes admitted are the code fork's Landlock helper, exactly as `sandbox.wrap`
     builds it: `[<this python>, -I, integrations/mcp/code/solus/landlock_exec.py, --env-fd 9,
     --home <p6_home>, --rw <folder>, --rw /tmp, --rw /var/tmp, --rw /dev/null, --rw /dev/zero,
     --rw /dev/tty, --rw <p6_home>/.ros, --, <program>]`, with env exactly `{PATH: /usr/bin:/bin,
     LANG: en_US.utf8}`.
   - `<program>` is either the fixed capture `/bin/bash --noprofile --norc -c 'source "$1" … exec
     /usr/bin/env -0' solus-profile <allowed setup file>` or one of the two fixed `ros2` argv.
   - 7 launches (pids 3797997, 3798047, 3798180, 3798223, 3798368, 3798421, 3798430), each exit 0.
     0 denied spawns, 0 `subprocess.run`.
   - The `ros2` children took part in DDS discovery on UDP, as `ros2 … list` does. The in-process
     guard covers this process only, and the fork's sandbox states "reads, exec and network are
     not restricted".
7. **The code host is a MockTransport.** The leg-3 and leg-6 GitHub sources' blob reads went to an
   `httpx.MockTransport` serving the fixture files (`test_code_content_software.Served`): 6
   requests (P3a 3, P3b 2, P3c 1, E 0).

| Count | 1 (link / route / forced) | 1v (link / ROS-less) | 2 | 2b | 3 (a / b / c) | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Scripted model calls | 0 | 0 | 0 | 0 | 0 | 0 | **2** (recipe; ceiling) | **2** (finding; runs) |
| Refusing reaches | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Companion frames | 1 / 1 / 1 | 1 / 2 | 1 | 1 | – | 6 | 5 (all `dry_run`) | – |
| Real `ros2` runs | 0 | 0 | 0 | 0 | 0 | **4** | 0 | 0 |
| Profile captures | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |
| Code-host requests | – | – | – | – | 3 / 2 / 1 | – | – | 0 |
| `_ros2_daemon` after | 0 | 0 | 0 | 0 | 0 | **0** | 0 | 0 |

`credit_ledger` gained 11 rows in the final run: 7 `trial_grant` (A, B, C, D, E, F, H) and 4
`usage`:

- D, the recipe: −4 (`code_standard`, `claude-fable-5-1`, `tokens_in` 1,155, `tokens_out` 80,
  turn `264a1885-…`) and −44 for the over-ceiling reply (`tokens_out` 4,102, turn `da20ba60-…`).
- E, the narrations: −1 (`openai_standard`, finding narration, no turn) and −1 (`openai_trivial`,
  runs narration, no turn).

The 4 `model call start` lines read `provider=anthropic model=claude-fable-5-1 role=code_standard
complexity=standard type=code purpose=answer turn_id=<that turn>` ×2, `provider=openai
model=gpt-5.6-sol role=openai_standard … purpose=narration turn_id=None`, and `provider=openai
model=gpt-5.6-luna role=openai_trivial complexity=trivial … purpose=narration turn_id=None`. These
are the catalog's routes, answered by the scripted adapters.

## Seed (final run; ids for the record)

People were minted as `tests/conftest.py::make_token` does, and `/users/me` provisioned them.
Teams and projects came from `POST /api/v1/teams` and `POST /api/v1/teams/{id}/projects` (C's three
projects share one team: the free plan holds 2 teams and 3 projects a person). F and H joined P6
through the production invite flow: `POST /teams/{t}/invites` 201, then `POST /invites/{token}/accept`
200 for each.

| Who / what | Id |
| --- | --- |
| A / **P1** (ros2_ws) / **P1v** (variants) | `01a18b9c-f792-7ede-9532-e2fc7151cfa6` / **`01a18b9c-f80a-7957-857e-438201ccf6d2`** / **`01a18b9c-f856-7ee5-a2a9-167ecfb1f880`** |
| B / **P2** (plain_repo) / **P2b** (frame budget) | `01a18b9c-f7b9-77dc-90fb-85553bd5e718` / **`01a18b9c-f88c-71db-9b8f-aaed26be6ad3`** / **`01a18b9c-f8c6-7df0-87f3-cb7cec895e1b`** |
| C / **P3a** / **P3b** / **P3c** (team `01a18b9c-f8f3-77f3-8434-d71e7b699e61`) | `01a18b9c-f7cc-77f1-a021-5f357fe65833` / **`01a18b9c-f8fa-734d-9ac3-a7e5103ea1af`** / **`01a18b9c-f939-74ff-894a-c163069d6f53`** / **`01a18b9c-f967-7e94-b76e-60a36efc9174`** |
| D / **P5** (firmware) | `01a18b9c-f7d5-7d1c-b696-064c5b79e09a` / **`01a18b9c-f996-7f8c-9dde-b0572589ebc7`** |
| E (owner) / F / H / **P6** (expertise; team `01a18b9c-f9c4-7937-9ef4-d3ef0f1b3d15`) | `01a18b9c-f7e1-7c8b-8cca-4038acc6058f` / `01a18b9c-f7e9-7f23-95e7-65380a3bf1c5` / `01a18b9c-f7f4-7c00-8b13-3fe48e2f031f` / **`01a18b9c-f9ce-701a-a285-72ca4e42f94b`** |
| Local sources (route-made) | P1 `01a18b9c-fd6e-7643-bdff-7f84fc30db26`, P1v `01a18b9c-ff1c-7828-af37-f946a9d15388`, P2 `01a18b9d-002c-711b-9364-857da5bad63a`, P2b `01a18b9d-00bd-72b7-b2b6-5cdefc144f24` |
| GitHub sources (seeded rows) | P3a `01a18b9d-21e2-7e8b-b497-23ebda6088a7`, P3b `01a18b9d-2291-7bf8-bd21-eefa7509ddd0`, P3c `01a18b9d-2338-718f-be25-f2e4294911d7`, P6 `01a18b9d-25f1-7498-804f-217c585dbc60` |
| Fake arms (`seed_fake_arm`, production writers) | P5: robot `a336913f-1ae5-…`, **brain `daae65a1-feee-484a-a128-65cbedce1468`**, code file `fw/fake_arm.ino` `a16ac5a6-…`; P6: robot `5e2c8a5e-28ab-40a4-83c6-8834785b5562`, brain `44073b66-a667-4871-926c-c615ce34e291`, servo 1 `398f3a35-6937-4bd7-b451-dc8310541ecc` |
| Companion instance ids | A `c60cbb687efd4eb3a67bbdc1930b7610` (P1, P1v), B `e1ea25d3acbc45a28cd6af426ea6abab`, C `99da508b199c4d07a43030eadede7e18`, D `c6fadcb53cfa4de3a6c521333716620e` |

**The admitted inventories**, from `validate_inventory` at hello:

```json
{"a/p1": [{"name": "local.scan_folder", "requires_confirmation": false, "timeout_seconds": null},
          {"name": "local.folder_digest", "requires_confirmation": false, "timeout_seconds": null},
          {"name": "code.ros2_nodes", "requires_confirmation": false, "timeout_seconds": 30.0},
          {"name": "code.ros2_topics", "requires_confirmation": false, "timeout_seconds": 30.0}],
 "c/p3a": [{"name": "code.ros2_nodes", "requires_confirmation": false, "timeout_seconds": 30.0}],
 "d/p5": [{"name": "machine.write_file", "requires_confirmation": true, "timeout_seconds": null}]}
```

The advertised input schemas are the servers' own, for example `code.ros2_nodes`:
`{"additionalProperties": false, "properties": {"profile": {"anyOf": [{"type": "string"}, {"type":
"null"}], "default": null, "title": "Profile"}}, "title": "tool_ros2_nodesArguments", "type":
"object"}`.

## Leg 1: `ros2_ws` through the local-folder connector

`POST /api/v1/projects/01a18b9c-f80a-…/local-folder {machine_id: c60cbb68…7610, machine_name:
p6-acceptance-host, folder_name: ros2_ws}` as A → **201**, `{bridge: {connected: true}, source
status connected}`, 0.282 s. The source is `01a18b9c-fd6e-7643-bdff-7f84fc30db26`, created by A.
The inline sync dispatched ONE frame, `local.scan_folder {}`, to A's companion.

**The payload, as the fork built it** (`local_solus.scan.scan_folder(packages/api/tests/fixtures/ros2_ws)`;
`root_name ros2_ws`, `git null`, digest `aea3c9ea5216dcd739584d5b905b6962`). The 9 tool files are
the fixture's `.py` files. Its `ros` part, built by `collect_ros_packages` (the fixture is a colcon
workspace, `src/*/package.xml` beside `install/`, so only `src/` counts), is 5,294 B encoded and
the whole frame 7,219 B:

```json
[{"manifest": "src/listener_py/package.xml", "files": [
   {"path": "src/listener_py/launch/listener.launch.xml", "chars": 214},
   {"path": "src/listener_py/setup.py", "chars": 583},
   {"path": "src/listener_py/listener_py/__init__.py", "chars": 101},
   {"path": "src/listener_py/listener_py/listener.py", "chars": 547}], "incomplete": false},
 {"manifest": "src/talker_py/package.xml", "files": [
   {"path": "src/talker_py/launch/talker.launch.py", "chars": 456},
   {"path": "src/talker_py/setup.py", "chars": 572},
   {"path": "src/talker_py/talker_py/__init__.py", "chars": 99},
   {"path": "src/talker_py/talker_py/talker.py", "chars": 611}], "incomplete": false}]
```

The cloud validated it as `FolderScan` (after ingress redaction: 0 masked runs in any ROS text)
and `derive_local_graph` mapped it to `clone:` (`local_folder`), `python:` (`python_code`), four
`package_requirement` rows, `ros_node:/listener`, `ros_node:/robot/talker` and
`ros_topic:/robot/chatter`, each ROS key under `clone:` by `contains`. The sync row
`01a18b9c-fd83-7f37-99f7-bf6cadb6e439` succeeded with 9 entities and 8 relations created and 0
errors.

**The ROS rows, as stored:**

```json
{"id": "01a18b9c-fda3-7c8c-b9c3-17ec05aab3dc", "kind": "ros_node", "name": "/robot/talker", "version": 1, "source_id": "01a18b9c-fd6e-7643-bdff-7f84fc30db26",
 "attrs": {"package": "talker_py", "publishes": ["/robot/chatter"], "executable": "talker", "subscribes": [], "declared_at": {"/robot/chatter": "src/talker_py/talker_py/talker.py:12"}, "launched_at": "src/talker_py/launch/talker.launch.py:11"}}
{"id": "01a18b9c-fda2-78b5-a7c2-98b5cbc4b88a", "kind": "ros_node", "name": "/listener", "version": 1, "source_id": "01a18b9c-fd6e-7643-bdff-7f84fc30db26",
 "attrs": {"package": "listener_py", "publishes": [], "executable": "listener", "subscribes": ["/robot/chatter"], "declared_at": {"/robot/chatter": "src/listener_py/listener_py/listener.py:12"}, "launched_at": "src/listener_py/launch/listener.launch.xml:3"}}
{"id": "01a18b9c-fda4-7fc4-89d4-9930a1d82fe2", "kind": "ros_topic", "name": "/robot/chatter", "version": 1, "source_id": "01a18b9c-fd6e-7643-bdff-7f84fc30db26",
 "attrs": {"type": "std_msgs/msg/String"}}
```

**The edges that touch them:**

| id | relation | origin | confidence | from → to | evidence |
| --- | --- | --- | --- | --- | --- |
| `01a18b9c-fda7-76b5-b2ce-a936480e52a1` | contains | connector | 1.0 | `ros2_ws` → `/robot/talker` | – |
| `01a18b9c-fda6-776e-993a-8df632c0dcd4` | contains | connector | 1.0 | `ros2_ws` → `/listener` | – |
| `01a18b9c-fda8-7dc1-a815-f02845cbd682` | contains | connector | 1.0 | `ros2_ws` → `/robot/chatter` | – |
| **`01a18b9c-fe17-7d55-850e-361071ff83fa`** | **publishes** | **inferred** | **0.9** | `/robot/talker` → `/robot/chatter` | `[{"ref": "src/talker_py/launch/talker.launch.py:11", "kind": "config", "detail": "declared at src/talker_py/talker_py/talker.py:12"}]` |
| **`01a18b9c-fe16-7765-8b00-3147a71f6dff`** | **subscribes** | **inferred** | **0.9** | `/listener` → `/robot/chatter` | `[{"ref": "src/listener_py/launch/listener.launch.xml:3", "kind": "config", "detail": "declared at src/listener_py/listener_py/listener.py:12"}]` |

- `ros_edges.infer` during that sync: `{module: ros_edges, created: 2, updated: 0, skipped: 0,
  candidates: 0}`.
- The clone: `{"kind": "local_folder", "name": "ros2_ws", "attrs": {"head": null, "host": null,
  "branch": null, "remote": null, "truncated": false, "file_count": 9, "machine_name":
  "p6-acceptance-host"}}`.
- Line 11 of `talker.launch.py` is its `Node(` line and line 3 of `listener.launch.xml` its `<node`
  line.

**Re-sync through the route.** `POST /sources/01a18b9c-fd6e-…/sync` → **202** `{job_id
01a18b9c-fe85-…, status queued}`.

- The companion received one frame, `local.folder_digest`. The digest equals the cursor's, and the
  run logged `sync skipped (unchanged) source=01a18b9c-fd6e-7643-bdff-7f84fc30db26
  sync=01a18b9c-fe95-7cdd-9ca5-13159794b977` (sync row: succeeded, 0/0/0/0).
- Before/after: `entities_identical: true, edges_identical: true`, 32 entities and 36 edges live
  both times.

**Forced re-sync** (`connectors/worker.py:execute_source_sync(..., force=True)`, the full pass the
gate skips; no route forces).

- One `local.scan_folder` frame (7,219 B again).
- `ros_edges.infer`: `{created: 0, updated: 0, skipped: 2}`. `sync ok source=01a18b9c-fd6e-…
  sync=01a18b9c-feb2-70e6-8001-38930448609c created=0 updated=0 rels=+0/-0 errors=0`.
- Before/after: identical ids, versions, confidences and evidence.

**No duplicate edges**, read from the database afterwards: `select project_id, src_id, dst_id,
relation_type … group by … having count(*) > 1` over P1 and P1v → no rows. Grouped by names, the
only repeated pairs are `requires ros2_ws → rclpy` ×2 and `→ std_msgs` ×2: two distinct
requirement nodes each, one per `package.xml`. Every ROS pair is single.

### 1, fix round 1: a script executable lands, a spaced one does not

In P1v (A), on a scratch copy of the fixture, the copy's `talker.launch.py` gained two launch lines
(the file as scanned):

```python
            Node(package="talker_py", executable="talker.py", name="script_talker", namespace="robot"),
            Node(package="talker_py", executable="tal ker", name="spaced_talker", namespace="robot"),
```

`POST /local-folder` → 201 (source `01a18b9c-ff1c-7828-af37-f946a9d15388`) landed:

```json
{"id": "01a18b9c-ff40-7481-8e4b-ef712d6cfa4d", "name": "/robot/script_talker", "attrs": {"package": "talker_py", "executable": "talker.py", "publishes": [], "subscribes": [], "launched_at": "src/talker_py/launch/talker.launch.py:17"}}
{"id": "01a18b9c-ff41-7c50-b2f7-b646913b1aea", "name": "/robot/talker", "attrs": {"package": "talker_py", "executable": "talker", "publishes": ["/robot/chatter"], "subscribes": [], "launched_at": "src/talker_py/launch/talker.launch.py:11"}}
{"id": "01a18b9c-ff3f-742f-9295-07e1378bd659", "name": "/listener", "attrs": {"package": "listener_py", "executable": "listener", "publishes": [], "subscribes": ["/robot/chatter"], "launched_at": "src/listener_py/launch/listener.launch.xml:3"}}
```

There is no `/robot/spaced_talker` row: `tal ker` is no identifier, so its line starts no node.
`/robot/script_talker` has no topics, because the `console_scripts` entry names `talker`, not
`talker.py` (observation 7).

### 1, fix round 1 (m4): a re-sync whose scan has no ROS package retires the inferred edges

The copy's `src/` was removed, leaving `install/.gitkeep` alone. `POST /sources/01a18b9c-ff1c-…/sync`
→ 202.

- The companion answered `local.folder_digest` (moved), then `local.scan_folder`: `files []`,
  `ros: []`, digest `cae66941d9efbd404e4d88758ea67670`. The cloud mapped it to `clone:` only.
- The sync row `01a18b9c-ffc3-7891-8eba-6706e7daef62`: 0 created, 1 updated, 9 relations deleted.
- `ros_edges.infer` ran on that sync (the clone is a code kind) and logged `ros_edges retired=2
  project=01a18b9c-f856-7ee5-a2a9-167ecfb1f880`.

| row | before | after |
| --- | --- | --- |
| `ros_node /robot/talker` `01a18b9c-ff41-…`, `/robot/script_talker` `01a18b9c-ff40-…`, `/listener` `01a18b9c-ff3f-…`, `ros_topic /robot/chatter` `01a18b9c-ff42-…` | live | tombstoned |
| `contains` ×4 from `ros2_ws` | live, 1.0 | deleted at 07:01:24.5619Z (the sync's apply) |
| `publishes` `01a18b9c-ff5d-7cc6-a58e-a54ff87ba4b4` /robot/talker → /robot/chatter | **live, inferred 0.9** | **deleted at 07:01:24.583793Z** (`ros_edges` retire) |
| `subscribes` `01a18b9c-ff5b-7db8-ab1e-580353c74434` /listener → /robot/chatter | **live, inferred 0.9** | **deleted at 07:01:24.583791Z** (`ros_edges` retire) |
| counts (live) | 33 entities, 37 edges, 4 ROS rows, 2 pub/sub | 24 entities, 26 edges, 0 ROS rows, 0 pub/sub |

## Leg 2: `plain_repo` shows nothing ROS

`POST /local-folder` as B on P2 → 201 (source `01a18b9d-002c-711b-9364-857da5bad63a`), one
`local.scan_folder` frame of 488 B.

- The fork's answer for `packages/api/tests/fixtures/plain_repo`: `files: ["tools/plain_tool.py"]`
  and **`ros: []`**, present and empty, not absent.
- The cloud's validated scan: `ros_is_none: false, ros: []`, mapped to `clone:` (`local_folder`)
  and `python:` (`python_code`), with one `contains`.
- The project's graph: kinds `local_folder, member, python_code, solus_*` (the new project's
  `.solus` scaffolding). `ros_entities_live` 0, `publishes_subscribes_live` 0.
- `plain_tool.py`'s `create_publisher("not-ros", "/not_a_topic", 10)` is text only: no
  `package.xml`, so no ROS read happened.

## Leg 2/7: the ROS payload within its frame budget, with non-ASCII text

The scratch workspace `bulky_ws` holds four packages (`pkg_a`–`pkg_d`), each with a manifest, a
`setup.py` (`console_scripts` `node = <pkg>.node:main`), `<pkg>/node.py`
(`create_publisher(String, "status", 10)`) and `launch/<pkg>.launch.py` (one `Node(...)` and a
comment of `é` ×15,360: 15,561 characters, 30,921 B of UTF-8, under `MAX_FILE_BYTES` 32,768). One
plain `tools/report.py` sits outside them.

`POST /local-folder` as B on P2b → 201 (source `01a18b9d-00bd-72b7-b2b6-5cdefc144f24`). The
fork's answer:

```json
{"ros_encoded_bytes": 186812, "ros": [
  {"manifest": "src/pkg_a/package.xml", "files": [["src/pkg_a/launch/pkg_a.launch.py", 15561], ["src/pkg_a/setup.py", 112], ["src/pkg_a/pkg_a/__init__.py", 0], ["src/pkg_a/pkg_a/node.py", 133]], "incomplete": false},
  {"manifest": "src/pkg_b/package.xml", "files": [["src/pkg_b/launch/pkg_b.launch.py", 15561], ["src/pkg_b/setup.py", 112], ["src/pkg_b/pkg_b/__init__.py", 0], ["src/pkg_b/pkg_b/node.py", 133]], "incomplete": false},
  {"manifest": "src/pkg_c/package.xml", "files": [], "incomplete": true}]}
```

- `pkg_d` was dropped. The companion logged (`solus.local.ros`, WARNING) "ros part cut at its
  frame budget after 3 packages".
- 186,812 ≤ `ROS_FRAME_BUDGET_BYTES` 262,144, while the UTF-8 text alone (~123 KiB) was inside
  `MAX_TOTAL_BYTES` 262,144: the budget measured the escaped encoding, where `é` costs 6 bytes.
- The whole `tool_result` frame, as the companion's `tool_result_ok` encoded it: **189,123 B** of
  the cloud's 1,048,576. `parse_frame` → `InboundFrame`, ok.
- The rest of the scan landed (sync `01a18b9d-00cd-…`: 5 created, 4 relations, 0 errors):
  `local_folder bulky_ws`, `python_code "bulky_ws (python)"`, `ros_node /node_a`, `ros_node
  /node_b`, `ros_topic /status`, `contains` ×4, and `publishes` `/node_a → /status` and `/node_b →
  /status`, both inferred 0.9. `pkg_c` (manifest only) starts no node.

## Leg 3: `module_contract_mismatch` on `policy_mismatch` (the code-content path)

**Which path landed: the code-content path.** Each project got a GitHub source (a seeded row: a
connect needs GitHub). Its sync was the real `connectors/runtime.run_sync(force=True,
registry=<the app's>)` over `test_code_content_software._ScriptedGitHub`, whose `sync()` answers
the fixture's files as `repo_result` builds them (a `code_repo` plus one `code_file` per file at
commit `a…a`). The real `read_software` then read the candidates through `CodeContentReader`, its
`_http` an `httpx.MockTransport` serving the blobs, and `_commit_success` and `infer_after_sync`
followed. The local scan states no module interfaces: 0 rows across P1, P1v, P2 and P2b, because
the companion ships ROS texts only.

**P3a: the fixture** (`config/controller.yaml`, `config/policy.yaml`, `envs/arm_env.py`), source
`01a18b9d-21e2-7e8b-b497-23ebda6088a7`.

- MockTransport requests:
  - `/repos/p6-acceptance/policy-mismatch/git/blobs/379443ce…`
  - `/repos/…/640f0516…`
  - `/repos/…/e5aa94ab…`
- Files read: `config/controller.yaml`, `config/policy.yaml`, `envs/arm_env.py`.
- `sync ok source=01a18b9d-21e2-… sync=01a18b9d-21f4-7175-86b2-42f75b966f29 created=4 updated=0
  rels=+3/-0 errors=0`.

The `policy_reader` facts, as `matrix_runner.build_fact_store` handed them to the run
(`FactStore.module_interfaces`, holder → `{source_id, interfaces}`):

```json
{"01a18b9d-21fe-7c0a-922a-bf8ec2a1e90b": {"source_id": "01a18b9d-21e2-7e8b-b497-23ebda6088a7", "interfaces": [{"role": "controller", "inputs": 7, "outputs": null, "ref": "config/controller.yaml:4", "checkpoint": null, "ambiguous": []}]},
 "01a18b9d-21ff-764d-9176-7dfc2e9c27bc": {"source_id": "01a18b9d-21e2-7e8b-b497-23ebda6088a7", "interfaces": [{"role": "policy", "inputs": 24, "outputs": 6, "ref": "config/policy.yaml:5", "checkpoint": "checkpoints/arm_policy.pt", "ambiguous": []}]},
 "01a18b9d-2200-73b2-bb6b-bd84487afb3a": {"source_id": "01a18b9d-21e2-7e8b-b497-23ebda6088a7", "interfaces": [{"role": "policy", "inputs": 24, "outputs": 6, "ref": "envs/arm_env.py:12", "checkpoint": null, "ambiguous": []}]}}
```

The three holders are the `code_file` rows `controller.yaml`, `policy.yaml` and `arm_env.py`
(`attrs.module_interfaces`). The checkpoint path is recorded, never opened.

`run_matrix(db, P3a)` (writing, as the matrix job calls it) → `module_contract_mismatch` `["fail",
"fail"]`, `findings_raised 2`:

```json
{"status": "fail", "severity": "warning", "message": "`config/policy.yaml`'s action space is 6 wide but `config/controller.yaml` takes 7 inputs", "subjects": ["01a18b9d-21ff-764d-9176-7dfc2e9c27bc", "01a18b9d-21fe-7c0a-922a-bf8ec2a1e90b"], "evidence": {"policy_ref": "config/policy.yaml:5", "action_dim": 6, "controller_ref": "config/controller.yaml:4", "input_dim": 7}}
{"status": "fail", "severity": "warning", "message": "`envs/arm_env.py`'s action space is 6 wide but `config/controller.yaml` takes 7 inputs", "subjects": ["01a18b9d-2200-73b2-bb6b-bd84487afb3a", "01a18b9d-21fe-7c0a-922a-bf8ec2a1e90b"], "evidence": {"policy_ref": "envs/arm_env.py:12", "action_dim": 6, "controller_ref": "config/controller.yaml:4", "input_dim": 7}}
```

- The two findings: `01a18b9d-2277-7e6b-b469-d2cccfc0143f` and `01a18b9d-227e-7448-a704-6377483c87c0`,
  both `module_contract_mismatch`, WARNING. Their headlines are the messages and their evidence
  is the same four keys.
- `config/controller.yaml:4` is its `joints:` line (line 2 is `controller:`). That is the fix
  round's "the single-controller mismatch still fails with the controller `ref` on the joints
  line".

**P3b: an arm (6 joints) and a gripper (1) beside a 6-wide policy** (scratch repo; source
`01a18b9d-2291-7bf8-bd21-eefa7509ddd0`).

- Files: `config/policy.yaml` `policy:\n  action_dim: 6\n`, and `config/controllers.yaml`, a
  block-style ros2_control file. Its `controller_manager.ros__parameters` declares both
  controllers by type; `arm_controller.ros__parameters.joints` lists 6 joints (`- shoulder_pan` …
  `- wrist_3`) and `gripper_controller.ros__parameters.joints` lists `- finger`.
- Facts: `controllers.yaml` holds `[{controller, inputs 6, ref config/controllers.yaml:10},
  {controller, inputs 1, ref config/controllers.yaml:19}]` (lines 10 and 19 are the two `joints:`
  keys), and `policy.yaml` holds `{policy, outputs 6, ref config/policy.yaml:3}`.
- `run_matrix` → exactly ONE result, no fail, no pass:

```json
{"status": "unknown_input", "severity": "info", "message": "could not check module_contract_mismatch: policy and controller pairing unknown; set it in the policy's own repository or folder: it states controllers of more than one width and nothing there says which one the policy feeds", "subjects": ["01a18b9d-22a7-7886-b028-1568cc72bafc", "01a18b9d-22a6-71fb-bf56-27ceda3dbc40"], "missing": {"name": "policy and controller pairing", "set_in": "the policy's own repository or folder: it states controllers of more than one width and nothing there says which one the policy feeds"}}
```

The subjects are (`policy.yaml`, `controllers.yaml`). `findings_raised 0`; the run's one `info`
for that unknown landed as finding `01a18b9d-232e-7ba3-817d-909086ce5a1f` (severity `info`,
subject `policy.yaml`), the matrix's "one info per (rule, entity)".

**P3c: `plain_repo` on a code host** (source `01a18b9d-2338-718f-be25-f2e4294911d7`).

- One read, `config.yaml`: a policy candidate by its name, which states nothing. The FactStore's
  `module_interfaces` is `{}`.
- `run_matrix` → `{"status": "unknown_input", "message": "could not check
  module_contract_mismatch: module_interfaces unknown; set it in the code host or linked folder's
  policy and controller modules, read by the software reader (P6)", "subjects": []}`. No fail, no
  finding.

## Leg 4: `code.ros2_nodes` / `code.ros2_topics` with this host's `/opt/ros/jazzy` system profile

The code fork's linked folder was a scratch copy of the `ros2_ws` fixture, `/tmp/p6-accept-78di9vpe/code/ros2_ws`,
which also holds the two overlay setup files below (they cannot be written into the tree).
`HOME` = `acceptance/p6_home`, with `.ros/` present. Host processes before the leg (/proc):
`{"_ros2_daemon": 0, "ros2": 0, "talker_listener": 0}`; no `/talker` was running.

**4.1 The profile, captured the way the fork captures it.** This is the body of
`integrations/mcp/code/solus/server.py:tool_profile_capture`, its own calls in order:
`plan_action(root, "profile_capture", {name: ros, setup_file: /opt/ros/jazzy/setup.bash})` →
`run_sandboxed(root, plan, runner=partial(default_runner, tail_bytes=MAX_ENV_BYTES + 1))` →
`profiles.finish_capture(...)`.

- The plan: `argv ["/bin/bash", "--noprofile", "--norc", "-c", "source \"$1\" >/dev/null 2>&1
  </dev/null || exit 97; exec /usr/bin/env -0", "solus-profile", "/opt/ros/jazzy/setup.bash"]`,
  sandbox `landlock-abi8`, `program_scope "system"`.
- One child, pid 3797997, exit 0 in 219 ms, 2,668 B of `env -0`, stderr empty.
- The answer, names only:

```json
{"ok": true, "name": "ros", "variables": ["AMENT_PREFIX_PATH", "CMAKE_PREFIX_PATH", "GZ_CONFIG_PATH", "GZ_SIM_RESOURCE_PATH", "GZ_SIM_SYSTEM_PLUGIN_PATH", "LD_LIBRARY_PATH", "PATH", "PYTHONPATH", "ROS_AUTOMATIC_DISCOVERY_RANGE", "ROS_DISTRO", "ROS_PYTHON_VERSION", "ROS_VERSION"], "dropped": ["PWD", "SHLVL"], "path_entries": 6, "reason": null}
```

The judge's inputs:

- **`SEARCH_PATH_VARIABLES`, 26:** AMENT_PREFIX_PATH, CLASSPATH, CMAKE_PREFIX_PATH,
  COLCON_PREFIX_PATH, CYCLONEDDS_URI, DYLD_LIBRARY_PATH, FASTDDS_DEFAULT_PROFILES_FILE,
  FASTDDS_ENVIRONMENT_FILE, FASTRTPS_DEFAULT_PROFILES_FILE, GEM_PATH, LD_LIBRARY_PATH, NODE_PATH,
  OPENSSL_CONF, OPENSSL_ENGINES, OPENSSL_MODULES, PATH, PERL5LIB, PYTHONEXECUTABLE, PYTHONHOME,
  PYTHONPATH, PYTHONPLATLIBDIR, PYTHONPYCACHEPREFIX, PYTHONUSERBASE, ROS_PACKAGE_PATH, RUBYLIB,
  `__PYVENV_LAUNCHER__`.
- **Present in the profile, 5:**
  - AMENT_PREFIX_PATH `[/opt/ros/jazzy]`;
  - CMAKE_PREFIX_PATH: 17 `/opt/ros/jazzy/opt/*_vendor` entries;
  - LD_LIBRARY_PATH: 20 `/opt/ros/jazzy/...` entries;
  - PATH `[/opt/ros/jazzy/opt/gz_msgs_vendor/bin, /opt/ros/jazzy/opt/gz_tools_vendor/bin,
    /opt/ros/jazzy/opt/gz_ogre_next_vendor/bin, /opt/ros/jazzy/bin, /usr/bin, /bin]`;
  - PYTHONPATH: 6 `/opt/ros/jazzy/...` entries.
- Absolute paths inside the folder, in any variable: none. Relative or empty entries in a judged
  variable: none.

**4.2 The planned reads** (`ros2_reads._plan_read`), each answering `program_scope "system"`,
`profile {name: ros, digest 11c30001…33e7}`, `program_realpath /opt/ros/jazzy/bin/ros2`:

```json
{"argv": ["/opt/ros/jazzy/bin/ros2", "node", "list", "--no-daemon", "--spin-time", "2"], "cwd": ".", "ok": true, "sandbox": {"kind": "landlock-abi8"}, "program_scope": "system"}
{"argv": ["/opt/ros/jazzy/bin/ros2", "topic", "list", "--no-daemon", "-t"], "cwd": ".", "ok": true, "sandbox": {"kind": "landlock-abi8"}, "program_scope": "system"}
```

**4.3 The live reads: the fork's own tool functions, in process, the real `ros2`.**

| call | child (pid, cwd) | exit, time | answer | `_ros2_daemon` before → after | `ros2` left |
| --- | --- | --- | --- | --- | --- |
| `ros2_nodes(root, "ros")` | 3798047, `/tmp/solus-ros2-7ckz_p6a` (empty after) | 0, 2,421 ms | `{"ok": true, "nodes": [], "truncated": false, "reason": null}` | 0 → 0 | none |
| `ros2_topics(root, "ros")` | 3798180, `/tmp/solus-ros2-d17_4s0b` (empty after) | 0, 966 ms | `{"ok": true, "topics": [{"name": "/parameter_events", "type": "rcl_interfaces/msg/ParameterEvent"}, {"name": "/rosout", "type": "rcl_interfaces/msg/Log"}], "truncated": false, "reason": null}` | 0 → 0 | none |

- The spawned argv (both alike): `<venv python> -I …/code/solus/landlock_exec.py --env-fd 9 --home
  <p6_home> --rw /tmp/p6-accept-78di9vpe/code/ros2_ws --rw /tmp --rw /var/tmp --rw /dev/null --rw
  /dev/zero --rw /dev/tty --rw <p6_home>/.ros -- /opt/ros/jazzy/bin/ros2 node list --no-daemon
  --spin-time 2`.
- The executor ran the command from the fresh, empty `/tmp/solus-ros2-*` directory (the plan's
  `cwd`), while the grants, the resolution and the scope re-check stayed on the folder.
- **DDS inside Landlock.** stderr was empty in all four real runs. Fast DDS printed its
  shared-memory refusals on **stdout**, which `ros2_reads` parses; the name grammar dropped each
  line (ANSI colour codes stripped here):

```
2026-10-30 03:01:25.468 [RTPS_TRANSPORT_SHM Error] Failed to create segment 3c76332e866e07ff: Permission denied -> Function compute_per_allocation_extra_size
2026-10-30 03:01:25.469 [RTPS_TRANSPORT_SHM Error] Failed to create Shared Memory Manager for domain fastrtps: Permission denied -> Function create
2026-10-30 03:01:25.469 [RTPS_PARTICIPANT Error] Unable to Register SHM Transport. SHM Transport is not supported in the current platform. -> Function RTPSParticipantImpl
```

Discovery then ran over UDP: the topic listing's own `/parameter_events` and `/rosout` came back.
No other participant was on the domain.

**4.4 The same reads through the cloud.** A's SOL registry for P1 registered `code.ros2_nodes` and
`code.ros2_topics`, each wrapped by `agent/tools/ros_live.py:live_graph_tool`. Each read was
dispatched in a turn (P5's turn composition). The companion answered with the same fork function
and the real `ros2`: pids 3798223 (2,435 ms) and 3798368 (976 ms), in fresh `/tmp/solus-ros2-*`
directories.

| call | answer reaching the model | `confirm_live` | graph before → after |
| --- | --- | --- | --- |
| `code.ros2_nodes {profile: ros}` | `{"ok": true, "nodes": [], "truncated": false, "reason": null}` | not called (an empty listing raises nothing) | 32 entities / 36 edges → identical rows |
| `code.ros2_topics {profile: ros}` | `/parameter_events`, `/rosout` with their types | `{ref: "ros2 topic list", topics: {/parameter_events, /rosout}, raised: 0}` | identical rows (ids, versions, confidences, evidence) |

A listing whose names no edge carries created and raised nothing. `_ros2_daemon` was 0 before and
after each.

**4.5 The matching bump.** No node may be started and none runs, so the listing was scripted
through the fork's own `Runner` seam (`execute.Runner`), deviation 2. `ros2_reads.ros2_nodes`
planned (system scope) and `execute_plan` prepared exactly as above. The scripted runner was handed
the argv `[…/landlock_exec.py … -- /opt/ros/jazzy/bin/ros2 node list --no-daemon --spin-time 2]`,
cwd `/tmp/solus-ros2-hggutf4h` (empty), env `{PATH: /usr/bin:/bin, LANG: en_US.utf8}` and timeout
20, and answered stdout `/robot/talker\n/ghost\n`. Nothing was spawned. The answer `{"nodes":
["/robot/talker", "/ghost"]}` went through the bridge to the cloud wrapper.

- `confirm_live(P1, ref "ros2 node list", nodes ["/robot/talker", "/ghost"])` → **raised 1**.
- `annotate_edge(P1, 01a18b9c-fe17-…, confirmed_by={kind: bus_enumeration, ref: "ros2 node list",
  detail: "seen live: /robot/talker"})` → confidence 1.0.

```json
BEFORE {"id": "01a18b9c-fe17-7d55-850e-361071ff83fa", "relation": "publishes", "confidence": 0.9, "origin": "inferred", "evidence": [{"ref": "src/talker_py/launch/talker.launch.py:11", "kind": "config", "detail": "declared at src/talker_py/talker_py/talker.py:12"}], "updated_at": "2026-10-30T07:01:24.119993+00:00"}
AFTER  {"id": "01a18b9c-fe17-7d55-850e-361071ff83fa", "relation": "publishes", "confidence": 1.0, "origin": "inferred", "evidence": [{"ref": "src/talker_py/launch/talker.launch.py:11", "kind": "config", "detail": "declared at src/talker_py/talker_py/talker.py:12"}, {"ref": "ros2 node list", "kind": "bus_enumeration", "detail": "seen live: /robot/talker"}], "updated_at": "2026-10-30T07:01:32.515523+00:00"}
```

The listener's `subscribes` stayed at 0.9 through this read: the listing did not name
`/listener`. **`/ghost` created nothing**: 32 entities and 36 edges live before and
after, and no row whose name holds `ghost`.

The topic listing, scripted the same way, was `/robot/chatter [std_msgs/msg/String]\n/ghost_topic
[std_msgs/msg/String]\n`. `confirm_live` → **raised 1**: the topic matched, its declared type
agrees, and `annotate_edge` ran on `01a18b9c-fe16-…`.

```json
BEFORE {"id": "01a18b9c-fe16-7765-8b00-3147a71f6dff", "relation": "subscribes", "confidence": 0.9, "evidence": [{"ref": "src/listener_py/launch/listener.launch.xml:3", "kind": "config", "detail": "declared at src/listener_py/listener_py/listener.py:12"}]}
AFTER  {"id": "01a18b9c-fe16-7765-8b00-3147a71f6dff", "relation": "subscribes", "confidence": 1.0, "evidence": [{"ref": "src/listener_py/launch/listener.launch.xml:3", "kind": "config", "detail": "declared at src/listener_py/listener_py/listener.py:12"}, {"ref": "ros2 topic list", "kind": "bus_enumeration", "detail": "seen live: /robot/chatter"}]}
```

The talker's edge, already 1.0, was not touched again. `/ghost_topic` created nothing (counts
unchanged). Both edges as stored afterwards (SQL): `publishes 1 inferred […, {"ref": "ros2 node
list", "kind": "bus_enumeration", "detail": "seen live: /robot/talker"}]` and `subscribes 1
inferred […, {"ref": "ros2 topic list", …, "detail": "seen live: /robot/chatter"}]`.

**4.6 `confirm_live` applies the grammar itself (m3).** It was called directly, under
`lock_project`, before the bump. `nodes ["/robot/talker\n", "/robot/talker ", "robot talker",
"/robot/tal-ker"]` and `topics {"/robot/chatter\n": "std_msgs/msg/String", "/robot/chat ter":
null}` → `live_names` `[]` and `[]`, **raised `[0, 0]`**. The graph was identical (both edges
still 0.9).

**4.7 Another project.** C's companion in P3a (another tenant) answered `code.ros2_nodes` with
`["/robot/talker", "/listener"]` (scripted runner). `confirm_live(P3a)` → raised 0. P1's rows
were identical before and after, and P3a's too.

**4.8 Overlays are refused before anything runs.** Two more profiles were captured from setup files
inside the folder (children 3798421 and 3798430, exit 0):

- `install/setup.bash` sources `/opt/ros/jazzy/setup.bash`, then exports
  `AMENT_PREFIX_PATH=<folder>/install/talker_py:…` and
  `PYTHONPATH=<folder>/install/talker_py/lib/python3.12/site-packages:…`. Variables naming the
  folder: `AMENT_PREFIX_PATH`, `PYTHONPATH`.
- `install/userbase.bash` sources the system setup and exports `PYTHONUSERBASE=<folder>/.local`.
  Variables naming the folder: `PYTHONUSERBASE`.

| call | planner `program_scope` | answer | spawns |
| --- | --- | --- | --- |
| `ros2_nodes(root, "overlay")` | `workspace` | `{"ok": false, "nodes": [], "truncated": false, "reason": "the profile reaches the linked folder (a workspace overlay): use code.exec"}` | 0 |
| `ros2_topics(root, "userbase")` | `workspace` | `{"ok": false, "topics": [], …, "reason": "the profile reaches the linked folder (a workspace overlay): use code.exec"}` | 0 |
| `ros2_nodes(root, None)` | – | `{"ok": false, …, "reason": "ros2 not available: capture a ROS profile first"}` | 0 |
| `ros2_nodes(root, "never-captured")` | – | `{"ok": false, …, "reason": "ros2 not available: capture a ROS profile first"}` | 0 |
| cloud `code.ros2_nodes {}` | – | `{"ok": false, "nodes": [], "truncated": false, "reason": "ros2 not available: capture a ROS profile first"}` | 0 |

**4.9 A cut 16 KiB listing never answers its first line (m1).** The scripted stdout was 16,422 B,
built so the last 16,384 B (`MAX_TAIL_BYTES`) start inside `/robot/arm/x`. Through
`ros2_nodes(root, "ros", runner=<scripted>)` the answer was `ok: true, truncated: true`, 512 names
answered (the cap), the first `/n00000`. **`/arm/x` was not answered**, and neither was
`/robot/arm/x`, since its head lies outside the tail. The scripted runner was handed cwd
`/tmp/solus-ros2-_wv47ogm` (empty).

**4.10 Daemons.**

- In process (/proc, before and after every call): `_ros2_daemon` 0 throughout, `ros2` 0 after
  each call.
- On the host (`acceptance/p6_procs.py`, /proc, run from Bash): `{"_ros2_daemon": 0, "ros2": 0,
  "talker_listener": 0}` before the harness (`p6_procs_before.json`), after it
  (`p6_procs_after.json`) and after the proxies (`p6_procs_after_proxies.json`).

## Leg 5: the firmware recipe on the fake arm's board

- **Seed.** P5 holds the fake arm (`seed_fake_arm`, D): board `fake brain`
  `daae65a1-feee-484a-a128-65cbedce1468`, its six parts driven over `fake bus`, and six confirmed
  `commands` edges from `fw/fake_arm.ino` (`FIRMWARE_SYMBOL` refs `fw/fake_arm.ino:11`–`:16`).
- **D's companion** advertises `machine.write_file`, admitted confirmation-gated. It is answered by
  the companion's builtin `MachineServer(<scratch workspace>).call_tool("write_file", …)`.
- **The workspace** holds one file, `fw/fake_arm.ino` = "// the fake arm's firmware today (P6
  acceptance scratch folder)\nvoid setup() {}\nvoid loop() {}\n" (sha256 `8fa8af93…fc66`).
- **D's registry** for P5 registered `firmware_recipe` and the owned `machine.write_file`.

**5.1 One Build turn (`ActionMode.DO`, turn `264a1885-…`): the recipe, then the write it
proposes.** The dispatcher is `build_mode_dispatch(DO, …, build_dispatch(registry, park,
routine_policy=BuildExecutionPolicy(registry, DO)))`, under the runner's turn wrapping, with the
code style "two-space indent; no macros".

1. `firmware_recipe {board_id: daae65a1-…, path: fw/fake_arm.ino}` → ok, 0.089 s:

```json
{"path": "fw/fake_arm.ino", "content": "#include <SolusTelemetry.h>\n// the fake arm's firmware from its topology (P6 acceptance: a scripted reply)\nSolusTelemetry telemetry(Serial, \"usb:FAKE-ARM-0001\");\nvoid setup() {\n  Serial.begin(115200);\n  telemetry.begin();\n}\nvoid loop() {\n  telemetry.add(\"servo1.position\", 0.0f, \"deg\");\n  telemetry.send();\n}\n", "card_rows": 3, "next": "call machine.write_file with exactly this path and content; the person approves the write on its card"}
```

   - The current file was read through the owned write's dry run: companion frame
     `machine.write_file {path: fw/fake_arm.ino, content: "", create_dirs: false, dry_run: true}`.
   - Then ONE model call (scripted, `purpose answer`, `type code`, user D, this turn's id; turn
     budget `model_calls` 1 → 2 of 18).
   - Its prompt starts with `FIRMWARE_RECIPE` (checked: true), then five fenced blocks:
     - `topology`: `{"board": "fake brain", "robots": ["Fake arm"], "commands": [{"relation":
       "commands", "part": "servo 1 (joint 1)", "code": ["fw/fake_arm.ino:11"], …}, …]}`;
     - `pins`: `[]` (no board definition);
     - `telemetry_library`;
     - `current_file`: `{"path": "fw/fake_arm.ino", "text": "// the fake arm's firmware today
       …"}`;
     - `code_style`: `{"text": "two-space indent; no macros"}`.
2. `machine.write_file {path, content}`, the recipe's answer in the same turn:
   - **The policy decision** (`BuildExecutionPolicy.prepare`, probed): `firmware_recipe → false`,
     **`machine.write_file → false`**. The write is forced to its card: `routed_by_firmware`
     holds for this turn.
   - The gate parked it: one `ToolConfirmation`, the card, `01a18b9d-2459-7b45-b1dd-bb17f91002ac`,
     status **`pending`**, preview built by the owned write's dry run (frame `dry_run: true`,
     content 309 chars). The full diff rows:

```json
[{"label": "File", "before": null, "after": "fw/fake_arm.ino"},
 {"label": "File state fingerprint", "before": null, "after": "48dcc3fc2e9bf2ae:fd7c82bcdfc71ea4:9f22d5e142206c17:8c5c8b2aaaa336e8"},
 {"label": "Content 1", "before": "// the fake arm's firmware today (P6 acceptance scratch folder)\nvoid setup() {}\nvoid loop() {}\n", "after": "#include <SolusTelemetry.h>\n// the fake arm's firmware from its topology (P6 acceptance: a scripted reply)\nSolusTelemetry telemetry(Serial, \"usb:FAKE-ARM-0001\");\nvoid setup() {\n  Serial.begin(115200);\n  telemetry.begin();\n}\nvoid loop() {\n  telemetry.add(\"servo1.position\", 0.0f, \"deg\");\n  telemetry.send();\n}\n"}]
```

   - The result handed back to the model (`unauthorized`, `retryable: false`): "machine.write_file
     is now waiting for the person to approve it — they have been shown exactly what it would do.
     This is not a failure and it does not need retrying: do not propose it again in this turn. …"

**5.2 The card appears even for an owned routine.** The same `machine.write_file {path, content}`
went to a fresh `BuildExecutionPolicy(registry, DO).prepare(...)` in a turn no recipe routed
(`bind_turn_id(<new>)`). Decision **`true`**: Build would run this owned write itself. Its two
validation previews were `dry_run: true` frames, and nothing was executed (`prepare` only decides).
The file sha was unchanged.

**5.3 Above the card ceiling.** A new Build turn (`da20ba60-…`): one dry-run read, then ONE
scripted reply of 41 lines × 399 characters. The recipe answered `tool_error`, "The new file would
take 43 card rows; a write card shows 40 rows of 400 characters. Nothing was proposed."
(`card_rows(current, reply)` = 43; `CARD_ROWS` 40, `ROW_CHARS` 400.) No card, no write.

**5.4 A path the topology does not name (R138).** Two turns:

- `{board_id: daae65a1-…, path: fw/other.ino}` with `fw/other.ino` present in the workspace.
- The same after deleting it.

Both answered `unauthorized`, "The graph does not name fw/other.ino as this board's firmware;
named: fw/fake_arm.ino.", word for word. The companion received **0 frames** for either, and each
turn made 0 model calls (budget 1 → 1).

**5.5 Another project's board, and outside a turn.**

- `board_id 44073b66-…` (P6's fake brain) → `not_found`, "board_id names no board in this
  project.", 0 frames, 0 model calls.
- Without a turn bound → `unavailable`, "firmware_recipe runs only inside a SOL turn."

**5.6 Nothing written without approval.**

- Companion `machine.write_file` frames in the whole leg: **5, all `dry_run: true`; 0 without**.
- Workspace files before: `{"fw/fake_arm.ino": "8fa8af93315fc89cd946ebe2a066b5dad098cf0a0a8bb9e936fa426889defc66"}`.
  After the card, after the unrouted decision and at the end: the same, 1 file (the temporary
  `fw/other.ino` was created and removed by 5.4).
- The card stays `pending`: approval was not exercised.

## Leg 6: expertise

**6.1 Four levels only on `member.attrs.expertise`; recompute after a code-source sync.**

- A in P1, after leg 1's local sync. `_commit_success` → `recompute_after_sync` → `store_expertise`
  (probed: P1, A, all `working`, at the link's sync and again at the forced re-sync).
  - The member node `01a18b9c-fe68-7c35-b689-de9f055e0a9b`:

    ```json
    {"expertise": {"control": "working", "software": "working", "mechanical": "working", "electronics": "working"}, "display_name": "p6-accept-a-c79a5738"}
    ```

  - No count, path or question is stored: `display_name` is `ensure_member`'s own key.
  - `compute_expertise(P1, A)` → the same four `working` levels.
  - The log line: `sync ok source=01a18b9c-fd6e-7643-bdff-7f84fc30db26
    sync=01a18b9c-fd83-7f37-99f7-bf6cadb6e439 created=9 updated=0 rels=+8/-0 errors=0`.
  - The history row: `{"type": "sync.completed", "payload": {"errors": 0, "sync_id":
    "01a18b9c-fd83-…", "source_id": "01a18b9c-fd6e-…", "entities_created": 9,
    "entities_updated": 0, "relations_created": 8, "relations_deleted": 0}}`.
- E in P6.
  - **Sync 1** (`01a18b9d-2605-…`, `sync ok … created=13 … errors=0`): E's GitHub source with 12
    `src/app/module_NN.py` files (software signal 10). `store_expertise` → `{control: working,
    electronics: working, mechanical: working, software: working}`. Repos alone reach `working`
    (m6). E's node `01a18b9d-2658-7918-b29d-df687df6d5f3` holds exactly that and `display_name`.
  - **E's questions**, through `POST /sol/conversations` then `POST …/messages` (200 each, the
    route persists the USER turn, deviation 6): "refactor the python timer in the talker node",
    "the firmware build breaks after the library update", "add a ros publisher for the battery
    voltage".
  - **Sync 2** (`01a18b9d-286d-…`, `sync ok … created=0 … errors=0`): `store_expertise` →
    `{control: working, electronics: working, mechanical: working, software: expert}`. The node's
    `updated_at` moved 07:01:34.430Z → 07:01:35.025Z.

**6.2 The override changes the SOL prompt's register.** E's turn `"convert 2.5 A to mA"` through the
real route, with the app's `LlmRunner(adapters=<refusing>)`. The runner built the system prompt
(`prompt.system_prompt`, probed), then the first tier answered "2.5 A = 2500 mA. This is unit
arithmetic alone: nothing in your project was read.", with 0 model calls.

- Without preferences: `expertise {software: expert}` (stored).
- With `preferences: {"expertise": {"software": "novice", "control": "novice"}}`:
  `expertise {control: novice, software: novice}`.
- Both prompts have 20 lines. **The one line that differs** (line 18, right after the mode note)
  equals `register_line` of each:

```
stored:   By domain: be terse and skip basics in software (expert).
override: By domain: explain fundamentals and define terms in control (novice); explain fundamentals and define terms in software (novice).
```

**6.3 The register reaches both narration prompts.**

- **Finding narration.** A stall finding `01a18b9d-29ec-780f-9163-0b823ff2316f` on E's fake arm,
  servo 3, was raised with `raise_finding` (the evaluator's spec, built inline: deviation 8). Then
  `app.state.narrator.hear(P6, E, arm.robot, [it])` ran. About 10 s later the flush made ONE
  scripted call (`purpose narration`, `openai_standard`, 1 message, no turn) and wrote the
  explanation "The joint holds against its command while it draws more current than its rating,
  which points to a load it cannot move." The system text it was sent ends:

```
… No markdown, HTML, URLs, brackets, braces or line breaks inside a string. Guide mode: explain each finding in accessible language, saying what its signals mean. By domain: be terse and skip basics in software (expert).
```

- **Runs narration** (`narrate_run`, R141). E uploaded a run manifest (`test_run_analysis.manifest()`
  with E's arm robot and servo 1, `POST /artifacts`), then imported it: `POST /bench/runs/import`
  → 201, run `673cdce5-6b29-4579-b12f-f3569ec1ab4c`, 3 packets. `POST
  /bench/runs/673cdce5-…/narrate` → **200 `{"mode": "model", …}`**, finding "Possible stall at
  servo 1 (joint 1)". ONE scripted call (`openai_trivial`); its system text ends:

```
… Explain qualitatively why current with absent commanded movement suggests a possible stall. No markdown, HTML, URLs or tools. Guide mode: explain current, position and command in accessible language. By domain: be terse and skip basics in software (expert).
```

**6.4 The sweep's member gate (R139) and its bounds.**

- `recompute_due_expertise(maker, now=2026-10-30T04:00Z)` → `0`: not `EXPERTISE_HOUR_UTC` (3),
  so nothing was listed. The sweep at 03:00 UTC was not run, because it lists the whole dev copy's
  member nodes (deviation 7).
- F and H asked their questions through the route (F: "what is a pid controller?", "explain how a
  trajectory follows its setpoints"; H: "how do I read the i2c bus?"). Then the sweep's own
  per-member step `_recompute_one(maker, P6, team, …)` ran for F → `1` and for H → `1`:
  - F's node `01a18b9d-28bf-…`: `{"expertise": {"control": "novice", "software": "working",
    "mechanical": "working", "electronics": "working"}, …}`;
  - H's node `01a18b9d-28cf-7655-83a2-52f080fdd07e`: `{"expertise": {"control": "working",
    "software": "working", "mechanical": "working", "electronics": "novice"}, …}`, `updated_at`
    07:01:35.063329Z.
- E removed H: `DELETE /api/v1/teams/{P6 team}/members/{H}` → **204**. H's membership row is gone
  (`select … from memberships` → no row).
- The sweep's listing, `_members_due()` narrowed to P6 with one `.where(project_id == P6)`, after
  the removal: `[["e", P6], ["f", P6]]`. F, whose node the same sweep step created at the same
  moment, is listed; **H is not**.
- `_recompute_one(maker, P6, team, H)` → **`0`**. H's node is unchanged: the same levels, version
  1, `updated_at` still 07:01:35.063329Z.
- Bounds, as constants: `MAX_DAILY_MEMBERS` 100 and `MEMBER_TIMEOUT_SECONDS` 1.0. The order "after
  change detection" is `connectors/worker.py:1047-1059`: `detected = await run_change_detection(…)`,
  then `await expertise.recompute_due_expertise(ctx["sessionmaker"], now=utcnow())`, then `return
  detected`. Both were checked by reading and by the proxy pins (`test_worker.py::
  test_the_hourly_sweep_asks_the_daily_expertise_check`, `test_expertise.py::
  test_a_member_past_its_time_is_skipped_and_the_sweep_goes_on`), not live.

**6.5 Teammates can read the levels (M168, by design: noted, not flagged).** F's `GET
/api/v1/projects/{P6}/entities/<E's member node>` → **200**. The route serializes `attrs` as
`properties` (`schemas.py:serialize_entity`), so F reads E's four levels. The harness read the
key `attrs` from that body and recorded `null` (observation 11).

## Leg 7: ratchets

- **No framework name under `software/`.** `grep -rniE
  "gym|hydra|torch|lerobot|stable.?baselines|ros2_control" packages/api/src/solus_api/software`
  printed nothing (`p6_leg7_framework_grep.stdout`, 0 bytes) and exited 1 (no match). `software/`
  holds `__init__.py`, `policy_reader.py`, `ros_reader.py`.
- **The vendor sweep over `software/` passes.** `tests/test_vendor_hygiene_api.py` (7 tests, among
  them `test_the_software_package_is_under_the_ratchet`), `tests/test_capability_hygiene.py` and
  `tests/test_model_call_sites.py` passed in the proxy slice, as did
  `tests/test_policy_reader.py::test_no_framework_name_under_software`.
- **Planted credential names are not in the payload.** A scratch copy of the fixture gained
  `src/talker_py/talker_py/apikey.py` and `src/talker_py/talker_py/credentials/config.py`. The
  fork's `scan_folder` over it:
  - **ROS payload** (10 texts): `src/listener_py/{package.xml, launch/listener.launch.xml,
    setup.py, listener_py/__init__.py, listener_py/listener.py}`, `src/talker_py/{package.xml,
    launch/talker.launch.py, setup.py, talker_py/__init__.py, talker_py/talker.py}`.
  - `planted_shipped: []`. **`planted_read: []`**: the ROS reader's `_read` (probed) opened exactly
    those 10 files and never either planted path. `talker.py` ships.
  - The scan's general tool-file list (`files`, SOLUSDEV-249) still names both planted files, with
    size and hash and no text (observation 2).
- **The frame budget with non-ASCII text:** leg 2/7 above.

## Proxy tests (after the live run)

The pytest guard (`ps -eo pid,args | grep -E "[u]v run pytest|[p]ython -m pytest|[p]ytest -q"`)
ran in its own call before each run and printed nothing. Each run was one process, with no
`--cov`.

```
cd packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2 uv run --frozen --no-sync pytest -q -rs -p no:cacheprovider tests/test_ros_reader.py tests/test_ros_edges.py tests/test_ros_live.py tests/test_annotate_edge.py tests/test_policy_reader.py tests/test_software_software.py tests/test_code_content_software.py tests/test_firmware_recipe.py tests/test_expertise.py tests/test_sol_routes_expertise.py tests/test_finding_narration_expertise.py tests/test_run_narration_expertise.py tests/test_bench_runs.py tests/test_worker.py tests/test_local_folder.py tests/test_kinds.py tests/test_matrix_registry.py tests/test_vendor_hygiene_api.py tests/test_capability_hygiene.py tests/test_model_call_sites.py tests/test_edge_writer_ratchet.py tests/test_sol_runtime.py tests/test_gateway_purpose.py tests/test_prompt.py
400 passed in 116.22s (0:01:56)

cd /home/beeboss/Solus && PYTHONDONTWRITEBYTECODE=1 uv run --frozen pytest -q -rs -p no:cacheprovider integrations/mcp/local/tests
251 passed in 0.83s

cd /home/beeboss/Solus && PYTHONDONTWRITEBYTECODE=1 uv run --frozen pytest -q -rs -p no:cacheprovider integrations/mcp/code/tests
2 failed, 1332 passed, 16 skipped in 37.38s
```

- **The API slice.**
  - The P6 brief's tests: `test_ros_reader` (its three named tests), `test_ros_edges`
    (`test_live_confirmation_bumps_existing_edges_only`), `test_policy_reader` (both named),
    `test_firmware_recipe` (`test_rmw_behind_card_and_refuses_above_ceiling`), `test_expertise`
    (both named) and `test_local_folder`.
  - Then the dispatch's `test_kinds` and `test_matrix_registry`, and the ratchets:
    `test_vendor_hygiene_api`, `test_capability_hygiene`, `test_model_call_sites`,
    `test_edge_writer_ratchet`, `test_sol_runtime` (SEC-H4 `.invoke(`), `test_gateway_purpose`.
  - Added, deviation 9:
    - the fix round's pins: `test_ros_live`, `test_annotate_edge`, `test_software_software`,
      `test_code_content_software`, `test_finding_narration_expertise`,
      `test_run_narration_expertise`, `test_bench_runs`, `test_sol_routes_expertise`,
      `test_prompt`;
    - `test_worker`, the sweep-order pin, since that order was not run live.
  - 0 skipped (`-rs` printed none), 0 failed.
- **The local fork: 251 passed.** Among them `test_ros.py::test_collect_ros_packages_and_colcon`
  and `::test_the_ros_part_fits_its_frame_budget_as_encoded`.
- **The code fork: 1332 passed, 16 skipped, 2 failed.** The passes include
  `test_ros2_reads.py::test_requires_system_scope_and_no_daemon` and
  `::test_a_cut_listings_first_line_is_dropped`.
  - The 2 failures are the pre-existing pair the P6 report names, left as found:
    - `test_code_process_tree.py::test_one_shot_command_cannot_leave_a_setsid_descendant` (":250
      AssertionError: a setsid descendant outlived the command");
    - `test_code_sandbox.py::test_foreign_writable_covers_tmp_and_caches_but_not_the_workspace`
      ("~/.local/share/uv is no longer writable").
  - The 16 skips are macOS sandbox-exec cases and two case-sensitive-file-system cases.
  - The run left no ROS or test process behind (/proc afterwards).
- Logs: `acceptance/p6_proxy_pytest.log`, `p6_proxy_local.log`, `p6_proxy_code.log`, each with
  its `.time`. `.coverage` md5 unchanged, the tree clean.

## Deviations from the brief and observations

1. **4 scripted model calls where the dispatch heading says "0 model calls".** The firmware recipe
   makes ONE call per ask by design (leg 5 asks twice: the card, and the over-ceiling refusal,
   which needs the reply to measure it). Each narration makes ONE call (leg 6 needs both prompts'
   text). Every one went through the real gateway, gated, metered and ledgered, answered by a
   counted scripted adapter as P5's vision reads were. 0 real calls, 0 refusing reaches. The SOL
   prompt proof (6.2) used first-tier turns, so 0 calls there.
2. **Leg 4's matching bump ran on a scripted stdout.** No ROS node may be started, and the live
   listing on this host was empty (nodes) or the CLI's own topics (`/parameter_events`, `/rosout`).
   So the bump was driven through the fork's own `Runner` seam (`execute.Runner`, the dispatch's
   "scripted runner"). The fork planned with the real captured profile and the real system-scope
   judgement, `execute_plan` prepared the real sandboxed argv and neutral cwd (recorded), and the
   runner answered fixed text in place of spawning. The cloud side (bridge, `live_graph_tool`,
   `confirm_live`, `annotate_edge`) was the production path. The four real `ros2` runs proved the
   live list, the sandbox, the cwd and the daemon count.
3. **The fork's profile capture was re-composed from `tool_profile_capture`'s own calls**
   (`plan_action` → `run_sandboxed` with the tail-sized runner → `finish_capture`). The server
   reads the folder from `SOLUS_MCP_WORKSPACE`, which the harness's environment guard keeps
   unset. For the fork's calls `HOME` was `acceptance/p6_home`, so the profiles and ros2's logs
   stayed out of the person's own home. The code fork's linked folder was a scratch copy of the
   fixture holding the two overlay setup files, while the local fork scanned the fixture in place
   for leg 1; a companion uses one linked folder for both.
4. **Leg 1's identical-graph re-sync was proven twice.** Through the route, the freshness gate's
   digest probe skipped it: the production path for an unchanged folder. Through the worker's own
   `execute_source_sync(force=True)`, the full pass ran again (`ros_edges` skipped 2). No route
   sends `force`.
5. **Code-host sources are seeded rows over the test's scripted connector**
   (`test_code_content_software._ScriptedGitHub` + `repo_result`, blobs over an
   `httpx.MockTransport`). The sync itself was the real `run_sync` → `read_software` →
   `_commit_success` → `infer_after_sync` → `recompute_after_sync`. `run_matrix` was called
   directly, as the matrix job calls it.
6. **The question turns ran on the in-tree `ScaffoldRunner`.** Expertise reads the person's own
   USER turns. The six questions were posted through the production SOL route with
   `app.state.agent_runner = ScaffoldRunner()` (model-free; the route persists the USER turn
   before any runner runs), then the app's `LlmRunner(adapters=<refusing>)` was restored.
7. **The daily sweep itself was not run.** At 03:00 UTC `recompute_due_expertise` lists the 100
   oldest member nodes of the whole dev copy, among them the copy's own dev member node
   (`pmadaram`, from the copied dev data), and `scheduled_change_detection` would probe every connected
   source in the copy. Run instead:
   - the sweep's own listing (`_members_due()` plus one `where(project_id == P6)`);
   - its own per-member step (`_recompute_one`);
   - `recompute_due_expertise` at 04:00 UTC (returns 0 without listing).
   The order and the bound are read from code and pinned by the proxy tests (Not verified here).
8. **The finding narration was triggered with `app.state.narrator.hear(...)`.** No bench session
   ran. The stall spec was built inline with the numbers of
   `tests/test_finding_narration.py::_stall_evidence`/`_observer_spec`: importing that module
   pulls `tests/conftest.py` (observation 9).
9. **The proxy slice adds the fix round's pins** and `test_worker.py` to the dispatch's list
   (listed above).
10. **Two void attempts**, both harness assumptions, kept as `p6_accept_live_VOID{1,2}*`.
    - **06:58:41Z:** importing `test_finding_narration` → `test_window_evaluator` → `conftest`
      rewrote `SOLUS_DATABASE_URL` and removed `SOLUS_REDIS_URL`. The harness's post-import guard
      refused to start ("an import changed the SOLUS_* environment"). Nothing touched a database.
    - **07:00:29Z:** C's third `POST /teams` was refused by the free plan's `max_teams` 2. Seven
      people and six projects (A, B, C two each, with their `.solus` scaffolding) were created
      before the stop; no leg ran. The final run put C's three projects in one team.
11. **Observations, harmless or worth a ticket, none a failure of a leg:**

    1. **Fast DDS writes its diagnostics to stdout, the stream `ros2_reads` parses.** Its three
       `RTPS_TRANSPORT_SHM`/`RTPS_PARTICIPANT` "Error" lines (shared memory denied by Landlock)
       preceded every listing; stderr was empty. The name grammar dropped them (each starts with
       an ANSI colour code and a date). A diagnostic line that happened to be a bare grammatical
       name would be answered as a node. The cloud would then only raise an existing edge whose
       node bears that exact name: it creates nothing.
    2. **The planted credential names reach the cloud as file names.** R135 keeps credential-shaped
       paths out of the ROS texts, and they were neither shipped nor read there. But the scan's
       general tool-file walk (SOLUSDEV-249) still lists `apikey.py` and
       `credentials/config.py` with size and a 32-hex hash (no text). Pre-existing behaviour,
       outside P6; a human may want `SECRET_NAME` on that list too.
    3. **The fixture yields two `module_contract_mismatch` fails, not one.** Its 6-wide action
       space is stated twice, in `config/policy.yaml:5` and `envs/arm_env.py:12`, and each policy
       is compared with the one controller. The dispatch's "one result" predates that; the unit
       pin `test_module_contract_mismatch_on_dim_difference` expects two.
    4. **P3b's single `unknown_input` also landed as one `info` finding** (on `policy.yaml`): the
       matrix's one info per (rule, entity). `findings_raised` counts it as 0.
    5. **No P6 data event was stored.** Every minted person is `consented=False`, so
       `ros.live_confirmed` and `sol.firmware_recipe.prepared` (counts-only payloads) left no
       `data_events` row: consent-gated by design. Their payloads could not be pasted.
    6. **An expertise write leaves the member node's `version` at 1**; only `updated_at` moves
       (JSONB reassigned through `ensure_member`).
    7. **`executable="talker.py"` lands a node with no topics.** The package's `console_scripts`
       entry is `talker`, so no module is matched to `talker.py`: Empty beats invented. A CMake
       package installing `talker.py` as a script would need its script read to state topics.
    8. **The over-ceiling reply still cost its model call**: 44 credits for the scripted
       4,102-token reply. The size is known only once the reply is in.
    9. **Harness pitfall for later runners:** importing `tests/test_window_evaluator.py` (directly
       or through `test_finding_narration.py`) imports `tests/conftest.py`, which points
       `SOLUS_DATABASE_URL` at the test database inside the importing process.
    10. **The free plan shapes any multi-project acceptance:** 2 teams, 3 projects and 4
        integrations a person (`models.py:787-789`).
    11. **The teammate read was recorded under the wrong key.** The harness read `attrs`; the
        entity route returns `properties`. The 200 stands, and the levels F could read are the
        stored ones pasted in 6.1.
    12. **`ros2 … list` joins DDS discovery on the LAN (UDP).** The sandbox does not restrict
        network ("reads, exec and network are not restricted", on every plan), and the harness's
        egress guard covers its own process only, as with P5's render children.

## Not verified here

- **The hourly job's order and bound, live.** That order is detection first, then
  `recompute_due_expertise`, at most 100 members, each cut off at 1 s. Running it would sweep the
  whole dev copy (deviation 7). It was read from `connectors/worker.py:1047-1059`, and its pins
  `test_worker.py::test_the_hourly_sweep_asks_the_daily_expertise_check` and
  `test_expertise.py::test_a_member_past_its_time_is_skipped_and_the_sweep_goes_on` passed in the
  proxy run.
- **A running ROS node's name raising an edge.** No node was started, and none ran on this host's
  domain. The raise was proven through the fork's runner seam (deviation 2) and pinned by
  `test_ros_edges.py::test_live_confirmation_bumps_existing_edges_only` and `test_ros_live.py`.
- **The forced card's approval, and the write landing after it.** The card stays `pending`.
- **A real model's firmware file or narration text.** Neither was produced (deviation 1).
- **A companion over a real WebSocket.** The frames were the companion's own encoder and the
  cloud's own `parse_frame` + `ingest_result`, in process. The desktop UI (the chat's card, Home's
  folder card) was not exercised.
- **The local folder's policy path.** The companion ships no policy or controller files yet, so
  leg 3 ran on the code-content path, the one that landed.

## Left behind

- **In `solus_sol`.** Counts before void attempt 1 → after the final run:

  |                         | before | after |
  | ----------------------- | ------ | ----- |
  | users                   | 24     | 38 (void 2: 7, final: 7) |
  | projects                | 27     | 42 (void 2: 6, final: 9) |
  | memberships             | 49     | 77 |
  | `credit_ledger`         | 31     | 49 (14 `trial_grant`, 4 `usage` from these runs) |
  | of which `usage`        | 11     | 15 |
  | findings                | 269    | 273 (P3a's 2 warnings, P3b's 1 info, P6's 1 stall) |
  | member nodes            | 1      | 11 |
  | `ros_node`/`ros_topic`  | 0      | 10 (P1: 3 live; P1v: 4 tombstoned; P2b: 3 live) |
  | `publishes`/`subscribes`| 0      | 6 (P1: 2 at 1.0; P1v: 2 retired; P2b: 2 at 0.9) |
  | entities                | 1,364  | 1,781 |
  | edges                   | 1,659  | 2,117 |
  | sources                 | 26     | 34 (the 8 this run made, all `disconnected`) |
  | artifacts               | 33     | 35 |
  | jobs                    | 14     | 20 |
  | tool confirmations      | 19     | 20 (P5's `pending` card) |
  | conversation turns      | 13     | 29 |

  - The final run's projects are in the Seed table. Void attempt 2's: `01a18b9c-306d-…`,
    `01a18b9c-30af-…`, `01a18b9c-30de-…`, `01a18b9c-310d-…`, `01a18b9c-313a-…`,
    `01a18b9c-3167-…`.
  - The two artifact rows' blobs lived in the process's temporary artifact root, removed at exit.
- **Not touched:** `solus`, `solus_sol_p1`, and every `solus_test_*` except `solus_test_d7fa72c2`
  (the API proxy run truncates it, as designed).
- **Redis 6390:** at 07:11:35Z, one key, `solus:upload-budget:bytes:498151:01a18b9c-f9c4-…` (TTL
  6,610 s). The four frequency-cap keys and the request-budget key had expired. `solus-redis-1`
  was never touched.
- **Processes.** The 7 Landlock children (3 captures, 4 `ros2` reads) were the harness's own and
  each exited 0. No `_ros2_daemon`, `ros2`, `talker` or `listener` process exists. Nothing else
  was started, stopped or killed (no `pkill`, no `pgrep -f`). The hook-started `dmypy run` PID
  3519903 was left alone, as was an unrelated `sleep 3600` under `cups-browsed` (PID 3809632).
- **Files** (the git-ignored plan workspace):
  - `acceptance/p6_accept_live.py`, `p6_accept_live_result.json` with `.stdout`, `.stderr` and
    `.time`, and the two `p6_accept_live_VOID{1,2}*` sets;
  - `p6_inventory.py` and `p6_inventory.json`, `.stdout`, `.stderr`;
  - `p6_procs.py` and `p6_procs_before.json`, `p6_procs_after.json`, `p6_procs_after_proxies.json`;
  - `p6_before.txt`, and `p6_leg7_framework_grep.{stdout,stderr,exit}`;
  - `p6_proxy_pytest.{log,time}`, `p6_proxy_local.{log,time}` and `p6_proxy_code.{log,time}`;
  - `p6_home/`: three captured profiles under `.solus/code-profiles/0a6c4b921fe6be05/` (variable
    names and `/opt/ros/...` and scratch paths only) and the four empty ros2 logs under
    `.ros/log/`;
  - `reports/`: this report.

  No tracked file changed.
