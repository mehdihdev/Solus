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

**Amended — 2026-08-15, SOLUSDEV-138/139 (approved in-chat during Lane E Phase 1):** Query embeddings issued by the W0-07 systems seam (`DbSolSystems`) run `allow_unmetered=True`. Rationale: the seam deliberately carries no user identity; embed volume is bounded upstream by the credit-gated (402) and frequency-capped (429) turn admission, so no capped or anonymous path can reach an embed; per-call cost is sub-cent. Revisit when identity plumbing reaches the seam or embed volume becomes material in billing.

**Amended — 2026-08-30, SOLUSDEV-167 (approved in-chat during Phase 1):** "One budget system" governs **model** cost. **Third-party integration API quotas are a SECOND, separate budget and are metered separately**, because they are denominated in a unit Solus neither buys nor can convert: a provider's own call allowance. Onshape's is **2,500 calls per YEAR per Onshape user** on Free/Standard/EDU (only 2xx/3xx counted; exhaustion answers HTTP 402) — an annual, per-provider-account quantity that a credits-shaped mechanism cannot express, since a sliding window cannot bound a year and credits cannot be spent to buy more of it.

Concretely: outbound provider calls are counted per **provider account** (not per team — the provider meters the user, so a team-keyed annual counter would hand one account N allowances), in Redis, at the connector's single HTTP chokepoint. Above a configured fraction of the allowance, `scheduled` and `agent` traffic degrades to cache-only while a user's explicit action still reaches the provider; above the allowance, or once an observed 402 latches, everything is refused. ADR-018's "sync is unmetered" **stands unchanged** — this meters provider quota, never credits, and nothing here reaches the credit ledger. Per ADR-024, an accounting write never fails a user's request: the meter fails **open**.

**Honest limit, recorded because it shapes the UI:** the true remaining allowance is unknowable from inside. Solus counts only its own calls from whenever the counter was created, so the ledger reads low for an account that was already partly spent. The only authoritative exhaustion signal is the provider's own 402. Any surfaced position must be labelled an estimate.

**Rejected:** extending the credits mechanism with a second unit (bends a credits-shaped system around an annual call count, and would imply provider quota is purchasable); leaving it unmetered (the failure this ticket exists to fix).

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

**Status:** Accepted — 2026-07-04, SOLUSDEV-72. Supersedes the pricing structure in ADR-017. **Amended 2026-08-08 (SOLUSDEV-102, founder-approved in-chat):** PRO price set to $35/month (was $30); plan starting-credit grants added (amounts and mechanics in ADR-024).
**Context:** The Individual/Team-seat structure (ADR-017) conflated "who the customer is" with "what they pay for," and hardcoded plan assumptions leak into enforcement. We want three clear plans and limit-enforcement that reads data, not plan names.
**Decision:** Three subscription plans:

- **BASIC** — $25/month or $200/year. **Full feature access**, including the advanced models for the SOL agent. Starts with a one-time **2,500-credit** grant (ADR-024). Limits: up to **4** connected integrated services, create/join up to **3** projects, create/join up to **2** COLLABORATIVE teams (the auto-created personal team, ADR-025, does **not** count).
- **PRO** — no limits: unlimited integrations, projects, and teams. Starts with a one-time **10,000-credit** grant (4× BASIC, ADR-024). For $35/month or $300/year _(amended 2026-08-08 — was $30/month)_.
- **ENTERPRISE** — variable per-seat pricing. The org fills out an application form (what they do, seats needed); we send a per-seat offer by email; they accept/decline; on accept, enterprise is set up (automatically or via manual back-and-forth). Fields: `seat_count`, custom `price_per_seat`.

**Cross-plan invite enforcement:** when a user is invited to (or tries to join) a project/team, the limit check is against the **invitee's own** plan limits — e.g. a BASIC user already at their project limit cannot be invited/join. This is a **HARD BLOCK** with a clear message, never an overflow-and-warn.

**Limits are stored as data on the subscription**, not in code: a `limits` JSONB (`max_integrations`, `max_projects`, `max_teams`; `null` = unlimited), populated from plan defaults and **overridable for Enterprise**. Enforcement reads this field and **never hardcodes plan names** (ADR-018/019 budget-and-limit machinery is the enforcement home).
**Rejected:** Individual/Team-seat pricing (ADR-017; conflated segment with plan); hardcoding plan names in enforcement branches (blocks Enterprise overrides and per-plan tuning); overflow-and-warn on invites (ambiguous billing, silent overage).
**Revisit when:** Real usage data allows tuning limit values and prices; if a plan between BASIC and PRO proves needed.

## ADR-024: Credits — per-user, packs, ledger + cached balance, cost-capped trial

**Status:** Accepted — 2026-07-04, SOLUSDEV-72; **amended 2026-07-04 (W0-03)** — margin default + debit-failure policy locked; **amended 2026-08-08 (SOLUSDEV-102, founder-approved in-chat)** — plan starting-credit grants added (see Decision). Refines ADR-018; carries forward the per-user credit model from ADR-017's 2026-07-03 amendment.
**Context:** Credits meter model-backed usage (ADR-018). We need per-user attribution, a purchasable top-up path, an auditable balance, and a trial that cannot run up an unbounded bill — all before we have real cost-per-operation data.
**Decision:**

- Credits are **per-user, with NO pooling** — regardless of whether the user is solo or in a team.
- **Purchase packs:** $10 / $25 / $50 / $100, each displayed with an **estimated** query count. Estimates are **provisional** (no real cost-per-operation data yet): ship conservative, calibrate post-pilot.
- **One-month free trial**, which must be **cost-capped** — a bounded credit grant, never unlimited.
- **Plan starting credits (2026-08-08):** each paid plan carries a **one-time** credit grant applied when the plan first becomes live for a user — **BASIC 2,500**, **PRO 10,000** (4×) — sized so BASIC comfortably covers two projects of normal SOL usage. Idempotent per (user, plan): renewals never re-grant; upgrading BASIC→PRO grants PRO's amount once. Amounts are **CONFIG** (calibratable like the trial grant), never hardcoded in enforcement. Ongoing top-ups are the purchase packs — buying credits never requires a plan upgrade.
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
- **Roles:** OWNER / ADMIN / MEMBER. **Only an OWNER can delete a project.**
- **Project = Workspace** — one single concept, not two layers.
- A project belongs to a team (**`project.team_id`**) — the scoping anchor for all access.
- **Per-project access:** on project creation, **all current team members are auto-granted access** (`project_memberships`), adjustable afterward.

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
- The Week-0 tree carried two parallel graph schemas: `graph_entity`/`graph_edge` (this ADR's
  shape, read by the SOL `get_entity` tool and mirrored by the fingerprint `SourceRef`) and a
  second `entities`/`relations` pair (added by the connector-runtime work, the only tables any
  connector actually wrote). Readers and writers never met, so `get_entity` on a synced project
  always returned `not_found`. This amendment collapses them into ONE pair on the canonical
  `graph_entity`/`graph_edge` names, absorbing the operationally-proven connector columns.
- **`entities`/`relations` are removed.** They were never sanctioned by an ADR. Their columns
  move onto `graph_entity`/`graph_edge`; the connector runtime now writes the canonical tables.
- **`graph_entity` gains** `source_id` (FK → `sources`, nullable — manual/fingerprint rows have
  none), `origin` (`connector` | `manual`, default `connector`), and `version` (int, optimistic
  concurrency per API.md §2.4). It keeps `source_connector`/`external_ref` (the fingerprint-facing
  provenance mirror). A partial-unique index `(source_id, external_ref) WHERE deleted_at IS NULL`
  gives idempotent re-sync.
- **`external_ref` is the identity linchpin**, made explicit: `graph_entity.external_ref` ==
  the connector's `EntityOut.source_key` == the fingerprint's `SourceRef.external_ref`. One value,
  three names; the write seam maps `source_key → external_ref`. (The fingerprint contract W0-06 is
  unchanged — it already keys on `external_ref`.)
- **`graph_edge` gains** `source_id` (FK → `sources`, nullable) and `origin`, with a partial-unique
  `(source_id, src_id, dst_id, relation_type) WHERE deleted_at IS NULL`. `domain_pair` is derived
  from the two endpoints' domains at write time; connector edges default `confidence = 1.0`.
- **`kind` and `relation_type` become free strings, not enums.** Connectors legitimately emit kinds
  (`code_repo`, `code_module`, `design_export`, and future `ros_node`, `cad_assembly`, …) and
  relations (`contains`, `part_of`, `mates_with`, `connected_to`) that no closed enum can hold.
  This resolves the `RelationType`-is-too-small gap already flagged in metadata-extraction.md §7a.
  The former `EntityKind` and `RelationType` enums are removed. `domain` stays enum-constrained.
- **`Domain` vocabulary reconciled to one canonical set:** `code`, `electrical`, `mechanical`,
  `simulation`, `runtime`. The connector layer previously used a rival enum (`software`,
  `electrical`, `mechanical`, `runtime`); `software` is reconciled to `code` (same world), and
  `runtime` is added. `runtime`/`simulation` are kept distinct (telemetry ≠ sim) and neither is
  emitted by a connector yet. `error_solution.domain` shares this enum; its DB CHECK is updated.
- **Soft-delete now covers connector-written graph rows.** The old `entities`/`relations` runtime
  HARD-deleted stale rows on re-sync — directly against this ADR's "graph-as-living-documentation"
  rejection of hard deletes. The unified runtime sets `deleted_at` instead. (Project/team/source
  _teardown_ still hard-deletes, since the parent row is physically removed.)

**Amended — 2026-07-12, SOLUSDEV-59 Decision C (origin vocabulary):**

`origin="fingerprint"` is a blessed well-known value of `graph_entity.origin`, alongside
`"connector"` (default) and `"manual"`. It marks DERIVED canonical entities materialized
by fingerprint ingestion (FP-02) — `kind="canonical_part"` rows aggregating cross-source
observations of one physical part — not rows synced from any external source. Concretely:

- Fingerprint-derived rows carry `origin="fingerprint"` with `source_id` and
  `external_ref` NULL; idempotency is keyed by the partial-unique
  `(project_id, canonical_key)` (`canonical_key` = the matcher's normalized base
  identity, `String(64)`, length-guarded — never truncated), NOT by
  `(source_id, external_ref)`. Canonical entities are PROJECT-scoped by design: the
  matcher's uuid5 canonical id is project-agnostic and lives in `attrs` for
  traceability only; the uuid7 PK convention is unchanged.
- Connector reconciliation/soft-delete sweeps never touch `origin="fingerprint"` rows;
  their lifecycle belongs to fingerprint ingestion (run-support staleness + the
  CLEAR+STAMP retraction sweep). Any future graph mutation surface must treat edit
  rights as an `origin == "manual"` ALLOWLIST so fingerprint rows are born read-only.
- Decision A's stance stands: `origin` remains a free `String(16)` — this amendment
  documents the third well-known value, it adds no enum.
- Re-key note: a normalization-policy change (e.g. the 2026-07-12 separator stripping:
  bases `MPU-6050`→`MPU6050`, `AMS1117-3.3`→`AMS11173.3`) changes the affected uuid5
  canonical ids and `canonical_key` values; orphaned old-base rows are accepted for
  dev-only data. Post-launch, such a policy change requires a keyed data migration.

**Amended — 2026-08-07, SOLUSDEV-136 (SYS-02, human-approved in-chat per ADR-032):**

Embedding indexes move from ivfflat (lists=100) to **HNSW** (m=16, ef_construction=64,
cosine) on both `graph_entity.embedding` and `error_solution.embedding`. Rationale:
ivfflat trains k-means centroids at CREATE INDEX time — ours were built on empty tables,
so recall is degenerate until a manual REINDEX after the first large load, and `lists`
needs retuning (~√rows) plus a REINDEX at each corpus order of magnitude. HNSW builds
incrementally with no training step, is correct when created empty, and holds
recall/latency through ~10⁶ vectors (10× the medium-term estimate) with no parameter
changes; costs are higher memory (~hundreds of MB of graph overhead at 10⁶ × 1536-d) and
slower builds — irrelevant at the current corpus (≈0 rows), which is precisely why the
switch happens now, within the entrypoint migration budget. pgvector ≥0.8 (deployed
0.8.2) additionally offers iterative index scans (`hnsw.iterative_scan`) that repair
filtered-ANN recall for project-scoped queries if the planner ever prefers the vector
index over per-project exact KNN. Everything else in this ADR stands.

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

## ADR-031: MCP hosting model — forked, Solus-owned servers on the customer machine

**Status:** Accepted (2026-07-30 — ratified by Pratham in-session alongside the bridge-protocol
contract and the `ToolErrorCode.UNAVAILABLE` extension; Mehdi review at the SOLUSDEV-154 MR)
**Context:** SOLUSDEV-153 (MCP foundation), SOLUSDEV-157 (MCP-03), SOLUSDEV-161 (BRG-02),
SOLUSDEV-154 (local bridge)

**Decision.** Solus integrates desktop/EDA/CAD tooling through the Model Context Protocol under a
**fork–harden–own** hosting model:

1. **Pattern 1 — tools.** MCP servers that act on a user's local tools are **forked into
   `integrations/mcp/<tool>/`, hardened, and owned by Solus** — never run from upstream
   registries at launch time (no `npx`/`uvx`/pip-at-launch). They execute on the **customer's
   machine**, launched and supervised by the bridge companion, and are exposed to SOL exclusively
   as the W0-04 `MCPTool` kind behind the untouched `ToolRegistry` (ADR-010: the agent
   orchestrates validated tools; the registry's never-raises invariant holds across the wire).
   The cloud treats the companion and everything it advertises or returns as **untrusted input**
   (CLAUDE.md §7); the tool namespace available to any SOL invocation is fixed cloud-side against
   the Solus-owned allowlist, never by what a machine advertises.
2. **Pattern 2 — telemetry.** Live sensor/runtime data **never rides an MCP tool interface**. It
   flows through the isolated `LiveConnection` seam (`docs/contracts/live-connection.md`,
   ADR-005/029/030), enforced mechanically by that contract's conformance suite.
3. **Enforcement of ownership.** Every fork carries: a provenance/license record
   (`PROVENANCE.template.md` — upstream SHA, vendored-tree hash, modification log), a **MIT or
   Apache-2.0 only** license boundary (stricter than `metadata-extraction.md` §6.6 — customer-
   machine code admits no copyleft/EULA ambiguity; Apache NOTICE preserved), a curated
   `allowlist.yaml` (single source of truth for exposed tools and per-tool
   `requires_confirmation`; server-side destructive hints are untrusted and ignored), a pinned
   Solus-authored `bin/launch` entrypoint (CLAUDE.md §7 pinned binaries; zero network at launch;
   deps from a hash-pinned lockfile at companion install time), and a **passed, evidence-based
   security review signed by both devs** (`SECURITY_REVIEW.template.md`), mechanically voided by
   any change to the vendored tree hash.

**Rationale.** Local tools (Onshape desktop, Altium, DelphiScript-scriptable EDA, flashing
toolchains) cannot be reached from the cloud; MCP is the interoperable protocol the ecosystem is
converging on, and W0-04 anticipated exactly this kind (`RemoteTool/MCPTool`). Running unaudited
third-party servers on customer machines is an unacceptable supply-chain and secret-leakage
surface — forking with a review gate converts "someone's GitHub repo" into Solus-owned, pinned,
reviewed code with a paper trail. One hosting model also resolves the bridge contract's open
holes (advertised-descriptor allowlisting; tool→server mapping) with one file per fork.

**Consequences.** Solus owns fork maintenance: a named CVE-intake mechanism per fork, a 14-day
re-vendor clock for CVEs on shipped paths, quarterly upstream diff reviews, and scoped re-reviews
on rebase. Review cost gates how fast new tool servers ship (deliberate). The license boundary
excludes some upstream servers; the answer is a clean-room or alternative upstream, not a policy
exception.

**Revisit when:** the companion gains OS-level sandboxing (posture declarations in the checklist
tighten into mechanism requirements); an MCP-server SDK of our own makes forks thin shims; or the
fork count makes per-fork review economics untenable (then invest in shared hardening layers, not
weaker review).

---

## ADR-032: Agent-editable governance docs (two-tier)

**Status:** Accepted (2026-07-30 — ratified by Pratham in-session; Mehdi review at the
SOLUSDEV-154 MR)
**Context:** SOLUSDEV-154 retrospective. The temp-file paste convention (agents write `temp-*.md`,
humans copy into DECISIONS.md / docs/contracts / docs/api / CI) made every governance change a
manual human copy step and broke agentic flow.

**Decision.** Governance files split into two agent-editable tiers plus a hard floor:

1. **Tier 1 — direct agent edits, no per-change approval** (the MR's 2-approval review is the
   gate): `docs/api/`, `docs/architecture/`, `docs/wireflows/`, `docs/schemas/`, `docs/qa/`,
   `.gitlab-ci.yml`, and `docs/contracts/` when landing content already approved in-session.
   Amendments are called out in the completion report.
2. **Tier 2 — in-chat approval BEFORE editing**: `DECISIONS.md` (new/changed ADRs),
   `packages/contracts/*`, `packages/shared-types/*`, and any `CLAUDE.md`. The agent presents the
   concrete change (AskUserQuestion or equivalent), the recorded human answer is the approval, the
   edit lands in a dedicated commit. Tier-2 edits are the orchestrator's alone — never delegated
   to subagents.

   **`packages/shared-types/*` added 2026-08-05 (Pratham, in-session, at the SOLUSDEV-216 MR
   prep).** ADR-028 already declared "the TypeScript types" human-owned, but this list named only
   `packages/contracts/*`, so the two documents disagreed about a directory six lanes now import.
   Tier 2 resolves it in favour of ADR-028. The LANE 0 contracts landed on
   `SOLUSDEV-216-CTR` before this line existed and **stand as approved** — the design questions
   behind them were put in-chat and answered, which is the control this tier encodes.

3. **Never agent-editable** (H1 hard-blocks): `.claude/hooks/*`, `.claude/settings*.json`,
   `.env*`. Harness and secrets integrity are not subject to this ADR.

**Rationale.** The durable human controls are the in-chat approval (recorded in the conversation
and the completion report) and the MR 2-approval merge gate — not the copy-paste act itself.
This supersedes the paste MECHANICS of the ADR-028-era convention; human ownership of decisions
is unchanged, only who types them. H1 was narrowed accordingly (hook change applied by a human,
as hook changes must be).

**Consequences.** Loop prompts no longer carry a "temp-\* for human paste" rule; contract docs
land directly with their features; ADR ratification happens in-chat with the sponsoring human
and is double-checked by the second founder at the MR. Agents editing this file follow rule 2
below with "in-chat approval" standing in for "only humans edit".

---

## ADR-033: Tool knowledge lives in a global, tenant-free table

**Status:** Accepted (2026-08-03 — approved in-session by Pratham against the concrete text below;
Mehdi review at the SOLUSDEV-96 MR)
**Context:** SOLUSDEV-96 (Onshape MCP server, A6)

**Context.** SOL needs vendor API knowledge to construct valid tool calls — "what parameters does
`extrude` take?", "what is a valid `endBound`?". That knowledge is Solus-authored or vendor-derived,
identical for every customer, and must never mix with customer data. Today there is nowhere to put
it: every table that stores text is project-scoped by `ForeignKey("projects.id",
ondelete="CASCADE")`, and the four non-tenant-scoped tables (`processed_stripe_events`,
`deleted_accounts`, `connector_secrets`, `oauth_states`) hold opaque ids, ciphertext, or tombstones
— never prose. The nearest global _knowledge_ precedent is `integrations/mcp/*/allowlist.yaml`:
Solus-authored, loaded at startup, with no runtime write path.

**Decision.** A `tool_doc` table with **no tenant scoping**, contained by four rules:

1. **No `project_id`/`team_id`/`user_id` column and no FK to those tables.** Absence of the column
   _is_ the enforcement — there is nowhere to put a tenant reference, so none can be added by
   accident.
2. **Typed columns only** (`tool`, `version`, `symbol`, `summary`, `parameters`, `source_url`,
   `confidence`, `acquisition_method`, `fetched_at`). No free-text JSONB a request handler could
   fill.
3. **No runtime write path.** Populated by an admin/ingestion job over **vendor documentation
   only** — never by a sync, a tool call, or anything holding a `SyncContext` or a `GraphEntity`.
4. **Retrieval is lexical-first** (`tool` + `version` + `symbol` exact, then full-text): "what does
   extrude take?" is a lookup, not a semantic search. A nullable `embedding` column is added and
   left **unpopulated** until `embed()` exists (`docs/api/gateway-embeddings.md` is a deferred
   MO-01 proposal and `graph_entity.embedding` is still NULL).

**Counter-example to stay unlike.** `DataEvent` has no FKs but is very much tenant-attributed and
content-bearing. "No FK" alone is not containment; rules 2 and 3 are what make this table
structurally incapable of holding customer data.

**Consequences.** This is the first global content-bearing table in the schema, and the precedent it
sets is narrow by design: a table qualifies only if it satisfies all four rules. Ingestion sources
are machine-readable — Onshape's public OpenAPI spec and its per-document `featurespecs` (which
includes custom features a customer imported, so those are read live and never stored) — so entries
are versioned and attributable rather than scraped prose. A hand-maintained schema table would rot;
this one is regenerable from its sources.

## ADR-034: Two-layer local state — `~/.solus` (machine-private) and repo `.solus/` (team-shared)

**Status:** Accepted (2026-08-30 — ratified in-session against the concrete text below; review at
the SOLUSDEV-166 MR)
**Context:** The project→working-copy link lives only in renderer localStorage, unreadable from
the Electron main process, so `SOLUS_COMPANION_WORKSPACE` is never set and workspace-gated MCP
forks (Altium) fail closed on every launch. Team-shared robot configuration (artifact manifests,
environment requirements, part declarations) has no home at all. Design:
docs/architecture/solus-folder.md.

**Decision.** Local and team state split into two layers that never mix:

1. **`~/.solus/` — machine-local, private, never synced.** Layout: `companion_id` (existing,
   unchanged), `config.json` (machine prefs), `projects.json` (registry
   `{ schema_version, projects: { <projectId>: { path, repoUrl?, lastOpenedAt } } }`),
   `projects/<projectId>/` (overrides + cache), `logs/`. Machine-written files are JSON only,
   carry `schema_version`, and are written atomically (temp + rename); the directory is 0700.
   The desktop MAIN process owns `projects.json`; the renderer's localStorage copy is a display
   cache. `SOLUS_COMPANION_WORKSPACE` derives from the registry at companion spawn. Because HOME
   survives the companion's `env -i` scrub, MCP forks can read `~/.solus`: no secrets, tokens,
   or credentials ever live there, nor server-owned settings (sol_mode, consent, onboarding).
2. **Repo-committed `<project>/.solus/` — team-shared, versioned, TOML** (`project.toml`,
   `parts/*.toml`), ingested by the git connector per ADR-030 and treated as untrusted input per
   CLAUDE.md §7 (strict schemas, unknown-field rejection, size caps, no executable fields).
   Implemented in later tickets; custom SOL instructions are explicitly excluded pending their
   own ADR.

**Why.** Machine state and team state have opposite privacy/sync semantics; conflating them
either leaks private machine paths to the team or hides team config from the graph. JSON
machine-side keeps the companion's zero-YAML posture; TOML repo-side parses with stdlib `tomllib`
and stays hand-editable.

**Consequences.** The registry closes the Altium fail-closed gap. `~/.solus` creation is
tightened to 0700 wherever it is created. Schemas are documented in
docs/contracts/local-state.md; layout/format changes to `~/.solus` require amending this ADR.

---

## How to add or change a decision

1. New decision: append an entry with the next ADR number, date it, set Status: Accepted.
2. Changing a decision: set the old entry's Status to **Superseded by ADR-XXX**, add the new entry referencing what it replaces and why. Never delete history.
3. Humans own decisions; agents may edit this file only under ADR-032 tier-2 (concrete change approved in-chat first, dedicated commit). An agent that believes a decision needs revisiting raises it in its design-review critique or completion report.
