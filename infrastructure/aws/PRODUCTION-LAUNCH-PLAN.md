# Solus production launch plan — api.solusforge.com, solusforge.com, desktop installers

**Status:** DRAFT for human review (2026-11-07). Supersedes nothing yet; it builds on, and corrects,
`infrastructure/aws/README.md`, `HUMAN-STEPS.md`, `taskdef.json` and
`infrastructure/ci/PROPOSAL-migration-deploy-step.md`, which were written for staging months ago.

**Method:** two independent read-only audit agents (backend runtime; desktop packaging + website)
checked the code on `main`, `SOLUSDEV-319` and `SOLUSDEV-322` against those docs, and the live endpoints
were probed. Every claim below that cites a file was verified in code; items marked _(inferred)_ still
need a real run to confirm.

---

## 0. Where we actually are (2026-11-07)

| Surface                         | State                                                                                                                                                                                                       |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `https://api.solusforge.com`    | **503** — the ALB has no healthy target. Staging is down.                                                                                                                                                   |
| `https://solusforge.com`        | On **Vercel**, landing page + waitlist only. No download page, no legal pages, footer links are `#`.                                                                                                        |
| `docs.solusforge.com`           | Linked from the desktop menu; **does not exist**.                                                                                                                                                           |
| AWS (`344838028176`, us-east-1) | Console-built, no IaC. One ALB (TLS done, wildcard cert to Feb 2027), one ECS service (staging, 0.25 vCPU/512 MB), RDS, `solus-staging-artifacts`. **No Redis, no worker, no prod service, no CAD bucket.** |
| CI                              | Lint, mypy, node tests, gitleaks, arm64 image build + staging deploy on `main`. **No pytest job. No installer builds. Prod deploy commented out.**                                                          |
| Desktop releases                | Manual, per-OS, host-arch only. **Unsigned, un-notarised, no auto-update.**                                                                                                                                 |
| Code that must ship             | Lives on **unpushed** `SOLUSDEV-319` (+46 commits) and `SOLUSDEV-322` (+45), siblings off `main`.                                                                                                           |

### What would break for a real user today (ranked)

1. **No production API.** And any desktop build without `VITE_API_BASE_URL` silently points at `localhost:8000` (`cspConnect.ts:15`).
2. **Fresh-DB boot crash.** Outside dev, `prepare_catalog` re-raises if the first-party BOM extension is not published (`extensions/bom_catalog_setup.py:41-60`, awaited unguarded at `main.py:290`). It needs `SOLUS_FIRST_PARTY_PUBLISHER_ID` to be an existing staff user — who can only exist after someone signs in to a running API. Chicken-and-egg; not in any deploy doc.
3. **Logins 401 without `SOLUS_SUPABASE_URL`.** Without it there is no JWKS client, only HS256 validates, and current Supabase projects sign ES256 (`core/security.py:80-106`). The taskdef doesn't set it.
4. **Packaged app CORS** _(inferred)_: the renderer loads via `loadFile` (`main/index.ts:575`) → `Origin: null`/file://; the API allowlist is localhost + `panel.solusforge.com`. Every API call from an installed app is likely blocked.
5. **Unsigned installers.** Gatekeeper blocks the app on macOS; the unsigned drive helper refuses to start (`build-solus-input.sh:78`); SmartScreen warns on Windows.
6. **MCP forks have no interpreter on user machines.** Each fork's `bin/launch` runs `<fork>/.venv/bin/python3`; those venvs are only created by the dev script `scripts/install-mcp-forks.sh` (needs `uv` + Python 3.12), `.venv` is gitignored, POSIX forks have no Windows launcher. KiCad/Altium/code tools would connect with zero usable tools.
7. **Two Alembic heads after merging 319 and 322.** Both `a31900000002` (319) and `a31900000001` (322) descend from `a32100000001`; the entrypoint's `alembic upgrade head` fails until a merge revision exists.
8. **API cannot run more than one task.** Bridge sessions (`bridge/registry.py`), the telemetry buffer and bench sessions are in-process memory. Scale up and SOL turns on task B can't reach a companion connected to task A.
9. **Secrets collide across environments.** Runtime keys live at `solus/connectors/<ref>` with no env in the path (`connectors/secrets.py:149`) — staging and prod in one account share the same Stripe and LLM keys; and `ops/stripe_setup.py:372` demands LIVE Stripe whenever `app_env != "dev"`, staging included.
10. **Long-lived connections vs the 60 s ALB idle timeout.** SOL turn SSE has no keepalive (`routers/sol.py:1340`); drive/tool steps can run 120 s _(inferred cut-off)_.
11. **Client IP lost behind the ALB** — uvicorn lacks `--proxy-headers --forwarded-allow-ips`, so every per-IP limiter collapses into one bucket _(inferred)_.
12. **Auth emails go nowhere useful.** `signUp`/`resetPasswordForEmail` pass no `emailRedirectTo` (`authStore.ts:211`) → links land on the Supabase Site URL, which has no handler page. Supabase's built-in SMTP is heavily rate-limited — prod needs custom SMTP.
13. **Live Bench is local-dev only.** `livebench` (MuJoCo, serial) runs inside the API process and is not in the image (`hardware_router.py:634`). Hosted users see "not installed on this server". A product decision, not a bug.
14. **The 319 branch's own validation gate is red** (mypy duplicate `solus.roster`, a hanging pytest, eslint complexity in `solApi.ts`/`HomeScreen.tsx`). Must be green before anything merges.

---

## 1. Target architecture

```
                         solusforge.com ──► Vercel (Next.js: landing, /download, legal, auth landing pages)
                    docs.solusforge.com ──► docs site (Vercel or S3+CloudFront)
               downloads.solusforge.com ──► CloudFront ──► S3 solus-prod-releases (installers + update feed)

  Desktop app ──HTTPS/SSE/WSS──► api.solusforge.com ──► ALB (TLS1.3, idle 300s, WAF)
                                               │
                     ┌─────────────────────────┴───────────────────────┐
              ECS Fargate (arm64)                              ECS Fargate (arm64)
              solus-api  ×1 (1 vCPU / 2 GB)                     solus-worker ×1 (1 vCPU / 2 GB)
              uvicorn, SSE, bridge WS, webhooks                  ARQ jobs + crons
                     │            │            │                        │
                RDS Postgres 16  ElastiCache Valkey (noeviction, TLS+AUTH)   S3: artifacts / cad-store
                pgvector, pg_trgm                                         Secrets Manager / CloudWatch
                     │
             one-off ECS task: `alembic upgrade head` + corpus ingest (run by CI before rollout)

  External: Supabase Auth (prod project) · Stripe (live) · OpenAI / Anthropic / Google · Brave · GitHub App/OAuth ·
            GitLab OAuth · Onshape OAuth + webhooks · Sentry · SES (Supabase custom SMTP)
```

Decisions baked in (all within ADR-003/006/007/009/037/038 — no new ADR needed except where flagged):

- **Same image, two services** (API, worker) + a **one-off migration task**. Migrations leave the container entrypoint for prod (keep it as a safety net only on staging), adopting the existing CI proposal — one run per deploy, no races, a red pipeline before any rollout.
- **API pinned to one task** until the bridge registry / telemetry buffer / bench sessions move to Redis (separate ticket, §4 WS-B6). Vertical scaling (2 vCPU/4 GB) is the lever until then.
- **Immutable image tags** (`$CI_COMMIT_SHORT_SHA`); task definitions rendered per environment from a template, never the mutable `arm-latest`.
- **Tasks stay in public subnets with public IPs + tight SGs** (as staging does) — no NAT Gateway (~$35+/mo each). RDS and Valkey in private subnets, reachable only from the task SGs.
- **Each account has its own ALB.** Prod is a separate account (D1), so ALBs and ACM certificates cannot be shared across accounts. Staging keeps its existing ALB at `staging-api.`; prod gets a new one at `api.`.
- **Installers on S3 + CloudFront** (not Vercel — bandwidth and file-size limits), with an `electron-updater` generic feed in the same bucket.

---

## 2. Decisions needed from humans (blocking)

| #   | Question                                                                                    | Recommendation                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Separate AWS account for prod (AWS Organizations) or one account with env-prefixed secrets? | **Separate prod account.** Fixes the secret-path collision (#9) with no code change, gives a clean IAM/blast-radius boundary, and is what enterprise/self-host buyers will ask about. Cost: $0.                                                                                                 |
| D2  | Adopt IaC?                                                                                  | **Yes — Terraform** (or OpenTofu), importing the console-built staging. Agents can then write `plan`s that a second agent reviews and a human applies; without IaC every agent fix is another undocumented console click (that is how staging hit five faults in a row). Needs an ADR (tier-2). |
| D3  | Launch platforms                                                                            | **macOS arm64 + Windows x64 at launch; macOS x64 and Linux (AppImage/deb) as "beta, unsigned-OK" or follow-up.** Snap needs a store account — drop for now.                                                                                                                                     |
| D4  | MCP fork runtime on user machines (#6)                                                      | **Bundle `python-build-standalone` 3.12 per OS inside the companion resources, and create each fork's venv on first run from a bundled, hash-pinned wheelhouse** (no network). Alternative: freeze each fork with PyInstaller (bigger installer, simpler runtime). Needs an ADR-031 amendment.  |
| D5  | Live Bench for hosted users (#13)                                                           | Ship launch with Live Bench **marked "requires local runtime"**, and ticket a local Live Bench worker in the companion (322 already moves teleop that way via the ADR-014 amendment).                                                                                                           |
| D6  | Availability posture                                                                        | **"Standard"** (Multi-AZ RDS, WAF) ≈ $340/mo AWS, or **"Lean"** (single-AZ, no WAF, staging stopped off-hours) ≈ $240/mo. See §6.                                                                                                                                                               |
| D7  | Packaged-app origin (#4)                                                                    | **Serve the renderer from a privileged custom scheme (`app://solus`) instead of `file://`** and add exactly that origin to prod CORS. Never allow `null`.                                                                                                                                       |
| D8  | Trial length                                                                                | Code says `stripe_trial_days=14`; ADR-024 says one month. Pick one.                                                                                                                                                                                                                             |
| D9  | Windows signing route                                                                       | Azure Trusted Signing (~$10/mo, needs eligible org identity) vs an OV/EV cert (~$200–500/yr, hardware token or cloud HSM).                                                                                                                                                                      |

---

## 3. Phased plan

Each phase ends with a gate. Tickets are proposed (`SOLUSDEV-4xx` placeholders); each is one branch/MR
per ADR-021. **Agents never push, never apply to prod, never write secrets** — every "human" box below
is genuinely human.

### Phase A — Make the code shippable (≈1 week, mostly parallel)

| Ticket | Work                                                                                                                                                                                                                                                                                                                                    | Owner                                  |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| A1     | Get 319's validation gate green; human pushes 319 and 322; merge both into `main` in order; **add the Alembic merge revision** for the 319/322 heads; verify a single head.                                                                                                                                                             | agent prepares, human merges           |
| A2     | **Boot-crash fix**: `prepare_catalog` must not take the API down on a fresh DB — degrade (log + readiness detail) and expose an ops command `python -m solus_api.ops bootstrap-catalog --publisher <user_id>` that runs after the first staff sign-in. Test: fresh DB + no publisher → API boots, `/readyz` reports `catalog: pending`. | worktree agent (TDD)                   |
| A3     | **Proxy + timeouts**: uvicorn `--proxy-headers --forwarded-allow-ips` (VPC CIDR); SOL turn SSE keepalive (reuse the 25 s live-channel ping). Tests for both.                                                                                                                                                                            | worktree agent                         |
| A4     | **Packaged-app origin (D7)**: custom privileged scheme for the renderer, CSP updated, `SOLUS_CORS_ORIGINS` gains `app://solus`. Proven with an actual packaged build hitting staging.                                                                                                                                                   | worktree agent + e2e-runner            |
| A5     | **Env-aware secrets** (only if D1 = one account): `solus/<env>/connectors/<ref>`, with a migration for existing refs. Contract-adjacent → in-chat approval first.                                                                                                                                                                       | agent after approval                   |
| A6     | **Add pytest to CI** (with Postgres+pgvector service; isolate DB per memory note) — today no backend test runs in CI at all.                                                                                                                                                                                                            | agent drafts `.gitlab-ci.yml` (tier-1) |
| A7     | **Auth email landing**: `emailRedirectTo` on sign-up/reset → `https://solusforge.com/auth/confirmed` and `/auth/reset` pages (which deep-link back or tell the user to return to the app).                                                                                                                                              | worktree agent (web + desktop)         |

**Gate A:** `main` contains 319+322, one Alembic head, full suite green in CI (node + python), a packaged
dev build talks to staging without CORS errors.

### Phase B — AWS foundation (≈1 week; agents write IaC, humans apply)

| Ticket | Work                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1     | **ADR: IaC (D2)** + Terraform skeleton: remote state (S3 + DynamoDB lock in a tooling/management account), modules `network`, `data` (RDS, Valkey), `storage` (S3 buckets), `compute` (ECS cluster, services, task defs, IAM), `edge` (ALB, listeners, WAF, CloudFront), `observability`. `terraform import` the existing staging resources first — **plan must show zero diff** before any change.                                                                                                                                                                                                                                              |
| B2     | **Prod account (D1)**: Organizations, SCPs (deny root, deny region ≠ us-east-1, deny disabling CloudTrail), IAM Identity Center for both devs (no IAM users), CloudTrail + GuardDuty + AWS Budgets alerts at $250/$400/$600. _Human._                                                                                                                                                                                                                                                                                                                                                                                                            |
| B3     | **Network**: VPC 2 AZs, public subnets (ALB + tasks), private subnets (RDS, Valkey). SGs: ALB ← 0.0.0.0/0:443/80; tasks ← ALB SG:8000; RDS ← task SGs:5432; Valkey ← task SGs:6379. Gateway VPC endpoint for S3 (free).                                                                                                                                                                                                                                                                                                                                                                                                                          |
| B4     | **Data**: RDS PostgreSQL 16, `db.t4g.medium` (Multi-AZ per D6), gp3 50 GB autoscaling to 200, encryption on, deletion protection, 14-day PITR, Performance Insights (free tier), `rds.force_ssl=1`, parameter for `shared_preload_libraries` not needed (pgvector/pg_trgm are plain extensions). ElastiCache **Valkey** `cache.t4g.small`, cluster mode **disabled** (ADR-037 needs `PSUBSCRIBE`), TLS + AUTH, `maxmemory-policy noeviction`.                                                                                                                                                                                                    |
| B5     | **Storage**: `solus-prod-artifacts` (no lifecycle expiry — holds extension bundles the boot depends on; no deny-without-SSE policy, because artifact puts send no SSE header), `solus-prod-cad-store` (per HUMAN-STEPS §SOLUSDEV-312: versioning off, TLS-only, deny-without-SSE, `cad/*` scoped IAM), `solus-prod-releases` (private, CloudFront OAC only). All Block Public Access.                                                                                                                                                                                                                                                            |
| B6     | **Compute**: ECR with scan-on-push + lifecycle (keep 30). Task defs `solus-api-prod`, `solus-worker-prod`, `solus-migrate-prod`, rendered from one template per env. API 1 vCPU/2 GB (measured import RSS ≈240 MB + Node Brave child + caches; 512 MB is not viable). Worker 1 vCPU/2 GB. Circuit breaker + rollback on; `minimumHealthyPercent=100`, `maximumPercent=200` for the worker; **API `desiredCount=1`, max 1** until WS-B6. Task role: S3 on the three buckets (scoped), Secrets Manager CRUD on `solus/connectors/*` (it creates secrets at runtime — `connectors/secrets.py:165-191`). Execution role: read only the boot secrets. |
| B7     | **Edge**: ALB idle timeout 300 s; one ALB per account (prod `api.`, staging `staging-api.`); health check `/healthz`; new ACM cert in the prod account (certs do not cross accounts). WAF (D6): AWS managed common + known-bad-inputs + IP rate rule; **exclude** `/api/v1/webhooks/*` and `/panel*` from body-inspection rules that would mangle signatures. CloudFront for `downloads.` with its own ACM cert in us-east-1.                                                                                                                                                                                                                                                                         |
| B8     | **Observability**: log groups `/solus/prod/{api,worker,migrate}` with 30-day retention; alarms → SNS → email: 5xx rate, target unhealthy, CPU/mem > 80 %, RDS free storage < 20 %, RDS CPU, Valkey memory, ECS task restarts, ARQ queue depth (custom metric), Budgets. Sentry DSN for API + desktop. External uptime check on `/healthz` (free tier of any uptime service).                                                                                                                                                                                                                                                                     |

**Gate B:** `terraform plan` clean in both accounts; a second, fresh-context agent has reviewed every plan
diff; humans have applied; empty infra passes the read-only verification sweep (§5).

### Phase C — Third-party production configuration (human-heavy, ≈2–3 days)

- **Supabase prod project** (separate from dev `jfoyyfaqxppczqmeiwzc`), Pro plan: Site URL `https://solusforge.com`; redirect allowlist `http://127.0.0.1:53682/auth/callback`, `http://[::1]:53682/auth/callback`, `https://solusforge.com/auth/*`; **custom SMTP via SES** (verify `solusforge.com` domain, DKIM/SPF/DMARC in DNS, request SES production access); GitHub provider configured; asymmetric JWT signing keys (closes ADR-009's revisit note).
- **Stripe live mode**: products/prices → `SOLUS_STRIPE_PLAN_PRICES` / `_PACK_*`; webhook endpoint `https://api.solusforge.com/api/v1/webhooks/stripe` → `stripe_webhook_secret`; checkout/portal return URLs overridden from the `localhost:5173` defaults; run `ops/stripe_setup.py` against live.
- **OAuth apps (prod)**: GitHub OAuth + **GitHub App** (7 settings, webhook `…/webhooks/github/app`), GitLab, Onshape (redirect `…/integrations/onshape/oauth/callback`, panel Action URL, webhook reachability). Keep localhost redirect URIs only on the dev apps.
- **Model providers**: prod OpenAI, Anthropic, Google keys with **provider-side spend limits**; Brave key. Store as `solus/connectors/{openai,anthropic,google,brave,stripe}_api_key` in the prod account.
- **Secrets Manager boot set** (prod): `database_url`, `supabase_jwt_secret`, `supabase_service_role_key`, `stripe_webhook_secret`, OAuth client secrets, GitHub App private key + webhook secret, `SOLUS_TOOLKB_VOTE_SALT` (**must be identical on API and worker**), `redis_url`, `sentry_dsn`.
- **Plain env** (prod): `SOLUS_APP_ENV=production` (exactly — `device_watch.py:51` keys on it), `SOLUS_SUPABASE_URL`, `SOLUS_PUBLIC_API_BASE_URL=https://api.solusforge.com`, `SOLUS_CORS_ORIGINS=app://solus`, `SOLUS_ARTIFACT_S3_BUCKET`, `SOLUS_CAD_STORE_S3_BUCKET`, `SOLUS_OAUTH_REDIRECT_APP`, `SOLUS_STAFF_USER_IDS`, `SOLUS_FIRST_PARTY_PUBLISHER_ID` (after bootstrap), `SOLUS_FINGERPRINT_EMBEDDING_ENABLED` (decide), Onshape quota/distribution settings.
- **Apple Developer Program** (Developer ID Application cert, team ID, notarytool API key) and **Windows signing (D9)**.
- **DNS** (Squarespace/Google zone): `api` CNAME → prod ALB, `staging-api` CNAME → staging ALB, `downloads` CNAME → CloudFront, `docs` → docs host, SES DKIM/SPF/DMARC records.

**Gate C:** a checklist in `HUMAN-STEPS.md` with every item ticked and verified by the read-only sweep (§5),
not by assertion.

### Phase D — Pipelines (≈1 week, parallel with C)

- **D-api** (`.gitlab-ci.yml`, tier-1): tag `vX.Y.Z` → build image tagged by SHA → push to prod ECR → `migrate:prod` one-off ECS task (`aws ecs run-task`, wait, fail pipeline on non-zero) → register task defs → update API + worker services → wait for steady state → smoke `/healthz` + `/readyz` → **manual approval gate** before the prod step. Staging keeps auto-deploy on `main`. Add `pip-audit`/`pnpm audit` (ADR-007 promises a dependency audit; it is missing).
- **D-desktop**: release pipeline on the same tag.
  - macOS arm64: built and signed **on a developer Mac** via one `make release-mac` (companion onedir → SolusInput helper → XPC → electron-builder with `notarize: true`, hardened runtime, identities from Keychain/env). GitLab SaaS macOS runners or EC2 Mac (≈$470/mo minimum) are not worth it yet.
  - Windows x64: GitLab SaaS Windows runner (or a dev box) with a `make release-win` equivalent in PowerShell; sign via D9.
  - Linux: CI arm64/x64 AppImage + deb (optional per D3).
  - Every job uploads to `s3://solus-prod-releases/<channel>/<version>/` plus `latest.yml` / `latest-mac.yml`, and writes SHA-256 sums.
- **Auto-update**: wire the already-installed `electron-updater` to the generic provider at `https://downloads.solusforge.com/stable/`; staged rollout via `stagingPercentage`; a `beta` channel for the team.
- **Build-time env guard**: production builds must **fail** if `VITE_API_BASE_URL` is unset or points at localhost (extend `prodAuthGuard.ts`, which already does this for the Supabase vars).

### Phase E — Desktop "just works" (≈1–2 weeks, the largest code phase)

- **E1 — MCP runtime (D4)**: bundled Python 3.12 + offline wheelhouse; first-run provisioning with a progress UI; Windows launchers (`launch.cmd`) for every POSIX fork; stop rsyncing developer `.venv`s into builds (exclude `.venv/` in `build-companion.sh`). Contract/ADR-031 amendment approved in chat first.
- **E2 — Companion validated on macOS arm64 + Windows x64** (only Linux ARM is validated today, per `apps/desktop/docs/companion-packaging.md`).
- **E3 — First-run experience**: detect KiCad / Fusion / etc. and explain what's missing (Guide vs Expert mode per ADR-016); permission prompts for the drive helper (Accessibility, Screen Recording) only when drive is enabled.
- **E4 — Signing correctness**: helper + companion pre-signed with their own identifiers (ADR-041), Solus.app signed + notarised + stapled; verify with `codesign --verify --deep --strict`, `spctl -a -vv`, `stapler validate`.

### Phase F — Website, docs, legal (≈3–4 days, independent — start immediately)

- `/download` page: OS detection, links to `downloads.solusforge.com/stable/…`, checksums, system requirements, "Intel Mac / Linux beta" notes.
- `/privacy-policy`, `/terms-of-service`, `/contact` (the desktop already links to them — `legalLinks.constants.ts:13-15`). Legal text is human/lawyer work; agents build the pages.
- `/auth/confirmed`, `/auth/reset` (from A7).
- Fix dead footer links; replace waitlist CTAs with Download (or gate behind invite — your call).
- `docs.solusforge.com`: Mintlify/Nextra/Docusaurus fed from `docs/` user-facing content; at minimum Getting Started, Connecting tools, Troubleshooting.
- Vercel: move to **Pro** (Hobby forbids commercial use); env vars for the waitlist stay.

### Phase G — Launch verification and cutover (≈3 days)

1. Prod infra up, empty → run migration task → API boots with catalog `pending` → a staff user signs in → `bootstrap-catalog` → restart → `/readyz` all `ok`.
2. Full Cowork QA pass on **signed** builds from `downloads.solusforge.com` on clean VMs/machines (fresh macOS arm64 user account, fresh Windows 11): download → install → sign-up (email confirm lands on our page) → GitHub login → create team → connect GitHub/Onshape/KiCad → SOL turn (long one, > 60 s, proves keepalive) → Stripe checkout (live, refunded) → auto-update from vN to vN+1.
3. Failure drills: kill the API task (circuit breaker), bad migration (pipeline stops before rollout), RDS failover (Multi-AZ), restore a PITR snapshot to a scratch instance.
4. Security subagent audit of the whole deploy surface (IAM policies, SGs, bucket policies, WAF exclusions, secrets, CORS, desktop fuses/signing).
5. Go/no-go checklist signed by both devs → DNS flip of `api.` to the prod target group → monitor 48 h.

---

## 4. Agent orchestration — how to do this accurately, not just quickly

**Principle:** agents write and verify; humans hold every credential and every irreversible button.
Accuracy comes from three mechanisms: _independent verification_ (the agent that writes never certifies
its own work), _executable evidence_ (read-only AWS sweeps and real packaged builds, not assertions), and
_IaC diffs_ (every infra change is a reviewable `terraform plan`).

### Lanes (parallel where file sets are disjoint)

| Lane             | Tickets                               | Execution                                                                            | Personas                                                                                                       |
| ---------------- | ------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| L1 Backend fixes | A2, A3, A5, A6, WS-B6                 | worktree workers on `SOLUSDEV-4xx/<task>`, TDD                                       | `tdd-guide` → `python-reviewer` → `security-reviewer`                                                          |
| L2 Desktop       | A4, A7(desktop), D build guard, E1–E4 | worktree workers; E1 sequential after its ADR                                        | `tdd-guide`, `typescript-reviewer`, `e2e-runner`                                                               |
| L3 IaC           | B1–B8                                 | one worker per Terraform module after the skeleton lands (modules are disjoint dirs) | `architect` (module boundaries), `security-reviewer` (IAM/SG/bucket policy), independent "plan reviewer" agent |
| L4 Pipelines     | D-api, D-desktop                      | sequential, one worker                                                               | `code-reviewer`                                                                                                |
| L5 Web/docs      | F, A7(web)                            | worktree worker, independent of everything                                           | `frontend-design`, `e2e-runner`                                                                                |
| L6 Verification  | §5 sweeps, Gate checks                | read-only agents, fresh context                                                      | `Explore`, `security-reviewer`                                                                                 |

Order: **A1 first and alone** (everything depends on merged `main`), then L1/L2/L3/L5 in parallel, L4
after L3's ECR/ECS exist, Phase G last. Ownership manifests in `.claude/state/ownership/<task>.list`
as the protocol requires; `planner` produces them in Phase 2 for each ticket.

### Accuracy mechanisms

1. **Two-agent rule for infra.** Agent X writes the Terraform; a fresh-context agent Y receives only the
   `terraform plan` output + this document's requirements table and must list every mismatch. Human
   applies only a plan Y passed.
2. **Read-only AWS verification agent.** A dedicated IAM role `solus-agent-readonly` (`ReadOnlyAccess`
   minus `secretsmanager:GetSecretValue`, minus `s3:GetObject` on data buckets) with the AWS CLI
   installed locally. The agent runs `describe-*`/`get-*` + `iam simulate-principal-policy` and diff-checks
   reality against the requirements tables (env var names, SG rules, idle timeout, bucket policies, alarm
   list). This is what would have caught staging's five sequential faults in one pass.
3. **Requirements tables are the spec.** §3's env/secret lists become a machine-checked file
   (`infrastructure/aws/required-config.yaml`) that a test compares against `config.py` Settings fields,
   so a new setting without a deploy entry fails CI. (Prevents this doc going stale the way the README did.)
4. **Real-artifact gates.** No desktop ticket closes on unit tests alone: a packaged, signed build must
   run against staging (CDP-driven by `e2e-runner`, `REMOTE_DEBUGGING_PORT` recipe already exists).
5. **Workflow fan-out for Phase G** (opt-in): one verifier agent per user flow from the Cowork QA file,
   each reporting pass/fail with evidence, then a single synthesis — only if you explicitly ask for a
   multi-agent workflow run.

---

## 5. Read-only verification sweep (run at every gate)

- Image: `docker run` the prod image locally with prod-shaped env (fake secrets) → boots, `/readyz` truthful.
- `aws ecs describe-task-definition` → every name in `required-config.yaml` present, no plaintext secrets in `environment[]`.
- `aws elbv2 describe-load-balancer-attributes` → `idle_timeout.timeout_seconds=300`.
- SG graph matches §B3 exactly; RDS/Valkey `PubliclyAccessible=false`.
- `aws s3api get-bucket-policy / get-public-access-block / get-bucket-versioning` per bucket.
- `iam simulate-principal-policy` for task + execution roles against the exact actions the code uses.
- `curl` probes: `/healthz`, `/readyz`, webhook routes return 4xx (not 404/5xx) without signatures, CORS preflight from `app://solus` allowed and from `https://evil.example` refused.
- Desktop: `codesign`, `spctl`, `stapler`, `signtool verify`, fuse read-back, `latest*.yml` hashes match artifacts.

---

## 6. Monthly cost estimate (us-east-1, on-demand list prices as of late 2026, USD)

Prices are from AWS public list pricing as I know it; confirm in the AWS Pricing Calculator before
committing — they move a few percent a year. Fargate arm64: $0.03238/vCPU-h, $0.00356/GB-h; 730 h/mo.

### Production (Standard posture)

| Item                                       | Sizing                                                                                                          | $/mo                                     |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Fargate API                                | 1 vCPU / 2 GB ×1                                                                                                | 29                                       |
| Fargate worker                             | 1 vCPU / 2 GB ×1                                                                                                | 29                                       |
| Migration task                             | ~5 min per deploy                                                                                               | <1                                       |
| RDS PostgreSQL                             | db.t4g.medium **Multi-AZ** + 50 GB gp3 (+ backups within free allowance)                                        | ~107                                     |
| ElastiCache Valkey                         | cache.t4g.small, 1 node                                                                                         | ~19                                      |
| ALB (prod account)                         | hours + ~5 LCU                                                                                                  | ~25                                      |
| Public IPv4                                | ALB (2) + tasks (~4 incl. staging)                                                                              | ~22                                      |
| WAF                                        | 1 web ACL, 4 rules, low traffic                                                                                 | ~12                                      |
| Secrets Manager                            | ~15 boot secrets + 6 provider keys                                                                              | ~9                                       |
| **Secrets Manager — per connected source** | $0.40 per user OAuth token stored                                                                               | **0.40 × connections** (e.g. 500 → $200) |
| CloudWatch                                 | ~15 GB logs, 15 alarms, a few custom metrics                                                                    | ~15                                      |
| S3 + CloudFront                            | artifacts/CAD small; installers ~250 MB × 3 OS; CloudFront's 1 TB/mo always-free egress covers ~4,000 downloads | ~5                                       |
| ECR, KMS, CloudTrail, GuardDuty            | small account                                                                                                   | ~10                                      |
| **Prod subtotal**                          |                                                                                                                 | **≈ $280** (+ per-connection secrets)    |

### Staging

| Item                                       | $/mo                                         |
| ------------------------------------------ | -------------------------------------------- |
| Fargate API + worker, 0.5 vCPU / 1 GB each | ~29                                          |
| RDS db.t4g.micro single-AZ + 20 GB         | ~14                                          |
| Valkey cache.t4g.micro                     | ~10                                          |
| Own ALB (already exists) + its public IPs  | ~20                                          |
| Logs, secrets, misc                        | ~8                                           |
| **Staging subtotal**                       | **≈ $80** (≈ $45 if stopped nights/weekends) |

### Third-party

| Item                                                     | $/mo          |
| -------------------------------------------------------- | ------------- |
| Supabase Pro (prod; free tier pauses and caps)           | 25            |
| Vercel Pro (Hobby forbids commercial use)                | 20 per seat   |
| SES (auth email)                                         | ~1            |
| Apple Developer Program ($99/yr)                         | ~8            |
| Windows signing (Trusted Signing vs OV/EV cert)          | ~10–40        |
| Sentry (Team; free Developer tier may suffice initially) | 0–26          |
| Docs host (Mintlify free/Nextra on Vercel)               | 0             |
| **Third-party subtotal**                                 | **≈ $65–140** |

### Totals

| Posture                                                                                              | AWS    | Third-party | **Total / mo** |
| ---------------------------------------------------------------------------------------------------- | ------ | ----------- | -------------- |
| **Lean** (single-AZ RDS, no WAF, staging off-hours)                                                  | ≈ $240 | ≈ $65       | **≈ $305**     |
| **Standard** (recommended)                                                                           | ≈ $360 | ≈ $100      | **≈ $460**     |
| Growth (~500 active users: API 2 vCPU/4 GB, RDS t4g.large Multi-AZ, Valkey medium, ~500 connections) | ≈ $750 | ≈ $150      | **≈ $900**     |

**Not included and likely to dominate:** LLM API spend (OpenAI/Anthropic/Google; the routing matrix in
`orchestration/models.yaml` uses all three, and drive uses Opus 5.5 computer-use). It is bounded per
team by the ADR-017/019/024 credit system — make sure the provider-side hard limits are set (Phase C).
Also not included: the existing self-hosted `aws-arm` GitLab runner's EC2 cost.

**Cost watch-outs:** (1) per-connection Secrets Manager at $0.40 each scales linearly — at a few hundred
connections, an envelope-encrypted DB column with one KMS key ($1/mo) becomes far cheaper; ticket it, it
touches the secret-store seam. (2) A NAT Gateway would add ~$35/mo + $0.045/GB; avoided by design.
(3) EC2 Mac for CI is ~$470/mo minimum — build macOS releases on a dev Mac.

---

## 7. Proposed timeline

| Week | Work                                                                        |
| ---- | --------------------------------------------------------------------------- |
| 1    | A1 (merge), decisions D1–D9, F starts, B1 ADR + skeleton + import           |
| 2    | A2–A7 in parallel; B2–B5; C begins (accounts, Apple, Supabase, Stripe live) |
| 3    | B6–B8 applied; D-api; E1 starts; F done                                     |
| 4    | E1–E4; D-desktop + auto-update; staging soak on the new stack               |
| 5    | Phase G verification, drills, go/no-go, cutover                             |

Roughly **five weeks** to a public download, assuming the human-only items (Apple enrolment can take
days; SES production access ~24 h; Windows identity validation days–weeks) are started in week 1.

---

## 8. Decisions recorded (2026-11-07, in-chat)

- **D1:** separate AWS account for production (AWS Organizations). A5 (env-prefixed secret paths) is dropped.
- **D2:** adopt Terraform/OpenTofu, importing console-built staging first. The ADR text is still to be proposed in chat (tier-2) before B1 starts.
- **D3:** launch on macOS arm64 + Windows x64, signed. Intel macOS and Linux follow as beta.
- **D6:** Standard posture: Multi-AZ RDS, WAF, staging always on. About $360/mo AWS (including staging's own ALB, about $20) + about $100/mo third-party, so about $460/mo before LLM spend and per-connection secrets.
