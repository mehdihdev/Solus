# COWORK_QA_foundation_path.md — SOLUSDEV-89 / SOLUS-FND-09 Foundation Integration Checkpoint

QA + sign-off plan for the foundation integration gate: prove the whole foundation path works
end-to-end (signup → team → invite+accept → project → a credited op) before Integrations work
begins. Written to be self-sufficient: you need a terminal with this repo checked out.

The automated proof of this gate is `tests/e2e/foundation_path.py` (pytest + httpx). This file is
the human-facing walkthrough and the **go/no-go readout** — including the one part of the gate
that is currently **blocked** (see the ⛔ section).

## Setup (required state)

**Option A — in-process (fastest; what CI runs):**

1. From the repo root: `uv sync --all-packages`.
2. `uv run pytest tests/e2e/foundation_path.py -v`. No server, DB, or accounts needed — the
   harness builds the app against in-memory SQLite and mints local JWTs.

**Option B — against deployed staging (the ticket's target environment):**

1. Staging must be reachable (ECS service auto-deployed on merge to main). Have its base URL.
2. Because Solus runs no signup/login endpoints (ADR-009 — auth is Supabase Auth), create the
   three identities in Supabase and **verify their emails**, then obtain a JWT for each:
   - `ALICE` (team owner), `BOB` (invited member), `CAROL` (outsider, for scope checks).
3. Run:
   ```bash
   SOLUS_E2E_BASE_URL=https://<staging-url> \
     SOLUS_E2E_TOKEN_ALICE=<jwt> SOLUS_E2E_TOKEN_BOB=<jwt> SOLUS_E2E_TOKEN_CAROL=<jwt> \
     uv run pytest tests/e2e/foundation_path.py -v
   ```
   A missing token skips the affected test with instructions rather than fabricating one.

Conventions to confirm on every response: success bodies are `{"data": ...}`; errors are
`{"error": {"code", "message", "details"}}`.

## Flow 1 — Signup/verify → auto-provisioning (ADR-009)

There is no Solus signup endpoint; the Supabase-verified identity's first authenticated call
provisions the Solus user + personal team. This is the Solus-side equivalent of "signup + verify".

- [ ] 1.1 First `GET /api/v1/users/me` (ALICE) → 200; `email` matches; exactly one team with
      `is_personal=true`, `role=owner`, `plan_status="trial"`, `trial_ends_at` set (~30 days out)
- [ ] 1.2 Subscription state is the placeholder trial (real billing is Phase 5 — see ⛔)

## Flow 2 — Team → invite → accept

- [ ] 2.1 `POST /api/v1/teams` (ALICE) → 201; `role="owner"`, `is_personal=false`
- [ ] 2.2 `POST /api/v1/teams/{team_id}/invites` (ALICE, `email=BOB`, `role="member"`) → 201;
      response includes a one-time `token`; `status="pending"`
- [ ] 2.3 BOB first `GET /users/me` (provision), then `POST /api/v1/invites/{token}/accept` → 200;
      `team_id` matches, `role="member"`
- [ ] 2.4 `GET /api/v1/teams/{team_id}/members` (ALICE) → BOB present with `role="member"`

## Flow 3 — Project creation & shared access

- [ ] 3.1 `POST /api/v1/teams/{team_id}/projects` (ALICE) → 201; `team_id` matches
- [ ] 3.2 `GET /api/v1/projects/{project_id}` (BOB, a member) → 200 (shared-team access works)

## Flow 4 — Scope holds (no cross-team leakage)

- [ ] 4.1 `GET /api/v1/teams/{team_id}` (CAROL, non-member) → **404** (no existence leak)
- [ ] 4.2 `GET /api/v1/projects/{project_id}` (CAROL) → **404**
- [ ] 4.3 `POST /api/v1/teams/{team_id}/projects` (CAROL) → **404** (cannot write into others' team)

## ⛔ Flow 5 — Credited model operation (BLOCKED — filed here)

The gate's second acceptance criterion — "run a credited op; credit deducts correctly and
webhook/DB state matches; assert credit ledger + subscription state" — **cannot be verified**:
the metered layer it depends on is **Phase 5 and not yet built/deployed**.

Missing pieces (verified in-repo on the SOLUSDEV-89 base):

- **SOL Agent** (API.md §2.9) — `reasoning/agent/` is an empty stub; no `agent/conversations` route.
- **Credit ledger / usage meter** (§2.14, ADR-018/019) — no credit/usage/budget model or route;
  `core/ratelimit.py`/`config.py` note the budget system is "Phase 5".
- **MO-03 cost tracking** — a listed dependency of this ticket; no cost-tracking code exists.
- **Billing webhook** (`POST /webhooks/billing`) — `[DEFERRED]` per API.md §7.2.2.

`test_credited_model_operation_deducts_credits` feature-detects these endpoints and **SKIPs with a
BLOCKING message** (the forward-looking deduction assertions are already written and activate
automatically once the endpoints exist).

- [ ] 5.1 Run the suite; confirm `test_credited_model_operation_deducts_credits` reports SKIPPED
      with the "metered credit layer not deployed" reason.

**Gate decision:** the foundation path (Flows 1–4) is **GREEN**. The credit half (Flow 5) is
**BLOCKED on Phase 5**. Per the ticket ("Any failure filed as a blocking bug before Jul 1"), this
is the filing. Sign-off options for the two devs:

1. Sign off the foundation path now and gate the credit assertion behind Phase 5 delivery (this
   test lights up automatically), **or**
2. Hold full FND-09 sign-off until Phase 5 (agent + credits + billing) ships, then re-run.

## Sign-off

- [ ] Dev 1: foundation path (Flows 1–4) verified
- [ ] Dev 2: foundation path (Flows 1–4) verified
- [ ] Blocking gap (Flow 5) acknowledged and scheduled with Phase 5
