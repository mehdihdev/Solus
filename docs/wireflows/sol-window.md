# Wireflow — the SOL window, hotkeys, "SOL sees your screen", the circle gesture

**Ticket:** SOLUSDEV-252 (S3) · architecture: `docs/architecture/sol-window.md` · replaces the corner orb
(`COWORK_QA_SOLX-02-orb.md` flows are retired). The SOL page (`docs/wireflows/sol-page.md`) is unchanged.

## A. Summoning

| Trigger                                            | Result                                                                                                                                                                                                                                               |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Double-tap Ctrl** (any app focused)              | The SOL window appears on the display under the cursor (saved geometry if any; else 420×640, bottom-right of the work area, 24 px margin) and takes focus. If already open: focus. Never steals focus from a chord — Ctrl+C in Onshape still copies. |
| **Ctrl+Space**                                     | Toggles the action mode Guide ↔ Build. The composer mode control, tray tooltip and menu radio update. No toast, no sound.                                                                                                                           |
| **Hold Ctrl + circle** (hook available)            | On release, if the path closes: the window appears (or focuses) showing the **region card** (C). If the path does not close: nothing happens.                                                                                                        |
| **Ctrl+Shift+C** (hook unavailable)                | Enters _circle mode_ for 10 s: the tray tooltip reads "Circle mode — draw a loop"; the same gesture works without holding Ctrl; ends on a detected loop or after 10 s.                                                                               |
| **Ctrl+Shift+Space** / **Cmd+Shift+Space** (macOS) | Primary spawn/focus shortcut, independent of native hook support.                                                                                                                                                                                    |

## B. The window

Frame: native, resizable, draggable, min 360×420, remembers geometry per display. Header row (36 px):
`SOL` wordmark · **sees-screen dot**
(green dot + "sees your screen" when the setting is on; absent when off) · **pin** toggle (always-on-top) ·
close. Body: `SolChat` (the same chat as the page — shared session per project, so a reply keeps streaming
across surfaces). Footer: the composer with the existing Guide/Do segmented control replaced by the mode
badge, `@` mentions, **Think harder** switch, send.

Status line under the header (only when something is degraded, plain language):

- "Hold Ctrl and circle to focus SOL on something" (hook active), or
- "Circle mode: press Ctrl+Shift+C, then draw a loop" (fallback), or
- "Screen capture needs the Screen Recording permission — open Settings" (macOS link), or
- "Screen capture is unavailable on Wayland", or
- "Global shortcuts are unavailable on Wayland — use the shortcuts inside this window".

## C. The region card (after a closed loop)

Above the composer: the crop (max 320 px wide, letterboxed), a small caption `<app> — <title>` when known,
and two lines:

1. **"What do you think this is?"** — SOL's own read, tentatively phrased ("This looks like…"). It is a
   real turn: the crop + context go to the model with a Solus-authored prompt asking for a short, hedged
   identification in the current tone mode. Streams into the chat as SOL's message.
2. **"What would you like to know about it?"** — the composer placeholder while the crop is attached. The
   region stays the subject of the next send (attached), shown as a chip on the composer with ×.

Dismiss (×) discards the crop from memory. Nothing is filed unless the user later chooses "File this to…"
(S5a).

If **screen intelligence is off**, the loop still opens the window, with the card replaced by one line:
"SOL didn't look — turn on _SOL sees your screen_ in Settings to let it." No capture happens.

## D. Settings → Preferences

A new row under SOL:

> **SOL sees your screen** — When on, SOL can take a picture of your screen when you summon it or circle
> something, uses it for that one question, and then discards it. Nothing is saved unless you file it.
> Off means SOL never captures. [toggle]

Default off. Turning it on shows the platform note once (permission needed / unavailable) and, on macOS,
a button that opens the Screen Recording pane.

## E. Tray

Icon: the Solus mark; with a small dot overlay while screen intelligence is on. Tooltip:
`SOL · Guide · sees your screen`. Menu: **Open SOL** · separator · **Guide** / **Build** (radio) ·
**SOL sees your screen** (checkbox) · separator · shortcuts line (disabled item, e.g. "Ctrl+Shift+Space —
open (Cmd+Shift+Space on macOS) · Ctrl+Space — mode · Ctrl+Shift+C — circle mode") · **Quit**. On Linux without an indicator host the
tray is skipped and the window header carries the same state.

## F. Failure paths to exercise

- Hook fails to load (linux-arm64 prebuild is x86-64): fallback chords registered, status line says so, no crash, no error dialog.
- macOS without Accessibility: same fallback + a link to the Accessibility pane.
- Wayland: capture disabled; the portal may require shortcut approval. If unavailable, the window still opens from the page ("Open SOL window" in the SOL page header).
- `globalShortcut.register` returns false (another app owns Ctrl+Space): status line names the conflict; mode toggle still works from the composer/tray.
- Two displays with different DPI: window opens on the display under the cursor at the right scale; saved geometry on a display that is gone → reset to default placement.
- Capture with the setting off → no capture, the one-line card.
- Ctrl+C / Ctrl+V / Ctrl+Z in another app while SOL runs → untouched.

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
