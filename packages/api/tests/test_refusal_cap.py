"""Model refusals are throttled, logged and — when text already reached the person — billed
(SOLUSDEV-319, approved in-chat 2026-11-09: "Throttle + log event").

A refused call costs Solus the prompt it was sent, so repeated refusals are a free way to burn
provider spend. Each refusal is recorded in a per-user sliding window; at the limit the next
call is refused pre-flight (a transient 429, like the frequency cap). Every refusal emits a
consent-gated `model.refused` data event. A refusal that streamed text first is debited for the
tokens the provider reported; one that delivered nothing stays free.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import (
    CreditLedger,
    DataEvent,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
)
from solus_api.orchestration import gates, gateway
from solus_api.orchestration.config import LimitsConfig
from solus_api.orchestration.gates import (
    FrequencyCapExceededError,
    check_refusal_cap,
    record_refusal,
)
from solus_api.orchestration.gateway import complete
from solus_api.orchestration.providers import (
    ImageBlock,
    ProviderRefusalError,
    ToolConversation,
    ToolUse,
    Usage,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_gates import FakeRedis
from test_gateway import _config

_LIMITS = LimitsConfig(max_refusals_per_window=2, refusal_window_seconds=600)
_REFUSED_USAGE = Usage(tokens_in=40, tokens_out=3)


@pytest.fixture(autouse=True)
def _fresh_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gates, "_local_window", gates._LocalFrequencyWindow())
    monkeypatch.setattr(gates, "_local_refusals", gates._LocalFrequencyWindow())
    monkeypatch.setattr(gates, "_warned_causes", set())


# --- the window -------------------------------------------------------------------------------


@pytest.mark.parametrize("redis", [FakeRedis(), None], ids=["redis", "local"])
async def test_the_refusal_cap_blocks_at_the_limit_and_recovers_after_the_window(
    redis: FakeRedis | None,
) -> None:
    user_id = uuid.uuid4()
    await check_refusal_cap(user_id, redis=redis, limits=_LIMITS, now=1_000.0)  # nothing yet
    for at in (1_000.0, 1_010.0):
        await record_refusal(user_id, redis=redis, limits=_LIMITS, now=at)

    with pytest.raises(FrequencyCapExceededError) as raised:
        await check_refusal_cap(user_id, redis=redis, limits=_LIMITS, now=1_020.0)

    assert raised.value.retry_after_seconds == 580  # until the oldest refusal leaves the window
    await check_refusal_cap(user_id, redis=redis, limits=_LIMITS, now=1_601.0)


async def test_checking_the_refusal_cap_never_counts_as_a_refusal() -> None:
    redis, user_id = FakeRedis(), uuid.uuid4()
    for _ in range(5):
        await check_refusal_cap(user_id, redis=redis, limits=_LIMITS, now=1_000.0)
    assert await redis.zcard(f"solus:refusals:{user_id}") == 0


async def test_refusals_are_counted_apart_from_ordinary_calls() -> None:
    redis, user_id = FakeRedis(), uuid.uuid4()
    for at in (1_000.0, 1_001.0):
        await record_refusal(user_id, redis=redis, limits=_LIMITS, now=at)
    # The frequency cap's own window is untouched by refusals.
    assert await redis.zcard(f"solus:freqcap:{user_id}") == 0
    assert await redis.zcard(f"solus:refusals:{user_id}") == 2


async def test_a_broken_redis_still_holds_the_refusal_cap_on_the_local_window() -> None:
    class BrokenRedis(FakeRedis):
        async def zcard(self, key: str) -> int:
            raise ConnectionError("redis down")

        async def zadd(self, key: str, mapping: dict[str, float]) -> int:
            raise ConnectionError("redis down")

    user_id, broken = uuid.uuid4(), BrokenRedis()
    for at in (1_000.0, 1_001.0):
        await record_refusal(user_id, redis=broken, limits=_LIMITS, now=at)
    with pytest.raises(FrequencyCapExceededError):
        await check_refusal_cap(user_id, redis=broken, limits=_LIMITS, now=1_002.0)


async def test_a_refusal_admitted_by_redis_is_mirrored_locally() -> None:
    """An outage starting mid-window still remembers the refusals Redis saw."""
    redis, user_id = FakeRedis(), uuid.uuid4()
    for at in (1_000.0, 1_001.0):
        await record_refusal(user_id, redis=redis, limits=_LIMITS, now=at)
    with pytest.raises(FrequencyCapExceededError):
        await check_refusal_cap(user_id, redis=None, limits=_LIMITS, now=1_002.0)


# --- the gateway ------------------------------------------------------------------------------


class _RefusingAdapter:
    def __init__(self, *, stream_first: bool = False) -> None:
        self.stream_first = stream_first
        self.calls = 0

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        self.calls += 1
        if self.stream_first:
            yield "Partial "
        raise ProviderRefusalError(
            f"anthropic/{model_name} refused the request", category="cyber", usage=_REFUSED_USAGE
        )


async def _user(db: AsyncSession, *, consent: bool = True) -> uuid.UUID:
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com", data_collection_consent=consent
    )
    db.add(user)
    await db.flush()
    db.add(Subscription(user_id=user.id, plan=PlanType.BASIC, status=SubscriptionStatus.TRIALING))
    await db.commit()
    return user.id


async def _refuse(
    db: AsyncSession, user_id: uuid.UUID, adapter: _RefusingAdapter, redis: Any = None
) -> None:
    config = _config("anthropic").model_copy(update={"limits": _LIMITS})
    with pytest.raises(ProviderRefusalError):
        await complete(
            "hi",
            secret_store=InMemorySecretStore(),
            config=config,
            adapters={"anthropic": adapter},
            user_id=user_id,
            session=db,
            redis=redis,
        )


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[CreditLedger]:
    return list(await db.scalars(select(CreditLedger).where(CreditLedger.user_id == user_id)))


async def _events(db: AsyncSession, user_id: uuid.UUID, event_type: str) -> list[DataEvent]:
    rows = await db.scalars(
        select(DataEvent).where(DataEvent.user_id == user_id, DataEvent.event_type == event_type)
    )
    return list(rows)


async def test_a_refusal_that_delivered_nothing_is_free_and_logged(db: AsyncSession) -> None:
    user_id = await _user(db)

    await _refuse(db, user_id, _RefusingAdapter())

    assert await _ledger(db, user_id) == []
    [event] = await _events(db, user_id, "model.refused")
    assert event.payload == {
        "provider": "anthropic",
        "model": "test-model",
        "role": "only_role",
        "category": "cyber",
        "purpose": "answer",
        "streamed": False,
        "debited": False,
        "tokens_in": 40,
        "tokens_out": 3,
    }


async def test_a_refusal_after_streamed_text_is_debited_for_the_reported_tokens(
    db: AsyncSession,
) -> None:
    user_id = await _user(db)

    await _refuse(db, user_id, _RefusingAdapter(stream_first=True))

    [row] = await _ledger(db, user_id)
    assert row.amount < 0
    assert row.attrs["tokens_in"] == 40 and row.attrs["tokens_out"] == 3
    [event] = await _events(db, user_id, "model.refused")
    assert event.payload["streamed"] is True and event.payload["debited"] is True


async def test_the_refused_event_respects_consent(db: AsyncSession) -> None:
    user_id = await _user(db, consent=False)
    await _refuse(db, user_id, _RefusingAdapter())
    assert await _events(db, user_id, "model.refused") == []


async def test_repeated_refusals_block_the_next_call_before_the_provider(
    db: AsyncSession,
) -> None:
    user_id, redis = await _user(db), FakeRedis()
    for _ in range(2):
        await _refuse(db, user_id, _RefusingAdapter(), redis)
    blocked = _RefusingAdapter()

    with pytest.raises(FrequencyCapExceededError):
        await complete(
            "hi",
            secret_store=InMemorySecretStore(),
            config=_config("anthropic").model_copy(update={"limits": _LIMITS}),
            adapters={"anthropic": blocked},
            user_id=user_id,
            session=db,
            redis=redis,
        )

    assert blocked.calls == 0
    [block] = await _events(db, user_id, "orchestration.blocked")
    assert block.payload["reason"] == "refusal_cap"


async def test_identityless_refusals_are_neither_recorded_nor_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exploding(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not run without identity")

    monkeypatch.setattr(gateway, "record_refusal", exploding)
    monkeypatch.setattr(gateway, "check_refusal_cap", exploding)
    with pytest.raises(ProviderRefusalError):
        await complete(
            "hi",
            secret_store=InMemorySecretStore(),
            config=_config("anthropic"),
            adapters={"anthropic": _RefusingAdapter()},
        )


# --- review fixes: accounting never masks the refusal ------------------------------------------


async def test_a_failing_debit_still_surfaces_the_refusal(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_pricing(*args: object, **kwargs: object) -> None:
        raise KeyError("no catalog entry for the role")

    monkeypatch.setattr(gateway, "_fire_cost_hook", broken_pricing)
    user_id = await _user(db)

    await _refuse(db, user_id, _RefusingAdapter(stream_first=True))  # raises ProviderRefusalError


async def test_a_failed_event_commit_leaves_the_session_usable(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.orchestration import gates as gates_module

    user_id = await _user(db)

    def failing_emit(session: AsyncSession, **kwargs: Any) -> None:
        session.add(User(supabase_user_id=None, email=None))  # violates NOT NULL at commit

    monkeypatch.setattr(gates_module, "emit_event", failing_emit)

    await _refuse(db, user_id, _RefusingAdapter())

    assert await db.get(User, user_id) is not None  # no PendingRollbackError
