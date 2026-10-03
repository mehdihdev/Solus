# Human steps — HTTPS front door and everything blocked behind it

The running list of things an agent cannot do: buying a domain, adding DNS records, writing
secrets, and registering redirect URIs in a vendor's developer portal. Everything else in
`https-front-door.sh` is automated and idempotent.

Account `344838028176`, region `us-east-1`.

---

## ✅ RESOLVED — domain and secrets

- Domain is **solusforge.com**, confirmed on Google Cloud DNS
  (`ns-cloud-a{1..4}.googledomains.com`). The earlier `solus.dev` in the repo is a different,
  parked domain — see the note under "repo references" below.
- `solus/staging/supabase` exists with key `jwt_secret`; `solus/staging/db` now has `database_url`.
  `ecsTaskExecutionRole` is `allowed` on both (verified with `iam simulate-principal-policy`).
- Task definition `solus-api:3` registered with the correct `SOLUS_*` names and the service pinned
  to it.

### ⚠️ Repo references to `solus.dev` (not urgent, but decide)

`cspConnect.test.ts` and `BillingScreen.tsx` mention `solus.dev`; those are cosmetic. **But
`fingerprint.solus.dev` is pinned into a uuid5 namespace** (`5303bedc-ab6d-5aed-927f-b8c897c5e801`).
That is a hash input: changing it repartitions fingerprint identity for every existing row. **Leave
it.** It is an opaque namespace seed, not a hostname anyone resolves.

---

## ✅ RESOLVED — certificate issued, HTTPS front door live

Certificate `a1709576-6966-4c1c-a7de-d68a29c257be` is **ISSUED** (both `solusforge.com` and
`*.solusforge.com` validated SUCCESS). HTTPS:443 listener added with TLS 1.3 policy; HTTP:80 now
returns `301` to HTTPS. Verified against the ALB:

```
ssl_verify=0    subject=CN=solusforge.com    issuer=Amazon RSA 2048 M04
notBefore=Aug  8 2026    notAfter=Feb 21 2027
```

SNI for `api.solusforge.com` already works off the wildcard. The ALB currently answers `503` because
no backend target is healthy — see BLOCKER 4.

---

## ⛔ BLOCKER 3 — add the `api` record in Squarespace

The last DNS step. `api.solusforge.com` must point at the ALB. Squarespace cannot do an ALIAS to an
AWS resource, so use a **CNAME** (fine here — it is a subdomain, not the apex):

| Field | Value |
| --- | --- |
| Type | `CNAME` |
| **Host** | `api` |
| **Data** | `solus-sload-balancer-1236877300.us-east-1.elb.amazonaws.com` |
| TTL | 300 (or the default) |

Squarespace auto-appends the zone, so Host is just `api` — **not** `api.solusforge.com`.

Verify:

```sh
dig +short api.solusforge.com          # -> the ALB name, then A records
curl -i https://api.solusforge.com/healthz
```

---

## ✅ STAGING IS UP — `https://api.solusforge.com/healthz` returns 200

```
HTTP/2 200      {"data":{"status":"ok"}}
/readyz         {"status":"ok","checks":{"database":"ok","redis":"not_configured","queue":"not_configured"}}
http://api...   301 -> https
```

Fifth and final boot fault was the artifact store. Fixed in `solus-api:5`:

- `SOLUS_ARTIFACT_S3_BUCKET=solus-staging-artifacts`
- **a TASK role** — `solus-staging-task-role`. There was none at all (`taskRoleArn: null`). This is
  not the same thing as the execution role: the execution role pulls the image and injects
  `secrets[]` at container start, but it is **not** the identity boto3 uses inside the process. So
  the task role is what S3 needs — and also what the runtime connector secret store needs, which
  would have been the *sixth* fault the moment anyone connected a source.
- Policy: `s3:GetObject/PutObject/DeleteObject` on `…/solus-staging-artifacts/*`, `s3:ListBucket` on
  the bucket, plus Secrets Manager on `solus/connectors/*` (the runtime prefix). All verified with
  `iam simulate-principal-policy`, not assumed.
- Deployment circuit breaker **re-enabled** (`enable=true, rollback=true, minimumHealthyPercent=100`)
  and the target confirmed still healthy afterwards.

---

## 🔎 THE FULL AUDIT — why we hit five faults one at a time, and what is left

Each fault was only visible after fixing the one beneath it: wrong env var names → no composed DSN →
no `?ssl=require` → wrong password → no artifact store. Here is the whole surface at once.

**Important: the audit had to run against `origin/main`, not the feature branch.** The deployed
image is built from `main`, which is 6 commits ahead here and contains
`storage/artifact_store.py` — a module that does not exist on this branch at all. Auditing the
working tree would have missed the very fault we were chasing.

### Every way the deployed app can REFUSE TO BOOT — there are exactly three, all now satisfied

| Refusal | Trigger | Status |
| --- | --- | --- |
| `Settings()` | `supabase_jwt_secret` is the **only** field in `config.py` with no default | ✅ wired |
| `build_secret_store` | no secret store configured and `app_env != "dev"` | ✅ satisfied by `SOLUS_AWS_REGION` |
| `build_artifact_store` | no artifact store configured and `app_env != "dev"` | ✅ fixed in `solus-api:5` |

Derived by walking every builder `create_app` calls at startup (`build_engine`,
`build_sessionmaker`, `build_secret_store`, `build_supabase_admin`, `build_jwks_client`,
`build_artifact_store`, `build_registry`) and checking each for `raise`. Only two raise, plus
pydantic's own required-field check. **There is no fourth boot refusal.**

### What is absent but does NOT block boot — these fail at RUNTIME instead

These are the next class of surprise. None stops the container starting; each silently disables a
feature until someone uses it.

| Missing | Consequence |
| --- | --- |
| `SOLUS_GITHUB_CLIENT_ID` / `_SECRET` | GitHub connect fails at OAuth start |
| `SOLUS_GITLAB_CLIENT_ID` / `_SECRET` | GitLab connect fails at OAuth start |
| `SOLUS_SUPABASE_URL` / `_SERVICE_ROLE_KEY` | account deletion removes local data but does **not** revoke the Supabase session or delete the auth user |
| `SOLUS_STRIPE_WEBHOOK_SECRET` | billing webhook returns 503; no live billing |
| `SOLUS_SENTRY_DSN` | no error reporting |
| `SOLUS_REDIS_URL` (empty) | degraded mode — no worker, no scheduled resync, no debit reconciliation. Documented and accepted for this cycle |

### ⚠️ The one that lands when this branch merges

`main` has no Onshape connector yet. Merging SOLUSDEV-96 adds **`SOLUS_ONSHAPE_CLIENT_ID`** and
**`SOLUS_ONSHAPE_CLIENT_SECRET`**, and without them Onshape connect fails at OAuth start with
`oauth_not_configured` — the same shape as the GitHub/GitLab gap above, and the first thing anyone
will try on staging after the merge. Register the app, then add both (as `secrets[]`, not
`environment[]`) in the same change that merges the branch.

---

## ⛔ BLOCKER 5 — OAuth redirect URIs (register after the origin exists)

The callback is built as `{public_api_base_url}/api/v1/integrations/{provider}/oauth/callback`
(`routers/integrations.py:76`). Register **both** — keep localhost so local development keeps
working:

**Onshape** — dev portal → your OAuth application → Redirect URLs:

```
https://api.solusforge.com/api/v1/integrations/onshape/oauth/callback
http://localhost:8000/api/v1/integrations/onshape/oauth/callback
```

**GitHub / GitLab** — same shape, substituting the provider segment.

**Autodesk APS** — only if a cloud-side Fusion integration is ever built. CAD-02 talks to the
customer's own local Fusion server over loopback and needs **no** redirect URI.

Redirect-URI _validation_ needs no change: `integrations.py:80` already allows `localhost`,
`127.0.0.1`, and whatever host `public_api_base_url` names.

---

## 📋 Environment values to set (I must not edit `.env*` — H1)

Once the origin exists:

| Variable                        | Where                | Value                                                                  |
| ------------------------------- | -------------------- | ---------------------------------------------------------------------- |
| `SOLUS_PUBLIC_API_BASE_URL`     | ECS task definition  | `https://api.solusforge.com`                                           |
| `SOLUS_CORS_ORIGINS`            | ECS task definition  | keep the localhost dev origins, and add the panel origin when A7 lands |
| `VITE_API_BASE_URL`             | desktop build env    | `https://api.solusforge.com/api/v1`                                    |
| `SOLUS_COMPANION_URL`           | desktop main process | `wss://api.solusforge.com/api/v1/projects/{project_id}/bridge`         |
| `SOLUS_COMPANION_ALLOWED_HOSTS` | desktop main process | `api.solusforge.com,localhost,127.0.0.1`                               |

### ⚠️ The bridge is more broken than "pointed at the old origin"

`SOLUS_COMPANION_URL` is set **nowhere** — not in the desktop main process, not in any env example.
And the companion enforces two rules (`companion/config.py:372-387`):

1. the scheme must be `wss://` (only localhost may use `ws://`), and
2. the host must appear in `SOLUS_COMPANION_ALLOWED_HOSTS`, which defaults to
   `localhost,127.0.0.1` — otherwise it refuses to dial, because that is where the bearer token
   would be sent.

So the bridge cannot reach staging today at all. HTTPS is exactly what unblocks it, but the new host
**must** be added to that allowlist or every session fails closed. That is deliberate: the allowlist
is what stops a redirected companion from posting the user's token to an attacker.

---

## ✅ Already done, no action needed

- `solus-staging-alb-sg` created; ALB moved onto it; 80 and 443 open to the internet.
- `solus-staging-services-sg` now allows **8000 only from the ALB's group**, and the ECS service was
  moved onto it. That group was already trusted by `solus-staging-rds-sg` — it existed and had
  simply never been attached, which is why the API had no route to its database.
- `assignPublicIp` stays **ENABLED** deliberately: there is no NAT gateway and no VPC endpoints, so
  the task needs a public IP to pull from ECR and reach Secrets Manager and CloudWatch. It is not an
  exposure — the security group is what makes the task unreachable. Removing it would require a NAT
  gateway (~$32/month) and buy nothing.
- Target group `sol-staging` already health-checks `/healthz` on 8000; no change needed.

## Cost

ACM certificate $0 · Google Cloud DNS zone ~$0.20/month · ALB already provisioned and billed ·
no new compute. The only new spend is the domain itself.

---

## 📋 A7 panel — what a human owes (SOLUSDEV-96, this branch)

### 1. Register the panel in the Onshape app (blocks §5 of `docs/qa/COWORK_QA_onshape_fusion.md`)

In the Onshape developer portal, on the same OAuth application as the connector, add an
**Element right panel** extension:

| Field    | Value                                                                              |
| -------- | ---------------------------------------------------------------------------------- |
| Location | `Element right panel`                                                              |
| Action URL | `https://api.solusforge.com/panel?documentId={$documentId}&workspaceId={$workspaceId}&elementId={$elementId}&userId={$userId}` |

**No DNS record and no CORS change are needed.** The panel is served from the API origin on purpose:
the page and every route it calls are same-origin, so `SOLUS_CORS_ORIGINS` does not have to be
widened for it. A separate `panel.` host would have bought isolation from a JSON-only origin and
cost a cert SAN, a DNS record, and a CORS entry — a bad trade.

`{$userId}` in that URL is **not** a credential and Solus never accepts it as one — see the ADR
below. It is there so the panel can pick which stored token to send when one machine has two Onshape
accounts.

### 2. `SOLUS_PANEL_FRAME_ANCESTORS` — only if Onshape frames from another host

Defaults to `https://*.onshape.com https://onshape.com`, which covers cad.onshape.com and
enterprise subdomains. An enterprise customer on a vanity domain needs it widened; nobody else does.

### 3. ⚠️ An ADR is needed (tier-2 — I must not write DECISIONS.md)

**Proposed title:** *Panel tokens are a second, disjoint credential class; `{$userId}` is never
identity.*

Text to consider:

> The Onshape panel authenticates with a Solus-minted bearer token obtained through a device-code
> pairing the user approved from an authenticated Solus session. This is a second credential class
> alongside Supabase JWTs, and the two namespaces are disjoint by construction: a panel route hashes
> its bearer and looks the digest up in `panel_bindings`, so a JWT simply misses, and nothing on the
> panel path can reach account provisioning.
>
> The `{$userId}` Onshape appends to the panel URL is **never** accepted as an authentication input.
> It is unsigned, supplied by a third party, and visible to anyone sharing a document — treating a
> match as access would let a collaborator read the owner's graph. Its only role is client-side:
> choosing which stored token to send.

Without this ADR a reviewer will read the second bearer path as a CLAUDE.md §7 violation. It is
enforced by `packages/api/tests/test_panel.py`, whose last three tests are structural rather than
behavioural: a dependant-tree walk, a source grep ratchet, and a route-enumerating test that fires a
valid-but-unknown Supabase JWT at every panel route and asserts the user count is unchanged.

---

## 📋 CAD-03 / CAD-04 — two vendoring decisions I must not make

Both fork targets were assessed at pinned commits with LICENSEs re-read in clones. Both are MIT.
Neither is vendored: an `upstream/` import cannot ship without two human sign-offs, so importing
20 MB now would only enlarge a diff you have to review anyway.

### 1. SolidWorks — `andrewbartels1/SolidworksMCP-python` @ `34a21fe` — **blocked, not by licence**

**48 of its 112 tools can report success for work that never happened.** `check_interference`
returns `"interference_found": False` when the adapter cannot perform the check;
`get_material_properties` always returns "Steel, Plain Carbon" regardless of the part; `save_file`
reports saved with a hardcoded 2024 timestamp. Evidence:
`integrations/mcp/solidworks/FABRICATED_DATA_AUDIT.txt`, regenerable with
`python3 integrations/mcp/tools/audit_fabricated_tools.py <clone>`.

The ticket assumed about eight. Options and my recommendation are in
`integrations/mcp/solidworks/PROVENANCE.md` §6 — briefly: **A** don't vendor, **B** vendor and strip
48, **C** write a thin Solus server using the upstream COM adapter as MIT-licensed reference.
I recommend **C**, with **A** as the interim, because B inherits a codebase whose default idiom is
the thing being stripped.

### 2. AutoCAD — `U-C4N/Autocad-MCP` @ `abc2a82` — **clean, and the shape of CAD-04 changed**

0 of 155 flagged by the same audit. More useful: its backend is **`ezdxf`**, which reads
`.dxf`/`.dwg` **without an AutoCAD licence**. That would put AutoCAD data in the graph for users who
have no seat — removing the BYO-licence gate from the ingestion path entirely.

Options in `integrations/mcp/autocad/PROVENANCE.md` §5. I recommend **B (depend on `ezdxf`
directly)** first, fork later if driving a live AutoCAD session is wanted.

**Also worth reading before anyone writes the connector**: §4 of that file. AutoCAD is not a 3D
assembly — block definitions are entities, block *inserts* are instance relations (40 inserts of one
bracket is one part), block attributes carry the manufacturer part number the fingerprint matcher
wants, and xrefs are the only `depends_on` available. There is **no mass and no volume**; anything
expecting them from a mechanical source must tolerate absence rather than default, since a defaulted
mass is the same class of lie as the SolidWorks finding.

## 📋 SOLUSDEV-312 — Redis, CAD store bucket and Onshape webhooks (ADR-037 / ADR-038)

**Redis (ElastiCache)** — required for live fan-out across API tasks, the ARQ worker, the quota meter and the CAD store index.
- Node-based Redis/Valkey, **cluster mode disabled** (live channels use `PSUBSCRIBE solus:live:*`), same VPC/private subnets as ECS, in-transit encryption + AUTH token.
- Parameter group `maxmemory-policy = noeviction` (ARQ queue + CAD index must not be evicted).
- SG: inbound 6379 only from the API and worker task SGs.
- Store `rediss://:<token>@<primary-endpoint>:6379/0` in Secrets Manager; inject as `SOLUS_REDIS_URL` via the task definition `secrets` block on **both** API and worker.
- Deploy the ARQ worker service (SOLUSDEV-144): same image/env, command `uv run arq solus_api.worker_main.WorkerSettings`.

**CAD store bucket** (`SOLUS_CAD_STORE_S3_BUCKET`) — a dedicated bucket, never the artifact bucket (artifacts expire after 1 h).
- Block Public Access: all on. **Versioning OFF** (or a 1-day noncurrent-version expiry) — with versioning, revocation deletes would only add delete markers and old CAD would survive.
- Bucket policy: deny any request without `aws:SecureTransport`; deny `s3:PutObject` without `s3:x-amz-server-side-encryption`.
- Default encryption SSE-S3 (the app also sends `AES256` on every put); optionally SSE-KMS with a dedicated key.
- Task role (API + worker): `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on `arn:aws:s3:::<bucket>/cad/*`; `s3:ListBucket` on the bucket with condition `s3:prefix` = `cad/*`.
- Optional cost guard: lifecycle rule expiring `cad/` objects after e.g. 400 days (re-exported on demand).

**Webhooks** — `SOLUS_PUBLIC_API_BASE_URL` must be the public **HTTPS** API origin (the ALB/front door). Onshape posts to `/api/v1/webhooks/onshape/{source_id}/{token}`; keep that path reachable from the internet.

**Migration** — run `alembic upgrade head` (adds `cad_purge_requests`, revision `a38000000001`).
