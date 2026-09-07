"""Health and quota position per account grant (SOLUSDEV-244 / HOME H4).

Everything here is DERIVED from what Solus already holds — the grant's status,
the bound sources' last sync errors, and the provider-quota ledger (SOLUSDEV-167)
— and never probed: a health check that called the provider would spend the very
allowance the card exists to protect, and the architecture forbids turning a
throttle into more traffic (`docs/architecture/change-signal-spine.md`).

The quota position is the meter's ESTIMATE (ADR-019 as amended): a floor on our
own calls since the counter started, never a remaining balance. Absent when the
provider is unmetered or the ledger is unreachable — a block that said "ok"
because Redis was down would be worse than no block.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.quota import QuotaState
from solus_api.connectors.registry import ConnectorContext, _onshape_meter
from solus_api.core.config import Settings
from solus_api.models import AccountConnection, ConnectionStatus, SourceType, User
from solus_api.services.connections import account_ref_for
from solus_api.services.events import emit_event

logger = logging.getLogger(__name__)

Health = Literal["healthy", "token_expired", "degraded"]

#: A bound source's sync failure that means the GRANT is gone, not the source.
_TOKEN_GONE_CODES: Final = frozenset({"invalid_credentials", "token_error"})
#: Redis key holding the last quota status Home recorded for an account, so a
#: transition is one event, not one per load. Same year-long TTL as the ledger.
_SEEN_TTL_SECONDS: Final = 400 * 24 * 3600
_EVENT_FOR_STATUS: Final = {
    "degraded": "integration.quota_degraded",
    "exhausted": "integration.quota_exhausted",
}


def connection_health(
    connection: AccountConnection,
    *,
    quota: QuotaState | None,
    source_error_codes: Iterable[str],
) -> Health:
    """Token trouble outranks quota — re-auth is what fixes it; quota trouble
    outranks nothing but is named so the card can explain what degrades."""
    if connection.status is ConnectionStatus.ERROR:
        return "token_expired"
    if any(code in _TOKEN_GONE_CODES for code in source_error_codes):
        return "token_expired"
    if quota is not None and (quota.degraded or quota.exhausted):
        return "degraded"
    return "healthy"


async def account_quota(
    settings: Settings, redis: Any | None, connection: AccountConnection
) -> QuotaState | None:
    """The meter's position for a metered provider account, or None."""
    if redis is None or connection.provider is not SourceType.ONSHAPE:
        return None
    meter = _onshape_meter(
        settings, redis, ConnectorContext(account_ref=account_ref_for(connection))
    )
    return await meter.state()


def _seen_key(connection: AccountConnection) -> str:
    return f"solus:intq:{connection.provider.value}:acct:{account_ref_for(connection)}:seen"


async def record_quota_transition(
    session: AsyncSession,
    redis: Any,
    *,
    user: User,
    connection: AccountConnection,
    quota: QuotaState,
) -> bool:
    """Emit `integration.quota_degraded` / `…_exhausted` once per transition
    INTO that state (CLAUDE.md §7: budget events feed abuse detection). Returns
    whether an event was queued. Never raises — accounting must not fail a read."""
    try:
        seen = await redis.get(_seen_key(connection))
        # A real client answers in bytes (no decode_responses); the fake in str.
        if isinstance(seen, bytes):
            seen = seen.decode("utf-8", "replace")
        if seen == quota.status:
            return False
        await redis.set(_seen_key(connection), quota.status, ex=_SEEN_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("could not read the quota transition marker")
        return False
    event_type = _EVENT_FOR_STATUS.get(quota.status)
    if event_type is None:
        return False
    emit_event(
        session,
        user=user,
        event_type=event_type,
        payload={
            "provider": connection.provider.value,
            "connection_id": str(connection.id),
            "used": quota.used,
            "allowance": quota.allowance,
            "estimated": quota.estimated,
        },
    )
    return True
