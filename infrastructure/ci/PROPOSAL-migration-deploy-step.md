# PROPOSAL — Database migrations in the deploy path

**Status:** proposal, awaiting human decision (`.gitlab-ci.yml` is human-owned, ADR-007).
**Author:** SOLUSDEV-152 agent work, 2026-07-19. **Decision needed:** adopt, defer, or reject the CI job below.

## Where things stand today (already shipped in SOLUSDEV-152)

The API container now runs `alembic upgrade head` in its entrypoint before starting
uvicorn — bounded (`SOLUS_MIGRATE_TIMEOUT_SECONDS`, default 120s), fail-fast (the
container exits non-zero before serving, so ECS keeps the previous task running), and
logged to CloudWatch. A fresh database gets its schema on first boot with **no CI
change required**. This closes the "fresh DB has no tables" boot blocker on its own.

## The proposal: an explicit `migrate:staging` CI job

Add a pipeline job that runs migrations _before_ the ECS rollout:

```diff
--- a/.gitlab-ci.yml
+++ b/.gitlab-ci.yml
@@ deploy stage @@
+migrate:staging:
+  extends: .python-base
+  stage: deploy
+  rules:
+    - if: $CI_COMMIT_BRANCH == "main"
+  environment:
+    name: staging
+  variables:
+    SOLUS_DATABASE_URL: $STAGING_DATABASE_URL
+  script:
+    - cd packages/api && uv run alembic upgrade head
+  needs: ["build:api-image"]
+
 deploy:staging:
   stage: deploy
+  needs: ["migrate:staging"]
   ...
```

## Trade-offs

|                     | Entrypoint (shipped)                                                                     | CI job (proposed)                                                                                        |
| ------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Fresh-DB boot works | yes                                                                                      | yes                                                                                                      |
| Failure surfaces    | container crash-loop in ECS (visible in CloudWatch, old task keeps serving)              | pipeline fails red _before_ any rollout starts                                                           |
| Concurrent tasks    | multiple tasks may race the migration (Alembic serializes via DB lock; benign but noisy) | exactly one migration run per deploy                                                                     |
| Rollback story      | none — a bad migration blocks every new task                                             | pipeline stops; no new task ever launched                                                                |
| Prerequisites       | none                                                                                     | `$STAGING_DATABASE_URL` as a **masked** CI variable; the `aws-arm` runner needs VPC network reach to RDS |

Both are idempotent (`upgrade head` on an up-to-date DB is a no-op), so **adopting the
CI job does not require removing the entrypoint** — they compose: CI applies the
migration deliberately, the entrypoint remains a safety net for manual task restarts.

## Recommendation

Adopt the CI job **when SOLUSDEV-144 stands up real prod infra** (it needs the runner
→ RDS network path anyway). Until then the entrypoint alone is adequate for staging.

## Decision checklist (humans)

- [ ] Create masked CI variable `STAGING_DATABASE_URL` (and later a prod equivalent)
- [ ] Confirm the `aws-arm` runner can reach RDS (security group / VPC)
- [ ] Apply the diff above to `.gitlab-ci.yml` (or reject and note here)
- [ ] Revisit at SOLUSDEV-144 if deferred
