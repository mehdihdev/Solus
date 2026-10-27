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

| Command    | Arguments                                                                       | Result                                                                                                                                                                                                                                                                 |
| ---------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `identify` | —                                                                               | `{ok, now, trust:{accessibility,screenRecording}, allowed, app:{bundleId,pid,name}\|null, window:{id,title,bounds}\|null}`. When the frontmost app is NOT drivable, `app` and `window` are null — another app's identity and window title never leave the machine.     |
| `capture`  | `--bundle B --window W [--max-edge N]` (256–2048, default 1568)                 | `{ok, png (base64), imageWidth, imageHeight, pointsWidth, pointsHeight}`; refuses unless W is on screen, owned by B, and B is drivable; shadow-free, and refused (`capture_failed`) if the image's shape does not match the window's (padding would skew coordinates). |
| `act`      | `--bundle B --window W --since T [--expect-width w --expect-height h] <verb> …` | `{ok, verb, idleSeconds, finishedAt}` or a refusal (mid-verb refusals add `postedEvents`).                                                                                                                                                                             |

`act` verbs (window-relative **points**, integers): `click --x --y [--button left\|right] [--count 1\|2]`
(no right double-click — a right click opens a menu), `move --x --y`, `drag --x --y --to-x --to-y`,
`scroll --x --y --dy [--dx]`, `key --chord cmd+shift+z`, `type --text "…"`, `wait --ms` (≤ 2000).

Checks before ANY event is posted (each failure is a refusal with a code; nothing is posted):

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
Posted events carry a Solus marker in `eventSourceUserData` — not used by the helper; it is what the
desktop's input listener filters on in slice 3 so SOL's own events never read as the user's.

Refusal codes: `usage`, `app_not_allowed`, `not_trusted`, `screen_recording_denied`, `not_frontmost`,
`window_mismatch`, `window_not_found`, `window_resized`, `window_chrome`, `out_of_bounds`, `occluded`,
`bad_chord`, `chord_denied`, `bad_text`, `secure_field`, `user_active`, `focus_lost`, `stopped`,
`capture_failed`.

Known limits (documented, not hidden): letter keys map to ANSI virtual keycodes (non-US layouts may
differ); a save/export reached through menus by clicking is not detectable by the chord allowlist — the
step budget, the plan approval and the API loop's verification are the controls there; a microsecond gap
remains between the last hit-test and a global pointer post (inherent); the kill switch's reading of the
HID idle counter and the stuck-button release are verified on real hardware in the QA pass, not in unit
tests; the bundle id is not yet tied to KiCad's code signature (to add when the list widens).

## 3. Companion `drive` server (slices 1–2)

`packages/companion/src/solus_companion/drive/` — a `BuiltinServer` like `machine`:

- `helper.py`: runs the helper at a **pinned absolute path** (`SOLUS_DRIVE_HELPER`, set by the desktop
  app), re-checked before EVERY run: absolute, a regular executable, no symlink anywhere on the path,
  and neither the file nor any directory above it group/other-writable (sticky directories excepted).
  `asyncio.create_subprocess_exec` with an argument list (never a shell), an empty environment but
  `PATH`, ONE deadline covering read + exit, a 24 MiB stdout cap (an incompressible 2048-px capture
  fits), exactly one JSON object split on `\n` only. Any early exit — timeout, cap, cancellation (Stop,
  a dropped bridge) — sends SIGTERM (the helper releases a held button), then SIGKILL after 1 s.
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

## 4. API `drive.step` and the loop (slice 2)

Code: `packages/api/src/solus_api/agent/drive/` — `actions.py` (toolset ↔ vocabulary), `port.py`
(helper replies, untrusted), `executor.py` (the loop), `tool.py` (`drive.step`), `wiring.py` (binding).
Model call: `orchestration/gateway.computer_use` → `providers.AnthropicAdapter.computer_use`.

- **The tool.** `drive.step {app: "kicad", intent}` — Solus-authored, `requires_confirmation`, registered
  only when the requesting user's companion advertises all three internal drive tools. `intent` is one
  line, ≤ 300 characters, no `<`/`>` (it is fenced as `<goal>` in the loop prompt), and refused if
  redaction would alter it (displayed = executed). Never auto-run (`command_auto.auto_judge` is false).
- **The card** is built from the arguments alone: App (`KiCad`), What SOL will do (the intent,
  verbatim), Budget (`up to 15 actions · 2 min`), Heads up ("SOL will move your mouse and type in this
  window. Move the mouse or press Esc to stop it."). While the card waits, the pill — not KiCad — is
  frontmost, so a live identify there would always be stale; the window check happens at bind instead.
- **Bind** (before any model sees a pixel): poll `drive.identify` up to 5 s for an allowlisted bundle
  (`DRIVABLE_APPS`, mirroring the helper) with a window; missing OS grants end the step (`not_trusted`),
  no app in front ends it with nothing done (`not_in_front`). `{bundle, window}` is fixed for the step.
- **Loop** — ADR-041 §6 and the 2026-10-26 amendment: capture (long edge 1280) → a user turn with the
  fenced goal, then the image → `gateway.computer_use` (role `computer_use`, `claude-opus-5-5`, effort
  high; frequency cap → spend gate → retry/breaker → debit, one DB session per round) with the fixed
  `computer_toolset_20260801` entry, its out-of-vocabulary members disabled, and
  `disable_parallel_tool_use` → `actions.map_action` → `drive.act` with `since` = the helper clock
  (identify's `now`, then each act's `finishedAt`) and `expect_width/height` = the latest capture's
  points. Model pixels map to points by `points/image`. The assistant content is replayed verbatim
  (`Usage.provider_items` — Opus 5.5 thinking blocks must come back unchanged); screenshots are never
  pruned.
- **Budget**: N = 15 actions, T = 120 s wall-clock from bind, model time included (`Settings.drive_max_*`).
  A screenshot does not spend an action; model rounds are capped at 2N + 2. Running out ends the step
  (`budget`) — it never extends itself.
- **Endings**: the model replies without a call (`done`, its text as the summary, ≤ 500 chars, returned
  as data); `refusal` stop reason (`declined`); a point outside the capture (`out_of_bounds`, before
  anything posts); any helper refusal ends the step with its code, and `user_active` is `paused` — Esc,
  double-Ctrl or a click on the pill are physical input, so stopping needs no route. An unsupported
  proposal (a modifier click, `repeat`, an unknown key) is answered as an error and costs one action.
  Anything but `done` raises a `ToolException` with a Solus sentence, so a running plan stops.
- **Containment rests on "a new window ends the step"** (`window_mismatch`): KiCad's own code-execution
  surfaces — the BOM generator's command line, the PCB editor's scripting console, the Plugin and
  Content Manager — are separate windows. Following a child dialog (the symbol chooser) is an ADR-041
  amendment with a dialog allowlist keyed by AX identity and those surfaces explicitly denied; window
  titles (attacker-chosen file names) never leave the port.
- **Progress** rides the command-output channel (`STREAMING_TOOLS` includes `drive.step`): one line per
  action, `action 3/15 · click · 12.4 s`, read by the desktop through `GET /confirmations/{id}/output`
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

- **Helper packaging (security-critical, see §1):** `solus-input` ships as its own signed, notarised,
  `LSUIElement` app bundle inside Solus.app; it — not Solus.app — receives the Accessibility and Screen
  Recording grants; the companion launches it with responsibility disclaimed; it verifies the caller's
  code signature (Solus team ID) and its own integrity. Signing identities and notarisation are human.
- Settings → SOL: **SOL can use your mouse and keyboard** (default off; shows the helper's Accessibility
  and Screen Recording state with the existing "Needs attention" fix card pattern). It sets
  `SOLUS_COMPANION_DRIVE` and `SOLUS_DRIVE_HELPER` and restarts the companion when changed.
- The pill shows the A3 status line (`DRIVING KICAD · STEP k OF N`, progress, Stop) from
  `drive_progress`; Stop and Esc cancel the step (the companion SIGTERMs the helper); any physical input
  is caught by the helper's kill switch even if the cancel never arrives. The amber outline is edge
  strips outside the bound window (§2 check 5). The desktop input listener ignores events carrying the
  Solus marker.

## 6. Slices

1. **This doc + `solus-input` + companion `DriveServer`** (tests; not wired; no allowlist).
2. **Done (2026-10-26):** API `exposure: internal`, `drive.step` + executor + computer-use adapter,
   events, red-team; the server wired; the allowlist drafted (human ratifies); bridge-protocol note.
3. Desktop: helper app packaging and signing (human), setting, A3 strip, outline, listener filter.
