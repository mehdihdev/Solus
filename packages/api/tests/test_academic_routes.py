"""Academic plan routes (SOLUSDEV-319, ADR-042): GET status, POST code, POST verify.

Covers auth, the domain rule, eligibility 409s, rate limits, code checks, the
subscription switch + first monthly grant, one-address-one-account, events, and
cross-user isolation (Bob can never read or use Alice's pending code)."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from conftest import ALICE, BOB, TEST_AUDIENCE, TEST_DATABASE_URL, TEST_JWT_SECRET, bearer, me
from httpx import ASGITransport, AsyncClient
from solus_api.core.config import Settings
from solus_api.deps import get_academic_mailer
from solus_api.main import create_app
from solus_api.models import (
    AcademicVerification,
    CreditLedger,
    CreditTxnType,
    DataEvent,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
    utcnow,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

BASE = "/api/v1/billing/academic"


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False

    async def send_code(self, to: str, code: str) -> None:
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append((to, code))

    def last_code(self) -> str:
        return self.sent[-1][1]


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
        sync_inline=True,
        academic_monthly_credits=1000,
    )


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
async def aclient(engine: Any, mailer: FakeMailer) -> Any:
    app = create_app(settings=_settings(), engine=engine)
    app.dependency_overrides[get_academic_mailer] = lambda: mailer
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _alice(client: AsyncClient, db: AsyncSession, *, consent: bool = False) -> dict[str, str]:
    headers = bearer(ALICE["sub"], ALICE["email"])
    await me(client, headers)
    if consent:
        await db.execute(
            update(User).where(User.email == ALICE["email"]).values(data_collection_consent=True)
        )
        await db.commit()
    return dict(headers)


async def _sub(db: AsyncSession, email: str) -> Subscription:
    db.expire_all()
    sub = await db.scalar(
        select(Subscription).join(User, User.id == Subscription.user_id).where(User.email == email)
    )
    assert sub is not None
    return sub


async def _events(db: AsyncSession, prefix: str) -> list[DataEvent]:
    db.expire_all()
    rows = await db.scalars(select(DataEvent).where(DataEvent.event_type.startswith(prefix)))
    return list(rows.all())


async def _send(client: AsyncClient, headers: dict[str, str], email: str = "ada@mit.edu") -> Any:
    return await client.post(f"{BASE}/code", json={"email": email}, headers=headers)


async def _verify(client: AsyncClient, headers: dict[str, str], code: str) -> Any:
    return await client.post(f"{BASE}/verify", json={"code": code}, headers=headers)


# ------------------------------------------------------------------ auth + read


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "", None),
        ("post", "/code", {"email": "a@mit.edu"}),
        ("post", "/verify", {"code": "123456"}),
    ],
)
async def test_unauthenticated_is_401(
    aclient: AsyncClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    resp = await aclient.request(method.upper(), f"{BASE}{path}", json=body)
    assert resp.status_code == 401


async def test_status_starts_as_none_with_suffix_hint(
    aclient: AsyncClient, db: AsyncSession
) -> None:
    headers = await _alice(aclient, db)
    data = (await aclient.get(BASE, headers=headers)).json()["data"]
    assert data["state"] == "none"
    assert data["email"] is None and data["pending_email"] is None
    assert data["monthly_credits"] == 1000
    assert "edu" in data["suffixes"] and "ac.uk" in data["suffixes"]


# ------------------------------------------------------------------ send code


async def test_send_code_emails_a_six_digit_code_and_goes_pending(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    resp = await _send(aclient, headers, "  Ada@CSAIL.MIT.edu ")
    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    assert data["state"] == "pending" and data["pending_email"] == "ada@csail.mit.edu"
    assert data["code_expires_at"]
    to, code = mailer.sent[-1]
    assert to == "ada@csail.mit.edu" and code.isdigit() and len(code) == 6
    row = await db.scalar(select(AcademicVerification))
    assert row is not None and row.code_hash and code not in row.code_hash


@pytest.mark.parametrize(
    "email", ["ada@gmail.com", "ada@edu", "ada@mit.edu.evil.com", "ada@notedu", "not-an-email"]
)
async def test_non_academic_address_is_422(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer, email: str
) -> None:
    headers = await _alice(aclient, db)
    resp = await _send(aclient, headers, email)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] in {"not_academic_email", "validation_error"}
    assert mailer.sent == []


@pytest.mark.parametrize("email", ["ada@ox.ac.uk", "ada@unimelb.edu.au", "ada@stanford.edu"])
async def test_international_academic_domains_are_accepted(
    aclient: AsyncClient, db: AsyncSession, email: str
) -> None:
    headers = await _alice(aclient, db)
    assert (await _send(aclient, headers, email)).status_code == 202


async def test_unknown_fields_are_rejected(aclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _alice(aclient, db)
    resp = await aclient.post(
        f"{BASE}/code", json={"email": "ada@mit.edu", "user_id": str(uuid.uuid4())}, headers=headers
    )
    assert resp.status_code == 422


async def test_live_stripe_subscription_is_409(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    sub = await _sub(db, ALICE["email"])
    sub.stripe_subscription_id = "sub_live"
    sub.status = SubscriptionStatus.ACTIVE
    await db.commit()
    resp = await _send(aclient, headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "stripe_subscription_active"
    assert mailer.sent == []


async def test_enterprise_is_not_eligible(aclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _alice(aclient, db)
    sub = await _sub(db, ALICE["email"])
    sub.plan = PlanType.ENTERPRISE
    sub.status = SubscriptionStatus.ACTIVE
    await db.commit()
    resp = await _send(aclient, headers)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "plan_not_eligible"


async def test_canceled_stripe_subscription_may_claim(
    aclient: AsyncClient, db: AsyncSession
) -> None:
    headers = await _alice(aclient, db)
    sub = await _sub(db, ALICE["email"])
    sub.stripe_subscription_id = "sub_old"
    sub.status = SubscriptionStatus.CANCELED
    await db.commit()
    assert (await _send(aclient, headers)).status_code == 202


async def test_resend_cooldown_is_429_with_retry_after(
    aclient: AsyncClient, db: AsyncSession
) -> None:
    headers = await _alice(aclient, db)
    assert (await _send(aclient, headers)).status_code == 202
    resp = await _send(aclient, headers)
    assert resp.status_code == 429 and resp.json()["error"]["code"] == "rate_limited"
    assert 0 < int(resp.headers["Retry-After"]) <= 60


async def test_hourly_send_cap_per_user(aclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _alice(aclient, db)
    for i in range(5):
        await db.execute(
            update(AcademicVerification).values(last_sent_at=utcnow() - timedelta(minutes=2))
        )
        await db.commit()
        assert (await _send(aclient, headers, f"ada{i}@mit.edu")).status_code == 202
    await db.execute(
        update(AcademicVerification).values(last_sent_at=utcnow() - timedelta(minutes=2))
    )
    await db.commit()
    assert (await _send(aclient, headers, "ada9@mit.edu")).status_code == 429


async def test_hourly_send_cap_per_address_across_accounts(
    aclient: AsyncClient, db: AsyncSession
) -> None:
    for i in range(3):
        headers = bearer(f"00000000-0000-0000-0000-0000000001{i:02d}", f"user{i}@example.com")
        await me(aclient, headers)
        assert (await _send(aclient, headers, "shared@mit.edu")).status_code == 202
    headers = bearer("00000000-0000-0000-0000-000000000199", "user9@example.com")
    await me(aclient, headers)
    resp = await _send(aclient, headers, "shared@mit.edu")
    assert resp.status_code == 429


async def test_mailer_unconfigured_is_503(engine: Any, db: AsyncSession) -> None:
    # No sender outside dev builds no mailer (test_academic_mail.py); the route turns that
    # None into 503 without generating or storing a code.
    app = create_app(settings=_settings(), engine=engine)
    app.dependency_overrides[get_academic_mailer] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        headers = bearer(ALICE["sub"], ALICE["email"])
        await me(c, headers)
        resp = await _send(c, headers)
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "email_unconfigured"


async def test_mailer_failure_is_502_and_leaves_no_usable_code(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    mailer.fail = True
    resp = await _send(aclient, headers)
    assert resp.status_code == 502 and resp.json()["error"]["code"] == "email_send_failed"
    assert (await aclient.get(BASE, headers=headers)).json()["data"]["state"] == "none"


async def test_code_sent_event_carries_domain_only(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db, consent=True)
    await _send(aclient, headers)
    events = await _events(db, "billing.academic.code_sent")
    assert [e.payload for e in events] == [{"domain": "mit.edu"}]
    assert mailer.last_code() not in str(events[0].payload)


# ------------------------------------------------------------------ verify


async def test_verify_switches_to_academic_and_grants_monthly_credits(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db, consent=True)
    await _send(aclient, headers)
    resp = await _verify(aclient, headers, mailer.last_code())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["state"] == "active" and data["email"] == "ada@mit.edu"
    sub = await _sub(db, ALICE["email"])
    assert sub.plan == PlanType.ACADEMIC and sub.status == SubscriptionStatus.ACTIVE
    assert sub.limits == default_limits(PlanType.BASIC)
    assert sub.stripe_subscription_id is None and sub.billing_interval is None
    assert sub.expires_at is not None
    assert timedelta(days=364) < sub.expires_at - utcnow() <= timedelta(days=365)
    grants = (
        await db.scalars(
            select(CreditLedger).where(
                CreditLedger.user_id == sub.user_id,
                CreditLedger.type == CreditTxnType.ACADEMIC_GRANT,
            )
        )
    ).all()
    assert [g.amount for g in grants] == [1000]
    assert [e.payload for e in await _events(db, "billing.academic.verified")] == [
        {"domain": "mit.edu"}
    ]
    me_sub = (await aclient.get("/api/v1/users/me/subscription", headers=headers)).json()["data"]
    assert me_sub["plan"] == "academic" and me_sub["trial_expired"] is False


async def test_verify_keeps_the_stripe_customer_for_packs(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    sub = await _sub(db, ALICE["email"])
    sub.stripe_customer_id, sub.stripe_subscription_id = "cus_1", "sub_old"
    sub.status = SubscriptionStatus.CANCELED
    await db.commit()
    await _send(aclient, headers)
    assert (await _verify(aclient, headers, mailer.last_code())).status_code == 200
    sub = await _sub(db, ALICE["email"])
    assert sub.stripe_customer_id == "cus_1" and sub.stripe_subscription_id is None


async def test_reverify_does_not_double_grant_in_one_month(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    for _ in range(2):
        await db.execute(
            update(AcademicVerification).values(last_sent_at=utcnow() - timedelta(minutes=2))
        )
        await db.commit()
        await _send(aclient, headers)
        assert (await _verify(aclient, headers, mailer.last_code())).status_code == 200
    sub = await _sub(db, ALICE["email"])
    total = await db.scalars(
        select(CreditLedger.amount).where(
            CreditLedger.user_id == sub.user_id, CreditLedger.type == CreditTxnType.ACADEMIC_GRANT
        )
    )
    assert list(total.all()) == [1000]


async def test_wrong_code_reports_attempts_left_then_locks(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db, consent=True)
    await _send(aclient, headers)
    wrong = "000000" if mailer.last_code() != "000000" else "111111"
    for left in (4, 3, 2, 1, 0):
        resp = await _verify(aclient, headers, wrong)
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_code"
        assert resp.json()["error"]["details"][0]["attempts_left"] == left
    resp = await _verify(aclient, headers, mailer.last_code())
    assert resp.status_code == 429 and resp.json()["error"]["code"] == "too_many_attempts"
    assert (await _sub(db, ALICE["email"])).plan != PlanType.ACADEMIC
    reasons = {e.payload["reason"] for e in await _events(db, "billing.academic.failed")}
    assert reasons == {"invalid_code", "too_many_attempts"}


async def test_expired_code_is_410(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    await _send(aclient, headers)
    await db.execute(
        update(AcademicVerification).values(code_expires_at=utcnow() - timedelta(seconds=1))
    )
    await db.commit()
    resp = await _verify(aclient, headers, mailer.last_code())
    assert resp.status_code == 410 and resp.json()["error"]["code"] == "code_expired"


async def test_verify_without_a_code_is_409(aclient: AsyncClient, db: AsyncSession) -> None:
    headers = await _alice(aclient, db)
    resp = await _verify(aclient, headers, "123456")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "no_pending_code"


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", " 12345"])
async def test_malformed_code_is_422(aclient: AsyncClient, db: AsyncSession, code: str) -> None:
    headers = await _alice(aclient, db)
    assert (await _verify(aclient, headers, code)).status_code == 422


async def test_verify_rechecks_stripe_eligibility(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    await _send(aclient, headers)
    sub = await _sub(db, ALICE["email"])
    sub.stripe_subscription_id, sub.status = "sub_new", SubscriptionStatus.ACTIVE
    await db.commit()
    resp = await _verify(aclient, headers, mailer.last_code())
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "stripe_subscription_active"


# ------------------------------------------------------------------ one address, one account


async def _verify_as(
    client: AsyncClient, mailer: FakeMailer, who: dict[str, str], email: str
) -> Any:
    headers = bearer(who["sub"], who["email"])
    await me(client, headers)
    assert (await _send(client, headers, email)).status_code == 202
    return await _verify(client, headers, mailer.last_code())


async def test_address_backing_a_live_plan_cannot_be_reused(
    aclient: AsyncClient, mailer: FakeMailer
) -> None:
    assert (await _verify_as(aclient, mailer, ALICE, "ada@mit.edu")).status_code == 200
    resp = await _verify_as(aclient, mailer, BOB, "ada@mit.edu")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "academic_email_in_use"


async def test_address_from_an_expired_plan_is_released(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    assert (await _verify_as(aclient, mailer, ALICE, "ada@mit.edu")).status_code == 200
    await db.execute(update(AcademicVerification).values(expires_at=utcnow() - timedelta(days=1)))
    await db.commit()
    assert (await _verify_as(aclient, mailer, BOB, "ada@mit.edu")).status_code == 200
    db.expire_all()
    holders = (
        await db.scalars(
            select(AcademicVerification).where(AcademicVerification.verified_email == "ada@mit.edu")
        )
    ).all()
    assert len(holders) == 1


# ------------------------------------------------------------------ isolation


async def test_bob_cannot_see_or_use_alices_pending_code(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    alice = await _alice(aclient, db)
    await _send(aclient, alice)
    alice_code = mailer.last_code()
    bob = bearer(BOB["sub"], BOB["email"])
    await me(aclient, bob)
    bob_view = (await aclient.get(BASE, headers=bob)).json()["data"]
    assert bob_view["state"] == "none" and bob_view["pending_email"] is None
    resp = await _verify(aclient, bob, alice_code)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "no_pending_code"
    assert (await _sub(db, BOB["email"])).plan != PlanType.ACADEMIC
    assert (await _verify(aclient, alice, alice_code)).status_code == 200


# ------------------------------------------------------------------ summary + checkout


async def test_status_reports_expired_after_validity(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    await _send(aclient, headers)
    await _verify(aclient, headers, mailer.last_code())
    past = utcnow() - timedelta(days=1)
    await db.execute(update(AcademicVerification).values(expires_at=past))
    await db.execute(update(Subscription).values(expires_at=past))
    await db.commit()
    data = (await aclient.get(BASE, headers=headers)).json()["data"]
    assert data["state"] == "expired" and data["email"] == "ada@mit.edu"


# ------------------------------------------------------------------ security review fixes


async def test_plus_tags_are_one_address_for_the_one_account_rule(
    aclient: AsyncClient, mailer: FakeMailer
) -> None:
    assert (await _verify_as(aclient, mailer, ALICE, "ada+one@mit.edu")).status_code == 200
    assert mailer.sent[-1][0] == "ada@mit.edu"
    resp = await _verify_as(aclient, mailer, BOB, "Ada+two@MIT.edu")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "academic_email_in_use"


@pytest.mark.parametrize(
    "email",
    [
        '"ada"@mit.edu',
        "ada <x@mit.edu>",
        "a,b@mit.edu",
        "ada @mit.edu",
        "ada@mit .edu",
        "ada@-mit.edu",
        "ada\n@mit.edu",
        ".ada@mit.edu",
        "+tag@mit.edu",
    ],
)
async def test_only_plain_addresses_are_accepted(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer, email: str
) -> None:
    headers = await _alice(aclient, db)
    resp = await _send(aclient, headers, email)
    assert resp.status_code == 422 and mailer.sent == []


async def test_address_cap_counts_every_send_not_accounts(
    aclient: AsyncClient, db: AsyncSession
) -> None:
    headers = await _alice(aclient, db)
    for _ in range(3):
        await db.execute(
            update(AcademicVerification).values(last_sent_at=utcnow() - timedelta(minutes=2))
        )
        await db.commit()
        assert (await _send(aclient, headers, "victim@mit.edu")).status_code == 202
    # Pointing the pending address elsewhere must not reset the victim's count.
    await db.execute(
        update(AcademicVerification).values(last_sent_at=utcnow() - timedelta(minutes=2))
    )
    await db.commit()
    assert (await _send(aclient, headers, "other@mit.edu")).status_code == 202
    await db.execute(
        update(AcademicVerification).values(last_sent_at=utcnow() - timedelta(minutes=2))
    )
    await db.commit()
    assert (await _send(aclient, headers, "victim+x@mit.edu")).status_code == 429


async def test_one_account_cannot_lock_the_owner_out(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    attacker = bearer(BOB["sub"], BOB["email"])
    await me(aclient, attacker)
    for _ in range(3):
        await db.execute(
            update(AcademicVerification).values(last_sent_at=utcnow() - timedelta(minutes=2))
        )
        await db.commit()
        assert (await _send(aclient, attacker, "ada@mit.edu")).status_code == 202
    owner = await _alice(aclient, db)
    assert (await _send(aclient, owner, "ada@mit.edu")).status_code == 202
    assert (await _verify(aclient, owner, mailer.last_code())).status_code == 200


# ------------------------------------------------------------------ Phase 4 review fixes


async def test_wrong_guesses_are_capped_per_day_across_resends(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db)
    statuses: list[int] = []
    for i in range(3):
        await db.execute(
            update(AcademicVerification).values(
                last_sent_at=utcnow() - timedelta(minutes=2), send_count=0
            )
        )
        await db.commit()
        assert (await _send(aclient, headers, f"x{i}@mit.edu")).status_code == 202
        wrong = "000000" if mailer.last_code() != "000000" else "111111"
        for _ in range(4):
            statuses.append((await _verify(aclient, headers, wrong)).status_code)
    # 10 wrong guesses a day, however many codes: the 11th is refused and kills the code.
    assert statuses.count(400) == 10 and statuses[10:] == [429, 409]
    # A fresh code does not reset the daily budget, even with the right digits.
    await db.execute(
        update(AcademicVerification).values(
            last_sent_at=utcnow() - timedelta(minutes=2), send_count=0
        )
    )
    await db.commit()
    assert (await _send(aclient, headers, "fresh@mit.edu")).status_code == 202
    assert (await _verify(aclient, headers, mailer.last_code())).status_code == 429


async def test_lockout_is_recorded_once_not_on_every_call(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    headers = await _alice(aclient, db, consent=True)
    await _send(aclient, headers)
    wrong = "000000" if mailer.last_code() != "000000" else "111111"
    for _ in range(5):
        await _verify(aclient, headers, wrong)
    for _ in range(5):
        await _verify(aclient, headers, wrong)
    failed = [e.payload["reason"] for e in await _events(db, "billing.academic.failed")]
    assert failed.count("too_many_attempts") == 1


async def test_delete_and_sign_up_again_gives_no_new_grant_or_year(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    from sqlalchemy import delete

    assert (await _verify_as(aclient, mailer, ALICE, "ada@mit.edu")).status_code == 200
    first_end = (await _sub(db, ALICE["email"])).expires_at
    await db.execute(delete(User).where(User.email == ALICE["email"]))
    await db.commit()
    assert (await _verify_as(aclient, mailer, BOB, "ada@mit.edu")).status_code == 200
    bob = await _sub(db, BOB["email"])
    assert bob.plan == PlanType.ACADEMIC and bob.expires_at == first_end
    grants = (
        await db.scalars(
            select(CreditLedger).where(CreditLedger.type == CreditTxnType.ACADEMIC_GRANT)
        )
    ).all()
    assert len(grants) == 1 and grants[0].user_id is None


async def test_address_is_released_when_the_holder_moves_to_a_paid_plan(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    assert (await _verify_as(aclient, mailer, ALICE, "ada@mit.edu")).status_code == 200
    alice = await _sub(db, ALICE["email"])
    alice.plan, alice.stripe_subscription_id = PlanType.PRO, "sub_pro"
    await db.commit()
    assert (await _verify_as(aclient, mailer, BOB, "ada@mit.edu")).status_code == 200


async def test_a_released_address_keeps_its_remaining_time(
    aclient: AsyncClient, db: AsyncSession, mailer: FakeMailer
) -> None:
    assert (await _verify_as(aclient, mailer, ALICE, "ada@mit.edu")).status_code == 200
    alice = await _sub(db, ALICE["email"])
    first_end = alice.expires_at
    alice.plan, alice.stripe_subscription_id = PlanType.PRO, "sub_pro"
    await db.commit()
    assert (await _verify_as(aclient, mailer, BOB, "ada@mit.edu")).status_code == 200
    assert (await _sub(db, BOB["email"])).expires_at == first_end
