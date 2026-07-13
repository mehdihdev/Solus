# COWORK QA — Billing verification checkpoint (SOLUSDEV-83 / SOLUS-FND-03)

Test plan for the money-moving path: idempotent Stripe webhook → DB sync,
atomic/idempotent credit deduction, and the free-trial cost cap. This is mostly
a backend/API + DB checkpoint (there is no customer-facing checkout UI yet —
that surface stays deferred). Run against a running API with a Postgres DB.

## Required setup state

- [ ] API running (`make dev-api`) with Postgres (`make db-up`), migrated to head
      (`alembic upgrade head`).
- [ ] For the webhook: `SOLUS_STRIPE_WEBHOOK_SECRET` set. Sign test events with
      the Stripe CLI (`stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe` + `stripe trigger …`) or a script that computes the `Stripe-Signature`
      HMAC. `SOLUS_STRIPE_PACK_CREDITS` maps a Stripe price id → credits, e.g.
      `{"price_123":5000}`.
- [ ] `SOLUS_TRIAL_CREDIT_GRANT` = the bounded trial cap (default 1000,
      provisional).
- [ ] A bearer token for one test user (see the API-implementation.md dev-JWT
      recipe). DB access (psql) to observe `credit_ledger` / `credit_balance` /
      `subscriptions` / `processed_stripe_events` / `pending_credit_debits`.

Legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Flow 1 — Trial credit grant + cost cap

1. First `GET /api/v1/users/me` as a fresh user (auto-provisions).
   - [ ] DB: a `credit_balance` row = `SOLUS_TRIAL_CREDIT_GRANT`; a
         `credit_ledger` `trial_grant` row of the same amount.
2. Re-provision path is idempotent: the grant is keyed `trial-grant:<user_id>`.
   - [ ] Re-triggering provisioning never double-grants (balance unchanged).
3. Pre-flight gate (verify via a small script calling
   `cost.has_sufficient_credits(user_id, estimate, session=…)`, or once a
   model-backed endpoint exists): returns True while balance covers the
   estimate, False at balance 0.
   - [ ] Blocks paid operations at the cap (balance 0 → False).

## Flow 2 — Credit deduction: atomic, idempotent, no double-spend

Use a script that calls `billing.credits.debit_credits` / `cost.track_cost`.

1. `track_cost(call_id="c1", …)` for a known token usage → balance drops by the
   computed credits; a `credit_ledger` `usage` row with `idempotency_key="c1"`.
   - [ ] Balance reduced exactly once; ledger row present.
2. Replay `track_cost(call_id="c1", …)` → **no** second debit (idempotent).
   - [ ] Balance unchanged on replay.
3. Concurrency: fire N concurrent guarded debits that together exceed the
   balance → only the affordable number succeed; balance never goes negative.
   - [ ] No double-spend; balance floor respected.
4. ADR-024 W0-03: the post-call debit never raises to the caller; a simulated
   debit failure records a `pending_credit_debits` row and the request still
   "succeeds".
   - [ ] Failed debit is deferred, not fatal.

## Flow 3 — Reconciliation worker (dead-letter)

1. Seed a `pending_credit_debits` row (status `pending`).
2. Run the worker (`uv run arq solus_api.worker_main.WorkerSettings`) or call
   `reconciliation.reconcile_pending_debits(sessionmaker)`.
   - [ ] The debit is applied (balance drops), the row flips to `reconciled`.
3. If the same key already applied inline, reconcile marks `reconciled` WITHOUT
   double-debiting.
   - [ ] No double-debit on reconcile.

## Flow 4 — Stripe webhook: signature, dedupe, reconciliation

1. Send an event with a **bad/missing signature** → `400 invalid_signature`;
   with the webhook secret unset → `503 billing_unconfigured`.
   - [ ] Unsigned/forged events are rejected before any DB effect.
2. Send a valid signed `checkout.session.completed` (mode=payment,
   `client_reference_id`=user id, `metadata.price_id` in the pack map) →
   `200 {processed:true}`; the user's balance increases by the mapped credits.
   - [ ] Credit pack granted once.
3. Re-send the **same event id** → `200 {processed:false}`; balance unchanged
   (deduped via `processed_stripe_events`).
   - [ ] Duplicate delivery is a no-op.
4. Subscription reconciliation (the AC's replay test): send
   `customer.subscription.updated` with `status=active` at `created=200`, then a
   replayed **older** `status=past_due` at `created=150`, in that order and also
   scrambled.
   - [ ] Final `subscriptions.status` = `active` regardless of order
         (last-write-wins by event time). A duplicate re-delivery does not change it.
5. `customer.subscription.deleted` → status `canceled`.
   - [ ] Reflected in DB.
6. `invoice.payment_failed` (customer linked to the user) → subscription
   `past_due` + a `payment.failed` notification for the user.
   - [ ] Status + notification present.

## Cross-tenant / isolation

- [ ] A webhook for customer A only affects user A's subscription/credits.
- [ ] Credit ops are per `user_id`; one user's debit never touches another's
      balance or ledger.

## Edge cases

- [ ] Webhook body over `SOLUS_STRIPE_WEBHOOK_MAX_BYTES` → `413`.
- [ ] `checkout.session.completed` payment with an **unmapped** price id → no
      grant (logged), event still marked processed.
- [ ] A tiny real model call still bills ≥ 1 credit (ceil), never 0.

## Sign-off

- [ ] Flows 1–4 pass; isolation holds.
- [ ] Webhook replay/out-of-order converges to correct final state.
- [ ] No double-spend/double-grant under retries or concurrency.

## Known scope notes (this cycle)

- Prices, `credits_per_dollar`, `margin_multiplier`, and pack→credit mappings are
  **PROVISIONAL** (ADR-024) — calibrate post-pilot.
- Only the Stripe **webhook** route is built; checkout-session creation and the
  customer-facing purchase/subscription-management routes remain deferred
  (API plan §7.2). The trial cost cap enforces at the pre-flight gate; the live
  model-call path that calls it lands with the SOL Agent (MO-01).
