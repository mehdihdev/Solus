# tests/e2e — end-to-end gate tests

Repo-root E2E suites that exercise the API as a black box over HTTP (pytest + httpx). These are
**not** part of the fast unit suite (`testpaths` in the root `pyproject.toml` excludes this
directory), so a bare `pytest` won't pick them up. Run them explicitly.

## foundation_path.py — SOLUSDEV-89 / SOLUS-FND-09

Scripts the foundation path: signup/verify → team → invite+accept → project → credited op, with
subscription-state, credit-ledger, and cross-team-scope assertions.

```bash
# In-process (default): builds the ASGI app on in-memory SQLite, mints local JWTs. Green in CI.
uv run pytest tests/e2e/foundation_path.py -v

# Against deployed staging: hits a live URL with real Supabase JWTs (ADR-009 — no signup endpoint).
SOLUS_E2E_BASE_URL=https://<staging-url> \
  SOLUS_E2E_TOKEN_ALICE=<jwt> SOLUS_E2E_TOKEN_BOB=<jwt> SOLUS_E2E_TOKEN_CAROL=<jwt> \
  uv run pytest tests/e2e/foundation_path.py -v
```

Identities: `alice` (team owner), `bob` (invited member), `carol` (outsider — cross-team leak
checks). In staging mode each identity's JWT comes from the matching `SOLUS_E2E_TOKEN_*` env var
(obtained from Supabase after signup + email verification); a missing token skips that test.

The "credited model operation" test **skips with a BLOCKING message** until the Phase 5 metered
layer (SOL Agent §2.9, credit ledger §2.14 / ADR-018/019, MO-03 cost tracking) is deployed. See
[`docs/qa/COWORK_QA_foundation_path.md`](../../docs/qa/COWORK_QA_foundation_path.md) for the gate
readout and the blocking-gap filing.
