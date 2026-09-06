"""SYS-02 gateway embedding extension (docs/api/gateway-embeddings.md).

One chokepoint (ADR-026): `embed()` lives beside `complete()`/`stream()`, bills
input tokens through the same idempotent `track_cost` debit, and is keyless-safe
end to end — `build_embed_fn` turns ANY failure into no-signal (None), matching
the FP-02 EmbedFn consumer contract.
"""

import uuid
from collections.abc import Sequence

import pytest
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import CreditLedger, PlanType, Subscription, SubscriptionStatus, User
from solus_api.orchestration import embeddings as embeddings_module
from solus_api.orchestration.config import (
    CostConfig,
    EmbeddingConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
    load_orchestration_config,
)
from solus_api.orchestration.embeddings import (
    EmbeddingsNotConfiguredError,
    OpenAIEmbeddingAdapter,
    build_embed_fn,
    embed,
)
from solus_api.orchestration.providers import (
    ProviderCredentialsMissingError,
    ProviderError,
    ProviderTransientError,
    Usage,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_DIM = 4


class MockEmbeddingAdapter:
    """Implements the EmbeddingAdapter protocol without any network layer."""

    def __init__(
        self,
        *,
        dimensions: int = _DIM,
        tokens_in: int = 7,
        fail_first: int = 0,
        vector_count: int | None = None,
    ) -> None:
        self.dimensions = dimensions
        self.tokens_in = tokens_in
        self.fail_first = fail_first
        self.vector_count = vector_count
        self.calls: list[tuple[str, int]] = []

    async def embed(
        self, model_name: str, texts: Sequence[str], *, dimensions: int
    ) -> tuple[list[list[float]], Usage]:
        self.calls.append((model_name, len(texts)))
        if self.fail_first > 0:
            self.fail_first -= 1
            raise ProviderTransientError("embedding provider overloaded")
        count = self.vector_count if self.vector_count is not None else len(texts)
        vectors = [[float(i)] * self.dimensions for i in range(count)]
        return vectors, Usage(tokens_in=self.tokens_in, tokens_out=0)


def _config(*, with_embeddings: bool = True) -> OrchestrationConfig:
    return OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider="anthropic",
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
        embeddings=(
            EmbeddingConfig(provider="openai", name="emb-test", dimensions=_DIM, price_in=0.02)
            if with_embeddings
            else None
        ),
    )


def _store() -> InMemorySecretStore:
    return InMemorySecretStore()  # empty: the whole suite runs keyless


def test_models_yaml_ships_the_embeddings_entry() -> None:
    config = load_orchestration_config()
    assert config.embeddings is not None
    assert config.embeddings.provider == "openai"
    assert config.embeddings.name == "text-embedding-3-small"
    assert config.embeddings.dimensions == 1536  # must match models.EMBEDDING_DIM


async def test_embed_happy_path() -> None:
    mock = MockEmbeddingAdapter()
    vectors = await embed(
        ["alpha", "beta"],
        secret_store=_store(),
        config=_config(),
        adapters={"openai": mock},
        allow_unmetered=True,
    )
    assert len(vectors) == 2
    assert all(len(v) == _DIM for v in vectors)
    assert mock.calls == [("emb-test", 2)]


async def test_embed_empty_texts_short_circuits() -> None:
    mock = MockEmbeddingAdapter()
    assert await embed([], secret_store=_store(), config=_config(), adapters={"openai": mock}) == []
    assert mock.calls == []


async def test_embed_without_config_entry_raises() -> None:
    with pytest.raises(EmbeddingsNotConfiguredError):
        await embed(["x"], secret_store=_store(), config=_config(with_embeddings=False))


async def test_embed_keyless_raises_credentials_missing() -> None:
    # The REAL adapter against an empty SecretStore: fails on the key fetch,
    # before any SDK import or network touch.
    with pytest.raises(ProviderCredentialsMissingError):
        await embed(["x"], secret_store=_store(), config=_config(), allow_unmetered=True)


async def test_embed_wrong_dimension_from_provider_raises() -> None:
    mock = MockEmbeddingAdapter(dimensions=_DIM + 1)
    with pytest.raises(ProviderError, match="dimension"):
        await embed(
            ["x"],
            secret_store=_store(),
            config=_config(),
            adapters={"openai": mock},
            allow_unmetered=True,
        )


async def test_embed_wrong_vector_count_from_provider_raises() -> None:
    mock = MockEmbeddingAdapter(vector_count=1)
    with pytest.raises(ProviderError, match="vector"):
        await embed(
            ["a", "b"],
            secret_store=_store(),
            config=_config(),
            adapters={"openai": mock},
            allow_unmetered=True,
        )


async def test_embed_retries_transient_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(embeddings_module, "_retry_sleep", fake_sleep)
    mock = MockEmbeddingAdapter(fail_first=1)
    vectors = await embed(
        ["x"],
        secret_store=_store(),
        config=_config(),
        adapters={"openai": mock},
        allow_unmetered=True,
    )
    assert len(vectors) == 1
    assert len(mock.calls) == 2  # one failure, one success
    assert len(delays) == 1  # backed off exactly once


async def test_embed_bills_the_call(db: AsyncSession) -> None:
    tag = uuid.uuid4().hex[:10]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    db.add(user)
    await db.flush()
    db.add(Subscription(user_id=user.id, plan=PlanType.BASIC, status=SubscriptionStatus.TRIALING))
    await db.commit()

    await embed(
        ["alpha"],
        secret_store=_store(),
        config=_config(),
        adapters={"openai": MockEmbeddingAdapter(tokens_in=7)},
        user_id=user.id,
        session=db,
    )
    row = await db.scalar(select(CreditLedger).where(CreditLedger.user_id == user.id))
    assert row is not None
    assert row.amount == -1  # ceil of a tiny input-only dollar cost never bills 0


async def test_embed_identity_less_skips_billing(db: AsyncSession) -> None:
    await embed(
        ["alpha"],
        secret_store=_store(),
        config=_config(),
        adapters={"openai": MockEmbeddingAdapter()},
        allow_unmetered=True,  # the explicit opt-in H1 requires
    )
    assert await db.scalar(select(func.count()).select_from(CreditLedger)) == 0


async def test_build_embed_fn_success_and_no_signal_paths() -> None:
    ok = build_embed_fn(
        _store(),
        config=_config(),
        adapters={"openai": MockEmbeddingAdapter()},
        allow_unmetered=True,
    )
    vector = await ok("alpha")
    assert vector is not None and len(vector) == _DIM

    # Keyless (real adapter, empty store) → None, never an exception.
    keyless = build_embed_fn(_store(), config=_config(), allow_unmetered=True)
    assert await keyless("alpha") is None


def test_openai_embedding_adapter_uses_the_shared_key_seam() -> None:
    adapter = OpenAIEmbeddingAdapter(_store())
    assert adapter.provider == "openai"
    assert adapter.secret_name == "openai_api_key"  # SecretStore global provider-key ref


# --- security-review hardening (SYS-02 Phase 4) --------------------------------


async def test_embed_without_identity_requires_explicit_opt_in() -> None:
    """H1: the unmetered call must never be the default shape — no identity and
    no opt-in → rejected BEFORE the adapter sees anything."""
    mock = MockEmbeddingAdapter()
    with pytest.raises(ValueError, match="allow_unmetered"):
        await embed(["x"], secret_store=_store(), config=_config(), adapters={"openai": mock})
    assert mock.calls == []


async def test_embed_oversized_batch_rejected_before_adapter() -> None:
    """H2: per-call input budget — the spend gate is pre-flight only, so an
    unbounded batch must be refused before any provider work."""
    from solus_api.orchestration.embeddings import MAX_EMBED_BATCH, MAX_EMBED_CHARS

    mock = MockEmbeddingAdapter()
    too_many = ["x"] * (MAX_EMBED_BATCH + 1)
    with pytest.raises(ProviderError, match="budget"):
        await embed(
            too_many,
            secret_store=_store(),
            config=_config(),
            adapters={"openai": mock},
            allow_unmetered=True,
        )
    too_long = ["y" * (MAX_EMBED_CHARS + 1)]
    with pytest.raises(ProviderError, match="budget"):
        await embed(
            too_long,
            secret_store=_store(),
            config=_config(),
            adapters={"openai": mock},
            allow_unmetered=True,
        )
    assert mock.calls == []
