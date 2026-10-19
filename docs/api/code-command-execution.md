# Code command execution — SOL runs commands (SOLUSDEV-317)

Route plan, tool contract and wire shapes. Tier-1 (ADR-032). Authority: DECISIONS.md ADR-031
amendment of 2026-10-18 (SOLUSDEV-317). Extends `code-environment.md` (the `code` server, the
`code.plan` preview, the one-use plan snapshot, incremental `tool_output`) and
`local-machine-actions.md`. Where this document and the "no generic command executor"
sentences of those documents disagree, this document wins.

## 1. What changes

Before SOLUSDEV-317, SOL could only run the typed verbs of the `code` server (venv create,
pip install, `python <script>`, `pytest`, git, Arduino). Everything else it could only print.
This feature adds:

| Capability                              | Tools                                                                                                               | Gated |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ----- |
| One-shot command                        | `code.exec`                                                                                                         | yes   |
| Long-running process                    | `code.process_start`, `code.process_stop`                                                                           | yes   |
| Process observation                     | `code.process_status`                                                                                               | no    |
| Environment profiles (ROS `setup.bash`) | `code.profile_capture`, `code.profile_delete`                                                                       | yes   |
| Profile listing                         | `code.profile_list`                                                                                                 | no    |
| OS sandbox                              | applied by the server to `create_environment`, `install`, `run`, `test`, `exec`, `process_start`, `profile_capture` | —     |

Invariants (ADR-031 amendment):

1. **argv only.** No shell string ever reaches a process. The model proposes a JSON list; the
   server resolves `argv[0]` to an absolute program and executes the list directly.
2. **Every execution is confirmed** on the central approval card. Build mode never executes a
   command automatically; none of these tools is an owned routine (`execution_policy.py`).
   The desktop's Cmd/Ctrl+Enter is an approval gesture on a visible card, not a bypass.
3. **Sandboxed or refused.** macOS: `/usr/bin/sandbox-exec`. Linux: Landlock (ABI ≥ 1).
   Anything else, or a failed probe: the plan answers `ok: false`, reason
   `"sandbox unavailable: <why>"`, and nothing runs.
4. **Denied programs** (§4) are refused by the cloud `CommandPolicy` before a card exists and
   again by the server's planner.
5. **Output is untrusted.** Ingress redaction applies to tails, progress chunks and process
   output exactly as for `code.run`.

## 2. The `code` server — new tools

All arguments are validated with strict Pydantic models (`extra="forbid"`, `strict=True`),
like the git/Arduino tools. Every tool returns a dict and never raises.

### 2.1 `code.exec` (gated, streams output)

Args:

```json
{
  "argv": ["colcon", "build", "--symlink-install"],
  "cwd": "ros_ws",
  "environment": ".venv",
  "profile": "ros",
  "timeout_seconds": 300
}
```

- `argv`: 1–64 strings, each 1–1024 chars, no NUL, CR or LF.
- `cwd`: workspace-relative directory (default `"."`), `is_safe_relative` + `resolve_inside`.
- `environment`: optional workspace venv, validated exactly like `code.run`'s (pyvenv.cfg +
  interpreter outside the workspace). No implicit default for `exec`.
- `profile`: optional profile name (§2.4).
- `timeout_seconds`: 1–600, default 120.

Result: the `code.run` result shape plus `sandbox`:
`{ok, argv, cwd, exit_code, stdout_tail, stderr_tail, duration_ms, timed_out, reason,
sandbox: "sandbox-exec" | "landlock" | null, git_metadata_changed: bool}`.
`argv[0]` in the result is the resolved absolute program path.

**Program resolution** (`argv[0]`), first match wins; the inherited `PATH` is never consulted:

1. Contains `/` and is relative → workspace-relative file (`./scripts/build.sh`,
   `tools/flash`), resolved inside the workspace, regular, executable.
2. Absolute → allowed only when its parent directory is one of the roots in steps 3–5.
3. Bare name → `<environment>/bin` when `environment` is given.
4. Bare name → the profile's `PATH` entries, in order (absolute, existing directories only).
5. Bare name → `execute.SEARCH_ROOTS` (unchanged).

The planner also refuses a resolved program whose basename (or realpath basename) is denied (§4).

### 2.2 `code.plan` — new actions

`code.plan {action: "exec" | "process_start" | "profile_capture", args}` plans these tools.
The answer for every action (old and new) gains three fields:

```json
{
  "argv": ["/opt/ros/jazzy/bin/colcon", "build", "--symlink-install"],
  "cwd": "ros_ws",
  "ok": true,
  "reason": null,
  "sandbox": {
    "kind": "sandbox-exec",
    "writable": ["<workspace>", "<tmp>", "~/.ros", "..."]
  },
  "profile": { "name": "ros", "digest": "<sha256 of the stored profile file>" },
  "environment": ".venv"
}
```

`sandbox` is null only when `ok` is false. `profile` is null when no profile is used. The
cloud fingerprint (§5.2) covers argv, cwd, environment, profile digest and sandbox kind, so a
re-captured profile or a changed sandbox invalidates an approval.

### 2.3 Long-running processes

`code.process_start` (gated, returns immediately): args = the `exec` args without
`timeout_seconds`, plus `name?` (1–64 printable chars, a label) and
`max_runtime_seconds?` (60–14400, default 3600).
Result: `{ok, process_id, pid, argv, cwd, started_at, sandbox, reason}`.

`code.process_status` (read): args `{process_id?: str, cursor?: int ≥ 0}`. Result:

```json
{
  "processes": [
    {
      "process_id": "…",
      "name": "bringup",
      "argv": ["…"],
      "cwd": "ros_ws",
      "state": "running",
      "pid": 4242,
      "exit_code": null,
      "started_at": "…",
      "ended_at": null,
      "sandbox": "landlock"
    }
  ],
  "output": {
    "process_id": "…",
    "chunks": [{ "seq": 1, "stream": "stdout", "text": "…" }],
    "cursor": 1,
    "truncated": false
  }
}
```

`state` is `running | exited | stopped | timed_out | failed_to_start`. `output` is present only
when `process_id` is given: chunks with `seq > cursor`, at most 64 KiB per answer.

`code.process_stop` (gated when SOL proposes it; also reachable by the user's own button, §6):
args `{process_id}`. Sends SIGTERM to the process group, SIGKILL after 5 s. Result
`{ok, process_id, state, exit_code}`.

Bounds and lifetime:

- At most **4** running processes per server; a fifth start is refused.
- Finished entries are kept 30 minutes, at most 16 entries in total.
- Output: complete lines ≤ 2048 chars (`LineOutput` rules), a ring of 256 KiB per process;
  older chunks are dropped and `truncated` is set.
- `max_runtime_seconds` elapsed → group killed, `state: timed_out`.
- Server shutdown (stdin EOF, SIGTERM, SIGINT) stops every process (SIGTERM, 5 s, SIGKILL).
  The companion restarts the server on project link/unlink, so unlink kills processes.
- Orphan reaping: each start records `{pid, pgid, start token}` in
  `~/.solus/code-processes/<workspace key>.json`; on server start, entries that are still alive
  **with the same start token** are killed and the file is cleared. Nothing is restarted.
- `process_*` is never replayed by the companion after a failure.

### 2.4 Environment profiles

A profile is the environment produced by sourcing a setup file (ROS `setup.bash`, a workspace
`install/setup.bash`, a vendor `env.sh`).

`code.profile_capture` (gated): args
`{name: "^[a-z0-9][a-z0-9_-]{0,31}$", setup_file: str, extends?: profile name}`.

- `setup_file` is either workspace-relative (resolved inside the workspace) or absolute with a
  realpath under `/opt/ros/`. It must be a regular file ≤ 256 KiB ending `.bash` or `.sh`.
- Execution, sandboxed, `cwd` = workspace, 30 s timeout, stdin closed, the base environment is
  the scrubbed child environment (plus the `extends` profile's variables when given):
  `["/bin/bash", "--noprofile", "--norc", "-c", CAPTURE_SCRIPT, "solus-profile", <setup_file>]`
  where `CAPTURE_SCRIPT` is the fixed Solus constant
  `'source "$1" >/dev/null 2>&1 </dev/null || exit 97; exec /usr/bin/env -0'`.
  The setup file is an argument (`$1`), never interpolated.
- The `env -0` output (≤ 256 KiB) is diffed against the base. Variables that are new or changed
  are kept, except names that are invalid (`^[A-Za-z_][A-Za-z0-9_]{0,127}$`), secret-shaped
  (case-insensitive `TOKEN|SECRET|PASSW|KEY|CREDENTIAL|AUTH|COOKIE|SESSION|PRIVATE`, prefixes
  `AWS_ GITHUB_ GH_ GITLAB_ NPM_ HF_ OPENAI_ ANTHROPIC_`, and `SSH_AUTH_SOCK`), or loader
  injection names (`LD_PRELOAD LD_AUDIT DYLD_INSERT_LIBRARIES BASH_ENV ENV
  PROMPT_COMMAND PYTHONSTARTUP`). `LD_LIBRARY_PATH`/`DYLD_LIBRARY_PATH` are kept (ROS needs them). At most 256 variables, each value ≤ 8192 chars.
- Stored at `~/.solus/code-profiles/<workspace key>/<name>.json`, written atomically
  (temp + rename, file 0600, directories 0700),
  `{schema_version: 1, name, setup_file, extends, captured_at, vars: {…}}`. The workspace key
  is the first 16 hex characters of sha256(realpath(workspace)).
- Result: `{ok, name, variables: [names], dropped: [names], path_entries: int, reason}`.
  **Values are never returned to the cloud.**

`code.profile_list` (read): `{profiles: [{name, setup_file, extends, captured_at, variables:
[names]}]}`. `code.profile_delete` (gated): `{name}` → `{ok, name}`.

Applying a profile (`exec`, `process_start`): the child environment is the scrubbed environment,
overlaid with the profile's variables. `HOME`, `TMPDIR` and `VIRTUAL_ENV` stay Solus-controlled;
when `environment` is also given, the venv `bin` directory is prepended to the profile's `PATH`.
A missing or unreadable profile refuses the plan.

## 3. The sandbox

`solus/sandbox.py` in the server wraps the final argv for every executing tool listed in §1.
Arduino keeps its existing bubblewrap posture; git tools are not changed.

Writable set (everything else is read-only; reads, exec and network are not restricted):

- the workspace (realpath), which contains any selected venv;
- the process temporary directory (`TMPDIR` realpath, `/private/tmp`, and on macOS this user's own Darwin cache dir — the `C`
sibling of `TMPDIR`, never all of `/private/var/folders`; `/tmp` and `/var/tmp` on Linux);
- device nodes `/dev/null`, `/dev/zero`, `/dev/tty`, `/dev/fd/*`, and serial devices
  (`/dev/cu.*`, `/dev/tty.*` on macOS; `/dev/ttyUSB*`, `/dev/ttyACM*` on Linux);
- declared tool caches under `HOME`: `.cache`, `Library/Caches`, `.ros`, `.npm`, `.pnpm-store`,
  `.local/share/pnpm`, `.local/share/uv`, `.cargo/registry`, `.cargo/git`, `.platformio`,
  `.arduino15`, `.gradle`, `.colcon`. Adding a cache is a SECURITY_REVIEW re-review trigger.

Denied even inside the workspace: on macOS, the whole workspace gitdir is read-only (the `.git`
entry and everything beneath it, plus the gitdir a `.git` file points to when that resolves
inside the workspace). Sandboxed commands can read the repository but cannot write it. Git
writes go through the dedicated git tools. On Linux, the protected metadata (`config*`,
`hooks/**`, `info/**`, `commondir`, `gitdir`, all of `modules/**` metadata, `worktrees/**`,
`.gitmodules`) is guarded by detection (below). `~/.solus/**` is denied everywhere.

macOS IPC hardening: the profile denies `process-exec` of `/bin/launchctl`,
`/usr/bin/osascript`, `/usr/bin/osacompile`, `/usr/bin/open`, `/usr/bin/automator` and
`mach-lookup` of `com.apple.coreservices.appleevents`, `com.apple.coreservices.launchservicesd`
and `com.apple.lsd.*`. launchd job submission is not blocked and is listed in `limitations`. Linux: with Landlock ABI ≥ 6 the
ruleset also scopes abstract unix sockets and signals.

The plan answer's `sandbox` object is `{kind, writable, limitations}`. `kind` is
`sandbox-exec` or `landlock-abi<N>`. `limitations` lists the known gaps for that kind, for
example `truncate not confined` (Landlock ABI < 3), `file metadata changes not confined`, or
`unix-socket/signal scoping unavailable` (ABI < 6). The card shows them. Landlock ABI ≥ 1 is
accepted, so Jetson-class 5.15 kernels work, with their limitations shown.

**macOS:** `["/usr/bin/sandbox-exec", "-p", PROFILE, "-D", "WORKSPACE=…", "-D", "TMP=…",
"-D", "HOME=…", program, *args]`. `PROFILE` is a Solus constant
`(version 1)(allow default)(deny file-write*)(allow file-write* …params…)` followed by the
explicit denials above. `sandbox-exec` must be the root-owned `/usr/bin/sandbox-exec`.

**Linux:** `[<server python>, "-I", "<fork>/solus/landlock_exec.py", "--rw", <path>, …, "--",
program, *args]`. The helper is Solus-authored, has no dependencies, sets
`PR_SET_NO_NEW_PRIVS`, creates a Landlock ruleset handling the filesystem write rights of the
best available ABI (`WRITE_FILE, REMOVE_DIR, REMOVE_FILE, MAKE_*`, `REFER` ≥ ABI 2, `TRUNCATE`
≥ ABI 3), adds `PATH_BENEATH` rules for the writable set, calls `landlock_restrict_self`, then
`os.execv`. Landlock only grants, so the protected-gitdir denial is enforced by detection: the server
hashes the full contents and modes of every protected path before and after every sandboxed
command. If a count or size cap is hit, the result counts as changed (fail closed); a change sets
`git_metadata_changed: true` in the result, the cloud shows it in the outcome, and the change is
reported (never silently kept or reverted). macOS reports the same flag (it should stay false).

Probe: `sandbox.available() -> (kind | None, reason)`, cached for the server's lifetime;
Linux probes `landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)`.

## 4. Command policy (cloud `CommandPolicy`, mirrored deny table in the server)

`solus_api/agent/command_policy.py` is pure: `classify(argv: Sequence[str]) -> CommandVerdict
{denied: bool, reason: str | None, risks: tuple[Risk, ...]}`. The program name is the basename
of `argv[0]`, with a trailing version suffix stripped for interpreters (`python3.12` →
`python`).

**Denied** (also refused by the server planner; both tables are cross-checked by a test):

- Shells: `sh bash zsh fish dash ksh csh tcsh pwsh busybox rbash ash mksh yash elvish nu xonsh
  oksh posh`.
- Command wrappers: `env xargs nohup setsid nice timeout time watch script expect
  sandbox-exec launchctl open osascript busybox stdbuf chroot unshare nsenter flock ionice
  taskset caffeinate arch chrt systemd-run setpriv prlimit unbuffer fakeroot proot firejail
  cpulimit faketime`.
- Privilege elevation: `sudo su doas pkexec runuser`.
- Inline code: `python -c`/`-<flags>c`, `node -e/--eval/-p/--print`, `ruby -e`, `perl -e/-E`,
  `php -r`, `lua -e`, `deno eval`, `bun -e/--eval`, `Rscript -e`.
- Git: `git` and every `git-*` helper (`git-upload-pack`, `git-receive-pack`, `git-shell`, …)
  are denied in `code.exec`/`code.process_start`. SOL uses the dedicated `code.git_status`,
  `code.git_log`, `code.git_diff`, `code.git_commit` and `code.git_push` tools. Git's option
  grammar (abbreviations, short-option clusters, per-verb command options, config injection)
  cannot be denied reliably, so it fails closed.
- Interpreter option parsing fails closed: an inline-code flag anywhere among the leading
  options (including combined short flags) denies, and so does an unknown leading option.
  Also denied: node `--import/--loader/--experimental-loader/--require/-r` with `data:` or
  `http(s):` values, the same specifiers for deno, `deno eval|repl`, `bun -p/--print`, and
  `php -B/-R/-E/-F`, php `-d` setting `allow_url_include`/`auto_prepend_file`/`auto_append_file`,
  perl `-M/-m` and ruby `-r/-I` values that are not plain module names, node `--inspect*` bound
  to a non-loopback host, and any specifier with a URL scheme other than `file:` (after trimming
  whitespace and control characters) for node, deno and bun.

Program names are normalised case-insensitively and fail closed by prefix: a basename that
starts with a known interpreter or shell name followed by a non-letter maps to it
(`python3.12-intel64`, `perl5.34-thread-multi`, `php-cgi`). Version and build suffixes, `-dbg` and a
trailing `w` are stripped, and `nodejs`→`node`, `pypy*`→`python`, `luajit`→`lua`. The server
checks both the `argv[0]` basename and the resolved realpath basename.

**Risks** (badges on the card; never a denial): `network`, `install`, `destructive`,
`hardware`, `remote`, `runs_shell` (allowed programs that can run shell text: `find -exec/-execdir/-ok`, `awk`,
`sed` with `e`), `project_scripts` (runs code defined by the project: `make`, `npm run`,
`pnpm run`, `yarn run`, `colcon build`, `cmake --build`, workspace-relative executables).
The full table lives in the module and its tests.

A denied call is refused **before parking** with `INVALID_ARGS` and a message that tells SOL
to propose a direct argv instead (no shell, no `&&`, no pipes).

## 5. Cloud: tools, cards, outcomes

### 5.1 Registration

`allowlist.yaml` entries (`requires_confirmation`, `timeout_seconds`):
`exec` true/630, `process_start` true/30, `process_stop` true/30, `process_status` false/15,
`profile_capture` true/60, `profile_list` false/15, `profile_delete` true/15.
None is registered as a Build owned routine. `code.exec`, `code.process_start` and
`code.profile_capture` require a complete plan preview: a failed or unrenderable plan refuses
the call instead of parking a card with argument rows.

### 5.2 Card rows

`code.exec` / `code.process_start` (in order): `program` (resolved absolute path), `command`
(the argv as a JSON array, chunked `command i/n` at 400 chars), `cwd`, `environment`,
`profile` (`name · digest[:12]` or `none`), `sandbox` (`<kind> — writes limited to the workspace, temp and tool caches`, plus `; limits: …` when `limitations` is non-empty), `risk` (comma-separated risks or `none flagged`),
`max runtime` (process only), `plan fingerprint`. Fingerprint = sha256 of canonical JSON
`{argv, cwd, environment, profile_digest, sandbox_kind}`, four 16-hex groups.
`code.profile_capture`: `setup file`, `extends`, `command` (the fixed bash argv), `sandbox`,
`plan fingerprint`. The one-use plan snapshot (`services/code_environment_adapter.py`) covers
these tools exactly as it covers `code.run`.

### 5.3 Outcome fed to the model

`command_outcome_text` keeps its shape. For `code.exec`, `code.run` and `code.test` the
output tail cap is **3000** chars (was 400); other tools keep 400. `code.process_start`
reports `started process <process_id> (pid …)`. `git_metadata_changed: true` adds
`WARNING: the command modified .git/hooks or .git/config`. The text is redacted and the TOOL
turn is fenced as data by `contain_result`.

### 5.4 Incremental output

The bridge output sink and the companion's progress relay cover `code.exec` as they cover
`code.run`/`code.test` (§"Incremental command output" of `code-environment.md`, unchanged
limits). `GET …/sol/confirmations/{id}/output` therefore serves `code.exec` too.

### 5.5 Continuing the turn after a command

`POST /api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages`
(`MessageCreate`) gains `resume_confirmation_id: UUID | null`. When set:

- `content` may be omitted (it becomes optional only together with this field; validation
  rejects a body with neither);
- the confirmation must belong to the caller and this conversation, be decided, and be one of
  the command tools (`code.exec`, `code.run`, `code.test`, `code.install`,
  `code.create_environment`, `code.process_start`, `code.profile_capture`);
- each confirmation can be resumed once (a second request answers `409 already_resumed`);
- at most **6** consecutive resume turns without a user-authored message (`409
resume_limit`); SOL then waits for the person;
- budget pre-flight, frequency cap and turn limits apply exactly as for a normal message;
- no user turn is stored; the assistant turn records `{resume_of: <confirmation_id>}`.

The desktop sends it automatically after an approved command card finishes (§7).

### 5.6 Events (`emit_event`, consent-gated)

| event                   | when                                                 | payload                                                                             |
| ----------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `sol.command.proposed`  | a command card is parked or a denied call is refused | `{tool, program, risks, denied}`                                                    |
| `sol.command.completed` | an approved command tool returns                     | `{tool, program, exit_code, timed_out, duration_ms, sandbox, git_metadata_changed}` |
| `sol.turn_resumed`      | a resume turn starts                                 | `{confirmation_id, tool, chain}`                                                    |
| `code.process.stopped`  | a stop succeeds                                      | `{via: "ui" \| "sol", state}`                                                       |
| `code.profile.captured` | capture succeeds                                     | `{variable_count, dropped_count}`                                                   |

`program` is the basename only. Full argv and variable names are never in events.

## 6. Routes (new)

| Method | Path                                                                                     | Purpose                                                                                                                                                                                                                       | Success |
| ------ | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| GET    | `/api/v1/projects/{project_id}/code/processes?machine_id=…`                              | `code.process_status {}` over the caller's own bridge session: `{bridge: {connected}, processes: […]}`. Offline → `processes: []`, `connected: false`. MEMBER+.                                                               | `200`   |
| GET    | `/api/v1/projects/{project_id}/code/processes/{process_id}/output?machine_id=…&cursor=…` | `code.process_status {process_id, cursor}` → `{output}`. Unknown process → `404 not_found`. MEMBER+.                                                                                                                          | `200`   |
| POST   | `/api/v1/projects/{project_id}/code/processes/{process_id}/stop?machine_id=…`            | The person's own Stop button: dispatches `code.process_stop` directly over their own bridge session (a user action, not a model proposal). Emits `code.process.stopped {via: "ui"}`. Offline → `409 bridge_offline`. MEMBER+. | `200`   |

All three are scoped to the authenticated user's own bridge session for that project: a team
member can never see or stop another member's processes (tested). Rate limited like the
code-environment route.

## 7. Desktop

See `docs/wireflows/sol-page.md` and `sol-window.md` (SOLUSDEV-317 sections): command card
header with program and risk badges, Cmd/Ctrl+Enter approval, retained final output, automatic
resume after an approved command, and the Running processes strip with Stop.

## 7a. Clarifications

- The decide route's `ToolResult` envelope carries the tool's result dict in `value` (`ok`,
  `exit_code`, `timed_out`, `reason`, tails, `sandbox`, `git_metadata_changed`).
- `code.process_status` with an unknown `process_id` answers `output: null` and does not list
  it. The cloud maps that to `404 not_found`.
- Output chunk fields: the confirmation-output route uses `sequence`; the process-output route
  uses `seq`. Both are strictly increasing integers.
- A resume turn uses the action mode currently shown on the SOL surface.

## 8. Errors

Tool refusals are tool results, never HTTP errors. Route errors: `404 not_found` (non-member,
unknown process), `409 bridge_offline` (stop only), `409 already_resumed`, `409 resume_limit`,
`422` validation.

## 9. Phase 4 security amendments (2026-10-19)

These supersede earlier sections where they conflict.

1. **The probe never executes workspace code.** `code.probe_environment` reads a workspace
   venv's packages from `site-packages/*.dist-info/METADATA` (name, version) and its Python
   version from `pyvenv.cfg`. It never starts `<venv>/bin/python`, `pip` or `uv pip list`
   against it. System interpreters on the pinned roots may still be asked for `--version`.
   The post-install CODE recording uses the same read-only probe.
2. **No hidden argv.** For `code.exec`, `code.process_start` and `code.profile_capture`, if
   redaction would change any of the `program`, `command*`, `cwd`, `environment`, `profile` or
   `setup file` rows, the call is refused and nothing is parked: "the command contains
   secret-shaped values that cannot be shown on the approval card".
3. **Processes are tamper-checked too.** `process_start` takes the git-metadata digest at
   start and compares it when the process exits, is stopped or timed out, and at shutdown.
   `process_status` entries, the stop result and the outcome text carry `git_metadata_changed`.
4. **HOME is never the workspace.** Every executing action is refused when the workspace
   realpath equals or contains `HOME` or `~/.solus`. The Linux helper also refuses any `--rw`
   path that contains them.
5. **Caches are data only.** The declared writable caches are narrowed to `.cache`,
   `Library/Caches`, `.ros`, `.npm/_cacache`, `.pnpm-store`, `.cargo/registry/cache`,
   `.gradle/caches`, `.platformio/.cache`, `.arduino15/staging`, `.colcon`.
   `.local/share/uv`, `.local/share/pnpm`, `.cargo/git`, and the roots of `.gradle`,
   `.platformio` and `.arduino15` are removed, because they hold code that later runs outside
   the sandbox. Program resolution refuses any executable whose realpath is inside the
   writable set but outside the workspace.
6. **Capture card.** `code.profile_capture` rows add `profile` (`<name>`, plus `replaces
   existing` when one exists) and `risk` (`project_scripts` for a workspace setup file). The
   fingerprint covers the profile name.
7. **Outcome on success.** For `code.exec`, `code.run` and `code.test` the output tail (≤ 3000)
   is included on exit 0 too.
8. **Profiles drop option-injection variables.** `NODE_OPTIONS`, `PERL5OPT`, `RUBYOPT`,
   `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS` and `GCONV_PATH` are dropped at capture (in addition to §2.4).
   `PYTHONPATH` and `LD_LIBRARY_PATH` are kept.
9. Event `program` values must match `^[A-Za-z0-9._+-]{1,64}$`, otherwise `"other"`. The resume
   chain check locks the conversation row. Linux process start tokens include the boot id.
10. Residual, documented: the server re-plans at execute time and does not receive the approved
   fingerprint (a sub-second window between the cloud's re-plan and the server's). On macOS a
   copied `launchctl`/`osascript` binary escapes the `process-exec` literal denials (the
   AppleEvents/LaunchServices mach denials still apply).
11. **Name matching.** For programs that are not workspace-relative (bare names resolved from the
    environment, profile or pinned roots, and absolute paths), matching against every denied set
    (shells, interpreters, wrappers, elevation, git) fails closed by prefix. A known name followed
    by the end, a version `[0-9][0-9.]*`, and/or tokens `[-.][a-z0-9.]+` is denied (`zsh-5.9`,
    `bash-5.2`, `php-cgi8.2`, `sudo-rs`, `sudo.ws`, `python3.12-intel64`, `env-x`, and the GNU `g`
    forms). Workspace-relative programs (`./env_setup.sh`, `tools/env-check.sh`) match on the exact
    normalised name only, for both the argv basename and the resolved realpath basename, because
    renaming a workspace file defeats any name rule anyway. Cloud and server both fail closed on
    unknown leading options for every interpreter, and a behavioural parity test runs both
    classifiers over a shared corpus. Path containment checks (writable roots, workspace,
    HOME/`.solus`) compare `(st_dev, st_ino)` of ancestors, so case-insensitive filesystems
    cannot fool them.
12. **Resume body.** `resume_confirmation_id` cannot be combined with `content` or `screenshot`
    (422).
13. **Shutdown.** On stdin EOF or a signal, the server ignores further SIGTERM/SIGINT while it
    stops processes, and escalates to SIGKILL within 1.5 s, so the SDK's 2 s termination window
    cannot cut cleanup short. Process-tree tracking prunes vanished pids and compares per-pid start
    tokens before signalling.
14. **Stop route.** A stop whose result does not arrive within the dispatch bound answers
    `504 stop_unconfirmed` (it may have landed); `404` is only for a process the server reports
    unknown.

## 10. Build auto-run and shell scripts (ADR-031 amendment 2026-10-19)

This section supersedes "every execution is confirmed" (§1 invariant 2) for the narrow class below.

### 10.1 Auto-run

In Build mode (`action_mode: do`), with `force_confirmation` false, a `code.exec` call executes
**without a card** when all of the following hold:

1. `CommandPolicy.classify(argv)` does not deny it, and its risks are empty.
2. The server plan answers `ok: true` with `program_scope: "system"`. `program_scope` is a new
   plan field for every action: `"workspace"` when the resolved program's realpath is inside the
   workspace (a workspace script, a venv binary, a profile PATH entry under the workspace),
   otherwise `"system"`. A workspace program counts as running project code, so it keeps the card.
3. The `BuildExecutionPolicy` routine path succeeds: argument validation, two identical
   complete previews (the same `code.plan` rows and fingerprint as a card would show), and
   single use.

The call is then dispatched exactly like an approved one. It streams output, gets the 3000-char
outcome tail, and is filed to Error logging on a non-zero exit. Its tool result reaches the
model in the same turn, so there is no resume. Events: `sol.command.completed` gains `auto:
true|false`. Everything else keeps the card: risk-flagged exec, `process_start/stop`,
`profile_capture/delete`, `create_environment`, `install`, `run`, `test`, and any exec whose plan
fails or is `program_scope: "workspace"`. Guide mode never executes.

### 10.2 Shell scripts

`bash` and `sh` are allowed **only** in this shape, which both the cloud and the server check:
`[bash|sh, <script>, *args]`. `<script>` is a workspace-relative path with no `..` segment
that ends in `.sh` or `.bash` and does not start with `-`. No option may come before the script
(`-c`, `-s`, `-i`, `-e`, `--rcfile`, `--init-file`, `-o`, `+o`, … are all refused), and stdin is
closed. The server additionally resolves `<script>` inside the workspace as a regular file.
Every other shell form stays denied, as do other shells (zsh, fish, …). The command carries the
`runs_shell` and `project_scripts` risks, so it always shows a card.

### 10.3 Desktop output presentation

- Command output (the live region on a running card, the output kept under a decided card, and
  auto-run results in the transcript) renders in the same code-block surface as SOL's markdown
  code blocks: the same background token, monospace font, rounded border and padding. It is
  plain text, never HTML.
- Every markdown code block in SOL messages and every command-output block has a **Copy**
  button in its top-right corner. It copies the block's plain text, shows "Copied" for about
  1.5 s, and has an accessible name ("Copy code" / "Copy output").
- An auto-run `code.exec` shows in the transcript as a compact command row: the program
  basename, status (`exited N` / `timed out`) and an `auto` label. Its output block is
  collapsed beyond 12 lines, and the Copy button copies the full retained output.
- "Output display limit reached" appears only when the output really was truncated (the
  route's `truncated` flag or the client's own caps), never on completion alone.

### 10.4 What counts as project code (security review, 2026-10-19)

Auto-run must never execute workspace code without a card, so both of the following are
judged as running project code:

- **Cloud risk.** `project_scripts` is added for an interpreter (any `INLINE_CODE` name) given a
  non-option positional argument or `-m <module>`, and for project runners: `pytest`, `tox`,
  `nox`, `npm`, `npx`, `pnpm`, `yarn`, `bun`, `deno`, `cargo`, `go`, `make`, `ninja`, `cmake`
  (build or source dir), `colcon`, `catkin`, `ros2 run|launch`, `gradle`/`gradlew`, `mvn`,
  `rake`, `bundle exec`, `poetry|uv|pipenv|hatch run`, `platformio|pio run|test`.
  `--version`/`--help`-only invocations stay no-risk.
- **Server scope.** `program_scope: "workspace"` for shell scripts, for interpreters given a
  script or module, for project runners, and whenever the resolved program path (before or
  after symlinks) or a workspace venv's bin dir holds the program. Right before spawn, the
  server re-resolves the program's realpath and scope, and refuses if either changed since
  planning.

Live output (§5.4): the server packs complete lines into each progress frame, up to the
2048-char frame limit, so normal bursts are not dropped. `truncated` means a real cap was hit.
