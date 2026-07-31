# Completion Report — SOLUS-BRG-01 + SOLUS-BRG-02-impl (SOLUSDEV-160/161 on SOLUSDEV-154)

## What was built

**Cloud (`packages/api/src/solus_api/bridge/` + `routers/bridge.py`)** — the channel from the
contract: strict `{type,data}` frames with W0-04 `ToolCall`/`ToolResult` riding verbatim
(invariant enforced at ingress) · ADR-031 allowlist gate (`validate_inventory`; tool namespace
fixed cloud-side; `requires_confirmation` only from `allowlist.yaml`) · session registry keyed by
server-derived `(user, team, project)` (exact-match routing — cross-tenant delivery structurally
impossible) · at-most-once dispatch with cloud-minted wire call_ids, 8+8 in-flight bound,
first-result-wins + §6 secret redaction at ingress, fail-fast on disconnect · 4409 supersede +
`bridge.session_superseded` audit event (stolen-JWT tripwire, both instance ids) · WS route with
header-only bearer auth, hello gate, idle/token-exp/revocation-poll deadlines, WS-scope rate
buckets, full close-code map (4400/4401/4403/4404/4409/4413/4429) · `BridgeTool` (W0-04 kind)
threaded into `build_sol_registry` — a SOL turn's tool set reflects the live companion inventory;
`GET /sol/tools` shows it. The reasoning import graph stays MCP-free (existing isolation test).

**Companion (`packages/companion`, new uv workspace member, no `solus_api` dependency)** —
`discover_servers` with the ADR-031 launch guard (command must resolve inside the integrations
root; symlink/`..` escapes refused) · persistent MCP stdio client sessions per server with
health-ping/restart/reap (PID-file-verified) and scrubbed child env · verbatim inventory
advertising (the cloud is the gate) · dial-out channel with header bearer, hello→hello_ack, 20 s
pings, jittered backoff, close-code policy (4400 stop-"update required" / 4401 refresh+redial /
4403 stop / 4409 stop-no-redial) · at-most-once dispatch mirroring `_map_result` (non-text never
inlined), never buffers across reconnects · `python -m solus_companion` entrypoint with graceful
SIGINT/SIGTERM.

**E2E (`tests/test_bridge_e2e.py`)** — real companion task ↔ real uvicorn WS ↔ real FastMCP
stdio mock: bind + `badschema` gated, `mock.echo`/`mock.add` round-trips through the SOL
registry, `mock.boom` stays a structured failure, `mock.sleepy` hits the cloud-owned timeout with
the late result dropped, companion death → fail-fast "bridge offline".

## Verification

Full suite on `solus_test_brg`: **1112 passed, 3 skipped** (+91 for this iteration: 22 frames /
7 allowlist / 12 service+registry / 5 tool / 17 WS incl. every reachable contract-§9 red-team
case / 53 companion / 1 E2E — companion tests count once). `ruff` clean repo-wide;
`mypy --strict` clean (217 api files + 7 companion files). All work in small `SOLUSDEV-154:`
commits (`fc2b740`..`77b61e9` + this docs commit).

## MANUAL E2E — HUMAN GATE (BRG-01 acceptance)

With Postgres up (`make db-up`) and from the repo root, in three terminals:

1. `SOLUS_SUPABASE_JWT_SECRET=<secret> uv run uvicorn --factory solus_api.main:create_app --port 8000`
2. Generate a real Supabase access token for a user who is a member of a project (or sign one
   with the shared secret). Then:
   `SOLUS_COMPANION_URL="ws://127.0.0.1:8000/api/v1/projects/<project_id>/bridge" \
 SOLUS_COMPANION_TOKEN="<token>" \
 SOLUS_COMPANION_INTEGRATIONS_ROOT="packages/companion/tests/fixtures/mcp_root" \
 uv run python -m solus_companion`
3. `curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/projects/<project_id>/sol/tools`
   → `mock.echo` listed; then POST a SOL message that invokes it (or drive
   `build_sol_registry(...).invoke(ToolCall(tool="mock.echo", args={"text": "hi"}))` from a
   `uv run python` shell) → `{"result": "hi"}` returns through the live socket.

## Delegated-judgment decisions / deviations (all flagged, none silent)

Listed in `temp-API-bridge-route.md` §"Deviations": TOOL_ERROR-for-offline until UNAVAILABLE is
ratified (BRG-03) · 4429 for the team cap · 4409 no-auto-redial · 15 s revocation poll (Redis
push seam documented) · unverified exp re-decode. Plus: in-memory single-instance session
registry this cycle (Protocol seam for Redis, `graph/buffer.py` pattern) · companion parses only
the `server:` field of allowlist.yaml (stdlib, no yaml dep; the cloud does full validation) ·
the confirmation gate (`requires_confirmation`) remains declared-but-unenforced platform-wide —
descriptors carry the flag; the central gate is still the documented hole it was before BRG.

## Human actions

1. Paste `temp-BRG-02-channel-contract.md` → `docs/contracts/bridge-protocol.md` (still pending
   from iteration 0) **plus** `temp-API-bridge-route.md` (§1 → docs/api, §2 → .gitlab-ci.yml one
   mypy line, §3 → the hello-inventory addendum + deviations review). Delete temp files.
2. Run the MANUAL E2E gate above.
3. Ratify ADR-031 (still "proposed") — this implementation builds on it.
4. 2-approval review of the integrated branch (no push/MR performed by the loop).
