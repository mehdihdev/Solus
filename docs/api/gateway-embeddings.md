# MO-01 gateway embedding extension (feeds FP-02's EmbedFn seam)

> **REFERENCE MATERIAL for MO-01** (model-orchestration gateway + embeddings).
> **Status:** proposal accepted-in-principle; implementation deferred to
> MO-01 (SOLUSDEV-58/SOLUSDEV-136). Formerly a root-level temp proposal
> file (FP-02), folded here in SOLUSDEV-152.

FP-02 shipped the consumer seam only — `solus_api.fingerprint.ingest.EmbedFn`, an
injectable `async (text) -> list[float] | None` — with `graph_entity.embedding`
staying NULL and everything keyless-safe until this lands. No provider code was
built outside the gateway (MO-01 stays the single chokepoint, ADR-026).

## What to add

An `embed()` entry point in `solus_api/orchestration/` beside `complete()`/`stream()`:

```python
async def embed(
    texts: Sequence[str],
    *,
    secret_store: SecretStore,
    config: OrchestrationConfig | None = None,
    user_id: uuid.UUID | None = None,
    session: AsyncSession | None = None,
    redis: RedisLike | None = None,
    enqueue: EnqueueFn | None = None,
) -> list[list[float]]
```

- **Model/provider in config, never code** (ADR-026): a new `embeddings:` entry in
  `models.yaml` naming the model (1536-d to match `graph_entity.embedding
Vector(1536)` / `EMBEDDING_DIM`) and its pricing.
- **Adapter**: a sibling embedding-adapter registry next to `build_adapter_registry`,
  reusing `_BaseAdapter._api_key()` (SecretStore global provider-key refs, e.g.
  `openai_api_key`) — do NOT widen the streaming `ProviderAdapter` protocol.
- **Gating/billing**: same identity rules as `complete()` — frequency cap → spend
  gate → call → `track_cost` idempotent debit via `call_id`; identity-less calls
  remain library-internal only (gateway.py docstring contract).
- **Failure semantics**: `ProviderCredentialsMissingError` when no key — FP-02's
  consumer already treats any exception as no-signal (embedding stays NULL).

## Consumption (after this lands)

The future fingerprint trigger router (where an authenticated user exists) builds
the EmbedFn when `SOLUS_FINGERPRINT_EMBEDDING_ENABLED` is on:

```python
async def embed_one(text: str) -> list[float] | None:
    return (await embed([text], secret_store=..., user_id=ctx.user.id, session=...))[0]

await scan_project(session, project_id, embed=embed_one)
```

## Out of scope here

- Retrieval/seeding of `extra_candidate_bases` from pgvector similarity (separate
  ticket; FP-01's invariant stands — similarity can only surface ambiguity, never
  merge).
- Backfill job for existing canonical rows (one-off ARQ task once embed() exists).
- Embedding refresh on canonical-text change (needs the text hash stored to diff).
