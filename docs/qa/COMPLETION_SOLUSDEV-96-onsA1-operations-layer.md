# Completion Report — SOLUS-ONS-A1: Onshape operations layer + read/query tools

**Status:** built, verified, on `SOLUSDEV-60/ons-a1-operations-layer`. Ends at the per-ticket gate.

## What this is

The first half of the "full Onshape MCP server": the operations SOL uses to *understand* Onshape.
Reads and queries only — writes land in A3 behind the confirmation flow A5 must build first.

## Two design decisions worth reviewing

**1. `InProcessTool`s, not `MCPTool`.** `MCPServerSpec` enforces `command` XOR `url` and
`_open_session` knows only stdio and streamable-http — there is no in-process transport, and adding
one would mean editing a security-reviewed module's core contract to gain nothing. `Tool` is a
Protocol, so `InProcessTool` already *is* "Python tools behind the same registry path", inheriting
JSON-Schema arg validation, the registry timeout, the never-raises envelope and
`confirmation_refusal` for free.

This serves the spec's actual requirement — *"keep the tool interface separable from the transport"*
— better than `MCPTool` would: `connectors/onshape_ops.py` has **no transport at all**. The same
functions can back a stdio/HTTP server later, or sit on top of Onshape's official server if it ships.

**2. `mcp_servers.ONSHAPE` deleted, not extended.** It was a streamable-http spec against
`mcp.onshape.com` gated on an **API key pair** — a credential that authenticates the *developer*,
not the customer, and so can only ever reach our own documents. It also pointed at a server Onshape
has announced but not shipped. The module docstring now records why Onshape is absent from the
catalog and where it lives instead. Two tests that used it as a keyless url-transport fixture now
use a purpose-built `URL_SPEC` — what they actually exercise is the keyless gate, not a vendor.

## What was built

- **`connectors/onshape_ops.py`** — eight transport-free operations over an authenticated client:
  `list_documents`, `list_elements`, `get_feature_tree`, `get_feature_specs`, `get_body_details`,
  `get_mass_properties`, `get_assembly_definition`, `get_variables`. Each is an `OnshapeOperation`
  (frozen) carrying its own JSON schema, so the catalog is data rather than a hand-maintained table.
- **`agent/tools/onshape_tools.py`** — binds each operation to ONE project and resolves credentials
  **per call**.
- **The connector's HTTP layer is now public**: `http`, `request`, `get_json`, `post_json`,
  `default_workspace`, plus `ONSHAPE_ID_RE`. Rename-only — one auth path, not two.
- `build_sol_registry` gained `connectors`; both `routers/sol.py` call sites pass it.

## The seam this proves

**A tool call is not a sync**, so the sync path's credential resolution does not apply. The chain is
project → the connected Onshape `Source` → its `secret_ref` → `resolve_credentials` →
`call_with_refresh` — the same refresh-once-and-retry machinery `/selectable` uses. Onshape tokens
live 60 minutes, so an expired token mid-tool-call is ordinary, not an error; a test proves the
refresh fires and **both** rotated tokens are persisted.

Resolution happens **per call, not at build time** — tools are constructed once per request but a
token can rotate inside it. Pinned by `test_credentials_are_resolved_per_call_not_cached_at_build`.

## Security posture

- **Tenant scope is constructor-bound** (the `get_entity` idiom): `project_id` is a closure
  variable, never an argument. A source in another project is `NOT_FOUND`, not a permission error —
  no existence oracle. Pinned by `test_another_projects_onshape_source_is_never_reachable`.
- **No operation accepts** `project_id`/`team_id`/`user_id`/`source_id`/`secret_ref`, and none
  accepts a token. Both asserted as invariants across the whole catalog, so a future operation
  cannot quietly add one.
- Every model-supplied id is validated against the connector's **own** `ONSHAPE_ID_RE` before URL
  interpolation — one definition of a valid id, not a second weaker gate.
- Upstream error text and the access token never reach a tool error (asserted).
- `additionalProperties: false` on every schema, so an extra key is `INVALID_ARGS` from the registry
  before a handler runs.
- **Fails closed**: no secret store ⇒ zero tools registered, rather than tools that always fail.

## Verification

- `ruff check .` clean · `mypy` clean over **all 11 changed files** (src and tests)
- `uv run pytest -q` — **1459 passed, 4 skipped** (was 1387)
- 40 new tests: 23 operations · 17 tool layer
- Single alembic head unchanged; no migration.

## Deliberate scope limits

- **Read-only.** Every operation asserts `requires_confirmation is False`; A3 adds writes.
- **STEP/STL export is not a tool yet.** The plan listed it here, but it is a long-poll translation
  the connector already performs for ingestion, and exposing it as a synchronous tool wants the same
  bounded-poll treatment the write path will need. Moved to A3 — flagged rather than silently dropped.
- **The `_default_workspace` auto-resolve costs one extra GET** per element read. Cheap and it
  removes a whole class of model error (supplying a workspace id it never saw).

## Owed live confirmation

The payload shapes in `tests/fixtures/onshape_sample.py` come from Onshape's public OpenAPI spec,
not a live tenant. Each constant names the endpoint it stands for so the confirmation run is
mechanical. **Accurate status: operations and the credential seam complete and proven against
documented payload shapes; live confirmation owed.**
