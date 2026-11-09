# Production launch — human-only steps

Companion to [`PRODUCTION-LAUNCH-PLAN.md`](PRODUCTION-LAUNCH-PLAN.md). These are the steps an agent **cannot
or must not** do. Each one needs a credential, a legal identity, a payment, a vendor portal, a DNS write,
a push or merge, or an irreversible apply. Agents prepare everything around them: scripts, Terraform plans,
exact values and verification commands.

Decisions so far: separate prod AWS account · Terraform/OpenTofu · signed macOS arm64 + Windows x64 at launch ·
Standard posture.

Legend: ⏳ = lead time outside our control, so start in week 1 · 🔑 = produces a secret: put it straight into
Secrets Manager or the Keychain. Never paste it into chat, `.env` committed files, tickets or docs.

---

## 1. Start this week (long lead times)

| #    | Step                                                                                                                                                       | Lead time                     | Notes                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1  | **Company identity pack.** Gather: legal entity name, registered address, D-U-N-S number, EIN/tax ID, business bank account, public website, support email | days                          | Apple, Stripe, the Windows signing CA and SES all ask for some subset of this. Get a D-U-N-S free from Dun & Bradstreet if you don't have one: up to ~2 weeks.                                                                                                                                                                                                                                                                  |
| 1.2  | ⏳ **Apple Developer Program, enrolled as an organisation** ($99/yr)                                                                                       | 2 days–2 weeks                | Must be the Account Holder. Needs the D-U-N-S number. Do not enrol as an individual: the installer would show a person's name.                                                                                                                                                                                                                                                                                                  |
| 1.3  | ⏳ **Windows code-signing identity** (decision D9)                                                                                                         | days–weeks                    | **A. Azure Trusted Signing** (~$10/mo): Azure subscription → Trusted Signing account → public-trust identity validation. Eligibility is restricted to organisations with verifiable history in certain countries; check yours first. **B. OV/EV certificate** from DigiCert, Sectigo or SSL.com (~$200–500/yr): org validation, then a hardware token or the CA's cloud HSM (private keys can no longer be exported to a file). |
| 1.4  | ⏳ **Create the AWS Organization + prod account**                                                                                                          | hours                         | From the current account `344838028176` (which becomes the management + staging account, or create a clean management account). Turn on **IAM Identity Center** and create SSO users for both devs with MFA. Put **MFA on the root user** of every account and lock the root credentials away.                                                                                                                                  |
| 1.5  | ⏳ **SES production access** in the prod account                                                                                                           | ~24 h after request           | Verify `solusforge.com` (DKIM records, see §4), then request to move out of the sandbox. Describe it as transactional auth email only (sign-up confirmations, password resets) sent via Supabase.                                                                                                                                                                                                                               |
| 1.6  | ⏳ **Stripe live-mode activation**                                                                                                                         | 1–3 days                      | Business details, bank account, statement descriptor (`SOLUS`), support contact, tax settings (decide whether to use Stripe Tax).                                                                                                                                                                                                                                                                                               |
| 1.7  | ⏳ **LLM provider prod orgs: OpenAI, Anthropic, Google AI**                                                                                                | days for tier upgrades        | Separate _prod_ projects with billing set. **Set hard monthly spend caps at the provider** as a backstop to our credit system. Anthropic and OpenAI rate tiers rise with spend history, so request upgrades early. The routing matrix uses all three, and drive uses Opus 5.5 computer-use.                                                                                                                                     |
| 1.8  | ⏳ **Legal documents**: Privacy Policy, Terms of Service, and ideally a DPA for teams                                                                      | 1–2 weeks with a lawyer       | Agents build the pages, not the text. The policy must name the subprocessors: AWS, Supabase, Vercel, Stripe, OpenAI, Anthropic, Google, Brave, Sentry, GitHub/GitLab/Onshape (connectors). The desktop app already links to `/privacy-policy`, `/terms-of-service` and `/contact`.                                                                                                                                              |
| 1.9  | **Support mailbox** (`support@` / `contact@solusforge.com`)                                                                                                | hours                         | Needed by Apple, Stripe, SES, the legal pages and the contact page.                                                                                                                                                                                                                                                                                                                                                             |
| 1.10 | ⏳ **Onshape app distribution**                                                                                                                            | Onshape review can take weeks | If customers outside your Onshape company will use the connector and panel, the OAuth app needs public distribution or App Store listing (setting `onshape_app_distribution`). Check Onshape's review requirements now.                                                                                                                                                                                                         |

---

## 2. Governance and git (unblocks all agent work)

| #   | Step                                                                                                                                                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2.1 | Answer the open decisions in plan §2: **D4** MCP runtime on user machines, **D5** Live Bench at launch, **D7** `app://solus` origin, **D8** trial length (14 days in code vs one month in ADR-024), **D9** Windows signing route.               |
| 2.2 | Approve in chat (tier-2, ADR-032) the concrete ADR texts the agent will propose: **IaC / Terraform**, **ADR-031 amendment** (bundled Python runtime for the forks), and the **ADR-009 note update** (JWKS now exists; asymmetric keys in prod). |
| 2.3 | Create Jira tickets for the phases (the agent can draft them; you file them or let the agent file them via the Atlassian connector once authorised).                                                                                            |
| 2.4 | **Push 319, review, merge to `main`; then push 322, review, merge** (the agent adds the Alembic merge revision on the feature branch first). Agents never push or merge.                                                                        |
| 2.5 | Push every later ticket branch, open the MRs, review and merge them.                                                                                                                                                                            |
| 2.6 | Rotate any secret that ever sat in a shared `.env.mega` or a chat, before prod uses it. Prod gets **fresh** keys for everything.                                                                                                                |

---

## 3. AWS (credentials and applies)

| #    | Step                                                                                                                                                                                                      | Notes                                                                                                                                                                                                                             |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1  | **Install the AWS CLI** and configure SSO profiles `solus-staging` and `solus-prod` on your machine                                                                                                       | There is no `aws` binary on this machine today.                                                                                                                                                                                   |
| 3.2  | **Create the agent's read-only role** `solus-agent-readonly` in both accounts and an SSO permission set for it                                                                                            | Use `ReadOnlyAccess` with explicit **deny** on `secretsmanager:GetSecretValue`, `ssm:GetParameter*`, `s3:GetObject` (data buckets), `kms:Decrypt`. This lets the verification agent check reality without seeing data or secrets. |
| 3.3  | **Diagnose the staging 503** with the agent driving that read-only role, or look in the console yourself                                                                                                  | No healthy target. Probably the boot-time catalog crash or a missing secret; the ECS task's stopped reason and the CloudWatch log will say.                                                                                       |
| 3.4  | **Bootstrap Terraform state**, one time: S3 state bucket (versioned, encrypted) and a DynamoDB lock table in the management account                                                                       | The agent writes the bootstrap; you run it. It is chicken-and-egg, because Terraform cannot create its own backend.                                                                                                               |
| 3.5  | **Run every `terraform apply`** after the plan has been reviewed by a second agent. Start with `terraform import` of the existing staging resources, and require a zero-diff plan before anything changes | Agents never apply. The order is network → data → storage → compute → edge → observability.                                                                                                                                       |
| 3.6  | **ACM certificates in the prod account**: `api.solusforge.com` (or a wildcard) for the ALB, and `downloads.solusforge.com` in us-east-1 for CloudFront                                                    | The existing wildcard cert lives in the staging account and **cannot be shared across accounts**. Add the DNS validation CNAMEs (§4).                                                                                             |
| 3.7  | **Write every prod secret** into Secrets Manager (§8 has the full list)                                                                                                                                   | 🔑 Paste values in the console, or run `aws secretsmanager put-secret-value` from your own shell, never from an agent session.                                                                                                    |
| 3.8  | **Turn on account guardrails**: CloudTrail (org trail), GuardDuty, AWS Budgets alerts (prod at $350 / $450 / $600; staging at $100), Cost Anomaly Detection                                               | Confirm each email subscription.                                                                                                                                                                                                  |
| 3.9  | **Confirm the SNS alarm email subscriptions** when they arrive.                                                                                                                                           |                                                                                                                                                                                                                                   |
| 3.10 | **Enable RDS deletion protection and check backups** in the console after the first apply (Terraform sets them; you verify a manual snapshot works).                                                      |                                                                                                                                                                                                                                   |

---

## 4. DNS (the `solusforge.com` zone at Squarespace/Google)

| Record                      | Type                                         | Value                                                             | When                 |
| --------------------------- | -------------------------------------------- | ----------------------------------------------------------------- | -------------------- |
| ACM validation (prod, ×1–2) | CNAME                                        | from ACM                                                          | 3.6                  |
| `api`                       | CNAME                                        | **prod** ALB DNS name                                             | at cutover (Phase G) |
| `staging-api`               | CNAME                                        | staging ALB DNS name                                              | Phase B              |
| `downloads`                 | CNAME                                        | CloudFront distribution domain                                    | Phase D              |
| `docs`                      | CNAME                                        | docs host (Vercel/Mintlify)                                       | Phase F              |
| SES DKIM ×3                 | CNAME                                        | from SES                                                          | 1.5                  |
| SPF                         | TXT on `@` (or a custom MAIL FROM subdomain) | `v=spf1 include:amazonses.com ~all`, merged with any existing SPF | 1.5                  |
| DMARC                       | TXT `_dmarc`                                 | `v=DMARC1; p=quarantine; rua=mailto:dmarc@solusforge.com`         | 1.5                  |
| Custom MAIL FROM (optional) | MX + TXT on `mail`                           | from SES                                                          | 1.5                  |

Keep TTL at 300 for `api` until a week after launch, so a rollback is fast.

---

## 5. Third-party portals (production registrations)

### 5.1 Supabase (new prod project, separate from dev `jfoyyfaqxppczqmeiwzc`)

- [ ] Create the project in us-east-1 on the **Pro** plan.
- [ ] 🔑 Copy the project URL, anon key, service-role key and JWT secret. **Turn on asymmetric JWT signing keys.**
- [ ] Auth → URL config: Site URL `https://solusforge.com`. Redirect URLs `http://127.0.0.1:53682/auth/callback`, `http://[::1]:53682/auth/callback` and `https://solusforge.com/auth/*`.
- [ ] Auth → SMTP: SES SMTP credentials (create them in SES; 🔑), sender `no-reply@solusforge.com`.
- [ ] Brand the email templates (confirm, reset, magic link).
- [ ] GitHub login: create a **separate GitHub OAuth app for Supabase** (callback `https://<project>.supabase.co/auth/v1/callback`) and paste its id and secret into Supabase.
- [ ] Turn on email confirmation, leaked-password protection, and sensible auth rate limits.

### 5.2 Stripe (live)

- [ ] Create products and prices for BASIC/PRO/ENTERPRISE plus credit packs, or run `ops/stripe_setup.py` **from your own shell** with the live key.
- [ ] Add a webhook endpoint `https://api.solusforge.com/api/v1/webhooks/stripe` with the event set from the billing docs, then 🔑 copy its signing secret.
- [ ] Configure the customer portal (cancellation, plan switching), branding and receipts.
- [ ] After launch: one real purchase, then refund it.

### 5.3 Connector OAuth apps (prod registrations; dev apps keep their localhost URIs)

- [ ] **GitHub OAuth app** (connector): callback `https://api.solusforge.com/api/v1/integrations/github/oauth/callback`. 🔑
- [ ] **GitHub App** (ADR-039): name, permissions, webhook URL `https://api.solusforge.com/api/v1/webhooks/github/app`, webhook secret, and installable by any account. 🔑 Generate the private key. That gives 7 settings in total.
- [ ] **GitLab application** (gitlab.com → Applications): same callback shape with `gitlab`. 🔑
- [ ] **Onshape OAuth app**: callback `…/integrations/onshape/oauth/callback`. Element-right-panel extension Action URL `https://api.solusforge.com/panel?documentId={$documentId}&workspaceId={$workspaceId}&elementId={$elementId}&userId={$userId}`. Webhooks need the public HTTPS origin. 🔑
- [ ] **Brave Search API** subscription. 🔑

### 5.4 Other services

- [ ] **Sentry**: org plus two projects (`solus-api`, `solus-desktop`). 🔑 DSNs.
- [ ] **Vercel**: upgrade the team to **Pro**; check the `solusforge.com` domain binding; set env vars for any new pages.
- [ ] **Docs host** account (if Mintlify) and the `docs` domain.
- [ ] **GitLab**: protect tags `v*`. Create a `production` environment that only maintainers can deploy to (deployment approvals need GitLab Premium; otherwise use a `when: manual` job on protected tags). Set up **AWS IAM OIDC for GitLab** (role trust on `project_path` + `ref_type:tag`) instead of long-lived access keys, and add the masked/protected CI variables.

---

## 6. Desktop release machine(s)

| #   | Step                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6.1 | On the **release Mac (arm64)**: install the Developer ID Application certificate into the login keychain. Run `xcrun notarytool store-credentials solus-notary` with an App Store Connect API key (🔑 .p8, Key ID, Issuer ID). Set `SOLUS_SIGN_IDENTITY` and `SOLUS_TEAM_ID` locally. |
| 6.2 | Run `make release-mac` (the agent builds the target) and check the output: `codesign --verify --deep --strict`, `spctl -a -vv`, `xcrun stapler validate`.                                                                                                                             |
| 6.3 | On the **Windows signing host** (a dev PC or CI runner with access to the token/HSM or the Trusted Signing credentials): run the signed build and check it with `signtool verify /pa`.                                                                                                |
| 6.4 | Upload the release (or approve the pipeline job that does) to `s3://solus-prod-releases/stable/<version>/`.                                                                                                                                                                           |
| 6.5 | Prepare **clean test machines**: a new macOS arm64 user account or VM, and a fresh Windows 11 VM. The QA must run where no dev tools, venvs or `.env` exist.                                                                                                                          |
| 6.6 | On the Mac test machine, grant the drive helper's Accessibility and Screen Recording permissions when prompted. Only a human can approve those OS prompts.                                                                                                                            |

---

## 7. Launch day (Phase G)

| #   | Step                                                                                                                                                                                                                                                                        |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 7.1 | Approve the manual **prod deploy** job: migration task, then the API + worker rollout.                                                                                                                                                                                      |
| 7.2 | **First staff sign-in** on prod with the signed desktop app. Copy your Supabase user id into `SOLUS_STAFF_USER_IDS` and `SOLUS_FIRST_PARTY_PUBLISHER_ID`, run `bootstrap-catalog` (the agent gives you the exact command), and redeploy. `/readyz` should then be all `ok`. |
| 7.3 | Run the Cowork QA pass, or supervise it, on the clean machines (plan §G.2), including a real Stripe charge + refund and an auto-update from vN to vN+1.                                                                                                                     |
| 7.4 | Watch the failure drills: stop the API task, run a deliberately bad migration on staging, force an RDS Multi-AZ failover, restore a PITR snapshot to a scratch instance.                                                                                                    |
| 7.5 | **Go/no-go**: both devs sign off on the checklist.                                                                                                                                                                                                                          |
| 7.6 | **Flip DNS**: point `api` at the prod ALB. Switch the website CTAs from waitlist to Download.                                                                                                                                                                               |
| 7.7 | Watch dashboards and Sentry for 48 h; agree who is on call and how alarms reach your phones.                                                                                                                                                                                |
| 7.8 | Email the waitlist (Google Sheet) once stable. Sending is yours.                                                                                                                                                                                                            |

---

## 8. Prod secret inventory (🔑, all written by a human)

**ECS boot secrets** (`secrets[]`, prod account):

- `database_url` (composed from the Terraform-generated RDS credentials, with `?ssl=require`)
- `supabase_jwt_secret`
- `supabase_service_role_key`
- `redis_url` (`rediss://:<auth>@…:6379/0`)
- `stripe_webhook_secret`
- `sentry_dsn`
- GitHub OAuth client secret
- GitLab client secret
- Onshape client secret
- GitHub App private key and webhook secret
- `SOLUS_TOOLKB_VOTE_SALT` (one value, shared by the API and the worker)

**Runtime SecretStore refs** (`solus/connectors/<ref>`):

- `openai_api_key`
- `anthropic_api_key`
- `google_api_key`
- `brave_api_key`
- `stripe_api_key` (live)

**Off-AWS:**

- Apple notary API key (.p8) and the Developer ID cert (Keychain on the release Mac)
- Windows signing token, HSM or Trusted Signing credentials
- Supabase SES SMTP credentials (stored in Supabase)
- GitLab OIDC needs no stored key
