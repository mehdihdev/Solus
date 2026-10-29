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
- **Why macOS is onedir: signed in place.** A onefile binary is a bootloader
  that unpacks the interpreter and its libraries into a temp dir at run time —
  code that was never signed. Onedir ships every Mach-O on disk, each signed
  (below), so the companion that runs is exactly the code that was signed and
  notarised.
- PyInstaller is pinned (`PYINSTALLER_VERSION` in the script, currently
  6.22.3 — the latest 6.x on PyPI on 2026-10-28; it was not in the local uv
  cache). The bootloader is part of the shipped binary, so bump it
  deliberately.
- The MCP tree always sits beside the binary because
  `config.default_integrations_root` looks for `mcp/` next to `sys.executable`
  (pinned for both layouts in `packages/companion/tests/test_fork_runtime.py`).
- The script removes `dist/companion/` first, so switching modes never leaves a
  file where a folder belongs.
- PyInstaller is deliberately **not** in any pyproject: the script uses
  `uv run --package solus-companion --with pyinstaller`, layering it ephemerally
  over the companion's real environment so websockets/mcp/pydantic are visible
  to its analysis. (Verified working with PyInstaller 6.21.0 on Linux ARM;
  the binary boots to companion config validation. The 6.22.3 pin has not been
  built yet.)
- Copies the vendored MCP tree beside the binary (excluding `*.template.md`
  scaffolding).
- Build per-platform — PyInstaller does not cross-compile.
- If a future dependency hides imports from the analyzer, add
  `--hidden-import` / `--copy-metadata` flags in the script.

`apps/desktop/electron-builder.yml` ships `dist/companion/` via
`extraResources` at `<resources>/companion/`. Run the companion build before
`electron-builder`, e.g. `./scripts/build-companion.sh && pnpm build:linux`.

### macOS signing

When `SOLUS_SIGN_IDENTITY` is set on macOS, `build-companion.sh` signs every
Mach-O under `solus-companion/_internal/` first, then the main binary with
`--options runtime --timestamp --identifier com.solusforge.solus.companion`,
and verifies the binary against the Solus team's Developer ID requirement
(`SOLUS_TEAM_ID`, ten upper-case letters/digits, is required):

```
anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6]
  and certificate leaf[field.1.2.840.113635.100.6.1.13]
  and certificate leaf[subject.OU] = "<SOLUS_TEAM_ID>"
  and identifier "com.solusforge.solus.companion"
```

Unset ⇒ a warning and an unsigned build, which cannot be notarised. Under the
XPC design (ADR-041 amendment 2026-10-28) the drive agent checks only
Solus.app's signature — the companion never talks to it — so the companion's
signature matters for notarisation and integrity, not for driving.
electron-builder's `mac.signIgnore` leaves it untouched, so Solus.app's own
entitlements are never applied to it.

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

### Drive calls: the companion relays, the desktop reaches the agent (slice 3b, XPC)

The companion never talks to the `solus-input` agent and no longer reads
`SOLUS_DRIVE_HELPER`; `SOLUS_COMPANION_DRIVE=1` (plus macOS and a linked
workspace) is the only switch. The agent is an XPC Mach service registered by
Solus.app with SMAppService while "SOL can use your mouse and keyboard" is on;
its only client is Solus.app's main process. The companion relays each drive
call to main over the stdin/stdout pipe main created for it
(`packages/companion/src/solus_companion/drive/helper.py`, `DriveRelay`):

- **Request.** One stdout line `{"type":"drive_request","id":N,"argv":[…]}`,
  flushed; ids increase. argv is `identify`, `capture` or `act` with its flags.
- **Reply.** Main answers on stdin with `{"type":"drive_reply","id":N,
  "reply":{…}}`; `config.apply_token_line` routes it to the pending call. ONE
  deadline covers the call. A reply over 24 MiB as JSON fails the call
  (`helper_output`); the reply must be one JSON object with an `ok` flag.
  Unknown or late ids are dropped. Agent-side failures arrive as replies with
  a refusal code (`agent_unavailable` when main cannot reach the agent).
- **Cancel.** Timeout or cancellation (Stop, a dropped bridge) writes
  `{"type":"drive_cancel","id":N}`; main stops the call in flight.
- **Stdin bounds.** The reader limit is 25 MiB so a capture-sized reply fits.
  Every other control line keeps its 32 KiB bound and is refused before
  parsing exactly as before; an oversize line is parsed only if it starts with
  `{"type":"drive_reply",` (main serialises `type` first) and is refused if it
  then turns out not to be a drive reply. Without a stdin control channel the
  relay is not attached and calls refuse `agent_unavailable` at once.
- **Stdout** carries only `drive_request`, `drive_cancel` and the
  `drive_window` outline lines; logging goes to stderr.

### Known limitation: allowlisted environment (no proxy variables)

A packaged companion does not inherit the app's environment wholesale
(ADR-041 amendment 2026-10-28): `companionEnv` in
`src/main/companionEnv.ts` passes only `PATH`, `HOME`, `USER`, `LOGNAME`,
`TMPDIR`, `LANG` and `LC_*` (`PACKAGED_ENV_ALLOWLIST`), then sets the
`SOLUS_COMPANION_*` values itself. Inherited `SOLUS_COMPANION_*` and `PYTHON*`
are deliberately ignored. A side effect is that `HTTPS_PROXY` / `HTTP_PROXY` /
`NO_PROXY`, `SSL_CERT_FILE` / `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE` and similar
are **not** passed, so a packaged companion behind a corporate proxy or a
TLS-intercepting CA cannot reach the cloud. Dev runs are unaffected because
they inherit the full environment. Supporting proxies needs a follow-up
decision on which variables to admit and how to validate them. Do not widen
the allowlist ad hoc.

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
