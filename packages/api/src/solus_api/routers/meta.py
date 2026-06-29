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
    settings = request.app.state.settings
    checks = {
        "database": "ok",
        # ARQ/Redis wiring arrives with the first job-producing endpoint (Phase 3).
        "redis": "configured" if settings.redis_url else "not_configured",
        "queue": "not_configured",
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
