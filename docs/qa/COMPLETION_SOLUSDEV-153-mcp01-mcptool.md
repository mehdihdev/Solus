# Completion Report — SOLUSDEV-153 / MCP-01: MCP tools as the W0-04 `MCPTool` kind

**Status:** built, integrated, hardened, verified. Awaiting human review (2-approval gate).
**Branch:** `SOLUSDEV-153-mcp-foundation` (sub-branch `SOLUSDEV-153/mcp-01-mcp-tool`, merged and deleted).

## Governing docs followed
`docs/contracts/agent-tool.md` (W0-04 — Tool protocol, four shapes, §5 never-raises invariant, §6
security), CLAUDE.md §7 (model-orchestration security), ADR-010 (agent = orchestrator of validated
tools), ADR-028 (contracts human-owned — `agent-tool.md` untouched).

## What was built
- `packages/api/src/solus_api/agent/tools/mcp_tool.py` — `MCPServerSpec` (frozen; exactly one
  transport: stdio or streamable-http; `required_secrets` = SecretStore KEY names;
  Solus-authored `requires_confirmation`), `MCPTool` (Tool-protocol impl, per-call session,
  never-raises mapping), `discover_mcp_tools` (timeout-bounded, failure-mapped, untrusted-input
  gates). The `mcp` SDK (**pinned `mcp>=1.28.1,<2.0`, resolved 1.28.1**) is imported ONLY here.
- `packages/api/src/solus_api/agent/tools/mcp_servers.py` — keyless-safe `ONSHAPE` /
  `WEB_SEARCH` specs (URLs/commands provisional pending MCP-03).
- `packages/api/src/solus_api/agent/tools/registry.py` — Phase-4 defense-in-depth: a schema
  failure during arg validation returns `ToolResult(tool_error)` instead of escaping (the
  registry's own documented invariant; no contract change).
- Mock MCP server fixture (real protocol, FastMCP over stdio, canned tools incl. binary-content
  and PID-file support) + 23 tests in `packages/api/tests/test_mcp_tool.py`.

## Gates proven by tests
- **Zero-knowledge call site:** parametrized test runs identical registry-level assertions for an
  `InProcessTool` and the MCP echo tool; a fresh-interpreter test proves importing
  `solus_api.agent.runtime` leaves `mcp` out of `sys.modules`.
- **Never-raises across the wire:** dead server → `tool_error` retryable; server `isError` →
  `tool_error` (text capped); hang → registry `timeout`; bad args → `invalid_args`; `$ref` schema
  through the registry → `tool_error`, never an escape.
- **Keyless-safe:** ONSHAPE/WEB_SEARCH with empty SecretStore → `unauthorized`, message names the
  keys + "SecretStore" (mirrors MO-01 `ProviderCredentialsMissingError`); connection provably
  never attempted; secret values never in descriptors/results/errors.
- **Red-team (CLAUDE.md §7):** injection-shaped/oversized names skipped; oversized and
  `$ref`-bearing schemas skipped; binary content never inlined; timed-out stdio child reaped;
  discovery bounded and failure-mapped.

## Verification
`ruff` clean · `mypy --strict` clean (fresh cache) · full suite **1055 passed, 3 skipped** on
`solus_test_mcp` · integrated diff reviewed by fresh-context code-reviewer, security-reviewer,
and python-reviewer; CRITICAL/HIGH/MEDIUM findings fixed in `cad7dad` (see below).

## Delegated-judgment decisions
Name qualification `{server}.{tool}`; per-call session (ponytail: pool when latency matters —
note the stdio shutdown adds ~2s SIGTERM grace past a timeout); `structuredContent` passthrough
else text-only content blocks; broad transport catch kept retryable=True (anyio exception shapes
vary) with full traceback to server log; discovery also credential-gates before connecting;
`requires_confirmation` is a blanket per-server flag (server `destructiveHint` untrusted, ignored).

## Flagged for humans (not fixable in this ticket)
1. **`docs/contracts/agent-tool.md` is now stale** (human-owned). Proposed edit for your paste:
   §2 kind table row `RemoteTool / MCPTool` status `Future` → `Built (MCP-01)`; §10 line
   "MCP / Desktop / Environment tool kinds — Documented, not built." → "MCP — built (MCP-01);
   Desktop / Environment — documented, not built."
2. **Tenant scoping of MCP credentials** (review HIGH, design-level): `required_secrets` are a
   flat/global SecretStore namespace. Before any SOL-loop wiring registers MCP tools per request,
   the keys must become per-team-scoped (mirror `get_entity`'s constructor-bound scope). Noted in
   the module docstring.
3. **Credential delivery is unbuilt by design** — presence checked, values never leave the store.
   The secret→server delivery seam lands with MCP-03/MCP-05 and needs its own security review.
4. **`npx` not pinned** (`TODO(MCP-03)` in code) — unreachable today (credential gate precedes
   spawn); MCP-03 vendoring must pin the launcher path.
5. **ArtifactRef plumbing**: non-text MCP content is stubbed (`inlined: false`), not yet persisted
   as real `ArtifactRef`s — follow-on when the artifacts wiring exists.
6. Residual untrusted surface: schema STRING LEAVES (titles/enums) are size-bounded, not
   sanitized; they reach the model as tool metadata.

## Deviations
- Phase-4 hardening tests were written after their fixes (reviewer-specified), not TDD-first —
  chosen to keep H8/H9 hooks green through the batch; original ticket tests were TDD-first.
- Worker note: one intermediate local commit was `--soft`-reset (unpushed, unseen) before the
  final coherent commit.
- Epic-level `COWORK_QA_mcp-foundation.md` lands at epic close (H11 advisory acknowledged).

## Commits
`48296d7` (ticket) · `66a05f9` (integration merge) · `cad7dad` (Phase-4 hardening).
