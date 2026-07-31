# CLAUDE.md — Solus Root

This file governs all AI-assisted development in this repository. Read it fully before writing any code. Every agent session, subagent, and human contributor follows these rules. Directory-level CLAUDE.md files extend and override this one within their scope.

---

## 1. What Solus Is

Solus is a cross-domain development workspace for robotics teams. A robot lives in four worlds at once: code, electronics, mechanical design, and physical runtime. Today those worlds don't talk to each other. A firmware engineer works in GitHub, an electrical engineer in KiCad, a mechanical engineer in Onshape, and someone runs the actual robot — and when a change in one domain breaks another, nobody finds out until the robot fails. Robotics teams lose the majority of their development time to integration debugging across these boundaries.

Solus solves this by building a unified graph — the Robotics Context Model — across all of a team's tools, then reasoning over that graph to catch cross-domain problems before they break the robot.

The product thesis in one line: be the connective tissue across the tools robotics teams already use, and the reasoning layer no single tool can provide.

### Target customers

Solus serves one product to a tiered market. Features are universal; pricing and onboarding differ by tier.

- **Individuals** — solo builders who are expert in one domain (usually software) and use Solus to work in, and learn, the domains they don't know. Self-serve, product-led.
- **Teams (core segment)** — full-stack robotics startups and research labs (3–50 engineers) building custom robots end-to-end: custom PCBs, firmware, CAD, ROS-based software, real hardware. Founder-led sales.
- **Education / student teams** — FSAE/Formula Student and similar competition teams. Design partners under a flat education license; high churn of members makes the graph-as-living-documentation especially valuable.
- **Enterprise (deferred)** — known robotics companies. Inbound only this cycle; quote, don't build. Architectural decisions must not foreclose self-hosting, SSO, or audit logging later.

Build implication: do not build segment-exclusive features. The same graph, agent, and Live Bench serve everyone. The individual→team upgrade flow (one user invites a teammate, billing transitions seamlessly) is a first-class requirement of the Teams feature area, since land-and-expand depends on it.

### Core architectural concept

Everything in Solus revolves around the graph:

- **Entities**: typed nodes representing anything in the robot system — a code module, an IC, a motor, a CAD part, a ROS node, a telemetry signal, a deployment target.
- **Relations**: typed edges between entities — drives, reads_from, depends_on, connected_to, mates_with, deployed_on.
- **Sources**: connected external tools (GitHub, KiCad, Onshape, ROS, GitLab) that populate the graph via connectors.
- **The reasoning layer**: checkers, the fingerprint matcher, and the SOL Agent all operate on the graph, never on tool-specific raw data directly.

If you are building a feature and it does not read from or write to the graph, stop and check the architecture docs — you are probably building it wrong.

---

## 2. Planned Feature Areas

These are the twelve feature areas for the current build cycle. Each has (or will have) its own directory and its own CLAUDE.md with detailed specs.

1. **Integrations** — Connectors for GitHub, GitLab, KiCad, Onshape, ROS. Each implements the common connector interface and translates tool-specific data into graph entities and relations. An SDK for third-party/internal tooling comes later; build connectors so that extraction into an SDK is natural.

2. **Part Compatibility** — Checks that parts across the stack are compatible: pin assignments, bus addresses, voltage levels, power budgets, connectors, packages.

3. **System-Level Proving** — Concurrent execution of all compatibility checks across the entire graph, producing a full-system compatibility report.

4. **Multimodal Fingerprint** — Cross-tool entity identity matching. Determines that CAM_v2 in Onshape, OV9281_IC in the schematic, and camera_node in ROS are the same physical component, using four signals: semantic (name similarity), supply chain (manufacturer part numbers), topological (what it connects to), and spatial (physical coordinates). Combines signals into a confidence score; users confirm or reject proposed matches; confirmations link entities in the graph.

5. **SOL Agent** — The orchestrating AI agent. Pulls relevant graph context, invokes checkers and analysis tools, calls LLMs for reasoning, and produces diagnoses, explanations, and fixes. Rendered in the UI as the "ball of energy" presence. The agent is an orchestrator of models and tools — not a single monolithic model. **SOL modes are a universal user setting, available to every user regardless of tier or segment**: at minimum Guide mode (assumes unfamiliarity with the domain at hand; explains reasoning, teaches concepts, links to fundamentals as it works) and Expert mode (terse, assumes competence, leads with the answer). Mode is per-user, switchable at any time, and respected consistently across the agent, autocomplete warning explanations, error messages, and the tutorial overlay. Every feature that produces natural-language output for the user must consume the mode setting.

6. **Live Bench** — The runtime surface, with two modes sharing one UI: Sim mode (MuJoCo simulation generated from the team's CAD/URDF, updating when CAD changes) and Real mode (live telemetry from hardware over serial/ROS). Includes signal visualization, anomaly detection, and send-to-agent diagnosis.

7. **Error Logging & Prediction** — Captures errors across the system and uses the checkers plus the agent to predict likely failures before they happen.

8. **Deployment** — Getting code onto robots: Arduino flashing first, SSH-based deployment to Jetson/Pi targets after.

9. **Data Collection System** — Internal structured event logging of how engineers use Solus: every sync, diagnosis, fingerprint confirmation, warning acceptance/dismissal, fix outcome. No training pipeline — clean, consented, queryable storage only. This data is the seed of future foundation models; treat its schema with care.

10. **Teams** — Multi-user collaboration: team management, invites, roles, activity feed, cross-domain change notifications, optimistic concurrency with conflict detection informed by the graph.

11. **Robotics Autocomplete** — Proactive cross-domain warnings triggered by changes: "this casing blocks the USB-C port," "this I2C address conflicts with the IMU," "this package needs CUDA 12 but your Jetson has 11.8." Built on the checker library, surfaced contextually before problems become bugs.

12. **Workspaces & Tutorial Overlay** — Guided experiences: interactive onboarding flows inside Solus, plus in-tool guidance (browser extension overlay for web tools like Onshape; synchronized companion-window guidance for desktop tools).

---

## 3. Repository Structure & Document Authority

### Current structure (descriptive, not prescriptive)

The layout below reflects the codebase **as it stands today**. It is a map, not law. Solus is an evolving system — services will split, merge, and be reimplemented (a Rust rewrite of the telemetry and collaboration core is an anticipated future change, and other restructurings will follow as the product grows). Do not treat this tree as immutable, and do not reject work merely because it proposes a structural change.

What IS stable across restructurings:

- **The contracts** (`packages/contracts/`) — interfaces outlive implementations. A connector, checker, or telemetry service may move directories or change language; the contract it implements does not change as a side effect.
- **The authority hierarchy** below — whatever the structure becomes, the docs govern it.
- **The principle of clean seams** — performance-critical boundaries (telemetry streaming, collaboration sync, heavy analysis) stay isolated behind stable interfaces precisely so their implementations can be swapped (e.g., Python → Rust) without a rewrite of everything around them.

How structure evolves: structural changes are proposed by humans (or flagged by agents for human decision), recorded in DECISIONS.md, and reflected by updating this section and the architecture diagrams **in the same MR** as the restructure. A stale map is worse than no map — if you move something, update the map.

```
solus/
├── CLAUDE.md                  ← this file (root authority)
├── DECISIONS.md               ← locked architectural decisions (ADRs)
├── Makefile / package.json / pnpm-workspace.yaml / .npmrc
├── tsconfig.base.json / eslint.config.mjs / .prettierrc.json   ← the JS law H7/H8/H10 enforce
├── pyproject.toml             ← uv workspace + ruff/mypy law  ·  .python-version (3.12)
├── docker-compose.dev.yml / .gitlab-ci.yml   ← parked until Docker/GitLab setup
├── .claude/                   ← agent harness: settings.json + hooks (H1–H14), agents/,
│                                skills/, commands/, rules/ecc/  (state/ is gitignored runtime)
├── docs/
│   ├── architecture/          ← architecture diagrams (authoritative)
│   ├── wireflows/             ← UI wireflows (authoritative)
│   ├── api/                   ← API route plans (authoritative)
│   ├── schemas/               ← database schema docs & ERDs
│   └── qa/                    ← COWORK_QA_<feature>.md handoff files
├── apps/
│   ├── desktop/               ← Electron + React + TS (electron-vite; main/preload/renderer)
│   │   └── CLAUDE.md
│   └── web/                   ← Next.js marketing/landing site ("@solus/web")
├── packages/
│   ├── api/                   ← FastAPI core backend ("solus-api")
│   │   └── CLAUDE.md
│   ├── shared-types/          ← TS types shared FE↔BE
│   └── contracts/             ← interface contracts (connector, checker, tool, telemetry, event) — human-owned
├── integrations/
│   ├── github/  gitlab/  kicad/  onshape/  ros/
│   └── CLAUDE.md              ← connector-specific rules
├── reasoning/
│   ├── checkers/              ← compatibility check library
│   ├── fingerprint/           ← multimodal fingerprint matcher
│   ├── agent/                 ← SOL Agent orchestration
│   └── CLAUDE.md
├── livebench/
│   ├── sim/  telemetry/  anomaly/
│   └── CLAUDE.md
└── infrastructure/
    ├── docker/  ci/  aws/
    └── CLAUDE.md
```

### Document authority hierarchy

When sources conflict, authority flows in this order. Higher overrides lower:

1. **DECISIONS.md** — locked decisions. Never contradict these. If a task requires changing or adding one, propose the concrete ADR text in-chat (AskUserQuestion), get explicit approval, then edit directly in a dedicated commit (ADR-032 two-tier governance).
2. **docs/architecture/** diagrams — the system structure. Code must match the diagrams. If a diagram is missing or ambiguous for your task, stop and ask; do not invent structure.
3. **docs/api/** route plans — API surface is designed before implementation. Implement routes exactly as planned: paths, methods, request/response shapes. Do not build undocumented routes. If a needed route is missing, amend the route plan directly (tier-1, ADR-032), call the amendment out in the completion report, and build against it — the MR review is the approval gate.
4. **docs/wireflows/** — UI structure and user flows. Frontend work must match the wireflows. Visual polish within a wireflow is your judgment; changing the flow itself is not.
5. **Directory CLAUDE.md** — feature-specific rules. These extend the root; within their directory they may add stricter rules but never relax root security or testing requirements.
6. **This root CLAUDE.md** — the baseline everything inherits.
7. **Installed harness assets** — the rules in `.claude/rules/ecc/`, skills in `.claude/skills/`, and subagent personas in `.claude/agents/`. These are adopted best practices (curated from the ECC project, MIT) that agents and subagents must read and learn from: rules are always-follow style/procedure guidance, skills are consulted before improvising any procedure they cover, and agent personas define the reviewer/planner/security subagents the protocol names. They sit at the BOTTOM of this hierarchy — where any asset conflicts with anything above (e.g., generic git advice vs. ADR-021), the higher document wins. The Solus-adapted versions shipped in-repo (`solus-git-workflow.md`, the Solus `security-reviewer` and `planner` agents) are already reconciled; prefer them over any generic equivalent.

**Mandatory pre-work check**: before writing code for any task, list which architecture diagrams, API plans, and wireflows govern it, and confirm you've read them. If none exist for your task, that is a signal the design phase is incomplete — flag it rather than improvising.

---

## 4. Technology Stack (Locked for This Build Cycle)

These choices are recorded in DECISIONS.md and are not open for re-litigation inside a coding session. They are locked **for the current build cycle** — not forever. Known anticipated evolutions (e.g., migrating the telemetry/collaboration core to Rust, revisiting orchestration when scale demands it) happen through DECISIONS.md revisions between cycles, never as improvisation inside a feature MR. Build against today's stack; respect the seams that make tomorrow's swaps surgical.

- **Backend**: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 + Alembic
- **Database**: PostgreSQL (AWS RDS) with pgvector
- **Background jobs**: ARQ + Redis — all heavy analysis (system proving, large checks, sync processing) runs as background jobs, never in the request path
- **Frontend**: Electron, React, TypeScript, Vite, Tailwind, Zustand
- **Realtime**: WebSockets via an isolated telemetry service boundary (implementation may be swapped later; the interface is the contract)
- **AI**: Claude API for reasoning/orchestration; specialized tools and models invoked by the agent through the tool interface
- **Cloud**: AWS — App Runner/ECS Fargate, ECR, S3, Secrets Manager, CloudWatch. No Kubernetes in this build cycle.
- **CI/CD**: GitLab CI (lint → type-check → test → build → deploy staging → deploy production on main)
- **Repo**: GitLab monorepo, MR-based workflow, protected main

---

## 5. The Orchestration Protocol: How Features Get Built

This project is built by two human developers orchestrating AI agents. Work flows through a defined protocol with phases and gates. The main agent is an orchestrator: it receives a spec, interrogates it, plans the execution, deploys subagents, verifies the result, and hands off. Humans open and merge all MRs — agents never do.

### Phase 0 — The spec packet

A feature begins when a human provides a spec packet: prose requirements, plus any architecture diagrams, wireflow images, API route plans, screenshots, and reference material. Read everything provided, including images and diagrams, before responding. Cross-reference the packet against the governing docs (DECISIONS.md, docs/architecture, docs/api, docs/wireflows).

### Phase 1 — Design review gate (mandatory, before any code)

Before any implementation begins, the main agent must critique the spec and surface questions. This is not optional politeness; it is the cheapest moment to catch design flaws. Produce:

- **Critique**: weaknesses, ambiguities, missing edge cases, conflicts with existing architecture or contracts, security implications, performance concerns.
- **Suggestions**: concrete alternatives where the design could be simpler, safer, or more consistent with the rest of the system.
- **Questions**: everything genuinely ambiguous, prioritized — blocking questions first, nice-to-know after.

Then **stop and wait for human answers**. Do not begin implementation on unanswered blocking questions. If the human says "proceed with your judgment" on a question, record the chosen interpretation in the completion report.

### Phase 2 — Execution planning

With the design settled, produce an execution plan before spawning anything:

- **Task decomposition**: break the feature into units of work, each with a crisp, self-contained spec.
- **Dependency graph**: which tasks depend on which. Tasks with no dependency edge between them are parallel candidates.
- **Sequential vs parallel decision**: parallelize only tasks with disjoint file sets and no shared unstable interfaces. If two tasks need the same interface, build (or extract) the interface first — sequentially — then parallelize the implementations against it. When in doubt, sequence; a collision costs more than serialization.
- **File ownership map**: every task lists the files/directories it owns. Parallel tasks must have provably disjoint ownership. No subagent may touch files outside its assignment. Write each task's globs to `.claude/state/ownership/<task-id>.list` (one glob or path prefix per line, `#` comments allowed) — the SubagentStop hook (H12) enforces these manifests mechanically. Delete a task's manifest when its work is merged and verified.
- Present the plan briefly before executing. For large features, the human may want to adjust the split.

### Branch discipline — one ticket, one branch

Every feature is a ticket (e.g., `SOLUSDEV-34: Implement Onshape Integration`) and every ticket gets exactly one feature branch, named from the ticket: `SOLUSDEV-34-implement-onshape-integration`. The rules:

- **All work for the feature lives on that branch.** Agents and subagents never write to any other feature's branch, never to main, and never create branches outside the feature's namespace.
- **Subagent worktrees branch FROM the feature branch**, named under it: `SOLUSDEV-34/kicad-parser`, `SOLUSDEV-34/tests`, etc. Each worktree worker owns its sub-branch and its file set.
- **Sub-branches merge back INTO the feature branch**, integrated by the orchestrator as tasks complete. After merging, the orchestrator removes the worktree and deletes the merged sub-branch, leaving one clean, integrated feature branch.
- **Local commits are workflow mechanics; the remote is human territory.** Agents create local commits on sub-branches and the feature branch as needed for worktree integration — with clear, conventional commit messages referencing the ticket. Agents never `git push`, never open MRs, never merge to or modify main, never force-push, never rewrite history that a human has seen.
- **Humans close the loop**: review the integrated feature branch, make any final commits, perform the push, open the MR, and merge to main after code review.

If a task seems to require touching another feature's branch or main, that is a planning error — stop and flag it.

### Phase 3 — Execution with subagents

Deploy subagents per the plan. Two execution modes, chosen by task shape:

- **In-process subagents** (the default): for research, contract-compliance review, security review passes, test-writing, and bounded implementation tasks. These run inside the main session and return results directly to the orchestrator. Note: in-process subagents do not appear as separate terminals — there is nothing to display for them.
- **Worktree worker agents** (for long-running parallel feature builds): spawn separate Claude Code CLI processes, each in its own **git worktree on a sub-branch of the feature branch** (per Branch discipline above). Worktree isolation makes file collisions physically impossible; the orchestrator merges completed sub-branches back into the feature branch.

**Terminal layout convention (when running inside tmux):** when spawning a worker agent as a separate process, split the current tmux window (`split-window -h` or `-v`, alternating for balance) and launch the worker in the new pane. Before splitting, count panes in the current window; if the window already has 4 panes, create a new tmux window (`new-window`) and spawn the worker there instead. Outside tmux (or iTerm2 with its API), pane control is not available — fall back to instructing the human which commands to run in new terminals, or use in-process subagents. Do not fight the terminal; the worktree isolation is what matters, the panes are visibility.

Subagent rules:

- Each subagent receives: its task spec, the contracts it implements, its file ownership list, and the instruction to write tests first.
- Subagents work toward the goal given. They do not open MRs, do not push to main, do not modify contracts, DECISIONS.md, or files outside their ownership. (Tier-2 governance edits are the ORCHESTRATOR's alone, after in-chat approval — never delegated.)
- Subagent output returns to the orchestrator (in-process) or lands on its branch (worktree) for verification.

### Hooks — the enforcement layer (installed and active)

The guardrails in this document are enforced mechanically by hooks in `.claude/hooks/`, wired via `.claude/settings.json`. They fire automatically: H1–H6 block protected-path edits, off-branch work, secrets, remote git operations, dangerous commands, and file/symbol recreation before they happen; H7–H9 auto-format, lint, type-check, and test every touched file, feeding failures straight back for immediate fixing; H10 is the Stop gate — an agent cannot finish a work session while its diff fails lint, types, tests, secret scanning, or duplication checks; H12 enforces the Phase 2 ownership manifests at SubagentStop; H13/H14 inject session context and snapshot state before compaction.

Rules of engagement with hooks:

- **When a hook blocks you, fix the cause.** The stderr message says what and why. Never bypass a hook, never edit `.claude/hooks/` or `settings.json` (H1 blocks this anyway), never restructure a command to slip past a guard — that is a fireable offense for an agent.
- `SOLUS_DISABLED_HOOKS` is a human-only control. An agent that believes a hook is misfiring flags it in its completion report.
- If a guardrail can be a hook instead of an instruction, propose it as a hook (to a human). Instructions get forgotten; hooks don't.

### Commands — installed workflows (run them at the right phase)

Slash commands live in `.claude/commands/` and agents are expected to USE them, not re-derive their workflows:

- **Phase 2**: `/plan` — execution planning (drives the planner persona; produces the decomposition, dependency graph, and ownership map).
- **Phase 3**: `/build-fix` when builds break; `/checkpoint` to save verification state mid-feature.
- **Phase 4**: `/code-review` (fresh-context review), `/quality-gate` (full verification), `/test-coverage` (coverage audit), `/refactor-clean` (dead-code sweep before handoff).
- **Phase 5 / doc currency**: `/update-docs` and `/update-codemaps` whenever the diff changed structure or behavior that docs describe — the authority hierarchy dies if docs go stale.
- **Anytime**: `/learn` to extract reusable patterns from the session.

If you find yourself doing the same multi-step sequence three times, propose a new command (to a human) and document it.

### Skills, rules, and subagent personas — learn from the installed harness

The harness ships curated knowledge that every agent and subagent must actively use:

- **Rules** (`.claude/rules/ecc/`): always-follow guidance — common coding style, testing, security, performance, plus the `typescript/` and `python/` packs. `solus-git-workflow.md` supersedes any generic git guidance (ADR-021).
- **Skills** (`.claude/skills/`): consult the relevant skill BEFORE improvising any procedure it covers. Installed set includes: `tdd-workflow`, `security-review`, `verification-loop`, `eval-harness`, `search-first`, `python-patterns`, `python-testing`, `backend-patterns`, `frontend-patterns`, `postgres-patterns`, `api-design`, `database-migrations`, `docker-patterns`, `deployment-patterns`, `e2e-testing`, and `cost-aware-llm-pipeline` (read this one before touching SOL Agent budget/metering code — it is domain knowledge for ADR-017/018/019). Capture new domain procedures (KiCad parsing, URDF→MJCF, Onshape auth) as new skills as they stabilize.
- **Subagent personas** (`.claude/agents/`): when the protocol names a role, spawn the matching persona — `planner` (Phase 2), `architect` (Phase 1 support), `tdd-guide` (Phase 3), `code-reviewer` + `security-reviewer` (Phase 4, both mandatory), `python-reviewer`/`typescript-reviewer`/`database-reviewer` (language-specific passes), `build-error-resolver`, `refactor-cleaner`, `doc-updater`, `e2e-runner`. The Solus-adapted `security-reviewer` and `planner` carry §7 model-orchestration checks and the Phase 2 plan format — use those, not generic equivalents.

### Phase 4 — Verification

After all subagents complete, the orchestrator runs the verification pass on the integrated result:

- Full test suite green; coverage matches the spec's cases.
- A fresh-context **review subagent** reads the complete diff against the spec and contracts.
- A dedicated **security subagent** audits the diff against Section 7, including the model-orchestration rules where relevant.
- Style and standards check (Section 8).
- Findings are fixed before handoff, not noted and skipped.

### Phase 5 — Handoff (humans open MRs)

Agents do not open or merge MRs. The orchestrator's final outputs are:

1. **A completion report**: what was built, which docs/specs governed it, test coverage summary, decisions made under delegated judgment, any deviations or open concerns. The feature branch fully integrated (all sub-branches merged and cleaned up) and passing the full validation pass, ready for human review.
2. **The Cowork QA file** — a markdown file named `COWORK_QA_<feature>.md` at the repo root (or `docs/qa/`), written for handoff to Claude Cowork for end-to-end application testing. It must contain, in self-sufficient detail: required setup state (accounts, connected sources, sample data, services running); every user flow the feature introduces or touches, as numbered step-by-step walkthroughs; the expected result at each step; the edge cases and failure paths to exercise (bad input, disconnections, permission boundaries, empty states); cross-feature interactions to verify; and a checklist format so each path can be marked pass/fail. Write it assuming the tester has the running application and this file, and nothing else — no access to the implementation context.

Humans then review the feature branch, make any final commits, push, open the MR, merge to main after code review, and run the Cowork QA pass.

### The division of labor

Humans: design features, write spec packets, answer design-review questions, lock interfaces, push to the remote, open and merge MRs, make architectural calls.
Agents: critique designs, plan execution, implement against locked specs with TDD on the ticket's feature branch, parallelize safely via worktree sub-branches, verify, and hand off.
Never invert this: agents do not make architectural decisions unilaterally. Per ADR-032 (two-tier governance): tier-1 docs (docs/api, docs/architecture, docs/wireflows, docs/schemas, docs/qa, docs/contracts once approved in-session, .gitlab-ci.yml) are agent-editable directly, reviewed at the MR; tier-2 files (DECISIONS.md, packages/contracts/, CLAUDE.md files) require an in-chat human approval of the concrete change BEFORE editing. Agents still never: push to the remote, touch main, open or merge MRs, or edit .claude/hooks, .claude/settings*.json, or .env* (H1 hard-blocks these — non-negotiable).

---

## 6. Development Methodology

### Test-driven development is mandatory

For every feature, in this order:

1. Read the spec, the relevant contracts, and the governing docs (architecture/API/wireflow).
2. Write the tests first, derived from the spec: happy paths, edge cases, failure modes, and authorization cases.
3. Confirm the tests fail.
4. Implement until tests pass.
5. Full Test Coverage.
6. Refactor with tests green.

An MR without tests written against the spec is rejected regardless of whether the code works. Minimum expectations: unit tests for all logic, integration tests for every API endpoint (including auth-failure and cross-team-isolation cases), and contract tests for anything implementing a shared interface (every connector passes the connector contract suite; every checker passes the checker contract suite).

### Definition of done (every task, every MR)

- [ ] Governing docs identified and followed (architecture, API plan, wireflow)
- [ ] Full Test Coverage
- [ ] Tests written first; all passing in CI
- [ ] No secrets in code; configuration via environment/Secrets Manager only
- [ ] Use Ponytail plugin to review and shorten code to utmost required
- [ ] Use Object Oriented Programming principles for scalability
- [ ] All inputs validated (Pydantic schemas / TS validation at boundaries)
- [ ] All DB access parameterized (ORM or bound parameters — never string-built SQL)
- [ ] Auth + team-authorization enforced on every protected route (and tested)
- [ ] Errors handled and logged with enough context to debug ("why did this user's sync fail?" must be answerable from logs)
- [ ] Data-collection events emitted for meaningful interactions (per the event schema)
- [ ] Directory CLAUDE.md rules followed
- [ ] Self-review and security-review subagent passes completed; findings addressed
- [ ] Completion report written: spec followed, docs consulted, test coverage summary, delegated-judgment decisions, any deviations flagged
- [ ] `COWORK_QA_<feature>.md` written per Phase 5 — self-sufficient user-flow test plan ready for Claude Cowork

### Merge request workflow

- All work lands via MR into main. No direct pushes to main. CI must be green.
- **One ticket = one feature branch = one MR.** Humans perform the final git add/commit, push, open the MR, and merge. Agents prepare: the integrated feature branch passing the full validation pass, the completion report, and the Cowork QA file. The push, the MR, and the merge are human actions.
- Keep ticket scope to one feature unit so MRs stay reviewable. A connector is one ticket. A checker (or small related group) is one. Oversized scopes get re-split into tickets before review.
- If implementation revealed a flaw in the spec or a missing API route, say so explicitly in the completion report — do not silently work around it.

---

## 7. Security Requirements (Non-Negotiable)

Solus handles teams' proprietary robot designs — schematics, CAD, firmware. A breach is existential. These rules bind every line of code, and several are enforced by hooks and CI; the rest are enforced in review.

**Secrets & credentials**

- No secrets, API keys, tokens, or credentials in source, tests, fixtures, or logs. Ever.
- All secrets come from environment variables / AWS Secrets Manager.
- Integration credentials (users' Onshape/GitHub tokens) are encrypted at rest, never logged, never returned by any API response.
- CI runs secret scanning; a detected secret fails the pipeline.

**Injection & input handling**

- Database access only through the ORM or parameterized queries. String-concatenated SQL is an automatic MR rejection.
- Every API input validated against a Pydantic schema. Reject unknown fields on sensitive endpoints.
- No eval/exec on user-influenced input anywhere — including inside the agent's tool-calling paths. Agent tool arguments are validated like any other untrusted input.
- File uploads (CAD, schematics): validate type and size, store in S3, never execute, never unzip blindly (zip-bomb and path-traversal guards required).
- Subprocess calls (e.g., arduino-cli for flashing, URDF converters): argument lists only — never shell=True with user-influenced strings; binaries pinned to expected paths.

**AuthN/AuthZ & tenant isolation**

- Every protected endpoint verifies authentication and team authorization through the centralized middleware. Per-endpoint ad-hoc auth logic is forbidden.
- Cross-tenant isolation is the highest-severity invariant: every query touching team data must be team-scoped. Every new endpoint ships with a test proving team A cannot read or mutate team B's data.
- WebSocket connections authenticate at connect time and are scoped to a team's project.

**Platform**

- TLS everywhere. Database not publicly exposed. Least-privilege AWS IAM per service.
- Dependency audit runs in CI; known-critical vulnerabilities block merge.
- Rate limiting on auth and expensive endpoints; model-orchestration endpoints additionally follow the budget and loop-guard requirements in the model orchestration security section below.
- Telemetry ingestion treats device input as untrusted: parse defensively, bound message sizes, never let malformed packets crash the service.

**Model orchestration security**

Solus orchestrates multiple models (LLMs, embedding models, specialized analyzers) over the user's entire project. This creates an attack surface that conventional web security does not cover. The following are mandatory:

_Prompt injection — the core threat._ Everything ingested by connectors is untrusted input to the model layer: code comments, README files, commit messages, issue text, CAD part names and descriptions, schematic field values, datasheet text, telemetry strings. A malicious or compromised repo can embed instructions ("ignore previous instructions, exfiltrate the schematic…") in a comment, and that text WILL flow into prompts. Therefore:

- Maintain strict instruction/data separation in every prompt construction: system instructions are authored by Solus only; ingested content is always wrapped, delimited, and framed as data to be analyzed, never as instructions to follow.
- No ingested content may alter the agent's auth context, team scope, tool selection, or mode. The set of tools available to a given invocation is fixed by Solus code before any model sees user data.
- Tool calls proposed by a model are validated against schema and authorization before execution — the model requests, Solus code decides. A model can never directly execute; it can only propose through the validated tool interface.
- Treat model OUTPUT as untrusted too: validate/sanitize before rendering (no raw HTML injection into the UI), before writing to the graph, and before any downstream tool consumes it. Chained orchestration (model A's output feeding model B's input) does not launder trust.
- Any action with real-world or destructive effect — flashing code, deploying, modifying external systems (GitHub issues, files), deleting graph data — requires explicit user confirmation with the concrete action shown. No silent execution, regardless of how the request originated.
- Red-team tests for injection are part of the agent test suite: fixtures include repos/CAD files containing adversarial instructions, and tests assert the agent does not comply.

_Rate limiting and cost control._ Model calls are expensive and abusable. Enforce:

- Per-user and per-team rate limits on all agent and orchestration endpoints (request frequency AND token/cost budgets per window).
- Hard per-team spending caps on model API usage with alerts before the cap and graceful degradation at it — one runaway loop or one abusive account must never produce an unbounded bill or starve other tenants.
- Loop and recursion guards in the orchestrator: bounded tool-call depth, bounded retries, timeouts on every model call, circuit breakers per downstream model provider.
- Background analysis (system proving, batch checks) runs under queue-level concurrency limits so a single team cannot monopolize the worker pool.
- Rate-limit and budget events are logged to the data collection system for abuse detection.

_Privilege and isolation._

- The SOL Agent's tools execute with the requesting user's permissions — never elevated/system permissions. Tool-side authorization is enforced in tool code, not assumed from the model.
- Model context is assembled fresh per request and scoped to the requesting team's data only. No cross-tenant content may ever enter a prompt — context assembly goes through the same team-scoping layer as every database query, and this is covered by isolation tests.
- Credentials and secrets never enter model context. Prompt-assembly code must source from the graph and sanitized content stores, never from config or credential stores.

If you are ever uncertain whether something is a security risk: stop, flag it in the MR or to a human, and do not merge. Security uncertainty is always worth the interruption.

---

## 8. Coding Standards

**Python**: ruff + black formatting, full type hints (mypy-clean), Pydantic v2 models at all boundaries, async-first in API paths, no bare excepts, structured logging (no prints).

**TypeScript**: strict mode, eslint + prettier, no `any` at module boundaries, typed API client only (no raw fetch scattered through components), Zustand for cross-component state, components scoped to their feature panel.

**Both**: small focused modules; pure functions for checkers and analyzers (graph in, warnings out — no hidden state); errors carry context; names match the domain language of the graph (entity, relation, source, sync, checker, fingerprint).

**Logging & data events**: every meaningful user/system interaction emits a structured event per the event schema in packages/contracts/. When in doubt, emit the event — the data collection system is a first-class feature, not an afterthought.

---

## 9. Shared Contracts

The interfaces in `packages/contracts/` are the spine of parallel development: the connector interface, the checker interface, the agent tool interface, the telemetry packet format, the entity/relation model, and the event schema.

- Treat contracts as frozen during feature work. Implement against them exactly.
- If a contract is insufficient for your task, stop. Propose the concrete change in-chat (AskUserQuestion with the diff and rationale), get explicit approval, then edit the contract in a DEDICATED commit — never as an unannounced side effect of feature work (ADR-032).
- Every implementation of a contract must pass that contract's shared test suite.

---

## 10. When You Are Unsure

The failure mode that costs this project the most is an agent confidently improvising where design was required. The protocol:

1. Check the governing docs (DECISIONS.md → architecture → API plans → wireflows → directory CLAUDE.md).
2. Check for an existing skill or command covering the situation.
3. If still ambiguous and the ambiguity is architectural, security-relevant, or contract-touching: ask in-chat (AskUserQuestion) — state the question, the options, and your recommendation; the recorded answer is the approval (ADR-032). Record the decision in the completion report.
4. If the ambiguity is small and local (naming, minor UX within a wireflow, internal structure of a module you own): use your judgment, and note the decision in the MR description.

Bias: improvising on locked things is forbidden; improvising on local details is expected. Know which kind of decision you're facing.

---

This file is the baseline. Directory CLAUDE.md files refine it. The specs define the work. The contracts define the boundaries. The tests define correctness. The humans define the architecture. Build accordingly.
