# Completion Report — SOLUSDEV-153 / MCP-02: LiveConnection formalization

**Status:** built, integrated, verified. Awaiting human review (2-approval gate) **and one human
paste** (see below).
**Branch:** `SOLUSDEV-153-mcp-foundation` (sub-branch `SOLUSDEV-153/mcp-02-live-connection`,
merged and deleted).

## Governing docs followed
`docs/contracts/connector-interface.md` (W0-05 §1 — LiveConnection documented sibling, §2
credential channel), `docs/contracts/sol-interface.md` (W0-07 §4 — windowed telemetry shapes,
reused never redefined), ADR-029 (telemetry untrusted), ADR-030 (boundary: live runtime data
never rides the Connector sync path), ADR-028 (contracts human-owned → temp-file doc).

## What was built
- `packages/api/src/solus_api/connectors/live.py` — `LiveConnection` ABC (exactly the four
  contract operations: `subscribe` / `on_batch` / `unsubscribe` / `status`), `LiveStatus`
  StrEnum (disconnected / connected / streaming), `NoopLiveConnection` roster placeholder with a
  test-only `feed()`. Payloads are the W0-07 `TelemetryWindowSummary`, imported from
  `solus_api.agent.interfaces` — **batch-summarized windows only, no raw-sample surface exists**.
- `packages/api/src/solus_api/connectors/live_conformance.py` —
  `assert_live_connection_contract`, package-importable, mirroring `assert_connector_contract`,
  including the **mechanical Pattern-2 guard**: an implementation that grows a Tool surface
  (`descriptor` + `invoke`) FAILS conformance with a message citing the rule. Proven able to
  catch a Tool-shaped impl, a leaky unsubscribe, and raw-sample payloads.
- `packages/api/tests/test_live_connection.py` — 11 tests (TDD-first, red confirmed).
- **`temp-MCP-02-live-connection.md` (repo root) — HUMAN ACTION REQUIRED:** written as the final
  contract doc; please review and paste to `docs/contracts/live-connection.md`. Xrefs CON-03,
  LB-01, LB-02, LNK-06, LB-06, W0-04/05/06/07, ADR-029/030.

## Hard rule status
Telemetry is Pattern 2 and is NOT forced through an MCP tool interface — enforced three ways:
`live.py` imports nothing MCP (tested by source scan), the conformance suite rejects Tool-shaped
implementations, and the contract doc states the rule normatively. No drift occurred.

## Integration fix (post-merge)
The eager `live` re-export in `connectors/__init__.py` closed an import cycle
(connectors ← agent.interfaces ← live) that broke a bare `import solus_api.agent.runtime` —
caught by MCP-01's import-graph gate test on the integrated branch only (each worktree alone was
green). Fixed in `b99d6f8`: `live` / `live_conformance` are imported directly, mirroring the
`mcp_tool` import-isolation decision; rationale documented in the package `__init__`.

## Verification
`ruff` clean · `mypy --strict` clean · full suite **1055 passed, 3 skipped** on `solus_test_mcp`
· fresh-context code-reviewer + security-reviewer + python-reviewer passes on the integrated
diff (no findings against MCP-02 beyond the cycle fix above).

## Delegated-judgment decisions
Status enum values + conformance-checkable semantics (active subscription ⇒ not disconnected;
delivery ⇒ streaming); opaque `str` handles; one callback per handle (re-register replaces; two
consumers = two subscriptions); `subscribe`/`unsubscribe` async, `on_batch`/`status` sync;
`provider: ClassVar[str]` mirroring `Connector`; conformance driven by an `emit` callable; no
custom error type (YAGNI). Credentials: doc states real impls use the W0-05 `secret_ref` channel;
no credential code in this ticket.

## Flagged for humans
1. **Paste `temp-MCP-02-live-connection.md` → `docs/contracts/live-connection.md`** (ADR-028).
2. Hook gaps observed: **H6** blocks markdown containing column-0 `class` lines inside fenced
   code (should probably skip `.md`); **H9**'s test-name heuristic expects `test_live.py` for
   `live.py` (spec fixed `test_live_connection.py`).
3. `.env`-related: hook/Makefile pytest runs use the per-checkout hash DB (nothing exports
   `SOLUS_TEST_DATABASE_URL`); the loop exports it explicitly. Also `test_secrets.py` was made
   hermetic to `.env` (`4f37fad`, pre-existing fragility, not from this epic).

## Commits
`31899e9` + `49eba95` (ticket) · `efd06c0` (integration merge) · `b99d6f8` (cycle fix) ·
`4f37fad` (hermetic test_secrets, orchestrator fix).
