# Fork security review — `gazebo` — 2026-11-09 (draft, P3-T1 skeleton)

Scope of this entry: the Solus-authored skeleton — `bin/launch`, `solus/env.allow`,
`solus/family_detect.py`, `solus/worlds.py`, `solus/tool_args.py`, `allowlist.yaml`. The
server, adapters, sessions and asset store (P3-T2/T3) append their own dated entries below
this one; nothing here is rewritten. Sign-off lines live in PROVENANCE.md and stay blank
until two humans review.

## 1. Supply chain

- [x] No `upstream/`: every shipped file is Solus-authored (PROVENANCE.md).
- [x] No runtime fetch — evidence: `bin/launch` read in full; `grep -E "npx|uvx|pipx|pip install|
npm install|curl|wget" bin/launch` → no hits (pinned by
      `tests/test_launch_entrypoint.py::test_launch_is_env_i_with_exactly_the_declared_passthrough`).
- [x] Lockfile committed, hash-pinned, byte-identical to `isaac/requirements.lock.txt`
      (pinned by `test_paper_trail_files_exist_with_blank_sign_offs`).
- [ ] Dependency audit at review time (`pip-audit -r requirements.lock.txt`) — humans at ship.

## 2. Least privilege

- [x] Runs as the invoking user; `grep -rn "sudo\|setuid\|seteuid" solus/ bin/` → none.
- [x] Binaries resolve ONLY through `SOLUS_GAZEBO_PATH` entries (absolute, existing dirs);
      the ambient PATH is never searched — `family_detect.gazebo_search_path`, pinned by
      `test_detect_never_uses_ambient_path`. The classic `gazebo` GUI wrapper is never executed
      (it hangs; RECON §2) — `test_classic_banner_with_nonzero_exit_is_success_and_gazebo_is_never_run`.
- [x] Filesystem scope: every tool path is root-relative and opened through
      `worlds.confined_open` (root descriptor + per-component `O_NOFOLLOW` + regular-file leaf);
      `..`, absolute, `//`, `.`, symlinked components and FIFOs are refused —
      `test_paths_refuse_traversal_symlink_and_outside_roots`,
      `test_confined_open_refuses_symlinked_leaf_dir_and_fifo`. Model files live only under
      `<workspace>/.solus/sim/models/<sha256>/` (`worlds.model_dir`).
- [x] No shell: the one subprocess site (`family_detect.subprocess_run`) takes an argv list with
      `capture_output`, a timeout and no `shell=`; stderr is dropped.
- [x] Nothing model-supplied reaches argv as an option: `tool_args` names match
      `^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$` (no leading `-`, no quotes/braces/colons/backslashes/
      whitespace, i.e. no protobuf text-format syntax) — `test_names_that_could_become_options_or_
textformat_are_refused`.

## 3. Sandbox posture

Declared (Linux; the only platform the three families are verified on): OS user permissions,
`env -i` launcher with the named passthrough list, cwd = the linked workspace, pinned
`SOLUS_GAZEBO_PATH`, `SOLUS_SIM_ROOTS` confinement. No network namespace. The simulator
processes the server will start (P3-T3) run with the same user permissions in their own
process group and are stopped only through the handle the fork holds.

## 4. Secret hygiene

- [x] Environment access confined to `solus/env.allow`; `bin/launch` re-exports exactly those
      names plus the companion-SET `SOLUS_MCP_WORKSPACE`
      (`test_launch_is_env_i_with_exactly_the_declared_passthrough`); `grep -rn "os.environ"
solus/` → `SOLUS_GAZEBO_PATH` (family_detect), `SOLUS_SIM_ROOTS` (worlds) only.
- [x] `SOLUS_MCP_WORKSPACE` is NOT an `env.allow` passthrough name (same invariant as the code,
      local and isaac forks). `supervisor.child_env` copies passthrough names from the companion's
      ambient environment before applying declared values, so listing it would let an ambient
      value become the confinement root when no folder is linked
      (`test_ambient_workspace_never_reaches_the_fork_when_no_folder_is_linked`).
- **Residual (Q4): `LD_LIBRARY_PATH` passthrough.** The ROS-vendor Harmonic `gz` and the conda
  Fortress/Classic binaries need the user's library path to run at all (under `env -i` Harmonic
  prints "I cannot find any available 'gz' command", RECON §2). The value is the USER's own, set
  in the companion's environment, never from a tool argument or the cloud; it lets the user's
  simulator load the user's libraries — the same trust as running `gz` in their shell. Accepted
  and recorded; a reviewer may narrow it to a Solus-set value later.
  **Sanitized:** `bin/launch` rebuilds `LD_LIBRARY_PATH` and every `*_CONFIG_PATH`,
  `*_PLUGIN_PATH`, `*_RESOURCE_PATH` and `*_MODEL_PATH` list before `cd`-ing into the workspace,
  keeping only non-empty entries that start with `/`. An empty or relative element means the
  cwd to ld.so(8) and to the plugin loaders, and the cwd is the cloned repo — a committed
  `libz.so.1` at the repo root would otherwise load into the fork and every simulator it starts
  (`test_launch_keeps_only_absolute_entries_in_library_and_plugin_paths`).
- **Residual (P9, `f19378b6`): `GZ_IP`, `IGN_IP`, `GAZEBO_IP` passthrough.** On a multi-homed host
  (P9 live run: a CGNAT Wi-Fi address plus tailscale) the simulator's transport advertised an
  interface the host could not connect to and every service call timed out; the three names let
  the user pin the bind address, exactly as they would in their shell. Values are the USER's own
  from the companion's environment, never a tool argument; the fork never reads them, only the
  simulator child does. Added after the sign-off draft above. **Accepted by Pratham Madaram in
  chat on 2026-11-11** ("yes on GZ_IP/IGN_IP/GAZEBO_IP"); completion report §11 item 18 closed.
- [x] No credential ever logged; no credential persistence: the skeleton writes no files.

## 5. Untrusted I/O

- [x] Tool inputs are hostile: `tool_args` models are `extra="forbid"`, numerically bounded
      (`steps ≤ 10000`, `window_s ≤ 10`, `duration_s ≤ 60`, ≤ 16 targets, finite floats),
      `data_b64 ≤ 96 KiB` base64, manifests ≤ 32 entries.
- [x] Parsers bound input sizes: world-file hints read ≤ 64 KiB (scan) / ≤ 1 MiB (open);
      the world scan is bounded to 500 files, depth 6, no symlinks, no hidden dirs.
- [x] No `eval`/`exec`/dynamic import anywhere in `solus/`.

## 6. Destructive actions

- [x] `save_world` is the only static `requires_confirmation: true` (it writes the user's own
      file). `open_world spawn set_joint_targets control run_routine stop` are gated per call by the
      API ownership ledger (`docs/contracts/action-gate.md`); `probe list_worlds attach list_models
joint_state` are reads; `put_asset` writes only under `.solus/sim/models/<sha256>/`.

## 7. Code-review depth

- Tier 1 (100% line-read, agent draft): `bin/launch`, `solus/env.allow`, `solus/family_detect.py`,
  `solus/worlds.py`, `solus/tool_args.py`. Human line-read pending.

## 8. Update path

- [ ] Both PROVENANCE sign-off lines dated against the shipping commit — humans.

Ordinary verification (2026-11-09): `uv run pytest -q integrations/mcp/gazebo/tests` green;
ruff and mypy clean on `solus/`. No simulator process was started by any test; fixture CLIs
under `tests/fixtures/bin/<family>/` replay stdout recorded from Harmonic 8.15.0, Fortress
6.16.0 and Classic 11.15.1 on this host.

---

# Fork security review — `gazebo` — 2026-11-09 (draft, P3-T2/P3-T3: adapters, server, sessions, asset store)

Appended entry (the P3-T1 entry above is unchanged). Scope: `solus/adapters/{adapter_base,
classic,ignition,gz}.py`, `solus/spawn.py` (P3-T2); `solus/gazebo_server.py`,
`solus/gazebo_routines.py`, `solus/world_sessions.py`, `solus/model_assets.py`, `solus/tool_args.py`
(now `strict=True`) (P3-T3). Sign-off lines live in PROVENANCE.md and stay blank until two humans
review; the tree hash at this draft is recorded there.

## 1. Supply chain

- [x] Still no `upstream/`, no runtime fetch, lockfile unchanged (byte-identical to isaac's).
- [x] The server imports only `mcp`, `pydantic` and the stdlib (`grep -n "^from\|^import"
solus/gazebo_server.py`); `xml.etree` is used only through `spawn._parse_guarded` (size cap,
      DOCTYPE/ENTITY refusal, loader-element walk) — the one XML parser of the fork.

## 2. Least privilege

- [x] Subprocesses: every argv starts with the pinned `Family.exe` (or a sibling in the same
      `bin_dir`), no `shell=`, scrubbed env (`sim_child_env`: `PATH=/usr/bin:/bin`, `LANG`, the
      `env.allow` names) — `test_every_argv_starts_with_the_pinned_binary_and_never_a_shell`.
- [x] Simulator processes: ONE owned per fork process (`WorldSessions`), `start_new_session=True`,
      killed ONLY by process group through the Popen handle the fork holds (SIGTERM, 5 s, SIGKILL,
      5 s) — never by name or pattern; attached (user-started) worlds hold no process and `stop`
      on them is refused with `not_owned` — `test_close_kills_only_owned_process_groups`,
      `test_stop_refuses_attached_session`, `test_unresponsive_owned_process_gets_a_bounded_sigkill`.
- [x] Filesystem: world files resolve against `SOLUS_SIM_ROOTS` through `worlds.read_confined`
      (fd-relative `O_NOFOLLOW`); `save_world` writes only through `worlds.confined_write` (O_EXCL
      sibling temp + rename, regular-file leaf) into the world's own root; models only from
      `.solus/sim/models/<sha256>/` after `ModelAssets.verified_dir` re-verifies every byte.
- [x] Nothing model-supplied reaches argv as an option or as text-format syntax: `check_name`
      guards every world/model/joint/spawn name again inside the adapters (defence in depth behind
      `tool_args`) — `test_argv_never_contains_a_shell_or_user_string_as_option`.

## 3. Sandbox posture

Unchanged from the P3-T1 declaration; now exercised: the fork's simulator children inherit the
scrubbed env plus the user's named passthrough (`LD_LIBRARY_PATH` residual below), a private
`HOME` under `<workspace>/.solus/sim/home`, cwd = that HOME, their own session/process group.

## 4. Secret hygiene

- [x] `os.environ` reads in `solus/`: `SOLUS_GAZEBO_PATH` (family_detect), `SOLUS_SIM_ROOTS`
      (worlds), `SOLUS_MCP_WORKSPACE` (server entrypoint), the `env.allow` names (adapter_base
      `sim_child_env`). Nothing else.
- [x] Results carry no absolute paths: `refused()` runs `redact_paths` over every reason; CLI
      stderr reaches a reason only through `stderr_detail` (last line, path-redacted, ≤ 200
      chars); previews name root-relative paths only — `test_results_never_carry_absolute_paths`,
      `test_cli_failures_and_unexpected_errors_are_results`. Residual: `spawn` passes the
      ABSOLUTE spawn-file path to the simulator (`sdf_filename:` / `gz model -f`) because the
      simulator needs it; it is under the linked workspace and never echoed back.
- **Residual (Q4): `LD_LIBRARY_PATH` passthrough** — unchanged, see the P3-T1 entry.

## 5. Untrusted I/O

- [x] Tool inputs are hostile: `tool_args` is now `strict=True` as well as `extra="forbid"` —
      `"3"` is not `3`, `"false"` is not `False` (`test_unknown_tool_and_invalid_arguments_are_
results_not_exceptions`); validation reasons carry field locations and messages, never the
      input (`validation_reason`, `include_input=False`).
- [x] Simulator output is hostile: protobuf text format parsed with a depth bound (16) and a size
      bound (8 MiB), unknown escapes kept literally, never raises past `CliError`; JSON lines
      parsed per line, non-objects dropped; joint windows decimated to ≤ 200 samples.
- [x] Model store: chunks ≤ 72 KiB raw, ≤ 32 MB per model, ≤ 20 MB per file, ≤ 32 manifest
      entries, exactly one top-level `.urdf`/`.sdf`; `sha256` MUST equal the canonical-manifest
      digest (the API's `Asset.sha256`), every file's bytes MUST match before ONE atomic rename
      promotes `<sha256>.partial/` → `<sha256>/`; symlinks, special files, extra files or edited
      bytes fail re-verification at spawn — `test_put_asset_bad_hash_discards_partial`,
      `test_verified_dir_rechecks_bytes_and_refuses_tampering_symlinks_and_extras`,
      `test_interrupted_put_asset_never_promotes_and_restarts_cleanly`,
      `test_spawn_refuses_unverified_model_dir`.
- [x] Generated/stored model XML is still treated as untrusted before the simulator loads it:
      `spawn.wrap_model` refuses DOCTYPE/ENTITY, `<plugin>`, `<include>`, `<gazebo>`,
      `<transmission>`, `<script>`, `<extension>`, namespaces, URI schemes and absolute/`..`
      paths in the input AND in the converter's output, then adds Solus's own systems.
- [x] The never-raises invariant: `GazeboToolService.call` maps `Unsupported`, `CliError`,
      `SessionRefusedError`, `ValueError`, `OSError`/`TimeoutError` and any other exception to
      `{ok: false, code, reason}`; the MCP boundary adds nothing but `wire_encode` —
      `test_service_never_raises_for_any_tool_with_garbage`.

## 6. Destructive actions

- [x] Every mutating tool (`open_world spawn set_joint_targets control run_routine stop
save_world`) answers `dry_run: true` with a complete `{ok, dry_run, preview: [{label, before,
after}], fingerprint}` and performs nothing (no process, no file, no publish) —
      `test_every_mutating_tool_dry_runs_to_a_complete_preview`.
- [x] `save_world` on Classic 11 is `{ok: false, code: unsupported_on, family, version, reason}`
      with one sentence, before any file is touched — `test_unsupported_cell_returns_unsupported_
on_with_one_sentence`.
- [x] `run_routine` wall time ≤ `duration_s + 10` (clock-checked loop, bounded readback window),
      ≤ 16 joints per target set, sweep targets every 0.25 s.

## 7. Code-review depth

- Tier 1 (100% line-read, agent draft): every file under `solus/` and `bin/`. Human line-read
  pending.

## 8. Update path

- [ ] Both PROVENANCE sign-off lines dated against the shipping commit — humans.

Ordinary verification (2026-11-09): `uv run pytest -q integrations/mcp/gazebo/tests` → 253
passed; `integrations/mcp/tests` → 20 passed; ruff and mypy clean on `solus/`; `uv run mypy
packages/api/src` clean. Launcher proven end to end: `SOLUS_MCP_PYTHON=<repo .venv python>
SOLUS_MCP_WORKSPACE=<scratch> integrations/mcp/gazebo/bin/launch` answered MCP `initialize`
(`solus-gazebo`), `list_tools` (13) and `probe` over stdio; with
`SOLUS_GAZEBO_PATH=/opt/ros/jazzy/opt/gz_tools_vendor/bin` and the shell's `GZ_*`/`LD_LIBRARY_PATH`
passed through, `probe` reported `gz 8.15.0 (Harmonic)` and its capability row. No simulator
process was started by any test or by the launcher check; the fixture CLIs replay stdout recorded
from Harmonic 8.15.0 and Classic 11.15.1 (the ign6 fixture is authored, see its header).

Addendum (2026-11-09, P3-T3 review fix, §2 least privilege): `open_world` refuses with
`world_already_running` when `adapter.running_worlds()` already lists the requested `<world name>`
before `adapter.start` — a user-started world is never re-labelled as Solus-owned (every later
call addresses the world by name over the shared transport, and the API cards nothing inside an
owned world). Readiness is the name appearing only AFTER the owned process started —
`test_open_world_refuses_a_name_the_user_is_already_running`,
`test_open_world_refuses_a_world_the_user_already_runs`. Fixture knob
`GZ_PARTITION=solus-fixture-idle` (authored: no server up) models the cold start.
Verification: `uv run pytest -q integrations/mcp/gazebo/tests integrations/mcp/tests` → 284 passed.

Addendum (2026-11-09, P3-T3 review fixes, §2 least privilege / §5 untrusted I/O):

- **Fail-closed running check.** `WorldSessions._running_now` used to map a `CliError` from
  `adapter.running_worlds()` to "nothing running", so a transport outage during `open_world` could
  start an owned simulator beside an unseen user world of the same name. It now raises
  `SessionRefusedError("transport_unavailable", "could not list running worlds, so Solus cannot
prove the world is free; retry or attach")` and `adapter.start` is never reached —
  `test_open_world_fails_closed_when_running_worlds_cannot_be_listed`.
- **Manifest file-type allowlist.** `put_asset` now requires EVERY manifest path (not only the
  top-level model file) to end, case-insensitively, in one of `.urdf .sdf .xml .stl .dae .obj
.mtl .png .jpg .jpeg .config`. `.so .py .dylib .sh`, extension-less names and double extensions
  such as `model.sdf.so` are refused at chunk 0 with `unsupported_file_type` before the partial
  directory exists — `test_put_asset_refuses_manifest_entries_outside_the_file_type_allowlist`,
  `test_put_asset_accepts_every_allowlisted_type_case_insensitively`. The top-level model file
  itself stays lower-case `.urdf`/`.sdf` (`model_file_of` unchanged; `spawn` picks the Classic
  wrapper suffix from it).
- **Accepted residual: no per-launch transport partition.** Owned servers are NOT yet isolated by a
  per-session `GZ_PARTITION` / `IGN_PARTITION`; every adapter CLI call shares the host's default
  transport, so owned-world identity rests on the pre-start absence check (now fail-closed) plus
  readiness-after-start. Upgrade path: mint a partition per owned session and thread it through
  every adapter CLI call (`start`, `running_worlds`, `topic`/`service` readers) so an owned world
  is addressable only on its own partition. Classic 11 has no partition knob; its identity
  argument stays the absence check.

Verification: `uv run pytest -q integrations/mcp/gazebo/tests integrations/mcp/tests` → 292
passed; `ruff check`/`ruff format` clean on `integrations/mcp/gazebo`; `uv run mypy
packages/api/src` clean (unchanged); `uv run mypy integrations/mcp/gazebo/solus` clean.

---

# Fork security review — `gazebo` — 2026-11-10 (P10: `exposure: internal`; human ratification and sign-off 1)

Appended entry; nothing above is rewritten. Scope: `allowlist.yaml` (server-level
`exposure: internal`, commit `e5266473`), the P9 fixes already reviewed in the entries above,
and the reviewed tree at `408fb7e2` (`d6e1a8e4383ba4828d2fc905b679eb8755068fdf`).

## Decisions taken by the human reviewer in chat (2026-11-10)

- [x] `allowlist.yaml` server-level `exposure: internal` ratified by Pratham Madaram (integrations/mcp/CLAUDE.md
      rule 2). No tool entry added, no `requires_confirmation` flipped; the key only restricts
      exposure. Loader test: `packages/api/tests/test_bridge_internal_exposure.py` expects
      `internal == {"drive", "gazebo", "isaac"}`; runtime drops the raw specs by flag AND by
      name (`runtime._internal_only`, both paths tested in `tests/test_sol_runtime.py`).
- [x] The API wrappers' per-call hooks now honour an `Approval required` preview row from this
      fork (`dynamic_gate.APPROVAL_REQUIRED_LABEL`, commit `b743b0c2`): a row with that label
      cards even on a Solus-owned session. This fork emits no such row today; emitting one can
      only make a call stricter.
- [x] Reviewer 1 sign-off recorded in `PROVENANCE.md` against `408fb7e2`.
- [ ] Reviewer 2 — a second human; the fork does not ship on one signature.
- [x] Residual `GZ_IP`/`IGN_IP`/`GAZEBO_IP` passthrough (`f19378b6`, §2026-11-09 entry above):
      explicit yes from Pratham Madaram in chat on 2026-11-11 (recorded by the agent on that
      instruction); completion report §11 item 18 closed. Reviewer 2 still reviews the entry.

## 8. Update path

- [x] Reviewer 1 line dated against `408fb7e2`; Reviewer 2 pending.

Verification at this entry (P10 rerun, `docs/qa/acceptance/P8-suites.md` §"P10 rerun"):
`uv run pytest -q integrations/mcp/gazebo/tests integrations/mcp/isaac/tests integrations/mcp/tests`
→ 506 passed; `ruff check .` clean; `mypy packages/api/src packages/companion/src livebench/src`
→ 687 files clean.
