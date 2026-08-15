# COWORK QA — SOLX-02: the persistent SOL orb (SOLUSDEV-201)

End-to-end test plan for the persistent orb: always-present orb, anchored chat
panel, corner docking, SOL chat (streaming, citations, tool trace, guide/do),
full-page SOL screen, and the detached always-on-top window. Written for a
tester with the running application and this file only.

## Required setup

- [ ] Solus API running locally (`packages/api`) with the SOLUSDEV-135 SOL chat
      routes live (`POST /api/v1/projects/{id}/sol/conversations`, SSE
      `…/messages`). The scaffold runner answers deterministically — no model
      key needed.
- [ ] Desktop app running under Electron (`pnpm dev` in `apps/desktop`).
      The detach flows REQUIRE Electron; a browser preview hides them by design.
- [ ] A signed-in user, onboarded, with at least one project created and open
      (the orb's chat is project-scoped).
- [ ] A second user account (or a teammate) for the isolation check.

## 1. The orb is always present

1. [ ] Sign in and land on Home: an amber orb sits in the bottom-right corner.
2. [ ] Navigate Home → Overview → Context Model → Live Bench → Team: the orb
       stays visible on every screen.
3. [ ] Open the SOL screen from the rail: the corner orb hides (the screen IS
       the chat surface); leaving the SOL screen brings it back.
4. [ ] Idle orb shows no animation. Expected: it pulses only while SOL streams.

## 2. Expand / collapse the chat panel

1. [ ] Click the orb: a chat panel opens anchored to the orb's corner —
       header (SOL, Open SOL screen, Detach, ×), message area, input row with
       a Guide/Do toggle and Send.
2. [ ] Click the orb again (or ×): the panel closes.
3. [ ] Reload the app with the panel open: the open/closed state and corner are
       remembered (persisted preference).
4. [ ] With NO project open (fresh account): the panel shows "Open a project to
       chat with SOL", no input.

## 3. Dock between corners

1. [ ] Drag the orb from bottom-right toward the top-left and release: it snaps
       to the top-left corner (nearest corner wins — there is no free placement).
2. [ ] Try all four corners. The open panel follows the orb's corner.
3. [ ] A small jiggle (a few px) does NOT count as a drag — it toggles the panel.
4. [ ] Reload: the docked corner is remembered.

## 4. Chat: streaming, citations, trace, guide/do

1. [ ] Send "What entities are in this project?" — the user message appears
       immediately, then SOL's reply streams in progressively; the orb pulses
       while streaming and stops after.
2. [ ] While typing (pause ~0.5 s), a small muted routing line appears under the
       input (tier · type · model). Clicking it opens the override popover
       (this-message-only). It must never block sending.
3. [ ] A reply grounded in graph data shows a CITATIONS region under the text:
       plain mono tokens, NOT hyperlinks, long tokens ellipsized (~64 chars).
       Expected: citations appear only in that region, never woven into prose.
4. [ ] A turn that used tools shows a collapsed "N tool steps" row; expanding it
       lists tool names with ok/error only — never raw argument values.
5. [ ] Toggle Guide → Do and send a message that would operate a tool. Expected:
       the request carries action_mode=do (server logs `agent.tool_invoked`
       with it); in Guide, mutating tools are refused by the backend.
6. [ ] Close and reopen the panel: the conversation history reloads (turns
       persist server-side per project, per user).
7. [ ] Stop the API and send a message: an "SOL is unreachable right now." note
       appears on the failed turn — no crash, no raw error text, pulse stops.
8. [ ] Sign in as the second user in the same project: they do NOT see the first
       user's conversation (owner-private, 404 posture).

## 5. Full-page SOL screen

1. [ ] Open SOL from the rail: header (orb, SOL, project name, Guide/Expert
       mode toggle) over the same chat surface, page-width.
2. [ ] The Guide/Expert toggle switches the universal SOL mode (ADR-016) and the
       hint text updates ("explains and teaches" / "terse, direct").
3. [ ] History matches what the orb panel showed — same conversation.
4. [ ] "Open SOL screen" in the orb panel header navigates here and closes the
       panel.

## 6. Detach to the always-on-top window

1. [ ] In the orb panel, click Detach: a small frameless window appears, always
       on top, showing SOL + project name + chat; the in-app orb dims with
       tooltip "SOL is detached — click to re-attach".
2. [ ] Focus another application: the SOL window stays on top.
3. [ ] Drag the SOL window by its header bar: it moves (frameless drag region).
4. [ ] Chat works in the detached window: streaming, citations, trace — same
       conversation as the main window (history converges on reload).
5. [ ] Click "Return to app" in the detached window: it closes; clicking the
       dimmed in-app orb restores the normal orb (re-attach is idempotent).
6. [ ] Close the detached window with the OS (Alt+F4 / ⌘W): no crash; clicking
       the dimmed orb in the main app recovers to the attached state.
7. [ ] Click Detach twice quickly: exactly one window exists (the second call
       focuses it).
8. [ ] Detach, then quit the app entirely: both windows close, no orphan
       process.

## 7. Accessibility + perf spot checks

1. [ ] With OS "reduce motion" enabled, the streaming pulse does not animate.
2. [ ] Keyboard: Tab reaches the orb button; Enter toggles the panel; the input,
       Guide/Do toggle, and Send are reachable and operable by keyboard.
3. [ ] With the app idle (orb visible, panel closed) the renderer's CPU usage is
       ~0 and no animation frames fire (DevTools performance monitor).

## 8. Cross-feature interactions

1. [ ] Switching the project from the topbar re-scopes the orb panel's chat to
       the new project (fresh history / empty state).
2. [ ] Sign out with the panel open: no crash; signing back in restores the orb.
3. [ ] The onboarding flow and auth screens show no orb (workspace-only mount).
4. [ ] Live contextIsolation round-trip (carried from SOL-IPC-01): in the
       detached window's DevTools, `window.solus.orbOverlay` exists and a
       malformed `publishToOverlay({type:'nope'})` throws without crashing
       either process.
