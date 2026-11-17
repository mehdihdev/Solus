# RECON — SOLUSDEV-326 robot onboarding (P0, read-only)

Date 2026-11-15. Branch `SOLUSDEV-326-robot-onboarding` at `f5042483` (== origin/main). Method: workflow `wf_8bf0e0cd-014` ran 10 read-only areas, each followed by an adversarial verifier, plus a completeness critic (21 agents, 0 errors). It also included host checks that open no device. Line numbers are at HEAD; the 2026-11-08 REPO_STATE doc's are stale. Plan: `~/.claude/plans/pasted-content-id-8b96-robot-fluffy-dove.md`.

## 1. What landed since 33e3bc08

`ce8dc82b` 319 (drive relay, Ember pill, PlanCard, `stored_args`/`invoke_stored`, SOL window starts a new chat on summon); `8bdf993e` 323 (onboarding wireflow); `163f52bc` 324 (summon screenshot); `51745361` 322 (sim agents, `agent/dynamic_gate.py` per-call `needs_confirmation` hook, `sim_session` ledger, Isaac no longer owned routines); `bf07be48` 325; `f5042483` 326 (thinking frames). New reports: `COMPLETION_SOLUSDEV-322-sim-integrations.md` and eight `COMPLETION_SOLUSDEV-319-*`. Alembic: one head, `a32200000004`, in `packages/api/migrations/versions` (not `alembic/versions`). `packages/api/src/solus_api/hardware/` is byte-identical to 33e3bc08.

## 2. Answers to the P0 checklist

1. **Gate**
   - `build_dispatch` `agent/runtime.py:1232-1303`. Production order: Guide/Build wrapper (`modes.py:97-118`, wired `routers/sol.py:1344-1356`), then auto-run policy, then park (`confirmations.request_confirmation` :519-589), then invoke.
   - Decide is `decide_confirmation` :592-750. It re-previews under a row lock with a 10 s cap and marks the row STALE on any difference outside `INFORMATIONAL_LABELS`. Approval runs `invoke_stored` with the STORED args. TTL is 30 min; expiry is lazy (rows stay PENDING).
   - Route `routers/sol_confirmations.py:285`; the decision body is decision-only (422 on any extra field). Card UI: `features/sol/ConfirmationCard.tsx` (Approve/Reject hard-coded :254,257).
   - **Modes have not been removed.** `modes.py` grew (DIRECT_WRITE_TOOLS, the hook), and Guide refuses gated calls before park. Guide is the Electron default (`apps/desktop/src/main/solSettings.ts:30-31`). So **no card can appear in Guide**.
   - The sim per-call hook is on main.
2. **Where hardware runs**
   - `bench_local = load_local()` (`livebench/sessions.py:78-82`, `main.py:483-486`), which exists only when the API process imports livebench (a developer-run local API). The packaged desktop calls a hosted API whose image ships no livebench (`infrastructure/docker/api.Dockerfile:25-36`).
   - The presence tool registers only in dev (`main.py:521-526` → `deps.py:611-621` → `runtime.py:2125-2136`); the port watcher runs whenever `app_env != production` (`device_watch.py:48-51`).
   - Nothing tells SOL that hardware is on another machine; that text exists only in route 503s (`hardware_router.py:634`).
3. **robot_category**
   - Sole writer: `PhysicalRobotService.create` (`services/physical_robots.py:163-202`).
   - It sits in 13 API source files, 11 API test files, 1 migration (`hardware_config_backfill.py`), 15 desktop source files and 7 desktop test files; none in livebench, contracts or shared-types.
   - Six ownership queries diverge: `_container_ids`, `store._owned_part_ids`, `attach_existing_parts`, `runtime._owned_parts`, `topology.read_topology`, `cad_suggestions._owners`.
   - `part.attrs.category` is write-only on the server. The category node is the only label for attached CAD/connector parts.
   - The 7-key vocabulary is required by the library `PartDefinition` (18 YAMLs).
4. **Config and topology**
   - `HardwareConfig` v1 (`hardware/config.py:283-331`) is the driver wire format and carries exactly one identity. Stored configs are v2 `EntityHardwareConfig`. There is no upgrade-on-read (`store.config_of` :65-70).
   - `put_config` rebuilds a single identity at 9 call sites.
   - Detect gates refuse a second device (`detect.py:582-588,666-679`), and `bindings._conflicting_bindings` allows one config per device.
   - `sync_topology` (`topology.py:80-164`) derives one endpoint and soft-deletes every edge it did not derive. `_validate_tree` (:395-412) rejects more than one parent.
   - `_robot_opener` (`livebench/bench_router.py:549-610`) is one of three duplicated openers; only it checks `host_machine_id`.
   - A lone part can open a session through provider `hardware`, but its telemetry never resolves (no `external_ref`). A detected device cannot become a standalone part.
5. **Route bodies holding orchestration:** `propose_detected` (:645-684), `confirm_detected` (:687-794), `_decide`/`_bind_accepted_device` (:886-963), `list_hardware_parts` (:243-284), `import_platform`/the robot branch of `import_part` (library_router). These are services already: topology propose/accept, host, wiring, presence prepare, CAD suggestions, `library_import`.
6. **Renderer to delete:**
   - `features/graph/hardware/*`: the scheduler, card rules, rail, `HardwareAddPanel` and its children; about 2.5k lines and 15 tests.
   - The 8 robot cards plus 2 snippet builders: about 2.5k lines and 9 tests. They mount inside `RobotTopologyGraph` and `RobotSidebar`, not on the robot node.
   - 5 dead `lib/api` modules.
   - `hardwareErrorText` must move first. `useProposalSources` is the only `source_refs` supplier; there is no server list method.
7. **Nothing moves anything today, except:**
   - `code.arduino_upload` refuses execution (`integrations/mcp/code/solus/arduino_upload.py:315-316`); it is Uno-only and its preview refuses a busy port (:327).
   - `deploy/flash.py` has no caller.
   - The Feetech writers have no caller, and there is no bus lock or command seam.
   - `recognition/active.py` has no caller.
   - **However, card-approved `code.exec`/`run`/`process_*` get read-write on `/dev/ttyUSB*` (`integrations/mcp/code/solus/sandbox.py:84-85`).**
   - Prior art: a reviewed Feetech actuation stack was reverted in `e224d4e5` (see `bd5d7adf`), and the ADR-014 SOL-motion amendments were removed in `9537920a`.
8. **SSH and ROS**
   - `_execute_pinned` (`livebench/deploy/companion.py:134-150`): pinned options, no TOFU.
   - Only the local API sees `SSH_AUTH_SOCK`.
   - Deploy is disabled outside tests. `ros_live.py` confirms edges only and writes no entities. `onboard_topology` has no caller.
   - livebench cannot be shipped as a zipapp (native wheels, Python 3.12).
9. **Docked panel and system turns**
   - No docked panel exists. `SolChat layout='panel'` is tested but unmounted.
   - No system/hidden message exists (`MessageCreate` is extra=forbid). Precedent: Solus-authored user bubbles (`PresenceCard.tsx:120`, `findingActions.ts:55-58`).
   - Resume admits only COMMAND_TOOLS, capped at 6 (`routers/sol_resume.py:40,177`).
10. **Canvas and visibility**
    - Canvas = `useWorkspaceGraph.readSnapshot` → `graphIndex.buildNavigationIndex` `onCanvas` (:86).
    - The per-user predicate seam is `GraphReadScope.entity_predicate` (`graph/read_scope.py:34-47`). The resolver, the hardware routes, `search_solus`, RAG's `SemanticCache` and the project card do not use it, or do not key by viewer.
11. **Arduino:** `/dev/ttyUSB0`, CH340 `1a86:7523`, sysfs `5-1.2.3`, **no USB serial** → `usb:port-5-1.2.3`. `.venv/bin/arduino-cli` 1.5.1 (pinned digest). The fork runtime `.venv/arduino` has `arduino:avr` 1.8.8 and avrdude 8.0.0-arduino1. No esptool. `~/.arduino15` has no AVR core.

## 3. Corrections to the spec (decided; see the plan's Phase-1 section)

- The Hardware page sends `do` + `force_confirmation`. No mode change.
- The card lives in a JSON column, never on `ToolDescriptor`.
- `ask_user` is answered through a server-authored user turn.
- The resume flag is server-sent.
- The identity list lives on stored v2 only. Drivers get a per-brain v1 projection; the frozen backfill migration needs a frozen copy of the v2 schema first.
- One merged session per robot.
- `in_graph`/`onboarded_by` are stored in attrs, with a viewer clause plus explicit predicates on every hardware read. `in_graph`/`onboarded_by` join `SOLUS_OWNED_ATTR_KEYS`.
- Categories: one ownership rule plus a one-way, idempotent migration that keeps the label on the re-pointed edge.
- A serial owner in livebench, `-hupcl`, and a typed busy error.
- `inspect_device` is free on a fresh plug-in or an owned port. It cards (per-call hook, approval) only when opening the port would restart a running board.
- Upload uses an API-owned wrapper with a preview-minted single-use token; the busy check leaves the dry run.
- The NanoSixChannels `device_id` is edited before flashing.
- The P6 agent is a stdlib relay. Onboard brains are derived in `sync_topology` from identity items. Survey rows are accepted through `apply_evidence`.

## 4. Human gates to schedule

1. **Action-gate contract additions** (P2).
2. **Fork changes** (P5): allowlist entries `code.arduino_upload` execution and `code.arduino_read_chip` (ratified), the Nano boards, a sandbox avrdude digest, and blank PROVENANCE sign-offs.
3. **ADR-034** (approved) plus the local-state contract for the pin file (P6).
4. **A new ADR for SOL-commanded bus writes and motion** (P7/P8; not yet asked).
5. **ADR-014** `from_sim_run` (approved).
6. **Wireflow rewrites** (P3).
7. **Accepted residuals:** card-approved `code.exec` can touch a serial port outside the owner; findings and activity rows about hidden hardware stay visible to teammates.

## 5. Baselines

- **DBs:** `solus_onboarding` (copy of `solus`, a32200000004, 0 robots, 96 parts). `solus_onboarding_mig` (copy of `solus_graph`, a32000000005, 24 live robots, 168 live `robot_category` nodes).
- **Python CI:** none (`.gitlab-ci.yml`). Python ratchets run locally.
- **Prompt budget:** `FIXED_PROMPT_TOKENS` 15,000, measured 14,461.
