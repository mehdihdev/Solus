"""Types of the staff billing operations layer (SOLUSDEV-313).

Errors, result views, the internal outcome/target carriers and the gateway Protocol.
Public names are re-exported from `solus_api.billing.admin_operations` (the import path
SOLUSDEV-314 depends on)."""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from solus_api.billing.stripe_gateway import (
    CancelMode,
    CancelResult,
    CompDuration,
    Proration,
    ScheduleResult,
    SubscriptionSnapshot,
)
from solus_api.models import Subscription, User


# --------------------------------------------------------------------- errors
class AdminOperationError(Exception):
    """Base error: a stable machine `code`, a human `message`, and `context`.

    `retryable` tells the caller whether repeating the SAME call (same audit id) can
    succeed."""

    code = "admin_operation_error"
    retryable = False

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context


class TargetNotFound(AdminOperationError):  # noqa: N818 - name fixed by the SOLUSDEV-314 contract
    code = "target_not_found"


class InvalidOperation(AdminOperationError):  # noqa: N818 - name fixed by the SOLUSDEV-314 contract
    code = "invalid_operation"


class NotCompedError(AdminOperationError):
    code = "not_comped"


class UnsupportedForNonStripe(AdminOperationError):  # noqa: N818 - name fixed by the SOLUSDEV-314 contract
    code = "unsupported_for_non_stripe"


class AdminOperationTimeoutError(AdminOperationError):
    """The whole operation exceeded its time budget; it was rolled back and the row
    lock released. Retry with the SAME audit_action_id (Stripe writes are idempotent)."""

    code = "operation_timeout"
    retryable = True


# -------------------------------------------------------------------- results
@dataclass(frozen=True)
class SubscriptionView:
    """Frozen, JSON-friendly snapshot of one subscription (plain str/int/None values)."""

    plan: str
    effective_plan: str
    status: str
    effective_limits: dict[str, int | None]
    limits_override: dict[str, int | None] | None
    comp_plan: str | None
    comp_expires_at: str | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    cancel_at: str | None
    expires_at: str | None
    stripe_price_id: str | None = None
    stripe_coupon_id: str | None = None
    stripe_schedule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdminOpResult:
    """What 314 records in its audit log. `before`/`after` are Stripe-projected for
    Stripe-backed operations; `noop` means nothing changed (and nothing was emitted)."""

    operation: str
    target_user_id: uuid.UUID
    audit_action_id: str
    before: SubscriptionView
    after: SubscriptionView
    stripe_refs: dict[str, str] = field(default_factory=dict)
    converges_via_webhook: bool = False
    noop: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "target_user_id": str(self.target_user_id),
            "audit_action_id": self.audit_action_id,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "stripe_refs": dict(self.stripe_refs),
            "converges_via_webhook": self.converges_via_webhook,
            "noop": self.noop,
        }


# ------------------------------------------------------------------- internals
@dataclass(frozen=True)
class AuditContext:
    """The validated who/why of one staff action (`reason` never leaves Solus)."""

    actor_staff_user_id: uuid.UUID
    audit_action_id: str
    reason: str

    @property
    def actor(self) -> str:
        return f"staff:{self.actor_staff_user_id}"


@dataclass(frozen=True)
class Outcome:
    """What one operation runner produced (before it is wrapped into an AdminOpResult)."""

    after: SubscriptionView
    refs: Mapping[str, str] = field(default_factory=dict)
    converges: bool = False
    noop: bool = False
    after_commit: Callable[[], Awaitable[None]] | None = None


@dataclass(frozen=True)
class Target:
    """The locked target: its user, live subscription, audit context and `before` view."""

    user: User
    sub: Subscription
    audit: AuditContext
    before: SubscriptionView


class AdminStripeGateway(Protocol):
    """The slice of `StripeGateway` this layer uses (satisfied by the real gateway and
    by `tests/fixtures/stripe_fake.FakeStripeGateway`)."""

    async def retrieve_subscription(self, sub_id: str) -> SubscriptionSnapshot: ...

    async def change_subscription_price(
        self,
        sub_id: str,
        price_id: str,
        *,
        proration: Proration,
        audit_action_id: str,
        actor: str,
        coupon_id: str | None = None,
        extra_metadata: Mapping[str, str] | None = None,
    ) -> SubscriptionSnapshot: ...

    async def ensure_comp_coupon(
        self, duration: CompDuration, months: int | None = None
    ) -> str: ...

    async def remove_comp_coupon(
        self, sub_id: str, audit_action_id: str, actor: str
    ) -> SubscriptionSnapshot: ...

    async def cancel_subscription(
        self,
        sub_id: str,
        *,
        mode: CancelMode,
        invoice_now: bool,
        prorate: bool,
        audit_action_id: str,
        actor: str | None,
    ) -> CancelResult: ...

    async def create_revert_schedule(
        self,
        sub_id: str,
        revert_price_id: str,
        *,
        comp_months: int,
        audit_action_id: str,
        actor: str,
    ) -> ScheduleResult: ...

    async def release_subscription_schedule(
        self, sub_or_schedule_id: str, audit_action_id: str, actor: str
    ) -> ScheduleResult: ...
