"""Gateway chokepoint: complete()/stream(), cost-hook seam, switchability (MO-01)."""

import logging
import uuid
from collections.abc import AsyncIterator, Sequence

import pytest
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import (
    CreditLedger,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
)
from solus_api.orchestration import gateway
from solus_api.orchestration.config import (
    CostConfig,
    LimitsConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
    load_orchestration_config,
)
from solus_api.orchestration.cost import compute_call_credits
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.gates import FrequencyCapExceededError, TrialCapReachedError
from solus_api.orchestration.gateway import complete, stream
from solus_api.orchestration.providers import (
    ImageBlock,
    ProviderCredentialsMissingError,
    ProviderError,
    ProviderTransientError,
    ToolConversation,
    ToolUse,
    UnknownProviderError,
    Usage,
    build_adapter_registry,
)
from solus_api.orchestration.resolution import (
    ContextWindowExceededError,
    OverrideNotViableError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_DEFAULT_USAGE = Usage(tokens_in=3, tokens_out=5)


@pytest.fixture
def no_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the MO-03 pre-flight gates for tests that unit-test other
    seams with sentinel sessions (the gates get real-DB tests of their own)."""

    async def _pass(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(gateway, "check_frequency_cap", _pass)
    monkeypatch.setattr(gateway, "assert_can_spend", _pass)


class MockAdapter:
    """Implements the ProviderAdapter protocol without any network layer."""

    def __init__(
        self,
        chunks: tuple[str, ...] = ("hel", "lo"),
        usage: Usage = _DEFAULT_USAGE,
        fail_after: int | None = None,
        omit_usage: bool = False,
    ) -> None:
        self.chunks = chunks
        self.usage = usage
        self.fail_after = fail_after
        self.omit_usage = omit_usage
        self.calls: list[str] = []
        self.images_seen: list[Sequence[ImageBlock] | None] = []

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
        self.calls.append(model_name)
        self.images_seen.append(images)
        for i, chunk in enumerate(self.chunks):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("provider blew up mid-stream")
            yield chunk
        if not self.omit_usage:
            yield self.usage


def _config(provider: str) -> OrchestrationConfig:
    """A config whose single role is filled by `provider` — switching the
    provider is a config edit, exactly like editing models.yaml."""
    return OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider=provider,
                name="test-model",
                price_in=1.0,
                price_out=2.0,
                context_window=100_000,
                roles=["only_role"],
            )
        ],
        matrix={},
        default_role="only_role",
        cost=CostConfig(credits_per_dollar=100.0),
    )


def _store() -> InMemorySecretStore:
    return InMemorySecretStore()  # empty: the whole suite runs keyless


async def test_complete_happy_path() -> None:
    mock = MockAdapter()
    result = await complete(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": mock},
    )
    assert result.text == "hello"
    assert result.tokens_in == 3
    assert result.tokens_out == 5
    assert result.model.model_name == "test-model"
    uuid.UUID(result.call_id)  # parseable → real per-call id
    assert mock.calls == ["test-model"]  # model name came from config, not code


async def test_default_config_path_uses_shipped_yaml_and_loads_it_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With config omitted, the gateway routes via the shipped models.yaml and
    caches the loaded config process-wide (no disk read per call)."""
    loads: list[int] = []

    def counting_load() -> OrchestrationConfig:
        loads.append(1)
        return load_orchestration_config()

    monkeypatch.setattr(gateway, "load_orchestration_config", counting_load)
    monkeypatch.setattr(gateway, "_default_config", None)
    mock = MockAdapter()
    # Explicit tier: this test is about config caching, not tier resolution.
    first = await complete(
        "hi",
        secret_store=_store(),
        complexity=Complexity.STANDARD,
        adapters={"openai": mock},
    )
    second = await complete(
        "hi",
        secret_store=_store(),
        complexity=Complexity.STANDARD,
        adapters={"openai": mock},
    )
    # STANDARD × GENERAL under the shipped yaml → openai_standard on openai
    # (SOLUSDEV-252 matrix: the GPT-5.6 ladder serves general questions).
    assert first.model.role == "openai_standard"
    assert first.model.provider == "openai"
    assert second.model == first.model
    assert len(loads) == 1


async def test_no_complexity_no_context_uses_query_estimator() -> None:
    """Resolution order, last rung (MO-02): with neither an explicit tier nor a
    context, the query-based estimator picks the tier. `_config()` carries the
    default EstimatorConfig (no keywords), so length is the only signal."""
    short = await complete(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    assert short.model.complexity is Complexity.TRIVIAL
    longer = await complete(
        " ".join(["word"] * 13),  # > trivial_max_words -> estimator says STANDARD
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    assert longer.model.complexity is Complexity.STANDARD


async def test_context_beats_query_estimator() -> None:
    """Middle rung: a supplied InteractionContext resolves via derive_complexity —
    the estimator (which would call 'hi' TRIVIAL) must not run."""
    result = await complete(
        "hi",
        secret_store=_store(),
        context=InteractionContext.SOL_OPEN_QUESTION,  # context default: HARD
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    assert result.model.complexity is Complexity.HARD


async def test_explicit_complexity_beats_context_and_query() -> None:
    """Top rung: an explicit complexity wins over both the context (TRIVIAL here)
    and the query text."""
    result = await complete(
        "hi",
        secret_store=_store(),
        complexity=Complexity.HARD,
        context=InteractionContext.CODE_AUTOCOMPLETE,  # context default: TRIVIAL
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    assert result.model.complexity is Complexity.HARD


async def test_type_is_forwarded_to_route() -> None:
    result = await complete(
        "hi",
        secret_store=_store(),
        type=RouteType.CODE,
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    assert result.model.route_type is RouteType.CODE


@pytest.mark.parametrize("provider", ["anthropic", "openai", "google"])
async def test_provider_switchability_is_config_only(provider: str) -> None:
    """Changing which provider fills the role (a config edit) changes which
    adapter is dispatched — zero code change."""
    mocks = {name: MockAdapter() for name in ("anthropic", "openai", "google")}
    await complete(
        "hi",
        secret_store=_store(),
        config=_config(provider),
        adapters=dict(mocks),
    )
    assert mocks[provider].calls == ["test-model"]
    for other, mock in mocks.items():
        if other != provider:
            assert mock.calls == []


async def test_stream_yields_chunks_and_exposes_final_usage() -> None:
    s = stream(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    before = s.completion
    assert before is None  # not finished yet
    chunks = [chunk async for chunk in s]
    assert chunks == ["hel", "lo"]
    completion = s.completion
    assert completion is not None
    assert completion.text == "hello"
    assert completion.tokens_in == 3
    assert completion.tokens_out == 5


async def test_cost_hook_called_after_complete(
    monkeypatch: pytest.MonkeyPatch, no_gates: None
) -> None:
    recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def recording_track_cost(*args: object, **kwargs: object) -> None:
        recorded.append((args, kwargs))

    monkeypatch.setattr(gateway, "track_cost", recording_track_cost)
    user_id = uuid.uuid4()
    session = object()
    result = await complete(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
        user_id=user_id,
        session=session,  # type: ignore[arg-type]
    )
    assert len(recorded) == 1
    args, kwargs = recorded[0]
    call_id, hooked_user, model, tokens_in, tokens_out = args
    assert call_id == result.call_id
    assert hooked_user == user_id
    assert model == result.model
    assert (tokens_in, tokens_out) == (3, 5)
    assert kwargs["session"] is session
    assert kwargs["cost"] == _config("anthropic").cost
    # MO-02b: the routed catalog entry rides along so MO-03's debit can bill
    # breakpoint (long-context) pricing without touching route()/ModelChoice.
    assert kwargs["entry"] == _config("anthropic").entry_for_role(result.model.role)


async def test_cost_hook_fires_only_after_stream_close(
    monkeypatch: pytest.MonkeyPatch, no_gates: None
) -> None:
    recorded: list[str] = []

    async def recording_track_cost(call_id: str, *args: object, **kwargs: object) -> None:
        recorded.append(call_id)

    monkeypatch.setattr(gateway, "track_cost", recording_track_cost)
    s = stream(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
        user_id=uuid.uuid4(),
        session=object(),  # type: ignore[arg-type]
    )
    it = aiter(s)
    await anext(it)  # first chunk consumed, stream still open
    assert recorded == []
    async for _ in it:
        pass
    assert len(recorded) == 1
    assert s.completion is not None


async def test_cost_hook_failure_never_breaks_a_served_completion(no_gates: None) -> None:
    """The locked policy: the REAL track_cost hits a sentinel session, fails
    internally, defers to reconciliation — and never touches the served result."""
    result = await complete(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
        user_id=uuid.uuid4(),
        session=object(),  # type: ignore[arg-type]
    )
    assert result.text == "hello"


async def test_cost_hook_skipped_without_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []

    async def recording_track_cost(call_id: str, *args: object, **kwargs: object) -> None:
        recorded.append(call_id)

    monkeypatch.setattr(gateway, "track_cost", recording_track_cost)
    await complete(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    assert recorded == []


async def test_abandoned_stream_skips_hook_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, no_gates: None
) -> None:
    recorded: list[str] = []

    async def recording_track_cost(call_id: str, *args: object, **kwargs: object) -> None:
        recorded.append(call_id)

    monkeypatch.setattr(gateway, "track_cost", recording_track_cost)
    s = stream(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
        user_id=uuid.uuid4(),
        session=object(),  # type: ignore[arg-type]
    )
    with caplog.at_level(logging.WARNING, logger="solus.orchestration.gateway"):
        await anext(aiter(s))  # consume one chunk...
        await s.aclose()  # ...then walk away
    assert recorded == []
    assert s.completion is None
    assert any("abandoned" in record.message for record in caplog.records)


async def test_unknown_provider_raises() -> None:
    with pytest.raises(UnknownProviderError):
        await complete(
            "hi",
            secret_store=_store(),
            config=_config("mystery"),
            adapters={"anthropic": MockAdapter()},
        )


async def test_stanza_only_provider_has_no_adapter_until_one_is_registered() -> None:
    """SOLUSDEV-252: `azure` is a config stanza (models.yaml `providers:`) with
    NO adapter. Routing to it must fail loudly, naming the missing adapter —
    production wiring = fill the stanza + register one adapter here."""
    with pytest.raises(UnknownProviderError, match="'azure'"):
        await complete(
            "hi",
            secret_store=_store(),
            config=_config("azure"),
            adapters=build_adapter_registry(_store()),
        )


async def test_mid_stream_provider_failure_wraps_and_skips_hook(
    monkeypatch: pytest.MonkeyPatch, no_gates: None
) -> None:
    recorded: list[str] = []

    async def recording_track_cost(call_id: str, *args: object, **kwargs: object) -> None:
        recorded.append(call_id)

    monkeypatch.setattr(gateway, "track_cost", recording_track_cost)
    with pytest.raises(ProviderError):
        await complete(
            "hi",
            secret_store=_store(),
            config=_config("anthropic"),
            adapters={"anthropic": MockAdapter(fail_after=1)},
            user_id=uuid.uuid4(),
            session=object(),  # type: ignore[arg-type]
        )
    assert recorded == []


async def test_missing_key_error_propagates_unwrapped_through_gateway() -> None:
    """The chokepoint surfaces the actionable no-key error itself — it must not
    be swallowed or re-wrapped as a generic ProviderError."""
    empty = InMemorySecretStore()
    with pytest.raises(ProviderCredentialsMissingError):
        await complete(
            "hi",
            secret_store=empty,
            config=_config("anthropic"),
            adapters=build_adapter_registry(empty),
        )


async def test_adapter_ending_without_usage_is_a_provider_error() -> None:
    with pytest.raises(ProviderError):
        await complete(
            "hi",
            secret_store=_store(),
            config=_config("anthropic"),
            adapters={"anthropic": MockAdapter(omit_usage=True)},
        )


# --- MO-04: window guard at the gateway (defense in depth) ---------------------


def _tiered_window_config() -> OrchestrationConfig:
    """trivial=1K window, standard=100K, hard=1M — same for every route type."""

    def row(role: str) -> dict[RouteType, str]:
        return {t: role for t in RouteType}

    return OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider="anthropic",
                name="tiny-model",
                price_in=1.0,
                price_out=2.0,
                context_window=1_000,
                roles=["r_trivial"],
            ),
            ModelCatalogEntry(
                provider="anthropic",
                name="mid-model",
                price_in=3.0,
                price_out=6.0,
                context_window=100_000,
                roles=["r_standard"],
            ),
            ModelCatalogEntry(
                provider="anthropic",
                name="big-model",
                price_in=5.0,
                price_out=10.0,
                context_window=1_000_000,
                roles=["r_hard"],
            ),
        ],
        matrix={
            Complexity.TRIVIAL: row("r_trivial"),
            Complexity.STANDARD: row("r_standard"),
            Complexity.HARD: row("r_hard"),
        },
        default_role="r_standard",
        cost=CostConfig(credits_per_dollar=100.0),
    )


async def test_user_override_that_cannot_fit_is_refused_never_escalated() -> None:
    """A hostile/naive client sends an explicit tier the request can't fit:
    the gateway refuses with the short reason — the adapter is NEVER called and
    the override is never silently upgraded."""
    mock = MockAdapter()
    with pytest.raises(OverrideNotViableError) as excinfo:
        await complete(
            "x" * 8_000,  # ~2K tokens > tiny-model's 1K
            secret_store=_store(),
            complexity=Complexity.TRIVIAL,
            config=_tiered_window_config(),
            adapters={"anthropic": mock},
        )
    assert "Too many tokens for this tier (2K > 1K)" in str(excinfo.value)
    assert mock.calls == []


async def test_system_routed_misfit_escalates_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No override = the miss is the system's fault: escalate to a fitting
    model in the same family instead of erroring at the user."""
    mock = MockAdapter()
    with caplog.at_level(logging.INFO, logger="solus.orchestration.gateway"):
        result = await complete(
            "x" * 8_000,  # ~2K tokens; estimator routes trivial-ish? force via context
            secret_store=_store(),
            context=InteractionContext.CODE_AUTOCOMPLETE,  # system-derived trivial
            config=_tiered_window_config(),
            adapters={"anthropic": mock},
        )
    assert result.model.model_name == "mid-model"
    assert mock.calls == ["mid-model"]
    assert any("window escalation" in record.message for record in caplog.records)


async def test_nothing_fits_raises_clear_window_error() -> None:
    mock = MockAdapter()
    with pytest.raises(ContextWindowExceededError) as excinfo:
        await complete(
            "x" * 8_000_000,  # ~2M tokens > every window
            secret_store=_store(),
            context=InteractionContext.CODE_AUTOCOMPLETE,
            config=_tiered_window_config(),
            adapters={"anthropic": mock},
        )
    assert "exceeds every available model" in str(excinfo.value)
    assert mock.calls == []


async def test_override_changes_the_routed_model_and_bills_it(db: AsyncSession) -> None:
    """MO-04 Part C: an overridden tier routes AND debits at the overridden
    model's price — never the originally-routed one."""
    tag = uuid.uuid4().hex[:10]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    db.add(user)
    await db.flush()
    db.add(Subscription(user_id=user.id, plan=PlanType.BASIC, status=SubscriptionStatus.TRIALING))
    await db.commit()
    user_id = user.id
    config = _tiered_window_config()
    result = await complete(
        "hi",  # estimator alone would say TRIVIAL -> tiny-model
        secret_store=_store(),
        complexity=Complexity.HARD,  # the user's per-call override
        config=config,
        adapters={"anthropic": MockAdapter(usage=Usage(tokens_in=11, tokens_out=13))},
        user_id=user_id,
        session=db,
    )
    assert result.model.model_name == "big-model"
    row = await db.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == result.call_id)
    )
    assert row is not None
    expected = compute_call_credits(
        result.model, 11, 13, config.cost, entry=config.entry_for_role(result.model.role)
    )
    assert row.amount == -expected  # big-model prices (5/10), not the default tier's


async def test_override_applies_to_one_call_only() -> None:
    """No persistence: the next call without an override re-estimates."""
    config = _tiered_window_config()
    overridden = await complete(
        "hi",
        secret_store=_store(),
        complexity=Complexity.HARD,
        config=config,
        adapters={"anthropic": MockAdapter()},
    )
    assert overridden.model.model_name == "big-model"
    plain = await complete(
        "hi",
        secret_store=_store(),
        config=config,
        adapters={"anthropic": MockAdapter()},
    )
    assert plain.model.model_name == "tiny-model"  # estimator: short no-signal query
    assert plain.model.complexity is Complexity.TRIVIAL


# --- MO-03: pre-flight gates + provider retry + real debit ---------------------


def _limits_config(provider: str, **limits_kwargs: float) -> OrchestrationConfig:
    base = _config(provider)
    return base.model_copy(update={"limits": LimitsConfig(**limits_kwargs)})  # type: ignore[arg-type]


async def test_gate_order_frequency_then_spend_then_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    async def fake_frequency(*args: object, **kwargs: object) -> None:
        order.append("frequency")

    async def fake_spend(*args: object, **kwargs: object) -> None:
        order.append("spend")

    monkeypatch.setattr(gateway, "check_frequency_cap", fake_frequency)
    monkeypatch.setattr(gateway, "assert_can_spend", fake_spend)
    mock = MockAdapter()
    await complete(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": mock},
        user_id=uuid.uuid4(),
        session=object(),  # type: ignore[arg-type]
    )
    assert order == ["frequency", "spend"]
    assert mock.calls == ["test-model"]


@pytest.mark.parametrize("blocking_gate", ["check_frequency_cap", "assert_can_spend"])
async def test_blocked_gate_prevents_provider_call_and_debit(
    monkeypatch: pytest.MonkeyPatch, blocking_gate: str
) -> None:
    """Both gates run BEFORE the provider call: a block means the adapter is
    never invoked and nothing is debited."""
    error: Exception = (
        FrequencyCapExceededError(7)
        if blocking_gate == "check_frequency_cap"
        else TrialCapReachedError(100, 100)
    )

    async def blocked(*args: object, **kwargs: object) -> None:
        raise error

    async def passing(*args: object, **kwargs: object) -> None:
        return None

    recorded: list[str] = []

    async def recording_track_cost(call_id: str, *args: object, **kwargs: object) -> None:
        recorded.append(call_id)

    other = "assert_can_spend" if blocking_gate == "check_frequency_cap" else "check_frequency_cap"
    monkeypatch.setattr(gateway, blocking_gate, blocked)
    monkeypatch.setattr(gateway, other, passing)
    monkeypatch.setattr(gateway, "track_cost", recording_track_cost)
    mock = MockAdapter()
    with pytest.raises(type(error)):
        await complete(
            "hi",
            secret_store=_store(),
            config=_config("anthropic"),
            adapters={"anthropic": mock},
            user_id=uuid.uuid4(),
            session=object(),  # type: ignore[arg-type]
        )
    assert mock.calls == []
    assert recorded == []


async def test_identityless_calls_skip_gates_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No user_id/session (dev/library use) -> gates never run, like the cost
    hook. Any HTTP exposure must always pass identity — flagged in gateway docs."""

    async def exploding_gate(*args: object, **kwargs: object) -> None:
        raise AssertionError("gate must not run without identity")

    monkeypatch.setattr(gateway, "check_frequency_cap", exploding_gate)
    monkeypatch.setattr(gateway, "assert_can_spend", exploding_gate)
    result = await complete(
        "hi",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": MockAdapter()},
    )
    assert result.text == "hello"


class TransientMockAdapter:
    """Raises ProviderTransientError for the first `fail_times` stream starts,
    then streams normally — the simulated provider 429."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.starts = 0

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
        self.starts += 1
        if self.starts <= self.fail_times:
            raise ProviderTransientError("simulated provider 429")
        yield "ok"
        yield _DEFAULT_USAGE


class MidStreamTransientAdapter:
    """Yields one chunk, then a transient error — must NOT be retried (tokens
    already reached the caller)."""

    def __init__(self) -> None:
        self.starts = 0

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
        self.starts += 1
        yield "partial"
        raise ProviderTransientError("simulated mid-stream 429")


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(gateway, "_sleep", fake_sleep)
    return delays


async def test_provider_transient_errors_are_retried_with_backoff(
    recorded_sleeps: list[float],
) -> None:
    adapter = TransientMockAdapter(fail_times=2)
    config = _limits_config("anthropic", retry_max_attempts=3, retry_backoff_seconds=0.25)
    result = await complete(
        "hi", secret_store=_store(), config=config, adapters={"anthropic": adapter}
    )
    assert result.text == "ok"
    assert adapter.starts == 3
    assert len(recorded_sleeps) == 2
    assert 0.25 <= recorded_sleeps[0] <= 0.5
    assert 0.5 <= recorded_sleeps[1] <= 1.0


async def test_retry_exhaustion_surfaces_clear_transient_error(
    recorded_sleeps: list[float],
) -> None:
    adapter = TransientMockAdapter(fail_times=99)
    config = _limits_config("anthropic", retry_max_attempts=3, retry_backoff_seconds=0.25)
    with pytest.raises(ProviderTransientError) as excinfo:
        await complete("hi", secret_store=_store(), config=config, adapters={"anthropic": adapter})
    assert "exhaust" in str(excinfo.value).lower()
    assert adapter.starts == 3
    assert len(recorded_sleeps) == 2
    assert 0.25 <= recorded_sleeps[0] <= 0.5
    assert 0.5 <= recorded_sleeps[1] <= 1.0


async def test_no_retry_after_first_streamed_chunk(recorded_sleeps: list[float]) -> None:
    adapter = MidStreamTransientAdapter()
    with pytest.raises(ProviderTransientError):
        await complete(
            "hi",
            secret_store=_store(),
            config=_limits_config("anthropic", retry_max_attempts=3, retry_backoff_seconds=0.25),
            adapters={"anthropic": adapter},
        )
    assert adapter.starts == 1  # tokens already streamed: never restarted
    assert recorded_sleeps == []


async def test_end_to_end_debit_lands_in_ledger_with_streamed_usage(
    db: AsyncSession,
) -> None:
    """The full MO-03 chain, no mocks on the billing side: real gates (trialing
    user under cap), mock provider, REAL track_cost — the stream's final
    captured usage becomes the ledger row."""
    tag = uuid.uuid4().hex[:10]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    db.add(user)
    await db.flush()
    db.add(Subscription(user_id=user.id, plan=PlanType.BASIC, status=SubscriptionStatus.TRIALING))
    await db.commit()
    user_id = user.id
    config = _config("anthropic")
    mock = MockAdapter(usage=Usage(tokens_in=7, tokens_out=9))
    result = await complete(
        "hi",
        secret_store=_store(),
        config=config,
        adapters={"anthropic": mock},
        user_id=user_id,
        session=db,  # redis=None -> frequency cap fails open (warned)
    )
    assert result.text == "hello"
    row = await db.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == result.call_id)
    )
    assert row is not None
    expected = compute_call_credits(
        result.model, 7, 9, config.cost, entry=config.entry_for_role(result.model.role)
    )
    assert row.amount == -expected
    assert row.attrs["tokens_in"] == 7
    assert row.attrs["tokens_out"] == 9  # streamed FINAL usage, not an estimate


async def test_images_thread_through_to_the_adapter() -> None:
    """FP-03: image blocks pass complete() → dispatch → adapter untouched;
    the images-absent path stays exactly the bare-string call."""
    mock = MockAdapter()
    image = ImageBlock(media_type="image/png", data=b"\x89PNG\r\n\x1a\nx")
    await complete(
        "extract markings",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": mock},
        images=[image],
    )
    await complete(
        "plain text",
        secret_store=_store(),
        config=_config("anthropic"),
        adapters={"anthropic": mock},
    )
    assert mock.images_seen == [[image], None]
