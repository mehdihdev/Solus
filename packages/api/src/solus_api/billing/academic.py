"""The Academic plan (ADR-042, SOLUSDEV-319): proof of an academic email, the switch to
the free plan, its monthly credits, and the daily sweep.

Rules (ADR-042):
- An academic address is one whose domain ends in a configured suffix (`.edu`,
  `.ac.uk`, …), with at least one label in front of it.
- A 6-digit code is emailed; only an HMAC of (user, address, code) is stored. Codes
  expire after 15 minutes and allow 5 wrong tries. Sending is limited per user (60 s
  cooldown, 5 per hour), per account and address (3 per hour), and per address (3
  distinct accounts per hour), counted from a send log so the limits hold across API
  processes and one account cannot lock an address's owner out.
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
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits
from solus_api.billing.entitlements import is_academic_expired
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.models import (
    AcademicAddressClaim,
    AcademicCodeSend,
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
# Wrong codes per account per day across every code it asks for, so re-sending cannot
# reset the guess budget (security review H1): about 10 guesses in 10^6 per account-day.
MAX_FAILED_PER_DAY = 10
FAILED_WINDOW = timedelta(days=1)
RESEND_COOLDOWN = timedelta(seconds=60)
SEND_WINDOW = timedelta(hours=1)
SENDS_PER_USER_PER_WINDOW = 5
# Per (account, address) and distinct accounts per address, each per hour.
SENDS_PER_ADDRESS_PER_WINDOW = 3
ACCOUNTS_PER_ADDRESS_PER_WINDOW = 3
SEND_LOG_RETENTION = timedelta(days=1)
# A Stripe subscription in one of these states is still billing: claiming Academic would
# leave the user paying for a plan they no longer have (ADR-042 §6).
_BILLING_STATUSES = frozenset(
    {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE}
)


# ------------------------------------------------------------------ pure rules


# A plain addr-spec after lower-casing: no quotes, spaces, comments, brackets or commas,
# so the address SES delivers to is exactly the one checked here (no parser differential).
_ADDR_SPEC = re.compile(
    r"^[a-z0-9._%+-]{1,64}@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$"
)


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def canonical_email(raw: str) -> str | None:
    """The mailbox an address delivers to, or None when it is not a plain address.

    Lower-cased, and a `+tag` is dropped from the local part, so `ada+1@mit.edu` and
    `ada@mit.edu` are one address for the one-account rule and the per-address send cap.
    The code is sent to this canonical form."""
    email = normalize_email(raw)
    if not _ADDR_SPEC.fullmatch(email):
        return None
    local, domain = email.split("@")
    local = local.split("+", 1)[0]
    if not local or local.startswith(".") or local.endswith(".") or ".." in local:
        return None
    return f"{local}@{domain}"


def academic_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1]


def is_academic_email(raw: str, suffixes: list[str]) -> bool:
    """True when `raw` is one `local@domain` address whose domain ends in a suffix, with at
    least one label before it (so `ada@edu` and `ada@fakeedu` never match)."""
    email = canonical_email(raw)
    if email is None:
        return False
    domain = academic_domain(email)
    return any(domain.endswith("." + s.strip(".").lower()) for s in suffixes if s.strip("."))


def month_key(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m")


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _grant_key(address_hash: str, month: str) -> str:
    return f"academic-grant:{address_hash[:32]}:{month}"


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
        email = canonical_email(raw_email) or ""
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
        self._session.add(AcademicCodeSend(address=email, user_id=user.id, created_at=now))
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
        # Serialize sends to one address across accounts for this transaction, then count
        # real sends in the append-only log (changing a pending address never lowers it).
        await self._session.execute(select(func.pg_advisory_xact_lock(func.hashtext(email))))
        window = (
            AcademicCodeSend.address == email,
            AcademicCodeSend.created_at > now - SEND_WINDOW,
        )
        own = await self._session.scalar(
            select(func.count())
            .select_from(AcademicCodeSend)
            .where(*window, AcademicCodeSend.user_id == row.user_id)
        )
        if (own or 0) >= SENDS_PER_ADDRESS_PER_WINDOW:
            raise _rate_limited(SEND_WINDOW, "Too many codes sent to that address; try later")
        # Other accounts count once each, so one account cannot lock the owner out; an
        # account already sending to this address is not blocked by later arrivals.
        others = await self._session.scalar(
            select(func.count(func.distinct(AcademicCodeSend.user_id))).where(
                *window, AcademicCodeSend.user_id != row.user_id
            )
        )
        if not own and (others or 0) >= ACCOUNTS_PER_ADDRESS_PER_WINDOW:
            raise _rate_limited(SEND_WINDOW, "Too many codes sent to that address; try later")

    # ---------------------------------------------------------------- verify

    async def verify(self, user: User, code: str) -> AcademicRead:
        now = utcnow()
        row = await self._locked_row(user.id)
        if row is None or row.code_hash is None or row.pending_email is None:
            raise APIError(409, "no_pending_code", "Ask for a code first")
        await self._check_code(user, row, code, now)
        email = row.pending_email
        sub = await self._require_subscription(user.id, lock=True)
        self._assert_eligible(sub)
        ends = await self._claim_address(user, email, now)
        self._activate(row, sub, email, now, ends)
        emit_event(
            self._session,
            user=user,
            event_type="billing.academic.verified",
            payload={"domain": academic_domain(email)},
        )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            # A concurrent verify of the same address by another account won the unique
            # index (fail closed); report it like any held address, not as a 500.
            await self._session.rollback()
            raise APIError(
                409, "academic_email_in_use", "That address is verified on another account"
            ) from exc
        logger.info("academic verified user_id=%s domain=%s", user.id, academic_domain(email))
        await self.apply_monthly_grant(user.id, now)
        return await self.status(user.id, now)

    async def _check_code(
        self, user: User, row: AcademicVerification, code: str, now: datetime
    ) -> None:
        """Raise unless `code` matches the live code. Each refusal is recorded at most once
        per code (the code is cleared when it dies), and wrong guesses also count against
        a daily per-account budget that re-sending does not reset."""
        assert row.code_hash is not None and row.pending_email is not None
        if row.failed_window_start is None or now - _aware(row.failed_window_start) >= (
            FAILED_WINDOW
        ):
            row.failed_window_start, row.failed_count = now, 0
        if row.attempts >= MAX_ATTEMPTS or row.failed_count >= MAX_FAILED_PER_DAY:
            row.code_hash = None
            await self._fail(user, "too_many_attempts")
            raise APIError(429, "too_many_attempts", "Too many wrong codes; try again later")
        if row.code_expires_at is None or _aware(row.code_expires_at) <= now:
            row.code_hash = None
            await self._fail(user, "code_expired")
            raise APIError(410, "code_expired", "That code has expired; send a new one")
        expected = self._hash(user.id, row.pending_email, code)
        if not hmac.compare_digest(row.code_hash, expected):
            row.attempts += 1
            row.failed_count += 1
            left = max(0, min(MAX_ATTEMPTS - row.attempts, MAX_FAILED_PER_DAY - row.failed_count))
            await self._fail(user, "invalid_code")
            raise APIError(
                400, "invalid_code", "That code didn't match", details=[{"attempts_left": left}]
            )

    async def _claim_address(self, user: User, email: str, now: datetime) -> datetime:
        """Take `email` for this account and return when its Academic plan ends.

        A live holder (another account still on an unexpired Academic plan) refuses with
        409. A holder that expired or moved to a paid plan is released. The address claim
        outlives account deletion, so deleting and signing up again keeps the original
        end date instead of starting a new year (security review H2)."""
        holder = await self._session.scalar(
            select(AcademicVerification)
            .where(
                AcademicVerification.verified_email == email,
                AcademicVerification.user_id != user.id,
            )
            .with_for_update()
        )
        if holder is not None:
            if await self._holds_live_plan(holder, now):
                await self._fail(user, "email_in_use")
                raise APIError(
                    409, "academic_email_in_use", "That address is verified on another account"
                )
            holder.verified_email = None
            await self._session.flush()
        return await self._upsert_claim(user.id, email, now)

    async def _holds_live_plan(self, holder: AcademicVerification, now: datetime) -> bool:
        if holder.expires_at is None or _aware(holder.expires_at) <= now:
            return False
        sub = await self._subscription(holder.user_id)
        return sub is not None and sub.plan == PlanType.ACADEMIC

    async def _upsert_claim(self, user_id: uuid.UUID, email: str, now: datetime) -> datetime:
        fresh = now + timedelta(days=self._settings.academic_validity_days)
        digest = self._address_hash(email)
        claim = await self._session.scalar(
            select(AcademicAddressClaim)
            .where(AcademicAddressClaim.address_hash == digest)
            .with_for_update()
        )
        if claim is None:
            self._session.add(
                AcademicAddressClaim(address_hash=digest, user_id=user_id, expires_at=fresh)
            )
            return fresh
        inherited = (
            claim.user_id is None
            and claim.expires_at is not None
            and _aware(claim.expires_at) > now
        )
        claim.user_id = user_id
        if not inherited or claim.expires_at is None:
            claim.expires_at = fresh
            return fresh
        return _aware(claim.expires_at)

    def _activate(
        self,
        row: AcademicVerification,
        sub: Subscription,
        email: str,
        now: datetime,
        ends: datetime,
    ) -> None:
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
        row = await self._row(user_id)
        if row is None or row.verified_email is None:
            return False
        month = month_key(now)
        # Keyed on the ADDRESS, whose ledger rows survive account deletion: a new account
        # verifying the same address gets nothing more this month. The per-user check stops
        # a second grant for switching addresses mid-month.
        key = _grant_key(self._address_hash(row.verified_email), month)
        if await self._ledger_has(key) or await self._granted_this_month(user_id, month):
            return False
        await self._expire_previous_grant(user_id)
        result = await credits.add_credits(
            self._session,
            user_id,
            self._settings.academic_monthly_credits,
            CreditTxnType.ACADEMIC_GRANT,
            idempotency_key=key,
            attrs={"reason": "academic_grant", "month": month},
        )
        return result.applied

    async def _granted_this_month(self, user_id: uuid.UUID, month: str) -> bool:
        found = await self._session.scalar(
            select(CreditLedger.id).where(
                CreditLedger.user_id == user_id,
                CreditLedger.type == CreditTxnType.ACADEMIC_GRANT,
                CreditLedger.attrs["month"].astext == month,
            )
        )
        return found is not None

    async def expire_unspent(self, user_id: uuid.UUID) -> None:
        """Remove the latest grant's unspent credits (plan ended; ADR-042: no rollover)."""
        await self._expire_previous_grant(user_id)

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

    def _key(self, label: str) -> bytes:
        """A purpose-bound key derived from the server secret (domain separation)."""
        secret = self._settings.supabase_jwt_secret.encode()
        return hmac.new(secret, f"solus-academic:{label}".encode(), hashlib.sha256).digest()

    def _hash(self, user_id: uuid.UUID, email: str, code: str) -> str:
        message = f"{user_id}:{email}:{code}".encode()
        return hmac.new(self._key("code"), message, hashlib.sha256).hexdigest()

    def _address_hash(self, email: str) -> str:
        return hmac.new(self._key("address"), email.encode(), hashlib.sha256).hexdigest()

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
    ended = await _record_expiries(session, now)
    for user_id in ended:
        await service.expire_unspent(user_id)
    expired = len(ended)
    await session.execute(
        delete(AcademicCodeSend).where(AcademicCodeSend.created_at < now - SEND_LOG_RETENTION)
    )
    await session.commit()
    if granted or expired:
        logger.info("academic sweep granted=%d expired=%d", granted, expired)
    return AcademicSweepSummary(granted=granted, expired=expired)


async def _record_expiries(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
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
    ended: list[uuid.UUID] = []
    for row, user in rows:
        ended.append(user.id)
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
    return ended
