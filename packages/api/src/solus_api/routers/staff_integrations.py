"""Staff-only integration metering view (SOLUSDEV-312, ADR-038 amendment 3).

`GET /api/v1/staff/integrations/onshape/quota` — pool-wide totals per OAuth
application. Teams see only their own account's usage; the pool totals and
breakdown live here, behind `RequireStaff`. Pure Redis reads (spends no provider
calls). The pool scope is shown ONLY as a hash — never an account id or email.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request

from solus_api.connectors.quota import CallMeter, known_pools
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, RequireStaff

router = APIRouter(prefix="/api/v1/staff/integrations")


@router.get("/onshape/quota")
async def onshape_pool_quota(
    request: Request, _user: CurrentUser, _staff: RequireStaff
) -> dict[str, Any]:
    settings = request.app.state.settings
    redis = getattr(request.app.state, "redis", None)
    year = datetime.now(UTC).year
    pools: list[dict[str, Any]] = []
    for scope in await known_pools(redis, "onshape"):
        meter = CallMeter(
            redis,
            provider="onshape",
            account_ref=scope,
            year=year,
            allowance=settings.onshape_annual_call_allowance,
            degrade_ratio=settings.integration_degrade_ratio,
            pool="owner",
            distribution=settings.onshape_app_distribution,
        )
        view = await meter.pool_view()
        pools.append({"pool_scope_hash": hashlib.sha256(scope.encode()).hexdigest(), **view})
    return envelope({"pools": pools})
