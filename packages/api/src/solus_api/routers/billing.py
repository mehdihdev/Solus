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
import uuid

import stripe
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing.plans import CHECKOUTABLE_PLANS, VALID_INTERVALS, plan_price_id
from solus_api.billing.stripe_events import process_event
from solus_api.billing.stripe_gateway import BillingUnconfiguredError, CheckoutMode
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep, SettingsDep, StripeGatewayDep
from solus_api.models import Subscription, SubscriptionStatus
from solus_api.schemas import CheckoutSessionCreate, CheckoutSessionRead, PortalSessionRead
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.billing.webhook")

router = APIRouter(prefix="/api/v1/webhooks")

# Authenticated, customer-facing billing actions (the outbound money-in surface).
# Separate router from the unauthenticated webhook above; both live in this module.
actions_router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


async def _subscription(session: AsyncSession, user_id: uuid.UUID) -> Subscription:
    sub = await session.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id, Subscription.deleted_at.is_(None)
        )
    )
    if sub is None:
        raise APIError(404, "not_found", "No subscription")
    return sub


# A subscription with a real Stripe subscription id in one of these states is
# already billing — a new Checkout would double-bill (see _resolve_checkout_target).
_LIVE_SUBSCRIPTION_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING})


def _resolve_checkout_target(
    body: CheckoutSessionCreate, sub: Subscription, settings: Settings
) -> tuple[CheckoutMode, str, int | None]:
    """Validate the request against config + the caller's current subscription and
    return (mode, price_id, trial_days). Raises APIError with a specific code on
    any invalid / unconfigured / duplicate-subscription case."""
    if body.kind == "subscription":
        if body.plan not in CHECKOUTABLE_PLANS:
            raise APIError(
                400, "plan_not_checkoutable", "This plan is not available for self-serve checkout"
            )
        # A fresh subscription-mode Checkout against an existing customer creates
        # a SECOND, separately billed Stripe subscription (double-billing) and
        # corrupts our single stripe_subscription_id mapping. An existing
        # paid/trialing Stripe subscriber changes plans in the billing portal.
        if sub.stripe_subscription_id and sub.status in _LIVE_SUBSCRIPTION_STATUSES:
            raise APIError(
                409,
                "already_subscribed",
                "You already have an active subscription — change plans in the billing portal.",
            )
        if body.interval not in VALID_INTERVALS:
            raise APIError(400, "invalid_interval", "interval must be 'month' or 'year'")
        price_id = plan_price_id(settings, body.plan, body.interval)
        if not price_id:
            raise APIError(
                503, "billing_unconfigured", "No Stripe price is configured for this plan"
            )
        return "subscription", price_id, settings.stripe_trial_days

    # credit pack: empty catalog is a server-config gap (503); a non-empty catalog
    # with an unknown id is a bad request (400).
    price_id = body.price_id or ""
    if not settings.stripe_pack_credits:
        raise APIError(503, "billing_unconfigured", "Credit packs are not configured")
    if price_id not in settings.stripe_pack_credits:
        raise APIError(400, "invalid_pack", "Unknown credit pack")
    return "payment", price_id, None


@actions_router.get("/packs")
async def list_credit_packs(user: CurrentUser, settings: SettingsDep) -> dict[str, object]:
    """The credit packs available for purchase (ADR-024), from server config so the
    UI never hard-codes environment-specific Stripe Price ids. Price ids are not
    secrets. Sorted by credit amount ascending."""
    packs = [
        {"price_id": price_id, "credits": amount}
        for price_id, amount in sorted(settings.stripe_pack_credits.items(), key=lambda kv: kv[1])
    ]
    return envelope({"packs": packs})


@actions_router.post("/checkout-session")
async def create_checkout_session(
    body: CheckoutSessionCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    gateway: StripeGatewayDep,
) -> dict[str, object]:
    """Start a Stripe Checkout for a subscription plan or a credit pack, returning
    the hosted redirect URL. The entitlement is applied by the webhook once Stripe
    confirms payment — never from this request (SOLUSDEV-83 / ADR-024)."""
    sub = await _subscription(session, user.id)
    mode, price_id, trial = _resolve_checkout_target(body, sub, settings)

    try:
        customer = await gateway.get_or_create_customer(
            existing=sub.stripe_customer_id, email=user.email, user_id=str(user.id)
        )
        if customer != sub.stripe_customer_id:
            sub.stripe_customer_id = customer
            await session.commit()
        url = await gateway.create_checkout_session(
            mode=mode,
            price_id=price_id,
            customer=customer,
            user_id=str(user.id),
            success_url=settings.stripe_checkout_success_url,
            cancel_url=settings.stripe_checkout_cancel_url,
            trial_days=trial,
        )
    except BillingUnconfiguredError as exc:
        raise APIError(503, "billing_unconfigured", "Billing is not configured") from exc
    except stripe.error.StripeError as exc:
        logger.warning("stripe checkout error: %s", type(exc).__name__)
        raise APIError(502, "billing_provider_error", "Payment provider error") from exc

    emit_event(
        session,
        user=user,
        event_type="billing.checkout_session.created",
        payload={"kind": body.kind, "price_id": price_id},
    )
    await session.commit()
    return envelope(CheckoutSessionRead(url=url).model_dump())


@actions_router.post("/portal-session")
async def create_portal_session(
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    gateway: StripeGatewayDep,
) -> dict[str, object]:
    """Open the Stripe-hosted billing portal (manage payment method, cancel,
    switch plan). Requires an existing Stripe customer (i.e. a prior checkout)."""
    sub = await _subscription(session, user.id)
    if not sub.stripe_customer_id:
        raise APIError(409, "no_billing_customer", "No billing account yet — subscribe first")
    try:
        url = await gateway.create_portal_session(
            customer=sub.stripe_customer_id,
            return_url=settings.stripe_billing_portal_return_url,
        )
    except BillingUnconfiguredError as exc:
        raise APIError(503, "billing_unconfigured", "Billing is not configured") from exc
    except stripe.error.StripeError as exc:
        logger.warning("stripe portal error: %s", type(exc).__name__)
        raise APIError(502, "billing_provider_error", "Payment provider error") from exc
    return envelope(PortalSessionRead(url=url).model_dump())


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
    processed = await process_event(
        session,
        event,
        pack_credits=settings.stripe_pack_credits,
        plan_prices=settings.stripe_plan_prices,
    )
    return envelope({"processed": processed})
