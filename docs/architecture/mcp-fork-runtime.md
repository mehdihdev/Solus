# MCP fork runtime — Python environments on the customer machine

**Status:** interface frozen for SOLUSDEV-329 (T0); reconciled with the implementation 2026-11-19
(T8). Where the code settled a detail this doc left open, the text below records the code's behaviour.
**Governs:** ADR-031 amendment 2026-11-19,
ADR-034 amendment 2026-11-19. **Related:** `docs/contracts/bridge-protocol.md` (status frame),
`docs/contracts/local-state.md` (`config.json`), `docs/wireflows/settings.md` (Python for local
tools), `apps/desktop/docs/companion-packaging.md`.

## 1. Purpose

The vendored Python MCP forks (`integrations/mcp/{kicad,code,local,altium,gazebo,isaac}`) need a
CPython interpreter with their locked dependencies. A packaged Solus cannot create that inside the
signed, read-only app bundle, and a customer machine may have no usable Python. This document fixes
where each fork's environment lives, how it is built, when the companion trusts it, and the
interfaces between the companion, desktop main, the renderer and the events API.

Not covered: Node forks (`brave` is cloud-launched), builtin servers (`drive`, `machine`),
vendor-run URL servers (Fusion).

## 2. Roots

Environments are large, regenerable caches. They live in the OS app-data folder, **not** in
`~/.solus` (ADR-034's small, private machine-state root). Only the interpreter _choice_ is
machine state (`~/.solus/config.json` → `mcp_runtime`, §8).

| OS      | App-data root (`<data>`)                                              |
| ------- | --------------------------------------------------------------------- |
| macOS   | `~/Library/Application Support/Solus`                                 |
| Windows | `%LOCALAPPDATA%\Solus` — never Electron's `appData` (that is Roaming) |
| Linux   | `$XDG_DATA_HOME/solus`, default `~/.local/share/solus`                |

```
<data>/
  mcp-envs/                  owner-only (§5); the trust root
    <fork>/                  one venv per fork, replaced whole, never patched
      bin/python | Scripts\python.exe
      solus-stamp.json       §4
  mcp-python/                owner-only; the managed interpreter (§7)
    <release>/               e.g. 20261001 — python-build-standalone release tag
      python/…               extracted install_only_stripped tree
```

`<fork>` matches `^[a-z][a-z0-9_-]{0,31}$` and is the fork's directory name.

**Dev override:** `SOLUS_COMPANION_MCP_ENVS_ROOT` (absolute path) replaces `<data>/mcp-envs`
(per-worktree isolation). It obeys the same owner-only rule. Packaged builds never set it.

## 3. Building an environment (setup time only)

1. **Base interpreter** — the user's choice (`path`), the best detected candidate (`auto`), or the
   managed one (`managed`). Accepted only if a health probe
   `<python> -I -c "<fixed probe>"` reports `implementation == "cpython"` and `(major, minor) in
{(3,12),(3,13)}`. Refused: other versions, PyPy, the Microsoft Store alias
   (`…\WindowsApps\python*.exe`). Code: `python_unsupported_version` for other versions, `python_not_cpython`
   for PyPy, `python_store_alias` for the Store alias.
   - **`auto`** (neither `--python` nor `--managed`) = `best_candidate`: the first supported
     candidate in detection order, with a 3.12.x candidate sorted ahead of 3.13.x. No supported
     candidate → `python_not_found`.
   - **Xcode stub:** on macOS, `/usr/bin/python3` is reported `python_unsupported_version` **without
     being executed** when neither `Library/Developer/CommandLineTools` nor `Applications/Xcode.app`
     exists under the system root. Running the stub would pop Apple's install dialog. With developer
     tools installed it is probed like any other candidate.
2. `<python> -I -m venv --copies <tmp>` where `<tmp>` is a sibling of `<data>/mcp-envs/<fork>`.
3. **Health check, before pip.** The copy's interpreter runs the probe immediately after venv
   creation and must resolve inside `<tmp>`. Failure → `venv_copies_unhealthy` (§6), env discarded.
   This fails fast, before any network use.
4. `<tmp-python> -I -m pip --isolated install --require-hashes --only-binary=:all: --no-deps
--no-input --disable-pip-version-check --index-url https://pypi.org/simple -r <lock>` where
   `<lock>` is the fork's shipped `requirements.lock.txt`.
5. Write `solus-stamp.json` (atomic: temp + rename), then atomically swap `<tmp>` into place
   (old env removed only after the new one is complete).

All subprocesses: argv lists only, never a shell. **Child env is built from scratch**
(`scrubbed_env`, `runtime/proc.py`), not filtered from the parent:

- POSIX: only `HOME`, `TMPDIR`, `LANG` are kept, plus a fixed `PATH=/usr/bin:/bin:/usr/sbin:/sbin`.
- Windows: an allowlist (`SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, `USERPROFILE`, `LOCALAPPDATA`,
  `APPDATA`) with a fixed `PATH` built from `SYSTEMROOT`.
- So `PIP_*`, `PYTHON*`, `VIRTUAL_ENV`, `CONDA_*` are never forwarded, and **proxy variables
  (`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, …) are not
  forwarded either.** Known limitation: a user behind a proxy or TLS-intercepting CA gets
  `network_unreachable`. Open follow-up (§12).

Timeouts per step (venv 120 s, pip 600 s per fork); stdout/stderr captured with a 64 KiB cap and
redacted before any of it reaches an error message. One fork failing never stops the others.

## 4. Stamp — `solus-stamp.json` (schema v1)

```json
{
  "schema_version": 1,
  "fork": "kicad",
  "lock_sha256": "<64 lowercase hex of the shipped requirements.lock.txt bytes>",
  "base": {
    "path": "/opt/homebrew/bin/python3.12",
    "version": "3.12.7",
    "implementation": "cpython",
    "managed": false
  },
  "created_at": "2026-11-19T18:04:00Z"
}
```

- All fields required; unknown fields reject; file ≤ 4 KiB; `version` matches `^3\.1[23]\.\d+$`.
- `base.path` is absolute. It is diagnostic, and used for `base_missing` (§5). It never leaves
  the machine (not in events, not in status `detail`).
- A newer `schema_version` → treated as `stamp_mismatch` (rebuild offered, never overwritten
  silently by `status`).

## 5. Trust rule (companion, at discovery — every launch)

A fork with a `requirements.lock.txt` is launched only when ALL hold; otherwise it is reported
`not_launched` with `detail` = the first failing code, and its tools stay unavailable:

| Check (in order)                                                                           | `detail` on failure          |
| ------------------------------------------------------------------------------------------ | ---------------------------- |
| `<envs>/<fork>/` exists with an interpreter and a stamp                                    | `needs_setup:no_env`         |
| `<envs>` and `<envs>/<fork>` are owner-only                                                | `needs_setup:not_owner_only` |
| stamp parses, `fork` matches, `lock_sha256` == sha256 of the shipped lock                  | `needs_setup:stamp_mismatch` |
| interpreter `realpath` is inside `<envs>/<fork>`, and the stamp's `base.path` still exists | `needs_setup:base_missing`   |

The resolve-inside check also fails as `needs_setup:no_env` when the interpreter escapes (a
symlinked venv). The companion then sets `SOLUS_MCP_PYTHON=<resolved absolute interpreter>` for the
launcher; launchers read the interpreter from that variable only (exit 78 when unset or not
executable), never PATH, never an in-tree `.venv`. An in-tree `<fork>/.venv` is ignored.

**Owner-only**

- POSIX: `lstat` not a symlink, `st_uid == geteuid()`, `mode & 0o077 == 0`. Setup creates with 0700.
- Windows: owner is the current user SID; DACL is protected (inheritance off) and has exactly two
  ACEs, both allow: current user SID (full control) and `S-1-5-18` SYSTEM (full control). Setup
  applies exactly that DACL.

`detail` codes are ASCII, ≤ 40 chars — well under the bridge's 512-char `detail` cap — and carry
no paths (bridge-protocol §status hygiene).

## 6. Companion CLI — `solus-companion runtime …`

The only provisioning entry point, for desktop main and `make mcp-forks` alike. Argv only.

| Subcommand        | Args                                                                  | Does                                                                |
| ----------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `detect`          | —                                                                     | Lists interpreter candidates with probe results. Read-only.         |
| `status`          | —                                                                     | Per-fork trust result (§5) for this platform's forks. Read-only.    |
| `provision`       | `--fork NAME` (repeatable) or `--all`; `--python PATH` or `--managed` | Builds envs (§3). `--managed` requires an installed managed Python. |
| `install-managed` | —                                                                     | Downloads + verifies + extracts the managed Python (§7). Network.   |

Common flags: `--envs-root PATH` (dev/test only; mirrors the env override). Forks not supported on
the host platform (`platform.json`) are skipped and reported `fork_result` `skipped`.

**Settled behaviour (code, 2026-11-19):**

- **Base selection in `provision`.** `--python PATH` and `--managed` are mutually exclusive. With
  **neither** flag the mode is `auto`: the best supported candidate, 3.12 preferred (§3 step 1).
  The desktop's `auto` mode sends neither flag; `path` sends `--python`; `managed` sends `--managed`.
- **Usage errors exit 3 with empty stdout.** Covered: neither `--fork` nor `--all`; both `--fork`/`--all`
  forms with an unknown name; a fork name that is not a fork directory; a fork directory with no
  `requirements.lock.txt` (treated as unknown, not as skipped); a relative `--python` or
  `--envs-root`; `--python` together with `--managed`. Nothing is written before a usage error.
- **No integrations root.** `provision` (and `status`) with no forks tree found fails: an `error`
  line with `error_code` `internal`, a `done` with outcome `failed`, exit 2. It never reports `ok`
  for a run that could build nothing, and it writes nothing. The root comes from
  `SOLUS_COMPANION_INTEGRATIONS_ROOT` when set, else a packaged `mcp/` beside the binary.
  Dev desktop sets the variable for the CLI (`runtimeCliEnv`, §9); see §12 for `make mcp-forks`.
- **Oversize candidate lines.** A line over 4096 bytes is **withheld** (not sent, not truncated)
  and logged to stderr. The emitter never truncates a path; a truncated path would be a lie
  the desktop might act on. `clip()` applies only to `message` fields.
- **Cancellation.** SIGINT / SIGTERM / CTRL_BREAK raise `Cancelled` in the build. The in-progress
  fork emits `fork_result` with `outcome` **`failed`** and `error_code` `cancelled` (the
  `fork_result` outcome enum has no `cancelled`; the run-level `done` carries `cancelled`). Forks
  not yet started are not reported. Exit 130.
- **`install-managed` output.** `progress*`, then either one `error` plus `done` `failed`, or a
  `done` `ok` with `ok: 1`. It emits no `fork_result`.

### Output — JSON Lines on stdout

One JSON object per line, UTF-8, each line ≤ 4096 bytes including `\n`. Nothing else is written to
stdout; human logs go to stderr. Every object has `"v": 1` and `"type"`. Readers MUST drop
(and count) any line that is oversize, not JSON, lacks `v: 1`, or has an unknown `type`, and keep
reading; they MUST NOT render raw line text.

| `type`        | Fields                                                                                                                                                                                                                      |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `candidate`   | `path` (abs), `version` (`"3.12.7"` or null), `implementation` (`cpython`\|`pypy`\|`unknown`), `source` (`path`\|`py_launcher`\|`registry`\|`known_location`\|`managed`), `supported` (bool), `reason` (null or error code) |
| `status`      | `fork`, `state` (`ready`\|`needs_setup`\|`unsupported_platform`), `detail` (null or §5 code), `base_version` (null or `"3.12.7"`), `managed` (bool)                                                                         |
| `progress`    | `fork` (null for global steps), `step` (`download`\|`verify`\|`extract`\|`venv`\|`install`\|`check`\|`stamp`), `done` (int ≥ 0), `total` (int ≥ 0 or null)                                                                  |
| `fork_result` | `fork`, `outcome` (`ok`\|`failed`\|`skipped`), `error_code` (null or code below), `message` (≤ 300 chars, redacted, no paths outside the envs root)                                                                         |
| `error`       | `error_code`, `message` (≤ 300 chars) — a failure not tied to one fork                                                                                                                                                      |
| `done`        | `outcome` (`ok`\|`partial`\|`failed`\|`cancelled`), `ok` (int), `failed` (int), `skipped` (int)                                                                                                                             |

`detect` emits `candidate*` then `done` (`ok` = supported candidates, `skipped` = unsupported, `failed` = 0; outcome `failed` with an `error` `python_not_found` when none is supported). `status` emits `status*` then `done` (`ok` = ready, `failed` = needs_setup, `skipped` = unsupported_platform; outcome `ok` regardless, since it is read-only). `provision` and
`install-managed` emit `progress*`, `fork_result*` (provision), optional `error`, then exactly one
`done` as the last line.

**Error codes:** `python_not_found`, `python_unsupported_version`, `python_not_cpython`,
`python_store_alias`, `python_probe_failed`, `managed_not_installed`, `venv_failed`,
`venv_copies_unhealthy`, `pip_failed`, `network_unreachable`, `hash_mismatch`,
`wheel_unavailable`, `managed_download_failed`, `managed_hash_mismatch`, `managed_too_large`,
`managed_extract_refused`, `not_owner_only`, `disk_full`, `timeout`, `cancelled`, `internal`.

**Exit codes:** `0` all ok (or read-only command succeeded) · `1` partial (some forks failed) ·
`2` failed (nothing provisioned / command failed) · `3` usage error (bad argv) · `130` cancelled
(SIGTERM / SIGINT / Windows CTRL_BREAK; the env being built is discarded, finished ones kept).

Golden fixtures: `packages/companion/tests/fixtures/mcp_runtime/`. Both the companion (emitter)
and desktop main (parser) test against them.

## 7. Managed Python (fallback)

Offered only when no supported candidate exists or the user picks it, and only after explicit
consent (Settings, §9). Source: python-build-standalone CPython 3.12, `install_only_stripped`
assets. The manifest is Solus-authored, compiled into the companion (it ships inside the signed
binary), and is the only thing that decides URL, hash and size:

```json
{
  "schema_version": 1,
  "release": "<python-build-standalone release tag>",
  "python_version": "3.12.x",
  "assets": {
    "darwin-arm64": {
      "url": "https://github.com/astral-sh/python-build-standalone/releases/download/<tag>/<file>.tar.gz",
      "sha256": "<64 hex>",
      "max_bytes": 80000000
    },
    "darwin-x64": { "url": "…", "sha256": "…", "max_bytes": 80000000 },
    "win32-x64": { "url": "…", "sha256": "…", "max_bytes": 80000000 },
    "linux-x64": { "url": "…", "sha256": "…", "max_bytes": 80000000 },
    "linux-arm64": { "url": "…", "sha256": "…", "max_bytes": 80000000 }
  }
}
```

**Human gate:** the release tag, asset names and SHA-256 values are chosen and verified by a human
against the release's published `SHA256SUMS`. Until then the manifest carries placeholder hashes
(all zeros) and `install-managed` refuses with `managed_hash_mismatch` — never a real-looking
invented hash.

The shipped manifest (`runtime/managed_manifest.json`) adds one Solus field, **`verified`**
(bool, default `false`), that is the explicit form of the gate. Shipped state today:
`verified: false`, `release: "PLACEHOLDER"`, all hashes zero.

**Refusal order in `install-managed` (code):**

1. No asset for this platform → `managed_download_failed`.
2. `verified` is not `true`, **or** this platform's asset `sha256` is all zeros →
   `managed_hash_mismatch`. This happens **before any network call and before any write**.
   The zero check looks at the current platform's asset only; a placeholder on another platform
   does not block this one. Flipping the flag and hashes is a human gate, together.
3. Download (byte cap enforced while streaming), SHA-256 check, vetted extract, swap.

On success the interpreter is `<data>/mcp-python/<release>/python/bin/python3`
(`python/python.exe` on Windows). `provision --managed` uses that path. The managed root is
`<envs-root>/../mcp-python` (§2), so `--envs-root` moves it too.

Download: HTTPS only, redirects only to `https` GitHub release hosts, streamed to a temp file with
the byte cap enforced while reading, SHA-256 verified **before** extraction. Extraction: tar
`filter="data"` semantics — no absolute paths, no `..`, no links pointing outside the target, no
device files; any refusal → `managed_extract_refused`, temp tree removed. Result lands in
`<data>/mcp-python/<release>/` (owner-only) and is then used by `provision --managed`.

## 8. Machine state — `~/.solus/config.json` → `mcp_runtime`

```json
{ "schema_version": 1, "sol": { … }, "mcp_runtime": { "schema_version": 1, "python": { "mode": "path", "path": "/opt/homebrew/bin/python3.12" } } }
```

`mode`: `auto` (best supported candidate at provision time) · `path` (`path` required, absolute) ·
`managed` (no `path`). Missing key = `auto`. Desktop main is the only writer (read-modify-write,
preserving `sol` and unknown keys, `localState` atomic write); a newer `mcp_runtime.schema_version`
is read-only. See `docs/contracts/local-state.md`.

## 9. Desktop IPC (main ↔ renderer)

All channels are `ipcMain.handle`, sender-gated to the app's own windows (same gate as `sol:*`).
Main spawns the CLI via `resolveCompanionCommand` with `execFile`-style argv; at most one
`provision`/`install-managed` run at a time (a second call rejects `busy`).

| Channel                     | Request                                                            | Response                                                                                 |
| --------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| `mcpRuntime:detect`         | —                                                                  | `{ candidates: Candidate[] }`                                                            |
| `mcpRuntime:status`         | —                                                                  | `{ forks: ForkStatus[] }`                                                                |
| `mcpRuntime:getChoice`      | —                                                                  | `{ mode: 'auto'\|'path'\|'managed', path: string \| null, writable: boolean }`           |
| `mcpRuntime:choose`         | `{ mode, path? }` (`path` absolute, ≤ 4096)                        | `{ ok: true, version_minor } \| { ok: false, error_code }` — `path` is re-probed in main |
| `mcpRuntime:provision`      | `{ trigger: 'settings'\|'first_run'\|'repair', forks?: string[] }` | `{ runId: string }` — then progress events, final `done`                                 |
| `mcpRuntime:installManaged` | `{ consent: true }` (literal)                                      | `{ runId: string }`                                                                      |
| `mcpRuntime:cancel`         | `{ runId }`                                                        | `{ ok: boolean }`                                                                        |

Push channel `mcpRuntime:progress` (main → renderer): `{ runId, event }` where `event` is one
parsed CLI object (§6) with `v` removed. Renderer types mirror §6 exactly. After a `done` with
`ok > 0`, main respawns the companion so the newly trusted forks launch.

**Settled behaviour (code, 2026-11-19):**

- **Main's own probe.** The CLI has no "probe this one path" subcommand. To validate a user-picked
  path, main runs its own fixed probe (`apps/desktop/src/main/mcpRuntime/probe.ts`):
  `<path> -I -c <fixed code>`, argv only, no shell, a from-scratch env (`PATH` only; `SYSTEMROOT`
  on Windows), a 10 s timeout and a 4 KiB output cap. The output is parsed strictly and only the
  version is kept. It refuses the Store alias (`python_store_alias`) by path and by realpath.
- **`choose` results.** `{ mode: 'path' }` with a path returns `{ ok: true, version_minor }`, where
  `version_minor` is `'3.12'`/`'3.13'` (null for `auto`; `'3.12'` for `managed`). `version_minor` is
  additive to §9's shape and feeds `python_tools.interpreter_chosen`.
- **Picker.** `{ mode: 'path' }` without a path opens main's file picker
  (`dialog.showOpenDialog`, `.exe` filter on Windows). Cancelling the picker returns
  `{ ok: false, error_code: 'cancelled' }`. A picked path that fails the probe returns the
  probe's code, and the choice is **not** saved.
- **Error mapping.** Any failure without a §6 code maps to `internal`. A malformed request
  (`choose`, `provision`, `installManaged`) is rejected or returns `internal`. An unauthorised
  sender is rejected.
- **Concurrency.** A second `provision` or `installManaged` while one is running rejects `busy`.
  If the companion command cannot be resolved, a call rejects `unavailable`.
- **Renderer-held state.** The "choice changed → needs setup" marking is computed in the renderer
  (`forksNeedingSetup(forks, choiceChanged)` in `pythonTools/pythonToolsRun.ts`). Main persists no
  per-fork stale flag; after a changed choice every OS-supported fork is queued for setup.
- **Guide-mode "Learn more"** expands in-app text (`LEARN_MORE` in `pythonToolsCopy.ts`). There is
  no docs URL yet: `docs.solusforge.com` does not exist.

## 10. Client events (`POST /api/v1/events`, ADR-011)

Enum and count payloads only — never a path, version patch level or error message.

| `event_type`                      | Payload                                                                                                                                       | When                                      |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `python_tools.interpreter_chosen` | `{ source: 'detected'\|'picked'\|'managed', version_minor: '3.12'\|'3.13' }`                                                                  | `mcpRuntime:choose` succeeds              |
| `python_tools.managed_consent`    | `{ accepted: boolean }`                                                                                                                       | the user answers the managed-Python offer |
| `python_tools.setup_finished`     | `{ outcome: 'ok'\|'partial'\|'failed'\|'cancelled', failed_forks: 0–32, error_code?: <§6 code>, trigger: 'settings'\|'first_run'\|'repair' }` | a provision run's `done`                  |

`error_code` is present only when `outcome != 'ok'` and is the first failing code. Validation is
JSON-strict (integers are integers).

## 11. Residual risks (accepted, carried into the security reviews)

- **Stdlib from the base install.** `--copies` copies the interpreter, not the standard library;
  the venv still loads stdlib from the base install outside `mcp-envs`. The trust rule binds the
  interpreter and site-packages, not the base install's stdlib. `base_missing` catches removal,
  not modification.
- **`--copies` breakage.** conda and pyenv `--enable-shared` builds link libpython via rpath and
  likely fail as copies. The post-create health check reports `venv_copies_unhealthy`, and
  Settings offers the managed Python.
- **3.13 wheels.** Locks were compiled for 3.12 (`--universal`). A pinned package without a cp313
  wheel fails under `--only-binary` as `wheel_unavailable`; fixing it is a lockfile change (fork
  re-review).
- **Microsoft Store Python** is refused (`python_store_alias`): app-execution aliases and AppData
  redirection make its paths unstable.
- **PyPI-only.** Users behind a mirror or blocking proxy get `network_unreachable`; there is no
  index override in this cycle. Proxy variables are not forwarded to setup children either
  (§3, "child env"); see §12.
- **Launcher changes are guarded by review only.** The tree-hash test covers `upstream/` and
  `vendor/`, not `bin/`; both-devs re-sign is the gate.

## 12. Open follow-ups (not blocking this cycle)

- **Proxy support.** Setup children get no proxy variables (§3). A packaged build behind a
  corporate proxy or TLS-intercepting CA cannot run `provision`. Needs a decision on which
  variables to admit (`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`/`_DIR`,
  `REQUESTS_CA_BUNDLE`) and how to validate them. The same gap is recorded for the packaged
  companion in `apps/desktop/docs/companion-packaging.md`.
- **Dev entry point.** `scripts/install-mcp-forks.sh` runs `runtime provision` through `uv run`,
  whose interpreter is `.venv/bin/python`. With no integrations root from the environment, the
  companion finds no `mcp/` beside it and fails with `internal` (§6). The script must export
  `SOLUS_COMPANION_INTEGRATIONS_ROOT` to the repo's `integrations/mcp`. Until it does,
  `make mcp-forks` needs that variable set in the caller's shell.
- **Managed Python go-live.** Real release tag, asset names and SHA-256 values, then
  `verified: true` (§7). Human gate. Until then Settings can show the managed offer, and install
  fails with `managed_hash_mismatch`.
- **Windows launchers.** `launch.cmd` exists for `kicad`, `code` and `local`. Not verified on
  Windows.
- **Help link.** Guide-mode "Learn more" is in-app text. A docs page needs `docs.solusforge.com`
  (not yet built) or a path under the marketing site.
