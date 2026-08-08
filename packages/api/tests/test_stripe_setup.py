"""Unit tests for the Stripe setup operator CLI (SOLUSDEV-83 follow-up).

No network: the Stripe catalog client is a fake and the SecretStore is a fake.
Covers the ADR-023/024 catalog data, the pack-credit conversion, the env-line
output, idempotent bootstrap (reuse-by-lookup-key, mismatch refusal, confirm
gate), the check verdicts (kind, interval, livemode-vs-app_env, active), the
put-key guardrails (prefix validation, in-memory-store refusal, overwrite
confirmation, TTY requirement, no key echo), and the run_command exit paths
(Stripe errors, missing key, no key material in output).
"""

import logging

import pytest
import stripe
from solus_api.billing.plans import VALID_INTERVALS
from solus_api.billing.stripe_events import WEBHOOK_EVENT_TYPES
from solus_api.billing.stripe_gateway import STRIPE_API_KEY_NAME
from solus_api.connectors.secrets import InMemorySecretStore, SecretNotFoundError, SecretStore
from solus_api.core.config import Settings
from solus_api.models import PlanType
from solus_api.ops.stripe_setup import (
    PACK_DOLLARS,
    PLAN_SPECS,
    WEBHOOK_ROUTE_PATH,
    PriceInfo,
    WebhookEndpointInfo,
    _resolve_confirm,
    format_env_lines,
    pack_credits,
    read_key_interactive,
    run_bootstrap,
    run_check,
    run_command,
    run_put_key,
    run_webhook,
)

TEST_KEY = "sk_test_abc123"

# --- fakes ---------------------------------------------------------------------


class _FakeStore(SecretStore):
    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(existing or {})

    async def put(self, ref: str, value: str) -> None:
        self.values[ref] = value

    async def get(self, ref: str) -> str:
        try:
            return self.values[ref]
        except KeyError as exc:
            raise SecretNotFoundError(ref) from exc

    async def delete(self, ref: str) -> None:  # pragma: no cover - unused
        self.values.pop(ref, None)


class _FakeCatalog:
    """In-memory stand-in for the Stripe catalog seam."""

    def __init__(self, existing: dict[str, PriceInfo] | None = None) -> None:
        self.by_lookup: dict[str, PriceInfo] = dict(existing or {})
        self.created: list[str] = []
        self._counter = 0

    async def account_id(self) -> str:
        return "acct_test"

    async def find_price_by_lookup(self, lookup_key: str) -> PriceInfo | None:
        found = self.by_lookup.get(lookup_key)
        return found if found and found.active else None

    async def get_price(self, price_id: str) -> PriceInfo | None:
        for info in self.by_lookup.values():
            if info.id == price_id:
                return info
        return None

    async def create_price(
        self, *, lookup_key: str, product_name: str, amount_cents: int, interval: str | None
    ) -> str:
        self._counter += 1
        price_id = f"price_new_{self._counter}"
        self.by_lookup[lookup_key] = PriceInfo(
            id=price_id,
            kind="recurring" if interval else "one_time",
            livemode=False,
            active=True,
            amount_cents=amount_cents,
            interval=interval,
        )
        self.created.append(lookup_key)
        return price_id


class _RaisingCatalog:
    """CatalogClient whose first call raises the given Stripe error."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def account_id(self) -> str:
        raise self._error

    async def find_price_by_lookup(self, lookup_key: str) -> PriceInfo | None:
        raise self._error  # pragma: no cover - account_id raises first

    async def get_price(self, price_id: str) -> PriceInfo | None:
        raise self._error  # pragma: no cover - account_id raises first

    async def create_price(self, **_: object) -> str:
        raise self._error  # pragma: no cover - account_id raises first


def _price(
    price_id: str,
    *,
    kind: str = "recurring",
    interval: str | None = "month",
    amount_cents: int = 2500,
    livemode: bool = False,
    active: bool = True,
) -> PriceInfo:
    return PriceInfo(
        id=price_id,
        kind=kind,  # type: ignore[arg-type]
        livemode=livemode,
        active=active,
        amount_cents=amount_cents,
        interval=interval if kind == "recurring" else None,
    )


def _settings(**overrides: object) -> Settings:
    # _env_file=None keeps this hermetic (see conftest): pydantic-settings merges
    # dict fields across sources, so a developer's real .env would leak in.
    return Settings(
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret="test-only",
        **overrides,  # type: ignore[arg-type]
    )


# --- catalog data (ADR-023 / ADR-024) -------------------------------------------


def test_plan_specs_match_adr023_pricing() -> None:
    amounts = {f"{s.plan}:{s.interval}": s.amount_cents for s in PLAN_SPECS}
    assert amounts == {
        "basic:month": 2500,
        "basic:year": 20000,
        "pro:month": 3000,
        "pro:year": 30000,
    }


def test_plan_specs_use_valid_plans_and_intervals() -> None:
    for spec in PLAN_SPECS:
        assert PlanType(spec.plan) in {PlanType.BASIC, PlanType.PRO}
        assert spec.interval in VALID_INTERVALS
        assert spec.lookup_key == f"solus_plan_{spec.plan}_{spec.interval}"


def test_pack_dollars_match_adr024() -> None:
    assert PACK_DOLLARS == (10, 25, 50, 100)


def test_pack_credits_conversion() -> None:
    assert pack_credits(10, credits_per_dollar=100.0) == 1000
    assert pack_credits(100, credits_per_dollar=100.0) == 10000
    assert pack_credits(25, credits_per_dollar=99.5) == 2487  # floors, never over-grants


# --- env-line output -------------------------------------------------------------


def test_format_env_lines_roundtrips_as_json() -> None:
    import json

    plan_map = {"basic:month": "price_a", "pro:year": "price_b"}
    pack_map = {"price_c": 1000, "price_d": 2500}
    out = format_env_lines(plan_map, pack_map)
    lines = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in out.splitlines()
        if "=" in line and line.startswith("SOLUS_")
    }
    assert json.loads(lines["SOLUS_STRIPE_PLAN_PRICES"].strip("'")) == plan_map
    assert json.loads(lines["SOLUS_STRIPE_PACK_CREDITS"].strip("'")) == pack_map


# --- bootstrap -------------------------------------------------------------------


async def test_bootstrap_creates_all_prices_when_none_exist() -> None:
    catalog = _FakeCatalog()
    plan_map, pack_map = await run_bootstrap(
        catalog, credits_per_dollar=100.0, mode="TEST", confirm=lambda _: True, out=lambda _: None
    )
    assert set(plan_map) == {"basic:month", "basic:year", "pro:month", "pro:year"}
    assert sorted(pack_map.values()) == [1000, 2500, 5000, 10000]
    assert len(catalog.created) == len(PLAN_SPECS) + len(PACK_DOLLARS)


async def test_bootstrap_reuses_existing_matching_price() -> None:
    existing = _price("price_existing", interval="month", amount_cents=2500)
    catalog = _FakeCatalog(existing={"solus_plan_basic_month": existing})
    plan_map, _ = await run_bootstrap(
        catalog, credits_per_dollar=100.0, mode="TEST", confirm=lambda _: True, out=lambda _: None
    )
    assert plan_map["basic:month"] == "price_existing"
    assert "solus_plan_basic_month" not in catalog.created


async def test_bootstrap_refuses_existing_price_with_wrong_amount_or_interval() -> None:
    wrong = _price("price_wrong", interval="month", amount_cents=300)  # $3, not $25
    catalog = _FakeCatalog(existing={"solus_plan_basic_month": wrong})
    with pytest.raises(SystemExit, match="solus_plan_basic_month"):
        await run_bootstrap(
            catalog,
            credits_per_dollar=100.0,
            mode="TEST",
            confirm=lambda _: True,
            out=lambda _: None,
        )
    assert catalog.created == []


async def test_bootstrap_ignores_archived_prices_and_creates_fresh() -> None:
    archived = _price("price_old", interval="month", amount_cents=2500, active=False)
    catalog = _FakeCatalog(existing={"solus_plan_basic_month": archived})
    plan_map, _ = await run_bootstrap(
        catalog, credits_per_dollar=100.0, mode="TEST", confirm=lambda _: True, out=lambda _: None
    )
    assert plan_map["basic:month"] != "price_old"
    assert "solus_plan_basic_month" in catalog.created


async def test_bootstrap_declined_confirmation_creates_nothing() -> None:
    catalog = _FakeCatalog()
    with pytest.raises(SystemExit, match="[Aa]borted"):
        await run_bootstrap(
            catalog,
            credits_per_dollar=100.0,
            mode="LIVE",
            confirm=lambda _: False,
            out=lambda _: None,
        )
    assert catalog.created == []


async def test_bootstrap_preview_shows_mode_and_catalog_before_confirm() -> None:
    catalog = _FakeCatalog()
    lines: list[str] = []
    prompts: list[str] = []

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    await run_bootstrap(
        catalog, credits_per_dollar=100.0, mode="LIVE", confirm=confirm, out=lines.append
    )
    preview = "\n".join(lines[: len(lines)])
    assert "LIVE" in preview
    assert "solus_plan_basic_month" in preview and "$25.00" in preview
    assert prompts and "LIVE" in prompts[0]


async def test_bootstrap_prints_pasteable_env_lines() -> None:
    catalog = _FakeCatalog()
    lines: list[str] = []
    plan_map, pack_map = await run_bootstrap(
        catalog, credits_per_dollar=100.0, mode="TEST", confirm=lambda _: True, out=lines.append
    )
    assert format_env_lines(plan_map, pack_map) in "\n".join(lines)


# --- check -----------------------------------------------------------------------


async def test_check_passes_when_prices_match_kind_interval_and_mode() -> None:
    catalog = _FakeCatalog(
        existing={
            "a": _price("price_plan", interval="year", amount_cents=20000),
            "b": _price("price_pack", kind="one_time"),
        }
    )
    ok = await run_check(
        catalog,
        plan_prices={"basic:year": "price_plan"},
        pack_credits_map={"price_pack": 1000},
        app_env="dev",
        out=lambda _: None,
    )
    assert ok


async def test_check_fails_on_missing_price() -> None:
    lines: list[str] = []
    ok = await run_check(
        _FakeCatalog(),
        plan_prices={"basic:month": "price_ghost"},
        pack_credits_map={},
        app_env="dev",
        out=lines.append,
    )
    assert not ok
    assert any("price_ghost" in line and "MISSING" in line for line in lines)


async def test_check_fails_on_wrong_price_kind() -> None:
    catalog = _FakeCatalog(existing={"a": _price("price_pack", kind="one_time")})
    lines: list[str] = []
    ok = await run_check(
        catalog,
        plan_prices={"basic:month": "price_pack"},  # a plan must be recurring
        pack_credits_map={},
        app_env="dev",
        out=lines.append,
    )
    assert not ok
    assert any("WRONG" in line for line in lines)


async def test_check_fails_on_interval_mismatch() -> None:
    monthly = _price("price_m", interval="month", amount_cents=20000)
    catalog = _FakeCatalog(existing={"a": monthly})
    lines: list[str] = []
    ok = await run_check(
        catalog,
        plan_prices={"basic:year": "price_m"},  # yearly plan key → monthly price
        pack_credits_map={},
        app_env="dev",
        out=lines.append,
    )
    assert not ok
    assert any("INTERVAL" in line for line in lines)


async def test_check_fails_on_test_mode_prices_in_production() -> None:
    catalog = _FakeCatalog(existing={"a": _price("price_t", livemode=False)})
    lines: list[str] = []
    ok = await run_check(
        catalog,
        plan_prices={"basic:month": "price_t"},
        pack_credits_map={},
        app_env="production",
        out=lines.append,
    )
    assert not ok
    assert any("MODE" in line for line in lines)


async def test_check_fails_on_live_mode_prices_in_dev() -> None:
    catalog = _FakeCatalog(existing={"a": _price("price_l", livemode=True)})
    ok = await run_check(
        catalog,
        plan_prices={"basic:month": "price_l"},
        pack_credits_map={},
        app_env="dev",
        out=lambda _: None,
    )
    assert not ok


async def test_check_fails_when_nothing_configured() -> None:
    ok = await run_check(
        _FakeCatalog(), plan_prices={}, pack_credits_map={}, app_env="dev", out=lambda _: None
    )
    assert not ok


# --- put-key ---------------------------------------------------------------------


async def test_put_key_stores_under_the_gateway_ref() -> None:
    store = _FakeStore()
    lines: list[str] = []
    await run_put_key(store, TEST_KEY, out=lines.append, confirm=lambda _: True)
    assert store.values[STRIPE_API_KEY_NAME] == TEST_KEY
    assert all(TEST_KEY not in line for line in lines)  # never echoed


async def test_put_key_rejects_non_secret_key_prefix() -> None:
    store = _FakeStore()
    with pytest.raises(SystemExit):
        await run_put_key(store, "pk_test_notsecret", out=lambda _: None, confirm=lambda _: True)
    assert store.values == {}


async def test_put_key_refuses_in_memory_store() -> None:
    with pytest.raises(SystemExit):
        await run_put_key(
            InMemorySecretStore(), TEST_KEY, out=lambda _: None, confirm=lambda _: True
        )


async def test_put_key_overwrite_requires_confirmation_without_key_material() -> None:
    # Deliberately short suffix: long enough to exercise the flow, short enough
    # that secret scanners (gitleaks stripe-access-token, 10+ char suffix) never
    # mistake this fixture for a real key.
    old = "sk_live_old9"
    store = _FakeStore({STRIPE_API_KEY_NAME: old})
    prompts: list[str] = []

    def refuse(prompt: str) -> bool:
        prompts.append(prompt)
        return False

    with pytest.raises(SystemExit, match="[Aa]borted"):
        await run_put_key(store, TEST_KEY, out=lambda _: None, confirm=refuse)
    assert store.values[STRIPE_API_KEY_NAME] == old  # untouched
    assert prompts and "LIVE" in prompts[0]  # mode shown…
    assert all(old not in p and old[-4:] not in p for p in prompts)  # …key material never


async def test_put_key_overwrite_proceeds_on_confirmation() -> None:
    store = _FakeStore({STRIPE_API_KEY_NAME: "sk_test_old"})
    await run_put_key(store, TEST_KEY, out=lambda _: None, confirm=lambda _: True)
    assert store.values[STRIPE_API_KEY_NAME] == TEST_KEY


async def test_put_key_emits_structured_log_without_key_material(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _FakeStore()
    with caplog.at_level(logging.INFO, logger="solus.ops.stripe_setup"):
        await run_put_key(store, TEST_KEY, out=lambda _: None, confirm=lambda _: True)
    records = [r for r in caplog.records if "stripe" in r.getMessage().lower()]
    assert records
    assert all(TEST_KEY not in r.getMessage() for r in records)


def test_read_key_refuses_non_tty_stdin() -> None:
    with pytest.raises(SystemExit, match="TTY"):
        read_key_interactive(isatty=lambda: False, prompt=lambda _: TEST_KEY)


def test_read_key_returns_stripped_input_on_tty() -> None:
    assert read_key_interactive(isatty=lambda: True, prompt=lambda _: f" {TEST_KEY} ") == TEST_KEY


# --- run_command (entrypoint wiring) ----------------------------------------------


async def _command(command: str, client: object, store: SecretStore) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = await run_command(
        command,
        settings=_settings(),
        store=store,
        make_client=lambda _key: client,  # type: ignore[arg-type,return-value]
        key_reader=lambda: TEST_KEY,
        confirm=lambda _: True,
        out=lines.append,
    )
    return code, lines


async def test_run_command_check_fails_cleanly_on_auth_error() -> None:
    client = _RaisingCatalog(stripe.error.AuthenticationError("Invalid API Key: sk_test_abc123"))
    code, lines = await _command("check", client, _FakeStore({STRIPE_API_KEY_NAME: TEST_KEY}))
    assert code == 1
    assert any("FAIL" in line for line in lines)
    assert all(TEST_KEY not in line for line in lines)  # fixed message, no echo of Stripe's


async def test_run_command_check_fails_cleanly_on_transient_stripe_error() -> None:
    error = stripe.error.APIConnectionError("connection reset")  # type: ignore[no-untyped-call]
    client = _RaisingCatalog(error)
    code, lines = await _command("check", client, _FakeStore({STRIPE_API_KEY_NAME: TEST_KEY}))
    assert code == 1
    assert any("FAIL" in line and "APIConnectionError" in line for line in lines)


async def test_run_command_check_requires_stored_key() -> None:
    code, lines = await _command("check", _FakeCatalog(), _FakeStore())
    assert code == 1
    assert any("put-key" in line for line in lines)


async def test_run_command_put_key_never_touches_stripe() -> None:
    calls: list[str] = []
    store = _FakeStore()
    code = await run_command(
        "put-key",
        settings=_settings(),
        store=store,
        make_client=lambda key: calls.append(key),  # type: ignore[arg-type,return-value]
        key_reader=lambda: TEST_KEY,
        confirm=lambda _: True,
        out=lambda _: None,
    )
    assert code == 0
    assert calls == []  # no Stripe client was ever constructed
    assert store.values[STRIPE_API_KEY_NAME] == TEST_KEY


def test_no_global_stripe_key_mutation() -> None:
    # Every command above ran against the module; the SDK global must stay unset.
    assert stripe.api_key is None


# --- webhook (production endpoint registration) ------------------------------------

WEBHOOK_SECRET_FIXTURE = "whsec_fake_test_fixture"
PROD_BASE = "https://api.solus.example"
PROD_URL = f"{PROD_BASE}{WEBHOOK_ROUTE_PATH}"


def _endpoint(
    url: str = PROD_URL,
    *,
    endpoint_id: str = "we_existing",
    status: str = "enabled",
    events: tuple[str, ...] | None = None,
) -> WebhookEndpointInfo:
    return WebhookEndpointInfo(
        id=endpoint_id,
        url=url,
        status=status,
        enabled_events=tuple(sorted(WEBHOOK_EVENT_TYPES)) if events is None else events,
    )


class _FakeWebhooks:
    """In-memory stand-in for the Stripe webhook-endpoint seam."""

    def __init__(self, existing: tuple[WebhookEndpointInfo, ...] = ()) -> None:
        self.endpoints: list[WebhookEndpointInfo] = list(existing)
        self.created: list[WebhookEndpointInfo] = []
        self.updated: list[tuple[str, tuple[str, ...]]] = []

    async def account_id(self) -> str:
        return "acct_test"

    async def list_webhook_endpoints(self) -> list[WebhookEndpointInfo]:
        return list(self.endpoints)

    async def create_webhook_endpoint(
        self, *, url: str, events: tuple[str, ...]
    ) -> tuple[WebhookEndpointInfo, str]:
        info = WebhookEndpointInfo(
            id=f"we_new_{len(self.created) + 1}", url=url, status="enabled", enabled_events=events
        )
        self.endpoints.append(info)
        self.created.append(info)
        return info, WEBHOOK_SECRET_FIXTURE

    async def update_webhook_endpoint(self, endpoint_id: str, *, events: tuple[str, ...]) -> None:
        self.updated.append((endpoint_id, events))


def test_webhook_event_types_cover_exactly_what_the_dispatcher_handles() -> None:
    # The registration list and the dispatcher must never drift: an event the
    # dispatcher handles but the endpoint doesn't subscribe to silently breaks
    # billing in production.
    assert WEBHOOK_EVENT_TYPES == frozenset(
        {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "checkout.session.completed",
            "invoice.payment_failed",
        }
    )


def _tty() -> bool:
    return True


async def test_webhook_creates_endpoint_when_none_exists() -> None:
    client = _FakeWebhooks()
    lines: list[str] = []
    await run_webhook(
        client,
        base_url=PROD_BASE,
        mode="LIVE",
        confirm=lambda _: True,
        out=lines.append,
        isatty=_tty,
    )
    assert len(client.created) == 1
    created = client.created[0]
    assert created.url == PROD_URL
    assert set(created.enabled_events) == set(WEBHOOK_EVENT_TYPES)
    # The signing secret is printed exactly once, as a pasteable env line, with
    # a handling warning — and nowhere else.
    secret_lines = [line for line in lines if WEBHOOK_SECRET_FIXTURE in line]
    assert secret_lines == [f"SOLUS_STRIPE_WEBHOOK_SECRET={WEBHOOK_SECRET_FIXTURE}"]
    assert any("shown once" in line.lower() or "secrets manager" in line.lower() for line in lines)


async def test_webhook_refuses_to_create_when_stdout_is_not_a_tty() -> None:
    # Creating prints the one-time signing secret; a redirected/piped/CI stdout
    # would persist it (same threat model as read_key_interactive, H1).
    client = _FakeWebhooks()
    lines: list[str] = []
    with pytest.raises(SystemExit, match="TTY"):
        await run_webhook(
            client,
            base_url=PROD_BASE,
            mode="LIVE",
            confirm=lambda _: True,
            out=lines.append,
            isatty=lambda: False,
        )
    assert client.created == []  # refused BEFORE creating — the secret is never burned
    assert all(WEBHOOK_SECRET_FIXTURE not in line for line in lines)


async def test_webhook_update_path_allows_non_tty() -> None:
    # Updating prints no secret, so it stays automatable.
    client = _FakeWebhooks(existing=(_endpoint(events=("checkout.session.completed",)),))
    await run_webhook(
        client,
        base_url=PROD_BASE,
        mode="LIVE",
        confirm=lambda _: True,
        out=lambda _: None,
        isatty=lambda: False,
    )
    assert client.updated


async def test_webhook_normalizes_trailing_slash_on_base_url() -> None:
    client = _FakeWebhooks()
    await run_webhook(
        client,
        base_url=f"{PROD_BASE}/",
        mode="LIVE",
        confirm=lambda _: True,
        out=lambda _: None,
        isatty=_tty,
    )
    assert client.created[0].url == PROD_URL


async def test_webhook_existing_matching_endpoint_is_left_alone() -> None:
    client = _FakeWebhooks(existing=(_endpoint(),))
    lines: list[str] = []
    await run_webhook(
        client,
        base_url=PROD_BASE,
        mode="LIVE",
        confirm=lambda _: True,
        out=lines.append,
        isatty=_tty,
    )
    assert client.created == []
    assert client.updated == []
    # No secret can be re-fetched for an existing endpoint; say so instead.
    assert all(WEBHOOK_SECRET_FIXTURE not in line for line in lines)
    assert any("OK" in line for line in lines)


async def test_webhook_existing_with_drifted_events_is_updated() -> None:
    stale = _endpoint(events=("checkout.session.completed",))
    client = _FakeWebhooks(existing=(stale,))
    await run_webhook(
        client,
        base_url=PROD_BASE,
        mode="LIVE",
        confirm=lambda _: True,
        out=lambda _: None,
        isatty=_tty,
    )
    assert client.created == []
    assert client.updated == [("we_existing", tuple(sorted(WEBHOOK_EVENT_TYPES)))]


async def test_webhook_disabled_endpoint_is_updated() -> None:
    client = _FakeWebhooks(existing=(_endpoint(status="disabled"),))
    await run_webhook(
        client,
        base_url=PROD_BASE,
        mode="LIVE",
        confirm=lambda _: True,
        out=lambda _: None,
        isatty=_tty,
    )
    assert client.updated  # re-enabled via update
    assert client.created == []


async def test_webhook_wildcard_endpoint_is_treated_as_covering() -> None:
    # A "*" endpoint receives every event; shrinking it to our list could break
    # another consumer sharing the endpoint — leave it alone.
    client = _FakeWebhooks(existing=(_endpoint(events=("*",)),))
    await run_webhook(
        client,
        base_url=PROD_BASE,
        mode="LIVE",
        confirm=lambda _: True,
        out=lambda _: None,
        isatty=_tty,
    )
    assert client.created == []
    assert client.updated == []


async def test_webhook_disabled_wildcard_endpoint_is_not_reported_ok() -> None:
    # A disabled wildcard endpoint means billing is silently dead — the tool
    # must fail loudly, never print "OK".
    client = _FakeWebhooks(existing=(_endpoint(status="disabled", events=("*",)),))
    with pytest.raises(SystemExit, match="(?i)disabled"):
        await run_webhook(
            client,
            base_url=PROD_BASE,
            mode="LIVE",
            confirm=lambda _: True,
            out=lambda _: None,
            isatty=_tty,
        )
    assert client.created == []
    assert client.updated == []


async def test_webhook_declined_confirmation_changes_nothing() -> None:
    client = _FakeWebhooks()
    with pytest.raises(SystemExit, match="[Aa]borted"):
        await run_webhook(
            client,
            base_url=PROD_BASE,
            mode="LIVE",
            confirm=lambda _: False,
            out=lambda _: None,
            isatty=_tty,
        )
    assert client.created == []
    assert client.updated == []


async def test_webhook_preview_shows_url_events_and_mode_before_confirm() -> None:
    client = _FakeWebhooks()
    lines: list[str] = []
    prompts: list[str] = []

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    await run_webhook(
        client, base_url=PROD_BASE, mode="LIVE", confirm=confirm, out=lines.append, isatty=_tty
    )
    preview = "\n".join(lines)
    assert PROD_URL in preview
    assert "checkout.session.completed" in preview
    assert prompts and "LIVE" in prompts[0]


async def test_webhook_create_and_update_emit_audit_log_without_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="solus.ops.stripe_setup"):
        fresh = _FakeWebhooks()
        await run_webhook(
            fresh,
            base_url=PROD_BASE,
            mode="LIVE",
            confirm=lambda _: True,
            out=lambda _: None,
            isatty=_tty,
        )
        stale = _FakeWebhooks(existing=(_endpoint(events=("checkout.session.completed",)),))
        await run_webhook(
            stale,
            base_url=PROD_BASE,
            mode="LIVE",
            confirm=lambda _: True,
            out=lambda _: None,
            isatty=_tty,
        )
    messages = [r.getMessage() for r in caplog.records]
    assert any("created" in m and fresh.created[0].id in m for m in messages)
    assert any("updated" in m and "we_existing" in m for m in messages)
    assert all("whsec_" not in m for m in messages)  # never any secret material


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://api.solus.example",  # not https
        "https://localhost:8000",  # local dev — that's what `pnpm dev:stripe` is for
        "https://127.0.0.1:8000",
        "not-a-url",
        "",
        "https://user:pw@api.solus.example",  # userinfo would ship credentials to Stripe
        "https://api.solus.example?x=1",  # query corrupts the registered URL
        "https://api.solus.example#frag",
        f"https://api.solus.example{WEBHOOK_ROUTE_PATH}",  # full webhook URL, not the base
    ],
)
async def test_webhook_refuses_malformed_or_local_urls(bad_url: str) -> None:
    client = _FakeWebhooks()
    with pytest.raises(SystemExit):
        await run_webhook(
            client,
            base_url=bad_url,
            mode="LIVE",
            confirm=lambda _: True,
            out=lambda _: None,
            isatty=_tty,
        )
    assert client.created == []


async def test_webhook_refuses_ambiguous_duplicate_endpoints() -> None:
    client = _FakeWebhooks(existing=(_endpoint(endpoint_id="we_1"), _endpoint(endpoint_id="we_2")))
    with pytest.raises(SystemExit, match="[Mm]ultiple"):
        await run_webhook(
            client,
            base_url=PROD_BASE,
            mode="LIVE",
            confirm=lambda _: True,
            out=lambda _: None,
            isatty=_tty,
        )
    assert client.updated == []


def test_assume_yes_never_applies_to_webhook() -> None:
    # §7: registering/updating a live webhook endpoint is an external mutation
    # that must show the concrete action — `--yes` must not bypass it.
    assert _resolve_confirm("bootstrap", assume_yes=True)("anything?") is True
    assert _resolve_confirm("webhook", assume_yes=True) is _resolve_confirm(
        "webhook", assume_yes=False
    )


async def test_run_command_webhook_requires_stored_key() -> None:
    lines: list[str] = []
    code = await run_command(
        "webhook",
        settings=_settings(),
        store=_FakeStore(),
        make_client=lambda _key: _FakeWebhooks(),  # type: ignore[arg-type,return-value]
        key_reader=lambda: TEST_KEY,
        confirm=lambda _: True,
        out=lines.append,
        url=PROD_BASE,
    )
    assert code == 1
    assert any("put-key" in line for line in lines)


async def test_run_command_webhook_registers_endpoint() -> None:
    client = _FakeWebhooks()
    code = await run_command(
        "webhook",
        settings=_settings(),
        store=_FakeStore({STRIPE_API_KEY_NAME: TEST_KEY}),
        make_client=lambda _key: client,  # type: ignore[arg-type,return-value]
        key_reader=lambda: TEST_KEY,
        confirm=lambda _: True,
        out=lambda _: None,
        url=PROD_BASE,
        stdout_isatty=_tty,
    )
    assert code == 0
    assert len(client.created) == 1


@pytest.mark.parametrize(
    ("key", "app_env"),
    [
        (TEST_KEY, "production"),  # test key must never register a production endpoint
        ("sk_live_x9", "dev"),  # live key must never register a dev endpoint
    ],
)
async def test_run_command_webhook_refuses_key_mode_env_mismatch(key: str, app_env: str) -> None:
    # A TEST-mode endpoint registered for production signs with a test secret,
    # so every real payment event is silently rejected (security review M3).
    client = _FakeWebhooks()
    lines: list[str] = []
    code = await run_command(
        "webhook",
        settings=_settings(app_env=app_env),
        store=_FakeStore({STRIPE_API_KEY_NAME: key}),
        make_client=lambda _key: client,  # type: ignore[arg-type,return-value]
        key_reader=lambda: key,
        confirm=lambda _: True,
        out=lines.append,
        url=PROD_BASE,
        stdout_isatty=_tty,
    )
    assert code == 1
    assert client.created == []
    assert any("FAIL" in line and "mode" in line for line in lines)


async def test_run_command_webhook_without_url_fails_cleanly() -> None:
    code = await run_command(
        "webhook",
        settings=_settings(),
        store=_FakeStore({STRIPE_API_KEY_NAME: TEST_KEY}),
        make_client=lambda _key: _FakeWebhooks(),  # type: ignore[arg-type,return-value]
        key_reader=lambda: TEST_KEY,
        confirm=lambda _: True,
        out=lambda _: None,
        url=None,
    )
    assert code == 1
