# Cowork QA — SOLUSDEV-319: multi-team Home (team rail + team overview)

You have the running Solus desktop app (dev build) and this file. Nothing else is assumed. Tick
**Pass** or **Fail** per step and note what you saw in the result table at the end. Words in
`code` are exact on-screen text unless marked "e.g.".

**What changed.** Home's left side is now a **team rail**: every team you belong to (your role
and the team's size), your personal workspace last, one click to switch, **Create a team**,
**Join with an invite code**, and the **invitations** waiting for you (Accept / Decline). The
right side opens on the active team's **overview**: a header (plan, size, Invite, ⋯ menu), the
team's projects as a table, a members preview, "You in <team>", and pending invites for owners
and admins. Your personal workspace shows your projects and a "Work with others" card instead of
a roster.

---

## 0. Setup

- [ ] The API database is migrated to revision **`a31900000002`** (invite decline):
      `cd packages/api && uv run alembic upgrade head`, then `uv run alembic current` shows
      `a31900000002`. A database already at `a31900000001` (SOLUSDEV-322's bench views) cannot
      run this branch: use a fresh database or one migrated from main.
- [ ] Start everything: from the repo root `REMOTE_DEBUGGING_PORT=9333 pnpm dev:all`.
- [ ] **User M** — signed in, email **verified**. Owner of team **T1** (≥ 2 projects, at least
      one with a GitHub source) and a member of team **T2** (role Member).
- [ ] **User O** — a second account that owns team **T3** (User M is not on T3).
- [ ] **User V** — a second account whose email is **not verified** (or a token with
      `email_verified: false`).

---

## 1. Team rail

1. [ ] Open Home (first rail icon). Expected: the greeting, `YOUR TEAMS · N`, and one row per
       team: T1 `Owner · <n> members`, T2 `Member · <n> members`, and last `Personal
workspace` / `Only you`. Sizes may appear a moment after the names.
2. [ ] The active team's row has the accent border. Click T2. Expected: T2's row takes the
       border; the right side shows T2's overview (heading T2).
3. [ ] Click `Personal workspace`. Expected: the overview heading reads `Personal workspace`,
       the mono line `ONLY YOU`, no members section, and a `WORK WITH OTHERS` card.
4. [ ] `Create a team` opens the New team dialog; `Join with an invite code` opens the Join
       dialog. Cancel both.
5. [ ] On a plan at its collaborative-team limit the rail shows `2 of 2 collaborative teams on
your plan · your personal team never counts` and an Upgrade button (→ Billing).

## 2. Team overview

1. [ ] With T1 active (you are Owner): the header shows T1, e.g. `TRIAL · 3 MEMBERS`, up to four
       avatars and `+N`, `Invite to T1`, and `⋯`.
2. [ ] `PROJECTS · N` table: each live project's name (and description), its repo under
       SOURCES (e.g. `owner/repo` with a GitHub mark, `—` when none), and LAST CHANGE (e.g.
       `synced GitHub · 2h ago`, or `No recent activity`). Archived projects are not in the
       table but under `ARCHIVED (N)`.
3. [ ] Click a project's name. Expected: the project pane (CURRENT PROJECT, tabs Overview /
       Sources / .solus / Activity) with `← Back to T1` above it; nothing opens in the
       workspace. Click Back: the overview returns.
4. [ ] `New project` creates a project in T1 and opens it in the workspace.
5. [ ] A row's `⋯` offers Edit details / Archive / Delete (Delete only for owners).
6. [ ] `MEMBERS · N` lists up to six members (avatar, name, email, role). `All N members and
invites` (singular `member` for one) opens the Team & invites view.
7. [ ] `YOU IN T1`: Role `Owner`, Joined (e.g. `3mo ago`), Projects = the live project count.
8. [ ] Invite someone (`Invite to T1` → an email). Expected: `PENDING INVITES · 1` with that
       email, `Member`, `sent now`, and `Manage invites` (→ Team & invites).
9. [ ] Switch to T2 (Member). Expected: no Invite button; instead `You're a Member here · ask an
owner or admin to invite`; no PENDING INVITES card; the ⋯ offers Join team, New team,
       Leave team (no Rename/Delete).
10. [ ] As a Viewer on some team: no `New project` button and no row `⋯`.

## 3. Invitations to me

1. [ ] As User O, invite User M's email to T3 as **Admin**, and (in a second team or after
       revoking) once more as **Member** if you want two rows.
2. [ ] As User M, open Home (reload if it was open). Expected: an `INVITATIONS · N` card in the
       rail: `T3`, `<O's name> invited you as an Admin`, `Accept`, `Decline`.
3. [ ] Click `Decline` on one. Expected: the row disappears. As User O: the invite is gone from
       T3's pending invites and O has a notification `<M's email> declined your invite`.
4. [ ] Click `Accept` on another. Expected: Home switches to T3's overview; T3 appears in
       YOUR TEAMS with `Admin · <n> members`; the card disappears when nothing is left.
5. [ ] **Closed meanwhile:** with a pending invite listed, revoke it as User O, then click
       Accept as User M. Expected: `That invitation is no longer open.` and the row leaves.
6. [ ] **Plan limit:** with User M at their collaborative-team limit, Accept. Expected: the
       limit message with Upgrade; the invitation stays.
7. [ ] **Unverified email:** as User V with a pending invite, open Home. Expected: the card
       reads `Verify your email to see the invitations sent to it.` and lists nothing.
8. [ ] **Someone else's invite:** as User M call
       `POST /api/v1/users/me/invites/<an invite id for another email>/accept` (e.g. via the
       renderer's DevTools console with M's token). Expected: `404`.

## 4. Existing flows still work

- [ ] Join a team by pasting a token (`Join with an invite code`), as before.
- [ ] Team ⋯ → Rename / Leave / Delete with their existing confirmations and gating.
- [ ] ACCOUNT → `Connected accounts` and `Team & invites` still swap the pane.
- [ ] A project's `Add additional sources` opens Connected accounts with `← Back to <project>`.
- [ ] Team names, member names, emails and project names containing `<b>x</b>` render as text.

## Result

| Flow                          | Pass/Fail | Notes |
| ----------------------------- | --------- | ----- |
| 1 Team rail                   |           |       |
| 2 Team overview               |           |       |
| 3.2 Invitations listed        |           |       |
| 3.3 Decline                   |           |       |
| 3.4 Accept                    |           |       |
| 3.5 Closed meanwhile          |           |       |
| 3.6 Plan limit                |           |       |
| 3.7 Unverified email          |           |       |
| 3.8 Someone else's invite 404 |           |       |
| 4 Existing flows              |           |       |
