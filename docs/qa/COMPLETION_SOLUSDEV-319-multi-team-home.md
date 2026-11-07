# Completion report — SOLUSDEV-319: multi-team Home (design D)

**Branch:** `SOLUSDEV-319-kicad-embedded-symbol-compare` (shared with other sessions; local
commits only, nothing pushed). **Commits:** `ab00f40a`, `192490e8`, `16c30dea`, `8a4df4c2`,
`943783b4`, `2183d075` (and this report). **QA handoff:**
`docs/qa/COWORK_QA_solusdev319_multi_team_home.md`.

## What was built

- **Team rail** (replaces the Home sidebar): every team I belong to — my role, the team's size,
  the personal workspace last — with one-click switching, Create a team, Join with an invite
  code, the plan-limit line, and the **invitations waiting for me** with Accept / Decline.
- **Team overview** (Home's default pane): header with plan, size, avatars, a role-aware Invite
  and the team ⋯ menu; the projects as a table (name, repos, last change) opening the existing
  project pane with "← Back to <team>"; a members preview linking to Team & invites; "You in
  <team>"; managers' pending invites. The personal workspace shows a "Work with others" card.
- **Backend — invitations to me:** `GET /api/v1/users/me/invites`,
  `POST …/{invite_id}/accept`, `POST …/{invite_id}/decline` (new `declined` invite status and
  `invite.declined` notification, migration `a31900000002`). The accept logic is shared with the
  token route (`join_via_invite`).

## Governing docs

- `docs/api/API.md` §2.1 (three rows) and `docs/api/API-implementation.md` §4 "Invitations to
  me" — amended first (tier-1, ADR-032).
- `docs/wireflows/home.md` "Layout: team rail + team overview (SOLUSDEV-319, multi-team Home,
  design D)" — amended; the concept B sidebar is marked superseded.
- ADR-009 (auth, email verification), ADR-025 (personal team stays solo), ADR-032 (plan limit,
  governance), ADR-016 (SOL mode stays per user).

## Decisions taken in chat

- Ticket: stay on SOLUSDEV-319. Base layout: design D, made multi-team.
- Per-project domain owner columns: **dropped**. Backend scope: **invitations to me only** (no
  "needs you" badges, member domains, or moving projects between teams).
- New routes require a **verified email**; decline is a new **`declined`** status.
- Plan approved as presented (dropped: warnings, last seen, per-team SOL mode, season handover).
- Security review H1: **admin proof, fail closed** (below).

## Delegated-judgment decisions

- Team sizes come from `GET /teams/{id}` per team (no API change to `/users/me`).
- Clicking the active team returns to its overview; clicking a project name opens the project
  pane (never the workspace).
- Accepting an invitation switches to the joined team; a refusal is named in the rail.
- `TeamStrip` became `TeamMenu` (the ⋯ and the limit line); `HomeProjectList` was retired.

## Tests

- API: `tests/test_my_invites.py` (20: list filters, verified-email and admin proof, fail-closed
  outside dev, 404 for others' and GitHub invites, accept/decline, races, mixed-case email, no
  token in notifications), `tests/test_supabase_admin.py` (+2), `tests/test_invites.py` (token
  route now matches the claim's email; notification without the token). The team/invite/auth/
  account suites were rerun after the fixes: 721 passed.
- Desktop: `TeamRail` (9), `TeamOverview` (8), `TeamProjectsTable` (5), `TeamMenu` (6),
  `teamLabels` (5), `useMyInvites` (7), `useTeamSizes` (6), `resources.myInvites` (6),
  `HomeScreen` (50). Full desktop suite green before the Phase 4 fixes (6548); the touched files
  green after.
- Live (dev:all on a clone of the dev DB, `solus_dev319`): rail with sizes, switching, team and
  personal overviews, project pane and back, Decline (status `declined`), Accept (joined as
  Admin, landed on the team). Fixed during the live check: sizes missing under StrictMode,
  "as an Admin", "All 1 member".

## Phase 4 review outcomes

- **Code review:** APPROVE. MEDIUM — `useTeamSizes` could re-request teams: fixed (ask once per
  team). LOW — a soft-deleted team in `_mine`: fixed.
- **Security review:**
  - **H1** — the verified-email gate relied on a claim Supabase rarely sends (absent = verified):
    fixed. `VerifiedEmail` now requires the auth user's `email_confirmed_at` (admin API) to
    name the token's email, and fails closed without a service-role key outside `app_env=dev`.
  - **M1** — the token route raced the by-id routes: fixed (row lock; lost race → `409`).
  - **M2** — the `team.invite` notification carried the token: removed.
  - **L4** — refusal logging: added for not-found.
  - **L1** (no route-specific rate limit), **L2** (team names as phishing text), **L3**
    (inviter name disclosure, intentional), **L5** (`getTeamDetail` path not encoded; ids are
    UUIDs), **L6** (migration f-string from constants): accepted, not changed.

## Open concerns and human gates

1. **Production needs `SUPABASE_SERVICE_ROLE_KEY`** (already a SOLUSDEV-82 deferred item):
   without it, invitations-to-me answer `403` outside dev. Joining by token still works.
2. **Migration heads:** `a31900000002` (this branch) and SOLUSDEV-322's `a31900000001` both
   revise `a32100000001`; whichever merges second needs an Alembic merge migration.
3. **Dev DB:** the shared dev DB is at `a31900000001` (322). This branch was run against a clone,
   `solus_dev319` (left in place, holding a seeded "Bracket Labs (QA)" team); drop it when done.
4. Push and MR (human only); run the Cowork QA pass.
5. `AssignPicker.tsx` lint errors are pre-existing (SOLUSDEV-216), not from this work.
