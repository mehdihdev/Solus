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

**SOLUSDEV-318:** the note is no longer plain text under the row. While the setting is on and capture is
not available, the row carries a `PERMISSION NEEDED` tag with `How to fix`, and the fix is a card at the
top of Settings (Needs attention): the platform message, the System Settings path in mono, and
`Open Screen Recording settings` (macOS only — main opens its own URL) · `Recheck` · `Turn off screen
capture`. See `docs/wireflows/settings.md`.

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

## SOLUSDEV-262 Guide tasks

In Guide mode, offer a walkthrough picker alongside chat in the current SOL window. Choosing
a trusted task loads its confidence-bearing steps into the existing GuidePanel. Scriptable
surfaces display copyable commands without executing them; browser surfaces use the panel;
native surfaces offer explicit overlay handoff with side-panel fallback. A missing control/version
match remains uncertain, with no fabricated arrow. Existing explicit capture may provide the
screenshot context for fallback. Switching mode/project/account/task dismisses prior guidance.
Build keeps its normal chat/tool path and actual approval cards. No new modal is introduced.

## SOLUSDEV-317 command execution

The SOL window uses the same command card, Cmd/Ctrl+Enter approval, retained output,
automatic resume and Running processes strip specified in `sol-page.md` ("Command execution
— SOLUSDEV-317"). The global shortcuts above are unchanged. Cmd/Ctrl+Enter is handled only
inside the focused SOL surface and is never registered globally.

## SOLUSDEV-319 Ember Pill (supersedes §A placement and §B frame)

Design: canvas "SOL Quick Summon", variant A. The SOL window becomes a floating pill.

**Summon.** Double-tap Ctrl toggles the pill: hidden → shown next to the cursor and focused (24 px
below-left of the pointer, flipped above it when the pointer is near the bottom of the work area,
clamped to the display under the cursor); shown → hidden. The other spawn paths (tray, page button,
Cmd/Ctrl+Shift+Space, the circle gesture) always show and focus. No geometry is remembered.

**Fresh on summon.** Every summon — the window created, or shown again after a hide — opens on a NEW
chat with the bar alone (A1), unless SOL is busy (streaming, the latest reply's approvals waiting, or a
plan running), in which case the user returns to that conversation. The previous conversation stays in
the SOL page's history; because the active-conversation pointer is shared with the page, the page
follows to the new chat. In Guide mode the walkthrough picker (SOLUSDEV-262) opens from a **Guide
tasks** chip in the footer rather than holding the panel open, and closes again on the next summon.

**Frame.** Frameless, transparent, always on top, not resizable by hand, 560 px wide. Collapsed it is
the bar alone:

- Bar (54 px): SOL orb · message input ("Ask SOL, or tell it what to do…") · Guide | Build segmented
  control (Ctrl+Space still toggles) · amber send arrow.
- Footer (30 px): the attached-region chip when present · "sees your screen" dot when on · Think harder
  and Confirm every change as compact toggles · `⌃Space mode` · `⌃⌃ hide`. Degraded-status lines
  (§B list) render in the footer area, one per line.

**Grows upward.** Once there is anything to show — messages, opened Guide tasks, the region card — a panel opens ABOVE the bar and the window grows upward with its bottom edge fixed (max 620 px,
never past the work-area top; the thread scrolls inside). If growing would cover the point the pointer
was at when summoned, the pill shifts right of that point when there is room. The panel has no header
of its own; New chat and history stay on the full SOL page.

**Dismiss.** Clicking another app hides the pill (the next summon starts fresh, as above). It does NOT hide while SOL is streaming, while the latest turn's approval is waiting, or while a plan
runs (an older, forgotten approval does not keep it up).
Esc hides it (closes the mention list first when that is open).

**Plan card.** In the pill, the non-command approvals a SOL reply parks render as one plan (a single
approval is a one-step plan): `PLAN · N STEPS`, each step numbered with its summary and its concrete
before → after rows (nothing hidden — CLAUDE.md §7). Buttons: **Run N steps** · **Show me how instead**
(declines the steps, switches to Guide and asks SOL to walk the user through it) · **Reject** (declines
them). Each step also names its tool, and values render exactly as they will run (`Not provided`, `Empty
string`, whitespace and newlines kept — the approval card's own rendering). **Run is armed only when SOL
has finished answering and every step has been on screen**; a step that arrives later disarms it until
it has been seen, and the card says why Run is waiting. One plan runs at a time. Run approves the steps ONE AT A TIME, in order, each through the normal decision call and its own
staleness re-check; the first failure stops the run with the server's reason, the remaining steps stay in
the plan, and a refused step is marked "refused — won't run", left out of the count and never sent
again. Command cards (SOLUSDEV-317) keep their own card. The
panel and page layouts keep one card per approval.

**Running.** While a plan runs the plan shows a status strip: `APPLYING · STEP k OF N`, the current
step's summary, an N-segment progress bar and **Stop** — Stop lets the in-flight step finish and leaves
the rest parked. SOL never moves the user's pointer in this ticket; free-form "SOL drives the
app" is a separate ticket that needs its own ADR (ADR-040 §2 limits synthetic input to KiCad save/revert).

## SOLUSDEV-319 slice 4 — driving the app in front (ADR-041 2026-10-31)

Architecture: `docs/architecture/sol-drive.md` §2.2. Applies only in **Build** with **SOL can use your
mouse and keyboard** on and driving available; otherwise nothing below happens and no app details leave
the desktop. Every word on the pill is Solus-authored except the app name and window title, which render
as plain text (never markup), single-line, truncated.

**1. Summon → front-app snapshot.** The user is in an app (say FreeCAD, "bracket_v3.FCStd") and summons
the pill. Before the pill takes focus (≤ 250 ms) main reads which app and window are in front. Nothing is
captured — no pixels, only the app identity and the window title. The pill looks exactly as in "Ember
Pill" above; there is no new chrome on summon. Summoning over a Solus window keeps the previous snapshot.

**2. The user asks** ("add a 3 mm fillet to the top edge"). The turn carries the front app. SOL answers
in this order of preference: an integration's tools, then editing files in the linked workspace, then
driving the window. If it chooses driving, the reply parks a drive card.

**3. Drive card** (one plan step, the plan card's normal rendering):

| Row              | Value                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------- |
| App              | `FreeCAD` (the app's name)                                                                  |
| Window           | `bracket_v3.FCStd` (the window title; `Untitled window` if none)                            |
| What SOL will do | the intent, verbatim                                                                        |
| Screen           | `SOL will see this window`                                                                  |
| Budget           | `up to 15 actions · 2 min`                                                                  |
| Heads up         | `SOL will move your mouse and type in this window. Move the mouse or press Esc to stop it.` |

Buttons as the plan card: **Run 1 step** · **Show me how instead** · **Reject**. Nothing is captured
until Run. KiCad cards are unchanged (App `KiCad`, no Window/Screen rows).

**4. Run → driving.** The user clicks the bound window to bring it forward (within 5 s). The A3 strip
shows `DRIVING FREECAD · STEP k OF N` (the app name upper-cased, ≤ 24 characters; `DRIVING KICAD` for
KiCad), the progress bar and **Stop**; the amber outline surrounds the window. Stop, Esc or touching the
mouse or keyboard pauses it (`paused — you took over`).

**5. Endings the user can see** (one plain sentence in the chat, naming the app, never the title):

- Done → SOL's one-line summary.
- The window was closed and reopened, or the app relaunched → `stopped — FreeCAD was restarted; summon
SOL over the window again`.
- A different window of the app is in front → `stopped — a different FreeCAD window is in front`.
- Another app stayed in front → `nothing done — FreeCAD was not in front; bring it forward and ask again`.
- With a linked workspace and the document inside it, a file there changed (SOL clicked Save, or the
  app autosaved) → `stopped — a file in this project changed`. Without a workspace there is no such
  ending; save, close, quit and print shortcuts are never available to SOL.
- An intent mentioning upload, flash or deploy is refused before any card: SOL says it can't do that
  step by driving and suggests the integration route (e.g. Deploy) instead.

**6. Denied app path.** Summoned over a terminal, password manager, System Settings, a mail or chat app,
a web browser or Solus itself: the turn carries only the app's name and identity, never its title. If
the user asks SOL to do something there, SOL replies that it can't use the mouse and keyboard in that
app, and offers what it can do (an integration's tools, editing workspace files, or Guide steps). No
card, no strip.

**7. KiCad without a linked folder.** KiCad stays project-bound: with no linked folder SOL says it can
drive KiCad only once a project folder is linked (Settings › Workspace), and offers the other routes.

**8. Drive off.** Setting off, Guide mode, or driving unavailable: no snapshot, no `front_app`, no drive
cards; SOL plans with APIs and file tools only, and in Build may mention that turning on _SOL can use
your mouse and keyboard_ in Settings would let it do the step itself.
