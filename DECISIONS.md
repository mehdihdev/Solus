# DECISIONS.md — Solus Architecture Decision Records

This file is the authoritative record of locked decisions. It sits at the top of the document authority hierarchy (see CLAUDE.md §3). Agents read it and treat it as settled; agents never modify it. Decisions change only through deliberate human revision of an entry (mark the old entry Superseded, add the new one). Each entry: context, decision, alternatives rejected, and when to revisit.

All entries below were codified 2026-06-06 from the initial planning cycle.

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

## ADR-010: SOL Agent is an orchestrator, not a custom multimodal model
**Status:** Accepted
**Context:** A trained-from-scratch multimodal robotics model is a multi-year research effort. The graph already performs structural multimodal fusion.
**Decision:** The agent orchestrates: pulls subgraph context, invokes validated tools (checkers, geometry analysis, retrieval), calls hosted LLMs (Claude) for reasoning, combines results. Specialized models plug in as tools behind the tool interface.
**Rejected:** Training custom foundation/multimodal models this cycle; monolithic model ingesting raw CAD/code/schematics.
**Revisit when:** ≥10–15K labeled interaction examples exist (see ADR-011) — then fine-tuning specialized models (e.g., heterogeneous GNNs for change-impact) becomes justified.

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

## ADR-016: SOL modes are a universal setting
**Status:** Accepted
**Decision:** Guide mode (teaches, explains, assumes domain unfamiliarity) and Expert mode (terse, leads with answers) — per-user, switchable anytime, available on every tier. Every feature producing natural-language output consumes the mode setting.
**Rejected:** Modes as a tier differentiator.

## ADR-017: Pricing — no free-forever tier; base subscription + credit allowance
**Status:** Accepted
**Decision:** Trial-then-pay (30-day or active-days trial; no card to start). Individual: $20/mo (annual ≈ $192) including a monthly credit allowance. Teams: per-seat ($50 academic / $120 commercial, 3-seat min) with a **pooled** team credit allowance scaling by seats and admin-controlled spending caps. Education: flat ≈$1,500/yr unlimited-seat license. Enterprise: quoted; committed-use credit blocks later.
**Rejected:** Free-forever tier (support load, weak demand signal), per-member team allowances (robotics usage is lumpy; pooling absorbs spikes).
**Revisit when:** Real usage data exists to tune allowance sizes and prices.

## ADR-018: Metering in credits, not tokens; ambient checks unmetered
**Status:** Accepted
**Decision:** Model-backed actions (agent queries, deep diagnoses, fingerprint LLM checks, proving runs) consume credits; pure-logic checkers and ambient autocomplete are unmetered. Allowance sized so 100% consumption ≈ model cost (base fee is margin). Overage: top-up packs or opt-in metered overage with user/admin-set caps — never silent charges. At the cap: graceful degradation to a cheaper-model "lite mode" with a banner, not a dead product. Always-visible usage meter.
**Rejected:** Raw token metering (incoherent across orchestrated models; blocks model swaps), metering the ambient layer (kills the feature psychologically).

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

---

## How to add or change a decision

1. New decision: append an entry with the next ADR number, date it, set Status: Accepted.
2. Changing a decision: set the old entry's Status to **Superseded by ADR-XXX**, add the new entry referencing what it replaces and why. Never delete history.
3. Only humans edit this file. An agent that believes a decision needs revisiting flags it in its design-review critique or completion report.