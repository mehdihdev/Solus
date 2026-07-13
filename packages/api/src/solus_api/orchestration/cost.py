"""Per-call cost tracking (ADR-024/018) — phase 3 of `select → call → track`.

`compute_call_credits` is the locked token→credit formula (with MO-02b
breakpoint pricing); `has_sufficient_credits` is the pre-flight gate;
`account_spend` exposes the rolling all-time USAGE total for the trial cap;
`track_cost` is the post-call debit hook (never raises — failures defer to
the billing dead-letter, `billing/reconciliation.py`).

The debit engine itself lives in `solus_api.billing` (SOLUSDEV-83): atomic,
row-locked, idempotent by `credit_ledger.idempotency_key` (the model call's
`call_id` is the key for gateway debits), shared with Stripe purchases and the
reconciliation sweep. This module is the orchestration-facing seam over it.
"""

import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits, reconciliation
from solus_api.models import CreditBalance
from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import CostConfig, ModelCatalogEntry

logger = logging.getLogger("solus.orchestration.cost")

# ARQ name of the billing dead-letter sweep (billing/reconciliation.py, also a
# 1-minute cron on the worker). After a failed inline debit is recorded,
# track_cost enqueues this by name for an immediate retry — the enqueue callable
# is injected by the caller (the repo's established seam, cf.
# run_change_detection(enqueue=...)), so this module never owns a Redis
# connection.
RECONCILE_JOB_NAME = "reconcile_credit_debits"

EnqueueFn = Callable[[str, dict[str, Any]], Awaitable[Any]]


def compute_call_credits(
    model: ModelChoice,
    tokens_in: int,
    tokens_out: int,
    cost: CostConfig,
    *,
    entry: ModelCatalogEntry | None = None,
) -> int:
    """Convert a completed call's token usage → credits to debit (ADR-024). Pure and
    deterministic given (model, tokens, cost, entry).

        dollars = tokens_in/1e6 * price_in + tokens_out/1e6 * price_out
        credits = ceil(dollars * margin_multiplier * credits_per_dollar)

    Breakpoint pricing (MO-02b): pass the routed model's catalog `entry`; when it
    carries long-context pricing and tokens_in EXCEEDS its threshold, the whole
    call bills at `price_in_long`/`price_out_long` (matching how providers charge
    the full request above the breakpoint). Flat-priced entries and `entry=None`
    bill at `model.price_in`/`price_out` exactly as before.

    Prices are USD per 1M tokens. `ceil` so a real call never bills 0 credits. The
    conversion is PROVISIONAL — calibrate `margin_multiplier` / `credits_per_dollar`
    from pilot data (ADR-024)."""
    price_in, price_out = model.price_in, model.price_out
    if (
        entry is not None
        and entry.long_context_threshold_tokens is not None
        and tokens_in > entry.long_context_threshold_tokens
        and entry.price_in_long is not None
        and entry.price_out_long is not None
    ):
        price_in, price_out = entry.price_in_long, entry.price_out_long
    dollars = (tokens_in / 1_000_000) * price_in + (tokens_out / 1_000_000) * price_out
    return math.ceil(dollars * cost.margin_multiplier * cost.credits_per_dollar)


async def has_sufficient_credits(
    user_id: uuid.UUID, estimated_credits: int, *, session: AsyncSession
) -> bool:
    """PRE-FLIGHT check (contract §7), run BEFORE `route()` by the caller — NOT part
    of route (route stays pure selection). Delegates to the billing gate: blocks
    when the cached balance can't cover the estimate, and blocks at balance 0
    (the free-trial hard cost cap, ADR-024 / SOLUSDEV-83). Block-vs-degrade
    policy lives in the caller (`gates.assert_can_spend` for the gateway)."""
    return await credits.check_spend_allowed(session, user_id, estimated_credits)


async def account_spend(user_id: uuid.UUID, *, session: AsyncSession) -> int:
    """A user's accumulated USAGE spend in credits — O(1) read of the rolling
    `CreditBalance.spent_total` maintained atomically by every debit (never a
    ledger scan).

    WINDOW SEMANTICS (documented): this is ALL-TIME usage spend. In v1 that
    equals trial-period spend — a user has exactly one trial and no pre-trial
    usage — which is what the trial cap (gates.assert_can_spend) consumes.
    Revisit when paid plans introduce post-trial usage that should not count
    against a (re)trial."""
    spent = await session.scalar(
        select(CreditBalance.spent_total).where(CreditBalance.user_id == user_id)
    )
    return spent or 0


async def track_cost(
    call_id: str,
    user_id: uuid.UUID,
    model: ModelChoice,
    tokens_in: int,
    tokens_out: int,
    *,
    session: AsyncSession,
    cost: CostConfig,
    entry: ModelCatalogEntry | None = None,
    enqueue: EnqueueFn | None = None,
) -> None:
    """POST-call hook (phase 3): runs AFTER the model responds (`tokens_out` is only
    known then). Computes credits via `compute_call_credits` (with MO-02b breakpoint
    pricing when `entry` is supplied) and applies the atomic idempotent debit via
    `billing.credits.debit_credits` (idempotency_key = call_id: a retried or
    concurrent hook for the same call debits exactly once).

    Debit-failure behavior (LOCKED, contract §6): the model call already ran and was
    paid for — NEVER fail the user's request on the accounting write. On any debit
    failure the debit is recorded in the billing dead-letter
    (`reconciliation.record_failed_debit`, idempotent by the same key) which the
    worker cron sweeps every minute; when `enqueue` is configured, the sweep is
    additionally enqueued immediately (`RECONCILE_JOB_NAME`). This hook NEVER
    raises."""
    amount = compute_call_credits(model, tokens_in, tokens_out, cost, entry=entry)
    if amount <= 0:
        return
    attrs = {
        "call_id": call_id,
        "model_name": model.model_name,
        "role": model.role,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
    try:
        await credits.debit_credits(session, user_id, amount, idempotency_key=call_id, attrs=attrs)
        return
    except Exception:
        logger.exception(
            "debit failed; deferring to reconciliation call_id=%s user_id=%s credits=%d",
            call_id,
            user_id,
            amount,
        )
        try:  # the session may be in a failed transaction — clear it, best-effort
            await session.rollback()
        except Exception:  # noqa: S110 - nothing actionable; reconciliation owns recovery
            pass
    try:
        await reconciliation.record_failed_debit(
            session, user_id, amount, idempotency_key=call_id, attrs=attrs
        )
    except Exception:  # noqa: BLE001 — even the dead-letter write is best-effort
        logger.exception(
            "could not record pending debit — payload (recover manually): "
            "call_id=%s user_id=%s credits=%d attrs=%s",
            call_id,
            user_id,
            amount,
            attrs,
        )
    if enqueue is None:
        return
    try:
        await enqueue(RECONCILE_JOB_NAME, {})
    except Exception:
        logger.exception("failed to enqueue reconciliation sweep call_id=%s", call_id)
