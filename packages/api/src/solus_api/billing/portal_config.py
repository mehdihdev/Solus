"""Code-managed Stripe Billing Portal configuration (SOLUSDEV-236).

The portal behaviour the billing wireflow approved lives here, not in the Stripe
dashboard: upgrades (higher amount / longer interval) are charged now with
proration, downgrades (lower amount / shorter interval) are scheduled at period
end, cancellation is at period end, plus payment-method update and invoice
history. `portal_configuration_params` is pure (graph/settings in, params out);
`ensure_portal_configuration` finds or creates the matching Stripe configuration
once and caches its id so no request ever creates one.
"""

import asyncio
import hashlib
import json
import logging
import weakref
from collections.abc import Mapping
from typing import Any, Protocol

from solus_api.billing.plans import CHECKOUTABLE_PLANS, VALID_INTERVALS, plan_price_id
from solus_api.billing.stripe_gateway import BillingUnconfiguredError
from solus_api.core.config import Settings

logger = logging.getLogger("solus.billing.portal_config")

#: Bump when the shape of the configuration below changes in a way a price change
#: would not capture; it is part of every configuration's identity.
PORTAL_CONFIG_VERSION = "1"
VERSION_METADATA_KEY = "solus_portal_config"
HASH_METADATA_KEY = "solus_config_hash"
_HASH_HEX_LENGTH = 32


class PortalConfigGateway(Protocol):
    async def list_portal_configurations(self) -> list[Any]: ...

    async def create_portal_configuration(
        self, params: dict[str, Any], *, key_hash: str
    ) -> str: ...

    async def price_products(self, price_ids: list[str]) -> dict[str, str]: ...


def _plan_price_ids(settings: Settings) -> list[str]:
    """Prices the portal may switch between — the same gate as Checkout
    (CHECKOUTABLE_PLANS × VALID_INTERVALS), so a stray enterprise or malformed key
    in `stripe_plan_prices` never becomes a self-serve switch target."""
    ids = {
        plan_price_id(settings, plan, interval)
        for plan in CHECKOUTABLE_PLANS
        for interval in VALID_INTERVALS
    }
    return sorted(pid for pid in ids if pid)


def _stable_hash(payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:_HASH_HEX_LENGTH]


def portal_fingerprint(settings: Settings) -> str:
    """Cache key: identity of the configuration derivable WITHOUT any Stripe call."""
    return _stable_hash({"v": PORTAL_CONFIG_VERSION, "prices": _plan_price_ids(settings)})


def portal_configuration_params(
    settings: Settings, price_products: Mapping[str, str]
) -> dict[str, Any]:
    """Params for `billing_portal.Configuration.create`. `price_products` maps each
    configured Price id to its Stripe Product id (resolved by the gateway)."""
    by_product: dict[str, list[str]] = {}
    for price_id in _plan_price_ids(settings):
        by_product.setdefault(price_products[price_id], []).append(price_id)
    features: dict[str, Any] = {
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "products": [
                {"product": p, "prices": sorted(ids)} for p, ids in sorted(by_product.items())
            ],
            # Upgrades are invoiced immediately with proration ...
            "proration_behavior": "always_invoice",
            # ... downgrades wait for the period end (wireflow billing.md Decisions).
            "schedule_at_period_end": {
                "conditions": [
                    {"type": "decreasing_item_amount"},
                    {"type": "shortening_interval"},
                ]
            },
        },
        "subscription_cancel": {
            "enabled": True,
            "mode": "at_period_end",
            "proration_behavior": "none",
        },
        "payment_method_update": {"enabled": True},
        "invoice_history": {"enabled": True},
        # Off: the account email is owned by Solus auth; editing it in Stripe would drift.
        "customer_update": {"enabled": False},
    }
    return {
        "features": features,
        "metadata": {
            VERSION_METADATA_KEY: PORTAL_CONFIG_VERSION,
            HASH_METADATA_KEY: _stable_hash(features),
        },
    }


class PortalConfigCache:
    """In-process fingerprint -> configuration id, with one lock per event loop so
    concurrent first requests create at most one configuration."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}
        self._locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
            weakref.WeakKeyDictionary()
        )

    def lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        return self._locks.setdefault(loop, asyncio.Lock())

    def get(self, key: str) -> str | None:
        return self._ids.get(key)

    def put(self, key: str, config_id: str) -> None:
        self._ids[key] = config_id

    def clear(self) -> None:
        self._ids.clear()


_CACHE = PortalConfigCache()


def reset_portal_config_cache() -> None:
    _CACHE.clear()


def _matching_id(configs: list[Any], want_hash: str) -> str | None:
    for config in configs:
        meta = (
            config.get("metadata")
            if isinstance(config, Mapping)
            else getattr(config, "metadata", None)
        )
        meta = meta or {}
        if (
            meta.get(VERSION_METADATA_KEY) == PORTAL_CONFIG_VERSION
            and meta.get(HASH_METADATA_KEY) == want_hash
        ):
            return str(config["id"] if isinstance(config, Mapping) else config.id)
    return None


async def ensure_portal_configuration(
    gateway: PortalConfigGateway, settings: Settings, *, cache: PortalConfigCache | None = None
) -> str:
    """Id of the Stripe portal configuration matching the code definition: cached, else
    reused from Stripe by version+hash metadata, else created exactly once."""
    store = cache or _CACHE
    prices = _plan_price_ids(settings)
    if not prices:
        raise BillingUnconfiguredError("No Stripe plan prices configured for the billing portal.")
    key = portal_fingerprint(settings)
    if (hit := store.get(key)) is not None:
        return hit
    async with store.lock():
        if (hit := store.get(key)) is not None:
            return hit
        params = portal_configuration_params(settings, await gateway.price_products(prices))
        want_hash = params["metadata"][HASH_METADATA_KEY]
        config_id = _matching_id(await gateway.list_portal_configurations(), want_hash)
        if config_id is None:
            config_id = await gateway.create_portal_configuration(params, key_hash=want_hash)
            logger.info("created billing portal configuration hash=%s", want_hash)
        store.put(key, config_id)
        return config_id
