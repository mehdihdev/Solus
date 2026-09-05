# Completion report — SOLUSDEV-242 · HOME H1: Home as the cross-project surface

Branch: `SOLUSDEV-242-home-cross-project-surface` (local commits only; no push, no MR).
Cowork QA: `docs/qa/COWORK_QA_home-h1-cross-project-surface.md`.

## What was built

**Home (apps/desktop, features/workspace)** — rebuilt as the cross-project surface:

- `useHomeData` now loads the ACTIVE team (`workspaceStore.teamId`, resolved by the new shared
  `activeTeam.ts` rule that the Team screen also uses), its projects (archived included) and its
  recent feed split per project (`projectActivity.ts`). Team switches are sequenced so a slow answer
  for the previous team never lands on the new one.
- `HomeScreen` → `ProjectGrid` of `ProjectCard`s (name, description, CURRENT mark, two rows of the
  project's own activity, `All activity →` dialog, Open / Switch to footer, ⋯ Rename/Archive/Delete),
  a New project tile (member+), a collapsed `ARCHIVED (N)` section (`ArchivedProjects`) with
  Unarchive / Delete, the shared `TeamSelect`, Join team / New team, and the SOLUSDEV-241 Connected
  Accounts card. The merged cross-team feed left Home (the Team screen keeps its feed).
- `ProjectActivityModal` + `useProjectActivity`: one project's full feed, server-filtered and paged.
- `ActivityModal` gained a `title` prop; `TeamSwitcher` moved out of `TeamScreen` into `TeamSelect`.

**Project switching — one choke point** (`features/workspace/projectSwitch.ts`):
`switchWorkspaceProject(next, surface)` is now the ONLY path (Home cards, the topbar pill, the Team
screen, and the dead-project validator). It sets the project and its team, clears the focus engine,
the Store detail selection and the shell toast, and reports a `project.switched` data event. The
module header carries the store audit (what holds project state and how each is kept honest).
Additional leak fixes found by the audit: the shell now resets an open **alert** detail route on switch
(only extension pages were reset); `useProjectSources` / `useProjectOverview` drop responses for a
project the user has since left (a slow answer could paint project A's documents over B); the graph
entity cache is cleared on sign-out (WS-01 parity); `WorkspaceProject` carries `teamId` so opening a
project makes its team the active team everywhere.

**API (packages/api)**: `GET /teams/{team_id}/activity?project_id=` narrows the team-scoped feed to
one project (`meta.total` follows the filter; a foreign project id matches nothing); `project.switched`
joined the closed client-event set (`POST /events`). `openapi.json` and the desktop `schema.ts`
regenerated.

## Governing docs

CLAUDE.md (root, apps/desktop), DECISIONS.md (ADR-009/016/021/032/034), docs/api/API.md §1.3/§2.2/
§2.3/§2.13/§5, docs/wireflows/project-topbar.md, activity-feed.md, store.md, widget-canvas.md,
docs/architecture/solus-folder.md. The ticket's `docs/design/SPEC.md` and `docs/design/screens/` do
not exist in this repository; the docs above governed instead.

Tier-1 amendments made directly (ADR-032, reviewed at the MR): `docs/api/API.md` §2.2 (activity
`project_id` filter), §2.13 (`project.switched`), §5 ("/" route description); new
`docs/wireflows/home.md` (plan of record for Home); `docs/wireflows/activity-feed.md` Home surface.
No tier-2 file (contracts, DECISIONS.md, CLAUDE.md) was touched.

## Verification

- Desktop: 247 files / 2582 tests green (`vitest run`), typecheck (node + web) clean, eslint clean on
  touched files, prettier applied to touched files. New/updated suites: `projectSwitch.test.ts`
  (every store driven through a switch, incl. the parked-confirmation case), `activeTeam.test.ts`,
  `useHomeData.test.ts`, `useProjectActivity.test.ts`, `projectActivity.test.ts`, `HomeScreen.test.tsx`
  (21 cases), `WorkspaceShell.test.tsx` (+3: toast cleared, alert route reset, graph cache on sign-out),
  `useProjectSources/useProjectOverview` stale-guard cases, `resources.test.ts`, TeamScreen/ProjectSwitcher
  payload updates.
- API: `test_activity.py` (+3: project filter, team scope of a foreign project id, non-UUID → 422),
  `test_events_ingest.py` (+1). ruff + mypy clean. Full API suite: see the "Suite runs" line below.
- **Run for real** against a private API instance (port 8001, same dev Postgres) and a scratch renderer
  (port 5199) with a minted dev JWT, driven by an Electron harness that seeded two projects with
  different sources (Rover: GitHub, Arm: GitLab) and sent a real do-mode SOL turn. 18/18 checks passed:
  active-team grid with CURRENT / Switch to; per-project activity on cards (Arm never shows Rover's
  rows); a REAL parked `solus.connect_integration` confirmation in Rover is not visible after switching
  to Arm on the same SOL screen, and is still parked on return; Sources for Arm show only GitLab and for
  Rover only GitHub after topbar switches; the project activity dialog is project-scoped; the Team
  screen shows the same active team; switching the team selector re-scopes the grid. Screenshots are
  in the session scratchpad (not committed).

## Decisions under delegated judgment

1. Per-project card activity is derived from ONE fetch of the team feed (50 rows) split by project,
   not one request per card — this desktop has 429'd itself before (SOLUSDEV-234). It is a window:
   a project absent from the team's latest 50 rows reads "No recent activity." The per-project dialog
   uses the new server filter for the full, correctly-totalled feed.
2. The cross-team merged activity panel was removed from Home per the ticket ("recent activity per
   project"); team-level rows (invites, members) live on the Team screen.
3. Opening or switching a project sets the active team from the project's team. `WorkspaceProject.teamId`
   is optional so pre-242 persisted state and the onboarding path keep working.
4. SOL sessions stay keyed per project in the background (SOLUSDEV-233 design): a switch never selects
   A's transcript for B, and A's parked confirmation stays parked for the user's return. The away-toast
   is cleared on switch so a "View" raised under A cannot open B's SOL page.
5. `project.switched` is reported only for signed-in sessions (the dev bypass has no token) and never
   for a re-select of the current project.

## Deviations / open concerns

- **Detached orb window**: it rehydrates the workspace project once from localStorage and does not
  follow a switch made in the main window; it is labelled with its own project name so nothing shows
  under the wrong project, but it goes stale. Out of this ticket's surface (lane-sol); flagged.
- Backend tests for the two router changes were written together with the change rather than observed
  red first (both are additive filters).
- `docs/api/API.md` fails `prettier --check` on main already; not reformatted here to keep the diff
  reviewable.
- Harness gotchas (same-URL hash reload, stale Electron partition) were recorded in session memory,
  not in the repo.
- Suite runs: (filled in below after the full API suite.)
