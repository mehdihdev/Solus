# AWS deployment — solus-api (staging)

How the API container gets built, configured, and booted on ECS Fargate, and
what "degraded mode" (no ARQ worker) means. Written for SOLUSDEV-152 (WS-B).

## Deploy path

Validation runs before merge. Protected `main` requires a successful MR pipeline;
its pipeline runs only the image build and staging deployment below. Pipeline
selection, performance evidence and QA are documented in
[`infrastructure/ci/README.md`](../ci/README.md).

1. `.gitlab-ci.yml` `build:api-image` builds `infrastructure/docker/api.Dockerfile`
   on the `aws-arm` runners and pushes `$ECR_URI:$CI_COMMIT_SHORT_SHA` and
   `$ECR_URI:arm-latest`. Because the runners are ARM, the image is
   linux/arm64 — `taskdef.json` therefore pins `cpuArchitecture: ARM64` and
   references the `arm-latest` tag.
2. `deploy:staging` forces a new deployment of the ECS service; the task
   definition is `infrastructure/aws/taskdef.json` (family `solus-api`).
3. Container boot sequence (see the entrypoint in `api.Dockerfile`):
   - `alembic upgrade head` against `SOLUS_DATABASE_URL` — bounded by
     `SOLUS_MIGRATE_TIMEOUT_SECONDS` (default 120s), fail-fast (`set -eu`),
     logged to CloudWatch (`/solus/staging/backend`). A fresh RDS database
     gets its entire schema here; nothing else in the deploy path creates
     tables (`SOLUS_AUTO_CREATE_TABLES` must stay false in shared envs).
   - `uvicorn --factory solus_api.main:create_app --host 0.0.0.0 --port 8000`.
   - If migration fails or times out the container exits non-zero **before**
     serving, so ECS keeps the previous task running instead of registering a
     half-migrated one.

Health probes: `GET /healthz` (liveness) and `GET /readyz` (readiness; 503
only when the database is unreachable — queue state is reported, never fatal).

## Configuration (all `SOLUS_*`, read by `packages/api/src/solus_api/core/config.py`)

Secrets — **always** via `secrets[]` (Secrets Manager ARN references), never
plaintext in `environment[]` and never committed anywhere:

| Env var                     | Source                                                 | Notes                                                                                                                                                                                                      |
| --------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SOLUS_DATABASE_URL`        | `solus/staging/db` secret, JSON key `database_url`     | Single DSN: `postgresql+asyncpg://USER:PASS@HOST:5432/DBNAME`. The secret historically held `username`/`password`/`port`/`dbname` keys — add the composed `database_url` key; the code reads only the DSN. |
| `SOLUS_SUPABASE_JWT_SECRET` | `solus/staging/supabase` secret, JSON key `jwt_secret` | **Required** — `Settings()` refuses to start without it (ADR-009). Create the secret, then replace the `XXXXXX` ARN suffix placeholder in `taskdef.json` with the real Secrets Manager suffix.             |

The ECS **execution role** (`ecsTaskExecutionRole`) needs
`secretsmanager:GetSecretValue` on both secret ARNs.

Plain environment:

| Env var              | Staging value              | Notes                                                                                                                                                                                                                      |
| -------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SOLUS_APP_ENV`      | `staging`                  |                                                                                                                                                                                                                            |
| `SOLUS_AWS_REGION`   | `us-east-1`                | Also selects the AWS Secrets Manager backend for connector credentials.                                                                                                                                                    |
| `SOLUS_CORS_ORIGINS` | dev origins (carried over) | Comma-separated browser/renderer origins.                                                                                                                                                                                  |
| `SOLUS_REDIS_URL`    | `""` (empty)               | Deliberately empty until the worker's Redis exists (SOLUSDEV-144). Empty/unset reads as "no queue" — see degraded mode below. Fill with the ElastiCache DSN on **both** the API and worker task definitions when it lands. |

## Degraded mode (no ARQ worker) — ACCEPTED for this cycle

Staging currently runs the API service only: no Redis, no ARQ worker. The API
is fully functional for request/response work, with these documented gaps:

**What does not run without the worker:**

- **No scheduled auto-resync.** The `scheduled_change_detection` cron
  (`solus_api/connectors/worker.py`) never fires, so connected sources are not
  probed for upstream changes. Syncs happen only when a user triggers them.
- **No `reconcile_credit_debits` sweep.** The billing dead-letter
  reconciliation cron (SOLUSDEV-83) never fires, and the on-demand enqueue
  after a failed inline debit also needs Redis — dead-lettered credit debits
  sit unreconciled until a worker exists.
- **Manual syncs run in-process.** `sources._dispatch_sync` falls back to
  FastAPI background tasks inside the API process: they compete with request
  handling for the same CPU, and an ECS deploy/restart kills any in-flight
  sync (it is recorded as stuck-RUNNING in logs, per runtime.py).
- **Job cancellation is record-level only** (`POST /jobs/{id}/cancel`
  docstring): with or without the worker, cancel marks the row and aborts
  nothing.

**How it is surfaced:** `GET /readyz` reports the truth from config —
`"redis"`/`"queue"` are `"configured"` when `SOLUS_REDIS_URL` is a non-empty
DSN, `"not_configured"` otherwise. Readiness never fails for a missing queue;
only an unreachable database returns 503.

## Running the worker (when Redis exists)

The worker is a separate process sharing the API codebase and env:

```sh
uv run arq solus_api.worker_main.WorkerSettings
```

It needs the same runtime env as the API (`SOLUS_DATABASE_URL`,
`SOLUS_REDIS_URL` — non-empty, `SOLUS_AWS_REGION` for the secret store, GitHub
OAuth vars for syncs that need them). It runs `sync_source` jobs plus the
`scheduled_change_detection` and `reconcile_credit_debits` crons.

**The production/staging worker ECS service lands with SOLUSDEV-144** — until
then, degraded mode above is the expected state and the ECS footprint is the
single `solus-api` service.

## Local smoke test of the image

```sh
docker build -f infrastructure/docker/api.Dockerfile -t solus-api .
docker run --rm -p 8000:8000 \
  -e SOLUS_DATABASE_URL="postgresql+asyncpg://solus:solus@host.docker.internal:5432/solus" \
  -e SOLUS_SUPABASE_JWT_SECRET="dev-only-value" \
  solus-api
curl localhost:8000/healthz && curl localhost:8000/readyz
```
