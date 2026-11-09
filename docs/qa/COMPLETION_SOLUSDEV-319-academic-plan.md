# Completion report — Academic plan (SOLUSDEV-319, ADR-042)

Branch: `SOLUSDEV-319-kicad-embedded-symbol-compare` (shared with other SOLUSDEV-319 work, by request). Commits: 73233065 (ADR), a243b866 (docs), c211804b (backend), 65bf2cb6 + 438d28dd (security review fixes), 9e31e235 (desktop), 69ef938e + bdd866db (Phase 4 fixes + QA). Unpushed.

## What was built

- **ADR-042** (tier-2, approved in-chat 2026-11-08): a free ACADEMIC plan. It requires a proven academic email (separate from the sign-in email), has BASIC limits, grants 1,000 credits a month with no rollover, and lasts 12 months before the user verifies again. Cross-referenced from ADR-017 and ADR-023.
- **API**:
  - Routes: `GET /billing/academic`, `POST /billing/academic/code` and `POST /billing/academic/verify`.
  - `billing/academic.py` holds the service, the monthly grant and the daily sweep.
  - `services/academic_mail.py` sends through SES, with a dev log fallback.
  - Migration `a31900000003`: `academic_verifications`, `academic_code_sends` and `academic_address_claims`, plus widened plan and credit-ledger CHECKs.
  - The spend gate blocks an expired Academic plan with `academic_expired`; purchased credits still unlock it.
  - Stripe webhook guards keep stale events from overwriting an Academic row, and Checkout never carries an Academic expiry over as a Stripe trial.
- **Desktop**: `AcademicPlanCard` is one full-width card below the plan grid with an in-card email → code → done flow. The billing state, current-plan card and data hook all understand Academic.

## Governing docs (updated in this MR)

- `docs/wireflows/billing.md` §Academic plan
- `docs/api/API.md` §2.14 Academic plan
- `docs/schemas/subscriptions.md` §Academic plan
- QA plan: `docs/qa/COWORK_QA_SOLUSDEV-319-academic-plan.md`

## Tests

- **API:** 107 academic tests: routes, credits and sweep, mailer, migration, isolation, abuse limits and webhook guards. 1,085 tests in the billing, gate, SOL and admin suites pass.
- **The one failure,** `test_sol_turn_limits::test_the_default_fixed_part_tracks_what_the_runner_measures` (13,597 > 13,000 tokens), comes from the Onshape tool definitions in 6cab9345, another session's commit. It is not from this work.
- **Desktop:** the full desktop suite passes (6,597 tests).
- **Not run:** a live end-to-end run with SES, and a visual check of the page.

## Decisions under delegated judgment

- **Re-verifying early:** an active plan restarts its year from today, because it needs fresh proof of the address.
- **Claims from other accounts:** an address released by another account (deleted, or moved to a paid plan) passes on its remaining time, not a fresh year.
- **Which credits are spent first:** academic credits count as spent before purchased ones when unspent credits are removed.
- **Daily lockout:** 10 wrong codes a day locks an account out of verification for 24 h.
- **Codes:** 6 digits.
- **Domain list:** `.edu` plus 18 international suffixes, in config.
- **Address forms:** a `+tag` is stripped. Subdomains (`cs.mit.edu` vs `mit.edu`) and alumni domains are treated as different addresses (policy, revisit with abuse data).

## Human gates

- **SES:**
  - Verify the sending domain and request production access.
  - Set `SOLUS_ACADEMIC_EMAIL_SENDER` and give the task role `ses:SendEmail`.
  - Optionally override `SOLUS_ACADEMIC_EMAIL_SUFFIXES`, `SOLUS_ACADEMIC_MONTHLY_CREDITS` and `SOLUS_ACADEMIC_VALIDITY_DAYS`.
- **Migration:** run `alembic upgrade head` (`a31900000003`).
- **Remote:** push the branch and open the MR, then run the Cowork QA pass.

## Known risks and follow-ups

- **No per-IP limiter yet** on `/code` and `/verify`. It needs the real client IP from behind the ALB.
- **No SES bounce or complaint handling** (SNS). It's needed before random-address sends can hurt the sender's reputation.
- **Blocking an owner:** 3+ separate accounts can delay an address owner's verification for an hour. This is the accepted trade-off against mail flooding.
- **Secret rotation:** rotating `SOLUS_SUPABASE_JWT_SECRET` resets address claims and grant keys once. A dedicated key would avoid that.
- **SOL copy:** no Guide-mode version of the `academic_expired` message exists. The SOL client shows the server's Expert text, the same as `trial_expired` today.
