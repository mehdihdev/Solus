"""The Academic plan (ADR-042, SOLUSDEV-319): proof of an academic email, the switch to
the free plan, its monthly credits, and the daily sweep.

Rules (ADR-042):
- An academic address is one whose domain ends in a configured suffix (`.edu`,
  `.ac.uk`, …), with at least one label in front of it.
- A 6-digit code is emailed; only an HMAC of (user, address, code) is stored. Codes
  expire after 15 minutes and allow 5 wrong tries. Sending is limited per user (60 s
  cooldown, 5 per hour) and per address (3 per hour), counted in the database so the
  limits hold across API processes.
- One address backs one account at a time; a holder whose plan has expired is released.
- Verifying makes the subscription `academic` / `active` with BASIC limits for
  `academic_validity_days`, and applies this month's grant.
- Each month's grant is idempotent per (user, month). Before it, the previous month's
  unspent academic credits are removed (academic credits count as spent first), never
  below a zero balance.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits
from solus_api.billing.entitlements import is_academic_expired
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.models import (
    AcademicVerification,
    CreditLedger,
    CreditTxnType,
    NotificationType,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
    utcnow,
)
from solus_api.schemas import AcademicRead
from solus_api.services.academic_mail import AcademicMailer
from solus_api.services.events import emit_event
from solus_api.services.notifications import notify_user

logger = logging.getLogger("solus.billing.academic")

AcademicState = Literal["none", "pending", "active", "expired"]

CODE_TTL = timedelta(minutes=15)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)
SEND_WINDOW = timedelta(hours=1)
SENDS_PER_USER_PER_WINDOW = 5
SENDS_PER_ADDRESS_PER_WINDOW = 3
# A Stripe subscription in one of these states is still billing: claiming Academic would
# leave the user paying for a plan they no longer have (ADR-042 §6).
_BILLING_STATUSES = frozenset(
    {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE}
)


# ------------------------------------------------------------------ pure rules


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def academic_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1]


def is_academic_email(raw: str, suffixes: list[str]) -> bool:
    """True when `raw` is one `local@domain` address whose domain ends in a suffix, with at
    least one label before it (so `ada@edu` and `ada@fakeedu` never match)."""
    email = normalize_email(raw)
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    if not local or not domain or ".." in domain:
        return False
    return any(domain.endswith("." + s.strip(".").lower()) for s in suffixes if s.strip("."))


def month_key(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m")


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _grant_key(user_id: uuid.UUID, month: str) -> str:
    return f"academic-grant:{user_id}:{month}"


def _expire_key(user_id: uuid.UUID, month: str) -> str:
    return f"academic-expire:{user_id}:{month}"


def _rate_limited(retry_after: timedelta, message: str) -> APIError:
    seconds = max(1, int(retry_after.total_seconds() + 0.999))
    return APIError(429, "rate_limited", message, headers={"Retry-After": str(seconds)})


# ------------------------------------------------------------------ service


class AcademicPlanService:
    """Academic verification and credits for one request or cron run. Every method acts on
    the given user's own rows only; callers pass the authenticated user, never an id from
    a request body."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    # ---------------------------------------------------------------- reads

    async def status(self, user_id: uuid.UUID, now: datetime | None = None) -> AcademicRead:
        now = now or utcnow()
        row = await self._row(user_id)
        sub = await self._subscription(user_id)
        return AcademicRead(
            state=self._state(row, sub, now),
            email=row.verified_email if row else None,
            pending_email=row.pending_email if self._pending(row, now) and row else None,
            code_expires_at=row.code_expires_at if self._pending(row, now) and row else None,
            expires_at=sub.expires_at if sub and sub.plan == PlanType.ACADEMIC else None,
            monthly_credits=self._settings.academic_monthly_credits,
            suffixes=list(self._settings.academic_email_suffixes),
        )

    @staticmethod
    def _pending(row: AcademicVerification | None, now: datetime) -> bool:
        return (
            row is not None
            and row.code_hash is not None
            and row.code_expires_at is not None
            and _aware(row.code_expires_at) > now
            and row.attempts < MAX_ATTEMPTS
        )

    def _state(
        self, row: AcademicVerification | None, sub: Subscription | None, now: datetime
    ) -> AcademicState:
        if self._pending(row, now):
            return "pending"
        if row is None or row.verified_email is None or sub is None:
            return "none"
        if sub.plan != PlanType.ACADEMIC:
            return "none"
        return "expired" if is_academic_expired(sub, now) else "active"

    # ---------------------------------------------------------------- send

    async def send_code(
        self, user: User, raw_email: str, mailer: AcademicMailer | None
    ) -> AcademicRead:
        now = utcnow()
        email = normalize_email(raw_email)
        if not is_academic_email(email, self._settings.academic_email_suffixes):
            raise APIError(
                422, "not_academic_email", "That address isn't on our list of academic domains"
            )
        self._assert_eligible(await self._require_subscription(user.id))
        if mailer is None:
            raise APIError(503, "email_unconfigured", "Verification email is not configured")
        row = await self._ensure_locked_row(user.id)
        await self._assert_send_allowed(row, email, now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        row.pending_email = email
        row.code_hash = self._hash(user.id, email, code)
        row.code_expires_at = now + CODE_TTL
        row.attempts = 0
        row.last_sent_at = now
        row.send_count += 1
        try:
            await mailer.send_code(email, code)
        except Exception as exc:  # noqa: BLE001 — any provider failure is one 502
            user_id = user.id  # read before rollback expires the instance
            await self._session.rollback()
            logger.warning(
                "academic code send failed user_id=%s domain=%s error=%s",
                user_id,
                academic_domain(email),
                type(exc).__name__,
            )
            raise APIError(502, "email_send_failed", "We couldn't send the email") from exc
        emit_event(
            self._session,
            user=user,
            event_type="billing.academic.code_sent",
            payload={"domain": academic_domain(email)},
        )
        await self._session.commit()
        logger.info("academic code sent user_id=%s domain=%s", user.id, academic_domain(email))
        return await self.status(user.id, now)

    async def _assert_send_allowed(
        self, row: AcademicVerification, email: str, now: datetime
    ) -> None:
        if row.last_sent_at and now - _aware(row.last_sent_at) < RESEND_COOLDOWN:
            wait = RESEND_COOLDOWN - (now - _aware(row.last_sent_at))
            raise _rate_limited(wait, "Wait a minute before asking for another code")
        if row.send_window_start is None or now - _aware(row.send_window_start) >= SEND_WINDOW:
            row.send_window_start, row.send_count = now, 0
        if row.send_count >= SENDS_PER_USER_PER_WINDOW:
            wait = SEND_WINDOW - (now - _aware(row.send_window_start))
            raise _rate_limited(wait, "Too many codes requested; try again later")
        recent = await self._session.scalar(
            select(func.count())
            .select_from(AcademicVerification)
            .where(
                AcademicVerification.pending_email == email,
                AcademicVerification.last_sent_at > now - SEND_WINDOW,
            )
        )
        if (recent or 0) >= SENDS_PER_ADDRESS_PER_WINDOW:
            raise _rate_limited(SEND_WINDOW, "Too many codes sent to that address; try later")

    # ---------------------------------------------------------------- verify

    async def verify(self, user: User, code: str) -> AcademicRead:
        now = utcnow()
        row = await self._locked_row(user.id)
        if row is None or row.code_hash is None or row.pending_email is None:
            raise APIError(409, "no_pending_code", "Ask for a code first")
        if row.attempts >= MAX_ATTEMPTS:
            await self._fail(user, "too_many_attempts")
            raise APIError(429, "too_many_attempts", "Too many wrong codes; send a new one")
        if row.code_expires_at is None or _aware(row.code_expires_at) <= now:
            await self._fail(user, "code_expired")
            raise APIError(410, "code_expired", "That code has expired; send a new one")
        email = row.pending_email
        if not hmac.compare_digest(row.code_hash, self._hash(user.id, email, code)):
            row.attempts += 1
            left = MAX_ATTEMPTS - row.attempts
            await self._fail(user, "invalid_code")
            raise APIError(
                400, "invalid_code", "That code didn't match", details=[{"attempts_left": left}]
            )
        sub = await self._require_subscription(user.id, lock=True)
        self._assert_eligible(sub)
        await self._claim_address(user, email, now)
        self._activate(row, sub, email, now)
        emit_event(
            self._session,
            user=user,
            event_type="billing.academic.verified",
            payload={"domain": academic_domain(email)},
        )
        await self._session.commit()
        logger.info("academic verified user_id=%s domain=%s", user.id, academic_domain(email))
        await self.apply_monthly_grant(user.id, now)
        return await self.status(user.id, now)

    async def _claim_address(self, user: User, email: str, now: datetime) -> None:
        holder = await self._session.scalar(
            select(AcademicVerification)
            .where(
                AcademicVerification.verified_email == email,
                AcademicVerification.user_id != user.id,
            )
            .with_for_update()
        )
        if holder is None:
            return
        if holder.expires_at is not None and _aware(holder.expires_at) > now:
            await self._fail(user, "email_in_use")
            raise APIError(
                409, "academic_email_in_use", "That address is verified on another account"
            )
        holder.verified_email = None
        await self._session.flush()

    def _activate(
        self, row: AcademicVerification, sub: Subscription, email: str, now: datetime
    ) -> None:
        ends = now + timedelta(days=self._settings.academic_validity_days)
        row.verified_email, row.verified_at, row.expires_at = email, now, ends
        row.expiry_notified_at = None
        row.pending_email = row.code_hash = None
        row.code_expires_at = None
        row.attempts = 0
        sub.plan = PlanType.ACADEMIC
        sub.status = SubscriptionStatus.ACTIVE
        sub.limits = default_limits(PlanType.ACADEMIC)
        sub.expires_at = ends
        # The customer stays (pack purchases); the ended Stripe subscription link does not,
        # so later reads never treat this row as Stripe-backed.
        sub.stripe_subscription_id = None
        sub.billing_interval = None
        sub.current_period_end = None
        sub.cancel_at = None

    async def _fail(self, user: User, reason: str) -> None:
        emit_event(
            self._session,
            user=user,
            event_type="billing.academic.failed",
            payload={"reason": reason},
        )
        await self._session.commit()

    # ---------------------------------------------------------------- credits

    async def apply_monthly_grant(self, user_id: uuid.UUID, now: datetime | None = None) -> bool:
        """Grant this month's academic credits once, after removing last month's unspent
        ones. False when the user is not on a live Academic plan or was already granted."""
        now = now or utcnow()
        sub = await self._subscription(user_id)
        if (
            sub is None
            or sub.plan != PlanType.ACADEMIC
            or sub.status != SubscriptionStatus.ACTIVE
            or is_academic_expired(sub, now)
        ):
            return False
        month = month_key(now)
        if await self._ledger_has(_grant_key(user_id, month)):
            return False
        await self._expire_previous_grant(user_id)
        result = await credits.add_credits(
            self._session,
            user_id,
            self._settings.academic_monthly_credits,
            CreditTxnType.ACADEMIC_GRANT,
            idempotency_key=_grant_key(user_id, month),
            attrs={"reason": "academic_grant", "month": month},
        )
        return result.applied

    async def _expire_previous_grant(self, user_id: uuid.UUID) -> None:
        previous = await self._session.scalar(
            select(CreditLedger)
            .where(
                CreditLedger.user_id == user_id,
                CreditLedger.type == CreditTxnType.ACADEMIC_GRANT,
            )
            .order_by(CreditLedger.created_at.desc())
            .limit(1)
        )
        if previous is None:
            return
        month = str((previous.attrs or {}).get("month", previous.id))
        key = _expire_key(user_id, month)
        if await self._ledger_has(key):
            return
        used = await self._session.scalar(
            select(func.coalesce(func.sum(-CreditLedger.amount), 0)).where(
                CreditLedger.user_id == user_id,
                CreditLedger.type == CreditTxnType.USAGE,
                CreditLedger.created_at >= previous.created_at,
            )
        )
        unused = max(0, previous.amount - int(used or 0))
        if unused == 0:
            return
        await credits.expire_credits(
            self._session,
            user_id,
            unused,
            idempotency_key=key,
            attrs={"reason": "academic_unspent", "month": month},
        )

    # ---------------------------------------------------------------- helpers

    def _hash(self, user_id: uuid.UUID, email: str, code: str) -> str:
        key = self._settings.supabase_jwt_secret.encode()
        return hmac.new(key, f"{user_id}:{email}:{code}".encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _assert_eligible(sub: Subscription) -> None:
        if sub.plan == PlanType.ENTERPRISE:
            raise APIError(409, "plan_not_eligible", "Enterprise plans can't switch to Academic")
        if sub.stripe_subscription_id and sub.status in _BILLING_STATUSES:
            raise APIError(
                409,
                "stripe_subscription_active",
                "Cancel your paid plan in Manage billing first, then verify",
            )

    async def _ledger_has(self, key: str) -> bool:
        found = await self._session.scalar(
            select(CreditLedger.id).where(CreditLedger.idempotency_key == key)
        )
        return found is not None

    async def _row(self, user_id: uuid.UUID) -> AcademicVerification | None:
        row: AcademicVerification | None = await self._session.scalar(
            select(AcademicVerification).where(AcademicVerification.user_id == user_id)
        )
        return row

    async def _locked_row(self, user_id: uuid.UUID) -> AcademicVerification | None:
        row: AcademicVerification | None = await self._session.scalar(
            select(AcademicVerification)
            .where(AcademicVerification.user_id == user_id)
            .with_for_update()
        )
        return row

    async def _ensure_locked_row(self, user_id: uuid.UUID) -> AcademicVerification:
        """The caller's row, created if absent (concurrency-safe), locked for update."""
        await self._session.execute(
            pg_insert(AcademicVerification)
            .values(id=uuid.uuid4(), user_id=user_id, created_at=utcnow(), updated_at=utcnow())
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        row = await self._locked_row(user_id)
        assert row is not None  # guaranteed by the insert above
        return row

    async def _subscription(self, user_id: uuid.UUID, *, lock: bool = False) -> Subscription | None:
        query = select(Subscription).where(
            Subscription.user_id == user_id, Subscription.deleted_at.is_(None)
        )
        sub: Subscription | None = await self._session.scalar(
            query.with_for_update() if lock else query
        )
        return sub

    async def _require_subscription(
        self, user_id: uuid.UUID, *, lock: bool = False
    ) -> Subscription:
        sub = await self._subscription(user_id, lock=lock)
        if sub is None:
            raise APIError(404, "not_found", "No subscription")
        return sub


# ------------------------------------------------------------------ sweep


@dataclass(frozen=True)
class AcademicSweepSummary:
    granted: int
    expired: int


async def sweep_academic(
    session: AsyncSession, settings: Settings, *, now: datetime | None = None
) -> AcademicSweepSummary:
    """Daily: apply this month's grant to every live Academic plan, and record each new
    expiry once (event + notification). Idempotent; safe to run more often."""
    now = now or utcnow()
    service = AcademicPlanService(session, settings)
    live = (
        await session.scalars(
            select(Subscription.user_id).where(
                Subscription.deleted_at.is_(None),
                Subscription.plan == PlanType.ACADEMIC,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at > now,
            )
        )
    ).all()
    granted = 0
    for user_id in live:
        if await service.apply_monthly_grant(user_id, now):
            granted += 1
    expired = await _record_expiries(session, now)
    if granted or expired:
        logger.info("academic sweep granted=%d expired=%d", granted, expired)
    return AcademicSweepSummary(granted=granted, expired=expired)


async def _record_expiries(session: AsyncSession, now: datetime) -> int:
    rows = (
        await session.execute(
            select(AcademicVerification, User)
            .join(Subscription, Subscription.user_id == AcademicVerification.user_id)
            .join(User, User.id == AcademicVerification.user_id)
            .where(
                Subscription.deleted_at.is_(None),
                Subscription.plan == PlanType.ACADEMIC,
                Subscription.expires_at <= now,
                AcademicVerification.verified_email.is_not(None),
                AcademicVerification.expiry_notified_at.is_(None),
            )
            .with_for_update(of=AcademicVerification, skip_locked=True)
        )
    ).all()
    for row, user in rows:
        row.expiry_notified_at = now
        emit_event(session, user=user, event_type="billing.academic.expired", payload={})
        notify_user(
            session,
            user_id=user.id,
            notification_type=NotificationType.SUBSCRIPTION_ENDED,
            title="Academic plan ended",
            body="Verify your academic email again in Billing to keep the free plan.",
            attrs={"plan": PlanType.ACADEMIC.value},
        )
    await session.commit()
    return len(rows)
