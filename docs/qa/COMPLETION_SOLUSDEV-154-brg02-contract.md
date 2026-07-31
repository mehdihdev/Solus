# Completion Report — SOLUS-BRG-02-contract: Cloud↔Bridge Channel Design (SOLUSDEV-154 / SOLUSDEV-161)

## What was built

`temp-BRG-02-channel-contract.md` (repo root; human paste target
`docs/contracts/bridge-protocol.md`): the design contract for the cloud↔companion channel —
transport (one outbound `wss://` WebSocket, companion dials out, no inbound port), authentication
(Supabase JWT on the handshake via the existing `decode_token`, server-derived (user, team,
project) scope, zero client-asserted identity), the session model (exact-scope routing invariant,
single-active-session supersede + audit tripwire, two-layer revocation), an 8-frame `{type,data}`
wire protocol carrying the W0-04 `ToolCall`/`ToolResult` shapes verbatim, at-most-once delivery
with cloud-owned timeouts, untrusted-payload hygiene (size caps, ingress redaction, log-hygiene
rules), ADR-019 abuse/cost bounds, a proposed route, a 10-case red-team suite for BRG-02-impl,
and named holes for everything MCP-03/BRG-03 own. **Docs-only diff — no code changed.**

This resolves the BRG-01↔BRG-02 dependency cycle by splitting BRG-02: the **contract** (this,
dependent only on W0-02, which is Done) vs the **impl** (blocked on MCP-03, co-built with BRG-01).

## Epic status: BLOCKED-ON-MCP-03

MCP-03 (SOLUSDEV-157) is unmerged ("Feature Planning"; `~/solus-mcp` has zero commits ahead of
main). BRG-01, BRG-02-impl, BRG-03, and BRG-04 are blocked and were **not** started — no invented
hosting model, no faked progress. The loop resumes when a human reports MCP-03 merged.

## Governing docs consulted

CLAUDE.md §5/§7/§9/§10 · DECISIONS.md (ADR-005, -009, -019; also verified it contains **no MCP
ADRs yet** — flagged) · Jira SOLUSDEV-166 (loop), -160/-161/-162/-163 (BRG-01..04), -157 (MCP-03),
-158 (MCP-04), -73 (W0-02, Done), -80 (W0-09, Done) · `docs/contracts/agent-tool.md` (W0-04) ·
`docs/contracts/connector-interface.md` (W0-05; telemetry-is-not-a-Connector seam) ·
`docs/api/API-implementation.md` (confirmed: no bridge route exists) · code anchors:
`core/security.py`, `core/responses.py`, `core/errors.py`, `agent/tools/shapes.py`,
`agent/stream.py`, `agent/tools/registry.py`, `routers/sol.py` (prefix convention). No
architecture diagram or wireflow exists for the bridge (noted).

## Phase-0 verification results

- `alembic heads` → single head `20af242f48a0`. ✅
- Test DB: `conftest.py` honors `SOLUS_TEST_DATABASE_URL` verbatim; `.env` sets `solus_test_brg`
  — but nothing auto-exports `.env` into pytest (no dotenv in conftest; `Settings(env_file)`
  feeds only app Settings). Bare `uv run pytest` uses the per-checkout hash default
  (`solus_test_cea95ac1`, still worktree-isolated). **Two run-mode gotchas found:**
  (1) injecting the whole `.env` (`uv run --env-file .env pytest`) breaks 3 tests that assert on
  `SOLUS_*` defaults (`test_auto_create_tables_defaults_off`, two `test_secrets.py` cases) —
  export ONLY `SOLUS_TEST_DATABASE_URL` instead; (2) running pytest with CWD at the repo root
  makes `Settings(env_file=".env")` itself load the root `.env`, failing the same secrets tests —
  run from `packages/api` (as CI does). Canonical green run used here:
  `cd packages/api && SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_brg uv run pytest`
  → 1021 passed, 3 skipped.

## Delegated-judgment decisions (recorded per CLAUDE.md §10)

1. **Auth mechanics:** handshake `Authorization` header + close-`4401`-at-expiry + redial,
   over first-message hello auth + in-band refresh. Rationale: token never in URL/logs, one auth
   mechanism, every reconnect re-derives scope (revocation backstop), and BRG-03 requires a
   robust reconnect path anyway. Documented in the contract as a **design-review question** —
   flip it if unbroken hour-plus sessions matter more than the smaller protocol.
2. **Frame envelope:** reuse the SYS-01 `{type,data}` shape with W0-04 payloads verbatim; unknown
   frame types ignored as the extension mechanism; one-integer protocol version.
3. **"Bridge offline" error:** mapped to existing `ToolError(code=TOOL_ERROR, retryable=True)`;
   a `ToolErrorCode.UNAVAILABLE` member is flagged as a contract-change proposal, not added.

## Flags for humans (action needed)

1. **Paste + approve** the contract → `docs/contracts/bridge-protocol.md` (2-approval gate; the
   ticket is human-critical — review §2's auth design-review question explicitly).
2. **Route plan amendment**: `WS /api/v1/projects/{project_id}/bridge` needs adding to
   `docs/api/API-implementation.md` before BRG-02-impl builds it (authority hierarchy #3).
3. **MCP pivot has no ADR** — ratify alongside MCP-03 so the contract can cite it durably.
4. **W0-09 discrepancy**: SOLUSDEV-80 is Done in Jira but `.agent/` + `docs/agent-harness.md`
   exist nowhere in the repo or git history. This loop ran on the operative prior-loop
   conventions; either land the harness files or amend the ticket.

## Test coverage summary

Docs-only change: no new tests (nothing executable shipped). The contract itself specifies the
red-team suite (10 cases) BRG-02-impl must ship. Full existing suite + ruff + mypy --strict run
green on `solus_test_brg` to prove the branch regresses nothing (results in the session report).

## Cowork QA

No `COWORK_QA_*` file: this ticket ships a design document, not a user-facing flow — there is
nothing for Claude Cowork to drive in the running app. The QA surface arrives with BRG-02-impl.
