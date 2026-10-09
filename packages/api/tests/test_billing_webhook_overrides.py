"""SOLUSDEV-313 T5: webhook x staff overrides/comps, admin wording, tombstone race.

The Stripe signature (verified in the router) is the only trust anchor; these tests
drive `process_event` with plain event dicts like test_billing_webhook.py does."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import bearer
from httpx import AsyncClient
from solus_api.billing.entitlements import effective_limits
from solus_api.billing.stripe_events import process_event
from solus_api.billing.stripe_gateway import ADMIN_ACTION_METADATA_KEY
from solus_api.models import (
    Notification,
    PlanType,
    ProcessedStripeEvent,
    StripeCancelRequest,
    Subscription,
    SubscriptionStatus,
    default_limits,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PRICES = {"basic:month": "price_basic", "pro:month": "price_pro"}
OVERRIDE = {"max_projects": 99, "max_teams": None}
CUS = "cus_T5"
SUB = "sub_T5"


async def _provision(client: AsyncClient, email: str = "t5@example.com") -> uuid.UUID:
    resp = await client.get("/api/v1/users/me", headers=bearer(f"sub-{email}", email))
    assert resp.status_code == 200
    return uuid.UUID(resp.json()["data"]["id"])


async def _sub(db: AsyncSession, user_id: uuid.UUID) -> Subscription:
    db.expire_all()
    row = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    assert row is not None
    return row


async def _setup(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    linked: bool = True,
    override: dict[str, Any] | None = None,
    comp: bool = False,
) -> None:
    row = await _sub(db, user_id)
    row.stripe_customer_id = CUS
    row.stripe_subscription_id = SUB if linked else None
    row.limits_override = override
    if comp:
        row.comp_plan = PlanType.PRO
        row.comp_expires_at = datetime.now(UTC) + timedelta(days=30)
    await db.commit()


def _sub_event(
    eid: str,
    etype: str = "customer.subscription.updated",
    *,
    status: str = "active",
    price: str | None = "price_pro",
    created: int = 1000,
    sub_id: str = SUB,
    customer: str = CUS,
    metadata: Any = None,
    previous: Any = None,
    cancel_at: int | None = None,
) -> dict[str, Any]:
    obj: dict[str, Any] = {"id": sub_id, "customer": customer, "status": status}
    if price is not None:
        obj["items"] = {"data": [{"price": {"id": price}}]}
    if metadata is not None:
        obj["metadata"] = metadata
    if cancel_at is not None:
        obj["cancel_at"] = cancel_at
    data: dict[str, Any] = {"object": obj}
    if previous is not None:
        data["previous_attributes"] = previous
    return {"id": eid, "type": etype, "created": created, "data": data}


def _checkout(
    eid: str, user_id: uuid.UUID | str | None, *, sub: str | None = SUB, customer: str = CUS
) -> dict[str, Any]:
    obj: dict[str, Any] = {"mode": "subscription", "customer": customer}
    if user_id is not None:
        obj["client_reference_id"] = str(user_id)
    if sub is not None:
        obj["subscription"] = sub
    return {
        "id": eid,
        "type": "checkout.session.completed",
        "created": 1000,
        "data": {"object": obj},
    }


def _invoice_failed(eid: str) -> dict[str, Any]:
    return {
        "id": eid,
        "type": "invoice.payment_failed",
        "created": 1000,
        "data": {"object": {"id": "in_1", "customer": CUS}},
    }


async def _run(db: AsyncSession, event: dict[str, Any]) -> bool:
    return await process_event(db, event, pack_credits={}, plan_prices=PRICES)


async def _notes(db: AsyncSession, user_id: uuid.UUID) -> list[Notification]:
    return list(
        (await db.scalars(select(Notification).where(Notification.user_id == user_id))).all()
    )


async def _cancel_rows(db: AsyncSession) -> list[StripeCancelRequest]:
    db.expire_all()
    return list((await db.scalars(select(StripeCancelRequest))).all())


# ------------------------------------------------ 1. override never touched


async def test_plan_change_updates_limits_but_override_still_wins(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=OVERRIDE)
    await _run(db, _sub_event("evt_a", price="price_pro"))
    row = await _sub(db, uid)
    assert row.plan is PlanType.PRO
    assert row.limits == default_limits(PlanType.PRO)
    assert row.limits_override == OVERRIDE
    eff = effective_limits(row)
    assert eff["max_projects"] == 99 and eff["max_teams"] is None
    assert eff["max_integrations"] is None  # PRO default falls through


async def test_downgrade_event_keeps_override(client: AsyncClient, db: AsyncSession) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=OVERRIDE)
    await _run(db, _sub_event("evt_a", price="price_pro", created=1000))
    await _run(db, _sub_event("evt_b", price="price_basic", created=2000))
    row = await _sub(db, uid)
    assert row.limits == default_limits(PlanType.BASIC)
    assert row.limits_override == OVERRIDE
    assert effective_limits(row)["max_projects"] == 99


@pytest.mark.parametrize(
    "event",
    [
        _sub_event("evt_c", "customer.subscription.created", price="price_pro"),
        _sub_event("evt_u", "customer.subscription.updated", price="price_basic"),
        _sub_event("evt_p", "customer.subscription.updated", status="past_due"),
        _sub_event("evt_s", "customer.subscription.updated", cancel_at=4_000_000_000),
        _sub_event("evt_d", "customer.subscription.deleted", status="canceled"),
        _sub_event("evt_ce", "customer.subscription.updated", status="canceled"),
        _checkout("evt_co", uuid.UUID(int=0)),  # user filled in below
        _invoice_failed("evt_inv"),
    ],
    ids=[
        "created",
        "updated",
        "past_due",
        "cancel_at",
        "deleted",
        "term_end_clamp",
        "checkout",
        "invoice",
    ],
)
async def test_override_and_effective_limits_identical_across_every_event(
    client: AsyncClient, db: AsyncSession, event: dict[str, Any]
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=OVERRIDE)
    if event["type"] == "checkout.session.completed":
        event["data"]["object"]["client_reference_id"] = str(uid)
    before = await _sub(db, uid)
    override_before = dict(before.limits_override or {})
    # effective limits when the plan-side limits are held constant
    await _run(db, event)
    after = await _sub(db, uid)
    assert after.limits_override == override_before == OVERRIDE
    eff = effective_limits(after)
    assert eff["max_projects"] == 99 and eff["max_teams"] is None


async def test_term_end_clamps_plan_limits_not_override(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=OVERRIDE)
    await _run(db, _sub_event("evt_a", price="price_pro", created=1000))
    await _run(
        db, _sub_event("evt_b", "customer.subscription.deleted", status="canceled", created=2000)
    )
    row = await _sub(db, uid)
    assert row.status is SubscriptionStatus.CANCELED
    assert row.limits == default_limits(PlanType.BASIC)
    assert row.limits_override == OVERRIDE
    assert effective_limits(row)["max_projects"] == 99


async def test_null_override_stays_null(client: AsyncClient, db: AsyncSession) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=None)
    await _run(db, _sub_event("evt_a"))
    assert (await _sub(db, uid)).limits_override is None


# ------------------------------------------------ 2. comp clearing


async def test_comp_cleared_on_first_link_via_subscription_event(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, linked=False, override=OVERRIDE, comp=True)
    await _run(db, _sub_event("evt_a", price="price_basic"))
    row = await _sub(db, uid)
    assert row.stripe_subscription_id == SUB
    assert row.comp_plan is None and row.comp_expires_at is None
    assert row.plan is PlanType.BASIC
    assert row.limits_override == OVERRIDE


async def test_comp_cleared_on_first_link_via_checkout(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, linked=False, override=OVERRIDE, comp=True)
    await _run(db, _checkout("evt_co", uid))
    row = await _sub(db, uid)
    assert row.stripe_subscription_id == SUB
    assert row.comp_plan is None and row.comp_expires_at is None
    assert row.limits_override == OVERRIDE


async def test_comp_not_cleared_when_already_linked(client: AsyncClient, db: AsyncSession) -> None:
    uid = await _provision(client)
    await _setup(db, uid, linked=True, comp=True)
    for i, ev in enumerate(
        [_sub_event("evt_a"), _checkout("evt_co", uid), _invoice_failed("evt_inv")]
    ):
        await _run(db, ev)
        row = await _sub(db, uid)
        assert row.comp_plan is PlanType.PRO, i
        assert row.comp_expires_at is not None, i


async def test_comp_set_after_first_link_survives_later_events(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, linked=False)
    await _run(db, _sub_event("evt_a", created=1000))
    row = await _sub(db, uid)
    row.comp_plan = PlanType.PRO
    await db.commit()
    await _run(db, _sub_event("evt_b", created=2000))
    assert (await _sub(db, uid)).comp_plan is PlanType.PRO


async def test_other_users_comp_unaffected(client: AsyncClient, db: AsyncSession) -> None:
    uid = await _provision(client)
    other = await _provision(client, "other-t5@example.com")
    await _setup(db, uid, linked=False)
    o = await _sub(db, other)
    o.comp_plan = PlanType.PRO
    await db.commit()
    await _run(db, _sub_event("evt_a"))
    assert (await _sub(db, other)).comp_plan is PlanType.PRO


async def test_terminal_first_link_does_not_clear_comp(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, linked=False, comp=True)
    await _run(db, _sub_event("evt_d", "customer.subscription.deleted", status="canceled"))
    assert (await _sub(db, uid)).comp_plan is PlanType.PRO


async def _setup_canceled_with_comp(db: AsyncSession, uid: uuid.UUID, old_sub: str) -> None:
    await _setup(db, uid, linked=True, override=OVERRIDE, comp=True)
    row = await _sub(db, uid)
    row.stripe_subscription_id = old_sub
    row.status = SubscriptionStatus.CANCELED
    await db.commit()


async def test_resubscribe_new_sub_id_event_clears_comp(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup_canceled_with_comp(db, uid, "sub_old")
    await _run(db, _sub_event("evt_re", price="price_pro", sub_id="sub_new"))
    row = await _sub(db, uid)
    assert row.stripe_subscription_id == "sub_new"
    assert row.comp_plan is None and row.comp_expires_at is None
    assert row.limits_override == OVERRIDE


async def test_resubscribe_new_sub_id_checkout_clears_comp(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup_canceled_with_comp(db, uid, "sub_old")
    await _run(db, _checkout("evt_re_co", uid, sub="sub_new"))
    row = await _sub(db, uid)
    assert row.stripe_subscription_id == "sub_new"
    assert row.comp_plan is None and row.comp_expires_at is None


async def test_same_sub_id_replay_does_not_clear_a_later_comp(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup_canceled_with_comp(db, uid, SUB)
    await _run(db, _sub_event("evt_same", sub_id=SUB, created=2000))
    await _run(db, _checkout("evt_same_co", uid, sub=SUB))
    row = await _sub(db, uid)
    assert row.comp_plan is PlanType.PRO and row.comp_expires_at is not None


async def test_terminal_event_with_new_sub_id_does_not_clear_comp(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup_canceled_with_comp(db, uid, "sub_old")
    await _run(
        db, _sub_event("evt_term", "customer.subscription.deleted", status="canceled", sub_id=SUB)
    )
    assert (await _sub(db, uid)).comp_plan is PlanType.PRO


# ------------------------------------------------ 3. admin-originated wording


def _admin_meta(action: str) -> dict[str, str]:
    return {ADMIN_ACTION_METADATA_KEY: action}


async def _plan_notes(db: AsyncSession, uid: uuid.UUID) -> list[Notification]:
    return [n for n in await _notes(db, uid) if n.title != "Payment successful"]


async def test_admin_plan_change_uses_support_wording(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid)
    await _run(db, _sub_event("evt_a", price="price_basic", created=1000))
    await _run(
        db,
        _sub_event(
            "evt_b",
            price="price_pro",
            created=2000,
            metadata=_admin_meta("act_1"),
            previous={"metadata": {ADMIN_ACTION_METADATA_KEY: None}},
        ),
    )
    notes = await _plan_notes(db, uid)
    assert len(notes) == 1
    assert "Solus support" in (notes[0].body or "")
    assert "act_1" not in (notes[0].body or "")
    assert "act_1" not in str(notes[0].attrs)


async def test_admin_wording_when_previous_id_replaced(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid)
    await _run(db, _sub_event("evt_a", price="price_basic", created=1000))
    await _run(
        db,
        _sub_event(
            "evt_b",
            price="price_pro",
            created=2000,
            metadata=_admin_meta("act_2"),
            previous={"metadata": _admin_meta("act_1")},
        ),
    )
    assert any("Solus support" in (n.body or "") for n in await _notes(db, uid))


@pytest.mark.parametrize(
    "previous",
    [
        None,  # no previous_attributes
        {"items": {}},  # no metadata change
        {"metadata": {"other": "x"}},  # metadata changed, but not our key
        {"metadata": None},
        {"metadata": "junk"},
        "junk",
    ],
)
async def test_stale_or_spoofed_metadata_gets_default_wording(
    client: AsyncClient, db: AsyncSession, previous: Any
) -> None:
    uid = await _provision(client)
    await _setup(db, uid)
    await _run(db, _sub_event("evt_a", price="price_basic", created=1000))
    await _run(
        db,
        _sub_event(
            "evt_b",
            price="price_pro",
            created=2000,
            metadata=_admin_meta("act_stale"),
            previous=previous,
        ),
    )
    notes = await _notes(db, uid)
    assert not any("Solus support" in (n.body or "") for n in notes)
    assert any(n.title == "Plan updated" for n in notes)


async def test_admin_metadata_removed_is_not_admin_action(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client)
    await _setup(db, uid)
    await _run(db, _sub_event("evt_a", price="price_basic", created=1000))
    await _run(
        db,
        _sub_event(
            "evt_b",
            price="price_pro",
            created=2000,
            metadata={},
            previous={"metadata": _admin_meta("act_1")},
        ),
    )
    assert not any("Solus support" in (n.body or "") for n in await _notes(db, uid))


async def test_admin_marker_never_changes_entitlement(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A forged marker with a basic price still yields exactly the purchased plan."""
    uid = await _provision(client)
    await _setup(db, uid)
    await _run(
        db,
        _sub_event(
            "evt_a",
            price="price_basic",
            metadata={**_admin_meta("act_1"), "plan": "pro"},
            previous={"metadata": {ADMIN_ACTION_METADATA_KEY: None}},
        ),
    )
    row = await _sub(db, uid)
    assert row.plan is PlanType.BASIC
    assert row.limits == default_limits(PlanType.BASIC)


# ------------------------------------------------ 4. tombstone race


async def _tombstone(db: AsyncSession, cus: str = CUS, sub: str | None = None) -> None:
    db.add(
        StripeCancelRequest(
            stripe_customer_id=cus,
            stripe_subscription_id=sub,
            completed_at=datetime.now(UTC),
            next_attempt_at=datetime.now(UTC),
        )
    )
    await db.commit()


@pytest.mark.parametrize(
    "etype", ["customer.subscription.created", "customer.subscription.updated"]
)
@pytest.mark.parametrize("status", ["active", "trialing", "past_due", "incomplete"])
async def test_late_subscription_event_for_tombstoned_customer_enqueues_cancel(
    db: AsyncSession, etype: str, status: str
) -> None:
    await _tombstone(db)
    assert await _run(db, _sub_event("evt_a", etype, status=status, sub_id="sub_late"))
    rows = await _cancel_rows(db)
    assert len(rows) == 1
    assert rows[0].stripe_customer_id == CUS
    assert rows[0].stripe_subscription_id == "sub_late"
    assert rows[0].completed_at is None  # re-armed
    assert rows[0].attempts == 0


async def test_replay_and_second_event_keep_exactly_one_row(db: AsyncSession) -> None:
    await _tombstone(db)
    ev = _sub_event("evt_a", sub_id="sub_late")
    assert await _run(db, ev) is True
    assert await _run(db, ev) is False  # replay no-op
    assert await _run(db, _sub_event("evt_b", sub_id="sub_later", created=2000)) is True
    rows = await _cancel_rows(db)
    assert len(rows) == 1 and rows[0].stripe_subscription_id == "sub_later"


async def test_late_checkout_for_tombstoned_customer_enqueues_cancel(db: AsyncSession) -> None:
    await _tombstone(db)
    # no client_reference_id at all, and also a reference to a deleted (absent) user
    await _run(db, _checkout("evt_a", None, sub="sub_co"))
    assert [r.stripe_subscription_id for r in await _cancel_rows(db)] == ["sub_co"]
    await _run(db, _checkout("evt_b", uuid.uuid4(), sub="sub_co2"))
    rows = await _cancel_rows(db)
    assert len(rows) == 1 and rows[0].stripe_subscription_id == "sub_co2"


async def test_checkout_without_subscription_id_enqueues_with_none_keeps_known(
    db: AsyncSession,
) -> None:
    await _tombstone(db, sub="sub_known")
    await _run(db, _checkout("evt_a", uuid.uuid4(), sub=None))
    rows = await _cancel_rows(db)
    assert len(rows) == 1 and rows[0].stripe_subscription_id == "sub_known"
    assert rows[0].completed_at is None


@pytest.mark.parametrize(
    ("etype", "status"),
    [
        ("customer.subscription.deleted", "canceled"),
        ("customer.subscription.updated", "canceled"),
        ("customer.subscription.updated", "incomplete_expired"),
        ("customer.subscription.created", "incomplete_expired"),
    ],
)
async def test_terminal_events_for_tombstoned_customer_ignored(
    db: AsyncSession, etype: str, status: str
) -> None:
    await _tombstone(db)
    assert await _run(db, _sub_event("evt_a", etype, status=status, sub_id="sub_late"))
    rows = await _cancel_rows(db)
    assert len(rows) == 1 and rows[0].stripe_subscription_id is None
    assert rows[0].completed_at is not None


async def test_non_tombstoned_unknown_customer_is_logged_and_ignored(db: AsyncSession) -> None:
    assert await _run(db, _sub_event("evt_a", customer="cus_stranger", sub_id="sub_x"))
    assert await _cancel_rows(db) == []
    assert await db.scalar(
        select(ProcessedStripeEvent.id).where(ProcessedStripeEvent.stripe_event_id == "evt_a")
    )


async def test_spoofed_customer_cannot_cancel_another_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An event naming a live customer (not a tombstone) enqueues nothing, and an event for
    a tombstone only ever targets the subscription id carried by the signed payload."""
    uid = await _provision(client)
    await _setup(db, uid)
    await _tombstone(db, cus="cus_dead")
    await _run(
        db,
        _sub_event(
            "evt_a",
            customer="cus_dead",
            sub_id="sub_mine",
            metadata={"subscription": SUB, "solus_user_id": str(uid)},
        ),
    )
    rows = await _cancel_rows(db)
    assert [(r.stripe_customer_id, r.stripe_subscription_id) for r in rows] == [
        ("cus_dead", "sub_mine")
    ]
    row = await _sub(db, uid)
    assert row.stripe_subscription_id == SUB and row.status is not SubscriptionStatus.CANCELED


async def _live_user_b(client: AsyncClient, db: AsyncSession) -> uuid.UUID:
    uid = await _provision(client, "live-b@example.com")
    await _setup(db, uid)
    return uid


async def _snapshot(db: AsyncSession, uid: uuid.UUID) -> tuple[Any, ...]:
    row = await _sub(db, uid)
    return (
        row.stripe_customer_id,
        row.stripe_subscription_id,
        row.plan,
        row.status,
        row.limits,
        row.stripe_event_at,
    )


async def test_checkout_for_a_live_user_naming_a_tombstoned_customer_does_not_relink(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _live_user_b(client, db)
    await _tombstone(db, cus="cus_dead")
    before = await _snapshot(db, uid)
    ledger_before = await _notes(db, uid)

    assert await _run(db, _checkout("evt_a", uid, sub="sub_new", customer="cus_dead"))

    assert await _snapshot(db, uid) == before
    assert len(await _notes(db, uid)) == len(ledger_before)
    [tomb] = await _cancel_rows(db)  # nothing enqueued: B's subscription is not canceled
    assert tomb.completed_at is not None and tomb.stripe_subscription_id is None


async def test_subscription_event_matching_b_by_sub_id_but_a_tombstoned_customer_is_ignored(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _live_user_b(client, db)
    await _tombstone(db, cus="cus_dead")
    before = await _snapshot(db, uid)

    assert await _run(db, _sub_event("evt_a", sub_id=SUB, customer="cus_dead", created=2000))

    assert await _snapshot(db, uid) == before
    [tomb] = await _cancel_rows(db)
    assert tomb.completed_at is not None


async def test_the_runner_never_cancels_b_after_a_refused_tombstone_link(
    client: AsyncClient, db: AsyncSession
) -> None:
    from fixtures.stripe_fake import FakeStripeGateway
    from solus_api.services.stripe_cancel import run_due_stripe_cancels

    uid = await _live_user_b(client, db)
    await _tombstone(db, cus="cus_dead")
    await _run(db, _checkout("evt_a", uid, sub="sub_new", customer="cus_dead"))
    await _run(db, _sub_event("evt_b", sub_id=SUB, customer="cus_dead", created=2000))
    fake = FakeStripeGateway()
    fake.seed_subscription("sub_new", customer_id="cus_dead")

    summary = await run_due_stripe_cancels(db, fake, now=datetime.now(UTC) + timedelta(days=2))

    assert summary.attempted == 0
    assert fake.calls_to("cancel_subscription") == []
    assert fake.subscriptions["sub_new"].status != "canceled"
    assert (await _sub(db, uid)).stripe_customer_id == CUS


async def test_a_live_users_own_customer_still_links_normally(
    client: AsyncClient, db: AsyncSession
) -> None:
    uid = await _provision(client, "relink@example.com")
    await _tombstone(db, cus="cus_dead")
    assert await _run(db, _checkout("evt_a", uid, sub="sub_ok", customer="cus_fresh"))
    row = await _sub(db, uid)
    assert (row.stripe_customer_id, row.stripe_subscription_id) == ("cus_fresh", "sub_ok")


async def test_deleted_user_event_is_safe_noop(client: AsyncClient, db: AsyncSession) -> None:
    uid = await _provision(client)
    await _setup(db, uid)
    row = await _sub(db, uid)
    row.deleted_at = datetime.now(UTC)
    await db.commit()
    assert await _run(db, _sub_event("evt_a")) is True
    assert await _cancel_rows(db) == []
    assert (await _sub(db, uid)).plan is not PlanType.PRO


async def test_invalid_ids_on_tombstone_path_do_not_crash(db: AsyncSession) -> None:
    await _tombstone(db)
    assert await _run(db, _sub_event("evt_a", sub_id="not-a-sub-id"))
    assert await _run(db, _checkout("evt_b", None, sub="bad id"))
    rows = await _cancel_rows(db)
    assert len(rows) == 1 and rows[0].completed_at is not None


# ------------------------------------------------ 5. dedupe / ordering / malformed


async def test_replayed_event_is_noop(client: AsyncClient, db: AsyncSession) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=OVERRIDE)
    ev = _sub_event("evt_a", price="price_pro")
    assert await _run(db, ev) is True
    before = len(await _notes(db, uid))
    assert await _run(db, ev) is False
    assert len(await _notes(db, uid)) == before


async def test_older_event_ignored(client: AsyncClient, db: AsyncSession) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=OVERRIDE)
    await _run(db, _sub_event("evt_new", price="price_pro", created=2000))
    await _run(db, _sub_event("evt_old", price="price_basic", created=1000))
    row = await _sub(db, uid)
    assert row.plan is PlanType.PRO
    assert row.limits == default_limits(PlanType.PRO)
    assert row.limits_override == OVERRIDE


@pytest.mark.parametrize(
    "event",
    [
        {
            "id": "evt_m1",
            "type": "customer.subscription.updated",
            "created": 1,
            "data": {"object": {}},
        },
        {"id": "evt_m2", "type": "customer.subscription.updated", "created": 1, "data": {}},
        {"id": "evt_m3", "type": "customer.subscription.updated", "created": 1},
        _sub_event(
            "evt_m4", metadata="junk", previous={"metadata": {ADMIN_ACTION_METADATA_KEY: "a"}}
        ),
        _sub_event("evt_m5", metadata=["x"], previous={"metadata": ["y"]}),
        _sub_event(
            "evt_m6",
            metadata={ADMIN_ACTION_METADATA_KEY: 7},
            previous={"metadata": {ADMIN_ACTION_METADATA_KEY: None}},
        ),
        {
            "id": "evt_m7",
            "type": "customer.subscription.updated",
            "created": 1,
            "data": {"object": {"id": SUB, "customer": CUS, "status": "active", "items": "junk"}},
        },
        {
            "id": "evt_m8",
            "type": "customer.subscription.updated",
            "created": 1,
            "data": {
                "object": {"id": SUB, "customer": CUS, "status": "active", "items": {"data": ["x"]}}
            },
        },
        {
            "id": "evt_m9",
            "type": "customer.subscription.updated",
            "created": 1,
            "data": {
                "object": {"id": 5, "customer": ["x"], "status": "active"},
                "previous_attributes": 3,
            },
        },
        {
            "id": "evt_m10",
            "type": "checkout.session.completed",
            "created": 1,
            "data": {"object": {"mode": "subscription", "customer": 5, "subscription": {"a": 1}}},
        },
    ],
    ids=lambda e: e["id"],
)
async def test_malformed_payloads_never_crash(
    client: AsyncClient, db: AsyncSession, event: dict[str, Any]
) -> None:
    uid = await _provision(client)
    await _setup(db, uid, override=OVERRIDE)
    await _tombstone(db, cus="cus_other")
    assert await _run(db, event) is True
    assert (await _sub(db, uid)).limits_override == OVERRIDE
