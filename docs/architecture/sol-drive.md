# Architecture — SOL drives desktop tools (ADR-041)

**Ticket:** SOLUSDEV-319 follow-up (kept on the 319 branch at the human's request). **Governing decision:**
DECISIONS.md ADR-041 (supersedes ADR-040 §2). Companions: `docs/architecture/sol-window.md` (the Ember
Pill), `docs/contracts/bridge-protocol.md`, `docs/contracts/action-gate.md`, ADR-019/026 (budgets,
routing), ADR-011 (data events). Design: canvas "SOL Quick Summon", board A3 (driving).

Approved in-chat (2026-10-26): the drive loop uses an Anthropic model with its computer-use tool; the
three-part split below; first slice = this doc + the helper + the companion server.

## 1. Where each part runs

```
cloud API                                   user's machine
─────────                                   ──────────────
SOL agent ── drive.step(app, intent) ──┐
  (gated: approval card / plan step)   │
                                       ▼
  DriveStepExecutor (bounded loop) ── bridge tool_call ──▶ companion ─ DriveServer (built-in "drive")
    model: computer-use (ADR-026)       drive.identify                    │ argv only, pinned path
    each turn: fresh user turn          drive.capture  ◀─ image artifact ─┤
      with the latest capture           drive.act                         ▼
    validate → act → re-capture                                       solus-input (signed helper app)
                                                                        identify · capture · act
                                                                        checks + kill switch
desktop renderer (pill) ◀── step progress events (turn stream) ── A3 status line + amber outline
```

- **Model credentials never leave the API.** The local side never calls a model; the API side never
  posts input. The bridge carries only `drive.*` tool calls and their results (§3).
- **The helper enforces the drive policy** — everything ADR-041 §5 requires is checked inside
  `solus-input` immediately before each event (§2). **It is the security boundary only once it alone
  holds the OS grants (§5, slice 3).** macOS attributes Accessibility and Screen Recording to the
  _responsible_ process: launched desktop app → companion → helper, the grant would belong to Solus.app,
  and every other child of the app (each MCP server the supervisor starts, every command SOL runs) could
  post events or capture the screen itself with none of these checks. Slice 3 therefore ships the helper
  as its own signed, `LSUIElement` app bundle that holds the grants, launched with responsibility
  disclaimed, which verifies its caller's code signature (Solus team ID) — Solus.app itself never holds
  Accessibility or Screen Recording. Until then nothing is wired (§3) and no grant is requested.

## 2. `solus-input` (slice 1)

Location `apps/desktop/native/solus-input/` (Swift package: `SolusInputCore` pure library, `solus-input`
executable, XCTest suite). macOS 14+ (ScreenCaptureKit). One process per call; **argv in, one JSON line
out**, exit 0 for every outcome including refusals and usage errors (the JSON `code` says which); a
non-zero exit means the helper crashed. All times are the helper's **monotonic** clock (system uptime).
Every command also takes **`--within WS`**: the linked workspace (absolute, resolved, never `/`), without
which it is a `usage` refusal (ADR-041 amendment M2, 2026-10-26).

| Command    | Arguments                                                                       | Result                                                                                                                                                                                                                                                                                                                                                        |
| ---------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `identify` | —                                                                               | `{ok, now, trust:{accessibility,screenRecording}, allowed, app:{bundleId,pid,name}\|null, window:{id,title,bounds}\|null}`. When the frontmost app is NOT drivable, or is drivable but working outside `WS` (`outsideWorkspace: true`), `app` and `window` are null — another app's (or another project's) identity and window title never leave the machine. |
| `capture`  | `--bundle B --window W [--max-edge N]` (256–2048, default 1568)                 | `{ok, png (base64), imageWidth, imageHeight, pointsWidth, pointsHeight, bounds}`; refuses unless W is on screen, owned by B, and B is drivable; shadow-free, and refused (`capture_failed`) if the image's shape does not match the window's (padding would skew coordinates).                                                                                |
| `act`      | `--bundle B --window W --since T [--expect-width w --expect-height h] <verb> …` | `{ok, verb, idleSeconds, finishedAt, bounds}` or a refusal (mid-verb refusals add `postedEvents`).                                                                                                                                                                                                                                                            |
| `trust`    | `[--prompt]` (no `--within`)                                                    | `{ok, trust:{accessibility,screenRecording}, unsignedDev}`. The desktop's permission rows; `--prompt` asks macOS to show both permission prompts for the helper. Slice 3b: reached only as the agent's `trust` op (§2.1).                                                                                                                                     |

`act` verbs (window-relative **points**, integers): `click --x --y [--button left\|right] [--count 1\|2]`
(no right double-click — a right click opens a menu), `move --x --y`, `drag --x --y --to-x --to-y`,
`scroll --x --y --dy [--dx]`, `key --chord cmd+shift+z`, `type --text "…"`, `wait --ms` (≤ 2000).

`bounds` is `{x, y, width, height}` of `W` in global points (top-left origin), re-read for that reply;
the companion forwards it to the desktop for the amber outline (§3, §5).

Checks before ANY event is posted (each failure is a refusal with a code; nothing is posted):

- **Caller** (slice 3b, ADR-041 amendment 2026-10-28): in a release build commands reach the helper only
  as XPC messages to the agent (§2.1) from Solus.app's main process; launchd starts it, so there is no
  parent to check (the slice 3 parent-chain check, the disclaim launcher and the 3b socket are removed).
  A release build run any other way is a `usage` refusal. Debug builds (`SOLUS_INPUT_UNSIGNED_DEV`,
  Package.swift debug configuration only) accept the commands on argv instead — dev main runs one process
  per call — skip every code-requirement check and report `unsignedDev: true`; they have no XPC listener.
- **Workspace** (every command with `--within`): absolute, resolved, not `/`, and neither the user's home
  directory nor any ancestor of it (home from `getpwuid`, never `$HOME`; byte compare by whole segment) —
  `usage` otherwise.

0. **Project binding** (capture and act): the process that owns `W` has its working directory at or below
   `WS` — read from the kernel (`proc_pidinfo` `PROC_PIDVNODEPATHINFO`, no grant needed), resolved; an
   unreadable one counts as outside (`outside_workspace`, no path in the message). KiCad works in its open
   project's folder; probed on KiCad 10, which exposes no `AXDocument` and puts no path in its title, so
   the working directory is the only signal there is. `act` repeats this before every posted event.

1. `B` is on the compiled-in drivable list — slice 1: `org.kicad.kicad`, `org.kicad.eeschema` (the
   schematic editor runs inside either). Amendments to ADR-041 widen it.
2. Accessibility is trusted (`AXIsProcessTrusted`).
3. The owner of the front-most layer-0 window (read live from the window server, not NSWorkspace) is
   `B`, and that window is `W`. Bounds are re-read, so a moved window still maps correctly; with
   `--expect-width/--expect-height` (the size last captured), a resize refuses `window_resized`.
4. Coordinates are inside `[0,width) × [0,height)` of that window, and **below its title bar** (close,
   minimise, zoom and the double-click-to-zoom strip; height from the AX close button, 28 pt fallback)
   — `window_chrome`. Closing needs its own approval (ADR-041 §4).
5. **Hit-test:** every pointer target's topmost visible on-screen window (any layer) is `W` itself —
   anything on top, Solus's own pill included, refuses with `occluded` (SOL must never be able to click
   its own Run button). Consequence for slice 3: the amber outline is drawn as edge strips OUTSIDE the
   window bounds, never as a window over it.
6. `key`: the chord parses and is on the **chord allowlist** (an allowlist cannot miss a system
   shortcut): an editing key alone or with shift (letters, digits, punctuation, Return, Escape, Tab,
   Space, Delete, arrows, Home/End/Page keys — never F-keys), or `cmd` + `z a f g = - 0`, or
   `cmd+shift+z`. **No clipboard chords** (ADR-041 §5): `cmd+c`/`cmd+x` overwrite the user's clipboard
   and `cmd+v` could carry a copied secret into the app and the next capture. Everything else — app
   switching, quit/close/hide, Spotlight, lock, screenshots, Spaces, save/print, any `ctrl`/`option`
   combination — refuses with `chord_denied`.
7. `type`: 1–200 Unicode scalars of visible text only — letters, marks, numbers, punctuation, symbols,
   the space — never control, format, private-use (U+F704 is Cocoa's F1) or line/paragraph separators.
8. **Password fields:** for `type` AND `key`, the bound process's focused element must readably NOT be
   an `AXSecureTextField`; "could not read focus" counts as secure (`secure_field`).
9. **Kill switch:** `--since T` comes from the helper's clock — `identify.now` (the step start), then
   each `act.finishedAt` — so the check never compares the cloud clock with the local one. `T` must be
   finite, not in the future and at most 10 minutes old. If the HID system has seen input more recently
   than `T`, refuse with `user_active`.

While posting, before EVERY event: a SIGTERM (the companion stopping the step) ends the verb with
`stopped`; the bound app and window must still be in front (`focus_lost`); there must be no input since
our previous post, allowing 3 ms for our own event to land (`user_active` — fails closed if delivery is
slower); and a pointer event is hit-tested again (`occluded` — a menu or dialog may have opened). Every
mid-verb stop reports `postedEvents`. A button still held when a verb stops is released globally while
the press point is still over `W` (where the window server tracks it), otherwise to the bound process
only (a global release over a popup menu would choose an item). Keyboard and text events go to the bound
process only (`CGEvent.postToPid`); pointer and scroll events post globally at the hit-tested point.
Posted events carry a Solus marker in `eventSourceUserData`. The desktop's key listener (`uiohook-napi`)
cannot read it, so slice 3 instead quiets the hotkey and circle detectors while a step runs (§5); the
chord policy (check 6) already means SOL never posts a `ctrl` key.

Refusal codes: `usage`, `app_not_allowed`, `not_trusted`, `screen_recording_denied`, `not_frontmost`,
`window_mismatch`, `window_not_found`, `window_resized`, `window_chrome`, `out_of_bounds`, `occluded`,
`bad_chord`, `chord_denied`, `bad_text`, `secure_field`, `user_active`, `focus_lost`, `stopped`,
`capture_failed`, `outside_workspace`, `caller_untrusted`.

Known limits (documented, not hidden): letter keys map to ANSI virtual keycodes (non-US layouts may
differ); effects outside the app are blocked structurally — plot, export, print and close-confirm all
go through dialogs, sheets or menus, which are other windows (checks 3 and 5, and the menu bar lies
outside the window) — except a toolbar **Save** click, which the companion detects (§3) and which ends the
step (ADR-041 amendment M3); a schematic opened from outside the project inside the same KiCad process
would pass check 0, and its window title would then reach identify (verified in the QA pass; accepted
residual — the working directory is the only signal KiCad gives); a microsecond gap
remains between the last hit-test and a global pointer post (inherent); the kill switch's reading of the
HID idle counter and the stuck-button release are verified on real hardware in the QA pass, not in unit
tests; the bundle id is not yet tied to KiCad's code signature (to add when the list widens).

### 2.1 Agent mode (slice 3b, XPC — ADR-041 amendment 2026-10-28)

The release helper runs as a **launchd agent** offering the XPC Mach service
`com.solusforge.solus.input.agent`, registered by Solus.app with SMAppService
(`app.setLoginItemSettings({type: 'agentService', serviceName: 'com.solusforge.solus.input.agent.plist'})`)
only while the drive setting is on and the helper is installed, unregistered otherwise. launchd starts it
on demand, so it is its own responsible process and the grants attach to SolusInput.app. Launch agent plist
(`Solus.app/Contents/Library/LaunchAgents/com.solusforge.solus.input.agent.plist`): `Label` and
`MachServices` `{com.solusforge.solus.input.agent: true}`, `BundleProgram`
`Contents/Resources/SolusInput.app/Contents/MacOS/solus-input`, `ProgramArguments` `[solus-input, serve]`,
no `RunAtLoad`, no `KeepAlive` (on demand; the agent exits after 60 s idle), `ProcessType`
`Interactive`, `AssociatedBundleIdentifiers` `[com.solusforge.solus]`.

**Who may talk to it.** The listener calls `setConnectionCodeSigningRequirement` with Solus.app's
requirement (`identifier "com.solusforge.solus"`, team ID, Developer ID clauses), so XPC checks every
message's send-time audit token; a process that sends and then execs fails (exec changes its pidversion —
reproduced on this machine), and a renderer or other Electron helper (`com.solusforge.solus.helper.*`)
never matches. The client (main's native module, below) sets the agent's requirement
(`com.solusforge.solus.input`) on its connection, so nothing else can pose as the agent (launchd owns the
service name too). The agent checks its own signature at start and exits on failure. The placeholder team
ID makes every requirement fail (release fails closed until a human sets it).

**Interface** (`@objc protocol SolusInputAgent`): `handle(_ request: Data, reply: (Data) -> Void)` and
`cancel()`. `request` is one JSON object (≤ 64 KiB):

| `op`    | Request                              | Reply                                                             |
| ------- | ------------------------------------ | ----------------------------------------------------------------- |
| `trust` | `{"v":1,"op":"trust","prompt":bool}` | the `trust` reply (§2)                                            |
| `run`   | `{"v":1,"op":"run","argv":[...]}`    | the runner's reply for `argv` (`identify`, `capture`, `act` only) |

Requests run one at a time on a serial queue. `cancel()` — or the connection being invalidated (main
quit, the companion relay dropped the call) — is the old SIGTERM: the runner stops before its next event
(`stopped`) and releases a held button. The kill switch and every §2 check are unchanged. Refusals:
`usage` (malformed request, unknown op, `argv` not identify/capture/act); a connection that fails the
requirement never reaches `handle`.

**The native module** (`apps/desktop/native/solus-input-xpc/`, Node-API, Objective-C++): exports
`request(json: string, timeoutMs: number): Promise<string>` and `cancel(): void`; one
`NSXPCConnection(machServiceName:)` with `setCodeSigningRequirement(agent)`, re-created after
invalidation; a deadline per request (on expiry it calls `cancel()` and rejects). Loaded only in packaged
builds, from inside the app bundle.

**Residuals (accepted; recorded here and in the completion report):** files swapped after the bundle
check, between spawn and use, are not re-checked; consent (`sol.drive`) and the folder registry live in
user-writable `~/.solus`, so a same-user process can forge them — it then needs the real Solus.app and the
user's session to get a drive step from the cloud; a user LaunchAgent that claims the Mach service name
first sees main's requests (the workspace path, typed text) but cannot answer them (the client requires
the agent's signature), so drive fails rather than misbehaves.

### 2.2 Frontmost-app driving (SOLUSDEV-319 slice 4, ADR-041 2026-10-31)

Governing text: ADR-041 amendments "frontmost-app driving" and "window-bound driving without a workspace"
(both 2026-10-31). They replace ADR-041 §3 (the allowlist) and narrow M2. **Where this section and §2–§5
disagree, this section wins**; the earlier sections describe slices 1–3b. Unchanged: §2 opt-in / Build
only, §4 budget, §5 vocabulary and checks (secure-field refusal included), §7 kill switch, §9, the team
policy flag, the XPC transport (§2.1) and main as the agent's only client.

**Three classes of app**, decided by the helper from the window owner's bundle id (never the title):

| Class             | Members                                        | Binding                                                                                | Workspace                                                    |
| ----------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| **Denied**        | the denylist below, Solus itself, no bundle id | none — never captured, never driven                                                    | —                                                            |
| **Project-bound** | `org.kicad.kicad`, `org.kicad.eeschema`        | M2: the window's process works at or below `--within` (unchanged §2 check 0)           | **required** (no linked folder ⇒ KiCad is not drivable)      |
| **Window-bound**  | every other app with a bundle id               | the summon snapshot `{bundleId, pid, windowId}`, re-verified before every `drive.step` | **not required**; when present it only scopes the save watch |

**The denylist** (compiled into `solus-input` as `DeniedApps`; widening or narrowing it is an ADR-041
amendment; the API and main never decide denial themselves). Matching: the window owner's
`CFBundleIdentifier`, compared **byte-exact** (case-sensitive) against an entry, or — for the entries
marked _family_ — equal to the entry or starting with the entry followed by `.` (so `com.google.Chrome`
family matches `com.google.Chrome.canary`, `com.google.Chrome.beta` and Chrome's PWA shims
`com.google.Chrome.app.*`, but not `com.google.Chromecast`). An owner with no bundle id, or one not matching
`^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$`, is denied.

- **Terminals and shells** (typing runs commands outside the ADR-031 sandbox): `com.apple.Terminal`,
  `com.googlecode.iterm2`, `dev.warp.Warp-Stable`, `dev.warp.Warp-Preview`,
  `com.mitchellh.ghostty`, `net.kovidgoyal.kitty`, `org.alacritty`, `com.github.wez.wezterm`,
  `co.zeit.hyper`; script runners, which are shells by another name: `com.apple.ScriptEditor2`,
  `com.apple.Automator`, `com.apple.shortcuts`, `com.latenightsw.ScriptDebugger8` (Script Debugger).
- **General-purpose hosts** (they open and run anything — apps, scripts, installers): `com.apple.finder`.
- **Remote-desktop and VM consoles** (they reach other machines and run commands there; ADR-041 amendment
  2026-11-01, M-1 — SOLUSDEV-319 Phase 4): `com.apple.ScreenSharing`, `com.microsoft.rdc.macos`,
  `com.utmapp.UTM`, `com.vmware.fusion`, `com.teamviewer.TeamViewer`, `com.philandro.anydesk`,
  `com.realvnc.vncviewer`, `tv.parsec.www`; families `com.parallels.desktop`, `org.virtualbox.app`,
  `com.p5sys.jump` (Jump Desktop) _(family)_.
- **Launchers and automation tools** (they run arbitrary actions and scripts; same amendment):
  `com.raycast.macos`, `org.hammerspoon.Hammerspoon`; families `com.runningwithcrayons.Alfred`,
  `com.stairways.keyboardmaestro` _(family)_.
- **Python REPLs** (they run arbitrary code; same amendment): `org.python.IDLE`, `org.thonny.Thonny`.
- **Disk imagers** (they write whole devices; same amendment): `io.balena.etcher`,
  `org.raspberrypi.imagingutility`.
- **Simulator GUIs** (ADR-041 amendment 2026-11-10, SOLUSDEV-322: SOL reaches a simulator only through
  the owned `gazebo.*`/`isaac.*` wrappers and the `sim_session` ledger, never by driving its window):
  `org.mujoco.mujoco` (MuJoCo.app, the `simulate` viewer) and `org.python.python` (the python.org
  framework process, which hosts the pip `mujoco.viewer` and the Gazebo python bindings). Gazebo's own
  macOS binaries (`gz sim`, `gzclient`, `ign gazebo`) run unbundled and Isaac Sim ships for Linux and
  Windows only, so both fall under the no-bundle-id rule above.
- **Password managers and credential prompts:** `com.1password.1password`, `com.agilebits.onepassword7`,
  `com.bitwarden.desktop`, `com.dashlane.dashlanephonefinal` (Dashlane's macOS app is the Catalyst build of
  its iOS app and keeps that id), `com.lastpass.LastPass`, `org.keepassxc.keepassxc`,
  `com.apple.keychainaccess`, `com.apple.Passwords` _(family)_; macOS authentication and consent prompts:
  `com.apple.SecurityAgent`, `com.apple.loginwindow`, `com.apple.coreservices.uiagent`,
  `com.apple.UserNotificationCenter`.
- **System Settings and system administration:** `com.apple.systempreferences` _(family — System Settings
  on macOS 13+ still uses this id; its panes run as extension processes under it)_,
  `com.apple.settings` _(family: the pane extensions, e.g. `com.apple.settings.PrivacySecurity.extension`)_,
  `com.apple.SystemSettings` (no shipping app uses it today; listed so a future rename fails closed),
  `com.apple.ActivityMonitor`, `com.apple.DiskUtility`, `com.apple.installer`.
- **Mail and messaging:** `com.apple.mail`, `com.microsoft.Outlook`, `com.readdle.smartemail-Mac`,
  `com.readdle.SparkDesktop`, `org.mozilla.thunderbird`, `com.mimestream.Mimestream`, `com.apple.MobileSMS`,
  `com.apple.FaceTime`, `com.tinyspeck.slackmacgap`, `com.hnc.Discord`, `com.microsoft.teams2`,
  `com.microsoft.teams`, `net.whatsapp.WhatsApp`, `ru.keepcoder.Telegram`, `org.telegram.desktop`,
  `org.whispersystems.signal-desktop`, `us.zoom.xos`.
- **Web browsers** (browser-hosted tools such as Onshape come later, each by amendment): `com.apple.Safari`,
  `com.apple.SafariTechnologyPreview`, `com.google.Chrome` _(family)_, `org.chromium.Chromium`,
  `org.mozilla.firefox`, `org.mozilla.firefoxdeveloperedition`, `org.mozilla.nightly`,
  `company.thebrowser.Browser` (Arc), `company.thebrowser.dia`, `com.microsoft.edgemac` _(family: Beta, Dev,
  Canary)_, `com.brave.Browser` _(family: beta, nightly)_, `com.operasoftware.Opera` _(family)_,
  `com.operasoftware.OperaGX` _(separate entry: it shares the prefix without a dot, so the family rule
  does not reach it)_, `com.vivaldi.Vivaldi` _(family)_, `com.kagi.kagimacOS` (Orion),
  `app.zen-browser.zen`.
- **Solus itself:** `com.solusforge.solus` _(family: the Electron helpers `com.solusforge.solus.helper.*`,
  the drive agent `com.solusforge.solus.input`, the companion `com.solusforge.solus.companion`)_ — the app
  id is electron-builder's `appId`; and the dev shell `com.github.Electron` _(family)_, which is what an
  unpackaged Solus runs as (this also denies any other unpackaged Electron app — accepted).

**Project-bound list** (`ProjectBoundApps`, compiled in; replaces `DrivableApps`): `org.kicad.kicad`,
`org.kicad.eeschema`. These keep every M2/M3 rule in §2–§4 and still need a linked workspace.

**Helper CLI changes (A1).**

- `--within WS` becomes **optional** on `identify`, `capture` and `act`. When present it is validated as
  today (§2 "Workspace"). `capture`/`act` with a project-bound `--bundle` and no `--within` are a `usage`
  refusal; for a window-bound bundle `--within` is accepted and used only for `documentDir` (below).
- `capture` and `act` take **`--pid P`** (decimal, 1…2³¹−1). It is **required** for a window-bound
  `--bundle` (`usage` without it) and optional for a project-bound one (checked when given). Checks, in
  order, before any capture or event: the bundle is not denied (`app_denied`); W exists and is on screen
  (`window_not_found`); W's owner bundle is B (`window_mismatch`); W's owner pid is P (`pid_mismatch`);
  for `act`, the frontmost app's pid is P and its front layer-0 window is W (`pid_mismatch` /
  `window_mismatch`; `not_frontmost` when another bundle is in front). `act` re-checks bundle, pid and
  window before every posted event (`focus_lost` mid-verb, as today).
- **`identify` reply** (replaces `allowed`, `app`, `window` and `outsideWorkspace`, which are removed;
  the companion's outline reads `front.bounds`):

  ```
  {ok, now, trust:{accessibility, screenRecording}, unsignedDev, front: Front | null}

  Front (drivable)  = {drivable: true, binding: "project"|"window", bundleId, name, pid,
                       windowId: int|null, title: string|null, bounds: {x,y,width,height}|null,
                       documentDir: string|null}
  Front (not drivable) = {drivable: false, bundleId, name, binding: "project"|null,
                          reason: "denied"|"no_workspace"|"outside_workspace"}
  ```

  `front` is null when nothing is in front or the owner has no usable bundle id (nothing about it
  leaves the machine). A **denied** app reports only `bundleId`, `name`, `reason: "denied"` — never a
  pid, window id, title or bounds. A project-bound app without `--within` reports
  `reason: "no_workspace"`, and one working outside it `reason: "outside_workspace"`, again with no
  pid/window/title (another project's window title never leaves the machine — M2). `windowId`, `title`
  and `bounds` are null when the drivable app has no ordinary window in front (nothing can be bound).
  `name` is the app's localized name, ≤ 64 scalars, visible text only (the helper drops control/format
  characters and truncates). `title` is the window title, ≤ 256 scalars, same cleaning, null when the
  window has none or Screen Recording is not granted. `documentDir` is the bound window's `AXDocument`
  folder **relative to `--within`** (POSIX, `""` for the workspace root), resolved with `realpath` and
  byte-compared by whole segment; null when there is no `--within`, the app exposes no `AXDocument`, or
  the document lies outside the workspace. Never an absolute path.

- **Denied chords for every binding** (`DeniedChords`, checked before the chord allowlist, so a future
  widening of the allowlist can never admit them; today the allowlist already refuses all of them):
  save `cmd+s`, `cmd+shift+s`, `cmd+option+s`, `cmd+option+shift+s`; close `cmd+w`, `cmd+shift+w`,
  `cmd+option+w`; quit `cmd+q`, `cmd+shift+q`, `cmd+option+q`, `cmd+option+shift+q`; print `cmd+p`,
  `cmd+shift+p`, `cmd+option+p`. Refusal `chord_denied`. Tests pin each one for a window-bound and a
  project-bound bundle.
- New refusal codes: `app_denied`, `pid_mismatch` (added to `port.KNOWN_CODES`; `window_mismatch` already
  exists). `app_not_allowed` is no longer produced (kept in `KNOWN_CODES` for older helpers).

**Companion (A2).** `drive` advertises its tools whenever the platform is macOS, the helper relay
exists and `SOLUS_COMPANION_DRIVE=1` — **no longer only with a linked workspace** (the `NO_WORKSPACE`
off-reason is removed). `capture` and `act` argument models gain `pid: int | None` (1…2³¹−1), passed
as `--pid`; `--within` is added only when a workspace is linked. From `identify` the companion keeps
`front.documentDir` and `front.title` for itself and forwards the reply without them (the window title
never reaches the cloud from `identify`; the API binds from the stored card args, and `Identity` carries
no title). The **saved-file watch**:

| Situation                                              | Watch                                                                                                                                                                                           |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| project-bound (KiCad)                                  | unchanged §3 (design files in the workspace)                                                                                                                                                    |
| window-bound, workspace linked, `documentDir` non-null | every regular file under `<workspace>/<documentDir>` (same exclusions and 10,000-entry cap as §3; `""` = whole workspace): a change ends the step `design_saved`, and `designSaved` is reported |
| window-bound, workspace linked, `documentDir` null     | off                                                                                                                                                                                             |
| window-bound, no workspace                             | off — `act` still needs the step's `identify` bind (`not_bound`), but takes no baseline; a step can never report "SOL saved"                                                                    |

Autosave writes count as changes (the watch cannot tell them apart), so with the watch on, an
autosaving app ends a step as `saved`; the sentence says "a file in this project changed" rather than
claiming SOL saved it.

**Main: summon snapshot and relay (A3).**

- **Snapshot.** On every summon of the pill (any path), while driving is available and the setting is on,
  main sends `identify` (with `--within` when the drive child has a workspace) through the agent and
  shows the pill when it answers or after **250 ms**, whichever is first; a reply arriving after the pill
  took focus is discarded. The reply's `front` becomes the **front snapshot**, unless it is denied as
  Solus itself (then the previous snapshot is kept). The snapshot is cleared on drive off, project
  switch, companion restart and child exit. Main gives the renderer only
  `{bundleId, name, title, pid, windowId, drivable, binding}` (no bounds, no `documentDir`).
- **Availability** (§5) no longer needs a linked folder: `no_folder` stops being a reason driving is
  unavailable and instead means only that KiCad is not drivable (the Settings row says so). The
  nested-folder rule still makes driving unavailable when a linked folder conflicts.
- **Relay rule** (extends `relayRefusal`, §5): `identify` is always relayed. `--within`, when the child has
  a workspace, may appear at most once and must equal it; when the child has none it must be absent.
  `capture`/`act` whose `--bundle` is project-bound need `--within`. Every other `capture`/`act` needs
  `--pid`, and `(--bundle, --pid, --window)` must equal the snapshot's `(bundleId, pid, windowId)` with
  the snapshot `drivable: true, binding: "window"`; otherwise main replies `window_mismatch` (or
  `usage` for malformed argv) and nothing reaches the agent. A compromised renderer or companion can
  therefore aim a window-bound step only at the window the user summoned SOL over.

**Turn `front_app` and the API (A4a/A4b).**

- **Sent only while driving is available.** The renderer adds `front_app` to a turn's body only on a
  Build turn (`action_mode: "do"`), with the setting on and driving available, from main's snapshot
  (shape: `docs/api/API-implementation.md`, streaming turn). Never on resume or wake turns (422). A
  denied app is sent as `{bundle_id, name, drivable: false}`; no title, pid or window id ever leaves the
  desktop for it. A window-bound app with no ordinary window in front (`windowId` null — e.g. only
  minimized windows — or 0) has nothing to bind: main's snapshot, the preload check and the renderer's
  body all downgrade it to `{drivable: false, binding: null}` with no title, pid or window id, and the
  API normalises a drivable window-bound `front_app` with a null or 0 `window_id` the same way instead
  of refusing the turn (Phase 4 F3). A Guide turn's `front_app` is dropped by the API (never in the
  prompt, never offers `front`, no `sol.front_app_attached`).
- **Storage.** The turn's `front_app` itself is not written to the transcript, `sol.message` or any log.
  But when SOL parks a `drive.step {app: "front"}`, the copied window binding — `bundle_id`, `name`,
  **`title`**, `pid`, `window_id` — is stored in that card's `tool_confirmations.args` (it is what the
  card shows and what the decide-time staleness re-check and the executor bind read), so the window
  title of a parked step is persisted for the life of that confirmation row.
- **Prompt.** The turn context carries one nonce-fenced `kind=front_app` data block: app name, bundle id,
  whether SOL can drive it and how it is bound; the title inside the fence as untrusted data. The
  Solus-authored framing orders the routes: **integration API tools first, then workspace file tools
  (e.g. `machine.write_file`), then `drive.step`**; for a denied app SOL says it cannot drive that app
  and offers the other routes. `front_app` never changes the tool set except as below, the mode, or the
  scope.
- **`drive.step {app, intent}`**, `app` enum **`kicad | front`**. `front` is offered only when the turn
  carries a `front_app` with `drivable: true, binding: "window"`; `kicad` keeps today's rules. The model's
  arguments are validated against that schema (no binding fields — a model-supplied `window` is
  `invalid_args`); then Solus code copies the turn's `front_app` into the parked call's stored arguments
  as `window: {bundle_id, name, title, pid, window_id}`. The binding therefore comes **only** from the
  turn's `front_app`, never from model arguments; the card's rows are built from it, so the decide-time
  staleness re-check covers it, and execution binds to exactly what was shown.
- **Bind for `front`** (before any capture): poll `identify` up to the 5 s focus wait. While a Solus
  window (denied as Solus) or nothing is in front, keep polling. `front` with the stored bundle and pid
  and window id ⇒ bound. Same bundle, different pid ⇒ end `refused/relaunched`; same bundle and pid,
  different window ⇒ `refused/window_mismatch`; a denied app ⇒ `refused/app_denied`; any other app
  until the wait ends ⇒ `not_in_front`. Nothing is captured in any of these. Every `capture` and `act` then
  carries `pid`. A relaunch or window change mid-step surfaces as the helper's `pid_mismatch` /
  `window_mismatch` / `focus_lost` and ends the step.
- **Card rows for `front`:** App (`front_app.name`), Window (the title, escaped like every card value —
  React text, the preview cleaner's single-line and redaction pass; `Untitled window` when null),
  What SOL will do (the intent, verbatim), Screen (`SOL will see this window`), Budget
  (`up to 15 actions · 2 min`), Heads up (as for KiCad). Nothing is captured before the user confirms.
- **Intent refusal.** `drive.step` refuses — at parse, so no card is parked, and again in the executor —
  an intent containing a word starting with `upload`, `flash` or `deploy`, matched after Unicode NFKC
  normalization and casefolding (so fullwidth and ligature forms such as `ｕｐｌｏａｄ` or `ﬂash` count),
  and any intent with a character outside visible text (format, control, combining, private-use,
  invisible letters — so `de<ZWSP>ploy` cannot split a stem); one shared check (`refused_intent`) serves
  both places (`intent_refused`; for every app; at parse a hidden character is reported as the
  `invalid_args` "plain visible text" refusal). Cross-script look-alikes (e.g. Cyrillic `а` in
  `аpload`) are not folded by NFKC and fall under the residual below. **Residual (recorded):** an in-window button with such an effect
  (e.g. an IDE's Upload toolbar button, a slicer's "send to printer") is reachable by a click whose
  intent avoids those words; mitigated by per-step approval, the loop's system prompt ("never upload,
  flash, deploy, send or print") and the live A3 strip.
- New outcome codes: `relaunched`, `intent_refused` (plus the helper's `app_denied`, `pid_mismatch`).
  Unfinished-step sentences for a window-bound step never carry the stored `window.name` or title —
  both are untrusted machine text and the sentence is the `ToolException` message returned to the model
  (Phase 4 F3); `{app}` is the fixed phrase "the window" (KiCad steps keep "KiCad"):
  `not_in_front` → "nothing done — the window was not in front; bring it forward and ask again";
  `relaunched` → "stopped — the app was restarted; summon SOL over its window again";
  `window_mismatch` → "stopped — a different window is in front"; `app_denied` → "stopped — SOL
  can't use the mouse and keyboard in that app"; `saved` for a window-bound step → "stopped — a file in
  this project changed"; `intent_refused` (a parse-time `invalid_args`) → "drive.step can't upload, flash
  or deploy; use the integration's own tools for that".

**Data events (ADR-011).** `drive.session_started` `{app, binding, budget}`, `drive.action`
`{index, verb, result, binding}`, `drive.aborted` `{outcome, code, binding}`, `drive.session_ended`
`{app, binding, actions, seconds, outcome, code}` — `app` is `kicad` or `front`, `binding` is
`project` or `window`; never a bundle id, app name or title. `sol.front_app_attached`
`{project_bound, drivable}` (booleans) once per turn that carries `front_app`; never the title or the
bundle id.

**Pill (A5).** The A3 strip reads `DRIVING <APP NAME> · STEP k OF N` with the app name from the
snapshot, upper-cased, as text, truncated to 24 characters (`KICAD` for KiCad). The wireflow is
`docs/wireflows/sol-window.md` "SOLUSDEV-319 slice 4".

**Residuals (accepted in the amendments):** typing into a terminal pane inside an allowed app (e.g. VS
Code's integrated terminal) cannot be detected; with no workspace nothing ties the window to the project
and a click inside it can still save or change a file outside any project. Both are covered only by
per-step approval and the live A3 strip.

## 3. Companion `drive` server (slices 1–2)

`packages/companion/src/solus_companion/drive/` — a `BuiltinServer` like `machine`:

- `helper.py` (slice 3b, XPC): the **relay to the desktop**. The companion never reaches the helper
  itself. Each call writes one stdout line `{"type":"drive_request","id":N,"argv":[…]}` (N increasing,
  argv identify/capture/act) and waits for `{"type":"drive_reply","id":N,"reply":{…}}` on stdin, under
  ONE deadline; a reply over 24 MiB as JSON is refused (an incompressible 2048-px capture fits).
  Timeout or cancellation (Stop, a dropped bridge) writes `{"type":"drive_cancel","id":N}`. Desktop-side
  failures arrive as a reply with a refusal code (`agent_unavailable` when the agent cannot be reached).
  Replies are validated as before (exactly one JSON object with `ok`).
- `server.py`: tools `identify`, `capture`, `act` with strict pydantic argument models
  (`extra="forbid"`, no NUL bytes); one call at a time (an `asyncio.Lock` — two acts must never
  interleave); `capture` returns an MCP `ImageContent` (staged as an artifact by the existing dispatch
  path — never inlined into a 1 MiB frame) plus a metadata `TextContent`. Advertises nothing unless the
  platform is macOS, the helper path validates, and `SOLUS_COMPANION_DRIVE=1` (set by the desktop only
  while "SOL can use your mouse and keyboard" is on). The switch is read at companion start, so turning
  it off restarts the companion (slice 3).

**Wired in slice 2, internal only.** The companion builds `drive` beside `machine`
(`__main__.build_builtins`). The API loads every `integrations/mcp/*/allowlist.yaml`, so
`integrations/mcp/drive/allowlist.yaml` (a DRAFT for human ratification, integrations/mcp/CLAUDE.md
rule 2) declares `exposure: internal`: `bridge/allowlist.py` accepts the three tools from the companion
and marks their specs `internal`, and `agent/runtime.py` leaves every internal spec out of SOL's tool
set. Only `drive.step` (§4) reaches them. A capture is staged `fetch_once`: the first pull serves it and
drops it from the companion's memory (ADR-041 §6); an unpulled one is evicted with the store's LRU.

**Bound to the project (ADR-041 amendment M2/M3).** `drive` is built with the companion's linked
workspace (`SOLUS_COMPANION_WORKSPACE`, resolved) and advertises nothing without one ("no project
workspace is linked"); every helper command carries `--within` it. A successful `identify` (the step's
bind) takes a **saved-design baseline** (`watch.saved_design_fingerprint`: size + mtime of every
`DESIGN_SUFFIXES` file, symlinks by their target, skipping KiCad's `.history/` snapshots and
`_autosave-` copies, which KiCad writes on a timer, plus `.git`, `node_modules` and `solus-artifacts`;
`""` — cannot observe, or more than 10,000 entries — counts as changed). Every `identify` clears the
baseline first, so a step never inherits the previous one's. `act` refuses `not_bound` before any bind and
`design_saved` when the baseline moved since; it also answers `design_saved` when the act failed after
saving. Every act reply and every capture's metadata carry `designSaved` — KiCad writes a moment after a
Save click, so the look after an act is where a save usually shows.

**Outline geometry (slice 3).** After an ok `identify` (its `window.bounds`) and every ok `capture` or
`act` (their `bounds`), the companion writes one line to its stdout for the desktop app:
`{"type":"drive_window","bounds":{"x":…,"y":…,"width":…,"height":…}}` — numbers only, never a title, a
bundle id or a path. The only other lines are `drive_request` and `drive_cancel` (above). The
desktop ignores any other line.

## 4. API `drive.step` and the loop (slice 2)

Code: `packages/api/src/solus_api/agent/drive/` — `actions.py` (toolset ↔ vocabulary), `port.py`
(helper replies, untrusted), `executor.py` (the loop), `tool.py` (`drive.step`), `wiring.py` (binding).
Model call: `orchestration/gateway.computer_use` → `providers.AnthropicAdapter.computer_use`.

- **The tool.** `drive.step {app: "kicad", intent}` — Solus-authored, `requires_confirmation`, registered
  only when the requesting user's companion advertises all three internal drive tools. `intent` is one
  line, ≤ 300 characters, no `<`/`>` (it is fenced as `<goal>` in the loop prompt), visible text only
  (NFC; no format, private-use, unassigned, combining or invisible characters; U+0020 the only space),
  single-spaced, and refused if redaction would alter it —
  anything the card would change is refused, so displayed = executed. Never auto-run
  (`command_auto.auto_judge` is false). One step at a time per user (`wiring.drive_lease`, keyed on the user — the instance id is
  client-supplied;
  process-local today, a Redis lease when the API is multi-instance).
- **The card** is built from the arguments alone: App (`KiCad`), What SOL will do (the intent,
  verbatim), Budget (`up to 15 actions · 2 min`), Heads up ("SOL will move your mouse and type in this
  window. Move the mouse or press Esc to stop it."). While the card waits, the pill — not KiCad — is
  frontmost, so a live identify there would always be stale; the window check happens at bind instead.
- **Bind** (before any model sees a pixel): poll `drive.identify` up to 5 s for an allowlisted bundle
  (`DRIVABLE_APPS`, mirroring the helper) with a window; missing OS grants end the step (`not_trusted`),
  no app in front ends it with nothing done (`not_in_front`), and a KiCad working on a project outside the
  linked workspace ends it at once (`refused/outside_workspace`). `{bundle, window}` is fixed for the step.
- **Loop** — ADR-041 §6 and the 2026-10-26 amendment: capture (long edge 1280) → a user turn with the
  fenced goal, then the image → `gateway.computer_use` (role `computer_use`, `claude-opus-5-5`, effort
  high; frequency cap → spend gate → retry/breaker → debit, one DB session per round) with the fixed
  `computer_toolset_20260801` entry, its out-of-vocabulary members disabled, and
  `disable_parallel_tool_use` → `actions.map_action` → `drive.act` with `since` = the helper clock
  (identify's `now`, then each act's `finishedAt`) and `expect_width/height` = the latest capture's
  points. Model pixels map to points by `points/image`. The assistant content is replayed verbatim
  (`Usage.provider_items` — Opus 5.5 thinking blocks must come back unchanged); screenshots are never
  pruned.
- **Budget**: N = 15 actions, T = 120 s wall-clock from bind, model time included, and a 400k
  input-token ceiling (`Settings.drive_max_*`). Every identify, capture and model round is cut at the time
  left (a round answering after the deadline never runs); one helper action has its own 15 s bound, since
  an action already sent must report how it ended; each bridge call has a 30 s deadline. An act's result
  carries a fresh capture, so one action is one model round; an explicit screenshot does not spend an
  action; rounds are capped at 2N + 2. The history is prompt-cached (it is never pruned); cache reads and writes (writes at 1.25×) count in
  `tokens_in`, so the debit and the token ceiling see the whole input. Running out
  ends the step (`budget`, code `time`/`actions`/`tokens`/`rounds`) — it never extends itself.
- **Endings**: the model replies without a call with `end_turn` (`done`, its text as the summary, ≤ 500
  chars, redacted, returned as data) — any other stop reason without a call is `error/model_incomplete`; `refusal` stop reason (`declined`); a point outside the capture (`out_of_bounds`, before
  anything posts); any helper refusal ends the step with its code, and `user_active` is `paused` — Esc,
  double-Ctrl or a click on the pill are physical input, so stopping needs no route. An act whose reply
  or capture says `designSaved`, or a `design_saved` refusal, ends the step as `saved` ("SOL saved the
  design to disk"); the action that saved counts and is not marked refused. Before reporting `done` the
  loop takes one last look (a capture, no model call) when any action ran, so a save landing late is
  never reported as `done`. An unsupported
  proposal (a modifier click, `repeat`, an unknown key) is answered as an error and costs one action.
  Anything but `done` raises a `ToolException` with a Solus sentence, so a running plan stops.
- **Containment rests on "a new window ends the step"** (`window_mismatch`): KiCad's own code-execution
  surfaces — the BOM generator's command line, the PCB editor's scripting console, the Plugin and
  Content Manager — are separate windows. Following a child dialog (the symbol chooser) is an ADR-041
  amendment with a dialog allowlist keyed by AX identity and those surfaces explicitly denied; window
  titles (attacker-chosen file names) never leave the port.
- **Progress** rides the command-output channel (`STREAMING_TOOLS` includes `drive.step`): one line per
  action, `action 3/15 · click · 12.4 s` — a **stable format** the pill parses (slice 3):
  `^action (\d+)/(\d+) · ([a-z]+) · (\d+\.\d) s$`, one per `\n`-terminated line; changing it is a
  desktop-visible change, read by the desktop through `GET /confirmations/{id}/output`
  exactly like an approved `code.exec`. No typed text, coordinates or pixels.
- **Data events** (ADR-011, consent-gated via `services/events.emit_event`): `drive.session_started`
  `{app, budget}`, `drive.action` `{index, verb, result}`, `drive.aborted` `{outcome, code}`,
  `drive.session_ended` `{app, actions, seconds, outcome, code}`. Never the intent, typed text or pixels.
- **Red-team** (`tests/test_drive_redteam.py`): an obedient model following planted instructions in the
  window (cmd+q, paste, the close button, other tools, more budget) cannot change the tool set, the bound
  window or the budget, and every planted shortcut ends at the helper's chord policy.

### Bridge protocol addendum (slice 2)

No new frame types: `drive.*` travel as ordinary `tool_call` / `tool_result` frames, capture bytes as the
existing staged artifact (`artifact_chunk`). The change is cloud-side registration only
(`exposure: internal`), noted in `docs/contracts/bridge-protocol.md` Addendum A.

## 5. Desktop and packaging (slice 3)

**Helper packaging (security-critical, see §1; ADR-041 amendments H1 and 2026-10-27).**

- `scripts/build-solus-input.sh` builds `dist/solus-input/SolusInput.app`: `Contents/MacOS/solus-input`
  (the helper, the bundle's executable), with
  `CFBundleIdentifier` `com.solusforge.solus.input` and `LSUIElement`. Signing runs only when
  `SOLUS_SIGN_IDENTITY` is set (hardened runtime, per-binary identifiers); otherwise the bundle is left
  unsigned with a warning. Release builds refuse every call until the team ID placeholder in
  `Signing.swift` is replaced (§2, caller check). Identities and notarisation are human.
- electron-builder ships it at `<resources>/SolusInput.app`. Solus.app never requests Accessibility or
  Screen Recording; the grants belong to the helper bundle.
- **The agent** (§2.1) replaces the slice 3 launcher and the 3b socket, which are removed.
  electron-builder copies `bundle/com.solusforge.solus.input.agent.plist` to
  `Contents/Library/LaunchAgents/` (`mac.extraFiles`). **Electron fuses** are locked (`electronFuses`:
  `runAsNode`, `enableNodeOptionsEnvironmentVariable`, `enableNodeCliInspectArguments` off;
  `enableEmbeddedAsarIntegrityValidation`, `onlyLoadAppFromAsar` on) and verified by reading them back
  from the packed app before signing; Solus.app's entitlements no longer include
  `allow-dyld-environment-variables`; a packaged build refuses to start with `--remote-debugging-port`,
  `--remote-debugging-pipe`, `--inspect*` or `--js-flags`. Together: a process satisfying Solus.app's
  requirement runs Solus code with Solus configuration.
- **The companion is built `--onedir` on macOS** (`scripts/build-companion.sh`), so every Mach-O in it is
  signed in place (a onefile build unpacks unsigned code at run time). The packaged companion is
  `<resources>/companion/solus-companion/solus-companion`, with `mcp/` beside it. PyInstaller is pinned.
- **Signing** (human: identities, SOLUSDEV-148/149): `scripts/build-solus-input.sh` and
  `scripts/build-companion.sh` sign with their own identifiers (`com.solusforge.solus.input`,
  `com.solusforge.solus.companion`), hardened runtime, no extra
  entitlements, when `SOLUS_SIGN_IDENTITY` and `SOLUS_TEAM_ID` are set, then verify the requirements and
  that the helper has no entitlements; the helper build fails if the release helper reports
  `unsignedDev: true`. electron-builder's `mac.signIgnore` leaves both untouched, so Solus.app's
  entitlements (JIT) are never applied to them. `make desktop-mac`
  builds both, then the app.
- **Bundle seal (security review HIGH-1).** A same-user process could copy Solus.app somewhere writable
  and replace the companion's files (Python reads them as data, so the kernel never re-checks them); the
  copy's untouched main would pass the agent's requirement and relay the fake companion's requests. So a
  packaged main checks its own bundle's static signature — nested code and the resource seal over the
  companion, `_internal/` and `mcp/` (`SecStaticCodeCheckValidity`, strict) — once per launch and at
  every drive-child spawn; a failure is `bundle_modified` (drive unavailable, relay not attached).
  Solus.app's requirement also refuses builds carrying `allow-dyld-environment-variables`,
  `disable-library-validation` or `get-task-allow`, and below a `CFBundleVersion` floor (a human raises
  it to the first signed 3b build), so an older or debug team-signed build never counts as Solus.app.
  A packaged main accepts only its executable, `-psn_*` and one `solus://` URL on its command line. (macOS; Linux and Windows builds, which have no drive agent, keep the switch denylist so AppImage's `--no-sandbox` still works). The floor compares versions numerically (verified with `codesign -R`: 1.10.0 ≥ 1.9.0), but `1.0.0-beta.1 ≥ 1.0.0` also passes, so raise the floor past every prerelease of the first hardened build (or ship a plain integer `CFBundleVersion`).
- **Main and the agent** (slice 3b): main is the agent's only client. It answers the companion's
  `drive_request` lines only for the child it spawned with drive on, and only for `identify`, `capture`
  and `act` argv whose `--within` is exactly the workspace main checked for that child (the nested-folder
  rule) — anything else gets a `usage` reply and nothing is sent. Packaged: through the native module
  (§2.1); dev: by running the resolved debug helper (`…/.build/debug/solus-input`, realpath — `.build/debug`
  is a symlink) once per call with the argv (argument list, `PATH`-only env, the same deadline; its stderr
  is logged, bounded). `drive_cancel`, or the child exiting, cancels the call in flight. `trust` for the
  permission rows goes the same way. The grants in dev belong to whatever launched the app, as in slices
  1–2.
- **The companion's environment** in a packaged build is built from an allowlist (`PATH`, `HOME`, `USER`,
  `LOGNAME`, `TMPDIR`, `LANG`, `LC_*`) plus the variables main computes; inherited `SOLUS_COMPANION_*` and
  `PYTHON*` are ignored, so the companion always dials the baked API and serves the registry workspace.
  Dev builds keep inheriting (developer overrides).

**Settings → SOL: "SOL can use your mouse and keyboard"** (`sol.drive` in `~/.solus/config.json`,
default off).

- The companion gets `SOLUS_COMPANION_DRIVE=1` only when the setting is on AND driving is available for
  the active project, and main answers its `drive_request` lines only then; otherwise the variable is
  removed (inherited values included, `SOLUS_DRIVE_HELPER` too) —
  the setting is the consent, an environment variable is not. Changing either restarts the companion.
  Only the main window may turn the setting on or ask for permissions; the SOL pill (which renders model
  output) may only turn it off and report a running step.
- **Available** means: macOS; the helper is installed (packaged: the agent plist and SolusInput.app are in
  the bundle; dev: the debug helper resolves and passes the helper path rule); the project has a linked folder; and that folder
  **neither contains, lies inside nor equals another linked project's folder** (security review M1 of
  M2/M3), compared after `realpath` by whole path segment, over every project in this machine's
  `~/.solus` registry (paths under the `/System/Volumes/Data` firmlink are refused as links). The helper's check is "at or below the workspace", so with nested links a step
  for the outer project would pass for a KiCad working on the inner one. A folder nested in a project's
  tree but not linked to another project is fine — its files already belong to that project. Any folder
  link change re-evaluates it.
- The row shows why driving is unavailable (`not_macos`, `no_helper`, `no_folder`, `nested_folder`), and,
  when on, the agent's state (`agent`: `enabled`, `requires_approval` — macOS wants approval under
  Login Items, shown as a Needs-attention card that opens that pane — `not_registered`, `not_found`, or
  null when unknown) and the helper's Accessibility and Screen Recording state from `trust`. A missing grant is a
  "Needs attention" card whose fix runs `trust --prompt`; the status is re-read when the window regains
  focus, and a missing grant is never served from the 10 s trust cache for more than 1 s.

**While a step runs.**

- The pill shows the A3 strip `DRIVING KICAD · STEP k OF N` with a progress bar and **Stop**, parsed
  from the step's progress lines (§4) while its confirmation output is incomplete. Stopping needs no
  route: a click on Stop, Esc, or any other physical input is caught by the helper's kill switch before
  the next event (`user_active` → `paused`). Stop shows `DRIVING KICAD · STOPPING…` and keeps the
  outline and the quiet period until the step's result arrives, since the step only ends at its next
  action.
- The renderer tells main a step is running (`sol.setDriving`, ref-counted per window; a closed window
  counts as ended; bounds are dropped when a step ends); main then draws the **amber outline** as
  four click-through strips just OUTSIDE the latest `drive_window` bounds (§3) — never over the window,
  which the hit-test would refuse (§2 check 5) — and quiets the double-tap-Ctrl and circle detectors,
  plus 300 ms after. Main clears both when the renderer says the step ended, or after 150 s (the 120 s
  budget plus margin) if it never does.

## 6. Slices

1. **This doc + `solus-input` + companion `DriveServer`** (tests; not wired; no allowlist).
2. **Done (2026-10-26):** API `exposure: internal`, `drive.step` + executor + computer-use adapter,
   events, red-team; the server wired; the allowlist drafted (human ratifies); bridge-protocol note.
3. **Done on the branch (2026-10-27):** helper app packaging (signing human), caller check, the setting
   with the nested-folder rule, A3 strip, outline, listener quiet period.
   3b. **Helper as an XPC agent (ADR-041 amendments C1, 3b, 2026-10-28):** an SMAppService agent
   registered by Solus.app holds the grants and serves only Solus.app's main process over XPC
   (send-time audit tokens, both sides verify requirements); the companion relays through main; the
   packaged companion environment is allowlisted; fuses locked and verified; no dyld entitlement; no
   remote debugging. Then the team ID can be set and release builds can drive.
4. **Frontmost-app driving (SOLUSDEV-319 slice 4, ADR-041 2026-10-31; §2.2):** A0 these docs;
   A1 `solus-input` denylist, project-bound list, `--pid`, optional `--within`, the new `identify` reply
   and pinned denied chords; A2 companion `pid`, drive without a workspace, the `documentDir` watch;
   A3 desktop main front snapshot at summon and the window-bound relay rule; A4b API `drive.step` app
   `front` with the stored window binding, bind re-verification, intent refusal, events and red-team;
   A4a turn `front_app` (schema, prompt block and ordering, `sol.front_app_attached`); A5 pill renderer
   (`front_app` on Build turns, front card rows, `DRIVING <APP NAME>` strip).
