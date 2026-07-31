# Agent-Tool Interface — Design Contract (SOLUS-W0-04)

**Status:** Design contract + **working implementation**. Ships the interface, the four
envelope shapes, `ArtifactRef`, the `ToolRegistry`, and the reference `get_entity` tool —
all functional end to end. Future tool KINDS (MCP/Desktop/Environment) and the artifact
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

**v1 ships one kind — `InProcessTool`** (wraps an async Python callable). Future kinds are further
implementations of the SAME protocol; the registry and SOL are untouched when they arrive:

| Kind                     | What it is                                                              | Status         |
| ------------------------ | ----------------------------------------------------------------------- | -------------- |
| **InProcessTool**        | An async Python callable in this process                                | **Built (v1)** |
| **RemoteTool / MCPTool** | Forwards to an external MCP server over the wire                        | Future         |
| **DesktopTool**          | UI / desktop interaction — the "being the cursor" capability lives HERE | Future         |
| **EnvironmentTool**      | Operates a connected tool or device                                     | Future         |

That MCP/remote tools carry a **raw JSON Schema** (not a Python type) is exactly why the registry
validates against the descriptor's `params` dict generically (§5) rather than a per-tool model.

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
| Confirmation _enforcement_ (gate before dispatch)         | **SOL-loop ticket**                |
| MCP / Desktop / Environment tool kinds                    | **Documented, not built**          |
| S3 bucket / presigned-URL endpoint / artifact-upload flow | **Later ticket**                   |
| SOL's reasoning about _how_ to use tools                  | **Out of scope (reasoning layer)** |

---

**Cross-references:** ADR-010 (agent-as-orchestrator), ADR-028 (human-owned contract), ADR-027
(graph/soft-delete), CLAUDE.md §7 (model-orchestration security). Code:
`packages/api/src/solus_api/agent/tools/` (`shapes.py`, `tool.py`, `registry.py`, `get_entity.py`);
the `artifacts` table + `artifact_is_accessible` in `models.py`, `ArtifactRead` in `schemas.py`,
migration `344b7841f6d3_add_artifacts_table.py`. Sibling contract: `model-orchestration.md` (W0-03)
— a tool MAY call the router, but tools and routing are separate interfaces.
