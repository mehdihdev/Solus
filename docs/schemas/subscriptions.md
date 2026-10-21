# Subscriptions table (SOLUSDEV-236)

Authority: ADR-023 (plans, limits as data), ADR-024 (trial 14 days, trial expiry),
ADR-032 (tier-1 doc). Model: `packages/api/src/solus_api/models.py` `class Subscription`.
Migration placeholder: **`a23600000001`** (adds `billing_interval` and
`current_period_end`; see §Migration).

One live subscription per user. The row is per **user**, not per team (ADR-023/025).

## Columns

Columns marked **new** were added by SOLUSDEV-236 (migration `a23600000001`). Everything else exists in the model today.

| Column                   | Type                                                                     | Null | Default                                       | Meaning                                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------ | ---- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `id`                     | UUID (UUIDv7)                                                            | no   | `uuid7()`                                     | PK                                                                                                                              |
| `user_id`                | UUID FK `users.id` ON DELETE CASCADE                                     | no   | —                                             | Owner. Indexed                                                                                                                  |
| `plan`                   | enum `PlanType` (`basic`, `pro`, `enterprise`)                           | no   | —                                             | Plan from what was bought (Stripe Price) or the trial choice. Comps do not change it (see `comp_plan`)                          |
| `status`                 | enum `SubscriptionStatus` (`active`, `past_due`, `canceled`, `trialing`) | no   | `trialing`                                    | Lifecycle. Mapped from Stripe status (`_STATUS_MAP`); unpaid/incomplete map to `past_due`                                       |
| `limits`                 | JSONB                                                                    | no   | `{}` (set to `default_limits(plan)` at write) | Plan limits as data (`null` value = unlimited). Enforcement reads `effective_limits`, never plan names                          |
| `limits_override`        | JSONB                                                                    | yes  | NULL                                          | Staff per-key override. Merged over `limits` at read time. Billing events never write it                                        |
| `expires_at`             | timestamptz                                                              | yes  | NULL                                          | Trial/period end. Rules in §expires_at. Read by the trial-expiry gate only when `stripe_subscription_id` IS NULL                |
| `cancel_at`              | timestamptz                                                              | yes  | NULL                                          | Scheduled cancellation (Stripe `cancel_at`). Set while cancel-at-period-end is pending; cleared on resume or when the term ends |
| `stripe_customer_id`     | String(255)                                                              | yes  | NULL                                          | Stripe `cus_…`. Never returned by any API                                                                                       |
| `stripe_subscription_id` | String(255)                                                              | yes  | NULL                                          | Stripe `sub_…`. Never returned by any API. NULL = no Stripe subscription (local trial, local comp, or pre-checkout)             |
| `seat_count`             | int                                                                      | yes  | NULL                                          | Enterprise seats (future). Staff-set                                                                                            |
| `custom_price_per_seat`  | int (cents)                                                              | yes  | NULL                                          | Enterprise price (future). Staff-set                                                                                            |
| `stripe_event_at`        | timestamptz                                                              | yes  | NULL                                          | `created` time of the last Stripe event applied. Out-of-order guard (last-write-wins)                                           |
| `comp_plan`              | enum `PlanType` (`subscription_comp_plan`)                               | yes  | NULL                                          | Staff comp: grants this plan's defaults while active. Read-time expiry                                                          |
| `comp_expires_at`        | timestamptz                                                              | yes  | NULL                                          | Comp end. NULL with `comp_plan` set = forever                                                                                   |
| `billing_interval`       | String(8), CHECK in (`month`, `year`)                                    | yes  | NULL                                          | **new.** Billing cadence of the Stripe Price (`recurring.interval`). NULL for a local trial or an unknown/unlinked row          |
| `current_period_end`     | timestamptz                                                              | yes  | NULL                                          | **new.** Raw Stripe renewal date (the current billing period end). Mirror only. Never used for gating                           |
| `created_at`             | timestamptz                                                              | no   | `utcnow()`                                    |                                                                                                                                 |
| `updated_at`             | timestamptz                                                              | no   | `utcnow()` (onupdate)                         |                                                                                                                                 |
| `deleted_at`             | timestamptz                                                              | yes  | NULL                                          | Soft delete. Indexed                                                                                                            |

### Indexes and constraints

- `uq_subscription_user`: partial unique on `(user_id) WHERE deleted_at IS NULL`.
- Index on `user_id`; index on `deleted_at`.
- **new:** `ck_subscriptions_billing_interval`: `billing_interval IS NULL OR billing_interval IN ('month', 'year')`.
- No secret column. Stripe ids are stored, never returned.

## expires_at rules

`expires_at` has one meaning per row state. The table below is the locked rule. The
webhook and reconciliation columns are built (SOLUSDEV-236).

| Row state                                                      | `expires_at` value                                                          | Written by                                                 |
| -------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Local trial (`stripe_subscription_id` NULL, `status` trialing) | Provisioning trial end: signup time + `stripe_trial_days` (14). Never reset | Provisioning (today: `deps._provision_user`, `TRIAL_DAYS`) |
| Stripe-linked, `status` trialing                               | Stripe `trial_end`                                                          | Webhook, reconciliation                                    |
| Stripe-linked, `status` active or past_due                     | Stripe `current_period_end`                                                 | Webhook, reconciliation                                    |
| Stripe-linked, `status` canceled                               | Last value kept (not cleared)                                               | Not written after term end                                 |
| Staff comp (`comp_plan`)                                       | Unchanged. The comp clock is `comp_expires_at`, not `expires_at`            | —                                                          |

Rules:

- **Expiry gate.** A local trial is expired when `status` is trialing,
  `stripe_subscription_id` IS NULL and `expires_at` < now. The check is read-time
  (no job, no new status value). Stripe-linked rows are never gated by it.
- **No trial restarts.** `PATCH /users/me/subscription` never touches `expires_at`.
- **Reads.** `SubscriptionRead.trial_expired` (bool) is computed with the same
  predicate as the gate. `trial.ends_at` in `GET /billing/summary` is `expires_at`
  while the trial state is not `none`.

## Who writes each column

| Column                                | Provisioning (signup)   | Trial PATCH                     | Webhook                                                             | Reconciliation                     | Staff ops                                                          | Notes                                      |
| ------------------------------------- | ----------------------- | ------------------------------- | ------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------ | ------------------------------------------ |
| `id`, `user_id`, `created_at`         | yes                     | —                               | —                                                                   | —                                  | —                                                                  |                                            |
| `plan`                                | `basic`                 | yes (trial only, `basic`/`pro`) | yes (from Stripe Price)                                             | yes (same path)                    | via comp/plan flows; Stripe-backed plan changes are made in Stripe | Unmapped price leaves plan unchanged       |
| `status`                              | `trialing`              | —                               | yes (`_STATUS_MAP`)                                                 | yes; `resource_missing` → canceled | yes (converges from Stripe)                                        | `deleted` event → canceled                 |
| `limits`                              | `default_limits(basic)` | yes (`default_limits(plan)`)    | yes (`default_limits` of the price's plan; BASIC clamp at term end) | yes (same path)                    | —                                                                  | Never plan names in enforcement            |
| `limits_override`                     | —                       | —                               | **never**                                                           | **never**                          | yes                                                                | Staff only                                 |
| `expires_at`                          | yes (trial end)         | never                           | yes (rule above)                                                    | yes                                | —                                                                  |                                            |
| `cancel_at`                           | —                       | —                               | yes (`_cancel_at_dt`); cleared on resume and term end               | yes                                | yes (via Stripe)                                                   |                                            |
| `stripe_customer_id`                  | —                       | —                               | yes (checkout completed, subscription events)                       | — (no re-link)                     | —                                                                  | Set on checkout (`get_or_create_customer`) |
| `stripe_subscription_id`              | —                       | —                               | yes (link on subscription event or checkout completed)              | — (no re-link)                     | —                                                                  | A new id clears a local comp               |
| `seat_count`, `custom_price_per_seat` | —                       | —                               | —                                                                   | —                                  | yes                                                                | Enterprise, future                         |
| `stripe_event_at`                     | —                       | —                               | yes (every applied event)                                           | —                                  | —                                                                  | Only moves forward                         |
| `comp_plan`, `comp_expires_at`        | —                       | —                               | yes (clears `comp_plan` on new Stripe link)                         | —                                  | yes (grant)                                                        | `comp_expiry` sweep clears expired comps   |
| `billing_interval` (new)              | NULL                    | —                               | yes (from price `recurring.interval`)                               | yes                                | —                                                                  | NULL for local rows                        |
| `current_period_end` (new)            | NULL                    | —                               | yes (raw Stripe value)                                              | yes                                | —                                                                  | Mirror only                                |
| `deleted_at`                          | —                       | —                               | —                                                                   | —                                  | —                                                                  | Account deletion (soft delete)             |

**Read-time only (no column):** trial state, `trial_expired`, `effective_limits`
(`limits` + `limits_override` + active comp), `is_comp_active`.

**Reconciliation** is the hourly cron that converges Stripe-linked rows (`billing/subscription_sync.py`, minute 5).
It does not touch local-only rows. It uses the same pure derivation as the webhook
(`expires_at`, `billing_interval`, `current_period_end`, `status`, `cancel_at`).
If Stripe returns `resource_missing` for a linked subscription, the row is canceled
through the term-end path (the same path as `customer.subscription.deleted`). A
circuit breaker stops the sweep when too many linked rows are missing in one run
(more than 5 % of the batch, minimum 10: the run aborts and writes nothing). Every changed row emits `billing.subscription.reconciled
{changed_fields, from_status, to_status, cause}`.

Do not confuse this with `billing/reconciliation.py`, which reconciles credit debits
(`pending_credit_debits`), not subscriptions.

## Migration `a23600000001` (placeholder)

- Add `billing_interval VARCHAR(8) NULL` with the CHECK constraint above.
- Add `current_period_end TIMESTAMPTZ NULL`.
- No backfill. Stripe-linked rows converge through reconciliation after deploy.
  Local trial rows keep `billing_interval` NULL and their existing `expires_at`.
- Downgrade drops the CHECK and both columns.
- Alembic is in use (`packages/api/migrations/versions`). The revision id is a
  placeholder until the revision is generated.

## Related

- `docs/api/API-implementation.md` §10 — endpoints, trial expiry block, summary shape.
- `docs/api/API.md` §2.14 — user-scoped billing routes.
- `docs/wireflows/billing.md` — the screen that reads these columns.
- `packages/api/src/solus_api/billing/stripe_events.py` — `_apply_subscription`, the webhook writer.
- `packages/api/src/solus_api/billing/entitlements.py` — `effective_limits`, `is_comp_active`.
