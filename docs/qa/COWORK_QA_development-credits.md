# Development credit exception — SOLUSDEV-261

Authority: ADR-024 approved development exception; architecture/development-credits.md,
wireflows/development-credits.md, API.md development credit section. Cost accounting
continues through the existing model-orchestration contract.

## Setup

Use the local development checkout and an authenticated verified Solus account.
Run the normal dependencies with `pnpm dev:all`. To opt in locally, create the
ignored `.solus-dev-credits.json` at the checkout root:

```json
{"user_ids": ["<your Solus user UUID>"]}
```

The UUID is the API's `users/me` identity, not the email or team ID. Only exact
`SOLUS_APP_ENV=dev` allows the exception. Shell variable
`SOLUS_DEVELOPMENT_UNLIMITED_CREDIT_USER_IDS` (comma-separated UUIDs) takes
precedence, including an explicitly empty value to disable. When the local JSON
is absent, normal Settings environment loading remains intact. Restart the
launcher after changing the file. Remove the UUID and restart to revoke.
No Stripe purchase or ledger grant is performed. Real provider charges continue.

## Acceptance paths

1. [ ] With an allowlisted account and depleted balance, open Billing. Expect
   “Unlimited (development)” in the Credits field.
2. [ ] Open SOL. Expect the same label and real measured usage, with no credit
   exhaustion warning or finite-allowance bar.
3. [ ] Send “Reply SOL is ready; no tools.” Expect a completed response despite
   the depleted balance. Confirm normal usage debit/cost logging remains present.
4. [ ] Sign in as a second, unlisted account. Expect finite balance/ordinary
   credit and trial gates. The API must never reveal the allowlist.
5. [ ] Remove the local UUID and restart. Refresh Billing and SOL. Expect the
   ordinary finite display and admission checks again.
6. [ ] In an isolated test deployment, use `app_env=production` or `staging` with
   the same allowlist. Expect `unlimited=false` and normal admission checks.
7. [ ] Supply malformed JSON, unknown keys or invalid UUIDs to the local file.
   Expect startup refusal without executing configuration text.
8. [ ] Leave the local file absent. Expect no automatically enabled accounts.
9. [ ] Request an integration write. Expect the normal approval card; do not
   approve solely as part of this credit test. Frequency/loop limits still apply.

## Observed verification (2026-09-12/13)

The running developer account displayed Unlimited (development) in both Billing
and SOL. Its measured usage stayed at 1,006 credits; a fresh SOL request returned
“SOL is ready.” without calling tools or changing integrations. Backend regression
checks cover actual debit/idempotence, trial/balance checks, frequency enforcement,
current-user isolation and production/staging refusal. No hardware verification.
