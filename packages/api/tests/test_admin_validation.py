"""Pure validation helpers of the staff billing operations (SOLUSDEV-313)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from solus_api.billing.admin_types import AuditContext, InvalidOperation
from solus_api.billing.admin_validation import (
    COMP_RETRY_TOLERANCE,
    KNOWN_LIMIT_KEYS,
    MAX_LIMIT_OVERRIDE,
    MAX_REASON_LEN,
    VALID_DURATIONS,
    VALID_PRORATIONS,
    add_months,
    check_bools,
    check_comp_terms,
    check_interval,
    check_override,
    check_plan,
    check_proration,
    same_expiry,
    validate_audit,
)
from solus_api.billing.stripe_gateway import CompDuration, Proration
from solus_api.models import PlanType

ACTOR = uuid.UUID("00000000-0000-0000-0000-0000000000cc")


def test_vocabularies_are_derived_from_the_gateway_literals() -> None:
    assert VALID_PRORATIONS == get_args(Proration)
    assert VALID_DURATIONS == get_args(CompDuration)


def test_known_limit_keys_cover_the_enforced_keys() -> None:
    assert {"max_integrations", "max_projects", "max_teams", "byo_paid_tools"} <= KNOWN_LIMIT_KEYS


def test_validate_audit_accepts_and_builds_the_actor_string() -> None:
    audit = validate_audit(ACTOR, "audit:1.x_y-z", "because")
    assert isinstance(audit, AuditContext)
    assert audit.actor == f"staff:{ACTOR}"


@pytest.mark.parametrize(
    ("actor", "audit_id", "reason"),
    [
        ("nope", "a1", "r"),
        (ACTOR, "", "r"),
        (ACTOR, "x" * 65, "r"),
        (ACTOR, "has space", "r"),
        (ACTOR, "a@b", "r"),
        (ACTOR, 5, "r"),
        (ACTOR, "a1", ""),
        (ACTOR, "a1", "  "),
        (ACTOR, "a1", 5),
        (ACTOR, "a1", "x" * (MAX_REASON_LEN + 1)),
    ],
)
def test_validate_audit_rejects(actor: Any, audit_id: Any, reason: Any) -> None:
    with pytest.raises(InvalidOperation):
        validate_audit(actor, audit_id, reason)


def test_check_proration_and_plan_and_interval() -> None:
    assert check_proration("none") == "none"
    with pytest.raises(InvalidOperation):
        check_proration("sometimes")
    assert check_plan(PlanType.PRO) is PlanType.PRO
    with pytest.raises(InvalidOperation):
        check_plan("pro")
    assert check_interval(None, required=False) is None
    assert check_interval("year", required=True) == "year"
    for bad in (None, "week"):
        with pytest.raises(InvalidOperation):
            check_interval(bad, required=True)


@pytest.mark.parametrize(
    ("duration", "months", "expected"),
    [
        ("once", None, ("once", None)),
        ("forever", None, ("forever", None)),
        ("repeating", 1, ("repeating", 1)),
        ("repeating", 36, ("repeating", 36)),
    ],
)
def test_check_comp_terms_accepts(duration: Any, months: Any, expected: Any) -> None:
    assert check_comp_terms(duration, months) == expected


@pytest.mark.parametrize(
    ("duration", "months"),
    [
        ("repeating", None),
        ("repeating", 0),
        ("repeating", 37),
        ("repeating", True),
        ("repeating", "3"),
        ("once", 2),
        ("forever", 1),
        ("weekly", None),
        (None, None),
    ],
)
def test_check_comp_terms_rejects(duration: Any, months: Any) -> None:
    with pytest.raises(InvalidOperation):
        check_comp_terms(duration, months)


def test_check_override_bounds() -> None:
    assert check_override(None) is None
    top = {"max_projects": MAX_LIMIT_OVERRIDE, "max_teams": 0, "max_integrations": None}
    assert check_override(top) == top
    bad_inputs: list[Any] = [
        {},
        [],
        {"nope": 1},
        {"max_teams": -1},
        {"max_teams": MAX_LIMIT_OVERRIDE + 1},
    ]
    for bad in bad_inputs:
        with pytest.raises(InvalidOperation):
            check_override(bad)


def test_check_bools() -> None:
    check_bools(a=True, b=False)
    with pytest.raises(InvalidOperation, match="a, b"):
        check_bools(a=True, b="no")


def test_add_months_is_calendar_correct() -> None:
    jan31 = datetime(2026, 1, 31, 12, tzinfo=UTC)
    assert add_months(jan31, 1) == datetime(2026, 2, 28, 12, tzinfo=UTC)
    assert add_months(jan31, 13) == datetime(2027, 2, 28, 12, tzinfo=UTC)
    assert add_months(datetime(2028, 1, 31, tzinfo=UTC), 1).day == 29
    assert add_months(datetime(2026, 12, 15, tzinfo=UTC), 1) == datetime(2027, 1, 15, tzinfo=UTC)


def test_same_expiry() -> None:
    base = datetime(2026, 3, 1, tzinfo=UTC)
    assert same_expiry(None, None)
    assert not same_expiry(None, base) and not same_expiry(base, None)
    assert same_expiry(base, base + COMP_RETRY_TOLERANCE)
    assert not same_expiry(base, base + COMP_RETRY_TOLERANCE + timedelta(seconds=1))
    assert same_expiry(base.replace(tzinfo=None), base)  # naive stored value is read as UTC
