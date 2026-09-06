# artifacts.md — Project Artifact Upload/Fetch Route Plan

**Ticket:** SOLUSDEV-100 (branch `SOLUSDEV-100-kicad-mcp`), task T4c0.
**Status:** PLANNED (tier-1 route-plan amendment, ADR-032 — agent-editable, the MR review is
the approval gate). Documented BEFORE implementation per the authority hierarchy (#3: no
undocumented routes). The implementing task is T4c on the same ticket.
**Provenance:** Amended under SOLUSDEV-100 (F1 decision, in-session human approval 2026-08-03);
closes bridge-protocol §10 ArtifactRef hole. **Amended again for the SOLUSDEV-100 Phase 4
security review** (2026-08-03, FIX-A): the content route (§4) was destructively consuming on
every GET with no role check (H1/CRITICAL-adjacent, M3) — it is now a role-gated,
NON-destructive read; one-shot consumption (§4.2/§4.3) moved to a single internal function,
`services.artifacts.consume_tool_artifact`, never reachable via any HTTP route. §4.3's
anti-forgery conditions gained an explicit team-scope check (condition 2). §4.4's upload cap
now also rejects bodies with no (or malformed) `Content-Length` (M1). §4.5's limiter documents
its per-instance/lazy-eviction characteristics explicitly (M2).
**Authority:** W0-04 (`docs/contracts/agent-tool.md` §4 `ArtifactRef`, §9 `artifacts` table +
`artifact_is_accessible`) · BRG-02 (`docs/contracts/bridge-protocol.md` §4/§6: bulk companion
output rides an `ArtifactRef`, never inline; §10 names this upload path as the open hole) ·
CLAUDE.md §7 (file uploads: validate type and size, never execute; tenant isolation; untrusted
companion input) · API.md §1.4 conventions (envelope, errors, rate-limit headers) via
[API-implementation.md](API-implementation.md).
**Consumers:** the companion (BRG-04) uploading bulk MCP tool output (KiCad/EDA exports) that a
`tool_result` references instead of inlining; the sync acquirer (T4c/KiCad MCP sync worker) that
fetches the bytes exactly once; SOL vision/analysis steps that lazily fetch an artifact's bytes.

---

## 1. Why this exists

`tool_result` frames on the bridge are capped at 1 MiB and CAD/EDA exports routinely exceed it.
W0-04 already ships the `artifacts` **table** and the `ArtifactRef` shape, and explicitly defers
"S3 bucket / presigned-URL endpoint / artifact-upload flow" to a later ticket — this is that
ticket's route plan. The companion uploads the bytes here over plain HTTPS (same Supabase JWT it
dials the bridge with), then puts the returned `ArtifactRef` inside the `tool_result.value`.

All routes live under `/api/v1/projects/{project_id}/artifacts` and resolve through `ProjectCtx`
(tenant isolation; non-member → **404**, no existence leak — the same posture as every project
route). Upload and content-fetch both require the `member` role (share-only/viewer → `403`,
Phase 4 fix); the metadata route needs only a resolvable project plus the per-artifact scope
check (§4.1) — it carries no role requirement because it is, and always was, non-destructive.

| Method | Path                                                            | Purpose                                         | Success |
| ------ | --------------------------------------------------------------- | ----------------------------------------------- | ------- |
| POST   | `/api/v1/projects/{project_id}/artifacts`                       | Multipart upload; returns a W0-04 `ArtifactRef` | `201`   |
| GET    | `/api/v1/projects/{project_id}/artifacts/{artifact_id}`         | Artifact metadata (registry row)                | `200`   |
| GET    | `/api/v1/projects/{project_id}/artifacts/{artifact_id}/content` | The raw bytes                                   | `200`   |

---

## 2. POST /api/v1/projects/{project_id}/artifacts — upload (member+)

`multipart/form-data`:

| part          | type   | required | notes                                                                                     |
| ------------- | ------ | -------- | ----------------------------------------------------------------------------------------- |
| `file`        | file   | yes      | the bytes; size-bounded pre-read (§4.4)                                                   |
| `media_type`  | string | yes      | syntactically valid `type/subtype` MIME string, ≤255 chars; invalid → `422`               |
| `source_tool` | string | no       | producing `{server}.{tool}` name, ≤64 chars — matches `artifacts.source_tool`             |
| `call_id`     | string | no       | the W0-04 `ToolCall.call_id` this upload fulfils; stored as `artifacts.tool_call_id` (§3) |

Auth is the standard centralized middleware + `ProjectCtx`. **`project_id`, `team_id` (via the
project), and `created_by` are derived server-side from the authenticated context — never
client-asserted** (the same AC-2 posture as the bridge: a client-supplied identity field anywhere
is ignored or rejected). `scope` is not a request field: every upload lands `PROJECT` (§4.1);
flipping an artifact `PRIVATE` stays the future opt-in described in `agent-tool.md` §9.

`201` — the envelope carries the W0-04 `ArtifactRef` shape verbatim:

```json
{
  "data": {
    "artifact_id": "019f9a01-2c44-7d1e-9b0a-3f52c1e0aa10",
    "uri": "/api/v1/projects/019ebe61-ef4e-72e1-8726-5905455db85a/artifacts/019f9a01-2c44-7d1e-9b0a-3f52c1e0aa10/content",
    "media_type": "application/zip",
    "storage": "local",
    "size_bytes": 2748812,
    "summary": null
  }
}
```

- The returned `uri` is always the **API content route** (relative), never a storage-internal
  locator — every fetch goes through the single authz path (§4.6). `storage` reports the backend
  that actually holds the bytes (`s3` prod / `local` dev).
- `413 payload_too_large` — body exceeds `artifact_max_bytes` (default **8 MiB**), enforced
  against `Content-Length` before reading and again while streaming (a lying header cannot
  overshoot).
- `422 validation_error` — malformed `media_type`, missing `file`, unknown form fields.
- File-upload hygiene per CLAUDE.md §7: bytes are stored verbatim and **never executed, never
  unzipped** by this surface; any archive extraction happens in the consuming sync worker behind
  its own zip-bomb/path-traversal guards.

## 3. GET /api/v1/projects/{project_id}/artifacts/{artifact_id} — metadata

`200` — the registry row (the existing `ArtifactRead` schema plus the planned `tool_call_id`
column), scope-enforced per §4.1:

```json
{
  "data": {
    "id": "019f9a01-2c44-7d1e-9b0a-3f52c1e0aa10",
    "project_id": "019ebe61-ef4e-72e1-8726-5905455db85a",
    "scope": "project",
    "uri": "/api/v1/projects/019ebe61-ef4e-72e1-8726-5905455db85a/artifacts/019f9a01-2c44-7d1e-9b0a-3f52c1e0aa10/content",
    "media_type": "application/zip",
    "size_bytes": 2748812,
    "storage_location": "local",
    "created_by": "019ebe5b-7aca-7770-acbb-c1897f15f46e",
    "source_tool": "kicad.export_project",
    "tool_call_id": "b0e2f6f4c1d84a2e9c3d5e6f7a8b9c0d",
    "created_at": "2026-08-03T10:12:44.101Z",
    "updated_at": "2026-08-03T10:12:44.101Z",
    "deleted_at": null
  }
}
```

`tool_call_id` (`String(64)`, nullable, indexed) is a **planned column** on the existing
`artifacts` table (new migration, T4c) recording which W0-04 `ToolCall` the upload fulfils —
the anti-forgery anchor of §4.3. All other columns above already exist (`models.py`,
`344b7841f6d3_add_artifacts_table.py`).

Unknown id, another project's artifact, soft-deleted (consumed/expired), or a `PRIVATE`
artifact you didn't create → `404` (no existence oracle — mirrors `agent-tool.md` §6's
"NOT_FOUND, not UNAUTHORIZED").

## 4. GET /api/v1/projects/{project_id}/artifacts/{artifact_id}/content — bytes (member+)

`200` — the raw bytes, `Content-Type: <media_type>`, `Content-Length: <size_bytes>`, streamed
from the storage backend. Same scope enforcement and identical `404` semantics as the metadata
route (§3), PLUS a `member`+ role requirement (`403` for viewer/share-only — a `ProjectCtx` with
`membership is None`). This route serves the stored bytes only — it never transforms, extracts,
or executes them, and (Phase 4 fix) it never consumes/destroys the artifact either: a member may
GET the same artifact repeatedly until its TTL sweep (§4.2) removes it. **This was a security
fix**: the route previously fetched-AND-destroyed on every GET with no role check at all, so any
project reader — including a viewer — could silently destroy a teammate's design export just by
reading it once. One-shot consumption is not a property of a generic content-serving route; see
§4.2/§4.3 for where it now lives exclusively.

---

## Semantics

### 4.1 Scope

Every artifact defaults to `scope = PROJECT` — any project member (or ADR-025 share-only user)
who resolves `ProjectCtx` may read it, enforced through the existing pure
`artifact_is_accessible` rule (`models.py`). Rationale: a team's own design exports are team
data, exactly as `graph_entity` rows are — **this default is ratified at MR review** (called out
in the T4c0 completion report). `PRIVATE` narrows reads to `created_by` only; failures surface
as `404`.

### 4.2 Retention — TTL sweep + one-shot consumption

Bridge-upload artifacts are a **hand-off buffer, not a document store** — with one exception:
an artifact filed into the project `.solus` (`POST …/solus/{section}/entries`, `kind:
"artifact"`, [solus.md](solus.md)) is marked **`retained`** and is exempt from both the TTL
sweep and one-shot consumption until its entry is deleted (SOLUSDEV-240). Everything below
applies to non-retained artifacts:

- `artifact_ttl_seconds` (config, default **3600**): an ARQ sweep job soft-deletes expired
  rows and deletes the backing bytes. Post-TTL fetches → `404` on both the metadata and content
  routes.
- **One-shot consumption** is the sync acquirer's OWN internal behavior, not a property of any
  HTTP route (Phase 4 fix — see §4 for what changed). The sync acquirer (the worker that
  resolves a bridge `tool_result`'s `ArtifactRef` into a sync input) calls
  `services.artifacts.consume_tool_artifact` — **the only function in the codebase that ever
  consumes an artifact** — which fetches the content exactly once; a consumed artifact is
  immediately **soft-deleted** (row kept for provenance, bytes removed, further fetches `404`
  from every route). This bounds the window in which untrusted companion bytes sit server-side
  and makes replay of a stale export impossible. `consume_tool_artifact` is never called from an
  HTTP handler — a companion or a client can never trigger consumption directly.

### 4.3 Anti-forgery consumption rules

`consume_tool_artifact` treats an `ArtifactRef` arriving in a `tool_result` as untrusted (bridge
§6). Before consuming, ALL of the following must match the cloud-side record of the originating
tool call — any mismatch → the artifact is left completely untouched (not consumed, not
soft-deleted) and the tool result fails as a structured error:

1. `artifacts.project_id` == the call's bound project scope,
2. the project's `team_id` == the call's bound team scope (Phase 4: verified against the
   `projects` row's ACTUAL `team_id`, not merely the acquirer's own scope parameter — a
   misconfigured or attacked source can no longer carry a mismatched team scope through),
3. `artifacts.created_by` == the session user who was dispatched the call,
4. `artifacts.source_tool` == the dispatched `{server}.{tool}` name,
5. `artifacts.tool_call_id` == the dispatched `ToolCall.call_id`,
6. the artifact is live (not consumed, not expired) — **single use, first consumer wins**.

A companion can therefore only fulfil the exact call it was sent, in its own scope, once. It can
never point a `tool_result` at another tenant's artifact, another user's upload, or a previously
consumed blob. Additionally (Phase 4 M4), the acquirer re-verifies the ACTING user still has live
team/project access immediately before calling `consume_tool_artifact` — a user removed from the
team after being resolved as a sync run's acting user no longer gets a rubber-stamped
`requester_has_project_access=True`; the run declines with a logged reason instead.

### 4.4 Size caps

| setting                     | default     | meaning                                                                                                    |
| --------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------- |
| `artifact_inline_max_bytes` | **512 KiB** | advisory threshold below which a tool result SHOULD inline the value instead of minting an artifact        |
| `artifact_max_bytes`        | **8 MiB**   | hard upload cap; over → `413 payload_too_large` (pre-read via `Content-Length` + enforced while streaming) |

Config sourced from `SOLUS_*` environment variables per the standard settings model
(`SOLUS_ARTIFACT_MAX_BYTES`, …).

**`Content-Length` is required (Phase 4 M1 fix):** a request with no `Content-Length` header (a
chunked-encoded body) is rejected with `411 length_required` BEFORE `request.form()` is ever
called — that call spools the entire multipart body to disk/memory with no cap of its own, so an
unbounded chunked upload could exhaust the server before the streamed cap (`read_bounded`) got a
chance to run. A malformed (non-integer) `Content-Length` is rejected the same way. A client that
declares a small, in-cap `Content-Length` but sends a larger body still cannot overshoot the cap
— `read_bounded` enforces it again while streaming, independent of the header.

### 4.5 Rate limiting

On top of the global per-token limiter (§7 of API-implementation.md), the upload route carries
its own budgets, enforced with the same machinery as the bridge caps and emitted to the
data-collection system:

| setting                                   | applies  | meaning                     |
| ----------------------------------------- | -------- | --------------------------- |
| `artifact_uploads_per_minute_per_user`    | per user | upload-request count budget |
| `artifact_upload_bytes_per_hour_per_team` | per team | accepted-byte budget        |

Exceeded → `429 rate_limited` (+ `Retry-After`). **Numbers are provisional pending the F13
security pass** — the settings names are the contract here, not the values.

`FixedWindowLimiter` (the mechanism behind both budgets above) has two documented v1
characteristics (Phase 4 M2): it is **per-process, in-memory** — on a multi-instance API
deployment, each instance enforces the limit independently, so the real aggregate budget is
`limit × instance_count`; a shared Redis counter is the named follow-up when the API goes
multi-instance (mirrors `bridge_revocation_poll_seconds`'s own documented single-instance gap).
Stale per-key counters are pruned lazily on every `bump()` call, so memory stays bounded by the
number of distinct keys seen in the CURRENT window, never by the lifetime count of every key the
process has ever seen.

### 4.6 Storage backends — the `ArtifactStore` protocol

Bytes are written/read through an `ArtifactStore` protocol (put/stream/delete), selected by
config: **S3 in prod, local filesystem in dev** — matching the existing `ArtifactStorage` enum
(`s3 | local`; `client` remains the bridge-side "bytes never left the machine" case and is not
served by these routes).

**Presigned S3 is the documented revisit path, not v1.** For >8 MiB CAD formats (STEP
assemblies, large fabrication exports) direct-to-S3 presigned PUT/GET is the obvious upgrade,
but it is deliberately deferred because: (a) the uploader is an **untrusted companion** — proxying
through the API keeps size caps, media-type validation, and the §4.3 provenance binding enforced
in one place at write time, whereas presigned URLs move enforcement to bucket policy + post-hoc
checks; (b) there is **no bucket infrastructure yet** (F11 — dev runs on the local backend); and
(c) a presigned GET would create a second read path that bypasses the **single authz path**
(`ProjectCtx` + `artifact_is_accessible` + one-shot bookkeeping). When F11 lands the bucket and a
real >8 MiB need arrives, presigning becomes a scoped follow-up amendment to this file.

---

## 5. Error code catalogue (this surface)

| HTTP | `error.code`        | Where                                                                                                                                 |
| ---- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 401  | `unauthorized`      | missing/invalid/expired JWT                                                                                                           |
| 403  | `forbidden`         | upload OR content-fetch as viewer / share-only user (Phase 4: content is now role-checked too; metadata reads are scope-checked only) |
| 404  | `not_found`         | non-member project; unknown/foreign/soft-deleted/consumed/expired artifact; `PRIVATE` non-creator                                     |
| 411  | `length_required`   | upload with no (or malformed) `Content-Length` (Phase 4 M1)                                                                           |
| 413  | `payload_too_large` | upload exceeds `artifact_max_bytes`                                                                                                   |
| 422  | `validation_error`  | malformed `media_type`, missing `file`, unknown form fields                                                                           |
| 429  | `rate_limited`      | §4.5 budgets exceeded                                                                                                                 |

---

**Cross-references:** `docs/contracts/agent-tool.md` (§4 `ArtifactRef`, §9 table + access rule,
§10 "artifact-upload flow — later ticket") · `docs/contracts/bridge-protocol.md` (§4
`tool_result` size cap, §6 payload hygiene, §10 the hole this closes) ·
[API-implementation.md](API-implementation.md) §12 (index entry) · CLAUDE.md §7 (uploads, tenant
isolation, untrusted client posture).
