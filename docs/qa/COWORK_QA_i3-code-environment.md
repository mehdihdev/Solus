# COWORK QA — INTEGRATIONS I3 · The Code environment (SOLUSDEV-250)

Self-sufficient end-to-end test plan. You have the running application and this file only.

## Required setup

- Everything from `COWORK_QA_i2-local-folders.md` (API on this machine, desktop in dev mode with
  the companion, forks materialised — this ticket adds the `code` server, so re-run
  `make mcp-forks` and check `integrations/mcp/code/.venv/bin/python3` exists), signed in as a
  verified project member with a folder linked on Home.
- Python 3.12 on PATH (`python3 --version`), `uv` optional (used when present).
- In the linked folder: `requirements.txt` containing `torch==2.3.0`, `gymnasium>=0.29`,
  `six==1.17.0`; `isaac/requirements.txt` containing `torch==2.1.0` and `numpy`;
  `tests/test_policy.py` with one failing assertion. Commit or just save — the folder watch
  re-scans on save.

## Flow 1 — dependencies land and the conflict is detected

1. Save the two requirement files. Expected within ~30 s: Workspace › the `local clone` node
   gains `requires` children — one `python_requirement` node per (file, package): four nodes.
2. Home › Connected accounts › **Software**: below "Local folder · <machine>" a **Code
   environment** row (mark `Py`). Expected status: "<python version> · no virtual environment ·
   5 requirements" and a second line "1 dependency conflict — split proposed".
3. **Details**. Expected: INTERPRETER lists your python3 (+ uv/conda "not found" honestly);
   REQUIREMENTS shows count 5 and the two files; CONFLICTS shows "'torch' is pinned differently
   across isaac/requirements.txt, requirements.txt — one environment cannot satisfy both" with
   pins `==2.1.0 · isaac/requirements.txt` and `==2.3.0 · requirements.txt`; PROPOSAL shows two
   environments (one per file), each with its requirements, and `split`.
4. Remove the conflict (make both pins `==2.3.0`), save. Expected within ~30 s: no conflict
   line; PROPOSAL says "Single environment" with all five requirements.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4

## Flow 2 — SOL proposes the split and every command is gated

Approval cards render only for turns sent from THIS desktop (a card parked by another client
shows as "waiting for your approval" text) — send every request below from the composer.

1. Restore the conflict. SOL (Do mode): "Set up my Python environment from the proposal."
   Expected: SOL calls `code.resolve_environment` (tool trace shows it), explains the split, and
   proposes `code.create_environment` — an **approval card** whose rows show the exact command
   (e.g. `python3 -m venv .venv` or `uv venv --python 3.12 .venv`) and `cwd .`. Nothing runs
   before you approve.
2. Approve. Expected: the card resolves; `.venv/` appears in the folder; the Code environment row
   now shows the venv path and "0 packages".
3. SOL proposes `code.install` for one environment. Expected: the card shows
   `.venv/bin/python -m pip install -- <packages…>` (or the uv equivalent) — every package name
   visible. To keep the run small, ask SOL to install only `six==1.17.0` first. Approve.
   Expected: `six` appears in the row's package count after the next probe (a `uv venv` has no
   pip; the probe reads packages through `uv pip list` in that case).
4. Reject a card. Expected: SOL reports the rejection; nothing ran; the folder is unchanged.
5. Guide mode: the same request. Expected: SOL explains and refuses to run commands, pointing
   at Do mode.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4 · [ ] 5

## Flow 3 — a failing test lands in Error logging

1. SOL (Do mode): "Run the tests." Expected: an approval card with
   `.venv/bin/python -m pytest -q -- tests`. Approve.
2. Expected: the tool result reports `exit_code 1` with the pytest tail in `stdout_tail`; ask
   "In one sentence: did the tests pass, and which test failed?" — SOL names
   `test_reward_is_positive` from the outcome it was handed (it never guesses).
3. Workspace › `.solus` (Project overview) › **Error logging** in the node panel. Expected: ONE
   new entry, author SOL, text starting with the exact command and "exited 1", followed by the
   pytest tail naming `test_reward_is_positive`.
4. Fix the test (`reward = 1`), re-run through SOL, approve. Expected: exit 0, NO new Error
   logging entry (success files nothing).

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4

## Edge cases and failure paths

- Ask SOL to install `-r requirements.txt` or `https://evil/pkg`: the card shows a `refused`
  row with the server's reason; approving runs nothing (`ok: false, exit_code: null`).
- Ask SOL to run `../outside.py` or `/etc/passwd`: refused (path is outside the linked folder).
- A script that sleeps 20 minutes: refused for `timeout_seconds` over 600, or killed at the
  timeout with the tail captured; the API stays responsive.
- Stop the companion: the row says "Solus companion is offline on this machine"; the modal still
  shows requirements/conflicts (graph facts) with probe sections "not probed"; SOL's `code.*`
  tools disappear from the tool list.
- A `requirements.txt` with 600 lines: the scan carries 500 and marks `truncated_dependencies`;
  the source's cursor shows it; nothing crashes.
- `environment.yml` with a `- pip:` block and `name=1.2` conda pins: both land; conda `=` becomes
  `==`.
- A teammate on another machine sees THEIR Code environment row (or none), never yours.

- [ ] all edge cases exercised

## Cross-feature checks

- The I2 folder flows still pass (link/unlink, Open in KiCad, edit re-syncs once).
- KiCad writes through SOL still show their diff (I4) — previews for `code.*` and
  `kicad.set_symbol_property` coexist.
- `run_checkers` in SOL now also returns `python_pin_conflict` warnings alongside the electrical
  rules when the scope includes requirement nodes.

- [ ] cross-feature checks
