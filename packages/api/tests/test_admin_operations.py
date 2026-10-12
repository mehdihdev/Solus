"""Staff billing operations, LOCAL (non-Stripe) subscriptions + validation + events
(SOLUSDEV-313 T6). The Stripe-backed paths live in test_admin_operations_stripe.py."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fixtures.stripe_fake import FakeStripeGateway
from solus_api.billing import admin_operations
from solus_api.billing.admin_operations import (
    AdminBillingOperations,
    AdminOperationError,
    InvalidOperation,
    NotCompedError,
    TargetNotFound,
    UnsupportedForNonStripe,
)
from solus_api.billing.admin_validation import MAX_LIMIT_OVERRIDE
from solus_api.billing.entitlements import effective_limits, effective_plan
from solus_api.billing.plan_grants import grant_plan_credits
from solus_api.core.config import Settings
from solus_api.models import (
    CreditBalance,
    CreditLedger,
    DataEvent,
    Notification,
    NotificationType,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
ACTOR = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
REASON = "customer escalation, ticket 4411 for jane@example.com"
Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
def maker(engine: Any) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _user(
    maker: Maker,
    *,
    plan: PlanType = PlanType.BASIC,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    consent: bool = False,
    with_sub: bool = True,
    **sub_fields: Any,
) -> uuid.UUID:
    uid = uuid.uuid4()
    async with maker() as s:
        s.add(
            User(
                id=uid,
                supabase_user_id=f"x-{uid}",
                email=f"{uid}@example.com",
                data_collection_consent=consent,
            )
        )
        await s.flush()
        if with_sub:
            fields = {"limits": default_limits(plan), **sub_fields}
            s.add(Subscription(user_id=uid, plan=plan, status=status, **fields))
        await s.commit()
    return uid


async def _sub(maker: Maker, uid: uuid.UUID) -> Subscription:
    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert sub is not None
    return sub


async def _count(maker: Maker, model: Any, **where: Any) -> int:
    async with maker() as s:
        stmt = select(func.count()).select_from(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return int(await s.scalar(stmt) or 0)


def _ops(
    s: AsyncSession, settings: Settings, gateway: FakeStripeGateway | None = None
) -> AdminBillingOperations:
    return AdminBillingOperations(s, gateway or FakeStripeGateway(), settings, now=lambda: NOW)


def _audit(n: int = 1) -> dict[str, Any]:
    return {"actor_staff_user_id": ACTOR, "audit_action_id": f"audit-{n}", "reason": REASON}


# ---------------------------------------------------------------- change_plan
async def test_local_change_plan_sets_plan_limits_and_clears_comp(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=None)
    async with maker() as s:
        res = await _ops(s, settings).change_plan(uid, plan=PlanType.PRO, **_audit())
    row = await _sub(maker, uid)
    assert (row.plan, row.limits) == (PlanType.PRO, default_limits(PlanType.PRO))
    assert row.status is SubscriptionStatus.ACTIVE
    assert row.comp_plan is None and row.comp_expires_at is None
    assert res.operation == "change_plan" and not res.noop and not res.converges_via_webhook
    assert res.before.plan == "basic" and res.after.plan == "pro"
    assert res.after.effective_plan == "pro"
    assert await _count(maker, CreditLedger) == 0  # no credit grant on a plan set


async def test_local_change_plan_noop_when_already_there(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker, consent=True)
    async with maker() as s:
        res = await _ops(s, settings).change_plan(uid, plan=PlanType.BASIC, **_audit())
    assert res.noop
    assert await _count(maker, DataEvent) == 0


# ------------------------------------------------------------------ validation
@pytest.mark.parametrize(
    "kwargs",
    [
        {"proration": "sometimes"},
        {"interval": "week"},
    ],
)
async def test_change_plan_rejects_bad_enum_args(
    maker: Maker, settings: Settings, kwargs: dict[str, Any]
) -> None:
    uid = await _user(maker)
    async with maker() as s:
        with pytest.raises(InvalidOperation):
            await _ops(s, settings).change_plan(uid, plan=PlanType.PRO, **kwargs, **_audit())
    assert (await _sub(maker, uid)).plan is PlanType.BASIC


@pytest.mark.parametrize(
    "override",
    [
        {"reason": ""},
        {"reason": "   "},
        {"reason": "x" * 2001},
        {"audit_action_id": ""},
        {"audit_action_id": "has space"},
        {"audit_action_id": "a@b.com"},
        {"audit_action_id": "x" * 65},
        {"actor_staff_user_id": "not-a-uuid"},
    ],
)
async def test_audit_arguments_are_validated(
    maker: Maker, settings: Settings, override: dict[str, Any]
) -> None:
    uid = await _user(maker)
    async with maker() as s:
        with pytest.raises(InvalidOperation):
            await _ops(s, settings).change_plan(uid, plan=PlanType.PRO, **{**_audit(), **override})


async def test_plan_must_be_a_plan_type(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    async with maker() as s:
        with pytest.raises(InvalidOperation):
            await _ops(s, settings).change_plan(uid, plan="pro", **_audit())  # type: ignore[arg-type]


async def test_unknown_target_and_missing_subscription(maker: Maker, settings: Settings) -> None:
    no_sub = await _user(maker, with_sub=False)
    async with maker() as s:
        for target in (uuid.uuid4(), no_sub):
            with pytest.raises(TargetNotFound) as exc:
                await _ops(s, settings).change_plan(target, plan=PlanType.PRO, **_audit())
            assert exc.value.code == "target_not_found"
            assert exc.value.context["target_user_id"] == str(target)


def test_errors_carry_stable_codes_and_context() -> None:
    err = NotCompedError("nope", target_user_id="u1")
    assert isinstance(err, AdminOperationError)
    assert (err.code, err.message, err.context) == ("not_comped", "nope", {"target_user_id": "u1"})
    assert UnsupportedForNonStripe("m").code == "unsupported_for_non_stripe"
    assert InvalidOperation("m").code == "invalid_operation"
    assert str(err) == "nope"


# ----------------------------------------------------------------- comp_upgrade
async def test_local_comp_once_expires_in_one_calendar_month_and_grants_credits(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(maker)
    async with maker() as s:
        res = await _ops(s, settings).comp_upgrade(
            uid, plan=PlanType.PRO, duration="once", **_audit()
        )
    row = await _sub(maker, uid)
    assert row.plan is PlanType.BASIC  # the purchased plan is untouched
    assert row.comp_plan is PlanType.PRO
    assert row.comp_expires_at == datetime(2026, 2, 28, 12, 0, tzinfo=UTC)  # Jan 31 + 1 month
    assert res.after.comp_plan == "pro" and res.after.effective_plan == "pro"
    assert res.after.effective_limits == default_limits(PlanType.PRO)
    assert res.before.effective_plan == "basic"
    async with maker() as s:
        bal = await s.scalar(select(CreditBalance).where(CreditBalance.user_id == uid))
    assert bal is not None and bal.balance == settings.plan_credit_grants["pro"]


@pytest.mark.parametrize(
    ("months", "expected"),
    [
        (1, datetime(2026, 2, 28, 12, tzinfo=UTC)),
        (3, datetime(2026, 4, 30, 12, tzinfo=UTC)),
        (13, datetime(2027, 2, 28, 12, tzinfo=UTC)),
        (36, datetime(2029, 1, 31, 12, tzinfo=UTC)),
    ],
)
async def test_local_comp_repeating_month_arithmetic(
    maker: Maker, settings: Settings, months: int, expected: datetime
) -> None:
    uid = await _user(maker)
    async with maker() as s:
        await _ops(s, settings).comp_upgrade(
            uid, plan=PlanType.PRO, duration="repeating", months=months, **_audit()
        )
    assert (await _sub(maker, uid)).comp_expires_at == expected


async def test_local_comp_forever_has_no_expiry(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    async with maker() as s:
        await _ops(s, settings).comp_upgrade(uid, plan=PlanType.PRO, duration="forever", **_audit())
    row = await _sub(maker, uid)
    assert row.comp_plan is PlanType.PRO and row.comp_expires_at is None
    assert effective_plan(row, NOW) is PlanType.PRO


@pytest.mark.parametrize(
    ("duration", "months"),
    [
        ("repeating", None),
        ("repeating", 0),
        ("repeating", 37),
        ("repeating", True),
        ("repeating", "3"),
        ("once", 1),
        ("forever", 6),
        ("weekly", None),
    ],
)
async def test_comp_validation_matrix(
    maker: Maker, settings: Settings, duration: Any, months: Any
) -> None:
    uid = await _user(maker)
    async with maker() as s:
        with pytest.raises(InvalidOperation):
            await _ops(s, settings).comp_upgrade(
                uid, plan=PlanType.PRO, duration=duration, months=months, **_audit()
            )
    assert (await _sub(maker, uid)).comp_plan is None


async def test_comp_credit_grant_happens_after_the_comp_is_committed(
    maker: Maker, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """grant_plan_credits commits mid-flow, so our local write must already be durable."""
    uid = await _user(maker)
    seen: list[PlanType | None] = []
    real = grant_plan_credits

    async def spy(session: AsyncSession, local: Subscription, grants: dict[str, int]) -> None:
        seen.append((await _sub(maker, uid)).comp_plan)  # a fresh session sees it
        assert local.plan is PlanType.PRO  # the comp plan's starting credits
        await real(session, local, grants)

    monkeypatch.setattr(admin_operations, "grant_plan_credits", spy)  # noqa
    async with maker() as s:
        await _ops(s, settings).comp_upgrade(uid, plan=PlanType.PRO, duration="forever", **_audit())
    assert seen == [PlanType.PRO]


async def test_comp_replay_never_double_grants_and_is_a_noop(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(maker, consent=True)
    results = []
    for _ in range(2):
        async with maker() as s:
            results.append(
                await _ops(s, settings).comp_upgrade(
                    uid, plan=PlanType.PRO, duration="forever", **_audit()
                )
            )
    assert [r.noop for r in results] == [False, True]
    assert await _count(maker, CreditLedger, user_id=uid) == 1
    assert await _count(maker, DataEvent) == 1  # no duplicate event on the replay


async def test_comp_recovers_a_grant_lost_after_the_commit(
    maker: Maker, settings: Settings
) -> None:
    """Comp committed but the grant never ran: the retry is a noop yet still grants."""
    uid = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=None)
    async with maker() as s:
        res = await _ops(s, settings).comp_upgrade(
            uid, plan=PlanType.PRO, duration="forever", **_audit()
        )
    assert res.noop
    assert await _count(maker, CreditLedger, user_id=uid) == 1


async def test_comp_enterprise_has_no_starting_grant(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    async with maker() as s:
        res = await _ops(s, settings).comp_upgrade(
            uid, plan=PlanType.ENTERPRISE, duration="forever", **_audit()
        )
    assert res.after.comp_plan == "enterprise"
    assert await _count(maker, CreditLedger) == 0


async def test_comp_on_inactive_subscription_does_not_grant(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(maker, status=SubscriptionStatus.PAST_DUE)
    async with maker() as s:
        await _ops(s, settings).comp_upgrade(uid, plan=PlanType.PRO, duration="forever", **_audit())
    assert await _count(maker, CreditLedger) == 0


# ------------------------------------------------------------------ remove_comp
async def test_local_remove_comp_clears_fields_and_not_comped_errors(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=None)
    async with maker() as s:
        res = await _ops(s, settings).remove_comp(uid, **_audit())
    row = await _sub(maker, uid)
    assert row.comp_plan is None and row.comp_expires_at is None
    assert res.before.comp_plan == "pro" and res.after.comp_plan is None
    assert res.after.effective_plan == "basic"
    async with maker() as s:
        with pytest.raises(NotCompedError):
            await _ops(s, settings).remove_comp(uid, **_audit(2))


# --------------------------------------------------------------- limits override
async def test_set_and_clear_limits_override(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    before = (await _sub(maker, uid)).limits
    async with maker() as s:
        res = await _ops(s, settings).set_limits_override(
            uid, limits={"max_projects": 50, "max_teams": None}, **_audit()
        )
    row = await _sub(maker, uid)
    assert row.limits_override == {"max_projects": 50, "max_teams": None}
    assert row.limits == before  # plan data is never touched
    assert effective_limits(row, NOW)["max_projects"] == 50
    assert effective_limits(row, NOW)["max_teams"] is None
    assert res.after.limits_override == {"max_projects": 50, "max_teams": None}
    assert res.before.limits_override is None
    async with maker() as s:
        again = await _ops(s, settings).set_limits_override(
            uid, limits={"max_projects": 50, "max_teams": None}, **_audit(2)
        )
    assert again.noop
    async with maker() as s:
        cleared = await _ops(s, settings).set_limits_override(uid, limits=None, **_audit(3))
    assert not cleared.noop
    assert (await _sub(maker, uid)).limits_override is None
    async with maker() as s:
        assert (await _ops(s, settings).set_limits_override(uid, limits=None, **_audit(4))).noop


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"unknown_key": 1},
        {"max_projects": -1},
        {"max_projects": True},
        {"max_projects": "5"},
        {"max_projects": 1.5},
        {"max_projects": MAX_LIMIT_OVERRIDE + 1},
        {1: 2},
    ],
)
async def test_limits_override_validation_matrix(
    maker: Maker, settings: Settings, bad: Any
) -> None:
    uid = await _user(maker)
    async with maker() as s:
        with pytest.raises(InvalidOperation):
            await _ops(s, settings).set_limits_override(uid, limits=bad, **_audit())
    assert (await _sub(maker, uid)).limits_override is None


async def test_limits_override_accepts_every_enforced_key(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    keys = {"max_integrations", "max_projects", "max_teams", "byo_paid_tools"}
    async with maker() as s:
        await _ops(s, settings).set_limits_override(uid, limits={k: 0 for k in keys}, **_audit())
    assert set((await _sub(maker, uid)).limits_override or {}) == keys


# ----------------------------------------------------------------------- cancel
async def test_local_immediate_cancel_clamps_clears_comp_keeps_override_and_notifies(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(
        maker,
        plan=PlanType.PRO,
        comp_plan=PlanType.ENTERPRISE,
        limits_override={"max_projects": 9},
        cancel_at=NOW,
    )
    async with maker() as s:
        res = await _ops(s, settings).cancel_subscription(uid, immediate=True, **_audit())
    row = await _sub(maker, uid)
    assert row.status is SubscriptionStatus.CANCELED and row.cancel_at is None
    assert row.limits == default_limits(PlanType.BASIC)
    assert row.comp_plan is None and row.limits_override == {"max_projects": 9}
    assert res.after.status == "canceled" and not res.converges_via_webhook
    async with maker() as s:
        notes = (await s.scalars(select(Notification).where(Notification.user_id == uid))).all()
    assert [n.type for n in notes] == [NotificationType.SUBSCRIPTION_ENDED]
    async with maker() as s:
        second = await _ops(s, settings).cancel_subscription(uid, immediate=True, **_audit(2))
    assert second.noop
    assert await _count(maker, Notification, user_id=uid) == 1


async def test_local_period_end_cancel_is_unsupported(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    async with maker() as s:
        with pytest.raises(UnsupportedForNonStripe) as exc:
            await _ops(s, settings).cancel_subscription(uid, immediate=False, **_audit())
    assert exc.value.code == "unsupported_for_non_stripe"
    assert (await _sub(maker, uid)).status is SubscriptionStatus.ACTIVE


async def test_cancel_args_must_be_bool(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    async with maker() as s:
        with pytest.raises(InvalidOperation):
            await _ops(s, settings).cancel_subscription(
                uid,
                immediate="yes",  # type: ignore[arg-type]
                **_audit(),
            )


# --------------------------------------------------- isolation, events, results
async def test_acting_on_user_a_never_mutates_user_b(maker: Maker, settings: Settings) -> None:
    a, b = await _user(maker), await _user(maker)
    before_b = await _sub(maker, b)
    async with maker() as s:
        ops = _ops(s, settings)
        await ops.change_plan(a, plan=PlanType.PRO, **_audit())
        await ops.comp_upgrade(a, plan=PlanType.ENTERPRISE, duration="forever", **_audit(2))
        await ops.set_limits_override(a, limits={"max_teams": 7}, **_audit(3))
        await ops.cancel_subscription(a, immediate=True, **_audit(4))
    after_b = await _sub(maker, b)
    for col in ("plan", "status", "limits", "limits_override", "comp_plan", "comp_expires_at"):
        assert getattr(after_b, col) == getattr(before_b, col)
    assert await _count(maker, Notification, user_id=b) == 0
    assert await _count(maker, CreditLedger, user_id=b) == 0


async def test_event_is_emitted_for_consenting_target_without_reason_or_email(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(maker, consent=True)
    async with maker() as s:
        await _ops(s, settings).change_plan(uid, plan=PlanType.PRO, **_audit())
    async with maker() as s:
        events = (await s.scalars(select(DataEvent))).all()
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "subscription.admin_changed" and ev.user_id == uid
    assert ev.payload == {
        "operation": "change_plan",
        "audit_action_id": "audit-1",
        "actor_staff_user_id": str(ACTOR),
        "target_user_id": str(uid),
    }
    blob = json.dumps(ev.payload)
    assert "ticket" not in blob and "@" not in blob


async def test_no_event_without_target_consent(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker, consent=False)
    async with maker() as s:
        await _ops(s, settings).change_plan(uid, plan=PlanType.PRO, **_audit())
    assert await _count(maker, DataEvent) == 0


async def test_result_is_json_serialisable_and_frozen(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=NOW.replace(year=2027))
    async with maker() as s:
        res = await _ops(s, settings).set_limits_override(
            uid, limits={"max_teams": None}, **_audit()
        )
    data = json.loads(json.dumps(res.to_dict()))
    assert data["operation"] == "set_limits_override"
    assert data["target_user_id"] == str(uid)
    assert data["before"]["comp_expires_at"].startswith("2027-01-31")
    assert data["after"]["limits_override"] == {"max_teams": None}
    assert set(data) >= {"audit_action_id", "stripe_refs", "converges_via_webhook", "noop"}
    with pytest.raises(AttributeError):
        res.noop = True  # type: ignore[misc]


async def test_local_ops_never_call_stripe(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    gateway = FakeStripeGateway()
    async with maker() as s:
        ops = _ops(s, settings, gateway)
        await ops.change_plan(uid, plan=PlanType.PRO, **_audit())
        await ops.set_limits_override(uid, limits={"max_teams": 1}, **_audit(2))
    assert gateway.calls == []


async def test_stripe_backed_row_that_is_canceled_is_handled_locally(
    maker: Maker, settings: Settings
) -> None:
    uid = await _user(maker, status=SubscriptionStatus.CANCELED, stripe_subscription_id="sub_old1")
    gateway = FakeStripeGateway()
    async with maker() as s:
        res = await _ops(s, settings, gateway).change_plan(uid, plan=PlanType.PRO, **_audit())
    assert not res.converges_via_webhook and gateway.calls == []
    assert (await _sub(maker, uid)).plan is PlanType.PRO


async def test_limits_override_accepts_the_cap_and_zero(maker: Maker, settings: Settings) -> None:
    uid = await _user(maker)
    limits = {"max_projects": MAX_LIMIT_OVERRIDE, "max_teams": 0}
    async with maker() as s:
        await _ops(s, settings).set_limits_override(uid, limits=limits, **_audit())
    assert (await _sub(maker, uid)).limits_override == limits


async def test_credit_grant_failure_after_commit_is_logged_and_result_still_returned(
    maker: Maker,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = await _user(maker)

    async def boom(*_: Any) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(admin_operations, "grant_plan_credits", boom)
    with caplog.at_level("ERROR", logger="solus.billing.admin_operations"):
        async with maker() as s:
            res = await _ops(s, settings).comp_upgrade(
                uid, plan=PlanType.PRO, duration="forever", **_audit()
            )
    assert not res.noop and res.after.comp_plan == "pro"
    assert (await _sub(maker, uid)).comp_plan is PlanType.PRO  # durable
    record = next(r for r in caplog.records if "credit grant failed" in r.getMessage())
    assert str(uid) in record.getMessage() and "audit-1" in record.getMessage()
    # Type name only: a DB traceback would carry bound parameters (user ids, amounts).
    assert "RuntimeError" in record.getMessage()
    assert "ledger down" not in caplog.text
    assert record.exc_info is None


async def test_a_retry_after_a_failed_grant_recovers_it(
    maker: Maker, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = await _user(maker)
    real = grant_plan_credits
    calls = {"n": 0}

    async def flaky(session: AsyncSession, local: Subscription, grants: dict[str, int]) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ledger down")
        await real(session, local, grants)

    monkeypatch.setattr(admin_operations, "grant_plan_credits", flaky)
    for _ in range(2):
        async with maker() as s:
            await _ops(s, settings).comp_upgrade(
                uid, plan=PlanType.PRO, duration="forever", **_audit()
            )
    assert await _count(maker, CreditLedger, user_id=uid) == 1
