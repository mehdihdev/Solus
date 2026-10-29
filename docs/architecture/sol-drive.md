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
4. **3b — helper as an XPC agent (ADR-041 amendments C1, 3b, 2026-10-28):** an SMAppService agent
   registered by Solus.app holds the grants and serves only Solus.app's main process over XPC
   (send-time audit tokens, both sides verify requirements); the companion relays through main; the
   packaged companion environment is allowlisted; fuses locked and verified; no dyld entitlement; no
   remote debugging. Then the team ID can be set and release builds can drive.
