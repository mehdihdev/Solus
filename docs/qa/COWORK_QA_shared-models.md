# Cowork QA — SOLUSDEV-72 Shared Data Models

**Feature:** the canonical SQLAlchemy 2.0 + Pydantic v2 schema (users, teams, memberships,
projects, project_memberships, subscriptions, credits, notifications, and the cross-domain
graph: graph_entity / graph_edge / error_solution), plus the first Alembic baseline migration.

**Nature of this ticket:** MODELS ONLY. It introduces **no new API routes or UI**. Its user-visible
impact is indirect: it reconciles the existing tenancy schema (field renames + soft-delete + new
tables) and moves the backend onto PostgreSQL + pgvector. So this QA pass is (A) a **regression
check** that every existing flow still works after the schema change, and (B) a **schema/migration
verification** done at the DB and test layer. There is no new screen to click through.

---

## Required setup state

1. Docker running. Bring up Postgres + Redis:
   ```bash
   make db-up          # starts pgvector/pgvector:pg16 on localhost:5432 (db "solus")
   ```
2. Python workspace synced: `uv sync --all-packages` (from repo root).
3. **Environment note (important for the tester):** the pre-commit hooks in this repo resolve
   `mypy`/`pytest`/`ruff` from whatever is on PATH. If Claude Code / the shell was launched from an
   Anaconda base env instead of the project's `.venv`, those hooks report false "module not found"
   errors. Run all verification through **`uv run ...`** (which uses the correct venv), or
   `source .venv/bin/activate` before launching. This does not affect the app itself.
4. Apply the schema to the dev database:
   ```bash
   cd packages/api
   SOLUS_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus uv run alembic upgrade head
   ```
5. A valid `packages/api/.env` with `SOLUS_SUPABASE_JWT_SECRET` (already present in dev). The API
   validates Supabase JWTs; test clients mint tokens with the same secret.

---

## Part A — Automated verification (run these first)

| #   | Step                                | Command                                                                                                        | Expected                                                                                                                                           | Pass/Fail |
| --- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| A1  | Migration applies on a **fresh** DB | create an empty DB, `alembic upgrade head` against it                                                          | Completes with no error; 17 tables + `vector` extension + ivfflat indexes exist                                                                    |           |
| A2  | Migration is reversible             | `alembic downgrade base` then `alembic upgrade head`                                                           | Both succeed (exit 0)                                                                                                                              |           |
| A3  | Full backend suite                  | `uv run pytest packages/api/tests -q`                                                                          | **102 passed**                                                                                                                                     |           |
| A4  | Round-trip persistence              | `uv run pytest packages/api/tests/test_shared_models.py -v`                                                    | 4 passed: full graph round-trip (vectors + `canonical_part_id` self-ref + FKs), credit ledger/balance, Read-schema validation, plan-limit defaults |           |
| A5  | Types + lint                        | `uv run mypy packages/api/src packages/api/tests packages/api/migrations` and `uv run ruff check packages/api` | Both clean                                                                                                                                         |           |

---

## Part B — Regression of existing flows (the schema change must not break these)

Run the API (`make dev-api`) or exercise via the test client. Every flow below existed before this
ticket; confirm each still behaves identically after the rename/migration.

### B1 — First login provisions a user + personal team

1. Authenticate as a new user (bearer token with a fresh `sub`).
2. `GET /api/v1/users/me`.

- **Expected:** user is created; `teams` has exactly one entry with `is_personal: true`, `role: owner`.
  (Internally `is_personal` is now derived from the new `kind == PERSONAL` — the response field is unchanged.)
- [ ] Pass

### B2 — User display name round-trips

1. `PATCH /api/v1/users/me` with `{"name": "Ada"}`.
2. `GET /api/v1/users/me`.

- **Expected:** response `name` is "Ada". (Stored in the renamed `display_name` column; API key unchanged.)
- [ ] Pass

### B3 — Create a collaborative team

1. `POST /api/v1/teams` `{"name":"Rovers"}`.

- **Expected:** 201; team detail shows `is_personal: false`. (New team defaults to `kind = COLLABORATIVE`.)
- [ ] Pass

### B4 — Invite + accept = individual→team upgrade

1. As owner of a **personal** team, `POST /api/v1/teams/{personal_team_id}/invites` `{"email":"bob@…","role":"member"}` → 201, returns a one-time `token`.
2. As Bob, `POST /api/v1/invites/{token}/accept`.

- **Expected:** Bob joins; the personal team flips to non-personal (`kind` PERSONAL→COLLABORATIVE); Bob's membership is created with status ACTIVE. Re-accepting or a second membership is rejected `409 already_member`.
- [ ] Pass

### B5 — Create a project (now records its creator)

1. `POST /api/v1/teams/{team_id}/projects` `{"name":"Rover-1"}`.

- **Expected:** 201. Internally `created_by` is set to the requesting user (new column; verify in DB it equals the creator's id).
- [ ] Pass

### B6 — Notifications list / read / read-all

1. Seed a notification for the user (or trigger one), `GET /api/v1/users/me/notifications`.
2. `POST /api/v1/users/me/notifications/{id}/read`; `POST …/read-all`.

- **Expected:** pagination works; `read_at` populates. Response now includes `type` (enum value), `attrs`, and `action_url` (renamed from `payload`; `type` is now a constrained enum).
- [ ] Pass

### B7 — Jobs resource + team scoping

1. `GET /api/v1/jobs/{job_id}` for a job in your team vs another team's job.

- **Expected:** own team → 200; other team → 404 (no existence leak). Membership lookup now goes through the new surrogate-PK path.
- [ ] Pass

### B8 — Settings (SOL mode) unaffected

1. `PATCH /api/v1/users/me/settings` `{"sol_mode":"expert"}`; `GET …/settings`.

- **Expected:** persists "expert". (`sol_mode` column retained through the reconciliation.)
- [ ] Pass

### B9 — Account deletion + last-owner safeguards

1. As sole owner of a shared team, `DELETE /api/v1/users/me`.

- **Expected:** `409 ownership_transfer_required`. Deleting a solo user (only personal team) succeeds `204`.
- [ ] Pass

---

## Part C — Cross-tenant isolation (highest-severity invariant)

### C1 — Team A cannot read/mutate Team B

1. User A creates team A + project; User B creates team B.
2. As B, attempt `GET /api/v1/teams/{A_team_id}`, `…/projects`, and any `{A_project_id}` route.

- **Expected:** every attempt → **404** (not 403 — no existence leak). This is covered by the existing isolation tests, which still pass on the new schema; re-confirm manually.
- [ ] Pass

---

## Part D — New schema surfaces (DB-level; no UI yet)

These have no endpoints in this ticket. Verify at the DB layer (psql) or trust the round-trip test (A4).

### D1 — Graph tables + pgvector

- `graph_entity`, `graph_edge`, `error_solution` exist; `embedding` columns are `vector(1536)`; ivfflat indexes present (`\d graph_entity`).
- `graph_entity.canonical_part_id` self-FK: an observation row can point at a canonical row (the fingerprint's output slot). Verified by A4's round-trip.
- [ ] Pass

### D2 — Billing + credits

- `subscriptions` (team-owned), `credit_balance` (per-user, unique per user), `credit_ledger` (append-only: has `created_at`, no `updated_at`/`deleted_at`).
- Plan-default limits config: BASIC = `{max_integrations:4, max_projects:3, max_teams:2}`, PRO = all null (unlimited), ENTERPRISE = `{}` (custom). Verified by A4.
- [ ] Pass

### D3 — Soft delete

- Soft-deletable tables carry `deleted_at`; partial-unique indexes on `memberships(team_id,user_id)` and `project_memberships(project_id,user_id)` are `WHERE deleted_at IS NULL` (a re-add after soft delete does not collide). Append-only tables (credit_ledger, notifications) have no `deleted_at`.
- [ ] Pass

---

## Failure paths to exercise

- Apply the migration twice (second `alembic upgrade head` is a no-op, not an error).
- Bad input on existing mutating routes (blank team/project name → 422; unknown fields → rejected).
- Expired / bad JWT → 401. Invite to a different email than the token was issued to → 403. Expired invite → 410.
- Personal team cannot be deleted → 409.

## Known caveats (not bugs)

- `make test` / the suite now **requires** Postgres (`make db-up`) — SQLite can no longer host the pgvector columns.
- ivfflat indexes on freshly-created empty tables have no centroids yet; they become effective once rows exist (operational, not a correctness issue).
- This ticket intentionally ships **no** enforcement logic (plan limits, credit deduction, project-membership auto-seeding, invite eligibility) — those are downstream tickets.
