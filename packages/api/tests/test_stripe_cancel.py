"""SOLUSDEV-313: durable Stripe cancel-on-account-deletion obligation (mirrors cad_purge)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fixtures.stripe_fake import FakeStripeGateway
from solus_api.billing.stripe_gateway import BillingUnconfiguredError, StripeOperationError
from solus_api.models import StripeCancelRequest
from solus_api.services import stripe_cancel
from solus_api.services.stripe_cancel import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS,
    LEASE_SECONDS,
    TERMINAL_BACKOFF_SECONDS,
    enqueue_stripe_cancel,
    is_tombstoned_customer,
    run_due_stripe_cancels,
    run_startup_stripe_cancels,
    run_stripe_cancels_after_commit,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


async def _rows(db: AsyncSession) -> list[StripeCancelRequest]:
    db.expire_all()
    return list((await db.scalars(select(StripeCancelRequest))).all())


async def _enqueue(db: AsyncSession, cus: str = "cus_A", sub: str | None = "sub_A") -> None:
    await enqueue_stripe_cancel(db, customer_id=cus, subscription_id=sub, now=NOW)
    await db.commit()


def _fake(*subs: str, customer: str = "cus_A") -> FakeStripeGateway:
    fake = FakeStripeGateway()
    for sub in subs:
        fake.seed_subscription(sub, customer_id=customer)
    return fake


def _audit_ids(fake: FakeStripeGateway) -> list[str]:
    return [c.kwargs["audit_action_id"] for c in fake.calls_to("cancel_subscription")]


class _Exploding:
    async def cancel_subscription(self, *args: object, **kwargs: object) -> object:
        raise KeyError("boom")


# ---------------------------------------------------------------- enqueue


async def test_enqueue_joins_the_callers_transaction_and_rolls_back_with_it(
    db: AsyncSession,
) -> None:
    await enqueue_stripe_cancel(db, customer_id="cus_A", subscription_id="sub_A")
    await db.rollback()
    assert await _rows(db) == []
    assert not await is_tombstoned_customer(db, "cus_A")


async def test_enqueue_does_not_commit(db: AsyncSession, engine: AsyncEngine) -> None:
    await enqueue_stripe_cancel(db, customer_id="cus_A", subscription_id="sub_A")
    async with async_sessionmaker(engine)() as other:
        assert await _rows(other) == []
    await db.rollback()


async def test_enqueue_re_arms_an_existing_row(db: AsyncSession) -> None:
    await _enqueue(db, sub=None)
    [row] = await _rows(db)
    assert row.stripe_subscription_id is None
    row.completed_at, row.attempts = NOW, 5
    await db.commit()

    await _enqueue(db, sub="sub_B")

    [again] = await _rows(db)
    assert again.stripe_subscription_id == "sub_B"
    assert again.completed_at is None and again.attempts == 0


async def test_re_arming_a_pending_row_keeps_attempts_and_backoff(db: AsyncSession) -> None:
    await _enqueue(db, sub="sub_A")
    fake = _fake("sub_A")
    fake.fail_always(
        "cancel_subscription", StripeOperationError("x", code="invalid", retryable=False)
    )
    await run_due_stripe_cancels(db, fake, now=NOW)
    [before] = await _rows(db)
    due_at = before.next_attempt_at
    assert before.attempts == 1 and due_at == NOW + timedelta(seconds=TERMINAL_BACKOFF_SECONDS)

    await _enqueue(db, sub="sub_B")

    [after] = await _rows(db)
    assert after.attempts == 1 and after.next_attempt_at == due_at
    assert after.completed_at is None


async def test_re_arming_a_pending_row_cancels_both_subscriptions(db: AsyncSession) -> None:
    await _enqueue(db, sub="sub_A")
    await _enqueue(db, sub="sub_B")
    fake = _fake("sub_A", "sub_B")

    await run_due_stripe_cancels(db, fake, now=NOW)

    assert fake.subscriptions["sub_A"].status == "canceled"
    assert fake.subscriptions["sub_B"].status == "canceled"
    assert len(set(_audit_ids(fake))) == 2


async def test_re_arm_without_subscription_keeps_the_known_one(db: AsyncSession) -> None:
    await _enqueue(db, sub="sub_A")
    await _enqueue(db, sub=None)
    [row] = await _rows(db)
    assert row.stripe_subscription_id == "sub_A"


@pytest.mark.parametrize(
    ("cus", "sub"),
    [
        ("x_1", "sub_A"),
        ("cus_", "sub_A"),
        ("cus_a b", "sub_A"),
        ("cus_A", "si_1"),
        ("cus_A", "sub_"),
    ],
)
async def test_invalid_ids_are_rejected(db: AsyncSession, cus: str, sub: str) -> None:
    with pytest.raises(ValueError, match="id"):
        await enqueue_stripe_cancel(db, customer_id=cus, subscription_id=sub)


def test_row_holds_only_stripe_ids_and_bookkeeping() -> None:
    columns = {c.name for c in StripeCancelRequest.__table__.columns}
    assert columns == {
        "id",
        "stripe_customer_id",
        "stripe_subscription_id",
        "attempts",
        "next_attempt_at",
        "completed_at",
        "created_at",
    }


# ---------------------------------------------------------------- tombstone


async def test_tombstone_before_and_after_completion(db: AsyncSession) -> None:
    assert not await is_tombstoned_customer(db, "cus_A")
    await _enqueue(db)
    assert await is_tombstoned_customer(db, "cus_A")
    await run_due_stripe_cancels(db, _fake("sub_A"), now=NOW)
    assert await is_tombstoned_customer(db, "cus_A")
    assert not await is_tombstoned_customer(db, "cus_other")


# ---------------------------------------------------------------- the run


async def test_success_cancels_immediately_with_final_invoice_and_no_proration(
    db: AsyncSession,
) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    [call] = fake.calls_to("cancel_subscription")
    assert call.args == ("sub_A",)
    assert call.kwargs["mode"] == "immediate"
    assert call.kwargs["invoice_now"] is True and call.kwargs["prorate"] is False
    assert call.kwargs["actor"] is None
    assert 0 < len(call.kwargs["audit_action_id"]) <= 64
    assert fake.subscriptions["sub_A"].status == "canceled"
    [row] = await _rows(db)
    assert row.completed_at == NOW
    assert (summary.completed, summary.failed) == (1, 0)


async def test_already_canceled_or_missing_counts_as_success(db: AsyncSession) -> None:
    await _enqueue(db, "cus_A", "sub_A")
    await _enqueue(db, "cus_B", "sub_B")
    fake = FakeStripeGateway()
    fake.seed_subscription("sub_A", status="canceled")  # sub_B is unknown to Stripe

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert summary.completed == 2
    assert all(r.completed_at == NOW for r in await _rows(db))


async def test_stripe_down_keeps_the_row_with_backoff_and_a_later_run_succeeds(
    db: AsyncSession,
) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    fake.fail_next("cancel_subscription", FakeStripeGateway.connection_error())

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert (summary.completed, summary.failed) == (0, 1)
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(seconds=BACKOFF_BASE_SECONDS)

    assert (await run_due_stripe_cancels(db, fake, now=NOW)).attempted == 0
    later = NOW + timedelta(seconds=BACKOFF_BASE_SECONDS)
    assert (await run_due_stripe_cancels(db, fake, now=later)).completed == 1
    [done] = await _rows(db)
    assert done.completed_at == later and fake.subscriptions["sub_A"].status == "canceled"


async def test_backoff_is_exponential_and_capped(db: AsyncSession) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    fake.fail_always("cancel_subscription", FakeStripeGateway.connection_error())
    delays: list[int] = []
    clock = NOW
    for _ in range(12):
        await run_due_stripe_cancels(db, fake, now=clock)
        [row] = await _rows(db)
        delays.append(int((row.next_attempt_at - clock).total_seconds()))
        clock = row.next_attempt_at
    assert delays[:3] == [BACKOFF_BASE_SECONDS * 2**i for i in range(3)]
    assert delays[-1] == BACKOFF_MAX_SECONDS == max(delays)


async def test_unconfigured_gateway_is_retried_later(db: AsyncSession) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    fake.fail_next("cancel_subscription", BillingUnconfiguredError("no key"))
    summary = await run_due_stripe_cancels(db, fake, now=NOW)
    assert summary.failed == 1
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 1
    assert (await run_due_stripe_cancels(db, fake, now=row.next_attempt_at)).completed == 1


async def test_non_retryable_error_backs_off_long_and_does_not_raise(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    fake.fail_next(
        "cancel_subscription", StripeOperationError("x", code="invalid", retryable=False)
    )
    summary = await run_due_stripe_cancels(db, fake, now=NOW)
    assert summary.failed == 1
    [row] = await _rows(db)
    assert row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(seconds=TERMINAL_BACKOFF_SECONDS)
    assert any(r.levelname == "ERROR" and "cus_A" in r.getMessage() for r in caplog.records)


async def test_customer_only_row_cancels_every_live_subscription_found_by_listing(
    db: AsyncSession,
) -> None:
    await _enqueue(db, sub=None)
    fake = _fake("sub_X", "sub_Z")
    fake.seed_subscription("sub_Y", customer_id="cus_A", status="canceled")
    fake.seed_subscription("sub_other", customer_id="cus_other")

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert [c.args[0] for c in fake.calls_to("cancel_subscription")] == ["sub_X", "sub_Z"]
    assert fake.subscriptions["sub_other"].status == "active"
    assert len(set(_audit_ids(fake))) == 2
    [row] = await _rows(db)
    assert row.completed_at == NOW and (summary.completed, summary.failed) == (1, 0)


async def test_customer_only_row_with_no_live_subscription_completes_as_a_tombstone(
    db: AsyncSession,
) -> None:
    await _enqueue(db, sub=None)
    fake = _fake()
    summary = await run_due_stripe_cancels(db, fake, now=NOW)
    assert summary.completed == 1 and fake.calls_to("cancel_subscription") == []
    [row] = await _rows(db)
    assert row.completed_at == NOW
    assert await is_tombstoned_customer(db, "cus_A")


async def test_a_hint_owned_by_another_customer_is_never_canceled(db: AsyncSession) -> None:
    await _enqueue(db, sub="sub_hint")
    fake = _fake("sub_live")
    fake.seed_subscription("sub_hint", customer_id="cus_elsewhere")

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert [c.args[0] for c in fake.calls_to("cancel_subscription")] == ["sub_live"]
    assert fake.subscriptions["sub_hint"].status == "active"
    assert (summary.completed, summary.failed) == (1, 0)
    [row] = await _rows(db)
    assert row.completed_at == NOW


async def test_a_hint_owned_by_the_same_customer_but_absent_from_the_listing_is_canceled(
    db: AsyncSession,
) -> None:
    await _enqueue(db, sub="sub_hint")
    fake = _fake("sub_live")
    fake.seed_subscription("sub_hint", customer_id="cus_A")
    fake.hide_from_listing("sub_hint")  # eventual consistency: retrievable, not yet listed

    await run_due_stripe_cancels(db, fake, now=NOW)

    assert {c.args[0] for c in fake.calls_to("cancel_subscription")} == {"sub_live", "sub_hint"}
    assert fake.subscriptions["sub_hint"].status == "canceled"


async def test_a_terminal_hint_absent_from_the_listing_is_skipped(db: AsyncSession) -> None:
    await _enqueue(db, sub="sub_hint")
    fake = _fake()
    fake.seed_subscription("sub_hint", customer_id="cus_A", status="canceled")

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert fake.calls_to("cancel_subscription") == [] and summary.completed == 1


async def test_a_hint_stripe_does_not_know_is_skipped_and_the_row_completes(
    db: AsyncSession,
) -> None:
    await _enqueue(db, sub="sub_hint")
    fake = _fake()  # sub_hint unknown: retrieve raises resource_missing

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert [c.args[0] for c in fake.calls_to("retrieve_subscription")] == ["sub_hint"]
    assert fake.calls_to("cancel_subscription") == []
    assert (summary.completed, summary.failed) == (1, 0)
    [row] = await _rows(db)
    assert row.completed_at == NOW


async def test_a_hint_retrieve_failure_is_retried_and_cancels_nothing_unverified(
    db: AsyncSession,
) -> None:
    await _enqueue(db, sub="sub_hint")
    fake = _fake()
    fake.seed_subscription("sub_hint", customer_id="cus_A")
    fake.hide_from_listing("sub_hint")
    fake.fail_next("retrieve_subscription", FakeStripeGateway.connection_error())

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert summary.failed == 1 and fake.calls_to("cancel_subscription") == []
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 1


async def test_a_listed_hint_is_not_retrieved(db: AsyncSession) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    await run_due_stripe_cancels(db, fake, now=NOW)
    assert fake.calls_to("retrieve_subscription") == []


async def test_list_failure_is_retried_with_backoff(db: AsyncSession) -> None:
    await _enqueue(db, sub=None)
    fake = _fake("sub_X")
    fake.fail_next("list_customer_subscriptions", FakeStripeGateway.connection_error())

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert (summary.completed, summary.failed) == (0, 1)
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(seconds=BACKOFF_BASE_SECONDS)
    assert fake.calls_to("cancel_subscription") == []
    later = row.next_attempt_at
    assert (await run_due_stripe_cancels(db, fake, now=later)).completed == 1
    assert fake.subscriptions["sub_X"].status == "canceled"


async def test_one_failing_subscription_does_not_stop_the_others(db: AsyncSession) -> None:
    await _enqueue(db, sub=None)
    fake = _fake("sub_X", "sub_Z")
    fake.fail_next("cancel_subscription", FakeStripeGateway.connection_error())

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert summary.failed == 1
    assert fake.subscriptions["sub_X"].status == "active"
    assert fake.subscriptions["sub_Z"].status == "canceled"
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 1
    await run_due_stripe_cancels(db, fake, now=row.next_attempt_at)
    assert fake.subscriptions["sub_X"].status == "canceled"


async def test_unexpected_exception_never_raises(db: AsyncSession) -> None:
    await _enqueue(db)
    summary = await run_due_stripe_cancels(db, _Exploding(), now=NOW)  # type: ignore[arg-type]
    assert summary.failed == 1
    [row] = await _rows(db)
    assert row.attempts == 1 and row.completed_at is None


async def test_limit_and_ordering_oldest_due_first(db: AsyncSession) -> None:
    for i, offset in enumerate([30, 10, 20]):
        await enqueue_stripe_cancel(db, customer_id=f"cus_{i}", subscription_id=f"sub_{i}", now=NOW)
        row = await db.scalar(
            select(StripeCancelRequest).where(StripeCancelRequest.stripe_customer_id == f"cus_{i}")
        )
        assert row is not None
        row.next_attempt_at = NOW - timedelta(seconds=offset)
    await db.commit()
    fake = FakeStripeGateway()
    for i in range(3):
        fake.seed_subscription(f"sub_{i}", customer_id=f"cus_{i}")

    summary = await run_due_stripe_cancels(db, fake, now=NOW, limit=2)

    assert summary.attempted == 2
    assert [c.args[0] for c in fake.calls_to("cancel_subscription")] == ["sub_0", "sub_2"]


async def test_completed_rows_are_not_run_again(db: AsyncSession) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    await run_due_stripe_cancels(db, fake, now=NOW)
    again = await run_due_stripe_cancels(db, fake, now=NOW + timedelta(days=1))
    assert again.attempted == 0 and len(fake.calls_to("cancel_subscription")) == 1


async def test_re_armed_row_cancels_a_later_subscription(db: AsyncSession) -> None:
    await _enqueue(db)
    fake = _fake("sub_A", "sub_B")
    await run_due_stripe_cancels(db, fake, now=NOW)
    await _enqueue(db, sub="sub_B")
    await run_due_stripe_cancels(db, fake, now=NOW)
    assert fake.subscriptions["sub_B"].status == "canceled"
    keys = {c.kwargs["audit_action_id"] for c in fake.calls_to("cancel_subscription")}
    assert len(keys) == 2


async def test_concurrent_runs_do_not_double_cancel(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        await _enqueue(setup)
    fake = _fake("sub_A")

    async def run() -> None:
        async with maker() as s:
            await run_due_stripe_cancels(s, fake, now=NOW)

    await asyncio.gather(run(), run())

    assert len(fake.calls_to("cancel_subscription")) == 1
    assert fake.subscriptions["sub_A"].status == "canceled"


# ---------------------------------------------------------------- after commit / startup


async def test_after_commit_runs_inline(db: AsyncSession) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    await run_stripe_cancels_after_commit(db, fake)
    assert fake.subscriptions["sub_A"].status == "canceled"


async def test_after_commit_swallows_everything(db: AsyncSession) -> None:
    await _enqueue(db)
    await run_stripe_cancels_after_commit(db, _Exploding())  # type: ignore[arg-type]
    await run_stripe_cancels_after_commit(db, None)


async def test_after_commit_swallows_a_broken_session() -> None:
    class _Broken:
        async def scalars(self, *a: object, **k: object) -> None:
            raise RuntimeError("db down")

        async def rollback(self) -> None:
            raise RuntimeError("still down")

    await run_stripe_cancels_after_commit(_Broken(), _fake())  # type: ignore[arg-type]


async def test_after_commit_times_out_without_raising_and_the_row_stays_due(
    db: AsyncSession,
) -> None:
    class _Slow:
        async def list_customer_subscriptions(self, customer_id: str) -> list[str]:
            return ["sub_A"]

        async def cancel_subscription(self, *a: object, **k: object) -> object:
            await asyncio.sleep(5)
            raise AssertionError("the inline timeout should have cancelled this")

    started = datetime.now(UTC)
    await enqueue_stripe_cancel(db, customer_id="cus_A", subscription_id="sub_A", now=started)
    await db.commit()
    await run_stripe_cancels_after_commit(db, _Slow(), timeout_seconds=0.05)  # type: ignore[arg-type]

    [row] = await _rows(db)
    assert row.completed_at is None
    # The claim's lease survived the cancelled run: not re-run early, due once it elapses.
    assert row.next_attempt_at >= started + timedelta(seconds=LEASE_SECONDS - 5)
    fake = _fake("sub_A")
    assert (await run_due_stripe_cancels(db, fake, now=started)).attempted == 0
    later = started + timedelta(seconds=LEASE_SECONDS + 60)
    assert (await run_due_stripe_cancels(db, fake, now=later)).completed == 1


async def test_after_commit_only_runs_the_given_customers(db: AsyncSession) -> None:
    await _enqueue(db, "cus_A", "sub_A")
    await _enqueue(db, "cus_B", "sub_B")
    fake = _fake("sub_A")
    fake.seed_subscription("sub_B", customer_id="cus_B")
    await db.execute(
        update(StripeCancelRequest).values(next_attempt_at=datetime(2020, 1, 1, tzinfo=UTC))
    )
    await db.commit()

    await run_stripe_cancels_after_commit(db, fake, customer_ids=["cus_B"])

    assert fake.subscriptions["sub_B"].status == "canceled"
    assert fake.subscriptions["sub_A"].status == "active"
    await run_stripe_cancels_after_commit(db, fake, customer_ids=[])
    assert fake.subscriptions["sub_A"].status == "active"


async def test_run_filters_by_customer_ids(db: AsyncSession) -> None:
    await _enqueue(db, "cus_A", "sub_A")
    await _enqueue(db, "cus_B", "sub_B")
    fake = _fake("sub_A")
    fake.seed_subscription("sub_B", customer_id="cus_B")
    summary = await run_due_stripe_cancels(db, fake, now=NOW, customer_ids={"cus_A"})
    assert summary.completed == 1 and fake.subscriptions["sub_B"].status == "active"


# ---------------------------------------------------------------- locks, lease, timeouts


async def test_no_row_lock_is_held_while_stripe_is_called(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        await _enqueue(setup)
    observed: dict[str, object] = {}

    class _Probe(FakeStripeGateway):
        async def cancel_subscription(self, *a: Any, **k: Any) -> Any:
            async with maker() as other:
                # NOWAIT raises if the runner still holds the row lock.
                locked = await other.scalar(
                    select(StripeCancelRequest).with_for_update(nowait=True)
                )
                assert locked is not None
                observed["lease"] = locked.next_attempt_at
                observed["completed"] = locked.completed_at
            return await super().cancel_subscription(*a, **k)

    probe = _Probe()
    probe.seed_subscription("sub_A", customer_id="cus_A")
    async with maker() as s:
        await run_due_stripe_cancels(s, probe, now=NOW)

    assert observed["lease"] == NOW + timedelta(seconds=LEASE_SECONDS)
    assert observed["completed"] is None
    async with maker() as check:
        [row] = await _rows(check)
    assert row.completed_at == NOW


async def test_a_re_arm_during_the_run_keeps_the_row_open(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        await _enqueue(setup, sub="sub_A")

    class _ReArm(FakeStripeGateway):
        async def cancel_subscription(self, *a: Any, **k: Any) -> Any:
            if not self.calls_to("cancel_subscription"):
                async with maker() as other:
                    await _enqueue(other, sub="sub_B")
            return await super().cancel_subscription(*a, **k)

    fake = _ReArm()
    fake.seed_subscription("sub_A", customer_id="cus_A")
    async with maker() as s:
        await run_due_stripe_cancels(s, fake, now=NOW)
    async with maker() as check:
        [row] = await _rows(check)
    assert row.completed_at is None and row.next_attempt_at <= NOW

    fake.seed_subscription("sub_B", customer_id="cus_A")
    async with maker() as s:
        await run_due_stripe_cancels(s, fake, now=NOW)
    assert fake.subscriptions["sub_B"].status == "canceled"


async def test_a_hung_row_times_out_and_backs_off(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Hang(FakeStripeGateway):
        async def cancel_subscription(self, *a: Any, **k: Any) -> Any:
            await asyncio.sleep(5)

    monkeypatch.setattr(stripe_cancel, "ROW_TIMEOUT_SECONDS", 0.05)
    await _enqueue(db)
    hang = _Hang()
    hang.seed_subscription("sub_A", customer_id="cus_A")

    summary = await run_due_stripe_cancels(db, hang, now=NOW)

    assert summary.failed == 1
    [row] = await _rows(db)
    assert row.attempts == 1 and row.next_attempt_at == NOW + timedelta(
        seconds=BACKOFF_BASE_SECONDS
    )


async def test_failures_log_only_the_type_not_the_message_or_a_traceback(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    class _Leaky:
        async def list_customer_subscriptions(self, customer_id: str) -> list[str]:
            raise KeyError("sk_live_SECRET_VALUE")

    await _enqueue(db)
    caplog.set_level("DEBUG")
    await run_due_stripe_cancels(db, _Leaky(), now=NOW)  # type: ignore[arg-type]
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "KeyError" in text and "SECRET" not in text
    assert all(r.exc_info is None for r in caplog.records)


async def test_stripe_errors_log_code_and_status(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    fake.fail_next(
        "cancel_subscription",
        StripeOperationError("x", code="rate_limit", http_status=429, retryable=True),
    )
    await run_due_stripe_cancels(db, fake, now=NOW)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "rate_limit" in text and "429" in text


async def test_startup_drains_due_rows_and_never_raises(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        await _enqueue(setup)
    fake = _fake("sub_A")
    await run_startup_stripe_cancels(maker, fake)
    assert fake.subscriptions["sub_A"].status == "canceled"

    await run_startup_stripe_cancels(maker, None)

    def broken() -> AsyncSession:
        raise RuntimeError("no db")

    await run_startup_stripe_cancels(broken, fake)


# ---------------------------------------------------------------- lease vs batch, completed rows


def test_the_lease_outlives_a_whole_batch_of_row_timeouts() -> None:
    assert stripe_cancel.LEASE_SECONDS > stripe_cancel.BATCH * stripe_cancel.ROW_TIMEOUT_SECONDS


async def test_a_row_still_inside_a_batch_lease_is_not_reclaimed(db: AsyncSession) -> None:
    await _enqueue(db)
    fake = _fake("sub_A")
    # Claim only (lease), simulate a slow earlier row: nothing else may take it meanwhile.
    claimed = await stripe_cancel._claim_due(db, NOW, 5, None)
    assert len(claimed) == 1
    inside = NOW + timedelta(seconds=stripe_cancel.BATCH * 50)
    assert (await run_due_stripe_cancels(db, fake, now=inside)).attempted == 0


async def test_a_late_failure_on_an_already_completed_row_is_ignored(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        await _enqueue(setup)
    after_lease = NOW + timedelta(seconds=LEASE_SECONDS + 1)

    class _Racing(FakeStripeGateway):
        """Runner 1 stalls in its listing; its lease expires; runner 2 finishes the row."""

        done = False

        async def list_customer_subscriptions(self, customer_id: str) -> list[str]:
            if not self.done:
                self.done = True
                async with maker() as other:
                    await run_due_stripe_cancels(other, self, now=after_lease)
                raise StripeOperationError("x", code="invalid", retryable=False)
            return await super().list_customer_subscriptions(customer_id)

    racing = _Racing()
    racing.seed_subscription("sub_A", customer_id="cus_A")
    caplog.set_level("DEBUG")
    async with maker() as s:
        summary = await run_due_stripe_cancels(s, racing, now=NOW)

    assert len(racing.calls_to("cancel_subscription")) == 1
    assert racing.subscriptions["sub_A"].status == "canceled"
    async with maker() as check:
        [row] = await _rows(check)
    assert row.completed_at == after_lease and row.attempts == 0
    assert not any("NON-RETRYABLE" in r.getMessage() for r in caplog.records)
    assert not any("Stripe cancel failed" in r.getMessage() for r in caplog.records)
    assert summary.attempted == 1


# ---------------------------------------------------------------- truncated listing


async def test_a_truncated_listing_cancels_what_it_collected_then_retries(
    db: AsyncSession,
) -> None:
    await _enqueue(db, sub=None)
    fake = _fake("sub_X", "sub_Z", "sub_W")
    fake.truncate_listing_after(2)

    summary = await run_due_stripe_cancels(db, fake, now=NOW)

    assert [c.args[0] for c in fake.calls_to("cancel_subscription")] == ["sub_X", "sub_Z"]
    assert (summary.completed, summary.failed) == (0, 1)
    [row] = await _rows(db)
    assert row.completed_at is None and row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(seconds=BACKOFF_BASE_SECONDS)


# ---------------------------------------------------------------- clock


async def test_each_rows_backoff_counts_from_when_it_failed_not_from_the_run_start(
    db: AsyncSession,
) -> None:
    await _enqueue(db, "cus_A", "sub_A")
    await _enqueue(db, "cus_B", "sub_B")
    fake = _fake("sub_A")
    fake.seed_subscription("sub_B", customer_id="cus_B")
    fake.fail_always("cancel_subscription", FakeStripeGateway.connection_error())
    ticks = iter(NOW + timedelta(seconds=100 * i) for i in range(100))

    await run_due_stripe_cancels(db, fake, clock=lambda: next(ticks))

    rows = sorted(await _rows(db), key=lambda r: r.next_attempt_at)
    first, second = rows
    assert second.next_attempt_at - first.next_attempt_at >= timedelta(seconds=100)
    assert min(r.next_attempt_at for r in rows) >= NOW + timedelta(seconds=BACKOFF_BASE_SECONDS)


# ---------------------------------------------------------------- DB-error logging


async def test_inline_and_startup_db_errors_log_only_the_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Broken:
        async def scalars(self, *a: object, **k: object) -> None:
            raise RuntimeError("password=hunter2 bound-parameter")

        async def rollback(self) -> None:
            raise RuntimeError("password=hunter2 rollback")

    def broken() -> Any:
        raise RuntimeError("password=hunter2 connect")

    caplog.set_level("DEBUG")
    await run_stripe_cancels_after_commit(_Broken(), _fake())  # type: ignore[arg-type]
    await run_startup_stripe_cancels(broken, _fake())
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in text and "hunter2" not in text
    assert all(r.exc_info is None for r in caplog.records)
