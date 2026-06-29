# API-implementation.md — Implemented Endpoints & Postman Examples

**Ticket:** SOLUSDEV-3 (branch `SOLUSDEV-3-api-foundation`)
**Scope:** [API.md](API.md) §8 **Phase 1 — Foundation**: §2.0 infra/meta, §2.1 users & settings
(api-keys excluded per the Phase 1 definition), §2.2 teams, §2.3 projects, §2.16 jobs — plus the
§1.4 conventions (envelope, errors, cursor pagination, rate-limit headers) and the §1.2/§1.3
centralized auth + team-scoping middleware.
**Code:** `packages/api` (FastAPI, Python 3.12). 94 tests passing; ruff + mypy strict clean.

All example responses below are **real captured output** from a locally running instance
(2026-06-13). UUIDs/timestamps will differ on your machine. Live secrets (invite tokens) are
replaced with `<placeholders>`.

---

## 1. Running the API locally for Postman testing

```bash
# from the repo root (uv required; Python 3.12 is fetched automatically)
uv sync --all-packages

# 1) create the dev database schema (SQLite for local testing; prod is Postgres/Alembic)
uv run python -c "
import asyncio
from solus_api.core.db import build_engine
from solus_api.models import Base
async def main():
    e = build_engine('sqlite+aiosqlite:///./solus-dev.db')
    async with e.begin() as c: await c.run_sync(Base.metadata.create_all)
    await e.dispose()
asyncio.run(main())"

# 2) run the server
SOLUS_SUPABASE_JWT_SECRET=dummy-dev-signing-value \
SOLUS_DATABASE_URL=sqlite+aiosqlite:///./solus-dev.db \
uv run uvicorn --factory solus_api.main:create_app --port 8000
```

Interactive OpenAPI docs: `http://localhost:8000/api/v1/docs`.

### Minting a dev JWT (ADR-009: clients send a Supabase Auth JWT)

There are no login endpoints — Solus validates Supabase JWTs (HS256, audience `authenticated`).
For Postman, mint a token signed with the same secret you started the server with:

```bash
uv run python -c "
import jwt, datetime
print(jwt.encode(
    {'sub': '11111111-1111-1111-1111-111111111111',   # any stable id = one user
     'email': 'alice@example.com',
     'aud': 'authenticated',
     'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=12)},
    'dummy-dev-signing-value', algorithm='HS256'))"
```

In Postman set a collection-level header: `Authorization: Bearer <token>`.
Mint a second token with a different `sub`/`email` to exercise multi-user flows
(invites, roles, cross-tenant 404s).

**First authenticated request auto-provisions** the user and their personal team (§1.3) — there
is no signup endpoint to call first.

### Conventions to verify on every response

| Check               | Expectation                                                                                                                            |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Success envelope    | `{"data": …}` plus `"meta"`/`"links"` when present                                                                                     |
| Error envelope      | `{"error": {"code", "message", "details"}}`                                                                                            |
| Rate-limit headers  | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` on everything except `/healthz`, `/readyz`; `429` adds `Retry-After` |
| Pagination          | `?cursor=&limit=` on notifications and activity; `meta.has_next`, `meta.next_cursor`                                                   |
| Scoping             | Non-member of a team/project → **404** (no existence leak); insufficient role → **403**                                                |
| Unknown body fields | **422** `validation_error` (schemas are `extra="forbid"`)                                                                              |

> SQLite note: `created_at`-style timestamps come back without a timezone suffix on the local
> SQLite setup (e.g. `2026-06-13T00:22:06.794639`). On PostgreSQL they are returned with offsets.
> All values are UTC either way.

---

## 2. §2.0 Infrastructure & meta (no auth)

### GET /healthz

```
GET http://localhost:8000/healthz
```

`200`

```json
{ "data": { "status": "ok" } }
```

### GET /readyz

```
GET http://localhost:8000/readyz
```

`200` (or `503` with `{"error": {"code": "unavailable", …}}` when the DB is unreachable)

```json
{
  "data": {
    "status": "ok",
    "checks": {
      "database": "ok",
      "redis": "not_configured",
      "queue": "not_configured"
    }
  }
}
```

Redis/ARQ report `not_configured` until the first job-producing endpoint lands (Phase 3).

### GET /api/v1/version

```
GET http://localhost:8000/api/v1/version
```

`200` — also a good place to see the rate-limit headers:

```
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 119
X-RateLimit-Reset: 1781310180
```

```json
{ "data": { "version": "0.1.0", "build_sha": "dev" } }
```

---

## 3. §2.1 Users & settings

### GET /api/v1/users/me

```
GET http://localhost:8000/api/v1/users/me
Authorization: Bearer {{token}}
```

`200` — first call creates the user + personal team:

```json
{
  "data": {
    "id": "019ebe5b-7aca-7770-acbb-c1897f15f46e",
    "email": "alice@example.com",
    "name": null,
    "avatar_url": null,
    "created_at": "2026-06-13T00:22:06.794639",
    "teams": [
      {
        "team_id": "019ebe5b-7ac9-7f08-a0ee-99662d44a2e4",
        "name": "Personal",
        "role": "owner",
        "is_personal": true,
        "plan_status": "trial",
        "trial_ends_at": "2026-07-13T00:22:06.793944Z"
      }
    ]
  }
}
```

No token → `401 {"error":{"code":"unauthorized","message":"Missing bearer token","details":[]}}`.

### PATCH /api/v1/users/me

```
PATCH http://localhost:8000/api/v1/users/me
Content-Type: application/json

{"name": "Alice Liddell"}
```

`200` — same shape as GET, with `"name": "Alice Liddell"`. Unknown fields (e.g. `"email"`) → `422`.

### DELETE /api/v1/users/me

`204` — deletes the account, personal team, and solo teams; leaves shared teams.
`409 ownership_transfer_required` (with the blocking `team_id`s in `details`) if the caller is
the **sole owner of a shared team** — transfer ownership first.

### GET /api/v1/users/me/settings

`200`

```json
{ "data": { "sol_mode": "guide" } }
```

### PATCH /api/v1/users/me/settings

```json
{ "sol_mode": "expert" }
```

`200 {"data":{"sol_mode":"expert"}}` — ADR-016: switchable any time. `"sol_mode":"yolo"` → `422`.

### GET /api/v1/users/me/notifications?limit=2

`200` — cursor-paginated, newest first:

```json
{
  "data": [
    {
      "id": "019ebe62-dcf1-769e-b971-98466525e19e",
      "type": "cross_domain_change",
      "title": "KiCad sync changed 3 entities your code depends on",
      "body": null,
      "payload": { "source": "kicad", "entities": 3 },
      "read_at": null,
      "created_at": "2026-06-13T00:30:10.673611"
    }
  ],
  "meta": { "limit": 2, "has_next": false, "next_cursor": null }
}
```

When `has_next` is true, pass `?cursor={{next_cursor}}` for the next page. A garbage cursor →
`400 invalid_cursor`. (Nothing produces notifications yet — cross-domain changes arrive in
Phase 2+. Seed rows directly in the DB to test, or just verify the empty list.)

### POST /api/v1/users/me/notifications/{notification_id}/read

`200` — the notification with `read_at` set. Another user's notification id → `404`.

### POST /api/v1/users/me/notifications/read-all

`200 {"data":{"updated": 3}}` (count of newly-read notifications).

---

## 4. §2.2 Teams, members, invites, activity

### POST /api/v1/teams

```json
{ "name": "Mars Rover Lab" }
```

`201`

```json
{
  "data": {
    "id": "019ebe61-ae57-75e5-bfa9-6ebc83df6b68",
    "name": "Mars Rover Lab",
    "is_personal": false,
    "plan_status": "trial",
    "created_at": "2026-06-13T00:28:53.207169",
    "member_count": 1,
    "role": "owner"
  }
}
```

### GET /api/v1/teams

`200` — every team the caller belongs to, with their role:

```json
{
  "data": [
    {
      "id": "019ebe5b-…a2e4",
      "name": "Personal",
      "is_personal": true,
      "plan_status": "trial",
      "role": "owner",
      "created_at": "2026-06-13T00:22:06.793944"
    },
    {
      "id": "019ebe61-…6b68",
      "name": "Mars Rover Lab",
      "is_personal": false,
      "plan_status": "trial",
      "role": "owner",
      "created_at": "2026-06-13T00:28:53.207169"
    }
  ]
}
```

### GET /api/v1/teams/{team_id}

`200` — detail incl. `member_count` and the caller's `role`. **Non-member → `404`** (verify with
your second token: this is the cross-tenant isolation contract).

### PATCH /api/v1/teams/{team_id} — admin+

```json
{ "name": "Renamed Lab" }
```

`200`. As `member`/`viewer` → `403`.

### DELETE /api/v1/teams/{team_id}?confirm=true — owner only

- without `?confirm=true` → `400 confirmation_required`
- as admin (not owner) → `403`
- personal team → `409 personal_team_undeletable`
- owner + confirm → `204`

### GET /api/v1/teams/{team_id}/members

`200`

```json
{
  "data": [
    {
      "user_id": "019ebe5b-…f46e",
      "email": "alice@example.com",
      "name": null,
      "role": "owner",
      "joined_at": "2026-06-13T00:28:53.209266"
    },
    {
      "user_id": "019ebe61-…fee1",
      "email": "bob@example.com",
      "name": null,
      "role": "member",
      "joined_at": "2026-06-13T00:28:53.317529"
    }
  ]
}
```

### PATCH /api/v1/teams/{team_id}/members/{user_id} — admin+

```json
{ "role": "admin" }
```

`200` — the updated member. Rules to verify:

- granting/revoking `owner` requires an **owner** (admin attempting it → `403`)
- demoting the **last owner** → `409 last_owner`

### DELETE /api/v1/teams/{team_id}/members/{user_id}

`204`. Self-removal (leave) is allowed for any role; removing someone else requires admin;
removing an owner requires owner; last owner can't leave (`409 last_owner`).

### POST /api/v1/teams/{team_id}/invites — admin+

```json
{ "email": "bob@example.com", "role": "member" }
```

`201` — **the token is returned once, only here** (no email delivery this cycle — hand the token
to the invitee):

```json
{
  "data": {
    "id": "019ebe61-ae9e-776e-b01e-4a8f2af10bf5",
    "team_id": "019ebe61-ae57-75e5-bfa9-6ebc83df6b68",
    "email": "bob@example.com",
    "role": "member",
    "status": "pending",
    "created_at": "2026-06-13T00:28:53.277831",
    "expires_at": "2026-06-20T00:28:53.277171",
    "token": "<urlsafe-invite-token-shown-once>"
  }
}
```

- `"role": "owner"` → `422` (ownership is granted only via the members route)
- duplicate pending invite → `409 invite_pending`; already a member → `409 already_member`
- **Inviting onto a personal team flips `is_personal` to `false`** — the ADR-015 individual→team
  upgrade entry point. Verify via `GET /teams/{team_id}` afterwards.

### GET /api/v1/teams/{team_id}/invites — admin+

`200` — pending invites, **without** the `token` field.

### DELETE /api/v1/teams/{team_id}/invites/{invite_id} — admin+

`204` — invite becomes `revoked`.

### POST /api/v1/invites/{invite_token}/accept — authed as invitee

`200`

```json
{
  "data": {
    "team_id": "019ebe61-ae57-75e5-bfa9-6ebc83df6b68",
    "role": "member"
  }
}
```

- wrong email on the accepting account → `403`
- revoked → `409 invite_revoked` · already used → `409 invite_already_accepted` · expired (7-day TTL) → `410 invite_expired`

### GET /api/v1/teams/{team_id}/activity?limit=3&type=&domain=&actor=

`200` — newest first, cursor-paginated, filterable. Emitted by team/project/member/invite/job
actions in this phase:

```json
{
  "data": [
    {
      "id": "019ebe61-ef4f-7a52-af6b-868be6055f42",
      "type": "project.created",
      "domain": null,
      "actor_id": "019ebe5b-7aca-7770-acbb-c1897f15f46e",
      "project_id": "019ebe61-ef4e-72e1-8726-5905455db85a",
      "payload": { "name": "Rover MK2" },
      "created_at": "2026-06-13T00:29:09.838579"
    },
    {
      "id": "019ebe61-aec4-788c-8af6-fcb4700c0ad2",
      "type": "invite.accepted",
      "domain": null,
      "actor_id": "019ebe61-ae8f-708c-928d-a645f433fee1",
      "project_id": null,
      "payload": { "email": "bob@example.com" },
      "created_at": "2026-06-13T00:28:53.316699"
    },
    {
      "id": "019ebe61-ae9d-7e63-bb0b-7261b101af15",
      "type": "invite.created",
      "domain": null,
      "actor_id": "019ebe5b-7aca-7770-acbb-c1897f15f46e",
      "project_id": null,
      "payload": { "email": "bob@example.com", "role": "member" },
      "created_at": "2026-06-13T00:28:53.277321"
    }
  ],
  "meta": {
    "limit": 3,
    "has_next": true,
    "next_cursor": "WyIyMDI2LTA2LTEzVDAwOjI4OjUzLjI3NzMyMSIsICIwMTllYmU2MS1hZTlkLTdlNjMtYmIwYi03MjYxYjEwMWFmMTUiXQ"
  }
}
```

---

## 5. §2.3 Projects

### POST /api/v1/teams/{team_id}/projects — member+ (viewer → 403)

```json
{ "name": "Rover MK2", "description": "Six-wheel autonomous rover" }
```

`201`

```json
{
  "data": {
    "id": "019ebe61-ef4e-72e1-8726-5905455db85a",
    "team_id": "019ebe61-ae57-75e5-bfa9-6ebc83df6b68",
    "name": "Rover MK2",
    "description": "Six-wheel autonomous rover",
    "created_at": "2026-06-13T00:29:09.838027",
    "updated_at": "2026-06-13T00:29:09.838028"
  }
}
```

### GET /api/v1/teams/{team_id}/projects

`200` — list, newest first.

### GET /api/v1/projects/{project_id}

`200` — detail adds the connected-source/graph summaries (empty until Phases 2–3 populate them):

```json
{
  "data": {
    "id": "019ebe61-ef4e-72e1-8726-5905455db85a",
    "team_id": "019ebe61-ae57-75e5-bfa9-6ebc83df6b68",
    "name": "Rover MK2",
    "description": "Six-wheel autonomous rover",
    "created_at": "2026-06-13T00:29:09.838027",
    "updated_at": "2026-06-13T00:29:09.838028",
    "stats": { "entities": 0, "relations": 0 },
    "sources": []
  }
}
```

**Cross-tenant check:** with a token for a user not on the team, GET/PATCH/DELETE all → `404`.

### PATCH /api/v1/projects/{project_id} — member+

```json
{ "description": "Six-wheel autonomous rover, mk2 chassis" }
```

`200` — updated detail.

### DELETE /api/v1/projects/{project_id}?confirm=true — admin+

Without confirm → `400 confirmation_required`; as member → `403`; admin + confirm → `204`.

---

## 6. §2.16 Jobs

No Phase 1 endpoint **creates** jobs (sync/check/proving arrive in Phases 3–4 and return
`202 + job_id` here), so to test now, seed a row directly:

```bash
uv run python -c "
import asyncio, uuid
from sqlalchemy.ext.asyncio import async_sessionmaker
from solus_api.core.db import build_engine
from solus_api.models import Job, JobKind
async def main():
    e = build_engine('sqlite+aiosqlite:///./solus-dev.db')
    async with async_sessionmaker(e, expire_on_commit=False)() as s:
        j = Job(project_id=uuid.UUID('<PROJECT_ID>'), team_id=uuid.UUID('<TEAM_ID>'), kind=JobKind.SYNC)
        s.add(j); await s.commit(); print(j.id)
    await e.dispose()
asyncio.run(main())"
```

### GET /api/v1/jobs/{job_id}

`200`

```json
{
  "data": {
    "id": "019ebe62-dcf0-7c41-935a-9b0b764d610d",
    "project_id": "019ebe61-ef4e-72e1-8726-5905455db85a",
    "kind": "sync",
    "status": "queued",
    "progress": 0,
    "result_ref": null,
    "error": null,
    "created_at": "2026-06-13T00:30:10.672473",
    "updated_at": "2026-06-13T00:30:10.672476",
    "finished_at": null
  }
}
```

Other team's job → `404`.

### GET /api/v1/projects/{project_id}/jobs?kind=sync&status=queued

`200` — list, filterable by `kind` (`sync|check_run|proving|fingerprint_scan|sim_rebuild`) and
`status` (`queued|running|succeeded|failed|cancelled`). Invalid values → `422`.

### POST /api/v1/jobs/{job_id}/cancel

`200` — job with `"status": "cancelled"` and `finished_at` set.
Cancelling a finished job → `409 job_not_cancellable` (`"Job is already cancelled"`).

---

## 7. Rate limiting (§1.4 interim)

Default 120 req/min per token (per client IP when unauthenticated), set via
`SOLUS_RATE_LIMIT_PER_MINUTE`. To see a `429` in Postman, restart the server with
`SOLUS_RATE_LIMIT_PER_MINUTE=3` and send 4 requests:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Rate limit exceeded",
    "details": []
  }
}
```

with `Retry-After: <seconds>`. `/healthz` and `/readyz` are exempt. This is a per-process
limiter; the Redis-backed ADR-019 budget system replaces it in Phase 5 with the same headers.

---

## 8. Error code catalogue (Phase 1)

| HTTP | `error.code`                                                                                                                                                                     | Where                                                                  |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| 400  | `confirmation_required`                                                                                                                                                          | team/project DELETE without `?confirm=true`                            |
| 400  | `invalid_cursor`                                                                                                                                                                 | malformed pagination cursor                                            |
| 401  | `unauthorized`                                                                                                                                                                   | missing/invalid/expired JWT, wrong audience                            |
| 403  | `forbidden`                                                                                                                                                                      | insufficient role; invite email mismatch; non-owner touching ownership |
| 404  | `not_found`                                                                                                                                                                      | unknown id **or** resource outside the caller's teams                  |
| 409  | `already_member`, `invite_pending`, `invite_revoked`, `invite_already_accepted`, `last_owner`, `personal_team_undeletable`, `ownership_transfer_required`, `job_not_cancellable` | state conflicts                                                        |
| 410  | `invite_expired`                                                                                                                                                                 | accepting an expired invite                                            |
| 422  | `validation_error`                                                                                                                                                               | schema violations, unknown fields, invalid enum values                 |
| 429  | `rate_limited`                                                                                                                                                                   | limiter window exceeded                                                |
| 503  | `unavailable`                                                                                                                                                                    | `/readyz` with dependencies down                                       |

---

## 9. Not implemented in this slice (and why)

| Surface                                                                  | Status                                                                                                                                                                    |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| §2.1 API keys (`/users/me/api-keys`)                                     | Excluded from Phase 1 by API.md §8 (rides with the MCP decision)                                                                                                          |
| §2.4–§2.15, WS/SSE                                                       | Later phases (graph, sources, checkers, agent, bench, …)                                                                                                                  |
| `POST /graph/query`, billing provider routes, MCP server, presence topic | **[DEFERRED]** per API.md §7.2 — blocked on human decisions                                                                                                               |
| Alembic migrations                                                       | Schema is final-for-phase but baseline migration generation needs a running Postgres; tracked for the integration-environment ticket. Tests/dev use `metadata.create_all` |
| ARQ/Redis worker wiring                                                  | No job-producing endpoint exists yet (first one: §2.5 sync in Phase 3); §2.16 read/cancel surface is live                                                                 |
| Data-collection consent endpoints (§2.13)                                | Phase 6; until then `data_collection_consent` defaults to **false** and ADR-011 events are not recorded                                                                   |

### Implementation decisions made under delegated judgment (CLAUDE.md §10)

- **404 vs 403:** non-membership returns 404 (anti-enumeration); insufficient role within a team returns 403.
- **Personal team:** named "Personal", undeletable, auto-created on first auth; inviting onto it flips it to a regular team (ADR-015 upgrade entry point).
- **Invite tokens** are returned once in the creation response since no email delivery exists this cycle.
- **Deletion confirmations** use `?confirm=true` (API.md says "confirmation required" without specifying a mechanism).
- **Trial state:** `plan_status: "trial"`, `trial_ends_at = team.created_at + 30d` — placeholder until ADR-017 billing lands (Phase 5).
