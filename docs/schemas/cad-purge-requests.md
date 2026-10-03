# `cad_purge_requests` (ADR-038 amendment §4, SOLUSDEV-312)

A durable obligation to delete one provider account's durable CAD derivatives.
Written in the **same transaction** as the revocation, account deletion, legacy
source disconnect, or project/team teardown that creates the duty, so the duty
exists if and only if the grant is gone.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `account_hash` | varchar(64), unique | `sha256("<provider>:<account_ref>")` — the CAD store prefix. Never an id, token, name or email. |
| `passes_remaining` | int | Starts at 2: a second pass ~15 min later catches a sync already in flight. |
| `attempts` | int | Failed attempts; drives backoff (60 s doubling to 1 h). |
| `next_attempt_at` | timestamptz, indexed | When the next pass is due. |
| `created_at` | timestamptz | |

**Not tenant-scoped** (no `team_id`/`project_id`): it holds only an opaque hash,
like `deleted_accounts` and the other ADR-027 opaque-id exceptions, and it must
outlive the team/project/account rows it was written for.

Runners: inline after the revoking request commits (15 s bound), the ARQ cron
`purge_cad_accounts` (every minute and at worker startup), and API startup.
Concurrent runners use `SELECT … FOR UPDATE SKIP LOCKED`. A row is deleted only
after its final pass finds the account prefix empty. Migration:
`packages/api/migrations/versions/a38000000001_adr_038_cad_purge_requests.py`.
