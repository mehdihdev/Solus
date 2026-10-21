# API-implementation.md — Implemented Endpoints & Postman Examples

**Ticket:** SOLUSDEV-3 (branch `SOLUSDEV-3-api-foundation`)
**Scope:** [API.md](API.md) §8 **Phase 1 — Foundation**: §2.0 infra/meta, §2.1 users & settings
(api-keys excluded per the Phase 1 definition), §2.2 teams, §2.3 projects, §2.16 jobs — plus the
§1.4 conventions (envelope, errors, cursor pagination, rate-limit headers) and the §1.2/§1.3
centralized auth + team-scoping middleware.
**Code:** `packages/api` (FastAPI, Python 3.12). 94 tests passing; ruff + mypy strict clean.

All example responses below are **real captured output** from a locally running instance
(2026-06-13; the `/readyz` note and the settings/subscription examples were re-captured
2026-07-19, SOLUSDEV-152). UUIDs/timestamps will differ on your machine. Live secrets
(invite tokens) are replaced with `<placeholders>`.

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

`redis` and `queue` report **config-level truth, not a live ping** (SOLUSDEV-152):
both say `configured` when `SOLUS_REDIS_URL` is set and `not_configured` otherwise
(the ARQ queue rides on the same DSN, ADR-005). A missing queue is an accepted
degraded state — sync dispatch falls back to in-process background tasks and
scheduled work does not run — and never fails readiness; only an unreachable
database returns the `503`.

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
{
  "data": {
    "sol_mode": "guide",
    "sol_custom_instruction": null,
    "data_collection_consent": false,
    "onboarding_step": "about"
  }
}
```

`data_collection_consent` is the ADR-011 opt-in/out switch (default **false**; see §9 —
events are recorded only while consented). `onboarding_step`
(`about|connect|build|done`) is the FND-08 resume point. `sol_custom_instruction`
(SOLUSDEV-233) is the user's standing preference note for SOL — 500 chars max; it
reaches the prompt only as a fenced data block, never as instruction text (§7).

### PATCH /api/v1/users/me/settings

```json
{ "sol_mode": "expert" }
```

`200` — same shape as GET with the change applied. All fields are patchable
independently; ADR-016: `sol_mode` switchable any time. `"sol_mode":"yolo"` → `422`.
`sol_custom_instruction` is tri-state: absent = unchanged, `null` = clear, a string
sets it (`> 500` chars → `422`). The `settings.updated` data event records only
`"set"`/`"cleared"` for this field — never the text.

### GET /api/v1/users/me/usage

`200` — the always-visible meter (ADR-018, SOLUSDEV-233). Credit-denominated
(ADR-018 rejected raw token metering):

```json
{
  "data": {
    "used": 941,
    "allowance": 10000,
    "balance": 9059,
    "cycle_start": "2026-08-10T00:00:00+00:00",
    "cycle_end": "2026-09-10T00:00:00+00:00"
  }
}
```

`used` sums USAGE ledger debits inside the current cycle — the monthly anniversary
window anchored at the subscription's creation (day clamped in short months,
Stripe-style), UTC calendar month before a subscription exists. `allowance` is the
plan's starting-credit grant (`settings.plan_credit_grants`; `null` = no
plan-derived denominator — clients show the balance alone).

### GET /api/v1/users/me/subscription

`200` — auto-provisioned on first auth (ADR-032: every user starts a 14-day `basic` trial;
`limits` is what enforcement reads, `null` = unlimited):

```json
{
  "data": {
    "id": "019f7a25-76a1-74b4-a6ee-c557ea1cf15f",
    "created_at": "2026-07-19T11:31:43.393859Z",
    "updated_at": "2026-07-19T11:31:43.393860Z",
    "deleted_at": null,
    "user_id": "019f7a25-769c-7888-80df-a7dc58fd7761",
    "plan": "basic",
    "status": "trialing",
    "limits": { "max_teams": 2, "max_projects": 3, "max_integrations": 4 },
    "expires_at": "2026-08-02T11:31:43.390521Z",
    "stripe_customer_id": null,
    "stripe_subscription_id": null,
    "seat_count": null,
    "custom_price_per_seat": null
  }
}
```

### PATCH /api/v1/users/me/subscription

```json
{ "plan": "pro" }
```

`200` — picks/changes the plan during onboarding: (re)starts a 14-day trial of the chosen
plan with that plan's default limits (ADR-032). `plan` ∈ `basic|pro|enterprise`; anything
else → `422`. No Stripe call is made — real billing/checkout stays deferred (§9).

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
    "next_cursor": "WyIyMDI2LTA2LTEzVDAwOjI4OjUzLjI3NzMyMSIsICIwMTllYmU2MS1hZTlkLTdlNjMtYmIwYi03MjYxYjEwMWFmMTUiXQ",
    "total": 7
  }
}
```

`meta.total` (SOLUSDEV-233) is the count of ALL activity rows matching the team scope and any
`type`/`domain`/`actor` filters — independent of `limit` and `cursor`, so it stays stable while
paging. Clients use it for "View all activity (N)" affordances. The count scan is capped at
1000 rows (`TOTAL_COUNT_CAP`, §7 cost control): a feed past the cap reports exactly 1000.

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

Per token (per client IP when unauthenticated), fixed 60 s window, per process. Reads and writes
are **separate buckets** (SOLUSDEV-234):

| Budget                                      | Setting                                  | Default  |
| ------------------------------------------- | ---------------------------------------- | -------- |
| Reads (`GET`/`HEAD`/`OPTIONS`)              | `SOLUS_RATE_LIMIT_PER_MINUTE`            | **1200** |
| Writes (everything else)                    | `SOLUS_WRITE_RATE_LIMIT_PER_MINUTE`      | **120**  |
| `POST /orchestration/classify` (own bucket) | `SOLUS_CLASSIFY_RATE_LIMIT_PER_MINUTE`   | 600      |
| `POST /panel/pair/start` (own bucket)       | `SOLUS_PANEL_PAIR_RATE_LIMIT_PER_MINUTE` | 120      |

The read budget is sized for one desktop session's steady-state polling (the Live Bench widget
is 2 req/s, the bridge/sources/extensions/widget pollers ~1 req/s, and a workspace load pages the
graph in 500-row bursts) with a ~10x margin, so it bounds a runaway loop without a healthy client
429ing itself. The write budget stays at 120 because it is the interim burst bound on
model-calling POSTs until the ADR-019 Redis frequency cap is live; raising reads never raises it.
This is a runaway-client guard, not an abuse control (keyed per bearer token per process).

To see a `429` in Postman, restart the server with `SOLUS_RATE_LIMIT_PER_MINUTE=3` and send 4
GETs:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Rate limit exceeded",
    "details": []
  }
}
```

with `Retry-After: <seconds>`. `/healthz` and `/readyz` are exempt; CORS preflights sit outside the
limiter (never counted, and a `429` carries CORS headers). The Redis-backed ADR-019 budget system
replaces this in Phase 5 with the same headers.

Client contract (desktop `lib/api/client.ts`, SOLUSDEV-234), both guards scoped to the bearer
token so a sign-out/sign-in shares nothing with the previous account:

- Concurrent identical plain GETs share one in-flight request. In-flight reads are dropped when
  any mutation completes, so a refetch after a write is always fresh.
- A GET `429` whose `X-RateLimit-Remaining` is `0` (or absent) pauses further GETs client-side
  until `Retry-After` elapses — 5 s when the header is missing or malformed, 60 s at most — and
  they fail fast with the same `rate_limited` error instead of hammering the window. A `429` from
  a route-level limiter (extension bundles, artifact content) arrives with headroom in that
  header and pauses nothing. Mutations are never coalesced or held back.

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

| Surface                                                                                                                                                                                                                            | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| §2.1 API keys (`/users/me/api-keys`)                                                                                                                                                                                               | Excluded from Phase 1 by API.md §8 (rides with the MCP decision)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| §2.4–§2.15, WS/SSE                                                                                                                                                                                                                 | Later phases (graph, sources, checkers, agent, bench, …)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `POST /graph/query`, MCP server, presence topic                                                                                                                                                                                    | **[DEFERRED]** per API.md §7.2 — blocked on human decisions                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Stripe billing routes (`POST /api/v1/webhooks/stripe`, `POST /api/v1/billing/checkout-session`, `POST /api/v1/billing/portal-session`, `GET /api/v1/billing/packs`, `GET /api/v1/users/me/credits`, `GET /api/v1/billing/summary`) | **Built** — webhook (SOLUSDEV-83) + the checkout/portal/packs/credits routes (SOLUSDEV-83 follow-up) lift the §7.2 deferral by human decision. **SOLUSDEV-236 (Built 2026-10-21):** `GET /api/v1/billing/summary` (new), `POST /api/v1/billing/portal-session` flow body, trial expiry (`402 trial_expired`), `billing_interval`/`current_period_end` and the hourly subscription reconciliation cron (§10). Locked by ADR-024 (2026-10-19 amendment); the summary shape was approved in-chat 2026-10-19. Full "select plan → Stripe Checkout → webhook confirms" flow. See §10. The trial-only `PATCH /users/me/subscription` (no Stripe call — ADR-032) remains live for onboarding, see §3. Enterprise stays contact-sales. |
| Alembic migrations                                                                                                                                                                                                                 | Schema is final-for-phase but baseline migration generation needs a running Postgres; tracked for the integration-environment ticket. Tests/dev use `metadata.create_all`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ARQ/Redis worker wiring                                                                                                                                                                                                            | No job-producing endpoint exists yet (first one: §2.5 sync in Phase 3); §2.16 read/cancel surface is live                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Data-collection consent (§2.13)                                                                                                                                                                                                    | **Live** — the ADR-011 opt-in/out ships as `data_collection_consent` on `GET`/`PATCH /users/me/settings` (see §3), not as dedicated §2.13 routes. Default remains **false**; events are recorded only while consented.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

### Implementation decisions made under delegated judgment (CLAUDE.md §10)

- **404 vs 403:** non-membership returns 404 (anti-enumeration); insufficient role within a team returns 403.
- **Personal team:** named "Personal", undeletable, auto-created on first auth; inviting onto it flips it to a regular team (ADR-015 upgrade entry point).
- **Invite tokens** are returned once in the creation response since no email delivery exists this cycle.
- **Deletion confirmations** use `?confirm=true` (API.md says "confirmation required" without specifying a mechanism).
- **Trial state:** `plan_status: "trial"`, `trial_ends_at = team.created_at + 30d` — placeholder until ADR-017 billing lands (Phase 5).

---

## 10. Billing money-path (SOLUSDEV-83 / SOLUS-FND-03)

Hardened money-moving surface. The webhook route was authorized by a human
decision that lifted the §7.2 billing-route deferral for it (SOLUSDEV-83); the
**customer-facing checkout + portal routes below** (SOLUSDEV-83 follow-up) were
authorized by a subsequent human decision to complete the "select plan →
Stripe Checkout → webhook confirms → plan/credits active" flow. Enterprise stays
contact-sales (ADR-023). The Stripe **secret API key** is not a setting — it is
read from the SecretStore under `stripe_api_key` (like the LLM provider keys),
never from config, env, responses, or logs.

### POST /api/v1/webhooks/stripe — Stripe events (unauthenticated; signed)

No bearer token (Stripe can't send one). Trust comes from the **Stripe signature**:
the raw body is size-bounded, then `stripe.Webhook.construct_event` verifies the
`Stripe-Signature` HMAC against `SOLUS_STRIPE_WEBHOOK_SECRET`.

- Missing/invalid signature → `400 invalid_signature`. Webhook secret unset →
  `503 billing_unconfigured`. Oversized body → `413 payload_too_large`.
- `200 {"data": {"processed": true|false}}` — `false` means the event id was
  already processed (deduped via `processed_stripe_events`).
- Idempotent + out-of-order safe: subscription state is last-write-wins by the
  event's `created` time (`subscriptions.stripe_event_at`); credit-pack grants
  are keyed by the Stripe event id.
- Handled events: `customer.subscription.created/updated/deleted` (upsert local
  subscription status), `checkout.session.completed` (link Stripe customer in
  subscription mode; grant a configured credit pack in payment mode — pack →
  credits map from `SOLUS_STRIPE_PACK_CREDITS`), `invoice.payment_failed`
  (mark `past_due` + `payment.failed` notification). Other types are ignored.
- Plan starting credits (ADR-023/024, amended 2026-08-08): when a subscription
  event leaves a plan live (active/trialing), its one-time starting grant
  (`SOLUS_PLAN_CREDIT_GRANTS`, default basic 2,500 / pro 10,000) is applied as a
  `plan_grant` ledger entry, idempotent per (user, plan) — renewals/replays never
  re-grant; an upgrade grants the new plan's amount once.
- Cancellation lifecycle (SOLUSDEV-102 follow-up): subscription events carry
  Stripe's `cancel_at` — stored on `subscriptions.cancel_at` (exposed via
  `GET /users/me/subscription`; drives the client's "your plan ends on X" bar)
  and cleared on resume. When a live subscription actually ends (deletion at
  term end, or an updated event landing `canceled`), limits clamp to the BASIC
  tier and `cancel_at` clears. Notifications: `subscription.canceled` (with the
  end date), `subscription.resumed`, `subscription.ended` — same-state
  replays/renewals stay silent.

### POST /api/v1/billing/checkout-session — start Stripe Checkout (authenticated)

Body: `{ "kind": "subscription", "plan": "basic|pro", "interval": "month|year" }`
or `{ "kind": "pack", "price_id": "<configured pack price id>" }`.

- `200 {"data": {"url": "<hosted Stripe Checkout URL>"}}`. The renderer opens the
  URL in the system browser; entitlement is applied only by the webhook once
  Stripe confirms payment — never from this request.
- Subscription mode uses the plan+interval → Price map (`SOLUS_STRIPE_PLAN_PRICES`)
  and applies `SOLUS_STRIPE_TRIAL_DAYS` as `trial_period_days`. Pack mode uses a
  `price_id` present in `SOLUS_STRIPE_PACK_CREDITS`.
- Reuses the caller's `stripe_customer_id` or creates one (persisted on their
  subscription); `client_reference_id` + `metadata.solus_user_id` carry identity
  to the webhook, `metadata.price_id` lets the webhook grant the right pack.
- Errors: `enterprise` or unknown plan → `400 plan_not_checkoutable`; missing/bad
  interval → `400 invalid_interval`; unknown pack → `400 invalid_pack`; plan with
  no configured Price → `503 billing_unconfigured`; no Stripe key → `503
billing_unconfigured`; Stripe API error → `502 billing_provider_error`.

### POST /api/v1/billing/portal-session — Stripe billing portal (authenticated)

- `200 {"data": {"url": "<Stripe billing-portal URL>"}}` — manage payment method,
  cancel, or switch plan. Requires an existing `stripe_customer_id` (a prior
  checkout): none → `409 no_billing_customer`. No key → `503`, Stripe error → `502`.
- **Optional body (SOLUSDEV-236, built):** `{"flow": "update" | "cancel"}`.
  Strict schema (`extra=forbid`): unknown fields or an unknown `flow` → `422 validation_error`.
  No body = the general portal (today's behaviour).
  - The subscription id is ALWAYS derived server-side from the caller's own row. The
    body never carries a customer or subscription id.
  - `flow` given and no live Stripe subscription (`stripe_subscription_id` set and
    `status` in `active | trialing | past_due`) → `409 no_active_subscription`.
  - `flow: "cancel"` while `cancel_at` is already set → `409 cancel_already_scheduled`.
  - `flow` maps to a Stripe portal deep link (`flow_data`): `update` →
    `subscription_update`, `cancel` → `subscription_cancel`, both bound to the
    caller's subscription id.
  - Every session passes a code-managed portal `configuration`: `subscription_update`
    enabled for the basic and pro prices (month and year); upgrades (Basic → Pro,
    month → year) charged prorated immediately; downgrades (lower amount or shorter
    interval) scheduled at period end; `subscription_cancel` at period end; payment
    method update; invoice history. The configuration definition lives in code.
    Both rules fit one configuration: `subscription_update.proration_behavior =
"always_invoice"` plus `schedule_at_period_end.conditions =
[decreasing_item_amount, shortening_interval]`.
  - Emits `billing.portal_session.created {flow: "general" | "update" | "cancel"}`.
  - Rate-limited (`429 rate_limited`). 10/min/user (its own limiter,
    `billing_portal_limiter`).
  - Stripe errors → `502 billing_provider_error` (unchanged).

### GET /api/v1/billing/summary — billing summary for the caller (authenticated, SOLUSDEV-236, built)

**Shape approved 2026-10-19 (in-chat, SOLUSDEV-236).** One read model for the Billing screen
(`docs/wireflows/billing.md`).

```json
{
  "data": {
    "plan": "basic",
    "status": "active",
    "billing_interval": "month",
    "current_period_end": "2026-11-19T00:00:00+00:00",
    "cancel_at": null,
    "trial": { "state": "none", "ends_at": null },
    "next_invoice": {
      "amount_cents": 2500,
      "currency": "usd",
      "date": "2026-11-19T00:00:00+00:00"
    },
    "payment_method": { "brand": "visa", "last4": "4242" },
    "prices": [
      {
        "plan": "basic",
        "interval": "month",
        "amount_cents": 2500,
        "currency": "usd"
      },
      {
        "plan": "basic",
        "interval": "year",
        "amount_cents": 20000,
        "currency": "usd"
      },
      {
        "plan": "pro",
        "interval": "month",
        "amount_cents": 3500,
        "currency": "usd"
      },
      {
        "plan": "pro",
        "interval": "year",
        "amount_cents": 30000,
        "currency": "usd"
      }
    ],
    "packs_available": true,
    "stripe_status": "ok"
  }
}
```

- `plan`, `status`, `billing_interval`, `current_period_end`, `cancel_at`: mirrored
  from the subscription row (no Stripe call).
- `trial.state`, derived at read time from the row:
  - `active`: a local trial with `now ≤ expires_at`, or a Stripe subscription in `trialing`.
  - `expired`: a local trial (`stripe_subscription_id` NULL, `status` trialing) with `now > expires_at`.
  - `none`: otherwise.
  - `ends_at` = `expires_at` when the state is not `none`, else null.
- `next_invoice`: the upcoming Stripe invoice (`amount_cents`, `currency`, `date`).
  Null when `stripe_status` is not `ok`, there is no Stripe subscription, `cancel_at`
  is set, or `status` is not `active`/`trialing`.
- `payment_method`: the customer's default card, **brand and last four digits only**.
  Null when unavailable or no card is on file.
- `prices`: the self-serve Price list (basic and pro, month and year) from
  `SOLUS_STRIPE_PLAN_PRICES`, with amounts from Stripe. Global cache ~10 min, not per
  user. Null when `stripe_status` is not `ok`. Enterprise is not listed (contact sales).
- `packs_available`: `SOLUS_STRIPE_PACK_CREDITS` is non-empty. No Stripe call.
- `stripe_status`:
  - `ok`: every Stripe call this response needs succeeded (or none was needed).
  - `unavailable`: a Stripe call errored or timed out. Budget: 3 s per call.
  - `unconfigured`: no Stripe key (or no price mapping for the self-serve plans).
- Degraded mode returns `200`. Stripe errors never produce a `502` or `503` here.
  Stripe-derived fields (`next_invoice`, `payment_method`, `prices`) are `null`.
- Never returned: `cus_…`, `sub_…`, `pm_…`, `in_…` ids, or card data beyond brand and last four.
- Rate-limited: `429 rate_limited`, 30/min/user (`billing_summary_limiter`). Per-user Stripe reads
  (next invoice, card) are cached ~60 s (10 s when degraded); local fields are recomputed
  from the row on every request; prices share one global ~10 min cache.
- Errors: `401 unauthorized`; `404 not_found` if the caller has no subscription row (not expected after provisioning); `429 rate_limited`.
- Team-scoping N/A: the summary is the caller's own subscription (ADR-023/025).
- Emits no data-collection event (read-only).

### GET /api/v1/billing/packs — purchasable credit packs (authenticated)

- `200 {"data": {"packs": [{"price_id": "...", "credits": 1000, "usd": 10}, ...]}}`
  from `SOLUS_STRIPE_PACK_CREDITS`, sorted by credits. `usd` is the whole-dollar
  display price from `SOLUS_STRIPE_PACK_USD` (`null` when unmapped) — display
  only; the charged amount is always the Stripe Price. Price ids are not secrets;
  this keeps the UI from hard-coding environment-specific Stripe ids.

### GET /api/v1/users/me/credits — credit balance (authenticated)

- `200 {"data": {"user_id": "...", "balance": <int>}}`. Always answerable — `0`
  before any ledger row exists. Team-scoping N/A: credits are per-user (ADR-024).

### Webhook plan derivation (SOLUSDEV-83 follow-up)

On `customer.subscription.created/updated`, the local `plan` + `limits` are now
set from the purchased Stripe **Price** (reverse `SOLUS_STRIPE_PLAN_PRICES`
lookup), so entitlement always reflects what was actually paid for — never a
client-supplied plan name. An unmapped price leaves the plan unchanged.

### Subscription state derivation, reconciliation and trial length (SOLUSDEV-236, built)

- **Shared derivation.** The webhook (`_apply_subscription`) and the reconciliation cron
  write `billing_interval`, `current_period_end` and `expires_at` through one pure
  function, so the two paths cannot disagree. `billing_interval` comes from the applied
  Price's `recurring.interval` (`month` | `year`). `current_period_end` is the raw Stripe
  value. `expires_at` follows the rules in `docs/schemas/subscriptions.md` §expires_at
  (Stripe `trial_end` while trialing, else `current_period_end`). Writes stay idempotent
  and last-write-wins by `stripe_event_at`, as today.
- **Reconciliation cron (hourly, ARQ).** Converges Stripe-linked rows
  (`stripe_subscription_id` set). A row whose subscription returns Stripe
  `resource_missing` is canceled through the term-end path (`_apply_term_end`: limits
  clamp to BASIC, `cancel_at` clears, `subscription.ended` notice). A circuit breaker
  aborts the run (nothing is written, `billing.reconcile.aborted` is logged) when more than
  5 % of the batch (minimum 10) report missing in one sweep. Local-only rows are never touched. Each changed
  row emits `billing.subscription.reconciled {changed_fields, from_status, to_status,
cause}` (consent-gated, ids and codes only). Not the same job as the credit-debit
  reconciler (`billing/reconciliation.py`).
- **`SubscriptionRead` (`GET /users/me/subscription`) gains** `billing_interval`
  (`month` | `year` | null), `current_period_end` (timestamptz | null) and
  `trial_expired` (bool, same predicate as the gate: local trial past `expires_at`). Staff
  fields stay hidden.
- **Trial length is one value.** `SOLUS_STRIPE_TRIAL_DAYS` (default 14) is the single source
  for the signup trial and for Checkout's `trial_period_days` (ADR-024). The current
  signup constant (`deps.TRIAL_DAYS`, 14) and the unused `trial_days` setting (30) are
  to be consolidated into it.
- **Team summary `trial_ends_at`** is derived from the caller's own subscription
  (`expires_at` for a trial), not `team.created_at + settings.trial_days`. Applies to
  the team summary in §2.2 (outside this section; follow-up).

### Credit money-path (internal, no public routes)

- **Trial cost cap:** first login grants a bounded credit allowance
  (`SOLUS_TRIAL_CREDIT_GRANT`, provisional). The pre-flight gate
  (`cost.has_sufficient_credits`) blocks paid model operations when the balance
  can't cover the estimate — at balance 0 this is the free-trial hard cap.
- **Deduction:** `cost.track_cost` (post-call) debits the actual credits
  atomically and idempotently (per-call key). Per ADR-024 W0-03 it never fails
  the user's already-paid result; a failed debit is recorded to
  `pending_credit_debits` and reconciled by an ARQ cron worker.
- **Conversion + prices are PROVISIONAL** (`orchestration/models.yaml`:
  `margin_multiplier`, `credits_per_dollar`; `SOLUS_STRIPE_PACK_CREDITS`) —
  calibrate post-pilot (ADR-024).
- **Trial expiry block (SOLUSDEV-236, ADR-024 amendment 2026-10-19; built):** the
  pre-flight gate (`orchestration/gates.py` `assert_can_spend`) refuses a metered call with
  **`402 trial_expired`** when the caller's subscription is a local trial
  (`stripe_subscription_id` IS NULL, `status` trialing) and `expires_at` < now. The
  refusal is the same family as `trial_cap_reached` and `insufficient_credits` (both 402
  per the gate's docstring). The error carries `details: {ends_at}` and no other data.
  Order of checks: development-allowlist bypass, then the trial-expiry check, then the
  existing trial-cap and credit checks.
  - **Purchased credits still unlock spend.** An expired trial may spend only when the
    ledger holds at least one `purchase` entry and the cached balance covers one credit
    (ADR-024 2026-10-19). A purchase with an empty balance is still `trial_expired`.
  - Projects, data, sync and unmetered features are never blocked by this rule.
  - Stripe-backed trials (`stripe_subscription_id` set) are never blocked by it.
  - Each block emits `orchestration.blocked {reason: "trial_expired", ends_at}`
    (consent-gated, best effort, like the other block reasons).
  - **Not in this doc:** the `POST /api/v1/events` closed set and the §8 error-code
    catalogue must list `trial_expired` once it is built (both are outside this amendment).
  - The SOL message and sourcing routes that already surface `insufficient_credits` (402)
    surface `trial_expired` through the same error path. Their route docs need the new
    code in a follow-up.

---

## 11. SOL chat (SOLUSDEV-135 / SOLUS-SYS-01) — LIVE; route-plan blessing still pending

The SOL agent surface was listed as a later phase (§9, "§2.4–§2.15, WS/SSE"). SOLUSDEV-135
introduced the following **project-scoped, owner-private** routes as the systems-side of the
reasoning↔systems seam, and has since merged to main, so the routes below are live. Formal
blessing of the route plan in the authoritative API design is still pending — flagged in that
ticket's completion report for approval.

All routes are under `/api/v1/projects/{project_id}/sol` and resolve through `ProjectCtx`
(tenant isolation). A conversation is owned by its creator: only `(project_id, created_by)`
reaches it, so another tenant OR another teammate in the same project gets `404`. Writes
require the `member` role; reads need only a resolvable project.

| Method | Path                                    | Purpose                                                                                 | Success |
| ------ | --------------------------------------- | --------------------------------------------------------------------------------------- | ------- |
| GET    | `/sol/tools`                            | List the W0-04 tool descriptors SOL may invoke (fixed by code)                          | `200`   |
| POST   | `/sol/conversations`                    | Create a conversation (`{title?}`)                                                      | `201`   |
| GET    | `/sol/conversations`                    | List the caller's conversations (cursor-paginated)                                      | `200`   |
| GET    | `/sol/conversations/{id}`               | Get one owned conversation                                                              | `200`   |
| DELETE | `/sol/conversations/{id}`               | Soft-delete an owned conversation                                                       | `204`   |
| GET    | `/sol/conversations/{id}/turns`         | List a conversation's turns (cursor-paginated)                                          | `200`   |
| GET    | `/sol/conversations/{id}/confirmations` | Restore this owner's active, unexpired approval cards                                   | `200`   |
| PATCH  | `/sol/conversations/{id}`               | Rename an owned conversation (`{title}`, non-blank, trimmed — SOLUSDEV-233)             | `200`   |
| POST   | `/sol/conversations/{id}/messages`      | Append a user message and **stream** SOL's reply (SSE)                                  | `200`   |
| POST   | `/sol/confirmations/{id}`               | Decide a parked destructive action (`{decision: approve\|reject}` — no `amend`, CTR-03) | `200`   |

SOLX-04: `GET /sol/tools` additionally lists `solus.list_integrations`, `solus.connect_integration` (destructive — parks through the CTR-03 gate), and `solus.verify_integration` when the connector registry is wired. Connecting from chat is discovery → confirm → verify; OAuth providers are pointed at the in-app flow (credentials never pass through tool arguments).

**Approval restoration (SOLUSDEV-261).** The confirmations GET requires the same
owner-private conversation access as history, with explicit project, team, user,
and conversation scoping. It returns an envelope containing an ordered array of
`{confirmation_id, tool, summary, preview, expires_at}` for pending rows whose
30-minute expiry is still in the future. Arguments are never returned. Decided
and expired actions are not actionable cards; their existing history remains.
Reading never extends expiry, rebuilds a preview, approves, or executes anything.
Repeated proposals with identical tool and canonical JSON arguments reuse the
same active row and stored preview within the same owner's conversation. A
conversation row lock serializes concurrent park checks and inserts. This does
not reuse decided/expired rows or treat chat text as approval.

**Streaming turn (`POST …/messages`).** Body: `{content, action_mode?, force_confirmation?, mentions?, preferences?}` where `action_mode` is
`"guide"` (default — SOL explains and points, never mutates) or `"do"` (SOL may operate tools;
destructive calls still park through the CTR-03 gate). SOLX-01: the mode is explicit per request,
logged per action (`agent.tool_invoked`), and enforced structurally in the dispatch closure.
SOLUSDEV-168: `mentions` is a list of graph entity ids the user pointed at with the composer's
`@` — integration-agnostic, because an entity id addresses any node in the graph at any depth.
They lead the neighbourhood's anchors (`reason.plan_query`), capped at `MAX_ANCHORS` (8) both
here and again in the planner, since that cap is what bounds the traversal's DB work. Ids are
NOT existence-checked: `load_neighborhood` is project-scoped, so one from another team yields
an empty neighbourhood rather than a distinguishable error — answering differently for "exists
elsewhere" than for "does not exist" would be a cross-tenant existence oracle.
Returns `text/event-stream`. The user turn is persisted
(and `sol.message` logged) before streaming; assistant/tool turns are persisted as the stream
completes. SSE `event:` names and their `data` payloads:

SOLUSDEV-244 / HOME H3: `preferences` is the desktop's copy of the user's own
`~/.solus/preferences.json` (ADR-034 amendment 2026-09-06) — `{schema_version, updatedAt?,
freeText, codeStyle, mechanical, electrical, documentation, unitsStandards}`, strict shape
(`422` on an unknown field), `freeText` ≤ 2 400 chars and each section ≤ 800 chars (`422`
over cap). The server keeps **no copy**: the transcript stores the message, never the
preferences. Non-empty sections reach the prompt only as one nonce-fenced
`kind=engineering_preferences` data block in the system prompt, under Solus-authored framing,
after the mode note and before the SOLUSDEV-233 styling note (`agent/prompt.py`); the framing
asks SOL to apply the conventions and to name the one that changed an answer, states that a
project's `.solus` conventions (reserved `kind=project_preferences`, empty for now) override them
and that they override shipped references (`kind=context_corpus`), and that they can never
change rules, tools, scope, or what counts as data. Absent or all-blank ⇒ no block.

- `token` — `{"text": "…"}` incremental reply delta
- `context_used` — `{"sections":[{"kind","citation","tokens"}],"truncated","dropped"}`
  (SOLUSDEV-233) the turn's context manifest, streamed once at turn start. Section
  TEXT never crosses the wire — kinds (`graph|telemetry|error|document`), verified
  citation tokens, and token weights only. Drives the client's "context in use" panel.
- `tool_call` — `{"call_id","tool","args"}` a proposed W0-04 tool invocation
- `tool_result` — the W0-04 `ToolResult` envelope (`{"call_id","ok","value"|"error"}`)
- `message` — `{"role":"assistant","content":"…","citations":["…"]}` the finished reply;
  `citations` is the SOL-02 structured provenance surface (verified by Solus code — renderers
  show it in a dedicated region, never linkified, display-capped, never parsed from prose)
- `error` — `{"code","message"}` a generic, author-safe failure (never a traceback, §7)
- `done` — `{"conversation_id","turn_id"}` terminal marker

The reasoning loop runs behind the `agent.runtime.AgentRunner` seam. This cycle ships a
deterministic, model-free `ScaffoldRunner` (mock-and-swap, like the systems test double) that proves
the plumbing end to end — lists tools, invokes the reference `get_entity` tool through the
per-request registry, pulls W0-07 graph context, and honors a bounded tool-call loop guard.
Model routing / credit metering (W0-03 `route()`/`track_cost`) remain MO-01 stubs, so no live
model call is made yet; per-team model-budget enforcement lands with MO-01.

### Bridge (SOLUSDEV-154 / SOLUS-BRG-02)

**`WS /api/v1/projects/{project_id}/bridge`** — the companion's dial-out channel. Project-scoped
per CLAUDE.md §7 ("WebSocket connections authenticate at connect time and are scoped to a team's
project"); one socket = one project scope.

- **Auth:** `Authorization: Bearer <Supabase access JWT>` on the upgrade request, verified by
  `decode_token`; scope derived server-side from DB memberships. Query-string tokens are never
  read. The bridge never provisions accounts. Non-member/unknown project → close `4404` (no
  existence leak — the same 404 posture as every project route).
- **Frames:** `{type, data}` JSON text messages per `docs/contracts/bridge-protocol.md`
  (`hello`/`hello_ack`/`tool_call`/`tool_result`/`status`/`ping`/`pong`/`error`).
- **Close codes:** `4400` protocol/version · `4401` auth/expiry · `4403` revoked mid-session ·
  `4404` non-member · `4409` superseded · `4413` oversize · `4429` rate/caps.
- **Config (`SOLUS_BRIDGE_*`):** `ALLOWLIST_ROOT` (default `integrations/mcp`) ·
  `CONTROL_FRAME_MAX_BYTES` 16384 · `TOOL_CALL_MAX_BYTES` 262144 · `TOOL_RESULT_MAX_BYTES`
  1048576 · `MSG_RATE_PER_SECOND` 20 · `MSG_BURST` 100 · `CONNECT_RATE_PER_MINUTE` 30 ·
  `MAX_INFLIGHT` 8 · `MAX_TEAM_SESSIONS` 10 · `IDLE_TIMEOUT_SECONDS` 60 ·
  `HELLO_TIMEOUT_SECONDS` 10 · `REVOCATION_POLL_SECONDS` 15.
- **Effect on SOL:** while a companion session is live, `GET /sol/tools` additionally lists the
  session's allowlist-validated `{server}.{tool}` descriptors; the SOL turn registry registers a
  `BridgeTool` per entry (scope fixed by Solus code at turn start).
- Implementation: `routers/bridge.py` + `solus_api/bridge/`; tests `tests/test_bridge.py` (WS
  protocol + red-team), `tests/test_bridge_e2e.py` (real companion round-trip).

---

## 12. Project artifacts (SOLUSDEV-100) — PLANNED, route plan in [artifacts.md](artifacts.md)

Tier-1 route-plan amendment (ADR-032; F1 decision, in-session human approval 2026-08-03) closing
the `docs/contracts/bridge-protocol.md` §10 "ArtifactRef upload path" hole: the HTTP surface a
companion uses to upload bulk MCP tool output (KiCad/EDA exports > the 1 MiB `tool_result` frame
cap) and the scope-enforced fetch routes for the W0-04 `artifacts` table. Documented before
implementation per the authority hierarchy (#3); the implementing task is T4c on the same ticket.

All routes resolve through `ProjectCtx` (non-member → `404`, no existence leak); upload requires
the `member` role.

| Method | Path                                                            | Purpose                                         | Success |
| ------ | --------------------------------------------------------------- | ----------------------------------------------- | ------- |
| POST   | `/api/v1/projects/{project_id}/artifacts`                       | Multipart upload; returns a W0-04 `ArtifactRef` | `201`   |
| GET    | `/api/v1/projects/{project_id}/artifacts/{artifact_id}`         | Artifact metadata (registry row)                | `200`   |
| GET    | `/api/v1/projects/{project_id}/artifacts/{artifact_id}/content` | The raw bytes                                   | `200`   |

Full plan — request/response shapes, `scope=PROJECT` default, TTL + one-shot consumption,
anti-forgery consumption rules, size caps (8 MiB), rate budgets, and the `ArtifactStore`
S3/local backends (presigned-S3 as the documented revisit path) — lives in
[artifacts.md](artifacts.md).

---

## 13. Graph subgraph extraction (SOLUSDEV-191 / SOLUS-WS-01) — LIVE

**`GET /api/v1/projects/{project_id}/graph`** — the focus-scope read. Planned in `API.md` §2.4
since SOLUSDEV-2; implemented here. One call returns everything a widget needs to re-scope when
the user selects an entity, so a focus change is a single bounded request rather than a reload.

| Param            | Type            | Default      | Notes                                                                                |
| ---------------- | --------------- | ------------ | ------------------------------------------------------------------------------------ |
| `root`           | UUID            | **required** | The focused entity. 404 if unknown or in another project.                            |
| `depth`          | int 0–2         | 1            | Hops to traverse. `422` beyond 2 (ADR-027 defers deep traversal).                    |
| `entity_types`   | csv, ≤32 values | all          | Filters which entities are reached _and_ traversed through. The root is always kept. |
| `relation_types` | csv, ≤32 values | all          | Filters which edges are followed and returned.                                       |
| `limit`          | int 1–500       | 200          | Max entities. When it bites, `truncated` is `true`.                                  |

**Response** — `{"data": {"entities": [...], "edges": [...], "truncated": false}}`. Entities and
edges use the same public keys as `/entities` and `/relations` (`type`, `source_key`,
`properties`, `from_entity_id`, `to_entity_id`), so the frontend has one entity type, not two.

- **Induced subgraph:** every returned edge has BOTH endpoints in `entities` — no dangling
  references, and edges _between_ neighbours are included (two parts wired to each other must not
  render as unrelated).
- **Undirected traversal:** focus asks what an entity relates to, not which way an edge points.
- **Bounded and honest:** `depth` and `limit` are capped by the route; `truncated` reports when a
  cap bit, because a silently capped subgraph reads as the whole picture.
- **Scoping:** `ProjectCtx` as every project route; non-member → 404, never 403 (no existence
  oracle). A malformed edge pointing at another project's entity resolves to nothing.
- Implementation: `routers/entities.py::get_subgraph` over `solus_api/graph/neighborhood.py`
  (`load_neighborhood`) — the SAME traversal a real `SolSystems.get_graph_context` adapts via
  `to_graph_context`, so the agent and the focused view can never disagree about the graph.
  Tests: `tests/test_neighborhood.py` (traversal), `tests/test_entities.py` (route + isolation).

---

## 14. Impact analysis (SOLUSDEV-197 / SOLUS-IMP-01) — PLANNED, engine LIVE

Tier-1 route-plan amendment (ADR-032) written with the IMP-01 engine, called out in its
completion report. The engine (`solus_api/impact/engine.py::compute_impact`) is implemented and
tested; the HTTP surface below is the plan the Impact widget's backend wiring implements when
LANE B mounts the widget against live data (it renders CTR-04 fixtures until then).

**`POST /api/v1/projects/{project_id}/impact`** — compute the impact of a proposed change.

Request body: `{"focus_id": "<entity uuid>", "change": [DiffRow, …], "depth": 0–2 (default 2)}`.
`change` reuses the action-gate `DiffRow` shape (CTR-03), exactly as `ImpactResult.change`
carries it.

Response — `{"data": ImpactResult}` per the CTR-04 contract (`docs/contracts/impact.md`):
`focus`, `change`, `computed_at`, `truncated`, `nodes[]` (each with `distance == len(path)`,
severity = worst consequence, path starting at the focus).

- **POST, not GET**: the request carries a change payload; the analysis is a computation over
  it, not an addressable resource. Nothing is persisted (v1).
- **Scoping:** `ProjectCtx` as every project route; non-member → 404, never 403. Unknown or
  cross-project `focus_id` → 404 (the engine refuses to resolve foreign entities).
- **Bounded:** depth capped at the traversal's `MAX_DEPTH` (2); `truncated` reported honestly.
  Consequence computation runs the checker adapter; when narration (IMP-02) calls the model
  gateway it is budget-metered per §7 — over-budget degrades to template rationale, never a 500.
- Rate limiting: expensive-endpoint class (per-user and per-team), same tier as agent routes.

---

## 15. Live Bench telemetry (SOLUSDEV-66 / SOLUS-LB-05) — LIVE

Tier-1 route-plan amendment (ADR-032), documented alongside implementation and called out in the
LANE H completion report. This is the first production wiring of the LNK-06 telemetry plumbing
(`TelemetryPlumbing`) and closes the "no bench route exists" gap flagged in Phase 0. Local bench
runners (sim connectors, serial/WS robot links — `livebench/`) PUSH LB-06 packet batches; the
Live Bench widget POLLS recent values, W0-07 summaries, and edge-observer events.

All routes resolve through `ProjectCtx` (non-member → `404`, no existence leak); ingest requires
the `member` role. Each packet decodes through the ratified LB-06 `from_wire` (§7 trust
boundary): hostile packets count as `rejected` and drop themselves, unresolved devices count as
`unresolved` — a batch never 500s on content. Buffer and event state are keyed by project id;
cross-tenant isolation is covered by `test_bench_router.py`.

| Method | Path                                                     | Purpose                                                      | Success |
| ------ | -------------------------------------------------------- | ------------------------------------------------------------ | ------- |
| POST   | `/api/v1/projects/{project_id}/bench/telemetry`          | Ingest ≤500 LB-06 wire packets + ≤100 observer events        | `200`   |
| GET    | `/api/v1/projects/{project_id}/bench/recent/{entity_id}` | Recent values for one entity (`RecentValuesView`)            | `200`   |
| GET    | `/api/v1/projects/{project_id}/bench/summary`            | W0-07 `TelemetrySummaryView` over a bounded window (≤3600s)  | `200`   |
| GET    | `/api/v1/projects/{project_id}/bench/events`             | Recent observer events (bounded per-project ring, ephemeral) | `200`   |

Deliberately poll/push REST for this cycle: the WS/SSE streaming upgrade stays on the §2.15
later-phases line, and `docs/contracts/sol-interface.md` §4 guarantees the windowed shapes carry
to continuous delivery without a contract change. Durable telemetry history stays out of scope
(LNK-06 decision: live ephemeral values only).

### Observed telemetry devices (SOLUSDEV-262 additive amendment)

`GET /api/v1/projects/{project_id}/bench/telemetry-devices` returns the standard
response envelope with `data: {device_ids: string[]}`. Central `ProjectCtx`
authorization applies (unauthenticated 401, non-member 404). Sorted, unique IDs
come only from valid packets actually ingested, including unresolved devices;
this creates neither a session nor serial ownership. The server uses monotonic
arrival time, never producer timestamps, and expires observations after 15 seconds.
The ephemeral index admits at most 128 devices per project and 256 projects;
new keys at capacity are ignored until expired entries are reclaimed. Existing
entries refresh while full. API restart clears this index. Live Bench merges
these IDs with session devices and uses the existing batched device-recent route.

## 15b. Bench sessions & local sources (SOLUSDEV-72) — LIVE

Tier-1 route-plan amendment (ADR-032), documented alongside implementation and called out in the
SOLUSDEV-72 completion report. Implements the session subset of §2.10 plus the sources /
device-recent amendment: the UI can now START a local connection — the gap `stream_live.py`
recorded ("no route exists yet") is closed, with the LB-05 isolation tests it demanded.

A session runs the provider's `LiveConnection` pump **in the API process** and tees every packet
into `TelemetryPlumbing` — the §15 ingest sink stays the ONE telemetry path. Providers load via
an optional runtime import of `livebench.local` (never a declared dependency; the package arrow
points livebench → solus-api): a server without livebench answers `GET /sources` with
`runner.available=false` and refuses session starts with `503 source_unavailable`. This is
honest for today's dev topology (API on the user's machine); a future companion-hosted runner
swaps in behind these same routes.

| Method | Path                                                             | Purpose                                                                                                                                                    | Success |
| ------ | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| GET    | `/api/v1/projects/{project_id}/bench/sources`                    | Honest machine inventory: simulators (available/not + reason), serial devices, runner state                                                                | `200`   |
| POST   | `/api/v1/projects/{project_id}/bench/sessions`                   | Start a session (`{mode, config}` discriminated on `config.provider`; member role)                                                                         | `201`   |
| GET    | `/api/v1/projects/{project_id}/bench/sessions`                   | List sessions, `?status=active\|ended&mode=sim\|real` (bounded ended ring)                                                                                 | `200`   |
| GET    | `/api/v1/projects/{project_id}/bench/sessions/{session_id}`      | Session detail: status, live link state, device_ids seen, counts, last window summary                                                                      | `200`   |
| POST   | `/api/v1/projects/{project_id}/bench/sessions/{session_id}/stop` | Stop (idempotent; `aclose` teardown flushes the pending window; member role)                                                                               | `200`   |
| GET    | `/api/v1/projects/{project_id}/bench/device-recent`              | `?device_id=…` (repeated, 1–16) `&limit=` — batched recent values for devices with NO graph entity yet (pre-RBT-05); one request covers every polled panel | `200`   |

Providers and their config (all bodies `extra="forbid"`): `mujoco` (inline MJCF ≤2 MB or the
built-in demo scene; realtime forced, bounded duration — a non-realtime run would busy-loop the
event loop), `gazebo` (bounded topic list, flag-shaped topics refused; pinned `gz` CLI),
`mcap-replay` (path confined under `Settings.bench_data_root`; unset root refuses MCAP outright),
`serial` (**bound by USB serial number**, resolved to `/dev/serial/by-id`; ambiguous or absent
serials refuse with candidates — `409 device_ambiguous` — unless an explicit still-enumerated
`confirmed_device_path` pick is supplied). Errors: `409 too_many_sessions` (per-project cap 4),
`404 device_not_found`, `503 source_unavailable`, `422` for config/path violations.

Session state is in-memory and project-keyed (BenchEventRing posture — lifecycle, not history;
no migration). Lifespan shutdown closes every pump/subprocess/port. Data events:
`bench.session_started` / `bench.session_stopped`.

Related (§2.5 amendment): `GET /api/v1/integrations/local-tools` lists vendor-run loopback MCP
servers from the ADR-031 catalog (Fusion today) for the desktop's generic `local-bridge` tile —
the next bridge-hosted tool is a backend catalog entry, zero frontend edits.

Isaac Sim stays a read-target (ADR-014): MCAP replay is the recorded path, and
`livebench/sim/isaac_direct.py` (run under Isaac's own python, stdlib-only, token via env) is the
ROS-free live path POSTing straight into §15's ingest route — zero new API surface.

---

## 16. Extensions & Store (SOLUSDEV-235) — PLANNED, route plan in [extensions.md](extensions.md)

Tier-1 route-plan amendment (ADR-032) written at the SOLUSDEV-235 Phase 2 plan (task EXT-00)
from the fixed decisions of that ticket's Phase 1 design review (ratified 2026-09-03, ADR-035 +
the ADR-034 amendment). It is the HTTP surface behind the Store (`docs/wireflows/store.md`): a
tenant-free catalog of approved extension versions, an open publish path (bundle via
`ArtifactStore`, manifest validated with the `extension-manifest` contract, review as an ARQ
job), per-project installs with pinned versions / validated settings / granted permissions, the
`storage.own` key-value store, per-user widget layouts, team policies, and `X-Solus-Extension`
attribution on the EXISTING §11 SOL turn route. Documented before implementation per the
authority hierarchy (#3); the implementing tasks are the EXT-xx tasks on the same ticket.

Catalog routes need only a signed-in user; project routes resolve through `ProjectCtx` with the
`member` floor (viewer → `403`, non-member → `404`); policy routes resolve through `TeamCtx`,
`owner` only. Everything is **Unmetered** (API.md §1.5 note).

| Method         | Path                                                            | Purpose                                                    | Success           |
| -------------- | --------------------------------------------------------------- | ---------------------------------------------------------- | ----------------- |
| GET            | `/api/v1/extensions`                                            | Catalog list (`?q=&cursor=&limit=`), approved only         | `200`             |
| GET            | `/api/v1/extensions/{slug}`                                     | Detail: manifest, asset URLs, publisher, verified          | `200`             |
| GET            | `/api/v1/extensions/{slug}/versions`                            | Versions (publisher sees unapproved + problems)            | `200`             |
| GET            | `/api/v1/extensions/{slug}/versions/{version}/bundle`           | Zip bytes + `X-Solus-Content-Hash`                         | `200`             |
| GET            | `/api/v1/extensions/{slug}/versions/{version}/assets/{path}`    | Recorded store assets only                                 | `200`             |
| POST           | `/api/v1/extensions/publish`                                    | Multipart bundle ≤ 25 MiB → version `pending` + review job | `202`             |
| GET            | `/api/v1/extensions/{slug}/versions/{version}/review`           | Review status (publisher only)                             | `200`             |
| DELETE         | `/api/v1/extensions/{slug}/versions/{version}`                  | Unpublish (soft delete)                                    | `204`             |
| PATCH          | `/api/v1/extensions/{slug}`                                     | `{ verified }` — staff only                                | `200`             |
| GET            | `/api/v1/projects/{project_id}/extensions`                      | Installed extensions                                       | `200`             |
| PUT            | `/api/v1/projects/{project_id}/extensions/{slug}`               | Install / update (`{ version?, grants }`)                  | `201` / `200`     |
| PATCH          | `/api/v1/projects/{project_id}/extensions/{slug}`               | `{ enabled?, settings? }`                                  | `200`             |
| DELETE         | `/api/v1/projects/{project_id}/extensions/{slug}`               | Uninstall                                                  | `204`             |
| GET/PUT/DELETE | `/api/v1/projects/{project_id}/extensions/{slug}/storage/{key}` | `storage.own` value                                        | `200`/`201`/`204` |
| GET/PUT        | `/api/v1/projects/{project_id}/widget-layout`                   | Caller's widget layout                                     | `200`             |
| GET            | `/api/v1/teams/{team_id}/extensions/policies`                   | Team policies                                              | `200`             |
| PUT            | `/api/v1/teams/{team_id}/extensions/policies/{slug}`            | Upsert policy                                              | `201` / `200`     |
| DELETE         | `/api/v1/teams/{team_id}/extensions/policies/{slug}`            | Reset policy                                               | `204`             |

Full plan — request/response shapes, the bounded-reader publish flow and review job, grants /
`409 grants_required`, settings validation, storage caps (64 KiB / 256 KiB), widget-layout
shape, the `X-Solus-Extension` attribution rule, data events, rate budgets, error catalogue and
the security checklist — lives in [extensions.md](extensions.md).

### SOLUSDEV-262 — packet units and device-view continuity

Recent telemetry samples add optional `unit: string|null`, copied from each packet's unit map.
Missing units remain unknown. Preserve units per sample across changes; do not infer from signal
names or convert stored values. Both memory and Redis buffers retain this metadata. Existing
unitless Redis rows still read with null units. The LB-06 packet contract is unchanged.

`bench/device-recent` continues serving a device after it resolves to a graph entity by reading
that entity's project-scoped recent buffer. Resolution must not make a streaming device disappear
from the no-focus view. Limits, identity scoping and negative/zero-limit behavior stay explicit.

The local `GET /projects/{project_id}/bench/sources` device rows also expose optional `headline`
metadata from the USB board definition. Both local connection pickers and discovery cards render
this tentative hint; `board`, `mcu_known`, serial ambiguity and explicit port confirmation retain
their existing meaning. Missing headlines preserve legacy fallback wording.

### SOLUSDEV-262 — optional Live Bench focus narrowing

`GET /projects/{project_id}/bench/device-recent` accepts optional UUID `focus_entity_id`.
Absent: existing device-keyed batch behavior, including unresolved observations. Present:
validate a live entity in the authorized project, then return only requested device views whose
resolved entity belongs to that entity or its accepted physical topology descendants. Physical
robot membership edges select its projection; brain/bus traversal follows accepted hardware
connectivity, never arbitrary source relations or name similarity. Unknown mapping yields
`devices:[]`, not unfiltered fallback; wrong-project/deleted focus returns404. Read-only: do not
open ports, create graph facts, alter focus, or change telemetry ownership.

**SOLUSDEV-262 reviewed offers.** `force_confirmation` is a strict boolean, default false.
When true, the per-turn Build policy cannot automatically authorize owned routines; mutating
calls follow the existing confirmation-card/decision path. Explicit host-mirror offers send true.
The flag does not grant tool, workspace or project authority and does not make Guide executable.
