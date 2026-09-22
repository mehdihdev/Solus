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
