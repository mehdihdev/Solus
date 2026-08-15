# Completion report — SOLUSDEV-213 (SOLUS-TU-10): the Guide overlay window

**Lane:** D (SOLUSDEV-215), built on the integration branch · **Branch:** `SOLUSDEV-69-integration-lane-orgy` · **Date:** 2026-08-14
**Sibling ticket:** SOLUSDEV-202 (SOLX-03) — see `COMPLETION_SOLUSDEV-202-solx03-confidence-gate.md`. The two were built together because they are the two halves of one window.

**Was blocked on SOL-IPC-01 (SOLUSDEV-223).** That block is genuinely gone: 223 landed with the LANE C merge (`0d2ff57`), and `packages/shared-types/src/orb-overlay.ts` plus the preload's `window.solus.orbOverlay` surface both ship both roles.

## What was built

`apps/desktop/src/main/overlay/overlayWindow.ts` — the **window host**: the Electron posture that makes a transparent, click-through, always-on-top surface behave like an overlay rather than like a window.

- `OVERLAY_WINDOW_OPTIONS` — `transparent`, `frame: false`, `focusable: false`, `skipTaskbar`, no shadow. The overlay must never steal focus from the tool the user is working in; a focus steal mid-drag in KiCad is worse than no overlay.
- `OVERLAY_WEB_PREFERENCES` — `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, on the shared preload. Same posture as every other Solus window; the overlay renders untrusted KB text (M7), so it gets no more privilege than the main window, not less.
- `overlayPosture(platform)` — the per-OS differences, isolated in one pure function rather than smeared through the creation path: `'screen-saver'` always-on-top level everywhere; `setIgnoreMouseEvents(true, { forward: true })` on darwin/win32 (Linux/X11 does not forward reliably, so it is set without forwarding); `setVisibleOnAllWorkspaces` on darwin only.
- `applyOverlayPosture(win, platform)` / `positionOverlayOver(win, bounds)` — applied against a narrow `OverlayWindowHandle` interface, not `BrowserWindow`, so the whole posture is asserted in tests with no display, no Electron, and no CAD tool. `positionOverlayOver` is a no-op returning `false` on a destroyed window (the tool can close between a `reposition` arriving and it being applied).
- `createOverlayBrowserWindow(...)` — the real composition: builds the window, loads the renderer at `#/overlay`, and attaches the CTR-06 wire via the existing `attachOrbOverlayWire`. Channel names come from `ORB_OVERLAY_CHANNELS` — the `orbOverlayWire.test.ts` ratchet scans `src/main/` and fails on any `orb-overlay:` string literal, and this file is inside it.

`apps/desktop/src/renderer/src/routes/AppRoutes.tsx` — the `#/overlay` route the window loads.

## Acceptance → evidence

| Acceptance                                       | Evidence                                                                                                                                  |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| A transparent always-on-top window over the tool | `OVERLAY_WINDOW_OPTIONS` + `overlayPosture` · `overlayWindow.test.ts` asserts transparency, framelessness, and the `'screen-saver'` level |
| Click-through — the user keeps using their tool  | `setIgnoreMouseEvents(true, {forward:true})` asserted per platform; the renderer sets `pointerEvents: 'none'` on every painted element    |
| Never steals focus                               | `focusable: false`, `skipTaskbar`, asserted                                                                                               |
| Follows the tool window                          | `positionOverlayOver`, asserted including the destroyed-window no-op                                                                      |
| Renders the guide step                           | `#/overlay` → `OverlayWindow` → `GuideOverlay` (SOLX-03)                                                                                  |
| Cross-platform                                   | `overlayPosture` is a table keyed by platform, asserted for all three                                                                     |

11 tests, `apps/desktop/src/main/overlay/overlayWindow.test.ts`.

## The two SOL-IPC-01 findings billed to this ticket

**M4 — "role-gate the preload surface in the ticket that creates the second window."** Assessed, and the exposure is already contained one layer down; I did not add a second gate.

`preload/index.ts` exposes both halves of the wire (`publishToOverlay`/`onOverlayToOrb` and `publishToOrb`/`onOrbToOverlay`) to every renderer. But `attachOrbOverlayWire` captures its window's `webContents.id` and **drops every inbound message whose sender id does not match** (`orbOverlayWire.ts`). One wire is attached per window, so:

- The **main** window calling either half reaches no wire at all — neither the orb's nor the overlay's filter accepts its sender id. Cross-window forgery is already blocked.
- What remains is a window forging to **itself** — the orb window publishing an overlay→orb message that only its own wire hears. Reaching that requires hostile JS already executing in that renderer, which under `contextIsolation: true`, `sandbox: true`, and `default-src 'self'` is a compromise that role-gating would not survive either.

Role-gating would mean threading a window role through the shared preload (`additionalArguments`), touching every window to narrow an attack that the sender filter already closes. Recorded here as a deliberate call rather than an omission — if the preload ever gains a capability that is **not** sender-filtered, this reasoning expires.

**M3 — "sender filtering holds only while renderer CSP stays `default-src 'self'`."** Verified still true: the overlay loads the same `apps/desktop/src/renderer/index.html`, whose CSP is `default-src 'self'; script-src 'self'; …` with no `frame-src` and no `<webview>`. The overlay window introduces no new origin and loads no remote content. If that CSP ever widens, the sender filter needs a `senderFrame === mainFrame` check, as `orbOverlayWire.ts` already notes.

## Delegated judgement

- **No wireflow exists for this lane** (`docs/wireflows/` holds only `license-capture.md`). TU-09 flagged the same gap and recorded it as delegated judgement; the overlay's visual treatment (a bordered box on the control, a dimmed surround, a bottom-left step panel) is my call and is the cheapest thing to change later.
- **Linux gets no mouse-event forwarding.** Electron's `forward` option is not reliable on X11. The window is still click-through; only the hover-tracking nicety is absent. Named in code rather than silently platform-branched.
- **CODEOWNERS:96 reserves `/apps/desktop/src/main/overlay/` for `@lane-toolkb`** — this ticket's lane — so the window host lives there, and the SOLX-03 renderer half lives under `features/overlay/`. That split is what the ownership file already implies; flagged in the plan as the one thing the repo could not settle, and resolved this way.

## Open for a human

- **The orb-side driver has no production caller.** `features/sol/overlayHandoff.ts` is built and tested but nothing spawns a handoff yet, so the end-to-end path is not live in the app. Both halves of the wire now exist; what is missing is the trigger (a "show me in the tool" affordance in the Guide panel) and tool-window detection, neither of which is in either ticket's text.
- **Tool-window detection is not built.** `positionOverlayOver` takes bounds; nothing produces them. Finding the KiCad window's bounds is an OS-specific capability that no ticket covers.
