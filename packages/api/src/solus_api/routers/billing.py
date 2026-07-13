"""Billing webhook endpoint (SOLUSDEV-83 / SOLUS-FND-03).

The one money-in surface: Stripe posts events here. We verify the signature with
the webhook signing secret, then hand the parsed event to the idempotent,
out-of-order-safe dispatcher. Untrusted input — the body is size-bounded and
never trusted until the signature checks out.

NOTE (API plan §7.2): billing provider routes were DEFERRED pending human
decisions; this route was authorized for SOLUSDEV-83. Documented in docs/api.
"""

import json
import logging

import stripe
from fastapi import APIRouter, Request

from solus_api.billing.stripe_events import process_event
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import SessionDep, SettingsDep

logger = logging.getLogger("solus.billing.webhook")

router = APIRouter(prefix="/api/v1/webhooks")


@router.post("/stripe")
async def stripe_webhook(
    request: Request, session: SessionDep, settings: SettingsDep
) -> dict[str, object]:
    secret = settings.stripe_webhook_secret
    if not secret:
        raise APIError(503, "billing_unconfigured", "Stripe webhook is not configured")

    # Bound the untrusted body BEFORE buffering it (Stripe always sends
    # Content-Length) so an oversized POST can't exhaust memory. Keep the
    # post-read check as a backstop for a lying/absent header.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.stripe_webhook_max_bytes:
        raise APIError(413, "payload_too_large", "Webhook payload too large")
    body = await request.body()
    if len(body) > settings.stripe_webhook_max_bytes:
        raise APIError(413, "payload_too_large", "Webhook payload too large")

    signature = request.headers.get("stripe-signature")
    if not signature:
        raise APIError(400, "invalid_signature", "Missing Stripe-Signature header")

    try:
        # Verifies the HMAC signature + timestamp tolerance; raises on tamper.
        stripe.Webhook.construct_event(body, signature, secret)  # type: ignore[no-untyped-call]
    except ValueError as exc:  # malformed payload
        raise APIError(400, "invalid_signature", "Malformed webhook payload") from exc
    except stripe.error.SignatureVerificationError as exc:
        raise APIError(400, "invalid_signature", "Webhook signature verification failed") from exc

    # Signature checked out — parse the (now-trusted) body as a plain dict.
    event = json.loads(body)
    processed = await process_event(session, event, pack_credits=settings.stripe_pack_credits)
    return envelope({"processed": processed})
