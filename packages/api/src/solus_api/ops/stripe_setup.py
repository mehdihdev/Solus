"""Stripe billing setup — operator CLI (SOLUSDEV-83 follow-up).

Usage (from packages/api):

    uv run stripe-setup put-key            # store the secret key (interactive TTY only)
    uv run stripe-setup check              # verify key + configured price ids
    uv run stripe-setup bootstrap [--yes]  # create the ADR-023/024 prices

`put-key` stores the Stripe secret key in the SecretStore under the ref the
gateway reads (`stripe_api_key`). The key is read via a hidden prompt on a real
TTY only — never argv, env, pipes, or logs — and is never echoed back
(CLAUDE.md §7). Overwriting an existing key requires confirmation.

`check` verifies the stored key against Stripe and confirms every configured
plan/pack Price id exists, is active, has the right type and interval, and
matches the deployment's mode (test prices in dev, live prices elsewhere).

`bootstrap` creates the ADR-023 plan Prices ($25/$200 BASIC, $30/$300 PRO) and
ADR-024 credit packs ($10/$25/$50/$100) idempotently — each Price carries a
`lookup_key`, so re-runs reuse what exists; an existing price that does not
match the catalog aborts loudly rather than being adopted. It previews the
exact catalog and key mode and requires confirmation (`--yes` for automation)
before touching the Stripe account, then prints the `.env.mega` lines to
paste. Amounts are PROVISIONAL until pilot calibration (ADR-023/024).

All Stripe calls pass `api_key` per call (no global `stripe.api_key` mutation),
matching the gateway's convention.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import stripe

from solus_api.billing.stripe_gateway import STRIPE_API_KEY_NAME
from solus_api.connectors.secrets import (
    InMemorySecretStore,
    SecretNotFoundError,
    SecretStore,
    build_secret_store,
)
from solus_api.core.config import Settings
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.orchestration.config import load_orchestration_config

logger = logging.getLogger("solus.ops.stripe_setup")

Out = Callable[[str], None]
Confirm = Callable[[str], bool]

# --- Catalog: ADR-023 plans + ADR-024 packs (PROVISIONAL until pilot) -----------


@dataclass(frozen=True)
class PlanPriceSpec:
    """One subscription Price to exist in Stripe: a plan at an interval."""

    plan: str
    interval: Literal["month", "year"]
    amount_cents: int

    @property
    def key(self) -> str:
        """The `stripe_plan_prices` config key ("<plan>:<interval>", plans.py)."""
        return f"{self.plan}:{self.interval}"

    @property
    def lookup_key(self) -> str:
        """Stable Stripe lookup key — makes bootstrap idempotent across runs."""
        return f"solus_plan_{self.plan}_{self.interval}"

    @property
    def product_name(self) -> str:
        return f"Solus {self.plan.capitalize()}"


PLAN_SPECS: tuple[PlanPriceSpec, ...] = (
    PlanPriceSpec("basic", "month", 25_00),
    PlanPriceSpec("basic", "year", 200_00),
    PlanPriceSpec("pro", "month", 30_00),
    PlanPriceSpec("pro", "year", 300_00),
)

# ADR-024 credit purchase packs, in dollars.
PACK_DOLLARS: tuple[int, ...] = (10, 25, 50, 100)


def pack_credits(dollars: int, *, credits_per_dollar: float) -> int:
    """Credits granted for a pack purchase. Floors so we never over-grant on a
    fractional conversion rate; the rate itself comes from models.yaml (ADR-024)."""
    return int(dollars * credits_per_dollar)


def pack_lookup_key(dollars: int) -> str:
    return f"solus_pack_{dollars}"


def format_env_lines(plan_map: dict[str, str], pack_map: dict[str, int]) -> str:
    """The exact `.env.mega` lines an operator pastes (single-quoted JSON, the
    format env-sync and pydantic-settings both accept)."""
    plans = json.dumps(plan_map, separators=(",", ":"), sort_keys=True)
    packs = json.dumps(pack_map, separators=(",", ":"), sort_keys=True)
    return f"SOLUS_STRIPE_PLAN_PRICES='{plans}'\nSOLUS_STRIPE_PACK_CREDITS='{packs}'"


def _dollars(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _key_mode(key: str) -> str:
    """TEST/LIVE label derived from the key prefix — never from key material."""
    return "TEST" if key.startswith(("sk_test_", "rk_test_")) else "LIVE"


# --- Stripe seam ------------------------------------------------------------------


@dataclass(frozen=True)
class PriceInfo:
    """The slice of a Stripe Price the CLI cares about."""

    id: str
    kind: Literal["recurring", "one_time"]
    livemode: bool
    active: bool
    amount_cents: int | None
    interval: str | None


class CatalogClient(Protocol):
    """Stripe catalog I/O behind a seam so command logic is unit-testable."""

    async def account_id(self) -> str: ...

    async def find_price_by_lookup(self, lookup_key: str) -> PriceInfo | None: ...

    async def get_price(self, price_id: str) -> PriceInfo | None: ...

    async def create_price(
        self, *, lookup_key: str, product_name: str, amount_cents: int, interval: str | None
    ) -> str: ...


def _price_info(price: stripe.Price) -> PriceInfo:
    return PriceInfo(
        id=price.id,
        kind="recurring" if price.recurring else "one_time",
        livemode=bool(price.livemode),
        active=bool(price.active),
        amount_cents=price.unit_amount,
        interval=price.recurring.interval if price.recurring else None,
    )


class StripeCatalogClient:
    """Real Stripe-backed CatalogClient; `api_key` passed per call, never global."""

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def account_id(self) -> str:
        account = await stripe.Account.retrieve_async(api_key=self._key)
        return str(account.id)

    async def find_price_by_lookup(self, lookup_key: str) -> PriceInfo | None:
        # active=True: an archived price holding the lookup key must not be
        # adopted — Checkout would reject it (security review H3).
        found = await stripe.Price.list_async(
            lookup_keys=[lookup_key], active=True, limit=1, api_key=self._key
        )
        return _price_info(found.data[0]) if found.data else None

    async def get_price(self, price_id: str) -> PriceInfo | None:
        try:
            return _price_info(await stripe.Price.retrieve_async(price_id, api_key=self._key))
        except stripe.error.InvalidRequestError:
            return None

    async def create_price(
        self, *, lookup_key: str, product_name: str, amount_cents: int, interval: str | None
    ) -> str:
        params: dict[str, object] = {
            "unit_amount": amount_cents,
            "currency": "usd",
            "lookup_key": lookup_key,
            # If an ARCHIVED price still holds this lookup key, move it here
            # instead of failing (pairs with the active=True filter above).
            "transfer_lookup_key": True,
            "product_data": {"name": product_name},
            "api_key": self._key,
        }
        if interval:
            params["recurring"] = {"interval": interval}
        price = await stripe.Price.create_async(**params)  # type: ignore[arg-type]
        return str(price.id)


# --- Commands ---------------------------------------------------------------------


def read_key_interactive(
    *,
    isatty: Callable[[], bool] | None = None,
    prompt: Callable[[str], str] | None = None,
) -> str:
    """Read the secret key from a real TTY only. Piped stdin is refused: getpass
    would silently fall back to echoing, and `echo $KEY | …` leaves the key in
    shell history and CI logs (security review H1)."""
    if not (isatty or sys.stdin.isatty)():
        raise SystemExit("Refusing: put-key must run on an interactive TTY; never pipe the key in.")
    with warnings.catch_warnings():
        # If getpass still can't disable echo, hard-fail instead of echoing.
        warnings.simplefilter("error", getpass.GetPassWarning)
        return (prompt or getpass.getpass)(
            "Stripe secret key (sk_test_... / sk_live_...): "
        ).strip()


async def run_put_key(store: SecretStore, key: str, out: Out, *, confirm: Confirm) -> None:
    """Validate and store the Stripe secret key under the gateway's ref."""
    if isinstance(store, InMemorySecretStore):
        raise SystemExit(
            "Refusing: the in-memory store loses the key on restart and lives in a "
            "different process than the API. Set SOLUS_SECRETS_KEY (local) or "
            "SOLUS_AWS_REGION (aws) first."
        )
    if not key.startswith(("sk_", "rk_")):
        raise SystemExit(
            "That doesn't look like a Stripe SECRET key (expected sk_... or rk_...); "
            "publishable keys (pk_...) cannot create checkout sessions."
        )
    try:
        existing_mode: str | None = _key_mode(await store.get(STRIPE_API_KEY_NAME))
    except SecretNotFoundError:
        existing_mode = None
    if existing_mode is not None and not confirm(
        f"A {existing_mode}-mode key is already stored under {STRIPE_API_KEY_NAME!r} — "
        "overwrite it? [yes/no]: "
    ):
        raise SystemExit("Aborted — existing key kept.")
    await store.put(STRIPE_API_KEY_NAME, key)
    mode = _key_mode(key)
    # Audit trail for the credential write (§8 structured logging) — the ref,
    # backend, and prefix-derived mode only; never any key material.
    logger.info(
        "stripe api key stored: ref=%r backend=%s mode=%s overwrote_existing=%s",
        STRIPE_API_KEY_NAME,
        type(store).__name__,
        mode,
        existing_mode is not None,
    )
    out(f"Stored {STRIPE_API_KEY_NAME!r} ({mode} mode) in the {type(store).__name__}.")


def _price_problem(
    info: PriceInfo | None, *, want_kind: str, want_interval: str | None, want_live: bool
) -> str | None:
    """Why this price can't serve checkout, or None if it's usable. Pure —
    the messages surface in run_check's per-price verdict lines."""
    if info is None:
        return "MISSING — no such price on this account"
    if info.kind != want_kind:
        return f"WRONG TYPE (is {info.kind}, need {want_kind})"
    if want_interval and info.interval != want_interval:
        return f"WRONG INTERVAL (is {info.interval}, need {want_interval})"
    if info.livemode != want_live:
        price_mode, env_wants = ("live", "test") if info.livemode else ("test", "live")
        return (
            f"MODE MISMATCH — {price_mode}-mode price, but this app_env requires {env_wants} mode"
        )
    if not info.active:
        return "INACTIVE (archived in Stripe)"
    return None


async def run_check(
    client: CatalogClient,
    *,
    plan_prices: dict[str, str],
    pack_credits_map: dict[str, int],
    app_env: str,
    out: Out,
) -> bool:
    """Verify the key reaches Stripe and every configured price id resolves to an
    active Price of the right kind, interval, and mode for this deployment.
    Returns True when billing is fully usable."""
    out(f"key: VALID — account {await client.account_id()!r}")
    want_live = app_env != "dev"

    async def verdict(label: str, price_id: str, want_kind: str, want_interval: str | None) -> bool:
        info = await client.get_price(price_id)
        problem = _price_problem(
            info, want_kind=want_kind, want_interval=want_interval, want_live=want_live
        )
        if problem:
            out(f"  {label!r} = {price_id!r}: {problem}")
            return False
        assert info is not None  # _price_problem returned None, so the price exists
        amount = _dollars(info.amount_cents) if info.amount_cents is not None else "?"
        out(
            f"  {label!r} = {price_id!r}: OK ({amount}, {'live' if info.livemode else 'test'} mode)"
        )
        return True

    ok = True
    if not plan_prices:
        out("plan prices: NONE configured (SOLUS_STRIPE_PLAN_PRICES is empty)")
        ok = False
    for key, price_id in plan_prices.items():
        _, _, interval = key.partition(":")
        ok &= await verdict(key, price_id, "recurring", interval or None)
    if not pack_credits_map:
        out("pack prices: none configured (packs are optional)")
    for price_id, credits in pack_credits_map.items():
        ok &= await verdict(f"pack→{credits}cr", price_id, "one_time", None)
    out("check: PASS — billing is fully configured" if ok else "check: FAIL — see above")
    return ok


def _bootstrap_preview(mode: str, credits_per_dollar: float, out: Out) -> None:
    """Show exactly what bootstrap will ensure, before anything is created (§7:
    external mutations show the concrete action first; security review H2)."""
    out(f"Will ensure these prices exist ({mode} mode account):")
    for spec in PLAN_SPECS:
        out(f"  {spec.lookup_key}: {_dollars(spec.amount_cents)}/{spec.interval}")
    for dollars in PACK_DOLLARS:
        credits = pack_credits(dollars, credits_per_dollar=credits_per_dollar)
        out(f"  {pack_lookup_key(dollars)}: {_dollars(dollars * 100)} one-time → {credits} credits")


async def run_bootstrap(
    client: CatalogClient,
    *,
    credits_per_dollar: float,
    mode: str,
    confirm: Confirm,
    out: Out,
) -> tuple[dict[str, str], dict[str, int]]:
    """Ensure the ADR-023/024 catalog exists in Stripe (create what's missing,
    reuse only exact matches by lookup key) and print the env lines. Returns
    (plan_map, pack_map)."""
    out(f"account: {await client.account_id()!r} — key mode: {mode}")
    _bootstrap_preview(mode, credits_per_dollar, out)
    if not confirm(f"Create/reuse these prices on this {mode}-mode account? [yes/no]: "):
        raise SystemExit("Aborted — nothing was created.")

    async def ensure(lookup_key: str, name: str, cents: int, interval: str | None) -> str:
        existing = await client.find_price_by_lookup(lookup_key)
        if existing and not existing.active:
            # Defensive: the real client filters archived prices out already.
            existing = None
        if existing:
            if existing.amount_cents != cents or existing.interval != interval:
                raise SystemExit(
                    f"{lookup_key}: existing price {existing.id!r} does not match the catalog "
                    f"(is {_dollars(existing.amount_cents or 0)}/{existing.interval}, "
                    f"want {_dollars(cents)}/{interval}) — resolve it in Stripe, then re-run."
                )
            out(f"  {lookup_key}: reusing {existing.id!r}")
            return existing.id
        price_id = await client.create_price(
            lookup_key=lookup_key, product_name=name, amount_cents=cents, interval=interval
        )
        out(f"  {lookup_key}: created {price_id!r} ({_dollars(cents)})")
        return price_id

    plan_map = {
        spec.key: await ensure(spec.lookup_key, spec.product_name, spec.amount_cents, spec.interval)
        for spec in PLAN_SPECS
    }
    pack_map = {
        await ensure(pack_lookup_key(d), f"Solus Credits ${d}", d * 100, None): pack_credits(
            d, credits_per_dollar=credits_per_dollar
        )
        for d in PACK_DOLLARS
    }
    out("\nPaste into .env.mega, then run `pnpm env:sync` and restart the API:\n")
    out(format_env_lines(plan_map, pack_map))
    return plan_map, pack_map


# --- Entry point -------------------------------------------------------------------


async def run_command(
    command: str,
    *,
    settings: Settings,
    store: SecretStore,
    make_client: Callable[[str], CatalogClient],
    key_reader: Callable[[], str],
    confirm: Confirm,
    out: Out,
) -> int:
    """Dispatch a CLI command against injected dependencies (unit-testable)."""
    if command == "put-key":
        await run_put_key(store, key_reader(), out, confirm=confirm)
        return 0

    try:
        api_key = await store.get(STRIPE_API_KEY_NAME)
    except SecretNotFoundError:
        out(f"FAIL: no {STRIPE_API_KEY_NAME!r} in the SecretStore — run put-key first.")
        return 1
    client = make_client(api_key)

    try:
        if command == "bootstrap":
            rate = load_orchestration_config().cost.credits_per_dollar
            await run_bootstrap(
                client,
                credits_per_dollar=rate,
                mode=_key_mode(api_key),
                confirm=confirm,
                out=out,
            )
            return 0
        ok = await run_check(
            client,
            plan_prices=settings.stripe_plan_prices,
            pack_credits_map=settings.stripe_pack_credits,
            app_env=settings.app_env,
            out=out,
        )
        return 0 if ok else 1
    except stripe.error.AuthenticationError:
        # Fixed message: Stripe's own text includes a partially-redacted key,
        # which would make tool output unsafe to paste into tickets (review L2).
        out("FAIL: Stripe rejected the stored key (authentication failed) — re-run put-key.")
        return 1
    except stripe.error.StripeError as exc:
        # Transient/API errors (network, rate limit) — keep the tool's consistent
        # FAIL messaging and exit code; bootstrap is idempotent, so just re-run.
        out(f"FAIL: Stripe error ({type(exc).__name__}): {exc.user_message or exc}")
        return 1


def _prompt_confirm(prompt: str) -> bool:
    return input(prompt).strip().lower() in {"y", "yes"}


async def _amain(command: str, *, assume_yes: bool) -> int:
    # Required Settings fields (e.g. supabase_jwt_secret) come from .env at
    # runtime; mypy can't see that, hence the ignore.
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    try:
        store = build_secret_store(settings, build_sessionmaker(engine))
        return await run_command(
            command,
            settings=settings,
            store=store,
            make_client=StripeCatalogClient,
            key_reader=read_key_interactive,
            confirm=(lambda _prompt: True) if assume_yes else _prompt_confirm,
            out=print,
        )
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="stripe-setup", description="Stripe billing setup (operator tool)"
    )
    parser.add_argument("command", choices=["put-key", "check", "bootstrap"])
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip confirmation prompts (bootstrap/put-key overwrite) for automation",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args.command, assume_yes=args.yes))


if __name__ == "__main__":
    sys.exit(main())
