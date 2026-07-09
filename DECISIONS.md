# DECISIONS.md — Solus Architecture Decision Records

This file is the authoritative record of locked decisions. It sits at the top of the document authority hierarchy (see CLAUDE.md §3). Agents read it and treat it as settled; agents never modify it. Decisions change only through deliberate human revision of an entry (mark the old entry Superseded, add the new one). Each entry: context, decision, alternatives rejected, and when to revisit.

All entries below were codified 2026-06-06 from the initial planning cycle.

> **Provenance note (2026-07-04, SOLUSDEV-72):** ADR-023–028 and the 2026-07-04 amendments/status changes on ADR-003, ADR-009, ADR-010, ADR-015, ADR-017, and ADR-018 were drafted by an AI agent under the founders' explicit instruction during SOLUSDEV-72 and are committed by a human — consistent with the human-owned-file rule (CLAUDE.md §5/§10). Each carries a dated `SOLUSDEV-72` marker.

---

## ADR-001: Graph-centric architecture (the Robotics Context Model)

**Status:** Accepted
**Context:** Solus's value is cross-domain reasoning over a robot's code, electronics, mechanical design, and runtime.
**Decision:** The unified graph (typed entities + typed relations) is the core abstraction. Connectors write to it; checkers, the fingerprint matcher, and the SOL Agent read from it. No feature reasons over tool-specific raw data directly.
**Rejected:** Per-tool feature silos; document-store representations.
**Revisit when:** Never expected — this is the product thesis.

## ADR-002: Python 3.12 + FastAPI backend

**Status:** Accepted
**Context:** Reasoning layer (LLM orchestration), robotics ecosystem (URDF, MuJoCo, ROS, KiCad APIs), and agent-friendliness are all Python-native. Two-developer team leaning on AI agents.
**Decision:** FastAPI + Pydantic v2 + SQLAlchemy 2.0/Alembic for the core API and orchestration.
**Rejected:** Node/TS (language boundary to all intelligence code), Go (weak robotics/ML ecosystem), Rust now (see ADR-004), Django (heavier, less async-native).
**Revisit when:** Specific hot paths prove too slow — swap those behind their seams (ADR-005), not the whole backend.

## ADR-003: PostgreSQL on AWS RDS, with pgvector

**Status:** Accepted
**Context:** Need relational integrity for the graph/teams/billing plus vector search for embeddings (fingerprint, retrieval).
**Decision:** Single managed Postgres with pgvector. Alembic migrations. Team-scoped access on every query.
**Rejected:** SQLite (no multi-tenant production story), Mongo (graph integrity), dedicated graph DB (premature; Postgres handles our scale).
**Revisit when:** Graph query patterns outgrow relational modeling at real scale.
**See also (2026-07-04, SOLUSDEV-72):** ADR-027 locks the concrete graph/pgvector schema conventions (`graph_entity`/`graph_edge`, `Vector(1536)` ivfflat, `canonical_part_id`) and records the Neo4j-evaluated-and-deferred decision behind a graph-access seam.

## ADR-004: Rust deferred to the next build cycle

**Status:** Accepted
**Context:** Rust (with yrs CRDTs) is the right long-term core for real-time collaboration and high-frequency telemetry, but a from-scratch Rust build doesn't fit the current 3-month cycle, and agents are slower/less reliable in Rust.
**Decision:** Ship this cycle in Python/TypeScript. Plan the Rust migration of the telemetry/collaboration core for the post-summer cycle.
**Rejected:** Full Rust rewrite now (timeline-fatal); tch-rs for ML ever (PyTorch ecosystem wins).
**Revisit when:** Post-summer cycle planning, or earlier if telemetry throughput becomes a real bottleneck.

## ADR-005: Clean seams around performance-critical boundaries

**Status:** Accepted
**Context:** Python has real limits in high-frequency realtime and CPU-bound work; we want surgical future swaps (ADR-004) instead of rewrites.
**Decision:** Telemetry streaming is an isolated service behind a stable WebSocket interface. Checkers are pure stateless functions (graph in, warnings out). All heavy analysis runs as background jobs (ARQ + Redis), never in the request path.
**Rejected:** Monolith with inline analysis.
**Revisit when:** N/A — the seams are the point.

## ADR-006: AWS with App Runner/ECS Fargate; no Kubernetes this cycle

**Status:** Accepted
**Context:** Two developers, no K8s operational experience, a handful of services.
**Decision:** Containers on App Runner or ECS Fargate; ECR; S3 for files; Secrets Manager; CloudWatch. GitLab CI builds and deploys.
**Rejected:** EKS/Kubernetes (weeks of ops overhead, zero product benefit at this scale).
**Revisit when:** >10 services, a dedicated platform engineer, or orchestration needs Fargate can't meet.

## ADR-007: GitLab monorepo + GitLab CI

**Status:** Accepted
**Decision:** Single monorepo. CI stages: lint → type-check → test → secret scan + dependency audit → build → deploy staging → deploy production on main merge. Protected main; MR-only.
**Rejected:** Polyrepo (coordination overhead for a 2-person team), GitHub (team preference: GitLab).

## ADR-008: Frontend — Electron + React + TypeScript + Vite + Tailwind + Zustand

**Status:** Accepted
**Context:** Desktop-first product; team knows the stack; Tauri is attractive later but a migration distraction now.
**Decision:** Electron this cycle. Strict TS, typed API client, Zustand state, feature-panel component scoping.
**Rejected:** Tauri now (pairs naturally with the Rust cycle, ADR-004), web-only (hardware access needs desktop).
**Revisit when:** The Rust cycle — Tauri shell rides along.

## ADR-009: Managed auth (Supabase Auth)

**Status:** Accepted
**Decision:** Supabase Auth for signup, magic links (academic users), password and GitHub OAuth. Backend validates JWTs; team scoping in our middleware.
**Rejected:** Rolling our own auth (never), Auth0 (cost at our stage).
**Revisit when (hardening — tracked, deferred, 2026-07-04, SOLUSDEV-72):** The backend currently validates Supabase JWTs via **HS256 shared-secret** — the signature IS cryptographically verified and `exp`/`aud` are checked, so forged tokens do **not** pass; **this is not a current vulnerability.** Migrating to **Supabase JWKS / RS256 (asymmetric) verification** (verify against a rotating public key; the backend holds no signing secret) and adding an **issuer (`iss`) check** is a deferred hardening item requiring a coordinated Supabase-config + code change. Not urgent — schedule when asymmetric signing keys are provisioned.

## ADR-010: SOL Agent is an orchestrator, not a custom multimodal model

**Status:** Accepted
**Context:** A trained-from-scratch multimodal robotics model is a multi-year research effort. The graph already performs structural multimodal fusion.
**Decision:** The agent orchestrates: pulls subgraph context, invokes validated tools (checkers, geometry analysis, retrieval), calls hosted LLMs (Claude) for reasoning, combines results. Specialized models plug in as tools behind the tool interface.
**Rejected:** Training custom foundation/multimodal models this cycle; monolithic model ingesting raw CAD/code/schematics.
**Revisit when:** ≥10–15K labeled interaction examples exist (see ADR-011) — then fine-tuning specialized models (e.g., heterogeneous GNNs for change-impact) becomes justified.
**See also (2026-07-04, SOLUSDEV-72):** ADR-026 locks the multi-model routing mechanics (the `route()` function, the model catalog as config, complexity-tier routing, and per-call cost tracking) the orchestrator uses.

## ADR-011: Data collection without a training pipeline

**Status:** Accepted
**Decision:** Every meaningful interaction (sync, diagnosis, fingerprint confirm/reject, warning accept/dismiss, fix outcome) is logged as a structured, consented event per the event schema. No training infrastructure this cycle. ToS must permit anonymized use for model improvement.
**Rejected:** Building training pipelines now (wasted months), not collecting (forfeits the long-term moat).

## ADR-012: Fingerprint matching ships as weighted heuristics + human confirmation

**Status:** Accepted
**Context:** Cross-tool entity identity (CAD part = schematic IC = ROS node) via four signals: semantic, supply chain (MPN), topological, spatial.
**Decision:** v1 combines signals with fixed weights into a confidence score; users confirm/reject proposed matches; confirmations link entities and become labeled data. Spatial signal is lowest weight (coordinate-frame fragility) and built last.
**Rejected:** Learned matcher now (no data yet).
**Revisit when:** Confirmation data is sufficient to train the learned version.

## ADR-013: Robotics autocomplete = checker library, not a predictive model

**Status:** Accepted
**Decision:** Proactive cross-domain warnings come from a library of pure-function checkers (pin conflicts, bus addresses, voltage, power budget, casing-port occlusion, deployment version mismatches, lifecycle flags, etc.) triggered on change, with LLM-generated explanations. System-level proving = all checkers run concurrently as a background job. Part compatibility = the parts-focused checker subset.
**Rejected:** Neural prediction of failures (no training data; rule precision builds trust first).

## ADR-014: MuJoCo as the built-in sim; integrate with external sims, don't compete

**Status:** Accepted
**Decision:** Live Bench ships Sim mode (MuJoCo from the team's URDF/CAD, updating on CAD sync) and Real mode (serial/ROS telemetry) behind one UI and one telemetry packet format. Isaac Sim/Gazebo are integration targets (read their data), never competitors. No parallel-environment RL infrastructure, no photorealistic rendering, no experiment-tracking product (integrate W&B/MLflow instead).
**Rejected:** Building a simulator/training platform (Isaac/Antioch's territory; years of work).

## ADR-015: Customer tiers — one product, tiered go-to-market

**Status:** Accepted
**Decision:** Individuals (self-serve, product-led), Teams (core segment, founder-led), Education/student teams (flat-license design partners, e.g., FSAE), Enterprise (deferred: inbound only, quote don't build — but never foreclose self-hosting/SSO/audit logs architecturally). No segment-exclusive features. The individual→team upgrade flow is a first-class requirement.
**Rejected:** Enterprise-first (procurement cycles kill a seed-stage company), hobbyist-first pricing.
**Clarified (2026-07-04, SOLUSDEV-72):** These are go-to-market **segments** (who we sell to and how), distinct from the billing **plans** (BASIC / PRO / ENTERPRISE, ADR-023). The individual→team upgrade is realized structurally by the auto-created personal team (ADR-025), so it is a billing/scope transition, not a data migration.

## ADR-016: SOL modes are a universal setting

**Status:** Accepted
**Decision:** Guide mode (teaches, explains, assumes domain unfamiliarity) and Expert mode (terse, leads with answers) — per-user, switchable anytime, available on every tier. Every feature producing natural-language output consumes the mode setting.
**Rejected:** Modes as a tier differentiator.

## ADR-017: Pricing — no free-forever tier; base subscription + credit allowance

**Status:** **Superseded by ADR-023 (pricing structure) and ADR-024 (credits)** — 2026-07-04, SOLUSDEV-72. _(Earlier: Accepted; amended 2026-07-03 to make the team credit allowance per-user, not pooled.)_
**Superseded:** The three-plan structure (BASIC / PRO / ENTERPRISE) in ADR-023 replaces the Individual/Team-seat pricing described below; the per-user credit model is carried forward and detailed in ADR-024. The body is retained for history only — do not read it as the current pricing.
**Decision (historical):** Trial-then-pay (30-day or active-days trial; no card to start). Individual: $20/mo (annual ≈ $192) including a monthly credit allowance. Teams: per-seat ($50 academic / $120 commercial, 3-seat min); each member gets a **per-user** monthly credit allowance — credits are per-user regardless of team, so they follow a user across the individual→team upgrade — under admin-controlled per-team spending caps. Education: flat ≈$1,500/yr unlimited-seat license. Enterprise: quoted; committed-use credit blocks later.
**Rejected (historical):** Free-forever tier (support load, weak demand signal).
**Amended (2026-07-03, SOLUSDEV-72):** Originally specified a _pooled_ team credit allowance and rejected per-member allowances (rationale: robotics usage is lumpy, pooling absorbs spikes). Superseded by per-user allowances: usage attribution is per-user (feeds ADR-011 cost-calibration and user history), credits/history stay portable across the individual→team upgrade (ADR-015 first-class flow), and one code path serves solo and team users (W0-01 keys `credit_balance`/`credit_ledger` by `user_id`). Spike-absorption is consciously traded away; per-team spending caps (ADR-018/019) still bound runaway cost, so tenant cost-safety is unaffected.
**Revisit when:** Real usage data exists to tune plan limits, pack sizes, and prices (see ADR-023/024).

## ADR-018: Metering in credits, not tokens; ambient checks unmetered

**Status:** Accepted
**Decision:** Model-backed actions (agent queries, deep diagnoses, fingerprint LLM checks, proving runs) consume credits; pure-logic checkers and ambient autocomplete are unmetered. Allowance sized so 100% consumption ≈ model cost (base fee is margin). Overage: top-up packs or opt-in metered overage with user/admin-set caps — never silent charges. At the cap: graceful degradation to a cheaper-model "lite mode" with a banner, not a dead product. Always-visible usage meter.
**Rejected:** Raw token metering (incoherent across orchestrated models; blocks model swaps), metering the ambient layer (kills the feature psychologically).
**Amended (2026-07-04, SOLUSDEV-72):** The credit-accounting specifics — purchase packs ($10/$25/$50/$100), the immutable append-only `credit_ledger` plus a cached per-user `credit_balance`, the **config-driven** token→credit conversion rate (embeds margin, calibratable), and the cost-capped free trial — are specified in ADR-024. This ADR's core stands unchanged: metering is denominated in credits (not tokens) and the ambient checker layer is unmetered.

## ADR-019: One budget system for security and billing

**Status:** Accepted
**Decision:** The per-user/per-team rate limits, token/cost budgets, spending caps, and loop guards mandated by CLAUDE.md §7 (model orchestration security) are the same mechanism that enforces ADR-017/018 billing. Build once, serve both.

## ADR-020: The orchestration protocol governs all feature development

**Status:** Accepted
**Decision:** Features flow through CLAUDE.md §5: spec packet → mandatory design-review gate (critique/suggestions/questions, wait for answers) → execution plan (decomposition, dependency graph, parallel-vs-sequential, file ownership) → execution (in-process subagents by default; worktree workers for long parallel builds; tmux pane convention with 4-pane → new window) → verification (tests, fresh-context review subagent, security subagent) → handoff (completion report + COWORK_QA file). TDD is mandatory throughout.
**Rejected:** Ad-hoc agent sessions; agents self-merging.

## ADR-021: Ticket-based branching; agents never touch the remote or main

**Status:** Accepted
**Decision:** One ticket (e.g., `SOLUSDEV-34`) = one feature branch (`SOLUSDEV-34-implement-onshape-integration`) = one MR. Subagent worktrees branch from the feature branch (`SOLUSDEV-34/<task>`), merge back into it via the orchestrator, and are cleaned up. Agents commit locally as workflow mechanics with ticket-referencing messages, but never push, never open/merge MRs, never touch main, never rewrite human-seen history. Humans review the integrated feature branch, make final commits, push, open the MR, and merge after code review.
**Rejected:** Agent-opened MRs (earlier draft; reversed by founder decision), direct-to-main agent work.

## ADR-022: Directory structure is descriptive, not prescriptive

**Status:** Accepted
**Decision:** The repo tree in CLAUDE.md is a current-state map. Contracts, the document authority hierarchy, and the clean-seam principle are stable across restructurings; the tree itself evolves through DECISIONS.md revisions, with the map and architecture diagrams updated in the same MR as any restructure.

## ADR-023: Pricing — three plans (BASIC / PRO / ENTERPRISE), limits stored as data

**Status:** Accepted — 2026-07-04, SOLUSDEV-72. Supersedes the pricing structure in ADR-017.
**Context:** The Individual/Team-seat structure (ADR-017) conflated "who the customer is" with "what they pay for," and hardcoded plan assumptions leak into enforcement. We want three clear plans and limit-enforcement that reads data, not plan names.
**Decision:** Three subscription plans:

- **BASIC** — $25/month or $200/year. **Full feature access**, including the advanced models for the SOL agent. Limits: up to **4** connected integrated services, create/join up to **3** projects, create/join up to **2** COLLABORATIVE teams (the auto-created personal team, ADR-025, does **not** count).
- **PRO** — no limits: unlimited integrations, projects, and teams. For $30/month or $300/year 
- **ENTERPRISE** — variable per-seat pricing. The org fills out an application form (what they do, seats needed); we send a per-seat offer by email; they accept/decline; on accept, enterprise is set up (automatically or via manual back-and-forth). Fields: `seat_count`, custom `price_per_seat`.

**Cross-plan invite enforcement:** when a user is invited to (or tries to join) a project/team, the limit check is against the **invitee's own** plan limits — e.g. a BASIC user already at their project limit cannot be invited/join. This is a **HARD BLOCK** with a clear message, never an overflow-and-warn.

**Limits are stored as data on the subscription**, not in code: a `limits` JSONB (`max_integrations`, `max_projects`, `max_teams`; `null` = unlimited), populated from plan defaults and **overridable for Enterprise**. Enforcement reads this field and **never hardcodes plan names** (ADR-018/019 budget-and-limit machinery is the enforcement home).
**Rejected:** Individual/Team-seat pricing (ADR-017; conflated segment with plan); hardcoding plan names in enforcement branches (blocks Enterprise overrides and per-plan tuning); overflow-and-warn on invites (ambiguous billing, silent overage).
**Revisit when:** Real usage data allows tuning limit values and prices; if a plan between BASIC and PRO proves needed.

## ADR-024: Credits — per-user, packs, ledger + cached balance, cost-capped trial

**Status:** Accepted — 2026-07-04, SOLUSDEV-72; **amended 2026-07-04 (W0-03)** — margin default + debit-failure policy locked. Refines ADR-018; carries forward the per-user credit model from ADR-017's 2026-07-03 amendment.
**Context:** Credits meter model-backed usage (ADR-018). We need per-user attribution, a purchasable top-up path, an auditable balance, and a trial that cannot run up an unbounded bill — all before we have real cost-per-operation data.
**Decision:**

- Credits are **per-user, with NO pooling** — regardless of whether the user is solo or in a team.
- **Purchase packs:** $10 / $25 / $50 / $100, each displayed with an **estimated** query count. Estimates are **provisional** (no real cost-per-operation data yet): ship conservative, calibrate post-pilot.
- **One-month free trial**, which must be **cost-capped** — a bounded credit grant, never unlimited.
- **Accounting:** an immutable, append-only **`credit_ledger`** is the source of truth, plus a cached per-user **`credit_balance`**. The **token→credit conversion rate embeds the margin and is CONFIG** (calibratable), never hardcoded. Per-call debits are written by the post-call cost hook (ADR-026).
- **Conversion + margin (W0-03):** `credits = ceil(dollars × margin_multiplier × credits_per_dollar)`, prices in USD per 1M tokens, `ceil` so a real call never bills 0. **`margin_multiplier` defaults to 2.0** — it covers infra + failed/retried calls + trial grants + profit (NOT pure profit, which is why 2.0, not ~1.25). Both `margin_multiplier` and `credits_per_dollar` live in config (`models.yaml`), provisional until pilot calibration.
- **Debit-failure policy (W0-03):** the model call already ran and was paid for — **never fail the user's request on the accounting write**. On debit failure (DB down, race), serve the result and enqueue the debit to a reconciliation / dead-letter path (ARQ + Redis); reconcile later.

**Rejected:** Pooled team credits (ADR-017 original; breaks per-user attribution and upgrade portability); mutable running-balance-only accounting (no audit trail); hardcoded conversion rate (blocks margin/price calibration); **blocking the user's answer on the accounting write** (W0-03 — accounting must never gate a paid-for result).
**Revisit when:** Pilot cost data lets us set real pack query-estimates, `credits_per_dollar`, and the `margin_multiplier`; if spike-heavy teams need optional pooling on top of per-user credits.

## ADR-025: Teams, identity, and the project-as-workspace model

**Status:** Accepted — 2026-07-04, SOLUSDEV-72. Clarifies and extends ADR-015 and API.md §1.3.
**Context:** Solo users and teams must share one code path, and every resource must have a single scoping anchor. We lock the membership, team-kind, role, and project model here.
**Decision:**

- **Team membership is many-to-many** — a user belongs to multiple teams.
- Every user gets exactly **one auto-created PERSONAL team** on signup (`kind: PERSONAL`). It owns their solo projects and their subscription, is **solo-only** (never has other members), and is **exempt from plan limits** (does not count toward the team limit). This is the mechanism that lets solo users and teams share one code path — everything belongs to a team.
- **COLLABORATIVE teams** (`kind: COLLABORATIVE`) are the real teams users create/join; these **count toward limits** (ADR-023).
- **Roles:** OWNER / ADMIN / MEMBER / **VIEWER** (read-only). **Only an OWNER can delete a
  project.** VIEWER is a ratified read-only tier — it is enforced in code (`ROLE_RANK`, and the
  role gates on OAuth/source/project writes) and documented in `docs/api/API.md` (roles are
  `owner|admin|member|viewer`); this amendment blesses it as part of the contract. A natural fit
  for the education segment's high member churn (read-only teammates).

- **Project = Workspace** — one single concept, not two layers.
- A project belongs to a team (**`project.team_id`**) — the scoping anchor for all access.
- **Per-project access:** on project creation, **all current team members are auto-granted access** (`project_memberships`), adjustable afterward.
**Decision:** The `NotificationType` vocabulary uses **dotted** values, matching the
activity/event-type convention (W0-01 originally drafted underscores). The ratified set:

- `team.invite`
- `invite.accepted`
- `project.created`
- `project.shared`
- `payment.failed`
- `credit.low`

Enforced at the model seam (`models.NotificationType`), validated when a notification row is
written. New notification kinds follow the `domain.event` dotted form.


**Rejected:** One-team-per-user (kills the shared solo/team code path); separate Workspace and Project layers (needless nesting); team-wide implicit project access with no per-project record (blocks later access tightening).
**Revisit when:** Per-project roles need to diverge from team roles, or nested/sub-teams are required.

## ADR-026: Multi-model routing — deterministic, config-driven, complexity-based

**Status:** Accepted — 2026-07-04, SOLUSDEV-72; **amended 2026-07-04 (W0-03)** — type-based routing is now a real v1 input, and the selection/cost mechanics are locked (see `docs/contracts/model-orchestration.md`). Extends ADR-010; feeds ADR-018/019/024.
**Context:** The orchestrator (ADR-010) must pick a model per call to control cost/quality, without hardcoding vendor model names or paying for a classifier model call on every request.
**Decision:**

- Routing is a **deterministic pure function**: `route(query, complexity, type, *, config) → ModelChoice`, a function of its inputs plus current config only — no model call, no credit check, no cost tracking (those are separate phases).
- **Model names are CONFIG** — a model catalog (`models.yaml`) carrying provider / name / prices / context window — **never hardcoded in code**.
- **Complexity-based routing** (tiers `trivial` / `standard` / `hard`, referencing model **ROLES** not names) is the foundation lever.
- **Type-based routing is a REAL v1 input** (amended — was "reserved passthrough no-op"): `RouteType` (`CODE` / `VISUAL_LOG` / `LONG_CONTEXT` / `GENERAL`, extensible) routes to the frontier model whose strength matches the query — Gemini-class for VISUAL*LOG / LONG_CONTEXT, Claude-class for CODE; `type=None` → GENERAL. The **reserved specialist slot** now covers only future \_truly-specialist* models (e.g. embodied/spatial, ADR-029) that don't exist as products yet.
- **Selection is a validated `(complexity × type) → role` matrix:** `route` resolves the pair → a role → a catalog entry. Each referenced role must be filled by **exactly one** catalog entry (enforced) so routing is deterministic; a missing matrix cell falls back to `default_role`.
- A deterministic **Step-1 gateway** maps interaction context → complexity tier **without a model call**. Complexity is auto-derived and never end-user-visible; the caller passes it to `route`. No model-call classification in v1.
- **Three phases, kept separate:** pre-flight balance check → `route` (pure select) → model call → post-call `track_cost`. `route` never does I/O.
- **Per-call cost tracking is a POST-call hook:** token cost → dollars (model config) → credits (configurable margin, ADR-024) → **debit the credit ledger**.

**Rejected:** Hardcoded model names in routing branches (blocks swaps/price changes); a model call to classify complexity in v1 (adds cost/latency); building _specialist_ (embodied/spatial) routing before such models exist — but frontier-strength type routing IS built now.
**Revisit when:** Truly-specialist model products (embodied/spatial, ADR-029) exist to fill the reserved slot; if measured routing quality justifies a learned classifier.

## ADR-027: Database & graph conventions

**Status:** Accepted — 2026-07-04, SOLUSDEV-72. Extends ADR-001 and ADR-003 with concrete conventions.
**Context:** The graph, teams, billing, and events share one Postgres. We lock key/soft-delete/graph-storage conventions so every table and query is consistent and team-scopable.
**Decision:**

- **UUID primary keys** (UUIDv7 where practical, for index locality).
- **Soft-delete via `deleted_at`** on a shared base mixin (the append-only `credit_ledger` and notifications are excepted — they are never soft-deleted).
- The cross-domain **graph lives in Postgres** — relations as rows (**`graph_entity`, `graph_edge`**), embeddings in **pgvector** (`Vector(1536)`, ivfflat index). **No separate graph database** (Neo4j was evaluated and **deferred** — Postgres + pgvector is sufficient for the shallow traversal we need now; revisit only if deep multi-hop traversal proves a **measured** bottleneck, and do it behind a graph-access seam).
- **`graph_entity` carries `canonical_part_id`** (self-reference) — the multimodal fingerprint (ADR-012) collapses cross-domain observations of one physical part to a single canonical entity.
- **`graph_edge` carries** `(src, dst, relation_type, domain_pair, confidence)`.

**Amended — 2026-07-08, SOLUSDEV-72 Decision A (graph-store unification):**

The two rival graph schemas that had drifted apart (the ADR-027 `graph_entity`/`graph_edge`
pair and the connector runtime's parallel `entities`/`relations` pair) are unified onto the
single `graph_entity`/`graph_edge` pair under the ADR-027 names. The `entities`/`relations`
tables and the closed `EntityKind`/`RelationType` enums are dropped. Concretely:

- **`graph_entity.kind` and `graph_edge.relation_type` are free strings** (`String(64)`), not
  closed enums. Connector-emitted kinds (`code_repo`, `code_module`, `code_file`,
  `design_export`, and future `ros_node`/`cad_assembly`/…) and relation types (`contains`,
  `part_of`, `mates_with`, `connected_to`/`net`, …) are valid values directly, with no
  per-kind migration. "Well-known values, documented but not enforced by the type system."
- **`graph_entity` absorbs the operationally-proven connector columns** from the retired
  `entities` table: `source_id` (FK → `sources`), `source_connector`, `external_ref` (the
  connector's stable per-source id), `origin` (default `"connector"`, or `"manual"`), and
  `version` (default 1). A partial-unique `(source_id, external_ref)` where live makes
  re-sync idempotent (upsert). `canonical_part_id` and the `Vector(1536)` ivfflat embedding
  are retained.
- **`graph_edge` carries `(src_id, dst_id, relation_type, domain_pair, confidence)`** and
  additionally `source_id` + `origin`; a partial-unique `(source_id, src_id, dst_id,
relation_type)` where live. `confidence` defaults to 1.0 for connector edges (the
  fingerprint's SAME_AS still uses it).
- **Soft-delete applies to connector-owned graph rows.** `graph_entity`/`graph_edge` use the
  shared `deleted_at` mixin; the sync runtime reconciles stale rows by setting `deleted_at`
  (never hard-deleting), preserving the graph-as-living-documentation invariant.
  - **Soft-delete via `deleted_at`** on a shared base mixin. **Exempt as a class:** (a) _append-only
  logs_ whose history is the record (e.g. `credit_ledger`) and (b) _ephemeral operational rows_
  whose lifecycle is a status/queue, not a document (e.g. `notifications`, OAuth-state, sync-job
  rows). These are hard-deleted or aged out, never soft-deleted. Everything that is
  graph-as-living-documentation (entities, edges, projects, teams, memberships, sources) keeps
  `deleted_at`. New tables inherit the mixin unless they clearly fall in one of the two exempt
  classes.
- **The `Domain` enum is the single canonical vocabulary** owned by `models.py`:
  `code`, `electrical`, `mechanical`, `simulation`, `runtime`. `Domain.SOFTWARE` is removed
  (the code domain is `code`); `runtime` is added (runtime/telemetry). The connector layer's
  former rival `Domain` (`software`/…) is gone and `connectors/contracts.py` re-exports the
  `models.py` enum.
- **Identity linchpin:** the connector's `EntityOut.source_key` is persisted to
  `graph_entity.external_ref` and is the SAME value the multimodal fingerprint reads as
  `SourceRef.external_ref` — i.e. `source_key` (output field) ≡ `external_ref` (graph/
  fingerprint column). The runtime maps `source_key → external_ref` at write time. The public
  API preserves the legacy wire keys via serializers (`type`←`kind`, `source_key`←
  `external_ref`, `properties`←`attrs`), so downstream consumers are unaffected by the rename.

Sub-decisions confirmed by this amendment: free-string `kind`/`relation_type` (A1/A3); one
`Domain` vocabulary incl. `runtime` (A2); soft-delete for connector-owned rows (A4). The
`RelationOut` metadata channel (§7b) is deliberately left open for the connector-contract
reconciliation (Decision B), not this amendment.



**Rejected:** Auto-increment integer PKs (leak counts, poor for distributed/merge); hard deletes as default (loses history/undo, breaks the graph-as-living-documentation value); a dedicated graph DB now (premature; Postgres handles current scale — mirrors ADR-003).
**Revisit when:** A measured deep-traversal bottleneck justifies a graph engine behind the graph-access seam.

## ADR-028: Week-0 shared contracts are human-owned

**Status:** Accepted — 2026-07-04, SOLUSDEV-72. References CLAUDE.md §9, ADR-020, ADR-022.
**Context:** Parallel feature development depends on a stable spine of interfaces. Those interfaces must not drift as a side effect of feature work.
**Decision:** The Week-0 shared contracts — **data models, the API envelope + auth, the TypeScript types, model orchestration, the agent-tool interface, the connector interface, the multimodal fingerprint output contract, the SOL reasoning↔systems interface, and the entity/relation graph model** — live in the contracts location and are **HUMAN-OWNED**: not agent-modified, with changes going through **both founders**. Implementations conform to these contracts; a contract change is a deliberate human act (an MR touching only the contract + rationale), never a side effect of a feature MR.
**Rejected:** Letting feature MRs edit contracts inline (interface drift; breaks parallel work); a single-owner contract (both founders must sign off).
**Revisit when:** The contract set stabilizes enough to extract a versioned SDK.

## ADR-029: Live Bench runtime understanding via multimodal / robotics VLMs

**Status:** Accepted (direction) — 2026-07-04. Extends ADR-014 (Live Bench), ADR-026 (routing), ADR-010 (orchestrator).
**Context:** Live Bench (feature area 6) streams runtime data — telemetry, and in Sim/Real modes visual/scene state — and users need "what's going on?" understanding (robot state, anomalies, incidents) that pure-logic checkers can't provide.
**Decision:**

- Adopt the **newest Google Gemini (3.x class, e.g. `gemini-3.1`)** as the frontier multimodal model for the `VISUAL_LOG` and `LONG_CONTEXT` route types (logs, telemetry, images, large datasheets). It fills the corresponding catalog roles in `models.yaml` (ADR-026 — names/versions are config; verify availability before use).
- **Evaluate a Google robotics embodied-reasoning VLM (Gemini Robotics / Gemini Robotics-ER class)** as a **specialist** for Live Bench scene/telemetry interpretation — understanding physical "what's going on" from runtime state. This activates ADR-026's **reserved specialist slot**.
- **Open design point (Live Bench ticket):** whether embodied understanding gets its own `RouteType` (e.g. `EMBODIED` / `SCENE`) + role, or rides `VISUAL_LOG` with the specialist model behind that role. Either way it is config + a matrix cell — no routing-code change (ADR-026).
- The VLM is invoked by the SOL Agent as a **tool** (ADR-010); its output is validated before it drives the graph or any action.

**Security (binds this ADR):** Live Bench / telemetry data is **untrusted input to the model layer** (CLAUDE.md §7 — telemetry-untrusted + prompt-injection). Ingested runtime content is framed as data, never instructions; the VLM's output is validated/sanitized before rendering, writing to the graph, or triggering any real-world/destructive action.
**Rejected:** A single monolithic multimodal model over raw runtime data (ADR-010 — the agent orchestrates specialists as tools); hardcoding the Gemini/robotics model names in code (ADR-026 — they are catalog config).
**Revisit when:** The Google robotics VLM is evaluated on real Live Bench data (accuracy / latency / cost); if an open-weights embodied model becomes viable to self-host.

## ADR-030: Connector metadata extraction — parse committed Git exports (v1), not live tool plugins

**Status:** Accepted — 2026-07-05, SOLUSDEV-72 (drafted by an AI agent under the founders'
explicit instruction during SOLUS-W0-05; committed by a human). Extends ADR-001 (graph-centric),
underpins the connector interface (SOLUS-W0-05, `docs/contracts/connector-interface.md`), and is
distinct from ADR-014/ADR-029 (Live Bench streaming).
**Context:** Design-artifact connectors — especially EDA (KiCad/LTspice/NgSpice/Altium) and
mechanical CAD (Onshape + proprietary STEP/DWG) — need a source of truth for tool data. Live,
in-tool plugins that stream a running application's state are fragile: they require the tool to be
open, are bespoke per tool, break on tool version changes, and carry no version history. Robotics
teams already commit their exported artifacts to Git — Gerber, STEP, JSON netlists, SPICE decks —
which are versioned, diffable, and available without a live tool session.
**Decision:** v1 connectors extract metadata by **parsing committed Git exports**
(Gerber / STEP / JSON netlist / SPICE), **NOT via live tool plugins**.

- **Native-feed connectors** (code hosts GitHub/GitLab; Onshape) sync via the source's own
  change feed (signature-verified webhooks / API notifications).
- **File-parse connectors** (EDA/CAD) are driven by the **Git repo's change events**: a new commit
  containing the exported artifact fires the connector's re-parse-and-diff path (the diff-based
  change detection in the SOLUS-W0-05 connector interface — `sync` / `detect_changes` +
  `diff_entities`).
- This keeps connectors event-driven (not poll-only), independent (each parses only its own
  source's artifacts and emits intra-source entities/relations), and free of any dependency on a
  running desktop tool. Live tool plugins and live in-tool state are **deferred**.
- **Boundary:** this governs DESIGN-ARTIFACT ingestion into the graph. Live runtime data
  (telemetry, Sim/Real scene state) is NOT a connector concern — it flows through Live Bench's
  `LiveConnection` streaming sibling and the separate telemetry packet-format contract
  (ADR-014/ADR-029). Parsing exports ≠ streaming runtime.

**Rejected:** Live per-tool plugins in v1 (fragile, require the tool running, per-tool engineering
cost, no version history, no clean diff/change-detection story); polling connectors (misses the
real-time-after-a-commit feel and wastes work); treating CAD/EDA the same as live telemetry
(different trust model, different cadence, different contract).
**Revisit when:** a connector genuinely needs live in-tool state that no committed export captures,
or a target tool has no usable committed export format — then a live-plugin or API-pull path is
evaluated behind the same `Connector` interface (the interface does not change; only the extraction
mechanism does).

## ADR-031: Connector interface — the shipped framework shape is ratified and relocated

**Status:** Accepted — 2026-07-08, SOLUSDEV-72 Decision B. Extends ADR-028 (Week-0 contracts are
human-owned), ADR-001 (the graph), ADR-027 (graph conventions / Decision A).

**Context:** Two rival connector interfaces coexisted under `packages/api/.../connectors/`: the
Week-0 contract-doc shape (`base.py` — `Integration`/`Connector`/`Session`, `detect_changes ->
Delta`) and the shipped ARQ-runtime framework shape (`contracts.py` — flat stateless
`Connector`/`OAuthConnector`, `SyncContext`, `SecretStore`, `detect_changes -> bool` + cursor).
`connectors/__init__.py` re-exported neither, blocking every future connector.

**Decision:**

- The **shipped framework shape wins** and is ratified as the contract (a deliberate inversion of
  "code fits contract" — the flat stateless chassis is correct for syncs that run in ARQ workers
  with no place for a long-lived session). The `Integration`/`Session`/`Delta` design is retired.
- Two guarantees the winning shape had dropped are **grafted back in**: (1) the identity linchpin
  `EntityOut.source_key` ≡ `graph_entity.external_ref` ≡ fingerprint `SourceRef.external_ref`
  (already chained by Decision A); (2) the `EntityOut.modality_hints` channel to the W0-06
  fingerprint matcher, persisted to a dedicated `graph_entity.modality_hints` JSONB column.
- The **incremental `Delta` path is a documented forward extension**, not built now (v1 is
  full-sync + cursor).
- The reusable **conformance suite is package-importable** (`solus_api.connectors.assert_connector_contract`),
  merging the shipped checks with the credential-hygiene scan and the negative-path proof.
- The single surviving interface is **relocated to `packages/contracts/python/`** (the human-owned
  contract home, per ADR-028 / CLAUDE.md §9) and re-exported from `solus_api.connectors`. The
  contract doc `docs/contracts/connector-interface.md` is amended to match (see the Decision B
  amendment).

**Rejected:** Keeping the `Integration`/`Session` lifecycle (no home for a live session in the
worker model); keeping both shapes (interface drift; blocks parallel connector work); dropping
`modality_hints` (cheap now, painful when EDA/CAD connectors land without the seam).

**Revisit when:** a connector genuinely needs incremental sync (promote the `Delta` forward
extension), or the contract set stabilizes enough to publish `packages/contracts/python/` as a
versioned SDK.

**Open placement note (for the relocation MR):** `connectors/contracts.py` currently imports the
`Domain` enum from `solus_api.models` (ADR-027 owns the vocabulary). A standalone
`packages/contracts/python/` package must not depend on `solus_api`. Resolve before wiring:
either relocate the `Domain` enum into the contracts package (and have `models.py` import it
back), or keep the canonical implementation in `solus_api.connectors` and treat
`packages/contracts/python/` as the published mirror. See `temp-contracts-python/README.md`.

## ADR-032: Per-user subscriptions & plan-limit enforcement

**Status:** Accepted — 2026-07-08, SOLUSDEV-72 Decisions C-E. Supersedes the per-team/personal-team
billing notion in ADR-015/ADR-023's early framing; extends ADR-025 (teams/projects).

**Context:** Limits must be enforced (teams, projects, integrations) without foreclosing the future
Stripe/Enterprise work, and the earlier "personal team owns the subscription" model conflated
teams with billing.

**Decision:**

- **Subscription is PER-USER.** Each user has one subscription (`subscriptions.user_id`, one live
  row per user). Not per-team; creating a team never pools billing.
- **Plans BASIC/PRO/ENTERPRISE set LIMITS, not features.** Limits are stored **as data** on the
  subscription (`limits` JSONB; a null/absent key = unlimited). **Enforcement reads `limits` and
  NEVER branches on plan name** (ADR-023). BASIC = `{max_teams:2, max_projects:3, max_integrations:4}`;
  PRO = all unlimited; ENTERPRISE = custom (set explicitly).
- **Teams is a feature on every plan.** The auto-provisioned **PERSONAL team always survives**
  (solo-only, one per user) and is **exempt from the team-count limit** — it was decoupled from
  billing, not removed. Inviting from a personal team spins up a new COLLABORATIVE team and issues
  the invite there (the personal team + its solo projects are untouched).
- **Every check is against the ACTING USER'S own subscription.** Team-count = the user's
  COLLABORATIVE memberships (excl. personal); projects = projects the user created (`created_by`);
  integrations = sources the user connected (`created_by`). The **cross-plan invite block** fires at
  ACCEPTANCE against the invitee's own team-count — a hard block (not overflow) with leave/upgrade
  destinations in the error `details`.
- **Race-safety:** the count and the insert run in one transaction with the acting user's
  subscription row locked `FOR UPDATE`, so concurrent creates cannot exceed the limit.
- **Onboarding:** a 14-day BASIC trial is provisioned at first auth; `PATCH /users/me/subscription`
  picks/changes the plan (sets `limits`, `status=trialing`, `expires_at=now+14d`). Trial expiry is
  **stored only** (`status`, `expires_at`) — no downgrade/lock/charge logic yet (future Stripe).
- **Project access is DUAL-SOURCE** (ADR-025): access = team membership **OR** a direct
  `ProjectMembership` share. Share-only users (no team role) are read-only.
- **Enterprise (not built, not precluded):** the only multi-user-subscription case is an Enterprise
  owner provisioning employee accounts under the enterprise subscription. The per-user model leaves
  room for it (no per-team billing assumption baked in).

**Rejected:** per-team subscriptions (conflates teams with billing); branching enforcement on plan
name (ADR-023 — limits are data); removing the personal team; overflow-and-warn on invite (must be
a hard block at acceptance).

**Revisit when:** Stripe integration lands (trial→active→past_due transitions, downgrade/lock at
expiry) and Enterprise provisioning is built.
---

## How to add or change a decision

1. New decision: append an entry with the next ADR number, date it, set Status: Accepted.
2. Changing a decision: set the old entry's Status to **Superseded by ADR-XXX**, add the new entry referencing what it replaces and why. Never delete history.
3. Only humans edit this file. An agent that believes a decision needs revisiting flags it in its design-review critique or completion report.
