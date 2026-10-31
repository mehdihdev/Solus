# FINAL tally, SOLUSDEV-321 on 67ec28a2

HEAD `67ec28a2edddeae56c7776989d0f34c34b41c90b` (one commit on 55d8b175, test only: `packages/api/tests/test_code_content_software.py` +4). Logs are in `acceptance/tally_67ec28a2/`. The ps guard was run alone and was clear before every pytest. Only one pytest ran at a time, always with `-p no:cacheprovider`, never `--cov`, and with `SOLUS_TEST_DATABASE_URL=…/solus_test_d7fa72c2`.

## Verdict: PASS

The only failures are the 2 pre-existing code-fork tests.

## Commands and summary lines

| # | Command | Summary line |
|---|---|---|
| 1 | `uv run pytest -q -n auto -p no:cacheprovider --ignore=packages/api/tests/test_cad_store.py --ignore=packages/api/tests/test_live_access.py` (`pytest_main.log`, 08:24:33Z → 08:40:25Z) | `2 failed, 15720 passed, 31 skipped, 1 xfailed, 24 warnings in 951.37s (0:15:51)` |
| 2 | `uv run pytest -q -p no:cacheprovider packages/api/tests/test_cad_store.py packages/api/tests/test_live_access.py` | `68 passed in 16.35s` |
| 3 | the 12 ratchets in one process (`pytest_ratchets.log`) | `180 passed in 40.50s` |
| 4 | `cd packages/api && uv run alembic heads` | `a32100000001 (head)` |
| 5 | `uv run ruff check packages livebench integrations` | `All checks passed!` |

## Failures (run 1, the valid root run)

- **pre-existing:** `integrations/mcp/code/tests/test_code_process_tree.py::test_one_shot_command_cannot_leave_a_setsid_descendant` ("a setsid descendant outlived the command"). It also failed at P0-T1, 3b0bf0e2 and 55d8b175.
- **pre-existing:** `integrations/mcp/code/tests/test_code_sandbox.py::test_foreign_writable_covers_tmp_and_caches_but_not_the_workspace` ("~/.local/share/uv is no longer writable"). It also failed at P0-T1, 3b0bf0e2 and 55d8b175.
- `test_code_content_software.py::test_a_code_sync_recomputes_its_creators_expertise` (the 55d8b175 regression) now **passes**. The 5 regressions from 3b0bf0e2 also pass.
- The `test_live_streams` expired-token flake passed.

## Void root runs (kept for evidence, not counted)

1. **`pytest_main_VOID1.*` (07:39Z):** the controller's Stop-gate pytest (pid 2084744) started 3 s after it. I stopped my own run by its pid (2084134), waited the gate out, and re-ran.
2. **`pytest_main_run2_SIGINTIGN.*` (07:51Z) and `pytest_main_run3_SIGINTIGN.*` (08:08Z):** both `4 failed, 15718 passed`. The 2 extra failures were `test_dev_launcher.py::test_ctrl_c_lets_every_service_finish_a_graceful_stop` and `::test_ctrl_c_in_a_terminal_stops_the_whole_stack` ("launcher never exited" / "Ctrl+C did not stop it").
   - **The cause was my runner, not the code.** It started pytest with `&` inside a non-interactive script, and such jobs inherit SIGINT as ignored. Proof: `SigIgn 0x6` for an `&` job vs `0x4` without one. The tests deliver Ctrl+C (SIGINT), so the launcher under test could never see it.
   - The same file serially, without `&`: `42 passed in 17.77s` (`pytest_dev_launcher_serial.log`).
   - Run 1 used a runner with no `&` (uv child `SigIgn 0000000000000000`) and both tests passed. They also passed under `-n auto` at 3b0bf0e2 and 55d8b175.
   - No collision in runs 2–4: the monitor's Stop-gate check was silent and the logs contain 0 Deadlock/TRUNCATE lines.

## Ratchet pass lines (one process, 180 passed)

`test_edge_writer_ratchet` 3 · `test_capability_hygiene` 7 · `test_vendor_hygiene_api` 7 · `lb_vendor_hygiene_test` 4 · `test_sol_runtime::test_only_the_gated_dispatcher_reaches_registry_invoke` 1 · `test_tool_registry` 29 · `test_never_raises_groups` 10 · `test_fingerprint_eval` 60 · `toolkb/test_guard` 30 · `contracts/test_relations_contract` 8 · `test_no_hardcoded_models` 2 · `integrations/mcp/tests/test_vendor_hygiene.py` 19 — all PASSED.

## Tree

`git rev-parse HEAD` = 67ec28a2 throughout. `git status --short` is empty. `.coverage` md5 is `7571ebfd2af623167baf221f5af68076`, unchanged.

## Processes started and stopped

- Root runs:
  - VOID1: uv 2084061, pytest 2084134. I sent SIGTERM to 2084134 (mine); both exited.
  - run 2: uv 2198632.
  - run 3: uv 2292524.
  - run 4: runner 2387878, uv 2387880.
- Runs 2–4, the serial test_dev_launcher run, the ignored-files run, the ratchets, ruff and alembic all ran to completion.
- The controller's gate pytest (2084744/2084746/2084823) was waited out and not touched.
