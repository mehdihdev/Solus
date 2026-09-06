# Cowork QA — HOME H1: Home as the cross-project surface (SOLUSDEV-242)

Home now shows ONE team's projects as a grid (create / open / switch / archive / delete) with each
project's own recent activity, a team selector, and the account-level actions (join team, new team,
connected accounts). Everything project-specific lives in the workspace screens. Switching projects
must carry nothing across. This file is the end-to-end test plan; it assumes the running application
and nothing else.

## Required setup

- API running (Postgres reachable), desktop renderer running against it, one signed-in user.
- The user belongs to **two teams**: their personal team and a shared team ("Team A" below) where they
  are the **owner** (only an owner can delete a project — ADR-025). If not, create a team from Home (`New team`).
- In Team A create two projects, **Rover** and **Arm**. Connect a DIFFERENT source to each (Sources
  screen; a GitHub repo on Rover and a GitLab repo on Arm is enough — a PAT is not required to create
  the row). Rename Rover once so it has more activity than Arm.
- Optional but strongly recommended for the SOL flow: a working LLM key and SOL credits on Team A.
- Tester should NOT have read the implementation session.

Mark each step ☐ pass / ✗ fail. Note the screen and the exact text on failure.

## Flow 1 — Home shows the active team's project grid

1. Open Home (rail top item, or the project pill → "All projects"). ☐
   - Expected: heading "Welcome back, <name>"; a line "Projects in <team>"; a team `<select>` labelled
     "Switch team" (only because you have two teams); `Join team` and `New team` on the right;
     CONNECTED ACCOUNTS card in the right column.
2. Confirm the grid shows only Team A's projects when Team A is selected: Rover and Arm cards plus a
   dashed **New project** tile; nothing from the personal team. ☐
3. Each card shows: graph glyph, name, description (if any), "RECENT ACTIVITY" with up to two rows,
   "All activity →", and a footer button. ☐
4. **Recent activity is per project**: Rover's card lists Rover's events (its rename and its source
   connection); Arm's card lists Arm's events only; nothing from Rover appears on Arm. ☐
5. Switch the team selector to the personal team. Expected: "Projects in <personal>", Rover/Arm are
   gone, the personal team's projects (or the empty tile) show. Switch back. ☐
6. Open the Team screen (rail). Expected: it shows the SAME team you selected on Home. Switch teams on
   the Team screen, go back Home: Home follows. ☐

## Flow 2 — Open and Switch to

1. With no project open (pill reads "No project"), every card's footer reads **Open**. Click Rover's
   footer button. Expected: lands on Rover's Overview; pill reads "Rover". ☐
2. Return Home. Expected: Rover's card reads **Open**; Arm's card reads **Switch to**. Cards share
   one subtle border; no card is highlighted. ☐
3. Click anywhere on Arm's card body (not the ⋯ menu). Expected: Arm's Overview; pill reads "Arm". ☐
4. Open the Sources screen. Expected: Arm's source only (the GitLab one), never Rover's. ☐
5. Use the project pill → Rover (stay on Sources). Expected: the list becomes Rover's source only;
   no flash of Arm's list, no leftover rows. ☐
6. Pill → a project in the OTHER team (if one exists). Go Home. Expected: Home's team selector and
   "Projects in" now name that other team. ☐

## Flow 3 — Nothing carries across a project switch (SOL)

Requires SOL to work. If it cannot, record "SOL unavailable" and skip to Flow 4.

1. Open Rover → SOL screen. Mode segment reads "Do" (default). Send:
   `Connect KiCad to this project now. Do not ask me anything, just do it.` ☐
   - Expected within ~30 s: SOL proposes `solus.connect_integration` and a card "SOL needs your
     approval" with **Approve / Reject** appears. Do NOT approve.
2. Pill → Arm (you stay on the SOL screen). Expected: header reads "ARM"; the transcript is Arm's
   (empty, "No chats yet…"); **the approval card is not there**; the Rover prompt text is not there. ☐
3. Pill → Rover. Expected: the transcript and the approval card are back, still awaiting a decision. ☐
4. Reject the card. Expected: the card clears; no error. ☐
5. In Rover, send any short question, then immediately switch to Arm before the reply finishes.
   Expected: if a "SOL replied" toast appears it reads "A turn finished in another project — switch
   back to read it." with NO "View" action; it never quotes Rover's prompt. (Toasts raised before a
   switch are cleared by the switch.) ☐

## Flow 4 — Alerts, Store detail, Live Bench across a switch

1. Open Rover → Context Model, select an entity (if the graph has any). Switch to Arm via the pill.
   Expected: no entity remains focused; widgets show Arm's (or empty) state, never Rover's neighbourhood. ☐
2. Open Rover → Store → click an extension to open its detail page. Pill → Arm. Expected: back on the
   Store catalog, not Arm's copy of Rover's detail page. ☐
3. If a notification toast with a "View" action for an alert exists, open the alert detail, then
   switch project via the pill. Expected: you land on Overview, not the previous project's alert. ☐
4. Live Bench: with Rover open, note the device/session list; switch to Arm. Expected: Arm's list
   (or its empty state); nothing from Rover. ☐

## Flow 5 — Create, rename, archive, unarchive, delete

1. Home → **New project** tile → name "Gripper" → Create. Expected: the project is created in the
   active team and opens on its Overview. Home shows it in the grid. ☐
2. ⋯ on Gripper → Rename → "Gripper v2" → Save. Expected: card renamed; opening the menu never opens the
   project. ☐
3. ⋯ on Gripper v2 → Archive. Expected: the card leaves the grid; a collapsed row **▸ ARCHIVED (1)**
   appears under the grid; the project pill's switcher no longer lists it. ☐
4. Expand ARCHIVED. Expected: Gripper v2 with **Unarchive** and a ✕ (delete, owner only). ☐
5. Unarchive. Expected: the card returns to the grid; ARCHIVED disappears (count 0). ☐
6. Archive again, expand, click ✕ → a confirmation dialog names the project → **Delete project**.
   Expected: it is gone from the grid, ARCHIVED, and the pill. ☐
7. Sign in as a **viewer** of Team A (or change your role). Expected: no ⋯ menus, no New project tile;
   cards still open. As a **member** or **admin**: ⋯ shows Rename/Archive but not Delete. ☐
8. Open Rover (pill reads "Rover"), go Home, ⋯ on Rover → Archive. Expected: Rover leaves the grid AND
   the pill reads "No project" — the shell never stays scoped to a hidden project. Unarchive it. ☐
9. Open Rover again, go Home, archive it, expand ARCHIVED, ✕ → Delete project. Expected: the pill
   reads "No project"; Overview/Sources/Context Model show their no-project state, never Rover's old
   entities. (Recreate Rover with its source if you still need it for other flows.) ☐
10. Force a failure (e.g. disconnect the API, then Archive). Expected: toast "That didn't work —
    Couldn't archive "<name>"."; the card stays. ☐

## Flow 6 — Per-project activity dialog

1. Rover card → **All activity →**. Expected: a dialog titled "Rover — activity", "N EVENTS" where N
   is Rover's own count, rows newest first, only Rover's events. ☐
2. If N > 50, a **Load more** button appends the next page; a failed page keeps the list. ☐
3. Close (✕ or click-out). Arm card → All activity. Expected: Arm's own events only. ☐

## Flow 7 — Teams and edge states

1. `Join team` with a bad token. Expected: inline error; dialog stays open. ☐
2. `Join team` with a valid invite token. Expected: the joined team becomes the active team; its
   projects fill the grid. ☐
3. `New team` → "Rocket Lab". Expected: Rocket Lab becomes active, empty grid with the New project
   tile ("Create one to start building the graph."). ☐
4. Leave every team (or use a fresh account with no teams). Expected: "You're not on any teams yet…"
   card; Join/New team still offered; no grid. ☐
5. Stop the API, reload the app. Expected: Home shows "You're signed in, but Solus can't reach its
   API…" — never a demo project. ☐
6. Sign out, then sign in as a DIFFERENT user on the same machine. Expected: Home shows only that
   user's teams; nothing of the previous user's projects, entities, or SOL chats is visible on any
   screen. ☐

## Cross-feature checks

- Project pill switcher still lists every team's live projects grouped by team, with the current one
  checked; archived projects never appear. ☐
- The Team screen's PROJECTS panel and Home's grid agree for the active team. ☐
- Data collection (if you can query it): each open/switch records a `project.switched` event scoped
  to the opened project with `from_project_id` and `surface` (home/topbar/team). ☐
