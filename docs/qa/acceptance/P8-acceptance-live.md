# P8 acceptance, live proof (SOLUSDEV-321 plan §3 "P8 acceptance"; dispatch legs 1–5 with "P8 as landed + fix round 1" and "After fix round 1"): in process, copy of the dev DB, scripted model text, no provider

One harness process, `acceptance/p8_accept_live.py`, in process (httpx.ASGITransport: no listening
socket) against `solus_sol` at alembic head `a32100000001` and the branch Redis on 6390. Every SOL
turn went through the production route `POST /api/v1/projects/{p}/sol/conversations/{c}/messages`
(SSE) with `app.state.agent_runner = LlmRunner(adapters=<P8AScriptedModel>)`, and every decision
through the production route `POST /api/v1/projects/{p}/sol/confirmations/{id}`: the real runner,
gate, park, decide path, Build policy, outcome recorder, gateway, metering and ledger. Only the
provider's text and a few named seams were scripted (listed under "Environment recipe"). The raw SSE
body of each of the 10 turns is kept as `acceptance/p8_sse_<turn>.txt`; the outcome rows, ledger rows
and events below were read back from the tables with `psql` (`acceptance/p8_sql_*`, `p8_leg*`). The
migration round trip ran against `solus_sol` after the live legs, then the proxy slice in one pytest
process. One complete earlier run (run 1, also all-PASS) is superseded and kept in
`acceptance/p8_run1/` (deviation 1); everything below is the final run.

## Verdicts

- **1. Every decision writes one `proposal_outcomes` row with `design_signals`: PASS.** 16 rows in
  P1 (table pasted under Leg 1): `accepted` ×3, `rejected` ×7, `expired` ×1, `stale` ×3,
  `accepted_auto` ×2. Every row carries `project_id`, `user_id`, `conversation_turn_id` (the
  decision's tool turn; null on the two auto-runs, documented), `tool`, `proposal_digest`,
  `entity_ids`, `design_signals` (4 keys, one per synced source), `machine_id` (A's machine
  `01a18de3-00f5-…`; null on teammate B's row: B has no companion) and `created_at`.
  - approve → `accepted`, reject → `rejected`, a card whose `expires_at` was moved 1 min into the past →
    `expired`, Build's owned routines (`machine.write_file`, `code.exec`) auto-run → `accepted_auto` ×2.
  - **All three `stale` cases reached live:** effect diverged (the `.solus` entry was edited by a
    person after parking: the click's preview had 1 row, different from the card's); provider-quota
    refusal (the Onshape ledger scripted through the meter's own writer to 1,750 of 2,500: the
    preview appended "Onshape API quota has reached its conservation threshold…", response code
    `unavailable`); missing complete preview (`machine.write_file`, the companion's dry run answered an
    error: 0 rows, no refusal, `requires_complete_preview` true).
  - **Digest recomputed by hand** (plain `python3`, sha256 of the stored arguments as canonical JSON):
    5 cards, 5 MATCH (pasted). The two orderings of the same `propose_part_definition` arguments
    (every level reversed, stored in their own key order) both digest to `3d479934…5175`.
  - **I2:** the non-code `propose_part_definition` card carried a stored preview row
    `{"label": "plan fingerprint", "after": "b0e88e58…:c9023553…:4a42205b…:dc8ae1ec…"}` — the code
    card's own fingerprint, forged — and its row digest is its arguments' `9b31e961…d4a1`, not the
    fingerprint.
  - **A `code.exec` card records its fingerprint:** row digest
    `b0e88e5809d87a3ec9023553e5fcefe94a42205b93b2f3e1dc8ae1ecd0fce61b` = the card's `plan
fingerprint` row without colons = sha256 of the plan fields recomputed by hand.
  - **M7 side by side:** the auto-run of the same command (`{"argv": ["uname", "-a"], "cwd": "."}`)
    recorded `ddb7c0e4…dfcf4` = sha256 of its arguments (by hand); the card path recorded the
    fingerprint `b0e88e58…e61b`. They differ, by design.
  - **M5:** the approved write's companion moved the code host's cursor to `1399b1a9…` (committed)
    while the write ran; the row recorded the click's `51e0fb8f…`, and B's next decision recorded
    `1399b1a9…`.
  - **Signals:** the 4 keys are the github `sha`, the kicad `content_sha`, the local `digest` and
    sha1 of the canonical gitlab cursor (recomputed by hand: `00a08296…3097`); the revision snapshot,
    the never-synced ROS source and the never-synced Onshape source are absent.
  - **`entity_ids`:** `bench.import_cad_scene` naming this project's robot by `robot_id` →
    `["3e49e92f-…"]`; every other card `[]` (observation 1: `set_hardware_config_field` names the
    same robot by `robot_entity_id`, outside the reference rule's keys, and records `[]`).
  - **`edited`: not reachable.** The decide body is `decision: Literal["approve", "reject"]`
    (StrictModel); `POST /confirmations/{id}` is the only decision route; `edited` appears only in
    `OutcomeDecision` and the CHECK.
- **2. `GET /projects/{id}/outcomes`: PASS.** A's listing: 16 items, ids = the table's
  `created_at desc, id desc`; paged `limit=5` → 5/5/5/1, the pages concatenated equal the full
  list, page 2 asked again with the same cursor returned the same 5 ids; `since=<4th newest>` → the
  4 newest. B (member): every row, A's with `machine_id`, `conversation_turn_id` and
  `proposal_digest` null, B's own with its turn and digest set. G (another team) and U (another
  project's owner) on P1 → 404, A on G's project → 404, unknown project → 404, no token → 401,
  `limit=201` → 422, malformed cursor → 400 `invalid_cursor`.
- **3. `GET /projects/{id}/usage/turns`: PASS.** U in P2: 13 rows, keys exactly
  `created_at, credits, id, purpose, tier, tokens_in, tokens_out, turn_id`; `grep -c balance` on the
  three saved bodies → 0, 0, 0 (exit 1); the zero-credit planner row is listed (`credits 0`, stored
  `amount 0`, `balance_after 1000` unread); teammate V's row is absent from U's list and V lists only
  it; G → 404, U on G's project → 404, A (not a member of P2) → 404, no token → 401, `limit=201` →
  422, malformed cursor → 400.
- **4. Purposes: PASS.** U's ledger holds `answer, extract, motif, narration, planner, vision, web` —
  every kind driven, each row with `project_id` = P2, a `tier` (not on `web`), a `turn_id` (not on
  `narration`, which runs outside a turn). The four round-1 sites each wrote their row in the turn:
  `render_view` → vision, `read_document` page read → extract, `firmware_recipe` → answer
  (`code_standard`), the screenshot read → vision. Not driven (outside any turn, no project by
  design, P8 Concerns §2): `fingerprint/*`, `impact/consequences.py`, `livebench/runs/narration.py`,
  `toolkb/ingest/visual.py`, `sourcing/engine.py`; the rulebook's `extract` shares the driven extractor.
- **5. Data-collection events: PASS.** 15 `sol.proposal_outcome` rows for A's 15 outcome rows, each
  `{outcome_id, tool, decision, proposal_digest}` equal to its row (SQL join: 15/15,
  `payload_equals_row true`), team and project set; B (consent off) has an outcome row and no event,
  and `emit_event` logged `event=sol.proposal_outcome user=<B> … consented=False`.
- **Migration round trip (leg 5's first paste): PASS.** `alembic downgrade -1` → `a32000000006`,
  `proposal_outcomes` gone, `ix_credit_ledger_user_created` gone; `alembic heads` →
  `a32100000001 (head)` (one); `alembic upgrade head` → `a32100000001`, the table and the index back,
  the index valid.
- **Proxy slice: PASS.** 39 files, one process: **706 passed in 272.01s**, 0 failed, 0 skipped.
- **NOT VERIFIED here:** the 90-day `since` floor reaching past rows older than 90 days (no such
  row exists live and inventing one was refused; `test_outcomes.py::test_cross_team_isolation_404`
  pins it, green); a real provider; the code fork's own `code.plan`/`code.exec` (hand-written
  companion answers); Onshape itself (MockTransport); an offscreen render (picture scripted).

**Model calls: 25 scripted, 0 real, 0 refused, 0 unscripted.** 25 adapter reaches
(`answer` 19, `vision` 2, `planner` 1, `extract` 1, `motif` 1, `narration` 1), 25 `model call
start` lines, 25 model-call `usage` rows (plus 2 `web` debit rows: no model). 0 refusing-adapter
reaches, 0 real adapter-registry builds, 0 processes started.

Ready to paste into the SDD ledger:

> P8 acceptance (live, in process, DB copy `solus_sol` upgraded a32000000006 → a32100000001 (one
> head), Redis `solus-redis-321`, the production SOL and decide routes with `LlmRunner(adapters=<scripted>)`:
> 25 scripted model calls, 0 real, 0 refused, 25 `model call start` lines; egress loopback-only; 0
> processes). Leg 1: 16 rows in one project — accepted ×3, rejected ×7, expired, stale ×3 (diverged
> preview; Onshape quota ledger scripted to 1,750/2,500 → `unavailable`; companion dry-run fault →
> missing complete preview), accepted_auto ×2 (write, `code.exec`) — each with project, decider,
> decision turn (null on auto-runs), tool, digest, entity_ids, 4 design signals (snapshot and
> never-synced sources absent), machine, created_at; 5 digests recomputed by hand, all match; two key
> orders → one digest; a forged `plan fingerprint` row on a non-code card → args digest; a `code.exec`
> card → its fingerprint, its auto-run → the args digest (M7); a cursor moved during an approved write
> → the row kept the click's sha (M5); `robot_id` → entity_ids [robot]; `edited` unreachable (body is
> approve|reject). Leg 2: newest-first, 4 stable pages of ≤5; teammate sees decider-only fields null;
> foreign 404, 401, 422, 400. Leg 3: 13 rows with purpose and tier, no `balance` anywhere, zero-credit
> row listed, teammate's row absent, foreign 404. Leg 4: purposes answer, extract, motif, narration,
> planner, vision, web. Leg 5: 15 consent-gated events (15/15 equal their rows), none for the
> unconsented teammate; downgrade -1 / upgrade head drops and recreates the table and
> `ix_credit_ledger_user_created`. Proxies: 706 passed (39 files, one process). Report:
> `docs/qa/acceptance/P8-acceptance-live.md.

## Run identity

| Item     | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Run time | **First step (alembic):** heads `a32100000001 (head)`; `current` `a32000000006 (mergepoint)` → upgrade → `a32100000001 (head)`, before any run (`p8_alembic_heads_before.txt`, `p8_alembic_upgrade.txt`). **Harness (final):** command 17:37:04.284Z → 17:38:24.699Z, exit 0 (internal 17:37:05.552Z → 17:38:23.936Z). **Round trip:** 17:43:23.227Z → 17:43:25.802Z. **Proxy pytest:** 17:44:57.039Z → 17:49:33.633Z, exit 0.                                                                                                                                                                                                                                                                                                                                                                     |
| Branch   | `SOLUSDEV-321-sol-checker-algorithm`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| HEAD     | `d1e4218b` (`d1e4218bd26038f265b73ff2a6dd2e529466dba2`) before and after. `git status --short` empty before the runs, after them and after the proxies. `.coverage` md5 `7571ebfd2af623167baf221f5af68076` before the proxies and the same after (not moved, no checkout needed).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Database | `solus_sol`, asserted from the server by the harness (`select current_database()`, and `alembic_version` = `a32100000001` or it refuses). Seeded fresh rows only; no table dropped by the harness (the round trip's downgrade dropped `proposal_outcomes` as the migration does; its 30 rows were dumped first and put back, "Left behind").                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Redis    | `redis://127.0.0.1:6390/0`, the branch's `solus-redis-321`. `solus-redis-1` was not touched.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Harness  | `acceptance/p8_accept_live.py`. Evidence beside it: `p8_accept_live_result.json` (every frame, scripted call, probe, log line), `.stdout`, `.stderr`, `.time`; the 10 SSE bodies `p8_sse_<turn>.txt`; `p8_usage_turns_{u,v,a_p1}.json` (the raw route bodies); `p8_seed_ids.json`; `p8_sql_leg1_rows.{txt,jsonl}`, `p8_signals_by_hand.txt`, `p8_digests_by_hand.txt`, `p8_code_digests.txt`, `p8_leg1_evidence.txt`, `p8_leg2_evidence.txt`, `p8_leg3_evidence.txt`, `p8_leg4_evidence.txt`, `p8_leg4_sql.txt`, `p8_leg5_sql.txt`, `p8_run_identity.txt`; `p8_migration_roundtrip.txt`, `p8_proposal_outcomes_before_roundtrip.sql`, `p8_proposal_outcomes_after_restore.sql`, `p8_restore.txt`, `p8_db_after_upgrade.txt`, `p8_db_final.txt`; `p8_proxy_pytest.{log,time}`; run 1 in `p8_run1/`. |
| Commands | Harness: `cd packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' timeout 900 uv run --frozen --no-sync python <harness>`. Alembic: `SOLUS_DATABASE_URL=…/solus_sol uv run alembic …` from `packages/api`. Proxies: below.                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

## Environment recipe as executed

1. **Database.** `solus_sol` held P7's leave-behind, upgraded first to `a32100000001`
   (`proposal_outcomes` created empty; `ix_credit_ledger_user_created` built, valid). Before run 1:
   45 users, 48 projects, 89 `credit_ledger` rows (48 `usage`), 0 outcomes, 0 data events, 34
   sources, 33 tool confirmations.
2. **Environment.** The harness refuses to start unless exactly `SOLUS_DATABASE_URL` and
   `SOLUS_REDIS_URL` hold the prescribed values, re-checks the `SOLUS_*` set after its imports, and
   refuses unless the server says `solus_sol` at `a32100000001`. `SOLUS_TEST_DATABASE_URL` was set only
   on the proxy pytest's command line.
3. **Settings, in code** (as P7): `Settings(_env_file=None, supabase_jwt_secret=<token_urlsafe(32) per
run>, audience authenticated, rate limits 100_000, sync_inline=True,
fingerprint_embedding_enabled=False, artifact_local_root=<TemporaryDirectory>)`; Onshape allowance
   2,500, degrade ratio 0.7, quota pool `owner` (defaults).
4. **App.** `create_app(settings, create_async_engine(solus_sol))`, then
   `hardware_connections.owner = RuntimeOwner(<tmp>, <tmp>)`,
   `agent_runner = LlmRunner(adapters={anthropic, google, openai: P8AScriptedModel})`, and the
   Narrator's `_complete = partial(gateway.complete, adapters=<P8AScriptedModel>)`. The lifespan was
   not run.
5. **The scripted model.** A runner round (purpose `answer` with a tool conversation) pops the next
   scripted round (text and tool uses under the provider-safe name, each resolved to an offered
   spec); any other call pops the next scripted reply for its purpose (`planner` replies with the
   first id it was offered and reports `Usage(0, 0)`; `vision`, `extract`, `motif`, the recipe's
   `answer` and `narration` reply with fixed text). Nothing scripted for a call → it raises (0 did).
6. **Adapter injection.** A gateway call whose caller named no adapters (`render_view`'s read, the
   page read, `label_motifs`, the firmware recipe) got the scripted adapters only while the phase that
   drives that purpose ran (`u3-tool-calls`: 4 calls, recorded `scripted (injected)`), else
   `P8ARefusingAdapter` (0 reaches).
7. **Companions** (`P8ACompanion`): in-process `BridgeSession`s whose hello inventory the real
   allowlist gates (`validate_inventory`), answered in process, encoded by the companion's own
   `map_result` / `tool_result_ok`, parsed by the cloud's `parse_frame` and handed to `ingest_result`.
   - A in P1: `machine.write_file` + `machine.tool_versions` (the builtin `MachineServer` over a
     scratch workspace holding `notes/README.txt`; its `which`/`capture` seams scripted, nothing
     runs) and `code.plan` + `code.exec` with the schemas the code fork's own server lists
     (`acceptance/p6_inventory.json`; `integrations/mcp/code` unchanged since, `git log`). Admitted:
     `machine.write_file` (confirm), `machine.tool_versions`, `code.plan`, `code.exec` (confirm).
     `code.plan` answers `{"ok": true, "argv": ["/usr/bin/uname", "-a"], "cwd": ".", "environment":
null, "profile": null, "sandbox": {"kind": "landlock", "limitations": []}, "program_scope":
"system"}` for that argv; `code.exec` answers exit 0 with a scripted stdout tail.
     Machine registered through `PUT …/members/me/machines/{instance}` → 200, entity
     `01a18de3-00f5-78aa-b6ef-3b1e107a5a84`.
   - U in P2: `machine.write_file` + `machine.tool_versions` over a workspace holding
     `fw/fake_arm.ino`.
   - Two scripted companion behaviours, each recorded on its frame: the M5 write lets a sync land
     (the code host's cursor updated and committed in its own session) and then takes a second; the
     missing-preview card's dry run answers `tool_error`.
8. **Other seams.** Onshape: `OnshapeConnector.http` → an `httpx.MockTransport` answering only
   `GET …/variables` (one Variable Studio table), 599 otherwise; the quota ledger written through the
   scoped connector's own `CallMeter.record(200)`, its keys deleted afterwards. Web:
   `deps.discover_research_tools` returns the two Brave tools only during the web turn (else none,
   the real no-key answer), `research_tool.call_discovered` answers from the turn's script.
   `render_view`: `Renderers.plan` returns a scene plan of the subject and `Renderers.render` a
   320×240 PNG (no render child); the read of it is the real `vision_extract` → gateway.
9. **Probes, recording only:** `confirmations._build_preview` and `execution_policy._build_preview`
   (rows, labels, the refusal appended), `BuildExecutionPolicy.prepare`, the decide route's
   `signals_at_click` and both routers' `record_outcome`, `CallMeter.admit`, the gateway's
   `stream`/`complete`, companion frames, a root log handler at INFO. 0 probe errors.
10. **Order of steps.** Seed P1 (A, B invited, G and PG, A's consent, 5 notes, the PDF artifact, 7
    sources, the Onshape source, the fake arm and a CAD leaf, A's companion and machine) → seed P2
    (U, V invited, the fake arm, two `servo 7` twins, two stall findings, a motif candidate, the PDF
    artifact, U's companion) → leg 1 (t1–t4 park 13 cards, t5 two auto-runs, 13 decisions, B's card and
    decision) → leg 2 → leg 4 (u1, u2, u3, the narration, v1) → leg 3 → leg 5 → teardown. A frequency
    pacer read the gate's own Redis window and kept every person under 18 of the 20 calls a minute (one
    wait, A, 59.22 s, before the `expire` decision). Then the round trip, the restore, the pytest guard
    in its own call, and the proxies.

## Why no real provider was reachable

1. **The runner's adapters are the script.** `LlmRunner(adapters=…)` hands the gateway one
   `P8AScriptedModel` per catalog provider (`anthropic`, `google`, `openai`). 25 reaches, 0
   unscripted, 0 rounds or replies left in any script.
2. **Every other gateway call** got the refusing adapter unless its purpose was the phase's: 0
   refusing reaches; 4 `scripted (injected)` calls, all in `u3-tool-calls`.
3. **The real adapter registry raises.** `gateway.build_adapter_registry` records and raises: 0 reaches.
4. **No credentials.** `InMemorySecretStore`; `secrets_key` unset, `aws_region` None, `supabase_url`
   None; the JWT secret per run; the Onshape secret a placeholder string.
5. **No `.env` read.** `DotEnvSettingsSource._read_env_files` refuses and records: 1 refusal
   (`/home/beeboss/Solus/.env` at import).
6. **Egress and spawn guards.** Only loopback 5432/6390 may connect and only loopback names resolve: 10
   attempts — `bind ::1:0` denied (urllib3's import-time IPv6 probe, as P3–P7), resolve
   `localhost:5432` ×4, connect `127.0.0.1:5432` ×4, connect `127.0.0.1:6390` ×1. Every way to start a
   process records and raises: 0 attempts.
7. **Brave and Onshape never left the process.** Discovery registered the web tools on 1 of 24
   registry builds (the web turn); 2 scripted Brave calls. One Onshape MockTransport request (the
   park-time variable read); the click's read was refused by the meter before any request.

| Count                   | t1  | t2  | t3  | t4  | t5  | t6 (B) | u1  | u2  | u3  | narration | v1  |
| ----------------------- | --- | --- | --- | --- | --- | ------ | --- | --- | --- | --------- | --- |
| Scripted model calls    | 2   | 2   | 2   | 2   | 3   | 2      | 3   | 1   | 6   | 1         | 1   |
| Cards parked            | 4   | 4   | 1   | 4   | 0   | 1      | 0   | 0   | 0   | –         | 0   |
| Outcome rows            | –   | –   | –   | –   | 2   | –      | –   | –   | –   | –         | –   |
| Refusing / real reaches | 0   | 0   | 0   | 0   | 0   | 0      | 0   | 0   | 0   | 0         | 0   |

Plus 14 decisions (13 A, 1 B), each one outcome row. `credit_ledger` gained 32 rows in the final run:
5 `trial_grant` (A, B, G, U, V), 25 model-call `usage` rows (A 11, B 2, U 11, V 1) and 2 `web` rows
(U). Routes (`model call start` lines): `openai_trivial` ×12, `openai_standard` ×5, `general_hard`
×4, `visual_standard` ×3, `code_standard` ×1. A line as logged:

```
model call start call_id=58ceefd1-7f52-48e4-abf9-271c98f8a3cf provider=openai model=gpt-5.6-sol role=openai_standard complexity=standard type=general purpose=answer turn_id=2eb7dae3-e72c-46d1-aead-9cd60e82eb59
```

## Seed (ids for the record)

People were minted as `tests/conftest.py::make_token` does and provisioned by `/users/me`; teams and
projects came from `POST /api/v1/teams` and `POST /api/v1/teams/{id}/projects`; B joined P1's team and
V joined P2's through `POST /teams/{t}/invites` 201 → `POST /invites/{token}/accept` 200. A gave consent
through `PATCH /api/v1/users/me/settings {"data_collection_consent": true}` → 200; nobody else did.

| Who / what                                                             | Id                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A (decider, consented) / **P1** (outcomes)                             | `01a18de2-fd7c-7b1f-a5cd-e9068087e571` / **`01a18de2-fdf4-7406-8d09-afd0a8b15c6d`** (team `01a18de2-fde0-…f207`)                                                                                                                                                                                                                                                                                                                                                                                       |
| B (P1 member, no consent)                                              | `01a18de2-fda6-77c1-8fee-4856d4052ce8`                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| G / **PG** (another team)                                              | `01a18de2-fdb2-7ab3-8bb3-16608189541c` / **`01a18de2-fe55-789f-b342-58b472e678ca`**                                                                                                                                                                                                                                                                                                                                                                                                                    |
| U / **P2** (usage)                                                     | `01a18de2-fdc0-7dd1-929a-cc0910637d67` / **`01a18de3-0138-7627-b490-90cef91ac441`**                                                                                                                                                                                                                                                                                                                                                                                                                    |
| V (P2 member)                                                          | `01a18de2-fdce-7379-abc3-53ed1bd338e2`                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| P1 sources (seeded rows)                                               | github `01a18de2-ff0f-…c2d4` (`sha` sha1("p8 head") = `51e0fb8f…74ce`), kicad `-ff12-…443d` (`content_sha`), local `-ff13-…a445` (`digest`), gitlab `-ff14-…9446` (`etag` + `page`, no token), github snapshot `-ff16-…34e5` (`revision_base_source_id` = github), ros `-ff17-…f27c` (`{}`), Onshape `-ff1a-…196c` (connected, write, document `fdf502de3a4841149199850f`, cursor `{}`)                                                                                                                |
| P1 entity targets                                                      | fake arm robot `3e49e92f-2a8c-4e73-a4a9-d338bc640070`; CAD leaf `01a18de3-00cd-79ce-b40a-d0f1e1767269` (part, mechanical, revision `p8r1`)                                                                                                                                                                                                                                                                                                                                                             |
| P1 artifact (the committed one-page `tests/fixtures/render_sheet.pdf`) | `01a18de2-ff09-7142-a1a7-9ea1f49ca176`                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| P2                                                                     | fake arm robot `d6c6904d-…d712`, brain `e2a0f29e-b665-49a4-8753-2a351f52fb65`, servo 1 `d9658453-ee21-4ffd-84de-b1896b3ae918`; twins `servo 7 (left)` `01a18de3-034d-786e-a7bc-38ad031b840f`, `servo 7 (right)` `01a18de3-034e-7fcd-85e1-78015423066f`; motif members R1 `-034f-…`, R2 `-0350-…`, net VSENSE `-0351-…` (`attrs.motifs` divider_adc, confidence 0.6); stall findings `01a18de3-0361-…1c31` (turn) and `01a18de3-036f-…012f` (narrated); artifact `01a18de3-0379-736e-b569-fd9084220a8b` |
| Machines (companion ids)                                               | A `kA` → machine entity `01a18de3-00f5-78aa-b6ef-3b1e107a5a84`                                                                                                                                                                                                                                                                                                                                                                                                                                         |

## Leg 1: five decisions → five rows (and every extra the dispatch names)

**The cards were parked by real turns** (A, `action_mode: do`): t1 four `edit_solus_entry`
proposals in one round; t2 `propose_part_definition` ×2 (the forged one, order A),
`bench.import_cad_scene` and `set_hardware_config_field`; t3 the order-B definition in a fresh chat;
t4 with `force_confirmation: true` `machine.write_file` ×2, `onshape.set_variable` and `code.exec`.
Each turn's frame order (t4 as an example, `p8_sse_t4-forced-cards.txt`): `context_used, (tool_call,
tool_result, tool_confirmation) ×4, token, message, done`. t5 (no force) auto-ran both owned
routines: `BuildExecutionPolicy.prepare` → `machine.write_file: true`, `code.exec: true`; frames
`context_used, tool_call, tool_result, tool_call, tool_result, token, message, done`, no card.

**The rows, as stored** (`psql`, P1, oldest first; `p8_sql_leg1_rows.txt`):

```
          created_at           |   decision    |           tool            |     digest16      |                entity_ids                | n_signals |              machine_id              |         conversation_turn_id         | decider |                  id
-------------------------------+---------------+---------------------------+-------------------+------------------------------------------+-----------+--------------------------------------+--------------------------------------+---------+--------------------------------------
 2026-10-30 17:37:08.698634+00 | accepted_auto | machine.write_file        | 6848ab296e16e801… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 |                                      | A       | 01a18de3-085a-75dd-b5f1-5b49c1f36f66
 2026-10-30 17:37:08.724615+00 | accepted_auto | code.exec                 | ddb7c0e431ba2250… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 |                                      | A       | 01a18de3-0874-7850-b472-c5c6e9c7faf6
 2026-10-30 17:37:08.870367+00 | accepted      | edit_solus_entry          | 3eaad0fbe389b14d… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-0905-7c9b-9bb0-d05a9252a804 | A       | 01a18de3-0906-7fa9-8803-67d8802095ce
 2026-10-30 17:37:08.949132+00 | rejected      | edit_solus_entry          | 47655db270dfc59b… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-0953-7ea4-860a-df4bcfb7bc6d | A       | 01a18de3-0955-792b-b8b9-b765f8e47e75
 2026-10-30 17:38:08.382227+00 | expired       | edit_solus_entry          | a09cce4fab3f555a… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f17a-7c52-9946-6f4518313c53 | A       | 01a18de3-f17e-7e24-b051-2a2164ba5c7f
 2026-10-30 17:38:08.519573+00 | stale         | edit_solus_entry          | 50b9384fcb867980… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f204-74d5-8164-ffaf7ac2e8a6 | A       | 01a18de3-f207-7540-9acb-b421796ae111
 2026-10-30 17:38:08.604097+00 | rejected      | propose_part_definition   | 9b31e961c11cebfc… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f259-7bb9-9ae1-ccd41d5c6a73 | A       | 01a18de3-f25c-7533-808e-385d4dc73e8d
 2026-10-30 17:38:08.695735+00 | rejected      | bench.import_cad_scene    | faaae159c64587d4… | ["3e49e92f-2a8c-4e73-a4a9-d338bc640070"] |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f2b1-7fab-81f5-82c16ccc9ded | A       | 01a18de3-f2b7-7347-920a-863ea2a10ed3
 2026-10-30 17:38:08.779762+00 | rejected      | set_hardware_config_field | 1740cfc4140ff6c3… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f30a-72f6-838d-b333fd4748c3 | A       | 01a18de3-f30b-706c-9b35-a96457785e62
 2026-10-30 17:38:08.861079+00 | rejected      | propose_part_definition   | 3d479934da39efee… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f35a-75aa-a3dc-2a470054d5f8 | A       | 01a18de3-f35d-7703-b7bb-58458f2b4ac3
 2026-10-30 17:38:08.941536+00 | rejected      | propose_part_definition   | 3d479934da39efee… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f3ab-7f4d-9a9e-694bc21b45dd | A       | 01a18de3-f3ad-7866-85bc-ec95cfe4e38f
 2026-10-30 17:38:09.026426+00 | stale         | machine.write_file        | 03d44074f1ea1aab… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f3ff-7b76-b9e0-9d136e01a4fc | A       | 01a18de3-f402-71ea-9318-65f0c3a05663
 2026-10-30 17:38:09.33835+00  | stale         | onshape.set_variable      | eb7d1ada2a2a9794… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f537-7969-8b8f-9e06dfcbfbf1 | A       | 01a18de3-f53a-75f0-881f-16d91dba2226
 2026-10-30 17:38:09.42013+00  | accepted      | code.exec                 | b0e88e5809d87a3e… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f58a-7e6e-818d-01853a7f7af3 | A       | 01a18de3-f58c-7b4d-a23f-a0ec46772bb9
 2026-10-30 17:38:10.529947+00 | accepted      | machine.write_file        | 3dc0331aee4fdc24… | []                                       |         4 | 01a18de3-00f5-78aa-b6ef-3b1e107a5a84 | 01a18de3-f9de-789d-a66e-1c80ca7fa4cc | A       | 01a18de3-f9e1-7106-b0ca-048cca87c52f
 2026-10-30 17:38:10.779427+00 | rejected      | edit_solus_entry          | 8e0797e4e13df412… | []                                       |         4 |                                      | 01a18de3-fad9-7be2-a049-b795131bd217 | B       | 01a18de3-fadb-7ec2-9cf2-d2b79cc96802
(16 rows)
```

The five binding decisions, whole (`row_to_json`, `p8_sql_leg1_rows.jsonl` lines 1, 3, 4, 5, 6):

```json
{"id":"01a18de3-085a-75dd-b5f1-5b49c1f36f66","project_id":"01a18de2-fdf4-7406-8d09-afd0a8b15c6d","user_id":"01a18de2-fd7c-7b1f-a5cd-e9068087e571","conversation_turn_id":null,"tool":"machine.write_file","proposal_digest":"6848ab296e16e801c7d92e73ef8211673d81c54770d0780050270cda6c8c78f9","decision":"accepted_auto","entity_ids":[],"design_signals":{"01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4": "51e0fb8ff4cc9869178f6f4d1c201f21038474ce", "01a18de2-ff12-7129-9730-4af55305443d": "2a96441d2d4a9bf24953ba0f00bd418bc0e57348779ee7bf98d557fe3c3ed898", "01a18de2-ff13-7d35-b3f3-bea28504a445": "3805b3a857211fd94c4461629b9a8576b0ddf1d57eff8dc58cf7a321f4092109", "01a18de2-ff14-7989-a71e-c5e319f09446": "00a0829699f67dbc94d6aadc9be8a1090b6a3097"},"machine_id":"01a18de3-00f5-78aa-b6ef-3b1e107a5a84","created_at":"2026-10-30T17:37:08.698634+00:00"}
{"id":"01a18de3-0906-7fa9-8803-67d8802095ce","project_id":"01a18de2-fdf4-7406-8d09-afd0a8b15c6d","user_id":"01a18de2-fd7c-7b1f-a5cd-e9068087e571","conversation_turn_id":"01a18de3-0905-7c9b-9bb0-d05a9252a804","tool":"edit_solus_entry","proposal_digest":"3eaad0fbe389b14d718d1e5d8333ff4f7dced5270ba836de04297e7ed105aed5","decision":"accepted","entity_ids":[],"design_signals":{"01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4": "51e0fb8ff4cc9869178f6f4d1c201f21038474ce", "01a18de2-ff12-7129-9730-4af55305443d": "2a96441d2d4a9bf24953ba0f00bd418bc0e57348779ee7bf98d557fe3c3ed898", "01a18de2-ff13-7d35-b3f3-bea28504a445": "3805b3a857211fd94c4461629b9a8576b0ddf1d57eff8dc58cf7a321f4092109", "01a18de2-ff14-7989-a71e-c5e319f09446": "00a0829699f67dbc94d6aadc9be8a1090b6a3097"},"machine_id":"01a18de3-00f5-78aa-b6ef-3b1e107a5a84","created_at":"2026-10-30T17:37:08.870367+00:00"}
{"id":"01a18de3-0955-792b-b8b9-b765f8e47e75","project_id":"01a18de2-fdf4-7406-8d09-afd0a8b15c6d","user_id":"01a18de2-fd7c-7b1f-a5cd-e9068087e571","conversation_turn_id":"01a18de3-0953-7ea4-860a-df4bcfb7bc6d","tool":"edit_solus_entry","proposal_digest":"47655db270dfc59b9ddf67fbb50ed51ddde99f323facf72ff2d4613399326dae","decision":"rejected","entity_ids":[],"design_signals":{"01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4": "51e0fb8ff4cc9869178f6f4d1c201f21038474ce", "01a18de2-ff12-7129-9730-4af55305443d": "2a96441d2d4a9bf24953ba0f00bd418bc0e57348779ee7bf98d557fe3c3ed898", "01a18de2-ff13-7d35-b3f3-bea28504a445": "3805b3a857211fd94c4461629b9a8576b0ddf1d57eff8dc58cf7a321f4092109", "01a18de2-ff14-7989-a71e-c5e319f09446": "00a0829699f67dbc94d6aadc9be8a1090b6a3097"},"machine_id":"01a18de3-00f5-78aa-b6ef-3b1e107a5a84","created_at":"2026-10-30T17:37:08.949132+00:00"}
{"id":"01a18de3-f17e-7e24-b051-2a2164ba5c7f","project_id":"01a18de2-fdf4-7406-8d09-afd0a8b15c6d","user_id":"01a18de2-fd7c-7b1f-a5cd-e9068087e571","conversation_turn_id":"01a18de3-f17a-7c52-9946-6f4518313c53","tool":"edit_solus_entry","proposal_digest":"a09cce4fab3f555a4ebcdcd04f76ada50c56803c254bc8198b4cc9a0c0b3ad0b","decision":"expired","entity_ids":[],"design_signals":{"01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4": "51e0fb8ff4cc9869178f6f4d1c201f21038474ce", "01a18de2-ff12-7129-9730-4af55305443d": "2a96441d2d4a9bf24953ba0f00bd418bc0e57348779ee7bf98d557fe3c3ed898", "01a18de2-ff13-7d35-b3f3-bea28504a445": "3805b3a857211fd94c4461629b9a8576b0ddf1d57eff8dc58cf7a321f4092109", "01a18de2-ff14-7989-a71e-c5e319f09446": "00a0829699f67dbc94d6aadc9be8a1090b6a3097"},"machine_id":"01a18de3-00f5-78aa-b6ef-3b1e107a5a84","created_at":"2026-10-30T17:38:08.382227+00:00"}
{"id":"01a18de3-f207-7540-9acb-b421796ae111","project_id":"01a18de2-fdf4-7406-8d09-afd0a8b15c6d","user_id":"01a18de2-fd7c-7b1f-a5cd-e9068087e571","conversation_turn_id":"01a18de3-f204-74d5-8164-ffaf7ac2e8a6","tool":"edit_solus_entry","proposal_digest":"50b9384fcb867980bc6033b9fd3b13b5b45efe449252def350410a685ffd0673","decision":"stale","entity_ids":[],"design_signals":{"01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4": "51e0fb8ff4cc9869178f6f4d1c201f21038474ce", "01a18de2-ff12-7129-9730-4af55305443d": "2a96441d2d4a9bf24953ba0f00bd418bc0e57348779ee7bf98d557fe3c3ed898", "01a18de2-ff13-7d35-b3f3-bea28504a445": "3805b3a857211fd94c4461629b9a8576b0ddf1d57eff8dc58cf7a321f4092109", "01a18de2-ff14-7989-a71e-c5e319f09446": "00a0829699f67dbc94d6aadc9be8a1090b6a3097"},"machine_id":"01a18de3-00f5-78aa-b6ef-3b1e107a5a84","created_at":"2026-10-30T17:38:08.519573+00:00"}
```

**Each row's `conversation_turn_id` is its decision's tool turn** (role `tool`):

```
approve   01a18de3-0905-…  "edit_solus_entry → approved by you and applied ok"
reject    01a18de3-0953-…  "edit_solus_entry → rejected by you; nothing was applied"
expire    01a18de3-f17a-…  "edit_solus_entry → not applied (unauthorized) — ask again to see the current change"
diverge   01a18de3-f204-…  "edit_solus_entry → not applied (unauthorized) — ask again to see the current change"
quota     01a18de3-f537-…  "onshape.set_variable → not applied (unavailable) — ask again to see the current change"
missing   01a18de3-f3ff-…  "machine.write_file → not applied (unauthorized) — ask again to see the current change"
code_card 01a18de3-f58a-…  "code.exec → approved by you; the command exited 0 — output tail: Linux p8-bench 6.8.0 aarch64 GNU/Linux (P8 acceptance: a scripted answer)"
m5        01a18de3-f9de-…  "machine.write_file → approved by you and applied ok"
b_reject  01a18de3-fad9-…  "edit_solus_entry → rejected by you; nothing was applied"
```

The two auto-run rows have `conversation_turn_id` null (`record_outcome` was handed
`conversation_turn_id=None` by `routers/sol.py`; P8 report deviation 6).

**The decide responses** (the route's envelope `data`):

```
approve   {"ok": true, "value": {"ok": true}, "error": null}
reject    {"ok": false, "error": {"code": "unauthorized", "message": "You rejected this action."}}
expire    {"ok": false, "error": {"code": "unauthorized", "message": "This action expired before it was approved; ask again."}}
diverge   {"ok": false, "error": {"code": "unauthorized", "message": "What this action would do has changed since it was shown to you. Nothing was applied — ask again to see the current change."}}
missing   {"ok": false, "error": {"code": "unauthorized", "message": "What this action would do has changed since it was shown to you. Nothing was applied — ask again to see the current change."}}
quota     {"ok": false, "error": {"code": "unavailable", "message": "Onshape API quota has reached its conservation threshold. SOL actions are paused to reserve the remaining allowance. Nothing was executed."}}
code_card {"ok": true, "value": {"exit_code": 0, "stdout_tail": "Linux p8-bench 6.8.0 aarch64 GNU/Linux (P8 acceptance: a scripted answer)\n", …, "argv": ["/usr/bin/uname", "-a"]}}
m5        {"ok": true, "value": {"path": "notes/p8-m5.txt", "bytes_written": 39, "changed": true, "verified": true}}
```

**The expired card.** Its `expires_at` was set to `now() - 1 minute` by SQL before the click
(`expires_at 2026-10-30 17:36:08.959+00` against the server's `now() 17:37:08.961+00`), the test's
method: the 30-minute `CONFIRMATION_TTL` was not waited out (deviation 2).

**The three stale cases** (the gate's `_build_preview` at the click, probed; the card's stored rows
from `tool_confirmations`):

```
diverge -> {"where": "gate", "tool": "edit_solus_entry", "rows": 1, "labels": ["Entry"], "refusals_appended": [], "requires_complete_preview": false}
   card:  {"label": "Entry", "before": "Power-up order: bus first, then the brain board, then the servos.", "after": "Power-up order: 1. the bus, 2. the brain board, 3. the servos."}
   entry now (PATCH …/solus/entries/{id} -> 200 between park and click): "Power-up order: the bus, then the servos, then the brain board (changed by a person)."
quota   -> {"where": "gate", "tool": "onshape.set_variable", "rows": 0, "labels": [], "refusals_appended": ["Onshape API quota has reached its conservation threshold. SOL actions are paused to reserve the remaining allowance. Nothing was executed."], "requires_complete_preview": true}
   card:  {"label": "document", "before": null, "after": "fdf502de3a4841149199850f"}
          {"label": "arm_length", "before": "{\"expression\": \"120 mm\", \"name\": \"arm_length\", \"type\": \"LENGTH\"}", "after": "{\"expression\": \"130 mm\", \"name\": \"arm_length\", \"type\": \"LENGTH\"}"}
   ledger: {"threshold": 1750, "used_before": 1, "key": "solus:intq:onshape:acct:p8-acceptance-onshape-fdf502de3a48:2026", "value_after": "1750"}; cleanup deleted 2 keys (the year count and its agent_write label)
   meter:  t4-forced-cards admitted; decide:quota {"admitted": false, "code": "quota_degraded", "used_before": "1750", "purpose": "agent"}
   MockTransport: 1 request, at park: GET /api/v6/variables/d/fdf502de…/w/02de3a48…/e/3a484114…/variables (answered); 0 at the click
missing -> {"where": "gate", "tool": "machine.write_file", "rows": 0, "labels": [], "refusals_appended": [], "requires_complete_preview": true}
   card:  {"label": "File", "after": "notes/p8-missing.txt"}, {"label": "File state fingerprint", "after": "856a2735…:042cd91b…:7116af40…:92c1f30a…"}, {"label": "Content 1", "after": "missing preview: a scripted fault\n"}
   companion frame at the click: machine.write_file dry_run=true -> "dry-run fault" (tool_error); log: solus.agent.confirmations "preview failed for machine.write_file (complete preview required=True)"
```

**The digest, recomputed by hand** (`p8_digests_by_hand.txt`: plain `python3 -I`, the stored
`tool_confirmations.args` text, `json.dumps(args, sort_keys=True, separators=(",", ":"))`,
sha256). The redaction is the identity for these arguments (the harness checked
`redact_value(_redact_args(args)) == args` for each: true):

```
card 01a18de3-04ff-7681-94d8-e2a799df3d6f edit_solus_entry
  stored args (as stored, key order kept): {"entry_id": "01a18de2-febb-7c29-840a-a0a5ab1d6664", "text": "Cable routing: run the servo leads along the left rail. Tie them every 5 cm."}
  canonical: {"entry_id":"01a18de2-febb-7c29-840a-a0a5ab1d6664","text":"Cable routing: run the servo leads along the left rail. Tie them every 5 cm."}
  sha256 by hand: 3eaad0fbe389b14d718d1e5d8333ff4f7dced5270ba836de04297e7ed105aed5
  row digest:     3eaad0fbe389b14d718d1e5d8333ff4f7dced5270ba836de04297e7ed105aed5 MATCH
card 01a18de3-05c5-7681-8259-2bd98662538c propose_part_definition
  stored args (as stored, key order kept): {"definition": {"name": "Fake bus buffer", "manufacturer": "Fake parts", "category": "buffer", "specs": {"supply_voltage": "5.0 V", "stall_current": "2 A"}}, "source_artifact_id": "01a18de2-ff09-7142-a1a7-9ea1f49ca176", "pages": [1]}
  sha256 by hand: 3d479934da39efee831d3072f14acb5eb93c0083596f6d8cfde873a13faf5175
  row digest:     3d479934da39efee831d3072f14acb5eb93c0083596f6d8cfde873a13faf5175 MATCH
card 01a18de3-06cb-7d3d-9efc-45962da36414 propose_part_definition
  stored args (as stored, key order kept): {"pages": [1], "source_artifact_id": "01a18de2-ff09-7142-a1a7-9ea1f49ca176", "definition": {"specs": {"stall_current": "2 A", "supply_voltage": "5.0 V"}, "category": "buffer", "manufacturer": "Fake parts", "name": "Fake bus buffer"}}
  canonical: {"definition":{"category":"buffer","manufacturer":"Fake parts","name":"Fake bus buffer","specs":{"stall_current":"2 A","supply_voltage":"5.0 V"}},"pages":[1],"source_artifact_id":"01a18de2-ff09-7142-a1a7-9ea1f49ca176"}
  sha256 by hand: 3d479934da39efee831d3072f14acb5eb93c0083596f6d8cfde873a13faf5175
  row digest:     3d479934da39efee831d3072f14acb5eb93c0083596f6d8cfde873a13faf5175 MATCH
card 01a18de3-05bf-71cb-8ff8-c637a2824320 propose_part_definition   (the forged label)
  stored args: {"definition": {"name": "Fake servo driver", "manufacturer": "Fake parts", "category": "driver", "specs": {"plan fingerprint": "b0e88e5809d87a3e:c9023553e5fcefe9:4a42205b93b2f3e1:dc8ae1ecd0fce61b", "supply_voltage": "6.0 V"}}, "source_artifact_id": "01a18de2-ff09-7142-a1a7-9ea1f49ca176", "pages": [1]}
  sha256 by hand: 9b31e961c11cebfc966ba3691d4e41315732fefeaf0d668108c6773e0e80d4a1
  row digest:     9b31e961c11cebfc966ba3691d4e41315732fefeaf0d668108c6773e0e80d4a1 MATCH
card 01a18de3-0608-7362-9a94-3303191003eb bench.import_cad_scene
  stored args: {"robot_id": "3e49e92f-2a8c-4e73-a4a9-d338bc640070", "source_entity_id": "01a18de3-00cd-79ce-b40a-d0f1e1767269", "expected_revision": "p8r1"}
  sha256 by hand: faaae159c64587d4ec720c6aef443476f328bfc640349108c86b4a2acd2a04d8
  row digest:     faaae159c64587d4ec720c6aef443476f328bfc640349108c86b4a2acd2a04d8 MATCH
```

The two orderings were proposed by the scripted model in that order in two chats (t2, t3), stored in
their own order (`tool_confirmations.args` is JSON, not JSONB), and digest alike. The pure
`proposal_digest` of both orderings in process: `3d479934…5175` twice.

**I2, the forged label on a non-code card.** The `propose_part_definition` card's preview as stored
(the spec name became a row label; the value is the code card's grouped fingerprint):

```
{"label": "name", "before": "(none)", "after": "Fake servo driver"}
{"label": "manufacturer", "before": "(none)", "after": "Fake parts"}
{"label": "category", "before": "(none)", "after": "driver"}
{"label": "plan fingerprint", "before": "(none)", "after": "b0e88e5809d87a3e:c9023553e5fcefe9:4a42205b93b2f3e1:dc8ae1ecd0fce61b"}
{"label": "supply_voltage", "before": "(none)", "after": "6.0 V"}
```

`record_outcome` was handed these labels (probe), and the row's digest is the arguments'
`9b31e961…d4a1`, not `b0e88e58…e61b`: the code card's row is the only one holding the fingerprint.

**A `code.*` card records its fingerprint; M7 side by side** (`p8_code_digests.txt`):

```
$ the code.exec card (01a18de3-0786-…) as stored: args, then its preview rows
{"argv": ["uname", "-a"], "cwd": "."}
{"label": "program", "before": null, "after": "/usr/bin/uname"}
{"label": "command", "before": null, "after": "[\"/usr/bin/uname\", \"-a\"]"}
{"label": "cwd", "before": null, "after": "."}
{"label": "environment", "before": null, "after": "none"}
{"label": "profile", "before": null, "after": "none"}
{"label": "sandbox", "before": null, "after": "landlock — writes limited to the workspace, temp and tool caches"}
{"label": "risk", "before": null, "after": "none flagged"}
{"label": "plan fingerprint", "before": null, "after": "b0e88e5809d87a3e:c9023553e5fcefe9:4a42205b93b2f3e1:dc8ae1ecd0fce61b"}

$ the fingerprint, by hand (plain python3, from the plan fields the companion answered)
canonical: {"argv":["/usr/bin/uname","-a"],"cwd":".","environment":null,"profile_digest":null,"sandbox_kind":"landlock"}
sha256:    b0e88e5809d87a3ec9023553e5fcefe94a42205b93b2f3e1dc8ae1ecd0fce61b
grouped:   b0e88e5809d87a3e:c9023553e5fcefe9:4a42205b93b2f3e1:dc8ae1ecd0fce61b
auto-run args canonical: {"argv":["uname","-a"],"cwd":"."} sha256: ddb7c0e431ba22504e691e08ba32eb05462176607780890ed56acfadde4dfcf4

$ the two code.exec rows side by side
   decision    |   tool    |                         proposal_digest                          |         conversation_turn_id
---------------+-----------+------------------------------------------------------------------+--------------------------------------
 accepted_auto | code.exec | ddb7c0e431ba22504e691e08ba32eb05462176607780890ed56acfadde4dfcf4 |
 accepted      | code.exec | b0e88e5809d87a3ec9023553e5fcefe94a42205b93b2f3e1dc8ae1ecd0fce61b | 01a18de3-f58a-7e6e-818d-01853a7f7af3
```

Same command, two digests, by design: an auto-run has no card, so its row digests its redacted
arguments; the card path records the plan fingerprint the person approved (API.md §2.9, M7).

**M5, the click's signals** (`p8_leg1_evidence.txt`):

```
signals_at_click (probe, read before decide_confirmation): "51e0fb8ff4cc9869178f6f4d1c201f21038474ce" t= 63.931
the scripted sync inside the approved write: {"source": "01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4", "cursor": {"branch": "main", "sha": "1399b1a9ee36cec650d7146da73643ebc429275f"}, "t": 63.94}
record_outcome handed design_signals: "51e0fb8ff4cc9869178f6f4d1c201f21038474ce"
row design_signals[github]: 51e0fb8ff4cc9869178f6f4d1c201f21038474ce
source cursor after the decision: {"branch": "main", "sha": "1399b1a9ee36cec650d7146da73643ebc429275f"}
next decision (B, after the sync) row design_signals[github]: 1399b1a9ee36cec650d7146da73643ebc429275f
companion frames during decide:m5: [["machine.write_file", true, "notes/p8-m5.txt", null, true], ["machine.write_file", true, "notes/p8-m5.txt", null, true], ["machine.write_file", null, "notes/p8-m5.txt", "a sync lands while the write runs", true]]
```

The two dry runs are the click's preview and the write's own check; the third frame is the write,
which committed the new cursor and slept 1 s before writing. `sha1(b"p8 head")` =
`51e0fb8f…74ce` and `sha1(b"p8 head after the sync")` = `1399b1a9…275f`, by hand.

**Design signals, recomputed by hand from the cursors** (`p8_signals_by_hand.txt`; the github
cursor shows its post-M5 value, every row before M5 holds `51e0fb8f…`):

```
                  id                  |  type   | is_snapshot |                                       cursor
--------------------------------------+---------+-------------+-------------------------------------------------------------------------------------
 01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4 | github  | f           | {"branch": "main", "sha": "1399b1a9ee36cec650d7146da73643ebc429275f"}
 01a18de2-ff12-7129-9730-4af55305443d | kicad   | f           | {"content_sha": "2a96441d2d4a9bf24953ba0f00bd418bc0e57348779ee7bf98d557fe3c3ed898"}
 01a18de2-ff13-7d35-b3f3-bea28504a445 | local   | f           | {"digest": "3805b3a857211fd94c4461629b9a8576b0ddf1d57eff8dc58cf7a321f4092109"}
 01a18de2-ff14-7989-a71e-c5e319f09446 | gitlab  | f           | {"etag": "W/\"p8-acceptance\"", "page": 3}
 01a18de2-ff16-7f69-91dd-5d1adee034e5 | github  | t           | {"sha": "299a37810c93684585470cefbfc8979a2ac8ec36"}
 01a18de2-ff17-7f97-b380-3e8efe6af27c | ros     | f           | {}
 01a18de2-ff1a-7742-9c90-9e22a152196c | onshape | f           | {}
01a18de2-ff0f-73dc-9d8b-b9e5a873c2d4 1399b1a9ee36cec650d7146da73643ebc429275f (token key)
01a18de2-ff12-7129-9730-4af55305443d 2a96441d2d4a9bf24953ba0f00bd418bc0e57348779ee7bf98d557fe3c3ed898 (token key)
01a18de2-ff13-7d35-b3f3-bea28504a445 3805b3a857211fd94c4461629b9a8576b0ddf1d57eff8dc58cf7a321f4092109 (token key)
01a18de2-ff14-7989-a71e-c5e319f09446 00a0829699f67dbc94d6aadc9be8a1090b6a3097 (sha1 of the canonical cursor)
01a18de2-ff16-7f69-91dd-5d1adee034e5 revision snapshot -> left out
01a18de2-ff17-7f97-b380-3e8efe6af27c never synced -> left out
01a18de2-ff1a-7742-9c90-9e22a152196c never synced -> left out
sha1(canonical gitlab cursor) = 00a0829699f67dbc94d6aadc9be8a1090b6a3097 {"etag":"W/\"p8-acceptance\"","page":3}
```

**`entity_ids`.** `bench.import_cad_scene {robot_id: 3e49e92f-…, source_entity_id: 01a18de3-00cd-…,
expected_revision: p8r1}` → `["3e49e92f-2a8c-4e73-a4a9-d338bc640070"]` (its card had 4 rows: Robot,
CAD source, Source revision, Geometry); `set_hardware_config_field {robot_entity_id: 3e49e92f-…,
path: bus_map.0.address, value: 9}` → `[]` (observation 1).

**`edited`.** `schemas.py`: `class ConfirmationDecision(StrictModel): decision: Literal["approve",
"reject"]`; `grep -rn '"edited"' packages/api/src` → only `services/outcomes.py:51` (the
`OutcomeDecision` Literal) and `models.py:1016` (the CHECK); the only decision route is
`routers/sol_confirmations.py:280 @router.post("/confirmations/{confirmation_id}")`. Nothing a person
can do edits a proposal before deciding it, so no `edited` row can be written here.

## Leg 2: `GET /projects/{id}/outcomes`

A (`p8_leg2_evidence.txt`), `limit=200` → 200, `meta {"limit": 200, "has_next": false,
"next_cursor": null}`, 16 items newest first (`ids == DB order (created_at desc, id desc): True`).
The newest three as listed to A (B's row is a teammate's, so its three decider fields are null to A):

```
{"created_at": "2026-10-30T17:38:10.779427Z", "decision": "rejected", "tool": "edit_solus_entry", "proposal_digest": null, "machine_id": null, "conversation_turn_id": null, "entity_ids": []}
{"created_at": "2026-10-30T17:38:10.529947Z", "decision": "accepted", "tool": "machine.write_file", "proposal_digest": "3dc0331aee4fdc24831af3ab190013c93d0e8e8cc1c9d12312ae1c8661102be9", "machine_id": "01a18de3-00f5-78aa-b6ef-3b1e107a5a84", "conversation_turn_id": "01a18de3-f9de-789d-a66e-1c80ca7fa4cc", "entity_ids": []}
{"created_at": "2026-10-30T17:38:09.420130Z", "decision": "accepted", "tool": "code.exec", "proposal_digest": "b0e88e5809d87a3ec9023553e5fcefe94a42205b93b2f3e1dc8ae1ecd0fce61b", "machine_id": "01a18de3-00f5-78aa-b6ef-3b1e107a5a84", "conversation_turn_id": "01a18de3-f58a-7e6e-818d-01853a7f7af3", "entity_ids": []}
```

The oldest item, whole: `{"id": "01a18de3-085a-75dd-b5f1-5b49c1f36f66", "conversation_turn_id": null,
"tool": "machine.write_file", "proposal_digest": "6848ab29…78f9", "decision": "accepted_auto",
"entity_ids": [], "design_signals": {<the 4 keys>}, "machine_id": "01a18de3-00f5-…", "created_at":
"2026-10-30T17:37:08.698634Z"}` — no `user_id`, no arguments, no preview.

Paged with `limit=5`:

```
{"params": {"limit": 5}, "status": 200, "ids": ["01a18de3-fadb-…", "01a18de3-f9e1-…", "01a18de3-f58c-…", "01a18de3-f53a-…", "01a18de3-f402-…"], "meta": {"limit": 5, "has_next": true, "next_cursor": "WyIyMDI2LTEwLTMwVDE3OjM4OjA5LjAyNjQyNiswMDowMCIsICIwMWExOGRlMy1mNDAyLTcxZWEtOTMxOC02NWYwYzNhMDU2NjMiXQ"}}
{"params": {"limit": 5, "cursor": "WyIyMDI2LTEwLTMwVDE3OjM4OjA5LjAyNjQyNiswMDowMCIsICIwMWExOGRlMy1mNDAyLTcxZWEtOTMxOC02NWYwYzNhMDU2NjMiXQ"}, "status": 200, "ids": ["01a18de3-f3ad-…", "01a18de3-f35d-…", "01a18de3-f30b-…", "01a18de3-f2b7-…", "01a18de3-f25c-…"], "meta": {"limit": 5, "has_next": true, …}}
{"params": {"limit": 5, "cursor": "WyIyMDI2LTEwLTMwVDE3OjM4OjA4LjYwNDA5NyswMDowMCIsICIwMWExOGRlMy1mMjVjLTc1MzMtODA4ZS0zODVkNGRjNzNlOGQiXQ"}, "status": 200, "ids": ["01a18de3-f207-…", "01a18de3-f17e-…", "01a18de3-0955-…", "01a18de3-0906-…", "01a18de3-0874-…"], "meta": {"limit": 5, "has_next": true, …}}
{"params": {"limit": 5, "cursor": "WyIyMDI2LTEwLTMwVDE3OjM3OjA4LjcyNDYxNSswMDowMCIsICIwMWExOGRlMy0wODc0LTc4NTAtYjQ3Mi1jNWM2ZTljN2ZhZjYiXQ"}, "status": 200, "ids": ["01a18de3-085a-…"], "meta": {"limit": 5, "has_next": false, "next_cursor": null}}
pages concatenated == the full list: True
page 2 asked again with the same cursor: same: True
since = 4th newest created_at 2026-10-30T17:38:09.338350Z -> 4 ids, == the 4 newest: True
since = now - 200 days -> {"status": 200, "count": 16}
```

The cursor decodes to `["2026-10-30T17:38:09.026426+00:00", "01a18de3-f402-…"]`: (created_at, id).

B, P1's member (`GET …/outcomes` → 200, 16 items): B's own row with its turn and digest, every one of
A's with the three decider-only fields null:

```
{"decision": "rejected", "tool": "edit_solus_entry", "proposal_digest": "8e0797e4e13df412af3cd335ba424e1a6c2e29ab6dd00b628f7c785e3abd29a5", "machine_id": null, "conversation_turn_id": "01a18de3-fad9-7be2-a049-b795131bd217"}
{"decision": "accepted", "tool": "machine.write_file", "proposal_digest": null, "machine_id": null, "conversation_turn_id": null}
{"decision": "accepted", "tool": "code.exec", "proposal_digest": null, "machine_id": null, "conversation_turn_id": null}
… (13 more of A's, all three null)
{"decision": "accepted_auto", "tool": "machine.write_file", "proposal_digest": null, "machine_id": null, "conversation_turn_id": null}
```

(B's `machine_id` is null on B's own row because B has no companion.) Refusals:

```
G (another team) on P1: 404      U (P2's owner, not in P1's team) on P1: 404
A on G's project: 404            unknown project id: 404            no token: 401
limit=201 -> 422 {"error":{"code":"validation_error",…,"loc":["query","limit"],"msg":"Input should be less than or equal to 200",…}}
cursor=not-a-cursor -> 400 {"error":{"code":"invalid_cursor","message":"Malformed pagination cursor","details":[]}}
```

## Leg 3: `GET /projects/{id}/usage/turns`

U in P2, `?since=<now - 1 day>&limit=200` → 200, 13 rows (raw body `p8_usage_turns_u.json`):

```
$ /usr/bin/grep -c balance p8_usage_turns_u.json p8_usage_turns_v.json p8_usage_turns_a_p1.json
p8_usage_turns_u.json:0
p8_usage_turns_v.json:0
p8_usage_turns_a_p1.json:0
(exit 1)
$ the keys of every item
['created_at', 'credits', 'id', 'purpose', 'tier', 'tokens_in', 'tokens_out', 'turn_id'] 13 {'limit': 200, 'has_next': False, 'next_cursor': None}
```

Two rows as listed, the first one and the zero-credit one:

```json
{"id": "01a18de4-2579-7fa8-9963-5cf0af09a058", "created_at": "2026-10-30T17:38:21.689413Z", "turn_id": null, "purpose": "narration", "tier": "standard", "credits": 1, "tokens_in": 541, "tokens_out": 51}
{"id": "01a18de3-fbbc-7830-9d31-c5427e77311a", "created_at": "2026-10-30T17:38:11.004953Z", "turn_id": "fb97b034-12e5-4e36-bdac-953215205824", "purpose": "planner", "tier": "trivial", "credits": 0, "tokens_in": 0, "tokens_out": 0}
```

The zero-credit row as stored: `amount 0`, `balance_after 1000` (a column the route never
selects), attrs `{"role": "openai_trivial", "tier": "trivial", "call_id": "839100d2-…", "purpose":
"planner", "turn_id": "fb97b034-…", "tokens_in": 0, "model_name": "gpt-5.6-luna", "project_id":
"01a18de3-0138-…", "tokens_out": 0}` (`p8_leg4_sql.txt`).

Another member's rows: V's only row in P2 (`answer`, `01a18de4-2dd7-708a-adcd-67570cbf43ba`) is
absent from U's list, and V lists exactly that row:

```json
{
  "data": [
    {
      "id": "01a18de4-2dd7-708a-adcd-67570cbf43ba",
      "created_at": "2026-10-30T17:38:23.831668Z",
      "turn_id": "131f0180-2ca4-4cd1-b323-fb574e04761c",
      "purpose": "answer",
      "tier": "hard",
      "credits": 2,
      "tokens_in": 460,
      "tokens_out": 15
    }
  ],
  "meta": { "limit": 200, "has_next": false, "next_cursor": null }
}
```

`ids U lists vs V lists (disjoint)`: 13, 1, True. Paged `limit=3` → page 2 from page 1's cursor
continues newest-first. A in P1 lists A's 11 `answer` rows. Refusals: G on P2 404, U on G's project
404, A (not a member of P2) 404, no token 401, `limit=201` 422, malformed cursor 400.

## Leg 4: every purpose that exists live

Turns of U in P2 (`p8_leg4_evidence.txt`):

- **u1** (Guide; `finding_id` = the turn's stall finding → HARD; a screenshot; "Why does servo 7 run
  hot after the stall the bench reported? Check what my screenshot shows."): three gateway calls,
  all with this turn's id and P2's id — `complete` purpose `planner` (`trivial`, `general`; the
  scripted reply named the first offered twin `01a18de3-034d-…`, `Usage(0, 0)`), `complete` purpose
  `vision` (`visual_log`, the screenshot, 1 image), `stream` purpose `answer`. `context_used` anchors:
  the finding's three subjects and **only the picked twin** (`name_match` `01a18de3-034d-…`); u2
  (not HARD: its round routed `openai_trivial`, no planner call) anchored both twins.
- **u2** (`/web fake servo 7 datasheet supply voltage`): the server's research step —
  `tool_call research {"max_pages": 2, "max_searches": 1, "question": "fake servo 7 datasheet supply
voltage"}`, the scripted Brave fetcher answered `brave_web_search {"query": …, "count": 10}` and
  `brave_llm_context {"query": …, "maximum_number_of_urls": 2}`, `research_sources {"cached": false,
"searches": 1, "pages": 1, …}` — then one `answer` round. Two `web` debit rows (`search`,
  `context`, 2 credits each).
- **u3** (Do; "Look at the top face of servo 1, read the datasheet I uploaded, label the open circuit
  motifs and draft the firmware for the fake brain."): round 1 proposed four tools, each ran with its
  own model call inside the turn:
  - `render_view {entity_id: servo 1, question: "What does the top face of servo 1 look like?"}` →
    `{"rendered": true, "renderer": "scene", "view": "face:top", "cached": false, "read": "Servo 1
(joint 1) seen from the top: a flat housing (scripted read).", …}` — purpose `vision`;
  - `read_document {source: {artifact_id: 01a18de3-0379-…}, pages: [1]}` → `{"pages_read": [1],
"proposals": [{"kind": "rating", "name": "supply voltage", "value": "6.0", "unit": "V", "quote":
"Supply 6.0 V (fake)", "page": 1}], "title": "fake schematic sheet", …}` — purpose `extract`;
  - `label_motifs {}` → `{"labelled": [{"label": "divider_adc", "members": [R1, R2, VSENSE], "shape":
"divider_adc"}], "dropped": 0}` — purpose `motif`;
  - `firmware_recipe {board_id: fake brain, path: fw/fake_arm.ino}` → `{"path": "fw/fake_arm.ino",
"content": "// the fake arm's firmware (P8 acceptance: a scripted reply)\nvoid setup() {}\nvoid
loop() {}\n", "card_rows": 3, …}` — purpose `answer`, route `code_standard`;
  - then round 2. Every one of the six calls carried this turn's id and P2's id.
- **The narration** (`app.state.narrator.hear(P2, U, robot, [the second stall finding])`, as P6):
  after the 10 s debounce, one `complete` purpose `narration` as U, `turn_id` None, P2's id; the
  finding's `explanation` was written.
- **v1** (V, Guide): one `answer` round.

U's usage rows as stored (`p8_leg4_sql.txt`):

```
          created_at           | amount |  purpose  |   tier   |  turn8   | project_is_p2 | web_kind |      role       | tin  | tout
-------------------------------+--------+-----------+----------+----------+---------------+----------+-----------------+------+------
 2026-10-30 17:38:11.004953+00 |      0 | planner   | trivial  | fb97b034 | t             |          | openai_trivial  | 0    | 0
 2026-10-30 17:38:11.067982+00 |     -1 | vision    | standard | fb97b034 | t             |          | visual_standard | 149  | 16
 2026-10-30 17:38:11.087603+00 |     -9 | answer    | hard     | fb97b034 | t             |          | general_hard    | 4250 | 15
 2026-10-30 17:38:11.218589+00 |     -2 | web       |          | 60c19d97 | t             | search   |                 |      |
 2026-10-30 17:38:11.226102+00 |     -2 | web       |          | 60c19d97 | t             | context  |                 |      |
 2026-10-30 17:38:11.261768+00 |     -1 | answer    | trivial  | 60c19d97 | t             |          | openai_trivial  | 608  | 16
 2026-10-30 17:38:11.40234+00  |     -3 | answer    | hard     | d1ca61be | t             |          | general_hard    | 1365 | 1
 2026-10-30 17:38:11.434622+00 |     -1 | vision    | standard | d1ca61be | t             |          | visual_standard | 226  | 17
 2026-10-30 17:38:11.5136+00   |     -1 | extract   | standard | d1ca61be | t             |          | visual_standard | 291  | 26
 2026-10-30 17:38:11.534031+00 |     -1 | motif     | trivial  | d1ca61be | t             |          | openai_trivial  | 194  | 10
 2026-10-30 17:38:11.604582+00 |     -3 | answer    | standard | d1ca61be | t             |          | code_standard   | 1135 | 25
 2026-10-30 17:38:11.621349+00 |     -4 | answer    | hard     | d1ca61be | t             |          | general_hard    | 1769 | 15
 2026-10-30 17:38:21.689413+00 |     -1 | narration | standard |          | t             |          | openai_standard | 541  | 51
(13 rows)

$ select distinct purpose …
  purpose  | rows | credits | with_project | with_turn | with_tier
-----------+------+---------+--------------+-----------+-----------
 answer    |    5 |      20 |            5 |         5 |         5
 extract   |    1 |       1 |            1 |         1 |         1
 motif     |    1 |       1 |            1 |         1 |         1
 narration |    1 |       1 |            1 |         0 |         1
 planner   |    1 |       0 |            1 |         1 |         1
 vision    |    2 |       2 |            2 |         2 |         2
 web       |    2 |       4 |            2 |         2 |         0
(7 rows)
```

Every kind the dispatch names was driven and is in the ledger. Not driven here (no turn, no project
by design): `fingerprint/visual.py` (vision), `fingerprint/escalation.py` (extract),
`impact/consequences.py` and `livebench/runs/narration.py` (narration), `toolkb/ingest/visual.py`
(vision), `sourcing/engine.py` (answer); the rulebook's `extract_rulebook` uses the same
`read_pages` → `extract_pages` path as the driven page read.

## Leg 5: the events, and the migration round trip

**Events** (`p8_leg5_sql.txt`):

```
$ select … from data_events where event_type = 'sol.proposal_outcome' and project_id = P1
          created_at           | who | team_is_p1s | project_is_p1 | payload
-------------------------------+-----+-------------+---------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 2026-10-30 17:37:08.700896+00 | A   | t           | t             | {"tool": "machine.write_file", "decision": "accepted_auto", "outcome_id": "01a18de3-085a-75dd-b5f1-5b49c1f36f66", "proposal_digest": "6848ab296e16e801c7d92e73ef8211673d81c54770d0780050270cda6c8c78f9"}
 2026-10-30 17:37:08.725376+00 | A   | t           | t             | {"tool": "code.exec", "decision": "accepted_auto", "outcome_id": "01a18de3-0874-7850-b472-c5c6e9c7faf6", "proposal_digest": "ddb7c0e431ba22504e691e08ba32eb05462176607780890ed56acfadde4dfcf4"}
 2026-10-30 17:37:08.870986+00 | A   | t           | t             | {"tool": "edit_solus_entry", "decision": "accepted", "outcome_id": "01a18de3-0906-7fa9-8803-67d8802095ce", "proposal_digest": "3eaad0fbe389b14d718d1e5d8333ff4f7dced5270ba836de04297e7ed105aed5"}
 2026-10-30 17:37:08.950281+00 | A   | t           | t             | {"tool": "edit_solus_entry", "decision": "rejected", "outcome_id": "01a18de3-0955-792b-b8b9-b765f8e47e75", "proposal_digest": "47655db270dfc59b9ddf67fbb50ed51ddde99f323facf72ff2d4613399326dae"}
 2026-10-30 17:38:08.383222+00 | A   | t           | t             | {"tool": "edit_solus_entry", "decision": "expired", "outcome_id": "01a18de3-f17e-7e24-b051-2a2164ba5c7f", "proposal_digest": "a09cce4fab3f555a4ebcdcd04f76ada50c56803c254bc8198b4cc9a0c0b3ad0b"}
 2026-10-30 17:38:08.520466+00 | A   | t           | t             | {"tool": "edit_solus_entry", "decision": "stale", "outcome_id": "01a18de3-f207-7540-9acb-b421796ae111", "proposal_digest": "50b9384fcb867980bc6033b9fd3b13b5b45efe449252def350410a685ffd0673"}
 2026-10-30 17:38:08.604956+00 | A   | t           | t             | {"tool": "propose_part_definition", "decision": "rejected", "outcome_id": "01a18de3-f25c-7533-808e-385d4dc73e8d", "proposal_digest": "9b31e961c11cebfc966ba3691d4e41315732fefeaf0d668108c6773e0e80d4a1"}
 2026-10-30 17:38:08.697668+00 | A   | t           | t             | {"tool": "bench.import_cad_scene", "decision": "rejected", "outcome_id": "01a18de3-f2b7-7347-920a-863ea2a10ed3", "proposal_digest": "faaae159c64587d4ec720c6aef443476f328bfc640349108c86b4a2acd2a04d8"}
 2026-10-30 17:38:08.781116+00 | A   | t           | t             | {"tool": "set_hardware_config_field", "decision": "rejected", "outcome_id": "01a18de3-f30b-706c-9b35-a96457785e62", "proposal_digest": "1740cfc4140ff6c3c124be9558b74293430dd79d4d08614d3333edb17f09b3e3"}
 2026-10-30 17:38:08.861909+00 | A   | t           | t             | {"tool": "propose_part_definition", "decision": "rejected", "outcome_id": "01a18de3-f35d-7703-b7bb-58458f2b4ac3", "proposal_digest": "3d479934da39efee831d3072f14acb5eb93c0083596f6d8cfde873a13faf5175"}
 2026-10-30 17:38:08.942347+00 | A   | t           | t             | {"tool": "propose_part_definition", "decision": "rejected", "outcome_id": "01a18de3-f3ad-7866-85bc-ec95cfe4e38f", "proposal_digest": "3d479934da39efee831d3072f14acb5eb93c0083596f6d8cfde873a13faf5175"}
 2026-10-30 17:38:09.027355+00 | A   | t           | t             | {"tool": "machine.write_file", "decision": "stale", "outcome_id": "01a18de3-f402-71ea-9318-65f0c3a05663", "proposal_digest": "03d44074f1ea1aab585bc86fd02a9cf1e05e9903b764c676038122057ecd4e38"}
 2026-10-30 17:38:09.33918+00  | A   | t           | t             | {"tool": "onshape.set_variable", "decision": "stale", "outcome_id": "01a18de3-f53a-75f0-881f-16d91dba2226", "proposal_digest": "eb7d1ada2a2a9794729208e1d52dfb23fe883a72bc869f8ea5829a1ce4e5fa13"}
 2026-10-30 17:38:09.420556+00 | A   | t           | t             | {"tool": "code.exec", "decision": "accepted", "outcome_id": "01a18de3-f58c-7b4d-a23f-a0ec46772bb9", "proposal_digest": "b0e88e5809d87a3ec9023553e5fcefe94a42205b93b2f3e1dc8ae1ecd0fce61b"}
 2026-10-30 17:38:10.531116+00 | A   | t           | t             | {"tool": "machine.write_file", "decision": "accepted", "outcome_id": "01a18de3-f9e1-7106-b0ca-048cca87c52f", "proposal_digest": "3dc0331aee4fdc24831af3ab190013c93d0e8e8cc1c9d12312ae1c8661102be9"}
(15 rows)

$ outcome rows of P1 with no event (consent off)
                  id                  | who |       tool       | decision | data_collection_consent
--------------------------------------+-----+------------------+----------+-------------------------
 01a18de3-fadb-7ec2-9cf2-d2b79cc96802 | B   | edit_solus_entry | rejected | f
(1 row)

$ every event row maps to one outcome row (join on payload.outcome_id)
 events | matched_rows | distinct_outcomes | payload_equals_row
--------+--------------+-------------------+--------------------
     15 |           15 |                15 | t
(1 row)
```

`emit_event` logged one line per recording, 16 in all; B's:
`event=sol.proposal_outcome user=01a18de2-fda6-77c1-8fee-4856d4052ce8 team=01a18de2-fde0-732b-bd92-5a4ce925f207 project=01a18de2-fdf4-7406-8d09-afd0a8b15c6d consented=False`.

**The migration round trip** (against `solus_sol`, after the live legs; `p8_migration_roundtrip.txt`;
the credit_ledger indexes read with `pg_index`/`pg_get_indexdef`, and `\d credit_ledger` at the end):

```
== 2026-10-30T17:43:23.227Z state before the round trip
 alembic_version | proposal_outcomes_table
 a32100000001    | proposal_outcomes
 ix_credit_ledger_user_created    | CREATE INDEX ix_credit_ledger_user_created ON public.credit_ledger USING btree (user_id, created_at) | t
 (+ credit_ledger_pkey, ix_credit_ledger_extension_id, ix_credit_ledger_user_id, uq_credit_ledger_idempotency_key; 5 rows)
$ uv run alembic downgrade -1
(exit 0)
$ uv run alembic current
a32000000006 (mergepoint)
== 2026-10-30T17:43:24.355Z state after the downgrade
 alembic_version | proposal_outcomes_table
 a32000000006    |
 credit_ledger_pkey, ix_credit_ledger_extension_id, ix_credit_ledger_user_id, uq_credit_ledger_idempotency_key (4 rows: ix_credit_ledger_user_created dropped)
$ uv run alembic heads
a32100000001 (head)
$ uv run alembic upgrade head
(exit 0)
$ uv run alembic current
a32100000001 (head)
== 2026-10-30T17:43:25.802Z state after the upgrade
 alembic_version | proposal_outcomes_table
 a32100000001    | proposal_outcomes
 ix_credit_ledger_user_created    | CREATE INDEX ix_credit_ledger_user_created ON public.credit_ledger USING btree (user_id, created_at) | t
 (5 rows)
\d credit_ledger … Indexes: "credit_ledger_pkey" PRIMARY KEY, btree (id) / "ix_credit_ledger_extension_id" btree (extension_id) / "ix_credit_ledger_user_created" btree (user_id, created_at) / "ix_credit_ledger_user_id" btree (user_id) / "uq_credit_ledger_idempotency_key" UNIQUE, btree (idempotency_key) WHERE idempotency_key IS NOT NULL
\d proposal_outcomes … the 11 columns, the 4 indexes, ck_proposal_outcomes_decision, the 3 foreign keys; 0 rows
```

`alembic` printed no "Running …" lines (the repo's logging config); the version table and the
schema reads above are the evidence. The 30 outcome rows both runs wrote were dumped before the
downgrade (`--data-only --column-inserts`, 30 INSERTs) and put back after the upgrade
(`psql -v ON_ERROR_STOP=1`, exit 0): `select count(*)` 30, and the INSERT lines of a re-dump hash
identically (`b5db1bda…a22b` both, `p8_restore.txt`).

## Proxy tests (after the live run and the round trip)

The pytest guard (`ps -eo pid,args | grep -E "[u]v run pytest|[p]ython -m pytest|[p]ytest -q"`)
ran in its own call at 17:44:39Z and printed nothing (exit 1). One process, no `--cov`:

```
cd packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2 timeout 1800 uv run --frozen --no-sync pytest -q -rs -p no:cacheprovider tests/test_outcomes.py tests/test_change_signals.py tests/test_usage_turns.py tests/test_cost.py tests/test_gateway_purpose.py tests/test_gateway.py tests/test_pagination.py tests/test_turn_context.py tests/test_confirmations.py tests/test_models.py tests/test_schema_drift_warning.py tests/test_main.py tests/test_findings.py tests/test_vision_extract.py tests/test_render_view.py tests/test_read_document.py tests/test_firmware_recipe.py tests/test_sol_screen.py tests/test_label_motifs.py tests/test_annotate_edge.py tests/test_capability_hygiene.py tests/test_codec.py tests/test_complexity.py tests/test_context.py tests/test_edge_writer_ratchet.py tests/test_exec.py tests/test_external_providers.py tests/test_feeds.py tests/test_hardware_config.py tests/test_hosted_tool_build.py tests/test_model_call_sites.py tests/test_no_hardcoded_models.py tests/test_providers.py tests/test_seed_script.py tests/test_sol_runtime.py tests/test_solx01_hardening.py tests/test_token_estimator_ratchet.py tests/test_type_estimator.py tests/test_vendor_hygiene_api.py
706 passed in 272.01s (0:04:32)
```

- **The dispatch's list:** `test_outcomes.py`, `test_change_signals.py`, `test_usage_turns.py`,
  `test_cost.py` (the only `test_cost*`). `tests/test_sol_confirmations*.py` matches no file (as the
  P8 report says); the decide route's own pins are in `test_outcomes.py` and `test_confirmations.py`.
- **Fix-round pins:** `test_gateway_purpose.py` (the AST pin: `project_id=` on every gateway call
  under `agent/`), `test_turn_context.py`, `test_pagination.py`, `test_findings.py` (the shared
  `PageMeta`), the four round-1 sites (`test_vision_extract.py`, `test_render_view.py`,
  `test_read_document.py`, `test_firmware_recipe.py`, `test_sol_screen.py`) and `test_label_motifs.py`
  (N1), `test_gateway.py`, `test_models.py`, `test_schema_drift_warning.py`, `test_main.py`.
- **Ratchets:** every `tests/test_*.py` that says "ratchet" (20 files, `grep -l -i ratchet`).
- 0 failed, 0 skipped (`-rs` printed none). Log `acceptance/p8_proxy_pytest.log`; times and the
  `.coverage` md5 before and after (equal) in `p8_proxy_pytest.time`. The tree stayed clean.

## Deviations from the brief and observations

1. **Two runs; the first is superseded, not void.** Run 1 (17:29:26Z → 17:30:46Z, exit 0) passed every
   leg with 14 rows; the harness was then extended with two entity-key cards
   (`bench.import_cad_scene`, `set_hardware_config_field`) so a row could show a non-empty
   `entity_ids`, and run again. Run 1's evidence is in `acceptance/p8_run1/`; its 14 rows and 13
   events stay in `solus_sol` beside the final run's 16 and 15.
2. **The expired card's clock was set, not waited out**: `expires_at = now() - 1 minute` by SQL (the
   method of `test_outcomes.py`); `CONFIRMATION_TTL` is 30 minutes. The decide path's own
   `row.expires_at <= utcnow()` check made it `expired`.
3. **Scripted seams beyond the model text**, each recorded beside its call: the companion answers
   (`code.plan`/`code.exec` hand-written — the code fork's server needs its private venv; the
   schemas are the fork's own listing), one dry-run fault (the missing-preview case), one write that
   moved a source cursor (M5), the Onshape MockTransport and quota ledger (P5's method), the Brave
   discovery and fetcher (the tests' seam, `call_discovered`), and `render_view`'s picture
   (`Renderers.plan`/`render`: no offscreen render child, which P5 proved). The vision, extract, motif,
   recipe and narration calls themselves were real gateway calls answered by the scripted adapter.
4. **Four adapter-less calls got the scripted adapters by injection** (`u3-tool-calls` only, the
   phase that drives vision, extract, motif and the recipe's answer); every other adapter-less call
   would have met the refusing adapter (none did).
5. **Sources and the Onshape source, the CAD leaf and the motif candidate are seeded rows**, as
   P4/P5 seeded theirs: a sync would be a provider call. The fake arms, findings, notes, teams and
   memberships came through the production writers and routes.

Observations, for a ruling (none is a FAIL of the landed contract):

1. **`entity_ids` follows error filing's reference rule** (`_entity_ref`: the first of `entity_id`,
   `focus_entity_ids`, `robot_id`, `part_entity_id`, so at most one id). A gated call that names this
   project's robot as `robot_entity_id` (`set_hardware_config_field`, row `01a18de3-f30b-…`) records
   `entity_ids: []`, and the CAD leaf `bench.import_cad_scene` names as `source_entity_id` is not
   recorded beside its robot. Consistent with the P8 report's stated rule; it under-reports what a
   decision was about. Fix shape: the outcome's own key list (adding `robot_entity_id`,
   `source_entity_id`) and every verified id rather than the first.
2. **`stale` does not say which case it was.** The row (and its event) is `stale` for a diverged
   effect, a provider-quota refusal and a missing complete preview alike; only the decide response
   (`unauthorized` vs `unavailable`) and the decision turn's words differ. For outcomes as training
   data, the case is lost. Fix shape: a closed `stale_reason` beside `decision`, or three decisions.
3. **An expired card's decision turn reads "not applied (unauthorized) — ask again to see the current
   change"** (`_decision_summary`'s approve-path wording; pre-existing, outside P8): the next model
   is not told the card ran out of time.
4. **The `model call start` log line names the turn but not the project**; the ledger row does
   (attribution only). "Which project did this call bill?" is answerable from the ledger, not the log.
5. **Pacing.** The harness waited 59.22 s once, before A's third decision, to keep A under the
   20-a-minute cap: the gate counts each SOL message (`routers/sol.py:1038`), each model call
   (`orchestration/gateway.py:311`) and each decision (`routers/sol_confirmations.py:134`) in one
   window, and A's five turns and first two decisions had filled 18 of it.
6. **The planner's pick is visible in the anchors**: u1 anchored one twin (`name_match`) where the
   non-HARD u2 anchored both — the tie-break changed the scope, as P1-T1 designed.

## Not verified here

- **The 90-day `since` floor** against a row older than 90 days: every live row is minutes old, and
  writing an old row would be an invented record. `since=now-200d` returned all 16 rows (200);
  `test_outcomes.py::test_cross_team_isolation_404` (a 100-day-old row) and
  `test_pagination.py::test_since_floor_reads_naive_as_utc_and_never_reaches_past_the_window` pin it,
  both green in the slice.
- **A real model** proposing any of these cards, or writing a vision read, a page read, a label, a
  firmware file or a narration: every model text was the fixture's.
- **The code fork's own planner and sandboxed exec, a real Onshape call, a real Brave call, an
  offscreen render**: scripted at the seams in deviation 3.
- **The desktop** (no Electron here): P8 changed no desktop code beyond the regenerated schema.

## Left behind

- **In `solus_sol`.** Counts before run 1 → after the final run (and the restore):

  |                       | before        | after                                                                        |
  | --------------------- | ------------- | ---------------------------------------------------------------------------- |
  | alembic_version       | a32000000006  | a32100000001                                                                 |
  | users                 | 45            | 55                                                                           |
  | projects              | 48            | 54                                                                           |
  | memberships           | 91            | 111                                                                          |
  | `credit_ledger`       | 89            | 153                                                                          |
  | of which `usage`      | 48            | 102                                                                          |
  | `proposal_outcomes`   | 0             | 30 (run 1: 14, final: 16; dumped, dropped by the downgrade, put back)        |
  | data events           | 0             | 134 (28 `sol.proposal_outcome`: run 1 13, final 15)                          |
  | sources               | 34            | 48                                                                           |
  | findings              | 274           | 278                                                                          |
  | machines              | 3             | 5                                                                            |
  | entities / edges      | 1,958 / 2,336 | 2,166 / 2,604                                                                |
  | `.solus` entries      | 199           | 238                                                                          |
  | artifacts             | 35            | 39                                                                           |
  | conversations / turns | 26 / 83       | 46 / 189                                                                     |
  | tool confirmations    | 33            | 59 (all 26 of the runs decided: 6 approved, 12 rejected, 6 stale, 2 expired) |

  The run's projects are in the Seed table (run 1's are in `p8_run1/p8_accept_live_RUN1_result.json`).
  The workspaces and the artifact root lived in the process's temporary directory, removed at exit.

- **Not touched:** `solus`, `solus_sol_p1`, and every `solus_test_*` except `solus_test_d7fa72c2`
  (the proxy run truncates it, as designed).
- **Redis 6390** now: two `solus:research:<P2>:<question>` digests (run 1's and the final run's
  usage projects; the 7-day research cache). The scripted Onshape ledger keys were deleted by the
  harness (2 each run); the `freqcap` and `project_card` keys have expired. `solus-redis-1` was never
  touched.
- **Processes.** None started, stopped or killed; no `pkill`, no `pgrep -f`.
- **Files** (the git-ignored plan workspace): `acceptance/p8_accept_live.py` and every `acceptance/p8_*`
  file named under Run identity, `acceptance/p8_run1/`; `reports/`: this report. No tracked file
  changed.
