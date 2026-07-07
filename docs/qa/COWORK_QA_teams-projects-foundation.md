# COWORK QA — Teams + Projects Foundation (SOLUSDEV-81 / SOLUSDEV-84 / SOLUSDEV-87)

End-to-end test plan for the multi-tenant Teams layer (org model, roles,
invitations, scoping), the Projects backend (CRUD, archive, dashboard,
notifications), and the Settings backend (user/team preferences, consent).
Written to be run against a running app with only this file.

## Required setup state

- [ ] API running (`pnpm dev:api`) with a database (`make db-up` or SQLite via
      `SOLUS_DATABASE_URL`); desktop app running (`pnpm dev:desktop`).
- [ ] Two real user accounts (User A, User B) you can sign in as — Supabase auth
      configured (`VITE_SUPABASE_*`, `SOLUS_SUPABASE_JWT_SECRET`).
- [ ] For API-level checks, a bearer token for each user (or use the app UI where
      the flow exists).

## Flow 1 — Team lifecycle and roles (SOLUSDEV-81)

1. As A: `POST /api/v1/teams {"name": "QA Robotics"}`. **Expected:** 201; A is
   `owner`; `GET /api/v1/teams` lists it.
2. As A: invite B — `POST /api/v1/teams/{tid}/invites {"email": "<B email>", "role": "member"}`.
   **Expected:** 201 with a one-time `token`; listing invites again does NOT show
   the token.
3. **Notification path:** as B (already registered): `GET /api/v1/users/me/notifications`.
   **Expected:** a `team.invite` notification whose payload carries the team id
   and the invite token.
4. As B: `POST /api/v1/invites/{token}/accept`. **Expected:** 200; B is a member.
   As A: **Expected:** an `invite.accepted` notification.
5. As A: change B's role `PATCH /api/v1/teams/{tid}/members/{b_id} {"role": "admin"}`.
   **Expected:** 200. As B (admin, not owner): try to grant yourself owner.
   **Expected:** 403 (only owners touch ownership).
6. **Last-owner guard:** as A (sole owner): `DELETE /api/v1/teams/{tid}/members/{a_id}`
   and `PATCH` A to `member`. **Expected:** both 409 `last_owner`.
7. Remove B: `DELETE .../members/{b_id}` as A. **Expected:** 204.

## Flow 2 — Scoping enforcement (SOLUSDEV-81, security-critical)

8. As B (no longer a member): `GET /api/v1/teams/{tid}`, `GET .../members`,
   `GET .../projects`. **Expected:** **404** on all — the API deliberately
   returns 404 (not the ticket's 403) so team existence never leaks. This is the
   documented convention (API.md §1.3); flag if you see 403 or data.
9. As B: `POST /api/v1/invites/{someone-elses-token}/accept` with a token issued
   to a different email. **Expected:** 403.

## Flow 3 — Projects CRUD + dashboard (SOLUSDEV-84)

10. As A: create two projects under the team. **Expected:** 201 each; other team
    members receive a `project.created` notification; the creator does not.
11. `GET /api/v1/teams/{tid}/projects`. **Expected:** each row has
    `stats: {entities, sources}` summary counts (zeros for fresh projects).
12. Connect a source and sync it (see the SOLUSDEV-103 QA file), then re-check:
    **Expected:** the list row's `stats.entities`/`stats.sources` reflect the
    sync; `GET /api/v1/projects/{pid}` detail shows real
    `stats: {entities, relations}` and a `sources` array (no `secret_ref`/token
    fields anywhere).
13. Update: `PATCH /api/v1/projects/{pid} {"description": "..."}`. **Expected:**
    200 with detail payload.

## Flow 4 — Archive / unarchive (SOLUSDEV-84)

14. `POST /api/v1/projects/{pid}/archive`. **Expected:** 200; `archived_at` set.
15. `GET /api/v1/teams/{tid}/projects`. **Expected:** archived project absent.
    With `?include_archived=true`: present. Detail by id still works.
16. `POST /api/v1/projects/{pid}/unarchive`. **Expected:** 200; back in the list.
17. As a `viewer` member: archive attempt. **Expected:** 403.

## Flow 5 — Delete cleans the graph (SOLUSDEV-84)

18. On a project with a synced source: `DELETE /api/v1/projects/{pid}?confirm=true`
    as admin. **Expected:** 204; entities/relations/sources/syncs for that
    project are gone; the stored connector credential is deleted from the secret
    store; other projects' graphs untouched.

## Flow 6 — Settings persistence (SOLUSDEV-87)

19. As A: `GET /api/v1/users/me/settings`. **Expected:**
    `{sol_mode: "guide", data_collection_consent: false}` (defaults).
20. `PATCH /api/v1/users/me/settings {"sol_mode": "expert", "data_collection_consent": true}`.
    **Expected:** 200 echoing both; a fresh GET returns the same (persisted).
21. **Consent gate:** with consent off, meaningful actions record no data-events;
    after opting in they do (internal `data_events` table — verify via DB or
    ask engineering). Opt back out (`false`) and confirm recording stops.
22. Team settings: `GET /api/v1/teams/{tid}`. **Expected:** detail includes
    `settings: {notify_project_created: true}`.
23. As A (owner): `PATCH /api/v1/teams/{tid} {"settings": {"notify_project_created": false}}`.
    **Expected:** 200; persists on re-read. Create a project — **Expected:** no
    `project.created` notification reaches other members. Flip back to `true`
    and confirm notifications resume.
24. As a `member` (not admin): same PATCH. **Expected:** 403.
25. `PATCH /api/v1/teams/{tid} {"settings": {"bogus_key": 1}}`. **Expected:** 422.

## Edge cases & failure paths

- [ ] Invite an email that's already a member → 409 `already_member`.
- [ ] Duplicate pending invite → 409 `invite_pending`.
- [ ] Accept an expired invite → 410; a revoked one → 409.
- [ ] Invite to a not-yet-registered email → no notification created (they get
      the token out-of-band); accept works after signup.
- [ ] Inviting onto a personal team flips `is_personal` to false (upgrade path).
- [ ] Archive twice → idempotent 200, `archived_at` unchanged semantics.
- [ ] Delete without `?confirm=true` → 400.

## Cross-tenant isolation (must pass)

- [ ] As B (non-member): archive/unarchive/delete A's project → 404.
- [ ] As B: `GET /api/v1/projects/{a_pid}` → 404; list A's team projects → 404.
- [ ] B's notifications never contain A's team/project events.

## Sign-off

- [ ] Flows 1–6 pass.
- [ ] All edge cases behave as described.
- [ ] All isolation checks return 404/403 as specified.
