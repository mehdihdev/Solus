# REPO STATE — Robot Onboarding, Live Bench, Simulation Integration (read-only recon)

Date: 2026-11-08 · Source of truth: `origin/main` = `33e3bc08529b77efed9b1c788f06eba2ab3a716e` (2026-10-31) · alembic head `a32100000001` · Host: Linux aarch64, no hardware opened, no simulator launched, no provider called.

Method: every answer was read from code on this commit; `uv run python` imports were used to print registries, enums and schemas; docs under `docs/qa/` were used only as claims to verify and are cited as such. Seven parallel read-only agents each drafted one section; the coordinator spot-checked the key claims (tool registry, gates, `propose_motion` callers, Gazebo callers) against code before assembly. Paths are relative to the repo root; `wc -l` for every file named in sections C–E is in G5.

## Ten-line summary

1. **main HEAD** `33e3bc08` (SOLUSDEV-321 "sol checker algorithm", 2026-10-31); SOLUSDEV-320, 317 and all SOL-depth phases P0–P8 are on main; L1–L5 Live Bench landed with 262; Gazebo exists only as a read-only `gz topic` telemetry source; no doc on main names an "I5".
2. **Tests at HEAD on this box**: livebench 770 pass, companion 386 pass, libs 72 pass, desktop 5960 tests pass with one file failing on a missing `@sentry/electron` install; API 11,891 pass + 68 pass serially, 1 failure (workspace phase-3 lease test = an xdist worker crash, unclassified) and 62 setup errors that are all a missing `SOLUS_TEST_DATABASE_URL` in the migration tests (environmental). Wall: API 36.5 min at `-n 8`.
3. **SOL tool surface**: 62 in-process tools register for a project without a companion; **20** of them touch hardware/bench/telemetry/sim/findings (5 gated writes: `hardware.flash_presence`, `hardware.deploy_companion`, `set_hardware_config_field`, `bench.import_cad_scene`, `apply_sim_change`); up to 14 more appear only when a companion advertises them (8 `isaac.*`, 4 `code.arduino_*`, `code.ros2_nodes/topics`). Guide and Build see the same descriptors; Guide refuses gated calls at dispatch.
4. **Gates**: one fused dispatch closure (Build auto-run policy → park a card → `confirmation_refusal` fallback → invoke); approval replays STORED args; `force_confirmation` is a request flag the desktop sets for firmware turns. The motion gate `propose_motion` exists in `livebench/recognition/active.py` with **no production caller**.
5. **Onboarding gaps**: (a) the whole detect → propose → confirm chain (devices, topology extraction, host attachment, presence wiring, CAD suggestions, library import) is REST + UI only — SOL cannot enumerate, propose or confirm a device; (b) one identity per robot, tree-only topology, `host`/`mcu` brains only, no `onboard` writer, no multi-MCU robot representable, no clock alignment across brains; (c) no physical test (ping/jog/sweep/pin toggle) as tool or route, and the only board writer flashes Solus-generated presence firmware (dev-only, `arduino-cli` on PATH).
6. **Live Bench gaps**: (a) SOL cannot start/stop a session, list runs, open run packets or compare runs (only `get_run` summary, `get_finding`, `get_envelope`, `get_telemetry` ≤3600 s); (b) nothing is persisted beyond 512-sample rings except recorded Runs, and sim sessions never run the window evaluator; (c) "what changed" exists only as run-vs-run snapshot diffs — no commit/firmware/CAD-revision diff between two times; the Bench has no topology or sensor pane and the scene shows nothing for a part with no confirmed joint binding.
7. **Simulation gaps**: (a) no simulator exposes the user's own scenes/worlds — nothing lists, opens, or inserts into a user stage; Gazebo has no SOL tool, write path or world API; (b) sim packets are keyed `<scene>/<joint>` or a `gz` topic and nothing writes a part's `external_ref` to a sim joint, so sim and real do not resolve to the same part node; (c) Isaac is a companion-local stdio MCP fork reached only through the bridge, rung-3 jobs (MuJoCo/ngspice/mesh) need Redis and were never run live per the reports, and there is no URDF/MJCF *generation* from CAD (static scenes with candidate joints only).
8. **Hardcoded flows**: 97 fixed sequences catalogued (§F Q47) — 43 onboarding, 24 bench, 20 sim, 10 companion; 14 are fully SOL-callable today, 16 partially, 65 not at all, 2 are transport plumbing (n/a).
9. **Never live-verified** (per the repo's own reports, §F Q46): MuJoCo rung-3 trajectory job, ngspice job, Isaac rung 4, a real `.mcap` replay, any application-firmware flash, the two-arm hot-swap, the leader arm answering, the companion → `machine.tool_versions` → divergence path over a real bridge, every Electron-side Live Bench pane in the SOL-depth acceptance.
10. **Not determined** (3 items, all minor): whether `dynamixel-2` was ever exercised on real hardware (no report sentence either way); whether the FindingsPane "one stream per pane" pin (321:878) holds at runtime; the referent of the M149 "resolve on `recorded`" follow-up. Everything else has a code-backed status.

## Three biggest gaps per area (for planning)

| Area | Gap 1 | Gap 2 | Gap 3 |
|---|---|---|---|
| Robot Onboarding | No SOL tools for enumerate/propose/confirm — `GET /hardware/detected`, `POST …/propose`, `POST …/confirm` and the UI scheduler in `useDeviceProposals.ts` are the only path | Single-brain data model: `HardwareConfig.identity` is one `TransportBinding`; `read_topology` enforces a tree; `brain_kind="onboard"` has no writer | No motion/physical-test tool; `propose_motion` unwired; no clock alignment (`ts_us` since boot lands as 1970-era timestamps next to host-clock drivers) |
| Live Bench | SOL has read-only summaries (`get_run`, `get_finding`, `get_envelope`, `get_telemetry`) and cannot start/stop sessions or compare runs | Telemetry history = 512-sample rings + Runs; sim sessions have `robot_entity_id=None` so no evaluator, no findings | No time-to-time "what changed" (only run-vs-run snapshot diffs); scene mapping is a manual `PUT /mapping` per joint |
| Simulation | No access to the user's own scenes in any simulator; Gazebo is a `gz topic -e` subprocess with no SOL tool | Sim packets don't key to part nodes (`<scene>/<joint>` ids, no `external_ref` writer); Isaac listed by `/sources` but `available=False` forever | Rung-3/4 never run live; no CAD → URDF/MJCF generation (`joints: []`, candidate mates only, `mate_frame` unknown) |

## A. Baseline

### Q1: HEAD, log, alembic head, which ticket groups are on main
Status: exists
Where: `git log --oneline -40 origin/main`; `cd packages/api && uv run alembic heads`
Note: Local `main` tracks `origin/main` with no ahead/behind; `git fetch origin main` returned the same SHA. Everything below was answered against this commit.

```
HEAD = origin/main = 33e3bc08529b77efed9b1c788f06eba2ab3a716e   2026-10-31 19:16:22 +0000
alembic head = a32100000001 (head)
```

```
33e3bc08 SOLUSDEV-321: sol checker algorithm
177305ef SOLUSDEV-320: corrections to graph workspace
3d670036 SOLUSDEV-318: add capture-settings and app-version IPC
a821f1f2 SOLUSDEV-317: move code-server test fixtures out of conftest.py so mypy resolves the API conftest
da9204ff SOLUSDEV-313: ADR-023 clarification — staff limits_override merged per key over plan defaults
5360f2a5 SOLUSDEV-312: ADR-037 live channels (project, team, user change hints)
5a6ae0bc SOLUSDEV-311: accept client.error data events (closed, typed payload)
6b7faa19 Solusdev 262 livebench robo sol initial
7aadbb4f SOLUSDEV-400: add product showcase motion piece (orb morph, 12 bars @ 118 BPM)
52844231 SOLUSDEV-260: fix blank desktop window — rename deviceCard.ts to deviceCardRules.ts
09353979 add design stuff
2ffbf8b8 Solusdev 261 integration check
fb56b607 SOLUSDEV-300: rebuild the landing page from the Claude Design waitlist mock
de1eddd8 SOLUSDEV-260: 250-252, robot onboarding + graph + sol initial
1fa93715 SOLUSDEV-252: amend metadata-extraction contract — S-expression netlist...
3a90ab6f SOLUSDEV-249: INTEGRATIONS I2 — local folders as a graph source
02590af8 SOLUSDEV-244: ADR-034 amendment — root engineering preferences in ~/.solus/preferences.json
4fa1ce86 SOLUSDEV-248: physical robot node initial
d0737491 SOLUSDEV-242: Home as the cross-project surface — active-team project grid,...
3003d518 SOLUSDEV-242-test
22ca1688 SOLUSDEV-240: graph workspace w1
43e8a06e SOLUSDEV-241: CORPUS C1 — corpus scope, licensing policy, chunk schema
12d33aea SOLUSDEV-234: stop the desktop 429ing itself against the API
6c507dbb SOLUSDEV-235: EXT-05 bundle installer + developer mode
54179866 SOLUSDEV-167: featurescript mcp
37cc91ef SOLUSDEV-233: add filter-scoped total to activity feed meta
215b0f5c SOLUSDEV-167: governance gate — change-signal spine architecture + tier-1 doc amendments
72a96d15 SOLUSDEV-165: emit machine-readable connect stages; add cancel + result-returning connect hooks
c4430b2e SOLUSDEV-165: emit machine-readable connect stages; add cancel + result-returning connect hooks
0ddce887 SOLUSDEV-72: local source catalog + packet tap on the stream pump
2a0b9389 SOLUSDEV-165: emit machine-readable connect stages; add cancel + result-returning connect hooks
f9bf9b8e SOLUSDEV-64: retry Onshape 429s with bounded Retry-After backoff
c02bee00 SOLUSDEV-69: seed every env-sourced SecretStore ref via make seed-secrets
00d967ca SOLUSDEV-70: wire the graph screen — entity list, focus-driven inspector
ae8fe02c SOLUSDEV-69-orgy
a79aea83 SOLUSDEV-102: split project folder Open into VSCode and file-manager options
a9f3bca4 SOLUSDEV-114: fix Sources page crash on structured last_error
9506ac5e SOLUSDEV-136: CTR-08 extend Modality with hardware-recognition members...
af613d09 SOLUSDEV-222: worktree protocol, CODEOWNERS and the lane-ownership CI check
41cd8a35 SOLUSDEV-89: foundation-path E2E gate (signup→team→project→credited op)
```

Squash sizes of the recent landings (`git show --stat`): `33e3bc08` 544 files / +100,483; `177305ef` 401 files / +51,844 / −17,742; `3d670036` 84 files; `a821f1f2` 457 files / +79,557; `6b7faa19` (262) 517 files; `de1eddd8` (260) 694 files; `4fa1ce86` (248) 214 files.

| Ticket group | On main? | Evidence (code, not docs) |
|---|---|---|
| SOLUSDEV-320 graph workspace | **yes** | `177305ef` (the only 320 commit; the whole feature was squashed into it); `docs/qa/COMPLETION_SOLUSDEV-320-graph-workspace.md` landed with it |
| SOLUSDEV-317 command palette / command gate | **yes** | `a821f1f2`; `agent/command_gate.py`, `command_auto.py`, `command_policy.py`, `command_*.py` present; `features/palette/` on the desktop |
| SOL depth (SOLUSDEV-321) | **yes, all phases P0–P8** | `33e3bc08` squash. Every module the completion report names exists and is wired (§B Q8): `agent/turn_scope.py`, `deterministic.py`, `deterministic_facts.py`, `layers.py`, `project_card.py`, `livebench/findings/envelopes.py` + `rules/` + `window_evaluator.py`, `finding_narration.py`, `checkers/matrix_runner.py`, `simulation/sim_ladder.py` + `providers/`, `agent/vision/render_view.py`, `software/ros_reader.py`, `agent/reasoning_frame.py`, `routers/outcomes.py`, `routers/usage_turns.py` |
| Brain-centric onboarding | **partial** | `hardware_brain` / `hardware_bus` kinds (`graph/kinds.py:32-33`), `hardware/host_topology.py` (host brain confirm), `hardware/presence.py` (MCU presence firmware). Only `host` and `mcu` brains are ever written; no `onboard` writer; one identity per robot (§C Q11) |
| L1–L5 Live Bench tickets | **yes (all five present in code)** | Landed in `6b7faa19` (262). L1 saved connections without focus (`BenchScreen.tsx`, `SavedRobotConnections.tsx`), L2 CAD import (`livebench/scene/cad_import.py`), L3 units (`signalUnits.ts`, packet `units`), L4 deterministic findings (`window_evaluator.py`), L5 runs (`livebench/runs/`). Physical gates still unverified per the 262 report (§F Q46) |
| I5 server-side sim | **not determined as a ticket name** | No file under `docs/qa/` on main contains the token `I5` in a sim context (grep over the 321 completion, the sol-depth QA and the acceptance folder: zero hits). The server-side simulation that does exist is the P4 ladder: `simulation/providers/mujoco_job.py`, `mesh_job.py`, `ngspice_provider.py` as ARQ jobs (§E Q36, Q40) — never run live per the reports |
| Gazebo | **partial (read-only)** | `livebench/src/livebench/sim/gazebo_source.py` (139 lines) + `GazeboSimConnection` + `local.open_gazebo` → `POST /bench/sessions {provider:"gazebo"}` (§E Q35). From SOLUSDEV-121 (LB-01). No SOL tool, no write path, "live `gz sim` smoke NOT RUN" per that report |

### Q2: Test counts, wall time, red suites
Status: exists
Where: run on this host (Linux aarch64) at HEAD with `uv run pytest -q -p no:cacheprovider …` and `pnpm --filter @solus/desktop exec vitest run`; Postgres came from `docker compose -f docker-compose.dev.yml up -d db redis` (the dev containers had exited after a reboot; the per-worker `solus_test_<hash>_gwN` databases were used, the dev database was not touched).
Note: The first `-n 8` API run aborted at collection with "Different tests were collected between gw3 and gwN" — the known uuid4-parametrised ids in `packages/api/tests/test_cad_store.py`. The rerun below uses the same split the SOLUSDEV-321 FINAL tally used (two files excluded from xdist, then run serially).

| Suite | Command | Result | Wall |
|---|---|---|---|
| API (xdist) | `uv run pytest packages/api/tests -q -n 8 --ignore=…/test_cad_store.py --ignore=…/test_live_access.py` | `1 failed, 11891 passed, 13 skipped, 13 warnings, 62 errors in 2183.10s (0:36:23)` | 2190 s (36.5 min, -n 8) |
| API (the two excluded files, serial) | `uv run pytest -q packages/api/tests/test_cad_store.py packages/api/tests/test_live_access.py` | `68 passed in 19.85s` | 26 s |
| livebench | `uv run pytest livebench/tests -q -n 4` | `770 passed, 1 skipped in 13.00s` | 13 s |
| companion | `uv run pytest packages/companion/tests -q` | `386 passed in 8.10s` | 9 s |
| libs (solus-telemetry) | `uv run pytest libs -q` | `72 passed in 5.35s` | 6 s |
| desktop (vitest) | `pnpm --filter @solus/desktop exec vitest run` | `Test Files 1 failed \| 571 passed (572)`, `Tests 5960 passed (5960)` | 66.5 s |

Red:
- **desktop**: `src/main/diagnostics/sentrySink.test.ts` fails to load — `Error: Failed to resolve import "@sentry/electron/main" from "src/main/diagnostics/sentrySink.ts"`. `apps/desktop/package.json:31` declares `"@sentry/electron": "7.20.0"` but neither `apps/desktop/node_modules/@sentry` nor the root `node_modules/@sentry` exists in this checkout — an install gap on this box, not a code failure. Every other test file passes.
- **API first attempt**: xdist collection mismatch from uuid4 param ids in `test_cad_store.py` (environmental; see rerun row).
- **API rerun** (`1 failed, 11891 passed, 13 skipped, 62 errors in 2183.10s (0:36:23)`): all **62 errors** are `KeyError: 'SOLUS_TEST_DATABASE_URL'` at fixture setup in the ten `*_migration*.py` test files (the `migration_db` fixture reads the env var directly; CI sets it, this run did not) — environmental, not a code failure. The **1 failure** is `packages/api/tests/test_workspace_service_phase3.py::test_canceled_owner_does_not_reset_a_successor_source_or_release_lease` reported as `worker 'gw6' crashed while running …` (pytest-xdist marks a test whose worker process died as FAILED; no assertion text exists, `test_api2.log:2169`). Not re-run in isolation (one pytest process at a time on this box); treat as unclassified (worker crash under `-n 8`, possibly memory/timeout) until rerun. The two serially-run files: `68 passed in 19.85s`.
- `.claude/state/last_validation.md` (pre-existing, from a prior session) records a stale `ModuleNotFoundError: solus_api.software` at collection; `uv run` rebuilt `solus-api` at the start of this session and the module imports fine now.

### Q3: docs/qa files landed on main after 2026-10-17
Status: exists
Where: `git log --since=2026-10-17 --name-only --format='%h %cs' -- docs/qa` → 4 commits (`a821f1f2` 2026-10-21, `3d670036` 2026-10-22, `177305ef` 2026-10-25, `33e3bc08` 2026-10-31); 25 markdown files + 3 PNGs. `docs/qa/` holds 269 entries in total.
Note: No file name in `docs/qa/` carries a date after 2026-10-17; the list below is by commit date on main.

| Commit (date) | File (lines) | One-line summary (from the file head) |
| --- | --- | --- |
| `a821f1f2` (10-21) | `COMPLETION_SOLUSDEV-317-sol-command-execution.md` (88) | Completion report: SOL runs any user-approved command in an OS sandbox; branch cut from unpushed SOLUSDEV-216 head; 92 commits, 164 files |
| `a821f1f2` | `COWORK_QA_command-palette.md` (100) | QA plan for the ⌘K command palette (SOLUSDEV-317), governed by `docs/wireflows/command-palette.md` |
| `a821f1f2` | `COWORK_QA_github-org-member-assignment.md` (129) | QA: assigning GitHub org members to Solus teammates in the one-roster People table; assignment is a label, not a permission |
| `a821f1f2` | `COWORK_QA_github-orgs-in-teams.md` (192) | QA (SOLUSDEV-216): linking a GitHub organization to a team via the Solus GitHub App; repos, push-triggered syncs, suggested invites |
| `a821f1f2` | `COWORK_QA_sol-command-execution.md` (107) | QA (SOLUSDEV-317): approval card → sandboxed run → SOL reads the result |
| `3d670036` (10-22) | `COWORK_QA_settings-redesign.md` (120) | QA for the redesigned desktop Settings screen (SOLUSDEV-318) |
| `177305ef` (10-25) | `COMPLETION_SOLUSDEV-320-graph-workspace.md` (3207) | Completion: graph workspace off main `da9204ff`; every phase landed; §7 lists unverified items (companion machine PUT, flash, host confirm) |
| `177305ef` | `REPO_STATE_2026-10-17.md` (2215) | Read-only recon of origin/main at `da9204ff` (SOLUSDEV-313), checked against code; scope note says hardware add UI/cards will be redone |
| `177305ef` | `screenshots/solusdev-320-{edge-panel-candidate,powers-edge-panel,workspace-root}.png` | three workspace screenshots for the 320 report |
| `33e3bc08` (10-31) | `COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md` (983) | Completion: SOL DEPTH; P1–P8 accepted in-process with scripted adapters, 0 real-provider calls; FINAL Part A PASS at `67ec28a2`, Part B not authorised |
| `33e3bc08` | `COWORK_QA_sol-depth.md` (700) | QA plan for SOL DEPTH (SOLUSDEV-321); final HEAD `67ec28a2`, alembic head `a32100000001`; distinguishes server-live vs "Desktop surface NOT VERIFIED (Electron)" |
| `33e3bc08` | `RECON_SOLUSDEV-321-sol-checker-algorithm.md` (50) | P0.1 recon of `177305ef` before any 321 edit; covers the 317 `code.exec` family and command gate |
| `33e3bc08` | `COWORK_QA_compatibility_checkers_core.md` (160) | QA for the checker library (SOLUSDEV-115 / CHK-01): backend-only, no route, no UI — exercised through Python |
| `33e3bc08` | `COWORK_QA_i3-code-environment.md` (99) | QA for Integrations I3 "Code environment" (SOLUSDEV-250): requires the `code` fork and companion |
| `33e3bc08` | `COWORK_QA_model-routing-gateway.md` (247) | QA for model routing framework + gateway + provider adapters (SOLUSDEV-58 / MO-01…04); backend library, no routes |
| `33e3bc08` | `acceptance/P1-acceptance-live.md` (264) | P1 live proof: graph-grounded answers with 0 model calls, 0 credit delta |
| `33e3bc08` | `acceptance/P2-acceptance-live.md` (524) | P2 live proof: real-time replay of the fake arm, stall finding within 2 s, scripted narration |
| `33e3bc08` | `acceptance/P3-acceptance-live.md` (804) | P3 live proof: matrix checks in inline and ARQ sync modes, ONE worker; companion-scan form UNVERIFIED (M104) |
| `33e3bc08` | `acceptance/P4-acceptance-live.md` (752) | P4 live proof: simulation ladder dispatch, twin-compare, pre-check; rung-3 against real binaries NOT VERIFIED |
| `33e3bc08` | `acceptance/P5-acceptance-live.md` (869) | P5 live proof: perception/render_view with offscreen MuJoCo render, scripted vision adapter, Onshape mocked |
| `33e3bc08` | `acceptance/P6-acceptance-live.md` (1170) | P6 live proof: software readers (ROS 2 Jazzy at `/opt/ros/jazzy`), in-process companions with real allowlist |
| `33e3bc08` | `acceptance/P7-acceptance-live.md` (812) | P7 live proof: reasoning frame/citations through the production SSE route with scripted model text |
| `33e3bc08` | `acceptance/P8-acceptance-live.md` (853) | P8 live proof: outcomes/confirmations through production routes at alembic head `a32100000001` |
| `33e3bc08` | `acceptance/FINAL-acceptance-live.md` (89) | FINAL Part A at `3b0bf0e2`: steps 1–3, 5–9 verified, step 10 failed, Part B (real provider) NOT VERIFIED |
| `33e3bc08` | `acceptance/FINAL-acceptance-rerun.md` (86) | R169 re-run at `55d8b175`: step 10 FAILED on one test-side pin; 5 earlier regressions pass |
| `33e3bc08` | `acceptance/FINAL-tally.md` (51) | Final tally at `67ec28a2`: PASS; only failures are 2 pre-existing code-fork tests |

## B. SOL's tool surface


### Q4: Registered tool list from `build_sol_registry` + companion/MCP rosters
Status: exists
Where:
- `packages/api/src/solus_api/agent/runtime.py` (1726) — `build_sol_registry` :111–283, `_register_user_tools` :307–426, `_register_bridge_tools` :505–623, `_owned_machine_tool` :626, `_owned_isaac_tools` :637
- `packages/api/src/solus_api/agent/tools/registry.py` (163) — `ToolRegistry` (invoke never raises, :76–114)
- `packages/api/src/solus_api/deps.py` (589) — `get_sol_registry` :502–560, the ONE production call site
- `packages/api/src/solus_api/agent/modes.py` (98) — Guide/Build dispatch wrapper
- `packages/api/src/solus_api/bridge/allowlist.py` (276) — companion allowlist gate
- `integrations/mcp/*/allowlist.yaml` — 11 files (altium 63, autocad 473, brave 29, code 127, fusion 40, isaac 38, kicad 77, local 22, machine 36, solidworks 338)
Note: 62 in-process tools register for a project with connectors/systems/artifact store/secret store wired and no companion connected. Companion ("bridge") tools are added per turn from the LIVE hello inventory of the requesting user's companion, filtered by the Solus-owned allowlist; `requires_confirmation` comes only from the allowlist. There is no per-mode tool list: Guide and Build are offered the SAME descriptors; Guide REFUSES at dispatch any tool with `requires_confirmation=True` (so "gated" == "Build-only").

**Method used:** `cd packages/api && uv run python <script>` calling
`build_sol_registry(async_sessionmaker(), pid, user_id=…, team_id=…, secret_store=InMemorySecretStore(), connectors=ConnectorRegistry(), systems=MagicMock(spec=SolSystems), artifact_store=MagicMock(), enqueue=MagicMock(), presence_service=MagicMock(), companion_deployment_service=MagicMock(), scene_enqueue=MagicMock(), graph_hub=MagicMock(), enqueue_sim=MagicMock(), redis=MagicMock())`, then `registry.tools()` and `research.model_visible(registry.list())`. Output header: `COUNT 62 model_visible 62`.

**Guide/Build rule (verbatim, `agent/modes.py:70–97`):**
```python
    mutating = frozenset(d.name for d in descriptors if d.requires_confirmation)

    async def mode_dispatch(call: ToolCall) -> ToolResult:
        refused = mode is ActionMode.GUIDE and call.tool in mutating
        result = mode_refusal(call) if refused else await dispatch(call)
```
`routers/sol.py:1095` offers `descriptors = with_knowledge_notes(tuple(registry.list()), …)` to BOTH modes; `runtime.py:1237` `offered = await placed_tools(model_visible(ctx.tools), …)` removes only `SERVER_DRIVEN_TOOLS` (= `{"research"}`, `agent/research.py:76`). Prompt text differs only: Guide "Explain and use read-only tools; never execute changes." vs Build (`prompt.py:385–393`).

Legend: **G** = gated (`requires_confirmation=True`: parks a card in Build, refused in Guide); **U** = ungated (both modes). "cond." = registered only under the named condition.

#### 4a. In-process tools (the 62 printed by the import)

**Hardware**
| name | one line | gate | Guide/Build | module (class) |
|---|---|---|---|---|
| `hardware.flash_presence` | Flash a prepared presence plan onto its reviewed local MCU (plan_id) | G | Build | `agent/tools/firmware_presence.py` (`PresenceFlashTool`, `requires_complete_preview=True`, timeout 150) |
| `hardware.deploy_companion` | Deploy a reviewed offline companion bundle to its provisioned onboard target (plan_id) | G | Build | `agent/tools/companion_deployment.py` (`CompanionDeploymentTool`, timeout 300) |
| `set_hardware_config_field` | Set ONE scalar field of a Physical Robot's hardware config by dotted path | G | Build | `agent/tools/solus_tools.py:461` |
| `firmware_recipe` | Write firmware for one board from the topology; writes nothing, returns path+content for `machine.write_file` | U | both | `agent/firmware_recipe.py:112` (cond.: user+team+secret_store) |
| `get_machine` | Read one machine by companion id (hostname, OS, arch, tool versions; recent_commands owner-gated) | U | both | `agent/tools/machine_tools.py:182` |
| `get_environment_divergences` | Stored environment divergence table per machine | U | both | `agent/tools/machine_tools.py:203` |
| `code.resolve_environment` | Propose the project's Python environment(s) from dependency files | U | both | `agent/tools/environment.py:29` |
| `analyze_rail_current` | Declared current contributions for one electrical net | U | both | `agent/tools/rail_current.py:22` (cond.: systems) |
| `sourcing.derive_torque` | Static holding torque for a CAD assembly | U | both | `sourcing/tools.py:28` |
| `link_environment` | Record a workspace code environment into `.solus` (reads `code.probe_environment`) | G | Build | `agent/tools/solus_tools.py:494` — **cond.: NOT in the 62**; only when the live companion advertises `code.probe_environment` ungated (`runtime.py:592–603`) |

**Bench**
| name | one line | gate | Guide/Build | module |
|---|---|---|---|---|
| `get_run` | Recorded summary of one bench run (robot, origin, status, counts, baseline flag) — not the packets | U | both | `agent/tools/finding_tools.py:146` |
| `bench.list_cad_sources` | Scoped synced CAD scene sources and observed revisions | U | both | `agent/tools/bench_scene.py:83` |
| `bench.import_cad_scene` | Import CAD geometry as a static Bench model | G | Build | `agent/tools/bench_scene.py:89` (`CadImportTool`) |
| `bench.cad_import_status` | Progress / resulting model identity for a CAD import | U | both | `agent/tools/bench_scene.py:102` |

**Telemetry**
| `get_telemetry` | Per-signal stats bucketed over a window (≤3600 s) | U | both | `agent/tools/builtin.py:113` (cond.: systems) |

**Scene / sim**
| name | one line | gate | Guide/Build | module |
|---|---|---|---|---|
| `simulate` | Simulate ONE quantity of one entity; rung 1 in-process, rung 3 enqueued, rungs 2/4 name the gated tool | U | both | `agent/tools/simulate.py` |
| `get_sim_result` | Read one simulation result by id | U | both | `agent/tools/simulate.py:717` |
| `apply_sim_change` | Apply ONE change `simulate` dry-ran this turn | G | Build | `agent/tools/apply_sim_change.py` (`SimChangeTool`) |
| `run_checkers` | Cross-domain checkers + interaction-matrix dry run around anchors | U | both | `agent/tools/builtin.py:207` (cond.: systems) |

**Isaac** — none in the 62; exist only when the connected companion advertises the `isaac` server (`runtime.py:637–662`, `agent/tools/isaac_tools.py`, `IsaacTool`, `requires_complete_preview = name not in ("probe","status")`): `isaac.probe`, `isaac.status` (U) and `isaac.start`, `isaac.stop`, `isaac.load_model`, `isaac.set_joint_limits`, `isaac.set_sensor_pose`, `isaac.run_routine` (G, Build) — timeouts `isaac_tools.py:30–39`.

**Gazebo** — absent as a SOL tool. Gazebo exists only as a bench-session source kind (`livebench/src/livebench/local.py:290 open_gazebo`), never reaches the registry.

**Code**
| `read_code_file` | Bounded line-numbered read of a mentioned `code_file` (internally dispatches `machine.read_code_file` on the companion) | U | both | `agent/tools/read_code_file.py` (cond.: connectors) |
| `machine.write_file` | Create/edit one workspace text file with complete before/after preview | G | Build | `agent/tools/machine_writes.py:69` (`MachineWriteTool`) — **cond.: wraps the bridge tool, only with a companion** |

**Graph / search / perception**
| name | one line | gate | Guide/Build | module |
|---|---|---|---|---|
| `get_entity` | Fetch a graph entity by id | U | both | `agent/tools/get_entity.py:22` |
| `query_graph` | Neighbourhood around anchors (degree ≤2, domains closed enum excluding `workspace`) | U | both | `agent/tools/builtin.py:70` |
| `search_workspace` | Search graph entities by name/text/ref | U | both | `agent/tools/search_tools.py:125` |
| `search_corpus` | Shared engineering-practice corpus | U | both | `agent/tools/search_tools.py:146` |
| `get_history` | Project history newest first | U | both | `agent/tools/machine_tools.py:213` |
| `retrieve_errors` | Error/solution history similar to a query | U | both | `agent/tools/builtin.py:146` |
| `render_view` | One labelled render of an entity, answered by vision | U | both | `agent/vision/render_view.py:120` |
| `make_diagram` | Wiring / plug-in diagram into a TTL artifact | U | both | `agent/tools/make_diagram.py:43` (cond.: artifact_store) |
| `label_motifs` | Label unsettled netlist motifs (metered model call) | U | both | `agent/tools/label_motifs.py:98` |
| `read_document` | PDF datasheet page-by-page extraction with citations | U | both | `agent/tools/read_document.py:83` |
| `propose_part_definition` | File a candidate part definition into `.solus` | G | Build | `agent/tools/read_document.py:137` |
| `extract_rulebook` | Candidate numeric limits from a filed rulebook PDF | U | both | `agent/tools/rulebook_tools.py:121` |

**`.solus`**
| `add_solus_entry` | File a short note into a `.solus` section | U | both | `agent/tools/solus_entry.py:27` |
| `search_solus` | Search `.solus` entries | U | both | `agent/tools/search_tools.py:136` |
| `edit_solus_entry` | Replace a note's text | G | Build | `agent/tools/solus_tools.py:431` |
| `delete_solus_entry` | Remove an entry (irreversible) | G | Build | `agent/tools/solus_tools.py:448` |

**Findings**
| `get_finding` | One finding: headline, severity, status, rule, subjects, newest evidence | U | both | `agent/tools/finding_tools.py:137` |
| `get_envelope` | Operating envelope of ONE quantity of a part | U | both | `agent/tools/finding_tools.py:157` |

**Research**
| `research` | Web research loop over the vendored Brave fork | U | **neither (server-driven)** | `agent/tools/research_tool.py:207` — cond.: Brave tools discovered at request scope; in `SERVER_DRIVEN_TOOLS`, removed from the model's specs (`research.py:617`) and answered NOT_FOUND if the model names it (`research.py:622–637`) |

**Integrations / Onshape (in-process)**
| `solus.list_integrations`, `solus.verify_integration` | U | `agent/connect_integration.py:51,76` |
| `solus.connect_integration` | G | `agent/connect_integration.py:61` |
| `onshape.list_documents`, `.list_elements`, `.list_parts`, `.get_feature_tree`, `.get_feature_specs`, `.get_variables`, `.get_mass_properties`, `.get_part_bounds`, `.get_body_details`, `.get_assembly_definition`, `.inspect_assembly_geometry`, `.resolve_reference` | U | `agent/tools/onshape_tools.py` |
| `onshape.add_feature` | G (`InProcessTool`, NOT auto-run eligible) | `agent/tools/onshape_tools.py` |
| `onshape.create_circle_sketch`, `.extrude_cut`, `.set_variable`, `.update_feature`, `.insert_part`, `.create_face_mate_connector`, `.create_circle_mate_connector`, `.create_fastened_mate`, `.restore_fastened_pose`, `.create_revolute_mate` | G (`ConfirmedOnshapeTool`) | `connectors/onshape_confirmation.py` |

Also conditional, not in the 62: hosted vendor MCP tools (`_register_hosted_tools`, Onshape FeatureScript, stored inventory), first-party widget-bundle tools (`_register_bundle_tools`), and `code.ros2_nodes`/`code.ros2_topics` wrapped by `agent/tools/ros_live.py:30–33` when advertised.

#### 4b. Companion allowlists SOL can reach (parsed from `integrations/mcp/*/allowlist.yaml` with `yaml.safe_load`)

Bridge tools become `{server}.{tool}` descriptors (`allowlist.py:validate_inventory`). Never offered to the model: `machine.read_code_file` (internal to `read_code_file`) and any `returns_image` tool (`runtime.py:534–536`).

```
=== machine  launched_by=builtin  tools=4 gated=2
  read_code_file   ungated   (hidden from the model; used by read_code_file)
  read_file        GATED
  write_file       GATED files_errors   (wrapped as MachineWriteTool)
  tool_versions    ungated
=== code  launched_by=companion  tools=25 gated=15
  probe_environment · plan · git_status · git_log · git_diff (ungated) · arduino_probe t=15 ·
  process_status t=15 · profile_list t=15 · ros2_nodes t=30 · ros2_topics t=30
  GATED: create_environment t=630 · install t=630 · run t=630 · test t=630 · git_commit t=90 ·
  git_push t=120 · arduino_prepare t=630 · arduino_compile t=150 · arduino_upload t=150 · exec t=630 ·
  process_start t=30 · process_stop t=30 · profile_capture t=60 · profile_delete t=15 · process_input t=15
  (GATED code.* carry files_errors except process_*/profile_*)
=== local  launched_by=companion  tools=3 gated=1
  scan_folder ungated · folder_digest ungated · open_in_tool GATED
=== isaac  launched_by=companion  tools=8 gated=6
  probe ungated · status ungated · start GATED t=195 · stop GATED t=20 · load_model GATED t=165 ·
  set_joint_limits GATED t=25 · set_sensor_pose GATED t=25 · run_routine GATED t=55   (all gated: files_errors)
=== kicad  launched_by=companion  tools=18 gated=6
  get_symbol_definition · get_schematic_geometry · check_erc · list_projects · get_project_structure ·
  extract_project_netlist · analyze_schematic_connections · analyze_bom · export_netlist · export_spice_netlist (ungated)
  export_schematic_pdf · export_board_pdf  (ungated, returns_image → only via render_view)
  GATED: create_schematic · add_symbol · add_wire · add_net_label · mark_no_connect · set_symbol_property
=== altium  launched_by=companion  tools=11 gated=2
  app_get_status · proj_get_path · proj_list_documents · proj_get_stats · proj_get_bom · proj_get_nets ·
  proj_get_component_info · list_nets · export_netlist (ungated)
  GATED: proj_set_parameter · sch_set_components_parameters
=== autocad  launched_by=companion  tools=155 gated=155  (every entry GATED; reasons "TODO Solus-authored")
=== solidworks launched_by=companion  tools=62 gated=62  (every entry GATED, incl. reads like get_mass_properties)
=== fusion  launched_by=companion url=http://127.0.0.1:27182/mcp  tools=0
=== brave  launched_by=cloud  tools=4 gated=0
  brave_web_search · brave_llm_context · brave_news_search · brave_summarizer
  (API-spawned; only brave_web_search + brave_llm_context are driven, by the server-side `research` loop — research.py:81-82)
```

---

### Q5: Hardware capabilities — SOL tool vs REST vs UI
Status: partial
Where:
- `packages/api/src/solus_api/hardware/hardware_router.py` (1113) — prefix `/api/v1/projects/{project_id}/hardware`
- `packages/api/src/solus_api/livebench/bench_router.py` (737) — prefix `/api/v1/projects/{project_id}/bench`
- `packages/api/src/solus_api/livebench/runs/router.py` (423) — `/bench/runs`
- `packages/api/src/solus_api/livebench/stream.py` (261) — `WS /ws/v1/bench/sessions/{session_id}`
- `packages/api/src/solus_api/routers/findings.py` (200) — `/api/v1/projects/{project_id}/findings`
- `livebench/src/livebench/recognition/active.py` (156) — RBT-04 `propose_motion`, unwired
Note: SOL can READ almost everything (machine, run, finding, envelope, telemetry window) and can WRITE through exactly three gated hardware tools (`hardware.flash_presence`, `hardware.deploy_companion`, `set_hardware_config_field`). Device enumeration/proposal/confirmation, bench sessions, run capture/compare/baseline, and finding resolve/dismiss/acknowledge are REST + UI only. No physical-test tool (ping/pin toggle/jog/sweep) exists as a tool or route; the only "move something" code is RBT-04 `run_active_identification` in `livebench/src`, with no caller in the API or desktop.

| capability | SOL tool | REST route | UI flow |
|---|---|---|---|
| enumerate devices | absent (closest: `get_machine`; `search_workspace` kind filters) | `GET /hardware/detected` (:638 "Devices on this machine at whichever level is honestly known (opens no port)"); `GET /bench/telemetry-devices` (:196); `GET /hardware/parts` (:243); `GET /hardware/unassigned` (:579) | `features/graph/hardware/DevicesFound.tsx`, `PendingDeviceCards.tsx` |
| propose a device | absent | `POST /hardware/detected/{device_ref}/propose` (:645); `POST /hardware/robots/{robot_id}/topology/extraction/propose` (:343); `…/topology/host/propose` (:408); `…/presence/wiring/propose` (:1057) | `DeviceCard.tsx`, `robots/ExtractionReviewCard.tsx`, `robots/HostAttachmentCard.tsx`, `robots/PresenceWiringCard.tsx` |
| confirm a device | absent | `POST /hardware/detected/{device_ref}/confirm` (:687); `…/topology/host/confirm` (:430); `…/presence/wiring/{proposal_id}/accept` (:1086); `POST /hardware/robots/{robot_id}/parts/attach` (:596) | `DevicesFound.tsx:58 confirm(card.ref, input)`; `DeviceCard.tsx:157` |
| read a device's channels | partial: `get_entity` (attrs), `get_envelope` (one quantity), first-tier `_pins`/`_bus` intents (`deterministic.py:328,347`) | `GET /hardware/entities/{entity_id}/config` (:162); `GET /hardware/robots/{robot_id}/topology` (:333) | `robots/RobotTopologyGraph.tsx`; `bench/SignalWidget.tsx` |
| read latest telemetry | partial: first-tier `_latest` (`deterministic.py:276`, reads `facts.latest`); else `get_telemetry` short window | `GET /bench/recent/{entity_id}` (:201); `GET /bench/device-recent?device_id=` (:700) | `bench/DeviceBenchView.tsx`, `SignalWidget.tsx`, `BenchRealtime.tsx` |
| read a window of telemetry | `get_telemetry {duration_seconds ≤3600, signals}` (`builtin.py:113`) | `GET /bench/summary` (:219); `GET /bench/events` (:231) | `bench/BenchScreen.tsx` |
| start / stop a bench session | absent | `POST /bench/sessions` (:586), `GET /bench/sessions` (:654), `GET …/{id}` (:665), `POST …/{id}/stop` (:676); `WS /ws/v1/bench/sessions/{session_id}` (`stream.py:233`) | `bench/ConnectDeviceModal.tsx`, `SavedRobotConnections.tsx`, `useActiveBenchSessions.ts`, `benchStream.ts:7` |
| run a physical test (ping, pin toggle, jog, sweep) | absent | absent (grep jog/sweep/toggle over hardware/livebench: none) | absent. Only `livebench/src/livebench/recognition/active.py` exists; no caller outside its tests |
| flash firmware | `hardware.flash_presence {plan_id}` (G) — the ONLY executor; `code.arduino_upload` (bridge, G) for a workspace build | prepare only: `POST /hardware/robots/{robot_id}/brains/{brain_id}/presence/prepare` (:1019); `GET /hardware/presence/profiles` (:989); `POST /hardware/companion-deployments/prepare` (:1004). No REST route executes a flash | `robots/PresenceCard.tsx:120` sends a SOL message "Request the complete confirmation preview for hardware.flash_presence with plan_id … wait for my explicit confirmation before flashing." → `sol/ConfirmationCard.tsx` |
| read firmware / sketch | `read_code_file` (U); `firmware_recipe` reads the current file; `machine.read_file` (G) | none hardware-specific | `workspace/CodeEnvironmentModal.tsx` (environment, not sketch) |
| open a run | `get_run {run_id}` (U, summary only) | `GET /bench/runs/{run_id}` (:285); `GET /bench/runs` (:178); `POST /bench/runs` (:78); `POST /bench/runs/import` (:125); `POST …/{id}/stop` (:304); `GET …/{id}/findings` (:376); `POST …/{id}/narrate` (:394) | `bench/runs/RunsView.tsx`, `RunPlayback.tsx`, `RunEvidence.tsx`, `RunNarrationPanel.tsx` |
| compare runs | absent | `POST /bench/runs/compare` (:215; `baseline_id`, optional `sim_result_id`); `POST …/{id}/baseline` (:338) | `runs/runsApi.ts:206 compareRuns`, `RunsView.tsx` |
| read a finding | `get_finding {finding_id}` (U); findings layer; `finding_id` anchor | `GET /findings` (:113), `GET /findings/{finding_id}` (:139) | `bench/findings/FindingsPane.tsx`, `FindingCard.tsx`; "Explain more / Propose a fix" → SOL with `finding_id` (`findingActions.ts:2,56`) |
| raise a finding | absent | absent (only `/resolve` :146, `/dismiss` :180, `/acknowledge` :194). Raised only by `livebench/findings/window_evaluator.py` and `checkers/matrix_runner.py` | absent |

---

### Q6: Motion and write gates
Status: exists (write gates); partial (motion gate exists in code but is unwired)
Where:
- `agent/runtime.py` (1726) — `confirmation_refusal` :857, `gate_tool_call` :884, `build_dispatch` :901–975
- `agent/execution_policy.py` (227); `agent/command_auto.py` (136); `agent/confirmations.py` (783) — `request_confirmation` :491, `decide_confirmation` :554 (approval executes :664); `agent/modes.py` (98)
- `routers/sol.py` (1309) — `force_confirmation` body field :272, wired :1120
- `livebench/src/livebench/recognition/active.py` (156) — `propose_motion`
- `apps/desktop/src/renderer/src/features/sol/solApi.ts` (359) — :218/:233 send `force_confirmation`
Note: Every proposed call goes through ONE fused closure (`build_dispatch`): Build auto-run policy → park (card) → fallback flat refusal → invoke. `confirmation_refusal` is only the FALLBACK when no `park` is wired; the route always wires `park` (`sol.py:1049–1092`), so in production a gated call is parked, not refused. Auto-run (no card) is limited to owned routine families whose tool class AND name are on a code-owned list and whose two consecutive complete previews are identical.

**`confirmation_refusal` and the gate (verbatim, `runtime.py:857–898`):**
```python
def confirmation_refusal(registry: ToolRegistry, call: ToolCall) -> ToolResult | None:
    descriptor = next((d for d in registry.list() if d.name == call.tool), None)
    if descriptor is not None and descriptor.requires_confirmation:
        return ToolResult.failure(
            call.call_id,
            ToolError(
                code=ToolErrorCode.UNAUTHORIZED,
                message=(
                    f"{call.tool} is a destructive action requiring explicit user "
                    "confirmation; the confirmation flow is not yet available"
                ),
                retryable=False,
            ),
        )
    return None


async def gate_tool_call(
    registry: ToolRegistry, park: "ParkFn | None", call: ToolCall
) -> ToolResult | None:
    if park is None:
        return confirmation_refusal(registry, call)
    parked = await park(call)
    return None if parked is None else parked.result
```
Other references: `connectors/onshape_ops.py:101`, `agent/tools/onshape_tools.py:10` (comments), `confirmations.py:3` (docstring).

**`build_dispatch` order (verbatim core, `runtime.py:927–972`):**
```python
    async def gated(call: ToolCall) -> ToolResult:
        call = call.model_copy(update={"args": deepcopy(call.args)})
        automatic = await routine_policy.prepare(call) if routine_policy is not None else False
        if isinstance(automatic, ToolResult):
            return automatic
        if automatic is True:
            ...
            routine_policy.execution_started(call)
            result = routine_policy.finish(await registry.invoke(call))
            ...
            return result
        refusal = await gate_tool_call(registry, park, call)
        if refusal is not None:
            logger.info("tool call gated tool=%.128r call_id=%.128r parked=%s", ...)
            return refusal
        return await registry.invoke(call)
```

**Approval executes the STORED args (verbatim, `confirmations.py:655–664`):**
```python
    row.status = ConfirmationStatus.APPROVED
    await session.commit()

    # The STORED args, never anything the client sent with the decision.
    stored = ToolCall(tool=row.tool, args=dict(row.args), call_id=call_id)

    async def _approved(call: ToolCall) -> ToolResult:
        return await registry.invoke(call)  # the sanctioned post-approval site
```
Route `POST /api/v1/projects/{id}/sol/confirmations/{confirmation_id}` (`routers/sol_confirmations.py:285`). `CONFIRMATION_TTL = 30 min` (`confirmations.py:71`), ≤50 preview rows (:78), stale re-preview refusal (:636–650).

**Build auto-run lists (verbatim, `execution_policy.py:20–52`):**
```python
_ONSHAPE = frozenset(
    {
        "onshape.create_circle_sketch",
        "onshape.extrude_cut",
        "onshape.set_variable",
        "onshape.update_feature",
        "onshape.insert_part",
        "onshape.create_face_mate_connector",
        "onshape.create_circle_mate_connector",
        "onshape.create_fastened_mate",
        "onshape.restore_fastened_pose",
        "onshape.create_revolute_mate",
    }
)
_ISAAC = frozenset(
    {
        "isaac.start",
        "isaac.stop",
        "isaac.load_model",
        "isaac.set_joint_limits",
        "isaac.set_sensor_pose",
        "isaac.run_routine",
    }
)
# Reviewed native schemas, canonical JSON SHA256. A fork schema change requires
# review before automatic execution; it cannot expand its own authority.
_BRIDGE_SCHEMAS = {
    "kicad.set_symbol_property": "fe54d27bb16d416c581bd0e935214c727494cb19dde9118087f3a2b68ef95460",
    "kicad.create_schematic": "1abaefefb6d7b3d1ce1991a6f3cd9ae0866dbd5fb0e25b8d258967b624069697",
    "kicad.add_symbol": "5fefa1e99937b7296ba450416560c3dba64463169278ef49d5644b905c601069",
    "kicad.add_wire": "5e6e4a48cc7945f30ca4e991d6957455bf12b97cfa3369bd084819f4f8711b3a",
    "kicad.add_net_label": "a33b8244417c825119c92bbf85cb2ef83dd4063af4eeb948ff2cc57dc3b50b49",
    "kicad.mark_no_connect": "17ad67f23274702a4adf46d6a03f140a7465c8fa448dfd4d79f379be357bff81",
    "code.git_commit": "4e10d162cd7921a0ea88d7b2440421d2818da182c2d82cc0b07ad863d4195665",
}
```

**`AUTO_TOOLS` (verbatim, `command_auto.py:30–36`):**
```python
AUTO_COMMAND_TOOL: Final = "code.exec"
#: §11.2: a bare Enter to a waiting interactive process may skip its card.
AUTO_INPUT_TOOL: Final = "code.process_input"
#: The code-owned tools Build may run without a card, each re-judged per call.
AUTO_TOOLS: Final = frozenset({AUTO_COMMAND_TOOL, AUTO_INPUT_TOOL})
#: The only `code.plan` `program_scope` that may skip the card (§10.1).
SYSTEM_SCOPE: Final = "system"
```

**Eligibility marking (verbatim, `execution_policy.py:59–88`):**
```python
def register_owned_routine(tool: Tool, *, family: str) -> None:
    """Called only by trusted assembly, after scope and implementation binding."""
    ...
    name = tool.descriptor.name
    eligible = (
        (family == "onshape" and type(tool) is ConfirmedOnshapeTool and name in _ONSHAPE)
        or (family == "isaac" and type(tool) is IsaacTool and name in _ISAAC)
        or (family == "machine" and type(tool) is MachineWriteTool and name == "machine.write_file")
        or (family == "command" and type(tool) is PlannedTool and name in AUTO_TOOLS)
    )
    if family == "bridge" and type(tool) is BridgeTool and name in _BRIDGE_SCHEMAS:
        digest = hashlib.sha256(_canonical(tool.descriptor.params).encode()).hexdigest()
        eligible = digest == _BRIDGE_SCHEMAS[name]
    if (
        eligible
        and tool.descriptor.requires_confirmation
        and getattr(tool, "requires_complete_preview", False) is True
        and callable(getattr(tool, "preview", None))
    ):
        owned: Any = tool
        owned._build_authority = _AUTHORITY, _canonical(tool.descriptor.model_dump())
```
Hardware/sim tools on the auto-run list: `machine.write_file`, the six `isaac.*` writes, the ten `onshape.*` `ConfirmedOnshapeTool`s, six `kicad.*` writes + `code.git_commit` (schema-pinned), `code.exec`/`code.process_input` (per-call `auto_judge`). **NOT** auto-run eligible, always a card: `hardware.flash_presence`, `hardware.deploy_companion`, `bench.import_cad_scene`, `apply_sim_change`, `set_hardware_config_field`, `onshape.add_feature`, every `.solus` write, `code.arduino_upload`, `code.run/test/install`, `code.git_push`, `machine.read_file`.

**`prepare` — `force_confirmation` and routed-turn exceptions (verbatim, `execution_policy.py:119–165`):**
```python
    async def prepare(self, call: ToolCall) -> bool | ToolResult:
        from solus_api.agent.firmware_recipe import routed_by_firmware
        from solus_api.agent.tools.apply_sim_change import routed_by_simulation

        forced = (
            self._force_confirmation
            or routed_by_simulation(call.tool)
            or routed_by_firmware(call.tool)
        )
        tool = None if forced else self._owned(call)
        if tool is None:
            return False
        command = call.tool == AUTO_COMMAND_TOOL
        if call.tool in AUTO_TOOLS and not auto_judge(call.tool, call.args):
            return False
        claimed = self._claim(tool, call)
        if not isinstance(claimed, str):
            return claimed
        quota_failures: list[str] = []
        before = await _build_preview(
            tool, deepcopy(call.args), force_complete=True, quota_failures=quota_failures
        )
        scopes = [_program_scope(tool, call.args)]
        if not before:
            return _refuse(call, quota_failures[0] if quota_failures else
                "The complete routine preview is unavailable. Nothing was executed.", ToolErrorCode.UNAVAILABLE)
        after = await _build_preview(
            tool, deepcopy(call.args), force_complete=True, quota_failures=quota_failures
        )
        scopes.append(_program_scope(tool, call.args))
        if quota_failures:
            return _refuse(call, quota_failures[0], ToolErrorCode.UNAVAILABLE)
        if not after or before != after:
            return _refuse(call, "The routine changed during validation. Nothing was executed; inspect current state.")
        if command and scopes != [SYSTEM_SCOPE, SYSTEM_SCOPE]:
            self._deferred.add(claimed)
            return False
        return True
```
`force_confirmation`: request body `MessageIn.force_confirmation: StrictBool = False` (`sol.py:272`) → `sol.py:1120` `BuildExecutionPolicy(registry, body.action_mode, force_confirmation=body.force_confirmation)`; desktop sets it only for "confirmation-required" turns (`solApi.ts:218,233`), e.g. `PresenceCard.tsx:120`. `routed_by_simulation` (`apply_sim_change.py:308`) and `routed_by_firmware` (`firmware_recipe.py:128`, `_ROUTED` OrderedDict of turn ids) keep the card on a write that `simulate`/`firmware_recipe` routed to this turn.

**Guide refusal (verbatim, `modes.py:43–57`):**
```python
def mode_refusal(call: ToolCall) -> ToolResult:
    return ToolResult.failure(
        call.call_id,
        ToolError(
            code=ToolErrorCode.UNAUTHORIZED,
            message=(
                f"{call.tool} changes the connected tool. Guide mode can explain "
                "the change; switch to Build mode to carry it out. "
                "Actions needing approval will still ask."
            ),
            retryable=False,
        ),
    )
```

**`propose_motion` (verbatim, `livebench/src/livebench/recognition/active.py:72–93`; only caller :128):**
```python
def propose_motion(plan: MotionPlan) -> ToolConfirmationEvent:
    """The gate payload: the exact motion, visible before anything moves."""
    return ToolConfirmationEvent(
        confirmation_id=uuid.uuid4().hex,
        tool="active_identification",
        args={
            "actuator": plan.actuator,
            "magnitude": plan.magnitude,
            "duration_seconds": plan.duration_seconds,
        },
        summary=(
            f"Command a bounded identification motion: {plan.actuator} to "
            f"{plan.magnitude} (normalized) for {plan.duration_seconds}s"
        ),
        preview=[
            DiffRow(
                label=f"commanded value on {plan.actuator}", before="0", after=str(plan.magnitude)
            ),
            DiffRow(label="duration", before=None, after=f"{plan.duration_seconds}s"),
        ],
    )
...
async def run_active_identification(plan, *, command, capture, approval) -> ActiveIdResult:
    event = propose_motion(plan)
    if not await approval(event):
        return ActiveIdResult("refused", None, 0.0, {}, None)
    baseline = await capture(plan.duration_seconds)
    await command(plan)
```
Bounds `MAX_MAGNITUDE = 0.2`, `MAX_DURATION_SECONDS = 5.0` (:33–34). **Who calls it: nobody in production.** grep over `packages/api/src`, `apps/desktop/src`, `livebench/src` hits only this file (+ `livebench/tests/lb_active_test.py`). `approval` is a plain callable; the module docstring says the real approval surface is "unmerged (SOLUSDEV-60)". Not a `Tool`, not in any registry, no `ToolConfirmation` rows.

---

### Q7: Context assembly for a SOL turn
Status: exists
Where:
- `agent/runtime.py` (1726) — `LlmRunner.run` :1212–1400
- `agent/layers.py` (237); `agent/context.py` (762) `build_context` :588–686; `agent/turn_scope.py` (570); `agent/project_card.py` (470); `agent/solus_layer.py` (471); `agent/sol_anchors.py` (161); `agent/turn_limits.py` (98); `agent/turn_budget.py` (85); `agent/turn_context.py` (140)
- `orchestration/models.yaml` (564) — `context_budget:` :412–426
- `routers/sol.py` (1309) — :1128–1220 fills `AgentRunContext`
Note: Eleven layers in a prefix-stable order, each capped by a share of a per-tier total. Focus, pins, the finding and the active bench robot DO enter: typed anchors to the scope planner (`ScopeInputs`), whose ONE graph pull becomes the graph layer and whose anchors drive the `.solus`-scoped, findings and envelope sections. The project card is a cached layer-2 section (≤300 tokens).

**Order inside `LlmRunner.run`:** system prompt (:1226) → `placed_tools(model_visible(ctx.tools))` (:1237) → `fixed_tokens` measured (:1245) → `resolve_anchor_inputs(focus, finding_id)` (:1249) → `round_one_complexity(about_finding=…)` (:1254) → tier (:1259) → `TurnBudget(turn_limits(mode, tier, fixed_tokens))` (:1264) → `plan_scope(ScopeInputs(message, tier, mentions, pins, focus, robot_id, finding_subjects, history_entity_ids, not_visible), search=index_search, load=systems.get_graph_context, disambiguate=HARD-only)` (:1268) → `answer_first_tier` (:1297; skipped on `/web`) → `ResearchStep` (:1304) → `build_context(graph=scope.graph, window=scope.window, budget=scope.budget, research=step.digest, sessionmaker, practice_question)` (:1316) → `round_one_complexity(about_finding=context.finding_in_scope)` (:1341) → `_with_screen_read` (:1342) → `.with_conversation().with_anchors().with_card(project_card_section(...))` (:1345–1352) → `AgentEvent.context_used(manifest)` (:1360) → rounds with `with_perception(with_turn(withhold_server_driven(ctx.dispatch)))` (:1389).

**Layer list (verbatim, `layers.py:54–66`):**
```python
LAYER_ORDER: Final[tuple[LayerKind, ...]] = (
    "preferences",
    "project_card",
    "solus_standing",
    "graph",
    "solus_scoped",
    "findings",
    "conversation",
    "retrieval",
    "corpus",
    "telemetry",
    "screen",
)
```
Section kinds → layers (`layers.py:87–101`): `project_card`; `solus_standing`/`solus` → `solus_standing`; `graph`; `solus_scoped`; `finding`,`envelope` → `findings`; `error`,`document`,`research` → `retrieval`; `corpus`; `telemetry`; `screen`.

**Default per-layer caps (verbatim, `layers.py:112–122`):**
```python
    preferences: int = Field(default=800, gt=0)
    project_card: int = Field(default=400, gt=0)
    solus_standing: int = Field(default=600, gt=0)
    graph: int = Field(default=1200, gt=0)
    solus_scoped: int = Field(default=400, gt=0)
    findings: int = Field(default=600, gt=0)
    conversation: int = Field(default=6000, gt=0)
    retrieval: int = Field(default=1200, gt=0)
    corpus: int = Field(default=4000, gt=0)
    telemetry: int = Field(default=600, gt=0)
    screen: int = Field(default=600, gt=0)
```
**Per-tier totals and shares (verbatim, `models.yaml:412–426`), applied by `LayeredContextBudget.for_tier` (`layers.py:136–146`, `cap = round(total * share)`):**
```yaml
context_budget:
  trivial: 8000
  standard: 24000
  hard: 60000
  layer_scale:
    preferences: 0.2
    project_card: 0.1
    solus_standing: 0.15
    graph: 0.3
    solus_scoped: 0.1
    findings: 0.15
    conversation: 1.5
    retrieval: 0.3
    corpus: 1.0
    telemetry: 0.15
```
(`screen` share at :427, outside my paste window.)

**Turn ceilings (verbatim, `turn_limits.py:16–17, 34, 56–66`):**
```python
GUIDE_MODEL_ROUNDS: Final = 5
GUIDE_TOOL_CALLS: Final = 8
FIXED_PROMPT_TOKENS: Final = 13_000
_MODE_CEILINGS: Final = {
    ActionMode.GUIDE: (GUIDE_MODEL_ROUNDS, GUIDE_TOOL_CALLS, 120.0, 6),
    ActionMode.DO: (16, 24, 300.0, 18),
}
_WEB_CAPS: Final = {
    Complexity.TRIVIAL: (1, 2),
    Complexity.STANDARD: (1, 2),
    Complexity.HARD: (3, 4),
}
```
`max_input_tokens = context_budget.total_for(tier) + fixed_tokens + tool_calls × tokens("x"*TOOL_RESULT_CAP)` (:84–96). `TurnBudget.check()` order: `tool_calls, model_calls, web_searches, web_fetches, input_tokens, model_rounds` (`turn_budget.py:66–85`).

**Scope planner knobs (verbatim, `turn_scope.py:99–111`):**
```python
MAX_SCOPE_TOKENS: Final = 8
MAX_TOKEN_CHARS: Final = 255
HITS_PER_TOKEN: Final = 5
MIN_HIT_SCORE: Final = 0.45
MAX_IMPLICIT_ANCHORS: Final = 5
INDEX_HITS: Final = 10
MAX_SCOPE_ENTITIES: Final = 60
PLANNER_MAX_TOKENS: Final = 64
_DEPTH: Final = 1
_HARD_DEPTH: Final = 2
_TELEMETRY_WINDOW_SECONDS: Final = 120.0
```
Anchors in blame order (docstring :8–11): focused entity, mentions, pins, a finding's subjects, the bench robot, pasted UUIDs, then message names, then the focus trail. Telemetry layer requested (120 s) only when domain weights include `runtime`. `history_entity_ids` are hints only.

**Where focus/pins/finding/robot come from:** body → `sol.py:1141–1144` (`focus=body.focus, pins=tuple(body.pins), finding_id=body.finding_id, robot_id=body.robot_id`); pins validated like mentions (409), finding/robot must be this project's (404) `sol.py:1024–1027`; a stale focus id is dropped by the runtime. Desktop: `solApi.ts:201–202`; findings pane anchors on `finding_id` (`findingActions.ts`).

**Project card:** `card_inputs(session, project_id, user_id, live=bridge.get(...), cache=app.state.project_card_cache, sessions=bench_sessions, connectors)` `sol.py:1101–1109`; `CARD_MAX_TOKENS = 300`, `CACHE_TTL_SECONDS = 600` (`project_card.py:48–49`); content: project name, physical robots, sources+capabilities, `.solus` counts, open-finding counts, budgets line, active bench sessions, caller's own live machine.

**`.solus`/findings in context (`solus_layer.py:1–20`):** standing goals/constraints + budgets (`solus_standing`), `errors` entries blaming a part in scope (`solus_scoped`), open findings observing a part in scope + up to four envelope lines per part (`findings`), relevant `.solus` hits + environment-divergence table (`retrieval`). A non-info finding in scope sets `Context.finding_in_scope` → round 1 HARD.

---

### Q8: Deterministic tier, scope planner, envelopes, narration (SOL depth P0–P3)
Status: exists
Where (all present on HEAD with the stated roles):
- P0 — `agent/layers.py` (237), `agent/project_card.py` (470), `agent/solus_layer.py` (471), `agent/sol_anchors.py` (161)
- P1-T1 scope planner — `agent/turn_scope.py` (570) `plan_scope` :215
- P1-T2 deterministic tier — `agent/deterministic.py` (785) `answer_first_tier` :148, `INTENTS` :595; `agent/deterministic_facts.py` (428) `FactSources` :139, `GraphFactSources` :187
- P1-T3 — `agent/turn_budget.py` (85), `agent/turn_limits.py` (98), `agent/turn_context.py` (140)
- P1-T4 — `agent/tools/finding_tools.py` (166), `machine_tools.py` (237), `search_tools.py` (155)
- P1-T5 — `agent/research.py` (795), `agent/tools/research_tool.py` (226)
- P2-T1 envelopes — `packages/api/src/solus_api/livebench/findings/envelopes.py` (770)
- P2 rules/evaluator — `packages/api/src/solus_api/livebench/findings/window_evaluator.py` (765), `livebench/findings/rules/`
- P2-T6 narration — `agent/finding_narration.py` (633) `Narrator` :435; `packages/api/src/solus_api/livebench/runs/narration.py` (119)
- P3 — `checkers/matrix_runner.py` (744) `judge_matrix` (called from `builtin.py:224`)
- P4 `agent/tools/simulate.py` (740), `apply_sim_change.py` (792); P5 `agent/vision/render_view.py` (422); P6 `agent/firmware_recipe.py` (422), `agent/tools/ros_live.py` (128); P7 `agent/reasoning_frame.py` (186); P8 `routers/outcomes.py` (84), `routers/usage_turns.py` (87)
Note: `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md` §1 claims P0–P8 + fix wave landed (`COWORK_QA_sol-depth.md` headed `final HEAD 67ec28a2`); HEAD 33e3bc08 ("SOLUSDEV-321: sol checker algorithm") contains every module the claims name, wired as described. Path correction vs the question: `envelopes.py` and `narration.py` live under `packages/api/src/solus_api/livebench/`, NOT the top-level `livebench/` package (which has no `findings/` or `runs/` dirs).

**Deterministic tier (verbatim docstring, `deterministic.py:1–10`):**
```
`answer_first_tier` runs after the scope planner and before any prompt renders. It matches the
message against `INTENTS` — eleven shapes, each a pattern the whole message must match and a
handler — and answers from the planned scope (`TurnScope.graph`, the ONE pull) and the
`FactSources` seams (`agent/deterministic_facts.py`, every read scoped to the project). Nothing
here calls a model (tests/test_model_call_sites.py, comments included). It never guesses: ...
the turn falls through to the model with the same scope. Expert mode gets the fact alone; Guide mode gets it and one fixed sentence on where
it comes from (`_GUIDE_NOTES`, CLAUDE.md §2 item 5).
```
Handlers (`deterministic.py:233–553`): `_limit`, `_latest`, `_related`, `_pins`, `_bus`, `_host`, `_conversion`, `_budget`, `_findings`, `_errors`, `_history`, `_here`, `_status`, `_count`. `MAX_LOOKUP_CHARS = 200`. Entry `runtime.py:1297` (`if ctx.facts and ctx.research_query is None`); an answered turn streams `context_used` + `answer_source("graph", …)` + `message`, no tool frame (`first_tier_events` :190–212). `GraphFactSources` bound at `sol.py:1157–1163` with telemetry plumbing and bench sessions.

**Envelope logic (verbatim docstring, `livebench/findings/envelopes.py:6–13`):**
```
**Sources**, highest first — a slot is owned by the first source that states it:
1. the part's own config limits (`PartConfig.limits.values` ...), source `config`, confidence 1.0
2. the part's library definition (`PartLimitsSpec`), `definition`, 1.0
3. the scene joint the part is bound to (`lower` / `upper`), `scene`, 1.0
4. a simulation's expected value (`attrs.expected[quantity]`, written by P4), `sim`, 0.8
5. what a baseline run measured on the part's channel (p1 / p99), `learned`, 0.6
```
`warn` derived from `envelopes.warn_fraction` (models.yaml). Consumers: P2 rules, `get_envelope`, `envelope` sections of the findings layer, narration packet.

**Narration — two model paths:** `agent/finding_narration.py` `Narrator` (:435): bound as a bench session's `on_raised`; debounce 10 s, ≤1 call/robot/60 s, ≤8 findings/packet, JSON array reply, `grounded_numbers` check, writes via `annotate_finding`, billed to session owner (`purpose="narration"`). `livebench/runs/narration.py` (119): `POST /bench/runs/{id}/narrate`, `_MAX_BATCH = 32`, digit-banning `_UNSAFE_PROSE`; "deterministic findings remain authoritative". Matrix: `run_checkers` folds `judge_matrix(context, facts).warnings` as a dry run (`builtin.py:220–226`).

---

### Q9: How SOL calls companion tools
Status: exists
Where:
- API: `routers/bridge.py` (761) — `WS /api/v1/projects/{project_id}/bridge` :624, `_frame_loop` :569, `_handle_parsed` tool_result :533–540; `bridge/frames.py` (344); `bridge/allowlist.py` (276); `bridge/service.py` (484) `dispatch` :205, `ingest_result` :272; `bridge/tool.py` (172); `bridge/registry.py` (113); `bridge/previews.py` (175); `agent/runtime.py` `_register_bridge_tools` :505
- Companion: `packages/companion/src/solus_companion/channel.py` (350) `_recv_loop` :129; `dispatch.py` (341) `Dispatcher` :133; `supervisor.py` (477) `call_tool` :371; `frames.py` (222) :171–188; `machine/server.py` (274); `machine/actions.py` (60); `machine/code_reader.py` (139)
- Rosters: `integrations/mcp/<server>/allowlist.yaml`; `integrations/mcp/README.md` (264) :109–139; `integrations/mcp/CLAUDE.md` (27) rule 2; `integrations/mcp/kicad/solus/roster.py` (66)
Note: One WebSocket per (user, team, project) from companion to API, JSON frames `{"type","data"}`. The companion's `hello` advertises servers+tools; the API keeps only allowlisted ones and builds a `BridgeTool` per entry per SOL turn. A SOL call becomes a `tool_call` frame; the companion routes `{server}.{tool}` to a builtin server (`machine`) or an MCP child process, answers with one `tool_result` frame; the API redacts and resolves the waiting future; errors come back as `ToolException` → `ToolResult(ok=False)`.

**Transport/frames.** Outbound (API→companion): `hello_ack, pong, tool_call, credential_ack, artifact_fetch` (`frames.py:185`). Inbound: `hello, ping, status, error, tool_result, tool_output, credential_submit, change, artifact_chunk` (:169–183; payload models :243–254). Caps: control frames ≤ `bridge_control_frame_max_bytes`, `tool_result` ≤ `bridge_tool_result_max_bytes`, hello its own cap (`parse_frame` :279–311). Per-session `max_inflight` slots; `entered >= max_inflight*2` → "bridge busy" (`service.py:215`).

**Allowlist gate (verbatim, `frames.py:53–63`):**
```python
class HelloTool(BaseModel):
    """One tool a companion advertises. UNTRUSTED — deliberately has no
    `requires_confirmation` field: that flag comes only from the Solus-owned
    allowlist, and a companion asserting it fails `extra="forbid"`."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    description: str = ""
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
```
`validate_inventory(hello, allowlist)` (`allowlist.py:229–276`) builds `ToolDescriptor(name=f"{server}.{tool}", description=tool.description[:UNTRUSTED_TEXT_CAP], description_trusted=False, consent_summary=allowed.reason, params=tool.input_schema, timeout_seconds=allowed.timeout_seconds, requires_confirmation=allowed.requires_confirmation, files_errors=allowed.files_errors)`; rejects unsafe names, oversized/unsafe schemas, duplicates, non-allowlisted tools.

**Adding a new companion tool (what the code requires):**
1. The server must advertise it in `hello` (`MachineServer.inventory()` `server.py:187–197` for the builtin; a fork's registration shim, e.g. `kicad/solus/roster.py` `EXPOSED_UPSTREAM_TOOLS`).
2. An entry in `integrations/mcp/<server>/allowlist.yaml` (`name`, `requires_confirmation`, `reason` mandatory on gated entries, optional `timeout_seconds ≤ 900`, `files_errors`, `returns_image`); `ServerAllowlist` is `extra="forbid"`. Per `integrations/mcp/CLAUDE.md:10–11` adding a tool to an existing allowlist is a human decision (agents may only draft).
3. For a complete before/after card: add the composed name to `_COMPLETE_PREVIEW_TOOLS`/`_DRY_RUN_TOOLS` (`allowlist.py:37–59`) and have the companion honour `dry_run: true`.
4. To ever auto-run in Build: its reviewed param-schema SHA256 in `_BRIDGE_SCHEMAS` (`execution_policy.py:42–50`).
5. For streaming/long `code.*` tools: `STREAMING_TOOLS` (service.py) and companion `STREAMING_CODE_TOOLS`.

**End-to-end example: `machine.tool_versions` (ungated, builtin server)**

(1) API-side tool — built per turn from the live inventory (`runtime.py:537–561`):
```python
        tool = BridgeTool(
            descriptor=spec.descriptor,
            sessions=bridge,
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
            call_cap_bytes=bridge_call_cap_bytes,
            preflight=preflight,
            preview=preview_builder(
                spec.descriptor.name,
                _bridge_reader(bridge, user_id, team_id, project_id, bridge_call_cap_bytes, preflight),
            ),
        )
```
Descriptor `description` = companion's "Report `--version` of a fixed list of developer tools on this machine (argv only)." (`server.py:140–145`), `params` = `ToolVersionsArgs.model_json_schema()` (no args), `requires_confirmation=False` from `integrations/mcp/machine/allowlist.yaml`.

(2) SOL proposes `{"tool":"machine.tool_versions","args":{}}` → `build_mode_dispatch` → `build_dispatch.gated` → not auto-run, not gated → `registry.invoke` → `BridgeTool.invoke` (`bridge/tool.py:139–152`):
```python
    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._preflight is not None:
            await self._preflight()
        session = self._sessions.get(self._user_id, self._team_id, self._project_id)
        if session is None:
            raise ToolException("bridge offline", code=ToolErrorCode.UNAVAILABLE, retryable=True)
        result = await dispatch(session, self._descriptor.name, args, call_cap_bytes=self._call_cap_bytes)
        if result.ok and result.value is not None:
            return result.value
        if result.error is not None:
            _raise_companion_error(self._descriptor.name, result.error)
```

(3) Wire — `service.py:205–249` mints a NEW wire `call_id` (SOL's never crosses), sends `tool_call_frame(call)` = `{"type":"tool_call","data":{"tool":"machine.tool_versions","args":{},"call_id":"<wire id>"}}` (`frames.py:330`), registers a future in `session.inflight[call_id]`; bounded by the registry's `asyncio.wait_for` (default 30 s; allowlist `timeout_seconds` overrides, `registry.py:95–98`).

(4) Companion — `channel.py:_recv_loop` → `parse_inbound` → `ToolCallIn` → `Dispatcher.handle_tool_call` (one task per call, duplicate call_id dropped, `dispatch.py:153–164`) → `_execute` (`dispatch.py:166–200`) splits `"machine.tool_versions"` → `supervisor.call_tool("machine","tool_versions",{})` (`supervisor.py:371–386`):
```python
        builtin = self._builtins.get(server)
        if builtin is not None:
            if tool not in builtin.tool_names:
                raise UnknownToolError(f"unknown tool {server}.{tool}")
            return await builtin.call_tool(tool, args)
```
→ `MachineServer.call_tool` (`server.py:203–222`): Pydantic-validates args (`extra="forbid"`), runs `_HANDLERS["tool_versions"]` = `_tool_versions` (`server.py:246–267`: `which()` each `DEFAULT_VERSION_BINARIES`, `[exe, "--version"]` argv-only, redacted line, absent binaries omitted) → `_ok_result({"tool_versions": {...}})` = `CallToolResult(structuredContent=value)`.

(5) Reply — `map_result` (`dispatch.py:75–99`): `structuredContent` dict → `tool_result_ok(call_id, value)` = `{"type":"tool_result","data":{"call_id":…,"ok":true,"value":{…}}}` (`frames.py:171`); sent by `Dispatcher._run` ("never send after a disconnect").

(6) API ingest — `_frame_loop` → `parse_frame` → `_handle_parsed` (`routers/bridge.py:533–536`) → `ingest_result` (`service.py:272–300`): unknown/duplicate call_id dropped+logged; `value` through `redact_value(...)`, error messages through `redact_text`; `future.set_result(result)`. `BridgeTool.invoke` returns `value`; registry wraps `ToolResult.success`; `exec.run_tool` logs; model sees it fenced via `prompt.contain_result`.

(7) Error path — companion `_execute`:
```python
        except UnknownToolError as exc:
            return tool_result_error(call.call_id, "not_found", str(exc), retryable=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("call %.64s failed: %s", call.call_id, type(exc).__name__)
            return tool_result_error(call.call_id, "tool_error", str(exc) or type(exc).__name__,
                retryable=not (server == "code" and tool in NEVER_REPLAYED_CODE_TOOLS))
```
A handler `MachineActionError`/bad args → `CallToolResult(isError=True)` → `map_result` → `tool_result_error(call_id, "tool_error", text, retryable=False)` (`dispatch.py:84–88`). API: `ingest_result` redacts `error.message`; `BridgeTool.invoke` → `_raise_companion_error` (`tool.py:26–35`) raises `ToolException(message[:UNTRUSTED_TEXT_CAP], code=error.code, retryable=…)`; `ToolRegistry.invoke` catches (`registry.py:103`) → `ToolResult.failure(call_id, ToolError(code, message, retryable))`. Transport: offline → `UNAVAILABLE "bridge offline"` retryable; disconnect mid-call → `fail_inflight` sets `ToolException("bridge disconnected", retryable=True)` on every pending future (`service.py:302–309`); registry timeout → `TIMEOUT` retryable. `files_errors: true` tools (e.g. `machine.write_file`, `code.exec`) additionally get filed into `.solus` Error logging (`agent/errors_filing.py` via `runtime.py`). SOL never sees a traceback (`registry.py:1–7`).

Gated bridge tools (e.g. `machine.write_file`) add: `request_confirmation` calls the tool's `preview` (`BridgeTool._preview`, `tool.py:154–172`: same call with `dry_run: true`; a non-`True` `dry_run` answer renders nothing; `requires_complete_preview` tools must return explicit `preview` rows) to build the card; on approval `decide_confirmation` re-previews and invokes the STORED args.

---


## C. Robot Onboarding


### Q10: Hardware entity kinds and their attrs shapes
Status: exists
Where: `packages/api/src/solus_api/graph/kinds.py` (92) — the vocabulary; writers: `services/physical_robots.py` (295), `hardware/store.py` (727), `hardware/topology.py` (412), `hardware/host_topology.py` (421), `hardware/topology_acceptance.py` (222), `hardware/presence.py` (388), `hardware/presence_topology.py` (362), `hardware/companion_deployment.py` (331), `services/machines.py` (169), `services/solus_graph.py` (300)
Note: `kind` is a free string column; `kinds.py` is the one list. `hardware_topology_member` is NOT an entity kind — it is a **relation type** (`topology.py:27`, `solus_contracts/relations.py:58`). There is no Pydantic/TypedDict model for any hardware entity's `attrs`; every shape below is the dict literal the writer code builds.

**The hardware block of `graph/kinds.py` (verbatim, lines 28–38):**
```python
# hardware
PHYSICAL_ROBOT: Final[str] = "physical_robot"
ROBOT_CATEGORY: Final[str] = "robot_category"
HARDWARE_CONFIG: Final[str] = "hardware_config"
HARDWARE_BRAIN: Final[str] = "hardware_brain"
HARDWARE_BUS: Final[str] = "hardware_bus"
HARDWARE_EVIDENCE: Final[str] = "hardware_evidence"
HARDWARE_PRESENCE_PLAN: Final[str] = "hardware_presence_plan"
HARDWARE_WIRING_PROPOSAL: Final[str] = "hardware_wiring_proposal"
#: Legacy camel case; stored in dev DBs, so renaming it is a data migration.
COMPANION_DEPLOYMENT_PLAN: Final[str] = "companionDeploymentPlan"
```
plus (lines 70–72) `MACHINE = "machine"`, `MEMBER = "member"`, and `PART = "part"` (line 14). Relation types used with these: `contains`, `configures`, `binds`, `hardware_connected_to`, `hardware_topology_member`, `hardware_evidence_for`, `presence_prepared_for`, `wiring_proposed_for`, `deployment_for_target`.

**Attrs as written (verbatim dict literals):**

| kind | writer | domain / origin | attrs literal |
|---|---|---|---|
| `physical_robot` | `services/physical_robots.py:165-172` | `PROJECT` / `manual` | `{"hardware_config_ref": None, "transport_refs": None}` — `hardware_config_ref` is later set to the CONFIG `SolusEntry` id (`store.py:223`); `transport_refs` is never written anywhere else (grep: only this literal). |
| `robot_category` | `services/physical_robots.py:174-184` | `PROJECT` / `manual` | `{"robot_id": str(root.id), "category": key}` — one per key of `ROBOT_CATEGORIES = {"sensors","actuators","controllers","end_effectors","power","structure","wiring"}` (`physical_robots.py:24-32`); edge robot→category `contains`. |
| `part` (detected) | `hardware/store.py:attach_part` 505-543 and `detect.py:confirm_proposal` | `PROJECT` / `manual` | `{**attrs, "category": category, "robot_id": str(robot.id), "provenance": provenance.value}` where detect passes `attrs={"address": row.address, "model": row.model, "device_ref": proposal.device_ref}`; `external_ref = "<device ref>/<address>"` (`part_ref`, `config.py:76`). |
| `part` (authored) | `store.py:create_part` 546-580 | same | `attrs={"specs": dict(specs)}` → merged with `category`, `robot_id`, `provenance="user"`. |
| `hardware_config` | `store.py:_create_entry` 186-226 via `solus_graph.attach_entry` 262-300 | `PROJECT` / `.solus` ORIGIN | `{"solus_entry_id": str(entry.id), "section": "environment", "subsection": "hardware", "configured_entity_id": str(subject.id)}`; edge config→subject `configures`. The config DOCUMENT itself is the `SolusEntry.payload` (`HardwareConfig` v1 / `EntityHardwareConfig` v2, `hardware/config.py`), not the node attrs. |
| `hardware_brain` (USB endpoint, derived) | `topology.py:sync_topology` 104-113 + `_node` 173-215 | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_topology_v1", "channel": config.identity.kind.value}`; id = `uuid5(project_id, "hardware_topology_v1:endpoint:<device_ref>")`; name = `device_ref`. No `brain_kind` on this node (comes from the host overlay edge, see Q11). |
| `hardware_bus` (derived) | `topology.py:119` | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_topology_v1"}` (facts `{}`); id = `uuid5(endpoint_id, "bus:<protocol>")`; name = protocol string (driver id). |
| `hardware_brain` (host) + `hardware_bus` ("USB") | `host_topology.py:_persist` 361-375 | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_host_topology_v1", "brain_kind": node.brain_kind, "channel": node.channel}` → host: `brain_kind="host", channel="local"`; bus: `brain_kind=None, channel="usb"`. id = `uuid5(project_id, "hardware_host_topology_v1:host:<machine_id>")`, bus `uuid5(host_id,"usb")`. |
| `hardware_evidence` | `topology_acceptance.py:154-166` | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_topology_v1", "nonoperational": True, "robot_id": str(robot_id)}`; edge brain→evidence `hardware_connected_to` with attrs `{managed_by, nonoperational, robot_id, reviewed_by, is_placement, reviewed_name, proposal_digest, source_kind, row}`. |
| `hardware_presence_plan` | `presence.py:prepare` ~150-190 | `RUNTIME` / `system` | `{"created_by", "robot_id", "brain_id", "profile", "kind", "target", "config_digest", "status": "prepared", "wiring_proposal_id", "wiring_digest", "source_artifact_id", "source_sha256", "binary_artifact_id", "binary_sha256"}`; `status` ∈ prepared→unknown→flashed/prepared. Edges plan→robot, plan→brain `presence_prepared_for`. |
| `hardware_wiring_proposal` | `presence_topology.py:propose` | `RUNTIME` / `system` | `{"created_by", "robot_id", "brain_id", "request": <WiringRequest json>, "digest", "status": "proposed"\|"accepted", "observations": [...], "unresolved": [...]}`; edge → brain `wiring_proposed_for`. |
| `companionDeploymentPlan` | `companion_deployment.py:prepare` 139-151 | `RUNTIME` / `system` | `{"created_by", "target_id", "artifact_id", "artifact_sha256", "target": <DeploymentTargetSnapshot json>, "status": "prepared"}` then `+ "outcome"`; edge → target `deployment_for_target`. |
| `machine` | `services/machines.py:upsert_machine` 118-148 | `RUNTIME` / `system` | `{**MachineIn(hostname, os, arch), "owner_user_id", "tool_versions": {...}, "devices": [], "flash_history": [], "recent_commands": []}`; `canonical_key = "machine:<companion_id>"`. `devices`/`flash_history` are created empty here and never written in this file (bridge command log owns `recent_commands`). |
| `member` | `machines.py:ensure_member` 60-80 | `PROJECT` / `system` | `{"display_name": display_name}`; `canonical_key = "member:<user_id>"`; member→machine `contains`. |

`DetectedDeviceOut` / `ProposalOut` (what the UI sees pre-confirm) are NOT graph entities — see Q16.

---

### Q11: Brain kinds, creation, multi-brain representation
Status: partial
Where: `hardware/topology.py` (412) `TopologyNode` 47-57; `hardware/host_topology.py` (421); `services/physical_robots.py` (295); tests `packages/api/tests/test_host_topology.py` (427), `test_bench_focus.py` (316), `test_companion_deployment.py` (417)
Note: Three `brain_kind` values exist as a Literal on the READ model; only `host` and `mcu` are ever written by code; `onboard` appears in code only as a test fixture literal and a topology-extraction `source_kind`. There is no multi-brain robot fixture; the only "two brains" test is one host + one MCU endpoint under one robot, and one host shared by two robots.

**`brain_kind` values (verbatim, `topology.py:47-57`):**
```python
class TopologyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    name: str
    role: Literal["brain", "bus", "device", "part"]
    brain_kind: Literal["host", "mcu", "onboard"] | None = None
    category: str | None = None
    channel: str | None = None
    software: str | None = None
    presence: str | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=32)
```

**How a brain is created (all paths found):**

| path | what it creates | brain_kind written | trigger |
|---|---|---|---|
| **derived from config** — `topology.py:sync_topology` 83-171 | ONE `hardware_brain` per robot, keyed by `config.identity.device_ref`, + one `hardware_bus` per `bus_map` protocol + `hardware_connected_to` bus→part edges | none (node attrs `{managed_by, channel}`) | `store.py:383` (every `put_config`) and `hardware_router.py:192` |
| **host confirm** — `host_topology.py:propose/confirm` | a `hardware_brain` for THIS machine (`machine_id` = `~/.solus/companion_id`, `host_identity.py`) + `hardware_bus` "USB", edges robot→host (`hardware_topology_member`), host→USB→endpoint (`hardware_connected_to`) | `"host"` on the host node; optional `endpoint_brain_kind: Literal["mcu"]` written onto the **edge** USB→endpoint (`host_topology.py:398`), never onto the endpoint node | user: `POST /robots/{id}/topology/host/propose` then `/confirm` (digest-checked, idempotency-keyed) |
| **manual / detected** | no route creates a `hardware_brain` directly; `POST /hardware/entities` accepts `kind: "part"\|"robot"` only (`hardware_router.py:117`, `createUnassignedPart.ts`) | — | — |
| **onboard** | **absent**: grep `"onboard"` in `packages/api/src`, `livebench/src`, `apps/desktop/src` (non-test) → only `topology.py:51` (Literal), `topology_observations.py:174-199` (`source_kind="onboard"` extraction of a snapshot `{ros2_nodes, ros2_topics, usb, tty, vendor}`), `topology_evidence.py:22`, `schema.ts`. The only `brain_kind="onboard"` node in the repo is the test fixture `test_companion_deployment.py:61` (`attrs={"brain_kind": "onboard"}`, `origin="system"`, inserted directly into the DB). |

**Precondition for any brain**: `host_topology.propose` 404s/409s unless the robot has an accepted `usb_serial`/`usb_can` identity (`host_topology.py:183-190`), the companion bridge session matches `machine_id`, and the device is currently enumerated. `presence.binding` additionally requires `usb_serial` only.

**How brains are linked (edges, from `host_topology.py:_persist` 376-411):**
```
robot ──hardware_topology_member──▶ host (brain_kind=host)   attrs {managed_by: hardware_host_topology_v1, robot_id, endpoint_id, protocol: None, software, software_entity_id}
host  ──hardware_connected_to────▶ USB bus                   attrs {..., protocol: "usb"}
USB   ──hardware_connected_to────▶ endpoint (hardware_brain)  attrs {..., protocol: "usb", brain_kind: "mcu"|None}
robot ──hardware_topology_member──▶ endpoint                 (from sync_topology, managed_by hardware_topology_v1)
endpoint ─hardware_connected_to──▶ <protocol> bus ─▶ parts
```
`read_topology` (`topology.py:218-371`) enforces a TREE: `_validate_tree` raises `409 topology_conflict` on any node with >1 incoming edge or a cycle. So **two brains both wired to the same part, or a brain reachable two ways, cannot be represented**. Host-vs-MCU is expressed only as host→USB→endpoint nesting; "onboard Linux" has no writer.

**Multi-brain fixtures/tests (grep `two brains|multiple brains|multi.?brain|second brain|two mcus|two boards|two controllers|brain_kind` over `packages/api/tests`, `livebench/tests`):**
- `test_host_topology.py:195-233`: one robot, host confirmed with `"endpoint_brain_kind": "mcu"` → asserts `any(n["brain_kind"] == "mcu")` and a `host` node. This is the only two-brain-kinds-in-one-robot test, and it is host + one MCU.
- `test_bench_focus.py:21-60`: THREE robots; `first` and `second` share ONE synthetic `host` entity via `hardware_topology_member`, each to its own motor. Tests focus scoping, not multi-brain semantics.
- `test_companion_deployment.py:56-63`: a lone `hardware_brain` with `brain_kind="onboard"` inserted as a deployment target; not attached to any robot topology.
- `test_policy_reader.py:27` "two controllers of different widths" refers to ros2_control controllers in YAML, not brains.
- A robot with two MCUs on two USB cables: **not representable** — `sync_topology` derives exactly one endpoint from the single `config.identity` (`HardwareConfig.identity: TransportBinding | None`, `config.py:329`); the v2 `EntityHardwareConfig` also has one `identity`. No test exists.

---

### Q12: Transports, drivers, interrogators, repo parsers, plugin roster — and what ran on hardware
Status: exists
Where: `livebench/src/livebench/hardware/registries.py` (39), `channel.py` (118), `driver.py` (100), `interrogator.py` (103), `repo_config.py` (499), `plugins/__init__.py` (60), `usb_serial.py` (113), `usb_can.py` (143), `network.py` (142), `bluetooth.py` (304), `plugins/mavlink/__init__.py` (23); reports `docs/qa/COMPLETION_SOLUSDEV-248-robot-onboarding.md` (139), `COMPLETION_SOLUSDEV-260.md` (237), `COMPLETION_SOLUSDEV-262.md` (215)
Note: Registries are built once (`functools.cache`), built-in transports first, then each `PLUGIN_MODULES` entry's `register()`. Printed live below via `uv run python` (no DB/serial opened).

**Plugin roster (verbatim, `plugins/__init__.py:21-31`):**
```python
PLUGIN_MODULES: Final[tuple[str, ...]] = (
    "livebench.plugins.lb06",
    "livebench.plugins.jsonlines",
    "livebench.plugins.raw",
    "livebench.plugins.feetech",
    "livebench.plugins.dynamixel",
    "livebench.plugins.odrive",
    "livebench.plugins.mavlink",
    "livebench.plugins.lerobot",
    "livebench.plugins.arduino",
)
```
**Registration order (`registries.py:24-38`):** `register_usb_serial`, `register_usb_can`, `register_udp`, `register_bluetooth`, then `load_all(registries)`. MAVLink re-registers UDP only if `WIFI` is absent (`plugins/mavlink/__init__.py:20-21`).

**Live registry dump (`uv run python -c ...` on HEAD):**
```
TRANSPORTS ['usb_serial', 'usb_can', 'wifi', 'ethernet', 'ble', 'bt_classic']
DRIVERS [('dynamixel-2', ['usb_serial'], ['dynamixel-sdk']),
         ('feetech-sts', ['usb_serial'], ['pyserial']),
         ('json-lines', ['ble', 'bt_classic', 'usb_serial'], []),
         ('lb06', ['ble', 'bt_classic', 'usb_serial'], []),
         ('mavlink', ['ethernet', 'usb_serial', 'wifi'], ['pymavlink']),
         ('odrive-can', ['usb_can'], ['python-can']),
         ('raw-lines', ['ble', 'bt_classic', 'usb_serial'], [])]
INTERROGATORS [
 {"interrogator_id": "serial-framing",     "transports": ["ble","bt_classic","usb_serial"], "safety": "listen"},
 {"interrogator_id": "feetech-bus",        "transports": ["usb_serial"],                    "safety": "ping"},
 {"interrogator_id": "dynamixel-2",        "transports": ["usb_serial"],                    "safety": "ping"},
 {"interrogator_id": "odrive-can",         "transports": ["usb_can"],                       "safety": "listen"},
 {"interrogator_id": "mavlink-heartbeat",  "transports": ["ethernet","usb_serial","wifi"],  "safety": "listen"}]
REPO_PARSERS ['generic-structured', 'lerobot', 'sketch-print-order']
```
(`TransportKind` enum has 7 values — `usb_serial, usb_can, ble, bt_classic, wifi, ethernet, ros2` (`config.py:53-60`); **`ros2` has no registered transport** and appears in livebench only as `TRANSPORT_PREFIX[ROS2]="ros2"`. `wifi` and `ethernet` are both the same UDP opener: `UDP_KINDS = (WIFI, ETHERNET)`, `network.py:26,139`.) Transport registry has no `catalog()`; `kinds()` only. `Safety` enum (`interrogator.py:25-28`): `PASSIVE="passive", PING="ping", LISTEN="listen"`. Plugins `lerobot` and `arduino` register repo parsers only (no transport/driver/interrogator); `arduino` additionally supplies the presence compiler/flash runner outside the registries.

**Exercised on real hardware — per the completion reports (sentences verbatim):**

| transport / driver | report | sentence |
|---|---|---|
| `usb_serial` + `feetech-sts` + `feetech-bus` | 248 row "2 · R3", column "On hardware (two six-servo serial arms, live API on :8000)" | "Both arms open by USB serial identity; six servos each at 1 Mbaud; sessions from the robot config stream ~30 Hz per servo; **every packet resolves** to its part (`ingested` 984 / 540 in 3 s, `unresolved` 0)" |
| same | 260 row 1 | "**Partial live / fixtures.** Follower serial 5B42134331 answered as six STS3215 servos; UI confirmation produced a connected robot and accepted mapped telemetry." Row 2: "**Unverified prerequisite.** Leader serial 5B42135040 visible but servos do not answer." |
| same, both arms | 262 line 61 | "Both arms streamed simultaneously without workspace focus." Row P0: "two boards, six responders each — Both simultaneous" |
| `usb_serial` transport-only (CH340 Uno, no protocol) | 262 lines 16-17, 56 | "Transport-only USB devices can be explicitly added as MCU connections without starting a session. The CH340 Uno remains **Possible Arduino connection**, with firmware unknown and identity tied to its USB port." |
| `usb_can` / `odrive-can`, UDP / `mavlink` | 248 row "2 · R3", column "Not verified" | "CAN and UDP against real hardware (none present)" — fixtures only: "Replay channel drives the CAN/UDP/line fixtures through transport → driver with no vendor import" |
| same | 262 row "P1 MAVLink/CAN/onboard twins/vendor proof" | "Not live machines \| Existing transport recordings \| Extended three-machine proof: 10 passing tests \| No live substitute claimed" |
| `ble` / `bt_classic` | 248 row "2 · R3" fixtures column | "bluetooth honest not-installed"; code: `bluetooth.py:228` docstring `"""UNVERIFIED WITHOUT HARDWARE: the live bleak path, kept to these lines on purpose."""` |
| `lb06` / `raw-lines` / `json-lines` on a real board | 248 §7 human step 3 | "**Flash a Nano** with `libs/solus-telemetry/arduino/examples/NanoSixChannels` … Then Detected → Propose → six rows by address (driver `raw-lines`/`lb06`) → Confirm → ~35 Hz." — listed as a HUMAN step, not done. 262 row "P1 heartbeat flash/uno.alive": "Not flashed". |
| `dynamixel-2` | no report sentence found claiming a live run | not determined (grep over 248/250/260/262 for "dynamixel" live claims: none; only vendor-hygiene mentions) |
| USB port swap / unplug-replug | 248 §7 steps 1-2, 260 row 2, 262 row P0 | "the physical gap was not exercised" (248:121); "Physical port swap/unplug/reconnect not performed." (260:50); "USB swap skipped by user" (262:124) |

Fixture proof that all three non-serial machines share one code path: `livebench/tests/lb_three_machines_test.py` (669) — "A recorded autopilot link (UDP), a recorded CAN base and a recorded bare-board float dump each run the SAME onboarding sequence".

---

### Q13: Reaching brains Solus does not run on
Status: partial
Where: `hardware/companion_deployment.py` (331); `agent/tools/companion_deployment.py` (69); `livebench/deploy/companion.py` (384); `livebench/deploy/companion_remote.py` (167); `livebench/deploy/fs.py` (82); `hardware/presence.py` (388); `hardware/presence_topology.py` (362); `agent/tools/ros_live.py` (128); `integrations/mcp/code/solus/ros2_reads.py` (124); `software/ros_reader.py` (618); `hardware/topology_observations.py` (273); `packages/companion/src/solus_companion/machine/server.py` (274); `deps.py:565-580`; `main.py:515-520`
Note: There is NO agent that runs on an onboard Linux computer and reports back. The only reach into a non-host brain is (a) SSH/scp installation of the **same desktop companion zipapp** onto a *pre-enrolled* Linux target, operator-wired and disabled by default, and (b) `arduino-cli upload` of Solus-generated presence firmware to a local AVR. ROS 2 is reached only via the local companion running `ros2 node list` / `ros2 topic list` on the host machine. MAVLink is a listen-only telemetry driver, not a command path.

**`hardware/companion_deployment.py` — what it actually does:**
- `CompanionDeploymentService.prepare(target_id, artifact_id)`: checks `target_id` is ANY live `GraphEntity` in the project (`_target` 93-99 — kind is not checked), asks the injected `DeploymentProvider.resolve_target()` for a `DeploymentTargetSnapshot {id, version, host, user, companion_instance_id, host_keys_sha256}`, fetches a *retained* artifact created by this user, ≤32 MiB, whose sha256 the provider's `bundle_allowed()` whitelists, then writes a `companionDeploymentPlan` entity (attrs in Q10).
- `preview()` returns the card rows: Target `user@host`, companion instance, SSH host-key authority SHA256, bundle SHA256, "Prerequisites: Pre-enrolled active service and trusted deploy helper; no bootstrap", "Operation: Install offline bundle, restart, verify fresh authenticated handshake; rollback on failure."
- `execute(plan_id)` — docstring: `"""Registered central tool invoke only; no HTTP write/approval flag endpoint."""` Sets `status="unknown"` and commits BEFORE calling `provider.execute()`, re-checks target+bundle, then records `DeploymentOutcome {status: succeeded|failed|refused, remote_state: unchanged|running|rolled_back|unknown, artifact_sha256, error_code}`.
- `FreshCompanionHandshake` (296-331): waits ≤25 s for a NEW bridge session from the same `companion_instance_id` with `may_write`, as proof the restarted remote companion reconnected.
- Enablement: `get_companion_deployment_service` 503s unless `app.state.companion_deployment_service_factory` exists. **Grep: nothing in `packages/api/src` or `livebench/src` sets that attribute** (only `deps.py:578` and `companion_deployment.py:282` read it). So on HEAD the HTTP route `POST /hardware/companion-deployments/prepare` (`hardware_router.py:1004`) and the SOL tool are 503/unregistered unless an operator wires a factory in. 262 row P1: "Live SSH deferred; initial enrollment unsupported; local factory disabled by default".

**`agent/tools/companion_deployment.py`:** registers SOL tool `hardware.deploy_companion` (`requires_confirmation=True`, `requires_complete_preview=True`, timeout 300 s, params `{plan_id}`) that calls `service.execute`; preview = service rows + simulation precheck rows. Registered only when the service exists (`agent/runtime.py:1708-1712`).

**`livebench/deploy/companion.py` (desktop-side runner, `CompanionDeployer`):** builds pinned `/usr/bin/ssh` / scp argv with user SSH config disabled and `known_hosts` pinned (`_execute_pinned` 134), stages phases `preflight → (scp bundle) → install → start → cleanup` (rollback on failure) by invoking the remote helper at `_HELPER = "/usr/local/libexec/solus-companion-deploy.py"`. `LocalCompanionDeploymentProvider` (308-384) is "Operator-installed, scoped adapter; never discovered or enabled automatically"; targets are a `Mapping[uuid, CompanionTarget]` handed in at construction — no enrollment route.

**`livebench/deploy/companion_remote.py` (runs ON the target, installed by an admin):** `RemoteDeployment.run(phase, operation, digest)` over `~/.solus/companion-deploy/{provisioned.json {format:1}, releases/<sha256>.pyz, current.pyz, staging/, active}`; swaps the `current.pyz` symlink and `systemctl --user restart solus-companion.service`. "This helper neither enrolls credentials nor installs units." `main()` returns 1 on any error with no output.

**`livebench/deploy/fs.py`:** `SshFilesystem.push/pull` via pinned scp with `BatchMode=yes`, host/user/remote-path regex allowlists. Grep for callers in non-test code: only `companion.py` imports it (`ExecFn, SshFilesystem`). No route or tool exposes push/pull directly.

**`presence.py` / `presence_topology.py`:** local-only. `PresenceService.binding()` requires the robot's identity to be `usb_serial`, the brain id to equal the derived endpoint id, an EMPTY `bus_map`/`parts`, and (if a protocol is set) `provider.accepts_protocol(driver_id)` → `{"arduino.telemetry","solus.telemetry"}` (`presence_provider.py:33-35`) — i.e. "Configured driver boards cannot receive presence firmware". `prepare()` compiles via `LocalPresenceProvider` (arduino-cli, profiles `uno_avr`/`nano_avr`, kinds `heartbeat|probe|topology`), stores source+hex as artifacts, writes the plan. `execute()` is reached only through SOL tool `hardware.flash_presence` (gated, `firmware_presence.py:44-60`) and uploads with `arduino-cli upload --verify --fqbn ... -p <path> --input-file presence.hex` after taking an exclusive `flock` on the tty. `WiringService` (presence_topology) produces a reviewed `hardware_wiring_proposal` from typed pins, a KiCad/Altium schematic source, or a completed probe run's `probe.analog.*` / `probe.i2c.*` values. Provider exists only when `app_env == "dev"` and `arduino-cli` is on PATH (`main.py:515-520`, `plugins/__init__.py:presence_provider`).

**ROS 2:** no bridge, no `rclpy` import anywhere (grep `rclpy|rosbridge|roslibpy` → none). Paths that exist: (1) `software/ros_reader.py` — static `ast`/XML/YAML parse of a ROS workspace's texts → `ros_node`/`ros_topic` entities; (2) `integrations/mcp/code/solus/ros2_reads.py` — the companion's code fork runs fixed argv `ros2 node list --no-daemon --spin-time 2` / `ros2 topic list --no-daemon -t` on the HOST machine under a captured profile; (3) `agent/tools/ros_live.py` wraps those two bridge tools (`code.ros2_nodes`, `code.ros2_topics`) and only bumps existing inferred edges; (4) `topology_observations.onboard_topology` accepts a snapshot dict with `ros2_nodes`/`ros2_topics` keys — but no code produces such a snapshot (grep `onboard_topology(` callers: `topology_evidence.py` plumbing only; no collector). `integrations/ros/` is an empty directory on HEAD (`ls` prints nothing).

**MAVLink:** driver + heartbeat interrogator over UDP/serial (`plugins/mavlink/*`, hand-rolled codec for HEARTBEAT/ATTITUDE/SERVO_OUTPUT_RAW). Listen/telemetry only; no command, param, or mission path.

**Companion package (`packages/companion`):** runs on the engineer's machine; `machine/server.py` exposes `tool_versions`, file read/write, code reader. `platforms.py` supports linux/darwin/win32. Nothing in it targets a remote robot computer.

---

### Q14: Clock alignment across brains
Status: absent (alignment) / exists (two-clock packet)
Where: `packages/api/src/solus_api/graph/packet.py` (153); `graph/codec.py` (188); `livebench/src/livebench/telemetry/normalize.py` (129); `livebench/src/livebench/plugins/lb06/lb06_lines.py` (81); `lb06_driver.py` (92); `plugins/feetech/feetech_driver.py:197`; `docs/contracts/telemetry-packet.md` (220); `libs/solus-telemetry/README.md` (194)
Note: No offset estimation, sync packet, NTP/PTP handling, or per-brain clock record exists anywhere (grep `clock_offset|offset_ms|clock skew|host_time|device_time|ntp|ptp|time_sync|clock sync|clock align` over livebench, graph, telemetry, libs → only `time.monotonic()` deadlines and the docstring sentence below). The design is: wall-clock `timestamp` + per-device monotonic `seq`; a board's `ts_us` since boot is accepted as-is and becomes a 1970-era `timestamp`.

**The packet model (verbatim, `graph/packet.py:65-77`):**
```python
    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(min_length=1, max_length=MAX_DEVICE_ID_LEN)
    timestamp: datetime
    values: dict[str, float]
    # Upper bounds as well as lower: a Python int is arbitrary-precision, so without `le` a
    # hostile producer could park a 4000-digit `seq` in the model that no int64 wire — and no
    # other runtime — can represent.
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1, le=MAX_SCHEMA_VERSION)
    seq: int | None = Field(default=None, ge=0, le=MAX_SEQ)
    units: dict[str, str] = Field(default_factory=dict)
```
Bounds (`packet.py:37-46`): `MAX_DEVICE_ID_LEN = 512`, `MAX_SIGNALS_PER_PACKET = 256`, `MAX_SIGNAL_NAME_LEN = 128`, `MAX_UNIT_LEN = 32`, `MAX_SAFE_INT = 2**53 - 1`, `MAX_SEQ = MAX_SAFE_INT`, `SCHEMA_VERSION = 1`. Wire: `timestamp` travels as `ts_us` (`codec.py:42 TS_KEY = "ts_us"`), decoded by `_from_epoch_us` (int only, `|raw| ≤ 2^53-1`, `codec.py:78-90`). The docstring's only clock statement (`packet.py:11-14`): "Two clocks, deliberately: `timestamp` is the wall-clock instant … while `seq` is the producer's MONOTONIC per-device counter. Real robot clocks drift and get NTP-corrected backwards; `seq` is what survives that, so consumers detect drops and reordering from `seq`, never from `timestamp` deltas."

**Contract doc `telemetry-packet.md` §2 table and §3 (verbatim):**
```
| `device_id`      | `str`, 1–512         | yes                 | Identity of the device **or topic**. Resolved against `graph_entity.external_ref`, project-scoped. |
| `timestamp`      | `datetime`, tz-aware | yes                 | Wall-clock instant of the reading. Naive datetimes are rejected.                                   |
| `values`         | `dict[str, float]`   | yes                 | Signal name → finite value. 1–256 entries, names ≤128 chars.                                       |
| `schema_version` | `int` ≥ 1            | no (default `1`)    | Wire-format version (§4).                                                                          |
| `seq`            | `int` ≥ 0 \| `None`  | no (default `None`) | Monotonic per-device counter (§3).                                                                 |
| `units`          | `dict[str, str]`     | no (default `{}`)   | Unit symbol per signal, ≤32 chars. Keys must be a subset of `values`.                              |
```
```
## 3. Two clocks, and why
`timestamp` is wall-clock; `seq` is monotonic. They are not redundant.
Windows bucket by `timestamp`, and correlating a telemetry event with a commit or a CAD edit needs
real time. But a real robot's clock drifts and gets NTP-corrected _backwards_, which reorders
samples and lands them in the wrong window. `seq` is the ordering that survives that.
**Consumers detect drops and reordering from `seq`, never from `timestamp` deltas.**
```

**The LB-06 line "parser" (`lb06_lines.py`) does not parse fields** — it is newline framing only: `LineReader.read_line()` returns one stripped line ≤ `MAX_LINE_BYTES = MAX_PACKET_BYTES + 1024` (= 64 KiB + 1 KiB), discards over-long lines, honours a monotonic deadline. `LineTransportParams {baud: 300..3_000_000 | None, timeout_s: 0.001..5.0 | None}` is the driver's params model. Field decoding happens in `normalize.packet_from_json_payload(topic, log_time_ns, line, trusted_identity=True)` (`lb06_driver.py:59-61`): if the JSON has key `ts_us` → `_decode_lb06` → `codec.decode_json` (the packet's own `ts_us` is used VERBATIM as `timestamp`; `log_time_ns` from the host clock is ignored); otherwise plain JSON is flattened and stamped with the host `log_time_ns`. The driver pins `device_id` to the channel's `device_ref` and drops relabelled packets.

**Consequence for a bare board:** the Arduino emitter writes `ts_us = micros()` (uint32 since boot, wraps every ~71.6 min, `SolusTelemetry.h:11-13`); the README says "Solus orders samples by `seq`, so this is accepted — it is simply not wall-clock time." Code: such packets land with `timestamp ≈ 1970-01-01 + micros`, and `graph/telemetry.py` windows (`get_telemetry`, lines 295-305) bucket by `timestamp`, so a boot-relative board and a host-clock driver (e.g. `feetech_driver.py:197 timestamp=datetime.now(tz=UTC)`) cannot be placed on one time axis. No code reconciles them. `seq` is produced per device by `Emitter`/`SolusTelemetry` and by the feetech driver (`feetech_driver.py:220`); there is no cross-device seq relation.

---

### Q15: A single part vs a whole robot; "unassigned" devices
Status: partial
Where: `hardware/detect.py` (902) `ConfirmIn` 206-225, `_confirm_connection` 700-770, `confirm_proposal` 772-880; `hardware/store.py:unassigned_parts_stmt` 603-610; `hardware_router.py` `/entities` 117, `/parts?ownership=unassigned` 243-257, `/unassigned` 579, `/detected*` 638-795; UI: `apps/desktop/src/renderer/src/features/graph/hardware/{DevicesFound.tsx (73), DeviceCard.tsx (295), PendingDeviceCards.tsx (47), deviceCardRules.ts (146), detected.ts (67), useDeviceProposals.ts (458), useDetectedDevicesFeed.ts (52), UnassignedParts.tsx (250), createUnassignedPart.ts (21), HardwareAddPanel.tsx (99)}`
Note: A detected DEVICE cannot exist in the graph without a Physical Robot — every confirm path creates or names a robot. "Unassigned" exists only for PARTS (authored or connector-imported, no owner) — not for devices. A lone servo or sensor plugged in is shown as a pending card until the user names a robot or dismisses it ("Not now", session-scoped).

**Confirm requires a robot target (verbatim, `detect.py:206-225`):**
```python
class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Annotated[NewRobotTarget | ExistingRobotTarget, Field(discriminator="kind")]
    accepted: list[AcceptedRow] = Field(max_length=MAX_ACCEPTED_ROWS)
    connection_only: StrictBool = False
    repo_config_id: str | None = Field(default=None, max_length=256)
    source_refs: SourceRefs = Field(default_factory=list)
    repo_root: str | None = Field(default=None, min_length=1, max_length=MAX_REPO_ROOT_CHARS)
    start_session: bool = True
    window_seconds: float = Field(default=1.0, gt=0, le=86400)
```
`NewRobotTarget {kind:"new", name: RobotName|None}` → `PhysicalRobotService.create()` (root + 7 categories, 8 entities); `ExistingRobotTarget {kind:"existing", robot_id}`. There is no "no robot" target.

**Device-level "unassigned": absent.** Pending state lives only in the renderer: `pendingDevices()` (`deviceCardRules.ts:60-71`) = enumerated devices whose `device_ref` is not a prefix of any entity `source_key` (`<device_ref>/<address>`) and not in the session `dismissed` set. Dismissal is a module-level Zustand set pruned when the device unplugs (`useDeviceProposals.ts:prunedDismissals`). Nothing persists a device without a robot; `machine.attrs.devices` exists (`machines.py:131`) but is never written by any code found (grep `"devices"` writers: only the `prior.get("devices", [])` carry-forward).

**Part-level "unassigned": exists.** `unassigned_parts_stmt` (`store.py:603-610`): live entities with `kind in PART_KINDS` not in `_owned_part_ids` (parts under a live robot's category). Routes: `GET /hardware/parts?ownership=unassigned`, `GET /hardware/unassigned`, `PATCH /parts/{id}/parent`, `POST /robots/{id}/parts/attach`. UI `UnassignedParts.tsx` ("Parts no robot owns. Pick robot and category.", `hardware.constants.ts` `HARDWARE_COPY.unassigned`) and `createUnassignedPart.ts` → `POST /hardware/entities {kind:"part", name, category}` ("an absent parent never creates a robot").

**Trace: one servo plugged in alone →**
1. `hardware/device_watch.py` `DeviceWatcher._tick` (1 Hz, local API only, `publish_local`) → SSE `hardware.devices_changed` with the full `DetectedDeviceOut[]` list → `useDetectedDevicesFeed.onDevices` → `detectedDevicesStore`.
2. `PendingDeviceCards.tsx` (canvas-edge rail, pill past 3) and `HardwareAddPanel.tsx` → `DevicesFound.tsx` → one `DeviceCard` per pending device; `useDeviceProposals` auto-calls `POST /detected/{ref}/propose` (≤2 in flight, silent retries at 5 s / 15 s).
3. A Feetech/Dynamixel servo on a bus board answers a ping → proposal `driver_id="feetech-sts"`, rows per address → card sentence `proposalHeadline` ("Looks like · …"), question `cardQuestion`: `choose` (2 repo configs) / `suggest` (link suggestion to an imported robot) / `name` → `NameRow` with input "Robot name" (placeholder = single repo match label or "Name this robot") + select "Part of: New robot | <existing robots>" + "Add". `defaultAccepted` puts every row in category `actuators` (`sensors` when `proposal.stream`).
4. A sensor streaming CSV/JSON lines → `serial-framing` interrogator → `driver_id` `raw-lines`/`json-lines`/`lb06`, `stream` set, rows per column, same card with glyph `⌇`, category `sensors`.
5. Add → `POST /detected/{ref}/confirm` → `confirm_proposal` → robot (new: 8 entities, or existing) + `part` per row keyed `<ref>/<addr>` + config layers `detected`/`repo`; `start_session` opens the robot connection; card shows "Added · connected / connecting… / <session_error>".
6. If nothing answers → see Q16 ("silent"); if the device is a bare USB bridge with no protocol → `connectionOnly` → button "Add MCU connection" → `_confirm_connection` writes identity-only config on a new/existing robot (`detect.py:700-770`; 409 if `saved.protocol or saved.bus_map or saved.parts`).

---

### Q16: Unknown protocol / silent device / unreachable brain
Status: exists
Where: `livebench/src/livebench/hardware/detection.py` (414); `livebench/src/livebench/recognition/passive.py` (269); `recognition/active.py` (156); `hardware/interrogator.py` (103); `hardware/channel.py` (118); `packages/api/src/solus_api/hardware/detect.py` (902); `hardware/local_runtime.py` (94); UI `deviceCardRules.ts`, `DeviceCard.tsx`, `detected.ts`
Note: There is no "unknown protocol" error — silence and unknown are proposals with `driver_id=None`. The API has no status enum for detection; the UI derives one. `recognition/active.py` (commanded-motion identification) has `verdict ∈ {identified, no_result, refused}` but no caller outside tests (grep `run_active_identification(` in src → only its definition).

**Enumeration levels and tone (verbatim, `detection.py:36-38`):**
```python
Level = Literal["transport", "board", "protocol", "platform"]
IdentityBasis = Literal["serial", "port_position", "none"]
Tone = Literal["looks_like", "probably", "something"]
```
`enumerate_devices` sets `level="board" if identity.mcu_known else "transport"`; `propose()` sets `level="protocol"` only when an interrogation answered. **`"platform"` is never assigned by any code** (grep `"platform"` in detection.py/detect.py → Literal only). Confidence→tone (`tone_for` 112-120): `best is None → "something"`; `≥0.85 → "looks_like"`; repo match or `≥0.5 → "probably"`; else `"something"`. Headlines (`headline_for` 94-110): known MCU board → its table headline; known bridge vendor → `VENDOR_FAMILY_TABLE` family; line stream behind a bridge → `BRIDGE_STREAM_HEADLINE`; else `UNKNOWN_HEADLINE` (from `livebench/definitions/usb_boards.py`).

**Passive identity (`passive.py:identify_port` 108-156):** unknown VID/PID → `ModalityMatch(confidence=0.05, LOW_CONFIDENCE, note "unknown VID/PID — reported as unknown, never guessed")`; USB bridge → `0.30 LOW_CONFIDENCE` "the MCU behind it is unknown"; known MCU board → `0.85 MATCHED`. Binding (`binding_of` 83-93): USB serial → `basis="serial"`; else USB port location → `port-<loc>`, `"port_position"`; else `None, "none"` → `DetectedDevice.device_ref=None` and `propose()` raises `ValueError("this device has no binding identity yet — reconnect it to verify")`. Two devices sharing a binding → `ambiguous=True`.

**Interrogation (`detection.py:interrogate_device` 162-189):** opens the transport at each of `DEFAULT_CANDIDATE_PARAMS` bauds `1_000_000, 115_200, 250_000, 57_600, 9_600` with `timeout_s=min(budget, 0.2)`, runs every registered interrogator for the transport; `TransportUnavailableError` (busy/absent/not installed, `channel.py:44-46`) → `logger.info("interrogation skipped …")` and `return []` — **a busy port is indistinguishable from silence** (docstring: "A busy or absent port is silence, never an error"). An interrogator that raises is skipped (`interrogator.py:interrogate` 85-103).

**Silent / unknown proposal (verbatim, `detection.py:propose` 300-318):**
```python
    if not interrogations:
        headline = headline_for(device, None)
        return Proposal(
            device_ref=device.device_ref,
            identity=device.identity,
            level=device.level,
            summary=(
                f"{headline} ({device.device_ref}): no protocol recognised — name the channels?"
            ),
            driver_id=None,
            params={},
            rows=[],
            repo_matches=[],
            disambiguation=None,
            confidence=device.confidence,
            evidence=list(device.evidence),
            headline=headline,
            identity_basis=device.identity_basis,
        )
```
Stream shape outcomes (`passive.characterize_stream`): `framing ∈ json-lines | csv | text | binary | silent`; `serial-framing` interrogator returns `None` for `text`/`binary`/`silent` (`lb06_interrogator._proposal`), so junk or binary streams also arrive as the `driver_id=None` proposal above.

**API-side errors (`detect.py:propose_via_local` 262-293, `hardware_router.py:confirm_detected` 687-795, `local_runtime.py`):**

| condition | HTTP | code |
|---|---|---|
| device not enumerated | 404 | `device_not_found` ("… is not connected to this machine" / "The device is no longer connected") |
| local runner >30 s | 503 | `source_unavailable` ("the local runner did not answer in time") |
| runner proposal fails `ProposalOut` validation | 503 | `source_unavailable` |
| repo source unparsable | 422 | `invalid_source` |
| no local runtime (`bench_local is None`) | — | `_local_runner` raises (cloud API never detects) |
| connection-only but identity changed/ambiguous | 409 | `device_changed` |
| part already owned | 409 | `conflict` "… is already part of robot <uuid> — reconnecting a known machine needs no second robot" |
| session open: ambiguous / absent / bad config / other | 409 `device_ambiguous` / 404 `device_not_found` / 422 `validation_error` / 503 `source_unavailable` (`local_runtime.py:22-41`) |

**UI status enum (verbatim, `deviceCardRules.ts:16-22`):**
```ts
export type DeviceCardStatus =
  | 'proposing'
  | 'proposed'
  | 'silent'
  | 'failed'
  | 'confirming'
  | 'done'
```
Mapping (`useDeviceProposals.ts:propose` 276-300): proposal with `driver_id === null` → `'silent'` + backoff retries `[5_000, 15_000]` ms; request threw → `'failed'` with backend text; `device.ambiguous` → initial `'failed'` with `AMBIGUOUS_NOTE = 'no unique identity yet — reconnect it to verify'`. Card copy: silent → `SILENT_TEXT = 'Nothing answered yet — is it powered and free?'` + Retry + Not now (`DeviceCard.tsx:37,132-147`); silent AND `connectionOnly(proposal)` (usb_serial, no driver/rows/params/stream) → question "Firmware and protocol are unknown." + button "Add MCU connection"; failed without proposal → `role="alert"` with backend message + Retry; 409 naming a robot → "Add to that robot instead" (`conflictText`, `robotIdFromMessage`). Transport-level title fallback: `'something on USB'` (`detected.ts`). Port-position identity note: `'identity from the USB port — keep it in this port'`.

**Unreachable brain (post-confirm):** a bound robot whose device is gone → session open 404 `device_not_found`; `ReconnectingSource` (`hardware/connection.py:138`) re-opens by identity each incarnation; `host_topology.propose` 404 `device_not_found` "The accepted USB endpoint is not currently present" and 503 `source_unavailable` "This hardware provider is on another or unknown machine" when `read_host_identity()` ≠ `machine_id`. No reachability state is stored on the brain entity.

---

### Q17: Telemetry library and the Arduino flash runner; SOL callability
Status: partial
Where: `libs/solus-telemetry/{README.md (194), python/src/solus_telemetry/__init__.py (143), micropython/solus_telemetry.py (149), arduino/src/SolusTelemetry.h (52), arduino/src/SolusTelemetry.cpp (101), arduino/examples/NanoSixChannels/NanoSixChannels.ino (40)}`; `livebench/src/livebench/deploy/flash.py` (146); `livebench/src/livebench/plugins/arduino/arduino_flash.py` (80); `plugins/arduino/presence.py` (159); `plugins/arduino/presence_provider.py` (146); `packages/api/src/solus_api/agent/tools/flash_history.py` (62); `agent/tools/firmware_presence.py` (65); `agent/firmware_recipe.py` (422); `integrations/mcp/code/solus/arduino_upload.py` (423); `integrations/mcp/code/allowlist.yaml:76-80`; `bridge/allowlist.py:54`
Note: Three distinct flash-shaped things exist and only ONE can write a board today: (1) `deploy/flash.py` + `ArduinoCliRunner` — a generic gated flash orchestrator with **no production caller**; (2) `hardware.flash_presence` — SOL tool that uploads Solus-generated presence firmware via `presence_provider.upload` (dev-only, arduino-cli on PATH); (3) `code.arduino_upload` — the companion MCP tool, whose non-dry-run path is **hard-refused** (`raise ArduinoError("device_ownership_unavailable")`). `firmware_recipe` writes sketch text through `machine.write_file`'s card; it does not flash.

**Telemetry library (`libs/solus-telemetry/`, MIT, no deps):** three emitters producing one LB-06 JSON line per packet with fixed key order `{"schema_version":1,"device_id":…,"ts_us":…,"values":{…},"seq":n,"units":{…}}`:
- Python `Emitter(device_id, write, clock_us=epoch µs)`, `format_line(...)`; validates bounds mirroring `packet.py` (`MAX_DEVICE_ID_LEN=512, MAX_SIGNALS=256, MAX_SIGNAL_NAME_LEN=128, MAX_UNIT_LEN=32, MAX_SAFE_INT=2**53-1, MAX_LINE_BYTES=64*1024`); plus `mirror.py` (`MethodAdapter, MirrorConfig, mirror`) and `http.py` (`HttpPublisher`).
- MicroPython `solus_telemetry.py` (same shape).
- Arduino C++ `SolusTelemetry(Stream&, deviceId)`, `begin()/add(name, float, unit)/send()`, `kMaxChannels = 16`, `ts_us = micros()` (uint32, since boot), 4 fixed decimals, `|value| < 1e9`.
- Parity test `python/tests/test_telemetry_lib_parity.py` (164) asserts bounds have not drifted from the Solus contract. The 248 report lists flashing the Nano example as a human step; 262: "Not flashed".

**`livebench/deploy/flash.py` (verbatim enums and result):**
```python
class FlashPhase(enum.StrEnum):
    PREPARING = "preparing"
    ERASING = "erasing"
    WRITING = "writing"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"

@dataclass(frozen=True)
class FlashResult:
    ok: bool
    device_state: Literal["unchanged", "flashed", "unknown"]
    artifact_sha256: str | None
    error: str | None
```
`flash(target, artifact, *, runner: FlashRunner, on_progress, approval)`: reads+hashes the artifact (cap `MAX_ARTIFACT_BYTES = 32 MiB`), if `approval` given emits `propose_flash` → `ToolConfirmationEvent(tool="flash_device", …)` and returns `"flash refused at the confirmation gate"` on denial; erase failure → `unchanged`, write/verify failure → `unknown`. `approval=None` is explicitly "the un-gated test/dev path; a route MUST pass a real approval seam". **Callers in non-test code: none** (grep `flash(` / `ArduinoCliRunner` → only definitions and `presence.py`/`companion.py` importing `FlashError`/`Approval`).

**`plugins/arduino/arduino_flash.py`:** `ArduinoCliRunner(binary, fqbn, port).upload_argv(artifact)` = `[binary, "upload", "--verify", "--fqbn", fqbn, "-p", port, "--input-file", artifact]`; runs once at `WRITING`. `run_cli(argv, timeout=120, output_limit=65536)` — absolute pinned binary required, `start_new_session=True`, SIGKILL of the process group in `finally`, tool output never echoed into errors. `run_cli` IS used in production by `presence.py` (compile) and `presence_provider.upload` (upload).

**Triggering and gating of the three paths:**

| path | trigger | gate | writes a board on HEAD? |
|---|---|---|---|
| `hardware.flash_presence` (SOL tool, `firmware_presence.py`) | user asks SOL after `POST /robots/{r}/brains/{b}/presence/prepare` created a plan (UI `PresenceCard.tsx`/`PresenceWiringCard.tsx` in `RobotTopologyGraph`) | `requires_confirmation=True`, `requires_complete_preview=True` (the whole sketch source is shown in ≤46 chunks of 500 chars, else 409 `presence_preview_too_large`); consent "Erase and replace this board firmware…"; `PresenceService.execute` re-checks config digest, wiring digest, USB snapshot, takes `flock` on the tty; registered only when `app.state.presence_provider` exists = `app_env == "dev"` and `arduino-cli` on PATH (`main.py:515-520`) | yes (dev only). 262: "Not flashed" live, "Budget availability, then manual card approval and live channel" owed. |
| `code.arduino_upload` (companion MCP, `integrations/mcp/code/solus/arduino_upload.py`) | SOL/bridge tool call; `allowlist.yaml:76-80 requires_confirmation: true, timeout_seconds: 150` | central gate; **but** `arduino_upload()` line ~312: `if not args.dry_run: raise ArduinoError("device_ownership_unavailable")` — docstring "Preview the immutable build and target; refuse execution without serial ownership." | **no** — dry-run preview only. `flash_history.record_tool_history` would log `firmware.flashed` on a clean run of this tool (`FLASH_TOOL = "code.arduino_upload"`), which cannot happen on HEAD. |
| `deploy/flash.py` + `ArduinoCliRunner` | none | `approval` seam | no caller |
| `firmware_recipe` (`agent/firmware_recipe.py`, descriptor name `firmware_recipe`, registered `agent/runtime.py:202-204`) | user asks SOL for firmware for a board | one model call; answer `{path, content, card_rows, next}` routed to `machine.write_file`'s confirmation card ("The recipe writes nothing itself") | writes a FILE on the user's machine via the companion, never flashes |

**SOL tool names that exist for this area:** `hardware.flash_presence`, `hardware.deploy_companion`, `firmware_recipe`, `machine.write_file`, `code.arduino_prepare`, `code.arduino_compile`, `code.arduino_upload` (dry-run only). A SOL tool that flashes an arbitrary user sketch/hex onto a board: **absent**.

---


### Q18: Binding a detected part to design counterparts
Status: partial (library: manual + suggested; CAD: suggested + manual, indirect; schematic: absent; URDF/MJCF joint: manual; code site: inferred-after-human-acceptance)
Where: packages/api/src/solus_api/hardware/detect.py (902), hardware/store.py (727), hardware/library_router.py (322), hardware/library_import.py (63), hardware/links.py (342), hardware/cad_suggestions.py (306), hardware/bindings.py (195), hardware/topology.py (412), hardware/presence_topology.py (362), hardware/topology_observations.py (273), livebench/scene/service.py (305), livebench/scene/schemas.py (63), livebench/scene/part_bindings.py (132), livebench/scene/cad_import.py (564), graph/inference/firmware_edges.py (283), graph/inference/joint_limits.py (163), linking/linker.py (454), livebench/persist.py (194), packages/contracts/python/solus_contracts/relations.py (273)
Note: A detected part is a manual `part` entity whose identity is `external_ref = "<device_ref>/<address>"` (detect.py:824-832). Nothing matches it to a library definition, CAD body or schematic symbol automatically; the only automatic edges to a detected part are `commands`/`reads` from a code_file, and those run only after a human accepts a firmware-extraction row. There is no part↔CAD or part↔schematic `same_as` for detected parts because the fingerprint persist seam (`livebench/persist.py`) has no production caller (grep across `packages/api/src/solus_api` finds only its own module and tests).

| Counterpart | Mode | Carrier (edge kind / field / attr keys) | Code |
|---|---|---|---|
| (a) Library part definition | **manual** (import) and **suggested** (device↔library-imported robot) — never automatic for a detected part | Same node, two fields: `GraphEntity.attrs.definition_id` (set only by library import) and `GraphEntity.external_ref` (set by detection/bind). No edge. Library import: `attach_part(... attrs={"model","manufacturer","definition_id","specs"}, provenance=LIBRARY)` with **no `external_ref`** ("the wire assigns identity later") — library_router.py:95-121; standalone: library_import.py:33-49 (`attrs.definition_id`, `provenance: "library"`). Suggestion: `_rule_bus_map` (links.py:128-145) scores a detected whole device against an identity-less robot whose `bus_map` addresses+models agree → `HardwareSuggestion` row (table, `subject_kind="device"`, links.py:227-268). Accept → `bind_device` (detect.py:567-623) writes `config.identity/protocol/bus_map` with provenance `detected` and sets each bus-mapped library part's `external_ref = part_ref(device_ref, address)` plus `attrs.device_ref/address` (detect.py:614-621). Detected-confirm path writes `attrs={"address","model","device_ref"}` only — **no `definition_id`** (detect.py:824-832); grep `definition_id` in hardware/ hits only library_import.py and library_router.py. Envelopes read `attrs.definition_id` (envelopes.py `_resolve_definition`). | detect.py:567-623, 774-860; library_router.py:95-121; library_import.py:33-49; links.py:128-145, 227-268 |
| (b) CAD body | **suggested** (only when a fingerprint `same_as` already exists) and **manual** (attach "From a file"); no automatic | Ownership edge `contains` (category node → CAD part), origin manual, written by `attach_existing_parts` (store.py:613-703, `_contains` store.py:490-503). The suggestion requires a pre-existing `same_as` edge, `origin == "fingerprint"`, `confidence >= 0.8`, `attrs.matched is True`, `attrs.canonical_id`, between a connected `Domain.MECHANICAL` connector part and a part a robot owns (cad_suggestions.py:81-119, 123-168) → `HardwareSuggestion(subject_kind="part", modality cad_model, evidence.matched_on="existing_same_as")` → accept → `attach_existing_parts` (cad_suggestions.py:217-249). Result: the CAD part becomes a *second* part under the robot category; no edge from the detected part to the CAD part is written. `same_as` writer is linking/linker.py (`RELATION_SAME_AS="same_as"`, `LINK_ORIGIN="fingerprint"`, lines 71-72) over connector entities. Scene level: `bench_scene_model.attrs.cad_bindings = [{mesh_key, source_entity_id}]` binds a mesh to a CAD *source entity* (schemas.py:47-56, `PUT /models/{id}/cad-bindings` scene/router.py:140), not to a part. | cad_suggestions.py; store.py:490-503, 596-703 (route hardware_router.py:596); scene/schemas.py:47-56 |
| (c) Schematic symbol | **absent** as part↔component link | No `same_as`/`wires`/other edge is ever written between a detected `part` and a `component`. What exists near it: `wires` edges component↔component from the netlist (`graph/inference/power_nets.py:133-140`, `attrs.nets`, `attrs.pins[<entity_id>]`); `presence_topology.py` mode `"schematic"` verifies an MCU-input wiring claim against schematic nodes/edges and emits evidence rows (lines 40-57, 133-197); `topology_observations.schematic_topology` (lines 256-273) emits `TopologyEvidence(source_kind="schematic")` rows which, once accepted, become `hardware_connected_to` edges (`topology.py` MARKER `hardware_topology_v1`, lines 22-27). None of these name a detected part by `external_ref`. | presence_topology.py:40-57,133-197; topology_observations.py:256-273; topology.py:22-27 |
| (d) URDF/MJCF joint | **manual** (PUT mapping); CAD import yields **suggested candidates only** (not persisted as bindings) | `bench_scene_model.attrs.bindings[] = {joint, part_entity_id, device_id, signal, unit, scale, offset}` (schemas.py:30-45) written by `PUT /bench/scene/models/{model_id}/mapping` (scene/router.py:105; service.py:250-283). Validation: joint must exist and not be `fixed`, unique per joint and per (part, signal), `accepted[part_entity_id] == binding.device_id` where `accepted` is `part_ref(config.identity.device_ref, bus_map.address)` (service.py:249-266), prismatic ⇔ unit `m` (268-270); `attrs.config_digest` stamped (280). Readers: `part_bindings.bound_scenes` / `scene_joint_for_part` (jsonb containment on `attrs.bindings[].part_entity_id`, part_bindings.py:54-87, 111-132) feeding the `scene` envelope source. CAD import writes `"bindings": []`, `joints: []` (cad_import.py:505, 548); `twin_of` lists `candidate_joints` from `mates_with` with `_actuator(entry)` = `{part_entity_id,...}` by bus_map (cad_import.py:271-298, 390-396) — a proposal payload, not a stored binding. There is **no joint entity** ("there is no joint entity yet", joint_limits.py:3). | scene/service.py:250-283; scene/schemas.py:30-45; part_bindings.py; cad_import.py:271-298, 505, 548 |
| (e) Code site | **inferred automatically, but only from human-accepted extraction rows** (ADR-012 flow) | Edges `commands` (code_file → part, confidence 0.8; 0.55 when `source_kind == "host_config"`; `attrs={"address","protocol","commanded"}`) and `reads` (code_file → part via the brain's `wires.attrs.pins`, confidence 0.55, `attrs={"pin"}`), evidence `EdgeEvidence(kind=FIRMWARE_SYMBOL, ref="<file>:<line>")` (firmware_edges.py:195-266). Address → part through the robot's `bus_map` (`_bus_map`, exactly one match required, firmware_edges.py:240-246). Input rows are `hardware_evidence_for` edges with `attrs.row` = `TopologyEvidence` (topology.py:22-24 `EVIDENCE_MARKER="hardware_extraction_evidence_v1"`, `EVIDENCE_RELATION="hardware_evidence_for"`), accepted via `topology_acceptance.py` → `infer_after_acceptance` (topology_acceptance.py:14). The "code site" is the `code_file` entity resolved by path suffix (`resolve_code_entity`); the line number lives only in evidence `ref` and `attrs.commanded.min_ref/max_ref` — no line/symbol node. `limits` (joint_limits.py) runs **bench_scene_model → code_file**, not to a part, `attrs={"joint","constant","line","matches"}`, confidence 0.5. UI: ExtractionReviewCard.tsx (`proposeExtraction`/`confirmExtraction`). | firmware_edges.py:1-17, 195-283; joint_limits.py:1-12, 113-163; topology_acceptance.py:1-30 |
| (config → part) | automatic on every config write | `binds` edge (legacy name, relations.py:56) config node → part, origin manual, confidence 1.0, `attrs={"device_ref","address","protocol","config_version","enabled"}`, `edge_id = uuid5(owner, f"binds:{target}:{ref}:{protocol}")` — bindings.py:40-108, called from store.py:276 on `put_entity_config`. Disabled (`enabled: False, disabled_reason: "ownership_changed"`) by `disable_part_bindings` (bindings.py:111-159; callers ownership.py:152, physical_robots.py:279). | bindings.py; store.py:237, 276 |

Verbatim — the edge vocabulary (relations.py:26-66):
```
class RelationType(enum.StrEnum):
    # identity
    SAME_AS = "same_as"
    # structure
    CONTAINS = "contains"
    PART_OF = "part_of"
    # dependency
    COMMANDS = "commands"
    READS = "reads"
    WIRES = "wires"
    POWERS = "powers"
    DRIVES = "drives"
    MOUNTS = "mounts"
    MATES_WITH = "mates_with"
    LIMITS = "limits"
    DEPENDS_ON = "depends_on"
    REQUIRES = "requires"
    HOSTS = "hosts"
    PUBLISHES = "publishes"
    SUBSCRIBES = "subscribes"
    # outcome
    MEASURED_BY = "measured_by"
    OBSERVED = "observed"
    FIXED_BY = "fixed_by"
    VERIFIED_BY = "verified_by"
    # legacy (written before this vocabulary; kept readable, never emitted by inference)
    CONNECTED_TO = "connected_to"
    CONFIGURES = "configures"
    BINDS = "binds"
    HARDWARE_CONNECTED_TO = "hardware_connected_to"
    HARDWARE_TOPOLOGY_MEMBER = "hardware_topology_member"
    HARDWARE_EVIDENCE_FOR = "hardware_evidence_for"
    PRESENCE_PREPARED_FOR = "presence_prepared_for"
    WIRING_PROPOSED_FOR = "wiring_proposed_for"
    DEPLOYMENT_FOR_TARGET = "deployment_for_target"
    CAD_VISUAL_FOR = "cad_visual_for"
    CLONE_OF = "clone_of"
    REFERENCES = "references"
    READS_FROM = "reads_from"  # read by checkers/core.py; superseded by `reads`
```

Verbatim — the scene joint binding (scene/schemas.py:30-45):
```
class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    joint: str = Field(min_length=1, max_length=128)
    part_entity_id: uuid.UUID
    device_id: str = Field(min_length=1, max_length=256)
    signal: str = Field(min_length=1, max_length=128)
    unit: Literal["rad", "deg", "m"]
    scale: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    offset: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0, strict=True)
    bindings: list[Binding] = Field(max_length=128)
```

---

### Q19: A part with no design counterpart — telemetry, findings, card
Status: exists (yes, fully; no "placeholder design" concept)
Where: packages/api/src/solus_api/hardware/detect.py (902), hardware/store.py (727), graph/resolver.py (99), graph/telemetry.py (323), livebench/sessions.py (516), livebench/findings/window_evaluator.py (765), livebench/findings/envelopes.py (770), hardware/connections.py (420), apps/desktop/src/renderer/src/features/graph/hardware/DeviceCard.tsx (295), features/bench/BenchScreen.tsx (257), features/bench/DeviceBenchView.tsx (570)
Note: A detected part is created from the wire alone and needs no library, CAD, schematic or scene counterpart; telemetry resolves to it by `external_ref`, the window evaluator runs rules on whatever channels it streams (envelope sources are all optional — without any, `build_envelope` returns None and the evaluator records `missing_signals` on the robot), and the Bench shows its device by session. The string "placeholder" does not occur in hardware/ or livebench/; the closest concepts are `LifecycleState.PLANNED` authored parts (no `external_ref`) and `bus_map` entries with `part_entity_id: None` (a free slot).

Trace:
1. **Creation** — `confirm_proposal` (detect.py:774-860): per accepted row, `attach_part(... attrs={"address": row.address, "model": row.model, "device_ref": proposal.device_ref}, provenance=DETECTED|REPO, external_ref=row.id)` → `GraphEntity(kind="part", domain=Domain.PROJECT, origin="manual", external_ref=<device_ref>/<address>, attrs += {"category","robot_id","provenance"})` under the robot's category node via `contains` (store.py:506-541). Config layer `detected`: `bus_map[] = {protocol: driver_id, address, part_entity_id, model}`, `parts[id] = {"telemetry": [{"name": f"{name}.position", "unit": None}], "lifecycle": "live"}` (detect.py:833-845). No definition_id, no scene, no code.
2. **Telemetry** — `DbEntityResolver.resolve` matches `packet.device_id == GraphEntity.external_ref` within the project (graph/resolver.py:79-92; module docstring line 4 "the identity linchpin"). `TelemetryPlumbing.ingest` (graph/telemetry.py:140-175) attaches samples to that entity or buffers them as unresolved. `SessionManager` tap: `result.entity_id` → `session.ingested += 1` and `_note_part(session, entity_id, packet)` records the part's channels (sessions.py:375-393); `SessionView.parts` (sessions.py:89-99) is what the evaluator reads.
3. **Findings** — `WindowEvaluator._load` → `load_envelope_inputs(db, project_id, streamed)` keeps any live entity with `kind in PART_KINDS` (envelopes.py:534-560; `PART_KINDS = {"part","component","cad_part","assembly"}`, store.py:581); envelope sources (config limits, definition, scene joint, sim expected, baseline) are each optional (envelopes.py:10-15); with none, `build_envelope` → None and the part has no envelope but rules still run over its channels (`_all_channels(streamed[part], one.config)`, window_evaluator.py:410-416), and what cannot be judged lands in `robot.attrs.missing_signals` (window_evaluator.py:708-731). Findings are raised with `source="observer"`, `bucket=str(session_id)` (window_evaluator.py docstring step 5).
4. **Session start** — `ConfirmIn.start_session` defaults True (detect.py:222); the route schedules `hardware_connections.schedule(project, user, robot, attempt_id, window_seconds)` after commit (hardware_router.py:812-815) and stamps `robot.attrs.connection = connection_state(attempt_id, status="connecting")` (hardware_router.py:751-755; connections.py:51-65). `_run` opens local hardware and `manager.start(...)` (connections.py:281-312).
5. **Card** — onboarding: `DeviceCard` → `doneText` renders "Added · connecting…" / "Added · connected" / "Added · <session_error>" (DeviceCard.tsx:39-52). Bench: `BenchScreen` derives `deviceIds = activeDeviceIds(sessions) ∪ externalDevices` (BenchScreen.tsx:76) and renders `BenchSignals`/`DeviceBenchView` per device (BenchScreen.tsx:121-130); no design counterpart is consulted.

Placeholder-adjacent facts:
- Authored part: `create_part` (store.py:544-578) → `attach_part(attrs={"specs"}, provenance=USER)` with no `external_ref`, config slot `PartConfig(lifecycle=<PLANNED|...>)`; `promote` (store.py:706-727) moves lifecycle only.
- Library part: "No `external_ref`: the wire assigns identity later, through detection and the suggestion inbox" (library_router.py:107-108).
- Free slot: `BusMapEntry.part_entity_id: uuid.UUID | None` (config.py:111-118); `_rule_slot` scores a detected part into an empty slot at the same address (links.py:101-114).

---

### Q20: Code in the graph — files, symbols, ROS
Status: partial (code files are nodes; ROS nodes/topics are nodes; no symbol/constant/pin/function nodes anywhere)
Where: packages/api/src/solus_api/graph/kinds.py (92), connectors/code_host.py (218), connectors/github.py (573), connectors/gitlab.py (481), connectors/local_folder.py (766), software/ros_reader.py (618), graph/inference/ros_edges.py (208), livebench/src/livebench/recognition/firmware.py (473), livebench/src/livebench/plugins/arduino/sketch_parser.py (266), livebench/src/livebench/plugins/arduino/wiring.py (66), livebench/src/livebench/plugins/lerobot/lerobot_parser.py (342), livebench/src/livebench/hardware/repo_config.py (499), agent/tools/read_code_file.py (365)
Note: `integrations/github/` is an empty directory on HEAD; the GitHub/GitLab readers live in `packages/api/src/solus_api/connectors/{github,gitlab,code_host}.py`. Firmware symbols (pins, constants, attach/goal calls) never become entities: they are `FirmwareFinding` → `TopologyEvidence` rows stored on `hardware_evidence_for` edges (`attrs.row`) and, after acceptance, folded into edge attrs (`commands.attrs.commanded`, `limits.attrs.matches`). Repo-config parsers (sketch, lerobot, generic YAML/JSON/TOML) produce `RepoConfigMatch` → `ProposalOut.repo_matches` → the `repo` config layer (part names, calibration) — also not nodes.

Entity kinds written per reader (verbatim `type=` strings):

| Reader | Kinds written | Code |
|---|---|---|
| connectors/github.py | `code_repo` (430); relations `contains` (449); modules/files/requirements via code_host | github.py:430-461 |
| connectors/gitlab.py | `code_repo` (337); `contains` (353); same code_host shapes | gitlab.py:337-353 |
| connectors/code_host.py (shared by both hosts) | `code_module` (190), `design_export` (202, `properties.export_kind/path/size/sha`), `code_file` (214, `properties={"size","sha","path"}`), `python_requirement` / `package_requirement` (141-142 via `requirement_entity`) | code_host.py:141-142, 187-218 |
| connectors/local_folder.py | root `local_clone` / `local_folder` (566); `PROJECT_KINDS = {"kicad": "kicad_project", "altium": "altium_project", "cad": "cad_folder", "arduino": "arduino_sketch", "python": "python_code"}` (83-89); `python_requirement` (154, 486-500); `ros_node` / `ros_topic` (519, 540); relation `REQUIRES` root → requirement (648) | local_folder.py:83-91, 154, 505-560, 566, 648 |
| software/ros_reader.py | writes nothing — pure parser returning `RosWorkspace(nodes: tuple[RosNode], topics: tuple[RosTopic], launched_at, declared_at)`; `RosNode{name, package, executable, publishes, subscribes}`, `RosTopic{name, type}` (82-105). Landed by `local_folder.ros_entities` as `kinds.ROS_NODE` with `properties={"package","executable","publishes","subscribes","launched_at","declared_at"}` and `kinds.ROS_TOPIC` with `properties={"type"}`. Edges `publishes`/`subscribes` by `graph/inference/ros_edges.py:42-43`. | ros_reader.py:82-105, 144; local_folder.py:512-549 |
| recognition/firmware.py | no kinds (see dataclass below); emits `ModalityMatch(modality=FIRMWARE_SYMBOL, confidence=0.55, state=LOW_CONFIDENCE)` evidence | firmware.py:97-124 |
| plugins/arduino/sketch_parser.py | no kinds; `RepoConfigMatch(config_id="sketch:<path>", parser_id="sketch-print-order", protocol_hint="raw-lines", parts=[RepoPartDecl(name, address=str(index))...], params={baud, declared_hz}, names_by_print_order=True)` | sketch_parser.py:243-266 |
| plugins/arduino/wiring.py | no kinds; `validate_wiring(profile_id, channel, kind∈{heartbeat,probe,topology}, wiring=[{channel,pin,kind∈{analog_input,digital_input}}])` for presence firmware | wiring.py:11-48 |
| plugins/lerobot/lerobot_parser.py | no kinds; `_LerobotClass{class_name, source, kinds, calibration_name, protocol_hint, port_hint, parts: list[RepoPartDecl], params}` → `RepoConfigMatch` | lerobot_parser.py:165-200, 266-342 |
| hardware/repo_config.py | no kinds; `RepoPartDecl{name, address, model, calibration_mode, calibration, calibration_source}`, `RepoConfigMatch{config_id, parser_id, label, source, protocol_hint, parts, port_hint, calibration_source, params, names_by_print_order}` | repo_config.py:57-84 |
| agent/tools/read_code_file.py | reads, never writes; requires `GraphEntity.kind == "code_file"` (86); tool `read_code_file` returns bounded line-numbered text (`MAX_LINES=200`, `MAX_TEXT_CHARS=16_000`) from a local saved copy or the synced commit | read_code_file.py:34-57, 74-100 |

Note: `kicad_project`, `altium_project`, `cad_folder`, `python_code` are **not** in `graph/kinds.py` (`ALL_KINDS`); kinds.py:4-5 says pre-existing modules keep local constants held equal by `tests/test_kinds.py` — these four are local to local_folder.py.

Verbatim — graph/kinds.py code/ROS/hardware block (lines 12-38, 59-62):
```
# electrical / code / mechanical (connectors)
PART: Final[str] = "part"
COMPONENT: Final[str] = "component"
NET: Final[str] = "net"
CODE_FILE: Final[str] = "code_file"
CODE_MODULE: Final[str] = "code_module"
CODE_REPO: Final[str] = "code_repo"
LOCAL_CLONE: Final[str] = "local_clone"
LOCAL_FOLDER: Final[str] = "local_folder"
ARDUINO_SKETCH: Final[str] = "arduino_sketch"
PYTHON_REQUIREMENT: Final[str] = "python_requirement"
PACKAGE_REQUIREMENT: Final[str] = "package_requirement"
CAD_DOCUMENT: Final[str] = "cad_document"
DESIGN_EXPORT: Final[str] = "design_export"
CANONICAL_PART: Final[str] = "canonical_part"

# hardware
PHYSICAL_ROBOT: Final[str] = "physical_robot"
ROBOT_CATEGORY: Final[str] = "robot_category"
HARDWARE_CONFIG: Final[str] = "hardware_config"
HARDWARE_BRAIN: Final[str] = "hardware_brain"
HARDWARE_BUS: Final[str] = "hardware_bus"
HARDWARE_EVIDENCE: Final[str] = "hardware_evidence"
HARDWARE_PRESENCE_PLAN: Final[str] = "hardware_presence_plan"
HARDWARE_WIRING_PROPOSAL: Final[str] = "hardware_wiring_proposal"
#: Legacy camel case; stored in dev DBs, so renaming it is a data migration.
COMPANION_DEPLOYMENT_PLAN: Final[str] = "companionDeploymentPlan"
...
# software (SOLUSDEV-321 P6, `software/ros_reader.py`): a ROS workspace's launched nodes and the
# topics their modules declare; `graph/inference/ros_edges.py` joins them.
ROS_NODE: Final[str] = "ros_node"
ROS_TOPIC: Final[str] = "ros_topic"
```

Verbatim — what `recognition/firmware.py` extracts (lines 63-71, 97-124):
```
FindingKind = Literal[
    "attach_call",
    "pin_constant",
    "motor_constant",
    "bus_begin",
    "analog_read",
    "library_include",
    "goal_call",
]
...
@dataclass(frozen=True)
class FirmwareFinding:
    """One extracted idiom instance, provenance-exact."""

    name: str
    kind: FindingKind
    file: str  # repo-relative posix path
    line: int  # 1-based
    language: Literal["cpp", "python"]
    pin: int | None = None
    value: float | None = None
    name_hint: str | None = None
    pin_ref: str | None = None  # exact source argument, including unresolved symbols

    @property
    def evidence(self) -> ModalityMatch:
        return ModalityMatch(
            modality=Modality.FIRMWARE_SYMBOL,
            source_ref=SourceRef(source_connector="repo", external_ref=self.file),
            confidence=0.55,
            state=MatchState.LOW_CONFIDENCE,
            evidence={
                "matched_on": "firmware_symbol",
                "value": self.name,
                "line": self.line,
                "note": _NOTE,
            },
        )
```
Caps: `MAX_FILE_BYTES = 1 MiB`, `MAX_FILES = 2000`, `MAX_EXTRACTION_BYTES = 256 KiB`, `MAX_EXTRACTION_FINDINGS = 256`, `MAX_GOAL_FINDINGS = 64` (firmware.py:48-49, 423-427). Goal calls: name matches `^(write|setgoal|settarget)` (case-insensitive), first argument a numeric literal ≤ 32 bits (firmware.py:74-76, 227-248).

Answer to "are symbols nodes": **no**. Constants, functions, pins, IDs: no entity kind exists for them (`ALL_KINDS` has none); pins appear only as edge attrs (`wires.attrs.pins`, `reads.attrs.pin`, `commands.attrs.address`) and library `PinSpec` (library.py:104-106). ROS nodes/topics: **yes**, `ros_node`/`ros_topic` entities. Code files: **yes**, `code_file` (hosts) and `arduino_sketch`/`python_code` project nodes (local folder); the local folder scan does not land per-file `code_file` nodes (only project/requirement/ROS nodes — local_folder.py:617-648).

---

### Q21: Characterization — learned per-part behaviour
Status: partial (one learned signal exists: baseline-run p1/p99 + rate per channel, computed on the fly and cached; nothing else learns; nothing persists learned values)
Where: packages/api/src/solus_api/livebench/runs/router.py (423), livebench/runs/store.py (199), livebench/runs/analysis.py (759), livebench/findings/envelopes.py (770), livebench/findings/window_evaluator.py (765), hardware/config.py (382), services/solus_config.py (572), livebench/findings/rules/tracking_rules.py (486), livebench/findings/rules/body_rules.py (255), livebench/src/livebench/faults.py (170)
Note: The only "learned" path is: a human marks one stopped run per robot as baseline (`POST /runs/{run_id}/baseline`), the window evaluator loads that run's manifest, and `_learned_stated` computes the p1/p99 of each part channel plus `expected_hz` as a 0.6-confidence `nominal` band. That result lives only in the Redis `EnvelopeCache` for 600 s; nothing writes it to the part, the config, or the run. No current-vs-speed, thermal rate, latency, noise floor or backlash estimator exists (those words occur only in narrative cause strings and in the fault-injection evaluator's `latency_seconds`).

grep results (non-test, `baseline|learned|characteriz` in packages/api/src/solus_api/livebench, hardware, livebench/src): hits only in `livebench/runs/store.py:42-66,129,192`, `livebench/runs/analysis.py:166-316,540-546`, `livebench/findings/window_evaluator.py:19,338,397,421-473`, `livebench/findings/envelopes.py:15-27,84,96,139-140,160-161,179,326-336`. `characteriz`: **no hits**. Nothing in `hardware/` or `livebench/src/`.

What exists:
- Marking: `mark_baseline` (runs/router.py:338-373) — refuses `status == "running"` (409 `run_active`), unmarks the robot's previous baseline, sets `bench_run.attrs.baseline = True`. `baseline_for` (runs/store.py:54-74) reads `attrs.baseline == "true"` AND `attrs.summary.robot_id == robot`, newest first.
- Loading: `WindowEvaluator._baseline_run` (window_evaluator.py:421-446) loads the manifest once per baseline id; failure → "no learned bounds" warning, never an error.
- Learning: `_learned_stated` (envelopes.py:326-362): samples = packets with `device_id == part.device_id` and `channel.name in packet.values`; requires `MIN_LEARNED_SAMPLES = 20` and a single canonical unit; `cuts = statistics.quantiles(values, n=100, method="inclusive")`; nominal `lo = cuts[0]` (p1), `hi = cuts[98]` (p99); `hz = (len(times)-1)/span`. Source `"learned"`, confidence `0.6` (envelopes.py:84, 96). Precedence: config 1.0 > definition 1.0 > scene 1.0 > sim 0.8 > learned 0.6 (envelopes.py:10-15, 91-97).
- Storage: `EnvelopeCache` — "Envelopes in the shared store (Redis when there is one) under `str(EnvelopeKey)`, 600 s" (envelopes.py:678-680; `ENVELOPE_TTL_SECONDS = 600` line 141; `MAX_INDEXED_KEYS = 256` line 144). `EnvelopeKey = (project_id, part_id, quantity, config_version, definition_id, run_id)` (window_evaluator.py:458-460). **Not** written to part attrs or config.
- Comparison (not learning): `runs/analysis.compare(baseline, candidate)` (analysis.py:299-316) returns `config_changes`, `source_snapshots_changed`, `divergences`, `clamp_attributions`, `finding_deltas`, `expected: "sim" | "baseline_run"`, `sim_control` — a diff between two run manifests, no model fitted.

Where results *would* go today: the `environment/hardware` CONFIG cell is `EntityHardwareConfig` (solus_config.py:105-114; store.py:49 `HARDWARE_SUBSECTION = "hardware"`), whose `PartConfig` holds only `calibration: PartCalibration{mode, values, source, owner}`, `limits: PartLimits{values}`, `telemetry: [TelemetryChannel{name, unit}]`, `firmware: dict`, `lifecycle` (config.py:152-185) — every valued leaf needs a `ProvenanceRecord{by ∈ library|repo|user|sol|detected, source}` (config.py:37-50, 283-309). There is no `learned`/`measured` provenance value and no learned field. Part entity attrs for detected parts are `{address, model, device_ref, category, robot_id, provenance}` (detect.py:830, store.py:521-531) — no measured values.

Not present (grep `noise floor|noise_floor|backlash|thermal|latency|hysteresis|deadband`, non-test): `backlash` only as cause text (tracking_rules.py:478 "backlash in the gear train drives a limit cycle"; body_rules.py:184 "compliance or backlash between them"); `latency_seconds` only in `livebench/src/livebench/faults.py:42,157,166` (fault-injection detection latency, an evaluation metric). No thermal-rate, current-vs-speed, noise-floor code.

---

### Q22: Physical test routines (bus ping, pin toggle, jog, sweep, step response, hold, human-prompted steps)
Status: absent (no jog/sweep/step-response/hold/pin-toggle routine and no "move it by hand" prompt); what exists is a broadcast presence PING during detection, read-only telemetry sweeps, and flashable Arduino presence sketches (heartbeat/probe/topology) behind the confirmation gate
Where: livebench/src/livebench/hardware/interrogator.py (103), livebench/src/livebench/plugins/dynamixel/dynamixel_interrogator.py (76), livebench/src/livebench/plugins/feetech/feetech_driver.py (278), livebench/src/livebench/plugins/feetech/feetech_codec.py (195), livebench/src/livebench/plugins/arduino/wiring.py (66), packages/api/src/solus_api/hardware/presence.py (388), hardware/presence_topology.py (362), hardware/hardware_router.py (1113), agent/tools/firmware_presence.py (65), hardware/topology_acceptance.py (222), apps/desktop/src/renderer/src/features/graph/robots/PresenceCard.tsx (384), PresenceWiringCard.tsx (524)
Note: The grep for `jog|sweep|step_response|step response|move the joint|by hand|pin toggle|toggle a pin|\bping\b` (word-bounded, non-test, across packages/api/src, livebench/src, apps/desktop/src, packages/companion/src) finds `sweep` only as connector scheduler vocabulary and the Feetech *read* loop, `ping` only in the Dynamixel interrogator / `interrogator.py` safety class / a GitHub webhook event / a shell-command risk list, and `by hand` only in a deps.py comment. The codecs *define* goal-position and torque-enable writes but no driver or route calls them.

| Routine | Exists? | Where / how gated | Callable by |
|---|---|---|---|
| Bus ping (presence) | yes — Dynamixel Protocol 2.0 broadcast ping (`Safety.PING`) | `DynamixelInterrogator.probe` (dynamixel_interrogator.py:49-75) runs inside `propose_via_local` for every detected device; `interrogator.py` Safety classes: `PASSIVE`, `PING`, `LISTEN` (lines 25-28); "Commanding motion is not an interrogation — that stays behind the confirmation gate (RBT-04)" (lines 5-6). Not user-gated (detection opens the port for the proposal budget). | UI automatically (`POST /hardware/detected/{ref}/propose`); not a SOL tool |
| Telemetry sweep (read) | yes — read-only register sweep | Feetech driver reads position every sweep, load+temperature every 10th (`_HEALTH_EVERY_N_SWEEPS`, feetech_driver.py:5, 53, 186-191); no write path called. `feetech_codec.write_goal_position` / `write_torque` exist (feetech_codec.py:97-101) and `dynamixel_definitions` has `goal_position`/`torque_enable` registers (lines 39-40) — **no caller** in livebench/src or packages/api (grep `goal|torque|write_register|set_position|actuate` in plugins/hardware/telemetry). | Starts with a robot session |
| Pin toggle | **absent** | — | — |
| Jog / sweep (motion) / step response / hold | **absent** | No code commands a goal position anywhere. | — |
| Human-prompted step ("move the joint by hand") | **absent** | No such prompt string in api, livebench, desktop or companion. | — |
| MCU presence firmware (heartbeat / probe / topology) | yes — Solus-authored Arduino sketch flashed to `uno_avr`/`nano_avr` | `PreparePresence.kind ∈ {"heartbeat","probe","topology"}`, `profile_id ∈ {"uno_avr","nano_avr"}`, topology requires an accepted `wiring_proposal_id` (presence.py:33-46). "probe" reads declared analog/digital inputs (`validate_wiring`, wiring.py:11-48) — a pin *read*, not a toggle. Routes: `POST /robots/{robot_id}/brains/{brain_id}/presence/prepare` (hardware_router.py:1019), `/presence/wiring/propose` (1057), `/presence/wiring/{proposal_id}/accept` (1086), `GET /presence/profiles` (989). Execution: "preparation never opens hardware; execution is gated" (presence.py:1). | UI: PresenceCard.tsx / PresenceWiringCard.tsx; SOL: `hardware.flash_presence` with `requires_confirmation=True` and a consent card ("A firmware action must never fall back to plan-ID-only consent", firmware_presence.py:17, 45-59) |
| Commanded fact (code-stated, not a test) | yes — from firmware extraction | `commands.attrs.commanded = {min,max,unit,min_ref,max_ref}` from literal goal calls (firmware_edges.py:8-17); accepted through `topology_acceptance.py` → `infer_after_acceptance` (line 14). It is static code intent, never an executed test. | UI: ExtractionReviewCard.tsx |

SOL tools that touch hardware (grep `name="` in agent/tools): `hardware.flash_presence` (gated), `hardware.deploy_companion` (companion_deployment.py:51), `get_telemetry` (builtin.py:117), `run_checkers` (184), `bench.list_cad_sources` / `bench.import_cad_scene` / `bench.cad_import_status` (bench_scene.py:83-102), `set_hardware_config_field` (solus_tools.py:461), `code.resolve_environment` (environment.py). None commands motion or toggles a pin.

---

### Q23: The current onboarding UI and the click path to live data
Status: exists
Where (components, `wc -l`): apps/desktop/src/renderer/src/features/graph/hardware/HardwareAddPanel.tsx (99), DevicesFound.tsx (73), DeviceCard.tsx (295), deviceCardRules.ts (146), PendingDeviceCards.tsx (47), useDeviceProposals.ts (458), useProposalSources.ts (116), useDetectedDevicesFeed.ts (52), detectedDevicesStore.ts (31), detected.ts (67), HardwareSearch.tsx (445), DescribeNew.tsx (197), UnassignedParts.tsx (250), HardwareSourcesPanel.tsx (303), HardwareConfigPanel.tsx (210), InlineSupplierResults.tsx (120), createUnassignedPart.ts (21); features/graph/robots/ExtractionReviewCard.tsx (365), PartLinkSuggestions.tsx (114), HostAttachmentCard.tsx (320), PresenceCard.tsx (384), PresenceWiringCard.tsx (524), FirmwareTelemetryOffer.tsx (246), RobotOrphans.tsx (134), usePhysicalRobots.tsx (143); features/graph/WorkspaceAdd.tsx (266), AddSourceRows.tsx (128), WorkspaceScreen.tsx (874), useWorkspaceEvents.ts (160), WidgetRegistrationContent.tsx (78); features/workspace/WorkspaceShell.tsx (809); features/bench/BenchScreen.tsx (257), ConnectDeviceModal.tsx (122), SavedRobotConnections.tsx (124), DeviceBenchView.tsx (570), useActiveBenchSessions.ts (61); widgets/livebench/LiveBenchWidget.tsx (239), widgets/livebench/recognition/RecognitionPanel.tsx (159); lib/api/hardware.ts (531)
Note: None of `DetectedModal`, `ProposalView`, `LibraryModal`, `FromFileModal`, `AuthoredPartModal` exist on HEAD (grep -rl over apps/desktop/src/renderer/src matches only `HardwareAddPanel`). Their roles are filled by: `DevicesFound`+`DeviceCard` (detected/proposal), `HardwareSearch` (library search + import, with `InlineSupplierResults`), `UnassignedParts` (attach "From a file"), `DescribeNew` (authored part). The onboarding surface is a *section of the Add modal* (tab "Hardware") plus a canvas-edge rail (`PendingDeviceCards`) that shows the same cards without opening the modal. Live data is on a different screen (Live Bench), reached from the left rail.

Component map (HardwareAddPanel.tsx:56-97): sections "Devices found" → `DevicesFound`; `HardwareSourcesPanel` ("Local configuration and calibration"); "Search" → `HardwareSearch` (`searchLibrary`, `importLibraryPlatform`, `importLibraryPart`, lib/api/hardware.ts:483-516); "Describe something new" → `DescribeNew` (`createHardwarePart` → `POST /robots/{id}/parts`); `UnassignedParts` (`listUnassignedParts`, `attachParts` → `POST /robots/{id}/parts/attach`). Robot-node cards (features/graph/robots/) appear on the robot's graph node after confirm: `HostAttachmentCard`, `PresenceCard`, `PresenceWiringCard`, `ExtractionReviewCard`, `FirmwareTelemetryOffer`, `PartLinkSuggestions`, `RobotOrphans`.

Click path, plug-in → live data (minimum path, via the rail):

| # | User action (clicks) | Component · handler | Network |
|---|---|---|---|
| 0 | Plug the device in (0 clicks) | Backend SSE `hardware.devices_changed` → `useWorkspaceEvents.ts:62-64` → `onDevices` → `detectedDevicesStore.setDevices` (useDetectedDevicesFeed.ts:23-31); `PendingDeviceCards` renders when `pendingDevices(...) > 0` (PendingDeviceCards.tsx:27-31); `DevicesFound` also mounts inside Add › Hardware | SSE frame; seed `GET /projects/{id}/hardware/detected` (useDetectedDevicesFeed.ts:37) |
| 0′ | (auto, 0 clicks) proposal | `useDeviceProposals.schedule` starts `propose()` per pending card up to `MAX_IN_FLIGHT` (useDeviceProposals.ts:286-299, 256-280); silent devices (`driver_id === null`) retry on `SILENT_BACKOFF_MS`. **Gate:** `schedule` returns early while `sourceRefs === null || sourceError` (useDeviceProposals.ts:288-292); `sourceRefs` comes from the MAIN-process bridge `window.solus.hardware.sources.list()` (useProposalSources.ts:68-104) — `null` until it answers, `[]` when there is no bridge/project, error → "Local source review is unavailable…" and **no proposal ever starts** | `POST /projects/{id}/hardware/detected/{ref}/propose` body `{source_refs, repo_root?, budget_s?}` (hardware_router.py:645-685; opens the port, runs interrogators incl. Dynamixel PING, reads repo evidence) |
| 1 | (only if > 3 pending devices) click pill "N devices found" | PendingDeviceCards.tsx:36-42 `setExpanded` | — |
| 2 | (only if several repo configs matched) click one option | `ChooseRow` → `onChoose(configId)` (DeviceCard.tsx:197-225; `cardQuestion` kind `choose`) | — |
| 3 | Type a robot name **or** pick an existing robot in "Part of" (1 click + 1 choice) | `NameRow` input (aria-label "Robot name", placeholder = single repo match label) / `<select aria-label="Part of">` (DeviceCard.tsx:244-280) | — |
| 4 | Click **Add** (or "Add MCU connection" when firmware/protocol unknown) | `NameRow.add` → `onConfirm({target, repoConfigId?})` (DeviceCard.tsx:248-252, 289-291) → `DevicesFound.onConfirm` → `confirm(card.ref, input)` (DevicesFound.tsx:57-59) → `useDeviceConfirmation` builds `confirmBody`: `{target, accepted: defaultAccepted(proposal), repo_config_id?, connection_only, start_session: !connectionOnly, window_seconds: 1}` + `sourceOptions()` (useDeviceProposals.ts:305-317, 427-456); `defaultAccepted` = every row, category `sensors` if `proposal.stream` else `actuators`, `function_name = row.proposed_function` (deviceCardRules.ts:115-122) | `POST /projects/{id}/hardware/detected/{ref}/confirm` (hardware_router.py:687-851): `confirm_proposal` (robot + parts + config), `hardware_connections.schedule(...)` when `start_session`, graph-changed frame; card → "Added · connecting…" (DeviceCard.tsx:39-52) |
| 4′ | Alternative to 3–4 when the card offers "It's <robot you imported>": click that button | `NameRow` suggestion button → `onAccept(suggestion)` (DeviceCard.tsx:281-285) → `accept(card.ref, suggestion.id)` (DevicesFound.tsx:60-65; useDeviceProposals.ts:376-398) | `POST /projects/{id}/hardware/suggestions/{sid}/accept` → `_bind_accepted_device` → `bind_device` + `_start_robot_session` (hardware_router.py:937-990) |
| 5 | Click **Live Bench** in the left rail | WorkspaceShell nav item `{ screen: 'bench', label: 'Live Bench' }` (WorkspaceShell.tsx:500) → `BenchScreen` (447-449); alternatively a robot widget's "Open bench" button (`WidgetRegistrationContent.tsx:46-48` → `navigate('bench')`, WorkspaceShell.tsx:440) | `useActiveBenchSessions` → `listBenchSessions(projectId)` (useActiveBenchSessions.ts:31); `deviceIds = activeDeviceIds(sessions) ∪ externalDevices` (BenchScreen.tsx:76) → `BenchSignals`/`DeviceBenchView` + WS stream (`useBenchRealtime`) |

Count: **2 clicks + typing a name** from the rail (Add, Live Bench), **4 clicks + typing** via the modal (Add button WorkspaceAdd.tsx:227 → "Hardware" row AddSourceRows.tsx:116-121 → Add → Live Bench), plus 0–2 optional clicks (pill, repo-config choice). The proposal itself costs 0 clicks but is blocked until the local-sources bridge answers (see 0′).

Bench-side alternatives (no graph parts created): `BenchHeader` "Manage connections" (BenchScreen.tsx:203-205) → `ConnectDeviceModal` → `DeviceRow` Connect → `createBenchSession(projectId, {mode: 'real', config})` (ConnectDeviceModal.tsx:34-42, 99-107) — a raw serial session; `SavedRobotConnections` "Connect saved <robot>" (SavedRobotConnections.tsx:111-115) restarts a confirmed robot's session. "Add hardware" button on the Bench header (BenchScreen.tsx:207-209) requests the Add modal on the `hardware` tab (`WorkspaceShell.tsx:389-404` `openAddRequest: { tab: 'hardware' }`).

Other onboarding entries (no device): `HardwareSearch` → `POST /hardware/library/platforms/{id}/import` or `/parts/{id}/import` (library_router.py:180, 246; import then `_reconcile` runs the link engine against detected devices, library_router.py:124-135); `DescribeNew` → `POST /robots/{id}/parts` (store.create_part); `UnassignedParts` → `POST /robots/{id}/parts/attach`; `HardwareConfigPanel` → `GET/PUT /robots/{id}/config`.

---


## D. Live Bench


### Q24: Layout today — panes, component tree, route
Status: exists
Where: apps/desktop/src/renderer/src/features/bench/BenchScreen.tsx (257), BenchCanvasHost.tsx (164), DeviceBenchView.tsx (570), BenchRealtime.tsx (213), bench.css (386), findings/FindingsPane.tsx (232), findings/FindingCard.tsx (326), runs/RunsView.tsx (373), runs/RunEvidence.tsx (313), scene/ScenePanel.tsx (464), scene/SceneViewer.tsx (154), ConnectDeviceModal.tsx (122), SavedRobotConnections.tsx (124), widgets/livebench/LiveBenchWidget.tsx (239), widgets/livebench/widget.manifest.ts (15), features/workspace/WorkspaceShell.tsx (809), features/workspace/shellStore.ts (83), routes/AppRoutes.tsx (107)
Note: One vertically scrolling screen, not tabs: a top bar, a two-column CSS grid (scene left, signals+findings right), then two full-width "secondary" sections (Runs, then the widget canvas). No topology pane and no live sensor pane exist in the Bench; the "sensor" area is two hardcoded empty-state paragraphs.

**Route.** There is no React Router path for the bench. `AppRoutes.tsx:62` mounts `<RootRoute />` at `/` which renders `<WorkspaceShell />` (`AppRoutes.tsx:39`). The shell's own in-memory route (`shellStore.ts:22`: `export type MainScreen = 'home' | 'workspace' | 'bench' | 'sol' | 'store' | 'billing' | 'settings'`) selects the screen; `WorkspaceShell.tsx:447-449`:
```
      case 'bench':
        // Add Hardware opens the existing Workspace onboarding flow.
        return <BenchScreen onNavigate={navigate} onAddHardware={addHardware.request} />
```

**Grid.** `bench.css:38-40` `.bench-panes { grid-template-columns: minmax(260px, 300px) minmax(0, 1fr) }`; `:356-357` narrows to `minmax(220px, 260px) 1fr`; `:365-366` collapses to `1fr`.

**Component tree (two levels under BenchScreen):**

| Level 1 (BenchScreen.tsx) | Level 2 | Pane / role | File (lines) |
|---|---|---|---|
| `NoProject` (`:37-48`) | `ScreenEmptyState` | Empty state when no project is open: "Live Bench watches connected hardware" / "NO PROJECT OPEN" | BenchScreen.tsx |
| `BenchHeader` (`:179-213`) | `Button` ×3, status span | Top bar: Pause/Resume, `PAUSED`/`● STREAMING`/`NO STREAM`, "Manage connections", "Add hardware" (only when `deviceIds.length === 0`) | BenchScreen.tsx |
| `ConnectDeviceModal` (`:97-102`) | `Devices` (DeviceRow/SessionChip from `features/project/localconnections/`), `SavedRobotConnections` | Session start/stop UI: enumerated serial devices + simulators + saved robots | ConnectDeviceModal.tsx (122), SavedRobotConnections.tsx (124) |
| `SessionChips` (`:215-233`), `ConnectionStatus` (`:236-257`) | — | Per-session chips "label · starting / disconnected (session ended) / link"; "Reconnecting — periodic updates" / "Live data access is unavailable." | BenchScreen.tsx |
| `aside.bench-left` → `ScenePanel compact` (lazy, `:23-25`, `:108`) | `SceneViewer` (three.js), `SceneStatus`, spawn form (robot select, `CadImport`, URDF/MJCF file, STL files, format, revision, replace), `SceneSettings` → per model `CadBindings`, `MappingReview` | **Scene pane** | scene/ScenePanel.tsx (464), SceneViewer.tsx (154), CadImport.tsx (238), CadBindings.tsx (154), MappingReview.tsx (212) |
| `aside.bench-left` static text (`:110-118`) | — | **"Sensors" are static placeholders only**: `No camera stream available. Recorded video is time-aligned in Runs below.` / `No LiDAR or depth stream available. Recorded point clouds appear in Runs below.` No code reads a camera or LiDAR live. | BenchScreen.tsx:110-118 |
| `BenchSignals` (`:153-177`) → `DeviceBenchView` | heading `{n} SIGNALS · CLICK TO SCOPE · CLICK NAME TO RENAME` / `WINDOW 8 S`; `DeviceChips`; `SignalsStatus` (`FocusStatus` + `DeviceStatus`); `SignalGrid` → `SignalWidget`; `Diagnostics` (collapsed second grid for `display_role === 'diagnostic'`); `PlaceholderBanner`; `Reasoning` (`LIVE REASONING · SOL WATCHES THE RUN`) | **Signals pane** (+ observer-event list) | DeviceBenchView.tsx (570), SignalWidget.tsx (301), primarySignals.ts (12) |
| `BenchSignals` children → `FindingsPane` (`:169-174`) | `OpenedFinding`, `RobotGroup` → `SeverityBlock` → `FindingCard`; `CouldNotCheck` → `UncheckedList` | **Findings pane** (`FINDINGS · N OPEN`, one group per connected robot; returns `null` when no groups and nothing selected, FindingsPane.tsx:42) | findings/FindingsPane.tsx (232), FindingCard.tsx (326), useRobotFindings.ts (145), findingActions.ts (105) |
| `section.bench-secondary "Runs and capture"` → `RunsView` (lazy, `:27-29`, `:130-134`) | `RunWorkspace`: robot search/select, session select, run name, Start recording, `RecordingImport`, `RunLoadStatus`, run list with Stop, Next runs, `RunEvidence` → `RunPlayback`, `RunNarrationPanel`, `RunComparisonPanel`, `SensorPreview` | **Runs pane** | runs/RunsView.tsx (373), RunEvidence.tsx (313), RunPlayback.tsx (85), RunNarrationPanel.tsx (67), SensorPreview.tsx (124) |
| `section.bench-secondary "Workspace widgets"` → `BenchCanvasHost embedded` (`:135-145`) | `WidgetCanvas` (features/canvas) with `BenchHeader` (status `FOCUSED` / `NO PART FOCUSED` / `NOTHING STREAMING` / `AWAITING DEVICE DATA`, BenchCanvasHost.tsx:36-57) | **Widget canvas**; the `livebench` widget (`widget.manifest.ts:7-13`, domains `['simulation','runtime']`, size wide/standard) renders the FOCUSED entity's tiles + 4 SVG rolling charts + anomaly markers (LiveBenchWidget.tsx:204-254) | BenchCanvasHost.tsx (164), LiveBenchWidget.tsx (239) |

Panes present: signals (yes), scene (yes), findings (yes), runs (yes), widget canvas (yes), sensors (static text only), topology (absent in the Bench), empty states: `NoProject`; `Connected hardware signals appear here automatically.` (DeviceBenchView.tsx:448); `No recent values from … — nothing to show yet.` (`:538-540`); `No models imported yet.` (ScenePanel.tsx:162); `No runs have been captured or imported in this project.` (RunsView.tsx:356).

Minor: `DeviceBenchView`'s `robotCount` prop (`:188`, used in `Reasoning` `:499`) is never passed by `BenchScreen`, so "across N robots" never renders.

---

### Q25: What decides what Live Bench shows (focus, discovery, bare sensor vs arm)
Status: exists
Where: BenchScreen.tsx (257), useActiveBenchSessions.ts (61), useExternalBenchDevices.ts (50), BenchRealtime.tsx (213), benchStream.ts (158), DeviceBenchView.tsx (570), packages/api/src/solus_api/livebench/bench_router.py (737), livebench/stream.py (261), livebench/focus_scope.py (58), graph/telemetry.py (323), livebench/sessions.py (516)
Note: Focus is NOT required: discovery runs regardless of focus (`BenchScreen.tsx:1-2, 65-68`); focus only narrows displayed devices through a server-side authorized topology projection. Devices are discovered from two polls, never from USB/mDNS in the Bench itself.

**Discovery (L1) — trace:**
1. `useActiveBenchSessions(projectId, true)` → `GET /api/v1/projects/{p}/bench/sessions` every 5 s (`ACTIVE_SESSIONS_POLL_MS = 5_000`, `:11`); keeps `ended` sessions only if previously seen (`:35-40`). Server: `SessionManager.list` (sessions.py:427-444), in-memory.
2. `useExternalBenchDevices(projectId, true)` → `GET …/bench/telemetry-devices` every 5 s (`:88-103`). Server: `TelemetryPlumbing.observed_device_ids` (telemetry.py:122-125) = device ids that pushed a packet within `OBSERVED_DEVICE_TTL_SECONDS = 15.0` (`:45`), `OBSERVED_DEVICE_CAP = 128`/project, `OBSERVED_PROJECT_CAP = 256` (`:46-47`). This is how HTTP-ingest producers (`POST /bench/telemetry`, bench_router.py:141-173) appear without a session.
3. `deviceIds = [...new Set([...activeDeviceIds(sessions), ...externalDevices])]` (BenchScreen.tsx:77); a session remembers ≤ `DEFAULT_DEVICE_IDS_KEPT = 64` ids (sessions.py:46, 365-366).
4. Data path: `useBenchRealtime` opens one WebSocket per non-ended session (`connectBenchStream`, BenchRealtime.tsx:180-214) at `/ws/v1/bench/sessions/{session_id}` (stream.py:291). First frame `Authenticate` (`:94-98`), re-authorize every 5 s or when the observed entity set changes (`:224-229`), `telemetry` snapshot every `INTERVAL = 0.1` s of `session.device_ids[:64]`, ≤64 signals each, points within the last 8 s, downsampled to 128 (`snapshot`, `:150-185`); frames over 1 MiB re-downsample 128→32→8→1 then close 4413 (`:196-205`). Caps: 64 streams/process, 8/user, 60 connects/min per IP (`:269, 298, 303`).
5. Fallback when the stream is not ready/blocked: `useDeviceBatch` polls `GET …/bench/device-recent?device_id=…` in chunks of 16 every `POLL_MS = 2500` with `limit=512` (DeviceBenchView.tsx:18-21, 84-90), plus `GET …/bench/events?limit=100` every 5 s (`:117, 134`).

**Focus — trace:** `useSharedFocus()` → `focusEntityId` (BenchScreen.tsx:55, 69). Server `device_recent` (bench_router.py:697-737) calls `focus_entity_ids` (focus_scope.py:14-58): recursive CTE from the focused entity over live `GraphEdge`s with `origin == "manual"`, `source_id IS NULL`, `attrs.managed_by ∈ (MARKER, HOST_MARKER)`; for a `physical_robot` focus it follows `MEMBERSHIP`/`RELATION` edges with `attrs.robot_id == focus`, else `RELATION` only. A device is kept only if `view.resolved_entity_id in allowed` (`:729`) — an UNRESOLVED device is always hidden under focus. Client `useFocusedDevices` probes the same route with `limit: 1` (BenchRealtime.tsx:249-285); `streamSelection` swaps `realtime.devices` for `realtime.focused` (DeviceBenchView.tsx:556-570). Guide-mode copy for an empty focus: `:174-176`.

**One bare sensor (no graph entity, no robot):** reaches the Bench by pushing LB-06 packets or a `serial`/sim session. Packets fail `DbEntityResolver` → unresolved device ring (telemetry.py:176-196: ≤16 devices/project, ≤16 signals/device, 256 samples/signal; drop-new at caps), counted `unresolved`. Shown as a device chip + signal cards with packet names/units; `hasPlaceholder` (DeviceBenchView.tsx:418-423: no unit, or name matching `^(PWM|ADC|GPIO|pin|channel)[-_ ]?\d+$`) shows the placeholder banner. No findings: the evaluator is created only when `session.robot_entity_id is not None` (sessions.py:396-399), i.e. only `robot`/`hardware`/`replay` sessions. No scene movement (bindings require accepted bus-map parts, scene/service.py:249-267). Under focus it disappears.

**Full arm with CAD (`provider: "robot"`):** `_robot_opener` resolves the robot's `HardwareConfig` (bench_router.py:536-603), opens via `livebench.local.open_robot` (local.py:534-557); packets resolve per part by `external_ref == part_ref(device_ref, address)` (hardware/config.py:75-77) → entity feed (512 samples/signal); `channel_roles` from the driver's `device_facts` tag `display_role` (sessions.py:332-356, bench_router.py:732-735); `WindowEvaluator` ticks every 1 s per session (window_evaluator.py:317, 348-356) and raises findings, which `FindingsPane` groups by `connectedRobots(sessions)`; `ScenePanel` moves joints of models whose `bindings` name those device ids (useSceneValues.ts) and shows `SCENE LINKED TO CAD — UPDATES WHEN THE CAD CHANGES` when `cad_bindings` exist (ScenePanel.tsx:389-391).

---

### Q26: Session model — providers, config models, lifecycle owner, start/stop from UI and SOL
Status: exists (UI start/stop); absent (SOL start/stop)
Where: packages/api/src/solus_api/livebench/bench_router.py (737), livebench/sessions.py (516), hardware/connections.py (420), hardware/hardware_router.py (1113), hardware/local_runtime.py (94), hardware/runtime.py (149), livebench/replay_provider.py (144), livebench/src/livebench/local.py (571), livebench/src/livebench/sim/connections.py (81), livebench/src/livebench/hardware/connection.py (150), livebench/src/livebench/telemetry/stream_live.py (143), packages/api/src/solus_api/connectors/live.py (122), apps/desktop/src/renderer/src/lib/api/resources.ts (1777), ConnectDeviceModal.tsx (122), SavedRobotConnections.tsx (124), packages/api/src/solus_api/main.py (691)
Note: `provider` is a discriminator on the request union (7 literals) but a plain `str` on the wire-out model. One in-memory `SessionManager` per API process owns every `TappableConnection`; `HardwareConnections` wraps it for saved-robot connections started from the Hardware confirm flow and mirrors state onto `physical_robot.attrs.connection`. No SOL tool starts or stops a session.

**Provider values.** Request side (`bench_router.py:270, 281, 294, 308, 326, 334, 345`): `"mujoco" | "gazebo" | "mcap-replay"` (sim; `_SIM_PROVIDERS = {"mujoco", "gazebo", "mcap-replay"}` `:232`) and `"serial" | "robot" | "hardware" | "replay"` (real). Connection-class `provider: ClassVar[str]`: `"mujoco"` (sim/connections.py:24), `"gazebo"` (`:55`), `"mcap-replay"` (`:72`), `"robot"` (hardware/connection.py:30), `"noop"` (connectors/live.py:82). The driverless `serial` path opens `SerialRobotConnection` (livebench/telemetry/robot.py) — its ClassVar value: not determined (file not read).

**Out model (verbatim, sessions.py:152-169):**
```python
class BenchSessionOut(BaseModel):
    """Wire shape of one bench session (frozen contract with the desktop)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    mode: Literal["sim", "real"]
    provider: str
    status: Literal["starting", "active", "ended"]
    link: str
    label: str
    created_at: datetime
    ended_at: datetime | None
    device: dict[str, Any] | None
    device_ids: list[str]
    counts: dict[str, int]
    last_summary: dict[str, Any] | None
    robot_entity_id: UUID | None = None
```
`link` is `LiveStatus` (connectors/live.py:36-41): `DISCONNECTED = "disconnected"`, `CONNECTED = "connected"`, `STREAMING = "streaming"`.

**Request config models (verbatim, bench_router.py:267-371):**
```python
class MujocoSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mujoco"]
    scene_name: str = Field(default="demo", min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    mjcf_xml: str | None = Field(default=None, min_length=1, max_length=MAX_MJCF_BYTES)
    sample_hz: float = Field(default=50.0, gt=0, le=200)
    duration_seconds: float = Field(default=300.0, gt=0, le=MAX_SESSION_SECONDS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class GazeboSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gazebo"]
    topics: list[str] = Field(min_length=1, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str]) -> list[str]:
        return _clean_topics(topics)


class McapSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mcap-replay"]
    mcap_path: str = Field(min_length=1, max_length=4096)
    topics: list[str] | None = Field(default=None, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str] | None) -> list[str] | None:
        return None if topics is None else _clean_topics(topics)


class SerialRealConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["serial"]
    serial_number: str | None = Field(default=None, min_length=1, max_length=128)
    confirmed_device_path: str | None = Field(default=None, min_length=1, max_length=256)
    baud: int = Field(default=115200, ge=300, le=3_000_000)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)
    # SOLUSDEV-248: a protocol driver by id with generic parameters — never a closed list of
    # driver names in this schema; the registry decides what exists.
    driver_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    driver_params: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=32
    )


class RobotRealConfig(BaseModel):
    """A session from a Physical Robot's HardwareConfig (docs/api/hardware.md §6)."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["robot"]
    robot_entity_id: uuid.UUID
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class HardwareRealConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["hardware"]
    entity_id: uuid.UUID
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class ReplayRealConfig(BaseModel):
    """DEV ONLY (docs/api/bench-runs.md): a recorded capture replayed as one of the project's
    robots. `recording` is a file under `Settings.bench_replay_root`; `driver_id` decodes it."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["replay"]
    recording: str = Field(min_length=1, max_length=4096)
    driver_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    robot_entity_id: uuid.UUID
    realtime: bool = True
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("recording")
    @classmethod
    def _printable(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("recording may not contain control characters")
        return value


class BenchSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["sim", "real"]
    config: Annotated[
        MujocoSimConfig
        | GazeboSimConfig
        | McapSimConfig
        | SerialRealConfig
        | RobotRealConfig
        | HardwareRealConfig
        | ReplayRealConfig,
        Field(discriminator="provider"),
    ]

    @model_validator(mode="after")
    def _mode_matches_provider(self) -> "BenchSessionIn":
        is_sim = self.config.provider in _SIM_PROVIDERS
        if is_sim != (self.mode == "sim"):
            raise ValueError(f"provider {self.config.provider!r} does not run in {self.mode} mode")
        return self
```
Constants (bench_router.py:226-230): `MAX_MJCF_BYTES = 2_000_000`, `MAX_TOPICS = 32`, `MAX_SESSION_SECONDS = 3600.0`, `MAX_WINDOW_SECONDS = 60.0`. `replay` needs `Settings.bench_replay_root` (core/config.py:286); `mcap-replay` needs `bench_data_root` (`:282`); `/bench/sources` reports `isaac` as never startable (local.py:134-143).

**Lifecycle owner.** `SessionManager` (sessions.py:236-516), in-memory, project-keyed: `DEFAULT_MAX_ACTIVE_PER_PROJECT = 4`, `DEFAULT_ENDED_KEPT = 32` (`:44-45`). `start` reserves a slot synchronously, acquires the connection through shielded `open_conn` (`_acquire_connection`, `:135-149`), installs the packet `tap` (`_tap_for`, `:358-382`: every packet → `TelemetryPlumbing.ingest`, observer, `ingested`/`unresolved`, `_note_part`), `subscribe(TelemetryWindow(duration_seconds=window_seconds))`, `on_batch` → `last_summary`, starts the evaluator for robot sessions (`:264-330`). `stop`/`_close_session` sets `ended_at` first, cancels the evaluator (`EVALUATOR_STOP_SECONDS = 5.0`), `aclose()`s the connection, calls `on_ended` (`:446-493`). `_sweep_dead` ends sessions whose pump reports `DISCONNECTED` (`:495-502`). Wired once in `main.py:492-511` with `observer_factory = livebench.local.session_observers`, `event_sink → BenchEventRing.append`, `evaluator_factory → WindowEvaluator(...)`.

`HardwareConnections` (hardware/connections.py:76-420) is the second owner for saved robots: `schedule()` (called from the Hardware confirm route, hardware_router.py:771-773) runs `_run` → `resolve_runtime_config` + `prepare_local_hardware` + config stamp check → `manager.start(mode="real", provider="robot", …, robot_entity_id=…, owner_user_id=…)` (`:312-323`) and writes `attrs.connection = {managed_by:"local_runtime", attempt_id, status connecting|connected|failed|disconnected, session_id, error, runtime_id}` on the `physical_robot` (`connection_state`, `:49-64`), publishing `graph.changed`. `manager.on_ended = self._session_ended` (`:93`). `routers/entities.py:213` cancels a robot's connection on delete.

**Start/stop from the UI.** `ConnectDeviceModal` → `start()` → `createBenchSession(projectId, input)` (`ConnectDeviceModal.tsx:34-36`; `resources.ts:1507` → `POST /projects/{p}/bench/sessions`); saved robot sends `{ mode: 'real', config: { provider: 'robot', robot_entity_id: robot.id } }` (SavedRobotConnections.tsx:56-59); devices/simulators send their config via `Devices` (`:105`). Stop → `stopBenchSession` (`resources.ts:1541` → `POST …/bench/sessions/{id}/stop`). Server emits data events `bench.session_started` / `bench.session_stopped` (bench_router.py:636-644, 684-692 → `services/events.emit_event` → `DataEvent`).

**Start/stop from SOL: absent.** Every registered in-process tool name on HEAD (grep over `packages/api/src/solus_api/agent`):
```
add_solus_entry, altium, analyze_rail_current, autocad, bench.cad_import_status,
bench.import_cad_scene, bench.list_cad_sources, brave, code.resolve_environment,
delete_solus_entry, edit_solus_entry, extract_rulebook, firmware_recipe, fusion,
get_entity, get_envelope, get_finding, get_run, get_telemetry, hardware.deploy_companion,
hardware.flash_presence, isaac.* , kicad, label_motifs, link_environment,
machine.write_file, make_diagram, onshape_fs, propose_part_definition, query_graph,
read_code_file, read_document, render_view, retrieve_errors, run_checkers,
set_hardware_config_field, solidworks, solus.connect_integration,
solus.list_integrations, solus.verify_integration, FeatureScript, <mcp>.<remote> (dynamic)
```
(`get_finding`/`get_run`/`get_envelope` are registered via `bounded_read_tool` in finding_tools.py:131-166, which a `name="…"` grep misses.) SOL only READS sessions: `project_card.card_inputs` lists active sessions for `active_device_ids` (agent/project_card.py:317-325) and `GraphFactSources` is handed the `SessionManager` (agent/deterministic_facts.py:200-206).

---

### Q27: Telemetry pipeline — resolver, windowing, rings, units, unresolved packets, persistence
Status: exists (pipeline); absent (durable telemetry history outside Runs)
Where: packages/api/src/solus_api/graph/resolver.py (99), graph/telemetry.py (323), graph/buffer.py (206), graph/packet.py (153), livebench/src/livebench/telemetry/windowing.py (156), livebench/src/livebench/telemetry/normalize.py (129), packages/api/src/solus_api/livebench/persist.py (194), livebench/stream.py (261), bench_router.py (737), apps/desktop/src/renderer/src/features/bench/signalUnits.ts (62), retainedSignals.ts (41), widgets/livebench/telemetry.ts (112)
Note: Packets resolve to a graph entity by `external_ref == device_id`; resolved samples go into a 512-sample ring per (project, entity, signal), unresolved ones into a smaller per-device ring. Nothing is persisted beyond those rings except what a recording Run captures. `persist.py` is not telemetry persistence — it persists the CONFIRMED ROBOT IDENTITY through the fingerprint seam.

**Resolver.** `DbEntityResolver.resolve` (resolver.py:402-422): `select(GraphEntity.id).where(project_id == …, current_scope(project_id).entity_predicate(), external_ref == device_id, deleted_at IS NULL).limit(1)`. Wrapped in `CachingEntityResolver` (`:361-399`): positives cached 30 s, negatives never, cleared at 4096 entries. Wired `main.py:473`. Robot part ids are `part_ref(device_ref, address)` = `"<transport>:<binding>/<address>"` (hardware/config.py:75-77).

**Windowing.** (a) In the connection: `WindowAggregator` (windowing.py:70-156) — event-time, anchored at the first accepted packet, closed by the first packet at/after `anchor + duration`; stragglers behind the watermark dropped; backward re-anchor allowed if everything still fits; `MAX_SIGNALS_PER_WINDOW = 1024`, `MAX_SAMPLES_PER_WINDOW = 100_000`, `MAX_WINDOW_SECONDS = 86_400.0`; emits `TelemetryWindowSummary` `mean/min/max/last/count`; a session subscribes with `window_seconds` (default 1.0, ≤60) and keeps only `last_summary`. (b) In the plumbing: `get_telemetry` (telemetry.py:287-323) buckets the project's buffered samples into `DEFAULT_SUMMARY_BUCKETS = 6` sub-windows of the requested `duration_seconds` (≤3600, `GET /bench/summary`). The evaluator (Q29) judges in `tick_seconds`-wide event-time windows of its own.

**Ring-buffer sizes:**
| Buffer | Size | File:line |
|---|---|---|
| Resolved entity ring per (project, entity, signal) | `DEFAULT_CAPACITY = 512`; Redis variant LTRIM 512, `DEFAULT_TTL_SECONDS = 3600` | buffer.py:23-24 |
| Unresolved device ring per project | `DEFAULT_UNRESOLVED_DEVICE_CAP = 16` × `DEFAULT_UNRESOLVED_SIGNALS_PER_DEVICE = 16` × `DEFAULT_UNRESOLVED_SAMPLES_CAP = 256` (drop-new) | telemetry.py:55-57, 176-196 |
| Observed device set | TTL 15 s, 128 devices/project, 256 projects | telemetry.py:45-47 |
| Observer event ring per project | `MAX_EVENTS_KEPT = 512` | bench_router.py:64, 110-139 |
| Session memory | 64 device ids, 32 ended sessions, 32 channels/part, 4 active/project | sessions.py:44-50 |
| Packet bounds | `MAX_DEVICE_ID_LEN = 512`, `MAX_SIGNALS_PER_PACKET = 256`, `MAX_SIGNAL_NAME_LEN = 128`, `MAX_UNIT_LEN = 32`, seq ≤ 2^53-1, tz-aware timestamps, finite floats | packet.py:243-253, 280-321 |
| Ingest route | `MAX_BATCH_PACKETS = 500`, `MAX_BATCH_EVENTS = 100`, body ≤ 4 MiB, `MAX_DISTINCT_SIGNALS_PER_BATCH = 4096`, event detail ≤ 4096 B | bench_router.py:62-77 |
| WS snapshot | 8 s window, 64 devices, 64 signals, 128 points (down to 1), 1 MiB frame, 0.1 s interval, heartbeat 5 s | stream.py:86-91, 161-176 |
| Desktop | `WINDOW_MS = 8000`, `RECENT_LIMIT = 512`, `POLL_MS = 2500`, 256 retained signals/device, `LIVE_MS = 3_000`, `STALE_MS = 15_000` | DeviceBenchView.tsx:18-22, retainedSignals.ts:368-371, telemetry.ts:31-32 |

**Units.** Packet carries `units: dict[signal, str]` (packet.py:278); a unit for an absent signal is rejected (`:314-321`). `RecentSample.unit` stored as sent (`:324-331`); the plumbing never converts. Desktop `signalUnits.ts` converts only within fixed families `['rad','deg'], ['rad/s','deg/s'], ['m','cm','mm'], ['A','mA'], ['V','mV']` (`:3-9`) to a per-user preference and never draws a line across a sample whose unit cannot be compared (`displayGroups`, `:50-62`). Envelopes canonicalize spellings (`_SPELLINGS`, envelopes.py:112-126) and leave out sources in another unit; the evaluator drops samples whose unit differs from the envelope's ("nothing is converted", window_evaluator.py:16-17). Scene `jointValue` requires `point.unit === binding.unit`, converts only `deg → rad` (kinematics.ts:255-268). `normalize.py` is the Foxglove/MCAP JSON → packet flattener (numeric leaves, depth 8, topic = device_id, LB-06 spoofing guard), not a unit normalizer.

**Unresolved packets.** Not errors: `ingest` returns `IngestResult(entity_id=None, accepted=0)` and buffers in the unresolved ring (telemetry.py:154-156, 176-196); the session counts `unresolved` (sessions.py:375-376); the ingest route responds `{"accepted","unresolved","rejected"}` (bench_router.py:173). A device that later resolves drops its unresolved ring (`:160-162`). `device-recent` reads the unresolved ring when the resolver returns None (`:225-245`), with `resolved_entity_id: null`.

**Persistence beyond the ring.** `persist.py` = `persist_confirmed_robot` / `recognize_robot` (RBT-05): writes `kind="canonical_part"` entities through `fingerprint.ingest.ingest_output` with user-confirmation evidence, and diffs observed bus identities against persisted ones on reconnect (`:460-553`). It stores no samples. Telemetry history: "live ephemeral lifecycle, no durable history by decision" (sessions.py:6-7; bench_router.py:111-112); Redis ring TTL 3600 s. The only durable samples are Run manifests (Q28) captured via `TelemetryPlumbing.capture_sink` (telemetry.py:98, 143-149; main.py:563) while a run is `running`.

---

### Q28: Runs — manifest, storage, compare, playback, SOL access
Status: exists (capture/compare/playback/import/baseline); partial (SOL: summary read only, no compare)
Where: packages/api/src/solus_api/livebench/runs/models.py (128), capture.py (236), store.py (199), analysis.py (759), snapshot.py (247), router.py (423), narration.py (119), apps/desktop/src/renderer/src/features/bench/runs/RunsView.tsx (373), RunEvidence.tsx (313), RunPlayback.tsx (85), playback.ts (46), runsApi.ts (240), packages/api/src/solus_api/agent/tools/finding_tools.py (166)
Note: A run is a `bench_run` graph entity plus an 8 MiB JSON artifact of packets, a parts/revision snapshot taken at start, and the findings its session raised. Compare is a server-side pure diff (optionally against a simulation twin). Playback is a client-side slider over exact recorded instants. SOL can read a run's summary (`get_run`) but has no tool to list, open the packets of, or compare runs.

**RunManifest (verbatim, models.py:29-101):**
```python
class PartEvidence(StrictModel):
    entity_id: UUID
    name: Text
    device_id: Text
    current_signal: Signal | None = None
    position_signal: Signal | None = None
    command_signal: Signal | None = None
    stall_current_a: Annotated[FiniteFloat, Field(gt=0)] | None = None
    position_min: FiniteFloat | None = None
    position_max: FiniteFloat | None = None
    position_unit: Annotated[str, Field(max_length=32)] | None = None
    code_site: Text | None = None
    cad_revision: Text | None = None


class SensorReference(StrictModel):
    artifact_id: UUID
    timestamp: AwareDatetime
    kind: Literal["camera", "lidar"]
    device_id: Text


class RevisionSnapshot(StrictModel):
    entity_id: UUID
    kind: Text
    name: Text
    source_id: UUID | None = None
    revision: Text | None = None
    # JSON serialized CONFIG/graph data, individually bounded and inert.
    data: Annotated[str, Field(max_length=65536)] | None = None


#: The graph findings one run's manifest carries at most (SOLUSDEV-321 P2-T7).
MAX_RUN_FINDINGS = 64


class RunFinding(StrictModel):
    """A graph finding the run's bench session raised while it ran (`runs/capture.py`): its id,
    and what compare matches it on across runs — `rule_id` and the sorted `subjects`, since a
    finding's id is per bench session — with how often and when it showed."""

    finding_id: UUID
    rule_id: Annotated[str, Field(min_length=1, max_length=128)]
    subjects: Annotated[list[UUID], Field(max_length=64), AfterValidator(sorted)]
    severity: Literal["info", "warning", "critical"]
    count: int = Field(ge=1, le=10**9)
    first_seen: AwareDatetime
    last_seen: AwareDatetime


class RunManifest(StrictModel):
    schema_version: Literal[1] = 1
    robot_id: UUID
    started_at: AwareDatetime
    packets: list[TelemetryPacket] = Field(default_factory=list, max_length=MAX_PACKETS)
    sensors: list[SensorReference] = Field(default_factory=list, max_length=10000)
    parts: list[PartEvidence] = Field(default_factory=list, max_length=256)
    snapshots: list[RevisionSnapshot] = Field(default_factory=list, max_length=256)
    # Optional, so every manifest recorded before findings existed still loads.
    findings: list[RunFinding] = Field(default_factory=list, max_length=MAX_RUN_FINDINGS)

    @model_validator(mode="after")
    def unique_parts(self) -> Self:
        if len({part.entity_id for part in self.parts}) != len(self.parts):
            raise ValueError("duplicate part identity")
        if len({part.device_id for part in self.parts}) != len(self.parts):
            raise ValueError("ambiguous part device identity")
        signals: set[tuple[str, str]] = set()
        for packet in self.packets:
            signals.update((packet.device_id, name) for name in packet.values)
            if len(signals) > 4096:
                raise ValueError("at most 4096 distinct device signals per run")
        return self
```
`MAX_BYTES = 8 * 1024 * 1024`, `MAX_PACKETS = 10000` (`:19-20`). `RunSummary` (`:117-128`): `id, robot_id, session_id?, name, origin: Literal["live","recorded","synthetic"], status: Literal["running","completed","truncated","interrupted"], started_at, ended_at?, packet_count, drop_count, artifact_id?`; `RunRead` adds `baseline: bool` (store.py:168-173).

**What a run captures.** `POST /bench/runs` (router.py:78-122): session must be `active`; `snapshot()` (snapshot.py:113-183) takes the robot's `focus_entity_ids` closure (≤256), builds `PartEvidence` for every `part` with an `external_ref` from the runtime hardware config (signals by channel suffix `position`/`current`/`commanded_position`, `stall_current_a` from `attrs.specs`, `position_min/max_<unit>` from limits), a `RevisionSnapshot` per entity (`revision = str(entity.version)`, `data` = attrs keys `specs, code_site, cad_revision, microversion, model_id, units`) and one per hardware-config entry (`kind="hardware_config"`, `revision = str(config_version)`, `data = payload`); refuses a session whose device does not match the robot's accepted identity (`:154-159`). `RunCaptureManager.ingest` (capture.py:457-488) appends every packet of that `session_id` with a byte cost until `MAX_PACKETS`, 4096 distinct signals or the byte budget (8 MiB − 1 KiB − 32 KiB findings reserve) → `truncated`, `drop_count++`. Checkpoint every 2 s (`:443`); `findings_during` (`:364-408`) folds in findings whose `evidence.session_id` is the run's session. Session ended → `interrupted`. Limits: 4 running/project, 64/process (router.py:96).

**Storage.** `GraphEntity(kind="bench_run", domain=PROJECT, origin="system", attrs={summary, checkpoint_id, created_by[, baseline]})` (store.py:146, 311-323); bytes via `create_artifact(media_type="application/vnd.solus.bench-run+json", source_tool="bench.capture")`, `retained=True`; final checkpoint filed into `.solus` DOCUMENTATION/guides as `<name>.bench-run.json` (`:244-255`); previous checkpoint soft-deleted and removed (`:261-284`). Sensor artifacts referenced are marked retained (`:213-229`).

**Routes** (router.py; prefix `/api/v1/projects/{p}/bench/runs`, `require_verified`): `POST ""`, `POST /import` (uploaded manifest, `origin recorded|synthetic`, `portable_manifest` + `validate_references`), `GET ""` (cursor, ≤50), `POST /compare`, `GET /{run_id}`, `POST /{run_id}/stop`, `POST /{run_id}/baseline` (one per robot; the evaluator reads its learned bounds), `GET /{run_id}/findings`, `POST /{run_id}/narrate`.

**Compare logic.** `CompareIn {baseline_id, candidate_id, sim_result_id?}` (`:57-62`). Running runs refused (409). With `sim_result_id`, `_twin_source` reads the project's `sim_result` entity + scenes binding the candidate's parts, and `analysis.twin_run` BUILDS the baseline from the simulation (`:247-282`). `analysis.compare` (analysis.py:299-317) returns:
```
config_changes, source_snapshots_changed (bool), divergences, clamp_attributions,
insufficient, finding_deltas (new|cleared|persisting, matched on rule_id + sorted subjects),
expected_source ("baseline_run" | "sim"), evidence (sim_control, only with a twin)
```
Same-robot only (`ValueError → 422 robot_mismatch`). `findings(run)` (`:93-147`) is the deterministic "Possible stall" card: current ≥ snapshotted `stall_current_a` while position still under a different command; else an `insufficient` reason. `narration.narrate` is one optional metered LLM batch (`_MAX_BATCH = 32`) forbidden from adding numbers/identifiers (`_UNSAFE_PROSE`).

**Playback.** Client-only: `playbackTimes` = sorted distinct ms offsets of packet/sensor timestamps; `playbackFrame` returns rows at exactly that offset — "no interpolation, stale values or synthesized media" (playback.ts:24-46); `RunPlayback` = range slider + table (≤200 rows) + sensor references (≤100) with `SensorPreview`. No server playback, no re-injection into live rings.

**UI compare.** `RunEvidence` "Choose a baseline" select → `compareRuns(projectId, baselineId, candidateId)` WITHOUT `sim_result_id` (RunEvidence.tsx:91-109, 129) although `runsApi.compareRuns` accepts it (`runsApi.ts:205-213`).

**SOL.** `get_run` reads `run_store.summary(record(...))` — "the summary only; the packets … cannot fit the cap" (finding_tools.py:77-86, 144-154). No tool lists runs, loads a manifest, marks a baseline or calls `compare`: absent.

---

### Q29: Observers and findings — observer list, event types, BenchEventRing, graph-finding call path
Status: exists
Where: livebench/src/livebench/anomaly/observers.py (196), livebench/src/livebench/anomaly/session.py (70), packages/api/src/solus_api/livebench/bench_router.py (737), livebench/sessions.py (516), livebench/findings/window_evaluator.py (765), livebench/findings/rules/__init__.py (26), graph/findings.py (582), main.py (691)
Note: The three `anomaly/observers.py` detectors never write a graph finding; only the CUSUM one is instantiated in the API path, and it only feeds the in-memory event ring. Graph findings on the Bench are written by `WindowEvaluator._raise` → `graph.findings.raise_finding` from the live-signal RULES (`SIGNAL_RULES`), with `source="observer"`; the evaluator then back-writes markers carrying `finding_id` into the same ring.

**Observer list and event types (verbatim, observers.py:23-36):**
```python
ObserverKind = Literal["threshold_breach", "change_point", "stream_gap"]


class ObserverEvent(BaseModel):
    """One detected anomaly, with enough context to route into the telemetry/error path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObserverKind
    device_id: str
    signal: str
    at: datetime
    value: float | None = None
    detail: dict[str, Any] = {}
```
| Observer | Fires | detail keys | Wired in API path? |
|---|---|---|---|
| `ThresholdObserver(signal, low, high, smoothing=1)` (`:39-90`) | `threshold_breach` when the median of the last `smoothing` samples leaves `[low, high]`; one event per excursion | `smoothed, low, high, smoothing` | **No** — never constructed outside tests |
| `CusumObserver(signal, baseline_samples=50, slack=0.5, decision=5.0)` (`:93-155`) | `change_point` two-sided CUSUM after learning mean/std from 50 samples; relearns after firing | `direction, baseline_mean, baseline_std, decision` | **Yes** via `SessionObservers` |
| `GapWatchdog(timeout_seconds)` (`:158-196`) | `stream_gap` from `tick(now)` when a streamed (device, signal) is silent past the timeout | `last_seen_seconds, timeout` | **No** in the API (the evaluator's `stream_gap` rule reimplements the semantics, sensor_rules.py:18-24) |

`SessionObservers` (session.py:221-266): one `CusumObserver` per `(device_id, signal)`, `max_signals=128` (≤256), resets on unit change, drops out-of-order by `seq` then timestamp, swallows arithmetic overflow per signal, returns `model_dump(mode="json")` dicts. Created per session by `livebench.local.session_observers` (local.py:567-571) ← `SessionManager(observer_factory=…)` (main.py:494) → `tap` calls `observer.add(packet)[:128]` → `event_sink` (sessions.py:368-374) → `BenchEventRing.append(project_id, ObserverEventIn.model_validate(event))` (main.py:495-497).

**BenchEventRing (verbatim, bench_router.py:110-139):**
```python
class BenchEventRing:
    """Bounded per-project observer-event ring. In-memory, like the LNK-06 buffer:
    live ephemeral values only — durable history is out of scope by decision."""

    def __init__(self, capacity: int = MAX_EVENTS_KEPT) -> None:
        self._events: dict[uuid.UUID, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=capacity)
        )

    def append(
        self, project_id: uuid.UUID, event: ObserverEventIn, *, finding_id: uuid.UUID | None = None
    ) -> None:
        """`finding_id` (SOLUSDEV-321 P2-T3) is attached here, to the ring's own record, by the
        server that raised the finding: `ObserverEventIn` has no such field, so an ingested event
        can never carry one, and `recent` hands out only the ids attached here."""
        record = event.model_dump(mode="json")
        if finding_id is not None:
            record["finding_id"] = str(finding_id)
        self._events[project_id].append(record)

    def recent(self, project_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        ring = self._events.get(project_id)
        if not ring:
            return []
        return list(ring)[-limit:]
```
`MAX_EVENTS_KEPT = 512` (`:64`). Read by `GET /bench/events?limit≤512` (`:206-212`); desktop decodes ≤100 with optional UUID `finding_id` (signalAnomalies.ts:30-53). External producers may POST events of any of the three kinds (`TelemetryBatchIn.events`, `:103-107`).

**Graph finding call path (trace):**
1. `main.py:502-511` builds a `WindowEvaluator(telemetry_buffer, sessionmaker, envelope_cache, SIGNAL_RULES, app.state.bench_events, on_raised=narrator.bound(view), artifacts=…, cpu_budget_ms, cpu_budget_ms_per_part)` per robot session.
2. `SessionManager._start_evaluator` (sessions.py:396-407) → `WindowEvaluator.start(view)` (window_evaluator.py:348-356): a task ticking every `tick_seconds = 1.0`.
3. Each tick reads new samples per part by event time, loads envelopes, evaluates `rules.SIGNAL_RULES` (rules/__init__.py:19-26: `COMMAND_RULES, TRACKING_RULES, BODY_RULES, ELECTRICAL_RULES, SENSOR_RULES, PREDICTION_RULES`) under a CPU budget.
4. `WindowEvaluator._raise` (`:684-705`) builds `FindingSpec(rule_id=hit.rule_id, severity, source="observer", headline, subjects, evidence=_finding_evidence(...), matrix_cell, domain, bucket=str(session_id))` and calls **`await raise_finding(db, project_id, spec)`** (`:704`) — the writer is **`solus_api.graph.findings.raise_finding`** (graph/findings.py:316-395): upsert on `canonical_key = sha1(project|rule_id|sorted subjects|bucket)`, `kind=finding`, attrs `{rule_id, severity, source, status, headline, explanation, detail, evidence, count, first_seen, last_seen, matrix_cell, subjects}`, `count++`/`last_seen` on re-raise, `observed` edges to each subject. Evidence always carries `robot_id` and `session_id` (`_finding_evidence`, `:260-275`).
5. `_write_missing` sets the robot's `attrs.missing_signals` (`:717-728`); `_mark` appends `ObserverEventIn(kind="stream_gap"|"threshold_breach", detail={"rule_id"})` per streamed channel with `finding_id` into the ring at a finding's first raise this session (`:738-755`); `_tell` hands ids to the narrator (`:757-765`).

So: **anomaly observers → ring only; rules via evaluator → `raise_finding`.** Other `raise_finding` producers (checkers via `finding_from_warning`, run compare, SOL, simulation; `FindingSource` findings.py:45) are outside the Bench session path.

---

### Q30: Expected values — anything comparing a live signal against a rating/limit/baseline/sim/previous run
Status: exists (server rules, run analysis, compare); absent (desktop-side thresholds)
Where: packages/api/src/solus_api/livebench/findings/envelopes.py (770), window_evaluator.py (765), rules/rule_base.py (527), command_rules.py (129), tracking_rules.py (486), body_rules.py (255), electrical_rules.py (359), sensor_rules.py (524), prediction_rules.py (290), sim_control.py (35), runs/analysis.py (759), runs/store.py (199), apps/desktop/src/renderer/src/features/bench/signalAnomalies.ts (87), SignalWidget.tsx (301), livebench/scene/part_bindings.py (132), agent/deterministic.py (785), agent/deterministic_facts.py (428)
Note: All comparison is server-side. Live samples are judged by pure rules against an `Envelope` (nominal/warn/limit per quantity) assembled from five sources in priority order; recorded runs are judged against a snapshotted stall rating, a baseline run, or a simulation twin. The desktop draws no limit lines; `signalAnomalies.ts` only decodes and positions markers.

**Envelope (verbatim, envelopes.py:147-173):**
```python
class Bound(BaseModel):
    """The two edges of a band; an edge nobody stated is None."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lo: float | None = None
    hi: float | None = None


class Envelope(BaseModel):
    ...
    part_id: uuid.UUID
    quantity: str
    unit: str | None = None
    nominal: Bound | None = None
    warn: Bound | None = None
    limit: Bound | None = None
    expected_hz: float | None = None
    bounds_source: dict[str, str]
    confidence: float
```
Sources, highest first (`envelopes.py:8-17`, `_CONFIDENCE :85-91`): `config` (PartConfig.limits: `current_a, stall_current_a, temp_c, voltage_min_v, voltage_max_v, torque_nm, position_min, position_max, velocity_max`, `position_min_<unit>/position_max_<unit>`) 1.0 → `definition` (library `PartLimitsSpec`) 1.0 → `scene` (bound joint `lower/upper`) 1.0 → `sim` (`attrs.expected[quantity]`) 0.8 → `learned` (baseline run p1/p99, `MIN_LEARNED_SAMPLES = 20`, plus `expected_hz`) 0.6; `warn` derived as `envelopes.warn_fraction` of the limit. `QUANTITIES = ("current", "temperature", "voltage", "position", "velocity", "torque")` (`:76`). `store.baseline_for` picks the robot's one `baseline` run (store.py:182-200).

| Comparison type | Exists? | Where |
|---|---|---|
| Commanded position past position limit (config/definition/scene) | yes | `command_exceeds_limit` command_rules.py:43-46 |
| Commanded velocity past `velocity_max` | yes | `command_rate_exceeds_limit` command_rules.py:85-88 |
| Current ≥ warn bound while command unmet & position still (stall) | yes | `tracking_error_stall` tracking_rules.py:201-204 |
| Error holds under steady command, current under nominal (slip) | yes | `tracking_error_slip` tracking_rules.py:311-314 |
| Error autocorrelation peak (oscillation) | yes | `tracking_oscillation` tracking_rules.py:387-390 |
| Actuator reports target reached while link sensor still moves | yes | `body_lag` body_rules.py:124-127 |
| Device error flags nonzero | yes | `error_flag` body_rules.py:209-212 |
| Current magnitude over rating for N samples | yes | `current_over_rating` electrical_rules.py:65-68 |
| Current peak correlated with voltage sag across rail peers | yes | `rail_sag_correlated` electrical_rules.py:179-182 |
| `reset_count` step under prior load | yes | `controller_reset_under_load` electrical_rules.py:296-299 |
| Sensor noise correlated with a motor's current | yes | `noise_tracks_motor_activity` sensor_rules.py:125-128 |
| Position bit-identical while command moves | yes | `sensor_frozen` sensor_rules.py:211-214 |
| Position past limit while command inside | yes | `sensor_out_of_range` sensor_rules.py:268-271 |
| Channel rate vs `expected_hz` (baseline) or own prior rate | yes | `rate_drift` sensor_rules.py:377-380 |
| Channel silent past expected periods (wall clock) | yes | `stream_gap` sensor_rules.py:473-476 |
| Temperature trend reaches limit within T | yes | `temp_trend_to_limit` prediction_rules.py:135-138 |
| Time-to-limit forecast | yes | `time_to_limit` prediction_rules.py:221-224 |
| Live vs simulation expected value | yes (envelope `sim` source, 0.8) | envelopes.py:13, `_expected_stated` :311 |
| Live vs baseline run (learned p1/p99, expected_hz) | yes | envelopes.py:14, `_learned_stated` :326; store.baseline_for |
| Recorded run vs snapshotted stall rating | yes | `analysis.findings` analysis.py:93-147 |
| Run vs previous run (config, snapshots, divergence, clamps, finding deltas) | yes | `analysis.compare` :299-317; `_config_changes :166`, `_divergences :191`, `_clamps :226`, `_finding_deltas :276` |
| Run vs simulation twin (residual attribution, sim-control label) | yes | `twin_run :641`, `residual_attribution :354`, `_sim_control :540`; sim_control.py:16-35 |
| Distribution shift (no rating) | yes, ring-only | `CusumObserver` → `change_point` (Q29) |
| Fixed threshold observer on live stream | code exists, **not wired** | `ThresholdObserver` observers.py:39-90 |
| Desktop limit lines / threshold shading on SignalWidget | **absent** | SignalWidget.tsx: only `anomalyMarkers` (`:173-177`) + unit conversion |
| `signalAnomalies.ts` comparison | **absent** (decode + x-position of server markers) | signalAnomalies.ts:30-87 |
| `LiveBenchWidget` comparison | **absent** | LiveBenchWidget.tsx:204-254 |
| SOL first-tier limit fact | partial — reads stated `part_limits`, `definition`, `scene_joint`, `latest` reading (deterministic_facts.py:217-240); whether `_limit`/`_stated_limit` (deterministic.py:233-275) compares reading to limit: not determined (handler bodies not read) | agent/deterministic.py:233, 254 |
| `part_bindings.py` | no comparison; shared helpers `bound_scenes`, `scene_joint_for_part`, `channel_for_quantity`, `finite_number` for envelopes + first tier | part_bindings.py:1-19 |

---

### Q31: "What changed" data — diffing commit, config version, firmware, swapped parts, CAD revision
Status: partial
Where: packages/api/src/solus_api/models.py (2072; `Activity` :1285-1313, `SourceRevision` :1429-1445, `SolusEntry.config_version` :1180), routers/history.py (59), routers/activity.py (63), routers/solus_config.py (216), routers/source_revisions.py (204), services/activity.py (74), livebench/runs/snapshot.py (247), livebench/runs/analysis.py (759), livebench/persist.py (194), hardware/store.py (727), livebench/scene/service.py (305), livebench/scene/cad_refresh.py (562)
Note: Between two RUNS the system can diff per-part evidence, hardware-config snapshots (by `config_version` and payload), graph entity versions and selected attrs, and findings — as booleans/lists over snapshots, not as a code-commit or firmware diff. Between two TIMES there is only the append-only `activities` feed (`GET /projects/{p}/history`) with five project event types; no endpoint diffs two timestamps.

**Activity model (verbatim, models.py:1285-1313, excluding __table_args__):**
```python
class Activity(UuidPkMixin, Base):
    """Team activity feed (§2.2). Append-only; deleted with its team."""

    __tablename__ = "activities"
    ...
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    type: Mapped[str] = mapped_column(String(64), index=True)
    domain: Mapped[str | None] = mapped_column(String(32), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    entity_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    why_ref: Mapped[str | None] = mapped_column(String(128), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
```
Project-activity writers on HEAD (`record_project_activity` callers): `"firmware.flashed"` (agent/tools/flash_history.py), `"finding.resolved"` (graph/findings.py:488-497), `"host.confirmed"` (hardware/host_topology.py), `"config.bumped"` (hardware/store.py), `"topology.confirmed"` (hardware/topology_acceptance.py); team-level `"team.created"` (routers/teams.py). Routes: `GET /api/v1/projects/{p}/history?since&entity&domain&actor&cursor&limit≤200` (history.py:91-122; `entity` = jsonb `@>` on `entity_ids`), `GET /api/v1/teams/{t}/activity?type&domain&actor&project_id` (activity.py:23-63). No bench session start/stop, sync, CAD change or run event writes an activity (session start/stop go to `DataEvent` via `emit_event`, bench_router.py:636, 684).

| Dimension | Can the system diff it? | What exists |
|---|---|---|
| Code commit | **partial / indirect** | `RevisionSnapshot.revision = str(entity.version)` is the GRAPH entity version, not a git SHA (snapshot.py:159-174); `code_site` attr captured. `SourceRevision(base_source_id, materialized_source_id, commit_id, branch)` exists per acquired branch view (models.py:1429-1445; `GET /sources/{s}/revisions`, `GET/PUT/DELETE /sources/{s}/view`, source_revisions.py:67-187) but the run snapshot does not record a commit id. Compare reports only `source_snapshots_changed: bool` (analysis.py:309) |
| Config version | **yes between runs; no history otherwise** | `SolusEntry.config_version` bumped in place (models.py:1180, check :1140-1141); snapshot stores `kind="hardware_config", revision=str(config_version), data=payload` (snapshot.py:175-183); `compare._config_changes` diffs `PartEvidence` by `entity_id` (analysis.py:166-189). `"config.bumped"` activity marks WHEN; prior payload not kept. REPO_STATE_2026-10-17.md:475 "No config history" still holds |
| Firmware | **partial** | `HardwareConfig.firmware` and `PartConfig.firmware` (hardware/config.py:184, 290) ride inside the hardware_config snapshot payload; `"firmware.flashed"` activity rows. Not a `RevisionSnapshot.data` key (keys: `specs, code_site, cad_revision, microversion, model_id, units`, snapshot.py:169-172); no firmware field on `PartEvidence` |
| Swapped parts | **yes, two mechanisms** | reconnect: `persist.recognize_robot` → `RobotRecognition(recognized, changed{ref:(was,now)}, added, missing)` vs persisted `canonical_part` fingerprint modalities (persist.py:525-553); between runs: `_config_changes` (analysis.py:166-189) |
| CAD revision | **partial** | attrs `cad_revision`, `microversion` captured per entity in the run snapshot; `PartEvidence.cad_revision`; scene model `source_digest = sha256([source.version, source.attrs])` + `source_current` (scene/service.py:78-113, 174); `cad_refresh` re-tessellates bound meshes after a source acquisition, `refresh_status current|queued|stale|error` (cad_refresh.py:355, 551). No route lists CAD revisions over time |
| Between two arbitrary times | **absent** | only the `history` feed (`since` filter) |
| Between two runs | **yes (bounded)** | `POST /bench/runs/compare` → `config_changes`, `source_snapshots_changed`, `divergences`, `clamp_attributions`, `finding_deltas`, `insufficient`, `expected_source`, `evidence` (router.py:215-244; analysis.py:299-317) |

---

### Q32: The scene — viewer, MJCF/URDF loading, multi-robot, CAD-change reload, joint mapping, empty state
Status: exists
Where: apps/desktop/package.json (76; `"three": "0.183.2"` :39, `"@types/three": "0.183.1"` :57), scene/SceneViewer.tsx (154), scene/kinematics.ts (149), scene/displayPose.ts (40), scene/useSceneValues.ts (77), scene/types.ts (53), scene/ScenePanel.tsx (464), scene/sceneApi.ts (250), scene/cadApi.ts (124), scene/CadImport.tsx (238), scene/CadBindings.tsx (154), scene/MappingReview.tsx (212), packages/api/src/solus_api/livebench/scene/service.py (305), parser.py (297), schemas.py (63), meshes.py (108), router.py (301), cad_refresh.py (562), cad_import.py (564), part_bindings.py (132), agent/tools/bench_scene.py (148)
Note: Plain three.js (no MuJoCo-wasm, no urdf-loader): the server parses URDF/MJCF into a normalized `KinematicModel` JSON; the client builds `Group`s per link/joint with primitive or STL-vertex meshes. Joints move from the latest telemetry point of a confirmed (joint, part, device, signal, unit, scale, offset) binding. Multi-robot = up to 32 models each tied to one `physical_robot`, placed by a per-user localStorage display pose; no namespace prefixing of joint names.

**Viewer.** `SceneViewer.tsx:1-12` imports `AmbientLight, Box3, DirectionalLight, GridHelper, PerspectiveCamera, Scene, Vector3, WebGLRenderer` from `three` and `OrbitControls` from `three/addons`; Z-up camera, pixel ratio ≤2, `ResizeObserver`, rAF loop reapplying display pose and `applyJoints` every frame, HTML `.bench-joint-chip` labels projected per bound joint (`:64-75, 108-113`), full dispose on unmount (`:118-132`). WebGL failure → "3D rendering is unavailable on this graphics device…" (`:34-38, 146-151`). Compact mode hides the grid and draws skeletons (joint spheres + segments) when joints exist (`:50, 54-57`; kinematics.ts:196-234, 290-303).

**Loading URDF/MJCF.** `ScenePanel` uploads the XML (≤1 MiB) and ≤64 STL files (≤8 MiB total) as artifacts, then `POST /api/v1/projects/{p}/bench/scene/models` (`ImportModel {robot_id, artifact_id, name, format: "urdf"|"mjcf", meshes[{reference, artifact_id}], source_entity_id?, source_revision?}`, schemas.py:320-332; routes router.py:57-83; `PUT /models/{id}` replaces with `expected_version`). `parse_model` (parser.py:224-265): root `robot` (URDF) or `mujoco` (MJCF); MJCF `hinge→revolute`, `slide→prismatic`, intrinsic euler → fixed-axis rpy (`mjcf_rpy :26`); `mimic` / MJCF `ref` refused (`:111`); visuals box/sphere/cylinder/mesh (STL vertices via `MeshCatalog`, sha256 `mesh_key`); |coord| ≤ 1e6; result ≤ 8 MiB. Stored as `GraphEntity(kind="bench_scene_model", domain=SIMULATION, origin="manual", attrs {robot_id, artifact_id, source_entity_id, source_revision, source_digest, model, bindings, config_digest, cad_bindings?})` with `references` edges (service.py:169-232); ≤32 models/project (`:146-147`). Output shape `SceneModel` (types.ts:53-73) incl. `source_current`, `refresh_status`, `cad_bindings`.

**Multi-robot namespacing.** Each model is bound to one `physical_robot` (`attrs.robot_id`); viewer renders all models into one `Scene` with per-model root pose from `poses[model.id]` (`SceneViewer.tsx:54-63, 100-104`), persisted at `localStorage["solus.scene.pose.v1:[user,project,model]"]` (displayPose.ts:6-7, 22-40; ±10000). Joint values keyed `values[model.id][joint.name]` (useSceneValues.ts:60-77), so two models may share joint names; nothing prefixes names or checks inter-robot collisions. Spawn form: "Robot for model" + "Replace model" (ScenePanel.tsx:170-184, 257-272).

**CAD-change reload path.** (1) `CadImport` → `GET /bench/scene/cad-sources` (eligible synced mechanical leaf parts, cad_refresh.py:43-64, 98) → `POST /bench/scene/cad-imports {robot_id, source_entity_id, expected_revision}` (202; `bench_scene_cad_import` entity) → `GET /cad-imports/{id}` polling (router.py:237-301; cadApi.ts:64-98). (2) `CadBindings` → `PUT /models/{id}/cad-bindings {expected_version, bindings[{mesh_key, source_entity_id}]}` (202, router.py:140). (3) After a source acquisition `cad_refresh.prepare(session, source_id)` → `reconcile_source` / `refresh_model` tessellate the bound STEP (`tessellate_isolated`, `MAX_TRIANGLES`) and swap mesh vertices; `complete` / `complete_imports` publish `graph.changed` and set `refresh_status` (`cad_refresh.py:183, 326, 355, 456, 504, 551`). (4) `SceneService.output` recomputes `source_current` = `config_digest` unchanged AND `source_digest == sha256([source.version, source.attrs])`; when false, `bindings` is returned EMPTY (service.py:78-113) and `ScenePanel` shows "Source or hardware mapping changed. Reimport or review the mapping before displaying live movement." (`:296-301`). Panel re-lists every 10 s (`:100`). SOL can drive (1): `bench.list_cad_sources`, `bench.import_cad_scene`, `bench.cad_import_status` (agent/tools/bench_scene.py:83-102).

**Joint mapping from telemetry.** `MappingReview` → `PUT /models/{id}/mapping {expected_version, bindings[≤128]{joint, part_entity_id, device_id, signal, unit: rad|deg|m, scale, offset}}` (schemas.py:335-349). Server (service.py:235-283): joint exists and is not `fixed`, unique joint and unique (part, signal), `device_id == part_ref(config.identity.device_ref, bus_map.address)` (only accepted bus-map parts), `prismatic ⇔ unit == "m"`; stamps `config_digest`. Client `useSceneValues` takes the newest point per binding from the stream (or polls `device-recent` `limit: 1` every 2.5 s for `source_current` models); `jointValue` (kinematics.ts:255-268) requires `point.unit === binding.unit`, age in `[-1 s, 10 s]`, applies `value*scale+offset`, `deg→rad`; `applyJoints` clamps to `[lower, upper]`, sets quaternion (revolute/continuous) or position (prismatic) along `axis` (`:236-254`). Status: `LIVE` when any joint has a value else `NO LIVE MAPPING`; `MAPPING CURRENT` vs `UNMAPPED` (ScenePanel.tsx:374-386).

**No model.** Empty scene (grid hidden in compact), "No models imported yet." (`:162`), `NO LIVE MAPPING` / `UNMAPPED`, caption `NO CAD LINK — IMPORT A MODEL TO SEE ITS GEOMETRY` (`:389-391`); compact spawn form collapsed behind "+ Spawn" (`:52, 157-160`). A model with no moving joints: "No moving joints are declared. This model is displayed as static geometry." (`:302-304`).

---

### Q33: Known Live Bench UI problems still open (from QA/completion files)
Status: partial
Where: docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md (983), docs/qa/COMPLETION_SOLUSDEV-262.md (215), docs/qa/COMPLETION_SOLUSDEV-66-lane-h-livebench.md (115), docs/qa/REPO_STATE_2026-10-17.md (2215); code checked: livebench/src/livebench/local.py (571), runs/RunEvidence.tsx (313), signalAnomalies.ts (87), findings/useRobotFindings.ts (145), graph/telemetry.py (323), BenchScreen.tsx (257)
Note: Grep terms `known issue|not fixed|deferred|still open|open issue|TODO|follow-up|not yet|unresolved|known gap|limitation` over `COMPLETION_SOLUSDEV-262*/260*/250*`, `*321*`, `*bench*`. No `docs/qa/COWORK_QA_livebench*.md` exists on HEAD. Items touching Live Bench, each checked against code:

| # | File:line | Quote (one line) | Addressed on HEAD? |
|---|---|---|---|
| 1 | COMPLETION_SOLUSDEV-321…md:494 (also :831 M134) | "the Live Bench's MuJoCo provider … compiles request-supplied scene XML behind only the substring guard `_reject_file_referencing_mjcf`, which misses `fileup=` and its five cube-texture siblings" | **No.** `local.py:242-252` is still the substring regex `(<include|file\s*=|meshdir|texturedir|assetdir|modelfiledir)`; no `fileup`, no parse-based walk. |
| 2 | COMPLETION_SOLUSDEV-321…md:928 (R117), :839 (M152/M153/M156) | "the Runs-view affordance is deferred (M153)" / "Sim-mode captures as twins and the Runs-view compare affordance are product calls" | **No.** `RunEvidence.tsx:129` calls `compareRuns(projectId, baselineId, candidateId)` with no `sim_result_id`; no UI to pick a simulation. |
| 3 | COMPLETION_SOLUSDEV-321…md:863 | "P2-T7 M8 (`anomalyMarkers` re-validates ids during render) and M7 (`useSelectedFinding` ignores `useWorkspaceFetchEnabled`) are desktop nits for a follow-up" | **No.** `signalAnomalies.ts:85` still calls `findingField(event.finding_id)` inside `anomalyMarkers`; `useWorkspaceFetchEnabled` is used once at `useRobotFindings.ts:68` (in `useRobotFindings`), not in `useSelectedFinding` (`:105`). |
| 4 | COMPLETION_SOLUSDEV-321…md:878 | "FindingsPane 'one stream per pane' pin counts hook calls during one rerender, not mounted subscriptions" | not determined (test-shape only; tests not run). |
| 5 | COMPLETION_SOLUSDEV-321…md:437, :470 | "real-arm current-based stall detection needs Present_Current/Present_Voltage in the vendor plugin and datasheet limits on the vendor definitions" | not determined (vendor plugin files not read). |
| 6 | COMPLETION_SOLUSDEV-321…md:836 (M149) | "resolve on `recorded` is a two-line follow-up if it bites" | not determined (referent not traced). |
| 7 | COMPLETION_SOLUSDEV-262.md:144 | "P3 jointless reason/CAD microversion refresh … Real Onshape edit optional live follow-up" | Code path exists (`cad_refresh.py`); live Onshape edit never exercised — human-owed check, not a code gap. |
| 8 | COMPLETION_SOLUSDEV-262.md:136, :209 | "Live SSH deferred" / "USB swap and live SSH deployment are explicitly deferred by the user" | Human-owed live checks (deployment), not Bench UI code. |
| 9 | COMPLETION_SOLUSDEV-66-lane-h-livebench.md:68 | "LANE A follow-ups (flagged, not edited): make the buffer's…" (unbounded unresolved buffer) | **Yes.** Unresolved ring is capped 16×16×256 (telemetry.py:55-57, 176-196). |
| 10 | REPO_STATE_2026-10-17.md:475 | "**No config history** — payload overwritten in place, `config_version` bumped." | **Still true** (models.py:1180; a `config.bumped` activity row now marks the bump, hardware/store.py, but the prior payload is not retained). |
| 11 | (code observation) BenchScreen.tsx:110-118 | "No camera stream available…" / "No LiDAR or depth stream available…" are hardcoded `<div>`s | The sensor pane is static text; no code path can show a live camera/LiDAR stream. Recorded `SensorReference`s appear only in Runs playback. |
| 12 | (code observation) DeviceBenchView.tsx:188, 499; BenchScreen.tsx:120-128 | `robotCount` prop never passed | Cosmetic: "across N robots" never renders. |

Bench QA flows live in `COWORK_QA_SOLUSDEV-262.md` (:89, :139, :175, :291) and `COWORK_QA_SOLUSDEV-262-ui-phases.md:11`, all unchecked `[ ]`; whether they were ever run: not determined.

---


## E. Simulation Integration


### Q34: Isaac Sim
Status: exists (control path, gated; never live-verified by this repo's automated tests; one human-run report claims a live lifecycle for an EARLIER routine shape)
Where:
- SOL wrappers: `packages/api/src/solus_api/agent/tools/isaac_tools.py` (416), `isaac_models.py` (246)
- Registration/gating: `packages/api/src/solus_api/agent/runtime.py` (1726; lines 551-554, 618-622, 649-675), `agent/execution_policy.py` (227; 34-43, 72), `bridge/allowlist.py` (276; 55-60)
- Status route: `routers/isaac_connection.py` (44), `services/isaac_connection.py` (87); model registration: `routers/simulation_models.py` (56), `services/simulation_models.py` (161)
- Vendored MCP fork (companion-launched): `integrations/mcp/isaac/solus/{server 204, controller 323, worker 93, actions 362, scene 248, runtime 60, models 246, assets 146, urdf 241, artifacts 106}.py`, `allowlist.yaml` (38), `bin/launch` (13)
- Read-only telemetry script (separate path): `livebench/src/livebench/sim/isaac_direct.py` (204)
- Desktop: `apps/desktop/src/renderer/src/features/workspace/IsaacConnectionPanel.tsx` (162)
Note: Eight tools `isaac.{probe,status,start,stop,load_model,set_joint_limits,set_sensor_pose,run_routine}` are the ONLY Isaac surface; they are cloud-owned wrappers (`IsaacTool`) over bridge tools from a companion-launched stdio MCP fork, which itself spawns `<SOLUS_ISAAC_RUNTIME>/python.sh worker.py` headless and talks to it over two private pipes. No network port, no Isaac extension, no ROS bridge, no hardcoded host: the simulator lives on the companion's machine; the cloud reaches it only via the authenticated bridge WebSocket. A separate human-run script (`isaac_direct.py`) POSTs joint states from a user-opened USD stage to the bench ingest route.

**Tool/MCP definitions**: verbatim pastes in "### G4" at the end. Summary (`isaac_tools.py:32-55`, `isaac_models.py:237-246`):

| tool | args (SOL-visible) | confirmation | timeout_s | reads/writes |
|---|---|---|---|---|
| `isaac.probe` | `{}` | no | 20 | READ `{available, platform, architecture, runtime_fingerprint}` (`controller.py:44-70`) |
| `isaac.status` | `{}` | no | 20 | READ `{state: running\|stopped, session_id, scene_generation, graph_digest, model_entity_id, loaded, positions_rad{joint_entity_id→rad}, link_bindings, limits_rad, sensor_poses}` (`actions.py:128-134`, `scene.py:123-147`) |
| `isaac.start` | `{dry_run?}` | yes (complete preview) | 195 | WRITE: spawn one headless `SimulationApp`; no scene loaded (`controller.py:80-151`) |
| `isaac.stop` | `{session_id, dry_run?}` | yes | 25 | WRITE: SIGTERM/SIGKILL the owned process group (`controller.py:271-298`) |
| `isaac.load_model` | `{session_id, model_entity_id, dry_run?}` | yes | 165 | WRITE: URDF import of a graph-registered `simulation_model` into a fresh stage + Solus ground cube + contact sensors (`scene.py:33-121`) |
| `isaac.set_joint_limits` | `{session_id, joint_entity_id, lower, upper, dry_run?}` | yes | 25 | WRITE `Articulation.set_dof_limits` with readback check (`scene.py:156-174`) |
| `isaac.set_sensor_pose` | `{session_id, sensor_entity_id, translation_m[3], orientation_wxyz[4], dry_run?}` | yes | 25 | WRITE `Contact.set_local_poses` with readback check (`scene.py:176-204`) |
| `isaac.run_routine` | `{session_id, routine:"joint_trajectory", duration_s 1-30, joints[{joint_entity_id,lower,upper}]≤16, waypoints[{positions[{joint_entity_id,position_rad}]}]≤16, dry_run?}` | yes | 55 | WRITE: position-target stepping at 60 Hz, ≤35 s wall; returns `{targets_reached, target_errors_rad, steps, waypoints[], positions_rad}` (`scene.py:206-248`) |

**How Solus connects** (code path):
1. Companion `discover_servers(root)` finds `integrations/mcp/isaac/{allowlist.yaml,bin/launch}` (`packages/companion/src/solus_companion/config.py:4-11,438`). `bin/launch` execs `env -i PATH=/usr/bin:/bin … SOLUS_MCP_WORKSPACE=… SOLUS_ISAAC_RUNTIME=… $SOLUS_MCP_PYTHON solus/server.py`; exits 78 if `SOLUS_MCP_PYTHON` or the workspace is unset (`bin/launch:7-11`).
2. `server.py:165-199` runs a stdio MCP server named `solus-isaac`; `Controller` reads only `SOLUS_ISAAC_RUNTIME` (absolute path, `runtime.py:16-24`) and reports `available` iff `platform.system()=="Linux"` and five files exist: `python.sh, setup_python_env.sh, VERSION, kit/python/bin/python3, apps/isaacsim.exp.base.python.kit` (`controller.py:52-59`).
3. `start` spawns `[<runtime>/python.sh, worker.py, <request_fd>, <reply_fd>, <session uuid>, <workspace_fd>, <runtime>, --/app/extensions/registryEnabled=false, --/telemetry/enableNVDF=false, --/telemetry/enableSentry=false, --/telemetry/enableAnonymousData=false]`, `start_new_session=True`, env `{HOME, PATH=/usr/bin:/bin, LANG, TMPDIR}` (`controller.py:167-190`, `runtime.py:27-33`). Transport: two pipes, newline-delimited JSON frames ≤128 KiB, sequence+generation checked both ways (`runtime.py:36-60`, `worker.py:18-55`).
4. Worker: `from isaacsim import SimulationApp; SimulationApp({"headless": True, "disable_viewport_updates": True}, experience=<runtime>/apps/isaacsim.exp.base.python.kit)` (`worker.py:64-69`). Isaac-6-era imports: `isaacsim.asset.importer.urdf.URDFImporter`, `isaacsim.core.experimental.prims.Articulation`, `isaacsim.sensors.experimental.physics.{Contact,ContactSensor}` (`scene.py:36-45`).
5. Cloud side: `runtime.py:553-554` drops every raw `isaac.*` bridge spec from generic registration ("Only the owned graph adapter may expose Isaac operations to SOL"); `_owned_isaac_tools` (649-675) rebuilds `BridgeTool`s for `spec.server == "isaac"` and wraps them via `build_isaac_tools` (`isaac_tools.py:400-416`); a wrapper registers only if its raw tool AND `isaac.status` are advertised.

**What it can read**: runtime fingerprint (probe); session state, scene generation, graph digest, loaded model id, per-joint positions (rad), per-joint limits, link prim paths, contact-sensor local poses (status). No scene-tree listing, no arbitrary prim/USD read, no camera/IMU/other sensors (`Sensor.kind: Literal["contact"]`, `isaac_models.py:52`).

**What it can write**: start/stop its own session; import ONE URDF(+STL) asset closure registered in the graph; set one joint's limits; set one contact-sensor pose; run one bounded joint trajectory. It cannot open a user's stage, spawn arbitrary prims, set physics params, or reset (`actions.py:59-64` lists exactly four actions). URDF is pre-validated against an element allowlist (`urdf.py:12-30`); assets come from the workspace `.solus/isaac/models/<sha256>/` via fd-relative `O_NOFOLLOW` opens (`assets.py:15-40`).

**Gating**: every mutating tool is `requires_confirmation=True`, `files_errors=True`, complete-preview (`isaac_tools.py:258-268`; `bridge/allowlist.py:55-60`); preview = dry-run through the fork (`{ok, dry_run, preview rows, fingerprint}`); invoke needs an unconsumed ticket whose canonical args and snapshot digest match, and re-resolves the graph model (version + SHA-256 of root and bound entities), refusing on change (`isaac_tools.py:367-397`). The model binding is a graph entity with `attrs.simulation_model` (schema_version 2) created by `POST /api/v1/projects/{id}/simulation-models` (`routers/simulation_models.py:19`; `RequireVerified` + `Role.MEMBER`). The six mutating tools are also eligible "owned routines" in Build mode (`execution_policy.py:34-43,72`), i.e. may auto-run without a card there (REPO_STATE_2026-10-17.md:14 flagged this; still true on HEAD). `GET /api/v1/projects/{id}/isaac/connection-status` is read-only, 20/min (`routers/isaac_connection.py:17-44`).

**Run against a live Isaac Sim per the reports** (quotes; none ran in this repo's tests):
- `docs/qa/FINAL_NON_ONSHAPE_SOLUSDEV-261.md:6-8` (2026-09-13): "Isaac's complete product lifecycle and calibrated routine ran successfully as integration operations; its strict physical grasp criterion correctly remained false." `:23`: "Owned headless start/stop, pinned SO-101 loading, six graph-bound joint limits, local sensor pose, explicit finite approach/close/lift routine, actual physics readbacks and saved revisions | Full SOL start → model → calibrated sensor → clearance → approach/close/lift → stop passed. … Bottle routine lifted 37.5209 mm, final bottle force 8.29553 N … Strict targets_reached=false and grasp_observed=false". CAVEAT: that report names an "approach/close/lift" routine and a "pinned SO-101"; HEAD's fork has only `routine: Literal["joint_trajectory"]` (`isaac_models.py:176`) and no pinned model (the generic-model rewrite is `COMPLETION_isaac-cleanup.md`).
- `docs/qa/COMPLETION_isaac-cleanup.md:62-63`: "No live GPU/vendor import, physical motion or full robotics demo acceptance was performed. The native adapter remains Linux/POSIX and vendor-version dependent."
- `docs/qa/COWORK_QA_isaac-development.md:47-49`: "Automated native fixtures cover parsing, confinement, lifecycle and mocked vendor readback. Record live GPU vendor execution separately with runtime/version, two model names and actual outcomes. Automated tests do not establish native readiness."
- `docs/qa/COMPLETION_SOLUSDEV-121-lb01-sim-connectors.md:39-43`: "Isaac itself is NOT INSTALLED on this machine (audited: no pip/Omniverse/container) … this acceptance line is honestly unmet."
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:440`: "Isaac (rung 4) | a declared target only".
- Tests: `integrations/mcp/isaac/tests/conftest.py:6-19` fabricates the 5 runtime files with content "fixture"; `packages/api/tests/test_isaac_tools.py:81` uses a `Native` fake. On HEAD the live claim rests solely on the 2026-09-13 human report, for a prior routine shape. Isaac version/GPU used: not determined (no report states them).

### Q35: Gazebo
Status: partial (telemetry read via `gz topic` CLI only; never live-run per reports)
Where: `livebench/src/livebench/sim/gazebo_source.py` (139), `livebench/src/livebench/sim/connections.py` (81; `GazeboSimConnection` 48-66), `livebench/src/livebench/local.py` (571; probe 121,131-133; `open_gazebo` 290-294), `packages/api/src/solus_api/livebench/bench_router.py` (737; `GazeboSimConfig` 278-288, opener 481-486), `livebench/src/livebench/telemetry/normalize.py` (129), desktop `SimulatorStartModal.tsx` (132; 22,40-45,99-101)
Note: `GazeboTopicSource` resolves `gz` once with `shutil.which`, then runs one pinned subprocess per topic — `gz topic -e -t <topic> --json-output` — turning each JSON line into a `TelemetryPacket` stamped with arrival time (`gazebo_source.py:64-77, 99-126, 41-58`); topics may not start with `-` (`:67-69`, `bench_router.py:256-264`). Callers: `POST /bench/sessions {mode:"sim", config:{provider:"gazebo", topics:[…]}}` → `_session_opener` → `local.open_gazebo` → `GazeboSimConnection` (`bench_router.py:481-486`, `local.py:290-294`, `connections.py:48-66`); desktop "Start Gazebo" modal collects topics (`SimulatorStartModal.tsx:22,40-45`). Availability = `which("gz")` (`local.py:121,131-133`). Absent: connector, MCP server, ROS/`ros_gz` bridge, `gz` transport binding, world listing, launch handling, model spawning, SOL tool, any write path. Repo grep for `gz\b|gazebo` outside these files hits only UI labels, `corpus/hosts.py:234` (allowed doc host), and tests. Report `COMPLETION_SOLUSDEV-121-lb01-sim-connectors.md:37-38`: "Gazebo: ✅ built + fixture-verified; **live `gz sim` smoke NOT RUN** (simulator not installed…)". No later report records a live Gazebo run.

### Q36: MuJoCo
Status: exists (in-process library in the API/worker; headless; offscreen EGL render; Live Bench AND SOL)
Where: `livebench/src/livebench/sim/mujoco_source.py` (100), `connections.py` (81; 21-45), `livebench/local.py` (255-287 `open_mujoco`, 80-90 demo MJCF), `livebench/src/livebench/sim/offscreen.py` (465), `packages/api/src/solus_api/simulation/providers/mujoco_job.py` (667), `agent/tools/simulate.py` (740), `agent/vision/renderers.py` (443; 227-235, 364), `agent/vision/render_view.py` (422), `connectors/worker.py` (1361; 1292, 1324), `livebench/pyproject.toml:11` (`mujoco>=3.11.0`)
Note: MuJoCo is a Python dependency of the `livebench` package, imported in-process by the API host (`mujoco_source.py:18`; optional `find_spec` import `mujoco_job.py:253-264`), never through the companion. Three uses:
1. **Live Bench sim session** (`provider:"mujoco"`): `MuJoCoPacketSource` compiles `MjModel.from_xml_string(xml)`, steps `mj_step`, emits one packet per joint `<scene>/<joint>` `{qpos,qvel}` and per sensor `{value}` at `sample_hz`; realtime forced on, duration required (`mujoco_source.py:25-96`, `local.py:255-287`). Default scene is the hinged-rod `demo` MJCF (`local.py:80-90`); user MJCF accepted after the substring guard `_reject_file_referencing_mjcf` (`local.py:242-251`; cap 2,000,000 bytes `bench_router.py:272`). Headless; no viewer anywhere.
2. **SOL rung-3 job** `run_mujoco_sim` (`RigidBodyTrajectory`, provider `rigid_body_trajectory`): forward dynamics of a `JointTrajectory` with position actuators → `peak_joint_torque_nm`, `peak_joint_force_n`, `peak_joint_current_a`; engine runs ONLY inside the ARQ job and inside a child process of the same interpreter with rlimits and a hard kill (`mujoco_job.py:40-47, 467-515`; `worker.py:1324` `timeout=300, max_tries=1, keep_result=0`). Reached only via the SOL tool `simulate` (`simulate.py:128-132, 429-467`).
3. **Offscreen render** for SOL `render_view`: `offscreen.render_scene_png` runs `engine.Renderer` in a child with `MUJOCO_GL=egl`, 800×600 default, PNG ≤2 MiB, plus a segmentation pass for per-body pixel boxes (`offscreen.py:1-34, 154-200, 413-437`); chosen by `agent/vision/renderers.py:227-235` when the entity has a scene model (`_offscreen()` optional import `:364`). Real-EGL evidence: `COMPLETION_SOLUSDEV-321…md:326` "24 passed (offscreen, real EGL)"; `:349` "`MUJOCO_GL=egl`: face question → 1 offscreen render (800×600, 0.919 s)".
Desktop: no `mujoco_wasm`/`mujoco-wasm` on HEAD (repo-wide grep hits only `docs/qa/REPO_STATE_2026-10-17.md:846,1163`, which already recorded "no mujoco-wasm … on main").

### Q37: Using the user's own scenes
Status: partial (mostly absent)

| step | exists? | where |
|---|---|---|
| List scenes/worlds in the user's simulator | absent | No Isaac tool lists stages (`actions.py:59-64`); Gazebo has no world API; the MuJoCo session takes XML text, not a file list (`bench_router.py:272`). `GET /bench/sources` lists simulator *availability* only (`bench_router.py:425-450`). |
| Open an existing scene | partial, human-run only | `isaac_direct.py:148,165-166`: `--scene /path.usd` → `omni.usd.get_context().open_stage(...)` under Isaac's own python, launched by a human with `SOLUS_TOKEN`; not reachable from SOL or the UI. Isaac MCP `load_model` always builds a fresh stage from Solus's own URDF import (`scene.py:49-63`). MCAP replay opens a *recording* (`local.py:297-303`), not a live scene. |
| Find the robot in a scene | partial | `isaac_direct.py:96-119` traverses `UsdPhysics.ArticulationRootAPI` prims and streams every articulation; Isaac MCP requires exactly one articulation after its own import (`scene.py:103-109`). Gazebo/MuJoCo: absent (names come from the user's XML/topics). |
| Insert the robot | partial | Only Isaac `load_model`: URDF+STL closure registered in the graph (`SimulationModel.asset`, `isaac_models.py:76-101`), imported with `URDFImporter(fix_base=True, …)` onto a Solus ground cube (`scene.py:49-98`). No spawn into a user world; no Gazebo/MuJoCo insert. |
| Map simulated signals to the same part nodes as real ones | partial | Same resolver as real: packet `device_id == graph_entity.external_ref` (`graph/resolver.py:80-92`, `graph/telemetry.py:150`). Sim device ids are `<scene>/<joint>` (`mujoco_source.py:76`, `isaac_direct.py:21,132`) or a `gz` topic (`gazebo_source.py:54`); real robot sessions key per part `<device>/<address>`. Nothing on HEAD writes a part's `external_ref` to a sim joint name, so a sim packet resolves only if some entity already carries that `external_ref`; otherwise `unresolved` (`sessions.py:375-376`). The scene-model `Binding {joint, part_entity_id, device_id, signal, unit, scale, offset}` (`scene/schemas.py:30-38`; `PUT /models/{id}/mapping`, `router.py:105`) is a user-confirmed display mapping, not an ingest resolver. |

### Q38: Model generation (CAD → URDF/MJCF)
Status: partial (CAD → static scene model + "twin" facts; no URDF/MJCF file generation)

| capability | status | file |
|---|---|---|
| Parse user-supplied URDF | exists | `livebench/scene/parser.py:156-176` (`link`, `joint` fixed/revolute/continuous/prismatic, limits required, no `mimic`) |
| Parse user-supplied MJCF | exists (strict subset) | `parser.py:179-221` (requires `compiler angle="radian" coordinate="local" eulerseq="xyz"`, one joint per body, no freejoint, explicit `range`) |
| Import a model via API | exists | `POST /api/v1/projects/{id}/bench/scene/models` `ImportModel{robot_id, artifact_id, name, format: urdf\|mjcf, meshes[]}` (`scene/schemas.py:15-23`, `router.py:66`) |
| CAD → scene model (static) | exists | `livebench/scene/cad_import.py` (`propose` 173, `materialize` 448): placed leaves from CAD transforms (`rigid_matrix` 38, mm→m) + STEP tessellation (`:454`); result has `joints: []` and `STATIC_REASON = "CAD contains no verified motion-joint definitions; this model is static."` (`:35`) |
| Mates as joints | partial — candidates only | `cad_import.py:336-387`: `mates_with` edges whose `mate_type` is in `MOVING_MATES` become `model.candidate_joints[{name, type, parent, child, axis: UNKNOWN, origin: UNKNOWN, actuated, actuator, limits}]`; "the mate frame is not in the graph" (`:282-283`), so rung-1 FK names `mate_frame` as a missing input (`deterministic_robot.py:24-27`) |
| Mass properties | partial | Twin: `masses: {}` + `MASS` missing input (`cad_import.py:295-301`). Rung-1 `mesh_mass` computes `mass_kg`/COM from a closed mesh + `material.density_kg_m3` (`deterministic_mech.py:8-14`). Onshape SOL tool `onshape.get_mass_properties` calls `/massproperties` (`connectors/onshape_ops.py:551-559, 693-697`) but nothing feeds it into the scene model/twin. |
| Sensor sites | partial | `cad_import.py:416-445`: `mounts` edges from a placed leaf with `attrs.position_m` → `sensor_sites[{device_entity_id, link, xyz}]`, else `xyz: UNKNOWN`; `mounts` edges written by `graph/inference/mates.py:43-55` |
| Definition limits | partial | `cad_import.py:398-413`: part-library `limits.position_min/max`, `unit: None`, never a joint's `lower/upper` |
| URDF/MJCF *generation* from CAD (onshape-to-robot or equivalent) | absent | repo grep for `onshape-to-robot\|onshape_to_robot` hits only `docs/qa/REPO_STATE_2026-10-17.md`. No `dof_` convention in code (only `articulation.dof_names` at `isaac_direct.py:125`). |
| CAD change → re-tessellate | exists | `scene/cad_refresh.py` (`prepare` 183, `refresh_model` 355, `complete` 456); UI reimport remains manual (`PUT /models/{id}/cad-bindings` 202, `router.py:140`) |

### Q39: Sim telemetry through the same pipeline
Status: exists (same `PacketStreamLiveConnection` → `SessionManager` tap → `TelemetryPlumbing.ingest` → `EntityResolver` by `external_ref`; keying to the same part nodes NOT guaranteed — see Q37)
Where: `livebench/src/livebench/telemetry/stream_live.py` (143; 1-6, 36-60), `packages/api/src/solus_api/livebench/sessions.py` (516; 307, 358-382), `graph/telemetry.py` (323; 140-157), `graph/resolver.py` (99; 80-92), `bench_router.py` (247-380, 464-493)
Note: Every sim source (MuJoCo, Gazebo, MCAP) and the serial source are `PacketSource`s under `PacketStreamLiveConnection` (`stream_live.py:4-6`). `SessionManager` attaches one `tap` per session regardless of mode (`sessions.py:307,358-382`) which calls `self._plumbing.ingest(project_id, packet, session_id)`; ingest resolves `packet.device_id` to a `GraphEntity` by `external_ref` within the project (`graph/telemetry.py:150`, `resolver.py:86-92`) and rings unresolved devices. Robot ("real") sessions additionally track resolved part channels and run the window evaluator (`sessions.py:379-399`); sim sessions have `robot_entity_id=None`, so no evaluator. `_SIM_PROVIDERS = {"mujoco", "gazebo", "mcap-replay"}` (`bench_router.py:253`); Isaac is listed by `/sources` but never startable (`local.py:134-143`: `available=False`, reason "Isaac Sim detected — stream live via the Isaac direct script, or replay an MCAP recording").

Sim provider config models, verbatim (`packages/api/src/solus_api/livebench/bench_router.py:247-303`):
```python
MAX_MJCF_BYTES = 2_000_000
MAX_TOPICS = 32
MAX_TOPIC_LEN = 256
MAX_SESSION_SECONDS = 3600.0
MAX_WINDOW_SECONDS = 60.0
_RUNNER_ABSENT = "livebench is not installed on this server"
_SIM_PROVIDERS = {"mujoco", "gazebo", "mcap-replay"}


def _clean_topics(topics: list[str]) -> list[str]:
    for topic in topics:
        if not 1 <= len(topic) <= MAX_TOPIC_LEN:
            raise ValueError("topic length out of range")
        if topic.startswith("-"):
            raise ValueError(f"topic may not look like a CLI flag: {topic[:32]!r}")
        if not topic.isprintable():
            raise ValueError("topic contains non-printable characters")
    return topics


class MujocoSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mujoco"]
    scene_name: str = Field(default="demo", min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    mjcf_xml: str | None = Field(default=None, min_length=1, max_length=MAX_MJCF_BYTES)
    sample_hz: float = Field(default=50.0, gt=0, le=200)
    duration_seconds: float = Field(default=300.0, gt=0, le=MAX_SESSION_SECONDS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class GazeboSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gazebo"]
    topics: list[str] = Field(min_length=1, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str]) -> list[str]:
        return _clean_topics(topics)


class McapSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mcap-replay"]
    mcap_path: str = Field(min_length=1, max_length=4096)
    topics: list[str] | None = Field(default=None, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str] | None) -> list[str] | None:
        return None if topics is None else _clean_topics(topics)
```
Session envelope (`bench_router.py:360-380`):
```python
class BenchSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["sim", "real"]
    config: Annotated[
        MujocoSimConfig
        | GazeboSimConfig
        | McapSimConfig
        | SerialRealConfig
        | RobotRealConfig
        | HardwareRealConfig
        | ReplayRealConfig,
        Field(discriminator="provider"),
    ]

    @model_validator(mode="after")
    def _mode_matches_provider(self) -> "BenchSessionIn":
        is_sim = self.config.provider in _SIM_PROVIDERS
        if is_sim != (self.mode == "sim"):
            raise ValueError(f"provider {self.config.provider!r} does not run in {self.mode} mode")
        return self
```
Sim connection classes (`livebench/src/livebench/sim/connections.py:21-81`): `MuJoCoSimConnection(xml, *, scene_name, start_time, sample_hz=50.0, duration_seconds=None, realtime=False, project_id=None)` provider `"mujoco"`; `GazeboSimConnection(topics=None, *, source=None, project_id=None)` provider `"gazebo"`; `McapReplaySimConnection(path, *, topics=None, project_id=None)` provider `"mcap-replay"`.

### Q40: Mechanical and electrical simulation
Status: exists (closed forms in process; ngspice and MuJoCo as worker jobs; no FEA/CalculiX/LTspice/KiCad-native sim)
Where: `packages/api/src/solus_api/simulation/providers/{deterministic_elec 148, deterministic_mech 281, deterministic_robot 436, mesh_interference 601, ngspice_provider 605, spice_deck 469, mujoco_job 667}.py`, `simulation/sim_ladder.py` (466; `LOCAL_PROVIDERS` 380-387), `simulation/mesh_job.py` (51), `agent/tools/simulate.py` (740), `agent/tools/apply_sim_change.py` (792), `agent/tools/rail_current.py` (71), `hardware/definitions/spice/generic.lib` (11), `core/config.py:292` (`ngspice_bin: Path | None = None`), `connectors/worker.py:1323-1325`

All calculators are reached by SOL through ONE tool, `simulate {question:{subject_id, quantity}, scope?, provider?, change?}` (`simulate.py:229-250`, `requires_confirmation=False`), plus `get_sim_result {sim_result_id}` and the always-gated `apply_sim_change` (`simulate.py:704-740`). Provider roster printed from code (`ladder_providers(shipped_simulation())`):

| calculator (provider name) | rung / domain | quantities | file | SOL tool | ever run against a real external binary? |
|---|---|---|---|---|---|
| `deterministic_elec` (power_sum, divider, rc_settling, cable_drop) | 1 / electrical | `cable_drop_v, divider_out_v, power_w, rc_settling_s` | `deterministic_elec.py:114-148` | `simulate` (in process, recorded) | n/a — pure Python |
| `deterministic_mech` (cantilever_bending, mesh_mass) | 1 / mechanical | `stress_mpa, yield_fraction, mass_kg, com_x_m, com_y_m, com_z_m` | `deterministic_mech.py:247-281` | `simulate` | n/a — numpy |
| `deterministic_robot` (forward_kinematics, joint_sweep) | 1 / mechanical | `tip_x_m, tip_y_m, tip_z_m, reach_m, sweep_span_m` | `deterministic_robot.py:390-436` | `simulate` | n/a — numpy |
| `mesh_interference` (+ reused cantilever_bending) | 3 / mechanical | `interference_mm, stress_mpa, yield_fraction` | `mesh_interference.py:590-601`; job `mesh_job.py:49` | `simulate` → ARQ `run_mesh_sim` | n/a — numpy; worker run recorded in `COMPLETION_SOLUSDEV-321…md:347` ("the mesh check ran in the worker … status recorded") |
| `spice_transient` (`NgspiceProvider`) | 3 / electrical | `peak_current_a, final_current_a, min_node_voltage_v` | `ngspice_provider.py:497-556`; grammar `spice_deck.py`; models `generic.lib` (5 lines: `d_generic, npn_generic, pnp_generic, nmos_generic, pmos_generic`) | `simulate` → ARQ `run_ngspice_sim` (`:600-605`) | **No.** Binary pinned by `settings.ngspice_bin` (`SOLUS_NGSPICE_BIN`), never PATH (`:280-291`); tests use a fake Python script as the simulator (`tests/test_ngspice_provider.py:106-121`); `which ngspice` here → absent; `NgspiceProvider(None).available` → `False`; `COMPLETION_SOLUSDEV-321…md:442`: "`ngspice` on the worker \| not installed; the provider reports 'not available on this machine'". |
| `rigid_body_trajectory` (`RigidBodyTrajectory`) | 3 / mechanical | `peak_joint_torque_nm, peak_joint_force_n, peak_joint_current_a` | `mujoco_job.py:605-667` | `simulate` → ARQ `run_mujoco_sim` | Yes, against the real `mujoco` module (a library, not an external binary): `tests/test_mujoco_job.py:84-85` `skipif(not engine_installed())`; `RigidBodyTrajectory().available` → `True` here; `COMPLETION…321:443`: "MuJoCo rung-3 job against a real robot scene \| the fake arm has no MJCF scene model" (engine test only). |
| `analyze_rail_current` | — | declared current sum per net | `agent/tools/rail_current.py:21-36` → `checkers/rail_current.py` | `analyze_rail_current` | n/a — graph arithmetic |
| FEA / CalculiX / LTspice / KiCad's own simulator | absent | — | no `calculix`/`ccx`/`ltspice` runner in code (REPO_STATE…:830 said "ngspice / CalculiX absent"; on HEAD ngspice exists as a pinned-binary provider, CalculiX still absent) | — | — |

KiCad side: fork tool `kicad.export_spice_netlist` produces the `spice_netlist` fact the ngspice provider reads (`COMPLETION…321:84`; `ngspice_provider.py:7-8`); no simulation runs inside KiCad.

### Q41: Simulation capability / provider abstraction
Status: exists (the connector `Capability` enum has NO simulation member; simulation is its own `SimProvider` protocol + ladder; `sim_result` kind + `verified_by` edges written by one writer)
Where: `packages/api/src/solus_api/connectors/contracts.py` (271; 37-52), `simulation/sim_capability.py` (154), `simulation/sim_ladder.py` (466), `simulation/sim_facts.py` (274), `simulation/providers/external_providers.py` (101), `orchestration/config.py` (567; 386-442), `orchestration/models.yaml` (564; 548-564), `graph/kinds.py` (92; 51-57, 78-86), `packages/contracts/python/solus_contracts/relations.py` (273; 52, 90), `packages/shared-types/src/relations.ts` (195; 39, 76)

**Connector `Capability` enum — no simulation member** (`connectors/contracts.py:37-52`, verbatim):
```python
class Capability(enum.StrEnum):
    """What a connector can do today (SOLUSDEV-320). Shared code asks the registry
    `providers_of(capability)`; it never names a provider."""

    CHANGE_SIGNAL = "change_signal"
    WEBHOOK = "webhook"
    STRUCTURE = "structure"
    GEOMETRY = "geometry"
    CONSTRUCTION_HISTORY = "construction_history"
    NETLIST = "netlist"
    RENDER = "render"
    WRITE_FEATURE = "write_feature"
    WRITE_PARAMETER = "write_parameter"
    WRITE_SYMBOL = "write_symbol"
    WRITE_NET = "write_net"
    WRITE_FILE = "write_file"
```
Simulation uses a separate protocol `SimProvider` (`sim_capability.py:136-154`): `name, domain, rung, quantities, can_answer(SimQuestion) -> MissingInputs, run(inputs) -> SimResult`; `SimResult{values: dict[SimName, SimValue{value, unit}], provenance: SimProvenance{solver, inputs: {name: SimInput{value, source: known|derived|assumed}}, leaves_out}}` (`:55-95`), ≤64 KiB JSON.

**The ladder** (`sim_ladder.py`; proposes only, never runs). Rungs (`orchestration/config.py:390-392`): `SimRung = Annotated[int, Field(ge=1, le=4, strict=True)]` — "1 closed-form code, 2 an external target, 3 local headless jobs, 4 an external full simulation". Decision logic, verbatim from `sim_ladder.py:9-39`:
```
**When.**
- `rule` and `real_world_action` read an `inconclusive` result that is inside its band. Its
  evidence must state a `quantity`, a `value` and a `limit`, and may state a `comparator`, the
  `rung` the value came from and a `unit`.
- `expected_value` reads an `unknown_input` whose missing fact is a quantity some provider
  computes.
- `user` reads both.

Any other result proposes nothing: empty beats invented.

**Cheap first.** A question's candidates are the providers that compute its quantity at a rung
above the one its value came from. They are ranked in where-order (below): when no style entry
prefers one and availability does not separate them, the cheapest goes first, which by default
is the lowest rung. A value with margin proposes nothing, so the ladder stops where it is.

**Whether.** The chosen provider's `can_answer` decides, for the asked quantity:
- nothing missing → run;
- only what it can derive → derive;
- an input nobody was asked for yet → ask for it, once (`asked` names what was asked);
- the asked quantity it still covers without the rest → run, with the rest stated in
  `leaves_out`. Covering only other quantities is not covering the question;
- otherwise → `missing_input`, which `missing_input_finding` words as the finding the caller
  raises.

**Where.** Candidates are ordered by:
1. a `constraints/style` entry `simulate <quantity> with <target>` (`*` for any quantity; the
   newest wins);
2. connected and configured (`available`, which the caller computes);
3. cost;
4. fidelity;
5. name.
```
Roster and config (`sim_ladder.py:380-387`; `models.yaml:555-564`):
```python
LOCAL_PROVIDERS: Final = (
    DeterministicMech(),
    DeterministicElec(),
    DeterministicRobot(),
    MeshInterference(),
    NgspiceProvider(None),
    RigidBodyTrajectory(),
)
```
```yaml
simulation:
  escalate_at: 0.8 # the spec's "within 20 % of a limit"
  bands: {}
  targets:
    - name: isaac # the full-simulation integration; P4-T4 routes it through its gated routine tool
      rung: 4
      domain: mechanical
      quantities: [joint_trajectory]
      cost: 4
      fidelity: 4
```
Ladder providers printed from code: `deterministic_mech(1) deterministic_elec(1) deterministic_robot(1) mesh_interference(3) spice_transient(3) rigid_body_trajectory(3) isaac(4: joint_trajectory)`. Rung-2/4 targets are never run by Solus: `ExternalTarget.run` raises `SimulationRefusedError`; `simulate` only names `<target>.run_routine` (`isaac.run_routine`) as the next gated tool (`external_providers.py:32, 56-58, 83-101`; `simulate.py:340-347`); "connected" iff that gated tool is in the turn's registry (`external_providers.py:69-81`). Rung-3 availability requires `settings.redis_url and not settings.sync_inline` (`sim_ladder.py:423-426`).

**`sim_result` entity and `verified_by` edges**: `graph/kinds.py:55-57`: `SIMULATION_MODEL = "simulation_model"`, `SIM_RESULT: Final[str] = "sim_result"` (also in `DESCRIPTOR_KINDS`, `:78-86`). `relations.py:52` `VERIFIED_BY = "verified_by"`; doc `:90` `"verified_by": "goal or claim → run or sim result"`; TS mirror `relations.ts:39,76`. ONE writer, `sim_facts.record_sim_result` (`sim_facts.py:79-117, 137-184`): creates `GraphEntity(kind="sim_result", domain=Domain.SIMULATION, origin="system", attrs={subject_id, rung, values, provenance, created_by})`, writes `verified_by` subject→result via `write_edge` with `EdgeEvidence(kind=EvidenceKind.SIM, ref=<result id>, detail=<solver>)`, confidence 1.0, and reassigns `subject.attrs.expected[quantity] = {value, unit, sim_result_id}`. Callers: `simulate._run` (rung 1, `simulate.py:359-367`), `run_and_record` for the three rung-3 jobs (`sim_facts.py:232-274`), `apply_sim_change` re-run. Readers: `get_sim_result` (`simulate.py:584-600`), envelopes (`bounds_source="sim"`), `POST /bench/runs/compare {sim_result_id?}` twin (`livebench/runs/analysis.py`; `COMPLETION…321:156`).

### Q42: Platform and simulator detection
Status: partial

| path | OS/arch it can run on (from code) | evidence |
|---|---|---|
| Isaac MCP fork | Linux only, with an installed Isaac runtime dir; probe hard-requires `platform.system() == "Linux"` + the 5 runtime files; POSIX APIs (`os.pipe`, `select`, `killpg`, `/proc/self/fd`) | `controller.py:59, 160-190, 303`; `worker.py:77`. No GPU check in code (the runtime itself is NVIDIA-only). |
| `isaac_direct.py` | wherever Isaac's `python.sh` runs (Linux; `omni.usd`, `isaacsim.core.*`) | `isaac_direct.py:3-4, 106-111, 159` |
| Gazebo source | any OS with `gz` on PATH (`shutil.which`), asyncio subprocess | `gazebo_source.py:70-75`; `local.py:121` |
| MuJoCo session / rung-3 job / offscreen | wherever the `mujoco` wheel imports (`mujoco>=3.11.0`); rung-3 child uses `limit_child` (`resource` rlimits → POSIX only); offscreen forces `MUJOCO_GL=egl` (Linux EGL) | `livebench/pyproject.toml:11`; `mujoco_job.py:253-264`; `offscreen.py:19, 183`; `ngspice_provider.py:47` (`import resource` at module import, so importing `sim_ladder`/`simulate` fails on Windows — whether any Windows API host exists: not determined) |
| ngspice provider | POSIX; binary pinned by `SOLUS_NGSPICE_BIN` (absolute path) | `ngspice_provider.py:22-33, 280-291`; `core/config.py:292,390` |
| MCAP replay | any (pure-Python `mcap`) | `mcap_replay.py`; `livebench/pyproject.toml:8` |

**Detection of installed simulators** — two places, neither is `machine.attrs.tool_versions`:
1. API-host probe `available_simulators()` (`livebench/local.py:113-144`): `find_spec("mujoco")`, `which("gz")`, `Path.home()/"isaacsim"`.is_dir() (`DEFAULT_ISAAC_ROOT`, `:75`); Isaac is always `available=False`. Surfaced by `GET /bench/sources` (`bench_router.py:425-450`) and desktop `SimulationPanel.tsx:55-60` ("No in-app start — use a script or an MCAP recording.").
2. Isaac-specific: `isaac.probe` via the companion fork (`controller.py:44-70`) and `GET …/isaac/connection-status` → `IsaacConnectionStatus{bridge, installation, owned_session, streaming: "none", reason}` (`services/isaac_connection.py:15-29`).

Companion `machine.tool_versions` detected tool list, verbatim (`packages/companion/src/solus_companion/config.py:96-109`) — contains NO simulator:
```python
#: SOLUSDEV-320: the fixed developer tools `machine.tool_versions` asks `--version` of.
#: Resolved with `shutil.which` at call time; an absent one is omitted, never invented.
DEFAULT_VERSION_BINARIES: tuple[str, ...] = (
    "python3",
    "node",
    "git",
    "kicad-cli",
    "arduino-cli",
    "ros2",
    "docker",
    "uv",
    "pip",
    "conda",
)
```
(`machine/server.py:250-266` runs `<exe> --version` per binary with a 2 s timeout and keeps one redacted line.) So the graph's `machine` node cannot state whether `gz`, `mujoco`, `isaacsim` or `ngspice` is installed on the user's machine.


## F. Cross-cutting

Read-only recon of HEAD `33e3bc08` (== origin/main, 2026-10-31). Every sweep below that says "ran statically" was executed with `uv run python` importing the test module's own functions (no pytest).

### Q43: Machine node `tool_versions`
Status: exists
Where:
- `packages/companion/src/solus_companion/config.py` (614 lines) — probe list `DEFAULT_VERSION_BINARIES` at 96–109; `CompanionConfig.version_binaries` at 231–232 (no env override: the only way to change the list is code)
- `packages/companion/src/solus_companion/machine/server.py` (274 lines) — `_tool_versions` handler 250–266; `absolute_path_which` 43–52; `redact_version_line` 55–59; `VERSION_PROBE_TIMEOUT = 2.0`, `VERSION_LINE_CAP = 200` at 32–33; `_WORKSPACE_FREE = {"tool_versions"}` at 35
- `packages/companion/tests/test_machine_tool_versions.py` (176 lines)
- `integrations/mcp/machine/allowlist.yaml` (36 lines) — `tool_versions` entry at 32–36 (`requires_confirmation: false`, flagged "for human ratification")
- `packages/api/src/solus_api/routers/machines.py` (192 lines) — server-side copy `TOOL_VERSION_BINARIES` 44–46, `_versions_of` 58–67, PUT dispatch 94–130
- `packages/api/src/solus_api/services/machines.py` (169 lines) — `upsert_machine` stores `attrs.tool_versions` 111–133 (REPLACES the dict when the companion answered; keeps the prior when it did not)
- `packages/api/src/solus_api/graph/kinds.py` (92 lines) — `MACHINE = "machine"` at 72
- SOL readers: `packages/api/src/solus_api/agent/tools/machine_tools.py` (237 lines), `packages/api/src/solus_api/agent/project_card.py` (470 lines), `packages/api/src/solus_api/agent/guide_toolkb_version.py` (96 lines), `packages/api/src/solus_api/services/environment_divergence.py` (235 lines)
Note: The companion's built-in `machine` server runs `<abs-path> --version` (argv only, 2 s per binary, first line, path-redacted) for a fixed list of ten binaries; absent binaries are omitted. The API's `PUT /projects/{id}/members/me/machines/{companion_id}` dispatches `machine.tool_versions` over the live bridge, drops any key not in its own copy of the list, redacts again, and stores the dict in the `machine` entity's `attrs.tool_versions`.

Probed tools, verbatim (`config.py:98-109`):
```
DEFAULT_VERSION_BINARIES: tuple[str, ...] = (
    "python3",
    "node",
    "git",
    "kicad-cli",
    "arduino-cli",
    "ros2",
    "docker",
    "uv",
    "pip",
    "conda",
)
```
Server-side mirror (`routers/machines.py:44-46`):
```
TOOL_VERSION_BINARIES: Final = frozenset(
    {"python3", "node", "git", "kicad-cli", "arduino-cli", "ros2", "docker", "uv", "pip", "conda"}
)
```

| Detected on the machine node? | Tool | Evidence |
| --- | --- | --- |
| yes | `ros2` | in both lists above |
| no | `colcon` | not in either list; the word appears only in the code fork's command policy (`integrations/mcp/code/solus/command_plan.py:245,290`, `sandbox.py:46`) — a run-policy, not a probe |
| no | Isaac Sim | not in the list; `grep -rniE "isaac|gazebo|gz|mujoco|colcon" packages/companion/src/` → only an unrelated comment at `supervisor.py:219` |
| no | Gazebo / `gz` | not in the list |
| no | MuJoCo | not in the list |

Simulators ARE probed, but elsewhere and never stored on the machine node: `livebench/src/livebench/local.py:112-146` `available_simulators()` checks `find_spec("mujoco")`, `shutil.which("gz")` and `Path.home()/"isaacsim"`.is_dir() (Isaac is `available=False` always — "never a startable session provider (ADR-014: read its data)"). Its only consumer is `GET /bench/sources` (`packages/api/src/solus_api/livebench/bench_router.py:425-449`), which returns a per-request `simulators` list plus an `mcap-replay` row gated on `settings.bench_data_root`. `services/machines.py` has no simulator attr (`grep -n simulator` → none).

How SOL reads `attrs.tool_versions`:

| Reader | Tool / surface | File:lines | What it does |
| --- | --- | --- | --- |
| `get_machine` | SOL read tool (registered `machine_tools.py:180-199`) | `machine_tools.py:60-96` | one row `{"tool_versions": {...}}` capped at 12 entries (`_TOOLS = 12`) + "+N more"; recent commands only for the owner |
| `get_environment_divergences` | SOL read tool (`machine_tools.py:201-209`) | `environment_divergence.py:111-121, 158-160` | per machine, compares the project's `EnvironmentSpec.tools` against `attrs.tool_versions` → `missing` / `version_drift` items (stored table, never recomputed by the tool) |
| project card machine block | every SOL turn's context (owner only) | `project_card.py:263-268` (`tool_versions()`), `270-291` (`machine_block`) | sorted, capped `_MAX_TOOL_VERSIONS`, names/values capped to `_NAME_CAP` |
| Guide tool-version answers | `guide_toolkb_version.py:36-54` | `MACHINE_TOOLS = {ToolFamily.KICAD: ("kicad-cli", "KiCad")}`; `machine_release()` extracts digits from the `kicad-cli` line | the ONLY binary whose version reaches the knowledge-base lookup today (`# ponytail: KiCad is the one the companion reports today`) |

### Q44: Vendor and capability hygiene ratchets
Status: exists
Where:
- `packages/api/tests/test_capability_hygiene.py` (162 lines)
- `packages/api/tests/test_vendor_hygiene_api.py` (116 lines)
- `livebench/tests/lb_vendor_hygiene_test.py` (77 lines)
- `apps/desktop/src/renderer/src/features/graph/hardware/vendorHygiene.test.ts` (42 lines)
- `packages/api/tests/test_edge_writer_ratchet.py` (50 lines), `packages/api/tests/test_token_estimator_ratchet.py` (70 lines) — ratchets, not vendor-related
- `integrations/mcp/tests/test_vendor_hygiene.py` (239 lines) — "vendor" here means vendored third-party trees (launcher pinning, ruff/mypy/pytest exclusion), not product names
- smaller per-task twins: `livebench/tests/lb_feetech_codec_test.py:249-259`, `livebench/tests/lb_usb_can_test.py:144-156`, `livebench/tests/lb_passive_test.py:108-114`, `packages/api/tests/test_hardware_config.py:66`
- Hooks/CI: `grep -rnE "ratchet|hygiene|vendor" .claude/hooks/ infrastructure/ci/ .gitlab-ci.yml scripts/` → no ratchet lives in a hook or CI script; the ratchets are ordinary pytest/vitest files collected by the normal suites.
Note: Four textual sweeps (word-boundary, case-insensitive) forbid product/vendor names in shared code. Three of them have NO allowlist mechanism at all; the capability ratchet honours a `# capability-hygiene: allow <reason>` trailing comment, and exactly one such line exists in the tree. All four sweeps pass statically on HEAD (0 offenders).

| Ratchet | Trees swept | Words | Allowlist mechanism | Current exceptions on HEAD |
| --- | --- | --- | --- | --- |
| capability (`test_capability_hygiene.py:30-56`) | `solus_api/{graph,checkers,impact,livebench/findings,simulation,agent/vision,software}/**` + 17 files (`agent/context.py, layers.py, project_card.py, reason.py, solus_layer.py, turn_scope.py, deterministic.py, deterministic_facts.py, finding_narration.py, reasoning_frame.py, citations.py, services/outcomes.py, services/change_signals.py, agent/tools/{read_tool,search_tools,finding_tools,machine_tools}.py`) — 106 files | `onshape kicad altium fusion solidworks github gitlab isaac gazebo mujoco foxglove ngspice` | `# capability-hygiene: allow <reason>` (reason mandatory; bare `allow` still fails) | **1 line**: `simulation/providers/mujoco_job.py:106` |
| API vendor (`test_vendor_hygiene_api.py:15-30`) | `solus_api/hardware/*.py, livebench/*.py, livebench/findings/*.py, livebench/findings/rules/*.py, checkers/*.py, checkers/cells/*.py, simulation/*.py, simulation/providers/*.py, software/*.py` (not `hardware/definitions/`) — 91 files; plus 7 fixed "connection paths" (`CONNECTION_PATHS`, lines 83–91: `services/isaac_connection.py, routers/isaac_connection.py, integrations/mcp/isaac/solus/{controller,server}.py, apps/desktop/.../resources.isaacConnection.ts, IsaacConnectionPanel.tsx, ConnectedAccountsCard.tsx`) | `feetech dynamixel lerobot sts3215 sts3250 scs0009 so-?10[01] px4 pixhawk odrive myactuator mavlink unitree ur5e? arduino teensy esp32 ch343 cp210x ft232 pl2303 xl330 xm430 robotis` | **none** ("NO allowlist: every hit is reported") | 0 |
| livebench vendor (`lb_vendor_hygiene_test.py:22-30`) | `livebench/{hardware,recognition,telemetry}/**` + `local.py` (33 files); second test: everything under `livebench/src/livebench` except `plugins/` and `definitions/` | same regex as API vendor | **none**; only `plugins/` and `definitions/` may name a product | 0 (and `PLUGIN_MODULES` = lb06, jsonlines, raw, feetech, dynamixel, odrive, mavlink, lerobot, arduino) |
| desktop vendor (`vendorHygiene.test.ts:12-14`) | `renderer/src/features/graph/hardware/*.ts(x)` + `renderer/src/widgets/livebench/recognition/*.ts(x)` (non-test) | API vendor regex + `ttyUSB ttyACM` + `\.ino\b` | **none** | not determined statically (vitest not run by this agent; no allow mechanism exists, so any hit would fail CI — the full desktop vitest run in Q2 passed this file) |
| edge writer (`test_edge_writer_ratchet.py:9`) | all `solus_api/**/*.py` except `tests/`, `migrations/` | `GraphEdge(` / `insert(GraphEdge` | `ALLOWED = {"graph/edges.py", "connectors/runtime.py"}` | those two files |
| token estimator (`test_token_estimator_ratchet.py:16-20`) | `solus_api/{agent,orchestration}/**` except `orchestration/type_estimator.py` | `/ 4`, `_CHARS_PER_TOKEN`, `chars_per_token` | `orchestration/config.py` may NAME the knob | that one file |

Allowlist constants, verbatim:

`test_capability_hygiene.py:56`:
```
ALLOW: Final = re.compile(r"#\s*capability-hygiene:\s*allow\s+\S.*$")
```
The one allowed line on HEAD (printed by the sweep, `simulation/providers/mujoco_job.py:106`):
```
ENGINE: Final = "mujoco"  # capability-hygiene: allow the engine's import and XML root
```
`test_edge_writer_ratchet.py:9`:
```
ALLOWED = {"graph/edges.py", "connectors/runtime.py"}
```
`integrations/mcp/tests/test_vendor_hygiene.py:50` (launcher exemption — empty by design):
```
PROVISIONAL_PATH_RESOLVED: frozenset[str] = frozenset()
```
Static sweep output on HEAD (functions imported from the test modules, no pytest):
```
swept files: 106
OFFENDERS: []
ALLOWED:
simulation/providers/mujoco_job.py:106: [mujoco] ENGINE: Final = "mujoco"  # capability-hygiene: allow the engine's import and XML root
vendor swept files: 91
VENDOR OFFENDERS: []
CONNECTION OFFENDERS: []
livebench shared files swept: 33
SHARED HITS: []
OUTSIDE HITS: []
```
Where vendor names are permitted: `solus_api/hardware/definitions/` (seed), `livebench/src/livebench/{plugins,definitions}/`. Not covered by any product-name ratchet: `livebench/src/livebench/sim/` (e.g. `isaac_direct.py` names Isaac freely), `solus_api/routers/`, `solus_api/services/` (except the two isaac connection files), the companion package, and all of `apps/desktop` outside the two swept directories.

### Q45: Feature flags and env toggles affecting hardware, bench, sim
Status: exists
Where: `packages/api/src/solus_api/core/config.py` (453 lines; `env_prefix="SOLUS_"`, `.env` at repo root, line 40–42); `env.example` (212 lines); `livebench/src/livebench/local.py` (571); `livebench/src/livebench/sim/isaac_direct.py` (204); `livebench/src/livebench/sim/offscreen.py` (465); `livebench/src/livebench/plugins/lerobot/lerobot_parser.py` (342); `packages/companion/src/solus_companion/config.py` (614); `apps/desktop/src/main/companion.ts` (503); `apps/desktop/src/main/companionEnv.ts` (158); `apps/desktop/src/renderer/src/env.d.ts` (14); `packages/api/src/solus_api/orchestration/models.yaml` (564)
Note: There is no feature-flag framework; every toggle is a pydantic-settings field (`SOLUS_*`), an install-presence check (`find_spec`), or a plain `os.environ` read. The renderer has exactly three `VITE_*` variables (`env.d.ts`), none hardware-related. `env.example` documents none of the bench/sim knobs (`grep -nE "BENCH|NGSPICE|ISAAC|MUJOCO|COMPANION" env.example` → nothing; only `SOLUS_REDIS_URL`:55, `SOLUS_SYNC_INLINE`:157, `SOLUS_FINGERPRINT_VISION_ENABLED`:187).

| Name | Where read (file:line) | Default | Effect |
| --- | --- | --- | --- |
| `SOLUS_BENCH_DATA_ROOT` (`bench_data_root`) | `core/config.py:282`; `livebench/bench_router.py:436,454` | `None` | Unset ⇒ `mcap-replay` source reported unavailable and MCAP sessions refused 503 (`_validated_mcap_path`); set ⇒ the only dir `.mcap` files may be read from |
| `SOLUS_BENCH_REPLAY_ROOT` (`bench_replay_root`) | `core/config.py:286`; `livebench/replay_provider.py:109-115` | `None` | Unset ("every deployed environment") ⇒ the DEV-ONLY `replay` bench provider refuses 503; set ⇒ confined recording root |
| `SOLUS_NGSPICE_BIN` (`ngspice_bin`) | `core/config.py:292`; `simulation/providers/ngspice_provider.py:22,281,605` | `None` | Unset/not a regular executable ⇒ rung-3 SPICE job reports "not available on this machine"; never looked up on PATH |
| `SOLUS_REDIS_URL` + `SOLUS_SYNC_INLINE` (`jobs_queued`) | `core/config.py:49,251`; `simulation/sim_ladder.py:423-426` | `None` / `False` | Rung-3 sim providers (mesh, MuJoCo, ngspice) are "available" only when `redis_url` set AND `sync_inline` false; otherwise only rung-1 in-process providers run |
| livebench installed (`load_local`) | `livebench/sessions.py:78-82`; `main.py:482` (`app.state.bench_local`) | present if `find_spec("livebench")` | Absent ⇒ `bench_local is None`, `GET /bench/sources` returns `_unavailable_sources()`, no local sessions; also gates `mujoco_job.available` (`mujoco_job.py:614-615`) |
| `mujoco` importable (`engine_installed`) | `simulation/providers/mujoco_job.py:253-256,614,635`; `livebench/local.py:120` | install presence | Absent ⇒ `NOT_AVAILABLE = "the physics engine is not available on this machine"` (`mujoco_job.py:107`); `/bench/sources` `mujoco.available=false` |
| `gz` on PATH | `livebench/local.py:121,130-132` | `shutil.which("gz")` | `/bench/sources` `gazebo.available`; `open_gazebo` raises `GazeboNotAvailableError` when absent (`local.py:290-291`) |
| Isaac root dir (`DEFAULT_ISAAC_ROOT`) | `livebench/local.py:75` (`Path.home()/"isaacsim"`), `:117,122,134-143` | `~/isaacsim`; per-call parameter, no env | Only changes the `reason` string; `isaac.available` is hard-coded `False` ("never a startable session provider") |
| `SOLUS_TOKEN` | `livebench/sim/isaac_direct.py:153-156` | unset | Isaac direct streaming script (run inside Isaac's python, not the API) refuses to start without it (exit 2) |
| `MUJOCO_GL=egl` | `livebench/sim/offscreen.py:183` | always set by Solus for the child | Not a toggle: the offscreen render subprocess is spawned with a scrubbed env {`HOME`, `LC_ALL=C`, `MUJOCO_GL=egl`, `OPENBLAS_NUM_THREADS=1`} |
| `HF_LEROBOT_CALIBRATION` | `livebench/plugins/lerobot/lerobot_parser.py:222` | `~/.cache/huggingface/lerobot/calibration` | Where the lerobot plugin looks for calibration files |
| `models.yaml simulation.targets` | `orchestration/models.yaml:555-564`; `simulation/providers/external_providers.py:63-81` | one target `isaac` (rung 4, mechanical, `joint_trajectory`) | A target is "connected" only when the turn's registry holds `<target>.run_routine` behind confirmation; nothing runs in process |
| `models.yaml observer.cpu_budget_ms` / `cpu_budget_ms_per_part` | `orchestration/models.yaml:544-546`; `main.py:477` | 20 / 10 ms | Live-signal window evaluator CPU budget per bench session |
| `SOLUS_FINGERPRINT_VISION_ENABLED` | `core/config.py:266`; `env.example:187` | `False` | FP-03 vision extraction over photo artifacts (fingerprint, not bench — listed because it is the only `*_ENABLED` boolean in settings) |
| `bridge_*` (13 fields) | `core/config.py:293-330` | e.g. `bridge_tool_timeout_seconds=30.0`, `bridge_tool_call_max_bytes=262_144`, `bridge_max_team_sessions=10` | Companion bridge caps; `bridge_tool_call_max_bytes` is the cap passed to the machine PUT's probe (`routers/machines.py:105`) |
| `bridge_allowlist_root` | `core/config.py:278` | `<repo>/integrations/mcp` | Where `allowlist.yaml` files (incl. `machine/`) are loaded from |
| `SOLUS_COMPANION_DEV_CMD` | `apps/desktop/src/main/companion.ts:48-51` | unset | Dev builds only: unset ⇒ companion disabled for the run (`null`); packaged builds always use `<resources>/companion/solus-companion` |
| `SOLUS_COMPANION_URL`, `_TOKEN`, `_ALLOWED_HOSTS`, `_INTEGRATIONS_ROOT`, `_INSTANCE_FILE`, `_WORKSPACE` | `packages/companion/src/solus_companion/config.py:567-605`; desktop fills defaults in `companionEnv.ts:128-142` | URL/TOKEN/INTEGRATIONS_ROOT required (companion exits otherwise); `ALLOWED_HOSTS` defaults `("localhost","127.0.0.1")` (`config.py:95`); `WORKSPACE` optional | No workspace ⇒ only `tool_versions` is advertised, every other machine tool fails closed (`machine/server.py:1-6,35`) |
| `SOLUS_MCP_WORKSPACE`, `SOLUS_MCP_PYTHON` | companion `config.py`/`supervisor.py` (grep count 7 / 1) | derived from `SOLUS_COMPANION_WORKSPACE` | Passed to vendored fork children |
| `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_DEV_PORT` | `env.d.ts:4-9`; `companion.ts:253`; `electron.vite.config.ts:84` | API base defaults to localhost:8000; Supabase absent ⇒ dev auth bypass | None hardware-specific; listed to show the renderer has no hw/bench/sim flag |

Not found (absent): any `SOLUS_*` setting named `*hardware*`, `*telemetry*`, `*flash*`, `*deploy*`, `*isaac*`, `*mujoco*`, `*gazebo*`, `*sim_*` in `core/config.py` (grep at lines 1–453 returned none); any `os.environ`/`getenv` read in `packages/api/src/solus_api/` relating to bench/sim/hardware (grep → none outside `core/config.py`); any `import.meta.env.VITE_*` in `apps/desktop/src/renderer/src/widgets/livebench/**`.

### Q46: Unverified / fixture-only / not-on-real-hardware items in completion reports
Status: exists
Where: `docs/qa/*.md` and `docs/qa/acceptance/*.md`; grep pattern `unverified|UNVERIFIED|not verified|fixture-only|fixture only|not run on real|never run|no hardware|not exercised|untested on` over the reports for SOLUSDEV-66/72/73/111/121/122/123/126/248/250/252/260/262/320/321 and the livebench/isaac/sim/bench/arduino files. Only hardware-, bench-, sim-, flash- or companion-relevant hits are kept below; UI/billing/Onshape-only hits were dropped.
Note: Zero hits in `COMPLETION_isaac-cleanup.md`, `COWORK_QA_isaac-cleanup.md`, `COWORK_QA_isaac-development.md`, `COMPLETION_SOLUSDEV-121-lb01-sim-connectors.md`, `COMPLETION_SOLUSDEV-123-lb03-deployment.md`, `COWORK_QA_SOLUSDEV-111-telemetry-plumbing.md`, `COWORK_QA_telemetry-packet.md`, `COMPLETION_SOLUSDEV-72-shared-models.md` — absence of the phrase, not proof of verification. There is no SOLUSDEV-73 report under `docs/qa/`.

- `docs/qa/COMPLETION_SOLUSDEV-66-lane-h-livebench.md:14` — "LB-02 robot + observers | 122 | Built; verified on real pty serial + real WS server. Physical-robot gate reported unverified (no robot)."
- `docs/qa/COMPLETION_SOLUSDEV-122-lb02-robot-observers.md:4` — "real WebSocket links; the physical-robot gate is honestly unverified (no robot on the bench)."
- `docs/qa/COMPLETION_SOLUSDEV-126-lb06-packet.md:139` — "test used UTC, so the property was unverified. Documented on `to_wire`, plus two tests"
- `docs/qa/COMPLETION_SOLUSDEV-72-local-connections.md:61-68` — "## Not verified here (human-assisted, flagged in COWORK_QA) — The two-identical-arms replug test: only ONE arm was physically connected this session. … Isaac direct script against a real articulated scene (§8), and a real `.mcap` replay (none exists on this machine yet). — A real serial LB-06 stream from the arm (the CH343 fronts an MCU that isn't emitting yet)."
- `docs/qa/COMPLETION_SOLUSDEV-248-robot-onboarding.md:121` — "(`lb_connection_test` covers the identity re-resolution; the physical gap was not exercised.)" [unplug/replug an arm for ~5 s]
- `docs/qa/COMPLETION_SOLUSDEV-248-robot-onboarding.md:23` — "6 · proofs | (a) `lb_three_machines_test.py`: PX4-over-UDP, ODrive-over-CAN, Arduino line rover through one shared module set; (b) vendor-hygiene ratchets … | —" (the "On hardware" column is empty: fixture-only)
- `docs/qa/COWORK_QA_SOLUSDEV-248.md:179` — "## Flow J — Generalisation proofs **(fixture only, in CI)**"
- `docs/qa/COWORK_QA_SOLUSDEV-250.md:190` — "Live: both adapters visible, follower six-servo evidence; physical insertion latency unverified."
- `docs/qa/COWORK_QA_SOLUSDEV-250.md:193` — "Unverified: leader not answering; no false second robot created."
- `docs/qa/COWORK_QA_SOLUSDEV-250.md:212` — "Device stream behavior covered by watcher/feed regressions; physical hot-plug network capture unverified."
- `docs/qa/COWORK_QA_SOLUSDEV-250.md:213` — "Live async lifecycle proven; expired-cache confirm took over 2 seconds, so cached sub-500-ms gate remains unverified."
- `docs/qa/COMPLETION_SOLUSDEV-252.md:416` — "**Unverified anywhere**: the native key hook's actual event delivery (no machine here can load it), the"
- `docs/qa/COMPLETION_SOLUSDEV-260.md:4` — "remain unverified as listed below; this is not a claim that every physical demo gate passed."
- `docs/qa/COMPLETION_SOLUSDEV-260.md:49` — "Follower serial 5B42134331 answered as six STS3215 servos; … No motion commanded. Arduino sketch/serial inference covered by the 523-pass Live Bench suite. Complete new SOL wiring turn/hotkey remains unverified because provider retries failed."
- `docs/qa/COMPLETION_SOLUSDEV-260.md:50` — "**Unverified prerequisite.** Leader serial 5B42135040 visible but servos do not answer. Power/cabling question pending; user mapping is tentative. Physical port swap/unplug/reconnect not performed."
- `docs/qa/COMPLETION_SOLUSDEV-260.md:54` — "**Fixtures / live unverified.** One I3 environment implementation and one destructive dispatch path. Companion uses the authorized ForgeTS workspace; `sim` absent and install not completed."
- `docs/qa/COMPLETION_SOLUSDEV-260.md:58` — "Native private calibration relink unverified because no calibration file was supplied."
- `docs/qa/PHASE0_SOLUSDEV-260.md:102` — "are synthetic; sessions are disabled and no hardware motion occurs."
- `docs/qa/PHASE0B_SOLUSDEV-260.md:54` — "historical robots/documents and physical hardware retention remain unverified."
- `docs/qa/PHASE4_SOLUSDEV-260.md:35` — "No hardware was opened and no synthetic graph data persisted."
- `docs/qa/PHASE5_SOLUSDEV-260.md:121` — "Still unverified: leader protocol/telemetry (5B42135040 visible but no servo answers;"
- `docs/qa/COMPLETION_SOLUSDEV-262.md:143` — "P3 two scenes/live joints/independent poses | Two synthetic UI models; independent persisted poses | None | URDF/MJCF/STL/mapping/pose tests | Actual arm geometry and confirmed live mappings unverified"
- `docs/qa/COMPLETION_SOLUSDEV-262.md:153` — "P5 external shortcut/overlay | Both native shortcuts pass | Screenshot crops | Native handoff/fallback tests | Real external-control pointing unverified"
- `docs/qa/COMPLETION_SOLUSDEV-262.md:208` — "pointing remain unverified live. Fixture checks do not establish those physical/UI results."
- `docs/qa/COMPLETION_SOLUSDEV-262-ui-phases.md:98` — "appearance gate remains unverified; numeric fixtures do not satisfy it."
- `docs/qa/COWORK_QA_SOLUSDEV-262-demo.md:19` — "The user reports both follower-finger sensors wired; actual ADC response remains unverified."
- `docs/qa/STATUS_SOLUSDEV-262-demo.md:148` — "response remains unverified. No firmware has been flashed."
- `docs/qa/PHASE0_SOLUSDEV-262.md:6` — "remain read-only. No hardware was flashed or commanded to move."
- `docs/qa/COWORK_QA_code-arduino-development.md:55` — "## Preparation and compile gates — not verified"
- `docs/qa/COWORK_QA_code-arduino-development.md:73` — "## Device and cross-feature gates — not verified"
- `docs/qa/COMPLETION_SOLUSDEV-320-graph-workspace.md:3049` — "The companion dispatch half of the machine PUT (`machine.tool_versions` + `code.probe_environment` over a real bridge, the `environment/software` CONFIG bound to the machine, non-empty divergence causes): the desktop MAIN reporter only runs inside a signed-in Electron session, which this walk could not drive"
- `docs/qa/COMPLETION_SOLUSDEV-320-graph-workspace.md:3050` — "The extraction propose/confirm HTTP path for acceptance 2 (needs the companion's local hardware sources); covered by `test_topology_acceptance.py`, …"
- `docs/qa/COMPLETION_SOLUSDEV-320-graph-workspace.md:3051` — "`overlay_edges` (`drives`, `hosts`, `robot.attrs.host_machine_id`) through a live host confirm; the bench `409 host_mismatch` with a bound robot; … `joint_limits` (no scene import), … `firmware.flashed` (no board, no flash)."
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:437` — "Live arm (Feetech bus) | no arm on this host; the fake arm is a replay recording | P2 replay through `POST /bench/sessions`; the vendor follow-up (Present_Current / Present_Voltage) is in needs-you"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:439` — "A real ROS 2 machine beyond this host's `/opt/ros/jazzy` system profile | only the system profile exists here; the live listing is empty"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:440` — "Isaac (rung 4) | a declared target only | `models.yaml simulation.targets`; `simulate` names the gated tool to call next"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:441` — "`kicad-cli` SPICE and PDF export | this host has KiCad only as a Flatpak whose adapter's fixed argv cannot export"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:442` — "`ngspice` on the worker | not installed; the provider reports \"not available on this machine\" | `ngspice_provider.py` job tests; `SOLUS_NGSPICE_BIN` is the knob"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:443` — "MuJoCo rung-3 job against a real robot scene | the fake arm has no MJCF scene model (M165: `POST /bench/scene/models` refuses the primitive MJCF the renderer accepts) | `test_mujoco_job.py` engine test; P5 renders on a seeded scene row"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:445` — "P3 item 1 on the companion-scan form | local proposal rows carry `source:<uuid>` refs and sketch entities are per directory (M104, pre-existing)"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:447` — "Real rule cost under load (observer budget) | this box only: p95 60.1 ms at 10 ms/part × 6 (M95)"
- `docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md:492` — "(P4-T3) A real KiCad SPICE export is unverified: this host has KiCad only as a Flatpak whose adapter's fixed argv cannot export SPICE"
- `docs/qa/COWORK_QA_sol-depth.md:484` — "9.6 | Rung 3 against real binaries | ngspice and `kicad-cli` absent → \"not available on this machine\"; the MuJoCo trajectory job never ran live (the fake arm's seeded scene model exists only for walkthroughs 11–12). NOT VERIFIED live."
- `docs/qa/COWORK_QA_sol-depth.md:501` — "The import's own enqueue and tessellation after approval are NOT VERIFIED (never ran in the acceptance)"
- `docs/qa/COWORK_QA_sol-depth.md:673` — "W4 Live Bench findings pane: stall, narration, markers, the six actions | replay root, fake arm; key for narration; pane NOT VERIFIED (Electron)"
- `docs/qa/COWORK_QA_sol-depth.md:682` — "W13 ROS workspace vs plain repo; live confirmation; policy contract | companion; ROS 2 Jazzy at `/opt/ros/jazzy`"
- `docs/qa/COWORK_QA_sol-depth.md:683` — "W14 Firmware recipe card | companion, provider key; card NOT VERIFIED (Electron) | NOT RECORDED in Part A (P6 live: PASS)"
- `docs/qa/acceptance/P2-acceptance-live.md:512` — "How often a real-time run folds `time_to_limit` into the stall. The \"about half\" figure is arithmetic on the band and the tick period, not a measurement over several runs."
- `docs/qa/acceptance/P3-acceptance-live.md:25` — "**The companion-scan form (a local-folder sync of `bus_sketch_goal.ino`) is UNVERIFIED (M104).**"
- `docs/qa/acceptance/P3-acceptance-live.md:761-763` — "**`proximity_pair` judging from positions (2b).** The divider fixture carries no board, so no positions."
- `docs/qa/acceptance/P4-acceptance-live.md:62-66` — "**5. Rung-3 jobs against real binaries: NOT VERIFIED here, as the dispatch foresaw.** No ngspice and no `kicad-cli` on this host (`SOLUS_NGSPICE_BIN` unset → \"not available on this machine\"). MuJoCo imports, but the fake arm has no MJCF scene model … so `run_mujoco_sim` had no fake-arm model to take and was not run live."
- `docs/qa/acceptance/P4-acceptance-live.md:88` — "**`apply_sim_change`: not exercised live, as dispatched** (it needs a SOL turn's card)"
- `docs/qa/acceptance/P4-acceptance-live.md:722-724` — "**The decide route and the real scene enqueue**: … the CAD import's queued sync and tessellation did not run."
- `docs/qa/acceptance/P4-acceptance-live.md:725-726` — "**A Sim-mode bench capture as a twin, and the Runs view's compare affordance**: deferred (M152, M153); the twin here is built from a `sim_result`"
- `docs/qa/acceptance/P5-acceptance-live.md:821-822` — "**A scene that the import route accepts**, rendered (observation 1). Mesh scenes are refused by design."
- `docs/qa/acceptance/P6-acceptance-live.md:1110-1112` — "**A running ROS node's name raising an edge.** No node was started, and none ran on this host's domain. The raise was proven through the fork's runner seam"
- `docs/qa/acceptance/P6-acceptance-live.md:1115-1117` — "**A companion over a real WebSocket.** The frames were the companion's own encoder and the cloud's own `parse_frame` + `ingest_result`, in process."
- `docs/qa/acceptance/P6-acceptance-live.md:1118-1119` — "**The local folder's policy path.** The companion ships no policy or controller files yet"
- `docs/qa/acceptance/P7-acceptance-live.md:777` — "**The KiCad fork's real inventory** and a real `kicad-cli --version` (deviations 2 and 3)."
- `docs/qa/acceptance/P8-acceptance-live.md:813-814` — "**The code fork's own planner and sandboxed exec, a real Onshape call, a real Brave call, an offscreen render**: scripted at the seams in deviation 3."
- `docs/qa/acceptance/FINAL-acceptance-live.md:11` — "**Part B (step 4): NOT VERIFIED** — no go-ahead and no provider key recorded in `needs-you.md`; not run."

Cross-cutting pattern from the list: no report records a live run of the MuJoCo rung-3 trajectory job, the ngspice job, Isaac rung 4, a real `.mcap` replay (SOLUSDEV-72), a real board flash (`firmware.flashed`), or the two-arm hot-swap; the leader arm (serial 5B42135040) never answered in any recorded session (260 ×2); the companion→`machine.tool_versions`→divergence path over a real bridge is unverified (320:3049).


### Q47: Hardcoded flows

Scope: every place on HEAD 33e3bc08 where onboarding / bench / sim / companion behaviour is a FIXED SEQUENCE in UI or backend code rather than a tool SOL can call. "SOL-callable" is judged against `build_sol_registry` (`packages/api/src/solus_api/agent/runtime.py:111`) and the tools it registers: `bench.list_cad_sources` / `bench.import_cad_scene` / `bench.cad_import_status` (tools/bench_scene.py:83–102), `hardware.flash_presence` (tools/firmware_presence.py:45), `hardware.deploy_companion` (tools/companion_deployment.py:51), `simulate` / `get_sim_result` (tools/simulate.py:125–126), `apply_sim_change` (tools/apply_sim_change.py:97), `get_finding` / `get_run` / `get_envelope` (tools/finding_tools.py:131–160), `get_machine` / `get_environment_divergences` / `get_history` (tools/machine_tools.py:172–215), `firmware_recipe` (agent/firmware_recipe.py:112), `machine.write_file` (tools/machine_writes.py:69), `isaac.*` (tools/isaac_tools.py:42–60, 261), `solus.list_integrations` / `solus.connect_integration` / `solus.verify_integration` (agent/connect_integration.py:51–76), the bridge `code.*` tools incl. `code.arduino_upload` (tools/flash_history.py:23) and `code.ros2_nodes` / `code.ros2_topics` (tools/ros_live.py:30–33), plus `query_graph` / `get_telemetry` / `retrieve_errors` / `run_checkers` (tools/builtin.py:68–184).

Paths are relative to `/home/beeboss/Solus/`. `api/` = `packages/api/src/solus_api/`, `lb/` = `livebench/src/livebench/`, `ui/` = `apps/desktop/src/renderer/src/`, `comp/` = `packages/companion/src/solus_companion/`.

| Area | File | Function/component | Fixed sequence (what it hard-wires) | Already SOL-callable? |
|---|---|---|---|---|
| onboarding | api/hardware/hardware_router.py | `propose_detected` L645 | read repo evidence → `propose_via_local` → re-read evidence, 409 on digest change → `PROPOSALS.put` → `exclude_bound` → `reconcile_device` suggestions → `hardware.proposal_built` event | no |
| onboarding | api/hardware/hardware_router.py | `confirm_detected` L687 | take cached proposal (or re-propose at 0.5 s) → re-detect device present → `exclude_bound` → connection-only identity check → `confirm_proposal` → optional `_start_robot_session` → graph publish → event | no |
| onboarding | api/hardware/hardware_router.py | `_start_robot_session` L797 | `resolve_runtime_config` → `read_entity_config` → `prepare_local_hardware` → `open_local_hardware` → `SessionManager.start` (window evaluator attached as the member) | no |
| onboarding | api/hardware/hardware_router.py | `_decide` L886 / `_bind_accepted_device` L937 | `decide_suggestion` → (device) re-propose 0.5 s → `bind_device` → `_start_robot_session`; (part) `is_cad_suggestion` → `accept_cad_suggestion` → publish | no |
| onboarding | api/hardware/hardware_router.py | `author_part` L509, `create_hardware_entity` L117, `promote_lifecycle` L545 | fixed REST create/attach/promote; lifecycle ladder `LifecycleState` planned→ordered→received→installed→live (api/hardware/config.py:121) | no |
| onboarding | api/hardware/hardware_router.py | `propose_part_suggestions` L855 → api/hardware/cad_suggestions.py `propose_cad_suggestions` L183 / `accept_cad_suggestion` L217 | lock → `_association` from existing identity links → dedupe against open rows → `persist_suggestions`; accept: re-verify association + evidence equality (409) → `attach_existing_parts` | no |
| onboarding | api/hardware/detect.py | `propose_via_local` L253 | `to_thread(local.propose_device)` under 30 s `PROPOSE_TIMEOUT_S` → `ProposalOut` validate | no |
| onboarding | api/hardware/detect.py | `confirm_proposal` L774 / `_confirm_connection` L699 | validate accepted rows → `_already_confirmed` → chosen repo config → new robot or lock+existing → per row `attach_part` (external_ref=row id, telemetry `<name>.position`, lifecycle LIVE) → layers detected/repo/user → `merge_layers` → `put_config` | no |
| onboarding | api/hardware/detect.py | `bind_device` L567 | `ensure_config` → 409 if bound elsewhere → write identity/protocol/bus_map provenance DETECTED → `_mark_live` → `put_config` → rewrite part `external_ref` | no |
| onboarding | api/hardware/detect.py → api/hardware/links.py | `reconcile_device` L522 → `suggest_links` L195 / `_score` L178 | fixed rule cascade `_rule_identity` → `_rule_slot` → `_rule_bus_map` → `_rule_firmware` → `_rule_shape` → tier by score → `persist_suggestions` | no |
| onboarding | lb/local.py | `propose_device` L501 | `enumerate_devices` → `interrogate_device` → (`parse_repo_sources` or `scan_repo`) → `match_configs` → `propose`; blocking, off-loop | no (HTTP route only) |
| onboarding | lb/hardware/detection.py | `enumerate_devices` L126 / `interrogate_device` L172 / `propose` L322 | enumerate without opening ports → try candidate params in order, first interrogator answer wins → bus_map + repo matches → disambiguation when >1 config → headline/tone | no |
| onboarding | api/hardware/topology_proposals.py | `TopologyProposalService.propose` L248 | snapshot → `_read` source → `parse_source` by `source_kind` → re-read (409 `source_changed`) → re-snapshot (409 `proposal_changed`) → digest | no |
| onboarding | api/hardware/topology_acceptance.py | `TopologyAcceptanceService.confirm` L111 | ledger replay → re-`propose` → hmac digest compare → `read_topology` → scope → per selection create/relink entity + `write_edge` → activity → `infer_after_acceptance` (api/graph/inference/__init__.py:132) | no |
| onboarding | api/hardware/topology_observations.py | `onboard_topology` L174 / `schematic_topology` L256 | fixed allowed kinds `{ros2_nodes, ros2_topics, usb, tty, vendor}` → `_runtime_row` each; schematic → `_schematic_rows` | no |
| onboarding | lb/hardware/topology_extractors.py | `firmware_topology` L86 / `repo_config_topology` L151 | FirmwareFinding → evidence rows; RepoConfigMatch → `_config_rows` | no |
| onboarding | api/hardware/host_topology.py | `HostTopologyService.propose` L174 / `confirm` L314 / `_persist` L353 | `robot_root` → `_source` → companion identity == `machine_id` → runtime config has USB endpoint → `endpoint_id` is the brain → `provider.devices()` lists device_ref → `_source(lock)` → `_preview` → 256 KiB cap; confirm: ledger replay → re-propose → digest → `_persist` host+bus edges → `infer_after_host_confirm` → activity | no |
| onboarding | api/hardware/presence.py | `PresenceService.prepare` L110 | provider present → `binding` digest → `_wiring` digest → `provider.prepare` (compile) → lock → re-check both digests (409) → sha-check source+binary ≤100 kB → `create_artifact`×2 → plan entity → edges to robot and brain | partially — `hardware.flash_presence` executes a plan but prepare is HTTP-only |
| onboarding | api/hardware/presence.py | `PresenceService.execute` L337 | lock → `checked(plan)` → record `unknown` → commit → re-lock → binding digest → `_check_plan_wiring` → `provider.upload` → record `flashed` / `unchanged` / `unknown` | yes: `hardware.flash_presence` (gated, complete preview) |
| onboarding | api/hardware/presence_topology.py | `WiringService.propose` L265 / `checked` L316 / `accept` L353 | lock → `presence.binding` → `_evidence` (schematic edges via `_schematic` L133 or probe run via `_probe` L202) → proposal entity + edge; accept: `checked` → digest → status accepted | no |
| onboarding | lb/plugins/arduino/presence.py + presence_provider.py + wiring.py | `generate_source` L35; `LocalPresenceProvider.prepare` L86 / `upload` L114; `validate_wiring` L11 | profiles `{uno_avr, nano_avr}` × kinds `{heartbeat, probe, topology}` → `validate_wiring` → `snapshot` → `PresenceCompiler.prepare` → `validate`; upload: size cap → `validate` → `arduino-cli upload` → re-`validate` | partially — upload reached only through `hardware.flash_presence` |
| onboarding | api/hardware/library_router.py | `import_platform` L181 / `_reconcile` L125 | `PhysicalRobotService.create` → per slot `_attach_definition` → `put_config` → `_reconcile` (`detect_devices` → `suggest_links` → `persist_suggestions`) → publish → event | no |
| onboarding | api/hardware/library_router.py + api/hardware/library_import.py | `import_part` L247 / `import_standalone_part` L17 | definition lookup → standalone (idempotent ledger replay) or `robot_root` → `_attach_definition` → `ensure_config` → `put_config` → publish | no |
| onboarding | api/hardware/device_watch.py | `DeviceWatcher._tick` L85 | 1 s poll `detect_devices` → `_fingerprint` diff → hub publish | no (push only) |
| onboarding | api/agent/connect_integration.py | `_connect_integration` L234 / `_verify_integration` L283 | roster check → existing source short-circuit → `auth_kind != NONE` returns sign-in instruction → `_create_source` | yes: `solus.connect_integration` / `solus.verify_integration` (account connectors; no file/local-folder path) |
| onboarding | api/agent/tools/ros_live.py | `live_graph_tool` L37 / `LIVE_TOOLS` L30 | bridge `code.ros2_nodes` / `code.ros2_topics` → write graph entities under `lock_project` → `ros.live_confirmed` event | yes: `code.ros2_nodes` / `code.ros2_topics` (wrapper is fixed) |
| onboarding | api/agent/firmware_recipe.py | `FirmwareRecipe.prepare` L261 | `_topology` → path decided before read → `_current` via owned dry-run → `_ask` model with fenced data blocks → `_note_routed` → card via `machine.write_file` | yes: `firmware_recipe` + gated `machine.write_file` |
| onboarding | ui/features/graph/hardware/useDeviceProposals.ts | module scheduler `schedule` / `propose` / `useDeviceConfirmation` (header L1–L9; `MAX_IN_FLIGHT` L61, `SILENT_BACKOFF_MS` L62; hooks L368–L458) | auto-interrogate every stable device, ≤2 in flight, silent retry 5 s/15 s → `proposing→proposed|silent|failed→confirming→done`; confirm → `confirmDetected` → `awaitMark`; accept → `acceptHardwareSuggestion` | no |
| onboarding | ui/features/graph/hardware/deviceCardRules.ts | `DeviceCardStatus` L17, `cardQuestion` L99, `defaultAccepted` L115 | fixed status enum and "one question per card" rule | no |
| onboarding | ui/features/graph/hardware/HardwareAddPanel.tsx | `HardwareAddPanel` L46 | fixed flow order: `DevicesFound` → `HardwareSourcesPanel` → `HardwareSearch` → `DescribeNew` → `UnassignedParts` | no |
| onboarding | ui/features/graph/hardware/HardwareSearch.tsx | platform/part import handlers L185 / L238 | platform → `importLibraryPlatform` (new robot); part → `importLibraryPart` (robot or standalone) | no |
| onboarding | ui/features/graph/hardware/DescribeNew.tsx | submit L78–L84 | `categoryFromName` guess → `createHardwarePart` or `createUnassignedPart` | no |
| onboarding | ui/features/graph/robots/PresenceCard.tsx | `prepare` L76 | load profiles → `canPrepare` → `preparePresence` → hands SOL the text "Request the complete confirmation preview for hardware.flash_presence with plan_id …" L120 | partially — fixed prepare, then the SOL tool |
| onboarding | ui/features/graph/robots/PresenceWiringCard.tsx | propose L166 / accept L192 | mode `schematic` \| `probe` → `proposeWiring` → `acceptWiring` | no |
| onboarding | ui/features/graph/robots/ExtractionReviewCard.tsx | propose L84 / confirm L129 | pick `source_kind` → `proposeExtraction` → select rows → `confirmExtraction` | no |
| onboarding | ui/features/graph/robots/HostAttachmentCard.tsx | L172 / L160 | `proposeHostTopology` → review → `confirmHostTopology` | no |
| onboarding | ui/features/graph/robots/PartLinkSuggestions.tsx | L52 | `proposePartLinks` → accept/reject rows | no |
| onboarding | ui/features/graph/robots/FirmwareTelemetryOffer.tsx / HostMirrorOffer.tsx | status machine L93 / L37; `prepareFirmwareOffer` (firmwareTelemetrySnippet.ts:47), `prepareMirrorOffer` (hostMirrorSnippet.ts:42) | fixed snippet offer → `request()` drives `idle→pending→requested→uncertain` (request target not traced here) | no |
| onboarding | ui/features/onboarding/connectSteps.ts | `wizardSteps` L42, `STAGE_STEP` L75 | rail derived per connector: `local-bridge`→[`bridge`]; `export-file`→[`file`,`index`]; else [`access`?]→`authorize`→`configure`→`index` | no |
| onboarding | ui/features/onboarding/edaConnect.ts | `runEdaConnect` L94 | `createSource` (file content as config) → `triggerSync` → `pollAcceptedSync` → `getSource` → `indexedSyncDetail` | partially — `solus.connect_integration` cannot take KiCad files |
| onboarding | ui/features/onboarding/kicadFiles.ts | classifier L9–L40 | content-sniff → `xml-netlist` / `sexpr-netlist` / `board` / `schematic` → config key `export` / `board` | no |
| onboarding | ui/features/onboarding/ConnectWizardModal.tsx | `BridgeAction` branch L420 | `local-bridge` connectors (local folder / machine) get a single fixed "Connect on this computer" action | no |
| onboarding | ui/features/workspace/accountSteps.ts | `nextStep` L22 | fixed next-action per catalog entry for the connected-accounts card | no |
| bench | api/livebench/bench_router.py | `start_session` L587 / `_session_opener` L464 / `_robot_opener` L522 | provider switch replay \| robot \| hardware \| mujoco \| gazebo \| mcap \| serial → opener closure → `manager.start` → commit; robot path: `robot_root`/`hardware_entity` → host identity match → `resolve_runtime_config` → `read_entity_config` → `prepare_local_hardware` → `open_local_hardware` | no |
| bench | api/livebench/sessions.py | `SessionManager.start` L264 / `_start_evaluator` L396 | `_sweep_dead` → cap → synchronous reserve → `_acquire_connection` → `subscribe(TelemetryWindow)` → tap → window evaluator task | no |
| bench | lb/hardware/connection.py | `open_robot_connection` L119 | transport → driver → eager open → `ReconnectingSource` → `PartRoutingSource` → channel roles (order fixed by docstring) | no |
| bench | api/livebench/findings/window_evaluator.py | `WindowEvaluator.tick` L362 / `_judge` L561 / `_raise` L680 | `_load` → `_read` → `window_ends` → per window `_contexts` → `_assess` → `_evaluate` over `SIGNAL_RULES` → `coalesce` → `_raise` → missing-list write → `_tell` | partially — `get_finding` / `get_envelope` read results; evaluator itself not callable |
| bench | api/livebench/findings/rules/__init__.py | `SIGNAL_RULES` L19 | fixed tuple COMMAND→TRACKING→BODY→ELECTRICAL→SENSOR→PREDICTION (17 rule ids: command_exceeds_limit, command_rate_exceeds_limit, tracking_error_stall, tracking_error_slip, tracking_oscillation, body_lag, error_flag, current_over_rating, rail_sag_correlated, controller_reset_under_load, noise_tracks_motor_activity, sensor_frozen, sensor_out_of_range, rate_drift, stream_gap, temp_trend_to_limit, time_to_limit) | no (`run_checkers` is the graph checker library, not these) |
| bench | api/livebench/findings/envelopes.py | `build_envelope` L425 / `_assemble` L382 | fixed source precedence config → definition → scene → expected(sim) → learned(baseline); `warn` derived from limit × fraction; confidence = min over sources; 600 s cache | yes (read): `get_envelope` |
| bench | api/livebench/findings/sim_control.py | `classify_sim_control` L16 / `simulation_gap` L32 | fixed truth table over real/sim/task pass | partially — surfaces through `get_run` compare evidence |
| bench | api/livebench/runs/router.py | `start_run` L79 | `lock_project` → active-run caps 4/64 → session active → `snapshot` manifest → encode → `store.save` → `captures.add` | no |
| bench | api/livebench/runs/capture.py | `RunCaptureManager._checkpoint_loop` L163 / `persist` L187 | interval checkpoint while active → final persist on stop | no |
| bench | api/livebench/runs/router.py + api/livebench/runs/analysis.py | `compare_runs` L216 → `compare` L299 / `_twin_source` L252 | load both → optional twin from `sim_result` → `_divergences` → `_config_changes` → `_clamps` → `_finding_deltas` → `_sim_control` (+ residual attribution) | partially — `get_run` |
| bench | api/livebench/runs/analysis.py | `findings` L93 | per part: needs position + current + stall rating → `_stall_window` → "Possible stall" card; else insufficient | partially — via run findings route only |
| bench | api/livebench/runs/router.py + api/livebench/runs/narration.py | `narrate_run` L395 → `narrate` L53 | `analysis.findings` → one metered prose batch → `_parse` | no |
| bench | api/livebench/runs/router.py | `mark_baseline` L339 | flips baseline flag on one run | no |
| bench | lb/anomaly/observers.py + lb/anomaly/session.py | `ThresholdObserver` L40, `CusumObserver` L94, `GapWatchdog` L158; `SessionObservers.add` L32 | fixed observer set per local session (`local.session_observers` L567 builds `SessionObservers`) | no |
| bench | lb/deploy/check.py | `await_post_deploy_telemetry` L22 | wait until expected device ids seen or `max_packets` → `PostDeployReport` | no |
| bench | ui/features/bench/ConnectDeviceModal.tsx | connect L36 | pick enumerated USB-serial → `createBenchSession` serial config | no |
| bench | ui/features/bench/SavedRobotConnections.tsx | `onConnect` L11 | saved robot → `createBenchSession` robot config | no |
| bench | ui/features/bench/BenchScreen.tsx | `BenchScreen` (header L1–L2, sessions L67) | poll `useActiveBenchSessions` → narrow panels by confirmed topology → empty project opens Workspace Add Hardware | no |
| bench | ui/features/bench/DeviceBenchView.tsx | fetch loops L86 / L117 | `getBenchDeviceRecent` in batches of 16 + `getSignalAnomalies` poll | no |
| bench | ui/features/bench/runs/RunsView.tsx | L142–L144 / L208 / L264 | upload artifact → `importRun`; `startRun`; `stopRun` | no |
| bench | ui/features/bench/runs/RunEvidence.tsx | baseline select L91 → `compareRuns` L129 | choose baseline → compare → render evidence | partially — `get_run` |
| bench | ui/features/bench/runs/RunNarrationPanel.tsx | L35 | `narrateRun` | no |
| bench | ui/widgets/livebench/recognition/RecognitionPanel.tsx + proposals.constants.ts | `decide` L35; tiers L10/L48/L80/L96 | accept/reject/edit over fixture tiers; not mounted outside its tests | no (fixture UI) |
| bench | ui/widgets/livebench/LiveBenchWidget.tsx | widget (header L1–L4) | poll bench routes for the focused part | no |
| sim | api/simulation/sim_ladder.py | `should_simulate` L167 / `propose_for` L196 / `_ranked` L313 / `LOCAL_PROVIDERS` L380 | `_asked` from rule results → candidates above rung in where-order → cheapest first; fixed provider tuple Mech, Elec, Robot, MeshInterference, Ngspice, RigidBodyTrajectory | yes: `simulate` |
| sim | api/simulation/sim_ladder.py | `precheck_real_world_action` L443 | ladder proposals for touched subjects appended to every gated card | partially — automatic inside the gate |
| sim | api/agent/tools/simulate.py | `SimulationTools._simulate` L259 → `_act` L318 / `_run` L349 / `_climb` L421 / `_enqueue` L429 | rung 1 in-process → `record_sim_result` → climb → rung 3 enqueue (`run_mesh_sim`, ngspice, mujoco jobs) → rung 2/4 routed to `{target}.run_routine` | yes: `simulate` / `get_sim_result` |
| sim | api/agent/tools/apply_sim_change.py | `ApplySimChange` descriptor L569 | dry-run preview → gated apply → owner writer → re-run rung 1 → record | yes: `apply_sim_change` (gated) |
| sim | api/simulation/providers/external_providers.py | `ExternalTarget.run` L56 / `ExternalProviders.route` L83 | never runs; routes to `{target}.run_routine` | yes: `isaac.run_routine` |
| sim | api/simulation/mesh_job.py + providers/mujoco_job.py + providers/ngspice_provider.py | `run_mesh_sim` L49; mujoco `MAX_STEPS` L111 / `READS` L156; ngspice `READS` L115 | fixed job bodies: MJCF → ≤50 k steps → series; deck → ngspice → raw | partially — only through `simulate` |
| sim | api/agent/tools/isaac_tools.py | `build_isaac_tools` L400, `_DESCRIPTIONS` L42 | probe / status / start / stop / load_model / set_joint_limits / set_sensor_pose / run_routine | yes: `isaac.*` |
| sim | api/livebench/scene/cad_import.py | `propose` L173 / `materialize` L448 | lock → robot → `selection` walk → pending dedupe → queue/scene caps 32 → row + `_references`; materialize: `selection` → export revision match → `tessellate_isolated` → caps → `twin_of` → `_candidate_joints` / `_sensor_sites` → artifact → entry → references | yes: `bench.import_cad_scene` (gated) / `bench.cad_import_status` |
| sim | api/livebench/scene/router.py | `import_cad` L238 / `bind_cad` L141 | propose → `enqueue_sync` → publish; bind: version → mesh keys → `eligible` → single source → edges → `enqueue_sync` refresh | partially — import yes, `bind_cad` no |
| sim | api/livebench/scene/cad_refresh.py | `prepare` L183 / `refresh_model` L355 / `complete_imports` L504 | on source sync: plan → `_mesh_updates` → `_replacement` → revision check → `reconcile_source` → normalize → caps → artifact → edges → commit | no (sync side effect) |
| sim | api/livebench/scene/service.py | `SceneService.import_model` L115 / `mapping` L235 | fetch artifact → `read_meshes` → `parse_model` → lock → robot/source → version 409 → cap 32 → artifact entries → attrs → edges; mapping PUT | no |
| sim | api/livebench/scene/router.py | `finish` L24 | post-write `infer_after_scene` (api/graph/inference/__init__.py:38) | no |
| sim | api/livebench/scene/part_bindings.py | `bound_scenes` L54 / `scene_joint_for_part` L76 | fixed joint ↔ part ↔ channel resolution | partially — feeds `get_envelope` |
| sim | ui/features/bench/scene/ScenePanel.tsx | `importFile` L106 → L448 | format `urdf` \| `mjcf` → `uploadArtifact` → `uploadMeshes` → `importSceneModel` | no |
| sim | ui/features/bench/scene/CadImport.tsx | `importCad` L96 | `startCadImport` → poll `cadImportStatus` until `complete` | partially — tool exists |
| sim | ui/features/bench/scene/CadBindings.tsx | L73 | `bindCad` | no |
| sim | ui/features/bench/scene/MappingReview.tsx | `confirm` L92 | `confirmSceneMapping` | no |
| sim | ui/features/workspace/SimulatorStartModal.tsx | config builder L39–L48 | kind mujoco \| gazebo \| mcap-replay → `onStart` → bench session | no |
| sim | ui/features/workspace/SimulationPanel.tsx | panel (header L1–L5) | `GET bench/sources` → Start → Stop | no |
| sim | ui/features/workspace/IsaacConnectionPanel.tsx | L44 | poll `getIsaacConnectionStatus`; Connect/Disconnect monitoring | partially — `isaac.probe` / `isaac.status` |
| companion | lb/deploy/flash.py | `flash` L95 / `_DEVICE_PHASES` L57 | PREPARING → size cap → approval → ERASING(0.3) → WRITING(0.8) → VERIFYING(0.95) → DONE; no caller outside tests | no |
| companion | lb/plugins/arduino/arduino_flash.py | `ArduinoCliRunner.upload_argv` L23 / `run` L36 | pinned `arduino-cli upload` argv | no |
| companion | integrations/mcp/code/solus/arduino_upload.py | `arduino_upload` L210 / `_preview` L146 | `verify_cli` → `verify_runtime` → `read_sketch` → build-id match → `resolve_device` → dry-run preview; execution closed (L228) | yes (bridge): `code.arduino_upload` — preview only, no flash executes |
| companion | api/agent/tools/flash_history.py | `record_tool_history` L26 | `firmware.flashed` row after a clean `code.arduino_upload` | n/a (hook) |
| companion | lb/deploy/companion.py | `CompanionDeployer.apply` L170 / `_deploy` L265 / `recover` L236 | approval → unchanged + revalidate → push bundle to staging → `_stage` preflight → install → handshake → restore / rollback / cleanup | yes: `hardware.deploy_companion` (runs a prepared plan) |
| companion | api/hardware/companion_deployment.py | `CompanionDeploymentService.prepare` L126 / `execute` L245 | lock → target snapshot → bundle sha → plan entity → edge → event; execute: `checked` → `unknown` → re-validate target + bundle → `provider.execute` → sha match → outcome | partially — prepare HTTP-only; execute = tool |
| companion | lb/deploy/companion_remote.py | `RemoteDeployment.run` L79 | fixed phases preflight / install / rollback / cleanup via systemctl | no |
| companion | lb/recognition/active.py | `run_active_identification` L120 | approval → baseline capture → `command(plan)` → during capture → `correlate` → verdict; no caller in api/ or companion | no |
| companion | comp/machine/file_write.py + comp/machine/server.py | `preview` L202 / `write` L269; `MachineServer.call_tool` L204 | plan → descriptor-confined publish | yes: `machine.write_file` (gated) |
| companion | comp/dispatch.py | `Dispatcher._command_call` L205 | progress-stream caps → `supervisor.call_tool` (generic transport, no hardware sequence) | n/a |

Not fixed sequences (checked, excluded): `comp/supervisor.py`, `comp/watch.py`, `comp/kicad_discovery.py` (server lifecycle / fingerprinting only); `api/hardware/bindings.py`, `operations.py`, `runtime.py`, `local_runtime.py` (pure assembly/ledger helpers called by the rows above).


### Q48: Opinion — the ten things that would most change a SOL-driven plan
Status: opinion (marked as such; everything above this heading is code-backed, this section is judgment)

1. **The registry already has the right shape; the gap is coverage, not architecture.** `build_sol_registry` + `ToolDescriptor(requires_confirmation, requires_complete_preview, preview)` + the fused `build_dispatch` (auto-run → park → invoke) + STORED-args approval is exactly the confirmation gate the brief asks for. Converting a flow means writing a `Tool` that calls the existing service (`detect.propose_via_local`, `confirm_proposal`, `SessionManager.start`, `runs.compare`) — the services are already pure enough. Do not build a second gate.
2. **Every onboarding chain is a service behind a route; none is a tool.** `hardware_router.py` (1,113 lines) is the real API: `propose_detected`, `confirm_detected`, `_decide`, `_start_robot_session`, topology propose/confirm, host propose/confirm, presence prepare. Each is a 3–6 step fixed sequence with digest/409 re-checks. The cheapest conversion is a thin tool per step (`hardware.list_devices` ungated, `hardware.propose_device` ungated, `hardware.confirm_device` gated) that reuses the route bodies, then let SOL sequence them. The UI scheduler in `useDeviceProposals.ts` (auto-propose every stable device, ≤2 in flight, silent backoff) is the piece to delete first.
3. **The single-identity robot model blocks multi-brain before any tool does.** `HardwareConfig.identity: TransportBinding | None` and `sync_topology`'s "one endpoint per robot", plus `read_topology`'s tree validation, mean a two-MCU arm or an onboard Linux + MCU robot cannot be stored. A SOL-driven onboarding that asks "which brain is this?" needs `identity` to become a list keyed by brain and the tree check relaxed to a DAG. This is a tier-2 contract change; schedule it first.
4. **Sim and real will never land on the same part until something writes `external_ref` for sim joints.** The resolver is one line (`device_id == external_ref`) and already shared. The scene `Binding{joint, part_entity_id, device_id, …}` is the user-confirmed mapping — a tool that, on confirm, also registers `<scene>/<joint>` as a secondary ref for the part (or a resolver that consults bindings) makes `get_telemetry`, envelopes and findings work identically for sim. Without it, "SOL working inside the user's Gazebo/Isaac" produces unresolved packets.
5. **Isaac is a companion-side stdio fork, not a connection to a running Isaac Sim.** `isaac.load_model` always builds a fresh stage from Solus's URDF import and requires exactly one articulation; `isaac_direct.py` (human-run, under Isaac's python) is the only code that opens a user's USD stage. "SOL inside the user's own Isaac scene" needs new fork actions (`list_stages`, `open_stage`, `find_articulations`, `spawn_at`) and the cloud wrappers for them; the gating machinery for those is already there (`_ISAAC` auto-run list, `IsaacTool`, allowlist).
6. **Gazebo needs a connector, not a patch.** Everything is one `gz topic -e --json-output` subprocess per topic. Listing worlds/models (`gz model --list`, `gz service -l`), spawning (`gz service /world/<w>/create`), and reading joint states from `/world/<w>/model/<m>/joint_state` are all CLI-reachable without a ROS bridge, so a `gazebo` builtin companion server (like `machine`) with an allowlist is the natural shape, mirroring the Isaac fork's cloud wrappers.
7. **Findings are already graph-grounded and deterministic; narration is the only model path.** `WindowEvaluator` → `SIGNAL_RULES` (17 rules) → `graph.findings.raise_finding` runs on every robot session with envelopes from five prioritized sources. A SOL-driven bench should not re-invent detection; it should get `start_session`/`stop_session`, `list_runs`/`open_run`/`compare_runs` tools and the ability to *propose* an envelope source (a definition limit, a baseline run) — the `learned` tier already computes p1/p99 but throws it away after 600 s in Redis; persist it on the part with a `measured` provenance and SOL has characterization for free.
8. **No code on HEAD moves anything.** Codecs define `write_goal_position`/`torque_enable`; nothing calls them; `run_active_identification` has no caller; `code.arduino_upload`'s non-dry-run path is hard-refused; `deploy/flash.py` has no caller. The first "physical test" tool (bounded jog with `MAX_MAGNITUDE=0.2`, `MAX_DURATION_SECONDS=5.0`, complete preview, always a card) can reuse `active.py` nearly verbatim — but it also needs the driver write path, which is new code on a real bus. Budget hardware QA time for it; nothing here has been exercised with motion.
9. **Clock alignment is a data-model gap, not a bench UI gap.** A bare board's `ts_us = micros()` becomes a 1970-era timestamp and sits on a different axis from host-clocked drivers; windows bucket by `timestamp`. Any multi-brain bench or sim-vs-real comparison needs a per-source offset (estimate at session start from arrival time vs packet time, store on the session/brain, apply in `TelemetryPlumbing.ingest`). This is small and should precede multi-brain work.
10. **Context already carries the bench robot, focus, pins and findings; the project card knows active sessions.** `plan_scope(ScopeInputs(… robot_id …))`, the `findings` layer with envelope lines, the `telemetry` layer (120 s window when `runtime` weight is present) and the 300-token project card with active bench sessions mean SOL *can* reason about the bench today — it just cannot act. The conversion order that follows from all of the above: (i) read tools for devices/sessions/runs, (ii) gated propose/confirm/start/stop/compare tools wrapping existing services, (iii) the `identity`-as-list contract change, (iv) sim joint → part ref writer, (v) Gazebo builtin + Isaac stage tools, (vi) the first motion tool. Items (i)–(ii) and (iv) are small; (iii), (v), (vi) are where the risk is.

## G. Appendices (verbatim)

### G1 — The SOL tool table (Q4, verbatim copy)

Status: exists
Where:
- `packages/api/src/solus_api/agent/runtime.py` (1726) — `build_sol_registry` :111–283, `_register_user_tools` :307–426, `_register_bridge_tools` :505–623, `_owned_machine_tool` :626, `_owned_isaac_tools` :637
- `packages/api/src/solus_api/agent/tools/registry.py` (163) — `ToolRegistry` (invoke never raises, :76–114)
- `packages/api/src/solus_api/deps.py` (589) — `get_sol_registry` :502–560, the ONE production call site
- `packages/api/src/solus_api/agent/modes.py` (98) — Guide/Build dispatch wrapper
- `packages/api/src/solus_api/bridge/allowlist.py` (276) — companion allowlist gate
- `integrations/mcp/*/allowlist.yaml` — 11 files (altium 63, autocad 473, brave 29, code 127, fusion 40, isaac 38, kicad 77, local 22, machine 36, solidworks 338)
Note: 62 in-process tools register for a project with connectors/systems/artifact store/secret store wired and no companion connected. Companion ("bridge") tools are added per turn from the LIVE hello inventory of the requesting user's companion, filtered by the Solus-owned allowlist; `requires_confirmation` comes only from the allowlist. There is no per-mode tool list: Guide and Build are offered the SAME descriptors; Guide REFUSES at dispatch any tool with `requires_confirmation=True` (so "gated" == "Build-only").

**Method used:** `cd packages/api && uv run python <script>` calling
`build_sol_registry(async_sessionmaker(), pid, user_id=…, team_id=…, secret_store=InMemorySecretStore(), connectors=ConnectorRegistry(), systems=MagicMock(spec=SolSystems), artifact_store=MagicMock(), enqueue=MagicMock(), presence_service=MagicMock(), companion_deployment_service=MagicMock(), scene_enqueue=MagicMock(), graph_hub=MagicMock(), enqueue_sim=MagicMock(), redis=MagicMock())`, then `registry.tools()` and `research.model_visible(registry.list())`. Output header: `COUNT 62 model_visible 62`.

**Guide/Build rule (verbatim, `agent/modes.py:70–97`):**
```python
    mutating = frozenset(d.name for d in descriptors if d.requires_confirmation)

    async def mode_dispatch(call: ToolCall) -> ToolResult:
        refused = mode is ActionMode.GUIDE and call.tool in mutating
        result = mode_refusal(call) if refused else await dispatch(call)
```
`routers/sol.py:1095` offers `descriptors = with_knowledge_notes(tuple(registry.list()), …)` to BOTH modes; `runtime.py:1237` `offered = await placed_tools(model_visible(ctx.tools), …)` removes only `SERVER_DRIVEN_TOOLS` (= `{"research"}`, `agent/research.py:76`). Prompt text differs only: Guide "Explain and use read-only tools; never execute changes." vs Build (`prompt.py:385–393`).

Legend: **G** = gated (`requires_confirmation=True`: parks a card in Build, refused in Guide); **U** = ungated (both modes). "cond." = registered only under the named condition.

#### 4a. In-process tools (the 62 printed by the import)

**Hardware**
| name | one line | gate | Guide/Build | module (class) |
|---|---|---|---|---|
| `hardware.flash_presence` | Flash a prepared presence plan onto its reviewed local MCU (plan_id) | G | Build | `agent/tools/firmware_presence.py` (`PresenceFlashTool`, `requires_complete_preview=True`, timeout 150) |
| `hardware.deploy_companion` | Deploy a reviewed offline companion bundle to its provisioned onboard target (plan_id) | G | Build | `agent/tools/companion_deployment.py` (`CompanionDeploymentTool`, timeout 300) |
| `set_hardware_config_field` | Set ONE scalar field of a Physical Robot's hardware config by dotted path | G | Build | `agent/tools/solus_tools.py:461` |
| `firmware_recipe` | Write firmware for one board from the topology; writes nothing, returns path+content for `machine.write_file` | U | both | `agent/firmware_recipe.py:112` (cond.: user+team+secret_store) |
| `get_machine` | Read one machine by companion id (hostname, OS, arch, tool versions; recent_commands owner-gated) | U | both | `agent/tools/machine_tools.py:182` |
| `get_environment_divergences` | Stored environment divergence table per machine | U | both | `agent/tools/machine_tools.py:203` |
| `code.resolve_environment` | Propose the project's Python environment(s) from dependency files | U | both | `agent/tools/environment.py:29` |
| `analyze_rail_current` | Declared current contributions for one electrical net | U | both | `agent/tools/rail_current.py:22` (cond.: systems) |
| `sourcing.derive_torque` | Static holding torque for a CAD assembly | U | both | `sourcing/tools.py:28` |
| `link_environment` | Record a workspace code environment into `.solus` (reads `code.probe_environment`) | G | Build | `agent/tools/solus_tools.py:494` — **cond.: NOT in the 62**; only when the live companion advertises `code.probe_environment` ungated (`runtime.py:592–603`) |

**Bench**
| name | one line | gate | Guide/Build | module |
|---|---|---|---|---|
| `get_run` | Recorded summary of one bench run (robot, origin, status, counts, baseline flag) — not the packets | U | both | `agent/tools/finding_tools.py:146` |
| `bench.list_cad_sources` | Scoped synced CAD scene sources and observed revisions | U | both | `agent/tools/bench_scene.py:83` |
| `bench.import_cad_scene` | Import CAD geometry as a static Bench model | G | Build | `agent/tools/bench_scene.py:89` (`CadImportTool`) |
| `bench.cad_import_status` | Progress / resulting model identity for a CAD import | U | both | `agent/tools/bench_scene.py:102` |

**Telemetry**
| `get_telemetry` | Per-signal stats bucketed over a window (≤3600 s) | U | both | `agent/tools/builtin.py:113` (cond.: systems) |

**Scene / sim**
| name | one line | gate | Guide/Build | module |
|---|---|---|---|---|
| `simulate` | Simulate ONE quantity of one entity; rung 1 in-process, rung 3 enqueued, rungs 2/4 name the gated tool | U | both | `agent/tools/simulate.py` |
| `get_sim_result` | Read one simulation result by id | U | both | `agent/tools/simulate.py:717` |
| `apply_sim_change` | Apply ONE change `simulate` dry-ran this turn | G | Build | `agent/tools/apply_sim_change.py` (`SimChangeTool`) |
| `run_checkers` | Cross-domain checkers + interaction-matrix dry run around anchors | U | both | `agent/tools/builtin.py:207` (cond.: systems) |

**Isaac** — none in the 62; exist only when the connected companion advertises the `isaac` server (`runtime.py:637–662`, `agent/tools/isaac_tools.py`, `IsaacTool`, `requires_complete_preview = name not in ("probe","status")`): `isaac.probe`, `isaac.status` (U) and `isaac.start`, `isaac.stop`, `isaac.load_model`, `isaac.set_joint_limits`, `isaac.set_sensor_pose`, `isaac.run_routine` (G, Build) — timeouts `isaac_tools.py:30–39`.

**Gazebo** — absent as a SOL tool. Gazebo exists only as a bench-session source kind (`livebench/src/livebench/local.py:290 open_gazebo`), never reaches the registry.

**Code**
| `read_code_file` | Bounded line-numbered read of a mentioned `code_file` (internally dispatches `machine.read_code_file` on the companion) | U | both | `agent/tools/read_code_file.py` (cond.: connectors) |
| `machine.write_file` | Create/edit one workspace text file with complete before/after preview | G | Build | `agent/tools/machine_writes.py:69` (`MachineWriteTool`) — **cond.: wraps the bridge tool, only with a companion** |

**Graph / search / perception**
| name | one line | gate | Guide/Build | module |
|---|---|---|---|---|
| `get_entity` | Fetch a graph entity by id | U | both | `agent/tools/get_entity.py:22` |
| `query_graph` | Neighbourhood around anchors (degree ≤2, domains closed enum excluding `workspace`) | U | both | `agent/tools/builtin.py:70` |
| `search_workspace` | Search graph entities by name/text/ref | U | both | `agent/tools/search_tools.py:125` |
| `search_corpus` | Shared engineering-practice corpus | U | both | `agent/tools/search_tools.py:146` |
| `get_history` | Project history newest first | U | both | `agent/tools/machine_tools.py:213` |
| `retrieve_errors` | Error/solution history similar to a query | U | both | `agent/tools/builtin.py:146` |
| `render_view` | One labelled render of an entity, answered by vision | U | both | `agent/vision/render_view.py:120` |
| `make_diagram` | Wiring / plug-in diagram into a TTL artifact | U | both | `agent/tools/make_diagram.py:43` (cond.: artifact_store) |
| `label_motifs` | Label unsettled netlist motifs (metered model call) | U | both | `agent/tools/label_motifs.py:98` |
| `read_document` | PDF datasheet page-by-page extraction with citations | U | both | `agent/tools/read_document.py:83` |
| `propose_part_definition` | File a candidate part definition into `.solus` | G | Build | `agent/tools/read_document.py:137` |
| `extract_rulebook` | Candidate numeric limits from a filed rulebook PDF | U | both | `agent/tools/rulebook_tools.py:121` |

**`.solus`**
| `add_solus_entry` | File a short note into a `.solus` section | U | both | `agent/tools/solus_entry.py:27` |
| `search_solus` | Search `.solus` entries | U | both | `agent/tools/search_tools.py:136` |
| `edit_solus_entry` | Replace a note's text | G | Build | `agent/tools/solus_tools.py:431` |
| `delete_solus_entry` | Remove an entry (irreversible) | G | Build | `agent/tools/solus_tools.py:448` |

**Findings**
| `get_finding` | One finding: headline, severity, status, rule, subjects, newest evidence | U | both | `agent/tools/finding_tools.py:137` |
| `get_envelope` | Operating envelope of ONE quantity of a part | U | both | `agent/tools/finding_tools.py:157` |

**Research**
| `research` | Web research loop over the vendored Brave fork | U | **neither (server-driven)** | `agent/tools/research_tool.py:207` — cond.: Brave tools discovered at request scope; in `SERVER_DRIVEN_TOOLS`, removed from the model's specs (`research.py:617`) and answered NOT_FOUND if the model names it (`research.py:622–637`) |

**Integrations / Onshape (in-process)**
| `solus.list_integrations`, `solus.verify_integration` | U | `agent/connect_integration.py:51,76` |
| `solus.connect_integration` | G | `agent/connect_integration.py:61` |
| `onshape.list_documents`, `.list_elements`, `.list_parts`, `.get_feature_tree`, `.get_feature_specs`, `.get_variables`, `.get_mass_properties`, `.get_part_bounds`, `.get_body_details`, `.get_assembly_definition`, `.inspect_assembly_geometry`, `.resolve_reference` | U | `agent/tools/onshape_tools.py` |
| `onshape.add_feature` | G (`InProcessTool`, NOT auto-run eligible) | `agent/tools/onshape_tools.py` |
| `onshape.create_circle_sketch`, `.extrude_cut`, `.set_variable`, `.update_feature`, `.insert_part`, `.create_face_mate_connector`, `.create_circle_mate_connector`, `.create_fastened_mate`, `.restore_fastened_pose`, `.create_revolute_mate` | G (`ConfirmedOnshapeTool`) | `connectors/onshape_confirmation.py` |

Also conditional, not in the 62: hosted vendor MCP tools (`_register_hosted_tools`, Onshape FeatureScript, stored inventory), first-party widget-bundle tools (`_register_bundle_tools`), and `code.ros2_nodes`/`code.ros2_topics` wrapped by `agent/tools/ros_live.py:30–33` when advertised.

#### 4b. Companion allowlists SOL can reach (parsed from `integrations/mcp/*/allowlist.yaml` with `yaml.safe_load`)

Bridge tools become `{server}.{tool}` descriptors (`allowlist.py:validate_inventory`). Never offered to the model: `machine.read_code_file` (internal to `read_code_file`) and any `returns_image` tool (`runtime.py:534–536`).

```
=== machine  launched_by=builtin  tools=4 gated=2
  read_code_file   ungated   (hidden from the model; used by read_code_file)
  read_file        GATED
  write_file       GATED files_errors   (wrapped as MachineWriteTool)
  tool_versions    ungated
=== code  launched_by=companion  tools=25 gated=15
  probe_environment · plan · git_status · git_log · git_diff (ungated) · arduino_probe t=15 ·
  process_status t=15 · profile_list t=15 · ros2_nodes t=30 · ros2_topics t=30
  GATED: create_environment t=630 · install t=630 · run t=630 · test t=630 · git_commit t=90 ·
  git_push t=120 · arduino_prepare t=630 · arduino_compile t=150 · arduino_upload t=150 · exec t=630 ·
  process_start t=30 · process_stop t=30 · profile_capture t=60 · profile_delete t=15 · process_input t=15
  (GATED code.* carry files_errors except process_*/profile_*)
=== local  launched_by=companion  tools=3 gated=1
  scan_folder ungated · folder_digest ungated · open_in_tool GATED
=== isaac  launched_by=companion  tools=8 gated=6
  probe ungated · status ungated · start GATED t=195 · stop GATED t=20 · load_model GATED t=165 ·
  set_joint_limits GATED t=25 · set_sensor_pose GATED t=25 · run_routine GATED t=55   (all gated: files_errors)
=== kicad  launched_by=companion  tools=18 gated=6
  get_symbol_definition · get_schematic_geometry · check_erc · list_projects · get_project_structure ·
  extract_project_netlist · analyze_schematic_connections · analyze_bom · export_netlist · export_spice_netlist (ungated)
  export_schematic_pdf · export_board_pdf  (ungated, returns_image → only via render_view)
  GATED: create_schematic · add_symbol · add_wire · add_net_label · mark_no_connect · set_symbol_property
=== altium  launched_by=companion  tools=11 gated=2
  app_get_status · proj_get_path · proj_list_documents · proj_get_stats · proj_get_bom · proj_get_nets ·
  proj_get_component_info · list_nets · export_netlist (ungated)
  GATED: proj_set_parameter · sch_set_components_parameters
=== autocad  launched_by=companion  tools=155 gated=155  (every entry GATED; reasons "TODO Solus-authored")
=== solidworks launched_by=companion  tools=62 gated=62  (every entry GATED, incl. reads like get_mass_properties)
=== fusion  launched_by=companion url=http://127.0.0.1:27182/mcp  tools=0
=== brave  launched_by=cloud  tools=4 gated=0
  brave_web_search · brave_llm_context · brave_news_search · brave_summarizer
  (API-spawned; only brave_web_search + brave_llm_context are driven, by the server-side `research` loop — research.py:81-82)
```

---


### G2 — Hardware, bench and sim entity kinds and attrs shapes (Q10, verbatim copy)

Status: exists
Where: `packages/api/src/solus_api/graph/kinds.py` (92) — the vocabulary; writers: `services/physical_robots.py` (295), `hardware/store.py` (727), `hardware/topology.py` (412), `hardware/host_topology.py` (421), `hardware/topology_acceptance.py` (222), `hardware/presence.py` (388), `hardware/presence_topology.py` (362), `hardware/companion_deployment.py` (331), `services/machines.py` (169), `services/solus_graph.py` (300)
Note: `kind` is a free string column; `kinds.py` is the one list. `hardware_topology_member` is NOT an entity kind — it is a **relation type** (`topology.py:27`, `solus_contracts/relations.py:58`). There is no Pydantic/TypedDict model for any hardware entity's `attrs`; every shape below is the dict literal the writer code builds.

**The hardware block of `graph/kinds.py` (verbatim, lines 28–38):**
```python
# hardware
PHYSICAL_ROBOT: Final[str] = "physical_robot"
ROBOT_CATEGORY: Final[str] = "robot_category"
HARDWARE_CONFIG: Final[str] = "hardware_config"
HARDWARE_BRAIN: Final[str] = "hardware_brain"
HARDWARE_BUS: Final[str] = "hardware_bus"
HARDWARE_EVIDENCE: Final[str] = "hardware_evidence"
HARDWARE_PRESENCE_PLAN: Final[str] = "hardware_presence_plan"
HARDWARE_WIRING_PROPOSAL: Final[str] = "hardware_wiring_proposal"
#: Legacy camel case; stored in dev DBs, so renaming it is a data migration.
COMPANION_DEPLOYMENT_PLAN: Final[str] = "companionDeploymentPlan"
```
plus (lines 70–72) `MACHINE = "machine"`, `MEMBER = "member"`, and `PART = "part"` (line 14). Relation types used with these: `contains`, `configures`, `binds`, `hardware_connected_to`, `hardware_topology_member`, `hardware_evidence_for`, `presence_prepared_for`, `wiring_proposed_for`, `deployment_for_target`.

**Attrs as written (verbatim dict literals):**

| kind | writer | domain / origin | attrs literal |
|---|---|---|---|
| `physical_robot` | `services/physical_robots.py:165-172` | `PROJECT` / `manual` | `{"hardware_config_ref": None, "transport_refs": None}` — `hardware_config_ref` is later set to the CONFIG `SolusEntry` id (`store.py:223`); `transport_refs` is never written anywhere else (grep: only this literal). |
| `robot_category` | `services/physical_robots.py:174-184` | `PROJECT` / `manual` | `{"robot_id": str(root.id), "category": key}` — one per key of `ROBOT_CATEGORIES = {"sensors","actuators","controllers","end_effectors","power","structure","wiring"}` (`physical_robots.py:24-32`); edge robot→category `contains`. |
| `part` (detected) | `hardware/store.py:attach_part` 505-543 and `detect.py:confirm_proposal` | `PROJECT` / `manual` | `{**attrs, "category": category, "robot_id": str(robot.id), "provenance": provenance.value}` where detect passes `attrs={"address": row.address, "model": row.model, "device_ref": proposal.device_ref}`; `external_ref = "<device ref>/<address>"` (`part_ref`, `config.py:76`). |
| `part` (authored) | `store.py:create_part` 546-580 | same | `attrs={"specs": dict(specs)}` → merged with `category`, `robot_id`, `provenance="user"`. |
| `hardware_config` | `store.py:_create_entry` 186-226 via `solus_graph.attach_entry` 262-300 | `PROJECT` / `.solus` ORIGIN | `{"solus_entry_id": str(entry.id), "section": "environment", "subsection": "hardware", "configured_entity_id": str(subject.id)}`; edge config→subject `configures`. The config DOCUMENT itself is the `SolusEntry.payload` (`HardwareConfig` v1 / `EntityHardwareConfig` v2, `hardware/config.py`), not the node attrs. |
| `hardware_brain` (USB endpoint, derived) | `topology.py:sync_topology` 104-113 + `_node` 173-215 | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_topology_v1", "channel": config.identity.kind.value}`; id = `uuid5(project_id, "hardware_topology_v1:endpoint:<device_ref>")`; name = `device_ref`. No `brain_kind` on this node (comes from the host overlay edge, see Q11). |
| `hardware_bus` (derived) | `topology.py:119` | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_topology_v1"}` (facts `{}`); id = `uuid5(endpoint_id, "bus:<protocol>")`; name = protocol string (driver id). |
| `hardware_brain` (host) + `hardware_bus` ("USB") | `host_topology.py:_persist` 361-375 | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_host_topology_v1", "brain_kind": node.brain_kind, "channel": node.channel}` → host: `brain_kind="host", channel="local"`; bus: `brain_kind=None, channel="usb"`. id = `uuid5(project_id, "hardware_host_topology_v1:host:<machine_id>")`, bus `uuid5(host_id,"usb")`. |
| `hardware_evidence` | `topology_acceptance.py:154-166` | `ELECTRICAL` / `manual` | `{"managed_by": "hardware_topology_v1", "nonoperational": True, "robot_id": str(robot_id)}`; edge brain→evidence `hardware_connected_to` with attrs `{managed_by, nonoperational, robot_id, reviewed_by, is_placement, reviewed_name, proposal_digest, source_kind, row}`. |
| `hardware_presence_plan` | `presence.py:prepare` ~150-190 | `RUNTIME` / `system` | `{"created_by", "robot_id", "brain_id", "profile", "kind", "target", "config_digest", "status": "prepared", "wiring_proposal_id", "wiring_digest", "source_artifact_id", "source_sha256", "binary_artifact_id", "binary_sha256"}`; `status` ∈ prepared→unknown→flashed/prepared. Edges plan→robot, plan→brain `presence_prepared_for`. |
| `hardware_wiring_proposal` | `presence_topology.py:propose` | `RUNTIME` / `system` | `{"created_by", "robot_id", "brain_id", "request": <WiringRequest json>, "digest", "status": "proposed"\|"accepted", "observations": [...], "unresolved": [...]}`; edge → brain `wiring_proposed_for`. |
| `companionDeploymentPlan` | `companion_deployment.py:prepare` 139-151 | `RUNTIME` / `system` | `{"created_by", "target_id", "artifact_id", "artifact_sha256", "target": <DeploymentTargetSnapshot json>, "status": "prepared"}` then `+ "outcome"`; edge → target `deployment_for_target`. |
| `machine` | `services/machines.py:upsert_machine` 118-148 | `RUNTIME` / `system` | `{**MachineIn(hostname, os, arch), "owner_user_id", "tool_versions": {...}, "devices": [], "flash_history": [], "recent_commands": []}`; `canonical_key = "machine:<companion_id>"`. `devices`/`flash_history` are created empty here and never written in this file (bridge command log owns `recent_commands`). |
| `member` | `machines.py:ensure_member` 60-80 | `PROJECT` / `system` | `{"display_name": display_name}`; `canonical_key = "member:<user_id>"`; member→machine `contains`. |

`DetectedDeviceOut` / `ProposalOut` (what the UI sees pre-confirm) are NOT graph entities — see Q16.

---


### G3 — Session provider config models (Q26), RunManifest (Q28), LB-06 packet (Q14), observer event types (Q29) — verbatim copies

#### G3.1 Session provider config models (from Q26)
Status: exists (UI start/stop); absent (SOL start/stop)
Where: packages/api/src/solus_api/livebench/bench_router.py (737), livebench/sessions.py (516), hardware/connections.py (420), hardware/hardware_router.py (1113), hardware/local_runtime.py (94), hardware/runtime.py (149), livebench/replay_provider.py (144), livebench/src/livebench/local.py (571), livebench/src/livebench/sim/connections.py (81), livebench/src/livebench/hardware/connection.py (150), livebench/src/livebench/telemetry/stream_live.py (143), packages/api/src/solus_api/connectors/live.py (122), apps/desktop/src/renderer/src/lib/api/resources.ts (1777), ConnectDeviceModal.tsx (122), SavedRobotConnections.tsx (124), packages/api/src/solus_api/main.py (691)
Note: `provider` is a discriminator on the request union (7 literals) but a plain `str` on the wire-out model. One in-memory `SessionManager` per API process owns every `TappableConnection`; `HardwareConnections` wraps it for saved-robot connections started from the Hardware confirm flow and mirrors state onto `physical_robot.attrs.connection`. No SOL tool starts or stops a session.

**Provider values.** Request side (`bench_router.py:270, 281, 294, 308, 326, 334, 345`): `"mujoco" | "gazebo" | "mcap-replay"` (sim; `_SIM_PROVIDERS = {"mujoco", "gazebo", "mcap-replay"}` `:232`) and `"serial" | "robot" | "hardware" | "replay"` (real). Connection-class `provider: ClassVar[str]`: `"mujoco"` (sim/connections.py:24), `"gazebo"` (`:55`), `"mcap-replay"` (`:72`), `"robot"` (hardware/connection.py:30), `"noop"` (connectors/live.py:82). The driverless `serial` path opens `SerialRobotConnection` (livebench/telemetry/robot.py) — its ClassVar value: not determined (file not read).

**Out model (verbatim, sessions.py:152-169):**
```python
class BenchSessionOut(BaseModel):
    """Wire shape of one bench session (frozen contract with the desktop)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    mode: Literal["sim", "real"]
    provider: str
    status: Literal["starting", "active", "ended"]
    link: str
    label: str
    created_at: datetime
    ended_at: datetime | None
    device: dict[str, Any] | None
    device_ids: list[str]
    counts: dict[str, int]
    last_summary: dict[str, Any] | None
    robot_entity_id: UUID | None = None
```
`link` is `LiveStatus` (connectors/live.py:36-41): `DISCONNECTED = "disconnected"`, `CONNECTED = "connected"`, `STREAMING = "streaming"`.

**Request config models (verbatim, bench_router.py:267-371):**
```python
class MujocoSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mujoco"]
    scene_name: str = Field(default="demo", min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    mjcf_xml: str | None = Field(default=None, min_length=1, max_length=MAX_MJCF_BYTES)
    sample_hz: float = Field(default=50.0, gt=0, le=200)
    duration_seconds: float = Field(default=300.0, gt=0, le=MAX_SESSION_SECONDS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class GazeboSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gazebo"]
    topics: list[str] = Field(min_length=1, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str]) -> list[str]:
        return _clean_topics(topics)


class McapSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mcap-replay"]
    mcap_path: str = Field(min_length=1, max_length=4096)
    topics: list[str] | None = Field(default=None, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str] | None) -> list[str] | None:
        return None if topics is None else _clean_topics(topics)


class SerialRealConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["serial"]
    serial_number: str | None = Field(default=None, min_length=1, max_length=128)
    confirmed_device_path: str | None = Field(default=None, min_length=1, max_length=256)
    baud: int = Field(default=115200, ge=300, le=3_000_000)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)
    # SOLUSDEV-248: a protocol driver by id with generic parameters — never a closed list of
    # driver names in this schema; the registry decides what exists.
    driver_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    driver_params: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=32
    )


class RobotRealConfig(BaseModel):
    """A session from a Physical Robot's HardwareConfig (docs/api/hardware.md §6)."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["robot"]
    robot_entity_id: uuid.UUID
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class HardwareRealConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["hardware"]
    entity_id: uuid.UUID
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class ReplayRealConfig(BaseModel):
    """DEV ONLY (docs/api/bench-runs.md): a recorded capture replayed as one of the project's
    robots. `recording` is a file under `Settings.bench_replay_root`; `driver_id` decodes it."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["replay"]
    recording: str = Field(min_length=1, max_length=4096)
    driver_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    robot_entity_id: uuid.UUID
    realtime: bool = True
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("recording")
    @classmethod
    def _printable(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("recording may not contain control characters")
        return value


class BenchSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["sim", "real"]
    config: Annotated[
        MujocoSimConfig
        | GazeboSimConfig
        | McapSimConfig
        | SerialRealConfig
        | RobotRealConfig
        | HardwareRealConfig
        | ReplayRealConfig,
        Field(discriminator="provider"),
    ]

    @model_validator(mode="after")
    def _mode_matches_provider(self) -> "BenchSessionIn":
        is_sim = self.config.provider in _SIM_PROVIDERS
        if is_sim != (self.mode == "sim"):
            raise ValueError(f"provider {self.config.provider!r} does not run in {self.mode} mode")
        return self
```
Constants (bench_router.py:226-230): `MAX_MJCF_BYTES = 2_000_000`, `MAX_TOPICS = 32`, `MAX_SESSION_SECONDS = 3600.0`, `MAX_WINDOW_SECONDS = 60.0`. `replay` needs `Settings.bench_replay_root` (core/config.py:286); `mcap-replay` needs `bench_data_root` (`:282`); `/bench/sources` reports `isaac` as never startable (local.py:134-143).

**Lifecycle owner.** `SessionManager` (sessions.py:236-516), in-memory, project-keyed: `DEFAULT_MAX_ACTIVE_PER_PROJECT = 4`, `DEFAULT_ENDED_KEPT = 32` (`:44-45`). `start` reserves a slot synchronously, acquires the connection through shielded `open_conn` (`_acquire_connection`, `:135-149`), installs the packet `tap` (`_tap_for`, `:358-382`: every packet → `TelemetryPlumbing.ingest`, observer, `ingested`/`unresolved`, `_note_part`), `subscribe(TelemetryWindow(duration_seconds=window_seconds))`, `on_batch` → `last_summary`, starts the evaluator for robot sessions (`:264-330`). `stop`/`_close_session` sets `ended_at` first, cancels the evaluator (`EVALUATOR_STOP_SECONDS = 5.0`), `aclose()`s the connection, calls `on_ended` (`:446-493`). `_sweep_dead` ends sessions whose pump reports `DISCONNECTED` (`:495-502`). Wired once in `main.py:492-511` with `observer_factory = livebench.local.session_observers`, `event_sink → BenchEventRing.append`, `evaluator_factory → WindowEvaluator(...)`.

`HardwareConnections` (hardware/connections.py:76-420) is the second owner for saved robots: `schedule()` (called from the Hardware confirm route, hardware_router.py:771-773) runs `_run` → `resolve_runtime_config` + `prepare_local_hardware` + config stamp check → `manager.start(mode="real", provider="robot", …, robot_entity_id=…, owner_user_id=…)` (`:312-323`) and writes `attrs.connection = {managed_by:"local_runtime", attempt_id, status connecting|connected|failed|disconnected, session_id, error, runtime_id}` on the `physical_robot` (`connection_state`, `:49-64`), publishing `graph.changed`. `manager.on_ended = self._session_ended` (`:93`). `routers/entities.py:213` cancels a robot's connection on delete.

**Start/stop from the UI.** `ConnectDeviceModal` → `start()` → `createBenchSession(projectId, input)` (`ConnectDeviceModal.tsx:34-36`; `resources.ts:1507` → `POST /projects/{p}/bench/sessions`); saved robot sends `{ mode: 'real', config: { provider: 'robot', robot_entity_id: robot.id } }` (SavedRobotConnections.tsx:56-59); devices/simulators send their config via `Devices` (`:105`). Stop → `stopBenchSession` (`resources.ts:1541` → `POST …/bench/sessions/{id}/stop`). Server emits data events `bench.session_started` / `bench.session_stopped` (bench_router.py:636-644, 684-692 → `services/events.emit_event` → `DataEvent`).

**Start/stop from SOL: absent.** Every registered in-process tool name on HEAD (grep over `packages/api/src/solus_api/agent`):
```
add_solus_entry, altium, analyze_rail_current, autocad, bench.cad_import_status,
bench.import_cad_scene, bench.list_cad_sources, brave, code.resolve_environment,
delete_solus_entry, edit_solus_entry, extract_rulebook, firmware_recipe, fusion,
get_entity, get_envelope, get_finding, get_run, get_telemetry, hardware.deploy_companion,
hardware.flash_presence, isaac.* , kicad, label_motifs, link_environment,
machine.write_file, make_diagram, onshape_fs, propose_part_definition, query_graph,
read_code_file, read_document, render_view, retrieve_errors, run_checkers,
set_hardware_config_field, solidworks, solus.connect_integration,
solus.list_integrations, solus.verify_integration, FeatureScript, <mcp>.<remote> (dynamic)
```
(`get_finding`/`get_run`/`get_envelope` are registered via `bounded_read_tool` in finding_tools.py:131-166, which a `name="…"` grep misses.) SOL only READS sessions: `project_card.card_inputs` lists active sessions for `active_device_ids` (agent/project_card.py:317-325) and `GraphFactSources` is handed the `SessionManager` (agent/deterministic_facts.py:200-206).

---


#### G3.2 RunManifest (from Q28)
Status: exists (capture/compare/playback/import/baseline); partial (SOL: summary read only, no compare)
Where: packages/api/src/solus_api/livebench/runs/models.py (128), capture.py (236), store.py (199), analysis.py (759), snapshot.py (247), router.py (423), narration.py (119), apps/desktop/src/renderer/src/features/bench/runs/RunsView.tsx (373), RunEvidence.tsx (313), RunPlayback.tsx (85), playback.ts (46), runsApi.ts (240), packages/api/src/solus_api/agent/tools/finding_tools.py (166)
Note: A run is a `bench_run` graph entity plus an 8 MiB JSON artifact of packets, a parts/revision snapshot taken at start, and the findings its session raised. Compare is a server-side pure diff (optionally against a simulation twin). Playback is a client-side slider over exact recorded instants. SOL can read a run's summary (`get_run`) but has no tool to list, open the packets of, or compare runs.

**RunManifest (verbatim, models.py:29-101):**
```python
class PartEvidence(StrictModel):
    entity_id: UUID
    name: Text
    device_id: Text
    current_signal: Signal | None = None
    position_signal: Signal | None = None
    command_signal: Signal | None = None
    stall_current_a: Annotated[FiniteFloat, Field(gt=0)] | None = None
    position_min: FiniteFloat | None = None
    position_max: FiniteFloat | None = None
    position_unit: Annotated[str, Field(max_length=32)] | None = None
    code_site: Text | None = None
    cad_revision: Text | None = None


class SensorReference(StrictModel):
    artifact_id: UUID
    timestamp: AwareDatetime
    kind: Literal["camera", "lidar"]
    device_id: Text


class RevisionSnapshot(StrictModel):
    entity_id: UUID
    kind: Text
    name: Text
    source_id: UUID | None = None
    revision: Text | None = None
    # JSON serialized CONFIG/graph data, individually bounded and inert.
    data: Annotated[str, Field(max_length=65536)] | None = None


#: The graph findings one run's manifest carries at most (SOLUSDEV-321 P2-T7).
MAX_RUN_FINDINGS = 64


class RunFinding(StrictModel):
    """A graph finding the run's bench session raised while it ran (`runs/capture.py`): its id,
    and what compare matches it on across runs — `rule_id` and the sorted `subjects`, since a
    finding's id is per bench session — with how often and when it showed."""

    finding_id: UUID
    rule_id: Annotated[str, Field(min_length=1, max_length=128)]
    subjects: Annotated[list[UUID], Field(max_length=64), AfterValidator(sorted)]
    severity: Literal["info", "warning", "critical"]
    count: int = Field(ge=1, le=10**9)
    first_seen: AwareDatetime
    last_seen: AwareDatetime


class RunManifest(StrictModel):
    schema_version: Literal[1] = 1
    robot_id: UUID
    started_at: AwareDatetime
    packets: list[TelemetryPacket] = Field(default_factory=list, max_length=MAX_PACKETS)
    sensors: list[SensorReference] = Field(default_factory=list, max_length=10000)
    parts: list[PartEvidence] = Field(default_factory=list, max_length=256)
    snapshots: list[RevisionSnapshot] = Field(default_factory=list, max_length=256)
    # Optional, so every manifest recorded before findings existed still loads.
    findings: list[RunFinding] = Field(default_factory=list, max_length=MAX_RUN_FINDINGS)

    @model_validator(mode="after")
    def unique_parts(self) -> Self:
        if len({part.entity_id for part in self.parts}) != len(self.parts):
            raise ValueError("duplicate part identity")
        if len({part.device_id for part in self.parts}) != len(self.parts):
            raise ValueError("ambiguous part device identity")
        signals: set[tuple[str, str]] = set()
        for packet in self.packets:
            signals.update((packet.device_id, name) for name in packet.values)
            if len(signals) > 4096:
                raise ValueError("at most 4096 distinct device signals per run")
        return self
```
`MAX_BYTES = 8 * 1024 * 1024`, `MAX_PACKETS = 10000` (`:19-20`). `RunSummary` (`:117-128`): `id, robot_id, session_id?, name, origin: Literal["live","recorded","synthetic"], status: Literal["running","completed","truncated","interrupted"], started_at, ended_at?, packet_count, drop_count, artifact_id?`; `RunRead` adds `baseline: bool` (store.py:168-173).

**What a run captures.** `POST /bench/runs` (router.py:78-122): session must be `active`; `snapshot()` (snapshot.py:113-183) takes the robot's `focus_entity_ids` closure (≤256), builds `PartEvidence` for every `part` with an `external_ref` from the runtime hardware config (signals by channel suffix `position`/`current`/`commanded_position`, `stall_current_a` from `attrs.specs`, `position_min/max_<unit>` from limits), a `RevisionSnapshot` per entity (`revision = str(entity.version)`, `data` = attrs keys `specs, code_site, cad_revision, microversion, model_id, units`) and one per hardware-config entry (`kind="hardware_config"`, `revision = str(config_version)`, `data = payload`); refuses a session whose device does not match the robot's accepted identity (`:154-159`). `RunCaptureManager.ingest` (capture.py:457-488) appends every packet of that `session_id` with a byte cost until `MAX_PACKETS`, 4096 distinct signals or the byte budget (8 MiB − 1 KiB − 32 KiB findings reserve) → `truncated`, `drop_count++`. Checkpoint every 2 s (`:443`); `findings_during` (`:364-408`) folds in findings whose `evidence.session_id` is the run's session. Session ended → `interrupted`. Limits: 4 running/project, 64/process (router.py:96).

**Storage.** `GraphEntity(kind="bench_run", domain=PROJECT, origin="system", attrs={summary, checkpoint_id, created_by[, baseline]})` (store.py:146, 311-323); bytes via `create_artifact(media_type="application/vnd.solus.bench-run+json", source_tool="bench.capture")`, `retained=True`; final checkpoint filed into `.solus` DOCUMENTATION/guides as `<name>.bench-run.json` (`:244-255`); previous checkpoint soft-deleted and removed (`:261-284`). Sensor artifacts referenced are marked retained (`:213-229`).

**Routes** (router.py; prefix `/api/v1/projects/{p}/bench/runs`, `require_verified`): `POST ""`, `POST /import` (uploaded manifest, `origin recorded|synthetic`, `portable_manifest` + `validate_references`), `GET ""` (cursor, ≤50), `POST /compare`, `GET /{run_id}`, `POST /{run_id}/stop`, `POST /{run_id}/baseline` (one per robot; the evaluator reads its learned bounds), `GET /{run_id}/findings`, `POST /{run_id}/narrate`.

**Compare logic.** `CompareIn {baseline_id, candidate_id, sim_result_id?}` (`:57-62`). Running runs refused (409). With `sim_result_id`, `_twin_source` reads the project's `sim_result` entity + scenes binding the candidate's parts, and `analysis.twin_run` BUILDS the baseline from the simulation (`:247-282`). `analysis.compare` (analysis.py:299-317) returns:
```
config_changes, source_snapshots_changed (bool), divergences, clamp_attributions,
insufficient, finding_deltas (new|cleared|persisting, matched on rule_id + sorted subjects),
expected_source ("baseline_run" | "sim"), evidence (sim_control, only with a twin)
```
Same-robot only (`ValueError → 422 robot_mismatch`). `findings(run)` (`:93-147`) is the deterministic "Possible stall" card: current ≥ snapshotted `stall_current_a` while position still under a different command; else an `insufficient` reason. `narration.narrate` is one optional metered LLM batch (`_MAX_BATCH = 32`) forbidden from adding numbers/identifiers (`_UNSAFE_PROSE`).

**Playback.** Client-only: `playbackTimes` = sorted distinct ms offsets of packet/sensor timestamps; `playbackFrame` returns rows at exactly that offset — "no interpolation, stale values or synthesized media" (playback.ts:24-46); `RunPlayback` = range slider + table (≤200 rows) + sensor references (≤100) with `SensorPreview`. No server playback, no re-injection into live rings.

**UI compare.** `RunEvidence` "Choose a baseline" select → `compareRuns(projectId, baselineId, candidateId)` WITHOUT `sim_result_id` (RunEvidence.tsx:91-109, 129) although `runsApi.compareRuns` accepts it (`runsApi.ts:205-213`).

**SOL.** `get_run` reads `run_store.summary(record(...))` — "the summary only; the packets … cannot fit the cap" (finding_tools.py:77-86, 144-154). No tool lists runs, loads a manifest, marks a baseline or calls `compare`: absent.

---


#### G3.3 LB-06 packet (from Q14)
Status: absent (alignment) / exists (two-clock packet)
Where: `packages/api/src/solus_api/graph/packet.py` (153); `graph/codec.py` (188); `livebench/src/livebench/telemetry/normalize.py` (129); `livebench/src/livebench/plugins/lb06/lb06_lines.py` (81); `lb06_driver.py` (92); `plugins/feetech/feetech_driver.py:197`; `docs/contracts/telemetry-packet.md` (220); `libs/solus-telemetry/README.md` (194)
Note: No offset estimation, sync packet, NTP/PTP handling, or per-brain clock record exists anywhere (grep `clock_offset|offset_ms|clock skew|host_time|device_time|ntp|ptp|time_sync|clock sync|clock align` over livebench, graph, telemetry, libs → only `time.monotonic()` deadlines and the docstring sentence below). The design is: wall-clock `timestamp` + per-device monotonic `seq`; a board's `ts_us` since boot is accepted as-is and becomes a 1970-era `timestamp`.

**The packet model (verbatim, `graph/packet.py:65-77`):**
```python
    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(min_length=1, max_length=MAX_DEVICE_ID_LEN)
    timestamp: datetime
    values: dict[str, float]
    # Upper bounds as well as lower: a Python int is arbitrary-precision, so without `le` a
    # hostile producer could park a 4000-digit `seq` in the model that no int64 wire — and no
    # other runtime — can represent.
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1, le=MAX_SCHEMA_VERSION)
    seq: int | None = Field(default=None, ge=0, le=MAX_SEQ)
    units: dict[str, str] = Field(default_factory=dict)
```
Bounds (`packet.py:37-46`): `MAX_DEVICE_ID_LEN = 512`, `MAX_SIGNALS_PER_PACKET = 256`, `MAX_SIGNAL_NAME_LEN = 128`, `MAX_UNIT_LEN = 32`, `MAX_SAFE_INT = 2**53 - 1`, `MAX_SEQ = MAX_SAFE_INT`, `SCHEMA_VERSION = 1`. Wire: `timestamp` travels as `ts_us` (`codec.py:42 TS_KEY = "ts_us"`), decoded by `_from_epoch_us` (int only, `|raw| ≤ 2^53-1`, `codec.py:78-90`). The docstring's only clock statement (`packet.py:11-14`): "Two clocks, deliberately: `timestamp` is the wall-clock instant … while `seq` is the producer's MONOTONIC per-device counter. Real robot clocks drift and get NTP-corrected backwards; `seq` is what survives that, so consumers detect drops and reordering from `seq`, never from `timestamp` deltas."

**Contract doc `telemetry-packet.md` §2 table and §3 (verbatim):**
```
| `device_id`      | `str`, 1–512         | yes                 | Identity of the device **or topic**. Resolved against `graph_entity.external_ref`, project-scoped. |
| `timestamp`      | `datetime`, tz-aware | yes                 | Wall-clock instant of the reading. Naive datetimes are rejected.                                   |
| `values`         | `dict[str, float]`   | yes                 | Signal name → finite value. 1–256 entries, names ≤128 chars.                                       |
| `schema_version` | `int` ≥ 1            | no (default `1`)    | Wire-format version (§4).                                                                          |
| `seq`            | `int` ≥ 0 \| `None`  | no (default `None`) | Monotonic per-device counter (§3).                                                                 |
| `units`          | `dict[str, str]`     | no (default `{}`)   | Unit symbol per signal, ≤32 chars. Keys must be a subset of `values`.                              |
```
```
## 3. Two clocks, and why
`timestamp` is wall-clock; `seq` is monotonic. They are not redundant.
Windows bucket by `timestamp`, and correlating a telemetry event with a commit or a CAD edit needs
real time. But a real robot's clock drifts and gets NTP-corrected _backwards_, which reorders
samples and lands them in the wrong window. `seq` is the ordering that survives that.
**Consumers detect drops and reordering from `seq`, never from `timestamp` deltas.**
```

**The LB-06 line "parser" (`lb06_lines.py`) does not parse fields** — it is newline framing only: `LineReader.read_line()` returns one stripped line ≤ `MAX_LINE_BYTES = MAX_PACKET_BYTES + 1024` (= 64 KiB + 1 KiB), discards over-long lines, honours a monotonic deadline. `LineTransportParams {baud: 300..3_000_000 | None, timeout_s: 0.001..5.0 | None}` is the driver's params model. Field decoding happens in `normalize.packet_from_json_payload(topic, log_time_ns, line, trusted_identity=True)` (`lb06_driver.py:59-61`): if the JSON has key `ts_us` → `_decode_lb06` → `codec.decode_json` (the packet's own `ts_us` is used VERBATIM as `timestamp`; `log_time_ns` from the host clock is ignored); otherwise plain JSON is flattened and stamped with the host `log_time_ns`. The driver pins `device_id` to the channel's `device_ref` and drops relabelled packets.

**Consequence for a bare board:** the Arduino emitter writes `ts_us = micros()` (uint32 since boot, wraps every ~71.6 min, `SolusTelemetry.h:11-13`); the README says "Solus orders samples by `seq`, so this is accepted — it is simply not wall-clock time." Code: such packets land with `timestamp ≈ 1970-01-01 + micros`, and `graph/telemetry.py` windows (`get_telemetry`, lines 295-305) bucket by `timestamp`, so a boot-relative board and a host-clock driver (e.g. `feetech_driver.py:197 timestamp=datetime.now(tz=UTC)`) cannot be placed on one time axis. No code reconciles them. `seq` is produced per device by `Emitter`/`SolusTelemetry` and by the feetech driver (`feetech_driver.py:220`); there is no cross-device seq relation.

---


#### G3.4 Observers, event types, BenchEventRing (from Q29)
Status: exists
Where: livebench/src/livebench/anomaly/observers.py (196), livebench/src/livebench/anomaly/session.py (70), packages/api/src/solus_api/livebench/bench_router.py (737), livebench/sessions.py (516), livebench/findings/window_evaluator.py (765), livebench/findings/rules/__init__.py (26), graph/findings.py (582), main.py (691)
Note: The three `anomaly/observers.py` detectors never write a graph finding; only the CUSUM one is instantiated in the API path, and it only feeds the in-memory event ring. Graph findings on the Bench are written by `WindowEvaluator._raise` → `graph.findings.raise_finding` from the live-signal RULES (`SIGNAL_RULES`), with `source="observer"`; the evaluator then back-writes markers carrying `finding_id` into the same ring.

**Observer list and event types (verbatim, observers.py:23-36):**
```python
ObserverKind = Literal["threshold_breach", "change_point", "stream_gap"]


class ObserverEvent(BaseModel):
    """One detected anomaly, with enough context to route into the telemetry/error path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObserverKind
    device_id: str
    signal: str
    at: datetime
    value: float | None = None
    detail: dict[str, Any] = {}
```
| Observer | Fires | detail keys | Wired in API path? |
|---|---|---|---|
| `ThresholdObserver(signal, low, high, smoothing=1)` (`:39-90`) | `threshold_breach` when the median of the last `smoothing` samples leaves `[low, high]`; one event per excursion | `smoothed, low, high, smoothing` | **No** — never constructed outside tests |
| `CusumObserver(signal, baseline_samples=50, slack=0.5, decision=5.0)` (`:93-155`) | `change_point` two-sided CUSUM after learning mean/std from 50 samples; relearns after firing | `direction, baseline_mean, baseline_std, decision` | **Yes** via `SessionObservers` |
| `GapWatchdog(timeout_seconds)` (`:158-196`) | `stream_gap` from `tick(now)` when a streamed (device, signal) is silent past the timeout | `last_seen_seconds, timeout` | **No** in the API (the evaluator's `stream_gap` rule reimplements the semantics, sensor_rules.py:18-24) |

`SessionObservers` (session.py:221-266): one `CusumObserver` per `(device_id, signal)`, `max_signals=128` (≤256), resets on unit change, drops out-of-order by `seq` then timestamp, swallows arithmetic overflow per signal, returns `model_dump(mode="json")` dicts. Created per session by `livebench.local.session_observers` (local.py:567-571) ← `SessionManager(observer_factory=…)` (main.py:494) → `tap` calls `observer.add(packet)[:128]` → `event_sink` (sessions.py:368-374) → `BenchEventRing.append(project_id, ObserverEventIn.model_validate(event))` (main.py:495-497).

**BenchEventRing (verbatim, bench_router.py:110-139):**
```python
class BenchEventRing:
    """Bounded per-project observer-event ring. In-memory, like the LNK-06 buffer:
    live ephemeral values only — durable history is out of scope by decision."""

    def __init__(self, capacity: int = MAX_EVENTS_KEPT) -> None:
        self._events: dict[uuid.UUID, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=capacity)
        )

    def append(
        self, project_id: uuid.UUID, event: ObserverEventIn, *, finding_id: uuid.UUID | None = None
    ) -> None:
        """`finding_id` (SOLUSDEV-321 P2-T3) is attached here, to the ring's own record, by the
        server that raised the finding: `ObserverEventIn` has no such field, so an ingested event
        can never carry one, and `recent` hands out only the ids attached here."""
        record = event.model_dump(mode="json")
        if finding_id is not None:
            record["finding_id"] = str(finding_id)
        self._events[project_id].append(record)

    def recent(self, project_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        ring = self._events.get(project_id)
        if not ring:
            return []
        return list(ring)[-limit:]
```
`MAX_EVENTS_KEPT = 512` (`:64`). Read by `GET /bench/events?limit≤512` (`:206-212`); desktop decodes ≤100 with optional UUID `finding_id` (signalAnomalies.ts:30-53). External producers may POST events of any of the three kinds (`TelemetryBatchIn.events`, `:103-107`).

**Graph finding call path (trace):**
1. `main.py:502-511` builds a `WindowEvaluator(telemetry_buffer, sessionmaker, envelope_cache, SIGNAL_RULES, app.state.bench_events, on_raised=narrator.bound(view), artifacts=…, cpu_budget_ms, cpu_budget_ms_per_part)` per robot session.
2. `SessionManager._start_evaluator` (sessions.py:396-407) → `WindowEvaluator.start(view)` (window_evaluator.py:348-356): a task ticking every `tick_seconds = 1.0`.
3. Each tick reads new samples per part by event time, loads envelopes, evaluates `rules.SIGNAL_RULES` (rules/__init__.py:19-26: `COMMAND_RULES, TRACKING_RULES, BODY_RULES, ELECTRICAL_RULES, SENSOR_RULES, PREDICTION_RULES`) under a CPU budget.
4. `WindowEvaluator._raise` (`:684-705`) builds `FindingSpec(rule_id=hit.rule_id, severity, source="observer", headline, subjects, evidence=_finding_evidence(...), matrix_cell, domain, bucket=str(session_id))` and calls **`await raise_finding(db, project_id, spec)`** (`:704`) — the writer is **`solus_api.graph.findings.raise_finding`** (graph/findings.py:316-395): upsert on `canonical_key = sha1(project|rule_id|sorted subjects|bucket)`, `kind=finding`, attrs `{rule_id, severity, source, status, headline, explanation, detail, evidence, count, first_seen, last_seen, matrix_cell, subjects}`, `count++`/`last_seen` on re-raise, `observed` edges to each subject. Evidence always carries `robot_id` and `session_id` (`_finding_evidence`, `:260-275`).
5. `_write_missing` sets the robot's `attrs.missing_signals` (`:717-728`); `_mark` appends `ObserverEventIn(kind="stream_gap"|"threshold_breach", detail={"rule_id"})` per streamed channel with `finding_id` into the ring at a finding's first raise this session (`:738-755`); `_tell` hands ids to the narrator (`:757-765`).

So: **anomaly observers → ring only; rules via evaluator → `raise_finding`.** Other `raise_finding` producers (checkers via `finding_from_warning`, run compare, SOL, simulation; `FindingSource` findings.py:45) are outside the Bench session path.

---


### G4 — Isaac/Gazebo tool definitions (verbatim)

#### G4.1 SOL-visible Isaac tools — `ToolDescriptor` fields as built by `IsaacTool.__init__` (`isaac_tools.py:251-269`); params = `PUBLIC_MODELS[name].model_json_schema()`, printed with `uv run python` on HEAD
```
=== isaac.probe  timeout_seconds=20  requires_confirmation=False  files_errors=False
description: Observe installed Isaac runtime readiness without starting it.
{"additionalProperties": false, "properties": {}, "title": "Empty", "type": "object"}
=== isaac.status  timeout_seconds=20  requires_confirmation=False  files_errors=False
description: Read this project’s owned Isaac session and scene state.
{"additionalProperties": false, "properties": {}, "title": "Empty", "type": "object"}
=== isaac.start  timeout_seconds=195  requires_confirmation=True  files_errors=True
description: Start one owned headless Isaac session; no scene is loaded implicitly.
{"additionalProperties": false, "properties": {"dry_run": {"default": false, "title": "Dry Run", "type": "boolean"}}, "title": "Start", "type": "object"}
=== isaac.stop  timeout_seconds=25  requires_confirmation=True  files_errors=True
description: Stop the exact owned Isaac session.
{"additionalProperties": false, "properties": {"dry_run": {"default": false, "title": "Dry Run", "type": "boolean"}, "session_id": {"title": "Session Id", "type": "string"}}, "required": ["session_id"], "title": "Session", "type": "object"}
=== isaac.load_model  timeout_seconds=165  requires_confirmation=True  files_errors=True
description: Load the explicit graph-bound model asset into the owned scene.
{"additionalProperties": false, "properties": {"dry_run": {"default": false, "title": "Dry Run", "type": "boolean"}, "model_entity_id": {"title": "Model Entity Id", "type": "string"}, "session_id": {"title": "Session Id", "type": "string"}}, "required": ["session_id", "model_entity_id"], "title": "Load", "type": "object"}
=== isaac.set_joint_limits  timeout_seconds=25  requires_confirmation=True  files_errors=True
description: Set the simulated limits of one graph-bound joint in radians.
{"additionalProperties": false, "properties": {"dry_run": {"default": false, "title": "Dry Run", "type": "boolean"}, "joint_entity_id": {"title": "Joint Entity Id", "type": "string"}, "lower": {"title": "Lower", "type": "number"}, "session_id": {"title": "Session Id", "type": "string"}, "upper": {"title": "Upper", "type": "number"}}, "required": ["session_id", "joint_entity_id", "lower", "upper"], "title": "JointLimits", "type": "object"}
=== isaac.set_sensor_pose  timeout_seconds=25  requires_confirmation=True  files_errors=True
description: Set one graph-bound contact sensor pose in parent-link metres and wxyz quaternion.
{"additionalProperties": false, "properties": {"dry_run": {"default": false, "title": "Dry Run", "type": "boolean"}, "orientation_wxyz": {"items": {"type": "number"}, "maxItems": 4, "minItems": 4, "title": "Orientation Wxyz", "type": "array"}, "sensor_entity_id": {"title": "Sensor Entity Id", "type": "string"}, "session_id": {"title": "Session Id", "type": "string"}, "translation_m": {"items": {"ge": -10, "le": 10, "type": "number"}, "maxItems": 3, "minItems": 3, "title": "Translation M", "type": "array"}}, "required": ["session_id", "sensor_entity_id", "translation_m", "orientation_wxyz"], "title": "SensorPose", "type": "object"}
=== isaac.run_routine  timeout_seconds=55  requires_confirmation=True  files_errors=True
description: Run a bounded joint trajectory with the selected model’s explicit ranges and waypoints.
{"$defs": {"Position": {"additionalProperties": false, "properties": {"joint_entity_id": {"title": "Joint Entity Id", "type": "string"}, "position_rad": {"title": "Position Rad", "type": "number"}}, "required": ["joint_entity_id", "position_rad"], "title": "Position", "type": "object"}, "Range": {"additionalProperties": false, "properties": {"joint_entity_id": {"title": "Joint Entity Id", "type": "string"}, "lower": {"title": "Lower", "type": "number"}, "upper": {"title": "Upper", "type": "number"}}, "required": ["joint_entity_id", "lower", "upper"], "title": "Range", "type": "object"}, "Waypoint": {"additionalProperties": false, "properties": {"positions": {"items": {"$ref": "#/$defs/Position"}, "maxItems": 16, "minItems": 1, "title": "Positions", "type": "array"}}, "required": ["positions"], "title": "Waypoint", "type": "object"}}, "additionalProperties": false, "properties": {"dry_run": {"default": false, "title": "Dry Run", "type": "boolean"}, "duration_s": {"ge": 1, "le": 30, "title": "Duration S", "type": "number"}, "joints": {"items": {"$ref": "#/$defs/Range"}, "maxItems": 16, "minItems": 1, "title": "Joints", "type": "array"}, "routine": {"const": "joint_trajectory", "title": "Routine", "type": "string"}, "session_id": {"title": "Session Id", "type": "string"}, "waypoints": {"items": {"$ref": "#/$defs/Waypoint"}, "maxItems": 16, "minItems": 1, "title": "Waypoints", "type": "array"}}, "required": ["routine", "duration_s", "joints", "waypoints", "session_id"], "title": "Routine", "type": "object"}
```

#### G4.2 `isaac_tools.py:31-55` — timeouts and descriptions (verbatim)
```python
_DIGEST = re.compile(r"[0-9a-f]{64}")
_TIMEOUTS = {
    "probe": 20,
    "status": 20,
    "start": 195,
    "stop": 25,
    "load_model": 165,
    "set_joint_limits": 25,
    "set_sensor_pose": 25,
    "run_routine": 55,
}
_DESCRIPTIONS = {
    "probe": "Observe installed Isaac runtime readiness without starting it.",
    "status": "Read this project’s owned Isaac session and scene state.",
    "start": "Start one owned headless Isaac session; no scene is loaded implicitly.",
    "stop": "Stop the exact owned Isaac session.",
    "load_model": "Load the explicit graph-bound model asset into the owned scene.",
    "set_joint_limits": "Set the simulated limits of one graph-bound joint in radians.",
    "set_sensor_pose": (
        "Set one graph-bound contact sensor pose in parent-link metres and wxyz quaternion."
    ),
    "run_routine": (
        "Run a bounded joint trajectory with the selected model’s explicit ranges and waypoints."
    ),
}
```

#### G4.3 `isaac_tools.py:251-269` — descriptor construction (verbatim)
```python
class IsaacTool:
    """The sole public wrapper; its raw bridge capability never enters the registry."""

    def __init__(self, name: str, raw: Mapping[str, Tool], resolver: _Resolver) -> None:
        self.name = name
        self.raw = raw
        self.resolver = resolver
        self.requires_complete_preview = name not in ("probe", "status")
        self._ticket: ContextVar[_Ticket | None] = ContextVar("isaac_approval", default=None)
        self._descriptor = ToolDescriptor(
            name="isaac." + name,
            description=_DESCRIPTIONS[name],
            params=PUBLIC_MODELS[name].model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=self.requires_complete_preview,
            consent_summary=_DESCRIPTIONS[name] if self.requires_complete_preview else None,
            timeout_seconds=_TIMEOUTS[name],
            files_errors=self.requires_complete_preview,
        )
```

#### G4.4 `isaac_models.py:193-246` — SOL-side argument models (verbatim)
```python
class Empty(Strict):
    pass


class Start(Strict):
    dry_run: bool = False


class Session(Start):
    session_id: EntityId


class Load(Session):
    model_entity_id: EntityId


class JointLimits(Session):
    joint_entity_id: EntityId
    lower: Number
    upper: Number

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError("ordered limits required")
        return self


class SensorPose(Session):
    sensor_entity_id: EntityId
    translation_m: Vec3
    orientation_wxyz: Quat

    @model_validator(mode="after")
    def quaternion(self) -> Self:
        if abs(math.hypot(*self.orientation_wxyz) - 1) > 1e-6:
            raise ValueError("unit quaternion required")
        return self


class Routine(Session, RoutineSpec):
    pass


PUBLIC_MODELS: dict[str, type[Strict]] = {
    "probe": Empty,
    "status": Empty,
    "start": Start,
    "stop": Session,
    "load_model": Load,
    "set_joint_limits": JointLimits,
    "set_sensor_pose": SensorPose,
    "run_routine": Routine,
}
```

#### G4.5 Fork-side MCP tool specs — `integrations/mcp/isaac/solus/server.py:26-64` (verbatim) and `tool_specs()` output printed with `uv run python` on HEAD
```python
class Empty(Strict):
    pass


class Start(Strict):
    dry_run: bool


class Stop(Start):
    session_id: EntityId


class LoadCall(Load):
    session_id: EntityId


class LimitsCall(Limits):
    session_id: EntityId


class PoseCall(Pose):
    session_id: EntityId


class RunCall(Run):
    session_id: EntityId


SCHEMAS: dict[str, type[Strict]] = {
    "probe": Empty,
    "status": Empty,
    "start": Start,
    "stop": Stop,
    "load_model": LoadCall,
    "set_joint_limits": LimitsCall,
    "set_sensor_pose": PoseCall,
    "run_routine": RunCall,
}
DEADLINES = {"load_model": 150, "set_joint_limits": 10, "set_sensor_pose": 10, "run_routine": 40}
```
```
=== probe | Owned Isaac probe. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {}, "title": "Empty", "type": "object"}
=== status | Owned Isaac status. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {}, "title": "Empty", "type": "object"}
=== start | Owned Isaac start. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {"dry_run": {"title": "Dry Run", "type": "boolean"}}, "required": ["dry_run"], "title": "Start", "type": "object"}
=== stop | Owned Isaac stop. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {"dry_run": {"title": "Dry Run", "type": "boolean"}, "session_id": {"title": "Session Id", "type": "string"}}, "required": ["dry_run", "session_id"], "title": "Stop", "type": "object"}
=== load_model | Owned Isaac load model. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {"dry_run": {"title": "Dry Run", "type": "boolean"}, "expected_scene_generation": {"maximum": 1000, "minimum": 0, "title": "Expected Scene Generation", "type": "integer"}, "graph_digest": {"title": "Graph Digest", "type": "string"}, "model_entity_id": {"title": "Model Entity Id", "type": "string"}, "resolved_model": {"additionalProperties": false, "properties": {"asset": {"additionalProperties": false, "properties": {"files": {"additionalProperties": {"type": "string"}, "maxProperties": 32, "minProperties": 1, "title": "Files", "type": "object"}, "sha256": {"pattern": "^[0-9a-f]{64}$", "title": "Sha256", "type": "string"}, "urdf_path": {"maxLength": 256, "minLength": 1, "title": "Urdf Path", "type": "string"}}, "required": ["urdf_path", "files", "sha256"], "title": "Asset", "type": "object"}, "joints": {"items": {"additionalProperties": false, "properties": {"child_link_entity_id": {"title": "Child Link Entity Id", "type": "string"}, "entity_id": {"title": "Entity Id", "type": "string"}, "lower_rad": {"ge": -100, "le": 100, "title": "Lower Rad", "type": "number"}, "name": {"pattern": "^[A-Za-z_][A-Za-z0-9_]{0,63}$", "title": "Name", "type": "string"}, "parent_link_entity_id": {"title": "Parent Link Entity Id", "type": "string"}, "upper_rad": {"ge": -100, "le": 100, "title": "Upper Rad", "type": "number"}}, "required": ["entity_id", "name", "parent_link_entity_id", "child_link_entity_id", "lower_rad", "upper_rad"], "title": "Joint", "type": "object"}, "maxItems": 16, "minItems": 1, "title": "Joints", "type": "array"}, "links": {"items": {"additionalProperties": false, "properties": {"entity_id": {"title": "Entity Id", "type": "string"}, "name": {"pattern": "^[A-Za-z_][A-Za-z0-9_]{0,63}$", "title": "Name", "type": "string"}}, "required": ["entity_id", "name"], "title": "Binding", "type": "object"}, "maxItems": 32, "minItems": 2, "title": "Links", "type": "array"}, "schema_version": {"const": 2, "title": "Schema Version", "type": "integer"}, "sensors": {"items": {"additionalProperties": false, "properties": {"entity_id": {"title": "Entity Id", "type": "string"}, "kind": {"const": "contact", "title": "Kind", "type": "string"}, "orientation_wxyz": {"items": {"type": "number"}, "maxItems": 4, "minItems": 4, "title": "Orientation Wxyz", "type": "array"}, "parent_link_entity_id": {"title": "Parent Link Entity Id", "type": "string"}, "radius_m": {"ge": 0.001, "le": 0.05, "title": "Radius M", "type": "number"}, "translation_m": {"items": {"ge": -10, "le": 10, "type": "number"}, "maxItems": 3, "minItems": 3, "title": "Translation M", "type": "array"}}, "required": ["entity_id", "parent_link_entity_id", "kind", "translation_m", "orientation_wxyz", "radius_m"], "title": "Sensor", "type": "object"}, "maxItems": 4, "title": "Sensors", "type": "array"}}, "required": ["schema_version", "asset", "links", "joints"], "title": "Model", "type": "object"}, "session_id": {"title": "Session Id", "type": "string"}}, "required": ["graph_digest", "expected_scene_generation", "dry_run", "model_entity_id", "resolved_model", "session_id"], "title": "LoadCall", "type": "object"}
=== set_joint_limits | Owned Isaac set joint limits. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {"dry_run": {"title": "Dry Run", "type": "boolean"}, "entity_id": {"title": "Entity Id", "type": "string"}, "expected_scene_generation": {"maximum": 1000, "minimum": 0, "title": "Expected Scene Generation", "type": "integer"}, "graph_digest": {"title": "Graph Digest", "type": "string"}, "lower": {"title": "Lower", "type": "number"}, "session_id": {"title": "Session Id", "type": "string"}, "upper": {"title": "Upper", "type": "number"}}, "required": ["graph_digest", "expected_scene_generation", "dry_run", "entity_id", "lower", "upper", "session_id"], "title": "LimitsCall", "type": "object"}
=== set_sensor_pose | Owned Isaac set sensor pose. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {"dry_run": {"title": "Dry Run", "type": "boolean"}, "entity_id": {"title": "Entity Id", "type": "string"}, "expected_scene_generation": {"maximum": 1000, "minimum": 0, "title": "Expected Scene Generation", "type": "integer"}, "graph_digest": {"title": "Graph Digest", "type": "string"}, "orientation_wxyz": {"items": {"type": "number"}, "maxItems": 4, "minItems": 4, "title": "Orientation Wxyz", "type": "array"}, "session_id": {"title": "Session Id", "type": "string"}, "translation_m": {"items": {"ge": -10, "le": 10, "type": "number"}, "maxItems": 3, "minItems": 3, "title": "Translation M", "type": "array"}}, "required": ["graph_digest", "expected_scene_generation", "dry_run", "entity_id", "translation_m", "orientation_wxyz", "session_id"], "title": "PoseCall", "type": "object"}
=== run_routine | Owned Isaac run routine. Graph arguments are supplied only by the authenticated Solus adapter.
{"additionalProperties": false, "properties": {"dry_run": {"title": "Dry Run", "type": "boolean"}, "expected_scene_generation": {"maximum": 1000, "minimum": 0, "title": "Expected Scene Generation", "type": "integer"}, "graph_digest": {"title": "Graph Digest", "type": "string"}, "routine_spec": {"additionalProperties": false, "properties": {"duration_s": {"ge": 1, "le": 30, "title": "Duration S", "type": "number"}, "joints": {"items": {"additionalProperties": false, "properties": {"joint_entity_id": {"title": "Joint Entity Id", "type": "string"}, "lower": {"title": "Lower", "type": "number"}, "upper": {"title": "Upper", "type": "number"}}, "required": ["joint_entity_id", "lower", "upper"], "title": "Range", "type": "object"}, "maxItems": 16, "minItems": 1, "title": "Joints", "type": "array"}, "routine": {"const": "joint_trajectory", "title": "Routine", "type": "string"}, "waypoints": {"items": {"additionalProperties": false, "properties": {"positions": {"items": {"additionalProperties": false, "properties": {"joint_entity_id": {"title": "Joint Entity Id", "type": "string"}, "position_rad": {"title": "Position Rad", "type": "number"}}, "required": ["joint_entity_id", "position_rad"], "title": "Position", "type": "object"}, "maxItems": 16, "minItems": 1, "title": "Positions", "type": "array"}}, "required": ["positions"], "title": "Waypoint", "type": "object"}, "maxItems": 16, "minItems": 1, "title": "Waypoints", "type": "array"}}, "required": ["routine", "duration_s", "joints", "waypoints"], "title": "Routine", "type": "object"}, "session_id": {"title": "Session Id", "type": "string"}}, "required": ["graph_digest", "expected_scene_generation", "dry_run", "routine_spec", "session_id"], "title": "RunCall", "type": "object"}
```

#### G4.6 Fork-side native action models — `integrations/mcp/isaac/solus/actions.py:32-64` (verbatim)
```python
class State(Strict):
    graph_digest: str
    expected_scene_generation: Annotated[int, Field(ge=0, le=1000)]
    dry_run: bool


class Load(State):
    model_entity_id: EntityId
    resolved_model: Model


class Limits(State):
    entity_id: EntityId
    lower: Number
    upper: Number


class Pose(State):
    entity_id: EntityId
    translation_m: Vec3
    orientation_wxyz: Quat


class Run(State):
    routine_spec: Routine


SCHEMAS: dict[str, type[State]] = {
    "load_model": Load,
    "set_joint_limits": Limits,
    "set_sensor_pose": Pose,
    "run_routine": Run,
}
```

#### G4.7 `integrations/mcp/isaac/allowlist.yaml` (verbatim, 38 lines)
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
```

#### G4.8 `integrations/mcp/isaac/bin/launch` (verbatim, 13 lines)
```sh
#!/bin/sh
# Solus-owned fixed launcher. Dependencies are materialized only at install time.
set -eu
PATH=/usr/bin:/bin
export PATH
BIN_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FORK_DIR=$(CDPATH= cd -- "$BIN_DIR/.." && pwd)
PYTHON="${SOLUS_MCP_PYTHON:-}"
if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then exit 78; fi
WORKSPACE="${SOLUS_MCP_WORKSPACE:-}"
if [ -z "$WORKSPACE" ]; then exit 78; fi
cd -- "$WORKSPACE"
exec /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 SOLUS_MCP_WORKSPACE="$WORKSPACE" SOLUS_ISAAC_RUNTIME="${SOLUS_ISAAC_RUNTIME:-}" "$PYTHON" "$FORK_DIR/solus/server.py"
```

#### G4.9 Fork worker launch argv and Isaac imports — `controller.py:167-190`, `worker.py:64-69`, `scene.py:36-63` (verbatim)
```python
                worker = Path(__file__).with_name("worker.py").resolve()
                argv = [
                    str(self.runtime / "python.sh"),
                    str(worker),
                    str(request_read),
                    str(reply_write),
                    self.session,
                    str(workspace_fd),
                    str(self.runtime),
                    "--/app/extensions/registryEnabled=false",
                    "--/telemetry/enableNVDF=false",
                    "--/telemetry/enableSentry=false",
                    "--/telemetry/enableAnonymousData=false",
                ]
                self.process = subprocess.Popen(  # noqa: S603 — fixed runtime/worker and owned FDs
                    argv,
                    cwd=private,
                    env=child_environment(private),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    pass_fds=(request_read, reply_write, workspace_fd),
                    start_new_session=True,
                )
# --- worker.py:64-69
    from isaacsim import SimulationApp

    app = SimulationApp(
        {"headless": True, "disable_viewport_updates": True},
        experience=str(runtime / "apps/isaacsim.exp.base.python.kit"),
    )
# --- scene.py:36-63
        from isaacsim.core.utils.extensions import enable_extension

        enable_extension("isaacsim.asset.importer.urdf")
        enable_extension("isaacsim.sensors.experimental.physics")
        import omni.usd
        from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig
        from isaacsim.core.api import SimulationContext
        from isaacsim.core.experimental.prims import Articulation
        from isaacsim.sensors.experimental.physics import Contact, ContactSensor
        from pxr import Gf, UsdGeom, UsdPhysics

        if self.sim is not None:
            self.sim.stop()
        imported = URDFImporter(
            URDFImporterConfig(
                urdf_path=str(asset_dir / model.asset.urdf_path),
                usd_path=str(output_dir),
                fix_base=True,
                merge_fixed_joints=False,
                run_asset_transformer=False,
                joint_target_type="position",
                joint_drive_type="force",
                collision_type="Convex Decomposition",
                override_joint_stiffness=400.0,
                override_joint_damping=20.0,
            )
        ).import_urdf()
        omni.usd.get_context().open_stage(imported)
```

#### G4.10 Cloud gating lists — `bridge/allowlist.py:42-65`, `agent/execution_policy.py:34-43`, `agent/runtime.py:551-554, 649-675` (verbatim)
```python
_COMPLETE_PREVIEW_TOOLS: Final = frozenset(
    {
        "kicad.create_schematic",
        "kicad.add_symbol",
        "kicad.add_wire",
        "kicad.add_net_label",
        "kicad.mark_no_connect",
        "kicad.set_symbol_property",
        "code.git_commit",
        "code.git_push",
        "code.arduino_prepare",
        "code.arduino_compile",
        "code.arduino_upload",
        "isaac.start",
        "isaac.stop",
        "isaac.load_model",
        "isaac.set_joint_limits",
        "isaac.set_sensor_pose",
        "isaac.run_routine",
    }
)
_DRY_RUN_TOOLS: Final = _COMPLETE_PREVIEW_TOOLS | frozenset(
    {"machine.run_command", "machine.install_package", "machine.create_environment"}
)
# --- execution_policy.py:34-43
_ISAAC = frozenset(
    {
        "isaac.start",
        "isaac.stop",
        "isaac.load_model",
        "isaac.set_joint_limits",
        "isaac.set_sensor_pose",
        "isaac.run_routine",
    }
)
# --- runtime.py:551-554
        # Internal simulator inputs carry resolved graph data. Only the owned
        # graph adapter may expose Isaac operations to SOL.
        if spec.server == "isaac" or spec.descriptor.name.startswith("isaac."):
            continue
# --- runtime.py:649-675
def _owned_isaac_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    bridge: "BridgeSessionRegistry",
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    call_cap_bytes: int,
) -> list["Tool"]:
    from solus_api.agent.tools.isaac_tools import build_isaac_tools
    from solus_api.bridge.tool import BridgeTool

    session = bridge.get(user_id, team_id, project_id)
    if session is None:
        return []
    raw = {
        spec.descriptor.name: BridgeTool(
            descriptor=spec.descriptor,
            sessions=bridge,
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
            call_cap_bytes=call_cap_bytes,
        )
        for spec in session.inventory
        if spec.server == "isaac" and spec.descriptor.name.startswith("isaac.")
    }
    return build_isaac_tools(session_factory, project_id, raw)
```

#### G4.11 Gazebo — there is NO tool/MCP definition. The only Gazebo code: `livebench/src/livebench/sim/gazebo_source.py:33-139` (verbatim), `GazeboSimConnection` (`connections.py:48-66`), `local.open_gazebo` (`local.py:290-294`)
```python
class GazeboNotAvailableError(RuntimeError):
    """The `gz` CLI is not installed — the Gazebo connector cannot run on this machine."""


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


async def packets_from_json_lines(
    topic: str,
    lines: AsyncIterator[bytes],
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> AsyncIterator[TelemetryPacket]:
    """One `gz topic --json-output` line → one packet; malformed lines are skipped."""
    async for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        stamp = clock()
        log_time_ns = int(stamp.timestamp() * _US_PER_S) * _NS_PER_US
        packet = packet_from_json_payload(topic, log_time_ns, stripped)
        if packet is None:
            logger.debug("skipping undecodable gz line on %s", topic)
            continue
        yield packet


class GazeboTopicSource:
    """Live source: one pinned `gz topic -e --json-output` subprocess per topic."""

    def __init__(self, topics: list[str], *, gz_binary: str | None = None) -> None:
        if not topics:
            raise ValueError("at least one topic required")
        for topic in topics:
            if topic.startswith("-"):
                raise ValueError(f"topic may not start with '-': {topic!r}")
        binary = gz_binary or shutil.which("gz")
        if binary is None:
            raise GazeboNotAvailableError(
                "`gz` CLI not found — install Gazebo (ros-jazzy-ros-gz) to stream from it"
            )
        self._binary = binary
        self._topics = list(topics)
        self._procs: list[asyncio.subprocess.Process] = []
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        queue: asyncio.Queue[TelemetryPacket | None] = asyncio.Queue()
        pumps = [asyncio.create_task(self._pump_topic(topic, queue)) for topic in self._topics]
        pending = len(pumps)
        try:
            while pending and not self._closed:
                packet = await queue.get()
                if packet is None:
                    pending -= 1
                    continue
                yield packet
        finally:
            for task in pumps:
                task.cancel()
            # Join the cancelled pumps so no "Task was destroyed but pending" leaks
            # (matches PacketStreamLiveConnection.aclose's discipline).
            await asyncio.gather(*pumps, return_exceptions=True)
            await self.aclose()

    async def _pump_topic(self, topic: str, queue: asyncio.Queue[TelemetryPacket | None]) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "topic",
                "-e",
                "-t",
                topic,
                "--json-output",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._procs.append(proc)
            assert proc.stdout is not None

            async def stdout_lines() -> AsyncIterator[bytes]:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    yield raw

            async for packet in packets_from_json_lines(topic, stdout_lines()):
                await queue.put(packet)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("gz topic pump for %s died", topic)
        finally:
            await queue.put(None)

    async def aclose(self) -> None:
        self._closed = True
        for proc in self._procs:
            if proc.returncode is None:
                proc.terminate()
                try:
                    # Reap the child; escalate to SIGKILL if it ignores SIGTERM.
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        self._procs.clear()
# --- connections.py:48-66
class GazeboSimConnection(PacketStreamLiveConnection):
    """Gazebo topics → windowed telemetry, via the pinned `gz` CLI subprocess.

    Raises `GazeboNotAvailableError` at construction when the CLI is absent (unless
    a `source` is injected — the fixture/test path, and any future gz-transport
    binding)."""

    provider: ClassVar[str] = "gazebo"

    def __init__(
        self,
        topics: list[str] | None = None,
        *,
        source: PacketSource | None = None,
        project_id: UUID | None = None,
    ) -> None:
        if source is None:
            source = GazeboTopicSource(topics or [])
        super().__init__(source=source, project_id=project_id)
# --- local.py:290-294
async def open_gazebo(topics: list[str], *, project_id: UUID) -> PacketStreamLiveConnection:
    """A Gazebo topic connection; raises `GazeboNotAvailableError` when gz is absent."""
    from livebench.sim.connections import GazeboSimConnection

    return GazeboSimConnection(topics, project_id=project_id)
```

#### G4.12 Isaac read-only script entry — `livebench/src/livebench/sim/isaac_direct.py:141-181` (verbatim; human-run under Isaac python, not a tool)
```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--scene", default=None, help="USD stage to open (omit to use the current stage)"
    )
    parser.add_argument("--scene-name", default="isaac", help="device_id prefix")
    parser.add_argument("--sample-hz", type=float, default=DEFAULT_SAMPLE_HZ)
    parser.add_argument("--duration", type=float, default=300.0)
    args = parser.parse_args(argv)

    token = os.environ.get("SOLUS_TOKEN")
    if not token:
        print("SOLUS_TOKEN is not set — refusing to run without credentials", file=sys.stderr)
        return 2
    _require_safe_url(args.url)

    from isaacsim import SimulationApp  # type: ignore[import-not-found]  # Isaac's python only

    sim_app = SimulationApp({"headless": True})
    try:
        import omni.usd

        if args.scene:
            omni.usd.get_context().open_stage(args.scene)
        from isaacsim.core.api import World  # type: ignore[import-not-found]

        world = World()
        world.reset()
        articulations = _find_articulations(args.scene_name)
        if not articulations:
            print("no articulations on this stage — nothing to stream", file=sys.stderr)
            return 1
        for articulation in articulations:
            articulation.initialize()

        period = 1.0 / args.sample_hz
        deadline = time.monotonic() + args.duration
        pending: list[dict[str, Any]] = []
        last_post = time.monotonic()
```

### G5 — `wc -l` of every file named in sections C to E (plus B, F, Q47), merged and de-duplicated

```
   112 apps/desktop/electron.vite.config.ts
     76 apps/desktop/package.json
   158 apps/desktop/src/main/companionEnv.ts
   503 apps/desktop/src/main/companion.ts
    14 apps/desktop/src/renderer/src/env.d.ts
    164 apps/desktop/src/renderer/src/features/bench/BenchCanvasHost.tsx
    386 apps/desktop/src/renderer/src/features/bench/bench.css
    213 apps/desktop/src/renderer/src/features/bench/BenchRealtime.tsx
    257 apps/desktop/src/renderer/src/features/bench/BenchScreen.tsx
    158 apps/desktop/src/renderer/src/features/bench/benchStream.ts
    122 apps/desktop/src/renderer/src/features/bench/ConnectDeviceModal.tsx
    570 apps/desktop/src/renderer/src/features/bench/DeviceBenchView.tsx
    105 apps/desktop/src/renderer/src/features/bench/findings/findingActions.ts
    326 apps/desktop/src/renderer/src/features/bench/findings/FindingCard.tsx
    232 apps/desktop/src/renderer/src/features/bench/findings/FindingsPane.tsx
    145 apps/desktop/src/renderer/src/features/bench/findings/useRobotFindings.ts
     12 apps/desktop/src/renderer/src/features/bench/primarySignals.ts
     41 apps/desktop/src/renderer/src/features/bench/retainedSignals.ts
     46 apps/desktop/src/renderer/src/features/bench/runs/playback.ts
    347 apps/desktop/src/renderer/src/features/bench/runs/runDecoders.ts
    313 apps/desktop/src/renderer/src/features/bench/runs/RunEvidence.tsx
     67 apps/desktop/src/renderer/src/features/bench/runs/RunNarrationPanel.tsx
     85 apps/desktop/src/renderer/src/features/bench/runs/RunPlayback.tsx
    240 apps/desktop/src/renderer/src/features/bench/runs/runsApi.ts
    373 apps/desktop/src/renderer/src/features/bench/runs/RunsView.tsx
     27 apps/desktop/src/renderer/src/features/bench/runs/sensorMedia.ts
    124 apps/desktop/src/renderer/src/features/bench/runs/SensorPreview.tsx
    124 apps/desktop/src/renderer/src/features/bench/SavedRobotConnections.tsx
    124 apps/desktop/src/renderer/src/features/bench/scene/cadApi.ts
    154 apps/desktop/src/renderer/src/features/bench/scene/CadBindings.tsx
    238 apps/desktop/src/renderer/src/features/bench/scene/CadImport.tsx
     40 apps/desktop/src/renderer/src/features/bench/scene/displayPose.ts
    149 apps/desktop/src/renderer/src/features/bench/scene/kinematics.ts
    212 apps/desktop/src/renderer/src/features/bench/scene/MappingReview.tsx
    250 apps/desktop/src/renderer/src/features/bench/scene/sceneApi.ts
    464 apps/desktop/src/renderer/src/features/bench/scene/ScenePanel.tsx
    154 apps/desktop/src/renderer/src/features/bench/scene/SceneViewer.tsx
     53 apps/desktop/src/renderer/src/features/bench/scene/types.ts
     77 apps/desktop/src/renderer/src/features/bench/scene/useSceneValues.ts
     87 apps/desktop/src/renderer/src/features/bench/signalAnomalies.ts
     62 apps/desktop/src/renderer/src/features/bench/signalUnits.ts
    301 apps/desktop/src/renderer/src/features/bench/SignalWidget.tsx
    61 apps/desktop/src/renderer/src/features/bench/useActiveBenchSessions.ts
     50 apps/desktop/src/renderer/src/features/bench/useExternalBenchDevices.ts
   128 apps/desktop/src/renderer/src/features/graph/AddSourceRows.tsx
    21 apps/desktop/src/renderer/src/features/graph/hardware/createUnassignedPart.ts
   197 apps/desktop/src/renderer/src/features/graph/hardware/DescribeNew.tsx
    31 apps/desktop/src/renderer/src/features/graph/hardware/detectedDevicesStore.ts
    67 apps/desktop/src/renderer/src/features/graph/hardware/detected.ts
   146 apps/desktop/src/renderer/src/features/graph/hardware/deviceCardRules.ts
    295 apps/desktop/src/renderer/src/features/graph/hardware/DeviceCard.tsx
     73 apps/desktop/src/renderer/src/features/graph/hardware/DevicesFound.tsx
    99 apps/desktop/src/renderer/src/features/graph/hardware/HardwareAddPanel.tsx
   210 apps/desktop/src/renderer/src/features/graph/hardware/HardwareConfigPanel.tsx
   445 apps/desktop/src/renderer/src/features/graph/hardware/HardwareSearch.tsx
   303 apps/desktop/src/renderer/src/features/graph/hardware/HardwareSourcesPanel.tsx
   120 apps/desktop/src/renderer/src/features/graph/hardware/InlineSupplierResults.tsx
     47 apps/desktop/src/renderer/src/features/graph/hardware/PendingDeviceCards.tsx
   250 apps/desktop/src/renderer/src/features/graph/hardware/UnassignedParts.tsx
    52 apps/desktop/src/renderer/src/features/graph/hardware/useDetectedDevicesFeed.ts
   458 apps/desktop/src/renderer/src/features/graph/hardware/useDeviceProposals.ts
   116 apps/desktop/src/renderer/src/features/graph/hardware/useProposalSources.ts
    42 apps/desktop/src/renderer/src/features/graph/hardware/vendorHygiene.test.ts
   365 apps/desktop/src/renderer/src/features/graph/robots/ExtractionReviewCard.tsx
   246 apps/desktop/src/renderer/src/features/graph/robots/FirmwareTelemetryOffer.tsx
     95 apps/desktop/src/renderer/src/features/graph/robots/firmwareTelemetrySnippet.ts
    320 apps/desktop/src/renderer/src/features/graph/robots/HostAttachmentCard.tsx
    186 apps/desktop/src/renderer/src/features/graph/robots/HostMirrorOffer.tsx
    142 apps/desktop/src/renderer/src/features/graph/robots/hostMirrorSnippet.ts
   114 apps/desktop/src/renderer/src/features/graph/robots/PartLinkSuggestions.tsx
    384 apps/desktop/src/renderer/src/features/graph/robots/PresenceCard.tsx
   524 apps/desktop/src/renderer/src/features/graph/robots/PresenceWiringCard.tsx
   134 apps/desktop/src/renderer/src/features/graph/robots/RobotOrphans.tsx
   243 apps/desktop/src/renderer/src/features/graph/robots/RobotTopologyGraph.tsx
   133 apps/desktop/src/renderer/src/features/graph/robots/topologyProjection.ts
   143 apps/desktop/src/renderer/src/features/graph/robots/usePhysicalRobots.tsx
   160 apps/desktop/src/renderer/src/features/graph/useWorkspaceEvents.ts
    78 apps/desktop/src/renderer/src/features/graph/WidgetRegistrationContent.tsx
   266 apps/desktop/src/renderer/src/features/graph/WorkspaceAdd.tsx
   874 apps/desktop/src/renderer/src/features/graph/WorkspaceScreen.tsx
    161 apps/desktop/src/renderer/src/features/onboarding/connectSteps.ts
    643 apps/desktop/src/renderer/src/features/onboarding/ConnectWizardModal.tsx
    151 apps/desktop/src/renderer/src/features/onboarding/edaConnect.ts
    168 apps/desktop/src/renderer/src/features/onboarding/kicadFiles.ts
     67 apps/desktop/src/renderer/src/features/sol/AutoRunRow.tsx
    332 apps/desktop/src/renderer/src/features/sol/ConfirmationCard.tsx
    359 apps/desktop/src/renderer/src/features/sol/solApi.ts
     65 apps/desktop/src/renderer/src/features/workspace/accountSteps.ts
     96 apps/desktop/src/renderer/src/features/workspace/CodeEnvironmentModal.tsx
    162 apps/desktop/src/renderer/src/features/workspace/IsaacConnectionPanel.tsx
     83 apps/desktop/src/renderer/src/features/workspace/shellStore.ts
    165 apps/desktop/src/renderer/src/features/workspace/SimulationPanel.tsx
    132 apps/desktop/src/renderer/src/features/workspace/SimulatorStartModal.tsx
   809 apps/desktop/src/renderer/src/features/workspace/WorkspaceShell.tsx
   531 apps/desktop/src/renderer/src/lib/api/hardware.ts
   1777 apps/desktop/src/renderer/src/lib/api/resources.ts
    107 apps/desktop/src/renderer/src/routes/AppRoutes.tsx
     56 apps/desktop/src/renderer/src/widgets/livebench/focusedTelemetry.ts
   239 apps/desktop/src/renderer/src/widgets/livebench/LiveBenchWidget.tsx
    111 apps/desktop/src/renderer/src/widgets/livebench/recognition/proposals.constants.ts
    159 apps/desktop/src/renderer/src/widgets/livebench/recognition/RecognitionPanel.tsx
    112 apps/desktop/src/renderer/src/widgets/livebench/telemetry.ts
     15 apps/desktop/src/renderer/src/widgets/livebench/widget.manifest.ts
   220 docs/contracts/telemetry-packet.md
     72 docs/qa/COMPLETION_isaac-cleanup.md
     52 docs/qa/COMPLETION_SOLUSDEV-121-lb01-sim-connectors.md
   139 docs/qa/COMPLETION_SOLUSDEV-248-robot-onboarding.md
   237 docs/qa/COMPLETION_SOLUSDEV-260.md
   215 docs/qa/COMPLETION_SOLUSDEV-262.md
    983 docs/qa/COMPLETION_SOLUSDEV-321-sol-checker-algorithm.md
    115 docs/qa/COMPLETION_SOLUSDEV-66-lane-h-livebench.md
     49 docs/qa/COWORK_QA_isaac-development.md
    700 docs/qa/COWORK_QA_sol-depth.md
     85 docs/qa/FINAL_NON_ONSHAPE_SOLUSDEV-261.md
  2215 docs/qa/REPO_STATE_2026-10-17.md
   212 env.example
     63 integrations/mcp/altium/allowlist.yaml
    473 integrations/mcp/autocad/allowlist.yaml
     29 integrations/mcp/brave/allowlist.yaml
     27 integrations/mcp/CLAUDE.md
    127 integrations/mcp/code/allowlist.yaml
   423 integrations/mcp/code/solus/arduino_upload.py
   493 integrations/mcp/code/solus/command_plan.py
   124 integrations/mcp/code/solus/ros2_reads.py
     40 integrations/mcp/fusion/allowlist.yaml
     38 integrations/mcp/isaac/allowlist.yaml
     13 integrations/mcp/isaac/bin/launch
    362 integrations/mcp/isaac/solus/actions.py
    106 integrations/mcp/isaac/solus/artifacts.py
    146 integrations/mcp/isaac/solus/assets.py
    323 integrations/mcp/isaac/solus/controller.py
    246 integrations/mcp/isaac/solus/models.py
     60 integrations/mcp/isaac/solus/runtime.py
    248 integrations/mcp/isaac/solus/scene.py
    204 integrations/mcp/isaac/solus/server.py
    241 integrations/mcp/isaac/solus/urdf.py
     93 integrations/mcp/isaac/solus/worker.py
     19 integrations/mcp/isaac/tests/conftest.py
     77 integrations/mcp/kicad/allowlist.yaml
     66 integrations/mcp/kicad/solus/roster.py
     22 integrations/mcp/local/allowlist.yaml
     36 integrations/mcp/machine/allowlist.yaml
    264 integrations/mcp/README.md
    338 integrations/mcp/solidworks/allowlist.yaml
   239 integrations/mcp/tests/test_vendor_hygiene.py
   101 libs/solus-telemetry/arduino/src/SolusTelemetry.cpp
    52 libs/solus-telemetry/arduino/src/SolusTelemetry.h
   149 libs/solus-telemetry/micropython/solus_telemetry.py
   143 libs/solus-telemetry/python/src/solus_telemetry/__init__.py
   194 libs/solus-telemetry/README.md
     33 livebench/pyproject.toml
    196 livebench/src/livebench/anomaly/observers.py
     70 livebench/src/livebench/anomaly/session.py
     39 livebench/src/livebench/deploy/check.py
   384 livebench/src/livebench/deploy/companion.py
   167 livebench/src/livebench/deploy/companion_remote.py
   146 livebench/src/livebench/deploy/flash.py
    82 livebench/src/livebench/deploy/fs.py
   170 livebench/src/livebench/faults.py
   304 livebench/src/livebench/hardware/bluetooth.py
   118 livebench/src/livebench/hardware/channel.py
   150 livebench/src/livebench/hardware/connection.py
   414 livebench/src/livebench/hardware/detection.py
   100 livebench/src/livebench/hardware/driver.py
    34 livebench/src/livebench/hardware/host_identity.py
   103 livebench/src/livebench/hardware/interrogator.py
   142 livebench/src/livebench/hardware/network.py
    39 livebench/src/livebench/hardware/registries.py
   499 livebench/src/livebench/hardware/repo_config.py
    176 livebench/src/livebench/hardware/topology_extractors.py
   143 livebench/src/livebench/hardware/usb_can.py
   113 livebench/src/livebench/hardware/usb_serial.py
    571 livebench/src/livebench/local.py
    80 livebench/src/livebench/plugins/arduino/arduino_flash.py
   146 livebench/src/livebench/plugins/arduino/presence_provider.py
   159 livebench/src/livebench/plugins/arduino/presence.py
   266 livebench/src/livebench/plugins/arduino/sketch_parser.py
    66 livebench/src/livebench/plugins/arduino/wiring.py
    76 livebench/src/livebench/plugins/dynamixel/dynamixel_interrogator.py
   195 livebench/src/livebench/plugins/feetech/feetech_codec.py
   278 livebench/src/livebench/plugins/feetech/feetech_driver.py
    60 livebench/src/livebench/plugins/__init__.py
    92 livebench/src/livebench/plugins/lb06/lb06_driver.py
   123 livebench/src/livebench/plugins/lb06/lb06_interrogator.py
    81 livebench/src/livebench/plugins/lb06/lb06_lines.py
   342 livebench/src/livebench/plugins/lerobot/lerobot_parser.py
    23 livebench/src/livebench/plugins/mavlink/__init__.py
    156 livebench/src/livebench/recognition/active.py
   473 livebench/src/livebench/recognition/firmware.py
   269 livebench/src/livebench/recognition/passive.py
     81 livebench/src/livebench/sim/connections.py
    139 livebench/src/livebench/sim/gazebo_source.py
    204 livebench/src/livebench/sim/isaac_direct.py
     38 livebench/src/livebench/sim/mcap_replay.py
    100 livebench/src/livebench/sim/mujoco_source.py
    465 livebench/src/livebench/sim/offscreen.py
   129 livebench/src/livebench/telemetry/normalize.py
     53 livebench/src/livebench/telemetry/observing_source.py
     83 livebench/src/livebench/telemetry/robot.py
    112 livebench/src/livebench/telemetry/serial_source.py
    143 livebench/src/livebench/telemetry/stream_live.py
    156 livebench/src/livebench/telemetry/windowing.py
     62 livebench/src/livebench/telemetry/ws_source.py
   259 livebench/tests/lb_feetech_codec_test.py
     56 livebench/tests/lb_gazebo_source_test.py
    517 livebench/tests/lb_local_test.py
   166 livebench/tests/lb_passive_test.py
   669 livebench/tests/lb_three_machines_test.py
   156 livebench/tests/lb_usb_can_test.py
    77 livebench/tests/lb_vendor_hygiene_test.py
    136 packages/api/src/solus_api/agent/command_auto.py
    783 packages/api/src/solus_api/agent/confirmations.py
    314 packages/api/src/solus_api/agent/connect_integration.py
    762 packages/api/src/solus_api/agent/context.py
    428 packages/api/src/solus_api/agent/deterministic_facts.py
    785 packages/api/src/solus_api/agent/deterministic.py
    329 packages/api/src/solus_api/agent/errors_filing.py
    227 packages/api/src/solus_api/agent/execution_policy.py
    633 packages/api/src/solus_api/agent/finding_narration.py
    422 packages/api/src/solus_api/agent/firmware_recipe.py
     96 packages/api/src/solus_api/agent/guide_toolkb_version.py
    237 packages/api/src/solus_api/agent/layers.py
     98 packages/api/src/solus_api/agent/modes.py
    470 packages/api/src/solus_api/agent/project_card.py
    600 packages/api/src/solus_api/agent/prompt.py
    186 packages/api/src/solus_api/agent/reasoning_frame.py
    795 packages/api/src/solus_api/agent/research.py
   1726 packages/api/src/solus_api/agent/runtime.py
    161 packages/api/src/solus_api/agent/sol_anchors.py
    471 packages/api/src/solus_api/agent/solus_layer.py
    792 packages/api/src/solus_api/agent/tools/apply_sim_change.py
    148 packages/api/src/solus_api/agent/tools/bench_scene.py
    269 packages/api/src/solus_api/agent/tools/builtin.py
     69 packages/api/src/solus_api/agent/tools/companion_deployment.py
     92 packages/api/src/solus_api/agent/tools/environment.py
    166 packages/api/src/solus_api/agent/tools/finding_tools.py
     65 packages/api/src/solus_api/agent/tools/firmware_presence.py
    62 packages/api/src/solus_api/agent/tools/flash_history.py
    108 packages/api/src/solus_api/agent/tools/get_entity.py
    632 packages/api/src/solus_api/agent/tools/hosted_tools.py
    246 packages/api/src/solus_api/agent/tools/isaac_models.py
    416 packages/api/src/solus_api/agent/tools/isaac_tools.py
    241 packages/api/src/solus_api/agent/tools/knowledge.py
    444 packages/api/src/solus_api/agent/tools/label_motifs.py
    237 packages/api/src/solus_api/agent/tools/machine_tools.py
    189 packages/api/src/solus_api/agent/tools/machine_writes.py
    189 packages/api/src/solus_api/agent/tools/make_diagram.py
    196 packages/api/src/solus_api/agent/tools/mcp_servers.py
    619 packages/api/src/solus_api/agent/tools/onshape_tools.py
     71 packages/api/src/solus_api/agent/tools/rail_current.py
    365 packages/api/src/solus_api/agent/tools/read_code_file.py
    564 packages/api/src/solus_api/agent/tools/read_document.py
    163 packages/api/src/solus_api/agent/tools/registry.py
    226 packages/api/src/solus_api/agent/tools/research_tool.py
    128 packages/api/src/solus_api/agent/tools/ros_live.py
    366 packages/api/src/solus_api/agent/tools/rulebook_tools.py
    155 packages/api/src/solus_api/agent/tools/search_tools.py
    147 packages/api/src/solus_api/agent/tools/shapes.py
    740 packages/api/src/solus_api/agent/tools/simulate.py
    101 packages/api/src/solus_api/agent/tools/solus_entry.py
    546 packages/api/src/solus_api/agent/tools/solus_tools.py
     85 packages/api/src/solus_api/agent/turn_budget.py
    140 packages/api/src/solus_api/agent/turn_context.py
     98 packages/api/src/solus_api/agent/turn_limits.py
    570 packages/api/src/solus_api/agent/turn_scope.py
    443 packages/api/src/solus_api/agent/vision/renderers.py
    422 packages/api/src/solus_api/agent/vision/render_view.py
    276 packages/api/src/solus_api/bridge/allowlist.py
    344 packages/api/src/solus_api/bridge/frames.py
    175 packages/api/src/solus_api/bridge/previews.py
    113 packages/api/src/solus_api/bridge/registry.py
    484 packages/api/src/solus_api/bridge/service.py
    172 packages/api/src/solus_api/bridge/tool.py
    744 packages/api/src/solus_api/checkers/matrix_runner.py
   218 packages/api/src/solus_api/connectors/code_host.py
    271 packages/api/src/solus_api/connectors/contracts.py
   573 packages/api/src/solus_api/connectors/github.py
   481 packages/api/src/solus_api/connectors/gitlab.py
    122 packages/api/src/solus_api/connectors/live.py
   766 packages/api/src/solus_api/connectors/local_folder.py
     82 packages/api/src/solus_api/connectors/onshape_confirmation.py
   1247 packages/api/src/solus_api/connectors/onshape_ops.py
   1361 packages/api/src/solus_api/connectors/worker.py
    453 packages/api/src/solus_api/core/config.py
    589 packages/api/src/solus_api/deps.py
    206 packages/api/src/solus_api/graph/buffer.py
   188 packages/api/src/solus_api/graph/codec.py
   353 packages/api/src/solus_api/graph/edges.py
    582 packages/api/src/solus_api/graph/findings.py
   283 packages/api/src/solus_api/graph/inference/firmware_edges.py
    175 packages/api/src/solus_api/graph/inference/__init__.py
   163 packages/api/src/solus_api/graph/inference/joint_limits.py
   158 packages/api/src/solus_api/graph/inference/power_nets.py
   208 packages/api/src/solus_api/graph/inference/ros_edges.py
    92 packages/api/src/solus_api/graph/kinds.py
   153 packages/api/src/solus_api/graph/packet.py
    99 packages/api/src/solus_api/graph/resolver.py
   323 packages/api/src/solus_api/graph/telemetry.py
   195 packages/api/src/solus_api/hardware/bindings.py
   306 packages/api/src/solus_api/hardware/cad_suggestions.py
    331 packages/api/src/solus_api/hardware/companion_deployment.py
   382 packages/api/src/solus_api/hardware/config.py
   420 packages/api/src/solus_api/hardware/connections.py
     11 packages/api/src/solus_api/hardware/definitions/spice/generic.lib
   902 packages/api/src/solus_api/hardware/detect.py
   104 packages/api/src/solus_api/hardware/device_watch.py
   1113 packages/api/src/solus_api/hardware/hardware_router.py
   421 packages/api/src/solus_api/hardware/host_topology.py
    63 packages/api/src/solus_api/hardware/library_import.py
   383 packages/api/src/solus_api/hardware/library.py
   322 packages/api/src/solus_api/hardware/library_router.py
   342 packages/api/src/solus_api/hardware/links.py
    94 packages/api/src/solus_api/hardware/local_runtime.py
   154 packages/api/src/solus_api/hardware/ownership.py
    388 packages/api/src/solus_api/hardware/presence.py
   362 packages/api/src/solus_api/hardware/presence_topology.py
    78 packages/api/src/solus_api/hardware/repo_evidence.py
   149 packages/api/src/solus_api/hardware/runtime.py
   727 packages/api/src/solus_api/hardware/store.py
   222 packages/api/src/solus_api/hardware/topology_acceptance.py
   165 packages/api/src/solus_api/hardware/topology_evidence.py
   273 packages/api/src/solus_api/hardware/topology_observations.py
   280 packages/api/src/solus_api/hardware/topology_proposals.py
   412 packages/api/src/solus_api/hardware/topology.py
   454 packages/api/src/solus_api/linking/linker.py
    737 packages/api/src/solus_api/livebench/bench_router.py
    770 packages/api/src/solus_api/livebench/findings/envelopes.py
   255 packages/api/src/solus_api/livebench/findings/rules/body_rules.py
    129 packages/api/src/solus_api/livebench/findings/rules/command_rules.py
    359 packages/api/src/solus_api/livebench/findings/rules/electrical_rules.py
     26 packages/api/src/solus_api/livebench/findings/rules/__init__.py
    290 packages/api/src/solus_api/livebench/findings/rules/prediction_rules.py
    527 packages/api/src/solus_api/livebench/findings/rules/rule_base.py
    524 packages/api/src/solus_api/livebench/findings/rules/sensor_rules.py
   486 packages/api/src/solus_api/livebench/findings/rules/tracking_rules.py
     35 packages/api/src/solus_api/livebench/findings/sim_control.py
    765 packages/api/src/solus_api/livebench/findings/window_evaluator.py
     58 packages/api/src/solus_api/livebench/focus_scope.py
   194 packages/api/src/solus_api/livebench/persist.py
    144 packages/api/src/solus_api/livebench/replay_provider.py
   759 packages/api/src/solus_api/livebench/runs/analysis.py
    236 packages/api/src/solus_api/livebench/runs/capture.py
    128 packages/api/src/solus_api/livebench/runs/models.py
    119 packages/api/src/solus_api/livebench/runs/narration.py
    423 packages/api/src/solus_api/livebench/runs/router.py
    247 packages/api/src/solus_api/livebench/runs/snapshot.py
   199 packages/api/src/solus_api/livebench/runs/store.py
   564 packages/api/src/solus_api/livebench/scene/cad_import.py
    562 packages/api/src/solus_api/livebench/scene/cad_refresh.py
    108 packages/api/src/solus_api/livebench/scene/meshes.py
    297 packages/api/src/solus_api/livebench/scene/parser.py
   132 packages/api/src/solus_api/livebench/scene/part_bindings.py
    301 packages/api/src/solus_api/livebench/scene/router.py
    63 packages/api/src/solus_api/livebench/scene/schemas.py
   305 packages/api/src/solus_api/livebench/scene/service.py
   516 packages/api/src/solus_api/livebench/sessions.py
    261 packages/api/src/solus_api/livebench/stream.py
    691 packages/api/src/solus_api/main.py
   2072 packages/api/src/solus_api/models.py
    567 packages/api/src/solus_api/orchestration/config.py
    564 packages/api/src/solus_api/orchestration/models.yaml
     63 packages/api/src/solus_api/routers/activity.py
    761 packages/api/src/solus_api/routers/bridge.py
    339 packages/api/src/solus_api/routers/entities.py
    200 packages/api/src/solus_api/routers/findings.py
     59 packages/api/src/solus_api/routers/history.py
     44 packages/api/src/solus_api/routers/isaac_connection.py
    192 packages/api/src/solus_api/routers/machines.py
     84 packages/api/src/solus_api/routers/outcomes.py
     56 packages/api/src/solus_api/routers/simulation_models.py
    338 packages/api/src/solus_api/routers/sol_confirmations.py
   1309 packages/api/src/solus_api/routers/sol.py
    216 packages/api/src/solus_api/routers/solus_config.py
    204 packages/api/src/solus_api/routers/source_revisions.py
     87 packages/api/src/solus_api/routers/usage_turns.py
     74 packages/api/src/solus_api/services/activity.py
   235 packages/api/src/solus_api/services/environment_divergence.py
     47 packages/api/src/solus_api/services/events.py
     87 packages/api/src/solus_api/services/isaac_connection.py
   169 packages/api/src/solus_api/services/machines.py
   295 packages/api/src/solus_api/services/physical_robots.py
    161 packages/api/src/solus_api/services/simulation_models.py
   572 packages/api/src/solus_api/services/solus_config.py
   300 packages/api/src/solus_api/services/solus_graph.py
     12 packages/api/src/solus_api/simulation/__init__.py
     51 packages/api/src/solus_api/simulation/mesh_job.py
    148 packages/api/src/solus_api/simulation/providers/deterministic_elec.py
    281 packages/api/src/solus_api/simulation/providers/deterministic_mech.py
    436 packages/api/src/solus_api/simulation/providers/deterministic_robot.py
    101 packages/api/src/solus_api/simulation/providers/external_providers.py
    251 packages/api/src/solus_api/simulation/providers/__init__.py
    601 packages/api/src/solus_api/simulation/providers/mesh_interference.py
    667 packages/api/src/solus_api/simulation/providers/mujoco_job.py
    605 packages/api/src/solus_api/simulation/providers/ngspice_provider.py
    469 packages/api/src/solus_api/simulation/providers/spice_deck.py
    154 packages/api/src/solus_api/simulation/sim_capability.py
    274 packages/api/src/solus_api/simulation/sim_facts.py
    466 packages/api/src/solus_api/simulation/sim_ladder.py
   618 packages/api/src/solus_api/software/ros_reader.py
    172 packages/api/src/solus_api/sourcing/tools.py
   316 packages/api/tests/test_bench_focus.py
    816 packages/api/tests/test_bench_router.py
   162 packages/api/tests/test_capability_hygiene.py
   417 packages/api/tests/test_companion_deployment.py
    50 packages/api/tests/test_edge_writer_ratchet.py
   250 packages/api/tests/test_hardware_config.py
   427 packages/api/tests/test_host_topology.py
    231 packages/api/tests/test_isaac_connection.py
    572 packages/api/tests/test_isaac_tools.py
    773 packages/api/tests/test_mujoco_job.py
    460 packages/api/tests/test_ngspice_provider.py
    70 packages/api/tests/test_token_estimator_ratchet.py
   116 packages/api/tests/test_vendor_hygiene_api.py
    350 packages/companion/src/solus_companion/channel.py
    614 packages/companion/src/solus_companion/config.py
    341 packages/companion/src/solus_companion/dispatch.py
    222 packages/companion/src/solus_companion/frames.py
     60 packages/companion/src/solus_companion/machine/actions.py
    139 packages/companion/src/solus_companion/machine/code_reader.py
    290 packages/companion/src/solus_companion/machine/file_write.py
    274 packages/companion/src/solus_companion/machine/server.py
    477 packages/companion/src/solus_companion/supervisor.py
   176 packages/companion/tests/test_machine_tool_versions.py
    97 packages/contracts/python/solus_contracts/hardware_local_state.py
   273 packages/contracts/python/solus_contracts/relations.py
    195 packages/shared-types/src/relations.ts
  117894 total (426 files)
```

---
End of report.
