# Companion packaging & supervision (SOLUSDEV-154 / BRG-04)

How the local-bridge companion (`packages/companion`, Python) is launched in dev,
built for release, shipped inside the Electron app, and cleaned up. Win/mac are
**config + docs only this cycle** — only Linux ARM (the dev box) is validated.

## Dev mode

The main process resolves the companion via `resolveCompanionCommand`
(`src/main/companion.ts`):

- **Packaged app**: `<resources>/companion/solus-companion` (`.exe` on Windows),
  no args. On macOS the binary is one level deeper,
  `<resources>/companion/solus-companion/solus-companion` (onedir — see below);
  `resolveCompanionCommand` must resolve that path on darwin.
- **Dev** (`app.isPackaged === false`): the `SOLUS_COMPANION_DEV_CMD` env var,
  split on whitespace, e.g.

  ```sh
  SOLUS_COMPANION_DEV_CMD='uv run python -m solus_companion' pnpm dev
  ```

- Neither ⇒ companion disabled for the run (one `console.warn` notice).

The child inherits the app's environment, so `SOLUS_COMPANION_URL` /
`SOLUS_COMPANION_INTEGRATIONS_ROOT` etc. pass straight through. The Supabase
access token is **never** in the environment or argv: the renderer's
`authStore.setSession` (the single choke point for sign-in / TOKEN_REFRESHED /
sign-out) relays it over IPC (`bridge:token`) and the main process writes
newline-delimited JSON to the companion's stdin —
`{"type":"token","access_token":"…"}`, or `{"type":"signout"}` on sign-out.
The latest token is remembered (in memory only) and replayed on respawn.

## Building the companion binary

```sh
./scripts/build-companion.sh
```

- Runs PyInstaller over `packages/companion/src/solus_companion/__main__.py`
  with `-p packages/companion/src`. The mode depends on the host:
  - **Linux / Windows — `--onefile`**: repo-root `dist/companion/solus-companion`
    (`.exe` on Windows), with the MCP tree at `dist/companion/mcp/`.
  - **macOS — `--onedir`** (sol-drive.md §5, ADR-041 amendment 2026-10-27):
    `dist/companion/solus-companion/solus-companion` plus PyInstaller's
    `_internal/`, with the MCP tree at `dist/companion/solus-companion/mcp/`.
    Packaged, that is `<resources>/companion/solus-companion/solus-companion`.
- **Why macOS is onedir.** A onefile binary is a bootloader that unpacks to a
  temp dir and runs the real interpreter as a *child* process. The SOL drive
  helper (`solus-input`) checks its caller: its parent must be the signed
  companion started with no arguments, and that parent's parent must be
  Solus.app. Under onefile the helper's parent is the unpacked child and
  its grandparent is the bootloader, not Solus.app, so every drive call would
  fail `caller_untrusted`. Onedir runs the interpreter in the one process
  Solus.app spawned.
- The MCP tree always sits beside the binary because
  `config.default_integrations_root` looks for `mcp/` next to `sys.executable`
  (pinned for both layouts in `packages/companion/tests/test_fork_runtime.py`).
- The script removes `dist/companion/` first, so switching modes never leaves a
  file where a folder belongs.

### macOS signing (what the drive helper requires)

The drive helper's caller check (ADR-041 amendment 2026-10-27) accepts only a
parent whose signature satisfies:

```
anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6]
  and certificate leaf[field.1.2.840.113635.100.6.1.13]
  and certificate leaf[subject.OU] = "<SOLUS_TEAM_ID>"
  and identifier "com.solusforge.solus.companion"
```

i.e. a Developer ID Application certificate of the Solus team, with the code
identifier **`com.solusforge.solus.companion`**. When `SOLUS_SIGN_IDENTITY` is
set on macOS, `build-companion.sh` signs every Mach-O under
`solus-companion/_internal/` first, then the main binary with
`--options runtime --timestamp --identifier com.solusforge.solus.companion`,
and verifies the binary against the requirement above (`SOLUS_TEAM_ID`, ten
upper-case letters/digits, is required). Unset ⇒ a warning and an unsigned
build, whose drive calls a release helper refuses (`caller_untrusted`).

Entitlements: none beyond the hardened runtime. A onedir build loads its
extension modules and Python library from signed files on disk under one team
signature, so library validation passes without
`disable-library-validation`. Not yet verified with a real identity: if a
ctypes callback ever fails under the hardened runtime, the candidate is
`com.apple.security.cs.allow-unsigned-executable-memory` — add it only with
that evidence and record why here.

`make desktop-mac` builds the companion (`companion-bin`) and the helper bundle
(`solus-input-app`, `scripts/build-solus-input.sh`) before
`pnpm --filter @solus/desktop build:mac`.

### Where the helper may live (`SOLUS_DRIVE_HELPER`)

The companion refuses a helper path (`resolve_helper`, treated as no helper)
unless it is an absolute, symlink-free, executable regular file that is not
group- or other-writable. Every **ancestor directory** must also be safe:
other-writable is refused unless the directory is sticky; group-writable is
allowed only when the directory is owned by root (uid 0). That admits
`/Applications` (`drwxrwxr-x root:admin` — an admin can replace anything there
anyway) and refuses a user-owned group-writable folder.
- PyInstaller is deliberately **not** in any pyproject: the script uses
  `uv run --package solus-companion --with pyinstaller`, layering it ephemerally
  over the companion's real environment so websockets/mcp/pydantic are visible
  to its analysis. (Verified working with PyInstaller 6.21.0 on Linux ARM;
  the binary boots to companion config validation.)
- Copies the vendored MCP tree beside the binary (excluding `*.template.md`
  scaffolding).
- Build per-platform — PyInstaller does not cross-compile.
- If a future dependency hides imports from the analyzer, add
  `--hidden-import` / `--copy-metadata` flags in the script.

`apps/desktop/electron-builder.yml` ships `dist/companion/` via
`extraResources` at `<resources>/companion/`. Run the companion build before
`electron-builder`, e.g. `./scripts/build-companion.sh && pnpm build:linux`.

## Supervision, pidfile, orphan reap

`src/main/companion.ts`:

- Spawned `detached` on POSIX so the companion leads its own process group;
  tree signals use `kill(-pid)` (fallback `kill(pid)`), Windows uses
  `taskkill /pid <pid> /T /F`.
- Unexpected exit ⇒ restart with equal-jitter exponential backoff, 1 s doubling
  to a 30 s cap, reset after 60 s stable uptime. Never restarts after
  `stopCompanion()`.
- `<userData>/companion.pid` is written at spawn. On the next app start, a live
  pid found there (e.g. after the app was SIGKILLed) is SIGTERMed as an orphan
  tree before takeover — but only after an identity check, since a stale pid
  may have been recycled by the OS to an unrelated same-user process: on Linux
  `/proc/<pid>/cmdline` (on macOS `ps -p <pid> -o command=`) must contain
  `solus-companion` or `solus_companion` (covers the packaged binary and the
  dev `python -m solus_companion`). On Windows there is no equally cheap
  identity read, so the reap is skipped entirely and the pidfile is just taken
  over — a true win32 orphan exits on its own when the cloud closes its
  superseded socket. The pidfile is removed on clean stop.
- `before-quit` holds the quit, SIGTERMs the tree, waits 3 s, SIGKILLs, then
  resumes quitting. `app.requestSingleInstanceLock()` guarantees one supervisor
  (a second launch focuses the first window and exits).

## Uninstall behavior per OS

- **Windows (NSIS)**: the uninstaller removes `<resources>/companion` with the
  app. **Gap**: uninstalling while the app (and companion) runs — NSIS prompts
  to close the running app; the companion dies with the app's process tree via
  the quit path. A companion orphaned by a hard-killed app is never reaped on
  win32 (the pid-recycling guard skips the reap there — see the pidfile section
  above), and no next launch comes after uninstall anyway. Known v1 gap;
  acceptable because the orphan holds no credentials on disk and exits when its
  cloud socket is closed server-side.
- **Linux AppImage**: "uninstall" = deleting the AppImage file; a running
  companion keeps its deleted binary mapped until exit. Same orphan note as
  above. `deb`: `apt remove` deletes files, no process management — quit the
  app first. `snap` (if used): snapd terminates the app's cgroup, taking the
  companion with it.
- **macOS**: dragging the `.app` to Trash does not stop running processes —
  quit the app first (quit tears the companion down). The pidfile lives in
  `~/Library/Application Support/Solus/` and is orphaned harmlessly.

## Auto-update (honest v1)

The companion binary and the vendored MCP servers ship **inside** app releases —
one artifact, one version. `electron-updater` is a dependency but is **unwired**:
no `publish` feed exists yet (release decision, SOLUSDEV-148/149). Until then,
updates are manual reinstalls. The wire protocol already covers forced
upgrades: the cloud closes the companion's WebSocket with code **4400 =
"update required"**, and the companion stops rather than reconnect-looping on an
incompatible protocol; the UI's bridge pill shows it offline.

## Code signing (external blocker: certs)

Signing is the last, swappable step of packaging (see the comment in
`electron-builder.yml`): Windows picks up `CSC_LINK`/`CSC_KEY_PASSWORD` at
build time; macOS needs a Developer ID identity plus flipping `notarize: true`.
Nothing else in the pipeline changes when certs land. This cycle: unsigned,
Linux ARM only.

## Linux ARM unsigned validation checklist

Steps 1–2 verified 2026-07-30 (`solus-1.0.0.AppImage`, 170 MB, companion +
vendored MCP tree present under `resources/companion/`). Two build-infra fixes
made it work: no nested `pnpm-workspace.yaml` may exist in this app dir (it
shadows the root workspace and breaks every pnpm call — build-script allowances
belong in the ROOT pnpm-workspace.yaml), and electron-builder ≥26.15 is
required (26.0.x's pnpm dependency collector fails on the symlinked store).
Steps 3–6 need a display — run them on the dev box, not headless.

1. `./scripts/build-companion.sh` — builds `dist/companion/`.
2. `pnpm --filter @solus/desktop build:linux` — packages the AppImage with
   `extraResources`.
3. Run the AppImage; sign in. `pgrep -f solus-companion` shows the companion.
4. Quit the app normally. `pgrep -f solus-companion` is empty (SIGTERM path).
5. `kill -9` the app's main process (companion is orphaned).
6. Relaunch the AppImage: the orphan is reaped via the pidfile
   (`pgrep` shows exactly one fresh companion).
