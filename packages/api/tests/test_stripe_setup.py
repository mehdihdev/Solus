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
from solus_api.billing.stripe_gateway import STRIPE_API_KEY_NAME
from solus_api.connectors.secrets import InMemorySecretStore, SecretNotFoundError, SecretStore
from solus_api.core.config import Settings
from solus_api.models import PlanType
from solus_api.ops.stripe_setup import (
    PACK_DOLLARS,
    PLAN_SPECS,
    PriceInfo,
    format_env_lines,
    pack_credits,
    read_key_interactive,
    run_bootstrap,
    run_check,
    run_command,
    run_put_key,
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
