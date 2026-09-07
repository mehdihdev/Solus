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

**Amended — 2026-09-05, SOLUSDEV-246 (STORE ST1, origin vocabulary, human-approved in-chat per
ADR-032):** `origin="extension"` is the fourth well-known value. It marks rows written by a
first-party bundle's in-repo backend (ADR-035 as amended the same day): `kind` is the bundle's
namespaced `ext:<id>:<name>`, `source_id` and `external_ref` are NULL, and the rows are
soft-deleted when the bundle is uninstalled from the project. Connector reconciliation sweeps
never touch them (as for `fingerprint`); edit rights follow the `origin == "manual"` allowlist
stance, so they are read-only through the generic entity routes. No enum is added.

**Amended — 2026-09-06, SOLUSDEV-246 (STORE ST2, human-approved in-chat per ADR-032):**

1. **`workspace` is a `Domain` value** (the seventh, beside SOLUSDEV-240's `project` — merged the
   same day) — the layer describing the workspace itself: the
   per-project `solus:workspace` root, the `solus:live_bench` node, and one `solus:widget` node
   per installed extension (peers under the root, `contains` edges from it). It is a graph-wide
   change: `models.Domain`, `solus_contracts.connector.Domain`, the manifest's `GRAPH_DOMAINS`,
   the shared-types `DOMAINS`, and the `domain` CHECK constraints on `graph_entity` and
   `error_solution` all move together in migration `b3f1c2d4e5a6`. Workspace-domain entities are
   excluded from SOL context assembly, checkers and fingerprinting; connectors may not emit it.
2. **`origin="system"`** is a well-known value for rows Solus writes about the workspace (the
   three kinds above). `source_id` and `external_ref` are NULL; they are read-only through the
   generic entity routes; created and removed only by the extension install lifecycle
   (`solus_api/widgets/graph_nodes.py`), never by connector reconciliation. For the record,
   `origin="linking"` (SOLUSDEV-106/107 cross-domain links) has been in use since LNK-01 and is
   likewise well-known. `origin` remains a free `String(16)`.

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

**Amended — 2026-09-05, SOLUSDEV-240 (WORKSPACE W1; human-approved in-chat per ADR-032):**

`Domain` gains a sixth canonical value, **`project`**, for entities that belong to the project as
a whole rather than to one engineering world: the project `.solus` node (`kind="solus_config"`)
and imported documents (`kind="document"`, e.g. a rules PDF). They are real graph nodes so Impact
and the focus engine reach them through the one traversal, and forcing them into `code` would
mislabel them. The VARCHAR CHECKs on `graph_entity.domain` and `error_solution.domain` are
recreated with the new value; `solus_contracts.connector.Domain`, `@solus/shared-types` `DOMAINS`,
and `docs/contracts/focus.md` mirror it in the same commit. No connector emits `project`; both
`.solus`-owned kinds carry `origin="manual"` (the existing user-editable value).

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
exception. A third pattern — vendor-hosted servers Solus cannot fork —
is added by ADR-035; Patterns 1 and 2 above are unchanged by it.

**Revisit when:** the companion gains OS-level sandboxing (posture declarations in the checklist
tighten into mechanism requirements); an MCP-server SDK of our own makes forks thin shims; or the
fork count makes per-fork review economics untenable (then invest in shared hardening layers, not
weaker review).

**Amendment (2026-09-07, SOLUSDEV-250 — approved in-session by Mehdi per ADR-032 tier 2):** the
launch-time rules above (no `npx`/`uvx`/pip at launch, hash-pinned deps) govern a fork's OWN
runtime. A Solus-authored Pattern-1 server MAY execute package installs, scripts and test runs
inside the USER's linked workspace and its environment when every command is an argument list
assembled by Solus code from validated arguments (never a shell string), is confirmation-gated
with the exact argv shown on the approval card, is confined to the linked workspace and its
venv/conda environment, and is bounded (timeout, output caps). These act on the user's
environment, never on Solus's.

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

**Amended 2026-09-01 (SOLUSDEV-233):** `projects/<id>/` gains its first occupant —
`projects/<id>/sol/<conversationId>.json`, a machine-local CACHE of a SOL chat's settled turns
(schema_version 1). The server remains the source of truth for conversations. File rules per
this ADR: JSON with schema_version, atomic temp+rename writes, 0600 files under the 0700 home,
ids validated in the MAIN process, 2 MB byte cap, item/length caps on read, newer schema_version
files are read-only. Accepted residual risk: user-TYPED message text is cached in plaintext on
the user's own machine (fork-readable per Layer-1 rules; assistant/tool content is already
secret-redacted server-side); mitigations: purge on account identity change, delete-with-chat.
Format changes to this file require amending this ADR.

**Amended 2026-09-03 (SOLUSDEV-235 / ADR-035):** Layer 1 gains `extensions/<id>/<version>/` —
a machine-local CACHE of installed extension bundles (manifest, assets, entry HTML/JS), plus
`extensions/index.json` (schema_version 1) recording installed versions and their content
hashes. The registry server remains the source of truth for what is installed; the cache is
verified by hash before use and may be deleted at any time. Bundles are static assets and are
never executed by the main process. Ids are validated main-process-side with the contract's
slug rule; files are 0600 under the 0700 home; per-bundle size cap 25 MiB. No secrets, per
Layer-1 rules.

**Amended 2026-09-05 (SOLUSDEV-240 / WORKSPACE W1, human-approved in-chat):** a third layer —
the **project-level `.solus`, server-stored**. Every project gets one at creation: a
`solus_config` graph node (domain `project`, origin `manual`) plus `solus_entries` rows under
five sections (Hardware configs, Project details, Error logging, Documentation, Code
environment). It is UI-edited in Workspace (import a file · ask SOL to find · type it) and
SOL-writable through the `add_solus_entry` tool, so it cannot be a repo file: no repo exists at
creation and the server cannot write a working copy. It is configuration, not a second store for
graph facts — parts stay in the graph; imported files are retained `artifacts` rows wrapped in
`document` nodes edged from `.solus`, never blobs in a JSON field. Layer 2's repo-committed TOML
remains the later feeder for connector-ingested declarations; `~/.solus` is unchanged. Routes:
`docs/api/solus.md`.

**Amended 2026-09-06 (SOLUSDEV-244 / HOME H3, human-approved in-chat):** Layer 1 gains
`~/.solus/preferences.json` (schema_version 1) — the user's **engineering preferences**, the one
Layer-1 file the user authors rather than the machine: `freeText` (≤ 2,400 chars) plus five
structured fields `codeStyle`, `mechanical`, `electrical`, `documentation`, `unitsStandards`
(≤ 800 chars each), and `updatedAt`. It is a document, not settings: no toggles, no server-owned
values. It is not a server-owned setting, so the Layer-1 ban on `sol_mode`/consent/onboarding does
not apply; the "never synced" rule holds — the server keeps **no copy**. The desktop attaches the
document to each SOL turn (`MessageCreate.preferences`), where it is validated against a strict
schema with the same caps and enters the prompt only as a nonce-fenced data block
(`kind=engineering_preferences`) under Solus-authored framing, after the mode note and before the
SOLUSDEV-233 styling note, with a Solus-authored trailer. Layering is explicit: project-level
`.solus` overrides root preferences, which override shipped corpus defaults (CORPUS C2+); the
project slot is reserved empty by this ticket. The framing instructs SOL to apply the conventions to
engineering recommendations and to say when one changed its answer from the default; they can never
change rules, tools, scope, or what counts as data. Red-team fixtures cover the new surface. File
rules per this ADR: JSON with schema_version, atomic temp+rename, 0600 under the 0700 home, 64 KiB
byte cap treated as corrupt, newer schema_version read-only, one file per machine. The TypeScript
shape lands in `packages/shared-types`; no Python twin is added because no Python process reads the
file (the API validates the request body with its own schema). This supersedes the solus-folder.md
§6 deferral for ROOT-level preferences only; team/project instructions remain deferred.

**Amended 2026-09-06 (SOLUSDEV-248 / ROBOT ONBOARDING R5, human-approved in-chat):** a
Hardware-configs entry may carry a structured payload — `SolusEntryKind.CONFIG`, a JSONB column
validated by the `HardwareConfig` Pydantic model on every write, one entry per Physical Robot,
provenance on every field. This is configuration, not graph facts: parts stay in the graph and
the entry references them by entity id; free-form or unvalidated JSON remains forbidden.

---

## ADR-035: Extensions — sandboxed views, a permission-checked host bridge, and an open registry

**Status:** Accepted (2026-09-03 — ratified by Mehdi in-session at the SOLUSDEV-235 backend design review; second-founder check at the MR)
**Context:** The Store (SOLUSDEV-235 frontend, `docs/wireflows/store.md`) installs _extensions_:
versioned bundles that add widgets, full pages, and windows to a project. Extensions may be
authored by anyone (open publishing), so their code is untrusted in exactly the way ADR-031
treats third-party MCP servers — but it renders inside the desktop app, next to the user's
session and the team's proprietary designs. CLAUDE.md §7 forbids letting such code hold
credentials, elevate its scope, or reach arbitrary hosts.

**Decision.**

1. **Runtime: every extension view executes in a sandboxed `<iframe>`.** The bundle is served
   read-only from a custom Electron protocol (`solus-ext://<id>/<version>/...`) that resolves
   only inside the installed bundle directory. The frame runs under `sandbox="allow-scripts"`
   with a strict CSP (no `connect-src`, no remote `script-src`, no `frame-src`), no Node, no
   preload. Window views host the same frame in a second `BrowserWindow`. Extension code never
   receives a Supabase token, an API base URL, or any credential.
2. **Bridge: extensions talk to Solus only through a host-mediated `postMessage` API.** The
   host (renderer) validates every request against a closed method allowlist, the manifest's
   declared `permissions.scopes` and `permissions.network`, and the open project's scope, then
   performs the real call with the user's session. Unknown methods, undeclared scopes, and hosts
   outside the allowlist are refused with a typed error; every refusal is a data-collection
   event. Model-invoking bridge methods carry the extension id as the credit attribution and are
   metered under the user's budget (ADR-018/019); the same loop guards and rate limits apply.
3. **Manifest: `extension.toml` at the bundle root is the whole declaration**, validated by the
   `extension-manifest` contract (`packages/contracts` + `packages/shared-types`): strict
   schema, unknown fields rejected except inside a bounded `[store]` block, size caps on every
   free-text field and asset, no executable or command fields. `id` is a mandatory slug
   (`^[a-z][a-z0-9-]{1,63}$`, case-insensitively unique) and doubles as the folder name;
   display name is free text. Icons are monochrome SVG reduced to a path-only subset by the
   host. Permissions are a closed scope set plus a network host allowlist; declaring either
   requires a privacy policy. Settings are declared as typed fields and rendered by Solus.
4. **Layout (amends ADR-034 Layer 1):** installed bundles are cached at
   `~/.solus/extensions/<id>/<version>/` (0700/0600, written atomically by the desktop MAIN
   process, content-hash verified against the registry before first use, removable at any
   time). A developer-mode entry may point at an unpacked folder anywhere on disk and is never
   published. Nothing extension-related lives in the repo-committed `.solus/` layer; the git
   connector ignores an `extensions/` folder there if one appears.
5. **Registry and publishing: open publish, manual verification.** Any signed-in developer may
   publish a version; an ARQ job validates the manifest, enforces bundle size and content-type
   caps, and rejects bundles with disallowed asset types before the version becomes visible.
   Bundle bytes ride the existing `ArtifactStore` path. The "Solus verified" badge is a manual
   flag set by Solus staff on the extension row, never derived from publisher name. Installs
   pin a version; updates are an explicit user action. Team owners may set project defaults and
   block an extension team-wide; project members may install unblocked extensions.

**Why.** The sandbox + bridge is the only combination that lets community code ship without
extending the ADR-031 fork-and-review economics to every extension, while keeping §7's
invariants mechanical rather than reviewed: the host decides what runs, what it may call, and
where it may connect. Pinning the manifest as a contract keeps the store, the validator, the
bridge, and the developer docs reading one shape.

**Consequences.** New contract `extension-manifest` (both languages, shared fixtures). New API
surface (`docs/api/API.md` §2.17 Extensions). New tables (`docs/schemas/extensions.md`). The
desktop main process gains a bundle installer, a custom protocol, and the extension window
host; the renderer gains the bridge host, the Live Bench widget canvas, and rail page slots.
Developer docs live in `docs/extensions/`. Format or layout changes to
`~/.solus/extensions/` amend this ADR and ADR-034 together.

**Revisit when:** Electron `webview`/utility-process isolation offers stronger boundaries than
the iframe sandbox; an extension needs a capability the closed scope set cannot express
(add the scope here, never as a bridge special case); or publish volume needs automated
review beyond static checks.

**Amended — 2026-09-05, SOLUSDEV-246 (STORE ST1, human-approved in-chat per ADR-032):**

1. **First-party bundles may carry server-side capability — declared, never shipped.**
   `extension.toml` `schema_version = 2` adds optional `[backend]`, `[graph]` and `[tools]`
   tables. The code behind them is an **in-repo** Python package
   (`packages/api/src/solus_api/widgets/<id>/`), reviewed at the MR exactly as ADR-031/MCP-03
   treat any code that runs outside the sandbox; a bundle zip never carries executable server
   code, and the publish validator rejects these tables unless the publisher is Solus staff and
   the in-repo package exists and provides what is declared. Community bundles are unchanged:
   the sandbox + bridge remain their whole surface. Routes mount at
   `/api/v1/projects/{project_id}/widgets/<id>/…`; tools register through the untouched W0-04
   `ToolRegistry` as `<id>.<name>`; kinds land as `ext:<id>:<name>` with `origin="extension"`.
2. **§4 amended — the repo `.solus/` layer gains one extension-related occupant.**
   `.solus/project.toml` may carry `[ext.<id>]` tables, one per installed first-party bundle,
   holding non-secret team defaults validated against that bundle's declared settings schema
   at read time. The git connector lands the file as a single `solus_project_toml` entity (the
   `solus_config` kind is the project's `.solus` root node, SOLUSDEV-242); nothing
   else extension-related lives in `.solus/`, and an `extensions/` folder there is still
   ignored.
3. **Uninstall leaves no trace.** Removing a bundle soft-deletes the graph entities of its
   declared kinds in that project (ADR-027 soft delete — reversible), deletes its settings,
   `storage.own` rows and canvas slots; the desktop removes its cache as before. The former
   "graph data it already added stays" copy is retired.

---

## ADR-035: MCP hosting model, third pattern — vendor-hosted servers we cannot fork

**Status:** Accepted (2026-08-31 — ratified by Pratham in-session per ADR-032 tier 2; Mehdi review at the SOLUSDEV-168 MR)
**Context:** SOLUSDEV-168 (hosted FeatureScript MCP), ADR-031 (MCP hosting model), ADR-019 as
amended 2026-08-30 (third-party integration quotas)

**Context.** ADR-031 fixed ONE hosting model — fork, harden, own, run on the customer's machine
— with two patterns: Pattern 1 tools (a vendored stdio fork the companion launches) and Pattern
2 telemetry (never MCP; the `LiveConnection` seam). Onshape Labs' FeatureScript MCP server
(`https://fs-mcp.labs.onshape.app/mcp`) is neither. It runs on **Onshape's own cloud
infrastructure**, closed-source: there is nothing to fork, no launch entrypoint to pin, no
vendored tree to hash. It authenticates per CUSTOMER over OAuth and spends that customer's own
Onshape API allocation. ADR-031's enforcement machinery — provenance record, license boundary,
pinned `bin/launch`, a security review voided by a vendored-tree hash change — has no subject
here, and applying it literally would either block the integration or be theatre. Its SECURITY
posture, however — _everything a server advertises or returns is untrusted; the tool namespace
available to any SOL invocation is fixed cloud-side against the Solus-owned allowlist, never by
what a machine advertises_ — is exactly what a vendor-hosted server needs, and more.

**Decision.** Solus adds a THIRD pattern to the ADR-031 hosting model. ADR-031 stands unchanged
for Patterns 1 and 2.

**Pattern 3 — vendor-hosted servers.** An MCP server running on a third party's infrastructure,
which Solus neither owns nor can fork, may be integrated under these conditions — all mechanism,
not posture:

1. **No forking obligation, because no Solus-shipped code runs on the customer's machine.**
   ADR-031's fork-harden-own requirements (PROVENANCE record, MIT/Apache-only boundary, pinned
   `bin/launch`, vendored-tree hash) are _inapplicable_ to Pattern 3 and are formally waived for
   it. They exist to control code Solus ships onto a customer's machine; Pattern 3 ships none.
   The supply-chain question is replaced by a vendor-admission question, answered by the review
   below.
2. **Hosted servers live in their own cloud-side registry, never in the loopback catalog.** The
   local catalog's `url` field means _loopback, on this machine_ as a security invariant — a
   non-loopback entry there would hand the companion an SSRF primitive inside the customer's
   network. Hosted servers get a separate registry (`agent/tools/remote_mcp.py`), and adding one
   is a DATA entry there and nothing else. If adding a server ever requires editing that
   module's logic rather than its data, the abstraction is wrong.
3. **Exposure is allowlist-driven, never what the server advertises.** Discovery stays LIVE —
   tool names are never hardcoded — but a discovered tool is registered only if it appears in
   the Solus-authored allowlist on the spec; anything else is SKIPPED with a warning, not merely
   gated. A tool the vendor adds between releases therefore does not exist in SOL's namespace at
   all. `requires_confirmation` and the consent sentence a human reads are Solus-authored per
   TOOL — never the server's own `destructiveHint`, `description`, or any other advertised text,
   which a vendor could use to describe a destructive tool as read-only. Tools that act on the
   customer's account or billing relationship rather than on their work are omitted by default
   and thereby unreachable (on fs-mcp: `logout`, which ends the customer's session, and
   `set_api_allocation`, which re-points who is billed).
4. **OAuth endpoints are PINNED as Solus data; discovery is forbidden.** The authorize, token
   and registration URLs are literal fields on the spec, captured from a live spike and
   reviewed. Solus does not use the MCP SDK's OAuth client provider, whose discovery fetches the
   URL read verbatim out of the server's own `WWW-Authenticate: resource_metadata="…"` header
   and then trusts that document's `authorization_servers[0]` — a blind SSRF out of the Solus
   cloud plus an authorization-server substitution primitive — and which additionally REWRITES
   the requested scope from the resource's advertised `scopes_supported` (fs-mcp advertises
   `OAuth2Delete` and `OAuth2ReadPII`, both forbidden on the record: Delete would let a confused
   agent wipe a customer's document). Scopes requested are the spec's own, minimised and
   recorded; a grant returned WIDER than requested is refused and never stored.
5. **Tokens are per customer, held on the Source, and never Solus's.** The grant identifies the
   CUSTOMER: the server acts as them, under their own vendor sign-in, spending their own API
   allocation. The token is stored in the SecretStore under a ref derived from the connected
   `Source`, resolved per call (hosted tokens are short-lived), refreshed in place, and swept on
   every source- and user-deletion path alongside the connector's own refs. A hosted server is
   never its own tile or `SourceType` — it is an add-on to a connection the customer already
   made, so tenant scope is the Source's scope and no new scoping concept is invented.
6. **The authorization code completes through an AUTHENTICATED exchange.** The code lands on the
   desktop loopback and is posted to an authenticated route that binds the OAuth state to the
   requesting user. The connector-era unauthenticated `GET /{provider}/oauth/callback` is NOT
   used for hosted servers: it never checks the state's `user_id`, and under a write scope that
   is an account-linking CSRF which would write into a victim's documents.
7. **Enabling a vendor app is DISCLOSED at connect time.** Turning a third-party app on someone
   else's vendor account is a trust cost even when free, and it OUTLIVES the Solus connection.
   The spec carries a plain notice naming the app, stating that it runs as the user, that it
   spends the user's own allowance, and that disconnecting Solus does not remove it. The notice
   informs; it never blocks the connection, and enabling a hosted add-on is never a step of the
   underlying connector's connect flow.
8. **Calls are metered under ADR-019's second budget.** Outbound calls spend the customer's own
   provider allowance, so they are admitted through the provider-quota meter under a DISTINCT
   provider key per hosted server — never sharing the connector's ledger, since the two are
   separate pools at the vendor — with SOL turns classified as deferrable `agent` traffic so
   they yield the degraded band to a human's own explicit action. No new budget mechanism, and
   nothing here reaches the credit ledger.

**What a NEW hosted server needs before it is added.** A signed, evidence-based review by both
devs, recorded like ADR-031's, covering:

- **Vendor and endpoint provenance** — who operates the server, on what domain, and a captured
  live spike as evidence for every pinned URL. Endpoints copied from documentation without a
  live capture are not evidence.
- **A live `tools/list` capture with EVERY advertised tool classified** — expose or omit, and
  for each exposed one whether it mutates plus its Solus-authored consent sentence. A tool that
  cannot be given an honest one-line consent sentence is not exposed.
- **Scope minimisation on the record** — the exact scopes requested, why each is needed, and
  which advertised scopes are deliberately refused.
- **Data-flow review** — what customer data leaves Solus in a call, and confirmation that no
  Solus credential, no other tenant's content, and no system-prompt text can reach the server.
- **Prompt-injection posture** — confirmation that advertised descriptions and schemas are
  treated as untrusted (descriptions fenced and capped, schema prose stripped, non-text results
  never inlined) and that results are validated before they render, write to the graph, or feed
  a downstream tool.
- **Failure and cost posture** — the vendor's rate/quota model, which quota key it meters
  against, and exactly what a human sees when the grant expires or the allowance is exhausted.
- **A written re-review trigger** — the review is voided by any change to the exposed tool set,
  the pinned endpoints, or the requested scopes. That is Pattern 3's equivalent of ADR-031's
  vendored-tree hash.

**Rationale.** Not all the interesting robotics tooling is local, and some of it will never be
forkable: FeatureScript authoring runs inside Onshape's own service and can run nowhere else.
Refusing Pattern 3 would exclude those capabilities outright; pretending it is Pattern 1 would
apply controls with no subject while leaving the controls that DO matter — namespace, scopes,
endpoints, token custody — unstated. ADR-031's real insight was that the tool namespace is fixed
cloud-side against a Solus-owned allowlist, never by what the far end advertises; that insight
is transport-independent and Pattern 3 carries it over verbatim, replacing supply-chain
ownership with a vendor-admission gate. Pinning the OAuth endpoints rather than discovering them
is the single highest-value control here: discovery is where an SSRF, an authorization-server
substitution and a scope escalation all enter through one attacker-controlled header.

**Consequences.** Solus depends on a vendor's uptime, versioning and pricing for a Pattern-3
capability with no fork to fall back on — a hosted server going away is a feature outage, and
that is accepted knowingly. A vendor that adds a tool gets NO reach into SOL until Solus
classifies it, so shipping a vendor's new tool costs a review and a release; the failure mode is
a missing capability, never an unreviewed one, which is the trade we want. The CUSTOMER, not
Solus, bears the vendor's API cost, so any allowance position surfaced in the UI must be
labelled an estimate (ADR-019's honest limit). Enabling a Pattern-3 app leaves a lasting change
on the customer's vendor account that Solus cannot undo, which is why the disclosure is
mandatory rather than advisory. Adding a second hosted server must remain a data entry plus a
review.

**Revisit when:** a vendor offers a self-hostable or forkable build of a server we use under
Pattern 3 (it then moves to Pattern 1 and the stricter controls apply); OAuth protected-resource
metadata discovery becomes safely constrainable — a pinned issuer allowlist would let endpoint
pinning relax without reopening the SSRF; the hosted-server count makes per-server admission
review untenable (then invest in a shared review template and automated capture-diffing, not a
weaker gate); or a hosted server needs to act on more than one tenant's data in a single call,
which this design forbids and which would need a new decision.

---

## ADR-036: Engineering corpus — a global long-prose table under extended ADR-033 containment

**Status:** Accepted (2026-09-06 — approved in-session by Mehdi against the concrete text below;
review at the SOLUSDEV-241 CORPUS C2 MR)
**Context:** CORPUS C1 (`docs/corpus/SCOPE.md`, `docs/corpus/LICENSING.md`,
`docs/schemas/corpus-chunk.md`) defined what SOL ships knowing and left storage open, flagging
that a chunk store would be the first global table whose rows are long prose — exactly what
ADR-033's "typed columns only" rule was written to prevent. The C2 ticket asks for ingestion
into pgvector through the existing RAG (SYS-02), domain-filtered retrieval, a versioned shipped
artifact, and a CI eval.

**Decision.** Two tables, `corpus_chunk` and `corpus_release`, with **no tenant column and no FK
to projects, teams, or users** (ADR-033 rule 1). The one relaxation of ADR-033 rule 2: `title`
and `body` are prose columns, contained by closed enums on every categorical field, per-column
caps from `docs/schemas/corpus-chunk.md`, no JSONB or free-form container, and a provenance
vocabulary with no customer or model value. The **only write path** is
`solus_api/corpus/ingest.py` reading the Solus-committed content tree and manifest, run as a
deploy/admin step and enforced by a tripwire test (ADR-033 rule 3). Retrieval filters by domain,
topic, and applicability in SQL first, then ANN when a query embedding exists and full-text
otherwise (ADR-033 rule 4, lexical-first); only `status = active` rows serve — `draft` never.
Chunks enter prompts only as `kind=context_corpus` nonce-fenced data blocks, packed below tenant
context (graph, error, document hits) and below the user's engineering preferences (ADR-034
amendment 2026-09-06). The corpus is versioned by a manifest (semver plus per-chunk content
hashes); ingest is idempotent, chunks absent from a newer manifest are marked `withdrawn` and
never deleted, and every applied version is recorded in `corpus_release`. `embedding` populates
at ingest, unmetered at Solus's cost, because `embed()` now exists (SYS-02); ADR-033's "until
`embed()` exists" condition is met.

**Why.** Prose is the content here, not a label, so the tool-knowledge prose patterns cannot be
the filter; containment must come from the absence of any field that could reference a customer,
closed vocabularies, one curated write path, and a serve gate on human review. A static bundle
would satisfy containment too, but forfeits ANN retrieval and contradicts the ticket.

**Consequences.** A second global prose table qualifies only under all of the above, and a
reviewer signature (`reviewer`, `reviewed_at`) is what moves a chunk from `draft` to served.
Adding any field named in `docs/schemas/corpus-chunk.md` §3 is a security change, not a schema
change. Content authored with LLM assistance is `drafting = llm_assisted` and is signed by the
human reviewer at the MR — the model is never the reviewer.

---

## How to add or change a decision

1. New decision: append an entry with the next ADR number, date it, set Status: Accepted.
2. Changing a decision: set the old entry's Status to **Superseded by ADR-XXX**, add the new entry referencing what it replaces and why. Never delete history.
3. Humans own decisions; agents may edit this file only under ADR-032 tier-2 (concrete change approved in-chat first, dedicated commit). An agent that believes a decision needs revisiting raises it in its design-review critique or completion report.
