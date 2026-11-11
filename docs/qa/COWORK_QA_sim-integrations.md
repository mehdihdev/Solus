# Cowork QA: SOLUSDEV-322 sim integrations

## What you are testing

SOL, the chat agent, can now work with simulators on the person's own machine.

- **See what is installed.** `sim.available` reports MuJoCo, Gazebo, Isaac, ngspice and the built-in calculators.
- **Work in the person's own Gazebo worlds** (Classic 11, Fortress, Harmonic and newer). SOL can open a world, insert a Solus-generated robot model, set joint targets, step time, run a bounded routine and stop.
- **Work in the person's own Isaac stages**, on an x86_64 Linux machine with an NVIDIA GPU.
- **Record what happened.** Results land on the same part nodes as the real hardware.
- **Generate a simulation model** (URDF + MJCF) from the CAD with a gap report.
- **Map simulated joints to parts.**

Everything new is driven from the SOL chat. There is **no new UI**. Where a step needs a request outside chat (pinning a Run, opening a bench session), the exact HTTP request is given.

### The rule under test

| Where the action happens                                      | What SOL does                                                                                                   |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| A session Solus started (`open_world`, `open_stage`)          | Acts **without a confirmation card**, in Build and in Guide                                                     |
| A session the person started (`attach`)                       | Every action **parks a card** in Build and is **refused** in Guide. SOL never stops a world the person started. |
| Writes to the person's own files (`save_world`, `save_stage`) | **Always a card**, even inside a Solus-started session                                                          |
| `sim.generate_model`, `sim.map_to_parts`                      | **Always a card**                                                                                               |

### Terms

- **Build** and **Guide**: the two SOL modes (mode badge in the SOL panel).
- **Card**: the confirmation card SOL parks in chat, with Approve and Reject.
- **Refusal**: SOL says it cannot do this in Guide mode; no card appears.
- Guide allows **8 tool calls per message**; Build allows 24. Some Guide flows below are split across two messages for this reason.

## Required setup

1. **Solus desktop app and API running**, with an account that has a project you own.
   - Have a second account in a **different team** ready for the isolation checks.
   - SOL provider keys must be configured; SOL makes real model calls in this QA.
2. **A companion machine** (the person's computer) connected to the project.
   - Linux with Gazebo for flows A–H and J–K.
   - x86_64 Linux with an NVIDIA GPU and Isaac Sim for flow I. If you have no such machine, mark flow I **N/A (no Isaac host)**.
3. **The Gazebo fork installed on the companion machine.** Run `make mcp-forks` from the repo root once. It creates `integrations/mcp/gazebo/.venv`.
4. **Companion environment** (set before the companion starts):
   - `SOLUS_GAZEBO_PATH` = the Gazebo bin directory or directories, colon-separated. For example, with ROS Jazzy Harmonic: `/opt/ros/jazzy/opt/gz_tools_vendor/bin`.
   - `SOLUS_SIM_ROOTS` = folders holding world files, colon-separated and absolute. For example `/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds:$HOME/worlds`.
   - The simulator's own variables. For Harmonic, source `/opt/ros/jazzy/setup.bash` in the companion's shell; that provides `GZ_CONFIG_PATH`, `GZ_SIM_SYSTEM_PLUGIN_PATH`, `GZ_SIM_RESOURCE_PATH` and `LD_LIBRARY_PATH`. Use `IGN_*` for Fortress and `GAZEBO_*` for Classic. On a machine with more than one network interface (Wi-Fi plus Docker, VPN, …) also set `GZ_IP=127.0.0.1` (`IGN_IP` / `GAZEBO_IP` for the other families); without it every simulator call times out.
   - Isaac only: `SOLUS_ISAAC_RUNTIME` as before.
5. **A project with a robot** whose parts are set up:
   - an Onshape assembly synced (at least two parts joined by one revolute mate), so `sim.generate_model` has something to work from;
   - a robot entity with hardware parts (servos) on its bus map;
   - optionally, real hardware for flow K's real-session half. Without hardware, mark K's real-session half N/A.
6. **A world file** under `SOLUS_SIM_ROOTS`. The stock `empty.sdf` or `default.sdf` works.
7. **Know which mode you are in.** Every flow below says Build or Guide. Switch with the mode badge.
8. **After a merge of main**, run `cd packages/api && uv run alembic upgrade head` against the API database; `uv run alembic heads` must print the single head `a32200000004`. The new Build-only `front_app` field on a SOL message (SOL drive, SOLUSDEV-319) does not affect any flow here: sim flows never bind a window, and drive is a separate feature with its own QA.

Known limits. These are not failures:

- Fortress cannot start a server on the build host; it may on yours.
- Isaac was never run live during development.
- The generated model spawns as written in Harmonic 8.15 and Classic 11.15 (defect A was fixed in P9). If a spawn still fails, SOL must say `ok: false` with one reason line from the simulator (no absolute paths) and the model must be absent from `list_models`; a spawn that says ok for a model that is not in the world is a **FAIL** (defect B, fixed in P9).
- On Classic, the spawned model has no visuals or collisions (its meshes do not resolve, finding K) and `set_joint_targets`/`control` can report ok without the server receiving them (finding J). Record what you see; neither is a pass/fail criterion for this QA.

## Flows

### A. `sim.available`: what is installed (Guide, then Build)

| #   | Step                                                                                                      | Expected                                                                                                                                       |
| --- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| A1  | Guide mode. Ask: "Which simulators can I use on my machine?"                                              | SOL calls `sim.available`. No card. It lists MuJoCo, Gazebo, Isaac, ngspice and calculators, each with installed / connected / runnable here.  |
| A2  | Read the Gazebo row.                                                                                      | It names the family and version that is actually installed (for example "gz 8.15.0"). It shows running sessions (owned 0, attached 0).         |
| A3  | Read the Isaac row. On macOS, Linux without an NVIDIA GPU, or ARM Linux, SOL must give one honest reason. | "Isaac runs only on Linux with an NVIDIA GPU." / "No NVIDIA GPU was detected on the machine (nvidia-smi absent)." / an "x86_64 only" sentence. |
| A4  | Same question in Build mode.                                                                              | Same answer, no card.                                                                                                                          |

### B. Owned Gazebo world: open → spawn → targets → step → routine → stop with zero cards (Build)

Before you start, a generated model must exist (flow G) and its joints must be mapped (flow H), or use a model already registered for the robot.

| #   | Step                                                                                                                                                  | Expected                                                                                                                                                           |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1  | Build. "List my Gazebo worlds."                                                                                                                       | `gazebo.list_worlds`. Your world files are shown by root-relative path, with a family hint. No card.                                                               |
| B2  | "Open `empty.sdf` headless."                                                                                                                          | `gazebo.open_world` returns ok with a session id, and SOL says Solus started it. No card. The process appears on the companion machine.                            |
| B3  | "Insert my arm model at the origin."                                                                                                                  | `gazebo.spawn`. If the companion lacks the model, SOL pushes it first in chunks; one call from your point of view. Ok, and `list_models` shows the model. No card. |
| B4  | "Set the elbow to 0.5 rad."                                                                                                                           | `gazebo.set_joint_targets` ok. No card.                                                                                                                            |
| B5  | "Step the world 100 steps."                                                                                                                           | `gazebo.control` step ok. No card.                                                                                                                                 |
| B6  | "Run a sweep on the elbow for 5 seconds."                                                                                                             | `gazebo.run_routine` ok. The result names a Run (B7). No card. If no robot is bound to the model, SOL says "no robot is bound to this model; map joints first".    |
| B7  | "What happened?"                                                                                                                                      | SOL labels the result with provider, family/version and what the result leaves out.                                                                                |
| B8  | "Stop the simulator."                                                                                                                                 | `gazebo.stop` ok. The process is gone from the companion machine. No card.                                                                                         |
| B9  | Check the whole flow.                                                                                                                                 | **0 cards** from B1–B8.                                                                                                                                            |
| B10 | Edit a copy of the model's URDF so Gazebo cannot parse it (for example delete `effort="-1"` from a `<limit>`), register it, and ask SOL to insert it. | `gazebo.spawn` answers `ok: false` with one reason line (Classic: "gz model failed: Error: SDF parsing the xml failed"); `list_models` does not show it. No card.  |

### B-Guide. Same chain in Guide

| #   | Step                                                                        | Expected                                                                                   |
| --- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| BG1 | Guide. "Open `empty.sdf` headless, list the models and spawn my arm."       | All run, with **no refusal and no card**: the session is Solus-owned.                      |
| BG2 | Next message: "Set the elbow to 0.5, step 100, run a 5 s sweep, then stop." | All run, no card. If SOL stops after 8 tool calls, send "continue". The limit is expected. |

### C. Attached world: the person's own running world (Build, then Guide)

Before you start: launch a world yourself on the companion machine, for example `gz sim -s -r empty.sdf` in a terminal.

| #   | Step                                         | Expected                                                                                                                         |
| --- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| C1  | Build. "Attach to my running world `empty`." | `gazebo.attach` ok. SOL says the person started it. No card.                                                                     |
| C2  | "List models." / "What is the elbow angle?"  | Reads work. No card.                                                                                                             |
| C3  | "Insert my arm."                             | **Card** parked, with a complete preview. Reject it: nothing changes in your world.                                              |
| C4  | "Set the elbow to 0.3."                      | **Card**. Approve it: the joint moves.                                                                                           |
| C5  | "Pause the world."                           | **Card**.                                                                                                                        |
| C6  | "Stop the simulator."                        | **Refused, no card.** SOL says the world was started by you and to stop it from where you started it. The process keeps running. |
| C7  | Switch to Guide. Repeat C3–C5.               | Each is **refused** ("Guide mode can explain …"). No new cards. C6 is refused the same way.                                      |

### D. `save_world`: always a card (Build; Harmonic or Fortress)

| #   | Step                                                               | Expected                                                                                                                                     |
| --- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | In an owned session (B2), Build: "Save this world to `saved.sdf`." | **Card** whose preview shows the destination and size.                                                                                       |
| D2  | Reject.                                                            | No file is written.                                                                                                                          |
| D3  | Ask again and approve.                                             | The file appears under your first `SOLUS_SIM_ROOTS` folder. A path outside the roots, or with `..` or a symlink, is refused with a sentence. |

### E. Classic: save is unsupported

Needs Classic 11 on `SOLUS_GAZEBO_PATH`.

| #   | Step                                            | Expected                                                                                                                                                                                                                                   |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| E1  | Open a Classic world (owned). "Save the world." | No file, no card. SOL's reply carries the fork's own sentence: "Classic 11 cannot write a running world back to its file." If SOL instead says "The complete change preview is unavailable…", that is a **FAIL** (gap 6a was fixed in P9). |
| E2  | Steps B3–B8 on Classic.                         | They work as in B. Joint velocity is not reported on Classic.                                                                                                                                                                              |

### F. Failure sentences

Each case should produce exactly one sentence SOL can repeat. No stack traces, no absolute paths from your machine.

| #   | Setup                                                          | Ask                                               | Expected sentence                                                                                                                                                                                                    |
| --- | -------------------------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1  | Companion disconnected                                         | "Open my world"                                   | "The companion is offline (bridge offline)."                                                                                                                                                                         |
| F2  | `SOLUS_GAZEBO_PATH` unset                                      | "Which simulators can I use?"                     | Gazebo is not installed or not found, said plainly.                                                                                                                                                                  |
| F6  | `SOLUS_GAZEBO_PATH` set on the API host, no Gazebo on its PATH | `GET /api/v1/projects/{project_id}/bench/sources` | The `gazebo` row is available and names the configured family (`gz`, `ign` or `classic`). With it unset and no Gazebo on PATH: not installed, "no `gz`, `ign` or `gzserver` CLI under SOLUS_GAZEBO_PATH or on PATH". |
| F3  | Owned world already open                                       | "Open another world"                              | Refused: one Solus-owned world per project.                                                                                                                                                                          |
| F4  | World name outside the roots                                   | "Open /etc/foo.sdf"                               | Refused with a reason.                                                                                                                                                                                               |
| F5  | No generated model                                             | "Spawn my arm"                                    | SOL says no verified model exists and offers `sim.generate_model`.                                                                                                                                                   |

### G. `sim.generate_model`: card whose preview is the gap report (Build)

| #   | Step                                                                  | Expected                                                                                                                                                                                                                                            |
| --- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1  | Build. "Generate a simulation model for my arm."                      | **Card**. The preview lists each property with value and source (masses, joint frames from mates, limits) and each **GAP** with where to set it (for example "GAP: mate frame missing", "tip.mass"). Long reports show 49 rows plus "… and N more". |
| G2  | Approve.                                                              | SOL says the job is queued. After it completes, ask "Is the model ready?". A simulation model exists for the robot, with URDF and MJCF.                                                                                                             |
| G3  | Guide: "Generate a model."                                            | Refused in Guide. No card.                                                                                                                                                                                                                          |
| G4  | A robot with no revolute mate that can move.                          | The card is refused with a sentence. Nothing is queued.                                                                                                                                                                                             |
| G5  | Change the CAD (re-sync Onshape with an edit), then ask about models. | A regenerated model appears beside the old one. The old one is kept.                                                                                                                                                                                |

### H. `sim.map_to_parts`: card (Build)

| #   | Step                                                                                     | Expected                                                                                                                             |
| --- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| H1  | With an owned Gazebo session running your model: "Map the simulated joints to my parts." | **Card**. Each row is part → `gazebo/<world>/<model>/<joint>`. Ambiguous joints are listed as "unmapped: <joint> (ambiguous: a, b)". |
| H2  | Approve.                                                                                 | The mapping is saved. The parts' real hardware identity is unchanged (real telemetry still resolves, K3).                            |
| H3  | Guide: same ask.                                                                         | Refused.                                                                                                                             |

### I. Isaac stage flows (x86_64 Linux with an NVIDIA GPU only; otherwise N/A)

| #   | Step                                | Expected                                                                         |
| --- | ----------------------------------- | -------------------------------------------------------------------------------- |
| I1  | Build. "List my Isaac stages."      | `isaac.list_stages` shows the `.usd` files under `SOLUS_SIM_ROOTS`. No card.     |
| I2  | "Open `<stage>.usd`."               | `isaac.open_stage` creates an owned session. No card. Your file is not modified. |
| I3  | "Find the articulations."           | All articulation roots are listed.                                               |
| I4  | "Insert my arm at x=0.5."           | `isaac.spawn_at` ok, with a model push if needed. No card.                       |
| I5  | "Read the IMU and contact sensors." | `isaac.read_state` returns those sensors.                                        |
| I6  | "Run a 5 s sweep on the elbow."     | Ok. A Run is filed; a sweep records no rung-4 fact. No card.                     |
| I7  | "Save the stage."                   | **Card**.                                                                        |
| I8  | Guide: I1–I6.                       | They run without a card. I7 is refused.                                          |
| I9  | Ask for a 60 s sweep.               | **Known risk:** the companion allowlist bound is 55 s. Record the outcome.       |

### J. Runs: a Run appears and can be pinned

| #   | Step                                                                                                | Expected                                                                                |
| --- | --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| J1  | After B6, ask SOL for the Run id, or list runs with `GET /api/v1/projects/{project_id}/bench/runs`. | A run with `origin: "sim"` exists. Its sim info names the provider, family and version. |
| J2  | `POST /api/v1/projects/{project_id}/bench/runs/{run_id}/pin` with your session bearer token.        | 200, `pinned: true`. Repeat: still 200 (idempotent).                                    |
| J3  | Same POST as the other team's account.                                                              | 404. Unknown run id: 404. No token: 401. A viewer-role member: 403.                     |

### L. Retention (operator-assisted)

| #   | Step                                              | Expected                                                                                                                                                                               |
| --- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| L1  | Ask the operator for the ARQ worker start-up log. | It lists `cron:prune_sim_runs_job`, which runs daily at 03:17.                                                                                                                         |
| L2  | Ask the operator to enqueue the job once.         | Finishes `● 0` when no sim run is older than 30 days. Pinned, baseline and finding-linked runs, and real runs, are never pruned. Nothing is expected to be deleted in a fresh project. |

### K. Cross-feature: a real session and a sim session on the same part

| #   | Step                                                                                                                                                                                                                                                                                                     | Expected                                                                                                                                                    |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| K1  | After H2, open a Gazebo bench session: `POST /api/v1/projects/{project_id}/bench/sessions` with body `{"mode": "sim", "config": {"provider": "gazebo", "family": "gz", "world": "<world>", "model": "<model>"}}` (the API host also needs Gazebo: set `SOLUS_GAZEBO_PATH` in the API's environment, F6). | The session starts. Sim joint packets resolve to the mapped parts.                                                                                          |
| K2  | Drive a joint (B4) and watch the bench session's part readings.                                                                                                                                                                                                                                          | The elbow part shows the simulated position. Findings from this session carry `evidence.sim = true`.                                                        |
| K3  | With real hardware connected, open a real session on the same robot.                                                                                                                                                                                                                                     | The real elbow resolves to the **same part node** as the simulated elbow. Mapping did not break real resolution.                                            |
| K4  | A simulated joint you did not map (for example `wrist`).                                                                                                                                                                                                                                                 | Stays unresolved and is not attached to any part.                                                                                                           |
| K5  | Second team's account: try to spawn the first project's model, or stop its session, from its own project.                                                                                                                                                                                                | Spawn is refused. Stop parks a card in **its own** project and never touches the first project's world. Approving another project's card fails (not found). |

## Pass/fail checklist

Each row maps to one flow. Mark P, F or N/A, and note the build/commit tested.

| Flow                                                 | Result | Notes |
| ---------------------------------------------------- | ------ | ----- |
| A1–A4 `sim.available`                                |        |       |
| B1–B10 owned Gazebo, Build, 0 cards                  |        |       |
| BG1–BG2 owned Gazebo, Guide, 0 cards                 |        |       |
| C1–C7 attached world cards / refusals / stop refused |        |       |
| D1–D3 `save_world` card                              |        |       |
| E1–E2 Classic unsupported                            |        |       |
| F1–F6 failure sentences                              |        |       |
| G1–G5 `sim.generate_model`                           |        |       |
| H1–H3 `sim.map_to_parts`                             |        |       |
| I1–I9 Isaac stages                                   |        |       |
| J1–J3 Runs and pin                                   |        |       |
| L1–L2 retention                                      |        |       |
| K1–K5 cross-feature and isolation                    |        |       |
