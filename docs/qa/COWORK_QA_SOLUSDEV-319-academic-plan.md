# COWORK QA — Academic plan (SOLUSDEV-319 / ADR-042)

A free **Academic** plan for students, teachers and researchers. A user proves an
academic email address (`.edu`, `.ac.uk`, `.edu.au`, …) with a 6-digit emailed
code. The address is separate from the sign-in email. Their plan becomes
**Academic**: Basic limits (4 integrations, 3 projects, 2 teams), 1,000 credits
every month (unspent credits don't carry over), valid for 12 months, then verify
again.

On the Billing page, Academic is **not** a fourth column next to Basic / Pro /
Enterprise. It is one full-width card directly under that row and above
**Buy credits**. Verification happens inside that card.

Legend: ✅ pass · ❌ fail · ➖ blocked/NA

## Required setup state

- [ ] API migrated to head (`alembic upgrade head` → revision `a31900000003`) and
      running, with the desktop app (`pnpm dev:all`) signed in.
- [ ] **Email delivery**, one of:
  - Dev (no SES): leave `SOLUS_ACADEMIC_EMAIL_SENDER` unset with `SOLUS_APP_ENV=dev`.
    The code is **logged by the API** (`solus.billing.academic_mail`, line
    "dev: academic verification code for … is NNNNNN"). Read it from the API log.
  - Staging: `SOLUS_ACADEMIC_EMAIL_SENDER` = a verified SES sender,
    `SOLUS_AWS_REGION` set, SES out of sandbox (or the test inbox verified in SES).
- [ ] Two test accounts: **A** and **B**. For eligibility tests, a third account
      **C** with a live Stripe test subscription (Basic or Pro via Checkout,
      Stripe test card 4242…).
- [ ] Two test academic inboxes you can read (or dev logs): e.g. `qa1@<school>.edu`,
      `qa2@<school>.ac.uk`.
- [ ] DB access (psql) for the cron and expiry checks: tables `subscriptions`,
      `academic_verifications`, `academic_code_sends`, `credit_ledger`, `data_events`.

---

## Flow 1 — Layout

1. Open **Billing** as account A (local trial).
   - [ ] Plans row still shows exactly three cards: Basic, Pro, Enterprise.
   - [ ] Below the row, one full-width **Academic** card with a **FREE** tag.
   - [ ] Card text: "Free for students, teachers and researchers." and
         "Basic limits · 1,000 credits every month · verify once a year".
   - [ ] Hint under the email field names `.edu, .ac.uk, .edu.au and similar`.
   - [ ] **Buy credits** is below the Academic card.
   - [ ] Narrow window: the card stays full width and readable; nothing overflows.

## Flow 2 — Verify (happy path)

1. Type `qa1@<school>.edu` and click **Send code**.
   - [ ] Card switches to "We sent a 6-digit code to qa1@<school>.edu. It expires in 15 minutes."
   - [ ] Focus is in the code field. **Resend code (60s)** is disabled and counts down.
   - [ ] One email arrives (or one dev log line). It contains the code and no
         other personal data. The subject does not contain the code.
2. Type the code and click **Verify** (or press Enter).
   - [ ] Message: "You're on the Academic plan — 1,000 credits are in your account."
   - [ ] Within a few seconds the page updates: current-plan card says
         **Academic plan · ACTIVE**, rows **Free until** {date one year out},
         **Next charge** "None — Academic is free". No Change plan / Cancel plan buttons.
   - [ ] Academic card shows "Verified qa1@<school>.edu · free until {date}" and **CURRENT PLAN**.
   - [ ] Credits went up by 1,000.
   - [ ] DB: `subscriptions.plan = 'academic'`, `status = 'active'`, `limits` = Basic's.
         `credit_ledger` has one `academic_grant` of 1000.
3. Plus addressing: sign-up variants map to one address.
   - [ ] Sending to `QA1+anything@<School>.edu` emails `qa1@<school>.edu`.

## Flow 3 — Code errors

1. Send a code, then type a wrong 6-digit code and Verify.
   - [ ] "That code didn't match — 4 tries left." Repeat: the count goes down to 0.
   - [ ] After 5 wrong tries, even the right code gives "Too many wrong codes. Wait a while, then send a new one." A further Verify says "That code can't be used anymore. Send a new one."
2. Letters and spaces in the code field are dropped; **Verify** stays disabled until 6 digits.
3. Wait 15 minutes (or set `academic_verifications.code_expires_at` to the past), then Verify.
   - [ ] "That code can't be used anymore. Send a new one."
4. **Use a different email** returns to the email step with the address prefilled.

4. Daily budget: after 10 wrong guesses in a day (spread across several codes), a fresh code with the
   right digits is still refused with the "Too many wrong codes" message until 24 h pass.

## Flow 4 — Address and rate limits

1. Enter `qa@gmail.com` → **Send code**.
   - [ ] "That address isn't on our list of academic domains. Use your school email." No email sent.
2. Try each of: `ada@edu`, `ada@mit.edu.evil.com`, `"ada"@mit.edu`, `ada <x@mit.edu>`.
   - [ ] Each is refused; no email sent.
3. Click **Resend code** before 60 s have passed (via a second Send).
   - [ ] "Too many codes requested. Try again in a minute."
4. From one account, send more than 3 codes to the same address within an hour
   (wait out the 60 s cooldown between them).
   - [ ] The 4th is refused with the rate-limit message.
5. From account B, send 3 codes to account A's not-yet-verified address; then from A send one.
   - [ ] A's send still goes through (one account cannot lock the owner out).

## Flow 5 — One address, one account

1. A has verified `qa1@<school>.edu` (Flow 2). As B, send a code to the same address and verify it.
   - [ ] "That address is already verified on another Solus account." B stays on its plan.
2. Expire A's academic plan (DB: set `academic_verifications.expires_at` and
   `subscriptions.expires_at` for A to yesterday). Repeat step 1 as B.
   - [ ] B verifies; A's row no longer holds the address.

3. Account deletion does not reset the address. Verify `qa2@<school>.ac.uk` as A, note the
   **Free until** date, delete account A (Settings → Account), sign up as a new account and verify
   `qa2@<school>.ac.uk` in the same month.
   - [ ] The new account is Academic with the **same** Free until date (not a new year).
   - [ ] No second 1,000-credit grant this month.
4. A holder who upgraded to Pro releases the address: another account can verify it.

## Flow 6 — Eligibility

1. As C (live Stripe subscription), open Billing.
   - [ ] Academic card says "To switch to Academic, cancel your paid plan in Manage billing first. You keep it until the period ends." No form.
2. Cancel C's subscription in the Stripe portal and let it end (or use Stripe test clocks).
   - [ ] Once the plan shows **canceled**, the form appears and verification works.
         C keeps its Stripe customer (credit packs still purchasable).

## Flow 7 — Upgrading from Academic

1. As an Academic user, click **Subscribe · Monthly** on Pro and pay with a test card.
   - [ ] Checkout does **not** show a year-long free trial carried over from Academic.
   - [ ] After return: plan is **Pro**; the Academic card no longer says CURRENT PLAN.

## Flow 8 — Monthly credits and expiry (cron)

1. Run the daily sweep manually (`academic_sweep` ARQ job, or call
   `sweep_academic` in a Python shell) in a new month. Simulate this by moving
   the user's `academic_grant` ledger row's `attrs.month`/`created_at` back one month.
   - [ ] Unspent credits from last month are removed (an `adjustment` row; never below zero).
   - [ ] When the plan expires, that month's unspent academic credits are removed as well.
   - [ ] A new 1,000 `academic_grant` is added. Running the sweep again adds nothing.
   - [ ] Purchased pack credits are not removed.
2. Expire the plan (set both `expires_at` columns to the past), run the sweep.
   - [ ] One notification "Academic plan ended". Running again sends no second one.
   - [ ] Billing banner: "Academic plan ended {date} — verify your academic email again or choose a plan".
         Current plan chip **EXPIRED**, row **Ended** {date}. The Academic card shows the form prefilled.
   - [ ] Ask SOL a question: refused with "Academic plan ended. Model features paused — verify again in Billing."
         Projects, sync and other features still work.
   - [ ] Buy a credit pack: SOL works again.
   - [ ] Verify again: plan is live, credits granted for this month (once).

## Flow 9 — Failure and degraded paths

1. Stop email delivery (staging: unset the sender and restart with `SOLUS_APP_ENV=staging`).
   - [ ] Send code shows "We can't send verification emails right now. Try again later."
2. Make `GET /api/v1/billing/academic` fail (stop the API briefly while the page is open, then reload).
   - [ ] Academic card shows "Academic verification is unavailable right now."; the rest of Billing degrades as before.
3. Stripe unavailable (`summary.stripe_status = unavailable`).
   - [ ] Academic verification still works (it does not depend on Stripe).
4. Offline: Billing shows the offline card; no Academic card.

## Flow 10 — Isolation and data events

1. As B, `GET /api/v1/billing/academic` while A has a pending code.
   - [ ] B sees `state: none`, no pending address. B cannot verify with A's code (`409 no_pending_code`).
2. With data-collection consent on, check `data_events`.
   - [ ] `billing.academic.code_sent` / `verified` carry only `{domain}`; `failed` only `{reason}`; no full address, no code.
3. API logs contain no codes outside dev (the SES mailer never logs the code).

## Cross-feature checks

- [ ] Plan limits: an Academic user can create 3 projects, a 4th is blocked with the normal plan-limit message.
- [ ] Invites: inviting an Academic user who is at their team limit is blocked (invitee's own limits, ADR-023).
- [ ] Settings → Plan section shows "Academic".
- [ ] Usage panel in SOL shows the credit balance including the monthly grant.
