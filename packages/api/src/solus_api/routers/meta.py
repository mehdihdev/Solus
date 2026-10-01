"""§2.0 Infrastructure & meta — unauthenticated probes and version info."""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.core.errors import error_response
from solus_api.core.responses import envelope

logger = logging.getLogger("solus.meta")

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return envelope({"status": "ok"})


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness. 503 only when the database is unreachable.

    Redis/queue state is config-level truth (is SOLUS_REDIS_URL set?), not a
    live ping: the API holds no persistent Redis connection, so a ping would
    add a fresh TCP connect — new latency and a new crash surface — to every
    load-balancer probe. And a missing queue is an ACCEPTED degraded state this
    cycle (infrastructure/aws/README.md): it must be visible here without
    failing readiness, so a reachability result could never change the status
    code anyway.
    """
    settings = request.app.state.settings
    # The ARQ queue rides on the same DSN (ADR-005): when it is unset/empty,
    # sync dispatch falls back to in-process background tasks and scheduled
    # work (auto-resync, credit-debit reconciliation) does not run.
    queue_state = "configured" if settings.redis_url else "not_configured"
    checks = {
        "database": "ok",
        "redis": queue_state,
        "queue": queue_state,
        # ADR-037 §4: `local_only` means live updates reach this process's streams alone.
        # Informational — it never changes the status code (a single API task is valid).
        "live_fanout": request.app.state.graph_hub.fanout_mode,
    }
    try:
        maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
        async with maker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness probe: database unreachable")
        checks["database"] = "error"
        return error_response(503, "unavailable", "Dependencies not ready", [checks])
    return JSONResponse(envelope({"status": "ok", "checks": checks}))


@router.get("/api/v1/version")
async def version(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return envelope({"version": settings.api_version, "build_sha": settings.build_sha})
