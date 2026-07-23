"""Outbound Stripe API — the money-in *initiation* surface (SOLUSDEV-83 follow-up).

Creates Stripe Customers, Checkout Sessions, and Billing Portal sessions. This is
the only place Solus calls Stripe outbound; the inbound webhook lives in
routers/billing.py + billing/stripe_events.py.

Security (CLAUDE.md §7): the Stripe SECRET key is sourced from the SecretStore
under `stripe_api_key` — never from config, env, or logs — and is passed per call
via the SDK's `api_key` option (no global mutable `stripe.api_key`, so concurrent
requests never race on it). Absent key ⇒ BillingUnconfiguredError, which the route
maps to 503, mirroring the webhook's `billing_unconfigured`.
"""

import logging
from typing import Any, Literal

import stripe

from solus_api.connectors.secrets import SecretNotFoundError, SecretStore

logger = logging.getLogger("solus.billing.stripe_gateway")

# SecretStore ref for the Stripe secret API key (sk_...). Provisioned by an
# operator into AWS Secrets Manager / the local Fernet store, like the LLM keys.
STRIPE_API_KEY_NAME = "stripe_api_key"

CheckoutMode = Literal["subscription", "payment"]


class BillingUnconfiguredError(RuntimeError):
    """No Stripe secret key is provisioned — Solus cannot call Stripe yet."""


class StripeGateway:
    """Thin async wrapper over the Stripe SDK, keyed from the SecretStore."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store

    async def _api_key(self) -> str:
        try:
            return await self._secret_store.get(STRIPE_API_KEY_NAME)
        except SecretNotFoundError as exc:
            raise BillingUnconfiguredError(
                f"No Stripe API key; set {STRIPE_API_KEY_NAME!r} in Secrets Manager / SecretStore."
            ) from exc

    async def get_or_create_customer(
        self, *, existing: str | None, email: str, user_id: str
    ) -> str:
        """Reuse the user's Stripe customer id if we already have one, else create
        one tagged with the Solus user id. Returns the customer id."""
        if existing:
            return existing
        key = await self._api_key()
        # Stripe's SDK params are strict TypedDicts; build a dynamic dict and splat.
        # Idempotency key (per user) collapses a double-submit into one customer.
        params: dict[str, Any] = {
            "metadata": {"solus_user_id": user_id},
            "api_key": key,
            "idempotency_key": f"solus-customer-{user_id}",
        }
        if email:
            params["email"] = email
        customer = await stripe.Customer.create_async(**params)
        return str(customer.id)

    async def create_checkout_session(
        self,
        *,
        mode: CheckoutMode,
        price_id: str,
        customer: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int | None = None,
    ) -> str:
        """Create a hosted Checkout Session and return its redirect URL. The user
        id rides in both `client_reference_id` and `metadata.solus_user_id`, and
        the price id in `metadata.price_id`, so the webhook can attribute the
        purchase and (for packs) grant the right credits."""
        key = await self._api_key()
        params: dict[str, Any] = {
            "mode": mode,
            "line_items": [{"price": price_id, "quantity": 1}],
            "customer": customer,
            "client_reference_id": user_id,
            "metadata": {"solus_user_id": user_id, "price_id": price_id},
            "success_url": success_url,
            "cancel_url": cancel_url,
            "api_key": key,
        }
        if mode == "subscription" and trial_days:
            params["subscription_data"] = {"trial_period_days": trial_days}
        session = await stripe.checkout.Session.create_async(**params)
        return str(session.url)

    async def create_portal_session(self, *, customer: str, return_url: str) -> str:
        """Create a Stripe-hosted Billing Portal session (manage/cancel/update
        card) and return its URL."""
        key = await self._api_key()
        params: dict[str, Any] = {"customer": customer, "return_url": return_url, "api_key": key}
        session = await stripe.billing_portal.Session.create_async(**params)
        return str(session.url)
