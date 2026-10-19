# `integrations/mcp/code/` — the Solus-authored `code` MCP server

The second Pattern-1 (ADR-031) server with **no upstream**: 100% Solus code, launched by the
bridge companion on the user's machine with `SOLUS_MCP_WORKSPACE` = the folder the user linked
to a project. It is the project's **Code environment** on THIS machine: it probes the
interpreters and the workspace virtualenv, and — under the ADR-031 amendment of 2026-09-07 —
creates the venv, installs packages, runs scripts and tests in the USER's environment, every
command an argument list assembled by Solus code, confirmation-gated with the exact argv on the
approval card, workspace-confined, and bounded.

Authoritative tool contracts: `docs/api/code-command-execution.md` (SOLUSDEV-317: `exec`,
`process_*`, `profile_*`, the sandbox), `docs/api/code-environment.md` §4 and
`docs/api/code-git-development.md` and `docs/api/code-arduino-development.md` (names, arguments, answers,
caps, the never-raises rule). The scan-side half of the feature (dependency parsing) lives in
the `local` fork (`../local`, §3 of the same doc).

## What is in this directory

| Path                    | Contents                                                                                                                                                                                      |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bin/launch`            | The ONLY entrypoint. Fixed argv, `env -i` scrub to the allowlist declared in `solus/env_allowlist.py` (local's set + `VIRTUAL_ENV`), `PATH=/usr/bin:/bin`, fork-private `.venv/bin/python3`, zero network I/O. |
| `allowlist.yaml`        | `server: code` + twenty-two tools: eight reads and fourteen confirmation-required actions. Single source of truth for discovery, the cloud ingress gate, and `solus/roster.py`. |
| `solus/`                | The server: `server.py` (FastMCP entry), `workspace.py` (fail-closed root + confinement, verbatim from `local`), `plan.py` (pure argv assembly + validation), `execute.py` (bounded, scrubbed execution), `probe.py`, `roster.py`, `env_allowlist.py`, `env.allow`; SOLUSDEV-317: `command_plan.py` + `command_deny.py` (exec planning and deny table), `sandbox.py` + `git_guard.py` + `landlock_exec.py` (OS sandbox), `profiles.py`, `processes.py` + `process_os.py`. |
| `requirements.lock.txt` | Hash-pinned `mcp` closure — byte-identical below the header to `../local/requirements.lock.txt`. `scripts/install-mcp-forks.sh` materializes `.venv/` from it; `.venv/` is gitignored.    |
| `PROVENANCE.md`         | Identity, license (MIT, Solus), no-upstream statement, exposed tools, blank sign-offs.                                                                                                       |
| `SECURITY_REVIEW.md`    | DRAFT checklist with pasted evidence — awaiting both human sign-offs.                                                                                                                        |
| `tests/`                | Launcher/allowlist/lockfile/provenance law plus unit tests for every module; `uv run pytest integrations/mcp/code -q`. Rootless `test_code_*.py` files (see `tests/code_paths.py` for why). |

## Tools

- `probe_environment {}` — `{python, interpreters (≤ 8), venv, conda, uv}`. Interpreters are
  `shutil.which` over `python3`, `python3.12`, `python3.11`, `python3.10`, `python` (deduplicated
  by real path), versions via `[exe, "--version"]` (10 s). The venv is the first of `.venv`,
  `venv`, `env` under the workspace carrying `bin/python` (or `Scripts/python.exe`), reported by
  its relative name with `python_version` and `packages` from
  `[venv_python, -m, pip, list, --format, json]` (60 s, ≤ 300 then `truncated`). `conda` = `[conda,
  env, list, --json]` names (≤ 32); `uv` = `{path, version}`. Any failing probe is null/empty.
- `plan {action, args}` — `{argv, cwd: ".", ok, reason}`: the EXACT argv the action would run,
  or the refusal. **Pure** — nothing is executed or created. This is what the approval card
  shows, and what the gated tool then executes (one source of truth).
- `create_environment {path?: ".venv", python?: "3.12"}` — `uv venv --python X <path>` when uv
  is present, else `python3.X -m venv <path>` (refused when neither exists). Refuses an existing
  path, a path outside the workspace, a version not shaped `3.X`.
- `install {packages: [≤ 64], environment?: ".venv"}` — `uv pip install --python <env>/bin/python
  -- <pkgs…>` (uv present) or `<env>/bin/python -m pip install -- <pkgs…>`. Each package must be a
  PEP 508 `name[extras][specifier]`: no leading `-`, no `://`, no `/` or `\`, no whitespace,
  ≤ 128 chars. The environment must be an existing venv inside the workspace.
- `run {script, args?: [≤ 32], environment?, timeout_seconds?: ≤ 600}` — `<env>/bin/python
  <script> <args…>`; the script must be a file inside the workspace and may not start with `-`;
  args are the script's own (option-shaped is fine, NUL/newline are not).
- `test {target?: "tests", environment?, timeout_seconds?}` — `<env>/bin/python -m pytest -q --
  <target>`; the target must exist inside the workspace.

The four environment actions answer `{ok, argv, cwd, exit_code, stdout_tail, stderr_tail, duration_ms,
timed_out, reason}` (+ `path` for `create_environment`); `ok` = exit 0; a refusal is
`{ok: false, exit_code: null, reason, …}` and never reaches the executor.

### Repository tools (SOLUSDEV-261)

`git_status`, `git_log` and `git_diff` observe the linked ordinary repository.
`git_commit` commits only the already staged index; `git_push` sends one exact
commit to one explicitly previewed branch. Both require a complete state-bound
dry-run approval. The commit preview includes the full branch ref and staged patch,
including significant whitespace. Changed branch/index/HEAD or destination refuse.
Git refusals use MCP errors. Post-write verification failures carry `uncertain:true`
and require inspection, never automatic retry. No generic shell or staging tool.

Git's executable and SSH client are pinned to trusted system roots, configuration
and subprocess behavior are restricted, and output/time are bounded. Ignore
dependency directories when validating the worktree; validate actual tracked paths
and Git metadata. Unsupported attributes, tracked symlinks, external Git directories
and conflicts are explicit limitations. Production push currently supports existing
native SSH identities for GitHub/GitLab only; it never adds host keys or credentials.
Final results are not an incremental terminal stream. See the API supplement for
exact schemas, constraints and local-versus-live evidence.

## How a command runs (`solus/execute.py`)

- `cwd` = the workspace. Argv paths are **workspace-relative** (`.venv/bin/python`,
  `policy/train.py`) so no absolute machine path crosses the bridge; a system tool is its bare
  name (`uv`, `python3.12`) and is resolved at execution against the PINNED search roots
  (`/usr/bin`, `/bin`, `/usr/local/bin`, `/opt/homebrew/bin`, the documented conda/uv/pipx
  user roots — `SEARCH_ROOTS`), never the inherited PATH. A relative interpreter must live
  inside the workspace (the venv directory is confined; the interpreter file itself may be the
  symlink every venv has).
- Scrubbed child environment: exactly `PATH` (`<env>/bin` + `/usr/bin:/bin`), `HOME`, `LANG`,
  `TMPDIR`, `VIRTUAL_ENV` (= the workspace venv, never the inherited one).
- `start_new_session=True`; a timeout SIGKILLs the whole process group; stdin is closed;
  stdout/stderr are spooled to temp files and tailed to 16 KiB each.
- `install` reaching PyPI is the USER's pip/uv under the amendment; the server itself performs
  zero network I/O at launch.

## Platform notes

- macOS / Linux: as above. Windows: `Scripts/python.exe` layouts are recognised by `plan`, but
  **no `bin/launch.cmd` ships** — the companion refuses the server on Windows until a human
  approves a Windows twin.

## Re-review

There is nothing to re-vendor. Any change to `bin/launch`, the env allowlist, `allowlist.yaml`,
`SEARCH_ROOTS`, or `requirements.lock.txt` voids the sign-offs in `PROVENANCE.md`.

## Arduino compilation

`arduino_probe` verifies the pinned CLI and frozen dependencies without launching
the CLI. `arduino_prepare` and `arduino_compile` require complete approval previews.
Preparation installs the pinned dependency closure into the owned application runtime;
compilation snapshots a linked Uno sketch and runs offline in Bubblewrap, exposing
only the verified toolchain and isolated job. Successful builds publish verified
immutable artifacts. Neither tool identifies, opens or flashes attached hardware.
The API plan documents limits, cancellation, failures and setup requirements.

## Command execution, processes and profiles (SOLUSDEV-317)

Contract: `docs/api/code-command-execution.md`. All confirmation-gated except the two reads.

- `exec {argv, cwd?, environment?, profile?, timeout_seconds?: 1–600 (120)}` — one argument
  list, never a shell. `argv[0]` resolves to an absolute program without the inherited PATH
  (workspace file → absolute in an allowed root → `<env>/bin` → profile PATH →
  `SEARCH_ROOTS`); `solus/command_deny.py` refuses shells, wrappers, elevation, inline code
  and git command injection. Answers the `run` shape plus `sandbox` and
  `git_metadata_changed`; output streams like `run`/`test`.
- `process_start {argv, cwd?, environment?, profile?, name?, max_runtime_seconds?: 60–14400}`,
  `process_stop {process_id}`, `process_status {process_id?, cursor?}` — at most 4 running,
  16 entries kept 30 min, 256 KiB line ring per process; stopped on server exit and
  reaped by start token on the next start; never restarted.
- `profile_capture {name, setup_file, extends?}`, `profile_list {}`, `profile_delete {name}` —
  a fixed Solus script sources the setup file inside the sandbox; the filtered variables are
  stored in `~/.solus/code-profiles/<workspace key>/` (0600); answers carry names only.
- `plan` answers every action with `sandbox {kind, writable, limitations}`, `profile
  {name, digest}` and `environment`.

**Sandbox (every executing tool).** macOS: root-owned `/usr/bin/sandbox-exec` with a constant
profile; Linux: `solus/landlock_exec.py` (Landlock ABI ≥ 1, kind `landlock-abi<N>`). Writes are
limited to the workspace, temp, a few devices and the declared HOME caches; git metadata and
`~/.solus` are protected (by profile on macOS, by detection on Linux). No sandbox → refused.
