# Cloud↔Bridge Channel — Contract (SOLUS-BRG-02, SOLUSDEV-161)

**Status:** Ratified contract (ADR-032 landing, 2026-07-30) — and IMPLEMENTED: BRG-02-impl
shipped on SOLUSDEV-154 (`solus_api/bridge/` + `routers/bridge.py` cloud-side,
`packages/companion` client-side). Where this document says "resolved by MCP-03/BRG-03", the
resolutions now live in Addendum A (hello inventory, ADR-031 allowlist gate) and Addendum B
(status frames). Implementation deviations are recorded at the end of Addendum A.
**Authority:** CLAUDE.md §7 (WebSocket connect-time auth + project scoping, untrusted device input,
credentials never in logs/model context, central confirmation gate, tenant isolation as the
highest-severity invariant) · W0-02 (SOLUSDEV-73: Supabase-JWT middleware posture + the
`{data,meta,links}` / `{"error":{code,message,details}}` envelopes, API.md §1.4) · W0-04
(`docs/contracts/agent-tool.md`: `ToolCall`/`ToolResult`/`ToolError`, `requires_confirmation`,
`ArtifactRef`) · SYS-01 (`agent/stream.py` `{type,data}` event framing) · ADR-005 (clean seams) ·
ADR-009 (Supabase auth) · ADR-019 (one budget system for security + billing).
**Consumers:** BRG-01 (the companion dials this channel and speaks this protocol), BRG-02-impl
(builds both ends), BRG-03 (rides `status` frames + the offline/online distinction), BRG-04
(bundles the companion that implements the client side), SOL agent orchestration (dispatches
bridge tools through the untouched `ToolRegistry`).

> ⚠ **Unrecorded decisions (flag for the founders):**
> 1. The MCP pivot itself (Pattern-1 tools = forked, owned MCP servers on the user's machine) is
>    stated across the MCP/BRG tickets but **is not yet an ADR**. Ratify alongside MCP-03 so this
>    contract can cite it durably (same situation `connector-interface.md` flagged for ADR-030).
> 2. The route this contract proposes (§8) **does not exist in `docs/api/API-implementation.md`**.
>    Per the authority hierarchy (docs/api is designed before implementation), it requires human
>    approval before BRG-02-impl builds it.
> 3. W0-09's harness deliverables (`.agent/`, `docs/agent-harness.md`) are absent from the repo
>    although SOLUSDEV-80 is marked Done — this contract was produced on the operative loop
>    conventions instead (completion reports in `docs/qa/`, `temp-*` human-paste files).

---

## 1. Scope and posture

This contract defines **how the cloud backend talks to a user's local companion process**: the
transport, authentication, session model, wire frames, delivery semantics, and the security
obligations of both ends. It covers **MCP tool calls only**. Telemetry is Pattern 2 and **never**
rides this channel — live sensor/robot data keeps its own isolated seam (`LiveConnection` /
telemetry packet contract, ADR-005; see `connector-interface.md` §1).

Posture in one line: **the companion is an untrusted client on an untrusted machine.** Every
guarantee below is enforced cloud-side; nothing depends on the companion binary behaving. A
malicious binary, a compromised local MCP server, or a stolen token must all be survivable with
bounded damage (§3, §6, §9).

## 2. Transport and authentication

**Transport:** one outbound **`wss://` WebSocket**, dialed by the companion to the backend.

- The companion always initiates — **no inbound port on the user's machine, ever** (AC-1;
  NAT/firewall-safe with zero user configuration).
- Plain **JSON text frames**. Both ends validate with Pydantic v2 (the companion may be a Node
  peer per BRG-04 — plain JSON is the constraint that keeps that open). No gRPC, no protobuf, no
  broker (locked stack).
- FastAPI/Starlette WebSocket support is native; App Runner/Fargate pass WebSockets. CLAUDE.md §7
  already legislates the discipline for exactly this transport: *"WebSocket connections
  authenticate at connect time and are scoped to a team's project."*
- Rejected: SSE + HTTP-POST pair (two half-channels, two auth points, hand-rolled correlation);
  long-poll (a WebSocket rebuilt badly); anything binary/brokered (banned deps, no need).

**Authentication (recommended: header at handshake, redial at expiry):**

- The companion sends `Authorization: Bearer <Supabase access JWT>` on the WS upgrade request. It
  is a native process — headers work; **the token never appears in the URL**, so it can never land
  in ALB/App Runner access logs (AC-4). The server MUST ignore any token supplied as a query
  parameter (tested, §9).
- The backend verifies the token with the **existing** `decode_token`
  (`packages/api/src/solus_api/core/security.py` — JWKS verification, alg-confusion pinned) and
  derives **(user, team, project) scope server-side from DB memberships**, exactly the W0-02
  posture. Client-asserted `user_id`/`team_id` anywhere in any frame are **ignored** (AC-2).
  Auth failure → close `4401`; the user not being a member of the requested project → close
  `4404` (mirrors the existing "non-member gets 404, no existence leak" API convention).
- **Token expiry mid-session:** the server records `exp` at bind and closes the socket `4401`
  when it passes. The companion redials with a fresh access token (it refreshes against Supabase
  directly — the **Supabase refresh token never transits the bridge** and the cloud never sees,
  stores, or logs it). Every reconnect is therefore a **full re-auth + scope re-derivation**,
  which doubles as the passive revocation backstop (§3). BRG-03 mandates a robust
  reconnect/resync path anyway; expiry simply exercises it on a schedule.
- **Design-review question (humans may flip this — the ticket is human-critical):** the rejected
  alternative is first-message `hello` auth plus an in-band `auth` refresh frame, which keeps one
  session unbroken across the ~1 h token life. Cost: two more frame types, a pre-auth socket
  state, and a grace-window state machine. Benefit: in-flight calls are not failed at expiry —
  but those losses are already bounded by the 30 s default tool timeout and surface as
  `retryable` errors SOL knows how to handle. This contract prefers the smaller protocol.

## 3. Session model

**What the server binds** (server-side record; nothing here is client-settable except as noted):

| field | source |
|---|---|
| `session_id` | server-generated |
| `user_id` | `TokenClaims.sub` from `decode_token` — only |
| `team_id`, `project_id` | server-verified from DB memberships for the project named at connect |
| `companion_instance_id` | companion-generated stable UUID — **routing/dedup/telemetry only, never authorization** (an untrusted client can fabricate it) |
| `connected_at`, `token_exp`, `protocol_version` | recorded at bind |

Scope is **fixed for the session's lifetime**. Switching project = a new socket. One socket = one
project scope; a companion working two projects opens two sockets (see §11 — no multiplexing).

**Routing invariant (the AC-2/AC-3 core):** a tool call carries its scope from the *cloud-side
request context* (the authenticated SOL turn that produced the `ToolCall`), never from any wire
message. Dispatch requires **exact match** on the session's server-bound
`(user_id, team_id, project_id)`. No fallback session, no "closest match", no scope widening —
registry lookups are keyed by bound scope only, so cross-tenant delivery is a bug class, not a
policy knob. A mandatory isolation test proves a team-A call can never reach a team-B session
(§7's highest-severity invariant; §9 case 9).

**No companion connected** → the call fails fast as a W0-04
`ToolResult.failure(call_id, ToolError(code=TOOL_ERROR, retryable=True, message="bridge offline"))`
inside the normal flow — SOL reasons about it like any tool failure. (`ToolErrorCode` has no
`UNAVAILABLE` member today; if BRG-03 needs the machine-readable distinction, adding one StrEnum
member is the sanctioned, wire-compatible extension — **flagged as a contract-change proposal per
CLAUDE.md §9, not silently added here**.)

**Duplicate sessions — single-active-session, newest wins:**

- Same `(user, project, companion_instance_id)` reconnecting → the new session supersedes the old
  (zombie-socket cleanup after network drops). Old closed `4409`.
- Different `companion_instance_id`, same `(user, project)` → newest still wins: old closed
  `4409`, its in-flight calls fail fast (`retryable: true`), and the backend **must emit a
  `bridge.session_superseded` audit/data-collection event carrying both instance ids**. A
  legitimate laptop swap and a stolen-JWT attacker connect look identical on the wire — the event
  is the tripwire, and it must be surfaceable to the user.

**Revocation** (logout, team removal mid-session) — two layers, both contractual:

1. *Push:* the membership-change path signals the bridge service (multi-instance Fargate → a
   shared signal; Redis is already in the stack — mechanism is impl, the bound is contract):
   matching sessions close `4403` within **≤ 30 s**.
2. *Backstop:* worst case, revocation lands at the next redial (token expiry, §2). A call
   dispatched to a revoked scope fails `ToolError(code=UNAUTHORIZED)`.

## 4. Wire protocol

Every frame is one JSON text message in the SYS-01 shape — `{"type": "<name>", "data": {...}}` —
cashing `stream.py`'s explicit promise that *"a WebSocket transport could carry the SAME events
unchanged."* `data` carries the **existing W0-04 models verbatim** (`model_dump(mode="json")`):
nothing about a tool call is redesigned, translated, or re-validated differently at the bridge
boundary. A richer envelope (per-frame ids, timestamps, headers) is rejected: correlation already
lives in `ToolCall.call_id`, TCP+WS give ordering, timestamps are a logging concern.

**The whole protocol — 8 frame types:**

| `type` | direction | `data` | when |
|---|---|---|---|
| `hello` | companion → cloud | `{"protocol_version": int, "companion_version": str}` + the local MCP-server/tool inventory: **payload hole, resolved by MCP-03** | First frame after the socket opens. |
| `hello_ack` | cloud → companion | `{"protocol_version": int}` | Reply to a valid `hello` — the companion's definite "registered" moment (the BRG-01 status light / BRG-03 anchor). Silence-as-acceptance rejected: the companion couldn't distinguish "accepted" from "server slow before closing". |
| `tool_call` | cloud → companion | W0-04 `ToolCall` verbatim: `{"tool", "args", "call_id"}` | When SOL dispatches a bridge tool. How `tool` maps to a specific local MCP server: **resolved by MCP-03**. Cloud-side the bridge fills the "RemoteTool/MCPTool — Future" slot already tabled in `agent-tool.md` §2, behind the untouched `ToolRegistry`. |
| `tool_result` | companion → cloud | W0-04 `ToolResult` verbatim: `{"call_id", "ok", "value"\|"error"}` | Exactly one per `tool_call`. The ok/value/error `model_validator` invariant is enforced at ingress — "a malformed result can never reach the model." Large outputs ride an `ArtifactRef` inside `value` (`ArtifactStorage.CLIENT` exists for exactly this), never inlined. |
| `status` | companion → cloud | **Payload hole, resolved by BRG-03** — must be able to express per-tool lifecycle (not-launched / launching / ready / busy) and BRG-01 supervise/health. This contract reserves the type name only. | On state change (BRG-03 defines cadence). |
| `ping` | companion → cloud | `{}` | Every 20 s (§5 liveness). App-level, not WS protocol ping — observable, and Starlette doesn't expose server pings cleanly. |
| `pong` | cloud → companion | `{}` | Immediate reply — how the companion detects a half-open TCP connection and redials. |
| `error` | both | The §1.4 error object from `core/errors.py`: `{"code", "message", "details"}` | Protocol-level failures **not** tied to a `call_id` (malformed frame, frame before `hello`, unsupported version). Tool failures NEVER use this — they are `ToolResult.error` **data** SOL reasons about, not channel errors. |

**Strictness & extension rule:** within a known `type`, `data` validates strictly (Pydantic
`extra="forbid"`, matching W0-04). An **unknown `type` is logged and ignored** by both ends — the
extension mechanism that lets BRG-01/BRG-03 add frames without a version bump or redesign.

**Versioning:** `hello.protocol_version` is **one integer**, starting at `1` (both ends ship from
this repo's release train, companion auto-updated per BRG-04 — no semver, no negotiation). Bump
only for a change an old peer would *mis-handle* (changed/removed fields in a known frame —
`extra="forbid"` makes those breaking). New frame types do **not** bump. Unsupported version →
one `error` frame `{"code": "unsupported_protocol_version", ..., "details": [{"supported": N}]}`
then close `4400`; the companion treats `4400` as "update required" — surface to the user, do not
auto-redial.

**App close codes, complete set:**
`4400` version · `4401` auth/expiry · `4403` revoked mid-session · `4404` non-member/unknown
project (no existence leak) · `4409` superseded · `4413` oversize frame · `4429` rate exceeded.

## 5. Delivery semantics and liveness

- **Correlation:** `ToolCall.call_id` (already `uuid4().hex`). One `tool_result` per `tool_call`.
  A duplicate `call_id` from the cloud is a protocol violation; the companion drops and logs.
- **Timeout ownership: cloud only.** The existing `ToolRegistry` already wraps every invocation in
  `asyncio.wait_for` (`descriptor.timeout_seconds`, default 30 s) producing
  `ToolError(code=TIMEOUT, retryable=True)`. The bridge adds nothing; the companion never enforces
  its own timeout (same rule the tool contract already states). A result arriving after the cloud
  timed out is dropped as an unknown `call_id` and logged.
- **Delivery: at-most-once, no wire-level retry.** A `tool_call` is written once to the live
  socket. Socket death before the result → the cloud fails the call immediately
  (`retryable: true`, "bridge disconnected"); retry policy belongs to SOL via the existing
  `retryable` flag, not to the protocol. No redelivery queue, no persistence.
- **Result acceptance:** a `tool_result.call_id` must match a currently in-flight call **of that
  same session**. Unknown, foreign-session, or already-answered ids → dropped + logged
  (replay/duplication defense). First result wins.
- **Idempotency note:** SOL may re-issue a retryable failure, so bridge tools that mutate local
  state should tolerate re-execution with the same `args`. Destructive actions are already gated
  by `ToolDescriptor.requires_confirmation`, enforced **cloud-side by the orchestrator before
  dispatch** (CLAUDE.md §7) — never delegated to the companion, which could lie.
- **Disconnect, companion side:** cancel in-flight local work best-effort; MUST NOT buffer results
  for delivery after reconnect (a reconnect is a new session; its old calls already failed
  cloud-side — this is also load-bearing for BRG-03's no-duplicate-entities rule).
- **Liveness:** companion `ping` every **20 s** (fixed contract constant — safely under App
  Runner/ALB idle timeouts; no negotiation). Cloud: no frame of any kind for **60 s** → close,
  mark bridge offline. Companion: no `pong` within one interval → assume half-open, close, redial
  (jittered exponential backoff; parameters are BRG-01's concern).
- **The three states BRG-03 needs, at the channel level:** *bridge offline* = no authenticated
  session for the scope (calls fail fast, §3). *Tool not launched / tool busy* = session exists;
  the companion reports via `status` frames and/or per-call failed `ToolResult`s. How the cloud
  caches/surfaces these is BRG-03's spec; this contract only guarantees the channel carries them.

## 6. Payload hygiene — results are untrusted input

Everything arriving on the socket is handled per §7's telemetry rules: parse defensively, bound
sizes, never crash on malformed input. Results additionally **feed SOL model context later**, so
this boundary is also prompt-injection ingress: tool output is DATA to be analyzed, never
instructions to follow, and it flows through the same instruction/data separation the agent layer
already enforces.

- **Schema at the boundary:** every inbound frame validates against the bridge frame schemas;
  `tool_result.data` must parse as the W0-04 `ToolResult` (frozen, `extra="forbid"`, invariant
  validator). Validation failure → frame dropped, structured log (`call_id` + reason only),
  counted against abuse limits; repeated failures → close.
- **Size caps** (contract defaults, config-tunable): control frames (`status`/`ping`/`pong`/
  `error`) ≤ **16 KiB** · `hello` ≤ **256 KiB** · `tool_call` ≤ **256 KiB** · `tool_result` ≤
  **1 MiB**. Oversize → close `4413`; an oversize `hello` carries `error.code = "oversize_hello"`.
  Bulk CAD/EDA output rides an `ArtifactRef`, never inline.

  > **Amendment (SOLUSDEV-252, explicitly approved by the user for SOLUSDEV-260).** `hello` was sized with the other
  > control frames, but it is the only one that grows with the DEPLOYMENT rather than with a
  > message: it advertises every allowlisted tool of every running server, JSON schemas included.
  > Two vendored forks plus the built-in `machine` server measured **22,531 bytes** live, so the
  > 16 KiB cap refused every real companion — and refused it as `expected_hello` → close `4400`,
  > which the companion surfaces as "update required", pointing the operator at a protocol
  > mismatch that did not exist. The socket is authenticated and team-scoped before this frame is
  > read, so the larger bound admits no anonymous traffic.
- **No-secrets rules (AC-4):**
  (a) the companion MUST NOT transmit local credentials, env values, or key material — stated, but
  defense-in-depth only, since the companion is untrusted;
  (b) the **enforced** layer is cloud-side ingress redaction before persistence or context
  assembly: deny-pattern scan over `value` (key names matching
  `token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key`, high-entropy value
  heuristics) with matches redacted;
  (c) `ToolError.message` is "never a traceback" (W0-04) — extended here to **never a local file
  path outside the project workspace, never an env dump**.
- **Log hygiene (AC-4):** cloud logs MAY carry `call_id`, `session_id`, tool name, scope ids,
  status/`ToolErrorCode`, sizes, timings, close codes — enough to answer "why did this user's
  call fail" (§6 debuggability) with zero payload retention. Cloud logs MUST NOT carry `args`,
  `value`, tokens, or raw frame bytes. (The asymmetry is deliberate: `AgentEvent.tool_call`
  streams `args` to the *user's own client* — same tenant; the prohibition is on cloud logs.)

## 7. Abuse and cost controls (ADR-019 hooks)

Contract defaults, config-tunable, enforced by the same budget machinery as billing (build once,
serve both). Rate-limit/budget events are emitted to the data-collection system (§7 abuse
detection).

- Connect-attempt rate limit per user/IP (auth-endpoint rule).
- Per-session inbound rate: **20 msg/s sustained, burst 100** — excess dropped, then close `4429`.
- Frame-size caps per §6, enforced pre-parse.
- **Bounded in-flight calls per session: 8.** Excess queues cloud-side under the same bound;
  overflow → immediate retryable failure (§7 loop-guard: bounded outstanding work).
- Per-call timeout per §5.
- Per-team cap on concurrent bridge sessions (seats + margin) — a stolen-JWT farm cannot register
  hundreds of companions.

## 8. Route surface (requires human approval)

No bridge route exists in `docs/api/API-implementation.md` (its only WebSocket mention is the
telemetry seam). Proposed, matching the existing prefix convention
(`routers/sol.py`: `/api/v1/projects/{project_id}/sol`):

> **`WS /api/v1/projects/{project_id}/bridge`** — project-scoped per CLAUDE.md §7; auth via the
> existing `decode_token`/deps flow; one socket = one project scope.

Not to be built until the route plan is amended and approved (authority hierarchy #3).

## 9. Red-team suite BRG-02-impl must ship

1. Expired/garbage JWT at connect → close `4401`, nothing registered, generic error (no verifier
   internals leaked).
2. `hello`/any frame asserts `team_id`/`user_id` → ignored; bound scope equals server-derived
   scope exactly.
3. Connect naming a project the user isn't a member of → close `4404`, nothing registered.
4. Token in URL query string → not accepted as auth; token string provably absent from all
   captured logs.
5. Second companion connects for the same (user, project) with a (stolen) valid JWT → old session
   closed `4409`, in-flight calls fail retryable, `bridge.session_superseded` emitted with both
   instance ids.
6. `tool_result` with mismatched / foreign-session / already-answered `call_id` → dropped +
   logged, never delivered, never enters model context; duplicate for a live id → first wins.
7. Malformed `ToolResult` (ok=true with error set; extra fields; 2 MiB frame) → rejected at
   ingress (`4413` for oversize), service does not crash, surfaced to SOL only as a structured
   `ToolError`.
8. Membership revoked mid-session → close `4403` within the ≤30 s bound; a call dispatched
   post-revocation fails `UNAUTHORIZED`; token allowed to lapse past `exp` → close `4401`.
9. Cross-tenant isolation: with live sessions for team A and team B, a team-A call is provably
   never dispatched to B's session.
10. Planted secret-shaped value in a `tool_result` → redacted before persistence/context, with a
    log-capture assertion that no `args`/`value` content appears in cloud logs.

## 10. Explicit holes (named, not guessed)

| hole | resolved by |
|---|---|
| `hello` tool/server inventory payload; which tools a companion may host; advertised-descriptor allowlisting | **MCP-03** (until then: companion-advertised anything is untrusted input; the tool namespace available to a SOL invocation is fixed cloud-side per §7) |
| `tool` → specific local MCP server mapping | **MCP-03** |
| Local sandboxing / least-privilege / fork-hardening checklist; companion-binary integrity | **MCP-03** (the security posture here must hold even if that ships nothing) |
| `status` frame payload (tool lifecycle, health cadence, UI surfacing) | **BRG-03** |
| `ToolErrorCode.UNAVAILABLE` member | flagged contract-change proposal (§3) |
| Reconnect backoff parameters | **BRG-01** |
| `ArtifactRef` upload path for companion-side bulk data | **MCP-03 / BRG follow-up** |

## 11. What NOT to build

| excluded | why |
|---|---|
| Multiplexed multi-project sessions | one socket per project keeps auth/scoping identical to every existing route; a second project is a second socket |
| Binary framing (msgpack/protobuf/CBOR) | plain JSON is a hard constraint (Node peer); `ArtifactRef` keeps bulk off the wire |
| Compression negotiation | permessage-deflate is a library default, not contract material |
| Message persistence / offline queueing / redelivery | at-most-once + SOL's `retryable` reasoning covers it; brokers are banned |
| Server-initiated reconnect orchestration | the companion is the dialer and owns reconnection; the cloud accepts and times out |
| Generic RPC framing (frame ids, acks, sequence numbers) | only tool_call/result correlate, via the `call_id` that already exists; TCP+WS order |
| Heartbeat/interval negotiation | fixed constants; two lines to change if ever wrong |
| Capability/tool-inventory schema in `hello` | MCP-03's decision — a named hole, not a guess |
| In-band auth refresh frames | expiry → `4401` → redial with a fresh token reuses the mandatory reconnect path (§2 design-review question if humans prefer unbroken sessions) |

---

## Addendum A — `hello` inventory schema (BRG-01/02-impl; fills §10's MCP-03 hole)

`hello.data`:

```json
{
  "protocol_version": 1,
  "companion_version": "<semverish string>",
  "companion_instance_id": "<stable uuid, client-generated — routing/telemetry only, never authorization>",
  "servers": [
    {
      "server": "<fork name, ^[a-z][a-z0-9_]{0,31}$>",
      "tools": [
        {"name": "...", "description": "...", "input_schema": { }, "output_schema": { } | null}
      ]
    }
  ]
}
```

Rules (all enforced cloud-side at bind, ADR-031): tools are advertised VERBATIM from the fork's
`list_tools()` — the cloud gates each entry against `integrations/mcp/<server>/allowlist.yaml`
(non-allowlisted/unsafe-name/oversized-or-`$ref`/malformed-schema entries are skipped with a
warning, never fatal); `requires_confirmation` comes ONLY from the allowlist — a hello carrying
that field anywhere fails `extra="forbid"` validation; descriptions capped at 500 chars; composed
`{server}.{tool}` ≤ 128 chars. The surviving set becomes the session's inventory and the SOL
turn's `BridgeTool`s.

**Deviations adopted during implementation (review with the paste):**

1. "Bridge offline" currently maps to `ToolError(code=TOOL_ERROR, retryable=true)`; the
   pre-sanctioned `ToolErrorCode.UNAVAILABLE` member lands with BRG-03 (contract-change proposal,
   ratify there).
2. The per-team session cap closes with `4429` (the contract named the cap but no code).
3. A superseded companion (`4409`) does NOT auto-redial — a zombie must not fight its successor.
4. Revocation push is a 15 s per-session membership poll (meets the ≤30 s bound); the Redis
   pub/sub push seam is documented for multi-instance.
5. `token_exp` is read by an unverified re-decode of the already-verified token string
   (`TokenClaims` carries no `exp`; widening `core/security.py` was avoided).

---

## Addendum B — the `status` frame (BRG-03; fills §10's BRG-03 hole)

## The `status` frame (companion → cloud) — BRG-03

```json
{
  "type": "status",
  "data": {
    "servers": [
      {
        "name": "kicad",
        "state": "ready",
        "detail": null,
        "updated_at": "2026-07-23T12:00:00Z"
      }
    ]
  }
}
```

- **Snapshot, never a delta.** Every frame carries the FULL per-server list; the cloud cache is
  the last frame verbatim and dies with the session. Idempotent — no ordering hazards, and a
  reconnect repopulates the cache with the single post-`hello_ack` snapshot.
- **Cadence:** one snapshot immediately after `hello_ack` on every (re)connect; then on any state
  change, coalesced to ≥1 s apart. No periodic resend — `ping` owns liveness.
- **`state` enum:** `not_launched | launching | ready | busy | error`. **Busy is per-SERVER, not
  per-tool**: these servers wrap serialized desktop applications — the process is the concurrency
  unit, and per-tool busy would be fabricated data the companion cannot honestly observe. (If a
  genuinely concurrent server ever ships, a per-tool map is a `protocol_version` bump.)
- **`detail`:** optional, ≤512 chars, §6-hygienic (no tracebacks, no env dumps, no paths outside
  the project workspace). `updated_at` = the server's last transition (ISO-8601).
- **Cloud handling:** strict validation (`extra="forbid"`) — malformed snapshots are dropped
  (violation-counted), the session survives; server `name`s are untrusted and filtered against
  the Solus-owned allowlist roster (unknown names dropped + logged); the surviving snapshot is
  cached on the session. **Dispatch never gates on the cache** — it is advisory, UI-facing; the
  companion is authoritative at call time (a call to a not-launched tool simply returns a
  retryable failed `ToolResult`).

## The three states the backend distinguishes (ticket AC)

| state             | signal                                                                    | surfaced as                                                                                                                              |
| ----------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| bridge offline    | no live session for (user, team, project)                                 | `GET …/bridge` → `connected: false`; a dispatched bridge tool fails fast `ToolError(code=unavailable, retryable=true, "bridge offline")` |
| tool not launched | session live; `status.servers[].state ∈ {not_launched, launching, error}` | `connected: true` + per-server states in the same endpoint                                                                               |
| tool busy         | session live; `state = busy` (per-server)                                 | ditto                                                                                                                                    |

## Read surface (proposed route — pair with the WS route amendment)

**`GET /api/v1/projects/{project_id}/bridge`** — ProjectCtx-scoped (non-member → 404, no
existence leak); **per-user semantics** (the registry is keyed `(user, team, project)` — you see
YOUR companion, not a teammate's; deliberate, documented). Envelope data:
`{connected, companion_version, connected_at?, status_updated_at?, servers: [...]}` (offline:
`{connected: false, companion_version: null, servers: []}`). No DB writes — liveness is ephemeral
by design. The desktop TopBar bridge pill polls this every 10 s.

## Degradation (what BRG-03 ships vs defers)

Shipped: the state surface above; `unavailable` fail-fast; the **no-dupe resync gate**
(`tests/test_bridge_resync.py`) locking that reconnect + re-sync is idempotent — upsert by
`(source_id, external_ref)` among live rows, soft-delete stale, partial-unique index; companion
never buffers results across reconnects (contract §5). Deferred to the per-tool connector
tickets (governed by the MCP-04 metadata-extraction amendment): the live-MCP-acquisition →
committed-export fallback flow itself, per-source "degraded" badges, and auto-triggered resync
on tool return (v1: availability restoration + normal sync paths + the idempotency gate satisfy
the AC).

---

## Addendum C — BYO-license credential capture frames (MCP-05)

Two frame types added under the §4 extension rule (**new frame types do NOT bump
`protocol_version`** — an old cloud logs-and-ignores `credential_submit`; an old companion
logs-and-ignores `credential_ack`).

| `type`              | direction         | `data`                                                                                                                                                                                                                            | when                                                                                                                                                                                                       |
| ------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `credential_submit` | companion → cloud | `{"server": str, "secrets": {<key_name>: <value>, ...}}` — the customer's own license credential VALUES for ONE `byo_paid` server, keyed by the credential key NAMES the catalog spec declares (`MCPServerSpec.license_secrets`). | When the user enters license credentials in the companion's capture UI (companion-side UI is the bridge loop's follow-on; the cloud accepts the frame as of MCP-05). Re-submits are idempotent overwrites. |
| `credential_ack`    | cloud → companion | `{"server": str, "ok": bool, "stored": [<key_name>, ...], "error": str \| null}` — key NAMES only, **never values**.                                                                                                              | Exactly one per `credential_submit`. `ok=false` carries a short static reason (`"unknown server"`, `"not a bring-your-own-license tool"`, `"unknown keys: <names>"`).                                      |

```json
{"type": "credential_submit",
 "data": {"server": "altium", "secrets": {"altium_license": "<the customer's license value>"}}}

{"type": "credential_ack",
 "data": {"server": "altium", "ok": true, "stored": ["altium_license"], "error": null}}
```

- **Size cap:** `credential_submit` is a control frame — the §6 **16 KiB** control cap applies
  (pre-parse; oversize → close `4413`, nothing parsed, nothing stored). License credentials are
  short strings; anything larger is not a license.
- **Validation (strict, wholesale):** `extra="forbid"` on the payload; `server` must exist in
  `MCP_SERVER_CATALOG` **and** be `byo_paid`; every submitted key must be in that spec's
  `license_secrets`. Any unknown key rejects the WHOLE frame — no partial writes. Malformed
  payloads take the existing §6 drop-and-count protocol-violation path; the socket survives.
- **Scope binding:** the storage ref's `team_id` comes from the SERVER-bound session scope
  (authenticated at connect), **never from the frame** — a companion cannot write into another
  tenant's namespace by construction.
- **Storage ref convention:** `mcp-license/<team_id>/<server_name>/<key_name>` — one definition,
  `license_secret_ref()` in `mcp_servers.py`, shared by the capture handler (write side), the
  invoke-time license gate (read side), and the `GET …/bridge` `license_state` surface, so the
  refs can never drift.
- **Never in cloud logs (§6 AC-4, extended):** the cloud NEVER logs the frame, the `secrets`
  mapping, or any value — handler log lines and the data-collection event
  (`bridge.license_credentials_submitted`) carry key NAMES + scope ids only; the payload model
  redacts `secrets` in `__repr__`/`__str__` and sets `hide_input_in_errors` so validation-error
  drop reasons cannot echo a value. Proven by tests (`test_bridge_credentials.py`): `caplog` at
  DEBUG across submit + failure paths asserts sentinel values appear in NO log record and NO
  outbound frame.
- **What this does NOT do:** no delivery of stored values to any MCP server (the delivery seam
  remains deliberately unbuilt, per MCP-01), no validation of the license against the vendor
  (that happens customer-side when the tool runs — BYO-paid tools are NOT on the in-house QA
  path), no read-back frame (values are write-only over the wire).

---

## Addendum D — artifact transfer frames (SOLUS-CAD-00c)

`metadata-extraction.md` §2.1 requires bulk export bytes to ride an `ArtifactRef`
(`ArtifactStorage.CLIENT`) and **never** be inlined into a tool result. Until this addendum the
companion had nowhere to put them, so `dispatch.map_result` dropped every non-text content block
with the note *"non-text content omitted (ArtifactRef plumbing pending)"* — a STEP export could
not cross the channel at all. Two new frame types close that, per the §4 extension rule (**no
`protocol_version` bump**; an old peer ignores them as unknown).

| type | direction | data |
| --- | --- | --- |
| `artifact_fetch` | cloud → companion | `{artifact_id, fetch_id}` |
| `artifact_chunk` | companion → cloud | `{fetch_id, data, final, error}` |

**Staging.** When a tool returns non-text content the companion stages the bytes in memory and the
result block carries a handle instead: `{type, inlined: false, artifact_id, media_type,
size_bytes}`. The bytes themselves never appear in a `tool_result`. Staging is bounded — per
artifact, in total, and by count — and evicts oldest-first, because the artifact a fetch wants is
the newest one. Nothing is written to disk, so a crash leaves nothing behind on a customer's
machine.

**Pull.** The cloud sends `artifact_fetch` with a fresh `fetch_id` and reads `artifact_chunk`
frames until one carries `final: true`. `data` is base64 so bytes survive a JSON text frame;
chunks are 512 KiB of raw bytes, comfortably under the 1 MiB frame cap once base64 inflates them.

**`fetch_id` is its own id space**, distinct from a `tool_call`'s `call_id`, so a chunk can never
resolve a tool call. An unknown `fetch_id` is dropped and logged — the same replay defence
`ingest_result` applies.

**Bounds (everything the companion sends is untrusted, CLAUDE.md §7).** A pull fails — never
returning a partial artifact — on any of: total bytes exceeding the transfer limit (checked
*while chunks arrive*, not after reassembly), the whole-transfer deadline elapsing, malformed
base64, an `error` chunk, or the session dying. Every failure is a `ToolException`, so callers keep
the W0-04 never-raises story.

**Lifecycle.** `clear()` on disconnect: the companion never buffers across reconnects (§5), so a
handle minted in one session must not resolve in the next. Waiting pulls are unblocked with an
error chunk when the socket dies.

---

## Addendum — the `change` frame (SOLUSDEV-167)

A design change on the customer's machine had no way to reach the cloud. Local sources were
discovered only by the scheduled sweep asking the companion to re-export — and for KiCad and Altium
the change signal IS the payload (a hash over the full export), so "has this changed?" cost exactly
as much as "give me everything". That makes local work invisible until the next sweep and makes the
sweep expensive, which is the shape of the problem SOLUSDEV-167 exists to fix.

One new frame type closes it, per the §4 extension rule (**no `protocol_version` bump**; an old peer
ignores it as unknown).

| type | direction | data |
| --- | --- | --- |
| `change` | companion → cloud | `{}` |

**The payload is empty, and that is the design.** The frame's meaning is entirely in its type: *some
design artifact under this companion's workspace moved; come and ask.* It deliberately carries no
digest (nothing would read it — the connector's own `detect_changes` is the authority) and no server
name (the sensor watches one workspace shared by both forks, so attributing a change to `kicad` vs
`altium` would be a guess). A field nothing reads is a field that goes stale silently.

**It is a hint, never evidence.** The cloud does not trust it and does not act on it directly: it
schedules the same per-source probe the sweep runs, which re-reads the change token with the
source's own credentials. So a buggy or hostile companion can, at worst, cause one debounced probe
of a source inside its own already-authenticated scope.

**Scope is server-derived, as always.** The frame body carries no ids. The cloud resolves
`(user, team, project)` from the `BridgeSession` bound at connect (§3's routing invariant), exactly
as it does for `status` and `credential_submit`. Two consequences that are easy to get wrong:

- The resulting sync must forward the **companion's** user as the acting user, taken from the
  session — not the source's creator. The live acquirer looks a session up by the exact
  `(user, team, project)` triple; fall back to `source.created_by` and a teammate's edit finds no
  session, declines, and silently reads the stale committed export instead — producing a "changed"
  notification containing no change.
- Handling must be a **cheap enqueue**. The frame handler is awaited inline in the recv loop, so
  doing the probe there would stall pongs and every in-flight `tool_result`.

**Abuse control.** `change` gets its own token bucket, following the `credential_submit` precedent
(a state-mutating unsolicited frame does not share the general bucket). It rides the 16 KiB control
cap and the violation ceiling unchanged; an empty payload makes the cap academic, which is a further
argument for keeping it empty.

**Sensor, companion side.** `st_mtime_ns` over `SOLUS_MCP_WORKSPACE`, excluding the forks' own
artifact directory (they write into it and would otherwise self-trigger), evaluated on the existing
health loop and pushed through a coalesced sender modelled on `_status_loop`. Stdlib only — no new
dependency, no fork edit, no ADR-031 re-vendor event. The ceiling is the loop's period, and the
upgrade path (a real watcher) is named in a `ponytail:` comment at the call site.

**Altium is explicitly out of this signal's reach.** Its fork never reads a design file — the export
sources entirely from live IPC — and Solus pins `force_recompile: False` so upstream never flushes
dirty documents. An unsaved Altium edit therefore has no disk footprint at all: mtime is not lossy
there, it is engineered stale. Altium's approximation is a periodic cheap IPC stat, and the UI says
"saved changes only" rather than claiming live.
