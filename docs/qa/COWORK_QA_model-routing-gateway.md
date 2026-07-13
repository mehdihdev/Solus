# COWORK QA — Model Routing Framework + Gateway + Provider Adapters (SOLUSDEV-58 / MO-01…MO-04)

This feature is a **backend library surface** — it adds NO HTTP routes and NO UI.
Every check below runs from a terminal at the repo root. You need: the repo,
`uv` installed, and (only for section 5) a real provider API key. **No API keys
are needed for sections 1–4.**

Setup state required:

- Repo checked out on branch `SOLUSDEV-58-Model-Routing`, `uv sync --all-packages` run.
- For section 2 only: local Postgres from `docker-compose.dev.yml` (or
  `SOLUS_TEST_DATABASE_URL` pointing at a pgvector Postgres) — the wider API
  test suite uses it; the orchestration tests themselves are DB-free.

---

## 1. Deterministic routing (no keys, no DB)

- [ ] 1.1 `cd packages/api && uv run pytest tests/test_router.py -q`
      → **Expected:** 18 passed. Covers the full 12-cell (complexity × type)
      matrix, `type=None` → GENERAL, missing-cell → `default_role`, and a
      50-run determinism loop.
- [ ] 1.2 Spot-check by hand:
      `    cd packages/api && uv run python -c "
from solus_api.orchestration import route, load_orchestration_config, Complexity, RouteType
cfg = load_orchestration_config()
print(route('q', Complexity.HARD, RouteType.CODE, config=cfg).model_name)
print(route('q', Complexity.STANDARD, RouteType.VISUAL_LOG, config=cfg).provider)"`
      → **Expected:** first line prints the Claude-class model that fills
      `code_hard` in `models.yaml`; second line prints `google` (Gemini-class
      for visual/log routing).

## 2. Full test suite (proves nothing else broke)

- [ ] 2.1 `uv run pytest -q` from the repo root
      → **Expected:** all tests pass; exactly **3 skipped** (the gated live
      smoke tests — correct without keys).
- [ ] 2.2 `uv run ruff check .` and `uv run mypy packages/api/src`
      → **Expected:** both clean.

## 3. Invariants (the ratchet tests)

- [ ] 3.1 `cd packages/api && uv run pytest tests/test_no_hardcoded_models.py -q`
      → **Expected:** 2 passed — (a) zero hardcoded model-id literals anywhere
      in `src/solus_api`; (b) provider SDKs imported only by
      `orchestration/providers.py`.
- [ ] 3.2 Negative check — prove the ratchet bites: temporarily add a line like
      `x = "claude-sonnet-5"` to any file under
      `packages/api/src/solus_api/`, rerun 3.1 → **Expected: FAIL** naming the
      file/line. Revert the line.

## 4. No-key behavior (critical path — we have no keys yet)

- [ ] 4.1 `cd packages/api && uv run pytest tests/test_providers.py tests/test_gateway.py -q`
      → **Expected:** all pass with an EMPTY secret store — routing, cost math,
      streaming, and the cost-hook seam all work keyless.
- [ ] 4.2 Manual: a real call without a key must fail with an actionable error:
      `    cd packages/api && uv run python -c "
import asyncio
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration import complete
asyncio.run(complete('hello', secret_store=InMemorySecretStore()))"`
      → **Expected:** `ProviderCredentialsMissingError: No API key for provider
'anthropic'; set 'anthropic_api_key' in Secrets Manager / SecretStore.`
      (NOT a stack trace from inside a provider SDK, NOT a network error.)

## 4b. Query-based complexity estimator (MO-02 — no keys, no DB)

- [ ] 4b.1 `cd packages/api && uv run pytest tests/test_complexity.py tests/test_complexity_labels.py -q`
      → **Expected:** all pass. Covers: the 32-query labeled robotics fixture
      (the FROZEN estimator spec), a 20-run determinism loop, the
      tunable-without-code proof (changing a config threshold flips the tier),
      empty/whitespace query → STANDARD (safe default, no crash), regex-pattern
      matching ("drifting" hits `\bdrift(s|ing|ed)?\b`, "adrift" doesn't),
      cross-domain breadth → HARD, keyword-repetition not stacking score, and
      the MO-02b adversarial/phrase-variant suites (4c below).
- [ ] 4b.2 Spot-check tier resolution by hand:
      `    cd packages/api && uv run python -c "
from solus_api.orchestration import estimate_complexity, load_orchestration_config
est = load_orchestration_config().estimator
print(estimate_complexity('what pin is PWM on an Arduino Nano', config=est))
print(estimate_complexity('why is my SLAM drifting when the robot turns', config=est))
print(estimate_complexity('', config=est))"`
      → **Expected:** `trivial`, `hard`, `standard` (in that order).
- [ ] 4b.3 Gateway resolution order (`tests/test_gateway.py`, part of 4.1):
      explicit `complexity` arg beats a supplied `context`, which beats the
      query-text estimator; with neither, the estimator picks the tier.
- [ ] 4b.4 Tunability without code: edit `packages/api/src/solus_api/orchestration/models.yaml`
      → under `estimator:` change `trivial_max_words` to `2`, rerun 4b.2
      → **Expected:** first line becomes `standard` (the 8-word query no longer
      qualifies as trivial). Revert the edit; rerun 4b.1 to confirm green again.
- [ ] 4b.5 Label review (HUMAN step, not Cowork): Pratham reviews
      `packages/api/tests/fixtures/complexity_labels.py` — the labels ARE the
      estimator spec. Disagreements are fixed by editing the label and
      re-tuning the yaml knobs, never code.

## 4c. MO-02b — catalog rebuild, breakpoint pricing, estimator robustness

- [ ] 4c.1 Adversarial lookalikes (part of 4b.1's run): "currently", "framework",
      "wireless", "escape", "ARM processor", "arm64", "powerful" must NOT fire
      the current/frame/wire/esc/arm/power markers. Spot-check:
      `    cd packages/api && uv run python -c "
from solus_api.orchestration import estimate_complexity, load_orchestration_config
est = load_orchestration_config().estimator
print(estimate_complexity('why is my arm64 build currently failing in CI', config=est))"`
      → **Expected:** `standard` (NOT `hard` — no false cross-domain).
- [ ] 4c.2 Phrase-variant equivalence: "why is my servo not working" /
      "why doesn't my servo work" / "why won't my servo turn" /
      "why isn't my servo responding" all print the SAME tier (`hard`).
- [ ] 4c.3 Plain lookups reach the cheap tier: "how do I turn on the LED" →
      `trivial` (phrasing is no longer a complexity signal).
- [ ] 4c.4 Trivial visual/long-context routing (the cost-inversion + window fix):
      `    cd packages/api && uv run python -c "
from solus_api.orchestration import route, load_orchestration_config, Complexity, RouteType
cfg = load_orchestration_config()
c = route('q', Complexity.TRIVIAL, RouteType.LONG_CONTEXT, config=cfg)
print(c.model_name, c.context_window)"`
      → **Expected:** the Flash-Lite-class model with a ~1M context window
      (NOT a 200K model — a long-but-simple input must physically fit).
- [ ] 4c.5 Breakpoint pricing (part of `tests/test_cost.py`): calls whose
      tokens_in exceed a model's `long_context_threshold_tokens` bill at
      `price_in_long`/`price_out_long`; flat-priced models are unaffected.
- [ ] 4c.6 OpenAI reachability: `models.yaml` carries the GPT-5.6 ladder
      (sol/terra/luna) on bench roles; pointing any matrix cell at
      `openai_frontier`/`openai_mid`/`openai_cheap` is a one-line yaml edit
      (covered by `tests/test_config.py` provider-reachability test).
- [ ] 4c.7 Concurrent test suites (MO-02b Part C): from the SAME checkout run
      `uv run pytest -q` and, simultaneously in a second terminal,
      `SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_b uv run pytest -q`
      → **Expected:** both green, no deadlock. (Different checkouts/worktrees
      isolate automatically via the path-hashed default DB name.)

## 4d. MO-03 — billing, caps, retry (needs Postgres; Redis optional)

- [ ] 4d.1 One-time: `cd packages/api && uv run alembic upgrade head`
      → **Expected:** applies `8d4f2a91c6e3` (credit_ledger.call_id unique
      index + credit_balance.spent_total). Additive — no DB drop needed.
- [ ] 4d.2 `cd packages/api && uv run pytest tests/test_cost.py tests/test_gates.py tests/test_reconcile.py tests/test_gateway.py -q`
      → **Expected:** all pass. Covers, among others, the four billing gates:
      debit == compute_call_credits exactly (with audit attrs + balance_after);
      SAME call_id twice AND two concurrent debits → exactly ONE ledger row
      (constraint-based idempotency); debit failure → user still gets the
      result, payload enqueued to reconciliation (replay never double-debits);
      trial cap blocks with the upgrade error / paid users gate on balance;
      frequency cap blocks with the transient error and recovers after the
      window; provider 429s retry with doubling backoff, exhaust cleanly, and
      never retry after the first streamed chunk; gate order is
      frequency → spend → call → debit; streaming final usage is what lands
      in the ledger.
- [ ] 4d.3 Distinction check (messages): the frequency-cap error says "try
      again in a moment" (transient, retryable); the trial-cap error says
      "Free trial usage limit reached — upgrade to continue" with
      `/settings/billing`. They must never be swapped.
- [ ] 4d.4 Redis behavior: with `SOLUS_REDIS_URL` unset the frequency cap
      FAILS OPEN and logs a "fail-open" warning per call (confirmed policy);
      with Redis up (docker-compose `redis:7`), keys `solus:freqcap:<user_id>`
      appear with a TTL.
- [ ] 4d.5 Overshoot semantics (by design, Q9): a trialing user just UNDER the
      cap can run one call that lands past it (billed actual); the NEXT call
      blocks. No cost pre-authorization exists.
- [ ] 4d.6 Identity gating (SECURITY, read before wiring any route): calls
      without `user_id`+`session` skip gates AND billing — library/dev only.
      Any HTTP exposure must pass the authenticated identity plus `redis` and
      `enqueue`. Circuit breakers + query-length bounds are still TODO at
      route-exposure time (gateway.py docstring).

## 4e. MO-04 — classify preview + per-call override (API + desktop)

- [ ] 4e.1 `cd packages/api && uv run pytest tests/test_type_estimator.py tests/test_type_labels.py tests/test_resolution.py tests/test_orchestration.py -q`
      → **Expected:** all pass. Covers the type estimator (26-label fixture,
      LONG_CONTEXT > VISUAL_LOG > CODE > GENERAL precedence, chain rungs), the
      shared resolution (both window-guard branches, escalation), and the
      classify endpoint (auth, viability options, no side effects, and the
      PREVIEW-DOESN'T-LIE matrix: classify(x) == complete(x)'s model exactly).
- [ ] 4e.2 Endpoint by hand (needs the API running + a bearer token):
      `POST /api/v1/orchestration/classify {"query": "fix this traceback from my ROS node"}`
      → **Expected:** `data.type == "code"`, a model name/provider, sources
      `estimator`, options with per-value `viable`/`reason`, `tokens_estimate`.
      Repeat rapidly: never a provider call, never a ledger row, its own
      X-RateLimit-Limit (600/min default) separate from the global budget.
- [ ] 4e.3 Desktop (scripted send unchanged): `cd apps/desktop && npm test` and
      `npm run typecheck` → green. In the app: type in the SOL composer →
      after a ~400ms pause a MUTED one-line indicator appears under the input
      (`standard · code · claude-sonnet-5`) — subtle, ignorable, no banner.
      Click it → small popover; pick `hard` → indicator shows `hard (you)`;
      non-viable options are dimmed with a tiny one-line reason ("Too many
      tokens for this tier (340K > 200K)"); `reset to estimate` restores.
      Send → the override is gone for the next message (this-call-only).
      Kill the API → indicator silently disappears; sending still works.
- [ ] 4e.4 Window guard (library-level, part of 4e.1): a user-overridden tier
      that can't hold the request is REFUSED with the short reason (adapter
      never called, never silently escalated); a system-routed miss ESCALATES
      within the role family and logs; nothing ever silently truncates.
- [ ] 4e.5 Label review (HUMAN): `packages/api/tests/fixtures/type_labels.py`
      — the 26 type labels ARE the estimator spec; re-tune the
      `type_estimator:` yaml section if you disagree (never code).

## 5. Live smoke (OPTIONAL — spends real money, needs a key)

- [ ] 5.1 With an Anthropic key:
      `SOLUS_LIVE_ANTHROPIC_KEY=sk-... uv run pytest -m live packages/api/tests/test_live_smoke.py -q`
      → **Expected:** the anthropic test passes (real completion, nonzero
      token counts); google/openai tests skip.
- [ ] 5.2 (If a Google key is available) `SOLUS_LIVE_GOOGLE_KEY=...` similarly
      → **Expected:** the google test passes and reports `provider == "google"`
      via the VISUAL_LOG route.
- [ ] 5.3 Without any env keys: `uv run pytest -m live -q`
      → **Expected:** 3 skipped, 0 failed (the gate holds).

## Edge cases & failure paths already covered by automated tests

(verify via 2.1; listed for awareness)

- Streaming yields tokens AND exposes final `tokens_in`/`tokens_out` after close.
- Cost hook fires exactly once, only after stream close, only when caller
  identity (user_id + session) is present; the MO-03 `track_cost` stub raising
  `NotImplementedError` never breaks a served completion.
- Abandoned stream (consumer stops early): no cost hook, `completion is None`,
  a structured warning is logged.
- Mid-stream provider failure surfaces as `ProviderError`; unknown provider in
  config surfaces as `UnknownProviderError`.
- Provider switchability: which adapter is dispatched follows the config only
  (test swaps anthropic/openai/google for the same role with zero code change).

## Cross-feature interactions

- None yet by design: no HTTP route exposes the gateway (deliberately deferred
  until MO-03 lands rate limiting/budgets — see the §7 deferral marker at the
  top of `packages/api/src/solus_api/orchestration/gateway.py`).
- SecretStore reuse: keys live in the same store the connector work uses
  (AWS Secrets Manager prefix `solus/connectors/` in prod).

## Known deferrals (do NOT file as bugs)

- (fixed in MO-03) `track_cost` / `has_sufficient_credits` / `account_spend`
  are real; retry/backoff, the trial spend cap, and the frequency cap are live.
  Still deferred to route-exposure work: per-provider circuit breakers,
  query-length bounds, and requiring identity (see 4d.6). Trial-EXPIRY
  consequences and Stripe/billing remain out of scope by ticket.
- The estimator is heuristic by design (no ML, no model call): it reads
  length, tool-need/diagnostic keywords, and domain breadth. Queries it cannot
  classify land on STANDARD deliberately.
- (fixed in MO-02b) models.yaml now carries the GPT-5.6 ladder on bench roles
  and Gemini 3.x-class models (ADR-029), with IDs/prices verified 2026-07-11;
  `gemini-3.1-pro-preview` is the live ID until Google's GA rename, and the
  terra/luna context windows are family-assumed (marked UNVERIFIED in yaml).
