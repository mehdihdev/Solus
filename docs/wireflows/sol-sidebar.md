# Wireflow — SOL Sidebar (SOLUSDEV-327)

A third SOL surface, between the pill (its own window, over any app) and the SOL page
(`MainScreen 'sol'`): a panel docked to the right of the current Solus screen, so the person
can work with SOL beside what they are looking at without leaving it. Design canvas:
Claude Design "SOL Sidebar" (2026-11-15) — boards _Prototype_, _States_, _Motion_, _Surfaces_.
Drawn in the Solus tokens (dark by default, follows the person's theme and accent).

```
| rail | current screen (reflows)                     | SOL sidebar (360px, 320–480) |
```

## 1. Where it lives

- Every shell route except the SOL page itself: Home, Workspace, Live Bench, Store, Billing,
  Settings, an alert, an extension page. On the SOL page the sidebar is not rendered — the page
  already is SOL — and the topbar toggle is hidden.
- **One conversation per project, shared by all three surfaces.** The sidebar drives the same
  per-project chat session as the page (`useSolChat(projectId)`, `solChatStore`): moving between
  sidebar, page and pill never starts a new chat, and a streaming reply keeps streaming across a
  screen change or a close.
- Without an open project the sidebar shows the chat surface's existing "Open a project…" note.

## 2. Opening and closing

- **SOL toggle** in the menu bar's right cluster, before the bridge pill: the SOL orb, `SOL` and
  the shortcut hint (`⌘J` on macOS, `Ctrl J` elsewhere). `aria-pressed` reflects the sidebar's
  state on the current screen; its orb mirrors the sidebar orb (breathes idle, quickens while SOL
  works — also while the sidebar is closed).
- **⌘J / Ctrl J** toggles it from anywhere in the shell (a renderer keydown listener, like ⌘K —
  never a global OS hotkey; never with Shift or Alt; never mid-IME-composition). On the SOL page
  the chord does nothing.
- **Escape** inside the sidebar closes it unless a popover inside it (the `@` picker, the attach
  menu) is open and consumes the key first.
- **It follows the person.** One open/closed state for the whole shell: open it on the Workspace
  and it stays open on the Bench, Home, Settings… — the tag, greeting and placeholder re-scope to
  each screen, with no re-opening motion. On the SOL page it is hidden (not closed): leaving the
  SOL page brings it back. Remembered on this machine (`localStorage`, best effort). First run:
  closed.
- Opening moves focus into the composer; closing returns focus to the toggle.

## 3. The panel

- **Header (44px):** the SOL orb, `SOL`, and a mono **context tag** naming the scope SOL is
  given — the screen in caps, and on the Workspace the focused node's name when one is focused
  (`WORKSPACE · imu`), else just the screen (`LIVE BENCH`, `HOME`). The tag is a label only: it
  is built from the route name and the focused entity's display name (capped at 32 characters),
  never from ingested free text beyond that name. Then three icon buttons:
  - **Pop out to the pill** (Electron only — hidden where there is no SOL window bridge): closes
    the sidebar and opens the SOL window, which already holds the thread.
  - **Open in the SOL page** (⤢): the panel morphs to fill the screen, then the shell navigates
    to the SOL page on the same conversation. The sidebar closes (it does not reappear when the
    person leaves the SOL page).
  - **Close** (×).
- **Thread:** the shared `SolChat` surface in its `sidebar` layout — the page's message rendering
  (markdown, Thinking block, confirmation cards, plan cards, reasoning block, citation chips that
  open the surface they name), tightened for 360px. Citation chips behave as on the page
  (`[entity:id]` focuses the node in the Workspace, `[finding:id]` opens the Bench finding, a
  `.solus` entry opens its node).
- **Empty state (context greeting):** when the conversation has no messages yet, SOL's first line
  names the screen it sits on, and up to three **suggestion chips** offer starting questions for
  that screen. A chip sends its text as the person's message. Greetings and chips are
  Solus-authored constants per screen (§6); screens without their own get a plain greeting naming
  the screen.
- **Composer:** input, `@` picker and Send only — no preferences row (no Guide/Build badge, Think
  harder, Confirm every change or routing line; those stay on the SOL page and the pill). A send
  uses the current shared action mode and the chat's Confirm-every-change choice as set elsewhere.
  Short per-screen placeholder so it fits one line at 320px (`Ask about the workspace`,
  `Ask about the bench`, generic `Ask SOL anything`). Sends from the sidebar carry the Workspace
  focus and the chat's pinned nodes exactly as the page does (`focus`, `pins`).
- **Proactive notes** (SOL speaking first, with actions under the note): the panel renders any
  SOL message the session holds, so when a later ticket (Live Bench) adds proactive notes they
  appear here with their action buttons. This ticket adds no proactive trigger of its own.
- **Width:** default 360px; drag the left edge between 320 and 480px; the width is remembered
  (same storage as §2). Keyboard: the resize handle is a focusable `separator` — ←/→ step 16px.

## 4. Fit

- Window ≥ 1100px wide: the panel **docks** — the screen beside it reflows narrower.
- Window < 1100px: the panel **overlays** the screen's right edge with a soft shadow; the screen
  keeps its width.

## 5. Motion

All motion uses the existing SOL curves, `--sol-ease-out` `cubic-bezier(0.16, 1, 0.3, 1)` for
things arriving and `--sol-ease-in` `cubic-bezier(0.4, 0, 0.9, 0.6)` for things leaving; leaving
is always quicker than arriving. Under the OS reduced-motion setting every transition jumps to
its end state.

| Moment          | Motion                                                                                   |
| --------------- | ---------------------------------------------------------------------------------------- |
| Open            | width 0 → W, 340ms ease-out; content fades in with a 24px slide, 60ms later              |
| Close           | content out first, width → 0, 220ms ease-in                                              |
| Message arrives | fade + 8px rise, 320ms ease-out (as in the pill)                                         |
| Greeting, chips | greeting 60ms after open; chips 120ms after the greeting                                 |
| Thinking        | the SOL page's Thinking block unchanged (shimmer label, pulsing step dot, 200ms fold)    |
| Orb             | glow breathes 4s while idle, 1.1s while SOL works; the toggle's orb mirrors it           |
| Expand to page  | the panel grows to fill the screen area, 420ms ease-out; then the SOL page's screen-in   |
| Pop out         | the panel content shrinks toward the bottom-right, 260ms ease-in; then the pill's own in |

## 6. Per-screen copy (Solus-authored)

| Screen    | Tag            | Greeting                                                                 | Suggestions                                                               |
| --------- | -------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| Workspace | `WORKSPACE`    | "I can see the workspace graph. Ask about any node, or how two connect." | What does this project's graph cover? · Is anything wired inconsistently? |
| Bench     | `LIVE BENCH`   | "I'm watching the bench with you. Ask about a signal or what to test."   | What should I test first? · What can I put on the bench?                  |
| Home      | `HOME`         | "Ask about this project, or what changed since you were last here."      | What changed recently? · What should I work on next?                      |
| Others    | screen in caps | "Ask SOL about this project."                                            | —                                                                         |

## 7. Data collection

`sol.sidebar_toggled` (client event, consent-gated like every client event): payload
`{action: open|close|expand|pop_out, screen, via: button|shortcut|header|escape}` — ids and
enums only, never message text.

## 8. States

- Closed (default) · Open + empty (greeting + chips) · Open + thread · Working (Thinking block,
  Stop in the composer) · Needs your OK (confirmation card; nothing runs until Approve) ·
  Offline (`SOL HISTORY UNAVAILABLE — OFFLINE`) · No project (the chat surface's note).
