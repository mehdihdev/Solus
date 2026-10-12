"""Boundary validation + pure helpers for staff billing operations (SOLUSDEV-313).

Everything here raises `InvalidOperation` (never the gateway's bare `ValueError`) and
derives its vocabularies from the gateway's own Literals/regexes so the two layers
cannot drift apart."""

import calendar
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TypeGuard, get_args

from solus_api.billing.admin_types import AuditContext, InvalidOperation
from solus_api.billing.plans import VALID_INTERVALS
from solus_api.billing.stripe_gateway import (
    _AUDIT_TOKEN_RE,
    CompDuration,
    Proration,
    _check_months,
)
from solus_api.models import PLAN_LIMITS, PlanType

VALID_PRORATIONS: tuple[str, ...] = get_args(Proration)
VALID_DURATIONS: tuple[str, ...] = get_args(CompDuration)
MAX_REASON_LEN = 2000
# Every key any plan defines (all four enforced keys live in the BASIC defaults).
KNOWN_LIMIT_KEYS = frozenset(k for limits in PLAN_LIMITS.values() for k in limits)
# Staff overrides are bounded: a typo (or a hostile value) must not become "unlimited".
# `None` is the only way to express unlimited.
MAX_LIMIT_OVERRIDE = 1_000_000
# A same-plan comp whose expiry differs by less than this is a retry, not a change.
COMP_RETRY_TOLERANCE = timedelta(hours=1)


def validate_audit(actor: object, audit_action_id: object, reason: object) -> AuditContext:
    """Validate the who/why of an action. `audit_action_id` doubles as the Stripe
    idempotency token, so it must satisfy the gateway's own token rule."""
    if not isinstance(actor, uuid.UUID):
        raise InvalidOperation("actor_staff_user_id must be a UUID")
    if not isinstance(audit_action_id, str) or not _AUDIT_TOKEN_RE.fullmatch(audit_action_id):
        raise InvalidOperation("audit_action_id must match [A-Za-z0-9_.:-]{1,64}")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LEN:
        raise InvalidOperation(f"reason must be 1..{MAX_REASON_LEN} characters")
    return AuditContext(actor, audit_action_id, reason)


def _is_proration(value: object) -> TypeGuard[Proration]:
    return value in VALID_PRORATIONS


def _is_duration(value: object) -> TypeGuard[CompDuration]:
    return value in VALID_DURATIONS


def check_proration(proration: object) -> Proration:
    if not _is_proration(proration):
        raise InvalidOperation("proration must be one of " + ", ".join(VALID_PRORATIONS))
    return proration


def check_interval(interval: object, *, required: bool) -> str | None:
    if interval is None and not required:
        return None
    if interval not in VALID_INTERVALS:
        raise InvalidOperation("interval must be 'month' or 'year' for a Stripe subscription")
    return str(interval)


def check_plan(plan: object) -> PlanType:
    if not isinstance(plan, PlanType):
        raise InvalidOperation("plan must be a PlanType")
    return plan


def check_comp_terms(duration: object, months: object) -> tuple[CompDuration, int | None]:
    if not _is_duration(duration):
        raise InvalidOperation("duration must be 'once', 'repeating' or 'forever'")
    if duration == "repeating":
        try:
            return duration, _check_months(months)
        except ValueError as exc:
            raise InvalidOperation(f"{exc} when repeating") from exc
    if months is not None:
        raise InvalidOperation("months is only valid with duration='repeating'")
    return duration, None


def check_override(limits: object) -> dict[str, int | None] | None:
    if limits is None:
        return None
    if not isinstance(limits, Mapping) or not limits:
        raise InvalidOperation("limits must be a non-empty mapping (use None to clear)")
    clean: dict[str, int | None] = {}
    for key, value in limits.items():
        if key not in KNOWN_LIMIT_KEYS:
            raise InvalidOperation(f"unknown limit key {key!r}", known=sorted(KNOWN_LIMIT_KEYS))
        if value is not None and (type(value) is not int or not 0 <= value <= MAX_LIMIT_OVERRIDE):
            raise InvalidOperation(
                f"limit {key!r} must be an int in 0..{MAX_LIMIT_OVERRIDE} or None (unlimited)"
            )
        clean[key] = value
    return clean


def check_bools(**flags: object) -> None:
    if not all(isinstance(v, bool) for v in flags.values()):
        raise InvalidOperation(", ".join(flags) + " must be bool")


def add_months(moment: datetime, months: int) -> datetime:
    """Calendar-correct month arithmetic (Jan 31 + 1 month = Feb 28/29)."""
    index = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(index, 12)
    day = min(moment.day, calendar.monthrange(year, month + 1)[1])
    return moment.replace(year=year, month=month + 1, day=day)


def same_expiry(existing: datetime | None, requested: datetime | None) -> bool:
    """Whether a requested comp expiry is the existing one (within the retry tolerance)."""
    if existing is None or requested is None:
        return existing is None and requested is None
    if existing.tzinfo is None:
        existing = existing.replace(tzinfo=UTC)
    return abs(requested - existing) <= COMP_RETRY_TOLERANCE
