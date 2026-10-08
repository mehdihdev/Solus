# COWORK QA — SOLUSDEV-313: Stripe pipeline support for staff-initiated billing changes

Self-sufficient test plan. Assume you have the running Solus app, this file, and nothing else.
Mark each checkbox PASS / FAIL and note the observed result for every FAIL.

## 0. What this feature is (so you can judge results)

SOLUSDEV-313 is a **backend service layer** plus webhook/gateway changes. There are **no new staff
routes and no new UI** (the staff admin app is SOLUSDEV-314). What a tester can observe:

1. Staff operations (change plan, comp upgrade/remove, limits override, cancel) — exercised through a
   **dev harness** in section 1.3 because no route exists yet.
2. Stripe webhook convergence — overrides survive, replays/out-of-order are safe.
3. **Deleting an account cancels its Stripe subscription** (final invoice, no proration) — testable in the app UI.
4. `PATCH /users/me/subscription` guard (no free trial restarts, no ENTERPRISE self-select).
5. Effective limits shown/enforced everywhere.

Business rules to verify against:

- Stripe is the source of truth for Stripe-backed subscriptions: staff changes happen in Stripe and the
  local row converges **only** via webhook.
- A `limits_override` is merged **per key** over plan limits (`null` = unlimited, absent key falls through)
  and is never written or cleared by billing events.
- Comps: Stripe-backed = 100%-off coupon `solus-comp-once` / `solus-comp-repeating-<N>` / `solus-comp-forever`
  plus a revert schedule (returns to the previous price when the coupon ends). Non-Stripe = local comp with
  expiry (`once` = 1 month, `repeating N` = N months, N 1–36, `forever` = no expiry).
- Account deletion: immediate cancel, **final invoice created, no proration**; the Stripe Customer is NOT deleted;
  deletion never blocked by Stripe being down.

## 1. Required setup

### 1.1 Services and accounts

- [ ] Postgres + Redis running; API migrated to head (`alembic heads` shows exactly `a31300000001`).
- [ ] API, ARQ worker, and desktop app running (`pnpm dev:all`; it also starts `stripe listen` forwarding to the
      local webhook). Confirm the worker log shows the crons `cancel_stripe_subscriptions` (every minute) and
      `expire_comps` (every 15 min).
- [ ] Stripe **test mode** account, restricted API key (write: Subscriptions, Coupons, Subscription Schedules,
      Customers/Invoices read) stored as the `stripe_api_key` secret. Webhook endpoint subscribed to
      `customer.subscription.created|updated|deleted`, `checkout.session.completed`, `invoice.payment_failed`.
- [ ] `stripe_plan_prices` configured for basic/pro × month/year (test-mode prices).
- [ ] Stripe CLI logged in (`stripe listen` running; `stripe events resend <evt_id>` available).

### 1.2 Test users (create via the app signup, verified email)

- **U-trial**: new user, still TRIALING, no Stripe link.
- **U-paid**: user who completed Stripe Checkout (test card `4242 4242 4242 4242`) for BASIC monthly.
- **U-victim**: a second paid user (used only to prove isolation).
- **U-owner**: user who owns a collaborative team with one other live member **M**.

### 1.3 Dev harness for staff operations

Run from `packages/api` with the same env as the API (python snippet; no route exists yet):

```python
# uv run python - <<'EOF'
import asyncio, uuid
from solus_api.billing.admin_operations import AdminBillingOperations
# build session, StripeGateway(secret_store), settings exactly as the app does (see deps.py)
# ops = AdminBillingOperations(session, gateway, settings)
# result = await ops.change_plan(TARGET_USER_ID, plan=PlanType.PRO, interval="month",
#     proration="create_prorations", actor_staff_user_id=uuid.uuid4(),
#     audit_action_id="qa-0001", reason="QA run")
# print(result.to_dict())
# EOF
```

Use a **fresh unique `audit_action_id` per action** (Stripe idempotency keys are derived from it).
Every result has `before`, `after`, `stripe_refs`, `converges_via_webhook`, `noop`.

## 2. Staff operations — flows

### 2.1 change_plan, non-Stripe user (U-trial)

1. `change_plan(U-trial, plan=PRO)` → result `noop=false`, `converges_via_webhook=false`.
   - [ ] `after.plan == "pro"`, `after.effective_limits` equals PRO limits; app Billing/Settings shows PRO limits.
2. Repeat with a NEW audit id and the same plan → [ ] `noop=true`, no duplicate event.
3. `change_plan(..., plan=ENTERPRISE)` on a non-Stripe user → [ ] succeeds locally (limits = unlimited).

### 2.2 change_plan, Stripe-backed user (U-paid)

1. `change_plan(U-paid, plan=PRO, interval="month", proration="create_prorations")`.
   - [ ] `converges_via_webhook=true`; `after` is projected from Stripe; **local row unchanged immediately**.
   - [ ] In Stripe Dashboard (test) the subscription now has the PRO price; proration line items exist.
   - [ ] Within seconds the webhook arrives and the app shows PRO (plan + limits).
2. Same call with `proration="none"` → [ ] no proration invoice items.
3. Same call with `proration="always_invoice"` → [ ] an invoice is created immediately.
4. Missing `interval` → [ ] `invalid_operation` error, nothing changed in Stripe.
5. `plan=ENTERPRISE` on a Stripe-backed user → [ ] `invalid_operation` (no Stripe price).
6. Retry the **same** call with the **same** `audit_action_id` → [ ] no second price change/charge (replay).
7. Same `audit_action_id` with **different** params → [ ] typed `StripeIdempotencyConflictError`.

### 2.3 comp_upgrade

**Non-Stripe (U-trial):**

1. `comp_upgrade(plan=PRO, duration="repeating", months=2)`.
   - [ ] `comp_plan=pro`, `comp_expires_at` ≈ now + 2 months; effective limits = PRO.
   - [ ] User received PRO starting credits **once** (check Credits page / ledger). Replaying the call grants nothing more.
2. `duration="once"` → [ ] expiry ≈ now + 1 month. `duration="forever"` → [ ] `comp_expires_at` null.
3. `months=0`, `months=37`, `months` with `duration="once"` → [ ] each rejected, nothing written.
4. Expire the comp (set `comp_expires_at` to the past in the DB): [ ] effective limits drop to the plan's limits
   **immediately** (read time), and within 15 minutes (or trigger `expire_comps`) the comp fields clear and the user
   gets a notification ("complimentary … access ended").
5. User later checks out through Stripe while comped → [ ] on the new Stripe link the comp is cleared and plan/limits
   come from what they bought (also test: user previously had a CANCELED Stripe subscription, is comped, then buys a
   NEW subscription → comp cleared, limits are the purchased plan's, not the comp's).

**Stripe-backed (U-paid, BASIC):**

1. `comp_upgrade(plan=PRO, duration="repeating", months=3, interval="month")`.
   - [ ] Stripe: price switched to PRO, coupon `solus-comp-repeating-3` attached, **upcoming invoice total = $0**,
         a subscription schedule exists that reverts to the BASIC price after 3 months.
   - [ ] Subscription metadata holds `solus_comp_prev_price` and `solus_comp_plan`.
2. `forever`/`once` variants → [ ] coupon `solus-comp-forever` / `solus-comp-once`; `forever` has no schedule.
3. Call `comp_upgrade` again (already comped) → [ ] previous price metadata is **not** overwritten with the comp price.
4. `change_plan` while comped → [ ] refused (`invalid_operation`, "remove the comp first").

### 2.4 remove_comp

1. Non-Stripe comped user → [ ] comp fields cleared; plan limits apply again.
2. Stripe-backed comped user → [ ] schedule released, price restored to the previous price, coupon removed,
   comp metadata cleared; next invoice is the normal price.
3. User that is not comped (and one with **stale** comp metadata but no `solus-comp-*` coupon) → [ ] `not_comped`
   error; Stripe untouched.
4. Half-finished retry (simulate coupon removal failing, then retry with same `audit_action_id`) → [ ] completes.

### 2.5 set_limits_override

1. `set_limits_override(U-trial, {"max_projects": 99})` → [ ] effective `max_projects` 99, other keys from the plan.
2. `{"max_projects": null}` → [ ] unlimited projects.
3. Create projects beyond the plan cap but within the override → [ ] allowed; beyond override → `plan_limit_reached`.
4. `{"bogus": 1}`, `{"max_projects": -1}`, `{"max_projects": true}`, `{}`, a value above the cap (1,000,000) →
   [ ] each rejected with `invalid_operation`; nothing written.
5. `None` → [ ] override cleared.
6. **Webhook survival (critical):** with an override set on U-paid, trigger plan changes and every event type
   (`stripe trigger customer.subscription.updated`, cancel at period end, resume, payment failure, subscription
   deleted/term end) → [ ] `limits_override` and effective limits per the merge rule are **unchanged** by every event;
   after term end the plan limits clamp to BASIC **underneath** the still-present override.
7. User-facing: `GET /users/me/subscription` shows effective limits and does **not** expose override/comp fields.

### 2.6 cancel_subscription

1. Stripe-backed, `immediate=false` → [ ] Stripe `cancel_at_period_end=true`; app shows the scheduled cancellation after
   the webhook; user keeps access until period end.
2. Stripe-backed, `immediate=true` (default `invoice_now=false`, `prorate=false`) → [ ] subscription canceled in Stripe;
   webhook clamps the user to BASIC limits, user notified "Subscription ended"; override retained.
3. Already-canceled subscription → [ ] treated as success/noop, no error.
4. Non-Stripe, `immediate=true` → [ ] status CANCELED, limits clamp to BASIC, comp cleared, override kept, user notified.
5. Non-Stripe, `immediate=false` → [ ] `unsupported_for_non_stripe`.
6. **Isolation:** run each op against U-trial/U-paid → [ ] U-victim's subscription, limits, comps unchanged.
7. A Stripe-backed op where the stored `stripe_customer_id` does not match the Stripe subscription's customer
   (tamper in the DB) → [ ] `invalid_operation` before any write.

## 3. Webhook convergence, replay and ordering (Stripe test mode)

1. [ ] Resend an already-processed event: `stripe events resend <evt_id>` → no state change, no duplicate notification
       or credit grant.
2. [ ] Resend an **older** subscription event after a newer one → ignored (local state keeps the newer one).
3. [ ] After a staff price change, the subscription event whose `previous_attributes.metadata` shows
       `solus_admin_action_id` changed → the plan-change notification reads "changed by Solus support".
4. [ ] A later customer-initiated change in the Billing Portal (stale admin metadata still on the subscription) →
       notification uses the **normal** wording, not "Solus support".
5. [ ] Malformed/odd payloads (use `stripe trigger` fixtures or a replayed event with fields removed) never produce a
       500 or crash the worker.
6. [ ] Webhook for a user whose account was deleted → HTTP 200, no error.

## 4. Account deletion → Stripe cancellation (UI flow)

Setup: U-paid with an active Stripe subscription (test card).

1. Settings → Delete account (confirm).
   - [ ] Deletion succeeds (204 / app returns to signed-out state) **regardless of Stripe**.
   - [ ] In Stripe Dashboard (test): the subscription is **canceled immediately**; a **final invoice exists**; there is
         **no proration/credit note** for unused time; the **Customer still exists**.
   - [ ] DB: `stripe_cancel_requests` has one row for the customer with `completed_at` set; it contains only Stripe ids.
2. **Stripe down:** stop `stripe`/block network or remove the Stripe key, then delete another paid user.
   - [ ] Deletion still succeeds; row remains with `completed_at` NULL and `attempts` ≥ 1.
   - [ ] Restore Stripe; within ~1–2 minutes (cron) the subscription is canceled and the row completes.
   - [ ] Restart the API with a pending row → startup drain cancels it.
3. **Already canceled** subscription (cancel in Stripe first, then delete the account) → [ ] row completes, no error.
4. **No Stripe customer** (U-trial deleted) → [ ] no `stripe_cancel_requests` row.
5. **Local status CANCELED but Stripe still live** (simulate a missed webhook) → [ ] the live subscription is still
   found by customer and canceled.
6. **Late checkout race:** open a Checkout session for a user, delete the account, then complete the payment in the
   open Checkout tab → [ ] the new subscription is canceled automatically (via webhook tombstone path / cron).
7. **Two subscriptions** on one customer, first cancel fails then a second subscription event arrives → [ ] **both**
   subscriptions end up canceled.
8. **Ownership blocker (self-delete):** U-owner (sole owner of a team with member M) deletes the account →
   [ ] unchanged behaviour: 409 `ownership_transfer_required` listing the team; nothing deleted. (Service-level
   `ownership_transfers` is exercised by automated tests; no UI.)
9. Deleting an account that is **not** a sole owner of any team → [ ] teams/membership/credits/connections cleaned up
   exactly as before this change (compare with a pre-change deletion; credits forfeited, ledger entry present).

## 5. Self-serve `PATCH /users/me/subscription`

1. U-trial: PATCH `{plan: "pro"}` repeatedly → [ ] 200 each time; `expires_at` **never changes** (no trial restart);
   status stays `trialing`.
2. PATCH `{plan: "enterprise"}` → [ ] rejected (422/409); plan unchanged.
3. U-paid (active Stripe) PATCH any plan → [ ] 409 `subscription_change_not_allowed`; plan/status/limits unchanged.
4. Canceled/past-due user PATCH → [ ] 409.
5. Unauthenticated → [ ] 401. User A cannot affect user B's subscription.
6. [ ] The desktop onboarding plan-picker still works for a new trial user (it offers only BASIC/PRO).

## 6. Effective limits enforcement (end to end)

For a user with override `{"max_integrations": 1}` on a PRO plan:

- [ ] Connecting a 2nd integration is blocked with `plan_limit_reached` (override stricter than plan).
- [ ] Accepting a team invite / creating a team / project honours the effective limits (override and comp).
- [ ] BYO tool entitlement follows the override (`byo_paid_tools`).
- [ ] Removing the override restores plan limits immediately.

## 7. Edge cases and failure paths (summary checklist)

- [ ] Stripe unreachable during a staff op → typed retryable error; DB row lock released; retry with the same
      `audit_action_id` succeeds.
- [ ] A staff op that hangs does not hold the user's subscription lock indefinitely (project creation for that user
      resumes after the timeout).
- [ ] Concurrent staff ops on the same user serialise (no lost update).
- [ ] Missing/invalid Stripe key → deletion still works; staff ops raise `BillingUnconfiguredError`.
- [ ] Invalid `audit_action_id` / actor (spaces, email, >64 chars) → rejected before any Stripe call.
- [ ] Reason text never appears in Stripe metadata, API logs, or data-collection events (grep logs and Stripe event
      payloads for a unique reason string).
- [ ] Data-collection: a staff op on a consenting user emits `subscription.admin_changed` with only operation, ids
      (no reason, no email); a non-consenting user emits nothing.

## 8. Cross-feature interactions

- [ ] **Credits:** comp grants PRO credits once; webhook plan grants on a Stripe comp do not double-grant on replay.
- [ ] **Notifications:** subscription ended / canceled / resumed / support-changed / comp-ended render with correct copy.
- [ ] **Teams:** ownership transfer (service-level) makes M the owner; deleting user then leaves cleanly; recipient's
      own team caps are unaffected.
- [ ] **Billing page (SOLUSDEV-152):** shows effective plan/limits and cancel-at bar for staff-canceled users.
- [ ] **Worker:** both new crons run without errors across a 30-minute soak; no duplicate cancels in Stripe.

## 9. Known gaps — report, do not fail the run on these

- Trials are not enforced (`expires_at` is stored only): a TRIALING user keeps trial limits indefinitely (product decision pending).
- Stripe behaviours not verified against live Stripe by automated tests (verify here and record): clearing subscription
  metadata with empty strings; already-canceled / already-released error handling; revert-schedule timing (counts months
  from the start of the **current billing cycle**, not the day the comp was applied); immediate cancel carries no metadata
  (audit trail is the idempotency key only).
- The Billing Portal must **not** allow plan switching for `forever`-comped customers (a forever coupon is not product-restricted).
- The Stripe Customer (email, `solus_user_id` metadata) remains after account deletion — retention policy is an open human decision.
- `stripe_cancel_requests` tombstones are retained indefinitely (no purge job yet).
