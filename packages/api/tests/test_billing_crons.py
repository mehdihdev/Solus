"""SOLUSDEV-313 T8: the worker crons and API startup hook for Stripe cancels and comp expiry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fixtures.stripe_fake import FakeStripeGateway
from solus_api import main
from solus_api.billing.stripe_gateway import StripeGateway
from solus_api.connectors import worker
from solus_api.connectors.worker import build_worker_settings, cancel_stripe_subscriptions
from solus_api.core.config import Settings
from solus_api.models import (
    PlanType,
    StripeCancelRequest,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from solus_api.services.stripe_cancel import enqueue_stripe_cancel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

PAST = datetime(2026, 1, 1, tzinfo=UTC)
Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


def _broken() -> Any:
    raise RuntimeError("database unreachable")


async def _enqueue(maker: Maker, sub: str = "sub_A") -> None:
    async with maker() as s:
        await enqueue_stripe_cancel(s, customer_id="cus_A", subscription_id=sub, now=PAST)
        await s.commit()


async def _rows(maker: Maker) -> list[StripeCancelRequest]:
    async with maker() as s:
        return list((await s.scalars(select(StripeCancelRequest))).all())


def _settings() -> Any:
    return build_worker_settings(
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            supabase_jwt_secret="test-only",
            redis_url="redis://localhost:6379",
        )
    )


# ------------------------------------------------------------ registration


def test_crons_are_registered_with_the_expected_cadence() -> None:
    crons = {job.coroutine.__name__: job for job in _settings().cron_jobs}
    cancel, comps = crons["cancel_stripe_subscriptions"], crons["expire_comps"]
    assert cancel.minute is None and cancel.second == 0 and cancel.run_at_startup is True
    assert comps.minute == {0, 15, 30, 45} and comps.run_at_startup is False


# ------------------------------------------------------------ cancel wrapper


async def test_cancel_wrapper_cancels_a_due_row_end_to_end(maker: Maker) -> None:
    await _enqueue(maker)
    fake = FakeStripeGateway()
    fake.seed_subscription("sub_A")

    done = await cancel_stripe_subscriptions({"sessionmaker": maker, "stripe_gateway": fake})

    assert done == 1
    assert fake.subscriptions["sub_A"].status == "canceled"
    [row] = await _rows(maker)
    assert row.completed_at is not None


async def test_cancel_wrapper_leaves_the_row_for_retry_on_gateway_failure(maker: Maker) -> None:
    await _enqueue(maker)
    fake = FakeStripeGateway()
    fake.seed_subscription("sub_A")
    fake.fail_always("cancel_subscription", FakeStripeGateway.connection_error())

    done = await cancel_stripe_subscriptions({"sessionmaker": maker, "stripe_gateway": fake})

    assert done == 0
    [row] = await _rows(maker)
    assert row.completed_at is None and row.attempts >= 1


async def test_cancel_wrapper_builds_the_gateway_from_the_secret_store(
    maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def build(store: Any) -> FakeStripeGateway:
        seen.append(store)
        return FakeStripeGateway()

    monkeypatch.setattr(worker, "StripeGateway", build)
    store = object()
    await cancel_stripe_subscriptions({"sessionmaker": maker, "secret_store": store})
    assert seen == [store]


async def test_cancel_wrapper_never_raises() -> None:
    ctx = {"sessionmaker": _broken, "stripe_gateway": FakeStripeGateway()}
    assert await cancel_stripe_subscriptions(ctx) == 0


# ------------------------------------------------------------ comp wrapper


async def test_expire_comps_reverts_an_expired_local_comp(maker: Maker) -> None:
    uid = uuid.uuid4()
    async with maker() as s:
        s.add(User(id=uid, supabase_user_id=f"x-{uid}", email=f"{uid}@example.com"))
        await s.flush()
        s.add(
            Subscription(
                user_id=uid,
                plan=PlanType.BASIC,
                status=SubscriptionStatus.ACTIVE,
                limits=default_limits(PlanType.BASIC),
                comp_plan=PlanType.PRO,
                comp_expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await s.commit()

    assert await worker.expire_comps({"sessionmaker": maker}) == 1

    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert sub is not None and sub.comp_plan is None and sub.comp_expires_at is None


async def test_expire_comps_never_raises() -> None:
    assert await worker.expire_comps({"sessionmaker": _broken}) == 0


# ------------------------------------------------------------ API startup


async def _start(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*args: object) -> None:
        pass

    monkeypatch.setattr(main, "configure_logging", lambda: None)
    monkeypatch.setattr(main, "report_provider_refs", noop)
    monkeypatch.setattr(main, "create_all_tables", noop)
    app.state.graph_hub = SimpleNamespace(start=noop, stop=noop)
    app.state.hardware_connections = SimpleNamespace(startup=noop, aclose=noop)
    app.state.bench_sessions = SimpleNamespace(aclose_all=noop)
    app.state.device_watch = None
    async with app.router.lifespan_context(app):
        pass


async def test_startup_runs_the_stripe_cancel_drain(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, Any]] = []

    async def fake_drain(sessionmaker: Any, gateway: Any) -> None:
        calls.append((sessionmaker, gateway))

    monkeypatch.setattr(main, "run_startup_stripe_cancels", fake_drain)
    await _start(app, monkeypatch)
    [(sm, gateway)] = calls
    assert sm is app.state.sessionmaker and isinstance(gateway, StripeGateway)


async def test_a_failing_stripe_drain_does_not_break_startup(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(sessionmaker: Any, gateway: Any) -> None:
        raise RuntimeError("stripe down")

    monkeypatch.setattr(main, "run_startup_stripe_cancels", explode)
    await _start(app, monkeypatch)  # must not raise
