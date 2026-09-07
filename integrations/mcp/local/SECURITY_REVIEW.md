# Fork security review — `local` @ tree `<pinned by the human reviewers>` — `2026-09-07`

> **DRAFT — awaiting human sign-off.** Filled from `integrations/mcp/SECURITY_REVIEW.template.md`
> by the SOLUSDEV-249 agent as the reviewers' worksheet. Append-only: later reviews are appended
> below, never rewrite this one. SIGNATURES LIVE IN PROVENANCE.md AND REMAIN BLANK — filling them
> is a human-only act. Items that require CI or a network-enabled machine are dispositioned
> **PENDING(human/CI)** explicitly rather than ticked on faith.
>
> Scope: the whole directory — there is no upstream. Exposed surface: the three tools in
> `allowlist.yaml` (`scan_folder`, `folder_digest` read-only; `open_in_tool` confirmation-gated).
> Solus-authored code under review: `bin/launch` (42 lines) and `solus/*.py` (~780 lines).
> Tree hash: reviewers pin `git rev-parse HEAD:integrations/mcp/local` at sign-off.

## 1. Supply chain

- [x] No upstream to match — evidence: `ls integrations/mcp/local` shows no `upstream/` or
      `vendor/`; `tests/test_provenance.py::test_provenance_states_solus_authored_with_no_upstream`
      asserts both are absent on every run.
- [x] No runtime fetch — evidence: `bin/launch` read in full (42 lines): `set -eu`, path
      computation, `cd -- "$WORKSPACE"`, `exec /usr/bin/env -i … "$PYTHON" "$FORK_DIR/solus/server.py"`.
      Token scan pinned by `test_launch_contains_no_network_or_installer_commands` (npx/uvx/pip
      install/uv/curl/wget/git clone/nc/ftp/rsync/ssh all absent).
- [x] Registry install hooks — none: nothing here is pip-installed; the companion materializes
      `requirements.lock.txt` into `.venv/` and `bin/launch` runs sources in place.
- [x] Lockfile committed, complete, hash-pinned — evidence: `requirements.lock.txt` carries 455
      `--hash=sha256:` lines over 31 packages (the `mcp==1.29.0` closure, derived from the altium
      lock's `# via` graph — header states this); shape enforced by `tests/test_lockfile.py`
      (exact pins, ≥1 hash each, mcp + its 14 direct deps present, no altium-only package leaked,
      pywin32 keeps its win32 marker). **PENDING(human/CI):** the offline
      `--require-hashes --no-index` reproduction in a network-disabled container; the authoring
      shell had no network and could only attempt a cache-backed install (see completion report).
- [ ] Dependency audit — **PENDING(human/CI):** `pip-audit` against `requirements.lock.txt` is
      the CI dependency-audit job; not runnable in the network-restricted authoring session.
- [ ] Reproducibility — **PENDING(human/CI):** two clean `make mcp-forks` runs resolve identical
      sets (hash pinning makes any divergence a hard install failure).

## 2. Least privilege

- [x] Runs as the invoking user — evidence:
      `grep -rnE 'sudo|setuid|seteuid|runas' solus/ bin/` → no hits.
- [x] Filesystem scope — evidence (tier-1 line-read of `solus/workspace.py`):
      `workspace_root()` raises on an unset/empty `SOLUS_MCP_WORKSPACE` (never cwd);
      `resolve_inside()` refuses empty, absolute, `..`, `.`, backslash/drive forms, then
      `resolve(strict=True)` and `is_relative_to(root)` — a symlink to outside is refused.
      `scan.py::_walk` uses `os.walk(followlinks=False)`, drops symlinked directories, and skips
      symlinked files before any read. Pinned by `tests/test_workspace.py`,
      `tests/test_scan.py::test_symlinks_are_neither_followed_nor_hashed`,
      `tests/test_open_in_tool.py::test_refuses_*`. The one read that can leave the folder by
      design is the worktree `gitdir:` pointer (§4 of the route plan requires it), NARROWED
      (review finding 3): the resolved gitdir AND commondir must lie inside the folder or under
      `Path.home()`, else None (`tests/test_gitremote.py::test_gitdir_pointer_to_etc_is_none`,
      `test_worktree_pointer_outside_home_is_none`, `test_commondir_redirect_outside_root_and_home_is_none`);
      bounded reads of `HEAD`, `commondir`, `config` (≤ 64 KiB), one loose ref, `packed-refs`
      (≤ 1 MiB); only an origin URL (userinfo stripped), branch name, and short sha are surfaced.
- [x] Network egress: **none** — evidence:
      `grep -rnE 'requests|urllib|http\.client|socket\.|fetch\(|axios|net\.connect|WebSocket' solus/ bin/`
      → no hits. The `mcp` SDK's HTTP transports are present in the venv but never imported:
      `server.py` calls `run(transport="stdio")` only.
- [x] No `shell=True` / `os.system` — evidence: `grep -rnE 'shell=True|os\.system' solus/ bin/` →
      no hits. The single subprocess site is `launch.py::spawn_detached` —
      `subprocess.Popen(argv, stdin/stdout/stderr=DEVNULL, start_new_session=True, close_fds=True)`
      with `argv` built by `build_argv` from a fixed absolute binary (`/usr/bin/open`,
      `/usr/bin/xdg-open`, or the `detect.find_tool` result) and the workspace-confined resolved
      path; `--` precedes the path on macOS. Windows `system` uses `os.startfile`. Pinned by
      `tests/test_open_in_tool.py` (argv shapes per platform, absolute binaries, detached
      spawn kwargs).
- [x] Fixed argv — evidence: `bin/launch` has no `$@`/`$*`
      (`test_launch_has_fixed_argv_with_no_argument_passthrough`); the server takes no argv.

## 3. Sandbox posture

- [x] Declared below.
- [ ] Functions under the strictest declared posture — **PENDING(human):** run the three tools
      once under a network-disabled, read-only-outside-workspace wrapper. Expected: no failures
      (the server never writes and never dials).
- [x] Nothing detects/disables sandboxing or self-modifies — evidence: tier-1 read of every
      file; `grep -rnE 'write_text|write_bytes|mkdir|unlink|rmtree|open\([^)]*["'"'"'](w|a)' solus/ bin/`
      → no hits (the server performs zero file writes).

## 4. Secret hygiene

- [x] Environment access confined to the declared allowlist — evidence:
      `grep -rnE 'os\.environ|getenv' solus/ bin/` → two hits: `workspace.py:25`
      (`SOLUS_MCP_WORKSPACE`) and `detect.py:105` (`HOME`, Windows VS Code per-user path only);
      both names are in `solus/env_allowlist.py`, which `bin/launch` is pinned to
      (`test_launch_scrubs_environment_to_the_declared_allowlist`); `solus/env.allow` is a
      strict subset (`test_env_allow_is_a_subset_of_the_declared_allowlist`).
- [x] No credential ever logged — evidence: logging sites are `server.py` `_guarded` (tool
      name + exception type/message), `server.py` `main` (startup), `launch.py` (tool +
      exception). No environment values, no file contents are logged; stderr is the companion's
      local log, never the bridge. **Wire hygiene (findings 1–2):** `open_in_tool` answers the
      fixed `launch failed` (OS error text with absolute paths/username stays in stderr —
      `test_spawn_failure_reason_leaks_no_path_or_user`), and `gitremote.strip_userinfo` drops
      `user:token@` from the origin URL before it leaves the machine
      (`test_origin_url_never_carries_userinfo_credentials`).
- [x] No telemetry/phone-home — covered by the §2 egress grep (no hits).
- [x] No credential persistence — the server writes nothing (§3 grep).
- [x] SecretStore values never reach the server — nothing reads Solus config or credential
      stores; the child env is the seven-name allowlist.

## 5. Untrusted I/O

- [x] Tool inputs treated as hostile — evidence (tier-2 line-read of `server.py`,
      `launch.py`, `workspace.py`): `open_in_tool` args are type-checked, the echoed `tool` is
      bounded to 64 chars, `path` goes through `resolve_inside`. `scan_folder`/`folder_digest`
      take no arguments. No archives are opened (no zip handling anywhere).
- [x] Parsers bound input sizes — evidence: `gitremote.py` bounds every read
      (`MAX_POINTER_BYTES` 4 KiB, `MAX_REF_BYTES` 4 KiB, `MAX_CONFIG_BYTES` 64 KiB,
      `MAX_PACKED_REFS_BYTES` 1 MiB, `MAX_URL_CHARS` 2048) and wraps parsing in a catch-all;
      `scan.py` caps hashing at 32 MiB per file (an explicit byte budget in the read loop, so a
      file growing mid-read is still null-hashed — `test_file_hash_stops_at_the_byte_budget_when_the_file_grows`)
      and abandons the walk at 2001 candidates so memory is bounded by the cap, not the tree
      (`test_collection_stops_at_the_cap_during_the_walk`); streams in 1 MiB chunks. Wire shape is redaction-safe by construction (file `hash` and `digest` are 32-hex
      blake2b-128, git `head` is the 12-hex short form, paths ride as split `parts`) so the
      cloud's `redact_value` never blanks a legitimate scan — pinned by
      `tests/test_scan.py::test_no_wire_string_is_redaction_shaped`. Malformed/oversize/unreadable inputs tested in `tests/test_gitremote.py`
      (garbage pointer, malformed config, oversize config, unreadable config, non-sha ref) and
      `tests/test_scan.py` (over-cap file, unreadable file, missing root). Never-raises pinned
      end-to-end by `tests/test_server.py::test_never_raises_when_every_internal_step_explodes`.
- [x] No `eval`/`exec`/dynamic import on input — evidence:
      `grep -rnE '\beval\(|\bexec\(|__import__|importlib' solus/ bin/` → no hits.

## 6. Destructive actions

- [x] Classification — `scan_folder`, `folder_digest`: read-only (no writes, no spawns).
      `open_in_tool`: launches a desktop application → destructive-class, `requires_confirmation:
      true` with a reason in `allowlist.yaml` (`test_open_in_tool_is_confirmation_gated_with_a_reason`).
- [x] Server-side annotations not relied on — the FastMCP tools carry no `annotations`; the
      allowlist is the only source (`solus_api.bridge.allowlist`).
- [x] No side effects beyond descriptions — tier-2 read: `scan_folder` reads only; `open_in_tool`
      spawns exactly one detached process on the confirmed path.

## 7. Code-review depth — the honest tiers

- [x] **Tier 1 — 100% line-read:** `bin/launch`, `solus/server.py`, `solus/workspace.py`,
      `solus/launch.py` (the only subprocess site), `solus/detect.py`, `solus/gitremote.py`
      (all file reads), `solus/scan.py`, `solus/toolmap.py`, `solus/roster.py`,
      `solus/env_allowlist.py`, `solus/env.allow`. That is every file — ~820 lines.
- [x] **Tier 2** — the `open_in_tool` handler and both file-touching handlers are inside tier 1.
- [x] **Tier 3** — n/a (nothing left unread).
- [x] Non-allowlisted tool code — none exists; `build_server()` raises if the registered set
      ever differs from `TOOL_ROSTER`.
- [x] Depth recorded — above. **Human reviewers must repeat the tier-1 read themselves**; this
      draft is the agent's worksheet, not a sign-off.

## 8. Update path

- [ ] Tree hash on the PROVENANCE sign-off lines — **PENDING(human):** blank until both devs
      sign against `git rev-parse HEAD:integrations/mcp/local`.
- [x] Re-review triggers listed in `PROVENANCE.md` (any `solus/`/`bin/` change, allowlist
      widening, env allowlist change, lockfile change, CVE, a Windows launcher).
- [ ] Both PROVENANCE sign-off lines dated — **PENDING(human).**

---

## Declared sandbox posture

- **macOS / Linux (today):** OS user permissions of the invoking user + `bin/launch` `env -i`
  scrub to seven names with `PATH=/usr/bin:/bin` + cwd = the linked folder + code-level
  confinement (`workspace.py`, symlink refusal in `scan.py`, argv-only spawns with absolute
  binaries in `launch.py`). No writes, no network. Assumes the companion adds nothing further;
  if a per-server sandbox (seatbelt / bwrap) arrives later, the server needs only read access
  to the workspace and the venv, plus the ability to spawn `/usr/bin/open` / `xdg-open` / the
  detected tool binary.
- **Windows:** code paths exist (`detect.py` roots, `os.startfile`), but **no `bin/launch.cmd`
  ships** — the companion refuses the server on Windows (fails closed) until a human approves
  a Windows launcher; `cmd` cannot scrub the environment, so the companion's `child_env`
  allowlist would be the scrub there (same residual the altium fork recorded).

## Residuals for the reviewers

1. NARROWED (finding 3, 2026-09-07): `gitremote.py` follows a worktree `gitdir:` pointer (or a
   `commondir` redirect) only when the resolved target is inside the linked folder or under
   `Path.home()`; anything else answers None. Bounded reads, `HEAD` must exist in the target,
   only origin URL (userinfo stripped) / branch / short sha are surfaced.
2. The lockfile was derived, not compiled, offline (see its header). A network-enabled
   `uv pip compile` regeneration before ship would remove the derivation caveat.
