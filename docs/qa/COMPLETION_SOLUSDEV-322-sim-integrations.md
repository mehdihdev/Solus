# Completion report: SOLUSDEV-322 sim integrations

Branch `SOLUSDEV-322-sim-integrations`. Base `33e3bc08` (`main` == `origin/main` at branch creation). Head of the P8 work: `43011a34` (P8-T4); the report and the Cowork QA file landed in `dde517af`. P9 (the fixes for what P8's live run and acceptance found, CLAUDE.md Phase 4) is `979274f4..f19378b6` (§1), and this P9 refresh of the handoff documents lands in one more commit on top. Work range: 71 commits `33e3bc08..43011a34`, 207 files changed, +29,666 / −1,769, plus the P9 commits. P10 (§17) merged `origin/main` `8bdf993e` (SOLUSDEV-319 drive, SOLUSDEV-323 onboarding) into the branch at `87d358d2` and reconciled the sim work with main's new conventions; the branch stood at 83 first-parent commits over `33e3bc08` at `e5266473` (P10-T1; 80 at `b1df3a31`, before the merge) — each handoff-record commit on top adds one.

Governing documents:

- Plan: `~/.claude/plans/pasted-content-id-1c37-sim-quirky-aurora.md`. It covers §0 recon, §1 design review, §1.3 answered questions Q1–Q4, §1.4 delegated decisions, §4 tasks, §6 verification and §7 report list.
- Recon: `docs/qa/RECON_SOLUSDEV-322-sim-integrations.md`.
- P8 evidence: `docs/qa/acceptance/P8-sim-acceptance.md` (T1), `P8-live-smoke.md` (T2), `P8-run-for-real.md` (T3), `P8-suites.md` (T4).
- P9 evidence: `docs/qa/acceptance/P9-T2-urdf-defect-A.md`, `P9-T3-classic-spawn-defect-B.md`, `P9-T4-family-hint-defect-E.md`, `P9-T5-bench-sources-gazebo-path-F1.md`; the P9 sections of `P8-sim-acceptance.md` (6a), `P8-live-smoke.md` (live rerun) and `P8-suites.md` (suite rerun).
- Docs read: DECISIONS.md ADR-014 (+2026-09-12 amendment), ADR-029, ADR-031, ADR-032; `docs/contracts/{action-gate,live-connection,telemetry-packet}.md`; `docs/api/{simulation,isaac-development,local-machine-actions,bench-runs}.md`; `docs/architecture/local-connections.md`; `integrations/mcp/{README,CLAUDE}.md`.
- Tier-1 docs written or amended on this branch (ADR-032):
  - new `docs/api/gazebo-integration.md` and `docs/schemas/sim-session.md`
  - `docs/api/{simulation,isaac-development,bench-runs,bench-scene,solus}.md`
  - `docs/contracts/action-gate.md` (step 1 per-call hook)
- Tier-2: DECISIONS.md changed once, in the dedicated commit `dc3db02a` (ADR-014 and ADR-041 amendments, both approved in chat 2026-11-10 against the concrete text; §13). No `packages/contracts/**`, CLAUDE.md or `.claude/**` edits.

What was built: SOL can now do the following.

- See which simulators the person's machine has (`sim.available`).
- Open the person's own Gazebo worlds (Classic 11, Ignition/Fortress, gz/Harmonic+) and Isaac stages.
- Spawn a Solus-generated model, drive joints, step time and run bounded routines. Inside a session Solus started, none of this needs a card. Inside a session the person started, every action cards.
- Map simulated joints onto the same part nodes as real hardware (`sim.map_to_parts`). Sim packets then resolve to the real part, and the window evaluator runs on sim sessions.
- Record sim Runs (`origin: "sim"`) with rung-4 facts. Pin a Run, and prune unpinned sim Run payloads after 30 days.
- Generate URDF and MJCF from the CAD scene with a gap report (`sim.generate_model`).

There is no simulation UI.

## 1. Per-phase summary and commits

| Phase | Tasks                                                                                                        | Commits (oldest → newest)                                                                                                                                                                                                                                                                                                            | Summary                                                                                                                                                                                                                                                                                                          |
| ----- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P0    | T1 recon, T2 conda envs                                                                                      | `dbd112c3`                                                                                                                                                                                                                                                                                                                           | RECON file and verified capability matrix; baselines (171 API + 137 fork/livebench tests, mypy 545 files clean). Classic and Fortress conda envs created by the orchestrator (`solus-gz-classic`, `solus-gz-fortress`).                                                                                          |
| P1    | T1 binaries, T2 `sim.available`, T3 ladder target                                                            | `82609c01`, `1cdb1931` (fix), `12c43fa5`, `dbff18bc` (fix), `86ed2471`                                                                                                                                                                                                                                                               | Companion probes `gz ign gazebo gzserver ngspice nvidia-smi` with per-binary argv (`VERSION_ARGV`), API mirror pinned equal; derived `attrs.simulators`; `sim.available`; `gazebo` rung-4 target (cost 3, fidelity 3); "connected == registered", route says `gate: "per call"`.                                 |
| P2    | T1 ledger, T2 per-call hook, T3 Isaac reclassified                                                           | `091a9ed3` (ledger, built before P1-T2 per plan §8), `dad834d3`, `81cc40e0`, `3c2240bd` (fix), `3642302f` (action-gate doc)                                                                                                                                                                                                          | `sim_session` ledger + `SessionsLedger`; `agent/dynamic_gate.needs_card` consulted at the three points; Isaac tools gated per call by ownership; Isaac no longer owned routines.                                                                                                                                 |
| P3    | T1 fork skeleton, T2 adapters, T3 server, T4 API wrappers, T5 telemetry, hardening                           | `22a7a1b0`, `0de59b60`, `492cec47`, `3c13ce12`, `43ba94b7`, `6501c3fb`, `82e8ad52`, `4e7abc37`, `cc7a162f`, `b6f32d04`, `ae16e9a3`, `72ba43aa`, `5f24b9e0`, `56bbff9c`, `d4c10c82`, `a46259ba`, `becaab11`, `4484a0c6`, `5311dd39`, `3ea19566`, `7a456f9f`, `7fd5d67f`, `8f848c98`, `fade90ea`, `d700f026`                           | New `integrations/mcp/gazebo/` fork (13 tools, three family adapters, owned process registry, chunked model store with manifest verification), owned `gazebo.*` API wrappers, Classic/Ignition/gz telemetry sources, `GazeboSimConfig{family, world, model}`, scrubbed simulator env and bounded companion text. |
| P4    | T1 Isaac fork actions, T2 API wrappers                                                                       | `6b2c1721` (package markers), `57e5ea73`, `55e7aebd` (fix), `695ff7fc`                                                                                                                                                                                                                                                               | Isaac `list_stages, open_stage, find_articulations, spawn_at, read_state, control, save_stage, put_asset`; sweep routine; probe reports `gui_attach: "unsupported"`.                                                                                                                                             |
| P5    | T1 map, T2 resolver, T3 evaluator, T4 runs                                                                   | `0eb49d8c`, `d851b3f6`, `c50925e9`, `e2e601ea` (fix), `c85dd2b7`, `f671a540`, `36fe4348`, `3c19d8b6` (fixes)                                                                                                                                                                                                                         | `sim.map_to_parts` → `attrs.sim_aliases`; resolver `source=` tag + GIN index; lazy robot adoption on sim sessions, `evidence.sim = true`; sim Runs, rung-4 facts, `POST /bench/runs/{id}/pin`; `sim_session.scene_name`.                                                                                         |
| P6    | T1 mate frames, T2 generation                                                                                | `044169d8`, `e227587e`, `75db2f25`, `4205c555`, `016018ad`, `37a677f4`, `40ee3f8a`, `dab76006`, `466085ce` (fix)                                                                                                                                                                                                                     | `matedCS` → `mates_with.attrs.mate_frame`; URDF writer, MJCF compile, ARQ `run_generate_sim_model`, `joint` entities, system-origin `simulation_model`, `sim.generate_model` card, CAD-refresh regeneration, rung-3 mapping from generated joints.                                                               |
| P7    | T1 prompt, T2 refusals, T3 retention                                                                         | `b3b75b8c`, `4cf27daf`, `4b6de094`, `578a62f5` (fix), `d17b25f5`, `8e22a23a` (fix), `6faba627` (type-clean tests)                                                                                                                                                                                                                    | `_SIMULATION_NOTE` in the system prompt (both modes, byte-stable); every sim refusal is one SOL-repeatable sentence; `prune_sim_runs` cron (03:17 daily).                                                                                                                                                        |
| P8    | T1 fixture acceptance, T2 live smoke, T3 run for real, T4 suites, T5 this report                             | `a03fa245`, `c8a89cc2`, `3b469432`, `fa370f38`, `10e8243a`, `7c58d765` (regression fix), `43011a34`                                                                                                                                                                                                                                  | See §6–§8.                                                                                                                                                                                                                                                                                                       |
| P9    | T1 scenario 6a, T2 defect A, T3 defect B, T4 defect E, T5 F1, T6 live rerun, T7 suites + handoff docs        | `979274f4` (B), `1cc71d4e` (E), `1e2130a8` (F1), `9bb1b108` (6a), `6022cc80` (A), `f19378b6` (live rerun, placeholder inertial + `*_IP` passthrough), plus the commit that carries this refresh (livebench mypy fix, P8-suites §P9 rerun, this report, the Cowork QA file)                                                           | Every defect P8 found that had an owner on this branch is fixed and proven: §6 (live), §8 (suites), §9 (6a), §10 (decisions), §11 "Fixed after P8 (P9)". Still open: D, F2, Fortress abseil, the Isaac row on aarch64.                                                                                           |
| P10   | Phase A merge of `origin/main` `8bdf993e`, B1 exposure-internal, B2 fixed prompt re-measured, B3 this record | `87d358d2` (merge, seven conflicts resolved, alembic merge revision `a32200000004`, `openapi.json`/`schema.ts` regenerated), `e5266473` (both sim allowlists `exposure: internal`, name check kept), `8d6aa964` (`FIXED_PROMPT_TOKENS` 15,000; caps 47,000/63,000; headroom 23,000/39,000), plus the commit that carries this record | See §17. Both bodies of work (SOLUSDEV-319 drive + SOLUSDEV-323 onboarding from main, SOLUSDEV-322 sim) are on one branch with one alembic head; the raw `gazebo.*`/`isaac.*` bridge specs are dropped by main's `exposure: internal` flag and by name.                                                          |

Review loop: every implementation task had separate python, security and spec reviewers. Every finding was fixed in a "review fixes" commit before the next task started. The fix commits are listed above.

## 2. Allowlist entries (ratified per plan §0 row 21; verbatim from the files at `43011a34`)

### 2.1 `integrations/mcp/gazebo/allowlist.yaml`: 13 entries

The plan's 12 ratified entries, plus `put_asset`, which was approved separately by Q1 (§2.3).

```yaml
server: gazebo
tools:
  - name: probe
    requires_confirmation: false
    timeout_seconds: 20
    reason: Read-only identity of the installed Gazebo families; launches nothing
  - name: list_worlds
    requires_confirmation: false
    timeout_seconds: 20
    reason: Read-only scan of the user's world files under SOLUS_SIM_ROOTS and running worlds
  - name: open_world
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 120
    reason: Starts one Solus-owned simulator process on the user's own world file
  - name: attach
    requires_confirmation: false
    timeout_seconds: 20
    reason: Read-only registration of a world the user started themselves
  - name: list_models
    requires_confirmation: false
    timeout_seconds: 20
    reason: Read-only models, links and joints of one registered world
  - name: spawn
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 60
    reason: Inserts a verified Solus-generated model into a registered world (per-call gate)
  - name: joint_state
    requires_confirmation: false
    timeout_seconds: 30
    reason: Read-only bounded window of joint positions and velocities
  - name: set_joint_targets
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 20
    reason: Sets bounded joint position targets inside a registered world (per-call gate)
  - name: control
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 60
    reason: Pauses, plays, steps or resets one registered world (per-call gate)
  - name: run_routine
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 90
    reason: Runs a finite bounded joint routine with readback (per-call gate)
  - name: stop
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 30
    reason: Stops only the simulator process this companion started (per-call gate)
  - name: save_world
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 30
    reason: writes the running world back into the user's own file
  - name: put_asset
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 30
    reason: stores one verified chunk of a Solus-generated model under .solus/sim/models
```

### 2.2 `integrations/mcp/isaac/allowlist.yaml`: 16 entries

The 8 entries that existed before this branch are unchanged. They are listed first, followed by the 8 added in P4-T1: the plan's 7 ratified entries plus `put_asset`, which was approved by Q1.

```yaml
server: isaac
tools:
  - name: probe
    requires_confirmation: false
    reason: Read-only installed runtime identity; does not launch Isaac
  - name: status
    requires_confirmation: false
    reason: Read-only status of this project-owned simulator
  - name: start
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 195
    reason: Starts one owned headless installed Isaac simulator
  - name: stop
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 20
    reason: Stops only this companion-owned simulator session
  - name: load_model
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 165
    reason: Replaces the owned scene with the validated graph-bound robot model
  - name: set_joint_limits
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 25
    reason: Changes exactly one graph-bound simulated joint limit
  - name: set_sensor_pose
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 25
    reason: Changes exactly one graph-bound contact sensor local pose
  - name: run_routine
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 55
    reason: Runs a finite joint_trajectory with explicit joint ranges and physical readback
  # SOLUSDEV-322 P4-T1 — the user's own stages. Gated PER CALL by the API-side ownership
  # ledger (docs/contracts/action-gate.md): no card inside a Solus-opened stage, a card
  # otherwise; only save_stage (a write into the user's own file) is statically gated.
  - name: list_stages
    requires_confirmation: false
    timeout_seconds: 20
    reason: Read-only scan of the USD stage files under SOLUS_SIM_ROOTS; launches nothing
  - name: open_stage
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 120
    reason: Starts one owned headless Isaac session on the user's own stage, opened in place
  - name: find_articulations
    requires_confirmation: false
    timeout_seconds: 30
    reason: Read-only list of every articulation root in the owned session's stage
  - name: spawn_at
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 165
    reason: Inserts a verified Solus-pushed model at a pose into the owned session's stage
  - name: read_state
    requires_confirmation: false
    timeout_seconds: 30
    reason: Read-only joint, IMU, contact and camera state of the owned session
  - name: control
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 60
    reason: Pauses, plays, steps or resets physics inside the owned session
  - name: save_stage
    requires_confirmation: true
    files_errors: true
    timeout_seconds: 60
    reason: saves the stage to the user's own file
  - name: put_asset
    requires_confirmation: false
    files_errors: true
    timeout_seconds: 30
    reason: Stores one manifest-verified chunk of a Solus-generated model under the workspace
```

The last entry of each file (`put_asset`) is the Q1-approved addition (§2.3).

### 2.3 The two Q1-approved `put_asset` entries (flagged separately)

`gazebo.put_asset` and `isaac.put_asset` are not part of the spec's ratified sets (12 Gazebo, 8 Isaac). Q1 approved them on 2026-11-08 ("chunked put via a fork tool, ungated, confined, sha256-verified before use"). Neither one is ever a SOL-visible tool: the API wrappers call them internally from `gazebo.spawn` / `isaac.spawn_at`. Each chunk is ≤ 64 KiB raw (`data_b64` ≤ 96 KiB). Promotion happens only when every file matches the manifest, and spawn refuses an unverified directory. Both entries are covered by the Reviewer 1 sign-off of 2026-11-10 (the reviewed tree includes `allowlist.yaml`; §12); Reviewer 2 is pending (integrations/mcp/CLAUDE.md rule 2, no single-reviewer shipping).

## 3. Gate changes (tool, before at `33e3bc08`, after at `43011a34`)

The per-call predicate is `agent/dynamic_gate.needs_card(tool, args)`. It returns static flag OR hook result OR hook error/timeout (5 s, fails closed). It is consulted in three places: `request_confirmation` step 1, the no-park fallback of `gate_tool_call`, and Guide's `mode_dispatch`.

Tests for the dispatch-level change (P2-T2, `tests/test_dynamic_gate.py`):

- `test_static_flag_wins_without_consulting_the_hook`
- `test_hook_false_dispatches_without_a_card_in_build_and_guide`
- `test_hook_true_parks_in_build_and_refuses_in_guide`
- `test_hook_exception_or_timeout_cards`
- `test_no_park_fallback_refuses_when_hook_says_card`
- `test_current_call_id_is_set_inside_the_dispatch_and_cleared_after`
- `test_guide_without_a_registry_keeps_the_static_semantics`

"Ledger" below means: no card iff `SessionsLedger.is_owned(project, provider, session_id)`. Otherwise the call parks a card in Build and is refused in Guide.

| Tool                                                                             | Before                                                                                                 | After                                                                                                             | Tests (file)                                                                                                                                                                                                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `isaac.probe`, `isaac.status`                                                    | ungated read                                                                                           | unchanged                                                                                                         | —                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `isaac.start`                                                                    | static card; Build owned routine                                                                       | hook False (owned by construction); success → `record_owned_start`                                                | `test_owned_session_runs_every_op_with_zero_cards_in_guide_and_build`, `test_start_records_the_requesting_user_on_the_ledger_row` (P2-T3, `test_isaac_tools.py`)                                                                                                                                                                                                                                                       |
| `isaac.stop`, `load_model`, `set_joint_limits`, `set_sensor_pose`, `run_routine` | static card; Build owned routines (`execution_policy._ISAAC`)                                          | ledger; no longer owned routines; `invoke` without a matching ticket re-asks its own hook, then re-plans          | `test_attached_or_unknown_session_cards_in_build_and_refuses_in_guide`, `test_forged_session_id_cards`, `test_ledger_read_failure_cards`, `test_invoke_without_ticket_still_replans_and_refuses_on_graph_change`, `test_a_parked_cards_leftover_ticket_does_not_poison_the_next_owned_call`, `test_invoke_without_ticket_refuses_when_its_own_hook_says_card`, `test_isaac_tools_are_no_longer_owned_routines` (P2-T3) |
| `isaac.list_stages`, `find_articulations`, `read_state`                          | — (new)                                                                                                | ungated reads                                                                                                     | `test_find_articulations_and_read_state_are_reads` (P4-T2)                                                                                                                                                                                                                                                                                                                                                             |
| `isaac.open_stage`                                                               | — (new)                                                                                                | hook False (owned by construction), ledger row with `scene_ref`                                                   | `test_open_stage_is_owned_by_construction_and_recorded` (P4-T2)                                                                                                                                                                                                                                                                                                                                                        |
| `isaac.spawn_at`, `isaac.control`                                                | — (new)                                                                                                | ledger                                                                                                            | `test_spawn_at_on_owned_stage_runs_without_a_card`, `test_spawn_at_pushes_missing_assets_in_chunks_then_spawns` (P4-T2)                                                                                                                                                                                                                                                                                                |
| `isaac.save_stage`                                                               | — (new)                                                                                                | static card                                                                                                       | `test_save_stage_cards_on_owned_stage` (P4-T2)                                                                                                                                                                                                                                                                                                                                                                         |
| `gazebo.probe`, `list_worlds`, `list_models`, `joint_state`                      | — (new)                                                                                                | ungated reads                                                                                                     | `test_reads_pass_parsed_arguments_through` (P3-T4, `test_gazebo_tools.py`)                                                                                                                                                                                                                                                                                                                                             |
| `gazebo.open_world`                                                              | — (new)                                                                                                | hook False (owned by construction); one owned world per project                                                   | `test_second_open_world_refuses_while_one_is_owned` (P3-T4)                                                                                                                                                                                                                                                                                                                                                            |
| `gazebo.attach`                                                                  | — (new)                                                                                                | ungated; records `owner="user"`; companion ownership claims ignored                                               | `test_companion_claims_of_ownership_are_ignored`, `test_ownership_claims_are_stripped_from_every_companion_result` (P3-T4)                                                                                                                                                                                                                                                                                             |
| `gazebo.spawn`, `set_joint_targets`, `control`, `run_routine`                    | — (new)                                                                                                | ledger                                                                                                            | `test_owned_world_runs_spawn_targets_step_routine_stop_with_zero_cards_in_both_modes`, `test_attached_world_spawn_targets_step_card_in_build_and_refuse_in_guide`, `test_session_owned_in_another_project_cards`, `test_ledger_read_failure_cards` (P3-T4)                                                                                                                                                             |
| `gazebo.stop`                                                                    | — (new)                                                                                                | ledger; on an attached world, refused in the tool and never carded                                                | `test_stop_on_attached_refuses_without_a_card`, `test_stop_does_not_end_another_projects_ledger_row` (P3-T4)                                                                                                                                                                                                                                                                                                           |
| `gazebo.save_world`                                                              | — (new)                                                                                                | static card                                                                                                       | `test_save_world_cards_on_an_owned_session` (P3-T4)                                                                                                                                                                                                                                                                                                                                                                    |
| `gazebo.put_asset`, `isaac.put_asset`                                            | — (new)                                                                                                | not SOL tools; called inside spawn / spawn_at                                                                     | `test_spawn_pushes_missing_assets_in_chunks_then_spawns` (P3-T4/P4-T2)                                                                                                                                                                                                                                                                                                                                                 |
| `sim.available`                                                                  | — (new)                                                                                                | ungated bounded read                                                                                              | `test_descriptor_is_an_ungated_bounded_read` (P1-T2)                                                                                                                                                                                                                                                                                                                                                                   |
| `sim.map_to_parts`                                                               | — (new)                                                                                                | static card, complete preview                                                                                     | `test_map_is_a_card_in_build_and_refused_in_guide` (P5-T1)                                                                                                                                                                                                                                                                                                                                                             |
| `sim.generate_model`                                                             | — (new)                                                                                                | static card, preview = gap report                                                                                 | `test_generate_is_a_card_whose_preview_is_the_gap_report` (P6-T2)                                                                                                                                                                                                                                                                                                                                                      |
| `simulate` rung-4 route                                                          | `requires_confirmation: True` / "asks the person first"; R115 forced a card via `routed_by_simulation` | `gate: "per call"`; the target tool's own gate decides; a target is connected when its routine tool is registered | `test_route_says_per_call_gate`, `test_a_target_connects_when_its_routine_tool_is_registered_regardless_of_gate`, `test_gazebo_ranks_before_isaac_on_cost_when_both_connected` (P1-T3)                                                                                                                                                                                                                                 |

Unchanged invariants: `confirmation_refusal`; `ToolRegistry.invoke` never raises; `registry.invoke` is called only from `runtime.build_dispatch` and `confirmations.decide_confirmation`; `routed_by_simulation` still guards the Onshape owned routines.

## 4. Ledger schema and migrations

Linear chain `a32100000001 → a32200000001 → a32200000002 → a32200000003`. P8-T3 verified it on `solus_sim`: `upgrade head → downgrade -3 → upgrade head`, one head. After the P10 merge of main (§17) the chain ends in the no-op merge revision `a32200000004` (`down_revision = ("a31900000003", "a32200000003")`), joining main's SOLUSDEV-319 head `a31900000002 → a31900000003` with this branch's `a32200000003`; `uv run alembic heads` prints `a32200000004 (head)` alone.

- `a32200000001_solusdev_322_sim_sessions.py` creates table `sim_session`:
  - columns: `id uuid pk`, `project_id uuid not null → projects.id ON DELETE CASCADE`, `provider varchar(32) not null`, `session_id varchar(128) not null`, `owner varchar(32) not null CHECK owner IN ('sol','user')` (constraint `sim_session_owner`), `started_by_call_id varchar(128)`, `scene_ref varchar(512)`, `started_at timestamptz not null`, `ended_at timestamptz`, `created_by uuid → users.id ON DELETE SET NULL`
  - indexes: unique partial `uq_sim_session_live (project_id, provider, session_id) WHERE ended_at IS NULL`, and `ix_sim_session_project_provider_ended (project_id, provider, ended_at)`
  - the plan specified a Postgres enum for `owner`; a CHECK constraint was used instead (§10)
- `a32200000002_solusdev_322_sim_aliases_index.py` adds a GIN `jsonb_path_ops` index `ix_graph_entity_sim_aliases` on `(attrs -> 'sim_aliases')`, partial `WHERE attrs ? 'sim_aliases'`.
- `a32200000003_solusdev_322_sim_session_scene_name.py` adds `sim_session.scene_name varchar(128)` (nullable). This came from a P5-T4 security review: a routine readback is keyed from the ledger's name for the scene, never from the companion.
- `a32200000004_solusdev_322_merge_main_heads.py` (P10) is the merge point of the two heads; `upgrade()` and `downgrade()` are `pass`.

Module `simulation/sessions_ledger.py` is vendor-free (provider is a string). Its methods are `record_owned_start`, `record_attached`, `is_owned` (true only for `owner='sol'` and `ended_at IS NULL`), `end_session`, `running`, `owned_running_count`. It raises `OwnedSessionRunningError` on a second live owned row. Schema doc: `docs/schemas/sim-session.md`.

## 5. For the Live Bench and Onboarding branches

These are the minimal edits to shared Live Bench files, verbatim from `git diff 33e3bc08..43011a34 -- <file>`. Commits that touched them: `7a456f9f`, `d851b3f6`, `c50925e9`, `c85dd2b7`, `d17b25f5`, `8e22a23a`. Smaller related edits without hunks here:

- `graph/telemetry.py`: `ingest(..., source=None)`.
- `main.py`: wires `part_robot_lookup(app.state.sessionmaker)`.
- `livebench/findings/{envelopes,window_evaluator}.py`: rad → part unit conversion, `evidence.sim`.
- `livebench/runs/analysis.py`.
- `livebench/runs/sim_run_retention.py` (new).
- `apps/desktop/src/renderer/src/lib/api/schema.ts`: regenerated.

### `packages/api/src/solus_api/livebench/sessions.py`

<!-- prettier-ignore-start -->
```diff
diff --git a/packages/api/src/solus_api/livebench/sessions.py b/packages/api/src/solus_api/livebench/sessions.py
index 3c05053a..11ab1bcf 100644
--- a/packages/api/src/solus_api/livebench/sessions.py
+++ b/packages/api/src/solus_api/livebench/sessions.py
@@ -97,6 +97,8 @@ class SessionView:
     robot_entity_id: UUID
     owner_user_id: UUID | None
     parts: Mapping[UUID, Mapping[str, datetime]]
+    #: SOLUSDEV-322 P5-T3: a simulated session — its findings say so in their evidence.
+    sim: bool = False
 
 
 class SessionEvaluator(Protocol):
@@ -189,6 +191,8 @@ class _Session:
     evaluator_task: asyncio.Task[None] | None = None
     #: robot sessions only: resolved part → channel → the event time the session first saw it
     parts: dict[UUID, dict[str, datetime]] = field(default_factory=dict)
+    #: sim sessions only (P5-T3): each resolved part looked up once → its robot, or None
+    tried_parts: dict[UUID, UUID | None] = field(default_factory=dict)
 
     def out(self, *, device_ids_kept: int) -> BenchSessionOut:
         if self.ended_at is not None:
@@ -246,10 +250,12 @@ class SessionManager:
         observer_factory: Callable[[], SessionObserver] | None = None,
         event_sink: Callable[[UUID, dict[str, Any]], None] | None = None,
         evaluator_factory: Callable[[SessionView], SessionEvaluator] | None = None,
+        robot_of_part: Callable[[UUID, UUID], Awaitable[UUID | None]] | None = None,
     ) -> None:
         self._plumbing = plumbing
         self._observer_factory = observer_factory
         self._evaluator_factory = evaluator_factory
+        self._robot_of_part = robot_of_part
         self._event_sink = event_sink
         self._cap = max_active_per_project
         self._device_ids_kept = device_ids_kept
@@ -364,7 +370,12 @@ class SessionManager:
             nonlocal observer
             if len(session.device_ids) < self._device_ids_kept:
                 session.device_ids.setdefault(packet.device_id)
-            result = await self._plumbing.ingest(project_id, packet, session_id=session.id)
+            result = await self._plumbing.ingest(
+                project_id,
+                packet,
+                session_id=session.id,
+                source=session.provider if session.mode == "sim" else None,
+            )
             if observer is not None and self._event_sink is not None:
                 try:
                     for event in observer.add(packet)[:128]:
@@ -376,11 +387,44 @@ class SessionManager:
                 session.unresolved += 1
             else:
                 session.ingested += 1
+                if session.mode == "sim":
+                    await self._adopt_robot(session, result.entity_id)
                 if session.robot_entity_id is not None:
                     self._note_part(session, result.entity_id, packet)
 
         return tap
 
+    async def _adopt_robot(self, session: _Session, part_id: UUID) -> None:
+        """P5-T3: a sim session binds to the robot of its first resolved part and starts the
+        evaluator; a part of a second robot un-binds it — one session judges one robot or none.
+        Each part is looked up once; a lookup that fails binds nothing."""
+        if self._robot_of_part is None or part_id in session.tried_parts:
+            return
+        session.tried_parts[part_id] = None
+        try:
+            robot = await self._robot_of_part(session.project_id, part_id)
+        except Exception:
+            logger.warning(
+                "robot lookup failed: project=%s session=%s", session.project_id, session.id
+            )
+            return
+        if robot is None:
+            return
+        session.tried_parts[part_id] = robot
+        robots = {found for found in session.tried_parts.values() if found is not None}
+        if len(robots) == 1 and session.robot_entity_id is None:
+            session.robot_entity_id = robot
+            session.evaluator_task = self._start_evaluator(session)
+        elif len(robots) > 1 and session.robot_entity_id is not None:
+            logger.warning(
+                "sim session streams parts of two robots; adopting none: project=%s session=%s",
+                session.project_id,
+                session.id,
+            )
+            session.robot_entity_id = None
+            await _stop_evaluator(session)
+            session.evaluator_task = None
+
     def _note_part(self, session: _Session, part_id: UUID, packet: TelemetryPacket) -> None:
         """Remember a resolved part's channels and the event time each began, bounded: at most
         `device_ids_kept` parts of `DEFAULT_CHANNELS_KEPT` channels (P2-T3)."""
@@ -403,6 +447,7 @@ class SessionManager:
             robot_entity_id=session.robot_entity_id,
             owner_user_id=session.owner_user_id,
             parts=session.parts,
+            sim=session.mode == "sim",
         )
         return self._evaluator_factory(view).start(view)
 
```
<!-- prettier-ignore-end -->

### `packages/api/src/solus_api/livebench/bench_router.py`

<!-- prettier-ignore-start -->
```diff
diff --git a/packages/api/src/solus_api/livebench/bench_router.py b/packages/api/src/solus_api/livebench/bench_router.py
index 237c62d0..91860592 100644
--- a/packages/api/src/solus_api/livebench/bench_router.py
+++ b/packages/api/src/solus_api/livebench/bench_router.py
@@ -251,6 +251,7 @@ MAX_SESSION_SECONDS = 3600.0
 MAX_WINDOW_SECONDS = 60.0
 _RUNNER_ABSENT = "livebench is not installed on this server"
 _SIM_PROVIDERS = {"mujoco", "gazebo", "mcap-replay"}
+_GAZEBO_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$"  # never option-shaped, never text-format syntax
 
 
 def _clean_topics(topics: list[str]) -> list[str]:
@@ -276,10 +277,16 @@ class MujocoSimConfig(BaseModel):
 
 
 class GazeboSimConfig(BaseModel):
+    """Manual `topics`, or (SOLUSDEV-322 P3-T5) a `world` + `model` whose joint_state stream the
+    livebench source derives for the installed (or named) Gazebo `family`."""
+
     model_config = ConfigDict(extra="forbid")
 
     provider: Literal["gazebo"]
-    topics: list[str] = Field(min_length=1, max_length=MAX_TOPICS)
+    topics: list[str] = Field(default_factory=list, max_length=MAX_TOPICS)
+    family: Literal["classic", "ignition", "gz"] | None = None
+    world: str | None = Field(default=None, pattern=_GAZEBO_NAME, max_length=64)
+    model: str | None = Field(default=None, pattern=_GAZEBO_NAME, max_length=64)
     window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)
 
     @field_validator("topics")
@@ -287,6 +294,14 @@ class GazeboSimConfig(BaseModel):
     def _bound_topics(cls, topics: list[str]) -> list[str]:
         return _clean_topics(topics)
 
+    @model_validator(mode="after")
+    def _topics_or_model(self) -> "GazeboSimConfig":
+        if (self.world is None) != (self.model is None):
+            raise ValueError("world and model go together")
+        if not self.topics and self.world is None:
+            raise ValueError("give topics, or a world and model")
+        return self
+
 
 class McapSimConfig(BaseModel):
     model_config = ConfigDict(extra="forbid")
@@ -479,11 +494,23 @@ def _session_opener(
 
         return open_mujoco, f"MuJoCo {cfg.scene_name}", None
     if isinstance(cfg, GazeboSimConfig):
+        gazebo_cfg = cfg
 
         async def open_gazebo() -> Any:
-            return await local.open_gazebo(list(cfg.topics), project_id=project_id)
+            return await local.open_gazebo(
+                list(gazebo_cfg.topics),
+                project_id=project_id,
+                family=gazebo_cfg.family,
+                world=gazebo_cfg.world,
+                model=gazebo_cfg.model,
+            )
 
-        return open_gazebo, f"Gazebo ({len(cfg.topics)} topic(s))", None
+        label = (
+            f"Gazebo {gazebo_cfg.world}/{gazebo_cfg.model}"
+            if gazebo_cfg.world
+            else f"Gazebo ({len(gazebo_cfg.topics)} topic(s))"
+        )
+        return open_gazebo, label, None
     if isinstance(cfg, McapSimConfig):
         mcap_path = _validated_mcap_path(settings, cfg.mcap_path)
 
```
<!-- prettier-ignore-end -->

### `packages/api/src/solus_api/graph/resolver.py`

<!-- prettier-ignore-start -->
```diff
diff --git a/packages/api/src/solus_api/graph/resolver.py b/packages/api/src/solus_api/graph/resolver.py
index 729d568c..7a4764c4 100644
--- a/packages/api/src/solus_api/graph/resolver.py
+++ b/packages/api/src/solus_api/graph/resolver.py
@@ -5,6 +5,14 @@ Ingestion attaches a packet to "the corresponding graph entity" by matching the
 docstring). Resolution is PROJECT-SCOPED: a device id known in one team's project never
 resolves under another's (§7 tenant isolation) — the query filters by `project_id`, which is
 derived from the authenticated request, never from the (untrusted) packet.
+
+SOLUSDEV-322 P5-T2 — the session-level `source` tag. A simulated joint and the real one must
+land on the SAME part node. A sim session's packets resolve with `source=<provider>` (the
+session's provider, set server-side, never by a packet): besides `external_ref`, a part answers
+when its `attrs.sim_aliases` (rows `{provider, device_id}`, written only by the gated mapping
+tool) holds `{provider: source, device_id}`. ONE query, an `external_ref` hit winning — no second
+round trip per unresolved 50 Hz packet. Without a source nothing changes: the query is the
+pre-322 one.
 """
 
 import time
@@ -12,26 +20,35 @@ from collections.abc import Callable
 from typing import Protocol
 from uuid import UUID
 
-from sqlalchemy import select
+from sqlalchemy import Select, and_, case, or_, select
+from sqlalchemy.dialects.postgresql import JSONB
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 
 from solus_api.graph.read_scope import current_scope
 from solus_api.models import GraphEntity
 
+ALIASES = "sim_aliases"
+
 
 class EntityResolver(Protocol):
-    """Maps a project-scoped device/topic id to a graph entity id, or None if unknown."""
+    """Maps a project-scoped device/topic id to a graph entity id, or None if unknown.
+    `source` is the session's provider tag; None resolves by `external_ref` alone."""
 
-    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None: ...
+    async def resolve(
+        self, project_id: UUID, device_id: str, *, source: str | None = None
+    ) -> UUID | None: ...
 
 
 class DictEntityResolver:
-    """In-memory resolver for tests/dev: an explicit `(project_id, device_id) → entity_id` map."""
+    """In-memory resolver for tests/dev: an explicit `(project_id, device_id) → entity_id` map.
+    Ignores `source`."""
 
     def __init__(self, mapping: dict[tuple[UUID, str], UUID]) -> None:
         self._mapping = dict(mapping)
 
-    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None:
+    async def resolve(
+        self, project_id: UUID, device_id: str, *, source: str | None = None
+    ) -> UUID | None:
         return self._mapping.get((project_id, device_id))
 
 
@@ -44,7 +61,8 @@ class CachingEntityResolver:
     cached, so a device that gets linked to an entity mid-stream attaches on
     the very next packet. Bounded: at `max_entries` the cache is cleared rather
     than grown (ponytail: full reset, LRU if churn ever matters — a reset costs
-    one TTL's worth of re-queries, not correctness)."""
+    one TTL's worth of re-queries, not correctness). Keyed on the source too: the
+    same device id under a real and a sim session are two entries."""
 
     def __init__(
         self,
@@ -58,15 +76,21 @@ class CachingEntityResolver:
         self._ttl = ttl_seconds
         self._max = max_entries
         self._clock = clock
-        self._cache: dict[tuple[UUID, str], tuple[float, UUID]] = {}
+        self._cache: dict[tuple[UUID, str | None, str], tuple[float, UUID]] = {}
 
-    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None:
-        key = (project_id, device_id)
+    async def resolve(
+        self, project_id: UUID, device_id: str, *, source: str | None = None
+    ) -> UUID | None:
+        key = (project_id, source, device_id)
         hit = self._cache.get(key)
         now = self._clock()
         if hit is not None and now - hit[0] < self._ttl:
             return hit[1]
-        entity_id = await self._inner.resolve(project_id, device_id)
+        # `source=` only when set: pre-322 resolvers (and test fakes) take two positionals.
+        if source is None:
+            entity_id = await self._inner.resolve(project_id, device_id)
+        else:
+            entity_id = await self._inner.resolve(project_id, device_id, source=source)
         if entity_id is not None:
             if len(self._cache) >= self._max:
                 self._cache.clear()
@@ -77,23 +101,38 @@ class CachingEntityResolver:
 
 
 class DbEntityResolver:
-    """Resolves against `graph_entity` by `external_ref`, scoped to the given project and to
-    live (non-soft-deleted) rows. Returns the matching entity id, or None."""
+    """Resolves against `graph_entity` by `external_ref` — and, under a `source`, by a matching
+    `attrs.sim_aliases` row — scoped to the given project and to live (non-soft-deleted) rows.
+    Returns the matching entity id, or None."""
 
     def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
         self._sessionmaker = sessionmaker
 
-    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None:
-        stmt = (
-            select(GraphEntity.id)
-            .where(
-                GraphEntity.project_id == project_id,
-                current_scope(project_id).entity_predicate(),
-                GraphEntity.external_ref == device_id,
-                GraphEntity.deleted_at.is_(None),
-            )
-            .limit(1)
+    async def resolve(
+        self, project_id: UUID, device_id: str, *, source: str | None = None
+    ) -> UUID | None:
+        stmt = select(GraphEntity.id).where(
+            GraphEntity.project_id == project_id,
+            current_scope(project_id).entity_predicate(),
+            GraphEntity.deleted_at.is_(None),
         )
+        if source is None:
+            stmt = stmt.where(GraphEntity.external_ref == device_id)
+        else:
+            stmt = _with_alias(stmt, device_id, source)
         async with self._sessionmaker() as session:
-            entity_id: UUID | None = await session.scalar(stmt)
+            entity_id: UUID | None = await session.scalar(stmt.limit(1))
             return entity_id
+
+
+def _with_alias(stmt: Select[tuple[UUID]], device_id: str, source: str) -> Select[tuple[UUID]]:
+    """`external_ref = :d OR attrs -> 'sim_aliases' @> [{provider: :s, device_id: :d}]`, the
+    `external_ref` hit first. `->` (not subscripting) so the partial GIN index on that expression
+    (`a32200000002`) serves the containment; `attrs ? 'sim_aliases'` is the index's predicate."""
+    by_ref = GraphEntity.external_ref == device_id
+    aliases = GraphEntity.attrs.op("->", return_type=JSONB)(ALIASES)
+    by_alias = and_(
+        GraphEntity.attrs.has_key(ALIASES),
+        aliases.contains([{"provider": source, "device_id": device_id}]),
+    )
+    return stmt.where(or_(by_ref, by_alias)).order_by(case((by_ref, 0), else_=1))
```
<!-- prettier-ignore-end -->

### `packages/api/src/solus_api/livebench/runs/models.py`

<!-- prettier-ignore-start -->
```diff
diff --git a/packages/api/src/solus_api/livebench/runs/models.py b/packages/api/src/solus_api/livebench/runs/models.py
index f0823948..4ef2bd7f 100644
--- a/packages/api/src/solus_api/livebench/runs/models.py
+++ b/packages/api/src/solus_api/livebench/runs/models.py
@@ -1,7 +1,7 @@
 """Strict portable recording format. Imported origins are claims, never live proof."""
 
 from datetime import datetime
-from typing import Annotated, Literal, Self
+from typing import Annotated, Any, Literal, Self
 from uuid import UUID
 
 from pydantic import (
@@ -76,6 +76,19 @@ class RunFinding(StrictModel):
     last_seen: AwareDatetime
 
 
+class SimRunInfo(StrictModel):
+    """What a simulated run (`origin="sim"`, SOLUSDEV-322 P5-T4) was run with: the provider,
+    its family and version when the companion said, the graph model's asset hash, the world or
+    stage it ran in (root-relative, never an absolute path) and the routine as requested."""
+
+    provider: Text
+    family: Text | None = None
+    version: Text | None = None
+    model_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
+    scene_ref: Text | None = None
+    routine: Annotated[dict[str, Any], Field(max_length=64)] = Field(default_factory=dict)
+
+
 class RunManifest(StrictModel):
     schema_version: Literal[1] = 1
     robot_id: UUID
@@ -86,6 +99,8 @@ class RunManifest(StrictModel):
     snapshots: list[RevisionSnapshot] = Field(default_factory=list, max_length=256)
     # Optional, so every manifest recorded before findings existed still loads.
     findings: list[RunFinding] = Field(default_factory=list, max_length=MAX_RUN_FINDINGS)
+    # Optional: only a simulated run carries it.
+    sim: SimRunInfo | None = None
 
     @model_validator(mode="after")
     def unique_parts(self) -> Self:
@@ -119,7 +134,7 @@ class RunSummary(StrictModel):
     robot_id: UUID
     session_id: UUID | None = None
     name: Annotated[str, Field(min_length=1, max_length=120)]
-    origin: Literal["live", "recorded", "synthetic"]
+    origin: Literal["live", "recorded", "synthetic", "sim"]
     status: Literal["running", "completed", "truncated", "interrupted"]
     started_at: datetime
     ended_at: datetime | None = None
```
<!-- prettier-ignore-end -->

### `packages/api/src/solus_api/livebench/runs/store.py`

<!-- prettier-ignore-start -->
```diff
diff --git a/packages/api/src/solus_api/livebench/runs/store.py b/packages/api/src/solus_api/livebench/runs/store.py
index a034856b..6c0ac5c1 100644
--- a/packages/api/src/solus_api/livebench/runs/store.py
+++ b/packages/api/src/solus_api/livebench/runs/store.py
@@ -38,16 +38,26 @@ async def record(
 
 
 class RunRead(RunSummary):
-    """A run as the routes and the retrieval tool read it: its summary, and whether it is its
-    robot's baseline. The flag is the record's own attr (`POST …/baseline`), never part of a
-    saved summary (`save` and `new_record` leave it out)."""
+    """A run as the routes and the retrieval tool read it: its summary, whether it is its
+    robot's baseline and whether it is pinned. The flags are the record's own attrs
+    (`POST …/baseline`, `POST …/pin`), never part of a saved summary (`save` and `new_record`
+    leave them out)."""
 
     baseline: bool = False
+    pinned: bool = False
+
+
+#: The read-side flags a saved summary never carries.
+FLAGS: set[str] = {"baseline", "pinned"}
 
 
 def summary(entity: GraphEntity) -> RunRead:
     return RunRead.model_validate(
-        {**entity.attrs["summary"], "baseline": entity.attrs.get("baseline") is True}
+        {
+            **entity.attrs["summary"],
+            "baseline": entity.attrs.get("baseline") is True,
+            "pinned": entity.attrs.get("pinned") is True,
+        }
     )
 
 
@@ -126,9 +136,18 @@ async def save(
         )
         info.artifact_id = artifact.id
     entity.attrs = {
-        "summary": info.model_dump(mode="json", exclude={"baseline"}),
+        "summary": info.model_dump(mode="json", exclude=FLAGS),
         "checkpoint_id": str(artifact.id),
         "created_by": str(user_id),
+        # SOLUSDEV-322 P5-T4: what retention (P7-T3) reads without loading the manifest.
+        **(
+            {
+                "sim": manifest.sim.model_dump(mode="json") if manifest.sim else None,
+                "findings_linked": bool(manifest.findings),
+            }
+            if final
+            else {}
+        ),
     }
     if old_id:
         old = await session.scalar(
@@ -189,7 +208,7 @@ def new_record(project_id: UUID, info: RunSummary, user_id: UUID) -> GraphEntity
         origin="system",
         name=info.name,
         attrs={
-            "summary": info.model_dump(mode="json", exclude={"baseline"}),
+            "summary": info.model_dump(mode="json", exclude=FLAGS),
             "created_by": str(user_id),
         },
     )
```
<!-- prettier-ignore-end -->

### `packages/api/src/solus_api/livebench/runs/router.py`

<!-- prettier-ignore-start -->
```diff
diff --git a/packages/api/src/solus_api/livebench/runs/router.py b/packages/api/src/solus_api/livebench/runs/router.py
index bf9fbf5c..b95b0991 100644
--- a/packages/api/src/solus_api/livebench/runs/router.py
+++ b/packages/api/src/solus_api/livebench/runs/router.py
@@ -373,6 +373,22 @@ async def mark_baseline(ctx: ProjectCtx, session: SessionDep, run_id: uuid.UUID)
     return envelope(store.summary(entity).model_dump(mode="json"))  # read again: now the baseline
 
 
+@router.post("/{run_id}/pin")
+async def pin_run(ctx: ProjectCtx, session: SessionDep, run_id: uuid.UUID) -> dict[str, Any]:
+    """Keep the run (SOLUSDEV-322 P5-T4): `attrs.pinned` is what sim-run retention reads to
+    leave a run alone. Idempotent; a run still running is refused as for `baseline`, since its
+    next checkpoint rewrites the whole record and the mark with it."""
+    require_role(ctx, Role.MEMBER)
+    await lock_project(session, ctx.project.id)
+    entity = await store.record(session, ctx.project.id, run_id)
+    if store.summary(entity).status == "running":
+        raise APIError(409, "run_active", "Stop the run before pinning it")
+    entity.attrs = {**entity.attrs, "pinned": True}
+    await session.commit()
+    logger.info("run pinned project=%s run=%s", ctx.project.id, run_id)
+    return envelope(store.summary(entity).model_dump(mode="json"))
+
+
 @router.get("/{run_id}/findings")
 async def get_findings(
     ctx: ProjectCtx, session: SessionDep, request: Request, run_id: uuid.UUID
```
<!-- prettier-ignore-end -->

### `apps/desktop/src/renderer/src/features/bench/runs/runDecoders.ts`

<!-- prettier-ignore-start -->
```diff
diff --git a/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.ts b/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.ts
index c62de2c1..62a12183 100644
--- a/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.ts
+++ b/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.ts
@@ -67,14 +67,15 @@ const summaryCheck = shape({
   robot_id: uuid,
   session_id: nullable(uuid),
   name: text(120),
-  origin: oneOf('live', 'recorded', 'synthetic'),
+  origin: oneOf('live', 'recorded', 'synthetic', 'sim'),
   status: oneOf('running', 'completed', 'truncated', 'interrupted'),
   started_at: timestamp,
   ended_at: nullable(timestamp),
   packet_count: count(10000),
   drop_count: count(),
   artifact_id: nullable(uuid),
-  baseline: optional(oneOf(true, false))
+  baseline: optional(oneOf(true, false)),
+  pinned: optional(oneOf(true, false))
 })
 const dictionary =
   (max: number, keyCheck: Check, valueCheck: Check, min = 0): Check =>
@@ -179,7 +180,7 @@ const detailCheck: Check = (value) =>
   value.summary.robot_id === value.manifest.robot_id
 const scalar: Check = (value) => value === null || finite(value) || text(512, 0)(value)
 const findingFields = {
-  evidence_origin: optional(oneOf('live', 'recorded', 'synthetic')),
+  evidence_origin: optional(oneOf('live', 'recorded', 'synthetic', 'sim')),
   findings: array(
     256,
     shape({
```
<!-- prettier-ignore-end -->

### `apps/desktop/src/renderer/src/features/bench/runs/runsApi.ts`

<!-- prettier-ignore-start -->
```diff
diff --git a/apps/desktop/src/renderer/src/features/bench/runs/runsApi.ts b/apps/desktop/src/renderer/src/features/bench/runs/runsApi.ts
index c00ecf82..3ffa213f 100644
--- a/apps/desktop/src/renderer/src/features/bench/runs/runsApi.ts
+++ b/apps/desktop/src/renderer/src/features/bench/runs/runsApi.ts
@@ -12,7 +12,7 @@ export interface RunSummary {
   robot_id: string
   session_id: string | null
   name: string
-  origin: 'live' | 'recorded' | 'synthetic'
+  origin: 'live' | 'recorded' | 'synthetic' | 'sim'
   status: 'running' | 'completed' | 'truncated' | 'interrupted'
   started_at: string
   ended_at: string | null
@@ -21,6 +21,7 @@ export interface RunSummary {
   artifact_id: string | null
   /** True for the run its robot's envelopes are learned from; start/import/live-stop omit it. */
   baseline?: boolean
+  pinned?: boolean
 }
 export interface RunPacket {
   device_id: string
@@ -84,7 +85,7 @@ export interface RunDetail {
   manifest: RunManifest
 }
 export interface RunFindings {
-  evidence_origin?: 'live' | 'recorded' | 'synthetic'
+  evidence_origin?: 'live' | 'recorded' | 'synthetic' | 'sim'
   findings: Array<{
     entity_id: string
     headline: string
```
<!-- prettier-ignore-end -->

### `apps/desktop/src/renderer/src/features/bench/runs/runDecoders.test.ts`

<!-- prettier-ignore-start -->
```diff
diff --git a/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.test.ts b/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.test.ts
index 9d6831ba..41433069 100644
--- a/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.test.ts
+++ b/apps/desktop/src/renderer/src/features/bench/runs/runDecoders.test.ts
@@ -126,6 +126,15 @@ it('keeps the baseline flag a list row and a detail summary carry', async () =>
   vi.mocked(api.request).mockResolvedValue({ summary: marked, manifest })
   expect((await getRun('p', id)).summary).toEqual(marked)
 })
+it('reads a simulated run (origin sim) and its pinned flag', async () => {
+  const sim = { ...summary, origin: 'sim', pinned: true }
+  vi.mocked(api.request).mockResolvedValue({ runs: [sim], next_cursor: null })
+  expect((await listRuns('p')).runs[0]).toEqual(sim)
+  vi.mocked(api.request).mockResolvedValue({ summary: sim, manifest })
+  expect((await getRun('p', id)).summary).toEqual(sim)
+  vi.mocked(api.request).mockResolvedValue({ runs: [{ ...summary, origin: 'dream' }], next_cursor: null })
+  await expect(listRuns('p')).rejects.toThrow()
+})
 it('reads a summary without a baseline key, as start, import and a live stop send it', async () => {
   vi.mocked(api.request).mockResolvedValue(summary)
   const started = await startRun('p', { robot_id: id, session_id: id, name: 'Run' })
```
<!-- prettier-ignore-end -->

Notes for those branches:

- The desktop needed six edits rather than the plan's four. `shape()` rejects unknown keys, so `pinned` had to be added as well.
- `RunSummary` is not in the OpenAPI, because the runs router returns `dict[str, Any]` envelopes (P8-T3 F2). Typing those responses is a route change for the Live Bench branch.
- `GET /bench/sources` reads `SOLUS_GAZEBO_PATH` first and falls back to `PATH` since `1e2130a8` (P9-T5; was P8-T3 F1).
- When a sim session sees parts of two robots, it un-binds with only a WARNING log. There is no `BenchSessionOut` field for it.

## 6. Live vs fixture-only per family

Harmonic and Classic are from the P9 rerun (`docs/qa/acceptance/P8-live-smoke.md` §"P9 rerun with the unmodified generated model", 2026-11-10, HEAD `f19378b6`); Fortress and Isaac are unchanged from P8-T2. Every run drove the fork's `GazeboToolService` in process under `env -i`.

| Family                                              | Verdict                                                                                                             | What ran                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Harmonic gz 8.15.0 (ROS Jazzy vendor)               | **LIVE with the unmodified generated model (P9 rerun)**                                                             | P9: the writer's own `two_link.urdf` (URDF sha256 `af585242…`, store `b36076168ce1…`, no hand amendment): probe → list_worlds → open_world headless → put_asset ×3 → spawn ok → list_models (`two_link`, links `base`/`arm`, revolute `elbow`) → control step 100 → joint_state (paused, 200 samples at ~0 rad) → set_joint_targets elbow 0.5 → play → joint_state (elbow 0.5000154 → 0.4999999 rad) → save_world → stop → probe (0 sessions); wall 16.2 s. P8 had the same chain with a hand-amended model (elbow 0.5052 rad). P8-T3 also proved `bin/launch` exits 78 without its vars, and that with the vars set `initialize → solus-gazebo`, `tools/list` → 13 tools, `probe` → gz 8.15.0.                                                                  |
| Classic gzserver 11.15.1 (conda `solus-gz-classic`) | **LIVE with the unmodified generated model (P9 rerun)**; spawn presence-confirmed, defect B proven on a broken copy | P9: the same unmodified model spawns (`spawn` ok, confirmed with `gz model -i`) and `list_models` shows it; `save_world` → `unsupported_on: classic 11.15.1` → stop; wall 9.9 s. A deliberately broken copy (`effort` removed) is refused: `{"ok": false, "code": "cli_failed", "reason": "gz model failed: Error: SDF parsing the xml failed"}` and `list_models` is empty (P8 reported `ok: true` here). `control` and `set_joint_targets` report ok but stayed unverified on this host in P9: the Classic CLI's one-shot publications were undeliverable to the Wi-Fi CGNAT address (findings G/J). P8 (hand-amended model, before `GAZEBO_IP`) had read the elbow at 0.49996 rad after targets 0.5. The fix `fa370f38` (`gz topic -d` whole seconds) stands. |
| Fortress ign 6.16.0 (conda `solus-gz-fortress`)     | **FIXTURE-ONLY**                                                                                                    | `probe` and `list_worlds` ran live. `open_world` failed: the server exits 255 because `libabsl_log_internal_check_op.so.2605.0.0` is missing (the env ships abseil 2608). The ign6 fixture is authored, not recorded.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Isaac                                               | **FIXTURE-ONLY**                                                                                                    | Isaac Sim is x86_64-only and this host is aarch64. Everything Isaac ran against the fork's fixture runtime and the API `Native` fake. The vendor-API code for the new actions (`isaacsim.*`/`pxr`) is unverified.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

Not run live: `run_routine`, `attach` and `reset` on any family. The fixture acceptance (§8) covers them.

Defects found by the live smoke:

- **A.** `urdf_writer` output was rejected by urdfdom (`effort`/`velocity` missing on `<limit>`, no `<inertial>` on the root). **Fixed** in `6022cc80` + `f19378b6` (P9-T2/T6), proven live above.
- **B.** Classic `spawn` reported `ok` when `gz model -f` failed to parse. **Fixed** in `979274f4` (P9-T3), proven live above.
- **D.** A saved Harmonic world references the Solus model store by absolute `file://` path. **Open** (§11).
- **E.** `family_hint` read Fortress stock worlds as `gz`. **Fixed** in `1cc71d4e` (P9-T4), checked against the installed stock worlds (files only).

Found by the P9 rerun and recorded, not changed (P8-live-smoke.md §"Also seen"): **I** a server crash after `spawn` surfaces only as timeouts and `session_unavailable` (the fork discards the server's stderr); **J** Classic `control`/`set_joint_targets` report ok for a publication nobody received; **K** Classic spawns the store model without its meshes (relative `filename` resolves against `GAZEBO_RESOURCE_PATH`, not the URDF's directory). Fixed on the way in `f19378b6`: **G** on a multi-homed host every service call timed out until `GZ_IP`/`IGN_IP`/`GAZEBO_IP` joined the named passthrough; **H** the 1 g placeholder inertial diverged in Harmonic's DART and aborted the server.

## 7. Out of scope

Not built on this branch:

- Isaac GUI attach (the probe says `gui_attach: "unsupported"`)
- Nucleus
- Policy rollouts
- Remote Isaac
- Sim-to-hardware transfer
- Any simulation UI

The SO-101 geometry was not available. P6 uses a two-link synthetic assembly and the existing inference fixture instead.

## 8. Tests: counts and wall times

Sources: P8-T4 (`P8-suites.md`), at `7c58d765`, and the P9 rerun below. One pytest process at a time; `SOLUS_TEST_DATABASE_URL` was never exported (set inline on one command, A4).

| Slice                                                                                     | Result                                                                | Wall      |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | --------- |
| API `-n 8 tests`, ignoring `test_cad_store.py` and `test_live_access.py` (A3)             | 12,176 passed, 13 skipped, 1 xfailed, 62 errors (pre-existing, below) | 1840.84 s |
| API serial: those two files (A2)                                                          | 68 passed                                                             | 18.48 s   |
| API migration files with the per-checkout URL inline (A4)                                 | 91 passed (the 62 A3 errors)                                          | 30.51 s   |
| Turn-limit dependents + ratchets (A5)                                                     | 318 passed                                                            | 63.27 s   |
| `livebench/tests packages/companion/tests` (B)                                            | 1,188 passed, 1 skipped                                               | 34.80 s   |
| `integrations/mcp/{gazebo,isaac}/tests`, `integrations/mcp/tests` and the other forks (C) | 2,816 passed, 17 skipped, 1 xfailed, 2 failed (pre-existing)          | 64.58 s   |
| `ruff check .`                                                                            | All checks passed                                                     | 0.17 s    |
| `mypy packages/api/src packages/companion/src`                                            | no issues, 576 files                                                  | 4.06 s    |
| mypy over the 166 changed `.py` files                                                     | 0 errors                                                              | 2.80 s    |
| `pnpm --filter @solus/desktop typecheck:web`                                              | clean                                                                 | 11.55 s   |

Totals: API 12,335 passed, 0 failed. Whole repo 16,339 passed. P8-T1 acceptance module: 14 passed, 1 xfailed (strict) in 31.99 s (wall 35.00 s). The ratchets after P8-T2 were 75 passed.

**P9 rerun (P9-T7, `P8-suites.md` §"P9 rerun", 2026-11-10, HEAD before `f19378b6`):**

| Slice                                                                              | Result                                                                                     | Wall            |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | --------------- |
| API `-n 8 tests`, ignoring `test_cad_store.py` and `test_live_access.py` (A1)      | 12,185 passed, 13 skipped, 0 xfailed, 62 errors (pre-existing)                             | 1766.46 s       |
| API serial: those two files (A2)                                                   | 68 passed                                                                                  | 18.26 s         |
| API migration files with the per-checkout URL inline (A4)                          | 91 passed (the 62 A1 errors)                                                               | 38.19 s         |
| The 7 ratchets (A5)                                                                | 75 passed                                                                                  | 17.77 s         |
| `livebench/tests packages/companion/tests` (B)                                     | 1,193 passed, 1 skipped                                                                    | 34.40 s         |
| `integrations/mcp/{gazebo,isaac}/tests integrations/mcp/tests` (C, sim forks only) | 504 passed                                                                                 | 15.71 s         |
| `ruff check .`                                                                     | All checks passed                                                                          | 0.12 s          |
| `mypy packages/api/src packages/companion/src livebench/src`                       | 6 `unused-ignore` errors in `livebench/sim/isaac_direct.py` → fixed → no issues, 669 files | 4.84 s / 0.59 s |
| mypy over the 167 changed `.py` files                                              | 0 errors                                                                                   | 2.00 s          |
| `pnpm --filter @solus/desktop typecheck:web`                                       | clean                                                                                      | 10.33 s         |

P9 totals: API 12,344 passed, 0 failed, 0 xfailed (the 6a strict xfail now passes). The P9-T1 acceptance re-run: 15 passed in 29.94 s. One regression versus P8 was found and fixed in the P9-T7 commit: `mypy livebench/src` (not in P8-T4's command) reported six unused `# type: ignore[import-not-found]` comments in `livebench/sim/isaac_direct.py`, made unused by the `6faba627` mypy override; the comments were removed (§10, P9-T7).

**P10 rerun (P10-T3, `P8-suites.md` §"P10 rerun", 2026-11-10, after the merge of main `8bdf993e`; HEAD before `3340b343`):**

| Slice                                                                         | Result                                                                                                                                            | Wall            |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| API `-n 8 tests`, ignoring `test_cad_store.py` and `test_live_access.py` (A1) | 12,851 passed, 13 skipped, 0 failed, 66 errors (pre-existing: the 10 migration files without the URL)                                             | 1933.18 s       |
| API serial: those two files (A2)                                              | 68 passed                                                                                                                                         | 20.50 s         |
| API migration files with the per-checkout URL inline (A4; now 10 files)       | 95 passed (the 66 A1 errors)                                                                                                                      | 37.01 s         |
| The 7 ratchets (A5)                                                           | 80 passed                                                                                                                                         | 19.80 s         |
| `livebench/tests packages/companion/tests` (B)                                | 1,342 passed, 1 skipped, **2 failed: main's `test_companion_drive.py`, pre-existing on `origin/main`** (below; fixed in `b8996e0a`, 81 passed ×3) | 44.31 s         |
| `integrations/mcp/{gazebo,isaac}/tests integrations/mcp/tests` (C2)           | 506 passed (`integrations/mcp/drive/tests` does not exist; C as named collected nothing)                                                          | 15.75 s         |
| `tests/acceptance/test_sim_acceptance.py` with `-s` (ACC)                     | 15 passed; TOTAL 48 scripted / 48 `model call start` / 0 real / 10 cards                                                                          | 35.60 s         |
| `ruff check .`                                                                | All checks passed                                                                                                                                 | 0.13 s          |
| `mypy packages/api/src packages/companion/src livebench/src`                  | no issues, 687 files                                                                                                                              | 0.53 s          |
| mypy over the 268 changed `.py` files in `33e3bc08..HEAD`                     | 102 errors, all in 22 files byte-identical to `origin/main` (kicad fork root, main's tests); 0 over this branch's 169 files                       | 0.56 s / 0.61 s |
| `pnpm --filter @solus/desktop typecheck:web`                                  | clean                                                                                                                                             | 10.93 s         |

P10 totals: API 13,014 passed, 0 failed, 0 xfailed (+670 over P9: main's SOLUSDEV-319/323 tests and the P10 B1 assertions). Pre-existing on `origin/main`, not changed here: `packages/companion/tests/test_companion_drive.py::test_a_hung_helper_is_killed_at_its_timeout` and `::test_a_cancelled_call_kills_the_helper` (file and `drive/` code byte-identical to `origin/main`; cause verified in `P8-suites.md` §"P10 rerun": the test's blocking `gone()` poll never lets the loop reap the terminated child under `PidfdChildWatcher`, so the zombie still answers `os.kill(pid, 0)`). On the human's instruction the test was fixed on this branch in `b8996e0a`: `gone()` is async and awaits `asyncio.sleep`, so the loop reaps the child; the file passed 81/81 on three consecutive runs. The 102 repo-root mypy errors in main-identical files (the kicad fork is type-checked from its own root; CI's mypy job covers `packages/api/src packages/companion/src`, clean).

CI `test:node` (pipeline 3052307850 on `095a4863`, the human's second merge of main, which brought SOLUSDEV-324) failed one test: `apps/desktop/src/renderer/src/features/sol/ChatsSidebar.test.tsx::groups rows under TODAY / THIS WEEK / EARLIER by last activity`, byte-identical to `origin/main`. Cause: the test stamps its "Fresh" row at `now - 1 h` and expects the TODAY group, but `chatGroups.labelFor` groups by calendar date, so between 00:00 and 01:00 (CI ran at 00:49 UTC; reproduced locally at 00:17 EST) the row lands in THIS WEEK. Fixed on this branch in the commit that adds this paragraph: the row is stamped at noon today, so the test holds at any hour and in any timezone. `pnpm test` afterwards: shared-types 313 passed, desktop 638 files / 6,817 tests passed, `test:env` 31 passed. (Locally the desktop suite also needed `pnpm install --frozen-lockfile` to materialise main's `@sentry/electron`; CI installs from the lockfile, so that was never a CI failure.)

One regression was found and fixed in `7c58d765`. The 3 new SOL tools and the simulation prompt pushed the measured fixed prompt from 13,379 tokens past `FIXED_PROMPT_TOKENS` 13,000. The constant became 14,000, and two dependent expectations moved by 1,000 (15,000 and 47,000/63,000 after the P10 merge, §17.4).

Pre-existing failures (not caused by this branch, unchanged):

1. xdist collection mismatch: `test_cad_store.py` and `test_live_access.py` have `uuid4()` parametrize ids. The files pass serially.
2. 62 setup errors with `KeyError: 'SOLUS_TEST_DATABASE_URL'` in 9 `*_migration*.py` files. They pass with the URL set (CI sets it).
3. `integrations/mcp/code/tests/test_code_process_tree.py::test_one_shot_command_cannot_leave_a_setsid_descendant`.
4. `integrations/mcp/code/tests/test_code_sandbox.py::test_foreign_writable_covers_tmp_and_caches_but_not_the_workspace` (`~/.local/share/uv` no longer writable; host-environmental).

Items 3 and 4 are the same failures SOLUSDEV-321 `FINAL-acceptance-live.md` step 10 recorded.

## 9. Model calls: scripted vs real

Every SOL turn used the production `LlmRunner` and gateway with a scripted adapter. `gateway.build_adapter_registry` was monkeypatched to raise, so no real adapter could be built. Source: P8-T1.

| Scenario                                                                     | Scripted | `model call start` | Real  | Cards                          |
| ---------------------------------------------------------------------------- | -------- | ------------------ | ----- | ------------------------------ |
| 1 no simulator (rung-1 `simulate`, then rung-4 route "gazebo not connected") | 4        | 4                  | 0     | 0                              |
| 2 gz 8.15.0 owned chain (Build 1 turn, Guide 2 turns)                        | 6        | 6                  | 0     | 1 (`sim.generate_model`)       |
| 2 ignition 6.16.0                                                            | 6        | 6                  | 0     | 1                              |
| 2 classic 11.15.1                                                            | 6        | 6                  | 0     | 1                              |
| 3 attached world                                                             | 4        | 4                  | 0     | 3 (Build) / 3 refusals (Guide) |
| 4 save on owned sessions                                                     | 2        | 2                  | 0     | 2                              |
| 5 Isaac (Build)                                                              | 2        | 2                  | 0     | 0                              |
| 5 Isaac (Guide)                                                              | 2        | 2                  | 0     | 0                              |
| 6a Classic `save_world`                                                      | 4        | 4                  | 0     | 0                              |
| 6a strict xfail (gap)                                                        | 4        | 4                  | 0     | 0                              |
| 6b Darwin/arm64                                                              | 2        | 2                  | 0     | 0                              |
| 6b Linux/x86_64 without GPU                                                  | 2        | 2                  | 0     | 0                              |
| 7 generation                                                                 | 0        | 0                  | 0     | 0                              |
| 8 retention                                                                  | 0        | 0                  | 0     | 0                              |
| 9 cross-project isolation                                                    | 4        | 4                  | 0     | 2                              |
| **Total**                                                                    | **48**   | **48**             | **0** | **10**                         |

P8-T2, P8-T3 and P8-T4 made 0 model calls of either kind. On `solus_sim`, `credit_ledger` has 4 rows, all `trial_grant`, and 0 `usage`. Real provider calls on this branch's acceptance: **0**.

P9: the P9-T1 re-run of the acceptance module (scenario 6a fixed) counted **48 scripted, 48 `model call start` lines, 0 real** over 15 passing rows; both 6a rows now record the fork's sentence in the turn's tool result. P9-T2..T6 made 0 model calls (no SOL turn). The P9-T7 suite rerun (§8) ran the same module inside the API suite with scripted adapters only: 0 real.

P10 (P10-T3, after the merge of main): the `-s` run of the acceptance module at `3340b343` printed `TOTAL (15 rows) scripted 48 · model-call-start 48 · real 0 · ledger 52 · cards 10`, 15 passed in 32.33 s: the gate order under main's restructured `request_confirmation` (`needs_card` → stored args → preview) still yields zero cards on owned sessions and the same 10 cards on attached ones. Every other P10 slice (§8) ran with scripted adapters only. Real provider calls in P10: **0**.

Scenario verdicts:

- PASS: 1 (with a substituted question, §10), 2 ×3 families, 3, 4, 5 (fixture-only), 6a (since P9-T1), 6b, 7, 8, 9.
- **6a was PARTIAL at P8**: the fork's `unsupported_on` sentence was lost at the park because `confirmations._build_preview` treated the wrapper's `ToolException` as a generic preview failure. `9bb1b108` (P9-T1) raises `PreviewRefusal(refusal_sentence(plan))` from `gazebo_tools._consent_rows` and `IsaacTool._consent_rows`; the strict xfail became a passing test (`6a through turn`: "Classic 11 cannot write a running world back to its file.").

## 10. Deviations and decisions under delegated judgment

From plan §1.4:

- **R115 superseded for sim tools.** A routed rung-4 call on an owned session runs without a card; on an attached session it cards. `routed_by_simulation` is unchanged and still guards the Onshape owned routines.
- **Isaac/Gazebo reclassification** as in §3. `stop` on an attached session refuses in the tool and never cards.
- **The authored `matedCS` fixture.** `tests/fixtures/inference/assembly_definition_mated_cs.json` was authored from the public Onshape Assemblies API schema, not captured (no live Onshape call was allowed). It is labelled so in its header.
- **Alias row shape.** `part.attrs.sim_aliases: [{provider, device_id}]` is written only by `sim.map_to_parts` (gated) under `lock_project`, with attrs reassigned. `external_ref` is never touched. The provider must match `^[a-z][a-z0-9_]{0,31}$`.
- **Sim packet signals.** `device_id = <world>/<model>/<joint>`, values `<joint>.position`/`.velocity` in rad and rad/s. Classic reports no velocity.
- **One vendor-free `scene_ref`.** `provider` is the discriminator. One owned Gazebo world per project.
- **`sim.available` limits.** At most two companion calls, and only when those tools are registered.
- **Module names** were chosen around H6/H9.
- **Run environment.** Dev DB `solus_sim`, redis `solus-redis-322` on :6391 (removed at the end), API :8030. No desktop run.

Mined from the implementer and reviewer journals:

- **P0/P3 detection chain.** `gazebo --version` hangs, so it is never executed. Classic `gz --version` prints `Invalid arguments`. Classic is probed only with `gzserver --version`, where banner plus exit 255 counts as success. `ign` has no `--version` fallback.
- **Classic CLI.** `gz model` has no `--list`/`-j`; joints come from `gz model -w <w> -m <m> -i`. Model names come from `/gazebo/<w>/<model>/…` topics. Joint state is polled at ≤ 10 Hz.
- **Fortress CLI.** `ign service --req` needs `--timeout`. `ign msg -l` prints `ign_msgs.X` while `--reqtype` takes `ignition.msgs.X`. There is no python binding. The text-format fallback for `--json-output` was not built, because `--json-output` was verified on 6.16.0.
- **Harmonic.** It steps only while paused, so the step request is `pause: true multi_step: <n>`. Joints are listed with `gz model -m <m> -j` (the scene message carries none), capped at the first 32 models.
- **P1-T1.** Only `gz`/`ign` have argv variants. The roster string the plan expected in `tests/test_sim_ladder.py` does not exist; `tests/test_config.py` was extended instead. `test_simulate.py`'s route pin was amended. The route's status sentence now says "its gate decides per call".
- **P1-T2.**
  - `SimAvailability` gets `settings=None` and reads the session's settings, as `simulate.py` does.
  - The `ngspice` row `version` is None, because the machine's version and the worker's binary differ.
  - Arch vocabulary accepts Node values (`x64`/`arm64`) as well as uname values (`x86_64`/`aarch64`).
- **P2-T1.**
  - `OwnedSessionRunningError` also refuses a live `owner=user` row with the same id.
  - `owner` is a CHECK constraint, not an enum.
  - The migration round-trip test runs on the per-checkout DB, with head restored in `finally`.
  - `docs/schemas/sim-session.md` was added.
- **P2-T2.** `current_call_id` is set around `gated` by `with_current_call_id` (C901 budget). The behaviour is identical and pinned by a test.
- **P2-T3.**
  - `_owned_isaac_tools` is kept as a thin wrapper, because `routers/isaac_connection.py` imports and monkeypatches it.
  - A second `start` is refused by the ledger after the native call.
  - `created_by` threading was added later (`test_start_records_the_requesting_user_on_the_ledger_row`).
- **P3-T1/T2/T3 names.** Symbol names differ from the plan sketch because of H6 (`GazeboToolService`, `<Tool>Args`, `WorldPose`, `SessionRefusedError`, …).
- **P3-T1/T2/T3 code changes.**
  - New module `solus/gazebo_routines.py` (`gazebo_server.py` would otherwise exceed 800 lines).
  - The partial store is a sibling `<sha256>.partial/`, not `<sha256>/.partial/`, so promotion is one atomic rename.
  - Pydantic strict mode makes `Vec3` a 3-element list.
  - `model_sha256` = sha256 of the canonical manifest JSON, enforced at chunk 0.
  - `put_asset` on an already-verified sha is acknowledged without a write.
  - `world_ref`/`dest` resolve against the first matching `SOLUS_SIM_ROOTS` entry.
  - `wrap_model` refuses `<plugin>`/`<include>`/`<uri>` loaders except a relative `<mesh><uri>`.
  - `GZ_CONFIG_PATH`/`IGN_CONFIG_PATH` are sanitized absolute-only, and `SOLUS_MCP_WORKSPACE` was removed from `env.allow`.
- **P3-T3 review fixes.** A one-chunk push never promoted (`unlink` of a missing state file). Fixed in `becaab11`.
- **P3-T4.**
  - The fork answers `model_not_verified` so the API keys its push on a code. The Isaac fork does the same (P4-T2).
  - The wrapper reuses private Isaac helpers; Isaac-worded helpers were re-authored as `_gz_*`.
  - The spawn preview for a model that must be pushed is wrapper-authored, and the fork's dry run still runs right before the native spawn.
  - A SOL-supplied `dry_run` records nothing in the ledger.
- **P3-T5.**
  - `GazeboTopicSource(topics, *, exe)` takes the family from the subclass.
  - The Classic source polls `gz model -i`.
  - `open_gazebo` builds the connection via `asyncio.to_thread`.
  - stdout lines are bounded at 64 KiB.
  - `GazeboSimConfig` is documented in `docs/api/gazebo-integration.md`.
- **P4-T1.**
  - `open_stage` creates the owned session (start + open in one call).
  - `save_stage` exports privately and the controller copies fd-relative into the root.
  - The camera "one frame" is a ≤ 64×64 grayscale PNG.
  - `run_routine`'s fork deadline is `duration_s + 10`.
- **P4-T2.**
  - `PUBLIC_MODELS` grew by 7, not 8: `put_asset` is internal.
  - Isaac `run_routine` cloud timeout 55 → 85 s.
  - Two push messages became vendor-neutral.
- **P5-T1.** IDs are validated as uuid text (strict pydantic). Rung 3 of the matching order (generated joints) was deferred to P6-T2 and landed in `dab76006`.
- **P5-T2.**
  - rad → part-unit conversion lives API-side in `envelopes.convert_unit` + `window_evaluator`, not in `livebench/telemetry/normalize.py` (that module never sees the part). The test is in the new `tests/test_window_evaluator_units.py`.
  - The alias query adds `attrs ? 'sim_aliases'` so the partial index applies.
- **P5-T3.**
  - Adoption runs for every newly resolved part, and a second robot un-binds the session.
  - `robot_of_part` walks `contains` and `part_of` upward.
  - The lookup is injected into `SessionManager`.
- **P5-T4.**
  - The desktop needed 6 edits (`pinned`).
  - The Gazebo fork's routine result carries `family`/`version`.
  - `record_sim_run` resolves through `DbEntityResolver.resolve(source=…)`, not the live buffers.
  - An Isaac sweep files a Run but no rung-4 fact (no final target).
  - Pin refuses a running run with 409 `run_active`.
  - Gazebo runs record `model_sha256` null.
  - Review fixes bind the routine's model API-side and key readback from the request and ledger, never the companion (`f671a540`, `36fe4348`, `3c19d8b6`), and added `scene_name` (`a32200000003`).
  - The solver word is restricted to an alphabet (`_solver_word`).
- **P6-T1.**
  - Tests went to `tests/test_inference_mates.py`, because `test_mechanical_connector*.py` does not exist.
  - The frame is validated as rigid; a non-rigid frame becomes a gap.
- **P6-T2.**
  - The mass source label is `cad_mass` (vendor sweep), not `onshape_mass`.
  - A framed mate without limits is a FIXED attachment plus a `<joint>.limits` gap.
  - Every link gets a `<collision>` mesh.
  - Limits order is user_config → definition → gap; there is no measured range in the graph.
  - Sensor sites appear in the gap report only.
  - The preview is capped at 50 rows.
  - `model_job.py` is 745 lines.
  - Work landed as 7 commits rather than one.
  - **Commit `75db2f25` was amended once by its implementer (message only, before any review saw it).** This is recorded here because the standing rules forbid amends.
- **P7-T2.**
  - `"bridge offline"` stays the contract message; the wrappers translate it to "The companion is offline (bridge offline)."
  - Bare-code refusals read "The companion refused the action (<code>)."
- **P7-T3.**
  - The cron wrapper is `prune_sim_runs_job`.
  - `kept` = live sim runs that keep their payload.
  - A pruned run's `.solus` entry still names the soft-deleted artifact (reads 404).
- **P8-T1.**
  - Scenario 1 used the rung-1 stress question. "Lift 500 g at full reach" has no rung-1 calculator; torque is rung 3.
  - Scenario 2's card was generated on the CAD arm, while spawn/routine ran the fake arm's pre-seeded model (the robot with a real bus identity).
  - Scenario 5 added `isaac.stop`.
  - Scenario 6b's fallback is a structural row (`mujoco runnable_here: true`), not prose.
  - The acceptance module is 1,376 lines.
- **P8-T2.** Classic `-d` fix (`fa370f38`). The `classic11` fixture was re-recorded.
- **P8-T3.** The API was started with `--factory solus_api.main:create_app`. The machine upsert used a bridge test client rather than the real companion (version lines were real). The pin 409 was not reachable over HTTP.
- **P8-T4.** `FIXED_PROMPT_TOKENS` 13,000 → 14,000 (`7c58d765`); → 15,000 in P10 (`8d6aa964`, §17.4).
- **P9-T1 (6a, `9bb1b108`).** `PreviewRefusal` subclasses `ToolException`, so every existing `pytest.raises(ToolException)` case is unchanged; the carried sentence goes through `refusal_sentence` (paths redacted to `<path>`, capped, period-terminated).
- **P9-T2 (defect A, `6022cc80`).** Every non-fixed `<limit>` carries `effort` and `velocity`; unknown values are SDF's `-1` "not enforced" sentinel (`UNENFORCED`), known values come from the new `GeneratedJoint.effort_nm`/`velocity_rad_s` (not populated by `model_job` yet: the graph has no actuator-limit source). Fixing a massless root to a `world` link was tried and **rejected** by the real converters (urdf2sdf lumps it into the world and drops the model), so a massless root, or a massless child of a non-fixed joint, gets a placeholder `<inertial>` and the report's `<link>.mass` gap names it. `mjcf_compile._hinted` turns a negative effort into MuJoCo's own `0` so no `actuatorfrcrange` is invented from the sentinel.
- **P9-T6 (`f19378b6`).** The 1 g placeholder diverged in Harmonic's DART (ODE AABB assertion, server SIGABRT): a kept massless link now weighs as much as the heaviest known link (floor 1 g) with a 3 cm radius of gyration. `GZ_IP`/`IGN_IP`/`GAZEBO_IP` joined `env.allow` and `bin/launch` (multi-homed hosts).
- **P9-T3 (defect B, `979274f4`).** Classic `_ok` raises `CliError` when rc != 0 **or** any stderr line starts with `Error` (reason: last line, path-redacted, bounded); every classic CLI call routes through it. `spawn` confirms presence once with `gz model -i` after the CLI returns. `gz joint --pos-t` on an absent model is still a silent rc-0 success (recorded as open, finding J).
- **P9-T4 (defect E, `1cc71d4e`).** `_PLUGIN_HINTS` order: `gz-sim-` (gz), `ignition-gazebo-` (ignition), `ignition::gazebo`, `gz::sim`, classic `lib*.so`; plugin filenames decide before namespaces, the SDF-version ≥ 1.10 fallback is unchanged.
- **P9-T5 (F1, `1e2130a8`).** `gazebo_family.family_on_disk(env)` reads the configured bin dirs (file checks, no subprocess; `gzserver` ⇒ classic before `ign`/`gz`, because the classic conda env also ships an `ign` shim); `available_simulators(..., env=None)` uses it first and the `which` lookup only as a fallback; the miss reason names both places.
- **P9-T7 (suites).** `mypy livebench/src` reported 6 `unused-ignore` errors in `livebench/sim/isaac_direct.py`: the `6faba627` mypy override (`ignore_missing_imports` for `isaacsim.*`/`omni`/`pxr`) made the file's `# type: ignore[import-not-found]` comments unused. P8-T4 ran mypy on `packages/api/src packages/companion/src` only, so it never saw them. The six comments were removed; no behaviour change.

## 11. Open questions for humans

### Fixed after P8 (P9)

These were open questions 8–11 at P8. They were fixed on the branch in P9 (CLAUDE.md Phase 4: findings are fixed before handoff), each with the implementer's delegated decision recorded in §10:

- **Scenario 6a** — `9bb1b108` (P9-T1). `PreviewRefusal(refusal_sentence(plan))` is raised from `gazebo_tools._consent_rows` and `IsaacTool._consent_rows`; the strict xfail is un-marked and passes; SOL's tool result carries "Classic 11 cannot write a running world back to its file."
- **Defect A, generated URDF rejected by Gazebo** — `6022cc80` (P9-T2) and `f19378b6` (P9-T6). Decision: `effort`/`velocity` on every non-fixed limit with the `-1` sentinel when unknown, and a placeholder inertial for a massless root or moving link (the heaviest known link's mass, floor 1 g), **not** a world-fixed root (rejected by urdf2sdf). Proven offline by `gz sdf -p` on both families and live by the unmodified model spawning in Harmonic and Classic.
- **Defect B, Classic false-success spawn** — `979274f4` (P9-T3). Decision: both halves — an `Error` stderr line fails every classic CLI call, and `spawn` confirms presence with `gz model -i`. Proven live on a deliberately broken copy (`ok: false`, `list_models` empty).
- **Defect E, Fortress stock worlds hinted as `gz`** — `1cc71d4e` (P9-T4). Decision: plugin filenames before namespaces (`gz-sim-`, `ignition-gazebo-`, then `ignition::gazebo`, `gz::sim`, classic `lib*.so`). Checked against the installed stock worlds of all three families, files only.
- **F1, `GET /bench/sources` and `SOLUS_GAZEBO_PATH`** — `1e2130a8` (P9-T5). Decision: `SOLUS_GAZEBO_PATH` first via file-only `family_on_disk`, PATH as a detection fallback, miss reason names both places. `docs/api/gazebo-integration.md` amended.

### Still open

1. **Isaac allowlist, original 8 entries.** They keep static `requires_confirmation: true`, while the API now gates per call and the Gazebo fork lists the same operations as `false`. Should the two forks be aligned?
2. **Isaac `run_routine` timeout.** The allowlist entry is `timeout_seconds: 55`, shorter than a 60 s sweep plus the fork's 10 s grace (the cloud bound is 85 s). Should it be raised to ≥ 75, or should the fork cap sweeps at about 40 s?
3. **Uppercase model files.** `ARM.URDF` passes the type allowlist but `model_file_of` refuses it as `model_file_ambiguous` (fail-safe). Are uppercase model files a supported input?
4. **`sim.map_to_parts` part overrides.** Should it accept explicit `part_id` overrides for ambiguous joints, or is a second call after renaming the intended loop?
5. **Superseded models.** A regenerated model lands beside the old one with the same name and nothing marks the old one superseded. Add `superseded_by`?
6. **Link and mesh bounds.** Links > 32 and meshes > 31 are refused (SimulationModel/Asset bounds) although a CAD import allows 128 leaves. Is selecting a sub-assembly the answer, or should the bounds be raised?
7. **MJCF location.** The compiled MJCF lives in `attrs.artifacts.mjcf`, outside the `asset.files` manifest. Should the Live Bench sim pane read it from there?
8. **Saved worlds and the Solus store (defect D).** A saved Harmonic world embeds the model store by absolute `file://` path, so the person's saved world depends on the companion workspace. Should `save_world` rewrite the `<include><uri>` (copy the model beside the world, or a `model://` URI)?
9. **`GET /bench/sources` Isaac row.** It says "detected" on aarch64 because `~/isaacsim` exists. Should detection also check the architecture?
10. **`RunSummary` in OpenAPI (F2).** Should the runs routes be typed? This is a Live Bench route change.
11. **Retention counting.** Should already-pruned runs count toward a robot's newest 20? Today they do not.
12. **`robot_of_part` edge origins.** It accepts connector-written `contains` edges. Restrict it to manual edges?
13. **Unmapped sim joints.** Each unmapped joint costs one query per packet. Add a short negative-cache TTL for `source != None` if load shows?
14. **`gui_attach` semantics.** It currently means "a running world of the newest family exists". Should it be constant per family?
15. **Fortress env repair.** The env has an abseil ABI mismatch (`libabsl_log_internal_check_op.so.2605.0.0` missing, the env ships abseil 2608). Repair it (`libabseil=20250512`) or recreate it, then re-run the live smoke for Fortress? Fortress stays FIXTURE-ONLY until then.
16. **`envelopes.py` split.** The file is at 798/800 lines; split out the unit vocabulary on next touch.
17. **`simulate.py` reason sentences.** The ladder tool's `none/not_available/missing_input` reasons are fragments, not sentences. Convert them?
18. **Accept the `GZ_IP`/`IGN_IP`/`GAZEBO_IP` passthrough (`f19378b6`). RESOLVED (explicit yes from Pratham Madaram in chat, 2026-11-11; recorded in `integrations/mcp/gazebo/SECURITY_REVIEW.md` §4 residual and §7 checklist).** The P9-T6 reviewer flagged that this widens what the companion copies from its ambient environment into the simulator child (three IP strings read only by the simulator's transport; the fork never reads them). The task did not grant it; it is recorded in `integrations/mcp/gazebo/SECURITY_REVIEW.md` as a residual and needs an explicit human yes at the MR.
19. **Inherited ticket edge.** A card parked in a task leaves a matching ticket that a same-args `invoke` in that task could consume. Production never reaches this. Close it for both wrappers?
20. **Sim Run packets and the live buffers.** Should a sim Run's packets also reach the live telemetry buffers, so the window evaluator sees tool-driven routines?
21. **Multi-world attach.** `gz model -m <m> -j` reads the first running world, which is fine for owned sessions. Revisit for multi-world attach.
22. **`APPROVAL_REQUIRED_LABEL` and the owned-session no-card path (P10 tension i). RESOLVED (human decision 2026-11-10: the hooks honour the label).** The constant now lives in `agent/dynamic_gate.py` (`execution_policy` imports it) with `approval_required(rows)`. Both sim wrappers' `needs_confirmation` first decide ownership, then, for every tool with a dry run (the session-creating `open_world`/`start`/`open_stage` included, after the fresh security review of `b743b0c2` found them dead-ending in `invoke`), read the fork's preview and card when any row carries the label; `invoke` additionally refuses an uncarded (no-ticket) call whose verified plan carries it, so a dispatcher that skipped the hook cannot run it. A plan that fails inside the hook answers "no card" because the same failure refuses the call in `_verified`. Cost: one extra dry run per owned mutating call. Tests: `test_dynamic_gate.py::test_approval_required_rows_are_recognised_by_label_only`, and in `test_gazebo_tools.py`/`test_isaac_tools.py` `test_an_approval_required_preview_row_cards_an_owned_session[guide|do]`, `test_invoke_without_ticket_refuses_when_the_preview_demands_approval` and the session-start twins `…_cards_instead_of_dead_ending`. Review notes left as-is (fail closed): on a spawn that first pushes the model, a label the fork adds only after the push refuses the owned call (a retry then cards) and is not shown on an already-approved card; a companion slower than `HOOK_TIMEOUT_SECONDS` (5 s) turns an owned call into a card.
23. **ADR-041 denylist and simulator GUI windows (P10 tension ii). RESOLVED `dc3db02a`.** ADR-041's frontmost-app denylist did not name Gazebo or Isaac Sim GUI windows, so a window-bound `drive.step` on a simulator GUI could have acted on a world through its own drive card, outside the `sim_session` ledger. The amendment adding simulator GUIs (Gazebo Classic, Ignition/gz sim, Isaac Sim, MuJoCo viewers) to the denylist was approved in chat on 2026-11-10 and applied to DECISIONS.md in the dedicated commit `dc3db02a`. Code enforcement followed on the human's instruction: `DeniedApps.exact` in `apps/desktop/native/solus-input/Sources/SolusInputCore/Policy.swift` gains `org.mujoco.mujoco` (MuJoCo.app, `MACOSX_BUNDLE_GUI_IDENTIFIER` in the MuJoCo `simulate/CMakeLists.txt`) and `org.python.python` (the python.org framework process hosting the pip `mujoco.viewer` and the Gazebo python bindings); `FrontmostAppTests.swift` lists both; `docs/architecture/sol-drive.md` §2.2 gains the "Simulator GUIs" bullet. Gazebo's own macOS binaries run unbundled and Isaac Sim has no macOS build, so both are already denied by the helper's no-bundle-id rule. **Not compiled or run here**: this host (Linux aarch64) has no Swift toolchain; the SOLUSDEV-319 owners should run `swift test` in `apps/desktop/native/solus-input` on a Mac.
24. **`with_front_app` registry rebuild vs. `sim.available` (P10 tension iii).** `routers/sol.py` runs `with_front_app(...)` each Build turn, which returns a new `ToolRegistry` when a drivable window is bound, while `SimAvailableTool` (`agent/tools/sim_available.py`) keeps the reference to the registry it was registered in. The two registries hold the same tools apart from the rebuilt `drive.step`, and `sim.available` only looks up `gazebo.probe`/`isaac.probe`, so this is harmless. Noted so nobody is surprised if `sim.available` ever lists tools.

## 12. Values the human must set

- **`SOLUS_GAZEBO_PATH`** (companion environment): colon-separated absolute bin dirs. On this host: `/opt/ros/jazzy/opt/gz_tools_vendor/bin`; Classic/Fortress `…/envs/solus-gz-{classic,fortress}/bin`. Binaries are never taken from `PATH`.
- **`SOLUS_SIM_ROOTS`** (companion environment): colon-separated absolute dirs that hold the person's worlds and stages, for example `/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds:<your worlds>`.
- **The simulator's own environment in the companion's environment**, passed through by name by `bin/launch` / `solus/env.allow`. Under `env -i` Harmonic finds no command without these.
  - `GZ_CONFIG_PATH`, `GZ_SIM_SYSTEM_PLUGIN_PATH`, `GZ_SIM_RESOURCE_PATH`, `GZ_PARTITION`, `GZ_IP`
  - `IGN_CONFIG_PATH`, `IGN_GAZEBO_SYSTEM_PLUGIN_PATH`, `IGN_GAZEBO_RESOURCE_PATH`, `IGN_PARTITION`, `IGN_IP`
  - `GAZEBO_MODEL_PATH`, `GAZEBO_PLUGIN_PATH`, `GAZEBO_RESOURCE_PATH`, `GAZEBO_MASTER_URI`, `GAZEBO_IP`
  - the `*_IP` names (P9-T6): on a multi-homed machine set them to `127.0.0.1`, or every local service call times out
  - `LD_LIBRARY_PATH` (an accepted residual in `SECURITY_REVIEW.md`)
- **`SOLUS_ISAAC_RUNTIME`**: unchanged, needed only on an x86_64 Isaac host.
- **Optional `SOLUS_NGSPICE_BIN`.**
- **`make mcp-forks`** on each companion machine to create `integrations/mcp/gazebo/.venv`. P8-T3 ran it here (hash-verified, 3.7 s).
- **Sign-off lines (2026-11-10):** Reviewer 1 (Pratham Madaram, instruction given in chat) is recorded in both `PROVENANCE.md` files against the reviewed commit `408fb7e2` (gazebo tree `d6e1a8e4…`, isaac tree `11344120…`), with dated entries in both `SECURITY_REVIEW.md` files; the server-level `exposure: internal` keys are ratified there. That sign-off covers `allowlist.yaml` as part of the reviewed tree, including the two `put_asset` entries. Still owed: **Reviewer 2** on both forks (rule 2, no single-reviewer shipping). The explicit yes on the `*_IP` passthrough (item 18) was given in chat on 2026-11-11 and is recorded in the gazebo `SECURITY_REVIEW.md`.
- **Shared-environment values** named by the API's startup warnings in P8-T3. None were needed for this branch: `SOLUS_TOOLKB_VOTE_SALT`, the secret store keys, the Supabase keys, the BOM Store ids, and the provider keys (`make seed-secrets`).

## 13. DECISIONS.md amendments (APPLIED `dc3db02a`, approved in chat 2026-11-10)

The plan §7 one-sentence proposal was expanded to the full paragraph below, approved in chat against that concrete text (ADR-032 tier-2) and appended to ADR-014 in the dedicated commit `dc3db02a`, together with the ADR-041 denylist amendment from §11 item 23:

> **Amended (2026-11-10, SOLUSDEV-322; approved in chat against the concrete text below):** SOL may open the user's own Gazebo worlds (Classic, Ignition and gz families behind one `gazebo.*` tool set; a cell a family lacks answers `unsupported_on`) and Isaac stages, attach to a simulator the user already started, find or insert the robot, read joint and sensor state, set joint targets, pause, play, step and reset time, and run bounded named routines. Whether an action needs a confirmation card is decided per call, API-side, from a server-owned ownership ledger (`sim_session`), never from a companion claim: in a session Solus started these actions run with no card in Guide and Build; in a session the user started, or one the ledger cannot prove, they card in Build and are refused in Guide; writing the user's own files (`save_world`, `save_stage`) always cards. Both simulator servers are `exposure: internal`, so only the owned `gazebo.*`/`isaac.*` wrappers are model-facing. Solus-generated models reach the machine as sha256-verified chunks under `.solus/sim/models/<sha256>/`, never at arbitrary paths. Sim telemetry carries a session-level provider tag so it resolves to the same part nodes as real hardware; routine results are Runs with `origin="sim"` and rung-4 sim facts on the robot, retained 30 days or the newest 20 per robot (pinned, baseline and finding-linked runs are kept). Remote Isaac, a simulation UI, policy rollouts and sim-to-hardware transfer stay out of scope. For these tools this supersedes the 2026-09-12 amendment's per-action gate; ADR-014's core (MuJoCo built in, integrate rather than compete) is unchanged.

> **ADR-041 amendment (2026-11-10, SOLUSDEV-322 P10; approved in-chat against the concrete text below):** The frontmost-app denylist also covers simulator GUIs: Gazebo Classic (`gazebo`, `gzclient`), Ignition and gz sim (`ign gazebo`, `gz sim`), Isaac Sim, and the MuJoCo viewers. SOL reaches a simulator only through the owned `gazebo.*`/`isaac.*` wrappers and the `sim_session` ownership ledger (ADR-014, 2026-11-10 amendment), never by driving its window, so a drive card can never stand in for the per-call sim gate or act on a world the user started.

## 14. H10 gate note

The full API suite runs far longer than H10's `timeout 600`:

- A3 took 1,837 s under `-n 8`.

At the gate this fails with no summary line. That is a timeout, not a code failure. P8-T4 therefore ran the suite in slices (§8); those slices are the evidence. Two branch commits exist so the gate's per-file type check stays clean:

- `6b2c1721` adds the package markers `integrations/__init__.py` and `integrations/mcp/__init__.py`. Without them, mypy names each fork module twice (by path and by import).
- `6faba627` type-cleans every test touched on the branch, adding a mypy override for the Isaac runtime modules that lazily import `isaacsim`/`omni`/`pxr`.

## 15. Evidence files

- `docs/qa/RECON_SOLUSDEV-322-sim-integrations.md`
- `docs/qa/acceptance/P8-sim-acceptance.md` (harness `packages/api/tests/acceptance/test_sim_acceptance.py`)
- `docs/qa/acceptance/P8-live-smoke.md`
- `docs/qa/acceptance/P8-run-for-real.md`
- `docs/qa/acceptance/P8-suites.md` (with the P9 rerun section). Its raw logs are in `docs/qa/acceptance/p8_suites/*.log`, gitignored and kept locally; the P9 rerun logs are in the P9 scratchpad only.
- `docs/qa/acceptance/P9-T2-urdf-defect-A.md`, `P9-T3-classic-spawn-defect-B.md`, `P9-T4-family-hint-defect-E.md`, `P9-T5-bench-sources-gazebo-path-F1.md`
- `docs/qa/COWORK_QA_sim-integrations.md`

`docs/qa/REPO_STATE_ONBOARDING_BENCH_SIM_2026-11-08.md` remains untracked, as instructed.

## 16. Session note: host reboot during P9

The host rebooted at about 21:09 on 2026-11-09 while the first P9 workflow was mid fix-round. The reboot killed that workflow, wiped the session scratchpad (the P8 smoke drivers were recreated from `P8-live-smoke.md` §Commands in P9-T2/T6) and stopped the dev containers `solus-db-1` and `solus-redis-1`. The agent's own `docker start` was denied by the permission classifier (shared resource), so the agent asked the human to run `docker start solus-db-1 solus-redis-1`; the human did, and P9 continued as P9a (database-free fixes `979274f4`, `1cc71d4e`, `1e2130a8`) and P9b (`9bb1b108`, `6022cc80`, `f19378b6`, `93eab590`). No container other than those two was started or stopped by anyone in this session after the reboot. The post-reboot host networking finding (G, CGNAT Wi-Fi address plus tailscale) is in §6 and `P8-live-smoke.md`.

## 17. Merge of main 8bdf993e (P10)

The human started `git merge origin/main` (MERGE_HEAD `8bdf993e`: SOLUSDEV-319 drive, SOLUSDEV-323 onboarding) on top of `b1df3a31`. Phase A (orchestrator, inline) finished it as `87d358d2`; Phase B (this workflow) reconciled the sim work with main's conventions in `e5266473` and `8d6aa964`, and records it here. Range: `b1df3a31..HEAD`. `git diff --stat 8bdf993e HEAD -- packages/api/src/solus_api/agent/drive` is empty (main's drive untouched).

### 17.1 Conflicts and how each was resolved

Seven paths conflicted. Verbatim from the merge commit message (`git show -s 87d358d2`):

```
Conflicts resolved (SOLUSDEV-322 P10):
  packages/api/src/solus_api/agent/execution_policy.py — main's
    APPROVAL_REQUIRED_LABEL kept; _ISAAC stays deleted (the Isaac wrappers
    are no longer owned routines on this branch)
  packages/api/src/solus_api/agent/modes.py — docstring names both Guide
    predicates (DIRECT_WRITE_TOOLS and the per-call needs_confirmation hook)
  packages/api/src/solus_api/agent/runtime.py — main's _internal_only()
    now also drops raw gazebo.* specs (both owned sim servers), so the
    wrappers stay the only model-facing surface
  packages/api/src/solus_api/agent/turn_limits.py,
  packages/api/tests/test_sol_turn_limits.py — comment-only
  packages/api/openapi.json, apps/desktop/.../schema.ts — regenerated
    (make gen-openapi) with both sides' routes and schemas
New: migrations/versions/a32200000004_solusdev_322_merge_main_heads.py
    joins main's a31900000003 and this branch's a32200000003 into one head.
```

### 17.2 Auto-merged and deliberately kept

- `agent/confirmations.request_confirmation`: the branch's entry check stays FIRST — `registered_tool(registry, call.tool)` then `await needs_card(tool, call.args)` (fails closed) — followed by main's `_refused_before_preview → _summarize → _with_stored_args → _pending_duplicate → _card_preview`. Verified at `confirmations.py:536-554` in this task; not changed.
- `agent/confirmations.decide_confirmation` executes an approved card with `registry.invoke_stored(call)` (`confirmations.py:703`), main's stored-args path; `registry.invoke` remains only in `runtime.build_dispatch` (`runtime.py:1274`, `:1295`).
- `agent/modes.build_mode_dispatch`: `mutating = DIRECT_WRITE_TOOLS | {d.name for d in descriptors if d.requires_confirmation}` plus `guide_refuses()` consulting `registry_needs_card(registry, call)` — main's named list and the branch's per-call hook, both refused in Guide.
- `routers/sol.py`: `with_front_app(...)` builds the turn's registry (`:1182`) and `build_mode_dispatch(..., registry=registry)` receives it (`:1274`), so Guide keeps the per-call hook check on the rebuilt registry.
- `runtime._internal_only`: main's `exposure: internal` flag check plus the branch's server/prefix name check (`_OWNED_SIM_SERVERS`, `_OWNED_SIM_PREFIXES`); `_owned_server_tools` still builds the owned wrappers from `session.inventory` directly.
- `test_sol_runtime.py` adapter list is the union (`drive/port.py`, `gazebo_tools.py`, `sim_available.py`); `prompt.py` carries `_SIMULATION_NOTE` and main's drive/front-app wording.

### 17.3 Alembic

Two heads after the merge: main's `a31900000003` (revises `a32100000001` via `a31900000002`) and this branch's `a32200000003`. The no-op merge revision `a32200000004` (`down_revision = ("a31900000003", "a32200000003")`) joins them; `cd packages/api && uv run alembic heads` → `a32200000004 (head)` (re-checked in this task). The migration test files pass with the per-checkout URL inline: 58 passed on 5 of them during Phase A; in this task all 13 `tests/test_*migration*.py` files (the 9 that errored in §8, the 3 other pre-existing migration tests, and `test_academic_migration.py` from main) ran as one process with `SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2` inline: `114 passed in 198.34s`.

### 17.4 Fixed prompt re-measured (B2, `8d6aa964`)

The merged registry has 67 in-process tools (60 base + main's 4 `onshape.*` removal tools + `sim.available`, `sim.map_to_parts`, `sim.generate_model`) and both prompt additions (SOLUSDEV-319 drive/front-app notes, SOLUSDEV-322 `_SIMULATION_NOTE`). `test_the_default_fixed_part_tracks_what_the_runner_measures` measured 14,461 tokens, so `FIXED_PROMPT_TOKENS` 14,000 → 15,000 (`turn_limits.py:33`), the turn caps 46,000/62,000 → 47,000/63,000 (Guide/Build, `test_sol_turn_limits.py:20-21`), the default `max_input_tokens` 24,000 + 15,000 + 8 × 1,000 (`:42`), and `test_turn_budget.py:153` headroom 22,000/38,000 → 23,000/39,000. Per the P10 recon, `test_turn_budget.py` was red on `origin/main` itself: it pinned 21,000/37,000 against main's `FIXED_PROMPT_TOKENS` 14,000 (`git show 8bdf993e:packages/api/tests/test_turn_budget.py:153`, `…/turn_limits.py:32`); the merged values are consistent.

### 17.5 Decisions taken in chat (2026-11-10)

- **Exposure-internal AND name check.** Both sim companion allowlists declare the server-level `exposure: internal` (main's SOLUSDEV-319 loader; `docs/contracts/bridge-protocol.md`), and `runtime._internal_only` keeps dropping raw `gazebo.*`/`isaac.*` specs by server name as defence in depth. The raw-inventory tests build each spec with `internal=True` and `internal=False` and prove the owned wrappers register exactly once either way (`e5266473`).
- **Decision 2 kept.** An owned session (Solus started it) means zero cards in Guide and Build; the per-call `needs_confirmation` hook decides. Main's `DIRECT_WRITE_TOOLS` posture (a named list of always-refused-in-Guide tools) stays its own list beside the hook; no sim tool is added to it.

### 17.6 Tensions for humans

Recorded as §11 items 22 (APPROVAL_REQUIRED_LABEL vs. the owned-session no-card path), 23 (ADR-041 denylist does not name simulator GUIs; amendment sentence proposed there) and 24 (`with_front_app` rebuild vs. `sim.available` registry reference; harmless). A fourth observation needs no decision: `test_turn_budget.py` was red on `origin/main` itself (§17.4) and is now consistent.

### 17.7 What this record did not do

§8 and §9 carry the P10 suite rerun (P10-T3, B4; `docs/qa/acceptance/P8-suites.md` §"P10 rerun"). §12 values are unchanged by the merge.
