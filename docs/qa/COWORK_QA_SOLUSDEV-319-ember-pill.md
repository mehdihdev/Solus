# COWORK QA — SOLUSDEV-319: SOL Ember Pill (quick-summon window)

## What changed

- The SOL window is now a floating **pill**: frameless, transparent, always on top, 560 px wide,
  opened next to the mouse pointer. It shows a bar (glowing orb · message box · **Guide | Build**
  switch · send arrow) and a footer (`SOL`, "sees your screen" dot, **Think harder**, **Confirm every
  change**, `×` hide). A panel with the conversation, Guide tasks and the circled-region card opens
  **above** the bar and the window grows upward.
- Clicking another app hides the pill (the conversation is kept). It stays up while SOL is answering,
  while the latest reply has approvals waiting, or while a plan runs. Esc and `×` hide it.
  Double-tap Ctrl and Cmd/Ctrl+Shift+Space toggle it.
- The "Keep on top" pin and remembered window position are gone (the pill is always on top and always
  opens at the pointer).
- In the pill, a SOL reply's **non-command** approvals render as one **plan card**:
  `PLAN · N STEPS`, each step with its tool, summary and exact before → after values. **Run N
  steps** approves them one at a time; **Show me how instead** declines them and asks SOL (in Guide)
  to walk you through it; **Reject** declines them. Command cards (run a program) keep their own card.
- SOL does NOT move your mouse in this ticket. "SOL drives the app" is a separate future ticket.

Spec: `docs/wireflows/sol-window.md` → "SOLUSDEV-319 Ember Pill".

## Setup

1. `pnpm dev:all` running; signed in; a project open in the main window that has KiCad linked
   (a KiCad project with at least two resistors, e.g. R1 and R2).
2. Settings → SOL: **SOL sees your screen** ON (for flows 3 and 8), hold-Ctrl gestures ON.
3. macOS: Accessibility granted to Solus (for double-tap Ctrl). Two displays if available.
4. Another app (KiCad, a browser) in front for the summon flows.

## Flows

| #   | Steps                                                                                                          | Expected                                                                                                                                                                                                                   | Pass/Fail |
| --- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| 1   | With KiCad in front, put the pointer mid-screen and press Cmd+Shift+Space (Ctrl+Shift+Space on Windows/Linux). | A 560 px-wide pill appears just below-left of the pointer, no title bar or traffic lights, rounded dark surfaces with KiCad visible around them. The message box has focus; placeholder "Ask SOL, or tell it what to do…". | [ ]       |
| 2   | Press the same shortcut again.                                                                                 | The pill hides.                                                                                                                                                                                                            | [ ]       |
| 3   | Double-tap Ctrl with the pointer near the **bottom** of the screen.                                            | The pill appears ABOVE the pointer (it flips) and fully on screen.                                                                                                                                                         | [ ]       |
| 4   | Double-tap Ctrl near the right edge, then on a second display.                                                 | It stays fully inside the work area of the display under the pointer each time.                                                                                                                                            | [ ]       |
| 5   | Switch Guide → Build in the pill, then press Ctrl+Space.                                                       | The switch moves to Build, then back to Guide; the tray menu radio matches each time.                                                                                                                                      | [ ]       |
| 6   | In Build with no conversation (start a new chat from the SOL page first), summon the pill.                     | Only the bar + footer show (no panel).                                                                                                                                                                                     | [ ]       |
| 7   | Ask "what's in this project?"                                                                                  | A panel opens ABOVE the bar and the window grows upward (its bottom edge stays put). The orb pulses while SOL answers.                                                                                                     | [ ]       |
| 8   | While SOL is answering, click into KiCad.                                                                      | The pill stays visible until the answer finishes; after that, clicking KiCad hides it.                                                                                                                                     | [ ]       |
| 9   | Summon again.                                                                                                  | Same conversation is still there, pill re-opened at the new pointer position.                                                                                                                                              | [ ]       |
| 10  | Press Esc; summon; click `×`.                                                                                  | Each hides the pill.                                                                                                                                                                                                       | [ ]       |
| 11  | Type `@` and pick nothing; press Esc.                                                                          | The mention list closes; the pill stays. A second Esc hides the pill.                                                                                                                                                      | [ ]       |
| 12  | Make a long conversation (8+ turns).                                                                           | The panel stops growing at the window's max height and scrolls inside; the bar, footer and status line are never cut off.                                                                                                  | [ ]       |
| 13  | Hold Ctrl and circle something on screen.                                                                      | The pill opens with the region card in the panel and a `screen` chip in the footer; × on the chip removes it.                                                                                                              | [ ]       |
| 14  | In Build, ask "set R1 to 10k and R2 to 4k7".                                                                   | One **plan card**: `PLAN · 2 STEPS`, each step shows its tool (e.g. `kicad.set_symbol_property`), summary and `before → after` values exactly (e.g. `4.7k → 10k`). No separate approval cards.                             | [ ]       |
| 15  | While SOL is still writing that reply, look at **Run 2 steps**.                                                | Disabled, with "SOL is still answering — the plan may grow."                                                                                                                                                               | [ ]       |
| 16  | Make the panel short enough that step 2 is scrolled out of view (small screen or long reply).                  | Run stays disabled with "Scroll through every step to enable Run." until step 2 has been scrolled into view.                                                                                                               | [ ]       |
| 17  | Click **Run 2 steps**.                                                                                         | "APPLYING · STEP 1 OF 2" with the step's summary, a 2-segment bar and Stop; then step 2; then the plan disappears and KiCad shows both values.                                                                             | [ ]       |
| 18  | Repeat 14 and click **Stop** during step 1.                                                                    | Step 1 completes; step 2 stays in the plan, not applied.                                                                                                                                                                   | [ ]       |
| 19  | Repeat 14; edit R2 in KiCad and save; then Run.                                                                | Step 2 fails with SOL's reason (e.g. "what this would do has changed"), is marked "refused — won't run", and the header reads `PLAN · 1 STEP · 1 REFUSED` (if step 1 is still pending).                                    | [ ]       |
| 20  | Repeat 14; click **Show me how instead**.                                                                      | Both steps are declined, the switch moves to Guide and SOL starts explaining how to do it yourself. Nothing changed in KiCad.                                                                                              | [ ]       |
| 21  | Repeat 14; click **Reject**.                                                                                   | Both declined, nothing changed, no new SOL message.                                                                                                                                                                        | [ ]       |
| 22  | Ask SOL to run the project's tests (a command).                                                                | A normal command card (program, risk badges, Cmd/Ctrl+Enter), NOT inside the plan.                                                                                                                                         | [ ]       |
| 23  | Leave a plan unapproved, ask something else, let it finish, then click another app.                            | The pill hides (an older, unanswered plan does not pin it open).                                                                                                                                                           | [ ]       |
| 24  | Open the full SOL page in the main window and do flow 14 there.                                                | The page still shows one approval card per step (the plan card is pill-only).                                                                                                                                              | [ ]       |

## Edge cases and failure paths

- Signed out: summon → the pill shows only "Sign in from the main Solus window to use SOL here." [ ]
- No project open: the pill bar shows the "Open a project…" message. [ ]
- Screen capture permission missing (macOS): the status line under the pill names it in plain text; no link. [ ]
- Hook unavailable (Wayland / no Accessibility): status line shows the fallback; Cmd/Ctrl+Shift+Space still toggles. [ ]
- Full-screen KiCad (macOS full-screen Space): the pill appears over it. [ ]
- A previously saved pin / window position (from an older build): ignored — the pill always opens at the pointer, always on top. [ ]

## Cross-feature checks

- SOLUSDEV-317 command execution: command cards, Cmd/Ctrl+Enter and the Running processes strip still work in the pill. [ ]
- SOLUSDEV-262 Guide tasks: in Guide mode the tasks picker sits at the top of the panel. [ ]
- Mode stays in sync across pill, SOL page composer and tray. [ ]
- Theme/accent change in Settings re-skins the pill (orb, send button, plan accents). [ ]
