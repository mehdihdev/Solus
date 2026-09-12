"""Gateway embedding extension (SYS-02, docs/api/gateway-embeddings.md).

`embed()` is the single embedding entry point beside `complete()`/`stream()` —
ADR-026's one chokepoint. Model identity and pricing live ONLY in models.yaml
(`embeddings:` entry). Identity gating matches the gateway: the MO-03 gates and
the idempotent `track_cost` debit run only when `user_id` + `session` are
supplied; identity-less calls are library-internal/dev/test use only.
Embeddings bill input tokens only (tokens_out = 0).

The streaming `ProviderAdapter` protocol is NOT widened — embedding calls get
their own minimal adapter, reusing `_BaseAdapter._api_key()` so key handling
has exactly one implementation (never a second provider stack).

`build_embed_fn` adapts `embed()` to the FP-02 `EmbedFn` seam
(`async (text) -> list[float] | None`). The alias itself is not imported:
`fingerprint` imports `orchestration` (escalation), so the reverse import would
be a cycle — the shape is structural and mypy checks it at the consumer.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Protocol

from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.cost import track_cost
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.orchestration.gates import assert_can_spend, check_frequency_cap
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.orchestration.providers import (
    DEFAULT_TIMEOUT_SECONDS,
    OPENAI_API_KEY_NAME,
    ProviderCredentialsMissingError,
    ProviderError,
    ProviderTransientError,
    UnknownProviderError,
    Usage,
    _BaseAdapter,
    normalize_provider_error,
)
from solus_api.orchestration.retry import retry_transient

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.connectors.secrets import SecretStore
    from solus_api.orchestration.config import EmbeddingConfig, LimitsConfig, OrchestrationConfig
    from solus_api.orchestration.cost import EnqueueFn
    from solus_api.orchestration.gates import RedisLike

logger = logging.getLogger("solus.orchestration.embeddings")

# Patchable seam for the retry backoff (tests record delays instead of waiting).
_retry_sleep = asyncio.sleep

# Per-call input budget (§7/ADR-019: the spend gate is pre-flight only, so one
# unbounded call could bill arbitrarily). ponytail: sized to OpenAI's own batch
# ceiling neighborhood; raise deliberately if a real consumer needs more.
MAX_EMBED_BATCH = 256
MAX_EMBED_CHARS = 500_000


class EmbeddingsNotConfiguredError(ProviderError):
    """models.yaml has no `embeddings:` entry — embedding is unavailable by config."""


def _check_call_policy(
    texts: Sequence[str],
    *,
    user_id: uuid.UUID | None,
    session: object | None,
    allow_unmetered: bool,
) -> None:
    """Identity + input-budget policy, enforced BEFORE gates or any provider work.
    Identity-less calls skip gates AND billing (gateway policy), so they must be
    an explicit opt-in, never the default shape (§7/ADR-019)."""
    if (user_id is None or session is None) and not allow_unmetered:
        raise ValueError(
            "embed() without user_id+session is unmetered (no gates, no debit); "
            "library-internal/dev callers must opt in with allow_unmetered=True"
        )
    if len(texts) > MAX_EMBED_BATCH or sum(len(text) for text in texts) > MAX_EMBED_CHARS:
        raise ProviderError(
            f"embedding batch exceeds the per-call budget "
            f"({MAX_EMBED_BATCH} texts / {MAX_EMBED_CHARS} chars)"
        )


class EmbeddingAdapter(Protocol):
    """One batch-embedding call surface per provider. Returns the vectors (in
    input order) plus the final `Usage`; on provider failure: raise."""

    async def embed(
        self, model_name: str, texts: Sequence[str], *, dimensions: int
    ) -> tuple[list[list[float]], Usage]: ...


class OpenAIEmbeddingAdapter(_BaseAdapter):
    provider = "openai"
    secret_name = OPENAI_API_KEY_NAME

    async def embed(
        self, model_name: str, texts: Sequence[str], *, dimensions: int
    ) -> tuple[list[list[float]], Usage]:
        api_key = await self._api_key()
        import openai  # lazy: keyless environments never touch provider SDKs

        # max_retries=0 keeps the SDK's silent default retries from preempting
        # the gateway-style backoff in `embed()` (ProviderTransientError).
        client = openai.AsyncOpenAI(api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=0)
        try:
            async with client:
                response = await client.embeddings.create(
                    model=model_name, input=list(texts), dimensions=dimensions
                )
        except openai.OpenAIError as exc:
            raise normalize_provider_error(self.provider, model_name, exc) from None
        ordered = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(texts))):
            # Duplicate/missing indices with a correct total would silently
            # mis-pair vectors to texts — refuse rather than guess.
            raise ProviderError(f"openai embedding response indices malformed for {model_name}")
        vectors = [item.embedding for item in ordered]
        return vectors, Usage(tokens_in=response.usage.prompt_tokens, tokens_out=0)


def build_embedding_adapter_registry(secret_store: SecretStore) -> Mapping[str, EmbeddingAdapter]:
    """The embedding-adapter registry, keyed by provider — sibling of
    `providers.build_adapter_registry` (which stays streaming-only)."""
    return {"openai": OpenAIEmbeddingAdapter(secret_store)}


async def _call_with_retry(
    adapter: EmbeddingAdapter,
    entry: EmbeddingConfig,
    texts: Sequence[str],
    *,
    limits: LimitsConfig,
    call_id: str,
) -> tuple[list[list[float]], Usage]:
    """The gateway's MO-03 transient retry/backoff, embedding-shaped: a full-call
    retry is safe here because nothing has streamed to the caller. Delegates to
    the ONE shared loop (SYS-05 retry.py)."""
    return await retry_transient(
        lambda: adapter.embed(entry.name, texts, dimensions=entry.dimensions),
        limits=limits,
        label=f"{entry.provider}/{entry.name}",
        call_id=call_id,
        sleep=lambda delay: _retry_sleep(delay),
        breaker_key=entry.provider,
    )


async def embed(
    texts: Sequence[str],
    *,
    secret_store: SecretStore,
    config: OrchestrationConfig | None = None,
    adapters: Mapping[str, EmbeddingAdapter] | None = None,
    user_id: uuid.UUID | None = None,
    session: AsyncSession | None = None,
    redis: RedisLike | None = None,
    enqueue: EnqueueFn | None = None,
    allow_unmetered: bool = False,
) -> list[list[float]]:
    """Embed `texts` via the configured model (models.yaml `embeddings:` entry).

    MO-03 order, same as `stream()`: frequency cap → spend/trial gate →
    provider call with transient retry/backoff → post-call idempotent debit.
    Gates and debit require `user_id` + `session`; a call WITHOUT identity is
    unmetered and must opt in explicitly via `allow_unmetered=True`
    (library-internal/dev/test only — HTTP exposure always passes identity).
    Input is budget-bounded per call (`MAX_EMBED_BATCH`/`MAX_EMBED_CHARS`).
    Raises `EmbeddingsNotConfiguredError` / `ProviderCredentialsMissingError` /
    `ProviderError` — FP-02-style consumers treat any exception as no-signal
    (`build_embed_fn` does exactly that).
    """
    resolved_config = config if config is not None else default_orchestration_config()
    entry = resolved_config.embeddings
    if entry is None:
        raise EmbeddingsNotConfiguredError(
            "models.yaml has no `embeddings:` entry; embedding is unavailable"
        )
    if not texts:
        return []
    _check_call_policy(texts, user_id=user_id, session=session, allow_unmetered=allow_unmetered)
    if user_id is not None and session is not None:
        await check_frequency_cap(
            user_id, redis=redis, limits=resolved_config.limits, session=session
        )
        await assert_can_spend(user_id, session=session, limits=resolved_config.limits)

    registry = adapters if adapters is not None else build_embedding_adapter_registry(secret_store)
    adapter = registry.get(entry.provider)
    if adapter is None:
        raise UnknownProviderError(
            f"No embedding adapter for provider {entry.provider!r}; registered: {sorted(registry)}"
        )

    call_id = str(uuid.uuid4())
    started = time.monotonic()
    # §7 logging: identifiers and counts only — never the texts.
    logger.info(
        "embedding call start call_id=%s provider=%s model=%s texts=%d",
        call_id,
        entry.provider,
        entry.name,
        len(texts),
    )
    vectors, usage = await _call_with_retry(
        adapter, entry, texts, limits=resolved_config.limits, call_id=call_id
    )
    if len(vectors) != len(texts):
        raise ProviderError(
            f"{entry.provider}/{entry.name} returned {len(vectors)} vectors for {len(texts)} texts"
        )
    if any(len(vector) != entry.dimensions for vector in vectors):
        raise ProviderError(
            f"{entry.provider}/{entry.name} returned a vector of unexpected dimension "
            f"(expected {entry.dimensions})"
        )

    logger.info(
        "embedding call done call_id=%s provider=%s model=%s texts=%d tokens_in=%d duration_ms=%d",
        call_id,
        entry.provider,
        entry.name,
        len(texts),
        usage.tokens_in,
        int((time.monotonic() - started) * 1000),
    )
    if user_id is not None and session is not None:
        # Same post-call debit seam as the gateway; a synthetic ModelChoice rides
        # `track_cost` unchanged (embeddings bill input only, so price_out=0; the
        # window field is not routing-relevant here but ModelChoice requires >0).
        choice = ModelChoice(
            provider=entry.provider,
            model_name=entry.name,
            price_in=entry.price_in,
            price_out=0.0,
            context_window=8192,
            role="embeddings",
            complexity=Complexity.TRIVIAL,
            route_type=RouteType.GENERAL,
            rationale="embeddings entry (models.yaml)",
        )
        await track_cost(
            call_id,
            user_id,
            choice,
            usage.tokens_in,
            0,
            session=session,
            cost=resolved_config.cost,
            enqueue=enqueue,
        )
    return vectors


def build_embed_fn(
    secret_store: SecretStore,
    *,
    config: OrchestrationConfig | None = None,
    adapters: Mapping[str, EmbeddingAdapter] | None = None,
    user_id: uuid.UUID | None = None,
    session: AsyncSession | None = None,
    redis: RedisLike | None = None,
    enqueue: EnqueueFn | None = None,
    allow_unmetered: bool = False,
) -> Callable[[str], Awaitable[list[float] | None]]:
    """Adapt `embed()` to the FP-02 `EmbedFn` seam: single text in, vector or
    no-signal (None) out — NEVER raises. This is the one composition point for
    every EmbedFn consumer (fingerprint ingest, RAG retrieval), so keyless
    environments degrade instead of failing. Identity (`user_id`+`session`) is
    the expected shape; `allow_unmetered=True` is the explicit library-internal
    opt-out (see `embed`)."""

    async def embed_one(text: str) -> list[float] | None:
        try:
            vectors = await embed(
                [text],
                secret_store=secret_store,
                config=config,
                adapters=adapters,
                user_id=user_id,
                session=session,
                redis=redis,
                enqueue=enqueue,
                allow_unmetered=allow_unmetered,
            )
        except ProviderCredentialsMissingError as exc:
            # Loud but compact: the fix is a seeding step, not a code bug — a
            # traceback here buries the one actionable line.
            logger.warning("embed_one degraded to no-signal: %s — run `make seed-secrets`", exc)
            return None
        except ProviderTransientError as exc:
            # Expected operational states (retries exhausted, circuit open) —
            # compact, no traceback, or an open circuit floods the log.
            logger.warning("embed_one degraded to no-signal: %s", exc)
            return None
        except Exception:  # noqa: BLE001 — embedding is best-effort no-signal
            logger.warning("embed_one failed; treating as no-signal", exc_info=True)
            return None
        return vectors[0] if vectors else None

    return embed_one
