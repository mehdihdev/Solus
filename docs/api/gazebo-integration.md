# Gazebo integration — SOLUSDEV-322 P3

Tier-1 route/tool plan for the owned `gazebo.*` tools (plan P3-T4). The fork that runs on the
user's machine is `integrations/mcp/gazebo/` (P3-T1..T3); the API wrappers are
`agent/tools/gazebo_tools.py` with the SOL-visible argument models in `agent/tools/gazebo_models.py`.
Everything shared with Isaac is vendor-free: the ownership ledger (`simulation/sessions_ledger.py`),
the per-call gate hook (`agent/dynamic_gate.py`, `docs/contracts/action-gate.md` step 1) and the
Run/`sim_result` seams P5 adds.

## Tools SOL sees

Only the twelve wrappers below enter the registry. The raw `gazebo.*` bridge adverts never do
(`runtime._register_bridge_tools` skips the `gazebo` server; `_owned_gazebo_tools` builds the
wrappers from the live inventory). `gazebo.put_asset` has no SOL-visible tool: it is `spawn`'s
internal step.

| tool                | kind           | gate                                                                       | cloud bound (s) | what it does                                                                                    |
| ------------------- | -------------- | -------------------------------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------------------- |
| `probe`             | read           | none                                                                       | 25              | installed families (`classic`/`ignition`/`gz`), capability row, running worlds, sessions        |
| `list_worlds`       | read           | none                                                                       | 25              | `*.sdf`/`*.world` under `SOLUS_SIM_ROOTS` (root-relative) + worlds running now                  |
| `open_world`        | writer (owned) | hook `False` — owned by construction                                       | 130             | starts one Solus-owned server on the user's world file; ledger row `owner="sol"`                |
| `attach`            | registration   | none (read-only)                                                           | 25              | registers a world the user started; ledger row `owner="user"`; every action inside it cards     |
| `list_models`       | read           | none                                                                       | 25              | models, links, joints of a registered world                                                     |
| `spawn`             | writer         | hook = `not ledger.is_owned`                                               | 300             | inserts a graph-bound `simulation_model` (pushes its files first when the companion lacks them) |
| `joint_state`       | read           | none                                                                       | 35              | bounded window of joint positions/velocities (rad, rad/s)                                       |
| `set_joint_targets` | writer         | hook = `not ledger.is_owned`                                               | 25              | ≤ 16 joint position targets (rad)                                                               |
| `control`           | writer         | hook = `not ledger.is_owned`                                               | 65              | pause / play / step (1..10000) / reset (`all`, `time`, `model_only`)                            |
| `run_routine`       | writer         | hook = `not ledger.is_owned`                                               | 100             | `joint_trajectory` (≤ 16 waypoints) or `sweep`, 1..60 s, with readback                          |
| `stop`              | writer         | hook = `not ledger.is_owned`; attached → refused in the tool, never carded | 35              | stops the server Solus started; ends the ledger row                                             |
| `save_world`        | writer         | static `requires_confirmation=True`                                        | 35              | writes the running world into the user's own file (`unsupported_on: classic 11`)                |

The cloud bound always exceeds the fork's allowlist bound (`integrations/mcp/gazebo/allowlist.yaml`)
so the cloud never reports TIMEOUT while the companion keeps running. `spawn`'s 300 s covers the
chunk push (~32 round trips for a 2 MiB model); the allowlist's 60 s binds only the native spawn.
The server is `exposure: internal` (docs/contracts/bridge-protocol.md): the owned `gazebo.*` wrappers
are the only model-facing surface, and `agent/runtime.py` also drops the raw specs by server name.

## Arguments (strict)

`agent/tools/gazebo_models.py`, `extra="forbid"`, `strict=True`, numbers finite and bounded,
floats dumped as floats. Names (`world`, `model`, `joint`, spawn `name`) match
`^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$` — never a leading `-` (an argv option), never quotes, braces,
colons, backslashes or whitespace (protobuf text-format syntax). Paths (`world_ref`, `dest`) are
≤ 16 plain components joined by `/` (no `..`, no leading `/`, no dotfiles). `session_id` is
`^[A-Za-z0-9-]{1,80}$` (owned ids are uuid4, attached ids `attached-<uuid4>`).

- `open_world{world_ref, family?, gui=false, dry_run}` · `attach{family, world}`
- `list_models{session_id}` · `joint_state{session_id, model, joints?, window_s 0..10}`
- `spawn{session_id, model_entity_id, name, pose{xyz, rpy}, dry_run}` — the only difference from
  the fork's `tool_args.py`: the graph entity replaces `model_sha256`
- `set_joint_targets{session_id, model, targets[{joint, position_rad}] ≤ 16, dry_run}`
- `control{session_id, action, steps 1..10000 = 1, reset_scope = "all", dry_run}`
- `run_routine{session_id, model, routine, duration_s 1..60, joints?, waypoints?, sweep?, dry_run}`
- `stop{session_id, dry_run}` · `save_world{session_id, dest, dry_run}`

## Gates and the ledger

- **Ownership is a DB fact.** `open_world` on `ok` records
  `sim_session{provider="gazebo", owner="sol", session_id, started_by_call_id=current_call_id,
scene_ref=world_ref, created_by=<the requesting user>}`; `attach` records `owner="user"` with
  `scene_ref=world`; `stop` on `ok` ends the row. Companion results are data: any `owned` /
  `owner` field a fork result carries is dropped and replaced by the ledger's `owner`
  (`test_companion_claims_of_ownership_are_ignored`).
- **One owned Gazebo server per project.** `open_world` refuses (in preview and invoke, before
  any native call) while an `owner="sol"` row has `ended_at IS NULL`:
  "A Gazebo world Solus started is still running in this project; stop it first."
- **The per-call hook** `needs_confirmation(args)`: `save_world` → `True`; reads, `attach`,
  `open_world` → `False`; writers → `not ledger.is_owned(project, "gazebo", session_id)`; a
  missing `session_id`, an unknown or forged id, or a ledger read that raises → card (fails
  closed in `dynamic_gate.needs_card`). `stop` of a world the ledger knows as attached answers
  `False` and `invoke` refuses it with "This world was started by you, not by Solus; stop it from
  where you started it." — never a card. An owned session still cards when the fork's own dry
  run carries a row labelled `Approval required` (ADR-040 §5, `dynamic_gate.APPROVAL_REQUIRED_LABEL`;
  P10 item 22): the hook reads the dry run for that label, and `invoke` refuses an uncarded call
  whose verified plan carries it, so the label can only make a call stricter.
- **Every writer previews completely before every native call**: the fork's `dry_run: true`
  result (`{ok, dry_run, preview[], fingerprint}`) becomes the card rows plus one binding row
  (native fingerprint; for `spawn` also the graph model id/version and graph snapshot digest).
  A matching ticket from `preview()` is verified against a fresh plan; without a ticket the tool
  asks its own hook and refuses when that says card (defence in depth, as `isaac_tools.py`).
- In Guide mode a call the hook would card is refused; in Build it parks with the preview.
  `routed_by_simulation` (R115) does not force a card for these tools (plan decision 2).

## `spawn`: graph-bound model, verified chunks

1. `model_entity_id` resolves through the shared v2 `simulation_model` resolver (project-scoped,
   read-scope predicate, every bound entity live): `asset{urdf_path, files{path: sha256}, sha256}`.
2. The fork is asked for a dry run with `model_sha256 = asset.sha256`. A result
   `{ok: false, code: "model_not_verified"}` (the fork's one code for absent, unverifiable or
   tampered) means "push it". The card then shows wrapper-authored rows — Model, Name in world,
   Pose, Session and **Model push: N chunk(s), B bytes into `.solus/sim/models/<sha16>…`** — and
   a preview pushes nothing.
3. On invoke, after the ticket/ownership check and the graph re-resolution, the files are read
   from the artifact store: `root.attrs.artifacts = {urdf: <artifact id>, meshes: {<path>: <id>}}`
   (written by the P6-T2 generation job), each row project-scoped and live, each file's sha256
   checked against the manifest before it leaves, ≤ 20 MB per file and ≤ 32 MB in all.
4. `gazebo.put_asset{sha256, path, index, total, data_b64, manifest (index 0 only)}` is called
   once per chunk, sequential indices across files, **≤ 64 KiB raw per chunk, `data_b64` ≤ 96 KiB**
   (`CHUNK_BYTES`, `MAX_DATA_B64`; asserted in `test_spawn_pushes_missing_assets_in_chunks_then_spawns`).
   Every ack must be `ok`; the last must be `promoted`.
5. The fork's own dry run is re-run (now with the model present) and then the native spawn.

Refusals before any chunk crosses: no artifact store wired, the companion offers no
`gazebo.put_asset`, a model file not at the top level of its manifest (the fork spawns from the
model file's directory), a missing or foreign artifact row, a digest mismatch, a size bound.

## Runs

`run_routine` on `ok` calls the `record_sim_run(args, result)` hook passed to
`build_gazebo_tools`. Here it is `no_sim_run` (a no-op); P5-T4 wires `livebench/sim_runs.py`'s
`record_sim_run` (Run with `origin="sim"`, `record_sim_result` at rung 4) without touching the
wrapper. No Run and no `sim_result` is written by this task.

## Telemetry

Telemetry never rides MCP (integrations/mcp/CLAUDE.md rule 6). The wrappers return bounded
`joint_state` windows for reasoning only; streaming goes through the livebench sources P3-T5 adds
(`GazeboTopicSource` per family, `device_id = <world>/<model>/<joint>`,
`values = {"<joint>.position": rad, "<joint>.velocity": rad/s}`), opened through the bench
session routes.

`POST /projects/{id}/bench/sessions` with `{"mode": "sim", "config": {"provider": "gazebo", ...}}`
(`GazeboSimConfig`, P3-T5): `topics: list[str]` (manual, still accepted) and/or `world` + `model`
(plain identifiers, `^[A-Za-z0-9_][A-Za-z0-9_.-]*$`, ≤ 64 chars) with an optional
`family: "classic" | "ignition" | "gz"` — one of `topics` or `world`+`model` is required, and
`world`/`model` go together. The livebench member (`livebench/sim/{gazebo_family,gazebo_source,
ignition_source,classic_source}.py`) resolves the streaming binary ONLY through `SOLUS_GAZEBO_PATH`
(never PATH), takes the newest installed family when none is named, and derives the model's
joint_state stream: `/world/<w>/model/<m>/joint_state` via `gz`/`ign topic -e --json-output` for
the new and ignition families; a ≤ 10 Hz `gz model -w <w> -m <m> -i` poll on classic 11, which
publishes no joint_state topic (`<joint>.position` only — classic reports no velocity). Classic
`topics` stream protobuf text format, flattened to numeric leaves (depth 16, 64 KiB per message).
The session label is `Gazebo <world>/<model>` or `Gazebo (<n> topic(s))`.

## Limits

- 12 SOL-visible tools; `put_asset` internal. Dry-run previews ≤ 40 rows of ≤ 400 chars.
- One owned server per project (ledger) and per fork process (`world_sessions.py`).
- `set_joint_targets` ≤ 16 targets; `run_routine` 1..60 s, wall time ≤ `duration_s + 10` in the fork.
- Model push ≤ 20 MB per file, ≤ 32 MB per model, ≤ 64 KiB raw per chunk.
- `save_world` is `unsupported_on: classic 11` — the fork answers `{ok: false, code: "unsupported_on"}`.

## Environment values (companion machine)

- `SOLUS_GAZEBO_PATH` — colon-separated absolute bin dirs; the only place binaries resolve from.
  `GET /projects/{id}/bench/sources` detects the installed family there first (newest first: `gz`,
  `ign`, `gzserver`), falling back to PATH for detection only; the miss reason names both places.
- `SOLUS_SIM_ROOTS` — colon-separated absolute dirs holding the user's worlds (and save targets).
- The simulator's own `GZ_*` / `IGN_*` / `GAZEBO_*` / `LD_LIBRARY_PATH`, re-exported by name through
  `bin/launch` (`solus/env.allow`); `LD_LIBRARY_PATH` is a recorded residual. On a multi-homed
  machine (VPN, docker bridges) set `GZ_IP` / `IGN_IP` / `GAZEBO_IP` to `127.0.0.1`: the simulators
  otherwise advertise the first non-loopback interface and local service calls time out.
- API side: the artifact store (`artifact_store` on `build_sol_registry`) must be wired for a model
  push; without it `spawn` still works for a model the companion already holds.

## Tests

`packages/api/tests/test_gazebo_tools.py`, `test_gazebo_models.py`; `test_sol_runtime.py`
(`test_raw_gazebo_inventory_never_becomes_a_tool`, adapter allowlist); fork
`integrations/mcp/gazebo/tests/test_gazebo_server.py` (`model_not_verified`).
