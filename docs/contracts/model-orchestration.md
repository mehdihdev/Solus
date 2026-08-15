# Model Orchestration — Design Contract (SOLUS-W0-03)

**Status:** Design contract. Ships the interface, config schema, and this document +
importable **stubs**. The routing/cost **implementation** is a later ticket (MO-01).
**Authority:** ADR-026 (multi-model routing), ADR-024 (credits), ADR-018 (metering), ADR-010
(agent is an orchestrator). Code: `packages/api/src/solus_api/orchestration/`.

Consumers: the SOL Agent (ADR-010) and Compatibility Research select a model per call through
`route()`, then meter it through `track_cost()`. The whole point of this contract is that
**model identity lives only in `models.yaml`** — there are zero hardcoded model strings in code,
so swapping which model serves a role is a config edit, not a code change.

---

## 1. The three phases: select → call → track

A model-backed request moves through three **separate** phases. Keeping them separate is what
makes `route()` pure and testable and keeps accounting off the request's critical path.

```
                      (caller / middleware)                (orchestrator)             (post-response)
 ┌───────────────┐   0. PRE-FLIGHT           ┌─────────┐   1. SELECT      ┌────────┐   2. CALL   ┌──────────┐   3. TRACK
 │ request +     │──▶ has_sufficient_credits ─▶│  gate  │─▶ route(...)  ──▶│ Model  │──▶ provider ─▶│ track_cost │
 │ interaction   │   (cached balance read)    │        │   → ModelChoice  │ Choice │   API call   │  (credits) │
 │ context       │   block/degrade if broke   └─────────┘   PURE, no I/O   └────────┘             └─────┬──────┘
 └───────────────┘                                                                                       │
        │ derive_complexity(context)  ── Step-1 gateway, NO model call ──────────────────────────────────┘
        ▼                                                                              debit credit_ledger
   Complexity tier                                                          (on failure → reconcile, never block user)
```

- **Phase 0 — pre-flight balance check** (`has_sufficient_credits`): a _separate_ concern that
  runs **before** `route()`. It is **not** part of `route`. See §7.
- **Phase 1 — select** (`route`): pure selection of a `ModelChoice`. No model call, no credit
  check, no cost tracking. See §2–§5.
- **Phase 2 — call**: the caller makes the actual model API call (out of scope here).
- **Phase 3 — track** (`track_cost`): post-call hook; converts tokens → credits and debits the
  ledger. Runs _after_ the response because `tokens_out` is only known then. See §6.

---

## 2. `route()` — the core interface

```python
route(query: str, complexity: Complexity, type: RouteType | None, *, config: OrchestrationConfig)
    -> ModelChoice
```

- **Deterministic**: a pure function of `(inputs + current config)`. Same inputs + same config →
  the same `ModelChoice`, always. No randomness, no time-dependence, no hidden state, and **no
  model call inside `route`**. Changing config changes the mapping — that is the intended swap
  mechanism, not nondeterminism.
- **Pure selection only.** `route()` does **not** check the user's credit balance, does **not**
  call the model, and does **not** track cost. Those are Phases 0/2/3.
- **Why `config` is an explicit parameter:** to keep `route` a pure function of _(inputs +
  config)_ with no hidden global. The caller (or a thin app-level singleton loaded via
  `load_orchestration_config()`) injects it. This is a deliberate elaboration of the ticket's
  bare `route(query, complexity, type)`.
- `query` is **reserved** for future within-tier heuristics; v1 selection is by `(complexity,
type)` only.

**Algorithm (MO-01 implements — `route` is a stub in W0-03):**

1. `resolved = type or RouteType.GENERAL` — `None` falls back to `GENERAL`.
2. `role = config.matrix.get(complexity, {}).get(resolved) or config.default_role` — a missing
   `(complexity, type)` cell falls back to the documented `default_role`.
3. `entry = config.entry_for_role(role)`.
4. return a `ModelChoice` built from `entry` (+ `role`, `complexity`, `resolved`, optional
   `rationale`).

---

## 3. Complexity + the Step-1 gateway

`Complexity` = `TRIVIAL | STANDARD | HARD` (three tiers).

**Framing (important):** "the caller supplies complexity" means the **calling code** passes it as
a parameter — the **end user never sees or provides it**. Complexity is derived **automatically**
by the deterministic gateway from interaction context. The UX is fully automatic; complexity is
an explicit parameter of `route()` only to keep `route` pure and testable.

**The gateway** (`derive_complexity(context: InteractionContext) -> Complexity`) maps interaction
context → tier **deterministically, with NO model call** (keeps routing cost near zero). It is an
**extensible** mapping (`CONTEXT_COMPLEXITY_DEFAULTS`); starter contexts:

| InteractionContext       | Complexity | Rationale                                |
| ------------------------ | ---------- | ---------------------------------------- |
| `CODE_AUTOCOMPLETE`      | TRIVIAL    | fast, cheap, high-frequency              |
| `TELEMETRY_SUMMARY`      | TRIVIAL    | incident/telemetry summary → cheap model |
| `SOL_OPEN_QUESTION`      | HARD       | open-ended reasoning                     |
| `COMPATIBILITY_RESEARCH` | STANDARD   | structured cross-domain analysis         |
| _(unknown)_              | STANDARD   | safe default                             |

Callers get their `complexity` value from this gateway based on what interaction they are in, then
pass it to `route()`. New callers add a row here — no change to `route`.

---

## 4. Type-based routing — a REAL v1 input

`RouteType` = `CODE | VISUAL_LOG | LONG_CONTEXT | GENERAL` (extensible). This is **not** a no-op:
it genuinely affects selection by routing to the frontier model whose strength matches the query.

- **CODE** → Claude-class models (strong CODE reasoning).
- **VISUAL_LOG** (logs, telemetry, images) → Gemini-class models (strong multimodal/log handling).
- **LONG_CONTEXT** (large datasheets/datasets) → Gemini-class models (very large context windows).
- **GENERAL** → the default when `type` is `None`.

**Reserved specialist slot:** truly-specialist models that don't exist as products yet (e.g. a
hypothetical spatial-reasoning specialist) get a **new `RouteType` member + catalog role** when
they arrive — no change to routing code. The frontier-strength routing above, however, IS built
as a real input in v1.

---

## 5. Selection: the `(complexity × type) → role` matrix

Selection is **two-dimensional**: `(Complexity tier × RouteType) → model ROLE`.

**Roles, not names,** are the indirection that keeps zero hardcoded model strings. A role is a tag
like `code_hard`, `visual_standard`, `general_trivial`. The catalog in `models.yaml` declares which
concrete model fills each role. `route()` computes the `(complexity, type)` pair → looks up the
role in the matrix → resolves the role to a catalog entry → returns it as the `ModelChoice`.
Swapping the model behind a role is a config edit.

- The matrix **may be partial**; a missing cell falls back to `default_role`.
- **Determinism invariant (validated):** each role referenced by the matrix (and `default_role`)
  must be filled by **exactly one** catalog entry. `OrchestrationConfig`'s validator rejects a
  role filled by two entries (ambiguous) or a referenced role absent from the catalog.

### `ModelChoice` (what `route` returns)

A frozen Pydantic v2 value object carrying the **resolved** config so the caller can both make the
call and compute cost afterward:

| field            | meaning                                            |
| ---------------- | -------------------------------------------------- |
| `provider`       | `anthropic` / `google` / `openai` / …              |
| `model_name`     | concrete model string, **from config**             |
| `price_in`       | USD **per 1M input tokens**                        |
| `price_out`      | USD **per 1M output tokens**                       |
| `context_window` | tokens                                             |
| `role`           | the role selected (for logging/debugging)          |
| `complexity`     | routing metadata: the tier that selected it        |
| `route_type`     | routing metadata: resolved type (`None` → GENERAL) |
| `rationale`      | optional human-readable "why this model"           |

---

## 6. Cost tracking — the post-call hook

```python
async track_cost(call_id, user_id, model: ModelChoice, tokens_in, tokens_out,
                 *, session, cost: CostConfig) -> None
```

Runs **after** the call (Phase 3). `user_id` is required — the ledger is per-user (ADR-024) and
`call_id` alone can't identify it.

**Conversion (locked, `compute_call_credits` is functional):**

```
dollars = tokens_in/1e6 * price_in + tokens_out/1e6 * price_out
credits = ceil(dollars * margin_multiplier * credits_per_dollar)
```

- Prices are **USD per 1M tokens**. `ceil` so a real call never bills 0 credits.
- **`margin_multiplier` (default `2.0`, config):** covers infra + failed/retried calls + trial
  grants + profit — **not pure profit**, which is why it is `2.0`, not ~`1.25`.
- **`credits_per_dollar` (config):** **provisional** — no real cost-per-op data yet (ADR-024);
  calibrate post-pilot. Both live in `cost:` in `models.yaml`, never in code.

**Then debit** (MO-01): append a `CreditLedger` USAGE row (`amount = -credits`, `balance_after`
snapshot, `attrs = {call_id, model_name, role, tokens_in, tokens_out}`) and update the cached
`CreditBalance` (both in `solus_api.models`).

**Debit-failure behavior (required):** the model call already ran and was paid for — **never fail
the user's request on the accounting write.** On debit failure (DB down, race), serve the user's
result and enqueue the debit to a **reconciliation / dead-letter path** (ARQ + Redis is available)
so credits reconcile later. This hook never raises to the caller in production; it swallows and
defers.

---

## 7. Balance pre-flight (Phase 0, separate from `route`)

Checking whether a user **has** enough credits is a **separate pre-flight step that happens before
`route()`** — done by the caller or middleware, **not** inside `route` (which stays pure
selection). Interface:

```python
async has_sufficient_credits(user_id, estimated_credits, *, session) -> bool
```

It reads the cached `CreditBalance` and compares against an estimate. On insufficient credits the
caller blocks or degrades to a cheaper "lite mode" (ADR-018) — that policy lives in the caller,
not here.

---

## 8. `models.yaml` config schema

Validated by `OrchestrationConfig` (`orchestration/config.py`). Structure:

- `version: int`
- `catalog: [ {provider, name, price_in, price_out, context_window, roles: […]} ]` — each entry is
  a concrete model and the role(s) it fills.
- `matrix: { <complexity>: { <route_type>: <role> } }` — the `(complexity × type) → role` map
  (may be partial).
- `default_role: str` — fallback for missing matrix cells.
- `cost: { margin_multiplier, credits_per_dollar, price_unit: usd_per_million_tokens }`.

Prices/names shipped in the example are **ILLUSTRATIVE and provisional** — verify against provider
pricing before production. Loaded via `load_orchestration_config(path=None)` (defaults to the
sibling `models.yaml`).

---

## 9. Functional vs stubbed in W0-03

| Component                                                        | W0-03 status                     |
| ---------------------------------------------------------------- | -------------------------------- |
| `models.yaml` + `OrchestrationConfig` + loader + role validation | **Functional** (config contract) |
| `compute_call_credits` (token→credit formula)                    | **Functional**                   |
| `derive_complexity` + `CONTEXT_COMPLEXITY_DEFAULTS` (gateway)    | **Functional** (starter mapping) |
| `ModelChoice`, `Complexity`, `RouteType`, `InteractionContext`   | **Functional** (types)           |
| `route()`                                                        | **Stub** → MO-01                 |
| `track_cost()` (ledger debit + reconciliation)                   | **Stub** → MO-01                 |
| `has_sufficient_credits()` (pre-flight)                          | **Stub** → MO-01                 |

**Cross-references:** ADR-026 (routing), ADR-024 (credits: `credit_ledger` + `credit_balance`),
ADR-018 (metering classes), ADR-010 (orchestrator). Credit tables: `CreditLedger` / `CreditBalance`
/ `CreditTxnType.USAGE` in `packages/api/src/solus_api/models.py`.

---

## Tool calling (SOLUS-RUN-01)

The gateway carried text only: one string in, text out. SOL's tool registry was therefore
unreachable — a model could be asked about a robot but could not look anything up. This section
covers the addition. **Routing, complexity, window policy and cost mechanics above are unchanged.**

### The shape

`stream()` and `complete()` take one optional `conversation: ToolConversation`:

| field | meaning |
| --- | --- |
| `system` | Solus-authored instruction text. The ONLY instruction position. |
| `messages` | `tuple[Turn, ...]` — multi-turn. A `Turn` carries `text`, `tool_uses` (assistant) or `tool_results` (user). |
| `tools` | `tuple[ToolSpec, ...]` — `name`, `description`, `input_schema`. |

`ToolSpec.input_schema` is a `ToolDescriptor.params` **verbatim** (it is already JSON Schema), so a
tool's `params` and `description` are now literally model-facing wire content — see
`docs/contracts/agent-tool.md` §5.

Calls the model proposes come back on `Completion.tool_calls: tuple[ToolUse, ...]`. They are
PROPOSALS: the shape carries no way to execute itself, and Solus code decides.

### Invariants

- **`conversation=None` is byte-identical to the text-only path.** One user message, no system
  prompt, no tools key. `fingerprint/escalation.py` and `visual.py` use that path and are untouched.
  Asserted directly on the wire request in `test_providers.py`.
- **The adapter yield contract extends** from `str* → Usage` to `str* → ToolUse* → Usage`. The
  `Usage` sentinel still terminates. `CompletionStream` absorbs `ToolUse` events rather than
  yielding them, because it is typed `AsyncIterator[str]` and every existing consumer treats what
  it yields as text.
- **A multi-round loop bills PER ROUND.** Each round is one gateway call: one frequency-cap check,
  one spend gate, one debit. §6 above describes a single call; a SOL turn is up to
  `MAX_MODEL_ROUNDS` of them.
- **Identity is required in practice.** `complete()` still defaults `user_id`/`session` to `None`
  and silently skips gates and debits when absent (unchanged, ADR-018). A tool loop must never
  inherit that: `LlmRunner` refuses to run without them.

### Provider support is a real constraint on the matrix

| provider | tool calling |
| --- | --- |
| anthropic | implemented |
| openai | raises `ToolCallingUnsupportedError` |
| google (gemini) | raises `ToolCallingUnsupportedError` |

`ToolCallingUnsupportedError` is a `ProviderError` but deliberately **not** a
`ProviderTransientError` — MO-03 backoff must not retry a structural gap.

This makes `models.yaml` load-bearing in a new way: a matrix cell that SOL routes to must name a
tool-capable provider. Today `SOL_OPEN_QUESTION → HARD → general_hard → claude-opus-4-8`. Repointing
that cell at a Gemini role fails **loudly** on the next SOL turn rather than silently dropping the
tools array and returning prose — which would look like the model simply choosing not to act.
