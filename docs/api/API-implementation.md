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
    "data_collection_consent": false,
    "onboarding_step": "about"
  }
}
```

`data_collection_consent` is the ADR-011 opt-in/out switch (default **false**; see §9 —
events are recorded only while consented). `onboarding_step`
(`about|connect|build|done`) is the FND-08 resume point.

### PATCH /api/v1/users/me/settings

```json
{ "sol_mode": "expert" }
```

`200` — same shape as GET with the change applied. All three fields are patchable
independently; ADR-016: `sol_mode` switchable any time. `"sol_mode":"yolo"` → `422`.

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

| Surface                                                                                                                                                                                             | Status                                                                                                                                                                                                                                                                                                                                                              |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| §2.1 API keys (`/users/me/api-keys`)                                                                                                                                                                | Excluded from Phase 1 by API.md §8 (rides with the MCP decision)                                                                                                                                                                                                                                                                                                    |
| §2.4–§2.15, WS/SSE                                                                                                                                                                                  | Later phases (graph, sources, checkers, agent, bench, …)                                                                                                                                                                                                                                                                                                            |
| `POST /graph/query`, MCP server, presence topic                                                                                                                                                     | **[DEFERRED]** per API.md §7.2 — blocked on human decisions                                                                                                                                                                                                                                                                                                         |
| Stripe billing routes (`POST /api/v1/webhooks/stripe`, `POST /api/v1/billing/checkout-session`, `POST /api/v1/billing/portal-session`, `GET /api/v1/billing/packs`, `GET /api/v1/users/me/credits`) | **Built** — webhook (SOLUSDEV-83) + the checkout/portal/packs/credits routes (SOLUSDEV-83 follow-up) lift the §7.2 deferral by human decision. Full "select plan → Stripe Checkout → webhook confirms" flow. See §10. The trial-only `PATCH /users/me/subscription` (no Stripe call — ADR-032) remains live for onboarding, see §3. Enterprise stays contact-sales. |
| Alembic migrations                                                                                                                                                                                  | Schema is final-for-phase but baseline migration generation needs a running Postgres; tracked for the integration-environment ticket. Tests/dev use `metadata.create_all`                                                                                                                                                                                           |
| ARQ/Redis worker wiring                                                                                                                                                                             | No job-producing endpoint exists yet (first one: §2.5 sync in Phase 3); §2.16 read/cancel surface is live                                                                                                                                                                                                                                                           |
| Data-collection consent (§2.13)                                                                                                                                                                     | **Live** — the ADR-011 opt-in/out ships as `data_collection_consent` on `GET`/`PATCH /users/me/settings` (see §3), not as dedicated §2.13 routes. Default remains **false**; events are recorded only while consented.                                                                                                                                              |

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

### GET /api/v1/billing/packs — purchasable credit packs (authenticated)

- `200 {"data": {"packs": [{"price_id": "...", "credits": 1000}, ...]}}` from
  `SOLUS_STRIPE_PACK_CREDITS`, sorted by credits. Price ids are not secrets; this
  keeps the UI from hard-coding environment-specific Stripe ids.

### GET /api/v1/users/me/credits — credit balance (authenticated)

- `200 {"data": {"user_id": "...", "balance": <int>}}`. Always answerable — `0`
  before any ledger row exists. Team-scoping N/A: credits are per-user (ADR-024).

### Webhook plan derivation (SOLUSDEV-83 follow-up)

On `customer.subscription.created/updated`, the local `plan` + `limits` are now
set from the purchased Stripe **Price** (reverse `SOLUS_STRIPE_PLAN_PRICES`
lookup), so entitlement always reflects what was actually paid for — never a
client-supplied plan name. An unmapped price leaves the plan unchanged.

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

| Method | Path                               | Purpose                                                        | Success |
| ------ | ---------------------------------- | -------------------------------------------------------------- | ------- |
| GET    | `/sol/tools`                       | List the W0-04 tool descriptors SOL may invoke (fixed by code) | `200`   |
| POST   | `/sol/conversations`               | Create a conversation (`{title?}`)                             | `201`   |
| GET    | `/sol/conversations`               | List the caller's conversations (cursor-paginated)             | `200`   |
| GET    | `/sol/conversations/{id}`          | Get one owned conversation                                     | `200`   |
| DELETE | `/sol/conversations/{id}`          | Soft-delete an owned conversation                              | `204`   |
| GET    | `/sol/conversations/{id}/turns`    | List a conversation's turns (cursor-paginated)                 | `200`   |
| POST   | `/sol/conversations/{id}/messages` | Append a user message and **stream** SOL's reply (SSE)         | `200`   |

**Streaming turn (`POST …/messages`).** Returns `text/event-stream`. The user turn is persisted
(and `sol.message` logged) before streaming; assistant/tool turns are persisted as the stream
completes. SSE `event:` names and their `data` payloads:

- `token` — `{"text": "…"}` incremental reply delta
- `tool_call` — `{"call_id","tool","args"}` a proposed W0-04 tool invocation
- `tool_result` — the W0-04 `ToolResult` envelope (`{"call_id","ok","value"|"error"}`)
- `message` — `{"role":"assistant","content":"…"}` the finished reply
- `error` — `{"code","message"}` a generic, author-safe failure (never a traceback, §7)
- `done` — `{"conversation_id","turn_id"}` terminal marker

The reasoning loop runs behind the `agent.runtime.AgentRunner` seam. This cycle ships a
deterministic, model-free `ScaffoldRunner` (mock-and-swap, like `FakeSolSystems`) that proves
the plumbing end to end — lists tools, invokes the reference `get_entity` tool through the
per-request registry, pulls W0-07 graph context, and honors a bounded tool-call loop guard.
Model routing / credit metering (W0-03 `route()`/`track_cost`) remain MO-01 stubs, so no live
model call is made yet; per-team model-budget enforcement lands with MO-01.
