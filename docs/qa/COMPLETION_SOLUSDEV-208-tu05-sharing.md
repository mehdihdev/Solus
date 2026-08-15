# Completion report — SOLUSDEV-208 (SOLUS-TU-05): sharing / compounding

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Date:** 2026-08-08
**Gate:** TU-06 merged (satisfied). **§7.3 design human-approved in-chat 2026-08-08.**

## What was built

- **`tool_knowledge_observation`** (server-only table, `toolkb/schema.py` + migration
  `b7e4d9f320a1`): one row per (entry, voter) — `knowledge_id` FK (cascade), a salted one-way
  `voter_hash` (NO user/team/project FK), `verdict`. `UNIQUE(knowledge_id, voter_hash)` is the
  anti-ballot-stuffing primitive: one voter, one vote. Mirrors the `data_events` precedent; never
  referenced by any read path (verified — no router/storage/guides touches it).
- **`toolkb/sharing.py`** — the compounding pipeline:
  - `voter_key(user_id)` — salted SHA-256, never the raw id, no FK.
  - `record_observation` — atomic upsert (a voter may change their mind; never counts twice).
  - `tally` — distinct confirm/reject voters.
  - `reconcile_entry` — recount, recompute confidence, set shared-store status as a **pure function
    of the current tally** (order-independent): a non-docs entry is `published` iff `confirms ≥ 2`
    **and** confidence `≥ 0.85`, else `candidate`. Docs entries are vendor-authoritative (votes move
    their confidence for tentative rendering, never their status).
  - `promote_eligible` — batch sweep over candidates (idempotent, order-independent).
- **`toolkb/feedback.py` (TU-08) refactored** to record per **distinct** voter, then reconcile — so
  `confirm_count`/`reject_count` are distinct-voter counts and a single actor can never move an
  entry. **This closes the TU-08 anti-ballot-stuffing flag.**

## Acceptance (met)

- A learning acquired on one install becomes available to others for the same tool+version — via
  promotion to the cross-tenant `published` store (the compounding moment). ✅
- Promotion is **confidence-gated** (≥ 0.85) **and corroboration-gated** (≥ 2 distinct voters). ✅
- Nothing project- or customer-specific can be shared — structurally guaranteed by TU-06; this layer
  only decides _which_ entries share, never _what_ they contain. ✅
- **Red-team invariant tested:** a single voter confirming any number of times stays one distinct
  voter and can never auto-promote.

## Phase-4 security + code review — run and FIXED (adversarial, verified)

Two reviewers over the diff, every finding independently verified. **5 confirmed, all fixed; 1
refuted (upheld my design).**

1. **HIGH — vote-anonymity salt had a source-embedded default.** With a hardcoded default, a
   DB-read attacker who also reads source could recompute `sha256(salt+user_id)` for every user and
   deanonymize votes — voiding the §7.3 promise, violating CLAUDE.md §7 ("no secret defaults in
   source"). **Fix:** removed the source secret; the salt is read from `SOLUS_TOOLKB_VOTE_SALT`, and
   when unset falls back to an **ephemeral per-process random** salt with a loud warning (the
   `secrets_key` degrade-with-warning posture). Deanonymization is impossible in every config; the
   unconfigured cost is only that de-dup doesn't survive a restart (dev-only). Salt rotation resets
   de-dup — documented in-code.
2. **MEDIUM — the promote/demote hysteresis was order-dependent** (a {3 confirms, 1 reject} set
   could stay `published` below the gate if confirms front-ran the reject). **Fix:** status is now a
   pure function of the tally (no hysteresis band); a parametrized regression test asserts both
   arrival orders reach `candidate`.
3. **MEDIUM — lost-update race:** two voters on the same entry could each tally only their own vote
   (READ COMMITTED) and miss a promotion. **Fix:** `apply_feedback` fetches the entry
   `with_for_update=True`, serializing concurrent votes per entry.
4. **MEDIUM — a promotion-gate test asserted inside an `if` guard** on the value it was proving
   (vacuous). **Fix:** concrete `confidence == approx(0.7)` + explicit status assertion.
5. **MEDIUM — no regression test pinned that no `/toolkb` route leaks voter identity.** **Fix:**
   added `test_no_toolkb_route_leaks_voter_identity` (feedback ack is aggregate-only; no `voter_hash`
   / voter / observation field in any response).
6. **Refuted — "docs demote exemption is unconditional":** intentional. Docs entries are
   vendor-authoritative; user votes render them tentative (TU-07) but never un-publish them. Upheld.

## Tests / verification

`tests/toolkb/test_sharing.py` (voter-key salting/opacity, observation dedup, distinct tally,
single-voter-cannot-promote red-team, distinct-voters-promote-to-shared, low-confidence-blocks,
rejects-keep-out, order-independence in both arrival orders, promote_eligible sweep,
already-published-not-reprocessed) + the updated feedback tests. Full toolkb suite **166 passed**;
full `packages/api` suite **1703 passed / 0 failed**; mypy clean.

## Post-merge follow-up fix (config loading)

The salt was initially read via raw `os.environ.get`, but the app loads config through pydantic
`Settings` (`env_file=".env"`) and never bridges `.env` into `os.environ` — so a salt placed in
`.env` was silently ignored and the ephemeral fallback used. Fixed: `sharing._load_vote_salt` now
reads a lane-local `_ToolkbSettings(BaseSettings, env_prefix="SOLUS_", env_file=".env")`, so both
`.env` and a real exported env var are honored, consistent with `connectors/secrets.py`. A
regression test (`test_configured_salt_is_honored_via_env`) pins it.

## Flags / follow-ups (human)

- **Set `SOLUS_TOOLKB_VOTE_SALT`** in **`packages/api/.env`** (the file the API loads — the app runs
  with cwd `packages/api`; the repo-root `.env` is NOT read by the API) or as a real env var /
  Secrets Manager entry in shared/prod. The unconfigured path is dev-only (ephemeral per-process
  salt, loud warning). The app still starts without it, unlike the JWT secret, because sharing is
  not request-critical.
- **Concurrency test:** the `with_for_update` fix is verified by reasoning + the sequential suite;
  a true two-connection concurrency test needs harness support the test DB fixtures don't provide
  today — noted as a follow-up.
- **Gate constants** (`PROMOTE_CONFIDENCE = 0.85`, `MIN_DISTINCT_VOTERS = 2`) are provisional —
  product-calibratable, same as the TU-04 initial-confidence values.
