# Agent-Tool Interface — Design Contract (SOLUS-W0-04)

**Status:** Design contract + **working implementation**. Ships the interface, the four
envelope shapes, `ArtifactRef`, the `ToolRegistry`, the reference `get_entity` tool, the
**`MCPTool` kind** (stdio and streamable-HTTP, including vendor-hosted servers
authenticated as the customer — ADR-031, ADR-035), and **confirmation enforcement** — all
functional end to end. The remaining tool KINDS (Desktop/Environment) and the artifact
byte-fetch flow are documented here, not built.
**Authority:** ADR-010 (the SOL Agent is an orchestrator of tools, not a monolith),
ADR-028 (Week-0 human-owned contract), ADR-027 (graph/soft-delete conventions), CLAUDE.md
§7 (model-orchestration security). Code: `packages/api/src/solus_api/agent/tools/`.

Consumers: the SOL Agent (ADR-010) and any agent loop invoke capabilities — read the graph,
run a checker, retrieve an error, later operate a device — through ONE interface. SOL decides
WHAT to call and WITH WHAT ARGS; the interface invokes it and returns a result the model can
consume. The whole point is that **adding a capability never rewires the agent**: every tool,
of every kind, looks identical to SOL.

---

## 1. Purpose and the three invariants

The interface makes capabilities **uniformly callable** without the reasoning code knowing HOW
each is implemented. Three invariants hold for every tool:

1. **Uniformity** — every tool looks identical to SOL. A `ToolCall` goes in, a `ToolResult`
   comes back. Adding a capability (or a whole new KIND of tool) never changes SOL or the registry.
2. **Safety** — a tool failure is NEVER an unhandled exception or a traceback to the model.
   Failures are structured `ToolError` DATA the model can reason about.
3. **Model-consumability** — a result serializes cleanly into the model context. Large/binary
   data is REFERENCED via `ArtifactRef`, never inlined.

---

## 2. `Tool` — a protocol, not a bare function

`Tool` is a `Protocol`, so different KINDS of capability plug in behind one interface. This is the
extensibility mechanism: the registry and SOL are written against the protocol and never change
when a new kind is added.

```python
class Tool(Protocol):
    @property
    def descriptor(self) -> ToolDescriptor: ...
    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        ...  # returns the `value`; raises ToolException on a typed failure
```

- A tool's `invoke` returns the raw `value` (a JSON-serializable dict) or raises `ToolException`
  to signal a typed failure. A tool **never** returns a `ToolResult` and **never** enforces its
  own timeout — the registry wraps every call into a structured result (§5).

**Two kinds ship today** — `InProcessTool` (wraps an async Python callable) and `MCPTool`
(forwards over the wire to an external MCP server). The remaining kinds are further
implementations of the SAME protocol; the registry and SOL are untouched when they arrive:

| Kind                | What it is                                                                                                                                                                        | Status         |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| **InProcessTool**   | An async Python callable in this process                                                                                                                                          | **Built (v1)** |
| **MCPTool**         | Forwards to an external MCP server: **stdio** (a vendored, Solus-owned fork the companion launches on the customer's machine — ADR-031) or **streamable-HTTP** (a vendor-hosted server reached from the cloud with the CUSTOMER's own token — ADR-035) | **Built**      |
| **DesktopTool**     | UI / desktop interaction — the "being the cursor" capability lives HERE                                                                                                            | Future         |
| **EnvironmentTool** | Operates a connected tool or device                                                                                                                                               | Future         |

That MCP/remote tools carry a **raw JSON Schema** (not a Python type) is exactly why the registry
validates against the descriptor's `params` dict generically (§5) rather than a per-tool model.

### 2.1 `MCPTool` — exposure is Solus's, and three optional hooks

A remote server is UNTRUSTED INPUT end to end (CLAUDE.md §7): its tool names, descriptions,
schemas and results are text an upstream fork or a vendor's cloud wrote.

**Exposure is allowlist-driven, never "what the server advertises."** `discover_mcp_tools`
connects, calls `tools/list`, and classifies each advertised tool through exactly ONE
source — never blended:

| Source                    | Where it comes from                            | A tool it does not name          |
| ------------------------- | ---------------------------------------------- | -------------------------------- |
| A hosted server's `policy` | `remote_mcp.HOSTED_SERVERS`, cloud-side        | **skipped** (ADR-035)            |
| A vendored fork's allowlist | `integrations/mcp/<server>/allowlist.yaml`     | **skipped** (ADR-031)            |
| The spec's blanket flag   | `MCPServerSpec.requires_confirmation`          | skipped when the flag is set     |

A tool the vendor adds between releases therefore cannot enter SOL's namespace at all.
Admitting it and merely gating it would be the same lie from the other direction: a
Solus-authored consent sentence in front of a tool Solus has never seen.

**A gated tool MUST carry `consent_summary`.** Its `description` is not Solus's
(`description_trusted=false`), and `_summarize` fails closed — with neither, the sentence a
human approves degrades to the bare tool NAME.

**Server-authored PROSE inside a schema is stripped for hosted specs.** Prompt assembly
fences an untrusted `description`, but passes `params` through verbatim, which makes every
`description`/`title`/`enum` leaf inside a server's JSON Schema unfenced,
instruction-position text. Structure (types, `required`) is kept; prose is dropped.

**Duplicate advertised names are dropped at discovery.** `ToolRegistry.register` raises on a
duplicate, at WIRING time — so without this a server could 500 every SOL request for a
project, including the one that would REJECT an already-parked destructive action.

Three optional constructor hooks, all defaulting to absent:

| Hook               | What it is                                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `headers_provider` | Resolves auth headers **per call** — a hosted token lives ~1h, so it cannot be captured at wiring time. Raising `ToolException` here is the sanctioned way to report "not connected / reconnect". |
| `preflight`        | Runs before any connection opens; raises to refuse. Registration meters nothing, so a tool that spends a real allowance brings its own admission (ADR-019 as amended). |
| `preview`          | The gate's duck-typed diff builder (§6). Set on the INSTANCE, so a tool without one truthfully has no `preview` attribute.                  |

---

## 3. The four core shapes

Pydantic v2 value objects (frozen). `ToolErrorCode` is the failure taxonomy.

**`ToolDescriptor`** — what a tool advertises to SOL. `description` and `params` are part of the
interface: the MODEL reads them to decide when and how to call the tool.

| field                   | meaning                                                                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `name`                  | unique, stable id (e.g. `get_entity`)                                                                                               |
| `description`           | natural language, read by the model                                                                                                 |
| `params`                | JSON Schema for the arguments                                                                                                       |
| `returns`               | JSON Schema for the result `value`                                                                                                  |
| `timeout_seconds`       | `float \| None` — per-tool override of the registry default                                                                         |
| `requires_confirmation` | `bool` (default `false`) — destructive/irreversible tool; the orchestrator must get explicit user confirmation before dispatch (§6) |
| `result_cap` | `int \| None` (default `None`) — per-tool override of the prompt layer's `TOOL_RESULT_CAP`, for a tool whose whole point is a payload bigger than the default. A Feature Studio read back at 4 000 characters is not a Feature Studio: the model would reason about a prefix and propose an overwrite built on the part it could see. Reads only — a mutating tool returns a status, not a payload, and keeps the default. Redaction and encoding are identical either way; only the bound moves. |
| `description_trusted` | `bool` (default `true`) — whether `description` is **Solus-authored**. `false` for a bridge or MCP tool, whose description is written by an upstream fork or a vendor's cloud. It still reaches the MODEL (it is how the model picks the right tool) but prompt assembly fences it as data so it cannot pose as a Solus instruction, and the consent surface refuses to build a sentence from it: with `description_trusted=false` and no `consent_summary`, the summary FAILS CLOSED to the tool name alone. Deliberately NOT inferred from `consent_summary is not None` — the two meanings will diverge. |
| `consent_summary` | `str \| None` (default `None`) — **Solus-authored** text for the consent surface, used INSTEAD of `description` when the latter cannot be trusted to phrase it. A bridge/MCP tool's `description` is advertised by an upstream fork: acceptable as model context (length-capped, treated as data), but it must never compose the sentence a human reads before approving a destructive action — a fork could describe a destructive tool as "read-only". Bridge tools set this from their allowlist `reason`, which is mandatory on every destructive entry and is reviewed with the fork. |

**`ToolCall`** — one invocation SOL proposes.

| field     | meaning                                                                     |
| --------- | --------------------------------------------------------------------------- |
| `call_id` | unique per call (defaults to a fresh id); correlates call ↔ result ↔ logs |
| `tool`    | tool name                                                                   |
| `args`    | arguments, validated against the tool's `params` schema                     |

**`ToolResult`** — the single envelope every call returns. SOL branches only on `ok`.

| field     | meaning                                                                      |
| --------- | ---------------------------------------------------------------------------- |
| `call_id` | echoes the `ToolCall` id                                                     |
| `ok`      | the single flag SOL branches on                                              |
| `value`   | present when `ok=true`; JSON-serializable dict; large data via `ArtifactRef` |
| `error`   | present when `ok=false`                                                      |

**`ToolError`** — a structured failure, never a traceback.

| field       | meaning                                                                                                                                                                                                                                                                     |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code`      | `ToolErrorCode`: `INVALID_ARGS \| NOT_FOUND \| TOOL_ERROR \| TIMEOUT \| UNAUTHORIZED \| UNAVAILABLE` — `UNAVAILABLE` ("the tool's backing channel has no live session", e.g. bridge offline) added by SOLUSDEV-154 per bridge-protocol §3; ratified 2026-07-30 with ADR-032 |
| `message`   | human/model-readable                                                                                                                                                                                                                                                        |
| `retryable` | can SOL sensibly retry (transient) or not (permanent)?                                                                                                                                                                                                                      |

**Invariant (validated):** a `ToolResult` with `ok=true` MUST carry a `value` and no `error`; with
`ok=false` it MUST carry an `error` and no `value`. Enforced by a model validator so a malformed
result can never reach the model. `ToolResult.success(...)` / `.failure(...)` are the constructors.

---

## 4. `ArtifactRef` — large/binary results are referenced, never inlined

Large or binary tool outputs (images, point clouds, screenshots, big buffers) travel as
references, not bytes, so transmission stays fast and the model context stays lean.

| field         | meaning                                                      |
| ------------- | ------------------------------------------------------------ |
| `artifact_id` | UUID handle into the `artifacts` table (§9)                  |
| `uri`         | where the bytes live                                         |
| `media_type`  | e.g. `image/png`, `application/octet-stream`                 |
| `storage`     | `ArtifactStorage`: `S3 \| LOCAL \| CLIENT`                   |
| `size_bytes`  | `int \| None` — so a consumer knows the cost before fetching |
| `summary`     | text the model reasons over WITHOUT fetching the bytes       |

**Principle:** SOL reasons on `summary`/findings; raw bytes are fetched **lazily** (a presigned URL
for clients, direct S3 for server-side consumers) only when a specific step — e.g. a vision-model
call — genuinely needs the pixels. A tool returning visual data returns
`{finding, region_of_interest, artifact_ref}`, **not** the image.

**Processing-location principle** (why the system stays fast — large data is _worked with_ wherever
keeps it OFF the reasoning path):

- **Client-side** for high-volume / real-time / locally-originating data (camera frames, live
  telemetry, screen) — edge processing produces a compact result; only distilled results travel.
- **ARQ workers** for cloud-side HEAVY jobs (cloud vision inference, heavy analysis, batch
  embedding) — the tool enqueues a job; the worker pulls from S3, processes, writes results back;
  SOL is not blocked.
- **Inline in the tool** ONLY for light/fast operations.

The reasoning loop NEVER processes large data directly.

---

## 5. `ToolRegistry` — the safety sequence

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None      # validates + caches the params schema; rejects dups
    def list(self) -> list[ToolDescriptor]      # name-sorted, a stable model view
    async def invoke(self, call: ToolCall) -> ToolResult
```

`invoke()` runs THE SAFETY SEQUENCE:

1. **Look up** the tool by `call.tool`. Not found → `ToolResult(ok=false, NOT_FOUND, retryable=false)`.
2. **Validate `call.args`** against the tool's `params` JSON Schema (a cached Draft-2020-12
   validator with format-checking, so a non-uuid where a `uuid` is required fails here). Invalid →
   `ToolResult(ok=false, INVALID_ARGS, retryable=false)`. A malformed call becomes a structured
   result, NOT a crash in the tool.
3. **Run** `tool.invoke(args)` bounded by the timeout (per-tool `timeout_seconds` else the registry
   default) and wrapped so ANY exception is trapped:
   - `ToolException` → its `code`/`message`/`retryable` (the message is author-written, safe for
     the model).
   - timeout → `ToolResult(ok=false, TIMEOUT, retryable=true)`.
   - any other exception (including a tool returning a non-dict) → `ToolResult(ok=false,
TOOL_ERROR)` with a **generic** message; the traceback is logged server-side and **NEVER**
     placed in the result.
4. Return the `ToolResult`.

**THE INVARIANT:** `invoke()` **NEVER raises** to its caller. Every failure — unknown tool, bad
args, tool exception, timeout, or a misbehaving tool — returns as a `ToolResult(ok=false)`. SOL's
reasoning can ALWAYS branch on `ok` and reason about `error`; it never try/catches and never sees a
traceback.

**The `BaseExceptionGroup` hole, closed centrally (SOLUSDEV-168).** `except Exception` does
**not** catch a `BaseExceptionGroup`. Verified on CPython 3.12.3: the constructor downgrades
an all-`Exception` group to `ExceptionGroup` (which IS an `Exception`, and was already
caught), but a group carrying a `CancelledError` stays a `BaseExceptionGroup` and escaped
the invariant entirely. Any tool whose transport runs an anyio task group — MCP over stdio
or streamable-HTTP, the bridge — produces one when a cancel races a real failure, and a
sequential dispatcher has nothing underneath it (`exec.run_tool_calls` papers over it at
BATCH level only). `invoke` now handles the group explicitly:

- a group carrying a `CancelledError` is **re-raised** — `wait_for` has already converted its
  own timeout, so a cancel arriving here is EXTERNAL (client gone, worker shutting down) and
  swallowing it would strand the turn;
- a `ToolException` at any depth surfaces **as itself**, so a deliberate typed failure
  ("reconnect FeatureScript") does not become the generic internal error;
- anything else is the generic `TOOL_ERROR`.

**Fail-fast on registration:** `register` validates the `params` schema (raises on a malformed
schema) and rejects a duplicate name, so dispatch stays deterministic and a bad tool is caught at
wiring time, not first call.

---

## 6. Security (binds this contract — CLAUDE.md §7)

- **Scope is bound by Solus code, never by model args.** A tool that reads tenant data is bound to
  the caller's scope at construction (the reference `get_entity` takes its `project_id` scope as a
  constructor argument, not a model-supplied arg). No ingested content may alter the agent's auth
  context, team scope, tool selection, or mode. The tool set for an invocation is fixed by Solus
  code before any model sees user data. **Bind per request:** the consuming SOL loop constructs a
  fresh, request-scoped registry/tool set from the authenticated scope on every invocation — a
  registry (or scoped tool) is never reused across tenants. This is a convention the contract does
  not type-enforce; the SOL-loop ticket owns it.
- **Tool-side authorization.** Authorization is enforced in tool code with the requesting user's
  permissions — never elevated, never assumed from the model. Out-of-scope reads return `NOT_FOUND`
  (not `UNAUTHORIZED`) so there is no cross-tenant existence oracle.
- **Ingested content in a `value` is DATA, not instructions.** A tool's `value` can carry
  attacker-influenced text — a `graph_entity` `name`, `external_ref`, or `attrs` originate in a
  connected repo/CAD/schematic. When that value is assembled into a prompt, the SOL context layer
  wraps and delimits it as data to be analyzed, never as instructions to follow (CLAUDE.md §7,
  prompt-injection). Red-team fixtures — entities/artifacts carrying adversarial instructions in
  their fields — are a requirement of that consuming prompt-assembly ticket, not of this interface
  (which only surfaces the fields).
- **Model output is untrusted.** A tool's `value` is validated/sanitized before it renders in the
  UI, writes to the graph, or feeds a downstream tool. Chained orchestration does not launder trust.
- **No secrets in results.** Tool results and prompt context source from the graph and sanitized
  stores, never from config or credential stores. Unexpected-exception messages are generic.
- **Real-world/destructive actions** (flashing, deploying, mutating external systems, deleting graph
  data) require explicit user confirmation with the concrete action shown. A tool **declares** this
  by setting `ToolDescriptor.requires_confirmation = true`; the orchestrator reads the flag and
  obtains confirmation **before it dispatches** the `ToolCall`, so the gate is enforced centrally
  rather than hand-rolled in each tool (a forgotten hand-rolled check would be a silent-execution
  path). The registry stays a pure dispatcher and does not read the flag — confirmation is a
  pre-dispatch, human-in-the-loop concern owned by the SOL loop.

---

## 7. Separation of concerns

- **Tools ≠ the model router (W0-03).** A tool is a capability SOL _invokes_; the router
  (`route()`) powers SOL's _reasoning_. A tool MAY internally call a model through the router, but
  the two interfaces do not merge.
- **"How to use a tool well" is a reasoning/context concern**, not this interface. Constructing SOL's
  context and prompting it to pick the right tool live in the SOL context layer; this interface only
  makes capabilities uniformly callable.
- **Event emission is a consumer concern.** The registry is a pure dispatcher and holds no request
  `user`/`session`, so it emits no data-collection events. The SOL loop that holds the request
  context emits `agent.tool_invoked` (per the event schema) around its registry calls.

---

## 8. Reference tool — `get_entity`

Proves the contract end to end.

```
descriptor:
  name: "get_entity"
  description: "Fetch a graph entity by its ID, returning kind, domain, name, attrs, and canonical_part_id."
  params:  { entity_id: string/uuid, required, additionalProperties: false }
  returns: JSON Schema mirroring the curated entity view (below)

build_get_entity_tool(session_factory, project_id) -> Tool   # project_id is the Solus-bound scope
```

The async handler reads `graph_entity` (W0-01) filtered by `id == entity_id AND project_id == scope
AND deleted_at IS NULL`, and returns a **curated, JSON-native** dict — `id, project_id, kind,
domain, name, canonical_part_id, source_connector, external_ref, attrs`. It **omits the embedding**
(a 1536-float vector is noise in the reasoning context — the same principle as §4: bulk data stays
off the reasoning path). A missing OR out-of-scope id raises `ToolException(NOT_FOUND)`.

This exercises: registration, arg validation (missing / non-uuid `entity_id` → INVALID_ARGS), a real
team-scoped DB read, a model-consumable dict, and a missing/out-of-scope entity → `ok=false,
NOT_FOUND` with no traceback.

---

## 9. `artifacts` table + scope behavior (W0-01 addendum)

The registry row for large-data references — bytes live in S3/on a client, metadata lives in
Postgres. Added as a NEW migration (`down_revision = 7ea820a98068`), never editing the original.

| column                                 | notes                                                                              |
| -------------------------------------- | ---------------------------------------------------------------------------------- |
| `id`                                   | UUID pk (UUIDv7)                                                                   |
| `project_id`                           | FK → projects (CASCADE); the scoping anchor                                        |
| `scope`                                | `ArtifactScope`: `PROJECT` (default) \| `PRIVATE` (extensible: TEAM, PUBLIC later) |
| `uri`, `media_type`, `size_bytes`      | where/what/how-big                                                                 |
| `storage_location`                     | `ArtifactStorage`: `S3 \| LOCAL \| CLIENT`                                         |
| `created_by`                           | FK → users (SET NULL); provenance                                                  |
| `source_tool`                          | which tool/call produced it                                                        |
| `created_at / updated_at / deleted_at` | timestamps + soft-delete (base mixin)                                              |

**Scope behavior (enforced in the access check, never via a per-artifact prompt):** `scope` DEFAULTS
to `PROJECT` — inherited from the project, so anyone with project access can fetch it, exactly as
`graph_entity` is project-scoped. Most artifacts are machine-generated byproducts and take the
PROJECT default silently. A user can OVERRIDE a specific artifact to `PRIVATE` (only `created_by`
may fetch) — an opt-in action on the artifacts they deliberately care about, never a prompt on
every artifact. The rule is a pure function:

```python
artifact_is_accessible(*, scope, created_by, requester_id, requester_has_project_access) -> bool
    # PRIVATE  → requester_id == created_by
    # PROJECT  → requester_has_project_access   (the caller computes this via the usual project query)
```

The S3 bucket, the presigned-URL endpoint, and the artifact-creation flow are LATER implementation
tickets. This contract adds the TABLE + Pydantic schema (`ArtifactRead`) + the `ArtifactRef` shape only.

---

## 10. Functional vs. future in W0-04

| Component                                                 | W0-04 status                       |
| --------------------------------------------------------- | ---------------------------------- |
| Four shapes + `ArtifactRef` + `ToolErrorCode`             | **Functional**                     |
| `Tool` protocol + `InProcessTool`                         | **Functional**                     |
| `ToolRegistry` (register / list / invoke — never raises)  | **Functional**                     |
| Reference `get_entity` tool (end to end)                  | **Functional**                     |
| `artifacts` table + `ArtifactRead` schema + access check  | **Functional**                     |
| `requires_confirmation` marker on `ToolDescriptor`        | **Functional (declared)**          |
| Confirmation _enforcement_ (gate before dispatch)         | **Functional** — `runtime.build_dispatch` fuses gate-then-invoke so a runner cannot skip it; `agent/confirmations.py` parks, renders the Solus-authored summary + preview, and decides under `FOR UPDATE` |
| `MCPTool` kind — stdio forks (ADR-031) + vendor-hosted servers (ADR-035) | **Functional**    |
| Desktop / Environment tool kinds                          | **Documented, not built**          |
| S3 bucket / presigned-URL endpoint / artifact-upload flow | **Later ticket**                   |
| SOL's reasoning about _how_ to use tools                  | **Out of scope (reasoning layer)** |

---

**Cross-references:** ADR-010 (agent-as-orchestrator), ADR-028 (human-owned contract), ADR-027
(graph/soft-delete), CLAUDE.md §7 (model-orchestration security). Code:
`packages/api/src/solus_api/agent/tools/` (`shapes.py`, `tool.py`, `registry.py`, `get_entity.py`);
the `artifacts` table + `artifact_is_accessible` in `models.py`, `ArtifactRead` in `schemas.py`,
migration `344b7841f6d3_add_artifacts_table.py`. Sibling contract: `model-orchestration.md` (W0-03)
— a tool MAY call the router, but tools and routing are separate interfaces.
