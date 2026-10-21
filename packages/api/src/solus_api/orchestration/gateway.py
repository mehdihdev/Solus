"""The single gateway chokepoint (ADR-026): ALL model usage flows through here.

`complete()` (request-response) and `stream()` (token streaming with final-usage
capture) route via the pure `route()` selector, dispatch to a provider adapter
(`providers.py` — the only module that touches provider SDKs), and invoke the
post-call cost hook (`track_cost`) with the final token usage. No other code
path in Solus may call a provider SDK.

MO-03 order of operations (all pre-flight before the provider call starts):

    frequency cap (Redis, transient block) → spend/trial gate (DB, upgrade
    block) → provider call with transient-error retry/backoff → post-call
    atomic idempotent debit (failure → ARQ reconciliation, never the caller's
    problem)

IDENTITY GATING (read this before exposing anything): the gates AND the debit
run only when `user_id` + `session` are supplied. Identity-less calls are for
library-internal/dev/test use ONLY — any HTTP exposure MUST pass the
authenticated user's identity (and should pass `redis` + `enqueue`), or calls
are neither limited nor billed. Remaining route-exposure work (§7): per-provider
circuit breakers, a query-length bound at the route boundary, mechanical
identity enforcement, and atomic at-debit trial-cap enforcement + a concurrency
red-team test (pre-flight reads bound sequential overshoot only — a concurrent
burst while the frequency cap is failed open can exceed the trial cap).

The gateway adds NO system prompt and never interprets model output —
instruction/data separation and output sanitization are the caller's concern
(CLAUDE.md §7); text passes through opaque in both directions. Per-call
timeouts are enforced in the adapters (providers.DEFAULT_TIMEOUT_SECONDS).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import OrchestrationConfig, load_orchestration_config
from solus_api.orchestration.cost import EnqueueFn, track_cost
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.gates import (
    FrequencyCapExceededError,
    InsufficientCreditsError,
    RedisLike,
    TrialCapReachedError,
    TrialExpiredError,
    assert_can_spend,
    check_frequency_cap,
)
from solus_api.orchestration.providers import (
    DEFAULT_MAX_TOKENS,
    ImageBlock,
    ProviderAdapter,
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
    resolve_routing,
)
from solus_api.orchestration.retry import retry_transient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.connectors.secrets import SecretStore
    from solus_api.orchestration.type_estimator import AttachmentHint

logger = logging.getLogger("solus.orchestration.gateway")

# Patchable seam for the retry backoff (tests record delays instead of waiting).
_sleep = asyncio.sleep

# Gate errors pass through the stream unwrapped — they are caller-facing policy
# blocks, not provider failures.
_PASSTHROUGH_ERRORS = (
    ProviderCredentialsMissingError,
    UnknownProviderError,
    ProviderError,  # includes ProviderTransientError
    FrequencyCapExceededError,
    TrialCapReachedError,
    TrialExpiredError,
    InsufficientCreditsError,
    OverrideNotViableError,
    ContextWindowExceededError,
)

# Process-wide lazy singleton for the shipped models.yaml, so the config-omitted
# path doesn't do a sync disk read + parse per call on the event-loop thread.
# Config edits require a process restart to take effect — the intended lever is
# an explicit `config=` argument (tests) or a deploy (models.yaml change).
_default_config: OrchestrationConfig | None = None


def _default_orchestration_config() -> OrchestrationConfig:
    global _default_config
    if _default_config is None:
        _default_config = load_orchestration_config()
    return _default_config


def default_orchestration_config() -> OrchestrationConfig:
    """Public accessor for the cached shipped config — the classify preview
    reads the SAME object the gateway routes with (preview-doesn't-lie)."""
    return _default_orchestration_config()


class Completion(BaseModel):
    """The result of one gateway call. `call_id` correlates logs and the
    credit-ledger row for this call (`credit_ledger.call_id`, unique)."""

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    text: str
    tokens_in: int
    tokens_out: int
    model: ModelChoice
    call_id: str
    #: Tool calls the model PROPOSED this round. Empty on every text-only call,
    #: so existing callers are unaffected. Proposals only — Solus code decides
    #: whether any of them runs.
    tool_calls: tuple[ToolUse, ...] = ()
    #: Cached-prefix subset of `tokens_in` (prompt caching); 0 when unknown.
    tokens_cached_in: int = 0
    #: Opaque provider replay items (see `providers.Usage.provider_items`). The
    #: runner copies them onto the next assistant `Turn`; nothing else reads them.
    provider_items: tuple[dict[str, Any], ...] = ()


def _select_adapter(provider: str, adapters: Mapping[str, ProviderAdapter]) -> ProviderAdapter:
    try:
        return adapters[provider]
    except KeyError as exc:
        raise UnknownProviderError(
            f"No adapter registered for provider {provider!r}; registered: {sorted(adapters)}"
        ) from exc


async def _fire_cost_hook(
    *,
    call_id: str,
    model: ModelChoice,
    usage: Usage,
    config: OrchestrationConfig,
    user_id: uuid.UUID | None,
    session: AsyncSession | None,
    enqueue: EnqueueFn | None,
    extension_id: uuid.UUID | None = None,
) -> None:
    """The post-call debit. Gated on caller identity; `track_cost` itself never
    raises (contract §6 — failures defer to reconciliation via `enqueue`). The
    routed catalog entry rides along so the debit bills breakpoint
    (long-context) pricing — `route()` stays pure and `ModelChoice` unchanged.
    `extension_id` is the SOLUSDEV-235 attribution, passed through untouched."""
    if user_id is None or session is None:
        return
    await track_cost(
        call_id,
        user_id,
        model,
        usage.tokens_in,
        usage.tokens_out,
        session=session,
        cost=config.cost,
        entry=config.entry_for_role(model.role),
        enqueue=enqueue,
        extension_id=extension_id,
        tokens_cached_in=usage.tokens_cached_in,
    )


class CompletionStream:
    """Async iterator of text chunks from one model call.

    `async for chunk in stream_obj:` yields `str` tokens as they arrive. The
    MO-03 pre-flight gates and the provider call itself start lazily on the
    FIRST iteration (async context; both gates pass before any provider work).
    Transient provider errors are retried with exponential backoff ONLY until
    the first event arrives — once tokens have streamed to the caller, a
    transient failure surfaces instead of silently restarting the stream.

    After natural exhaustion, `.completion` holds the full `Completion` and the
    cost hook has fired exactly once. `aclose()` abandons the call early: the
    provider stream is closed, `.completion` stays None, and the hook does NOT
    fire (usage is unknowable mid-stream).
    """

    # ponytail: abandoned streams go unbilled and are only logged; per-provider
    # partial-usage reconciliation is future work if leakage ever matters.

    def __init__(
        self,
        inner_factory: Callable[[], AsyncIterator[str | ToolUse | Usage]],
        *,
        call_id: str,
        model: ModelChoice,
        config: OrchestrationConfig,
        user_id: uuid.UUID | None,
        session: AsyncSession | None,
        redis: RedisLike | None,
        enqueue: EnqueueFn | None,
        extension_id: uuid.UUID | None = None,
    ) -> None:
        self._inner_factory = inner_factory
        self._inner: AsyncIterator[str | ToolUse | Usage] | None = None
        self._call_id = call_id
        self._model = model
        self._config = config
        self._user_id = user_id
        self._session = session
        self._redis = redis
        self._enqueue = enqueue
        self._extension_id = extension_id
        self._parts: list[str] = []
        self._tool_uses: list[ToolUse] = []
        self._started = time.monotonic()
        self._closed = False
        self.completion: Completion | None = None

    def __aiter__(self) -> CompletionStream:
        return self

    async def __anext__(self) -> str:
        # Loops so a ToolUse event is absorbed rather than returned: this
        # iterator is typed `AsyncIterator[str]` and every existing consumer
        # treats what it yields as text. A tool call must never leak out as a
        # text chunk.
        while True:
            event = await self._next_inner()
            if isinstance(event, Usage):
                await self._finalize(event)
                raise StopAsyncIteration
            if isinstance(event, ToolUse):
                self._tool_uses.append(event)
                continue
            self._parts.append(event)
            return event

    async def _next_inner(self) -> str | ToolUse | Usage:
        if self._closed:
            raise StopAsyncIteration
        try:
            if self._inner is None:
                event = await self._start()
            else:
                event = await self._inner.__anext__()
        except StopAsyncIteration:
            # Adapter ended without yielding its final Usage — contract breach.
            self._closed = True
            raise ProviderError(
                f"{self._model.provider}/{self._model.model_name} stream ended "
                "without reporting usage"
            ) from None
        except _PASSTHROUGH_ERRORS:
            self._closed = True
            raise
        except Exception as exc:
            self._closed = True
            await self._close_inner()
            raise ProviderError(
                f"{self._model.provider}/{self._model.model_name} call failed"
            ) from exc
        return event

    async def _start(self) -> str | ToolUse | Usage:
        """Pre-flight gates, then start the provider stream with transient
        retry; returns the first inner event. MO-03 order: frequency cap →
        spend/trial gate → (retry-wrapped) provider call."""
        if self._user_id is not None and self._session is not None:
            await check_frequency_cap(
                self._user_id,
                redis=self._redis,
                limits=self._config.limits,
                session=self._session,
            )
            await assert_can_spend(self._user_id, session=self._session, limits=self._config.limits)

        async def _attempt() -> tuple[Any, str | ToolUse | Usage]:
            inner = self._inner_factory()
            try:
                event = await inner.__anext__()
            except ProviderTransientError:
                # The attempt owns its cleanup: close the failed stream before
                # the shared loop decides whether to retry (SYS-05 retry.py).
                await _close_generator(inner)
                raise
            return inner, event

        self._inner, event = await retry_transient(
            _attempt,
            limits=self._config.limits,
            label=f"{self._model.provider}/{self._model.model_name}",
            call_id=self._call_id,
            sleep=lambda delay: _sleep(delay),
            breaker_key=self._model.provider,
        )
        return event

    async def aclose(self) -> None:
        """Abandon the stream early (caller stopped consuming)."""
        if self._closed:
            return
        self._closed = True
        await self._close_inner()
        logger.warning(
            "model call abandoned before completion; usage unknown call_id=%s provider=%s model=%s",
            self._call_id,
            self._model.provider,
            self._model.model_name,
        )

    async def _close_inner(self) -> None:
        if self._inner is not None:
            await _close_generator(self._inner)

    async def _finalize(self, usage: Usage) -> None:
        self._closed = True
        await self._close_inner()
        self.completion = Completion(
            text="".join(self._parts),
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            model=self._model,
            call_id=self._call_id,
            tool_calls=tuple(self._tool_uses),
            tokens_cached_in=usage.tokens_cached_in,
            provider_items=tuple(usage.provider_items),
        )
        logger.info(
            "model call done call_id=%s provider=%s model=%s role=%s "
            "tokens_in=%d tokens_cached_in=%d tokens_out=%d duration_ms=%d",
            self._call_id,
            self._model.provider,
            self._model.model_name,
            self._model.role,
            usage.tokens_in,
            usage.tokens_cached_in,
            usage.tokens_out,
            int((time.monotonic() - self._started) * 1000),
        )
        await _fire_cost_hook(
            call_id=self._call_id,
            model=self._model,
            usage=usage,
            config=self._config,
            user_id=self._user_id,
            session=self._session,
            enqueue=self._enqueue,
            extension_id=self._extension_id,
        )


async def _close_generator(inner: AsyncIterator[str | ToolUse | Usage]) -> None:
    if isinstance(inner, AsyncGenerator):
        await inner.aclose()


def stream(
    query: str,
    *,
    secret_store: SecretStore,
    complexity: Complexity | None = None,
    context: InteractionContext | None = None,
    type: RouteType | None = None,
    attachments: Sequence[AttachmentHint] | None = None,
    images: Sequence[ImageBlock] | None = None,
    conversation: ToolConversation | None = None,
    config: OrchestrationConfig | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
    user_id: uuid.UUID | None = None,
    session: AsyncSession | None = None,
    redis: RedisLike | None = None,
    enqueue: EnqueueFn | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    extension_id: uuid.UUID | None = None,
    estimate_from: str | None = None,
) -> CompletionStream:
    """Streaming variant of the gateway. Routing and adapter selection happen
    here (synchronously); gates and the provider call start on first iteration.

    `extension_id` (SOLUSDEV-235 / ADR-035 §2): the extension whose `sol.ask`
    caused this call, already verified by the route. Attribution only — it
    reaches `credit_ledger.extension_id` and changes no gate or budget.

    Routing (MO-04): both chains + window policy live in ONE shared function —
    `resolution.resolve_routing` — which the classify preview also calls, so
    the preview cannot disagree with the call. Chains (symmetric): explicit arg
    -> context-derived -> query estimator (complexity safe default STANDARD;
    type safe default GENERAL). Window guard: a USER-overridden tier/type that
    cannot hold the request raises `OverrideNotViableError` (short factual
    reason, never a silent escalation); a SYSTEM-routed miss escalates within
    the role family (logged) or raises `ContextWindowExceededError` when
    nothing fits. Never silent truncation.

    `conversation` (SOLUS-RUN-01) carries a system prompt, multi-turn messages
    and tool definitions. When it is None the call is byte-identical to the
    text-only path every existing caller uses. When supplied, `query` is used
    ONLY for routing and token estimation — the conversation is the request —
    and any tool calls the model proposes land on `Completion.tool_calls`.
    Not every provider implements it: an adapter that cannot raises
    `ToolCallingUnsupportedError` rather than silently dropping the tools.

    MO-03: `redis` powers the per-user frequency cap (None -> fail-open with a
    warning, confirmed policy); `enqueue` is the ARQ seam for debit
    reconciliation (None -> failed debits are ERROR-logged for manual
    recovery). Both gates and the debit require `user_id` + `session` — see the
    module docstring's identity-gating warning.
    """
    resolved_config = config if config is not None else _default_orchestration_config()
    resolved = resolve_routing(
        query,
        complexity=complexity,
        context=context,
        type=type,
        attachments=attachments,
        estimate_from=estimate_from,
        config=resolved_config,
    )
    if not resolved.fits:
        if resolved.explicit_override:
            raise OverrideNotViableError(resolved.reason or "Override does not fit")
        raise ContextWindowExceededError(resolved.reason or "Request exceeds every model")
    if resolved.escalated:
        logger.info(
            "window escalation: system-routed role=%s could not hold ~%d tokens; "
            "escalated to role=%s model=%s",
            resolved.escalated_from_role,
            resolved.tokens_estimate,
            resolved.choice.role,
            resolved.choice.model_name,
        )
    choice = resolved.choice
    registry = adapters if adapters is not None else build_adapter_registry(secret_store)
    adapter = _select_adapter(choice.provider, registry)
    call_id = str(uuid.uuid4())
    # §7 logging: identifiers and counts only — never the query or completion text.
    logger.info(
        "model call start call_id=%s provider=%s model=%s role=%s complexity=%s type=%s",
        call_id,
        choice.provider,
        choice.model_name,
        choice.role,
        choice.complexity,
        choice.route_type,
    )
    # `reasoning_effort` rides only when the catalog entry sets one, so adapters
    # (and test fakes) for non-reasoning entries keep the pre-S1 call shape.
    effort_kw: dict[str, str] = (
        {"reasoning_effort": choice.reasoning_effort} if choice.reasoning_effort else {}
    )
    return CompletionStream(
        lambda: adapter.stream(
            choice.model_name,
            query,
            max_tokens=max_tokens,
            images=images,
            conversation=conversation,
            **effort_kw,
        ),
        call_id=call_id,
        model=choice,
        config=resolved_config,
        user_id=user_id,
        session=session,
        redis=redis,
        enqueue=enqueue,
        extension_id=extension_id,
    )


async def complete(
    query: str,
    *,
    secret_store: SecretStore,
    complexity: Complexity | None = None,
    context: InteractionContext | None = None,
    type: RouteType | None = None,
    attachments: Sequence[AttachmentHint] | None = None,
    images: Sequence[ImageBlock] | None = None,
    conversation: ToolConversation | None = None,
    config: OrchestrationConfig | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
    user_id: uuid.UUID | None = None,
    session: AsyncSession | None = None,
    redis: RedisLike | None = None,
    enqueue: EnqueueFn | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    extension_id: uuid.UUID | None = None,
    estimate_from: str | None = None,
) -> Completion:
    """Request-response gateway call: drains the streaming path (one code path,
    identical usage numbers) and returns the full `Completion`. Routing, window
    guard, gating, and retry semantics are documented on `stream()`."""
    completion_stream = stream(
        query,
        secret_store=secret_store,
        complexity=complexity,
        context=context,
        type=type,
        attachments=attachments,
        images=images,
        conversation=conversation,
        config=config,
        adapters=adapters,
        user_id=user_id,
        session=session,
        redis=redis,
        enqueue=enqueue,
        max_tokens=max_tokens,
        extension_id=extension_id,
        estimate_from=estimate_from,
    )
    async for _ in completion_stream:
        pass
    if completion_stream.completion is None:  # pragma: no cover - defensive
        raise ProviderError("stream finished without producing a completion")
    return completion_stream.completion
