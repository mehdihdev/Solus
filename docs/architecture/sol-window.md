# SOL window, global hotkeys, on-screen intelligence, the Ctrl-hold gesture

**Ticket:** SOLUSDEV-252 (S3) · **Authority:** CLAUDE.md §7, ADR-016 (modes), ADR-029 (VISUAL_LOG),
ADR-034 (`~/.solus` machine-local state), `docs/contracts/orb-overlay.md` (CTR-06, tier-2 — unchanged)
· **Status:** tier-1 amendment, reviewed at the MR. The prompt for SOLUSDEV-252 is the spec; this
document is the structure the code must match. The wireflow is `docs/wireflows/sol-window.md`.

## 1. What changes

The corner orb (`MiniOrb`, `SolOrb`, `OrbWindow`, `orbStore`, route `#/orb`) is removed. SOL has two
surfaces: the SOL **page** (`#/` → `SolScreen`, unchanged) and the **SOL window** — a resizable,
draggable, geometry-remembering, optionally always-on-top `BrowserWindow` at route `#/sol-window`
that appears only when summoned (double-tap Ctrl) or by gesture (Ctrl-hold circle). The SOL window is
the new **CTR-06 host**: `attachOrbOverlayWire` is attached to it at creation and `overlayHandoff.ts`
stays in `features/sol/` with the SOL window as its caller. The contract, its channel names and the
LANE D overlay (`#/overlay`, `features/overlay/*`) do not change.

## 2. Module map (`apps/desktop/src`)

| Module                                     | Owns                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main/platform/capabilities.ts`            | Runtime detection → `PlatformCapabilities` (os, arch, session type, hook loadable, capture mode, tray host, permissions) and the human-readable degrade message per capability. The only place that inspects `process.platform`/`XDG_SESSION_TYPE`/`WAYLAND_DISPLAY`.                                                                                                      |
| `main/hotkeys/ctrlStateMachine.ts`         | Pure state machine over key/cursor events (§4). No Electron imports.                                                                                                                                                                                                                                                                                                       |
| `main/hotkeys/keyHook.ts`                  | Optional native hook loader: `require('uiohook-napi')` in try/catch + self-test (§5). Feeds the state machine.                                                                                                                                                                                                                                                             |
| `main/hotkeys/globalHotkeys.ts`            | `globalShortcut` registration: `Ctrl+Space` (mode toggle), the spawn fallback chord, `Ctrl+Shift+C` (circle mode). Registration failures are reported, never fatal.                                                                                                                                                                                                        |
| `main/gesture/cursorSampler.ts`            | Polls `screen.getCursorScreenPoint()` at ~60 Hz only while sampling is armed; emits the path.                                                                                                                                                                                                                                                                              |
| `main/gesture/circleDetector.ts`           | Pure geometry: path → `{ closed, bbox, sweepDeg, travelPx }` and the accept rule (§4).                                                                                                                                                                                                                                                                                     |
| `main/capture/screenCapture.ts`            | One interface (§6) over `desktopCapturer`; per-OS permission probes; returns `CaptureResult` or `CaptureUnavailable` — never throws to callers.                                                                                                                                                                                                                            |
| `main/capture/activeWindow.ts`             | Best-effort foreground window `{ app, title }` per OS (§6); `null` when unknown.                                                                                                                                                                                                                                                                                           |
| `main/solSettings.ts`                      | `~/.solus/config.json` keys (§7) via the existing `localState` atomic-write deps; pushes `sol:state` to every renderer on change.                                                                                                                                                                                                                                          |
| `main/sol-window/solWindow.ts`             | The window manager (create/focus/toggle always-on-top, geometry persistence, DPI/multi-monitor placement) — replaces the SOLX-02 detach/attach registry.                                                                                                                                                                                                                   |
| `main/tray.ts`                             | Tray icon + menu; reflects mode, sees-screen state, hook/capture status.                                                                                                                                                                                                                                                                                                   |
| `preload/index.ts` → `window.solus.sol`    | `getState()`, `setMode()`, `setScreenIntelligence()`, `setAlwaysOnTop()`, `setHotkeys()`, `onState(cb)`, `onRegion(cb)`, `open()`, `openCaptureSettings()` (SOLUSDEV-318: no argument — main opens its own capture capability's `settingsUrl`, allowlisted by `isSystemSettingsUrl`). Channel names from `main/sol-window/solWindow.constants.ts` only (existing ratchet). |
| renderer `features/sol/SolWindow.tsx`      | Route `#/sol-window`: header (sees-screen dot, pin), the region card, `SolChat`.                                                                                                                                                                                                                                                                                           |
| renderer `features/sol/SolChat.tsx`        | `OrbChat.tsx` renamed; unchanged behaviour.                                                                                                                                                                                                                                                                                                                                |
| renderer `features/sol/solSessionStore.ts` | The parts of `orbStore` the chat still needs (`conversationByProject`, `streaming`), nothing orb-shaped.                                                                                                                                                                                                                                                                   |

## 3. Platform capability table (what runs where)

| Capability                                                    | Windows x64 / arm64       | macOS x64 / arm64                                                                                      | Linux X11 x64                                                                        | Linux X11 arm64                                                               | Linux Wayland                                                                                                           |
| ------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Ctrl+Space / chords (`globalShortcut`)                        | ✓                         | ✓ (may collide with input-source switching — a failed registration is reported in the window and tray) | ✓                                                                                    | ✓                                                                             | Portal registration attempted; approval/compositor support required                                                     |
| Double-tap Ctrl / Ctrl-hold (needs bare-modifier key up/down) | `uiohook-napi` prebuild ✓ | prebuild ✓ + **Accessibility** permission (`systemPreferences.isTrustedAccessibilityClient`)           | prebuild ✓                                                                           | **✗ the published prebuild is an x86-64 ELF** (sha256 = linux-x64) → fallback | ✗ libuiohook is X11-only → fallback                                                                                     |
| Cursor position (`screen.getCursorScreenPoint`)               | ✓                         | ✓                                                                                                      | ✓                                                                                    | ✓                                                                             | degraded (only reliable over own windows)                                                                               |
| Screen capture (`desktopCapturer`)                            | ✓                         | ✓ after **Screen Recording** permission (`getMediaAccessStatus('screen')`; explain + deep link)        | ✓                                                                                    | ✓                                                                             | ✗ the PipeWire portal shows a per-capture dialog, which contradicts "no per-capture UI" → capture disabled with message |
| Tray                                                          | ✓                         | ✓                                                                                                      | ✓ if an indicator host exists (GNOME: AppIndicator extension) else window-only state | same                                                                          | same                                                                                                                    |
| Active window title/app                                       | best effort (§6)          | best effort                                                                                            | `xprop` when present                                                                 | same                                                                          | ✗                                                                                                                       |

**Gesture fallback when the hook is unavailable** (linux-arm64, Wayland, macOS without Accessibility, load
failure): `Ctrl+Shift+C` enters _circle mode_ for 10 s — the same circle gesture works without holding
Ctrl — and the primary `Ctrl+Shift+Space` (`Cmd+Shift+Space` on macOS) spawns/focuses the window. The window and the tray state plainly which is
active ("Hold Ctrl and circle" vs "Circle mode: Ctrl+Shift+C").

The native module is an `optionalDependency` with N-API prebuilds (no Electron rebuild); it does **not**
gate the build on any target. `electron-builder.yml` keeps `npmRebuild: false`.

## 4. The Ctrl state machine (pure)

Inputs: `ctrlDown(t)`, `ctrlUp(t)`, `otherKeyDown(t)`, `cursor(t, x, y)`. Outputs: `doubleTap`,
`gestureStart`, `gestureEnd(path)`, `passthrough`. Constants (DIP): `TAP_MAX_MS = 250`,
`TAP_MAX_MOVE_PX = 6`, `DOUBLE_TAP_WINDOW_MS = 350`, `GESTURE_MIN_TRAVEL_PX = 200`,
`GESTURE_MIN_BBOX_PX = 40`, `GESTURE_MIN_SWEEP_DEG = 300`, `GESTURE_CLOSE_RATIO = 0.25`.

- `idle` → `ctrlDown` → `down(t0, p0)`.
- `down` → `otherKeyDown` → `chord`: **passthrough** (we never consume; the OS app gets its Ctrl+key). Back to `idle` on `ctrlUp`.
- `down` → `ctrlUp` within `TAP_MAX_MS` and travel ≤ `TAP_MAX_MOVE_PX` → `tap(t)`; a second tap within `DOUBLE_TAP_WINDOW_MS` → **doubleTap** → `idle`.
- `down` → cursor travel > `TAP_MAX_MOVE_PX` or hold > `TAP_MAX_MS` → `gesturing` (sampling armed) → `ctrlUp` → **gestureEnd(path)** → circle test: `travelPx ≥ 200`, `bbox ≥ 40×40`, `sweepDeg ≥ 300`, distance(start, end) ≤ `0.25 × diag(bbox)`. Fail → no-op (no UI). Pass → region = bbox + 12 % margin, clamped to the display.
- `Ctrl+Space` is a `globalShortcut` accelerator handled outside the machine; the hook sees the Ctrl press, then a key → `chord` → passthrough, so the two never interfere. Tests cover: double-tap, hold+circle, chord passthrough (Ctrl+C), Ctrl+Space, and a tap followed by a chord.

## 5. Hook loading and the self-test

`keyHook.ts`: `loadKeyHook(): KeyHook | null`. Steps: (1) `require('uiohook-napi')` in try/catch;
(2) `uIOhook.start()` in try/catch; (3) self-test = both succeeded **and** the platform is not Wayland
**and** on macOS `isTrustedAccessibilityClient(false)` is true. Any failure → `null` + a one-line
capability message (never a throw, never a crash). The hook only OBSERVES; nothing is ever swallowed.
`uIOhook.stop()` on `before-quit`.

## 6. Screen capture

```ts
interface ScreenCapture {
  capability(): {
    mode: "available" | "needs-permission" | "unavailable";
    message: string;
    settingsUrl?: string;
  };
  captureRegion(
    region: Rect /* DIP, screen coords */,
  ): Promise<CaptureResult | CaptureUnavailable>;
}
interface CaptureResult {
  png: Buffer;
  width: number;
  height: number;
  scale: number;
  display: number;
  context: { crop: Rect; screen: Rect };
  window: { app: string; title: string } | null;
}
```

Implementation: `desktopCapturer.getSources({ types: ['screen'], thumbnailSize })` for the display under the
region, `NativeImage.crop` for the region, and a second, downscaled full-screen image (≤ 1280 px wide) as
surrounding context — posted as `screenshot.context`, consumed only by the extractor pass (§8). Permission probes: darwin `getMediaAccessStatus('screen')` → `needs-permission` with
`x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture`; Wayland → `unavailable`.
`activeWindow.ts`: X11 → `execFile('/usr/bin/xprop', [...])` (argument list, pinned path, optional);
darwin/win32 → `null` in this ticket (documented gap; no native module ships for it).

**Ephemeral by construction:** captures live in memory for one turn, are attached to that turn's request,
and are dropped. Nothing is written to disk. Filing an artifact (S5a) is the only path that persists one.

## 7. Settings and state (ADR-034 layer 1, main-owned)

`~/.solus/config.json` → `sol: { actionMode: 'guide' | 'do', screenIntelligence: boolean, hotkeys: boolean,
alwaysOnTop: boolean, window: { x, y, width, height, displayId } | null }`. Defaults: `guide`, `false`, `true`,
`false`, `null`. `hotkeys: false` stops the native key hook and the cursor sampler (the global chords stay); it is the
consent surface for a global keyboard hook, in the tray menu and Settings.
`screenIntelligence` **off means no capture ever** — the gesture still opens the window, without a crop,
and says why. The action mode is the SOLX-01 `guide | do` axis, labelled **Guide | Build** in UI (ADR-016's
Guide/Expert tone setting is untouched, server-persisted, in Settings). Every renderer receives
`sol:state` pushes; the SOL page composer and the window read the same value.

## 8. From capture to the model

`MessageCreate.screenshot: { media_type: 'image/png' | 'image/jpeg', data: <base64 crop>, width, height,
source: { app, title } | null, context: <base64 PNG of the surrounding screen, ≤ 1280 px wide> | null }` —
at most one per turn, crop ≤ 2.5 MiB decoded (3.5 MiB encoded), context ≤ 1.5 MiB decoded, both magic-byte
sniffed (the `fingerprint/visual.py` posture) and rejected with a 422 that names the reason and never echoes the
bytes. The runner:

1. **VISUAL_LOG extractor pass** (ADR-029): `gateway.complete(type=RouteType.VISUAL_LOG, images=[crop, context?])`
   with a Solus-authored transcription prompt → a `screen` context section (≤ 600 tokens), fenced as DATA like
   every other section. Vision proposes; the section is labelled tentative. The context image is used **only**
   here — it never reaches the reasoning turn or the transcript.
2. **Pixels on the turn:** the crop rides the live user `Turn` as `Turn.images` (additive provider-neutral field)
   so a reasoner whose adapter accepts images in a conversation (Anthropic, OpenAI) sees the evidence. The
   gesture region is "the subject of the next request": the window's composer keeps the crop attached until the
   user sends or dismisses it.
3. Nothing pixel-shaped reaches the transcript: the persisted user turn carries `attrs.screenshot =
{ width, height, app }` only.

Routing is unchanged: the turn's `context` still derives the route type, so a screenshot never flips a
tool-calling SOL turn onto a provider that cannot carry tools; the extractor pass is the VISUAL_LOG call. Every catalog entry a GENERAL or CODE matrix cell (any tier) or `default_role` resolves to must have
`accepts_images: true` — `orchestration/config.py` rejects a text-only model there at config load, never on a paid call.

## 9. Security

Screen pixels and window titles are **untrusted input to the model layer** (CLAUDE.md §7): the extractor
output and the title/app strings are fenced data; the red-team suite gains a screenshot whose text says
"ignore previous instructions" and asserts non-compliance. No capture without the setting; no capture is
ever logged, persisted or returned by any API. Hotkeys observe and never inject or block keys. All IPC is
sender-gated like the existing channels.

## SOLUSDEV-260 shortcut and header follow-up

The primary summon shortcut is Ctrl+Shift+Space on Windows/Linux and Cmd+Shift+Space
on macOS (Electron CommandOrControl+Shift+Space), registered independently of native
key-hook availability. The native double-tap gesture remains optional; no ARM64
native build is required to summon SOL. Registration failures are surfaced honestly,
and the Open SOL window button remains available. Wayland support may use the
Electron GlobalShortcuts portal when supported; missing portal/permission still
degrades to the clickable path. The header has no mode selector; Settings and the
composer retain their controls. An already-open SOL window follows main-window
workspace selection changes.
