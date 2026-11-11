# COWORK QA — SOLUSDEV-324: SOL actually sees your screen

**Bug:** with "SOL sees your screen" on, the SOL pill answered "I can't see your screen" to any typed question.
**Fix:** summoning SOL takes one picture of the screen (before the pill appears) and sends it with the next
question. Circling a region still works and wins over the summon picture.

## Setup

- [ ] Solus desktop running from this branch (`pnpm dev:all`), signed in, a project selected.
- [ ] macOS: Solus (or the dev Electron) granted **Screen Recording** in System Settings › Privacy & Security.
- [ ] Settings › SOL › **SOL sees your screen** ON. A model with vision configured for SOL.
- [ ] Another app with recognisable content in front (e.g. a browser page with a clear heading).

## Flows

1. **Typed question sees the screen**
   - [ ] Over the browser, press Cmd+Shift+Space (or double-tap Ctrl). Pill opens; footer shows "sees your screen".
   - [ ] Type "what's on my screen right now" → send. Expected: the user row shows **screen attached**; SOL
         describes the browser page (heading/content), not "I can't see your screen".
   - [ ] The answer does not describe the SOL pill itself (the picture was taken before it appeared).
2. **One question only**
   - [ ] Without re-summoning, ask a second question. Expected: no "screen attached" on that row.
   - [ ] Hide the pill (Esc), switch to a different app/page, summon again, ask. Expected: SOL describes the
         NEW screen.
3. **Circled region wins**
   - [ ] Hold Ctrl and circle a part of the screen. Region card appears. Ask a question. Expected: SOL answers
         about the circled area.
4. **Multi-monitor** (if available)
   - [ ] Summon with the cursor on the second display; ask. Expected: SOL describes that display.

## Edge / failure paths

- [ ] Setting **off** → summon, ask "what's on my screen". Expected: no "screen attached"; SOL says it can't see it.
- [ ] Setting on but Screen Recording **denied** → status line names the permission; the question still sends
      (without a picture), no error.
- [ ] Summon, then turn the setting off in Settings before asking → ask. Expected: no picture sent.
- [ ] Summon, Esc to hide, re-summon within 5 s (resume) → ask. Expected: a fresh picture is attached.
- [ ] Sign out while the pill holds a picture; sign in as another account; ask without re-summoning.
      Expected: no picture from before sign-out.
- [ ] Very busy screen (full-screen photo or dense CAD view) → ask. Expected: the turn sends (picture attached
      or silently omitted), never a 422 error.
- [ ] Summon feels instant (< ~0.5 s) even with the capture.

## Cross-feature

- [ ] SOL page in the main window (not the pill): typing a question never attaches a summon picture.
- [ ] Guide tasks / Build drive in the pill still work as before.
