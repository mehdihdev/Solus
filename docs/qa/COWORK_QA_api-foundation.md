# COWORK_QA_api-foundation.md — SOLUSDEV-3 Phase 1 Foundation API

QA test plan for the Solus core API Phase 1 slice (API.md §8 Phase 1). Written to be
self-sufficient: you need a terminal with this repo checked out and nothing else. There is no
UI yet — all flows are exercised over HTTP (curl or Postman).

## Setup (required state)

1. From the repo root: `uv sync --all-packages` (installs Python 3.12 + deps automatically).
2. Create the dev database and start the server — copy both commands from
   `docs/api/API-implementation.md` §1 (schema bootstrap + uvicorn run). Server listens on
   `http://localhost:8000`.
3. Mint TWO dev JWTs using the snippet in API-implementation.md §1:
   - **ALICE**: `sub=11111111-1111-1111-1111-111111111111`, `email=alice@example.com`
   - **BOB**: `sub=22222222-2222-2222-2222-222222222222`, `email=bob@example.com`
     Export them as `$ALICE` and `$BOB`. All requests below use
     `-H "Authorization: Bearer $ALICE"` unless stated.
4. No accounts exist beforehand — the first authenticated call creates them (that is itself
   under test).

Conventions to check on EVERY response: success bodies are `{"data": ...}`; errors are
`{"error": {"code", "message", "details"}}`; all routes except `/healthz`/`/readyz` carry
`X-RateLimit-*` headers.

## Flow 1 — Probes & version (no auth)

- [ ] 1.1 `GET /healthz` → 200 `{"data":{"status":"ok"}}`
- [ ] 1.2 `GET /readyz` → 200, `checks.database == "ok"`, redis/queue `"not_configured"`
- [ ] 1.3 `GET /api/v1/version` → 200 with `version` and `build_sha`; `X-RateLimit-Limit: 120` header present

## Flow 2 — First login auto-provisioning

- [ ] 2.1 `GET /api/v1/users/me` (ALICE) → 200; user has `email=alice@example.com`; exactly one team named "Personal" with `role=owner`, `is_personal=true`, `plan_status=trial`, `trial_ends_at` ≈ 30 days out
- [ ] 2.2 Repeat 2.1 → same user `id` (no duplicate provisioning)
- [ ] 2.3 `GET /api/v1/users/me` with no header → 401 `unauthorized`
- [ ] 2.4 Same with `Authorization: Bearer garbage` → 401
- [ ] 2.5 Mint an EXPIRED token (negative `timedelta`) → 401

## Flow 3 — Profile & settings

- [ ] 3.1 `PATCH /users/me` `{"name":"Alice Liddell"}` → 200, name updated; persists on re-GET
- [ ] 3.2 `PATCH /users/me` `{"email":"x@y.z"}` → 422 (unknown field rejected)
- [ ] 3.3 `GET /users/me/settings` → 200 `{"sol_mode":"guide"}` (default)
- [ ] 3.4 `PATCH /users/me/settings` `{"sol_mode":"expert"}` → 200; re-GET shows expert
- [ ] 3.5 `PATCH /users/me/settings` `{"sol_mode":"yolo"}` → 422

## Flow 4 — Teams CRUD & isolation

- [ ] 4.1 `POST /api/v1/teams` `{"name":"Mars Rover Lab"}` → 201; `role=owner`, `member_count=1`, `is_personal=false`
- [ ] 4.2 `GET /api/v1/teams` → 200; lists Personal + Mars Rover Lab with roles
- [ ] 4.3 `GET /api/v1/teams/{id}` → 200 detail
- [ ] 4.4 **Isolation:** provision BOB (`GET /users/me` with $BOB), then as BOB: `GET /teams/{alice_team_id}`, `/members`, `/invites`, `/activity`, `/projects` → ALL 404 (not 403 — no existence leak)
- [ ] 4.5 `PATCH /teams/{id}` `{"name":"Renamed"}` as owner → 200
- [ ] 4.6 `DELETE /teams/{id}` without `?confirm=true` → 400 `confirmation_required`
- [ ] 4.7 `DELETE /teams/{personal_team_id}?confirm=true` → 409 `personal_team_undeletable`

## Flow 5 — Invites & the individual→team upgrade

- [ ] 5.1 As ALICE on Mars Rover Lab: `POST /teams/{id}/invites` `{"email":"bob@example.com","role":"member"}` → 201; response INCLUDES `token`
- [ ] 5.2 `GET /teams/{id}/invites` → 200; pending invite listed WITHOUT `token`
- [ ] 5.3 Duplicate invite (same email) → 409 `invite_pending`
- [ ] 5.4 Invite with `"role":"owner"` → 422
- [ ] 5.5 As BOB: `POST /api/v1/invites/{token}/accept` → 200 `{team_id, role}`; `GET /teams` as BOB now lists the team
- [ ] 5.6 Re-accept same token → 409 `invite_already_accepted`
- [ ] 5.7 Invite `carol@example.com`, then accept with BOB's token → 403 (email mismatch)
- [ ] 5.8 Revoke carol's invite (`DELETE /teams/{id}/invites/{invite_id}`) → 204; accepting it afterwards → 409 `invite_revoked`
- [ ] 5.9 **Upgrade path:** invite anyone onto ALICE's "Personal" team → 201; `GET /teams/{personal_id}` now shows `is_personal=false`

## Flow 6 — Members & roles

- [ ] 6.1 `GET /teams/{id}/members` → 200; alice owner + bob member
- [ ] 6.2 As BOB (member): `PATCH /members/{alice_id}` → 403; `POST /invites` → 403
- [ ] 6.3 As ALICE: `PATCH /members/{bob_id}` `{"role":"admin"}` → 200
- [ ] 6.4 As BOB (now admin): `PATCH /members/{bob_id}` `{"role":"owner"}` → 403 (only owners grant ownership)
- [ ] 6.5 As ALICE: demote herself (`{"role":"member"}`) while sole owner → 409 `last_owner`
- [ ] 6.6 As BOB: `DELETE /members/{bob_id}` (self-leave) → 204; members list shrinks
- [ ] 6.7 As ALICE alone: `DELETE /members/{alice_id}` → 409 `last_owner`

## Flow 7 — Projects

- [ ] 7.1 `POST /teams/{id}/projects` `{"name":"Rover MK2","description":"Six-wheel autonomous rover"}` → 201
- [ ] 7.2 `GET /projects/{id}` → 200; includes `stats: {entities: 0, relations: 0}` and `sources: []`
- [ ] 7.3 `PATCH /projects/{id}` `{"description":"updated"}` → 200
- [ ] 7.4 Re-invite BOB as `viewer`; as BOB: `POST /teams/{id}/projects` → 403
- [ ] 7.5 As a non-member (fresh third token): GET/PATCH/DELETE on the project → 404
- [ ] 7.6 `DELETE /projects/{id}` without confirm → 400; as viewer with confirm → 403; as ALICE with `?confirm=true` → 204; re-GET → 404

## Flow 8 — Jobs (seeded; no producer endpoints yet)

Seed a job with the snippet in API-implementation.md §6 (uses the project/team ids from Flow 7).

- [ ] 8.1 `GET /api/v1/jobs/{job_id}` → 200; `status=queued`, `progress=0`
- [ ] 8.2 `GET /projects/{id}/jobs?kind=sync` → 200, contains the job; `?kind=bogus` → 422
- [ ] 8.3 `POST /jobs/{job_id}/cancel` → 200 `status=cancelled` with `finished_at`
- [ ] 8.4 Cancel again → 409 `job_not_cancellable`
- [ ] 8.5 As BOB (if not on the team): all three routes → 404

## Flow 9 — Activity feed

- [ ] 9.1 `GET /teams/{id}/activity` → 200; newest-first; includes `team.created`, `invite.created`, `invite.accepted`, `project.created`, `member.role_changed`, `job.cancelled` from earlier flows
- [ ] 9.2 `?type=project.created` filter → only that type
- [ ] 9.3 `?actor={bob_id}` → only bob's actions
- [ ] 9.4 `?limit=2` → 2 rows + `meta.has_next=true` + `next_cursor`; following the cursor returns the remainder without duplicates

## Flow 10 — Notifications

Seed 3 notifications for ALICE (same pattern as the job seed; model `Notification`).

- [ ] 10.1 `GET /users/me/notifications?limit=2` → 2 rows, `has_next=true`; cursor walk reaches all 3
- [ ] 10.2 `POST /users/me/notifications/{id}/read` → 200 with `read_at`
- [ ] 10.3 As BOB, mark ALICE's notification read → 404
- [ ] 10.4 `POST /users/me/notifications/read-all` → 200 with remaining count; list shows all read
- [ ] 10.5 `?cursor=%%%bogus` → 400 `invalid_cursor`

## Flow 11 — Account deletion edge cases

- [ ] 11.1 As ALICE while sole owner of a shared team (with BOB on it): `DELETE /users/me` → 409 `ownership_transfer_required` with team id in `details`
- [ ] 11.2 Promote BOB to owner, retry → 204
- [ ] 11.3 Re-auth as ALICE → fresh account (new user id, new Personal team)

## Flow 12 — Rate limiting

Restart the server with `SOLUS_RATE_LIMIT_PER_MINUTE=3`.

- [ ] 12.1 4th request inside a minute → 429 `rate_limited` with `Retry-After`
- [ ] 12.2 `X-RateLimit-Remaining` decrements across the first 3 responses
- [ ] 12.3 `/healthz` never 429s

## Cross-feature interactions

- [ ] C.1 Deleting a team removes its projects and jobs (seed a job, delete team, `GET /jobs/{id}` → 404)
- [ ] C.2 Invite acceptance is visible in BOTH `GET /teams` (BOB) and the team activity feed (ALICE)
- [ ] C.3 Data-collection consent gate: with default consent (off), no rows appear in `data_events` table after any flow; flipping `data_collection_consent=true` in the DB and creating a team adds a `team.created` event row (ADR-011)
