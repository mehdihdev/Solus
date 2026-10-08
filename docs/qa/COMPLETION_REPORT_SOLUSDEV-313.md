# SOLUSDEV-313 — Completion report

Branch: `SOLUSDEV-313-stripe-admin-operations` (from `main`). Nothing pushed; no MR opened. 42 files,
+10,008 / −367, 39 local commits (sub-branches merged and deleted; no worktrees remain).

## 1. What was built

Backend service layer + webhook/gateway changes for staff-initiated billing changes, plus two billing bug fixes.
No staff routes, no UI (SOLUSDEV-314 builds those and calls this layer).

| Area                          | Where                                                                                                                                                                                                                                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Effective limits (one reader) | `billing/entitlements.py` (`effective_plan`, `effective_limits`, `is_comp_active`); consumed by `services/limits.py`, `SubscriptionRead`                                                                                                                                                                |
| Schema                        | `Subscription.limits_override` JSONB, `comp_plan`, `comp_expires_at`; `StripeCancelRequest`; migration `a31300000001` (single head, downgrade, nullable adds, CHECK `NOT VALID`→`VALIDATE`, partial index)                                                                                              |
| Stripe gateway writes         | `billing/stripe_gateway.py`: `retrieve_subscription`, `change_subscription_price`, `ensure_comp_coupon`, `apply/remove_comp_coupon`, `cancel_subscription`, revert schedules, `list_customer_subscriptions`; per-call 30 s timeout; idempotency key + audit metadata on every staff write; typed errors |
| Admin operations              | `billing/admin_operations.py` (+ `admin_types/validation/projection.py`): `change_plan`, `comp_upgrade`, `remove_comp`, `set_limits_override`, `cancel_subscription` → `AdminOpResult{before, after, stripe_refs, converges_via_webhook, noop}`                                                         |
| Comp expiry                   | read-time in `entitlements`; ARQ sweep `billing/comp_expiry.py` (every 15 min, batched)                                                                                                                                                                                                                 |
| Webhook                       | `billing/stripe_events.py`: override never touched; new-link comp clearing; admin-originated wording via `previous_attributes.metadata`; tombstone race; malformed-payload hardening                                                                                                                    |
| Account deletion              | `services/account_deletion.py` (extracted; `ownership_transfers`); durable `services/stripe_cancel.py` (+ worker cron every minute, API startup drain)                                                                                                                                                  |
| Bug fixes                     | Deleted accounts no longer keep being billed; `PATCH /users/me/subscription` guarded (TRIALING + no Stripe sub, no `expires_at` reset, BASIC/PRO only)                                                                                                                                                  |
| Docs                          | `DECISIONS.md` ADR-023 clarification (tier-2, approved in chat; own commit `d73809a2`); `docs/api/API.md` §2.14 notes (tier-1); `docs/qa/COWORK_QA_SOLUSDEV-313-stripe-admin-ops.md`                                                                                                                    |

## 2. Governing docs consulted

DECISIONS.md ADR-021/023/024/032/037/038 §1; docs/api/API.md §2.14; CLAUDE.md §3–§9; `.claude/rules/**`; skills
`stripe-best-practices`, `security-review`, `database-migrations`, `tdd-workflow`, `python-testing`.
**Gaps flagged:** `packages/api/CLAUDE.md` does not exist (root map lists it); no billing diagram under `docs/architecture`;
no wireflows apply. The governing set used was ADR-023 + API.md §2.14 + the Phase 1 answers.

## 3. Phase 1 answers (human) and delegated-judgment decisions

Human decisions:

1. Self-serve PATCH: **guard it** (TRIALING + no Stripe sub; never reset `expires_at`).
2. Override **survives** subscription end until staff clears it (plan defaults still clamp to BASIC underneath).
3. Comp expiry: **hybrid** (read-time exact + ARQ sweep that materialises and notifies).
4. Local comp **grants plan starting credits** via the same idempotent per-user-per-plan key.
5. ADR-023 clarification text **approved**.
6. Deletion cancel: **immediate, final invoice created, NO proration** (`invoice_now=True, prorate=False`).
7. Stripe-backed comp end: **revert to the previous price** (metadata + Subscription Schedule). Local `once` = 1 month, `repeating N` = N months (1–36), `forever` = no expiry.

Delegated judgment (flagging for review):

- Coupons are created through the API with deterministic ids (`solus-comp-once|repeating-<N>|forever`); no human-created coupons needed.
- Stripe-backed ops never write the local row; `after` is projected from Stripe's response; local converges via webhook only.
- A canceled/deleted event never clears a comp on first link; a link is "new" when the incoming subscription id differs from the stored one (resubscribe case found in review).
- `change_plan` on a Stripe subscription that carries a comp coupon is **refused** ("remove the comp first"); `remove_comp` requires a `solus-comp-*` coupon **and** the previous-price marker.
- The cancel queue row is a **customer tombstone**: the runner lists the customer's non-canceled subscriptions in Stripe and cancels all; a stored subscription-id hint is canceled only after Stripe confirms it belongs to that customer.
- The service commits its own writes; each operation is capped at 120 s (lock hold) and is safe to retry with the same `audit_action_id`.
- Ownership transfer promotes an existing live member to OWNER (bypasses plan-limit checks, same as the existing role-change route).
- Notification types reused (no new `NotificationType`, no CHECK change).
- The migration `a31300000001` was amended in place during review (never deployed) rather than adding a second revision.

## 4. Service API for SOLUSDEV-314

```python
from solus_api.billing.admin_operations import (
    AdminBillingOperations, AdminOpResult, SubscriptionView,
    AdminOperationError, TargetNotFound, InvalidOperation, NotCompedError,
    UnsupportedForNonStripe, AdminOperationTimeoutError,
)
ops = AdminBillingOperations(session, gateway, settings)       # gateway: StripeGateway(secret_store)
# every method: keyword-only after target_user_id, plus actor_staff_user_id: UUID,
#               audit_action_id: str, reason: str  -> AdminOpResult
await ops.change_plan(target, plan=, interval=None, proration="create_prorations"|"none"|"always_invoice")
await ops.comp_upgrade(target, plan=, duration="once"|"repeating"|"forever", months=None, interval=None, proration="none")
await ops.remove_comp(target, proration="none")
await ops.set_limits_override(target, limits={...}|None)       # None clears; {} rejected; values int 0..1_000_000 or None
await ops.cancel_subscription(target, immediate=bool, invoice_now=False, prorate=False)
result.to_dict()   # JSON-safe {before, after, stripe_refs, converges_via_webhook, noop}
# sweep (worker): billing.comp_expiry.sweep_expired_comps(session)
# deletion:
from solus_api.services.account_deletion import AccountDeletionService
await AccountDeletionService(session, secret_store=, supabase_admin=, cache=, gateway=).delete_account(user, ownership_transfers={team_id: new_owner_id}|None)
```

Contract notes for 314:

- **The layer trusts its caller.** 314 must authorize the staff member first, and must mint a **unique `audit_action_id` per action and persist it before calling** (Stripe's idempotency window is 24 h; local ops ignore the id).
- Errors carry stable `.code` and `.retryable`; gateway errors (`StripeOperationError`, `StripeIdempotencyConflictError`, `BillingUnconfiguredError`) pass through.
- `reason` is for 314's audit log only: it is never sent to Stripe, logs or events. Event emitted: `subscription.admin_changed` (operation, audit_action_id, actor_staff_user_id, target_user_id).
- `AccountDeletionService` raises `OwnershipTransferRequired(team_ids)` / `InvalidOwnershipTransfer(code, team_id, reason)`.
- **Recommend 314's customer-detail page show an active `limits_override` and comp prominently next to the plan** (a forgotten override must be noticed).

## 5. Verification

- Full API suite (final head `52dc9ca8`): **8,436 passed, 6 skipped, 2 failed** in 26 m 31 s. The 2 failures are
  `tests/test_dev_launcher.py::test_ctrl_c_in_a_terminal_stops_the_whole_stack` and
  `::test_ctrl_c_lets_every_service_finish_a_graceful_stop`: SIGINT/timing tests under a loaded machine. The branch changes no
  launcher or script files, and `test_dev_launcher.py` passes **42/42 in isolation**. Treated as environmental flakiness; not confirmed against `main`.
- Coverage (agent-measured, `coverage run`): `stripe_cancel.py` 99%, `stripe_gateway.py` 97%, `admin_operations.py` / `admin_projection.py` / `comp_expiry.py` 100%,
  `stripe_events.py` 96%, `account_deletion.py` 82%, `limits.py` 86%, `entitlements.py` 84%. `plan_grants.py` and `schemas.py`/`users.py` were not measured (no coverage tool in the repo env).
- ruff/mypy clean on all touched files (the post-edit hook prints a mypy "INTERNAL ERROR" inside third-party packages; direct mypy runs pass).
- TDD: red-first evidence captured for the review fixes (11 failing tests before the cancel-queue security fix). For the original T1–T8 tasks red-first
  evidence is partial (some agents wrote implementation and tests in one step) and cannot be shown from history.

## 6. Phase 4 review outcome

Reviews run: code-reviewer, security-reviewer, python-reviewer, database-reviewer (+ two security re-reviews).

- Database: no critical. Fixed: partial index on pending rows, `FOR UPDATE` on the deletion subscription read, comp-sweep batching, `NOT VALID` CHECK.
- Python/code: file split (`admin_operations.py` 878 → 690 lines), typing/dedupe/dead code, comp cleared on resubscribe, re-exports removed.
- Security: first review **FAIL** (H-1: re-arm could overwrite a pending cancel) — fixed by the customer-tombstone runner. Re-review then found **NEW-H1**
  (a stored hint id was canceled without an ownership check, and a test asserted that) and NEW-M1 (lease shorter than a batch) — both fixed with red-first tests,
  plus LOW-1…5. Final re-check on `52dc9ca8`: ****PASS** for handoff (no critical/high/medium; NEW-H1 and NEW-M1 closed). Its three remaining lows were then fixed: cron wrappers and the admin credit-grant failure path now log the exception type only (caplog tests added), and the webhook re-arm is documented as the backstop for the lease-lapse window**.

## 7. Human decisions still open (not decided by agents)

1. **Retention of `stripe_cancel_requests`** — completed tombstones are kept indefinitely (Stripe ids only). They must outlive the late-checkout window; pick a purge age (suggest ≥ 90 days) and add a job.
2. **PII on the Stripe Customer after deletion** — email and `metadata.solus_user_id` remain. Options: redact after the cancel completes, or keep for invoice/tax retention.
3. **`forever` comp coupons are not product-restricted** — mitigate by disabling plan switching in the Billing Portal, or restrict coupons with `applies_to` (needs product ids/per-plan coupon ids).
4. **Trial expiry is not enforced anywhere** (`expires_at` is stored only). A TRIALING user keeps trial limits forever. Product decision.
5. **`StaffPrincipal` type** so the service cannot be called with an arbitrary UUID — belongs in 314's auth design.
6. **Deletion cancel policy** (final invoice, no proration) is implemented as you specified; confirm the business policy is final.
7. LOW-6 (accepted): re-arming a row inside its 24 h terminal backoff keeps the backoff.
8. Pre-existing, not fixed: Checkout always passes `stripe_trial_days`, so cancel-and-resubscribe loops can earn repeated Stripe trials (`routers/billing.py`).

## 8. Human task checklist (agents did not do these)

- [ ] Create a Stripe **restricted API key** with write access to **Subscriptions, Subscription Schedules, Coupons** (and read Customers/Invoices) — test **and** live; store as the `stripe_api_key` secret (Secrets Manager / `.env`; agents never edit `.env*`).
- [ ] Confirm the webhook endpoint is subscribed to `customer.subscription.created|updated|deleted`, `checkout.session.completed`, `invoice.payment_failed`.
- [ ] Confirm `stripe_plan_prices` is configured for basic/pro × month/year in each environment.
- [ ] Decide Billing Portal plan-switching setting (see open item 3).
- [ ] Apply migration `a31300000001` (single head; if `main` gains another revision before merge, add a merge revision).
- [ ] Ensure the ARQ worker runs with the new crons (`cancel_stripe_subscriptions` every minute, `expire_comps` every 15 min).
- [ ] Run the test-mode QA with `stripe listen` (started by `pnpm dev:all`) and `stripe events resend` for replay tests: **`docs/qa/COWORK_QA_SOLUSDEV-313-stripe-admin-ops.md`**.
- [ ] Verify against live Stripe test mode (not covered by automated tests): metadata unset via empty string; "already canceled/released" handling; revert-schedule timing (counts from the start of the current cycle).
- [ ] Review, push, open the MR, merge.

## 9. Deviations / notes

- `docs/api/API.md`: a formatter hook re-padded unrelated markdown tables in the first docs commit (whitespace only, no content lost); consider reverting those hunks in review.
- `routers/users.py` no longer re-exports `delete_projects_cascade`/`delete_team_cascade`; `routers/teams.py` and `routers/projects.py` import them from `services/account_deletion` (touched outside the original ownership, in a review-fix task).
- `StripeGateway` is now imported at module level in `connectors/worker.py` (no circular import).
- API startup awaits a bounded (≤15 s) Stripe cancel drain; it never fails startup.
- Agent worktrees started from a stale base several times; each agent fast-forwarded to the correct commit first. Hooks H8/H9 call bare `pytest`/`ruff` that are not on PATH inside fresh worktrees until `uv sync` is run (flag for a human: possible hook misfire).
