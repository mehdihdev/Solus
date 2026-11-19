# Cowork QA — Responsive Home (SOLUSDEV-328, design A2)

Home's team overview now fills the window in full-height columns, and the SOL sidebar's starting
width scales with the window until you resize it. Governing docs: `docs/wireflows/home.md`
("Fills the window") and `docs/wireflows/sol-sidebar.md` §3 Width.

## Setup

- [ ] Solus desktop running against a working API (`pnpm dev:all`), signed in.
- [ ] Account on **two collaborative teams** plus the personal workspace. Team A ("Arm Lab"):
      you are **Owner**, ≥ 3 members, ≥ 1 pending invite, ≥ 3 projects, one archived, some
      synced activity (more than one page — e.g. 30+ events). Team B: you are a **Member**.
- [ ] A second account that is a **Viewer** on Team A (permission checks).
- [ ] A display you can resize the Solus window on up to ≥ 2200px wide (or an external monitor).
- [ ] Clear the sidebar's saved width: DevTools → Application → Local Storage → delete
      `solus.sol-sidebar` (first-run state).

## 1. Overview columns follow Home's width

| #   | Step                                                             | Expected                                                                                                                                                                                                                             | ✓/✗ |
| --- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| 1.1 | Open Home on Team A, window ~1440 wide, SOL sidebar closed       | Header bar (team, `ACTIVE · N MEMBERS`, avatars, Invite to Arm Lab, ⋯). Below: PROJECTS table on the left, TEAM column (340px, raised background) on the right. No empty strip on the right; both columns reach the window's bottom. |     |
| 1.2 | Scroll inside the PROJECTS column, then inside the TEAM column   | Each scrolls on its own; the header bar stays put.                                                                                                                                                                                   |     |
| 1.3 | Widen the window until Home (right of the team rail) is ≥ 1680px | A third column appears between them: the project column.                                                                                                                                                                             |     |
| 1.4 | Narrow the window until Home is < 880px                          | One scroll: projects, then the team column beneath with a divider. Nothing clipped sideways.                                                                                                                                         |     |
| 1.5 | Drag the window width back and forth across both thresholds      | Columns change without a page reload or flicker of the pane's entrance animation.                                                                                                                                                    |     |

## 2. The project column (wide only)

| #   | Step                                                                          | Expected                                                                                                                                                                                                                                               | ✓/✗ |
| --- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| 2.1 | Wide Home, switch to Team A right after starting the app with no project open | Project column reads "Pick a project to see it here." Nothing is selected for you.                                                                                                                                                                     |     |
| 2.2 | Click a project name in the table                                             | Home stays on the overview. The row gets an accent edge; the project column shows its name, repo line, description, Live Bench, Open workspace, SOURCES and .SOLUS side by side, then PROJECT ACTIVITY. The topbar's project pill shows it as current. |     |
| 2.3 | Click a different project                                                     | Column swaps to it; the marked row moves; the pane does not replay its fade-in.                                                                                                                                                                        |     |
| 2.4 | In PROJECT ACTIVITY, click Load more (project with many events)               | Older rows append; the button goes when there are no more.                                                                                                                                                                                             |     |
| 2.5 | Click .SOLUS → Add instructions                                               | Opens the tabbed project pane (with "← Back to Arm Lab").                                                                                                                                                                                              |     |
| 2.6 | Click Live Bench / Open workspace                                             | Navigate to the Live Bench / open the project workspace.                                                                                                                                                                                               |     |
| 2.7 | Make a Team B project current, then switch the rail to Team A                 | Team A's project column shows "Pick a project…" — another team's project never shows.                                                                                                                                                                  |     |
| 2.8 | Narrow below 1680 and click a project name                                    | Opens the tabbed project pane as before (no column).                                                                                                                                                                                                   |     |

## 3. The team column

| #   | Step                                  | Expected                                                                                                                                                 | ✓/✗ |
| --- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 3.1 | Team A as Owner                       | MEMBERS · N lists **every** member with "<Role> · joined <when>"; hover a row shows the email.                                                           |     |
| 3.2 | Team with many members (≥ 12)         | The members section stops at ~40% of the column and scrolls on its own; activity stays visible below.                                                    |     |
| 3.3 | Click "All N members and invites"     | Opens Team & invites.                                                                                                                                    |     |
| 3.4 | As Owner/Admin with a pending invite  | PENDING INVITES · N with invitee, role, "sent <when>", and Manage invites.                                                                               |     |
| 3.5 | Sign in as the Viewer on Team A       | No PENDING INVITES; header reads "You're a Viewer here · ask an owner or admin to invite"; no Invite button.                                             |     |
| 3.6 | TEAM ACTIVITY with > 1 page of events | Rows show actor names; **Load older activity** appends older rows and disappears at the end. Button is disabled while loading.                           |     |
| 3.7 | A team with no activity               | "No activity yet. Syncs, invites, and project changes will show up here." and no paging button.                                                          |     |
| 3.8 | Switch to the personal workspace      | Header "Personal workspace · ONLY YOU"; team column shows only TEAM ACTIVITY (no members, no invites).                                                   |     |
| 3.9 | Confirm the old cards are gone        | No "You in <team>" card and no "Work with others" card anywhere on the overview. Join with an invite code still works from the team rail and the ⋯ menu. |     |

## 4. SOL sidebar width

| #   | Step                                                             | Expected                                                                                 | ✓/✗ |
| --- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --- |
| 4.1 | First-run state, window 1440, press ⌘J (Ctrl J)                  | Sidebar opens at 360px.                                                                  |     |
| 4.2 | Window 1920                                                      | Sidebar is ~422px.                                                                       |     |
| 4.3 | Window ≥ 2200                                                    | Sidebar is 480px.                                                                        |     |
| 4.4 | Resize the window while the sidebar is open                      | Sidebar width follows the window (360–480).                                              |     |
| 4.5 | Drag the sidebar's left edge to ~400px, then resize the window   | Sidebar stays at your 400px at every window size.                                        |     |
| 4.6 | Restart the app                                                  | Sidebar comes back at 400px (your width is remembered).                                  |     |
| 4.7 | Focus the resize handle and press ←/→ in first-run state at 1920 | Steps by 16px starting from ~422 (not from 360), and the width is now yours.             |     |
| 4.8 | Window < 1100                                                    | Sidebar overlays Home's right edge with a shadow; Home keeps its width (unchanged rule). |     |

## 5. Home with the sidebar open (the reason for this work)

| #   | Step                                               | Expected                                                                                           | ✓/✗ |
| --- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------- | --- |
| 5.1 | Window 2560, first-run width, sidebar open on Home | Sidebar 480px; Home still ≥ 1680 → three columns: projects │ project │ team. No large empty areas. |     |
| 5.2 | Window 1920, sidebar open                          | Sidebar ~422; Home drops to two columns (projects │ team).                                         |     |
| 5.3 | Window 1440, sidebar open                          | Home is ~880–1100 wide → two columns if ≥ 880, else stacked. Nothing overlaps the sidebar.         |     |
| 5.4 | Toggle ⌘J repeatedly on a wide window              | Home's columns reflow each time the sidebar docks/undocks.                                         |     |

## 6. Regressions to spot-check

- [ ] Team & invites, Connected accounts and the project pane still show their readable column (not stretched edge to edge).
- [ ] Row ⋯ menu (rename, archive, delete per role), New project, ARCHIVED (N) behave as before.
- [ ] Offline / signed-out Home still shows the honest offline card.
- [ ] Switching teams from the rail lands on the new team's overview with the columns intact.
- [ ] Light theme and the other accents: column backgrounds and the selected-row edge use theme tokens.
