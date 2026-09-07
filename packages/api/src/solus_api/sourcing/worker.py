"""ARQ entry for `JobKind.SOURCING` (SOLUSDEV-246 ST5). Never raises."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from solus_api.sourcing.engine import run_request

logger = logging.getLogger("solus.sourcing")

SOURCING_JOB = "sourcing_request"


async def sourcing_request(ctx: dict[str, Any], request_id: str) -> str:
    try:
        target = uuid.UUID(request_id)
    except ValueError:
        logger.error("sourcing: malformed request id %r", request_id)
        return ""
    try:
        status = await run_request(
            ctx["sessionmaker"],
            target,
            secret_store=ctx["secret_store"],
            redis=ctx.get("redis"),
        )
    except Exception:  # noqa: BLE001 — never raise to ARQ
        logger.exception("sourcing: unrecoverable failure request=%s", target)
        return "error"
    return status.value if status is not None else ""
