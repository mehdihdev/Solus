# Fork security review — `code` @ tree `<pinned by the human reviewers>` — `2026-09-07`

> **DRAFT — awaiting human sign-off.** Filled from `integrations/mcp/SECURITY_REVIEW.template.md`
> by the SOLUSDEV-250 agent as the reviewers' worksheet. Append-only: later reviews are appended
> below, never rewrite this one. SIGNATURES LIVE IN PROVENANCE.md AND REMAIN BLANK — filling them
> is a human-only act. Items that require CI or a network-enabled machine are dispositioned
> **PENDING(human/CI)** explicitly rather than ticked on faith.
>
> Scope: the whole directory — there is no upstream. Exposed surface: the six tools in
> `allowlist.yaml` (`probe_environment`, `plan` read-only; `create_environment`, `install`,
> `run`, `test` confirmation-gated). Solus-authored code under review: `bin/launch` (47 lines)
> and `solus/*.py` (~950 lines). Tree hash: reviewers pin
> `git rev-parse HEAD:integrations/mcp/code` at sign-off.
>
> Threat model note: unlike `local`, this server EXECUTES on confirmation — installs (network
> egress by the user's pip/uv), scripts and pytest in the user's workspace venv. That is its
> declared function under the ADR-031 amendment of 2026-09-07; the review question is whether it
> can do anything BEYOND the confirmed argv, outside the workspace, or without the gate.

## 1. Supply chain

- [x] No upstream to match — evidence: `ls integrations/mcp/code` shows no `upstream/` or
      `vendor/`; `tests/test_code_provenance.py` asserts both are absent on every run.
- [x] No runtime fetch at LAUNCH — evidence: `bin/launch` read in full (47 lines): `set -eu`,
      path computation, `cd -- "$WORKSPACE"`, `exec /usr/bin/env -i … "$PYTHON"
      "$FORK_DIR/solus/server.py"`. Token scan pinned by
      `test_launch_contains_no_network_or_installer_commands` (command lines only — the comment
      block mentions installs to say they are NOT done here).
- [x] Registry install hooks — none: nothing here is pip-installed; the companion materializes
      `requirements.lock.txt` into `.venv/` and `bin/launch` runs sources in place.
- [x] Lockfile committed, complete, hash-pinned — evidence: `requirements.lock.txt` carries 455
      `--hash=sha256:` lines over 31 packages (`mcp==1.29.0` closure), byte-identical below the
      header to the `local` fork's lock (`test_lockfile_body_is_identical_to_the_local_forks`);
      shape enforced by `tests/test_code_lockfile.py`. **PENDING(human/CI):** the offline
      `--require-hashes --no-index` reproduction.
- [ ] Dependency audit — **PENDING(human/CI):** `pip-audit` against `requirements.lock.txt`.
- [ ] Reproducibility — **PENDING(human/CI):** two clean `scripts/install-mcp-forks.sh` runs.

## 2. Least privilege

- [x] Runs as the invoking user — evidence: `grep -rnE 'sudo|setuid|seteuid|runas' solus/ bin/`
      → no hits.
- [x] Filesystem scope — evidence (tier-1 line-read of `solus/workspace.py`, verbatim the
      `local` module — `test_is_verbatim_the_local_forks_module_below_the_docstring`): every
      caller path (`path`, `environment`, `script`, `target`) passes `plan.py::_relative`
      (relative, traversal-free, no `-` prefix, no NUL/newline, ≤ 512 chars) and then
      `resolve_inside` (symlink-resolved, must stay under the root). The one deliberate
      exception: the venv INTERPRETER file may be a symlink to a system python (every venv is),
      so `execute.py::resolve_executable` confines its DIRECTORY (`resolve_inside(parent)`) and
      requires the file to exist and be executable — a venv directory that is itself a symlink
      outside is refused (`test_install_refuses_a_venv_symlinked_outside`,
      `test_relative_interpreter_must_live_inside_the_workspace`). `create_environment` refuses
      an existing/symlinked target and a parent outside the root.
- [x] Network egress: **none by the server** — evidence:
      `grep -rnE 'requests|urllib|http\.client|socket\.|fetch\(|axios|net\.connect|WebSocket' solus/ bin/`
      → no hits; `server.py` runs `transport="stdio"` only. The CHILD of a confirmed `install`
      reaches the package index through the user's own pip/uv — that is the tool's declared
      function (allowlist reason says so) and is the amendment's explicit allowance.
- [x] No `shell=True` / `os.system` — evidence: `grep -rnE 'shell=True|os\.system' solus/ bin/`
      → no hits. Exactly two subprocess sites: `execute.py:122` (`subprocess.Popen(argv,
      cwd=workspace, env=scrubbed, stdin=DEVNULL, stdout/stderr=tempfile,
      start_new_session=True, close_fds=True)`) and `probe.py:53` (`subprocess.run(argv,
      stdin=DEVNULL, capture_output=True, timeout=…, env=scrubbed, start_new_session=True)`).
      Every argv is a list assembled by `plan.py` from validated fields, or a fixed probe list.
- [x] Fixed argv — evidence: `bin/launch` has no `$@`/`$*`
      (`test_launch_has_fixed_argv_with_no_argument_passthrough`); the server takes no argv.
      Caller-influenced argv elements: package strings (PEP 508 regex, no `-`/`://`/`/`/space —
      `test_install_refuses_option_url_path_and_malformed_packages`, 19 hostile shapes), the
      script/target path (confined, not `-`-prefixed), the run `args` (the script's own argv,
      after the script path; ≤ 32 × 256 chars, no NUL/newline), the python version
      (`^3\.\d{1,2}$`). `--` precedes packages and the pytest target.
- [x] Binaries pinned — evidence: `execute.py::SEARCH_ROOTS` is a fixed list; `pinned_which`
      never reads the inherited PATH (`test_pinned_which_never_consults_the_inherited_path`);
      `bin/launch` pins PATH to `/usr/bin:/bin` regardless.

## 3. Sandbox posture

- [x] Declared below.
- [ ] Functions under the strictest declared posture — **PENDING(human):** run `probe_environment`
      and `plan` under a network-disabled, read-only-outside-workspace wrapper (expected: no
      failures); run one confirmed `run` and `test` the same way (expected: only the workspace
      and TMPDIR are written).
- [x] Nothing detects/disables sandboxing or self-modifies — evidence: tier-1 read of every
      file; `grep -rnE 'write_text|write_bytes|mkdir|unlink|rmtree|open\([^)]*["'"'"'](w|a)' solus/ bin/`
      → no hits. The server's own writes are two `tempfile.TemporaryFile()` spools in
      `execute.py:121` (unlinked on creation, under TMPDIR). Everything else that writes is the
      CHILD the user confirmed (venv creation, pip, the script) — inside the workspace by cwd
      and by the confined venv path.

## 4. Secret hygiene

- [x] Environment access confined to the declared allowlist — evidence:
      `grep -rnE 'os\.environ|getenv' solus/ bin/` → three hits: `workspace.py:27`
      (`SOLUS_MCP_WORKSPACE`), `execute.py:88` and `probe.py:46` (both read ONLY
      `PASSTHROUGH_NAMES` = `HOME`, `LANG`, `TMPDIR`). All in `solus/env_allowlist.py`, which
      `bin/launch` is pinned to (`test_launch_scrubs_environment_to_the_declared_allowlist`);
      `solus/env.allow` is a strict subset. The inherited `VIRTUAL_ENV` is passed by the
      launcher but never READ: `scrubbed_env` sets it from the plan.
- [x] Children never inherit a secret — evidence: `execute.py::scrubbed_env` builds the child
      env from scratch: exactly `PATH`, `HOME`, `LANG`, `TMPDIR`, `VIRTUAL_ENV`
      (`test_scrubbed_env_is_exactly_the_documented_names` seeds `AWS_SECRET_ACCESS_KEY`,
      `GITHUB_TOKEN`, an evil PATH and a foreign VIRTUAL_ENV and asserts none reach the child).
- [x] No credential ever logged — evidence: four logging sites (`server.py:82` tool name +
      exception type/message, `server.py:198` startup, `probe.py:166` and `execute.py:188`
      exception TYPE only). No environment values, no child output is logged; stderr is the
      companion's local log, never the bridge. **Wire hygiene:** argv carries no absolute
      workspace path (`test_no_ok_argv_carries_an_absolute_path`); refusal reasons echo at most
      64 chars of caller input (`test_install_echoes_a_bounded_slice_of_the_offender`);
      `stdout_tail`/`stderr_tail` ARE the child's output (declared — the cloud's ingress
      redaction owns that side per the template note).
- [x] No telemetry/phone-home — covered by the §2 egress grep (no hits).
- [x] No credential persistence — the server writes only the two temp spools (§3).
- [x] SecretStore values never reach the server — nothing reads Solus config or credential
      stores; the child env is the five-name scrub.

## 5. Untrusted I/O

- [x] Tool inputs treated as hostile — evidence (tier-2 line-read of `plan.py`, `server.py`):
      `plan_action` re-validates every field from an untrusted dict regardless of FastMCP's
      typing (action ∈ 4 names, `args` an object, each field type/shape/bound checked —
      `tests/test_code_plan.py`, 80+ cases incl. `None`, ints, bools, oversize, NUL). No
      archives are opened.
- [x] Parsers bound input sizes; malformed input never crashes — evidence: probe JSON
      (`pip list`, `conda env list`) is parsed under `try` with shape checks and caps (300
      packages, 32 envs, 39-char strings — `test_env_dir_is_found_last_and_pip_garbage_is_empty`,
      `test_conda_garbage_and_cap`); captured stdout is cut at 1 MiB before parsing
      (`test_run_capture_bounds_stdout`); child output is spooled to disk and tailed to 16 KiB
      (`test_tails_are_cut_to_16_kib`, undecodable bytes replaced). Never-raises pinned
      end-to-end by `test_never_raises_when_every_internal_step_explodes` (server) and
      `test_never_raises_when_probes_explode`.
- [x] No HIDDEN `eval`/`exec`/dynamic import — evidence:
      `grep -rnE '\beval\(|\bexec\(|__import__|importlib' solus/ bin/` → no hits. `run` and
      `test` are DECLARED interpreter tools (their function), confirmation-gated, executing only
      a workspace-confined script/target with the workspace venv interpreter.
- [x] Bounded execution — evidence: `timeout_seconds` 1..600 (default 600) enforced in `plan.py`
      (`test_run_refuses_bad_timeouts`); `default_runner` SIGKILLs the process GROUP on timeout
      (`test_default_runner_kills_the_whole_process_group_on_timeout` spawns a grandchild and
      asserts it dies); stdin is closed (`test_default_runner_stdin_is_closed`).

## 6. Destructive actions

- [x] Classification — `probe_environment` (spawns `--version` / `pip list` / `conda env list`
      probes: read-only, no writes) and `plan` (pure) are non-destructive. `create_environment`
      (writes a venv), `install` (network + writes into the venv), `run` and `test` (arbitrary
      code) are destructive-class, each `requires_confirmation: true` with a reason in
      `allowlist.yaml` (`test_read_tools_are_unconfirmed_and_acting_tools_are_gated_with_reasons`).
- [x] Server-side annotations not relied on — the FastMCP tools carry no `annotations`; the
      allowlist is the only source (`solus_api.bridge.allowlist`).
- [x] No side effects beyond descriptions — tier-2 read: each gated handler plans, then runs
      EXACTLY the planned argv (`test_gated_tools_execute_exactly_what_plan_answers`,
      `test_run_executes_for_real_over_the_wire` observes the child's argv); a refused plan never
      reaches the executor (`test_refusals_over_the_wire_never_execute`).

## 7. Code-review depth — the honest tiers

- [x] **Tier 1 — 100% line-read:** `bin/launch`, `solus/server.py`, `solus/workspace.py`,
      `solus/plan.py`, `solus/execute.py` (both subprocess sites, all env access, the temp
      spools), `solus/probe.py`, `solus/roster.py`, `solus/env_allowlist.py`, `solus/env.allow`.
      That is every file — ~1000 lines.
- [x] **Tier 2** — all four gated handlers and the probe are inside tier 1.
- [x] **Tier 3** — n/a (nothing left unread).
- [x] Non-allowlisted tool code — none exists; `build_server()` raises if the registered set
      ever differs from `TOOL_ROSTER`.
- [x] Depth recorded — above. **Human reviewers must repeat the tier-1 read themselves**; this
      draft is the agent's worksheet, not a sign-off.

## 8. Update path

- [ ] Tree hash on the PROVENANCE sign-off lines — **PENDING(human).**
- [x] Re-review triggers listed in `PROVENANCE.md` (any `solus/`/`bin/` change, allowlist
      widening, env allowlist or `SEARCH_ROOTS` change, lockfile change, CVE, a Windows launcher).
- [ ] Both PROVENANCE sign-off lines dated — **PENDING(human).**

---

## Declared sandbox posture

- **macOS / Linux (today):** OS user permissions of the invoking user + `bin/launch` `env -i`
  scrub to eight names with `PATH=/usr/bin:/bin` + cwd = the linked folder + code-level
  confinement (`workspace.py`, `plan.py` validation, `execute.py` scrubbed child env, pinned
  search roots, process-group timeout). The server itself makes no network connections and
  writes only two temp spools. CONFIRMED CHILDREN run with the user's full OS permissions inside
  the workspace cwd — that is the declared function; a per-server sandbox (seatbelt / bwrap)
  arriving later should grant the child read/write on the workspace and TMPDIR, read on the
  system interpreters/uv/conda roots, and network only for `install`.
- **Windows:** `Scripts/python.exe` layouts are recognised by `plan.py`, but **no
  `bin/launch.cmd` ships** — the companion refuses the server on Windows (fails closed) until a
  human approves a Windows launcher; `os.killpg` is absent there, so the timeout would fall back
  to killing the direct child only (`execute.py::_kill_group`) — a Windows review item.

## Residuals for the reviewers

1. **Bare tool names in argv.** `uv` / `python3.X` appear by bare name on the approval card and
   are resolved at execution against `SEARCH_ROOTS` (which includes `~/.local/bin`, `~/.cargo/bin`
   and the conda user roots under `$HOME`). Chosen so the card never carries an absolute path
   with the username; the trade-off is that the resolution is by pinned LIST rather than a
   single pinned path. A user-writable root (`~/.local/bin`) is the user's own machine — same
   trust as their PATH — but reviewers should confirm they accept the list.
2. `probe_environment` runs `--version` on whatever `SEARCH_ROOTS` yields for the fixed names
   and `pip list` on the workspace venv's interpreter, unconfirmed (read-only by contract).
   Phase 4 security review C1 found that a directory merely containing `bin/python` — i.e.
   workspace content a cloned repo can commit — was treated as that venv, a drive-by execution
   path through the desktop's poll. `plan.venv_python` now requires a `pyvenv.cfg` AND an
   interpreter that resolves OUTSIDE the workspace (every venv links or copies the base
   interpreter); a planted script resolves inside and is never run
   (`tests/test_code_probe.py::test_a_planted_workspace_interpreter_is_never_executed`). What
   remains is execution of the user's OWN base interpreter, which the contract (§4) requires.
3. The lockfile is a copy of the `local` fork's derived (not compiled) lock — the same
   regeneration caveat applies.

## 2026-09-12 — SOLUSDEV-261 Git extension (agent verification)

This supplements the prior review; it does not supply either human shipping sign-off.

- [x] Five fixed tools, two gated writes; no raw shell/argv/repository URL inputs.
- [x] Complete patch/branch/index/destination previews; strict argument schemas.
- [x] Same-OID branch switches and changed index/remote tips refuse stale actions.
- [x] Fixed Git/SSH runtime, scoped transports, hooks/helpers/configuration restricted.
- [x] Bounded subprocess output/deadlines, owned-operation locks and readback checks.
- [x] Uncertain writes persist as possibly applied and require inspection, no auto retry.
- [x] Ignored dependencies are not traversed; tracked paths and metadata remain checked.
- [x] 41 Git tests,83 confirmation/bridge tests,246 Code/registration tests passed.
- [x] Fresh code review and independent security review passed after findings were fixed.
- [ ] Both human reviewers ratify the changed source tree before shipping.

Read-only ForgeTS observation succeeded; no live commit or push was attempted.
Existing conflicts, unsupported Git layout/configuration and absent trusted SSH
credentials remain refusals. Final output is bounded; no incremental log-stream
claim is made by this slice.

## 2026-09-12 — SOLUSDEV-261 Arduino extension (agent verification)

Scope: pinned Uno toolchain preparation/compilation, strict MCP registration,
complete confirmation previews, and truthful command outcomes. Human shipping
signatures remain outstanding; these results are not human ratification.

- [x] CLI and nine vendor archives pinned by digest and size; installed content,
  internal links, configuration and generated metadata verified exactly.
- [x] Compiler bytes sealed; Bubblewrap data/descriptor mounts bind execution to
  verified bytes and held directories. No host home, network or real devices mounted.
- [x] Empty/partial/unknown runtime state refuses; no automatic repair or retries.
- [x] Approval previews bind all logical argv/mount identities and source state;
  only internal OS descriptor numbers are substituted after validation.
- [x] Strict transport inputs expose only the frozen Uno FQBN and refuse extra fields.
- [x] Bounded source snapshots, output/deadline limits, cancellation and cleanup;
  regression tests preserve replaced directories and confine partial-copy cleanup.
- [x] Full hard-capped compiler JSON validated internally; only bounded tails returned.
  Artifact display remains complete through central prompt containment/redaction.
- [x] Failed/uncertain/no-op commands receive truthful history and error filing.
- [x] Independent code/Python and security reviews passed, all findings resolved.
- [x] 315 Code tests passed with 88.21% line coverage; 222 bridge/confirmation/prompt
  tests passed. Source lint and typing passed.
- [x] Actual engine prepared a disposable `.venv/a2qe` toolchain, compiled generated
  Blink offline, verified ELF/HEX artifacts, then reused the verified build without
  starting another compiler. No device was opened or flashed.

The disposable proof is not a production SOL approval or physical-board proof.
Production preparation/compilation still require their concrete human cards.

## 2026-10-18 — SOLUSDEV-317 command execution, processes, profiles, sandbox

**DRAFT — agent verification, awaiting human sign-off.** Authority: DECISIONS.md ADR-031
amendment of 2026-10-18; contract `docs/api/code-command-execution.md` §1–4, §5.4. These
results are not human ratification; both PROVENANCE sign-offs are void until re-signed.

New surface: `exec` (gated, streams), `process_start` / `process_stop` (gated),
`process_status` (read), `profile_capture` / `profile_delete` (gated), `profile_list` (read).

Posture:

- [x] **argv only.** Strict Pydantic transport models (`extra=forbid`, no coercion). No
  shell string reaches a process; `argv[0]` resolves to an absolute program without the
  inherited PATH (workspace file → absolute in an allowed root → `<env>/bin` → profile PATH
  → `SEARCH_ROOTS`) and the result shows the resolved path.
- [x] **Deny table** (`solus/command_deny.py`, plain literals mirrored by the cloud
  `CommandPolicy`), checked on the proposed name, the resolved program and its realpath:
  shells, wrappers, elevation/namespace tools, `git` and every `git-*` helper (SOL uses
  the dedicated, previewed git tools), inline-code interpreter options (python fails
  closed on unknown leading options), loader specifiers containing whitespace/controls or
  any non-`file:` URL scheme, perl/ruby module values (also inside short-option
  clusters). Names are normalised (case, version/build suffixes, `<known name><non-letter>…`
  prefixes, GNU `g` prefixes of wrappers, aliases).
- [x] **Sandbox or refuse** for EVERY executing tool (`create_environment`, `install`,
  `run`, `test`, `exec`, `process_start`, `profile_capture`): the planner refuses with
  `sandbox unavailable: …` when the cached probe fails. macOS: root-owned
  `/usr/bin/sandbox-exec` with a constant profile (writes only to the workspace, temp, a
  few devices and the declared HOME caches; the WHOLE gitdir is read-only — the `.git`
  entry, the resolved gitdir (gitfile targets) and its common dir — and `~/.solus` is
  denied, so git operations inside sandboxed commands cannot write the repository; launchctl/osascript/open/osacompile/automator exec denied; AppleEvents and
  LaunchServices lookups denied). Linux: Solus-authored `solus/landlock_exec.py` (ctypes
  only, `-I`, fixed minimal environment, child environment over an inherited descriptor,
  NO_NEW_PRIVS, best-ABI write rights, ABI ≥ 6 socket/signal scoping, network left open
  by decision). Real sandbox-exec tests run on macOS; real Landlock tests skip off Linux.
- [x] **Git metadata detection** around every sandboxed command: full-content, mode-aware
  digest of the protected set; any cap → always "changed" (`git_metadata_changed: true`).
  The command's process group — and every descendant seen in process-table snapshots,
  including ones that left the group via setsid — is killed after the leader exits,
  before the check. Linux servers set PR_SET_CHILD_SUBREAPER so orphans stay visible.
- [x] **Loader injection**: `LD_PRELOAD`, `LD_AUDIT`, `DYLD_INSERT_LIBRARIES`,
  `GCONV_PATH` never reach a child; profiles additionally drop `BASH_ENV ENV
  PROMPT_COMMAND PYTHONSTARTUP` and secret-shaped names.
- [x] **Profiles**: fixed `CAPTURE_SCRIPT` with the setup file as `$1`; setup files are
  workspace files or realpaths under `/opt/ros/` (≤ 256 KiB, `.bash`/`.sh`); stored at
  `~/.solus/code-profiles/<key>/` atomically (0600/0700, `schema_version 1`), re-validated
  on load (corrupt or tampered → refusal, never a crash), values never returned.
- [x] **Processes**: ≤ 4 running, ≤ 16 entries, 30 min retention, 256 KiB ring of complete
  lines, 64 KiB per answer, `max_runtime_seconds` enforced, SIGTERM → 5 s → SIGKILL to
  the group and the snapshotted descendant tree,
  stop-all on stdin EOF/SIGTERM/SIGINT (real-server test), orphan reaping by start token
  (`/bin/ps -o lstart=` / `/proc/<pid>/stat`), no PR_SET_PDEATHSIG, never restarted.
- [x] Companion: `code.exec` progress relayed like `code.run`; `run test exec
  process_start process_stop profile_capture install create_environment` are never
  replayed and their transport errors are not retryable.

Residual risks for the reviewers (the deny table is defense in depth behind the human
card and the sandbox; it is intentionally not expanded further):

- Reads, exec and network are unrestricted on both platforms; a confirmed command can
  read anything the user can and talk to the network.
- macOS: launchd job submission over XPC is not blocked (only the CLI tools and
  AppleEvents/LaunchServices lookups are); `sandbox-exec` is deprecated by Apple.
  DYLD_* variables are stripped by SIP when crossing `/usr/bin/sandbox-exec`, so a ROS
  profile's `DYLD_LIBRARY_PATH` may not reach the target.
- Descendant tracking is snapshot-based (every 0.5 s): a descendant that double-forks
  between snapshots (macOS has no subreaper) can survive a stop. No cgroups by decision.
- Linux: Landlock grants only — git metadata is protected by detection, not prevention; file metadata (chmod/chown/utimes) is not confined; ABI < 3 cannot confine
  truncate, ABI < 6 cannot scope abstract sockets/signals. Cache directories that do not
  exist yet are not writable on Linux (Landlock needs an existing path).
- The deny table cannot see what an allowed program does (`make`, `npm run`, workspace
  scripts run project code by design — flagged as `project_scripts` on the card).
- A gitdir outside the workspace is protected by the profile rules but its contents are
  outside the writable set anyway unless it lives under temp or a cache.
- Server process registry lives in memory; a SIGKILLed server leaves processes until the
  next start reaps them (start-token match).

Re-review triggers added by this slice: any change to `HOME_CACHES` (adding a cache), the
macOS profile, `landlock_exec.py`, `command_deny.py` tables, `CAPTURE_SCRIPT`, the profile
filters, process bounds, or `SEARCH_ROOTS`.

- [ ] Both human reviewers ratify the changed source tree before shipping.

### 2026-10-19 addendum — SOLUSDEV-317 Phase 4 fixes (append-only; the entry above stands as written)

**DRAFT — agent verification, awaiting human sign-off.** Authority:
`docs/api/code-command-execution.md` §9 (Phase 4 security amendments, 2026-10-19).

Correction to the entry above: "Git metadata detection **around every sandboxed
command**" was not true as shipped on 2026-10-18 — only the one-shot tools (`run`, `test`,
`exec`, `install`, `create_environment`, `profile_capture`) compared the digest;
`process_start` did not. Fixed below (§9.3).

Fixes verified by tests in this slice:

- [x] **C1 / §9.1 — the probe never executes workspace code.** `probe_environment` reads
  a workspace venv's packages from `site-packages/*.dist-info/METADATA` (Name/Version;
  ≤ 4096 directory entries, ≤ 4 site dirs, ≤ 64 KiB per file, ≤ 300 packages +
  `truncated`, no symlinked dist-info or METADATA) and its Python version from
  `pyvenv.cfg`. It never starts `<venv>/bin/python`, pip or `uv pip list`. System
  interpreters on the pinned roots are still asked `--version`. Real test: a `.venv` whose
  `bin/python` links to a real interpreter and whose site-packages carries an
  import-time `.pth` payload — no side effect, packages still listed.
- [x] **FIFO-safe reads** (`solus/safe_read.py`): METADATA, `pyvenv.cfg`, gitfile/`commondir`
  targets, git-metadata streams and profile files open with `O_NONBLOCK` and must be
  regular files, so a planted named pipe cannot hang the server.
- [x] **H2 / §9.3 — processes are tamper-checked.** `process_start` takes the
  git-metadata digest at start and compares it at exit, stop, timeout and shutdown;
  `process_status` entries and the stop result carry `git_metadata_changed`. Real macOS
  test: a started process cannot write `.git/hooks` (sandbox denial) and reports no change.
- [x] **H3 / §9.4 — HOME is never the workspace.** Every executing action is refused when
  the workspace realpath equals or contains HOME or `~/.solus` (or lies inside
  `~/.solus`); `~/.solus` is also resolved when it is a symlink, and containment is judged
  by `(st_dev, st_ino)` ancestry as well as spelling (case-insensitive APFS). `wrap`
  refuses the same. The Linux helper takes HOME as an explicit `--home` argument, opens
  each `--rw` path ONCE (`O_PATH|O_NOFOLLOW`), refuses symlinks and any descriptor that
  holds HOME/`~/.solus`, and adds the Landlock rule from that same descriptor (no
  check-then-use window). Temp roots that contain HOME are not granted.
- [x] **H4 / §9.5 — caches are data only.** `HOME_CACHES` narrowed to `.cache`,
  `Library/Caches`, `.ros`, `.npm/_cacache`, `.pnpm-store`, `.cargo/registry/cache`,
  `.gradle/caches`, `.platformio/.cache`, `.arduino15/staging`, `.colcon`. `pinned_which`,
  the command planner's resolver and the executor's final resolution refuse a program
  whose realpath (inode-compared) lies in the writable set outside the workspace (temp,
  user cache dir, caches) — e.g. a venv interpreter linked into `/tmp`.
- [x] **§9.13 — shutdown.** The signal handler ignores further SIGTERM/SIGINT, stops every
  started process with a 1.0 s SIGTERM grace then SIGKILL, and exits; previously a
  SIGTERM with stdin still open never reached the cleanup (the stdio transport waited on
  stdin). Real-server test: a TERM-ignoring process is dead < 2 s after the server's
  SIGTERM, with a second SIGTERM sent mid-cleanup.
- [x] **M2 / L3 — tree tracking.** Vanished pids are pruned on every snapshot; each pid's
  start token is recorded when first seen and must still match before it is signalled;
  Linux tokens carry `/proc/sys/kernel/random/boot_id`. Snapshots are at most every
  1.0 s on macOS (`ps` cost), 0.5 s on Linux.
- [x] **M3 / §9.11 — deny table.** Outside the workspace a denied name followed by a
  version and/or `[-.]` tokens is denied for every denied set (`zsh-5.9`, `php-cgi8.2`,
  `sudo-rs`, `sudo.ws`, `env-x`, `gtimeout`); workspace-relative programs match exact
  normalised names of argv[0] and of the resolved realpath only (`./env_setup.sh`,
  `./time_sync.py`, `./nu_test` run). Every interpreter in `INLINE_CODE` fails closed on
  leading options not in its known-safe list (`node --run`, `node -x`,
  `node --env-file`, `php -d/-z/-c`, `perl -d`, `lua -l data:…`). `classify_denial(argv)`
  is the stdlib-only entry point the cloud's parity test loads by path.
- [x] **L5 / §9.8 — one loader list** (`profiles.LOADER_NAMES`) for capture and spawn:
  adds `NODE_OPTIONS PERL5OPT RUBYOPT JAVA_TOOL_OPTIONS _JAVA_OPTIONS GCONV_PATH`;
  `PYTHONPATH` and `LD_LIBRARY_PATH` are kept.
- [x] **L6** — the companion never replays `code.profile_delete`. **L7** — the macOS
  limitations shown on the card add "a copied launchctl/osascript binary is not covered
  by the exec denial".
- [x] LOW — `Registry.stop()` sweeps first, so a process that exited on its own reports
  `exited`, not `stopped`; the server uses public refusal helpers; `default_runner` is
  split into functions under 50 lines.

Residual risks added for the reviewers:

- **The server re-plans at execute time and does not receive the approved fingerprint.**
  The cloud re-plans and compares before dispatch, but between the cloud's re-plan and
  the server's own planning there is a (sub-second) window in which the workspace could
  change what the same arguments resolve to. Not closed in this slice.
- **macOS copied binaries.** The `process-exec` denials are literal paths: a copy of
  `launchctl`/`osascript` placed in the workspace or temp escapes them (the AppleEvents
  and LaunchServices mach-lookup denials still apply, and temp copies no longer resolve
  as programs, but a workspace copy run by an allowed program is not prevented).
- `allowlist.yaml`'s `probe_environment` reason and `docs/api/code-environment.md` §4
  still describe the probe as running `pip list`; §9.1 supersedes them — both need a
  human/doc-owner edit (allowlist edits are human decisions).
- Linux real-Landlock behaviour of the new descriptor-based grants is covered by unit
  tests with injected openers here; the real-kernel test still only runs on Linux CI.

- [ ] Both human reviewers ratify the changed source tree before shipping.

### 2026-10-19 addendum (2) — review round on the fixes above (append-only)

- [x] Tree tracking: every stop/kill path takes a forced, un-rate-limited snapshot before
  SIGTERM and again before SIGKILL; an unknown start token is retried on later
  snapshots, and a token-less pid is signalled only while it is in the leader's parent
  chain in the fresh table; skipped pids are logged (pid only, no argv). Linux falls back
  to the raw start time when `boot_id` is unreadable.
- [x] Deny table: outside the workspace a known name followed by the end or ANY
  non-letter is denied (`perl5.36.0-x86_64-linux`, `bash+x`, `sh~`; this supersedes the
  version/token shape in addendum 1); workspace programs stay exact. node/bun
  `--inspect`, `--inspect-brk`, `--inspect-wait` are bare flags or a loopback port only
  (`0.0.0.0`, `[::]` and other hosts are refused). Loader values of short options inside
  clusters (`-rX`, `-vr X`) get the same remote-scheme check as the long forms.

### 2026-10-19 addendum (3) — Build auto-run scope and bash/sh workspace scripts (append-only)

Authority: DECISIONS.md ADR-031 amendment of 2026-10-19; `docs/api/code-command-execution.md` §10.
Both items change what the planner lets through, so both are re-review triggers.

- [x] **`program_scope` on every `code.plan` answer** (`"workspace"` | `"system"`, null when
  refused). `"workspace"` when the resolved program's realpath is inside the workspace
  (inode-ancestry containment, the same `_within` the deny rules use) or it sits in the
  selected workspace venv's `bin` dir (a venv interpreter links outside but runs project
  code); bare names (pinned system roots) and links that leave the workspace are `"system"`.
  The cloud auto-runs a no-risk `code.exec` only on `"system"`, so a wrong `"system"` would
  skip the approval card for project code. The field never relaxes the deny table: a
  workspace link to an outside `bash-5.2` is still matched fail-closed by its target's name.
  Re-review relevance: any change to program resolution, `_within`, or the venv rule.
- [x] **bash/sh run workspace scripts.** `command_deny.shell_script` allows exactly
  `[bash|sh, <script>, *args]`: argv[0]'s basename is exactly `bash` or `sh` (a bare name or
  an absolute path, never a workspace file, never a versioned/prefixed variant such as
  `bash-5.2`); `<script>` ends `.sh`/`.bash`, starts with none of `-`, `+`, `/`, `~`, and has
  no `..` segment; no option precedes it. The resolved program and its realpath must also be
  named `bash`/`sh` (or `dash`, Debian's `/bin/sh` target); a renamed shell is still denied.
  Every other shell form (`-c`, `-s`, `-x`, `--rcfile`, `--`, `+o`, …) and every other shell
  stays denied, and `classify_denial` (the cloud parity entry point) gives the same answer.
  The planner additionally resolves the script against `cwd` inside the workspace as a regular
  file ("script must be an existing .sh/.bash file inside the linked folder"). stdin is closed;
  the script runs under the same sandbox as any exec (real macOS test: a workspace script
  echoes and writes inside, and its write outside the workspace is denied). The script is
  project code with full shell power inside the sandbox — equivalent to an executable
  workspace script, which was already allowed behind the card. Re-review relevance: the
  shell-script shape, the accepted realpath names, and the cloud's `runs_shell` +
  `project_scripts` risks that keep it behind the card (`program_scope` is `"system"` for
  `/bin/bash`, so the card for these commands depends on those cloud risks).
- Residual: the script file is checked at plan time; it can change between approval and
  execution like any workspace program (same window as the re-plan residual above).

### 2026-10-19 addendum (4) — program_scope follows what runs; plan-to-spawn check (append-only)

- [x] `program_scope` is `"workspace"` (supersedes addendum 3 where they differ) when the
  resolved program's path is in the workspace before OR after following links (so any
  workspace venv `bin`, and a workspace link to a system binary); for a §10.2 shell script;
  for an interpreter given anything but `--version`/`-V`/`-VV`/`--help`/`-h`/`-v`; for a
  project runner (pytest, tox, nox, npm, npx, pnpm, yarn, bun, deno, cargo, go, make, gmake,
  ninja, cmake, colcon, catkin, catkin_make, gradle, gradlew, mvn, rake) by argv[0] or
  realpath name; for `ros2 run|launch`, `bundle exec`, `poetry|uv|pipenv|hatch|pio|platformio
  run`; and for a profile capture of a workspace setup file.
- [x] TOCTOU: the plan records the program's realpath; right before spawn the server
  re-resolves the program, and refuses ("the program changed after it was planned") when the
  realpath or the recomputed scope differs. The planned path (not the realpath) is still what
  runs, so venv interpreters keep their link semantics. Plans not built by `plan_action`
  carry no scope and are not compared.
- Re-review relevance: the runner tables, the info-flag set, and the spawn-time comparison.

### 2026-10-19 addendum (5) — broader runner denylist; profiles and venvs decide scope (append-only)

- [x] More project runners give `"workspace"`: always pdm, rye, pixi, hatch, rosrun,
  roslaunch, ctest, meson, scons, bazel, bazelisk, just, task, invoke, nox, pre-commit (plus
  the addendum-4 set); by subcommand pip/pip3 `install|download|wheel`, uv
  `sync|pip|run|build|tool`, poetry `install|build|run`, conda/mamba/micromamba
  `run|install|env`. A runner invoked only with `--version`/`-V`/`--help`/`-h` stays
  `"system"`. This remains a denylist (the auto-run model is "anything without a risk badge").
- [x] Any applied profile whose PATH, PYTHONPATH, LD_LIBRARY_PATH, DYLD_LIBRARY_PATH,
  AMENT_PREFIX_PATH, COLCON_PREFIX_PATH, CMAKE_PREFIX_PATH, ROS_PACKAGE_PATH, NODE_PATH,
  GEM_PATH, PERL5LIB, RUBYLIB or CLASSPATH has an entry in the workspace (inode containment;
  a not-yet-built entry is judged by its nearest existing ancestor; an empty or relative entry
  counts as the working directory) makes the command `"workspace"` — e.g. `ros2 topic list`
  under a workspace overlay. So does an explicit workspace venv `environment`
  (`create_environment` excepted: it creates one, it does not run it). The spawn-time
  recomputation uses the same plan fields.

### 2026-10-19 addendum (6) — interactive processes and `process_input` (append-only)

Governing text: ADR-031 amendment 2026-10-19 (interactive processes) and
docs/api/code-command-execution.md §11.1. Agent verification; the human sign-offs above are
unchanged and still required.

- [x] `process_start {interactive: true}` attaches a Solus-owned pseudo-terminal
  (`process_os.default_pty_spawn`): `os.openpty()`, slave as fds 0-2, `start_new_session`,
  24x120 window, slave closed in the parent, master non-blocking and non-inheritable; a failed
  spawn closes both ends (tested: no descriptor leak). It runs through the unchanged
  `sandbox.wrap` (sandbox-exec / Landlock helper). The child gets `TERM=dumb`. The PTY is not
  made the controlling terminal (no TIOCSCTTY): no line-discipline signals exist to send, and
  `/dev/tty` opens fail closed. Non-interactive processes keep stdin closed.
- [x] Landlock helper: `--env-fd` must now be > 2, so the helper can never consume and close a
  standard stream; a test proves fds 0-2 reach the final `execve` untouched.
- [x] REPLs and bare shells are refused in interactive mode (`command_deny.repl_reason`): an
  `INLINE_CODE` interpreter or shell (argv[0] and resolved names, matched like the deny table)
  with no non-option positional and no `-m <module>`; option values are consumed by the same
  per-interpreter option tables, `-` (stdin) and a bare `--` count as no script. The plan answer
  for `process_start` carries `interactive`, so the card and fingerprint reflect it.
- [x] Output: UTF-8 with replacement; 7- and 8-bit CSI, OSC/DCS/SOS/PM/APC strings (BEL or ST
  terminated; an unterminated string stops being discarded after 4096 chars), other ESC
  sequences, C0 controls except `\n`/`\t`, DEL and C1 controls are removed; `\r\n` → `\n`,
  lone `\r` ends a line. Lines keep the 2048-char suppression rule and the 256 KiB ring. The
  held partial line is exposed at most 512 chars; `prompt_tail` is ≤ 5 lines + pending,
  ≤ 1024 chars, tabs → spaces, no controls. Output is still untrusted data; redaction stays
  cloud-side (§11.2).
- [x] `awaiting_input` per §11.1 with an injectable clock; `prompt_seq` increments on each new
  detection. Interpretation: after input is sent, the answered line (and the terminal's echo
  of the input) never re-triggers detection; new output past the echo does.
- [x] `process_input` (gated, strict schema, `text` maxLength 1024): text must satisfy
  `str.isprintable()` (no C0/C1, no line/paragraph separators, no tab); a newline is written
  only for `enter`. Refused for unknown, not-running or non-interactive processes and for
  empty-without-Enter. The write holds a per-entry lock shared with the master close, so input
  can never land on a reused descriptor, and gives up after 2 s (`ok: false`, partial
  `sent_chars`). The companion never replays `code.process_input`.
- [x] Cleanup: the reader closes the master at EOF/EIO; stop, timeout, exit and shutdown join
  the reader and, if a descendant still holds the slave, stop it and close the master (tested
  with a held slave, and on real sandboxed processes for stop and stop-all).
- Residual: a program reading the terminal in raw mode receives exactly the printable text;
  the line discipline's canonical-mode limit (MAX_CANON, 1024 bytes on macOS) can truncate a
  long multi-byte line — the write then times out and reports `ok: false`.
- Re-review relevance: the escape stripper, the REPL table, the input validator and the
  master-fd lifecycle.

### 2026-10-19 addendum (7) — REPL guard hardening (append-only; addendum 6 stands as written)

- [x] The interactive-mode REPL check moved to `solus/repl_guard.py` and now fails closed:
  an interpreter must reach its script through options its table knows; any unknown option
  refuses. REPL-forcing flags are refused anywhere among leading options, including inside
  short clusters: python `-i`, node/bun `-i`/`--interactive`, perl `-d`, lua `-i`, php `-a`.
  Shells must start with their script (any leading `-`/`+` option refuses: `-i`, `-s`,
  `--rcfile`, `--init-file`, `-o`, `+o`, …). `-` (stdin) and a bare `--` are no script.
- [x] `-m <module>` counts only for python-family interpreters (python, pypy), and not for
  the REPL/debugger modules code, pdb, idlelib, asyncio, IPython, ipdb, pudb, ptpython,
  bpython (top-level package matched). perl -m/-M, ruby -r and node -r load a library and
  then read code from the terminal, so without a script they are refused. REPL/debugger
  subcommands are refused: node `inspect`/`debug`, bun `repl`, deno `repl`/`eval`; bare deno
  is refused.
- [x] REPL, debugger and database-shell programs are refused in interactive mode whatever
  their arguments: ipython, ptpython, bpython, irb, pry, rails, sqlite3, psql, mysql, mongo,
  mongosh, redis-cli, gdb, lldb, pdb, R, julia, ghci, erl, iex, node-inspect, tclsh, wish
  (casefolded basename or normalised name, so versioned names like `tclsh8.6` match).
  Non-interactive processes and `code.exec` are unaffected (stdin closed).
- Residual: this is a denylist of known REPL programs. An unknown program that reads and
  runs code from its terminal is not detected; every interactive start remains behind the
  approval card.

### 2026-10-19 addendum (8) — REPL guard: workspace scripts, stdin paths, more programs (append-only)

- [x] In interactive mode the script an interpreter or shell runs, and `deno run`'s module,
  must be an existing regular file inside the workspace, resolved relative to the planned cwd
  with the same check as §10.2 shell scripts (`command_plan._script_file`). Paths outside the
  workspace, directories, missing files and `..` escapes are refused. With no script check
  supplied, the guard refuses everything (fail closed).
- [x] For every interactive program, an argument (or an option's `=value`) that is `-`, or
  whose normalised absolute path is under `/dev/` or `/proc/<pid|self>/fd`, is refused, so
  code is never read from stdin or the terminal through a path (e.g. `make -f /dev/stdin`,
  `deno run /dev/tty`). Consequence: an interactive program cannot be given a serial device
  path such as `/dev/cu.usbmodem*` as an argument; such programs run non-interactively.
- [x] python `-m` additionally refuses cProfile, profile, trace, runpy, timeit, xonsh,
  sqlite3, jupyter, jupyter_console, ptipython, bpdb, web_pdb, rpdb, remote_pdb and ipykernel
  (they run or forward other code, or open a prompt).
- [x] Also refused as interactive programs, whatever their arguments: less, more, most,
  man, vi, vim, nvim, view, ex, ed, emacs, ftp, telnet, ssh, nc, ncat, socat, screen, tmux,
  script, expect (pagers and editors have shell escapes; the rest are remote or terminal
  shells).
