# Cowork QA — SOLUSDEV-233: Activity feed preview + "View all activity" dialog

Feature under test: the Team screen's **TEAM ACTIVITY** panel and the Home
screen's **RECENT ACTIVITY** panel now show at most **6 rows**. When more
activity exists, a blue **`View all activity (N) →`** button appears at the
bottom of the panel and opens a dialog listing the full feed (with a
**Load more** button on the Team feed). The backend activity route now reports
a `total` count in its pagination meta.

## Required setup

- [ ] Solus API running locally with a reachable database; desktop app running
      and signed in (workspace linked — not the offline dev-bypass state).
- [ ] One team where your user is **owner**, with at least one project.
- [ ] **Seed at least 8 activity events** in that team. Any mix of: creating /
      renaming / archiving / unarchiving projects, sending or revoking invites,
      connecting or disconnecting a source, starting a sync. Each action adds
      one activity row.
- [ ] (For the cross-team path) a second team you belong to, with 2–3 activity
      events of its own.
- [ ] (Optional, for the pagination path) a team with **more than 50** activity
      events — a quick loop of project renames works.

## Flow 1 — Team screen panel truncation

1. Open the **Team** screen (people icon in the left rail) for the seeded team.
   - Expected: `TEAM ACTIVITY` panel shows **exactly 6** rows, newest first,
     each with an avatar, the actor's name in bold, a human sentence
     ("created the project …", "sent an invite …"), and a relative time.
2. Look at the bottom of the panel.
   - Expected: a blue **`View all activity (N) →`** row, where **N is the real
     total** number of events in the team (not 6, not the loaded count if more
     exist server-side).
3. Pass/fail: [ ]

## Flow 2 — View-all dialog (Team)

1. Click `View all activity (N)`.
   - Expected: a centered dialog over a dimmed backdrop titled **ALL ACTIVITY**
     with **`N EVENTS`** on the right and a ✕ close button. All loaded rows are
     listed (8+ from setup), same row format as the panel, scrollable if tall.
2. If the team has more than 50 events: a **Load more** button sits under the
   rows.
   - Click it. Expected: the button shows `Loading…` briefly, then ~50 more
     rows append below (no duplicates, order preserved). When everything is
     loaded, the button disappears.
3. Close the dialog three ways (reopen between each): the ✕ button, clicking
   the dimmed backdrop, and clicking inside the dialog (should NOT close it —
   only the first two close).
4. Pass/fail: [ ]

## Flow 3 — Home screen panel truncation (cross-team)

1. Open **Home** (house icon).
   - Expected: `RECENT ACTIVITY` panel (right column) shows **at most 6** rows
     merged across all your teams, newest first — plain text rows (no avatars),
     each with a relative time.
2. With 8+ total events across teams, expect the blue
   `View all activity (N) →` row, where **N is the sum of every team's total**.
3. Click it.
   - Expected: the same ALL ACTIVITY dialog, listing the merged feed (up to 50
     rows per team). **No Load more button** on Home — this is by design.
4. Pass/fail: [ ]

## Flow 4 — Feed that fits (no button)

1. Create a brand-new team (New team) and open its Team screen. It will have
   only 1–2 events (team created, maybe project created).
   - Expected: the activity rows render, and there is **no**
     `View all activity` button anywhere in the panel.
2. Same check on Home for a fresh account with ≤6 total events (if available).
3. Pass/fail: [ ]

## Flow 5 — Live update interaction

1. On the Team screen, with the panel showing 6 rows and the button visible,
   create a new project.
   - Expected after the refresh: the newest event ("created the project …")
     appears at the top of the panel, the panel still shows 6 rows, and the
     button count **N increases by one**.
2. Pass/fail: [ ]

## Edge cases & failure paths

- [ ] **Offline**: quit the API and reload the app. Home and Team show their
      honest offline messages — no activity panel, no view-all button, no crash.
- [ ] **Empty team feed**: a team with zero events shows "No activity yet…"
      (Team) / "Nothing yet." (Home) and no button.
- [ ] **Load-more failure**: (if testable) kill the API while the dialog is
      open, then click Load more. Expected: the already-listed rows stay; no
      crash; button returns to `Load more`.
- [ ] **Cross-team isolation**: sign in as a user in team A only. The Team
      panel, dialog, and counts must never include team B's events. Verify the
      count N matches team A's own history.
- [ ] **Permissions**: a `viewer`-role member sees the panel, button, and
      dialog identically (read-only feature — no role gating expected).

## Cross-feature interactions

- [ ] Invite accept / archive / unarchive flows from
      `COWORK_QA_teams-frontend.md` still append visible activity rows (now to
      the 6-row preview) — the new truncation must not hide the newest event.
- [ ] Opening the view-all dialog does not interfere with the other Team-screen
      modals (Invite, New team, Join, New project) before or after use.
- [ ] Team switcher: switch teams while on the Team screen; the panel, button
      count, and dialog reflect the newly selected team only.
