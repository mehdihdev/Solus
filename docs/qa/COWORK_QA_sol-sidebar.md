# Cowork QA — SOL Sidebar (SOLUSDEV-327)

A SOL panel docked to the right of every Solus screen except the SOL page. It shares one
conversation per project with the SOL page and the SOL pill. Spec: `docs/wireflows/sol-sidebar.md`.

## Setup

- [ ] Solus desktop running (`pnpm dev:all`), signed in, data-collection consent ON (for the event check).
- [ ] A project open with a connected source and a populated Workspace graph (so a node can be focused).
- [ ] SOL working (API reachable, credits available) — at least one message answerable.
- [ ] macOS: ⌘ is the modifier. Windows/Linux: Ctrl.
- [ ] A window at least 1300px wide to start.

## 1. Toggle and shortcut

1. [ ] Open the Workspace. In the menu bar's right cluster, before the bridge pill, there is a **SOL** button with a small glowing orb and `⌘J` (or `Ctrl J`). Expected: not pressed.
2. [ ] Click it. Expected: a panel slides open from the right (~⅓ s), the Workspace reflows narrower (not covered), the panel content fades/slides in slightly after the frame; the button reads pressed (accent tint). The composer has keyboard focus.
3. [ ] Press ⌘J. Expected: the panel closes faster than it opened; content fades first; focus returns to the SOL button.
4. [ ] Press ⌘J again. Expected: opens. Press ⌘⇧J and ⌥⌘J. Expected: nothing happens.
5. [ ] With the panel open, press Escape while the composer is focused. Expected: closes.
6. [ ] Type `@` plus a few letters in the composer until the node picker list appears, then press Escape. Expected: only the picker closes; the sidebar stays open.

## 2. It follows you

1. [ ] Open the sidebar on Workspace. Go to Live Bench, Home, Settings. Expected: it stays open on every screen, without replaying the slide; the tag, greeting and placeholder change to each screen; the thread is the same.
2. [ ] Close it on Home, go to Workspace. Expected: closed there too.
3. [ ] Open it, quit and relaunch Solus. Expected: open again.
4. [ ] With it open, go to the **SOL** rail item. Expected: no sidebar and no SOL toggle in the menu bar; ⌘J does nothing. Go back to Workspace: the sidebar is there again.

## 3. Header and context greeting

1. [ ] On Workspace with no node focused, open the sidebar on a project whose current chat is empty (start a New chat on the SOL page first if needed). Expected header: orb · `SOL` · tag `WORKSPACE`. Body: an accent-tinted SOL note ("I can see the workspace graph…"), then two suggestion chips rising in just after it. Placeholder: "Ask about the workspace", on one line. The composer shows only +, the input and Send — no Build/Guide, Think harder, Confirm every change or routing line.
2. [ ] Click a node in the Workspace graph. Expected: the tag becomes `WORKSPACE · <node name>`; a very long name is cut with "…".
3. [ ] Live Bench: tag `LIVE BENCH`, bench greeting, chips "What should I test first?" / "What can I put on the bench?", placeholder "Ask about the bench".
4. [ ] Home: tag `HOME`, home greeting and chips. Billing / Settings / Store: tag names the screen, plain "Ask SOL about this project." greeting, no chips.
5. [ ] Click a chip. Expected: it appears as your message; the shimmering **Thinking…** label shows; the header orb (and the menu-bar orb) breathe faster; SOL answers. The chip row is gone once the chat has messages.

## 4. One conversation across surfaces

1. [ ] Ask a long question in the sidebar. While SOL is still streaming, click the SOL rail item. Expected: the SOL page shows the same conversation, still streaming.
2. [ ] Go back to Workspace (sidebar open). Expected: same thread, reply complete or still streaming — never a new chat.
3. [ ] Close the sidebar mid-stream. Expected: the menu-bar orb keeps breathing fast until the reply finishes. Reopen: the full reply is there.
4. [ ] Open the SOL window/pill (Electron). Expected: it holds the same thread.

## 5. Expand and pop out

1. [ ] In the sidebar header click **Open in the SOL page** (diagonal arrows). Expected: the panel grows to fill the screen area (~0.4 s), then the SOL page appears on the same conversation. Leaving the SOL page shows the sidebar **closed**.
2. [ ] Open the sidebar again, click **Pop out to the pill** (frame icon). Expected: the panel contents shrink toward the bottom-right corner and fade (~¼ s), the sidebar closes, and the SOL pill window appears with the same thread.
3. [ ] Run the renderer in a plain browser (no Electron): the pop-out button is absent; expand and close still work.

## 6. Width and fit

1. [ ] Hover the sidebar's left edge: an accent line appears and the cursor becomes a resize cursor. Drag left/right. Expected: the width follows, stopping at 320px minimum and 480px maximum; the screen reflows. Relaunch: width remembered.
2. [ ] Tab to the edge handle (focus ring/accent line) and press ← / →. Expected: 16px steps within the same bounds.
3. [ ] Narrow the Solus window below ~1100px. Expected: the sidebar now floats over the screen's right edge with a soft shadow; the screen keeps its width. Widen again: it docks.

## 7. Thread behaviour in the sidebar

1. [ ] Ask something that cites a graph node. Click an `[entity:…]` citation chip. Expected: the Workspace opens with that node focused.
2. [ ] Ask SOL to delete a graph link. Expected: a confirmation card appears in the sidebar; nothing changes until Approve; Reject clears it. A routine edit (e.g. renaming a note) may run without a card — SOL builds as needed.
3. [ ] On the SOL page, the pill and the sidebar: no Guide/Build control, no Think harder, no Confirm every change and no routing line anywhere in the composer.

## 8. Motion and accessibility

1. [ ] macOS System Settings → Accessibility → Display → Reduce motion ON. Repeat 1.2, 3.5, 5.1, 5.2. Expected: no sliding, fading, morphing or orb breathing — every change is instant; everything still works.
2. [ ] Switch Settings → Appearance to the light theme and another accent. Expected: the sidebar, bubbles, orb and toggle follow the theme and accent.
3. [ ] Screen reader / accessibility inspector: the panel is a landmark "SOL sidebar"; the toggle is a pressed/unpressed button; header buttons are named "Pop out to the pill", "Open in the SOL page", "Close SOL sidebar"; the handle is a separator "Resize SOL sidebar" with a value.

## 9. Edge cases

1. [ ] No project open (Home after signing in fresh): open the sidebar. Expected: "Open a project to chat with SOL…" note; no errors.
2. [ ] API offline (stop the API): open the sidebar. Expected: `SOL HISTORY UNAVAILABLE — OFFLINE`; the app does not crash.
3. [ ] Switch project from the topbar with the sidebar open. Expected: the thread switches to the new project's conversation; the tag drops any focused node from the old project.
4. [ ] Out of credits: send from the sidebar. Expected: the same top-up notice as the SOL page.
5. [ ] Rapidly press ⌘J ~10 times. Expected: ends in a consistent open/closed state matching the toggle; no stuck half-width panel.

## 10. Data collection

1. [ ] With consent ON, perform: open via button, close via ⌘J, close via Escape, expand, pop out. Expected: `data_events` gains `sol.sidebar_toggled` rows with payloads like `{"action":"open","screen":"workspace","via":"button"}` — enums only, never message text.
2. [ ] With consent OFF: no rows are stored.

## Pass/fail summary

| Section               | Pass | Notes |
| --------------------- | ---- | ----- |
| 1 Toggle and shortcut |      |       |
| 2 Per-screen memory   |      |       |
| 3 Header and greeting |      |       |
| 4 One conversation    |      |       |
| 5 Expand / pop out    |      |       |
| 6 Width and fit       |      |       |
| 7 Thread behaviour    |      |       |
| 8 Motion / a11y       |      |       |
| 9 Edge cases          |      |       |
| 10 Data collection    |      |       |
