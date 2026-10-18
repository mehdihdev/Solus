"""POST /api/v1/webhooks/github/app: the GitHub App's single signed webhook (SOLUSDEV-216).

The HMAC signature is the only credential (ADR-039 section 5, docs/api/github-orgs.md):
the body is read under a hard cap, verified in constant time over the RAW bytes, and only then
parsed. The delivery claim and every effect share one transaction; syncs are enqueued only
after it commits, so a rolled-back delivery starts nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from typing import Any, Final

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request, Response

from solus_api.core.errors import APIError
from solus_api.deps import SessionDep, SettingsDep
from solus_api.services.github_app_events import PENDING_SYNCS_KEY, dispatch
from solus_api.services.github_webhook_deliveries import claim_delivery

logger = logging.getLogger("solus.webhooks.github_app")

router = APIRouter(prefix="/api/v1/webhooks/github", tags=["github-app-webhooks"])

MAX_APP_WEBHOOK_BYTES: Final = 2 * 1024 * 1024
_SIGNATURE: Final = re.compile(r"sha256=[0-9a-f]{64}", re.ASCII)
_EVENT: Final = re.compile(r"[a-z][a-z_]{0,63}", re.ASCII)
_DELIVERY: Final = re.compile(r"[A-Za-z0-9-]{1,64}", re.ASCII)


def _too_large() -> APIError:
    return APIError(413, "payload_too_large", "Webhook payload too large")


async def _read_bounded(request: Request) -> bytes:
    """The raw body, refused by declared length and again if the stream outgrows the cap."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except ValueError:
            raise APIError(400, "bad_request", "Content-Length is invalid") from None
        if size < 0 or size > MAX_APP_WEBHOOK_BYTES:
            raise _too_large()
    chunks: list[bytes] = []
    seen = 0
    async for chunk in request.stream():
        seen += len(chunk)
        if seen > MAX_APP_WEBHOOK_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_signature(secret: str, body: bytes, header: str | None) -> None:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if (
        header is None
        or _SIGNATURE.fullmatch(header) is None
        or not hmac.compare_digest(header.encode(), expected.encode())
    ):
        logger.info("github app webhook rejected: bad signature")
        raise APIError(401, "invalid_signature", "Invalid webhook signature")


def _parse(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        raise APIError(400, "bad_request", "Malformed JSON body") from None
    if not isinstance(payload, dict):
        raise APIError(400, "bad_request", "Webhook body must be a JSON object")
    return payload


def _header(request: Request, name: str, pattern: re.Pattern[str]) -> str:
    value = request.headers.get(name)
    if value is None or pattern.fullmatch(value) is None:
        raise APIError(400, "bad_request", f"Missing or invalid {name}")
    return value


@router.post("/app", status_code=204)
async def github_app_webhook(
    request: Request,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    secret = settings.github_app_webhook_secret
    if secret is None or not secret.get_secret_value():
        raise APIError(503, "github_app_unconfigured", "GitHub App webhook is not configured")
    body = await _read_bounded(request)
    _verify_signature(secret.get_secret_value(), body, request.headers.get("x-hub-signature-256"))
    payload = _parse(body)
    event = _header(request, "x-github-event", _EVENT)
    delivery = _header(request, "x-github-delivery", _DELIVERY)
    if event == "ping":
        return Response(status_code=204)

    if not await claim_delivery(session, delivery):
        logger.info("github app webhook duplicate delivery=%s", delivery)
        await session.rollback()
        return Response(status_code=204)
    await dispatch(session, event, payload, app_state=request.app.state)
    pending: list[uuid.UUID] = list(session.info.pop(PENDING_SYNCS_KEY, []))
    await session.commit()

    for source_id in dict.fromkeys(pending):
        background.add_task(_sync_source, request.app, source_id)
    return Response(status_code=204)


async def _sync_source(app: FastAPI, source_id: uuid.UUID) -> None:
    """Enqueue (ARQ) or run inline (`sync_inline` / no Redis) the ordinary sync, as
    `routers.webhooks._probe_source` does. A webhook never surfaces an error."""
    from solus_api.connectors import worker
    from solus_api.models import SyncTrigger

    state = app.state
    settings = state.settings
    try:
        if not settings.sync_inline and settings.redis_url:
            from solus_api.routers.sources import _arq_pool

            pool = getattr(state, "arq_pool", None) or await _arq_pool(app)
            await pool.enqueue_job(
                "sync_source", str(source_id), _job_id=f"github-push:{source_id}"
            )
            return
        await worker.execute_source_sync(
            sessionmaker=state.sessionmaker,
            registry=state.connector_registry,
            secret_store=state.secret_store,
            source_id=source_id,
            trigger=SyncTrigger.WEBHOOK,
            store=getattr(state, "integration_store", None),
            hub=getattr(state, "graph_hub", None),
            artifact_store=getattr(state, "artifact_store", None),
            webhook_callback_base=settings.public_api_base_url,
            label="webhook",
        )
    except Exception:  # noqa: BLE001 - a webhook must never surface an error
        logger.exception("github push sync failed source=%s", source_id)
