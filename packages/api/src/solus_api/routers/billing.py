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
from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing.plans import CHECKOUTABLE_PLANS, VALID_INTERVALS, plan_price_id
from solus_api.billing.portal_config import ensure_portal_configuration
from solus_api.billing.stripe_events import process_event
from solus_api.billing.stripe_gateway import (
    BillingUnconfiguredError,
    CheckoutMode,
    StripeOperationError,
)
from solus_api.billing.summary import BillingSummaryService
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep, SettingsDep, StripeGatewayDep
from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.models import Subscription, SubscriptionStatus
from solus_api.schemas import (
    CheckoutSessionCreate,
    CheckoutSessionRead,
    PortalSessionCreate,
    PortalSessionRead,
)
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


# Portal deep links need a subscription that is still billable (SOLUSDEV-236).
_PORTAL_FLOW_STATUSES = frozenset(
    {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE}
)
_PORTAL_LIMITER_ATTR = "billing_portal_limiter"
_PORTAL_WINDOW_SECONDS = 60
PORTAL_SESSIONS_PER_MINUTE = 10

_SUMMARY_LIMITER_ATTR = "billing_summary_limiter"
_SUMMARY_WINDOW_SECONDS = 60
SUMMARY_REQUESTS_PER_MINUTE = 30

# Stripe rejects a Checkout `trial_end` less than ~48h in the future, so a local trial
# with less than this left is not carried over (SOLUSDEV-236).
_MIN_STRIPE_TRIAL_LEAD = timedelta(hours=48)


def _carried_trial_end(sub: Subscription, now: datetime | None = None) -> int | None:
    """Stripe `trial_end` (epoch seconds) that carries a LIVE local trial's remaining
    time into the paid subscription (wireflow billing.md Decisions 1). None when the
    trial is Stripe-backed, expired, has no end date, or has under 48h left (Stripe
    would refuse it) — the customer then starts paying immediately."""
    if sub.stripe_subscription_id is not None or sub.expires_at is None:
        return None
    ends_at = sub.expires_at if sub.expires_at.tzinfo else sub.expires_at.replace(tzinfo=UTC)
    if ends_at - (now or datetime.now(UTC)) <= _MIN_STRIPE_TRIAL_LEAD:
        return None
    return int(ends_at.timestamp())


def _resolve_checkout_target(
    body: CheckoutSessionCreate, sub: Subscription, settings: Settings
) -> tuple[CheckoutMode, str, int | None]:
    """Validate the request against config + the caller's current subscription and
    return (mode, price_id, trial_end). Raises APIError with a specific code on
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
        return "subscription", price_id, _carried_trial_end(sub)

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
    secrets. Sorted by credit amount ascending. `usd` is the display price (whole
    dollars) when configured; the charged amount is always the Stripe Price."""
    packs = [
        {
            "price_id": price_id,
            "credits": amount,
            "usd": settings.stripe_pack_usd.get(price_id),
        }
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
    mode, price_id, trial_end = _resolve_checkout_target(body, sub, settings)

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
            trial_end=trial_end,
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


def _portal_flow_target(sub: Subscription, flow: str | None) -> str | None:
    """The caller's own Stripe subscription id for a portal deep link (None for the
    general portal). 409s when the flow cannot apply."""
    if flow is None:
        return None
    if sub.stripe_subscription_id is None or sub.status not in _PORTAL_FLOW_STATUSES:
        raise APIError(409, "no_active_subscription", "You have no active subscription")
    if flow == "cancel" and sub.cancel_at is not None:
        raise APIError(409, "cancel_already_scheduled", "Cancellation is already scheduled")
    return sub.stripe_subscription_id


@actions_router.get("/summary")
async def get_billing_summary(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    gateway: StripeGatewayDep,
) -> Any:
    """The caller's own billing read model (SOLUSDEV-236). Stripe trouble degrades the
    Stripe-derived fields to null with a 200; it never produces a 502/503 here."""
    limiter = get_or_create_limiter(
        request.app.state, _SUMMARY_LIMITER_ATTR, _SUMMARY_WINDOW_SECONDS
    )
    if limiter.bump(str(user.id)) > SUMMARY_REQUESTS_PER_MINUTE:
        return rate_limited_response(
            "Too many billing summary requests; slow down", _SUMMARY_WINDOW_SECONDS
        )
    sub = await _subscription(session, user.id)
    summary = await BillingSummaryService(gateway, settings).summarize(sub)
    return envelope(summary.model_dump(mode="json"))


@actions_router.post("/portal-session")
async def create_portal_session(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    gateway: StripeGatewayDep,
    body: PortalSessionCreate | None = None,
) -> Any:
    """Open the Stripe-hosted billing portal (manage payment method, cancel,
    switch plan), optionally deep-linked into the update/cancel flow. Requires an
    existing Stripe customer (i.e. a prior checkout)."""
    limiter = get_or_create_limiter(request.app.state, _PORTAL_LIMITER_ATTR, _PORTAL_WINDOW_SECONDS)
    if limiter.bump(str(user.id)) > PORTAL_SESSIONS_PER_MINUTE:
        return rate_limited_response(
            "Too many billing portal requests; slow down", _PORTAL_WINDOW_SECONDS
        )
    flow = body.flow if body is not None else None
    sub = await _subscription(session, user.id)
    if not sub.stripe_customer_id:
        raise APIError(409, "no_billing_customer", "No billing account yet — subscribe first")
    subscription_id = _portal_flow_target(sub, flow)
    try:
        configuration = await ensure_portal_configuration(gateway, settings)
        url = await gateway.create_portal_session(
            customer=sub.stripe_customer_id,
            return_url=settings.stripe_billing_portal_return_url,
            configuration=configuration,
            flow=flow,
            subscription_id=subscription_id,
        )
    except BillingUnconfiguredError as exc:
        raise APIError(503, "billing_unconfigured", "Billing is not configured") from exc
    except (stripe.error.StripeError, StripeOperationError) as exc:
        logger.warning("stripe portal error: %s", type(exc).__name__)
        raise APIError(502, "billing_provider_error", "Payment provider error") from exc
    emit_event(
        session,
        user=user,
        event_type="billing.portal_session.created",
        payload={"flow": flow or "general"},
    )
    await session.commit()
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
        plan_credit_grants=settings.plan_credit_grants,
    )
    return envelope({"processed": processed})
