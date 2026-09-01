# API.md — Solus Core API Surface

**Status:** FINALIZED v1.0 (2026-06-11) — ready for phased implementation. Becomes fully
authoritative per CLAUDE.md §3 when the SOLUSDEV-2 MR merges. Implementation builds routes
exactly as planned here — paths, methods, request/response shapes. Routes and sections marked
**[DEFERRED]** are explicitly out of scope until their blocking human decision lands (§7.2);
do not implement them. A needed route missing from this plan is proposed in the MR description
and approved before building (CLAUDE.md §3). Implementation order is defined in §8.

**Governing context consulted:** CLAUDE.md (root), DECISIONS.md ADR-001…ADR-022,
`packages/contracts/README.md`, `.claude/skills/api-design`. `docs/architecture/` and
`docs/wireflows/` are currently empty; the working decisions this plan locks in their absence
are recorded in §7.1 and must be reconciled if those documents later contradict them
(higher authority wins).

This document covers four surfaces:

1. **REST API** — the FastAPI core backend (`packages/api`, planned), `/api/v1/*`
2. **Realtime** — WebSocket + SSE endpoints, `/ws/v1/*`
3. **MCP server** — Solus exposed as an MCP server for users' coding agents, `/mcp/v1`
4. **Frontend routes** — the Electron renderer route map (`apps/desktop`)

---

## 1. Global Conventions

### 1.1 Base URL & versioning

- All REST routes live under `/api/v1/`. URL-path versioning (skill recommendation); no v2 until a breaking change forces it.
- WebSockets under `/ws/v1/`, MCP under `/mcp/v1`.
- Infrastructure endpoints (`/healthz`, `/readyz`) are unversioned and unauthenticated.

### 1.2 Authentication (ADR-009)

- Clients authenticate with a **Supabase Auth JWT** in `Authorization: Bearer <jwt>`. The backend validates the JWT; Solus does not run its own login/signup/password endpoints — signup, magic links, password auth, and GitHub OAuth all happen against Supabase from the client.
- Team scoping is enforced by **centralized middleware** (CLAUDE.md §7) on every protected route. No per-endpoint ad-hoc auth.
- WebSocket connections authenticate at connect time (token in first message or query param) and are scoped to one team's project.
- Inbound webhooks (GitHub/GitLab/Onshape) authenticate via provider signature verification, not bearer tokens.

### 1.3 Tenancy model

```
User ──member of──▶ Team ──owns──▶ Project ──contains──▶ Graph (entities, relations), Sources, Bench, …
```

- **Every individual user gets a personal team created at first login.** This is what makes the individual→team upgrade flow (ADR-015) a billing transition rather than a data migration.
- **Locked at finalization (§7.1):** one graph per project, multiple projects per team. The graph, sources, bench, warnings, and all other feature-area resources hang off the project.
- Collection routes are nested under their owner (`/teams/{team_id}/projects`, `/projects/{project_id}/entities`). Middleware resolves `project_id → team_id` and enforces membership on every request. Cross-tenant isolation tests are mandatory per endpoint (CLAUDE.md §6/§7).

### 1.4 Request/response conventions

- JSON, `snake_case` field names (Pydantic v2 backend; the typed TS client maps as-is).
- IDs are UUIDs (UUIDv7 preferred for index locality), opaque to clients.
- Success envelope: `{ "data": …, "meta": …?, "links": …? }`. Error envelope:
  `{ "error": { "code": "...", "message": "...", "details": [...] } }` with semantic HTTP status codes (400/401/403/404/409/422/429).
- **Pagination:** cursor-based by default (`?cursor=&limit=`, `meta.has_next`, `meta.next_cursor`). Offset allowed only on small admin-ish lists.
- **Filtering/sorting:** `?field=value`, bracket comparators (`created_at[after]=`), `?sort=-created_at`, `?q=` for search.
- **Long-running work never runs in the request path** (ADR-005). Any heavy operation returns `202 Accepted` with a Job resource (`{ "data": { "job_id": …, "status": "queued" } }`) and a `Location: /api/v1/jobs/{job_id}` header. Progress is polled via Jobs or pushed over the project WebSocket.
- **Idempotency:** mutating POSTs accept an optional `Idempotency-Key` header; required on billing and deployment endpoints.
- **Rate limiting** (CLAUDE.md §7, ADR-019): all endpoints return `X-RateLimit-Limit/Remaining/Reset`; 429 includes `Retry-After`. Model-backed endpoints additionally enforce credit budgets and return `X-Solus-Credits-Charged` and `X-Solus-Credits-Remaining` headers (ADR-018).
- **SOL mode** (ADR-016): every endpoint that produces natural-language output reads the per-user mode from settings. An optional `X-Sol-Mode: guide|expert` header overrides per-request (e.g., "explain this one to me").
- **Data events** (ADR-011): meaningful interactions emit structured events server-side automatically; the explicit ingestion endpoint (§2.13) exists for client-originated events only.

### 1.5 Metering classes (ADR-018)

| Class                 | Examples                                                                                            | Billing                                                                   |
| --------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **Unmetered**         | CRUD, graph reads, pure-logic checker runs, ambient autocomplete warnings, sync                     | Included in subscription                                                  |
| **Metered (credits)** | Agent conversations, deep diagnoses, LLM warning explanations, fingerprint LLM passes, proving runs | Per-user / pooled team allowance; graceful "lite mode" degradation at cap |

---

## 2. REST API

### 2.0 Infrastructure & meta

| Method | Path              | Auth | Description                            |
| ------ | ----------------- | ---- | -------------------------------------- |
| GET    | `/healthz`        | none | Liveness probe                         |
| GET    | `/readyz`         | none | Readiness (DB, Redis, queue reachable) |
| GET    | `/api/v1/version` | none | API version, build SHA                 |

### 2.1 Users & settings

| Method | Path                                                    | Description                                                                                                 |
| ------ | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/users/me`                                      | Current user profile, teams, trial/subscription status                                                      |
| PATCH  | `/api/v1/users/me`                                      | Update profile (name, avatar)                                                                               |
| DELETE | `/api/v1/users/me`                                      | Account deletion (cascades per data-retention policy)                                                       |
| GET    | `/api/v1/users/me/settings`                             | Settings incl. `sol_mode` (ADR-016), `data_collection_consent` (ADR-011), `onboarding_step` (FND-08 resume) |
| PATCH  | `/api/v1/users/me/settings`                             | Update settings (sol_mode switchable anytime; consent opt-in/out — SOLUSDEV-87)                             |
| GET    | `/api/v1/users/me/notifications`                        | Cross-domain change notifications, cursor-paginated                                                         |
| POST   | `/api/v1/users/me/notifications/{notification_id}/read` | Mark read                                                                                                   |
| POST   | `/api/v1/users/me/notifications/read-all`               | Mark all read                                                                                               |
| GET    | `/api/v1/users/me/api-keys`                             | API keys (MCP access, §4) — prefix shown, secret shown once at creation                                     |
| POST   | `/api/v1/users/me/api-keys`                             | Create key: `{ name, project_ids: [] }` (project-scoped)                                                    |
| DELETE | `/api/v1/users/me/api-keys/{key_id}`                    | Revoke key                                                                                                  |

### 2.2 Teams (feature area 10)

| Method | Path                                          | Description                                                                                                                                                           |
| ------ | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/teams`                               | Teams the caller belongs to                                                                                                                                           |
| POST   | `/api/v1/teams`                               | Create team (also the individual→team upgrade entry point)                                                                                                            |
| GET    | `/api/v1/teams/{team_id}`                     | Team detail                                                                                                                                                           |
| PATCH  | `/api/v1/teams/{team_id}`                     | Rename, settings (admin)                                                                                                                                              |
| DELETE | `/api/v1/teams/{team_id}`                     | Delete team (owner only, confirmation required)                                                                                                                       |
| GET    | `/api/v1/teams/{team_id}/members`             | Members with roles                                                                                                                                                    |
| PATCH  | `/api/v1/teams/{team_id}/members/{user_id}`   | Change role (`owner\|admin\|member\|viewer`)                                                                                                                          |
| DELETE | `/api/v1/teams/{team_id}/members/{user_id}`   | Remove member                                                                                                                                                         |
| GET    | `/api/v1/teams/{team_id}/invites`             | Pending invites                                                                                                                                                       |
| POST   | `/api/v1/teams/{team_id}/invites`             | Invite by email; on a personal team this triggers the seamless individual→team billing transition (ADR-015/017)                                                       |
| DELETE | `/api/v1/teams/{team_id}/invites/{invite_id}` | Revoke invite                                                                                                                                                         |
| POST   | `/api/v1/invites/{invite_token}/accept`       | Accept invite (authed as invitee)                                                                                                                                     |
| GET    | `/api/v1/teams/{team_id}/activity`            | Activity feed (syncs, diagnoses, confirmations, deploys), cursor-paginated, filterable by `?domain=&actor=&type=`; `meta.total` carries the filter-matching row count |

### 2.3 Projects

| Method | Path                                      | Description                                                                                                   |
| ------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/teams/{team_id}/projects`        | List projects with dashboard summary counts; `?include_archived=true` to include archived (added SOLUSDEV-84) |
| POST   | `/api/v1/teams/{team_id}/projects`        | Create project (notifies other team members)                                                                  |
| GET    | `/api/v1/projects/{project_id}`           | Project detail (incl. connected-source summary, graph stats)                                                  |
| PATCH  | `/api/v1/projects/{project_id}`           | Update name/description/settings                                                                              |
| POST   | `/api/v1/projects/{project_id}/archive`   | Archive (soft delete; leaves default listing, keeps graph) — added SOLUSDEV-84                                |
| POST   | `/api/v1/projects/{project_id}/unarchive` | Restore an archived project — added SOLUSDEV-84                                                               |
| DELETE | `/api/v1/projects/{project_id}`           | Delete (admin, confirmation required)                                                                         |

### 2.4 Graph — entities & relations (ADR-001, the core)

Connector-owned entities/relations are **read-only** through this API (the connector is the source of truth; edits happen in the source tool and arrive via sync). Manually created entities (`origin: "manual"`) are user-editable. Concurrency uses optimistic versioning: writes carry `If-Match: <version>`; a stale version returns `409` with the conflicting change summary (feature area 10's graph-informed conflict detection).

| Method | Path                                                           | Description                                                                                                                                                                         |
| ------ | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/projects/{project_id}/entities`                       | List/filter: `?type=&source_id=&domain=&q=&fields=`                                                                                                                                 |
| POST   | `/api/v1/projects/{project_id}/entities`                       | Create manual entity                                                                                                                                                                |
| GET    | `/api/v1/projects/{project_id}/entities/{entity_id}`           | Entity detail incl. provenance (source, last sync)                                                                                                                                  |
| PATCH  | `/api/v1/projects/{project_id}/entities/{entity_id}`           | Update manual entity (409 on connector-owned)                                                                                                                                       |
| DELETE | `/api/v1/projects/{project_id}/entities/{entity_id}`           | Delete manual entity                                                                                                                                                                |
| GET    | `/api/v1/projects/{project_id}/entities/{entity_id}/relations` | Edges touching this entity: `?direction=in\|out\|both&type=`                                                                                                                        |
| GET    | `/api/v1/projects/{project_id}/relations`                      | List/filter relations: `?type=&from=&to=`                                                                                                                                           |
| POST   | `/api/v1/projects/{project_id}/relations`                      | Create manual relation                                                                                                                                                              |
| DELETE | `/api/v1/projects/{project_id}/relations/{relation_id}`        | Delete manual relation                                                                                                                                                              |
| GET    | `/api/v1/projects/{project_id}/graph`                          | **[IMPLEMENTED — WS-01/SOLUSDEV-191]** Subgraph extraction: `?root=<entity_id>&depth=0..2&entity_types=&relation_types=&limit=` — powers the graph view and the shared-focus engine |
| POST   | `/api/v1/projects/{project_id}/graph/query`                    | **[DEFERRED — §7.2.1]** Structured traversal query (body: typed query DSL) for complex multi-hop questions; the SOL Agent's graph tool uses the same code path                      |
| GET    | `/api/v1/projects/{project_id}/graph/changes`                  | Change log of graph deltas: `?since=&domain=` — feeds cross-domain notifications                                                                                                    |

`POST /graph/query` is deferred until the query DSL contract lands in `packages/contracts/` (§7.2.1). All other routes in this section are implementable; `GET /graph` (parameterized subgraph extraction) covers the graph view's needs in the interim.

### 2.5 Sources & integrations (feature area 1)

| Method | Path                                                                | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ------ | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/api/v1/integrations`                                              | Catalog of available connector types (github, gitlab, kicad, onshape, ros) + their required config/auth shape                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| GET    | `/api/v1/integrations/local-tools`                                  | Bridge-hosted desktop tools (vendor-run loopback MCP servers from the ADR-031 catalog — Fusion today): type, display name, loopback host, connect notice. Drives the generic `local-bridge` catalog tile; the next tool is a backend catalog entry, zero frontend edits (SOLUSDEV-72)                                                                                                                                                                                                                                                                                                                                                                                    |
| GET    | `/api/v1/projects/{project_id}/sources`                             | Connected sources with status/last-sync                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| POST   | `/api/v1/projects/{project_id}/sources`                             | Connect a source (type + config; credentials go to encrypted store, never echoed back)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| GET    | `/api/v1/projects/{project_id}/sources/{source_id}`                 | Source detail (config sans secrets, sync history summary)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| PATCH  | `/api/v1/projects/{project_id}/sources/{source_id}`                 | Update config (e.g., watched branch/document)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| DELETE | `/api/v1/projects/{project_id}/sources/{source_id}`                 | Disconnect; body flag `retain_entities: bool`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| POST   | `/api/v1/projects/{project_id}/sources/{source_id}/sync`            | Trigger sync → **202 + Job**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| GET    | `/api/v1/projects/{project_id}/sources/{source_id}/syncs`           | Sync history (status, entity/relation delta counts, errors)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| GET    | `/api/v1/projects/{project_id}/sources/{source_id}/syncs/{sync_id}` | Sync detail incl. per-item errors ("why did this user's sync fail?" answerable)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| POST   | `/api/v1/integrations/{provider}/oauth/start`                       | Begin OAuth (returns provider authorize URL + state); optional `redirect_uri` for the desktop loopback flow                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| GET    | `/api/v1/integrations/{provider}/oauth/callback`                    | Web OAuth redirect target; stores encrypted token, redirects back to app                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| POST   | `/api/v1/integrations/{provider}/oauth/exchange`                    | Desktop loopback completion (added SOLUSDEV-103): app posts the captured `{state, code}`; server exchanges + stores the token. State is bound to the requesting user.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| POST   | `/api/v1/webhooks/{provider}/{source_id}/{token}`                   | Inbound change webhooks (SOLUSDEV-167). **The per-source URL token IS the credential**: `token` is `secrets.token_urlsafe(32)`, minted at connect and stored sha256-digested on the `Source`, so the path resolves to exactly ONE source. Returns **204 without parsing the body** — the payload is a doorbell, never data (§7). Body-matching was rejected: two teams tracking the same upstream document would both match, so one tenant's push would spend another's quota. Provider HMAC (GitHub `X-Hub-Signature-256`) is kept as defence in depth where the vendor actually signs; Onshape publishes no signature scheme, which the token design makes irrelevant. |

### 2.6 Checkers, part compatibility & system proving (feature areas 2, 3)

Checkers are pure functions (graph in, warnings out — ADR-013); runs execute as background jobs.

| Method | Path                                                         | Description                                                                                                                  |
| ------ | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/checkers`                                           | Checker registry: id, domain pair, category (pin, bus, voltage, power, connector, package, occlusion, version…), description |
| POST   | `/api/v1/projects/{project_id}/check-runs`                   | Run selected checkers: body `{ checker_ids?: [], scope?: { entity_ids: [] } }` → **202 + Job**. Pure-logic = unmetered       |
| GET    | `/api/v1/projects/{project_id}/check-runs`                   | Run history                                                                                                                  |
| GET    | `/api/v1/projects/{project_id}/check-runs/{run_id}`          | Status + findings (warnings created, see §2.7)                                                                               |
| POST   | `/api/v1/projects/{project_id}/proving-runs`                 | **System-level proving**: all checkers, whole graph, concurrent → **202 + Job**. Metered (ADR-018)                           |
| GET    | `/api/v1/projects/{project_id}/proving-runs`                 | Proving history                                                                                                              |
| GET    | `/api/v1/projects/{project_id}/proving-runs/{run_id}`        | Status + summary                                                                                                             |
| GET    | `/api/v1/projects/{project_id}/proving-runs/{run_id}/report` | Full-system compatibility report (grouped findings, pass/fail matrix, `?format=json\|pdf`)                                   |

### 2.7 Warnings — robotics autocomplete surface (feature area 11)

Warnings are the durable output of checker runs and change-triggered ambient checks. Accept/dismiss decisions are first-class data-collection events (ADR-011).

| Method | Path                                                              | Description                                                                                                    |
| ------ | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/projects/{project_id}/warnings`                          | List/filter: `?status=open\|accepted\|dismissed\|resolved&severity=&domain=&entity_id=&checker_id=`            |
| GET    | `/api/v1/projects/{project_id}/warnings/{warning_id}`             | Detail: triggering change, involved entities, checker provenance                                               |
| POST   | `/api/v1/projects/{project_id}/warnings/{warning_id}/accept`      | Acknowledge as real (event emitted)                                                                            |
| POST   | `/api/v1/projects/{project_id}/warnings/{warning_id}/dismiss`     | Dismiss with optional `reason` (event emitted)                                                                 |
| GET    | `/api/v1/projects/{project_id}/warnings/{warning_id}/explanation` | LLM explanation in the caller's SOL mode. **Metered**; cached per (warning, mode)                              |
| POST   | `/api/v1/projects/{project_id}/warnings/{warning_id}/diagnose`    | Escalate to SOL Agent → creates agent conversation seeded with the warning context (returns `conversation_id`) |

### 2.8 Multimodal fingerprint (feature area 4, ADR-012)

| Method | Path                                                                        | Description                                                                                                                                               |
| ------ | --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/api/v1/projects/{project_id}/fingerprint/scans`                           | Run the matcher across the graph → **202 + Job**. Heuristic pass unmetered; optional LLM-assisted pass metered                                            |
| GET    | `/api/v1/projects/{project_id}/fingerprint/proposals`                       | Proposed matches: `?status=pending&min_confidence=` — each carries per-signal scores (semantic, supply_chain, topological, spatial) + combined confidence |
| GET    | `/api/v1/projects/{project_id}/fingerprint/proposals/{proposal_id}`         | Proposal detail with signal-by-signal evidence                                                                                                            |
| POST   | `/api/v1/projects/{project_id}/fingerprint/proposals/{proposal_id}/confirm` | Confirm → creates `same_physical_component` link in the graph; logged as labeled data (ADR-011)                                                           |
| POST   | `/api/v1/projects/{project_id}/fingerprint/proposals/{proposal_id}/reject`  | Reject with optional reason; logged as labeled data                                                                                                       |
| GET    | `/api/v1/projects/{project_id}/fingerprint/links`                           | Confirmed identity links                                                                                                                                  |
| DELETE | `/api/v1/projects/{project_id}/fingerprint/links/{link_id}`                 | Unlink (mistaken confirmation)                                                                                                                            |

### 2.9 SOL Agent (feature area 5, ADR-010)

All agent endpoints are **metered**, rate-limited, and budget-guarded (ADR-018/019). Tool calls proposed by the model are validated server-side; any real-world action requires explicit user approval (§7) via the actions sub-resource. Context is assembled fresh per request, team-scoped only.

| Method | Path                                                                                              | Description                                                                                                                                           |
| ------ | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/api/v1/projects/{project_id}/agent/conversations`                                               | Start conversation: `{ message, context?: { entity_ids?, warning_id?, anomaly_id?, error_id? } }` → returns conversation; first response streams (§3) |
| GET    | `/api/v1/projects/{project_id}/agent/conversations`                                               | List conversations                                                                                                                                    |
| GET    | `/api/v1/projects/{project_id}/agent/conversations/{conversation_id}`                             | Full transcript: messages, tool invocations, diagnoses, proposed fixes                                                                                |
| POST   | `/api/v1/projects/{project_id}/agent/conversations/{conversation_id}/messages`                    | Send message. Response: `text/event-stream` (SSE) of tokens, tool-call status, final diagnosis. Respects SOL mode                                     |
| POST   | `/api/v1/projects/{project_id}/agent/conversations/{conversation_id}/cancel`                      | Cancel in-flight run (loop-guard surface)                                                                                                             |
| GET    | `/api/v1/projects/{project_id}/agent/conversations/{conversation_id}/actions`                     | Pending proposed actions awaiting approval                                                                                                            |
| POST   | `/api/v1/projects/{project_id}/agent/conversations/{conversation_id}/actions/{action_id}/approve` | Approve a concrete shown action (deploy, modify external system, delete graph data). **No silent execution**                                          |
| POST   | `/api/v1/projects/{project_id}/agent/conversations/{conversation_id}/actions/{action_id}/reject`  | Reject proposed action                                                                                                                                |
| DELETE | `/api/v1/projects/{project_id}/agent/conversations/{conversation_id}`                             | Delete conversation                                                                                                                                   |

### 2.10 Live Bench (feature area 6, ADR-014)

One session model, two modes. Telemetry flows over WebSocket (§3); REST manages lifecycle.

> **SOLUSDEV-72 amendment (2026-08-16).** The local-connections surface added three
> routes to this section, and the session start/list/detail/stop subset below is now
> implemented (see API-implementation.md §15b for the live shapes). Sessions run the
> LiveConnection pump in-process and tee packets into the existing §2.13 ingest sink —
> one telemetry path, never two. `config` is discriminated by `config.provider`
> (`mujoco` | `gazebo` | `mcap-replay` for sim; `serial` for real); serial sessions bind
> devices by **USB serial number** resolved to `/dev/serial/by-id` (never a raw tty path),
> refusing ambiguous/absent serials without an explicit user-confirmed pick.

| Method | Path                                                                                 | Description                                                                                                                                                                                                                        |
| ------ | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/projects/{project_id}/bench/sources`                                        | What THIS machine can start, honestly: simulators (available / not-installed + reason) and enumerated USB-serial devices (serial, vid:pid, board claim, `mcu_known`, confidence, ambiguity) plus runner availability (SOLUSDEV-72) |
| GET    | `/api/v1/projects/{project_id}/bench/device-recent`                                  | `?device_id=&limit=` — recent values for a streaming device that has **no graph entity yet** (pre-RBT-05); includes `resolved_entity_id` when the device does resolve (SOLUSDEV-72)                                                |
| POST   | `/api/v1/projects/{project_id}/bench/sessions`                                       | Start session: `{ mode: "sim"\|"real", config }` (sim: model ref; real: serial/ROS source)                                                                                                                                         |
| GET    | `/api/v1/projects/{project_id}/bench/sessions`                                       | Sessions: `?status=active\|ended&mode=`                                                                                                                                                                                            |
| GET    | `/api/v1/projects/{project_id}/bench/sessions/{session_id}`                          | Session detail: mode, signals registered, duration, anomaly count                                                                                                                                                                  |
| POST   | `/api/v1/projects/{project_id}/bench/sessions/{session_id}/stop`                     | End session                                                                                                                                                                                                                        |
| GET    | `/api/v1/projects/{project_id}/bench/sessions/{session_id}/signals`                  | Signal catalog for the session (name, unit, rate, source entity)                                                                                                                                                                   |
| GET    | `/api/v1/projects/{project_id}/bench/sessions/{session_id}/signals/{signal_id}/data` | Historical window: `?from=&to=&resolution=` (downsampled)                                                                                                                                                                          |
| POST   | `/api/v1/projects/{project_id}/bench/sessions/{session_id}/recordings`               | Start/stop a named recording: `{ action: "start"\|"stop", name? }`                                                                                                                                                                 |
| GET    | `/api/v1/projects/{project_id}/bench/recordings`                                     | Stored recordings                                                                                                                                                                                                                  |
| GET    | `/api/v1/projects/{project_id}/bench/sessions/{session_id}/anomalies`                | Detected anomalies (signal, window, kind, severity)                                                                                                                                                                                |
| POST   | `/api/v1/projects/{project_id}/bench/anomalies/{anomaly_id}/diagnose`                | **Send-to-agent**: creates agent conversation seeded with anomaly + graph context                                                                                                                                                  |
| GET    | `/api/v1/projects/{project_id}/bench/sim/model`                                      | Current MJCF model + provenance (which CAD sync produced it)                                                                                                                                                                       |
| POST   | `/api/v1/projects/{project_id}/bench/sim/model/rebuild`                              | Regenerate MJCF from latest CAD/URDF → **202 + Job** (also auto-triggered on CAD sync)                                                                                                                                             |

### 2.11 Error logging & prediction (feature area 7)

| Method | Path                                                                | Description                                                                                                                        |
| ------ | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/api/v1/projects/{project_id}/errors`                              | Ingest error(s) — batch-capable; sources: desktop app, deploy targets, bench sessions. Payload validated/bounded (untrusted input) |
| GET    | `/api/v1/projects/{project_id}/errors`                              | List/filter: `?source=&severity=&entity_id=&from=&to=`                                                                             |
| GET    | `/api/v1/projects/{project_id}/errors/{error_id}`                   | Error detail with linked graph entities                                                                                            |
| POST   | `/api/v1/projects/{project_id}/errors/{error_id}/diagnose`          | Escalate to SOL Agent (metered) → conversation                                                                                     |
| GET    | `/api/v1/projects/{project_id}/predictions`                         | Predicted likely failures (checker + agent derived): `?status=open&severity=`                                                      |
| GET    | `/api/v1/projects/{project_id}/predictions/{prediction_id}`         | Prediction detail: evidence chain, affected entities                                                                               |
| POST   | `/api/v1/projects/{project_id}/predictions/{prediction_id}/dismiss` | Dismiss (event emitted)                                                                                                            |

### 2.12 Deployment (feature area 8)

Flashing/SSH execution happens **on the user's machine via the desktop app**; the API manages targets, artifacts, history, and coordination. Every deployment is an explicit user-confirmed action (§7). `Idempotency-Key` required on deployment creation.

**Locked at finalization (§7.1):** the status-callback `PATCH` authenticates with the same Supabase user JWT as every other route — the desktop app already holds the user's session, so no device-credential scheme is introduced this cycle. The callback is additionally restricted to the user who created the deployment (403 otherwise), and status transitions are validated server-side (`queued→running→succeeded|failed` only).

| Method | Path                                                                   | Description                                                                                               |
| ------ | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/projects/{project_id}/deploy/targets`                         | Registered targets                                                                                        |
| POST   | `/api/v1/projects/{project_id}/deploy/targets`                         | Register target: `{ kind: "arduino"\|"ssh", config }` (SSH credentials → encrypted store, never returned) |
| GET    | `/api/v1/projects/{project_id}/deploy/targets/{target_id}`             | Target detail + last deployment                                                                           |
| PATCH  | `/api/v1/projects/{project_id}/deploy/targets/{target_id}`             | Update config                                                                                             |
| DELETE | `/api/v1/projects/{project_id}/deploy/targets/{target_id}`             | Remove target                                                                                             |
| POST   | `/api/v1/projects/{project_id}/deploy/targets/{target_id}/deployments` | Create deployment: `{ artifact_ref, source_ref }` → **202**; desktop app executes and reports status back |
| GET    | `/api/v1/projects/{project_id}/deployments`                            | Deployment history: `?target_id=&status=`                                                                 |
| GET    | `/api/v1/projects/{project_id}/deployments/{deployment_id}`            | Status, version, what-changed summary                                                                     |
| PATCH  | `/api/v1/projects/{project_id}/deployments/{deployment_id}`            | Status callback from the executing desktop client (`running\|succeeded\|failed` + logs ref)               |
| GET    | `/api/v1/projects/{project_id}/deployments/{deployment_id}/logs`       | Deployment/flash logs                                                                                     |

### 2.13 Data collection events (feature area 9, ADR-011)

| Method | Path                       | Description                                                                                                                                                                                        |
| ------ | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/api/v1/events`           | Batch ingest of client-originated structured events, validated against the event schema contract in `packages/contracts/`. Server-originated events are emitted internally, not through this route |
| GET    | `/api/v1/users/me/consent` | Current data-collection consent state                                                                                                                                                              |
| PUT    | `/api/v1/users/me/consent` | Update consent (consent-gated collection is the ADR-011 invariant)                                                                                                                                 |

No query/export API this cycle — storage is internal (ADR-011). Revisit when analysis tooling is needed; not a blocker.

### 2.14 Usage, budgets & billing (ADR-017/018/019)

One budget system serves security and billing. Admin-only routes marked (A).

Usage and budget routes (the ADR-019 security half) are implementable now. The four provider-facing billing routes (checkout, portal, top-ups, billing webhook) are **[DEFERRED — §7.2.2]** until the payment-provider ADR lands; their shapes below are the plan of record once it does.

| Method | Path                                           | Description                                                                                                                                                                                       |
| ------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/users/me/usage`                       | Always-visible meter (IMPLEMENTED, SOLUSDEV-233): `{used, allowance, balance, cycle_start, cycle_end}` — credits used this anniversary cycle vs. the plan grant; per-category split still planned |
| GET    | `/api/v1/teams/{team_id}/usage`                | Pooled team meter; `?group_by=member\|category\|day` (A for member breakdown)                                                                                                                     |
| GET    | `/api/v1/teams/{team_id}/budget`               | Caps, alert thresholds, degradation ("lite mode") state                                                                                                                                           |
| PATCH  | `/api/v1/teams/{team_id}/budget`               | (A) Set spending caps, alert thresholds, overage opt-in — never silent charges                                                                                                                    |
| GET    | `/api/v1/teams/{team_id}/billing/subscription` | Plan, seats, trial state, renewal                                                                                                                                                                 |
| POST   | `/api/v1/teams/{team_id}/billing/checkout`     | **[DEFERRED]** (A) Start checkout/upgrade flow (seat changes, individual→team transition) → provider redirect URL                                                                                 |
| POST   | `/api/v1/teams/{team_id}/billing/portal`       | **[DEFERRED]** (A) Billing-portal session (payment method, invoices)                                                                                                                              |
| POST   | `/api/v1/teams/{team_id}/billing/top-ups`      | **[DEFERRED]** (A) Purchase credit top-up pack (`Idempotency-Key` required)                                                                                                                       |
| GET    | `/api/v1/teams/{team_id}/billing/invoices`     | Invoice list                                                                                                                                                                                      |
| POST   | `/api/v1/webhooks/billing`                     | **[DEFERRED]** Payment-provider webhooks (signature-verified)                                                                                                                                     |

### 2.15 Workspaces & tutorial overlay (feature area 12)

| Method | Path                                                | Description                                                                                                                               |
| ------ | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/tutorials`                                 | Available guided flows: `?surface=app\|overlay&tool=`                                                                                     |
| GET    | `/api/v1/tutorials/{tutorial_id}`                   | Tutorial definition (steps, anchors, completion criteria). Step copy respects SOL mode                                                    |
| GET    | `/api/v1/users/me/tutorials/progress`               | Progress across all tutorials                                                                                                             |
| PUT    | `/api/v1/users/me/tutorials/{tutorial_id}/progress` | Update progress (current step, completed)                                                                                                 |
| GET    | `/api/v1/overlay/guides`                            | Browser-extension overlay: `?tool=onshape&context=<page-context>` → contextual guidance payload for the current page in the external tool |

### 2.16 Jobs (shared infrastructure, ADR-005)

Every `202 Accepted` from any feature area resolves here. Job completion/progress also pushes over the project WebSocket.

| Method | Path                                 | Description                                                                                    |
| ------ | ------------------------------------ | ---------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/jobs/{job_id}`              | Status: `queued\|running\|succeeded\|failed\|cancelled`, progress %, result ref, error context |
| GET    | `/api/v1/projects/{project_id}/jobs` | Project job list: `?kind=sync\|check_run\|proving\|fingerprint_scan\|sim_rebuild&status=`      |
| POST   | `/api/v1/jobs/{job_id}/cancel`       | Cancel queued/running job                                                                      |

---

## 3. Realtime — WebSocket & SSE

WebSocket implementations live behind the isolated telemetry service boundary (ADR-005) so the Rust rewrite (ADR-004) swaps the implementation, not the interface. All connections authenticate at connect time and are scoped to one team's project (§7). Device-originated telemetry is parsed defensively: bounded message sizes, malformed packets dropped and logged, never crash the service.

| Protocol | Path                                              | Direction     | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| -------- | ------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SSE      | `GET /api/v1/projects/{project_id}/events`        | server→client | Project event channel (SOLUSDEV-167). Carries `graph.changed` — an invalidation **hint** (`{type, project_id, source_id, sync_id, counts, at}`, ~200 bytes), never a delta: the host refetches its one focused key, so N mounted lenses stay one request (`widget-contract.md` §"never fetch your own scope"). **SSE, not WS, and the reason is auth**: the only existing WS auth in this repo reads an `Authorization` header, which works solely because the companion is a Python client — no browser `WebSocket` can set a header, and the renderer is Chromium. SSE runs under the ordinary `ProjectCtx` dependency, so it needs no new credential path, and the client half already ships (`solStream.ts`). One-way is sufficient; the client subscribes by connecting. |
| WS       | `/ws/v1/bench/sessions/{session_id}`              | bidirectional | Live Bench telemetry stream — packets per the telemetry contract in `packages/contracts/` (one format for sim AND real, ADR-014). Client→server: control inputs (sim), subscription changes. Server→client: signal frames, anomaly events                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| SSE      | `POST …/agent/conversations/{id}/messages` (§2.9) | server→client | Agent response streaming: token deltas, tool-call lifecycle events, action-approval requests, final message. SSE chosen over WS here: one-shot streams, simpler client, no bidirectional need                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

**Locked at finalization (§7.1):** SSE for agent response streaming, WS for telemetry — Electron's Chromium renderer supports both natively, and the one-shot nature of agent responses fits SSE.

**Amended — SOLUSDEV-167:** the **project event channel is SSE**, not WS. The original choice assumed the bridge's WS auth could be reused; it cannot — that pattern reads an `Authorization` header, which is available only because the companion is a Python client. A browser `WebSocket` cannot set headers, so WS here would mean inventing a second credential path (subprotocol- or query-carried) plus reconnect logic in the client, to buy a bidirectional channel nothing needs. SSE runs under the ordinary `ProjectCtx` dependency and reuses the shipped client parser. Consequently there is **no client `subscribe` frame and no topic set** — connecting to a project's stream IS the subscription, and `graph.changed` is the only event type produced today. `warnings` and `jobs` become additional event types on the same stream when their producers exist; `presence` stays **[DEFERRED — §7.2.4]** on its own schema. WS remains the telemetry transport (`/ws/v1/bench/sessions/{session_id}`), where the client genuinely sends control input.

---

## 4. MCP Server — `/mcp/v1` **[DEFERRED — §7.2.3, entire section]**

Solus as an MCP server lets a user's coding agent (Claude Code, etc.) query the robot's cross-domain context while writing firmware — the graph becomes context for external AI tools.

> **Governance note:** an MCP surface is not one of the twelve feature areas in CLAUDE.md §2 and requires an ADR to enter scope. This section is the agreed shape **if and when** that ADR lands — do not implement any of it before then. The REST routes it maps onto (and the API-key routes in §2.1 that would authenticate it) are independently useful and are NOT deferred.

**Transport & auth:** Streamable HTTP at `/mcp/v1`. Auth via per-user **Solus API keys** (§2.1, project-scoped, revocable). All tool handlers run through the same team-scoping middleware and rate/budget limits as the REST API; the key carries the user's permissions — never elevated (§7).

**Tools (all read or propose; no destructive writes via MCP this cycle):**

| Tool                       | Maps to          | Description                                             |
| -------------------------- | ---------------- | ------------------------------------------------------- |
| `solus_list_projects`      | §2.3             | Projects visible to the key                             |
| `solus_query_graph`        | §2.4 graph/query | Traversal queries: "what does this I2C bus connect to?" |
| `solus_get_entity`         | §2.4             | Entity detail + relations + provenance                  |
| `solus_search_entities`    | §2.4 list        | Search by name/type/domain                              |
| `solus_get_warnings`       | §2.7             | Open cross-domain warnings, filterable                  |
| `solus_run_checkers`       | §2.6             | Run pure-logic checkers, return findings (unmetered)    |
| `solus_get_proving_report` | §2.6             | Latest full-system compatibility report                 |
| `solus_fingerprint_status` | §2.8             | Identity links + pending proposals for an entity        |
| `solus_get_bench_status`   | §2.10            | Active sessions, recent anomalies, signal snapshot      |
| `solus_get_errors`         | §2.11            | Recent errors/predictions for an entity or subsystem    |

**Resources:** `solus://projects/{project_id}/graph`, `solus://projects/{project_id}/warnings`, `solus://projects/{project_id}/proving-report` — read-only snapshots for context loading.

Graph content returned through MCP is ingested-tool data — callers' agents must treat it as data, and Solus wraps/delimits it accordingly (§7 prompt-injection rules apply in both directions).

---

## 5. Frontend Routes — Electron Renderer (`apps/desktop`)

React Router (memory/hash history in Electron). The persistent SOL "ball of energy" presence and the always-visible usage meter (ADR-018) live in the app shell, outside the router.

> `docs/wireflows/` is empty at finalization; this map is the plan of record until wireflows exist. When they land, wireflows win (CLAUDE.md §3) and this section is reconciled in the same MR.

```
/login                                  Supabase auth (password, magic link, GitHub OAuth)
/onboarding                             First-run: create/join team, connect first source, pick SOL mode

/                                       Workspace home: project list across teams, recent activity
/projects/:projectId                    Project overview: graph stats, source health, open warnings, recent jobs
/projects/:projectId/graph              Graph explorer (subgraph view, entity inspector panel)
/projects/:projectId/graph/:entityId    Entity detail (relations, provenance, warnings, identity links)
/projects/:projectId/sources            Connected sources, sync status/history
/projects/:projectId/sources/connect    Connector catalog + connect flow (incl. OAuth handoff)
/projects/:projectId/checks             Check runs, checker registry, run-selected UI
/projects/:projectId/proving            Proving runs + full-system report viewer
/projects/:projectId/warnings           Warning inbox (filter, accept/dismiss, explain, send-to-agent)
/projects/:projectId/fingerprint        Match proposals (confirm/reject), confirmed links
/projects/:projectId/agent              SOL Agent conversation list
/projects/:projectId/agent/:conversationId   Conversation view (stream, tool timeline, action approvals)
/projects/:projectId/bench              Live Bench: mode switch (sim/real), signal plots, anomalies, recordings
/projects/:projectId/bench/:sessionId   Session detail / replay
/projects/:projectId/errors             Error log + predictions
/projects/:projectId/deploy             Targets, deploy action (confirm dialog), deployment history
/projects/:projectId/settings           Project settings

/teams/:teamId                          Team home: activity feed, members
/teams/:teamId/members                  Members, roles, invites (admin)
/teams/:teamId/usage                    Pooled usage, budget caps (admin), per-member breakdown
/teams/:teamId/billing                  Subscription, seats, top-ups, invoices (admin)
/teams/:teamId/settings                 Team settings

/settings                               Profile, SOL mode toggle, notifications, consent, API keys
/settings/usage                         Personal usage meter detail
/tutorials                              Guided-flow library
/tutorials/:tutorialId                  In-app tutorial runner
```

---

## 6. Cross-Cutting Security Checklist (binds every endpoint above)

Restating CLAUDE.md §7 obligations as they apply to this surface — every implementing MR must satisfy:

- [ ] Centralized authN/authZ middleware; team-scoped queries; cross-tenant isolation test per endpoint
- [ ] Pydantic validation on every input; unknown fields rejected on sensitive endpoints
- [ ] Connector/webhook/telemetry/error payloads treated as untrusted (bounded, parsed defensively)
- [ ] Ingested content reaching any prompt is wrapped as data — never instructions (agent, explanations, overlay)
- [ ] Model-proposed tool calls validated against schema + authz before execution; destructive actions require explicit approval (§2.9 actions)
- [ ] Rate limits on everything; credit budgets + loop guards on all metered routes (ADR-019)
- [ ] Credentials encrypted at rest, never logged, never in any response body
- [ ] No secrets in model context, ever
- [ ] Structured event emitted for every meaningful interaction (ADR-011)

---

## 7. Design-Review Outcomes

The six open questions from the draft review, resolved or deferred at finalization (2026-06-11).

### 7.1 Resolved — locked working decisions

These were local/API-surface decisions (CLAUDE.md §10: improvising on local details is expected); each is recorded inline where it applies. If a later architecture diagram or wireflow contradicts one, the higher-authority document wins and this file is updated in the same MR.

- **Graph ownership** (was Q4): one graph per project, multiple projects per team (§1.3). Consistent with the ADR-001 tenancy chain; no DECISIONS.md entry contradicts it.
- **Agent streaming transport** (was Q5): SSE for agent responses, WS for project events and telemetry (§3). Electron's renderer is Chromium — both are natively supported; SSE fits one-shot response streams.
- **Deployment callback auth** (was Q6): same Supabase user JWT, restricted to the deployment's creator, with server-validated status transitions (§2.12). No new credential scheme this cycle.

### 7.2 Deferred — blocked on a human decision (do **not** implement)

Routes/sections marked **[DEFERRED]** above trace here. Everything else in this document is implementable.

1. **Graph query DSL** (§2.4, `POST /graph/query`) — blocked on a query-DSL contract in `packages/contracts/` (human-owned). `GET /graph` covers interim needs.
2. **Provider-facing billing** (§2.14: checkout, portal, top-ups, billing webhook) — blocked on a payment-provider ADR (Stripe-shaped as drafted). Usage/budget routes are NOT blocked.
3. **MCP server** (§4, entire surface) — blocked on an ADR adding it to scope. The §2.1 API-key routes it would use are NOT blocked.
4. **Presence/concurrency topic** (§3, project WS channel) — blocked on the presence message schema landing in the telemetry/event contracts. The other WS topics are NOT blocked.

---

## 8. Implementation Phasing

Recommended build order for the first implementation tickets. Each phase is independently shippable and respects the dependency direction (everything depends on Phase 1's middleware, envelope, and Jobs plumbing). One ticket per slice per the MR-scope rule (CLAUDE.md §6); the phases below are groupings, not single tickets.

| Phase                      | Sections                                                         | Contents                                                                                                                                                                                                                       |
| -------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **1 — Foundation**         | §2.0, §2.1 (sans api-keys), §2.2, §2.3, §2.16                    | App skeleton, health probes, JWT validation + centralized team-scoping middleware, response envelope, error format, users/settings, teams, projects, Jobs infrastructure (ARQ + Redis). This is the first implementation slice |
| **2 — Graph core**         | §2.4 (sans `graph/query`), §3 project WS channel (sans presence) | Entity/relation CRUD, subgraph extraction, change log, graph deltas over WS. Requires the entity/relation contract in `packages/contracts/`                                                                                    |
| **3 — Sources & sync**     | §2.5                                                             | Connector catalog, source lifecycle, sync jobs, OAuth flows, inbound webhooks. Requires the connector contract; first connector (GitHub) rides along                                                                           |
| **4 — Reasoning surface**  | §2.6, §2.7                                                       | Checker registry, check runs, proving runs, warnings. Requires the checker contract                                                                                                                                            |
| **5 — Metered features**   | §2.9, §2.7 explanation, §2.8, §2.14 usage/budget                 | Budget/rate-limit system first (ADR-019 — it gates everything else here), then agent conversations + SSE, fingerprint, warning explanations                                                                                    |
| **6 — Runtime & the rest** | §2.10, §2.11, §2.12, §2.13, §2.15, §3 bench WS                   | Live Bench, errors/predictions, deployment, events ingestion, tutorials                                                                                                                                                        |

Within every phase: TDD per CLAUDE.md §6, cross-tenant isolation test per endpoint, structured events per ADR-011, and the §6 security checklist on every MR.

---

## Restoration note (SOLUSDEV-191 / WS-01, 2026-08-01)

This file is authority level 3 (CLAUDE.md §3) but was **deleted from the tree** in commit
`d4fa914` ("Solusdev 72 shared dev models"), apparently by accident — nothing referenced its
removal, and ~40 source comments still cite it ("API.md §2.4", "§1.4", "§5"). It was absent from
both `main` and every feature branch until now. Restored verbatim from `d4fa914^`, with §2.4's
`GET /graph` row marked implemented.

Two caveats for readers:

- Everything else here is the route **plan** as written at SOLUSDEV-2 and is not a statement of
  what exists today. `docs/api/API-implementation.md` is the record of what is actually built.
- §5's frontend route map predates the workspace shell (which navigates by `useState` inside
  `WorkspaceShell`, not by URL). Treat it as intent, not as current structure.
