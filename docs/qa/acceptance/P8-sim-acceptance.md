# P8-T1 fixture acceptance (SOLUSDEV-322 plan §4 P8-T1): in process, per-checkout pytest DB, scripted adapters only, no provider, no simulator process

HEAD `6faba627ff27c465c26bf569aa25e4bf3d4c1ecd` before the run (`git status --short`: only the
untracked `docs/qa/REPO_STATE_ONBOARDING_BENCH_SIM_2026-11-08.md` and the new
`packages/api/tests/acceptance/`); HEAD after = the commit that lands this file and the harness
(recorded in the completion report as `head_sha`). Run 2026-11-09 19:41Z on this aarch64 host.

**Re-run after the review fixes** (scenario 9 cross-project isolation added; the xfail test now
records its row; the harness prints a TOTAL row): HEAD before `a03fa2450978433c01087de00680b925c18f2562`
(the harness commit), run 2026-11-09 19:52:05Z; HEAD after = the `P8-T1 review fixes` commit. The
command, table and totals below are from the **second review-fix re-run**: HEAD before
`c8a89cc2d92613c485057fb3467c36a325a597c2`, run 2026-11-09 19:55:50Z, adding the scenario-6b
fallback assertion (the MuJoCo and calculators rows of the same `sim.available` result are
`runnable_here: True`); HEAD after = the `P8-T1 review fixes — scenario 6b fallback` commit.

**P9-T1 re-run (scenario 6a fixed):** HEAD before `1e2130a8fc09b251d4bb5ce909e0a9e5fc9fcabc` plus
the uncommitted P9-T1 working tree (`gazebo_tools._consent_rows` / `IsaacTool._consent_rows` raise
`PreviewRefusal(refusal_sentence(plan))` for a refused dry run; the 6a xfail marker removed; one unit
test each in `test_gazebo_tools.py` / `test_isaac_tools.py`), run 2026-11-10 05:24:58Z; HEAD after =
the `the fork's unsupported_on sentence survives the park (scenario 6a)` commit. Its command, 6a rows
and TOTAL are in "Scenario 6a through the turn" below; the original P8 table is kept as recorded.

Harness: `packages/api/tests/acceptance/test_sim_acceptance.py` (committed; nested test dir with no
`__init__.py`, as `tests/sourcing/`). It runs against the conftest's per-checkout pytest database
(`SOLUS_TEST_DATABASE_URL` unset), with `tests/conftest.py`'s `app` / `client` / `engine` fixtures.
Every SOL turn is the production shape — `LlmRunner` over the real gateway (routing, metering,
`credit_ledger`, the `model call start` log line), `build_mode_dispatch` wrapping `build_dispatch`
with the real `request_confirmation` park, the real `decide_confirmation` for the one approval —
with one substitution: the provider adapter is `ScriptedModel`, which emits each scenario's
tool-call sequence and answers `ok` to anything else, and `gateway.build_adapter_registry` is
monkeypatched to raise for the whole module, so a real adapter cannot be built. Companions are
fakes in the shape of `tests/test_gazebo_tools.Native` / `tests/test_isaac_tools.Native` (a
`GazeboCompanion` per family; `IsaacCompanion` answering `read_state` for the sensors asked);
ownership is the `SessionsLedger`'s. Isaac cannot run here (x86_64 only): fixture-only.

## Command and result

```
cd packages/api && uv run pytest -q tests/acceptance/test_sim_acceptance.py -p no:cacheprovider -s
.........x.....
14 passed, 1 xfailed in 31.99s
wall 35.00 s            (/usr/bin/time; one pytest process; no other pytest running — pgrep clear)
```

Lint/type on the new file (from the repo root): `uv run ruff check packages/api/tests/acceptance/`
→ `All checks passed!`; `uv run ruff format --check` → `1 file already formatted`;
`uv run mypy packages/api/tests/acceptance/test_sim_acceptance.py` → `Success: no issues found in 1
source file`.

Ratchets, one process after the module (`tests/test_capability_hygiene.py test_vendor_hygiene_api.py
test_sol_runtime.py test_model_call_sites.py test_edge_writer_ratchet.py test_hosted_tool_build.py
test_kinds.py`): **75 passed in 36.60s** (wall 39.58 s) on the second re-run.

## Per-scenario table (pasted from the run's terminal summary)

(P8 run as recorded; the two `6a` rows were superseded by the P9-T1 re-run, pasted in "Scenario 6a
through the turn" below.)

Columns: `scripted` = calls the scripted adapter answered; `starts` = the gateway's `model call
start` log lines captured by `caplog`; `real` = starts − scripted (asserted 0 in every row, and
`build_adapter_registry` was forbidden); `ledger` = `credit_ledger` rows in the (per-test truncated)
table at the end of the scenario; `cards` = `tool_confirmations` rows.

```
P8-T1 sim acceptance
scenario                     scripted starts real ledger cards  wall s  note
----------------------------------------------------------------------------
1 no simulator                      4      4    0      4     0    0.20  rung 1 41.4 MPa stops; joint_trajectory → route gazebo not connected
2 gz 8.15.0                         6      6    0      7     1    1.34  Build 1 turn (9 calls), Guide 2 turns (4+4); card = sim.generate_model (8 rows, approved → 3 artifact kinds); 2 sim Runs on the fake arm; elbow = servo 3
2 ignition 6.16.0                   6      6    0      7     1    1.37  Build 1 turn (9 calls), Guide 2 turns (4+4); card = sim.generate_model (8 rows, approved → 3 artifact kinds); 2 sim Runs on the fake arm; elbow = servo 3
2 classic 11.15.1                   6      6    0      7     1    1.45  Build 1 turn (9 calls), Guide 2 turns (4+4); card = sim.generate_model (8 rows, approved → 3 artifact kinds); 2 sim Runs on the fake arm; elbow = servo 3
3 attached world                    4      4    0      4     3    0.39  Build: 3 cards (spawn, set_joint_targets, control); Guide: 3 refusals; stop refused in both, no card, fork never asked
4 save on owned                     2      2    0      2     2    0.17  2 cards on 2 owned sessions; neither file written
5 isaac do                          2      2    0      2     0    0.11  7 ops ok, 0 cards (fixture-only host)
5 isaac guide                       2      2    0      2     0    0.12  7 ops ok, 0 cards (fixture-only host)
6a classic save_world               4      4    0      4     0    0.15  preview: 'Classic 11 cannot write a running world back to its file.'; 0 cards; the turn's tool result said: 'The complete change preview is unavailable. Nothing was parked or applied; read the current design and try again.'
6a xfail (gap)                      4      4    0      4     0    0.09  strict xfail; tool result said: 'The complete change preview is unavailable. Nothing was parked or applied; read the current design and try again.'
6b Darwin/arm64                     2      2    0      2     0    0.17  isaac: Isaac runs only on Linux with an NVIDIA GPU.; fallback mujoco 3.11.0 runnable_here=True
6b Linux/x86_64                     2      2    0      2     0    0.10  isaac: No NVIDIA GPU was detected on the machine (nvidia-smi absent).; fallback mujoco 3.11.0 runnable_here=True
7 generation                        0      0    0      1     0    1.85  URDF 1936 B, MJCF 1255 B, gaps ['Fm2.limits', 'tip.mass']; frameless mate → Fm2.frame gap (the mate connector frame (attrs.mate_fra…); fixture: 2 mates no frame, 1 with frames
8 retention                         0      0    0      0     0    0.60  now=2026-11-09 03:17Z: 22 sim @40 d + 2 sim @5 d + 2 real @40 d → deleted 4, kept 20; second pass deleted 0
9 cross-project isolation           4      4    0      4     2    0.34  B: spawn(A's model) refused, stop(A's session) parked in B, 0 B writes, cards [('gazebo.save_world', 'A'), ('gazebo.stop', 'B')]; decide(A's card as B) → not_found, card still pending; run_store.record(B, A's run) → 404
----------------------------------------------------------------------------
TOTAL (15 rows)                    48     48    0     52    10    8.44
```

Model calls over the whole module (the TOTAL row, printed by the harness): **48 scripted, 48
`model call start` lines, 0 real** over 15 rows. That includes
`test_scenario_6a_the_turns_tool_result_carries_the_classic_sentence` (row `6a xfail (gap)` in the
P8 table, 4 calls; `6a through turn` and passing since P9-T1) and scenario 9 (4 calls). The
first pass of this document said "34": that was a miscount — its own table summed to 40, and the
xfail test's 4 calls were not recorded at all. Every
routed call was `provider=openai model=gpt-5.6-luna role=openai_trivial complexity=trivial
purpose=answer` (from the per-test captured log; the scripted adapter was registered under all
three provider names, so the router's choice never mattered). Ledger: one `usage` row per
scripted call, plus — in the scenarios whose person was provisioned through `/users/me`
(2 and 7) — one non-usage row written at provisioning, before any model call: scenario 7 makes 0
model calls and shows exactly that 1 row; scenario 2 shows 6 + 1.

## Verdict per scenario

| #   | Scenario (plan §4 P8-T1)                                                                                                                                                                                                                                                                                                                                           | Verdict                                                | What was seen                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | No simulator → rung-1 `simulate` answer, zero cards, only `simulate` called                                                                                                                                                                                                                                                                                        | **PASS, with one substitution (deviation 1)**          | Build turn: the model called `simulate` once (`question {subject_id, quantity: stress_mpa}` on a bracket at 15 % of yield) → `decision ran, rung 1, verdict stops`, reason "… with margin, the ladder stops here", value 41.4 MPa; tool list of the turn == `["simulate"]`; 0 cards. Second turn with `quantity: joint_trajectory` (the one quantity only rung 4 answers) → `decision route`, `route {rung 4, target gazebo, connected False, status "not connected"}`: the one line naming Gazebo (Isaac is the sibling target).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| 2   | ×3 families, owned Gazebo chain: probe → list_worlds → open_world → `sim.generate_model` (card: gap report, approve) → spawn → set_joint_targets → control step → run_routine → stop; zero cards for the sim ops in Guide AND Build; Build one turn, Guide two turns at `GUIDE_TOOL_CALLS = 8`; a sim Run exists; the elbow resolves to the real elbow's part node | **PASS** (gz 8.15.0, ignition 6.16.0, classic 11.15.1) | Build: one turn, 9 tool calls in one round + the closing round; all 8 sim ops `ok`; `open_world` result `owner: "sol"`; the only card is `sim.generate_model` (preview == `gap_report_rows(gap_report(gather(...)))`, 8 rows); each writer reached the companion exactly once, `spawn` carried `model_sha256` = the graph digest (never an entity id). `run_routine`'s result carried `run` (a Run id) and `run_reason: None`; the Run: `origin sim`, `robot_id` = the fake arm, `attrs.sim.family/version` = the family under test; manifest parts `[(servo 3's entity id, "demo/arm1/elbow")]`. The elbow: through `TelemetryPlumbing.ingest`, `demo/arm1/elbow` with source `gazebo` and the real bus packet `usb:FAKE-ARM-0001/3` with no source both resolve to servo 3's node. Approve: `decide_confirmation(approve=True)` → `status queued`, the enqueue recorded `("run_generate_sim_model", <project>, request)`; the job run inline (no ARQ worker in a pytest module) → `status generated`, model artifacts `urdf`, `mjcf`, `meshes` (3 kinds). Guide: `GUIDE_TOOL_CALLS == 8`; turn A probe, list_worlds, open_world, spawn (4); turn B set_joint_targets, control, run_routine, stop (4); all `ok`, still exactly 1 card (the Build one), a second distinct Run, ledger shows no running session after `stop`. Note: the generate card targets the CAD arm in the same project, while spawn/sweep run the fake arm's pre-seeded `simulation_model` — the robot that has a real bus identity (deviation 2). |
| 3   | Attached world: spawn, set_joint_targets, control each park a card in Build and refuse in Guide; `gazebo.stop` refuses                                                                                                                                                                                                                                             | **PASS**                                               | Build turn: `attach` → `owner: "user"`; spawn/set_joint_targets/control each `UNAUTHORIZED` "… waiting for the person to approve …" → 3 cards, each with a complete native preview; `stop` → `TOOL_ERROR` "… started by you …", no card. Guide turn: the same three → "Guide mode can explain …", no new card; `stop` refused the same way. The fake companion saw no `spawn`/`set_joint_targets`/`control`/`stop` write.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 4   | `gazebo.save_world` and `isaac.save_stage` card on owned sessions                                                                                                                                                                                                                                                                                                  | **PASS**                                               | One Build turn: `open_world` (owned) and `open_stage` (owned) `ok`; `save_world` and `save_stage` both "waiting for the person" → cards `["gazebo.save_world", "isaac.save_stage"]` with previews; neither companion saw a write; the ledger shows 1 owned gazebo + 1 owned isaac session.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 5   | Fixture Isaac: list_stages → open_stage → find_articulations → spawn_at → read_state (imu, contact) → run_routine sweep; zero cards                                                                                                                                                                                                                                | **PASS (fixture-only)** in Build and in Guide          | 7 ops (the plan's six plus `stop`, added so the Guide run can reopen the one owned stage per project) all `ok` in each mode; `read_state` asked for `/World/arm/imu` and `/World/arm/contact` and the result named exactly those two; `spawn_at` reached the fake with `model_sha256` = the graph digest; one `run_routine` write; 0 cards. Isaac itself never ran: this host is aarch64.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 6   | Classic `save_world` → `unsupported_on: classic 11`, SOL says so in one line; macOS and Linux-without-GPU machine attrs → honest Isaac rows + fallback sentence                                                                                                                                                                                                    | **6a PASS (P9-T1; was PARTIAL, deviation 3); 6b PASS (fallback = the runnable MuJoCo row; deviation 7)** | 6a: the companion's dry run answered the fork's own `Unsupported.wire()` (`{"ok": false, "code": "unsupported_on", "family": "classic", "version": "11", "reason": "classic 11 cannot write a running world back to its file"}`); `gazebo.save_world.preview(...)` raised exactly `Classic 11 cannot write a running world back to its file.` (one sentence, one period); 0 cards; the scripted reply was that sentence verbatim. **But through the turn** the tool result SOL received was `The complete change preview is unavailable. Nothing was parked or applied; read the current design and try again.` — the fork's reason was lost at the park (`confirmations._build_preview` catches the wrapper's `ToolException` as a generic preview failure; only a `PreviewRefusal` is carried). **Fixed in P9-T1**: `_consent_rows` now raises `PreviewRefusal(refusal_sentence(plan))` for a refused dry run; the re-run's tool result is `Classic 11 cannot write a running world back to its file.` in both 6a rows (pasted below), the xfail is gone and `test_scenario_6a_the_turns_tool_result_carries_the_classic_sentence` passes. 6b: machine `Darwin/arm64` with `nvidia-smi` → isaac `connected True, runnable_here False`, reason `Isaac runs only on Linux with an NVIDIA GPU.`; machine `Linux/x86_64` without → `No NVIDIA GPU was detected on the machine (nvidia-smi absent).`; both through a Guide turn calling `sim.available`; 0 cards. Fallback, asserted in the same result: `mujoco` row `runnable_here True, reason None` (mujoco 3.11.0) and `calculators` `runnable_here True`; the harness records `fallback mujoco 3.11.0 runnable_here=True` for both machines.                                                                                                                                                                                                                                                                                                                             |
| 7   | Generation on the two-link fixture → URDF + MJCF + gap report; the inference fixture → mate-frame gap                                                                                                                                                                                                                                                              | **PASS** (no model call)                               | `run_generate_sim_model` on the CAD arm (base ⟶ arm ⟶ tip, two revolute mates, `test_model_job.cad_arm`) → `status generated`; artifacts `urdf` (1936 B, `<robot …`), `mjcf` (1255 B, `<mujoco …`, mujoco 3.11.0 present), meshes `base/arm/tip.stl`; model gaps include `tip.mass` and `Fm2.limits`; the gap report lists `Fm1.frame`, `Fm2.frame` as properties. The arm with one frameless mate → gap `Fm2.frame` whose `set_in` names the mate connector frame. The Onshape inference fixtures: `assembly_definition.json` → 2 mates, both `frame is None` (the gap); `assembly_definition_mated_cs.json` → 1 mate with a frame.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 8   | Retention with a frozen clock                                                                                                                                                                                                                                                                                                                                      | **PASS**                                               | `now = 2026-11-09 03:17Z`; robot with 22 sim runs ended 40 d ago, 2 sim runs 5 d ago, 2 real (`origin live`) runs 40 d ago → `prune_sim_runs` deleted 4 (the 4 oldest sim payloads: artifact row soft-deleted, bytes gone, `payload_deleted_at` stamped), kept 20; the 18 newer old sim runs, both recent and both real runs stayed `live`; a second pass under the same clock deleted 0.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 9   | Cross-project isolation (review finding, not in plan §4 P8-T1): two teams/projects A and B on one ledger. A: open_world → spawn → run_routine (a sim Run) → save_world (parked in A). B's Build turn: `gazebo.spawn` with A's `simulation_model` id, `gazebo.stop` on A's ledger session; B decides A's card; `run_store.record(B, A's run)`                       | **PASS**                                               | B's spawn refused before any park (preview of A's model fails, no card); B's stop on A's session is a non-owned session to B, so it parked a card in **project B** (as `test_gazebo_tools.test_session_owned_in_another_project_cards` designs), never in A; B's companion received 0 non-dry-run calls and A's companion received no call during B's turn; A's ledger row unchanged `(SESSION, sol)`; cards = `[('gazebo.save_world', 'A'), ('gazebo.stop', 'B')]`; `decide_confirmation(A's card, project_id=B, user_id=B)` → `not_found`, card still `pending`, no save_world write; `run_store.record(B, A's run)` → APIError 404, `record(A, A's run)` returns it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

## Scenario 6a through the turn (P9-T1 re-run, 2026-11-10 05:24:58Z, PASS)

The P8 gap: `_consent_rows` raised a plain `ToolException` for a refused dry run, which
`confirmations._build_preview` swallowed as a generic preview failure. P9-T1 raises
`PreviewRefusal(refusal_sentence(plan), code=TOOL_ERROR)` instead (gazebo and the Isaac twin);
`PreviewRefusal` subclasses `ToolException`, so every `pytest.raises(ToolException)` case is
unchanged, and `_build_preview` carries `safe_message` into the park's refusal. `refusal_sentence`
(`sim_assets.py`) already redacts absolute paths to `<path>`, caps and ends the fork's reason with a
period, so the carried sentence has no host path (the Isaac unit test asserts
`Store <path> is a symlink.`).

Red first (the two source files stashed, the three tests run one process at a time): the gazebo
and Isaac unit tests failed with `ToolException: Classic 11 cannot write a running world back to its
file.` / `ToolException: Store <path> is a symlink.` (a `ToolException`, not a `PreviewRefusal`);
the acceptance test's red run collided with the Stop gate's concurrent full-suite pytest (TRUNCATE
deadlock) and is not claimed as a clean red.

Green, one pytest process at a time, no foreign pytest running (`pgrep` on the venv's pytest
binary clear before and after each, after the gate's three full-suite runs had exited):

```
cd packages/api && uv run pytest -q tests/acceptance/test_sim_acceptance.py -p no:cacheprovider -s
...............
6a classic save_world               4      4    0      4     0    0.26  preview: 'Classic 11 cannot write a running world back to its file.'; 0 cards; the turn's tool result said: 'Classic 11 cannot write a running world back to its file.'
6a through turn                     4      4    0      4     0    0.10  tool result said: 'Classic 11 cannot write a running world back to its file.'
----------------------------------------------------------------------------
TOTAL (15 rows)                    48     48    0     52    10    7.28
15 passed in 29.94s
wall 32.96 s

tests/test_dynamic_gate.py      7 passed in 3.62s
tests/test_sol_runtime.py      35 passed in 32.35s
tests/test_gazebo_tools.py     55 passed in 65.78s   (new: test_refused_dry_run_raises_preview_refusal_with_the_fork_sentence)
tests/test_isaac_tools.py      85 passed in 106.98s  (new: test_refused_dry_run_raises_preview_refusal_with_the_fork_sentence)
ratchets (capability_hygiene, vendor_hygiene_api, sol_runtime, model_call_sites,
          edge_writer_ratchet, hosted_tool_build, kinds)   75 passed in 34.33s
```

Model calls: 48 scripted, 48 `model call start` lines, **0 real** (unchanged from P8; the
`6a through turn` row now records its 4 calls as a passing test). `ruff check` / `ruff format
--check` on the five touched files: clean; `uv run mypy` (repo root, strict config) on the same
five: clean.

The P8 failing assertion, for the record (H9 hook's run of the pre-xfail harness, 2026-11-09 19:3xZ):

```
>       assert in_turn, saved.error
E       AssertionError: The complete change preview is unavailable. Nothing was parked or applied; read the current design and try again.
E       assert False
packages/api/tests/acceptance/test_sim_acceptance.py:1070: AssertionError
WARNING  solus.agent.confirmations:confirmations.py:215 preview failed for gazebo.save_world (complete preview required=True)
```

## Deviations (what the plan says vs what was done, and why)

1. **Scenario 1's question.** The plan's "will this arm lift 500 g at full reach?" has no rung-1
   calculator on this branch: rung 1 computes stress / yield fraction (`deterministic_mech`),
   forward kinematics and reach (`deterministic_robot`) and circuit quantities; torque/lift is a
   rung-3 MuJoCo job quantity (`peak_joint_torque_nm`). The scenario was therefore run on the one
   rung-1 strength question the fixtures carry (the bracket at 15 % of yield → `stops`, with
   margin), and the "one line naming Gazebo/Isaac" was reached with `joint_trajectory`, the
   quantity that routes to the rung-4 targets (`route gazebo … not connected`).
2. **Scenario 2's generate card and spawn target.** The card is real (`sim.generate_model` on the
   CAD arm; approved through `decide_confirmation`; the enqueued job run inline — no ARQ worker in
   a pytest module), but spawn / set_joint_targets / run_routine act on the fake arm's pre-seeded
   `simulation_model` (joint `elbow` = servo 3's own node), not on the freshly generated CAD model:
   the fake arm is the robot with a real bus identity (`usb:FAKE-ARM-0001/3`), which is what makes
   "the elbow resolves to the real elbow's part node" provable in the same project. In Guide the
   generate step is omitted from the chain (a static card: Guide refuses it before any park), as the
   plan's Guide split ("probe…spawn, then targets…stop") already implies.
3. **Scenario 6a was a gap** (resolved in P9-T1, above): the fork's `unsupported_on` sentence
   reached SOL from a direct `preview()` and from the wrapper's own result shapes, but not through
   a turn that parks the card. P8 did not change production code (its rule) and carried the claim
   as a strict xfail; P9-T1 made `_consent_rows` raise `PreviewRefusal` and un-marked the test.
4. **Scenario 5 adds `isaac.stop`** at the end of the chain so the Guide run can `open_stage` again
   (one owned Isaac session per project); the plan's six ops are unchanged otherwise.
5. **The model-call accounting is per test, from `caplog`** (the gateway's `model call start`
   lines) and the per-test-truncated `credit_ledger`; with `-s` those log lines are not in the
   terminal transcript, only in the counters above. `real` is starts − scripted, and a real adapter
   build was made impossible for the module.
6. **File length.** `test_sim_acceptance.py` is 1376 lines after formatting (eight scenarios, their
   fakes and seeding in one module, as `test_isaac_tools.py` 1428 / `test_sol_runtime.py` 1130 /
   `test_sim_runs.py` 1023 already are). Not split: a sibling helper module in a nested test dir
   without `__init__.py` would need an H9 pairing the task exempts only test modules from.
7. **Scenario 6b's "fallback sentence" is a row, not prose.** `sim.available` (production
   `agent/tools/sim_available.py`) writes no sentence pointing from Isaac to another simulator;
   the fallback it gives is structural — in the same result the `mujoco` row (and `calculators`)
   is `runnable_here: True` with no reason, and that is what the harness asserts. The SOL reply in
   the turn is scripted (`ok`), so asserting a scripted sentence would prove nothing about the
   product; whether the live model turns the rows into a "use MuJoCo instead" line is a live-run
   check, not done here. No production change made.

## Not done here (by the task's scope)

- No simulator process was started (Harmonic / Fortress / Classic smoke is P8-T2); no `solus_sim`
  DB, no `solus-redis-322`, no API on `:8030` were touched by this task — the harness is in process
  against the pytest database only.
- No real provider call anywhere: 48 scripted, 0 real (TOTAL row).
