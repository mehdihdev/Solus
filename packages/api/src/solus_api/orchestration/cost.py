"""Per-call cost tracking (ADR-024/018) — phase 3 of `select → call → track`.

`compute_call_credits` is FUNCTIONAL: it locks the token→credit formula (the cost
contract). `has_sufficient_credits` (pre-flight) and `track_cost` (the ledger
debit + reconciliation) are STUBS implemented in MO-01.
"""

import logging
import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits, reconciliation
from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import CostConfig

logger = logging.getLogger("solus.orchestration.cost")


def compute_call_credits(
    model: ModelChoice, tokens_in: int, tokens_out: int, cost: CostConfig
) -> int:
    """Convert a completed call's token usage → credits to debit (ADR-024). Pure and
    deterministic given (model, tokens, cost).

        dollars = tokens_in/1e6 * price_in + tokens_out/1e6 * price_out
        credits = ceil(dollars * margin_multiplier * credits_per_dollar)

    Prices are USD per 1M tokens. `ceil` so a real call never bills 0 credits. The
    conversion is PROVISIONAL — calibrate `margin_multiplier` / `credits_per_dollar`
    from pilot data (ADR-024)."""
    dollars = (tokens_in / 1_000_000) * model.price_in + (tokens_out / 1_000_000) * model.price_out
    return math.ceil(dollars * cost.margin_multiplier * cost.credits_per_dollar)


async def has_sufficient_credits(
    user_id: uuid.UUID, estimated_credits: int, *, session: AsyncSession
) -> bool:
    """PRE-FLIGHT check, run BEFORE `route()` by the caller/middleware — NOT part of
    route (route stays pure selection). Delegates to the billing gate: blocks when
    the balance can't cover the estimate, and blocks at balance 0 (the free-trial
    hard cost cap, ADR-024 / SOLUSDEV-83)."""
    return await credits.check_spend_allowed(session, user_id, estimated_credits)


async def track_cost(
    call_id: str,
    user_id: uuid.UUID,
    model: ModelChoice,
    tokens_in: int,
    tokens_out: int,
    *,
    session: AsyncSession,
    cost: CostConfig,
) -> None:
    """POST-call hook (phase 3): runs AFTER the model responds (`tokens_out` is only
    known then). STUB → MO-01. Intended behavior:

      1. credits = compute_call_credits(model, tokens_in, tokens_out, cost)
      2. append a CreditLedger USAGE row (amount = -credits, balance_after snapshot,
         attrs = {call_id, model_name, role, tokens_in, tokens_out})
      3. update the cached CreditBalance for the user.

    Debit-failure behavior (REQUIRED): the model call already ran and was paid for —
    NEVER fail the user's request on the accounting write. On debit failure (DB down,
    race) serve the result and enqueue the debit to a reconciliation / dead-letter
    path (ARQ + Redis) so credits reconcile later. This hook never raises to the caller
    in production; it swallows and defers.

    `user_id` is required — the ledger is per-user and `call_id` alone can't identify it.
    """
    amount = compute_call_credits(model, tokens_in, tokens_out, cost)
    if amount <= 0:
        return
    attrs = {
        "call_id": call_id,
        "model": model.model_name,
        "role": model.role,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
    try:
        # `call_id` is the idempotency key: a retried post-call hook debits once.
        await credits.debit_credits(session, user_id, amount, idempotency_key=call_id, attrs=attrs)
    except Exception:  # noqa: BLE001 — ADR-024 W0-03: never fail a paid result on accounting
        logger.exception("credit debit failed call=%s; deferring to reconciliation", call_id)
        # The failed transaction is poisoned — reset before recording the dead-letter.
        await session.rollback()
        try:
            await reconciliation.record_failed_debit(
                session, user_id, amount, idempotency_key=call_id, attrs=attrs
            )
        except Exception:  # noqa: BLE001 — even the dead-letter write is best-effort
            logger.exception("could not record pending debit call=%s", call_id)
