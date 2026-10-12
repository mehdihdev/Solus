# SOLUSDEV-313 — Completion report

Branch: `SOLUSDEV-313-stripe-admin-operations` (from `main`; `main` has not moved, so no merge or Alembic merge revision is needed).
Nothing pushed; no MR opened. 43 files, +10,996 / −348, 53 local commits (all sub-branches merged and deleted; no worktrees remain).

## 1. What was built

Backend service layer + webhook/gateway changes for staff-initiated billing changes, plus two billing bug fixes.
No staff routes, no UI (SOLUSDEV-314 builds those and calls this layer).

| Area                          | Where                                                                                                                                                                                                                                                                                                                        |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Effective limits (one reader) | `billing/entitlements.py` (`effective_plan`, `effective_limits`, `is_comp_active`); consumed by `services/limits.py`, `SubscriptionRead`                                                                                                                                                                                     |
| Schema                        | `Subscription.limits_override` JSONB, `comp_plan`, `comp_expires_at`; `StripeCancelRequest`; migration `a31300000001` (single head, downgrade, nullable adds, CHECK `NOT VALID`→`VALIDATE`, partial index on pending rows)                                                                                                   |
| Stripe gateway writes         | `billing/stripe_gateway.py`: `retrieve_subscription`, `change_subscription_price`, `ensure_comp_coupon`, `apply/remove_comp_coupon`, `cancel_subscription`, revert schedules, `list_customer_subscriptions`, `redact_customer`; per-call 30 s timeout; idempotency key + audit metadata on every staff write; typed errors   |
| Admin operations              | `billing/admin_operations.py` (+ `admin_types/validation/projection.py`): `change_plan`, `comp_upgrade`, `remove_comp`, `set_limits_override`, `cancel_subscription` → `AdminOpResult{before, after, stripe_refs, converges_via_webhook, noop}`                                                                              |
| Comp expiry                   | read-time in `entitlements`; ARQ sweep `billing/comp_expiry.py` (every 15 min, batched)                                                                                                                                                                                                                                      |
| Webhook                       | `billing/stripe_events.py`: override never touched; new-link comp clearing; admin-originated wording via `previous_attributes.metadata`; tombstone race; refuses to link a tombstoned customer to a live user; malformed-payload hardening                                                                                   |
| Account deletion              | `services/account_deletion.py` (extracted; validated `ownership_transfers`); durable `services/stripe_cancel.py` (worker cron every minute + API startup drain): cancels every live subscription of the customer (final invoice, no proration), then redacts the Customer's `name` and `metadata.solus_user_id` (email kept) |
| Bug fixes                     | Deleted accounts no longer keep being billed; `PATCH /users/me/subscription` guarded (TRIALING + no Stripe sub, no `expires_at` reset, BASIC/PRO only)                                                                                                                                                                       |
| Docs                          | `DECISIONS.md` ADR-023 clarification (tier-2, approved in chat; own commit `d73809a2`); `docs/api/API.md` §2.14 paragraph (tier-1; diff vs `main` is +8 lines only); `docs/qa/COWORK_QA_SOLUSDEV-313-stripe-admin-ops.md`                                                                                                    |

## 2. Governing docs consulted

DECISIONS.md ADR-021/023/024/032/037/038 §1; docs/api/API.md §2.14; CLAUDE.md §3–§9; `.claude/rules/**`; skills
`stripe-best-practices`, `security-review`, `database-migrations`, `tdd-workflow`, `python-testing`.
**Gaps flagged:** `packages/api/CLAUDE.md` does not exist (root map lists it); no billing diagram under `docs/architecture`;
no wireflows apply. The governing set used was ADR-023 + API.md §2.14 + the human decisions below.

## 3. Human decisions and delegated-judgment decisions

Human decisions (all recorded in chat):

1. Self-serve PATCH: **guard it** (TRIALING + no Stripe sub; never reset `expires_at`).
2. Override **survives** subscription end until staff clears it (plan defaults still clamp to BASIC underneath).
3. Comp expiry: **hybrid** (read-time exact + ARQ sweep that materialises and notifies).
4. Local comp **grants plan starting credits** via the same idempotent per-user-per-plan key.
5. ADR-023 clarification text **approved**.
6. Deletion cancel: **immediate, final invoice created, NO proration** (`invoice_now=True, prorate=False`).
7. Stripe-backed comp end: **revert to the previous price**. Local `once` = 1 month, `repeating N` = N months (1–36), `forever` = no expiry.
8. (2026-10-09) **Tombstones are never purged**: completed `stripe_cancel_requests` rows (Stripe ids only) are retained indefinitely.
9. (2026-10-09) **Redact Customer PII after a deletion cancel**: clear `name` and `metadata.solus_user_id`; keep the email and the Customer (invoice/tax records).

Delegated judgment (flagging for review):

- Coupons are created through the API with deterministic ids (`solus-comp-once|repeating-<N>|forever`); no human-created coupons needed.
- Stripe-backed ops never write the local row; `after` is projected from Stripe's response; local converges via webhook only.
- A link is "new" when the incoming subscription id differs from the stored one; terminal (canceled/deleted) events never clear a comp.
- `change_plan` on a Stripe subscription carrying a comp coupon is **refused** ("remove the comp first"); `remove_comp` requires a `solus-comp-*` coupon **and** the previous-price marker.
- The cancel queue row is a **customer tombstone**: the runner lists the customer's non-canceled subscriptions in Stripe and cancels all; a stored subscription-id hint is canceled only after Stripe confirms it belongs to that customer.
- A re-arm of a pending row that brings a NEW subscription id makes the row due immediately (attempts/backoff history kept); same/no id keeps the backoff.
- The webhook ignores a link of a tombstoned customer to a different live user, and logs it at ERROR with the marker `billing.tombstoned_customer_refused` (ids only). The dead customer's own new subscription is still canceled via its own event, so the affected live user may have been billed for a first period with no entitlement and needs a **manual refund**.
- The cancel runner treats a Stripe idempotency-key conflict as retryable with the short backoff (with fixed keys and parameters it can only mean two runners at once); the gateway's mapping used by admin operations is unchanged. A failure after a mid-run re-arm is due immediately.
- Account deletion skips tombstoning a customer that another LIVE subscription row also references (a legacy mislink) and logs `billing.shared_customer_not_tombstoned` at ERROR, so deleting one user can never cancel another live user's subscription.
- The service commits its own writes; each operation is capped at 120 s (lock hold) and is safe to retry with the same `audit_action_id`.
- Ownership transfer promotes an existing live member to OWNER (bypasses plan-limit checks, same as the existing role-change route).
- Notification types reused (no new `NotificationType`, no CHECK change).
- Migration `a31300000001` was amended in place during review (never deployed) rather than adding a second revision.

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

- Full API suite on the final head (`4e26c47c`): **FINAL_SUITE_RESULT**
- Full API suite on the previous head (`38a9e14b`, before the last round of review fixes): **8,477 passed, 6 skipped, 0 failed** (28 m 51 s).
- Earliest full run (head `52dc9ca8`, before the redaction and re-arm work): 8,436 passed, 6 skipped, 2 failed. The 2 failures were
  `tests/test_dev_launcher.py::test_ctrl_c_in_a_terminal_stops_the_whole_stack` and `::test_ctrl_c_lets_every_service_finish_a_graceful_stop`:
  SIGINT/timing tests under a loaded machine. The branch changes no launcher or script files and `test_dev_launcher.py`
  passed **42/42 in isolation**. Treated as environmental flakiness; not confirmed against `main`.
- `make typecheck` (mypy over `packages/api/src` + the TypeScript projects): clean. Python lint (`ruff check .`): clean.
  **`pnpm lint` fails on pre-existing files** under `.design-sync/` and `.ds-sync/` (tracked on `main`, untouched by this branch);
  CI's `lint:node` job may trip on them if its path filter triggers.
- Coverage (agent-measured, `coverage run`): `stripe_cancel.py` 99%, `stripe_gateway.py` 97%, `admin_operations.py` / `admin_projection.py` / `comp_expiry.py` 100%,
  `stripe_events.py` 96%, `account_deletion.py` 82%, `limits.py` 86%, `entitlements.py` 84%. `plan_grants.py`, `schemas.py`, `users.py` were not measured (no coverage tool in the repo env).
- TDD: red-first evidence captured for all review-fix rounds (11, 31 and 5 newly failing tests before the cancel-queue, redaction and re-arm fixes).
  For the original T1–T8 tasks red-first evidence is partial (some agents wrote implementation and tests in one step) and cannot be shown from history.
- Dev database migrated to `a31300000001`; all new objects verified (columns, both indexes, validated CHECK).

## 6. Phase 4 review outcome

Reviews run: code-reviewer, security-reviewer, python-reviewer, database-reviewer, plus three targeted security re-reviews.

- Database: no critical. Fixed: partial index on pending rows, `FOR UPDATE` on the deletion subscription read, comp-sweep batching, `NOT VALID` CHECK.
- Python/code: file split (`admin_operations.py` 878 → 690 lines), typing/dedupe/dead code, comp cleared on resubscribe, re-exports removed.
- Security, round 1: **FAIL** (H-1: re-arm could overwrite a pending cancel) → fixed by the customer-tombstone runner.
- Security, round 2: found **NEW-H1** (a stored hint id was canceled without an ownership check, and a test asserted that) and NEW-M1 (lease shorter than a batch) → fixed with red-first tests, plus LOW-1…5. Final re-check on `52dc9ca8`: **PASS**; its remaining lows were then fixed.
- Security, round 3 (redaction): **PASS** with two MEDIUMs, both fixed in FIX-F: (a) a late subscription for a tombstoned customer could wait up to 24 h if redaction was failing (now due immediately); (b) a signed checkout could link a tombstoned customer to a live user (now refused).
- Security, round 4 (the two FIX-F changes): **PASS** with two MEDIUMs and a LOW, all fixed in FIX-G: (a) a re-arm could overwrite a runner's active lease, so a Stripe idempotency 409 was treated as terminal and the late subscription again waited 24 h (a conflict is now a short retryable backoff, and a failure after a mid-run re-arm is due immediately; the lease overwrite itself still happens but its consequences are now harmless); (b) the refused-link comment and test were wrong about what happens to the live user's subscription (comments corrected, ERROR marker added, test rewritten with the realistic Stripe event sequence); (c) deletion now skips a customer shared with another live subscription row.
- **Accepted LOWs (documented):** a transient Stripe 5xx can replay for up to 24 h under the same idempotency key (self-heals; backoff ≤ 1 h); there is no dead-letter/max-attempts state, so a permanently failing redaction logs an ERROR daily (alert on it); alternating new subscription ids on one tombstoned customer each re-arm its row to due-now (about one batch slot per event, needs Stripe-side activity).
- **Not independently re-reviewed:** the three FIX-G commits (runner failure branch and conflict classification, ERROR markers, deletion shared-customer guard) were test-first and covered by the suites, but no security reviewer looked at them after they landed. Each previous round found a real but smaller edge case (HIGH, then MEDIUM, then MEDIUM). A human reviewer should read those three commits (`git log --oneline -3 --first-parent` shows the merge; the changes are in `services/stripe_cancel.py`, `billing/stripe_events.py`, `services/account_deletion.py`).

## 7. Human decisions still open

1. **Billing Portal plan switching** — `forever` comp coupons are not product-restricted; disable plan switching in the Portal (or restrict coupons with `applies_to`).
2. **Trial expiry is not enforced anywhere** (`expires_at` is stored only): a TRIALING user keeps trial limits forever. Product decision.
3. **`StaffPrincipal` type** so the service cannot be called with an arbitrary UUID: belongs in SOLUSDEV-314's auth design.
4. Confirm the deletion policy (final invoice, no proration) is final before live.
5. Pre-existing, not fixed: Checkout always passes `stripe_trial_days`, so cancel-and-resubscribe loops can earn repeated Stripe trials (`routers/billing.py`).

Decided (no action needed): tombstones never purged; Customer name + `solus_user_id` redacted, email and Customer kept.

## 8. Human task checklist

Agents already did: lint/typecheck, final suites, docs cleanup, dev-DB migration, test-DB cleanup. **Still yours:**

- [ ] Create a Stripe **restricted API key** (test + live): Write on **Customers, Checkout Sessions, Customer portal, Subscriptions, Subscription Schedules, Coupons**; **Invoices: Read**. (`stripe-setup bootstrap`/`webhook` additionally need Products, Prices and Webhook endpoints: use a temporary setup key.) Store it with `uv run stripe-setup put-key` (the redaction needs **Customers: write**; a missing permission shows up as a non-retryable failure with an ERROR log).
- [ ] `uv run stripe-setup bootstrap`, then `check`; paste `SOLUS_STRIPE_PLAN_PRICES` into the environment.
- [ ] Register the production webhook with `uv run stripe-setup webhook --url https://<api-domain>`; store the printed `whsec_...` as `SOLUS_STRIPE_WEBHOOK_SECRET`.
- [ ] Disable plan switching in the Billing Portal (open decision 1).
- [ ] Deploy order: migration `a31300000001` → API → worker (`arq solus_api.worker_main.WorkerSettings`); confirm the `cancel_stripe_subscriptions` (every minute) and `expire_comps` (every 15 min) crons start.
- [ ] Run the QA in `docs/qa/COWORK_QA_SOLUSDEV-313-stripe-admin-ops.md` against Stripe test mode; it lists the behaviours that could not be verified without live Stripe: **`name=""` clearing the Customer name**, metadata unset via empty strings, already-canceled / already-released handling, revert-schedule timing (counts from the start of the current billing cycle).
- [ ] Alert on these log lines: `NON-RETRYABLE, needs an operator` (a deleted account's cancel or redaction is stuck), `billing.tombstoned_customer_refused` (a live user was billed for a subscription Solus will not honour: **refund them**), `billing.shared_customer_not_tombstoned` (a deletion skipped a shared Stripe customer: investigate the mislink). Also alert on `stripe_cancel_requests` rows with `completed_at is null` older than ~15 minutes.
- [ ] Push, open the MR, merge; then delete the ownership manifests `.claude/state/ownership/T[1-9].list` and `FIX-*.list`.
- [ ] File follow-up tickets: trial-expiry enforcement; `StaffPrincipal` in 314; checkout trial loops; (optional) dead-letter/alert state for permanently failing deletion cancels.

## 9. Deviations / notes

- `routers/users.py` no longer re-exports `delete_projects_cascade`/`delete_team_cascade`; `routers/teams.py` and `routers/projects.py` import them from `services/account_deletion` (touched outside the original ownership, in a review-fix task).
- `StripeGateway` is now imported at module level in `connectors/worker.py` (no circular import).
- API startup awaits a bounded (≤15 s) Stripe cancel drain; it never fails startup.
- Agent worktrees started from a stale base several times; each agent fast-forwarded to the correct commit first. Hooks H8/H9 call bare `pytest`/`ruff` that are not on PATH inside fresh worktrees until `uv sync` is run, and H8 prints a mypy "INTERNAL ERROR" from third-party packages on many edits (direct mypy runs pass): flag for a human as a possible hook misfire. No hook was bypassed or edited.
