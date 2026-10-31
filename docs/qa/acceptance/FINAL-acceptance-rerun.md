# FINAL acceptance re-run (R169): step 10 in full, plus the step 5 and step 7 sync legs, on 55d8b175

HEAD `55d8b175c461f894ef5800cc872be29243e54edb` before and after every leg (`acceptance/final_step5/tree.txt`, `acceptance/final_step7/tree.txt`).
`git status --short` was empty at the end, and `.coverage` md5 stayed `7571ebfd2af623167baf221f5af68076`. Run 2026-10-31 06:27Z → 07:00Z.
The 3b0bf0e2 evidence is kept unchanged under `acceptance/final_step5_3b0bf0e2/`, `final_step5_worker_sync_3b0bf0e2/` and `final_step7_3b0bf0e2/`. The re-run wrote fresh `final_step5/`, `final_step5_worker_sync/` and `final_step7/` with the same harness, `acceptance/final_accept_live.py step5|step7`, unchanged. It used the `final_head_harness/p6_accept_live.py` copy and in-process scripted adapters. Step 10 logs are in `acceptance/rerun_step10/`.

## Verdicts

**Step 10: FAILED.** 1 deterministic regression. It is the test-side twin of the R168 fix, a test that still expects the old behaviour. The other failures are the 2 named pre-existing ones. The 5 regressions from the 3b0bf0e2 run all pass now.
**Step 5 (P3 legs): VERIFIED.** The sync no longer creates a `member` entity.
**Step 7 (P6 legs): VERIFIED.** All legs pass and no `member` entity is created. One observation about the expertise leg is given below.

## Step 10 tallies (ps guard clear and alone before each pytest; one pytest at a time)

| Command | 55d8b175 (this run) | 3b0bf0e2 run |
|---|---|---|
| root `pytest -q -n auto -p no:cacheprovider --ignore=test_cad_store --ignore=test_live_access` | **3 failed, 15719 passed, 31 skipped, 1 xfailed, 887.44 s** | 8 failed, 15713 passed, 31 skipped, 1 xfailed |
| the two ignored files | 68 passed | 68 passed |
| livebench `tests` | 770 passed, 1 skipped | same |
| companion `tests` | 384 passed | same |
| kicad fork | 486 passed, 1 skipped, 1 xfailed | same |
| code fork | 2 failed (pre-existing), 1332 passed, 16 skipped | same |
| local fork | 251 passed | same |
| desktop `npx vitest run` | Files 1 failed (pre-existing `sentrySink.test.ts` import) / 571 passed; Tests 5960 passed | same |
| `typecheck:web` | exit 0 | same |
| `typecheck:node` | exit 2, only `sentrySink.ts(90,17) TS2307 '@sentry/electron/main'` (pre-existing) | same |
| `ruff check packages livebench integrations` | All checks passed | same |
| mypy `packages/api/src` / `livebench/src` / `packages/companion/src` | no issues in 545 / 90 / 17 files | same |
| `alembic heads` | `a32100000001 (head)` | same |
| ratchets, one process (`pytest_ratchets.log`) | 180 passed | 180 passed |

Ratchet pass lines: `test_edge_writer_ratchet` 3, `test_capability_hygiene` 7, `test_vendor_hygiene_api` 7, `lb_vendor_hygiene_test` 4, `test_sol_runtime::test_only_the_gated_dispatcher_reaches_registry_invoke` 1, `test_tool_registry` 29, `test_never_raises_groups` 10, `test_fingerprint_eval` 60, `toolkb/test_guard` 30, `contracts/test_relations_contract` 8, `test_no_hardcoded_models` 2, `integrations/mcp/tests/test_vendor_hygiene.py` 19. All PASSED. (The `ERROR solus.tools:registry.py` lines in that log are captured log output from the tests that make a tool raise. They are not test errors.)

### Failures, classified

- **REGRESSION (deterministic):** `packages/api/tests/test_code_content_software.py::test_a_code_sync_recomputes_its_creators_expertise`. It failed under `-n auto` and again serially (`pytest_main_failed_rerun.log`: 1 failed).
  - Error: `ValueError: not enough values to unpack (expected 1, got 0)` at `test_code_content_software.py:336`, on `(member,) = await db.scalars(select(GraphEntity).where(project_id == …, kind == "member"))`.
  - Cause: the test seeds a creator with no registered machine, runs a code sync, and expects a member node carrying the levels. The R168 fix (`agent/expertise.py` `store_expertise` no longer calls `ensure_member`) now correctly creates no member. So the test still pins the pre-fix behaviour.
  - The test file is unchanged since `fff1ac3f` and not touched in 3b0bf0e2..55d8b175. It passed at 3b0bf0e2 (it is not among that run's 8 failures).
  - Needed fix: test only. Register a machine (or call `ensure_member`) for the creator before the sync, or assert that no member and no stored levels exist. No code fix.
- **pre-existing:** `integrations/mcp/code/tests/test_code_process_tree.py::test_one_shot_command_cannot_leave_a_setsid_descendant` and `test_code_sandbox.py::test_foreign_writable_covers_tmp_and_caches_but_not_the_workspace`. They fail in the root run and in the code fork run, as at 3b0bf0e2 and P0-T1.
- **pre-existing:** the desktop `sentrySink.test.ts` import failure and the `typecheck:node` TS2307.
- **flake:** `test_live_streams::test_an_expired_token_ends_the_account_stream_at_reverification` passed under `-n auto` this time, so no serial re-run was needed.
- **The 5 regressions from 3b0bf0e2 are now passing in the root run:** `test_entities::test_filter_entities_by_type_and_domain`, `test_sources::test_disconnect_cascades_entities_by_default`, `test_sources::test_disconnect_can_retain_entities`, `test_sources::test_sync_lands_entities_and_relations`, and `test_integrations_stack::test_full_stack_ingest_fingerprint_link_check_graph`.

## Step 5 (P3 harness, three legs)

- inline: rc 0, `exit 0`, failure "". arq (worker python pid 1798790): rc 0. arq-worker-sync (worker python pid 1801201): rc 0.
- All three legs: 0 scripted calls, 0 refused, 0 `model call start` lines. No `arq:*` key left in `solus-redis-321`.
- `member` entities per project (dev copy `solus_sol`):

| Project | 55d8b175 | 3b0bf0e2 |
|---|---|---|
| fake-arm sketch project (inline 4th) | `01a190a5-4449…` 30 live entities, **0 member** | `01a19052-25ef…` 31 live entities, **1 member** |
| the other inline projects, arq and worker-sync | 94/12/11/94/94 live, 0 member | 0 member |

## Step 7 (P6 harness)

- rc 0, `exit 0`, `failed_legs []`. Scripted: answer 2, narration 2. 0 unscripted, refusing-adapter reaches 0, real adapter builds 0. ROS daemons 0/0 before and after.
- **No member entity is created anywhere in the run.** DB `members` count was 36 → 36 across the whole run. At 3b0bf0e2 it was 25 → 35.

| Measure | 55d8b175 | 3b0bf0e2 |
|---|---|---|
| `member_a` (leg 1) | `null` | a node created 05:11:33.558, after the sync |
| `member_e_after_sync_1/2`, `member_f`, `member_h_before_removal` (leg 6) | `null` | nodes |

- **Entity counts, leg `1-ros2-ws`, project p1 `01a190a8-ac88-765c-be9c-b2b8b20830a9` (local-folder sync of `ros2_ws`):**
  - before the sync: **20** live, 20 all (harness `before`, matched in the DB by `created_at < sync start`).
  - after: **31** live, 31 all. The sync created 9; the 2 resyncs created 0. Kinds: local_folder 1, package_requirement 4, python_code 1, ros_node 2, ros_topic 1, solus_config 1, solus_note 2, solus_section 7, solus_subsection 12. No member.
  - At 3b0bf0e2 the same leg went 20 → **32**. The extra entity was the `member` node; edges were 36 then, 35 now.
- **Entity counts, leg `6-expertise`, project p6 `01a190a8-ae29-717f-9cb9-fa5e6f8af7b1` (code-source sync):**
  - before sync_1: 39. After sync_1: 52 (+13 created). sync_2: +0. 55 at the end of the leg (bench_run, document and finding added later in the leg). No member.
  - At 3b0bf0e2 the project ended with 3 `member` nodes (e, f, h).
- **Observation (not a failure):** with no member node, leg 6 now stores no levels.
  - `prompt_stored` has `expertise null`, `register_lines []` (at 3b0bf0e2: `software (expert)` with a register line). `teammate_reads_levels` is `null`.
  - This is the intended R168 behaviour ("without one nothing is stored and the register stays unchanged"). But the P6 harness does not assert on it, so the stored-register path is no longer exercised end to end by this leg.

## Processes started and stopped (by pid only)

- Orchestrators (foreground or my own background task, each ran to completion): step5 and step7.
- Children run to completion: 1778903, 1798816, 1801266 (step 5); 1804970, 1804974, 1804980, 1806227 (step 7).
- ARQ workers, stopped by SIGTERM to the recorded python pid by the harness: 1798790 (uv 1798787) and 1801201 (uv 1801198), both rc 0 with `/proc` gone.
- Redis MONITOR `docker exec` clients ended by their handles.
- pytest, vitest, mypy, ruff and tsc ran to completion one at a time.
- The controller's Stop-gate pytest (pids 1772259/1772260/1772283) was waited out and not touched.
- No container was stopped or started. Nothing else was signalled.
