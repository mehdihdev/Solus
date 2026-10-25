# Solus repo state — 2026-10-17

Read-only reconnaissance of `origin/main`. Every answer was checked against code, not docs.

> **Scope note (user, 2026-10-17):** the hardware add UI and cards (Q37, the SPEC five-cards row in Q8, the hardware rows in Q71/Q74) will be redone later. Treat them as current state only, not as gaps to plan against.

## Summary
1. **Main HEAD**: `da9204ff`, 2026-10-12, SOLUSDEV-313. Local `main` == `origin/main`; 84 squash commits on main.
2. **Alembic**: one head, `a31300000001`. The dev DB `solus` is also at that head. `uq_solus_config_subject_live` and `ck_solus_config_subject` are now created by `a26000000003`.
3. **Tests**: the API suite collects 8,489 tests; it was **not run** because it migrates a test DB. Every other suite was run, 7,519 passing in total: companion 344, livebench 712, telemetry lib 72, integrations 1,459, ci 64, desktop vitest 4,547, shared-types 296, env 25. One desktop test file fails to load because of local `node_modules` drift (`@sentry/electron`).
4. **CI has no Python test job**: it was removed in `de1eddd8`. Every Python ratchet (vendor hygiene, `registry.invoke`, never-raises, zero-false-merge, confirmation gate) is unenforced at merge.
5. **Ticket groups present**: 260 (v2 entity-owned config), 248 R1–R5, L1–L5, S1–S5, ST1–ST5, H1–H5, the brain-centric topology, UI + Isaac fix, and 261. **Partial**: I1–I5, because I5 (server-side sim) was never merged.
6. **Gap 1 — no cross-domain substrate**: the checkers and the diagram builder read semantic edges (`drives`/`reads_from`/`powers`) that **no code writes and no route can create**. The fingerprint linker has no production caller. In dev, 0 of 2,832 entities have embeddings and `corpus_chunk` is empty. The "reasoning layer over a unified graph" in root CLAUDE.md §1 has almost no cross-domain edges to reason over.
7. **Gap 2 — Build mode skips the consent card**: in Build mode about 24 write tools auto-run without a consent card (10 Onshape, 6 Isaac, `machine.write_file`, 6 KiCad writes, `code.git_commit`). Root CLAUDE.md §7 says every destructive action needs explicit confirmation. `add_solus_entry` and `bom.add_item` are ungated, so they also run in Guide mode.
8. **Gap 3 — the repo map and spec are wrong**: root CLAUDE.md §3 places code under `reasoning/` and `integrations/<tool>/`; both contain only `.gitkeep`, and all the code is in `packages/api/src/solus_api/`. Four of the directory CLAUDE.md files it lists are absent. `docs/design/SPEC.md` exists but swaps the hotkeys, specifies 5 Add-hardware cards (the code has 3), and its `screens/` folder is missing.
9. **SOL in practice**: every chat turn is routed as GENERAL, so it goes to OpenAI and never to Claude. The whole context is capped at **4,000 tokens**, with `.solus` entries clipped to 500 chars. SOL never reads the workspace focus store. Guide mode can't point at anything: there are 2 authored walkthroughs and 0 screen locators.
10. **Not determined** (listed at the end of this file): desktop launchability, conversation/`data_events` retention, the Onshape double-click-to-allow issue, and the remaining `change-signal-spine` lease rules, among others.

> **Caveats.** Dev-DB row counts include writes from every worktree (the DB is shared). Fork agents produced sections A–J. H2 blocked the Write tool on `main` even for scratchpad paths, so this file was assembled in the scratchpad and copied into `docs/qa/` by the user. H6 rejects markdown containing column-0 `class X` lines for existing symbols. Some model dumps (Q59, Q61) are therefore field lists rather than verbatim class bodies.

## A. Tree and gates

### Q1 — Main HEAD
Status: exists
Where: `origin/main` = local `main` = `da9204ffca020aa84fdfb4d218a4104fba8d9bd0`, 2026-10-12 11:46:49 +0000, "SOLUSDEV-313: ADR-023 clarification — staff limits_override merged per key over plan defaults". 84 commits on main, all squash merges; the big ones are subject-only.
```
da9204ff 2026-10-12 SOLUSDEV-313: ADR-023 clarification — staff limits_override merged per key over plan defaults
5360f2a5 2026-10-07 SOLUSDEV-312: ADR-037 live channels (project, team, user change hints)
5a6ae0bc 2026-09-29 SOLUSDEV-311: accept client.error data events (closed, typed payload)
6b7faa19 2026-09-26 Solusdev 262 livebench robo sol initial            (517 files, +61,956/−7,566)
7aadbb4f 2026-09-26 SOLUSDEV-400: add product showcase motion piece (orb morph, 12 bars @ 118 BPM)
52844231 2026-09-22 SOLUSDEV-260: fix blank desktop window — rename deviceCard.ts to deviceCardRules.ts
09353979 2026-09-18 add design stuff
2ffbf8b8 2026-09-14 Solusdev 261 integration check                     (532 files, +55,863/−6,524)
fb56b607 2026-09-13 SOLUSDEV-300: rebuild the landing page from the Claude Design waitlist mock
de1eddd8 2026-09-12 SOLUSDEV-260: 250-252, robot onboarding + graph + sol initial (694 files, +73,870/−11,012)
1fa93715 2026-09-09 SOLUSDEV-252: amend metadata-extraction contract — S-expression netlist...
3a90ab6f 2026-09-07 SOLUSDEV-249: INTEGRATIONS I2 — local folders as a graph source
02590af8 2026-09-07 SOLUSDEV-244: ADR-034 amendment — root engineering preferences in ~/.solus/preferences.json
4fa1ce86 2026-09-07 SOLUSDEV-248: physical robot node initial          (214 files, +29,427/−510)
d0737491 2026-09-06 SOLUSDEV-242: Home as the cross-project surface — active-team project grid,...
3003d518 2026-09-06 SOLUSDEV-242-test
22ca1688 2026-09-06 SOLUSDEV-240: graph workspace w1
43e8a06e 2026-09-05 SOLUSDEV-241: CORPUS C1 — corpus scope, licensing policy, chunk schema
12d33aea 2026-09-05 SOLUSDEV-234: stop the desktop 429ing itself against the API
6c507dbb 2026-09-04 SOLUSDEV-235: EXT-05 bundle installer + developer mode
54179866 2026-09-03 SOLUSDEV-167: featurescript mcp
37cc91ef 2026-09-01 SOLUSDEV-233: add filter-scoped total to activity feed meta
215b0f5c 2026-08-31 SOLUSDEV-167: governance gate — change-signal spine architecture + tier-1 doc amendments
72a96d15 2026-08-31 SOLUSDEV-165: emit machine-readable connect stages; add cancel + result-returning connect hooks
c4430b2e 2026-08-30 SOLUSDEV-165: (same subject)
0ddce887 2026-08-16 SOLUSDEV-72: local source catalog + packet tap on the stream pump
2a0b9389 2026-08-16 SOLUSDEV-165: (same subject)
f9bf9b8e 2026-08-16 SOLUSDEV-64: retry Onshape 429s with bounded Retry-After backoff
c02bee00 2026-08-16 SOLUSDEV-69: seed every env-sourced SecretStore ref via make seed-secrets
00d967ca 2026-08-15 SOLUSDEV-70: wire the graph screen — entity list, focus-driven inspector
```
Presence judged from tree + migrations + committed completion files, not report prose alone:

| Group | Status | Evidence on main |
|---|---|---|
| 260 consolidation (251/252/250) | present | `de1eddd8`; `hardware/ownership.py`, `operations.py`, `local_sources.py`; migrations `a25100000001`, `a26000000002` (backfill), `a26000000003` (constraints) |
| 248 R1–R5 | present | `4fa1ce86`; `services/physical_robots.py`; migration `8f1c2a7d4e90` (R5) |
| L1–L5 Live Bench | present | `6b7faa19`; openapi `/bench/runs*` (8 ops), `/bench/scene/models*`; `livebench/runs/router.py` |
| S1–S5 SOL | present | S1/S2/S3/S5 via 252 in `de1eddd8` (`orchestration/providers.py` uses `client.responses.create`; `main/hotkeys/index.ts`); S4 via 262 |
| I1–I5 integrations | partial | I1 `43e8a06e`, I2 `3a90ab6f`, I3 `routers/code_environment.py`/`services/code_env.py`, I4 `bridge/previews.py`. **I5 absent** — `COMPLETION_SOLUSDEV-252-kicad-natural-ingestion.md:178`: `SOLUSDEV-252-sim-sources` never merged |
| ST1–ST5 store | present | `widgets/`, `sourcing/`; migrations `d5e6f7a8b9c0`, `f7a8b9c0d1e2`, `f0a1b2c3d4e5` |
| H1–H5 home | present | `d0737491`, `02590af8`; `main/preferencesStore.ts` |
| Brain-centric onboarding (L1–L5/W5/S4) | present | `6b7faa19`; `hardware/host_topology.py`, `presence_topology.py`, `topology_*.py`; migration `a26200000001_brain_topology` |
| UI implementation + Isaac fix | present | `routers/isaac_connection.py`; `HardwareAddPanel.tsx` = Devices found / Search / Describe something new (+ UnassignedParts) |
| Integration check (261) | present | `2ffbf8b8`; migration `a26100000001`; `docs/qa/ACCEPTANCE_SOLUSDEV-261.md` |

Note: 260/261/262 each landed as one subject-only squash; the tree and `docs/qa/` are the only record of what landed.

### Q2 — Working tree
Status: exists
Where: `/home/beeboss/Solus` on `main`; `git status --short` empty.
Note: Ignored-but-present items stepped around:
```
!! .Codex/ (340K; .gitignore:70)   !! .aws_env   !! .claude/settings.local.json
!! .claude/state/  (last_validation.md is STALE — ruff failure from a sibling worktree)
!! .dmypy.json .mypy_cache/ .ruff_cache/ .playwright-mcp/ .venv/ .vscode/
!! .env  .env.mega  (WORKTREES.md says .env.mega retired in 698374c)
!! .solus-dev-credits.json
!! apps/desktop/.env  packages/api/.env  (WORKTREES.md: "no per-package .env files anymore")
!! apps/desktop/out/ apps/desktop/*.tsbuildinfo apps/web/.next/
!! tmp/ (2.1G)   !! integrations/mcp/*/.venv, __pycache__
```

### Q3 — Package layout
Status: exists
Where:
| Dir | Lang | Entry | One line |
|---|---|---|---|
| `packages/api` | Py | `solus_api.main:app`; `worker_main.WorkerSettings` (ARQ, 14 lines); script `stripe-setup` | Entire backend: graph, connectors, checkers, fingerprint, agent, hardware, bench, billing |
| `packages/companion` | Py | `solus_companion/__main__.py` | Customer-machine process; dials out to the API bridge WS, supervises MCP forks |
| `packages/contracts` | Py+TS | `python/`, `typescript/` | Human-owned contracts; **0 tests of its own** |
| `packages/shared-types` | TS | `src/index.ts` | FE↔BE types |
| `apps/desktop` | TS (Electron 39.2.6, React 19.2.1, electron-vite) | `out/main/index.js` | Product UI |
| `apps/web` | Next.js | `app/` | Landing site |
| `libs/solus-telemetry` | C++/MicroPython/Py | `arduino/`, `micropython/`, `python/` | On-device telemetry library |
| `livebench` | Py | `livebench/` | Drivers/plugins, recognition, telemetry, sim |
| `reasoning/{agent,checkers,fingerprint}` | — | — | **`.gitkeep` only** — real code is in `packages/api/src/solus_api/` |
| `integrations/{github,gitlab,kicad,ros}` | — | — | **`.gitkeep` only**; `onshape/` = 5-file panel harness; connectors live in `solus_api/connectors/` |
| `integrations/mcp/*` | Py/Node | `bin/launch` | Vendored forks: altium 495 files, kicad 269, brave 67, code 45, local 35, isaac 34; autocad/solidworks/fusion/machine 2–4-file stubs |
| `scripts/` | sh/Py/mjs | `dev-all.sh`, `dev_ports.py`, `qa_approver.py`, `dev_credits.py`, `seed-provider-keys.py` | Dev tooling |
| `infrastructure/` | sh/Docker | `docker/api.Dockerfile`, `aws/taskdef.json`, `ci/scan-secrets.sh` | Deploy + CI |
| `tests/e2e` | Py | conftest only | Stub |

Import direction:
```
solus_contracts importers: api 27 files · companion 1 · livebench 0 · libs 0
livebench → solus_api: declared dep ("solus-api" in livebench/pyproject), 50+ modules
solus_api → livebench: UNDECLARED, lazy, circular — hardware/topology_proposals.py:116-118
  (livebench.hardware.repo_config, livebench.hardware.topology_extractors, livebench.recognition.firmware)
companion → solus_api: 0 (frames.py mirrors bridge.frames "without importing it")
desktop → packages/api: no code import; hand mirrors (lib/telemetry/packet.ts ↔ graph/codec.py); generated schema.ts from openapi.json; @solus/shared-types bundled into main/preload
```

### Q4 — Alembic
Status: exists
Where: `packages/api/migrations/versions/` (63 files)
```
$ uv run --no-sync alembic heads
a31300000001 (head)
```
Note: One head. Data-only migrations: `a26000000002_hardware_config_backfill` (runs frozen `migrations/hardware_config_backfill.py`), `a26200000001_brain_topology`, `a7c5d2e91f04_byo_paid_tools_backfill`, `b6f242d8e731_solus_graph`, `c7f242e9a842_document_roots`, `c4d5e6f7a8b9_v1_manifest_document`, plus ~10 pure merge revisions. **`uq_solus_config_subject_live` and `ck_solus_config_subject` are now created** in `a26000000003_hardware_config_constraints.py` (and present in the dev DB, see Q22). Every named constraint/index in `models.py` was matched against migration files — none missing (not diffed against a live schema).

### Q5 — Tests
Status: partial
Where: measured 2026-10-17, one process at a time:
| Suite | Collected | Result | Wall |
|---|---|---|---|
| API | **8,489** (collect-only, 3.8 s, no DB needed) | **not run** (needs Postgres, migrates a test DB). Last reported: 8,477 passed / 6 skipped in 28m51s on a 313 branch head, not main (`COMPLETION_REPORT_SOLUSDEV-313.md:94`) | — |
| companion | 344 | 344 passed | 5.7 s |
| livebench | 713 | 712 passed, 1 skipped | 19.7 s |
| contracts (`packages/contracts`) | 0 | — (contract suites live in `packages/api/tests/contracts/`) | — |
| telemetry lib | 72 | 72 passed | 5.3 s |
| integrations | 1,461 | 1,459 passed, 1 skipped, 1 xfailed | 33.5 s |
| infrastructure/ci | 64 | 64 passed | 1.2 s |
| desktop vitest | 446 files | 4,547 passed; 1 file failed to load (`sentrySink.test.ts` can't resolve `@sentry/electron/main` — declared + locked but missing from local node_modules: install drift, not code) | 27.6 s |
| shared-types | 296 | 296 passed | 0.3 s |
| `pnpm test:env` | 25 | 25 passed | 0.2 s |

CI change filter (`.gitlab-ci.yml`): Python jobs on `.gitlab-ci.yml, pyproject.toml, uv.lock, .dockerignore, infrastructure/**, packages/api/**, packages/companion/**, packages/contracts/python/**, livebench/**, libs/**, integrations/**, reasoning/**, scripts/**/*.py`. Node jobs on `.gitlab-ci.yml, package.json, pnpm-lock.yaml, pnpm-workspace.yaml, .npmrc, tsconfig.base.json, eslint.config.mjs, .prettierrc.json, vitest.config.ts, apps/**, packages/shared-types/**, packages/contracts/**, scripts/**`. Jobs: ruff, eslint, mypy (api + companion only), `pnpm typecheck`, `pnpm test`, gitleaks → image build/staging deploy on main.
Note: **CI has no Python test job** — `test:python` removed in `de1eddd8` at the user's request (`infrastructure/ci/README.md:8`). Desktop green apart from install drift; API suite on main: **green (per the user, 2026-10-17; not re-run in this session)**.

### Q6 — Structural tests / ratchets
Status: exists
Where:
| Invariant | File | Asserts | In CI? |
|---|---|---|---|
| Vendor hygiene (API) | `packages/api/tests/test_vendor_hygiene_api.py` (75) | Sweeps `hardware/*.py`, `livebench/*.py` (not `hardware/definitions/`) with `\b(feetech\|dynamixel\|lerobot\|sts3215\|sts3250\|scs0009\|so-?10[01]\|px4\|pixhawk\|odrive\|myactuator\|mavlink\|unitree\|ur5e?\|arduino\|teensy\|esp32\|ch343\|cp210x\|ft232\|pl2303\|xl330\|xm430\|robotis)\b` (i), no allowlist; second test over 7 Isaac connection files | No |
| Vendor hygiene (livebench) | `livebench/tests/lb_vendor_hygiene_test.py` (77) | Same regex over `hardware, recognition, telemetry` + `local.py`; vendor names only in `plugins/` + `definitions/`; shared loop imports no plugin | No |
| Vendor hygiene (desktop) | `apps/desktop/src/renderer/src/features/graph/hardware/vendorHygiene.test.ts` (42) | Same list + `ttyUSB\|ttyACM`, `\.ino\b` over `features/graph/hardware/` (non-recursive), `widgets/livebench/recognition` | Yes |
| Fork hygiene | `integrations/mcp/tests/test_vendor_hygiene.py` (239) | dir name = allowlist server = catalog name; no npx/uvx/pip/python/node launchers; allowlists parse without skips | No |
| Ungated dispatch | `packages/api/tests/test_sol_runtime.py:249` | `.invoke(` in `agent/` only in `runtime.py`, `confirmations.py`, `tools/registry.py` + adapters `isaac_tools.py`, `machine_writes.py`; repo-wide `registry.invoke(` allowed in the first three — **three files, not two** | No |
| Flywheel write unreachable | same file, `test_no_runner_path_reaches_the_flywheel_write` | No runner/tool/context code calls `record_error_solution` | No |
| Never-raises | `test_tool_registry.py` (l.156), `test_never_raises_groups.py` | invoke returns structured failure, incl. ExceptionGroups | No |
| Zero false merges | `test_fingerprint_eval.py:121` + `fixtures/fingerprint_labels.py` | No labelled case merges wrongly | No |
| Toolkb tenancy | `toolkb/test_guard.py`; `contracts/test_tool_knowledge.py:74` | Table rejects customer content | No |
| Dotted names | `test_openai_responses.py:485`; `test_prompt.py:266` | Long dotted names fit the provider cap and round-trip | No |
| Confirmation gate | `test_confirmations.py` (60 tests); `contracts/test_action_gate.py` | Gated tools require approval; diff renders | No |
| Hardcoded models | `test_no_hardcoded_models.py` | No model names outside config; provider SDKs only in adapter | No |
| Stale copy | `apps/desktop/src/renderer/src/staleCopy.test.ts` | Banned strings absent | Yes |
Note: Every Python ratchet is "No" because CI has no Python test job (Q5).

### Q7 — Worktree isolation
Status: partial
Where: `scripts/dev-all.sh` (321), `scripts/dev_ports.py` (79), `docker-compose.dev.yml` (35), `env.example` (202), `docs/WORKTREES.md` (198), `apps/desktop/src/main/companion.ts` (494), `companionEnv.ts`, `packages/companion/src/solus_companion/config.py`
Note: Ports come from the checkout's root `.env` (`VITE_API_BASE_URL`, `VITE_DEV_PORT`; defaults 8000/5173). `dev-all.sh` **refuses rather than kills** on a busy port (lsof → "port N is occupied (PID(s): …) — refusing to start" → bind probe); 5432 reused only if this checkout's own Compose `db` holds it. Compose binds fixed host ports 5432/6379; a second worktree gets its own dev DB only by hand-editing `SOLUS_DATABASE_URL`. Test DB is per-checkout: `solus_test_<sha1(path)[:8]>`. Companion never listens: desktop MAIN spawns it (pidfile `userData/companion.pid`) with `SOLUS_COMPANION_URL` + token; it dials out to `wss://…/api/v1/projects/{id}/bridge` derived from the API base (allowlist `SOLUS_COMPANION_ALLOWED_HOSTS`). pg_dump snapshots: no script/convention; ad hoc (e.g. `/tmp/solus260-snapshots/…dump`, `PHASE0_SOLUSDEV-260.md:43`), run inside the container (host has no pg_dump).

### Q8 — Governing docs
Status: exists
Where: (`tree` not installed — equivalent listing)
```
docs/ api/(25) architecture/(19) CAPABILITIES.md CODEMAPS/{livebench,onshape,repository-context,workspace}.md contracts/(20)
      corpus/{AUTHORING,LICENSING,SCOPE}.md design/SPEC.md env-consolidation.md extensions/(5) integrations/{github,gitlab,onshape}-setup.md
      qa/(256 files) RUNBOOK.md schemas/{cad-purge-requests,corpus-chunk,extensions,hardware-config,source-revisions,sourcing}.md
      superpowers/specs/ ui-reference/(prototype v1–v4 html, directions/, graph-options/, shots/) wireflows/(18) WORKTREES.md
api/: account-hosted API-implementation API artifacts bench-runs bench-scene code-arduino-development code-environment code-git-development corpus document-tree extensions gateway-embeddings hardware isaac-development kicad-development local-folder local-machine-actions onshape-development solus source-revisions sourcing toolkb widget-bundles workspace
architecture/: change-signal-spine code-environment desktop-error-handling development-credits engineering-corpus extensions-runtime hardware-onboarding local-connections local-folders local-machine-actions sol-artifacts sol-context-layers sol-in-tools sol-research solus-folder sol-window source-revisions telemetry-viz-out workspace-navigation
wireflows/: account-hosted activity-feed bom development-credits document-tree extensions-runtime hardware-onboarding home license-capture local-connections project-topbar sol-page sol-window sources-connect-wizard sourcing store widget-canvas workspace
```
`docs/design/SPEC.md` **exists** (207 lines) — a real product spec (introduced `4fa1ce86`, rewritten `6b7faa19`). The `docs/design/screens/` folder it cites is **absent**.

ADRs: 001 graph-centric · 002 Py/FastAPI · 003 Postgres+pgvector · 004 Rust deferred · 005 clean seams · 006 AWS ECS, no k8s · 007 GitLab · 008 Electron/React stack · 009 Supabase auth · 010 SOL orchestrator · 011 data collection · 012 fingerprint heuristics + confirm · 013 autocomplete = checkers · 014 MuJoCo built-in sim · 015 tiers · 016 SOL modes universal · 017 pricing · 018 credits metering · 019 one budget system · 020 orchestration protocol · 021 ticket branching · 022 directory descriptive · 023 three plans · 024 credits ledger · 025 teams/project-as-workspace · 026 multi-model routing · 027 DB & graph conventions · 028 week-0 contracts human-owned · 029 Live Bench VLMs · 030 parse committed Git exports · 031 MCP forks on customer machine · 032 two-tier governance · 033 global tool knowledge · 034 two-layer local state · **035 used twice** (Extensions; MCP third pattern) · 036 engineering corpus · ADR-019/035 Onshape amendments · 037 live channels · 038 Onshape mirror (+ amendment).

Doc claims the code does not meet (verified):
| Doc | Claim | Gap |
|---|---|---|
| Root CLAUDE.md §3 | connectors in `integrations/<tool>/`; reasoning in `reasoning/` | Both `.gitkeep`-only; code is under `packages/api/src/solus_api/` |
| Root CLAUDE.md §3 | directory CLAUDE.md in packages/api, integrations, reasoning, livebench, infrastructure | Only root, `apps/desktop/`, `integrations/mcp/` have one |
| Root CLAUDE.md §4/§6 | CI runs tests; contract suites pass in CI | No Python test job since `de1eddd8` |
| SPEC.md §5 | double-tap Ctrl toggles mode; Ctrl+Space spawns the panel | Reversed: `hotkeys/index.ts:122` double-tap summons; Ctrl+Space is `onToggleMode` |
| SPEC.md §3 | five Add→Hardware cards | Three sections + UnassignedParts (`HardwareAddPanel.tsx`) |
| SPEC.md §3 | one lifecycle ending in "live" | BOM `…installed, retired` (`widgets/bom/rows.py:42`); hardware `…installed, live` (`schema.ts:4472`) |
| SPEC.md header | screens in `docs/design/screens/` | Folder absent |
| apps/desktop/CLAUDE.md | `components/ui` has `SolOrb` | Not in `apps/desktop/src` |
| WORKTREES.md | no per-package `.env`; `.env.mega` retired | All three exist locally |
| ADR-034 | repo `.solus/` holds `project.toml` + `parts/*.toml` | Only `project.toml` is read (`connectors/code_host.py:84-110`); the user-facing `.solus` is server-side `solus_entries` |
| `contracts/action_gate.py:17` | park/approve flow "not yet on main" | `agent/confirmations.py` + `gate_tool_call` are on main (from Q76) |
| `agent/tools/solus_entry.py` docstring | auto error filing is "a later ticket" | Live for 18 tools (Q26) |
| Checkers / diagram builder (code-level claim) | read `drives`/`reads_from`/`powers` edges | No code writes them; no route creates edges (Q10) |
| DECISIONS.md | unique ADR numbers | ADR-035 twice |
| docker-compose comment | Redis "not yet wired" | Stale; ARQ worker exists |

Clean mechanical checks: every `METHOD /path` in `docs/api/*.md` matches `openapi.json` (233 ops) except routes the docs mark deferred (`/graph/query`, `/impact`, `/observations/*`, `/hardware/robots/`, Onshape upstream `GET /documents/{d}`). `openapi.json` vs the running app: **not determined** (not regenerated). Backticked file refs resolve except runtime files and five KiCad dev filenames (`kicad-development.md:294-300`). Only `sol-artifacts.md`, `sol-context-layers.md` carry "IMPLEMENTED", `solus-folder.md` "partially implemented"; the other 16 architecture docs have no status line.


## B. Graph and data model

> Dev DB caveat: every worktree shares the `solus` dev DB on :5432 (`alembic_version` = `a31300000001`, main's head), so row counts include whatever any branch wrote. Totals: 2,832 entity rows (503 soft-deleted), 19 projects, 0 embedded.

### Q9 — `graph_entity`
Status: exists
Where: `packages/api/src/solus_api/models.py` (1849) — `GraphEntity` L708–788, `Domain` L144–162
Note: **`kind` (`String(64)`) and `origin` (`String(16)`) are free strings, not enums**; only `domain` is an enum. `origin` values in dev: manual 1395, connector 899, recognition 19, system 15, fingerprint 1.
```python
class GraphEntity(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):  # id uuid7, created_at, updated_at, deleted_at
    __tablename__ = "graph_entity"
    # indexes: ix_graph_entity_embedding (HNSW cosine), uq_graph_entity_source_ref (source_id, external_ref) partial-live,
    #   ix_graph_entity_project_kind, uq_graph_entity_project_canonical_key, uq_graph_entity_workspace_singleton,
    #   uq_graph_entity_workspace_widget_slug ((attrs->>'slug'))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)  # free string (see Domain docstring)
    domain: Mapped[Domain] = mapped_column(_enum_column(Domain))
    name: Mapped[str] = mapped_column(String(512))
    canonical_part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("graph_entity.id", ondelete="SET NULL"), default=None, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), default=None, index=True)
    source_connector: Mapped[str | None] = mapped_column(String(64), default=None)
    external_ref: Mapped[str | None] = mapped_column(String(512), default=None)  # id in source tool
    canonical_key: Mapped[str | None] = mapped_column(String(64), default=None)
    origin: Mapped[str] = mapped_column(String(16), default="connector")
    version: Mapped[int] = mapped_column(Integer, default=1)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    modality_hints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), default=None)

class Domain(enum.StrEnum):
    CODE = "code"; ELECTRICAL = "electrical"; MECHANICAL = "mechanical"; SIMULATION = "simulation"
    RUNTIME = "runtime"; PROJECT = "project"  # SOLUSDEV-240
    WORKSPACE = "workspace"  # SOLUSDEV-246 ST2; excluded from SOL context, checkers, fingerprinting
```
(Columns condensed onto single lines; `class` headers reproduced from the source.)
Live rows by kind|domain (dev DB):
```
part|mechanical 1423 · robot_category|project 161 · hardware_config|project 149 · code_file|code 136 · part|project 123
solus_section|project 95 · net|electrical 30 · physical_robot|project 23 · code_module|code 22 · solus_config|project 19
hardware_brain|electrical 19 · hardware_bus|electrical 18 · document|project 13 · motor|runtime 12 · cad_document|mechanical 12
robot_link|simulation 8 · robot|runtime 7 · robot_joint|simulation 6 · kicad_project|electrical 6 · component|electrical 4
bench_scene_model|simulation 3 · solus:workspace 3 · arduino_sketch|code 3 · solus:live_bench 3 · bench_run|project 3
bench_scene_cad_import|simulation 3 · local_folder|code 2 · hardware_presence_plan|runtime 2 · hardware_wiring_proposal|runtime 2
python_code|code 2 · assembly|mechanical 2 · code_repo|code 2 · solus:widget 2 · solus_error|project 2 · motor|mechanical 1
sensor|mechanical 1 · solus_note|project 1 · battery|mechanical 1 · document|mechanical 1 · simulation_object 1 · sensor|simulation 1
canonical_part|electrical 1 · simulation_model 1
```

### Q10 — `graph_edge` and edge types
Status: exists (structural); semantic edges partial (read by checkers, written by no code)
Where: `models.py` `GraphEdge` L791–820
Note: `relation_type` is a free `String(64)`. **No API route creates an edge** (`routers/entities.py` only has `GET /entities/{id}/relations`, `GET /graph`, `GET /relations`); every edge comes from a connector sync or a service. Checkers read `drives`/`reads_from`/`powers` but nothing in `packages/` writes them — the single `drives` and `reads_from` rows in dev are tagged `qa_fixture`. None of `commands, wires, mounts, limits, depends_on, hosts, measured_by, observed, fixed_by, verified_by, mates_with` is written anywhere.
```python
class GraphEdge(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):  # uq_graph_edge_source_edge (source_id, src_id, dst_id, relation_type) partial-live
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), default=None, index=True)
    src_id / dst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_entity.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(64))  # free string
    domain_pair: Mapped[str] = mapped_column(String(64))  # e.g. "code<->electrical"
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    origin: Mapped[str] = mapped_column(String(16), default="connector")
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
```
| edge type | writers | readers | dev rows |
|---|---|---|---|
| contains | github.py:346, gitlab.py:321, document_graph.py:23, local_folder.py:541 (via runtime.py:283); hardware/ownership.py:138, store.py:498,643, physical_robots.py:194, simulation_models.py:96, solus_graph.py:182, sourcing/service.py:349, widgets/graph_nodes.py:179 | Navigator (nodeTypes.ts:16), topologyProjection.ts, robot sidebar, accountAnchors.ts, hardware/runtime.py, ownership.py, cad_suggestions.py, solus_graph.py:146 | 1072 |
| part_of | connectors/mechanical.py:221; livebench recognition | Navigator (nodeTypes.ts:17), scene/cad_import.py:79,98, sourcing/service.py:90 | 1062 |
| references | solus_graph.py, scene/cad_import.py:216,340, cad_refresh.py:420, scene/service.py:222 | solus_graph.py:146; Navigator cross-links | 26 |
| configures | hardware/store.py:210 | hardware config resolution | 149 |
| binds | hardware/bindings.py:87 | hardware/runtime.py:83, store.py:365 | 15 |
| same_as | linking/linker.py:350 | Impact (impact/engine.py:45), widgets/bom/rows.py:37, cad_suggestions.py | 2 |
| connected_to | connectors/eda.py:256 (KiCad) | checkers/rail_current.py:55, presence_topology.py:83, agent/diagram/build.py | 48 |
| requires | local_folder.py:543 | Navigator (nodeTypes.ts:39) | 0 |
| clone_of | services/local_links.py:134 | not determined | 0 |
| hardware_connected_to / hardware_topology_member | hardware/topology.py:232, topology_acceptance.py:173, host_topology.py:395, migration a26200000001 | topology.py:83,256, bindings.py:138, livebench/focus_scope.py:52 | 121 / 19 |
| hardware_evidence_for | topology.py (EVIDENCE_RELATION) | topology.py:256 | 0 |
| presence_prepared_for | hardware/presence.py:188 | presence | 4 |
| wiring_proposed_for | presence_topology.py:298 | presence | 2 |
| deployment_for_target | companion_deployment.py:151 | not determined | 0 |
| cad_visual_for | scene/router.py:197 | scene/router.py:185 | 0 |
| drives / reads_from / powers | **none** | checkers/attributes.py:57-59, rail_current.py:48,60, diagram/build.py:31 | 1/1/0 (fixtures) |

### Q11 — Edge evidence
Status: partial
Where: `models.py` L791–820; `hardware/topology_acceptance.py` L166–186; `hardware/links.py` L283–326; `hardware/hardware_router.py` L890–918
Note: Columns give `confidence` (default 1.0), `origin`, `source_id`, `domain_pair`. `domain_pair` is inconsistent: `x<->y` everywhere except presence code, which writes `runtime:runtime`. No `created_by`, no direction semantics beyond src→dst, no 3×3 matrix cell. `attrs` keys actually written: `binds` {address, config_version, device_ref, enabled, protocol}; `connected_to` {net, pins}; `contains` {section}; `hardware_*` {address, evidence, managed_by, protocol, robot_id; topology acceptance also reviewed_by, proposal_digest, row}; `part_of` {placement}; `references` {section}; `same_as` {canonical_id, matched}. `hardware_suggestions` rows are pre-edges: `decide_suggestion` only changes status and supersedes siblings; the router does the edge work (accepted device suggestion → bind → `binds`/config; accepted CAD part suggestion → `attach_existing_parts` → `contains`).

### Q12 — Fingerprint seam
Status: partial (matcher + ingest exist; linking pipeline has no production caller)
Where: `fingerprint/contract.py` (133), `matcher.py` (468), `ingest.py` (684), `matching.yaml` (121), `linking/linker.py` (448). Tests: `test_fingerprint_eval.py` (259, zero-false-merge gate), `_contract` (108), `_hardware_modalities` (73), `_labels` (95).
Note: `ModalityMatch.source_ref: SourceRef` ✓. **`EntityOut.source_id` does not exist — the field is `EntityOut.source_key`** (`connectors/contracts.py:49`, `solus_contracts/connector.py:63`). `EntityOut.modality_hints` ✓. CTR-08 modalities are declared but unscored (matcher routes them to `unmatched`). `scan_project` / `link_from_fingerprint` are called only from tests; outside tests fingerprint code is used only by `livebench/persist.py` (`ingest_output`) and `cad_suggestions.py` (a constant). LLM escalation, embedding writes and vision default off (`core/config.py` L234–244).
Modality: part_number, datasheet, schematic_symbol, cad_model, photo, bus_enumeration, firmware_symbol, telemetry_channel.
Thresholds: matched 0.80, low_confidence 0.50. Weights: exact_mpn 0.95, base_known_suffix 0.90, specific_symbol 0.85, generic_symbol 0.05, datasheet 0.55, photo 0.55, corroboration +0.03; penalties package/footprint 0.10, manufacturer 0.05; LLM cap 0.70.

### Q13 — Canvas rendering
Status: exists
Where: `features/graph/navigation/`: GraphNavigator.tsx 270, graphIndex.ts 132, layout.ts 96, GraphLinks.tsx 173, GraphCard.tsx 327, useGraphNavigation.ts 386, nodeTypes.ts 48
Note: Containment tree (from `contains` out-edges + `part_of` in-edges) shown one level at a time. Saved positions win, else a golden-angle spiral around the parent with overlap rejection; no force solver; fixed 280×250 cards. `MAX_VISIBLE_NODES = 24` per page, paginated. Non-tree edges are projected onto the nearest visible ancestor, grouped per card pair, drawn as curved SVG paths labelled "N links · types" (distinct style when cross-domain), max 64 drawn, with a paginated list of real endpoints. No layout library (`three` is installed, used only by Live Bench).

### Q14 — Semantic zoom + drag
Status: exists
Where: useGraphNavigation.ts L93–129, GraphCard.tsx L33–138, GraphNavigator.tsx L256–269, useWorkspaceLayout.ts (326), `routers/workspace_layout.py` (43, GET/PUT), `WorkspaceLayout` model L444–461, `robots/topologyProjection.ts` (133), `useSolusNodes.tsx` (199), `SolusNodeContent.tsx` (146)
Note: Wheel up over a card with children enters it; wheel down goes to the parent. Children = containment edges for every type, except `local_folder`/`local_clone` which also show `requires` → `python_requirement`. Free drag exists; positions persist in one project-wide `workspace_layouts.positions` JSONB. Physical Robots: `TopologyProjection` hides the seven `robot_category` nodes and shows **brain → bus → device** via synthetic `contains` edges. `.solus` always sorts first; sections render via `useSolusNodes`/`SolusNodeContent`.

### Q15 — Search / index
Status: partial
Where: `routers/entities.py` L107–112, `rag/retrieval.py` (332), `corpus/retrieval.py`, `orchestration/embeddings.py` (311), `main.py` L440–452, `sol/mentionToken.ts` (68), `useMentionPicker.ts` (154), `agent/reason.py` L86–102
Note: Entity search = ILIKE on name, external_ref, `attrs.path`; no tsvector column, no GIN/trigram index (retrieval builds a text index on the fly). pgvector + HNSW on `graph_entity`, `error_solution`, `tool_docs` — **0/2,832 entities embedded**. Embed seam still unmetered (`allow_unmetered=True` at `main.py:449`, `corpus/ingest.py:310`). Composer: `@` opens an entity picker, ids sent as `mentions`; **no `/` commands**. GitHub/GitLab emit per-file `code_file` + per-directory `code_module`; local folders emit only project-level entities. No symbol/import index anywhere.

### Q16 — Focus store
Status: exists
Where: `workspace/focusStore.ts` (194), `useSharedFocus.ts` (57), `graph/workspaceFocus.ts` (41)
Note: Zustand: `focusedEntityId`, `path` (breadcrumb recording the relation per step), `depth`, neighbourhood cache per (project, entity, depth). `clearProject()` on project switch/sign-out; `reconcileWorkspaceFocus` rebuilds the path after a graph change or clears if the entity is gone. Subscribers: WorkspaceScreen, NodeSidebar, SolusSidebar, useSolusNodes, BenchScreen, WidgetHost, WorkspaceShell, projectSwitch, extension bridge. **Not subscribed: SOL (no hits in `features/sol`) and the Add panel.**

### Q17 — Machine and user nodes
Status: partial
Where: `hardware/host_topology.py` (408), `schemas.py` L229–239 (`LocalFolderLink`), desktop `main/index.ts` L170–181, `models.py` Membership L374–391, ProjectMembership L429–441
Note: No user or machine entity kind; closest is `hardware_brain` with `brain_kind="host"`. "Which machine" = `~/.solus/companion_id` + hostname, read in desktop MAIN, sent only when a local folder is linked; OS/arch detected but never stored in the graph. Members: team-level `memberships` (owner/admin/member/viewer) + `project_memberships` (no role column).

### Q18 — Events
Status: exists
Where: `routers/live.py` (369), `graph/live.py` (404), `graph/live_publisher.py` (486), `solus_contracts/live_events.py` (241), `useWorkspaceEvents.ts` (151), `live/reconnect.ts` (149)
Note: One `LiveHub` over Redis channels `solus:live:{project|team|user}:{id}`; streams `/projects/{id}/events` and `/users/me/events`. `graph/live.py` emits `graph.changed`, `hardware.devices_changed`; `live_publisher.py` emits the rest after commit. Access re-checked every 30 s and on revocation; keepalive 25 s. Desktop reconnects via `runReconnectingStream` (403/404 ends it). `routers/events.py` is client data-event intake, not SSE.
Frame types — project: `graph.changed, hardware.devices_changed, layout.changed, sources.changed, project.updated, job.updated, access.revoked, ready`. Account: `team.updated, team.members_changed, team.invites_changed, team.projects_changed, team.activity, notification.created, membership.changed, access.revoked, ready`.


## C. `.solus`

### Q19 — Sections today
Status: partial
Where: `packages/api/src/solus_api/models.py` (1849) :933; labels in `services/solus_graph.py` (227) and `apps/desktop/src/renderer/src/features/graph/useSolusConfig.ts` (111)
```python
class SolusSection(enum.StrEnum):
    """The five sections of a project's `.solus` (SOLUSDEV-240)."""

    HARDWARE = "hardware"
    DETAILS = "details"
    ERRORS = "errors"
    DOCS = "docs"
    CODE = "code"
```
Display names (API + desktop): hardware = "Hardware configs", details = "Project details", errors = "Error logging", docs = "Documentation", code = "Code environment".

| Asked-for section | Status |
|---|---|
| goals | absent |
| constraints | absent |
| documentation | exists (`docs`) |
| errors / error logging | exists (`errors`) |
| environment / code environment | exists (`code`) |
| hardware configs | exists (`hardware`) |
| project details | exists (`details`) |
| members | absent |
| history | absent |

Note: Five fixed sections. Dev DB live rows: hardware/config 149, hardware/artifact 2, docs/artifact 10, details/text 1, details/artifact 1, errors/sol 2; no `code` entries.

### Q20 — `SolusEntry`
Status: exists
Where: `models.py` :943–1001; limits `services/solus_config.py` (301) :46–47
```python
class SolusEntryKind(enum.StrEnum):
    TEXT = "text"  # typed by a person
    ARTIFACT = "artifact"  # an imported file — a `document` graph node
    SOL = "sol"  # filed by SOL via `add_solus_entry`
    CONFIG = "config"  # a Physical Robot's HardwareConfig (ADR-034 amendment 2026-09-06)

class SolusEntry(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "solus_entries"
    __table_args__ = (
        Index("ix_solus_entries_project_section", "project_id", "section"),
        Index(
            "uq_solus_config_subject_live",
            "project_id",
            "configured_entity_id",
            unique=True,
            postgresql_where=text("kind = 'config' AND deleted_at IS NULL"),
        ),
        CheckConstraint(
            "config_version >= 0 AND (kind = 'config' OR "
            "(configured_entity_id IS NULL AND config_version = 0))",
            name="ck_solus_config_subject",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[SolusSection] = mapped_column(_enum_column(SolusSection))
    kind: Mapped[SolusEntryKind] = mapped_column(_enum_column(SolusEntryKind))
    # TEXT/SOL: the note. ARTIFACT: the display name of the file.
    text: Mapped[str | None] = mapped_column(Text, default=None)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), default=None
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="SET NULL"), default=None
    )
    author: Mapped[str] = mapped_column(String(16), default="user")  # "user" | "sol"
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    configured_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="RESTRICT"), default=None
    )
    config_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
```
Note: Soft delete via `deleted_at`. Author = `author` ("user"/"sol") + `created_by`; no per-entry provenance column (only CONFIG payloads carry a field-level `provenance` map). Limits: 4000 chars/entry, 500 live entries/section. Only `hardware` (`EntityHardwareConfig`) and `code` (`CodeEnvironment`) accept CONFIG payloads; others → 422.

### Q21 — `SolusGraph`
Status: exists
Where: `services/solus_graph.py` (227); identity backfill `migrations/versions/b6f242d8e731_solusdev_242_solus_graph.py` (152, raw-SQL `INSERT INTO graph_entity` data migration); table `b7e2d4a9c1f0_solusdev_240_solus_config.py` (74)
Note: `ensure` locks the project row (`FOR UPDATE`) then creates/repairs one `solus_config` root (".solus"), five `solus_section` nodes, and one node per live entry (kind `document` | `hardware_config` | `solus_error` (errors) | `solus_note` (everything else, incl. code environments)); all `domain=project, origin=manual`. Edges: `contains` (root→section, section→entry) and `references` (root→document), `domain_pair="project<->project"`, `attrs.section`. Text is not duplicated as graph facts — node name is a 120-char preview; full text stays in `solus_entries.text`.

### Q22 — Hardware config state on main
Status: exists (entity-owned v2 + v1 adapters)
Where: `hardware/config.py` (382), `store.py` (699), `runtime.py` (149), `migration.py` (107), `ownership.py` (152), `operations.py` (159), `bindings.py` (187), `hardware_router.py` (1110), `services/physical_robots.py` (294); migrations `a25100000001`, `a26000000002` (41) → `migrations/hardware_config_backfill.py` (442), `a26000000003` (32)
Note: One `EntityHardwareConfig` (schema 2) per physical subject in a CONFIG row keyed by `configured_entity_id`; v1 is adapter-only (`resolve_runtime_config` builds the v1 view; `put_config` = `split_legacy_document` → `put_entity_config` per subject); a stored v1 payload → 409 `config_upgrade_required`. **Owner-key collision looks fixed (read, not run)**: `resolve_runtime_config` reads the owner's stored `identity`/`protocol`/`bus_map` and excludes the owner from `parts`; `split_legacy_document` writes them back onto the owner; `_preserve_owner_component` keeps v2-only fields and swaps only firmware; `_preserve_part_connection` keeps children's connections; any disabled `binds` edge → 409 rather than saving a filtered `bus_map`. Backfill doubles as preflight (raises on ambiguous/cross-project rows; downgrade refuses once v2 rows exist). `a26000000003` creates **both constraints, present in the dev DB** (alembic `a31300000001`). Tests: `test_hardware_data_migration.py`, `test_hardware_runtime_roundtrip.py`, `test_hardware_roundtrip_regression.py`. `GET /robots/{id}/config` neither writes nor locks. **`PUT /robots/{id}/config` takes no If-Match** (body `{config}`) → last-writer-wins; `PUT /entities/{id}/config` requires If-Match. `disable_part_bindings` called on robot removal (`physical_robots.py:278–280`) and re-parenting (`ownership.py:150`).

### Q23 — Machine-local split
Status: exists
Where: `apps/desktop/src/main/hardwareLocalState.ts` (223), `hardwareSources.ts` (437), `solus_contracts/hardware_local_state.py` (97), `shared-types/src/hardware-local-state.ts` (141), `api/.../hardware/local_sources.py` (141), `HardwareSourcesPanel.tsx` (303)
Note: A3 is built. Desktop MAIN writes `~/.solus/projects/<pid>/hardware.json` per user: `sources` (absolute path + content hash; shared data refers only to `source:<uuid>`) and `bindings` (last-seen port hint). Renderer calls IPC `hardware:sources:list|pick|recheck` (`main/index.ts:259–263`); `HardwareSourcesPanel` mounted in `HardwareAddPanel`, `HardwareConfigPanel`, `ExtractionReviewCard`. API reads the file only for an authenticated local runner (`LocalHardwareSources.for_local_runner`). Machine-local: source paths/hashes, last tty, projects registry, SOL chat cache, live (unstored) code probe. Shared: v2 configs (portable `kind:binding` identity only; `last_seen_path` stripped), graph, `.solus`.

### Q24 — User-level `~/.solus`
Status: exists
Where:
| File | Writer | Purpose |
|---|---|---|
| `~/.solus/projects.json` | `main/localState.ts` (376) | project→working-copy registry |
| `~/.solus/preferences.json` | `main/preferencesStore.ts` (139) | engineering preferences: `freeText` (≤2400) + `codeStyle`, `mechanical`, `electrical`, `documentation`, `unitsStandards` (≤800 each) |
| `~/.solus/config.json` (`sol` key) | `main/solSettings.ts` (173) | SOL window/hotkey settings |
| `~/.solus/companion_id` | `main/machineIdentity.ts` (103) | companion instance id |
| `~/.solus/extensions/index.json` + bundles | `main/extensions/extensionIndex.ts` (199) | installed extensions |
| `~/.solus/projects/<pid>/hardware.json` | `main/hardwareLocalState.ts` | Q23 |
| `~/.solus/projects/<pid>/sol/` | `main/solChatCache.ts` (237) | SOL chat cache |
| `<userData>/companion.pid` | `main/companion.ts:165` | pid file |

Note: **SOL reads `preferences.json` on every turn** (attached by desktop, re-validated by `agent/preferences.py`, rendered into the system prompt `agent/runtime.py:668–673, 990–1031`) — the "claude.md equivalent" exists. Separate server-side `custom_instruction` (migration `a7d3f9c41e88`). No per-user mirror (`members/<user>/`) inside a project.

### Q25 — Code environment
Status: partial
Where: `services/code_env.py` (165), `routers/code_environment.py` (131), `agent/tools/environment.py` (92), `checkers/environment.py`, `connectors/local_folder.py` (658), `integrations/mcp/local/solus/deps.py` (287), `integrations/mcp/code/solus/probe.py` (209), `CodeEnvironmentRow.tsx` (104), `CodeEnvironmentModal.tsx` (96)
Note: I3 on main. Parsed: `requirements*.txt`, `pyproject.toml`, `environment.yml` → `python_requirement` nodes + `requires` edges; **no** `package.json`/`Dockerfile`/`devcontainer.json`/`pixi.toml` parser. Live probe `code.probe_environment`: Python interpreters, workspace venv + pip/uv list, conda envs, `uv`; no docker/ROS detection. `propose_environments` proposes one env per conflicting file. Per-machine record: `code` CONFIG `CodeEnvironment` (type, interpreter, version, packages ≤500, os/arch, provenance), written only by gated `link_environment`; dev DB has none; probe result itself not stored.

### Q26 — Error entries
Status: exists (auto-filer; no dedupe)
Where: `agent/errors_filing.py` (235), called from `agent/runtime.py:53` and `agent/confirmations.py:42`
Note: Writers: Workspace UI, ungated `add_solus_entry`, `read_document.py:430`, auto-filer `file_tool_error`. Auto-filer fires on a `files_errors` tool's `ok=False` / non-zero exit / timeout — 18 tools: code MCP (create_environment, install, run, test, git_commit, git_push, arduino_prepare, arduino_compile, arduino_upload), isaac MCP (start, stop, load_model, set_joint_limits, set_sensor_pose, run_routine), machine MCP (open_in_tool, write_file), in-process `machine_writes`. Not filed: checker findings, bench runs. Shape (TEXT/`sol`, redacted, ≤4000 chars):
```
Tool failure: <tool>
When: <iso>
Entity: <ids or ->
Command: <redacted args ≤1500>
Executed argv: <redacted ≤1500>
Error [<code>]: <message ≤1500>
Filed automatically by SOL — edit or delete this note if it is wrong.
```
No dedupe, no count field.

### Q27 — History
Status: partial
Where: `models.py`: `conversations`/`conversation_turns` (:1496/:1517), `tool_confirmations`, `hardware_operations`, `hardware_suggestions` (:1029), `data_events` (:1426), `activities`, `syncs`, `source_revisions`; `livebench/runs/store.py` (164)
Note: SOL sessions (append-only turns with tool envelope + sol_mode), tool approvals, reviewed hardware writes, link suggestions, ADR-011 event log, bench runs as `bench_run` entities (`origin=system`) whose retained artifacts are filed into `docs`. **No config history** — payload overwritten in place, `config_version` bumped. Artifacts TTL-swept unless `retained`. Retention of conversations and `data_events`: **not determined**.

### Q28 — Goals / constraints
Status: absent
Where: —
Note: Nearest is free text in `details`. No checker reads `solus_entries`. `.solus` text reaches SOL only as data in the `project_solus` context layer (`agent/context.py`, newest first, capped per entry).

### Q29 — SOL writes to `.solus`
Status: exists
Where: `agent/tools/solus_entry.py` (86), `agent/tools/solus_tools.py` (546)
Note: Ungated `add_solus_entry` appends text to any of the five sections (project/user bound by closure). Gated (consent sentence + before/after preview re-run at decision time): `edit_solus_entry`, `delete_solus_entry`, `set_hardware_config_field`, `link_environment` (only when a bridge fetch exists). `set_hardware_config_field` now uses v2: resolves the path to one subject (part `component.*`, robot `component.firmware.*`, or robot's own field), sets one leaf with `sol` provenance, `put_entity_config(expected_version)`, requires matching preview revision (shows field before/after and config version N→N+1). Whole-config wipe fixed; subject with no config → 404.


## D. Onboarding and hardware

### Q30 — Physical Robot structure as built
Status: partial
Where: `packages/api/src/solus_api/services/physical_robots.py` (294); brain/bus overlay: `hardware/topology.py` (406), `hardware/host_topology.py` (408), `hardware/topology_proposals.py` (280), `hardware/topology_acceptance.py` (199), `hardware/topology_observations.py` (273), `hardware/topology_evidence.py` (165); UI `features/graph/robots/RobotTopologyGraph.tsx` (243, mounted from `WorkspaceScreen.tsx:228`)
Note: Ownership is still robot → seven `robot_category` children (`contains` edges) → parts. `attrs` placeholders on the root: `{"hardware_config_ref": None, "transport_refs": None}`; categories carry `{"robot_id", "category"}`. Brain-centric work landed as an **additive overlay** (`MARKER = "hardware_topology_v1"`, "never grants transport permissions"): `sync_topology` derives `hardware_brain` (from `config.identity.device_ref`) and `hardware_bus` (one per `bus_map` protocol) entities, linked by `hardware_connected_to` / `hardware_topology_member` edges plus `hardware_evidence` entities via `hardware_evidence_for`. `TopologyNode.role ∈ {brain,bus,device,part}`, `brain_kind ∈ {host,mcu,onboard}`. A host brain + "USB" bus is added by user-confirmed `topology/host/{propose,confirm}`.

```python
ROBOT_CATEGORIES = {
    "sensors": "Sensors",
    "actuators": "Actuators / motors",
    "controllers": "Controllers",
    "end_effectors": "End effectors",
    "power": "Power",
    "structure": "Structure",
    "wiring": "Wiring",
}
```
Creation callers of `PhysicalRobotService.create` (five sites, not three):

| Caller | Line |
|---|---|
| `routers/entities.py` (POST entity, `type: physical_robot`) | 171 |
| `hardware/operations.py` (reviewed hardware op) | 115 |
| `hardware/library_router.py` (platform import) | 194 |
| `hardware/detect.py` (detected confirm, new robot) | 741 |
| `hardware/detect.py` (second confirm path) | 797 |

### Q31 — Registries
Status: exists
Where: `livebench/src/livebench/hardware/registries.py` (39), `plugins/__init__.py` (60); see table
Note: Registries are built once per process (`functools.cache`). Built-in transports register first, then every plugin in `PLUGIN_MODULES`. A plugin whose import fails is skipped with an info log. No MHS reader exists anywhere. "MHS" shows up only in `docs/design/SPEC.md:107` and the 248 completion report. `definitions/vendor/` is the intended seam, and it is empty.

```python
PLUGIN_MODULES: Final[tuple[str, ...]] = (
    "livebench.plugins.lb06",
    "livebench.plugins.jsonlines",
    "livebench.plugins.raw",
    "livebench.plugins.feetech",
    "livebench.plugins.dynamixel",
    "livebench.plugins.odrive",
    "livebench.plugins.mavlink",
    "livebench.plugins.lerobot",
    "livebench.plugins.arduino",
)
```
Registry members (from the source, not from running it):

| Registry | Members |
|---|---|
| TransportRegistry | `usb_serial` (`hardware/usb_serial.py`), `usb_can` (`usb_can.py`), `wifi` UDP (`network.py`, also re-registered by mavlink if absent), `ble` + `bt_classic` (`bluetooth.py`). The transport-kind enum (`hardware/config.py:53`) has the values usb_serial, usb_can, ble, bt_classic, wifi, ethernet, ros2; **`ethernet` and `ros2` have no registered transport** |
| DriverRegistry | `lb06`, `json-lines`, `raw-lines`, `feetech-sts`, `dynamixel-2`, `odrive-can`, `mavlink` |
| InterrogatorRegistry | `serial-framing` (lb06), `feetech-bus`, `dynamixel-2`, `odrive-can`, `mavlink-heartbeat` |
| RepoParserRegistry | `generic-structured` (built-in, `with_generic`), `lerobot`, `sketch-print-order` (arduino) |

| Plugin | Provides | Lines (all files) |
|---|---|---|
| lb06 | driver `lb06`, interrogator `serial-framing` (listen, conf ≤0.30) | 17+91+123+81 = 312 |
| jsonlines | driver `json-lines` | 14+24 = 38 |
| raw | driver `raw-lines` | 14+131 = 145 |
| feetech | driver `feetech-sts`, interrogator `feetech-bus` (ping sweep ids 1–12), codec, definitions | 18+195+76+277+104 = 670 |
| dynamixel | driver `dynamixel-2`, interrogator (one Protocol 2.0 broadcast ping) | 21+153+48+185+76 = 483 |
| odrive | driver `odrive-can`, interrogator (CAN listen for heartbeats, conf 0.92) | 22+69+50+125+89 = 355 |
| mavlink | driver `mavlink`, interrogator `mavlink-heartbeat` (listen), hand-rolled codec, UDP transport | 23+140+93+183+107 = 546 |
| lerobot | repo parser `lerobot` (AST over Robot/Teleoperator classes + HF calibration JSON) | 16+342 = 358 |
| arduino | repo parser `sketch-print-order`; also `arduino_flash.py` (FlashRunner, not registered), `presence.py`/`presence_provider.py`/`wiring.py` (presence firmware) | 17+80+146+159+266+66 = 734 |

### Q32 — Topology sources
Status: partial
Where: interrogators above; `livebench/hardware/repo_config.py` (499); `plugins/lerobot/lerobot_parser.py` (342); `livebench/recognition/firmware.py` (408); `livebench/hardware/topology_extractors.py` (176); `hardware/topology_proposals.py` (280); `hardware/topology_observations.py` (273)
Note: What is wired today:
- **Broadcast ping:** Dynamixel 2.0 only. Feetech uses a unicast ping sweep over ids 1–12.
- **Listen-only:** ODrive CAN heartbeats, MAVLink HEARTBEAT, and serial-framing stream shape.
- **Repo-config parsing:** the generic YAML/JSON/TOML `motors`/`parts` shape parser, the lerobot AST reader, and the Arduino sketch print-order reader.
- **Firmware symbols, from source only:** tree-sitter over `.ino/.cpp/.c/.h/.hpp` and MicroPython. It finds attach calls, pin/motor constants, `bus_begin`, `analog_read` and includes, as `firmware_symbol` evidence at 0.55. It is reachable through the topology `extraction` propose/confirm routes. No `.hex`/binary reading exists.

Onboard Linux and schematic: `onboard_topology()` (accepts `ros2_nodes`, `ros2_topics`, `usb`, `tty`, `vendor` observations) and `schematic_topology()` exist, but **no production caller exists** (only `tests/test_topology_observations.py` and `livebench/tests/lb_three_machines_test.py`). No SSH collection of `ros2 node list` or `lsusb` exists anywhere: no grep hits for paramiko, asyncssh, `ros2 node list` or `lsusb`.

### Q33 — Part definition schema
Status: partial
Where: `packages/api/src/solus_api/hardware/library.py` (342) — `PartDefinition`, `PlatformDefinition`, `PlatformPart`; `hardware/definitions/{parts,platforms,vendor}`; `agent/tools/read_document.py` (507)
Note: Fields actually present on `PartDefinition`:
- `id`, `name`, `manufacturer`, `keywords`, `notes`, `category` (one of the seven)
- `specs: dict[str, Scalar]` (≤32 free-form keys, e.g. `voltage_v`, `stall_torque_kg_cm`)
- `driver_id`, `protocol_version`, `resolution`
- `register_map {name: {address, size}}` (≤64)
- `telemetry [{quantity, unit}]` (≤32)
- `calibration_mode`, `datasheet_url`

**Absent:** per-pin pinout, a structured electrical block, control modes, a mechanical block, behavioural classes (heat/noise/magnetic) and a safe-limits block. `PartLimits` exists only on the per-robot config (`config.py`), not on the definition.

Seeded: 18 parts and 6 platforms (`odrive-diff-base`, `px4-quadrotor`, `so101-follower`, `so101-leader`, `unitree-go2`, `ur5e`). `definitions/vendor/` holds only `.gitkeep`.

Datasheet path exists: the SOL tool `read_document` takes a PDF URL or artifact, renders ≤12 pages and makes one metered vision call that returns a candidate `PartDefinition`. The gated tool `propose_part_definition` then files it as a cited **`.solus` Hardware text entry**, not into the library. A human must hand-promote it to a YAML file. Both tools register only when `secret_store` is present (`agent/runtime.py:~306`).

### Q34 — Library
Status: exists
Where: `hardware/library.py` (342), `hardware/library_router.py` (322), `hardware/library_import.py` (63)
Note: YAML is loaded once into memory (`functools.cache load_library`), with no table and no runtime write path. It fails loudly on a bad file, a duplicate id or an id ≠ file stem.

Search is lexical: tokens are matched against id, name, manufacturer, keywords and machine_class, ranked by matched-token count then id. Routes under `/api/v1/projects/{id}/hardware/library`:
- `GET ""`
- `GET /{kind}/{definition_id}`
- `POST /platforms/{id}/import` (creates a robot plus parts and writes a LIBRARY config layer)
- `POST /parts/{id}/import` (into a robot, or standalone through the `ReviewedHardwareOperations` idempotency ledger)

On platform import, `_reconcile` runs `local.detect_devices` and feeds each device through the link-suggestion engine (`PartObservation` → `HardwareSuggestion`). It is best-effort: with no local runner it returns `[]`, and nothing auto-links.

### Q35 — Deployment onto a brain
Status: partial
Where: `livebench/deploy/flash.py` (146), `plugins/arduino/arduino_flash.py` (80), `plugins/arduino/presence*.py`, `hardware/presence.py` (387), `agent/tools/firmware_presence.py` (52), `livebench/deploy/companion.py` (384) + `companion_remote.py` (167), `hardware/companion_deployment.py` (330), `libs/solus-telemetry/` (arduino `SolusTelemetry.cpp` 101, micropython 149, python `http.py` 198 / `mirror.py` 215 / `__init__` 143)
Note: Flashing is limited to **presence firmware** (profiles `uno_avr` and `nano_avr`; kinds heartbeat/probe/topology). It goes through the SOL tool `hardware.flash_presence`, which has `requires_confirmation=True` and `requires_complete_preview` and uses `arduino-cli` resolved via `shutil.which`.

The UI reaches it through `PresenceCard`/`PresenceWiringCard` in `RobotTopologyGraph` (prepare/wiring routes under `/robots/{id}/brains/{brain_id}/presence/*`). Onboard-Linux deploy is `hardware.deploy_companion` (gated). It installs a companion zipapp onto a **pre-enrolled** target over SSH through a pinned helper at `/usr/local/libexec/solus-companion-deploy.py`; it never enrolls. No ROS package or MCP is deployed to onboard Linux.

Motion: `FeetechCodec.write_goal_position` and `recognition/active.run_active_identification` (which is gated by `propose_motion`) have **no production caller**. No path commands motion.

### Q36 — Identity binding
Status: exists
Where: `hardware/config.py:63-92` (`TRANSPORT_PREFIX`, `part_ref`, `device_ref`), `graph/resolver.py` (99), `livebench/local.py` (507), `livebench/hardware/usb_serial.py` (113), `livebench/telemetry/reconnect.py` (117), `hardware/detect.py` (902)
Note: Confirmed:
- `device_ref = f"{TRANSPORT_PREFIX[kind]}:{binding}"`, with prefixes usb, can, ble, bt, ip, ros2.
- `part_ref = f"{device_ref}/{address}"` is written to `part.external_ref` in `detect.bind_device`.
- `DbResolver` matches `GraphEntity.external_ref == device_id` within project scope; a caching wrapper sits in front.
- Reconnect re-resolves the tty from the USB serial number through the `/dev/serial/by-id` alias (`local.py:183-213`). `ReconnectingSource` uses backoff from 0.5 s to a 30 s cap.

Servo-count change: newly answering addresses are appended as unbound `bus_map` rows. Addresses that stopped answering keep their entry and are simply not marked `live` (`_mark_live`). Nothing is deleted.

409s:
- `detect.py:404`: "already part of robot… reconnecting a known machine needs no second robot"
- `:584`: "already bound to <device_ref>"
- `:671/674/678`: `proposal_changed` on identity, protocol or address collision
- `:731`: `conflict`
- `hardware_router.py:727`: `device_changed`

### Q37 — Hardware add UI
Status: partial
Where: `features/graph/hardware/HardwareAddPanel.tsx` (99, mounted from `robots/usePhysicalRobots.tsx:51`). `DetectedModal.tsx`, `ProposalView.tsx`, `LibraryModal.tsx`, `FromFileModal.tsx` and `AuthoredPartModal.tsx` are **absent** (no files by those names).
Note: The panel has three titled sections: **Devices found** (`DevicesFound` 73 / `DeviceCard` 295), **Search** (`HardwareSearch` 445, library plus `InlineSupplierResults` 120) and **Describe something new** (`DescribeNew` 197). Two untitled blocks sit beside them: `HardwareSourcesPanel` (303, "Local configuration and calibration") and `UnassignedParts` (250). So the "three things" shrink effectively landed, in commit de1eddd8 (SOLUSDEV-260); there is no five-card layout. Separate robot-topology cards: `ExtractionReviewCard` 365, `PresenceCard` 384, `PresenceWiringCard` 524, `HostAttachmentCard` 320, `FirmwareTelemetryOffer` 246, `HostMirrorOffer` 186.


## E. SOL


All answers read against `/home/beeboss/Solus` @ `da9204ff` (== origin/main). No model/provider calls were made. Paths are relative to `packages/api/src/solus_api/` unless they start with `apps/`, `integrations/` or `packages/`.

### Q38 — Gateway
Status: exists
Where: `orchestration/models.yaml` (430), `orchestration/providers.py` (901), `orchestration/gateway.py` (530), `orchestration/router.py` (67), `orchestration/resolution.py` (177), `orchestration/complexity.py` (100), `orchestration/type_estimator.py` (108), `orchestration/gates.py` (226), `orchestration/cost.py` (213), `orchestration/retry.py` (204), `routers/orchestration.py` (133)
Note: Three adapters are registered: `AnthropicAdapter`, `OpenAIAdapter`, `GeminiAdapter` (`providers.py:889-901`). Azure is a config stanza only, with `endpoint: ""`; routing to it raises `UnknownProviderError`. There is no OpenRouter and no Ollama. Routing is deterministic with no model call. Complexity goes explicit → regex estimator on the live message (`estimate_from`) → context default → estimator. Type goes explicit → `derive_type(context)` → `estimate_type`. Then `route()` reads the `(complexity × type)` cell of the matrix, and the window policy escalates a system-routed choice within the same type family. Tiers are trivial/standard/hard. The only override a user can reach is the composer's **"Think harder"** switch, which bumps the estimated tier by one and passes it as an explicit tier (`agent/runtime.py:_complexity_override`). The tier/type popover (`ClassifyIndicator.tsx`) is marked "UNWIRED" in its own header. Cost hooks: `gates.check_frequency_cap` (20 calls/min, Redis sliding window) and `gates.assert_can_spend` (trial cap 1000 credits) run before the call; `cost.track_cost` debits after it (`gateway.py:163-170, 283-289`). `POST /orchestration/classify` previews routing.
**Live in dev:** the root `.env` has `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GEMINI_API_KEY` (all non-empty). The dev DB `connector_secrets` holds the refs `anthropic_api_key`, `brave_api_key`, `google_api_key` and `openai_api_key`, so all three providers can be called. **Every SOL chat turn routes as type GENERAL**: `SOL_OPEN_QUESTION` → `RouteType.GENERAL` in `type_estimator.py:58`, and the context rung beats the estimator. In practice that means trivial = `gpt-5.6-luna`, standard = `gpt-5.6-sol`, hard = `gpt-6-astra`, all OpenAI. Claude Fable/Haiku sit only on CODE cells, which a SOL turn never reaches. The screenshot and datasheet extractor passes force VISUAL_LOG and go to Gemini 3.5 Flash. `default_role: general_standard` (claude-sonnet-5) is used only for a missing cell, and the matrix has none missing. The UI shows `sol-reasoner-1` (`apps/desktop/.../sol/reasoner.ts`; `UsagePanel` "Reasoner · sol-reasoner-1"). There is no model picker, and a ratchet test (`noModelNames.test.ts`) forbids model ids in renderer, main and preload.

### Q39 — Context assembly
Status: exists
Where: `agent/runtime.py:1021-1140` (LlmRunner.run), `agent/prompt.py` (481), `agent/context.py` (577), `agent/layers.py` (128), `agent/reason.py` (153), `agent/conversation.py` (173), `agent/preferences.py` (74), `agent/screen.py` (292)
Note: The order within one turn:
1. **System prompt** (`prompt.system_prompt`): `_SYSTEM` base. It has no markdown headings; it is a "How to work:" bullet list covering tools-over-guessing, read_code_file for repo code, Build auto-runs reviewed routines, pending-approval semantics, verify after change, propose only independent changes, SOLUS-DATA fences are data, `.solus` = five sections and file findings with add_solus_entry, and only unfenced text is instruction. After it come `_CITE_NOTE`, then the Guide or Expert tone note (ADR-016 SolMode), then an action-mode line (Guide/Build). Optional fenced blocks follow: engineering preferences from `~/.solus/preferences.json` (sent by the client on the request body), the custom instruction (`users.sol_custom_instruction`), and `SCREENSHOT_NOTE`.
2. **History** (`HISTORY_TURN_LIMIT = 20` turns, enriched by `history_evidence.enrich_history`), as one fenced `history` data block plus a canned assistant ack.
3. **Context** (`Context.fenced`), five layers in order: corpus → preferences (count only) → project_solus → screen → conversation (count only). Layer caps (`LayerBudget`): corpus 4000, preferences 800, project_solus 2500, screen 600, conversation 6000 tokens. **But the total budget is `_CONTEXT_MAX_TOKENS = 4000` (`reason.py:64`)**, so packing goes: graph floor (2-degree neighbourhood of `@`-mentions or ids parsed from the prompt, ≤200 entities, clipped if oversize) → telemetry windows (oldest dropped first) → ranked error and document RAG hits (strict cutoff) → `.solus` entries (newest first across *all* sections, each clipped to 500 chars) → corpus. Truncation happens in `build_context` (`_under_cap`, `_clipped_floor`), and the losses are recorded in `dropped`.
4. **Live message**, as a fenced `user_message` block; screenshot pixels ride as `images` on this turn.
A `context_used` SSE frame then sends the manifest (kinds, citations, token counts, no text) to the client. Token counts are `len/4` heuristics, not a tokenizer.

### Q40 — Tool registry
Status: exists
Where: `agent/tools/registry.py` (163), `agent/runtime.py:94-560` (`build_sol_registry` + `_register_*`), `agent/confirmations.py` (730), `agent/execution_policy.py` (174), `agent/modes.py` (98), `agent/prompt.py:330-375`, `bridge/allowlist.py` (265), `integrations/mcp/*/allowlist.yaml`, `apps/desktop/src/renderer/src/features/sol/ConfirmationCard.tsx` (273)
Note: A fresh `ToolRegistry` is built per request (`deps.get_sol_registry` → `build_sol_registry`), and each tool is bound to the project/user by Solus code. `registry.register(tool)` is the only way in. The registry is a plain dispatcher. Its `invoke()` never raises: unknown tool, bad args (jsonschema Draft 2020-12), ToolException, timeout (default 30 s) and `BaseExceptionGroup` all become `ToolResult(ok=False)`, and only an external `CancelledError` group propagates (`registry.py:100-136`). The runner never holds the registry: `build_dispatch` fuses gate-then-invoke, and `build_mode_dispatch` wraps it with the Guide refusal (`modes.py`).

**`confirmation_refusal`** is defined at `runtime.py:~710` and is the fallback when no `park` is wired. In production `routers/sol.py:~930` supplies `park` → `confirmations.request_confirmation`, which persists the exact args and streams a `tool_confirmation` SSE frame (`agent/stream.py:86`). `ConfirmationCard.tsx` renders it as generic `{label, before, after}` rows. Approval → `confirmations.py:564` invokes.

**Important (Build mode bypasses the card):** `BuildExecutionPolicy.prepare` (`execution_policy.py:104-160`) **auto-executes without a consent card** any "owned routine" tool. The set is 10 Onshape writes, 6 `isaac.*` writes, `machine.write_file`, and 6 `kicad.*` writes plus `code.git_commit` (bridge tools whose schema SHA matches a pinned digest). It runs them after two identical complete previews, and only in Build/DO mode, unless the composer's "force confirmation" toggle (`body.force_confirmation`) is on. Everything else that is gated parks for approval. The system prompt tells the model this. This reads as a deliberate relaxation of CLAUDE.md §7's "any destructive action requires explicit user confirmation".

**Dotted names:** `prompt.provider_tool_names` maps `[^a-zA-Z0-9_-]` → `_`, caps at 64 and adds a deterministic collision suffix; `resolve_tool_name` maps back before dispatch, and an unknown name passes through so the registry answers NOT_FOUND.

`rg -n "registry.invoke"` (production hits only; about 120 test-file hits under `packages/api/tests/` omitted):
```
packages/api/src/solus_api/agent/tools/mcp_tool.py:451:            # `registry.invoke`'s.
packages/api/src/solus_api/agent/tools/registry.py:124:    `await registry.invoke(call)` had nothing underneath it.
packages/api/src/solus_api/agent/tools/exec.py:10:  the only production holders of `registry.invoke` stay `runtime.py` and
packages/api/src/solus_api/agent/runtime.py:773:    forgotten it, and cannot reach `registry.invoke` at all — it never receives
packages/api/src/solus_api/agent/runtime.py:779:    `registry.invoke` besides the confirmation flow's post-approval path
packages/api/src/solus_api/agent/runtime.py:805:            result = routine_policy.finish(await registry.invoke(call))
packages/api/src/solus_api/agent/runtime.py:826:        return await registry.invoke(call)
packages/api/src/solus_api/agent/confirmations.py:564:        return await registry.invoke(call)  # the sanctioned post-approval site
```
That is three call sites in two files. The ratchet is `packages/api/tests/test_sol_runtime.py:249` `test_only_the_gated_dispatcher_reaches_registry_invoke`. One more out-of-gate invoke exists by design: `_register_bridge_tools` calls `_tool.invoke` directly for the ungated `code.probe_environment` read feeding `link_environment`.

**Registered tools**

Columns: Gated = `requires_confirmation`. Modes: Guide refuses every gated tool (`mode_refusal`); Build sends gated tools to park, and auto-runs them if they are an owned routine (marked **auto**). Ungated tools run in both modes.

| Tool | One line | Gated | Modes |
|---|---|---|---|
| `get_entity` | Read one graph entity by id (project-scoped) | no | both |
| `query_graph` | Graph neighbourhood read via SolSystems | no | both |
| `get_telemetry` | Telemetry window summary | no | both |
| `retrieve_errors` | Error-history retrieval | no | both |
| `run_checkers` | Run the checker library over the graph | no | both |
| `analyze_rail_current` | Rail-current analysis | no | both |
| `read_code_file` | Read a repo file by graph entity (selected branch / verified local copy) | no | both |
| `add_solus_entry` | File a note into a project `.solus` section | **no** | both |
| `edit_solus_entry` | Edit a `.solus` entry | yes | Build (park) |
| `delete_solus_entry` | Delete a `.solus` entry | yes | Build (park) |
| `set_hardware_config_field` | Set one hardware-config field | yes | Build (park) |
| `link_environment` | File/link an observed code environment (needs companion) | yes | Build (park) |
| `make_diagram` | Draw an SVG diagram into a TTL artifact | no | both |
| `read_document` | Fetch/render datasheet PDF, extract specs w/ page cites (metered VISUAL_LOG call) | no | both |
| `propose_part_definition` | Propose a part definition from an extracted datasheet | yes | Build (park) |
| `sourcing.derive_torque` | Torque arithmetic over the graph | no | both |
| `code.resolve_environment` | Resolve declared code environment | no | both |
| `bom.add_item` | Add a planned/raw BOM row (first-party bundle, if installed) | **no** | both |
| `research` | Web research loop over Brave MCP (only if discovered) | no | both |
| `solus.list_integrations` | List connectable integrations | no | both |
| `solus.connect_integration` | Connect an integration | yes | Build (park) |
| `solus.verify_integration` | Verify a connection | no | both |
| `bench.list_cad_sources` | List CAD sources for a bench scene | no | both |
| `bench.import_cad_scene` | Import CAD → sim scene (enqueues job) | yes | Build (park) |
| `bench.cad_import_status` | Poll the import job | no | both |
| `hardware.flash_presence` | Flash presence firmware (if service wired) | yes | Build (park) |
| `hardware.deploy_companion` | Deploy companion to a device (if service wired) | yes | Build (park) |
| `onshape.list_documents` · `list_elements` · `get_feature_tree` · `get_feature_specs` · `get_body_details` · `get_mass_properties` · `get_assembly_definition` · `get_variables` · `inspect_assembly_geometry` · `list_parts` · `get_part_bounds` · `resolve_reference` | Onshape reads (12) over team OAuth | no | both |
| `onshape.add_feature` | Add a feature | yes | Build (park) |
| `onshape.set_variable` · `update_feature` · `insert_part` · `extrude_cut` · `create_circle_sketch` · `create_face_mate_connector` · `create_circle_mate_connector` · `create_fastened_mate` · `create_revolute_mate` · `restore_fastened_pose` | Onshape writes (10) | yes | Build **auto** |
| `onshape_fs.whoami` · `get_api_usage` · `get_featurescript` · `list_feature_studios` · `read_featurescript_notes` · `search_featurescript_documentation` · `test_featurescript` | Hosted Onshape Labs FeatureScript MCP reads (inventory persisted at connect) | no | both |
| `onshape_fs.put_featurescript` · `create_geometry` · `create_feature_studio` · `test_feature` · `edit_featurescript_notes` | FeatureScript MCP writes | yes | Build (park) |
| `isaac.probe` · `isaac.status` | Isaac readiness / owned session state (companion) | no | both |
| `isaac.start` · `stop` · `load_model` · `set_joint_limits` · `set_sensor_pose` · `run_routine` | Owned Isaac session ops (companion) | yes | Build **auto** |
| `machine.read_file` | Read any file on the companion machine | yes | Build (park) |
| `machine.write_file` | Write a file (`MachineWriteTool` wrapper) | yes | Build **auto** |
| `local.scan_folder` · `local.folder_digest` | Local folder scan (companion) | no | both |
| `local.open_in_tool` | Open a file in its desktop tool | yes | Build (park) |
| `code.probe_environment` · `plan` · `git_status` · `git_log` · `git_diff` · `arduino_probe` | Code/env reads (companion) | no | both |
| `code.git_commit` | Commit (pinned schema digest) | yes | Build **auto** |
| `code.create_environment` · `install` · `run` · `test` · `git_push` · `arduino_prepare` · `arduino_compile` · `arduino_upload` | Env / run / push / flash (companion) | yes | Build (park) |
| `kicad.get_symbol_definition` · `get_schematic_geometry` · `check_erc` · `list_projects` · `get_project_structure` · `extract_project_netlist` · `analyze_schematic_connections` · `analyze_bom` · `export_netlist` | KiCad reads (vendored MCP fork via companion) | no | both |
| `kicad.create_schematic` · `add_symbol` · `add_wire` · `add_net_label` · `mark_no_connect` · `set_symbol_property` | KiCad schematic writes | yes | Build **auto** |
| `altium.*`: 9 reads + `proj_set_parameter`, `sch_set_components_parameters` | Altium MCP (BYO-paid license preflight) | writes only | reads both / writes Build (park) |
| `autocad.*` (155) | AutoCAD MCP: every tool gated, reads included | yes (all) | Build (park) |
| `solidworks.*` (62) | SolidWorks MCP: every tool gated | yes (all) | Build (park) |
| `fusion.*` | Allowlist has 0 tools | — | — |
| `brave.*` (4) | Consumed by `research`; not offered directly | no | — |

Companion-sourced rows register only when the user's companion is connected and advertises them. Names are filtered by the allowlist YAMLs, and `requires_confirmation` comes only from the allowlist. `machine.read_code_file` and raw `isaac.*` are deliberately hidden. There is no per-mode tool *set*: Guide sees the same descriptors and is refused at dispatch.

### Q41 — Guide / Build
Status: partial
Where: `agent/modes.py` (98), `agent/turn_limits.py` (22), `agent/execution_policy.py` (174), `agent/prompt.py:300-312`, `apps/desktop/src/renderer/src/features/guide/*` (GuidePanel 218, GuideTasks 159, useNativeGuideHandoff 124, guideApi 98, useGuide 44), `features/overlay/*` (overlaySession 147, overlayDecision 82, GuideOverlay 71, OverlayWindow 64), `apps/desktop/src/main/overlay/overlayWindow.ts` (162), `toolkb/guides.py` (186), `toolkb/guides/*.json` (2)
Note: `ActionMode` is `guide | do` (UI label "Build"), carried as a field on each turn request (`action_mode`, default guide). The prompt is the same apart from one action-mode sentence, and the tool set is the same. Guide is enforced structurally: a dispatch wrapper refuses every `requires_confirmation` tool. Limits are Guide 5 rounds / 8 tool calls / 120 s and Build 16 / 24 / 300 s.
Asked "how do I add a mate in Onshape", Guide answers in **text only**: the SOL turn has no path that highlights or points. The pointing overlay is driven only by **authored walkthroughs**. In Guide mode the SOL window shows a `GuideTasks` picker (Onshape / KiCad / Code + version) that lists `toolkb/guides/*.json`. Exactly two guides exist, `onshape_6mm_hole` (4 steps) and `kicad_first_schematic` (6 steps), and there is none for mates. The dev DB has 126 published tool-knowledge rows (kicad 107, code 10, isaac 7, onshape 2) and **0 of them carry a screen locator**, so the overlay always takes its no-coordinates fallback.
Build can run every gated tool in Q40. Owned routines auto-run with no card, and the rest park for approval. The gate is present in both modes. Guide never reaches it because it refuses gated tools first.

### Q42 — SOL window and hotkeys
Status: exists (runtime behaviour on this machine not determined)
Where: `apps/desktop/src/main/hotkeys/index.ts` (243), `globalHotkeys.ts` (93), `ctrlStateMachine.ts` (114), `keyHook.ts` (131), `main/gesture/circleDetector.ts` (110), `cursorSampler.ts` (44), `main/sol-window/solWindow.ts` (378), `orbOverlayWire.ts` (182), `nativeGuideTarget.ts` (76), `main/solSettings.ts` (173), `main/capture/screenCapture.ts` (201), `activeWindow.ts` (68), `main/platform/capabilities.ts` (110), `main/index.ts:405-660`
Note: `globalShortcut` registers three things. `Control+Space` **toggles Guide/Build mode**; it does not spawn. `CommandOrControl+Shift+Space` summons. `Control+Shift+C` enters a 10 s circle mode. Double-tap Ctrl (≤250 ms taps, 350 ms window, uiohook-napi key hook) **summons**: `windows.open()` focuses the existing window if one is open and otherwise creates one, so it never toggles closed. Hold-Ctrl-and-circle exists through the hook (`gestureStart/End` → `circleDetector` → `onRegion` → region capture); with no hook, Ctrl+Shift+C is the fallback. The floating window is one 420×640 BrowserWindow (min 360×420) at `#/sol-window`. Its geometry persists to `~/.solus/config.json` (`sol.window`, clamped to a live display), and always-on-top is optional (default off). Global shortcuts work while another app has focus.
Screen capture is opt-in: `screenIntelligence` defaults to false. A capture happens only on a circle gesture and is held in memory for one turn. The visible indicator is the attached-region chip ("Remove screenshot") and "screen attached" on the sent message; there is no persistent recording indicator. macOS: `getMediaAccessStatus('screen')` and `isTrustedAccessibilityClient(false)` probes surface a needs-permission message with a settings URL; Solus never prompts for the permission itself. The corner orb is retired (`overlayHandoff.ts` header); `Orb*` survives only as CTR-06 contract and IPC names. Per memory, the uiohook linux-arm64 prebuild is x64, so on this box the hook is likely unavailable and fallback mode applies (not re-verified).

### Q43 — Chat UI
Status: exists
Where: `apps/desktop/src/renderer/src/features/sol/`: SolChat.tsx (665), solChatStore.ts (683), ChatsSidebar.tsx (362), solApi.ts (288), ConfirmationCard.tsx (273), ContextPanel.tsx (238), ClassifyIndicator.tsx (238, unwired), UsagePanel.tsx (184), solStream.ts (165), useMentionPicker.ts (154), overlayHandoff.ts (152), SolWindow.tsx (143), ArtifactCard.tsx (129), streamBench.ts (120), useSolChat.ts (118), SolScreen.tsx (115), markdownSplit.ts (113), solCache.ts (110), solWindowStore.ts (105), solSessionStore.ts (104), useClassifyPreview.ts (72), mentionToken.ts (68), useMentionSearch.ts (65), CommandOutput.tsx (61), useCustomInstruction.ts (60), useSolConversations.ts (58), Markdown.tsx (54), tokenBatcher.ts (53), RegionCard.tsx (35), ModeBadge.tsx (24), citationLabel.ts (9), reasoner.ts (4)
Note: Tokens are batched to one flush per animation frame (`tokenBatcher.ts`). Rendering uses `react-markdown@^10.1` + `remark-gfm` with `skipHtml`; links render as inert spans and images are dropped. A settled-prefix/tail split (`markdownSplit.ts`) re-parses only the block still being written, and an open code fence stays in the tail until it closes, so code blocks are stable once settled. There is no virtualization library: rows are memoized, and settled rows use CSS `content-visibility`. Citations render as ≤12 inert mono chips that are **not linked to entities**. A collapsed `<details>` "N tool steps" shows `tool → ok/error/running…` per call (`TraceView`). The SOL page's right panel (`ContextPanel`) lists the last `context_used` manifest: document citations as files and graph citations as entity chips. There is no reasoning/thinking panel.

### Q44 — Vision
Status: partial
Where: `agent/screen.py` (292), `agent/documents/{extract.py 212, pdf.py 130, fetch.py 124}`, `orchestration/providers.py:264-500` (`ImageBlock`, per-provider encoding), `fingerprint/visual.py` (229), `agent/tools/mcp_tool.py:~361`
Note: Images reach a model in three ways.
1. **Screenshot.** The route decodes and sniffs it. `read_screen` makes one metered extractor call with `complexity=STANDARD, type=VISUAL_LOG` (Gemini 3.5 Flash), and the same pixels also ride the main turn's `images`.
2. **Datasheet.** `read_document` renders PDF pages (pypdfium, width 1400) and runs a VISUAL_LOG extraction.
3. **Silkscreen photo.** FP-03 `fingerprint/visual.py` is a silkscreen-photo extractor gated by `fingerprint_vision_enabled`. It has no authenticated trigger.
MCP/bridge tool image blocks are **summarized and dropped** (`mcp_tool.py:361`), so e.g. `autocad.view_screenshot` pixels never reach the model. Absent: any annotated-render pipeline, any render cache, and any CAD render source. There are no Onshape shaded-view/thumbnail calls and no `kicad-cli` SVG/PNG export; `kicad-cli` is used only for netlists.

### Q45 — Tool-knowledge base
Status: exists
Where: `toolkb/` (schema.py 327, guard.py 317, router.py 263, sharing.py 230, guides.py 186, review.py 125, staleness.py 107, feedback.py 97, catalog.py 96, storage.py 71), `toolkb/catalog/{onshape,kicad,fusion}.json`, `toolkb/guides/*.json`, `toolkb/ingest/{kicad.py,visual.py}`, `agent/tools/knowledge.py` (221), `routers/sol.py:~962` (`with_knowledge_notes`)
Note: One global table, `tool_knowledge`, plus `tool_knowledge_observation`. **The tenancy boundary is structural: there is no team, project or user column and no JSONB.** Rows are written only via `toolkb.guard`. What is stored is per-control UI knowledge: tool, version range, surface, control_id, label, effect, description, menu_path, shortcut, an optional normalized locator box, provenance, status candidate/published, confidence, and a pgvector embedding. Share flow: a candidate is promoted to `published` once it clears a confidence gate and has ≥ N distinct salted-hash voters; it is demoted again below a lower gate; docs-published rows are exempt.
SOL reads the knowledge base two ways, with no retrieval tool:
- **Notes.** For write tools mapped in `TOOL_CONTROLS` (isaac.start, code.git_*, code.arduino_*, kicad writes, onshape.set_variable, add_feature, update_feature…), the published entry is appended to that tool's description as a fenced note.
- **Outcomes.** After a confirmed write runs, it records a confirm/reject observation.
The Guide panel resolves authored guides against the knowledge base. Dev DB: 126 published rows (kicad 107, code 10, isaac 7, onshape 2), 0 with locators.


### Q46 — Terminal
Status: partial (no PTY/shell; fixed argv-only commands, mutating ones behind confirmation)
Where:
| Piece | File (lines) |
|---|---|
| No PTY / xterm | `rg "node-pty\|xterm\|pty.spawn\|ptyprocess\|pexpect"` → 0 hits in packages, apps, libs, livebench, reasoning, integrations |
| I3 `code` MCP server | `integrations/mcp/code/allowlist.yaml` (80), `solus/server.py` (424), `plan.py` (288), `execute.py` (245) |
| Companion supervisor running MCP servers | `packages/companion/src/solus_companion/supervisor.py` (440) |
| Companion built-in `machine` server (file read/write only) | `machine/server.py` (175), `machine/actions.py` (60) |
| Test proving built-in server has no run_command | `packages/companion/tests/test_companion_environments.py` (16) |
| Desktop process spawns | `main/projectFolder.ts` (102, `git clone`), `companion.ts` (494, starts companion), `capture/activeWindow.ts` (68, `xprop`), `sol-window/nativeGuideTarget.ts` (76) |

Note: No free-form shell, no "run command" tool. The `code` server has fixed tools (`probe_environment`, `plan`, `create_environment`, `install`, `run`, `test`, `git_status/log/diff/commit/push`, `arduino_probe/prepare/compile/upload`); every mutating tool needs confirmation and auto-files errors on failure; `plan.py` builds a fixed argv that the server runs verbatim with a ≤600 s timeout. The built-in `machine` server refuses `run_command`/`install_package`/`create_environment` by design. No sudo/elevation handling, no shell hook, no command-history reader.

### Q47 — ROS
Status: absent
Where: `orchestration/models.yaml:283,381-383` (regexes `ros2?`, `colcon`, `catkin`, `roslaunch` — model routing only); `agent/research.py:52`, `corpus/domains.py:286` (keyword lists); `hardware/topology_observations.py:137,186` (273) — `onboard_topology()` checks a pre-recorded `ros2_nodes`/`ros2_topics` snapshot, called only by tests, nothing produces one; `integrations/ros/` = `.gitkeep` only; `livebench/src/livebench/sim/isaac_direct.py:1` calls itself "the ROS-free direct path".
Note: 0 hits for `rclpy`, `ament_`, `rosbridge`, `ROS_DOMAIN`. No `package.xml`/launch-file parsing, no `ros2 node list`, no colcon detection, no DDS discovery; local-folder scanner (`detect.py`, `scan.py`) has no ROS detection. Gazebo streaming uses the `gz` CLI, not ROS.

### Q48 — Corpus / RAG
Status: partial (corpus shipped; empty in dev DB; no embeddings anywhere)
Where: `corpus/content/` 121 `.md` + `manifest.json` (613) + `corpus.toml`, ~704 KB (electrical/mechanical/robotics/software/systems); `chunking.py` (385); `ingest.py` (313) + `__main__.py` (108); `schema.py` (154, `corpus_chunk` with 1536-dim pgvector + HNSW); `retrieval.py` (183: SQL filter by domain/topic/applicability, vector rank if query embedding else English FTS, low-confidence <0.6 flagged not dropped, ≤20 results); `router.py` (148, `/api/v1/corpus`, FTS only); `agent/context.py` (577) l.84-86, 345-498 — corpus injected into every turn via `DbSolSystems.rag_query` (not a model-callable tool); `orchestration/embeddings.py` (311), `main.py:449` `build_embed_fn(..., allow_unmetered=True)`, OpenAI `text-embedding-3-small` 1536-d (`models.yaml:177-181`).
Dev DB (read-only):
```
corpus_chunk by status          => []          (empty)
graph_entity count, embedded    => (2832, 0)
error_solution count            => 0
```
Note: Embed seam still unmetered by decision (`main.py:440-445` cites ADR-018); `corpus/ingest.py:310` and `impact/consequences.py:289` also opt out. No reranker. Every pgvector column (`graph_entity`, `error_solution`, `models.py:1492`, `toolkb/schema.py:224`) is empty in dev, so retrieval is FTS or nothing.

### Q49 — Visible reasoning
Status: partial
Where: `features/sol/SolChat.tsx` (665); `ContextPanel.tsx` (238) in `SolScreen.tsx` (115); `citationLabel.ts` (9); backend `agent/stream.py` (`CONTEXT_USED` frame), `agent/context.py:195`.
Note: Each message has a collapsible "N tool steps" list (`tool → ok | running… | errorCode`), no arguments shown. Citations = plain non-clickable chips (≤12, cut to 64 chars). Right panel "CONTEXT IN USE" shows section labels + counts from the last turn plus graph-entity chips that don't link to the canvas. No per-`.solus`-entry provenance, no reasoning text.

### Q50 — Filing
Status: partial
Where: `agent/tools/make_diagram.py` (189), `agent/errors_filing.py` (235), `services/artifacts.py` (376), `services/solus_config.py` (301), `livebench/runs/store.py` (164), `features/sol/ArtifactCard.tsx` (129), `models.py:886-913` (`Artifact`, `retained` default false).
Note: Artifacts are temporary rows swept unless `retained`; SOL never files on its own. `make_diagram` writes a temp artifact; the user files it via "File this to…?" on the card (sets `retained=True`, creates a `document` entity, `solus_config.py:160`). After 260, `make_diagram` reads the v2 config (`make_diagram.py:92-114`); a leftover v1 config raises `409 config_upgrade_required` (`hardware/store.py:176`) — not run. **Error auto-filing is live**: any tool flagged `files_errors` that fails (call error / non-zero exit / timeout) → `file_tool_error` writes one `errors` entry authored `sol` (called from `runtime.py:1179`, `confirmations.py:593`); args redacted, 4000-char cap, **no dedupe/count**. Live Bench runs retain their artifacts (`runs/store.py:70,83`).

### Q51 — Checkers
Status: partial
Where:
| Rule | File | Domains |
|---|---|---|
| `op_amp_mismatch` | `checkers/core.py:31` (331) | electrical |
| `sensor_frequency_conflict` | `core.py:125` | code ↔ electrical |
| `power_compatibility` | `core.py:222` | electrical |
| `python_pin_conflict` | `checkers/environment.py:102` (210) | code |
| rail-current accounting (report, not checker) | `checkers/rail_current.py` (138) | electrical |
| telemetry threshold / CUSUM observers | `livebench/src/livebench/anomaly/observers.py` (196) | live signal |

Interface `checkers/interface.py` (109): `Warning{checker_id, severity (info|warning|critical), domains, message, evidence, entity_ids, suggested_area}` + `run_checkers()`; `DEFAULT_CHECKERS` = the 4 rules (`core.py:321`). Lives in `solus_api`, never moved to `packages/contracts/`.
Note: No Finding type or table (only `class Finding` is `agent/research.py:75`, research tool). Results reach the user only when SOL calls `run_checkers` / `analyze_rail_current` / `code.resolve_environment`. `impact/engine.py` (227) and `impact/consequences.py` (319) are imported only by tests. No mechanical rule.

### Q52 — Deterministic tier
Status: partial (only model *selection* is model-free)
Where: `orchestration/router.py` (67), `complexity.py` (100), `type_estimator.py` (108), `resolution.py` (177), routing matrix `models.yaml:183-200`, `agent/runtime.py` (1312; `LlmRunner` l.1006 wired in `main.py:381`; `ScaffoldRunner` l.849 tests only).
Note: Regex heuristics pick complexity (trivial/standard/hard) × request type (general/code/visual/long-context) → model, no model call in the choice. Every turn then ends in `gateway.stream` (`runtime.py:1104`); without a user identity it raises. Nothing answers without a model — no graph-query shortcut, unit conversion, arithmetic or limit-check path. SemanticCache caches retrieval, not answers.

### Q53 — Simulation
Status: partial
Where: MuJoCo python `livebench/sim/mujoco_source.py` (100) + `connections.py` (81), started from `local.py:263` (real physics → telemetry packets); Gazebo `gazebo_source.py` (139, `gz` CLI); MCAP `mcap_replay.py` (38); Isaac read-only `isaac_direct.py` (204); Isaac control MCP `integrations/mcp/isaac/` (`controller.py` 323 launches `SOLUS_ISAAC_RUNTIME`), SOL tools `agent/tools/isaac_tools.py` (416) + `isaac_models.py` (246): `isaac.{probe, status, start, stop, load_model, set_joint_limits, set_sensor_pose, run_routine}` (all but probe/status gated); desktop scene three.js 0.183.2 (`features/bench/scene/SceneViewer.tsx`), no MuJoCo in renderer; ngspice / CalculiX absent.
Note: No `simulate_*` tool; nothing produces an expected value compared to telemetry. Simulators are telemetry sources, not predictive solvers.


## F. Live Bench

(Desktop paths relative to `apps/desktop/src/renderer/src/`; API paths relative to `packages/api/src/solus_api/`.)

### Q54 — Layout
Status: exists
Where: `features/bench/BenchScreen.tsx` (226), `scene/ScenePanel.tsx` (464), `DeviceBenchView.tsx` (570), `SignalWidget.tsx` (249), `runs/RunsView.tsx` (373), `BenchCanvasHost.tsx` (164), `ConnectDeviceModal.tsx` (122), `widgets/livebench/LiveBenchWidget.tsx` (239)
Note: "Panes not tabs" landed: left aside = scene + static "No camera stream" / "No LiDAR or depth stream" placeholders; right pane = device signals, with Runs and "Workspace widgets" below. No findings pane — anomalies are only markers on signal widgets. Recorded sensor frames show only in run playback.

### Q55 — Scene
Status: partial
Where: `scene/SceneViewer.tsx` (154), `kinematics.ts` (149), `displayPose.ts` (40), `sceneApi.ts` (250), `CadImport.tsx` (238), `CadBindings.tsx` (154), `MappingReview.tsx` (212); API `livebench/scene/{router 296, service 302, parser 297, meshes 108, cad_import 346, cad_refresh 559}.py`; `connectors/worker.py:450`
Note: three.js 0.183 with an in-house URDF/MJCF kinematic tree — no mujoco-wasm or urdf-loader on main. Models are `graph_entity` kind `bench_scene_model`, one per Physical Robot, several rendered side by side with separate poses (the only multi-robot "namespacing"). CAD-change path exists: Onshape sync `prepare()`/`complete()` re-tessellates the STEP export keyed on `observed_microversion`; the UI does **not** auto-reload — it shows "Source or hardware mapping changed. Reimport…". Poses persist only in localStorage (`solus.scene.pose.v1:[user,project,model]`). Jointless models render static.

### Q56 — Observers → findings
Status: partial
Where: `livebench/anomaly/observers.py` (196, Threshold/Cusum), `anomaly/session.py` (70); API `livebench/sessions.py:308-321`; `bench_router.py:91-148` (`ObserverEventIn`, `BenchEventRing` cap 512), `GET /bench/events`; desktop `signalAnomalies.ts` (73)
Note: Event kinds `threshold_breach | change_point | stream_gap` → in-memory per-project ring → desktop polls `/bench/events` and draws time-only markers. No Finding type/table for live data; events vanish on restart. `graph/live.py` (404) is the SSE/Redis hint hub, not an observer. L4 partial: SOL has the `get_telemetry` builtin and telemetry summaries in context (`agent/context.py:305,483`) but cannot read observer events or runs.

### Q57 — Runs
Status: exists (L5 built)
Where: API `livebench/runs/{models 100, capture 151, store 164, snapshot 244, analysis 271, narration 111, router 326}.py`; desktop `runs/{RunsView 373, RunPlayback 85, RunEvidence 274, runDecoders.ts 290, SensorPreview 124}`
Note: Routes: create, import, list, compare, get, stop, `{id}/findings`, `{id}/narrate`. A run = `graph_entity` kind `bench_run` + a RunManifest artifact (≤8 MiB, ≤10k packets) carrying PartEvidence (signals, stall current, limits, code_site, cad_revision), scrubbed config/graph snapshots, camera/lidar refs; filed into `.solus` via `add_artifact_entry`, checkpoint artifacts `retained=True`. Analysis deterministic (stall windows; compare = config changes, divergences, clamps) + one optional metered narration batch. No dedicated tables, no retention policy.

### Q58 — Telemetry resolution
Status: exists
Where: `graph/{resolver 99, packet 153, codec 188, buffer 206, telemetry 322}.py`; `bench_router.py:149-184`
Note: Match is `device_id == external_ref`, project-scoped, non-deleted, `limit(1)`, behind a positive-only cache (30 s TTL, 4096 entries). Packet: device_id ≤512, aware timestamp, values ≤256, units, seq; wire `ts_us` integer. W0-07 summaries use 6 buckets. Ring 512 samples/signal (Redis variant LTRIM, 1 h TTL). Unresolved packets are counted (`unresolved`) and held in a 16 device × 16 signal × 256 sample ring; the desktop shows that count nowhere outside tests.

### Q59 — Session config
Status: exists
Where: `bench_router.py:244-340`; `sessions.py:129-187`; desktop `useActiveBenchSessions.ts` (61), `useExternalBenchDevices.ts` (50), `SavedRobotConnections.tsx` (124), `localconnections/DeviceRow.tsx`
```
MujocoSimConfig    provider "mujoco"; scene_name="demo"; mjcf_xml|None ≤2,000,000; sample_hz=50 (≤200); duration_seconds=300 (≤3600); window_seconds=1 (≤60)
GazeboSimConfig    provider "gazebo"; topics 1..32 (each 1..256, no leading "-"); window_seconds=1
McapSimConfig      provider "mcap-replay"; mcap_path 1..4096; topics|None ≤32; window_seconds=1
SerialRealConfig   provider "serial"; serial_number|None; confirmed_device_path|None; baud=115200 (300..3M); window_seconds=1; driver_id|None ^[a-z0-9][a-z0-9._-]{0,63}$; driver_params ≤32
RobotRealConfig    provider "robot"; robot_entity_id: UUID; window_seconds=1
HardwareRealConfig provider "hardware"; entity_id: UUID; window_seconds=1
BenchSessionIn     mode sim|real; config discriminated on provider; _SIM_PROVIDERS={"mujoco","gazebo","mcap-replay"} ⇔ mode sim
BenchSessionOut    id, mode, provider, status starting|active|ended, link, label, created_at, ended_at, device, device_ids, counts{ingested,unresolved}, last_summary
```
(Field lists, not verbatim class bodies — H6 refuses column-0 `class` lines naming existing symbols.)
Note: No `replay`/`sim`/Isaac provider. **The API process owns the lifecycle**: in-memory SessionManager (4 active/project, 32 ended kept) that opens the serial port itself via the optional `livebench.local` import — real mode works only with a local API. UI: POST `/bench/sessions`, `/stop`. L1 discovery is focus-independent: polls sessions every 5 s + `telemetry-devices`.

### Q60 — Sim / Isaac connection
Status: partial
Where: `livebench/sim/{isaac_direct 204, mujoco_source 100, gazebo_source 139, mcap_replay 38, connections 81}.py`; `integrations/mcp/isaac/`; `agent/tools/isaac_tools.py` (416), `isaac_models.py` (246)
Note: Isaac is local-only: `isaac_direct.py` runs under Isaac's python and POSTs to `/bench/telemetry` (default `http://localhost:8000/api/v1`, `--url` override, token from `SOLUS_TOKEN`); companion Isaac MCP takes `SOLUS_ISAAC_RUNTIME` and gates start/load_model/run_routine. MCAP = local file; Gazebo = live topics. I5 server-side sim absent. Vendor names outside the plugin tree: `bench_router.py` `_SIM_PROVIDERS` + sources list (incl. "isaac"), desktop `resources.ts:1379-1394`.

## G. Integrations

### Q61 — Capabilities declared
Status: absent (no capability vocabulary in the contract)
Where: `packages/contracts/python/solus_contracts/connector.py` (187); `connectors/contracts.py` (250); `registry.py:280-366`
Note: `rg "change_signal|construction_history|capabilit"` → nothing relevant. Nothing is *declared*; the table is what each connector actually does.

| Connector | Status | Actual behaviour |
|---|---|---|
| Onshape | exists | structure, STEP geometry, microversion change detection, webhook, 11 native writes + 5 FeatureScript-MCP writes; no render/thumbnail; feature tree read-only |
| KiCad | exists | netlist (XML/S-expr) + `.kicad_pcb`, hash change detection; writes only via MCP fork |
| Local folder | exists | one node per tool project, digest change detection |
| GitHub / GitLab | exists | git tree, SHA+ETag change detection, `.solus` blob read |
| Altium | partial | 46-line scaffold + MCP allowlist (11 tools, 2 gated) |
| Isaac | partial | not a connector: MCP bridge + direct script |
| Foxglove / Gazebo / MuJoCo | partial | livebench telemetry/sim sources, not connectors |
| Fusion | absent | empty allowlist |
| SolidWorks / AutoCAD | absent | allowlists of 62/155 tools, no server code |
| ROS | absent | `.gitkeep` only |

Contract (members, not verbatim — H6): `Connector(abc.ABC)` ClassVars `provider`, `auth_kind=NONE`, `config_fields=()`, `supports_token_connect=False`; abstract `validate_credentials(creds) -> AccountInfo`, `sync(ctx) -> SyncResult`, `detect_changes(ctx) -> bool`. `OAuthConnector` adds `auth_kind=OAUTH`, `scopes=()`, `authorize_url(*, state, redirect_uri)`, `exchange_code(*, code, redirect_uri)`. `EntityOut{source_key, type, domain, name, properties, modality_hints}`; `RelationOut{from_key, to_key, type, properties}`. Domain enum: code, electrical, mechanical, simulation, runtime, project, workspace.

### Q62 — Cache and quota
Status: exists
Where: `connectors/{httpcache 248, integration_cache 567, onshape_read_cache 499, quota 446, worker 1284}.py`; `services/onshape_webhooks.py` (509); `routers/webhooks.py` (397); `config.py:186-227`
Note: Single-flight via Redis SET NX EX; per-account cache keys; payloads in a write-once CAD store; `cache_only` query flag on sources + document-tree routes. Annual quota ledger (`onshape_annual_call_allowance=2500`, degrade at 0.7, 402 latch); 2026-09-14 audit recorded 1,260/1,800 = 70%, live testing paused. **Webhooks register on sync dispatch, not at OAuth connect**, and only when `public_api_base_url` is public HTTPS — default `http://localhost:8000`, so dev never registers one. 90 s quiet period + quiet-job prefix present; remaining `change-signal-spine.md` lease rules **not determined**.

### Q63 — Onshape
Status: partial
Where: `connectors/onshape_ops.py` (1247) + authoring/refs/cut/sketch/mates modules; `agent/tools/onshape_tools.py` (619); `remote_mcp.py:157-230`
Note: OAuth app: 12 read ops (incl. list_documents), 11 write ops all `requires_confirmation=True`. FeatureScript MCP (fs-mcp.labs.onshape.app): 5 mutating tools; `logout` and `set_api_allocation` deliberately unregistered. No folder listing, no rename. Double-click-to-allow issue: **not determined**.

### Q64 — KiCad
Status: partial
Where: `connectors/kicad*.py` (~1,400 lines); `integrations/mcp/kicad/`; companion `kicad_discovery.py` (43)
Note: Parses netlist + PCB, refuses raw `.kicad_sch`; live export via the MCP fork's `kicad-cli`. Fork has 6 gated schematic writes (`set_symbol_property` allowlisted but not registered). No IPC API, no ngspice.

### Q65 — Local folder
Status: partial
Where: `connectors/local_folder.py` (658); `integrations/mcp/local/solus/{scan 163, toolmap 58}.py`; companion `watch.py` (224); desktop `main/index.ts:670`
Note: Folder picked in MAIN, scanned by the companion; nodes per tool project (KiCad, Altium, CAD-suffix folder, Arduino, one Python root). No ROS / PlatformIO / `package.xml` detection. Watching = stat-poll sweep emitting payload-free change frames. Git origin → deterministic edge to the repo node.

### Q66 — GitHub
Status: partial
Where: `connectors/github.py` (459), `code_content.py` (137)
Note: Lists repos, walks the tree at head SHA, SHA+ETag change detection, bounded file reads. No clone, no webhook, no API write; commits/pushes only via the companion `code` MCP (gated).

### Q67 — Write gating
Status: exists
Where:
| Surface | Write tools | Gate |
|---|---|---|
| Onshape native | set_variable, add_feature, insert_part, update_feature, extrude_cut, create_circle_sketch, create_{face,circle}_mate_connector, create_{fastened,revolute}_mate, restore_fastened_pose | requires_confirmation=True |
| FeatureScript MCP | put_featurescript, create_geometry, create_feature_studio, test_feature, edit_featurescript_notes | mutating → consent |
| KiCad MCP | create_schematic, add_symbol, add_wire, add_net_label, mark_no_connect, set_symbol_property | true |
| Altium MCP | proj_set_parameter, sch_set_components_parameters | true |
| companion code | create_environment, install, run, test, git_commit, git_push, arduino_prepare/compile/upload | true |
| companion machine / local / isaac | write_file+read_file / open_in_tool / start, stop, load_model, set_joint_limits, set_sensor_pose, run_routine | true |
| SOL bench.import_cad_scene | CAD import into scene | True |
| SolidWorks / AutoCAD | all | true, no server code |
| GitHub / GitLab API | none | — |
Note: "Gated" here means the tool declares confirmation. **But see Q40/Q41 (E1): in Build mode about 24 owned write tools auto-run without a consent card unless the user ticks force-confirmation.**


## H. UI

(Renderer paths relative to `apps/desktop/src/renderer/src/` unless prefixed.)

### Q68 — Navigation
Status: exists
Where:
| Piece | File | Lines |
|---|---|---|
| Router (HashRouter) | `App.tsx` / `routes/AppRoutes.tsx` | 49 / 107 |
| Shell (title row + menu row + left rail + screen) | `features/workspace/WorkspaceShell.tsx` | 803 |
| Route state | `features/workspace/shellStore.ts` | 66 |
| Title row | `features/workspace/TitleBar.tsx` | 36 |
| Menu row | `features/workspace/MenuBar.tsx` + `menuBar.constants.ts` | 250 + 75 |
| Search box | `features/workspace/ShellChrome.tsx` (`SearchBox` l.14–37) | 287 |

Note: URL routes: `/` (Landing if signed out → `/onboarding` if not onboarded → `WorkspaceShell`), `/login`, `/signup`, `/reset-password`, `/onboarding`, `/sol-window` (separate SOL window), `/overlay` (click-through guide overlay), `/ext-window/:extensionId`, `*` → `/`. Inside the shell, screens are **not routes**: `useState<ShellRoute>` (not persisted) with `MainScreen = 'home'|'workspace'|'bench'|'sol'|'store'|'billing'|'settings'` plus detail routes `alert` and `ext-page`; registering a screen = editing the type union + `RAIL_*` arrays + the `ScreenView` switch. A persistent top bar exists (SOLUSDEV-235): 44px title row (project-switcher pill, drag region) + menu row (`Solus · View · Robot · Help`, bridge pill, search, bell, sign out); left rail Home / Workspace / Live Bench / SOL, accent "+" Store, separator, extension tabs; Billing/Settings/avatar at bottom. No app-wide right sidebar (per-screen: `NodeSidebar` in Workspace, `ContextPanel`+`UsagePanel` in SOL). The "Search … ⌘K" box is a static `<div>` — no input, no handler, no ⌘K listener anywhere (`rg "key === 'k'"` → none).

### Q69 — Component trees
Status: exists
Where:
- **Home** — `features/workspace/HomeScreen.tsx` (327): TeamStrip 234, ProjectGrid 124, `team/MembersPanel.tsx` 540 (LiveMembers, InviteModal), TeamActivityPanel 99, ConnectedAccountsCard 512 (→ AccountRows 478, `onboarding/ConnectWizardModal`), SolusCard 312, `project/ProjectFolderCard.tsx` 398, HomeTeamModals 188, `modals.tsx` 307; hooks useHomeData 291, useHomeTeam 537.
- **Workspace** — `features/graph/WorkspaceScreen.tsx` (728): `robots/RobotTopologyGraph.tsx` 243 → `navigation/GraphNavigator.tsx` 270 (GraphCard 327, GraphLinks 173, graphIndex 132, layout 96, useGraphNavigation 386, GraphSuggestions 144); `sidebar/NodeSidebar.tsx` 190; WorkspaceAdd 119; `hardware/PendingDeviceCards` 47; WidgetRegistrationContent 78; AccountNodeContent 25; hooks useWorkspaceGraph 159, useWorkspaceLayout 326, useSolusNodes 199, usePhysicalRobots 143, useWorkspaceEvents 151, `workspace/focusStore` 194.
- **Live Bench** — `features/bench/BenchScreen.tsx` (226): DeviceBenchView 570, BenchCanvasHost 164 → `canvas/WidgetCanvas`, BenchRealtime 213, ConnectDeviceModal 122, useActiveBenchSessions 61, useExternalBenchDevices 50; plus SignalWidget, SavedRobotConnections, `scene/`, `runs/`, `bench.css` 386.
- **SOL** — `features/sol/SolScreen.tsx` (115): SolChat 665, ChatsSidebar 362, ContextPanel 238, UsagePanel 184, useSolChat 118; separate window `SolWindow.tsx` 143.
- **Store** — `features/extensions/StoreScreen.tsx` (259): ExtensionCard 171, ExtensionDetail 279 (+`detail/`), CreateExtensionModal 42, extensionLogic 410, useExtensions 191, extensionsStore 18; first-party `bom/BomScreen.tsx` 246 via `firstParty.ts`.

Note: Workspace mounts the graph through `RobotTopologyGraph`, not directly. Extension page views render in-shell as `ext-page`.

### Q70 — Styling
Status: exists
Where: `assets/main.css` 658 (Tailwind v4 `@import 'tailwindcss'` + `@theme`), `theme/tokens.constants.ts` 138, `theme/applyTheme.ts` 51, `store/settingsStore.ts` 38, `components/ui/` (15 primitives), 10 feature CSS files (`graph/navigation/navigation.css` 733, `bench/bench.css` 386, `graph/hardware/hardware.css` 202, `sol/ConfirmationCard.css` 189, …).
Note: Tailwind 4 utilities map to CSS vars set at runtime by `applyTheme`, but the dominant idiom is inline `style={}` with `var(--…)` (1,265 inline styles vs 294 `className`); no CSS modules / styled-components. 5 theme presets (dark default, light, dkplus, monokai, solarized) × 4 accents (amber default) × compact/regular density, persisted in localStorage `solus_settings_v1`; domain colours `--sw/--ee/--me/--rt`. IBM Plex Sans/Mono via `@fontsource`. Icons: hand-rolled inline SVG in `components/ui/icons.constants.tsx`, no icon library; integration logos in `assets/integrations/`. Primitives: Avatar, Button, Card, ContextMenu, DomainChip, Field, KV, Mono, Segmented, SolusLogo, Spark, Spinner, Switch, Wordmark, icons. **No Modal/Dialog primitive**; no `design-system/` folder.

### Q71 — Styled vs. placeholder
Status: partial
Where: code + `demo-screenshots/*.jpg` (15, dated 2026-09-16) + `docs/qa/COMPLETION_SOLUSDEV-262-ui-phases.md`
Note: Styled: shell chrome, Home, Workspace inspector empty state, Live Bench "one view", SOL screen, Store/BOM, Billing (490), Settings (90 + `sections/`). Placeholder/unfinished: top-bar search + ⌘K (decorative); Workspace graph illegible at "Fit" (`02-workspace-system-graph.jpg`), saved "matrix" layouts deliberately kept (262 report l.109); SOL context panel mostly empty-state copy; live camera/LiDAR shows "unavailable" (no live media API); describe-a-part category is a local fallback labelled "suggestion", not a SOL call. No "coming soon"/lorem/stub screens found by rg.

### Q72 — Home
Status: exists
Where: Q69 Home tree + `connectedAccounts.ts` 143, `AccountRows.tsx` 478
Note: Home (SOLUSDEV-242 H1–H5): active-team strip (switcher only with >1 team), project grid with "New project" tile + archived projects, members with roles, one-time-token invites / join by token, create/rename/leave/delete team, team activity feed, "Connected accounts" card grouped by domain (logo, status, `account_login` username, Revoke/Disconnect/Stop; registry-driven; connect wizard = OAuth → document picking, file upload for export tools, Start for simulators), project `.solus` card, local-folder card, explicit offline / team-gone states, no demo data.

### Q73 — Store and widgets
Status: exists (ST1–ST5 on main)
Where: `features/extensions/` (incl. `pinsStore.ts`, `firstParty.ts`), `features/workspace/extensionRail.ts` 156, `useExtensionRail.ts` 192, `features/bom/` (BomScreen 246, BomTable 151, AddRowModal 124, bomLogic 140, useBom 132), `features/sourcing/`, `features/canvas/`, `features/workspace/widget.contract.ts` 91, `packages/shared-types/src/extension-manifest.ts` (`views.widget` l.535, `views.page` l.546).
Note: Extension = `extension.toml` bundle (ADR-035), installed per project. Rail tab (ST3) only if installed + enabled + not team-blocked + declares `[views.page]`; tabs after the Store separator, pinned first; pins ("Pin for all projects") are server-backed, a pinned-but-uninstalled extension still gets a tab saying so. Pages (ST4): community = sandboxed frame; first-party = in-repo React keyed by slug (`FIRST_PARTY_PAGES = { bom: BomScreen }`). `[views.widget]` widgets appear only in Live Bench's "+ Add widget" picker (`BenchCanvasHost` → `WidgetCanvas`), implementing `WidgetProps` (focus + neighbourhood in, closed action set out). BOM: one row per physical part with lifecycle, plus purchase/raw-material rows. Sourcing (ST5): requirement → metered candidate job → compare → part enters graph as PLANNED; also via Add › Hardware › Sourced. EXT-20 dev registrations get a `DEV` mark.

### Q74 — Known UI problems
Status: partial
Where:
| Problem | Source | State |
|---|---|---|
| Stale channels vanish on remount (WS window drops samples > 8 s old) | `docs/qa/STATUS_SOLUSDEV-262-demo.md` l.288–293 | **Open** |
| Slow/disappearing telemetry (2.5 s polling, anomaly requests blocking readings, 8 s card removal, duplicated `/api/v1` prefix) | same l.242–248 | Fixed in software; leader-arm physical USB disconnects remain |
| Blank native window on Add → Hardware (React max update depth) | same l.169–180 | Fixed + regression test |
| Graph unreadable at Fit; old matrix layouts kept | 262 completion l.109; screenshot 02 | Open by design |
| Hardware panel overflows 33px at 1280×720 | 262 completion | Open (fits at 1280×800) |
| Live camera/LiDAR | 262 completion | No API |
| Describe category is a local fallback | 262 completion | Open |
| "MCU unknown" | `COWORK_QA_SOLUSDEV-72-local-connections.md` l.22 | **Intended** — never guesses an MCU |
| Empty robot name | `COMPLETION_SOLUSDEV-250.md` l.10 | Reported fixed (`63090f6`) |
| Top-bar search does nothing | `ShellChrome.tsx` l.14–37 | Open, undocumented |
| Full demo / graph acceptance | `STATUS_SOLUSDEV-262-demo.md` l.4, 84, 227 | "not yet accepted" |

Note: "Laggy" appears in no QA doc (the telemetry rows are the lag reports). "Unassigned notes": **not determined** — only unassigned *parts* exist, as a designed list.

### Q75 — Desktop build
Status: partial
Where: `apps/desktop/package.json`, `electron.vite.config.ts`, `electron-builder.yml`
Note: `npx electron-vite build` exit 0 in 3.4 s → gitignored `apps/desktop/out/`, `git status` clean after (main 214 kB, preload 22 kB, renderer 3.23 MB, lazy ScenePanel 1.17 MB, RunsView 35 kB). `npm run build` not run (its `gen:api` rewrites tracked `lib/api/schema.ts`). `npm run typecheck` **fails on this machine**: `src/main/diagnostics/sentrySink.ts(90,17): TS2307 Cannot find module '@sentry/electron/main'` — in package.json + lockfile but missing from `node_modules` (stale local install since SOLUSDEV-311); `typecheck:web` passes. Launchability **not determined** (not launched). Packager not run (downloads from GitHub; repo-root `dist/companion/` needed by `extraResources` is absent). Electron 39.2.6, React 19.2.1 (web: 19.2.4), Vite 7.2.6 via electron-vite 5.0.0, TS 5.9.3, Tailwind 4.3.1, Zustand 5, react-router-dom 7.18 (HashRouter), three 0.183.2, react-markdown 10 + remark-gfm. Targets: win (nsis), mac (dmg, unsigned, `notarize: false`), linux (AppImage, snap, deb). This machine: linux aarch64.


## I. Honest gaps

### Q76 — Doc claims the code doesn't meet / deferral markers
Status: exists
Where: counts of `rg -i -c "deferred|not yet|TODO|placeholder|stub|FIXME|XXX"` (line hits, includes tests and vendored trees):

| dir | hits |
|---|---|
| packages/ | 249 |
| apps/ | 400 (mostly vitest `stubApi`/`vi.stubGlobal`/`placeholder=` props) |
| libs/ | 2 |
| docs/ | 323 (top: docs/api/API.md 18, docs/contracts/metadata-extraction.md 11) |
| livebench/ | 4 |
| integrations/ | 951 (≈all in vendored `integrations/mcp/altium/upstream/**`) |

Twenty most consequential (source, non-test):

| # | line | reading |
|---|---|---|
| 1 | `packages/api/src/solus_api/contracts/action_gate.py:17` "That work is **not yet on** main. On main today the gate is a flat fail-closed refusal (runtime.py:162)" | STALE contract docstring: `agent/confirmations.py` and `gate_tool_call` (park/approve) ARE on main; the contract still says they aren't. |
| 2 | `packages/api/src/solus_api/agent/runtime.py:737` "the confirmation flow is not yet available" | Fallback refusal text when `build_dispatch` gets no `park`; any runner not wired with `park` refuses every `requires_confirmation` tool. |
| 3 | `packages/api/src/solus_api/routers/sol.py:1018` "Redis/ARQ not yet deployed for this app … the cap FAILS OPEN inside the gateway" | SOL frequency cap/cost hook fail open when `app.state.redis` absent (.env does set SOLUS_REDIS_URL; whether lifespan populates app.state.redis: not determined). |
| 4 | `packages/api/src/solus_api/orchestration/providers.py:21` "Per-provider circuit breakers remain deferred" | CLAUDE.md §7 requires circuit breakers per provider; not built. |
| 5 | `packages/api/src/solus_api/orchestration/__init__.py:17` "failed debits deferred to the ARQ reconciliation job" | Debit reconciliation depends on ARQ, which per #3 isn't deployed for the app. |
| 6 | `packages/api/src/solus_api/fingerprint/visual.py:27,112,118` "ArtifactRef byte-fetch is deferred (W0-04)" | Vision fingerprint skips artifact images; plus `fingerprint_vision_enabled=False` by default. |
| 7 | `docs/contracts/agent-tool.md:366` "Desktop / Environment tool kinds — Documented, not built" | Contract names tool kinds with no implementation. |
| 8 | `docs/contracts/connector-interface.md:34,285` "LiveConnection — DOCUMENTED SIBLING, NOT built" | Doc says not built, but `connectors/live.py:79` has a "roster placeholder … connects to nothing" — a placeholder, not a real LiveConnection. |
| 9 | `docs/contracts/sol-interface.md:95,192` "Streaming extension (designed-for, NOT built)" / telemetry stream-of-summaries not built | SOL over live telemetry streams is design-only per the contract. |
| 10 | `packages/api/src/solus_api/connectors/altium.py:35` "proprietary path is a scaffolded post-launch stub" | Altium connector's native path is a stub. |
| 11 | `packages/api/src/solus_api/services/onshape_write_sync.py:135` `return {"status": "deferred"}` / `agent/onshape_turn_sync.py:66` | Onshape writes report graph sync as deferred (ADR-038 quiet period, 90 s); graph lags writes by design. |
| 12 | `packages/api/src/solus_api/connectors/worker.py:1099,1266` "registration was explicitly deferred to T4b" | Artifact registration from sync not done (also `services/artifacts.py:317`). |
| 13 | `packages/api/src/solus_api/connectors/mechanical.py:67` STL → `cad_body` "deferred" | STL files produce no product-identity entity. |
| 14 | `docs/architecture/solus-folder.md:99` `instructions.md # team notes for SOL — DEFERRED (§6)` | No team-instructions file for SOL in `.solus`. |
| 15 | `docs/api/API-implementation.md:728` "`POST /graph/query`, MCP server, presence topic — [DEFERRED]" | No generic graph query route. |
| 16 | `docs/api/hardware.md:498` "live SSH are deferred; injected SSH/helper fixtures establish only software behavior" | Onboard-Linux deployment is fixture-only. |
| 17 | `docs/api/workspace.md:70` "Generic manual CRUD remains deferred" | Manual graph entity CRUD limited to one subtype. |
| 18 | `docs/architecture/hardware-onboarding.md:266` "Arbitrary extraction confirmation is deferred" | Datasheet/extraction → part confirmation limited to explicit selections. |
| 19 | `packages/api/src/solus_api/routers/billing.py:8` "billing provider routes were DEFERRED pending human decisions" | Only the Stripe webhook route was authorized (later 313 added admin ops). |
| 20 | `packages/api/src/solus_api/graph/neighborhood.py:14` "ADR-027 deferred a graph database" | Graph traversal is iterated SQL frontier, not a graph DB/recursive CTE. |

Note: integrations/github, gitlab, kicad, ros directories are EMPTY on main (onshape has 40 KB); connectors live in `packages/api/src/solus_api/connectors/` and MCP forks in `integrations/mcp/` (535 MB). CLAUDE.md §3 map is stale on this point.

### Q77 — Feature flags
Status: exists
Where: `packages/api/src/solus_api/core/config.py` (376 lines, pydantic-settings, `env_prefix="SOLUS_"`, reads repo-root `.env`); companion `packages/companion/src/solus_companion/config.py`; desktop `apps/desktop/src/main/**`.

| flag (env) | default | dev .env | effect |
|---|---|---|---|
| SOLUS_APP_ENV | `dev` | dev | env label |
| SOLUS_AUTO_CREATE_TABLES | False | false | create_all instead of alembic |
| SOLUS_SYNC_INLINE | False | **true** | connector syncs run in-process instead of ARQ |
| SOLUS_FINGERPRINT_LLM_ENABLED | False | false | LLM signal in fingerprint |
| SOLUS_FINGERPRINT_EMBEDDING_ENABLED | False | false | embedding signal in fingerprint |
| SOLUS_FINGERPRINT_VISION_ENABLED | False | false | vision signal in fingerprint |
| SOLUS_REDIS_URL | None | set | Redis (rate caps/ARQ) |
| SOLUS_SECRETS_BACKEND | None (auto) | — | force aws/local/memory |
| SOLUS_ONSHAPE_QUOTA_POOL | `owner` | — | Onshape quota accounting pool |
| SOLUS_ONSHAPE_APP_DISTRIBUTION | `private` | — | private vs app_store |
| SOLUS_ONSHAPE_ANNUAL_CALL_ALLOWANCE | 2500 | — | quota budget |
| SOLUS_ONSHAPE_QUIET_PERIOD_SECONDS | 90 (0–600) | — | ADR-038 deferred sync |
| SOLUS_INTEGRATION_DEGRADE_RATIO | 0.7 | — | cache-only degrade threshold |
| SOLUS_INTEGRATION_*_TTL_SECONDS | signal 3600 / listing 7d / payload 30d | — | httpcache TTLs |
| SOLUS_STAFF_USER_IDS | "" | — | staff (UUID-validated) |
| SOLUS_DEVELOPMENT_UNLIMITED_CREDIT_USER_IDS | "" | — | dev unlimited credits |
| SOLUS_TRIAL_CREDIT_GRANT / TRIAL_DAYS / STRIPE_TRIAL_DAYS | 1000 / 30 / 14 | set | billing |
| SOLUS_RATE_LIMIT_PER_MINUTE / WRITE_ / CLASSIFY_ | 1200 / 120 / 600 | classify set | rate limits |
| SOLUS_BRIDGE_* (≈20 knobs) | e.g. hello 262144 B, control 16384 B, tool timeout 30 s, max team sessions 10 | — | companion bridge bounds |
| SOLUS_ARTIFACT_* / CAD_STORE_* | 8 MiB artifact, 256 MiB CAD object | — | storage bounds |
| SOLUS_EXTENSION_*_PER_* | various | — | extension rate limits |
| SOLUS_BENCH_DATA_ROOT / ARTIFACT_LOCAL_ROOT / CAD_STORE_LOCAL_ROOT | None | — | local storage roots |
| SOLUS_COMPANION_WORKSPACE / _INTEGRATIONS_ROOT / _ALLOWED_HOSTS / _TOKEN / _INSTANCE_FILE / _URL / _DEV_CMD | unset | — | companion config |
| SOLUS_NODE_BIN, SOLUS_MCP_PYTHON, SOLUS_MCP_FORK_PYTHON | unset | — | runtime binaries for MCP forks |
| SOLUS_DEBUG_GESTURE (desktop `main/hotkeys/index.ts:197`) | unset | — | logs gesture samples |
| SOLUS_TOKEN (livebench `sim/isaac_direct.py:153`) | unset | — | Isaac direct auth |
| HF_LEROBOT_CALIBRATION (lerobot plugin) | `~/.cache/huggingface/lerobot/calibration` | — | calibration path |
| VITE_API_BASE_URL / VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY | unset → dev auth bypass when Supabase URL absent | — | desktop renderer |

Note: `scripts/qa_approver.py` is an "explicit, inactive dev QA client" — not a flag, never imported by startup.

### Q78 — Vendor leakage outside ratchets
Status: partial (ratchets cover narrow trees; leakage exists elsewhere)
Where: ratchets and their scanned trees:

| ratchet file | scans | regex |
|---|---|---|
| `livebench/tests/lb_vendor_hygiene_test.py` | `livebench/src/**` except `plugins/`,`definitions/` (no allowlist) | `\b(feetech|dynamixel|lerobot|sts3215|sts3250|scs0009|so-?10[01]|px4|pixhawk|odrive|myactuator|mavlink|unitree|ur5e?|arduino|teensy|esp32|ch343|cp210x|ft232|pl2303|xl330|xm430|robotis)\b` /i |
| `packages/api/tests/test_vendor_hygiene_api.py` | `solus_api/hardware/*.py`, `solus_api/livebench/*.py` (non-recursive; not `hardware/definitions/`) + 7 Isaac connection files | same regex |
| `apps/desktop/src/renderer/src/features/graph/hardware/vendorHygiene.test.ts` | `features/graph/hardware/*.ts(x)` (non-recursive) + `widgets/livebench/recognition/` | same + `ttyUSB|ttyACM|\.ino` |
| ~12 per-module tests (`lb_registries_test.py:84`, `lb_driver_test.py:143`, …) | one file each | short regex `feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink` |
| `integrations/mcp/tests/test_vendor_hygiene.py` | different concern: vendored MCP trees excluded from lint/stdio launchers pinned | — |

Same regex over unscanned trees (excluding tests and `hardware/definitions/`):

```
packages/api/src/solus_api: 75 hits in 25 files   (53 of them in corpus/ content+hosts+domains, legitimate citations)
  connectors/local_folder.py:11   ToolName Literal["kicad","altium","cad","arduino","python"]; source_key f"arduino:{dir}"; projection "arduino-observations-v1"
  corpus/domains.py:6             "arduino","sts3215","feetech","so-101","so101","dynamixel" (classifier keywords)
  corpus/enums.py:1               mcu_family {"avr","stm32","esp32",...}
  agent/tools/knowledge.py:3      "code.arduino_prepare/compile/upload" tool ids
  toolkb/catalog.py:2             docs.arduino.cc/arduino-cli
  agent/research.py:1             "mavlink" in a bus-word list
apps/desktop/src: 5 hits in 4 files
  features/project/localFolder.constants.ts:30,64     'Arduino' copy + arduino badge
  lib/api/resources.localfolder.ts:16
  features/graph/robots/FirmwareTelemetryOffer.tsx:52 item.tool === 'arduino' && path.endsWith('.ino')
  features/graph/robots/HostAttachmentCard.tsx:80     ['python','arduino'].includes(item.tool)
libs/: 11 hits in 4 files (solus-telemetry Arduino library — vendor-specific by purpose)
packages/companion/src, packages/contracts, packages/shared-types/src: 0
```
Note: the real leak is "arduino" as a first-class tool kind in the local-folder connector and in `features/graph/robots/*` (outside the desktop ratchet's non-recursive `features/graph/hardware/` scope). Corpus hits are citations by design.

### Q79 — Unverified on hardware / live
Status: exists (list compiled from completion reports on main; the reports' work is on main only where its ticket commit is — 260/262 are in `git log origin/main`)
Where: `docs/qa/COMPLETION_*.md`, `docs/qa/REVIEW_SOLUSDEV-251_premerge.md`, `docs/qa/ACCEPTANCE_SOLUSDEV-261.md`
- 260: both-arms / USB port swap / unplug-reconnect — unverified (leader servos did not answer); import+reconciliation — fixtures; SOL field edit — fixtures (live SOL blocked by provider failure); I3 environment install — live unverified; Brave/page citations — no successful cited live turn; four-document gate — unverified; embedding generation — unverified.
- 262: actual arm geometry + confirmed live joint mappings in scene; real Onshape dimension change → scene refresh; live anomaly markers; camera/LiDAR (none connected); induced stall and paired clamp experiments (synthetic only); live narration; external-control overlay pointing; Uno flash review (402 budget, never reached a card); live SSH onboard deployment; USB swap — all unverified/deferred.
- 252: native key-hook event delivery ("unverified anywhere"); real-window scroll pinning.
- 251 (I4 SOL-in-tools): Onshape write round-trip not run live; 251 premerge review: Python suite could not run (no Postgres), desktop vitest/typecheck not run, A3 (machine-local bindings) not built.
- 261: assembly insertion returned `mutation_unverified` after vendor 503; GitHub OAuth/sync not exercised (repo node seeded); GitLab excluded; Variable Studio writes + automatic graph refresh unverified (also COWORK_QA_integration-check-phase1.md:12, COWORK_QA_kicad-development.md:212 KiCad post-write refresh unverified).
- 248: physical reconnect gap not exercised; Elegoo car never attached (250, fixture twin only).
- 228 RBT-01: live Dynamixel bus NOT RUN; live CAN (ODrive) NOT RUN.
- 121 LB-01: live `gz sim` NOT RUN; 105 Foxglove live robot bridge NOT RUN; 123 LB-03 live flash + scp NOT RUN; 124 LB-04 fault induction on a running robot NOT RUN.
- 241 corpus C2/C3: `-m live` model-judged eval not run.
- 242 H2 / 241 I1: real browser OAuth completion not run.
- 246 ST1/ST3: Store UI against API and repo `[ext.bom]` path not exercised live.
- HANDOFF_featurescript-mcp: Onshape Labs admin-gating unverified.
- model-routing gateway: terra/luna context windows marked UNVERIFIED in models.yaml.
- 313: Stripe subscription-clearing behaviours unverified against live Stripe.


### Q80 — What surprised me (opinion)
Status: opinion
Where: —
Note: These are ranked by how much each one should change the three planned prompts.
1. **There are almost no cross-domain edges.** The checkers read `drives`, `reads_from` and `powers`, but nothing writes them. No route creates an edge. `link_from_fingerprint`/`scan_project` run only in tests: the dev DB has 1 canonical part and 2 `same_as` edges. The impact engine has no production caller. Any "SOL depth across domains" prompt has to start by **producing semantic edges, with evidence**. The edge table already has `confidence`, `origin` and `attrs`, but no `created_by`, no evidence schema, and `domain_pair` comes in two formats (Q10, Q11, Q12, Q51).
2. **SOL's window is 4,000 tokens, and chat never reaches Claude.** The per-layer caps add up to about 14k but the total cap is 4k (`reason.py:64`). The route type is pinned to GENERAL, so chat goes to OpenAI. Expanding SOL's understanding is first a context-budget and routing problem (Q38, Q39).
3. **There are no Python tests in CI.** Every ratchet the prompts will lean on is advisory until `test:python` returns. Whether the API suite is green on main is unknown (Q5, Q6).
4. **Build mode auto-executes writes.** About 24 tools run without a card after two identical previews. Prompts that assume "every write shows a consent card" are wrong; decide whether that relaxation stays (Q40, Q41, Q67).
5. **A robot has two structures.** The brain → bus → device overlay (`hardware_brain`/`hardware_bus`, `hardware_topology_member`) drives the canvas. The seven-category tree plus the v2 entity-owned config remains the "compatibility authority". The graph prompt must pick one owner (Q14, Q22, Q30).
6. **Retrieval is dark.** 0 of 2,832 entities are embedded and `corpus_chunk` is empty in dev, so search is ILIKE. The embed seam is still unmetered, there are no `/` commands and no symbol index. A search or `@` feature is net-new work (Q15, Q48).
7. **`.solus` is server-side rows, not files.** It has 5 fixed sections: no goals, constraints, members or history. ADR-034's repo `.solus/parts/*.toml` is not read. Config is overwritten in place, with no history. Auto error-filing is live but has no dedupe. `~/.solus/preferences.json` already reaches every turn (Q19–Q28).
8. **Live Bench state lives in odd places.** The API process opens the serial ports (real mode needs a local API). Observer events sit in an in-memory ring with no Finding table. Scene poses are kept only in localStorage. The scene is three.js with no mujoco-wasm. Nothing produces a sim-expected value (Q53, Q55, Q56, Q59).
9. **The UI is hard to restyle.** The shell has no routes (an 803-line `useState` switch). There are 1,265 inline `style={}` versus 294 `className`. No Modal primitive exists. The ⌘K search is decorative. The graph shows one containment level at a time with a 24-card cap and spiral placement, and saved matrix layouts are kept (Q13, Q68, Q70, Q71).
10. **Docs describe things that aren't there, a fourth time.** The root map points at empty directories. SPEC.md has the hotkeys reversed. The action-gate contract says the gate is "not yet on main" when it is. ADR-035 is numbered twice. 260, 261 and 262 (about 1.7k files) landed as subject-only squashes, so `docs/qa/` is the only changelog (Q8, Q76).

## J. Appendices

### J1 — tree (no `tree` binary on this machine; equivalent `find packages apps libs -maxdepth 3` with the same prunes + egg-info/caches/out; 622 lines, TRUNCATED at 400)
```
apps
apps/desktop
apps/desktop/build
apps/desktop/build/entitlements.mac.plist
apps/desktop/build/icon.icns
apps/desktop/build/icon.ico
apps/desktop/build/icon.png
apps/desktop/CLAUDE.md
apps/desktop/docs
apps/desktop/docs/companion-packaging.md
apps/desktop/.editorconfig
apps/desktop/electron-builder.yml
apps/desktop/electron.vite.config.ts
apps/desktop/.env
apps/desktop/eslint.config.mjs
apps/desktop/.gitignore
apps/desktop/.npmrc
apps/desktop/package.json
apps/desktop/pnpm-lock.yaml
apps/desktop/.prettierignore
apps/desktop/.prettierrc.yaml
apps/desktop/README.md
apps/desktop/resources
apps/desktop/resources/icon.png
apps/desktop/src
apps/desktop/src/main
apps/desktop/src/preload
apps/desktop/src/renderer
apps/desktop/test
apps/desktop/test/setup.ts
apps/desktop/tsconfig.json
apps/desktop/tsconfig.node.json
apps/desktop/tsconfig.node.tsbuildinfo
apps/desktop/tsconfig.web.json
apps/desktop/tsconfig.web.tsbuildinfo
apps/desktop/vitest.config.ts
apps/desktop/.vscode
apps/desktop/.vscode/extensions.json
apps/desktop/.vscode/launch.json
apps/desktop/.vscode/settings.json
apps/web
apps/web/app
apps/web/app/api
apps/web/app/landing.css
apps/web/app/layout.js
apps/web/app/page.js
apps/web/components
apps/web/components/landing
apps/web/.gitignore
apps/web/lib
apps/web/lib/waitlist
apps/web/.next
apps/web/.next/app-path-routes-manifest.json
apps/web/.next/BUILD_ID
apps/web/.next/build-manifest.json
apps/web/.next/cache
apps/web/next.config.mjs
apps/web/.next/dev
apps/web/.next/diagnostics
apps/web/.next/export-marker.json
apps/web/.next/fallback-build-manifest.json
apps/web/.next/images-manifest.json
apps/web/.next/next-minimal-server.js.nft.json
apps/web/.next/next-server.js.nft.json
apps/web/.next/package.json
apps/web/.next/prerender-manifest.json
apps/web/.next/required-server-files.js
apps/web/.next/required-server-files.json
apps/web/.next/routes-manifest.json
apps/web/.next/server
apps/web/.next/static
apps/web/.next/trace
apps/web/.next/trace-build
apps/web/.next/turbopack
apps/web/.next/types
apps/web/package.json
apps/web/public
apps/web/public/images
apps/web/README.md
apps/web/vercel.json
libs
libs/solus-telemetry
libs/solus-telemetry/arduino
libs/solus-telemetry/arduino/examples
libs/solus-telemetry/arduino/extras
libs/solus-telemetry/arduino/library.properties
libs/solus-telemetry/arduino/src
libs/solus-telemetry/LICENSE
libs/solus-telemetry/micropython
libs/solus-telemetry/micropython/__init__.py
libs/solus-telemetry/micropython/solus_telemetry.py
libs/solus-telemetry/python
libs/solus-telemetry/python/pyproject.toml
libs/solus-telemetry/python/src
libs/solus-telemetry/python/tests
libs/solus-telemetry/README.md
packages
packages/api
packages/api/alembic.ini
packages/api/.env
packages/api/.gitignore
packages/api/migrations
packages/api/migrations/env.py
packages/api/migrations/hardware_config_backfill.py
packages/api/migrations/script.py.mako
packages/api/migrations/versions
packages/api/openapi.json
packages/api/pyproject.toml
packages/api/scripts
packages/api/scripts/perf_rag_retrieval.py
packages/api/src
packages/api/src/solus_api
packages/api/tests
packages/api/tests/bom
packages/api/tests/conftest.py
packages/api/tests/contracts
packages/api/tests/corpus
packages/api/tests/fixtures
packages/api/tests/sourcing
packages/api/tests/telemetry_corpus.py
packages/api/tests/test_access_modes.py
packages/api/tests/test_account_deletion.py
packages/api/tests/test_account_deletion_service.py
packages/api/tests/test_account_deletion_stripe.py
packages/api/tests/test_account_hosted.py
packages/api/tests/test_activity.py
packages/api/tests/test_admin_operations.py
packages/api/tests/test_admin_operations_stripe.py
packages/api/tests/test_admin_projection.py
packages/api/tests/test_admin_validation.py
packages/api/tests/test_allowlist.py
packages/api/tests/test_altium_connector.py
packages/api/tests/test_arduino_observations.py
packages/api/tests/test_artifact_retention.py
packages/api/tests/test_artifacts.py
packages/api/tests/test_artifacts_service.py
packages/api/tests/test_artifact_store.py
packages/api/tests/test_artifact_upload.py
packages/api/tests/test_attributes.py
packages/api/tests/test_bench_external_streams.py
packages/api/tests/test_bench_focus.py
packages/api/tests/test_bench_robot_provider.py
packages/api/tests/test_bench_router.py
packages/api/tests/test_bench_runs.py
packages/api/tests/test_bench_scene_cad_import.py
packages/api/tests/test_bench_scene.py
packages/api/tests/test_bench_scene_registry.py
packages/api/tests/test_bench_stream.py
packages/api/tests/test_billing_admin_migration.py
packages/api/tests/test_billing_checkout.py
packages/api/tests/test_billing_crons.py
packages/api/tests/test_billing_webhook_overrides.py
packages/api/tests/test_billing_webhook.py
packages/api/tests/test_bom_catalog_setup.py
packages/api/tests/test_bridge_allowlist.py
packages/api/tests/test_bridge_allowlist_url.py
packages/api/tests/test_bridge_artifacts.py
packages/api/tests/test_bridge_change_frame.py
packages/api/tests/test_bridge_credentials.py
packages/api/tests/test_bridge_e2e.py
packages/api/tests/test_bridge_hello_cap.py
packages/api/tests/test_bridge_platforms.py
packages/api/tests/test_bridge_previews.py
packages/api/tests/test_bridge.py
packages/api/tests/test_bridge_resync.py
packages/api/tests/test_bridge_status.py
packages/api/tests/test_bridge_tool.py
packages/api/tests/test_buffer.py
packages/api/tests/test_build_execution_policy.py
packages/api/tests/test_builtin.py
packages/api/tests/test_cad_purge.py
packages/api/tests/test_cad_purge_routes.py
packages/api/tests/test_cad_purge_worker.py
packages/api/tests/test_cad_store.py
packages/api/tests/test_cad_suggestions.py
packages/api/tests/test_checker_graphs.py
packages/api/tests/test_choice.py
packages/api/tests/test_code_content.py
packages/api/tests/test_codec.py
packages/api/tests/test_code_environment_adapter.py
packages/api/tests/test_code_environment.py
packages/api/tests/test_code_env.py
packages/api/tests/test_code_host.py
packages/api/tests/test_command_output.py
packages/api/tests/test_companion_deployment.py
packages/api/tests/test_comp_expiry.py
packages/api/tests/test_complexity_labels.py
packages/api/tests/test_complexity.py
packages/api/tests/test_config.py
packages/api/tests/test_config_sections_phase4.py
packages/api/tests/test_confirmation_restore.py
packages/api/tests/test_confirmations.py
packages/api/tests/test_connect_integration.py
packages/api/tests/test_connection_adoption.py
packages/api/tests/test_connection_health.py
packages/api/tests/test_connections.py
packages/api/tests/test_connector_conformance.py
packages/api/tests/test_connector_quota.py
packages/api/tests/test_consequences.py
packages/api/tests/test_context_layers.py
packages/api/tests/test_context.py
packages/api/tests/test_contracts_package.py
packages/api/tests/test_contracts.py
packages/api/tests/test_conversation.py
packages/api/tests/test_core.py
packages/api/tests/test_cost.py
packages/api/tests/test_credits.py
packages/api/tests/test_db.py
packages/api/tests/test_deps.py
packages/api/tests/test_detect_signal_names.py
packages/api/tests/test_development_credits.py
packages/api/tests/test_development_credit_views.py
packages/api/tests/test_device_watch.py
packages/api/tests/test_dev_launcher.py
packages/api/tests/test_document_tree_routes.py
packages/api/tests/test_eda.py
packages/api/tests/test_embeddings.py
packages/api/tests/test_engine.py
packages/api/tests/test_entities_prefix.py
packages/api/tests/test_entities.py
packages/api/tests/test_entities_search.py
packages/api/tests/test_entitlements.py
packages/api/tests/test_enums.py
packages/api/tests/test_environment.py
packages/api/tests/test_error_filing.py
packages/api/tests/test_errors_filing.py
packages/api/tests/test_errors.py
packages/api/tests/test_escalation.py
packages/api/tests/test_events_ingest.py
packages/api/tests/test_events.py
packages/api/tests/test_exec.py
packages/api/tests/test_export_acquisition.py
packages/api/tests/test_export_common.py
packages/api/tests/test_extension_bundle_download.py
packages/api/tests/test_extension_bundle.py
packages/api/tests/test_extension_bundle_store.py
packages/api/tests/test_extension_catalog.py
packages/api/tests/test_extension_checks.py
packages/api/tests/test_extension_credit_attribution.py
packages/api/tests/test_extension_install_isolation.py
packages/api/tests/test_extension_installs.py
packages/api/tests/test_extension_manifest.py
packages/api/tests/test_extension_permissions.py
packages/api/tests/test_extension_publish.py
packages/api/tests/test_extension_ratelimit.py
packages/api/tests/test_extension_red_team.py
packages/api/tests/test_extension_registry_models.py
packages/api/tests/test_extension_review_job.py
packages/api/tests/test_extension_review_status.py
packages/api/tests/test_extension_router_wiring.py
packages/api/tests/test_extension_settings_values.py
packages/api/tests/test_extension_svg.py
packages/api/tests/test_extension_team_policy.py
packages/api/tests/test_featurescript_preview.py
packages/api/tests/test_feeds.py
packages/api/tests/test_fingerprint_contract.py
packages/api/tests/test_fingerprint_eval.py
packages/api/tests/test_fingerprint_hardware_modalities.py
packages/api/tests/test_fingerprint_labels.py
packages/api/tests/test_firmware_presence.py
packages/api/tests/test_first_party_catalog.py
packages/api/tests/test_fixture_bundle_folder.py
packages/api/tests/test_force_confirmation.py
packages/api/tests/test_frames.py
packages/api/tests/test_gates.py
packages/api/tests/test_gateway.py
packages/api/tests/test_get_entity.py
packages/api/tests/test_github_connector.py
packages/api/tests/test_gitlab_connector.py
packages/api/tests/test_git_revisions.py
packages/api/tests/test_graph_live.py
packages/api/tests/test_graph_prune_qa.py
packages/api/tests/test_graph_read_scope.py
packages/api/tests/test_hardware_attach.py
packages/api/tests/test_hardware_config_migration.py
packages/api/tests/test_hardware_config.py
packages/api/tests/test_hardware_confirm_sources_phase3.py
packages/api/tests/test_hardware_connections.py
packages/api/tests/test_hardware_data_migration.py
packages/api/tests/test_hardware_detect.py
packages/api/tests/test_hardware_lifecycle_phase3.py
packages/api/tests/test_hardware_local_sources.py
packages/api/tests/test_hardware_migration_constraints.py
packages/api/tests/test_hardware_operations.py
packages/api/tests/test_hardware_ownership.py
packages/api/tests/test_hardware_repo_evidence.py
packages/api/tests/test_hardware_retired_config.py
packages/api/tests/test_hardware_roundtrip_regression.py
packages/api/tests/test_hardware_router.py
packages/api/tests/test_hardware_runtime_owner.py
packages/api/tests/test_hardware_runtime_roundtrip.py
packages/api/tests/test_hardware_source_integration.py
packages/api/tests/test_hardware_source_refs.py
packages/api/tests/test_hardware_topology.py
packages/api/tests/test_hosted_mcp_spec.py
packages/api/tests/test_hosted_oauth.py
packages/api/tests/test_hosted_routes.py
packages/api/tests/test_hosted_tool_build.py
packages/api/tests/test_host_topology.py
packages/api/tests/test_httpcache.py
packages/api/tests/test_impact_revision_scope.py
packages/api/tests/test_ingest.py
packages/api/tests/test_injection_corpus.py
packages/api/tests/test_integration_cache_durable.py
packages/api/tests/test_integration_cache_durable_scope.py
packages/api/tests/test_integration_cache.py
packages/api/tests/test_integration_setup.py
packages/api/tests/test_integrations.py
packages/api/tests/test_integrations_stack.py
packages/api/tests/test_interface.py
packages/api/tests/test_invites.py
packages/api/tests/test_isaac_connection.py
packages/api/tests/test_isaac_native_preview_budget.py
packages/api/tests/test_isaac_tools.py
packages/api/tests/test_jobs.py
packages/api/tests/test_kicad_acquisition_fallback.py
packages/api/tests/test_kicad_audit_cross_feature.py
packages/api/tests/test_kicad_audit_file_pick_ingest.py
packages/api/tests/test_kicad_audit_hostile_input.py
packages/api/tests/test_kicad_audit_isolation.py
packages/api/tests/test_kicad_audit_model_context.py
packages/api/tests/test_kicad_change_signal_graph.py
packages/api/tests/test_kicad_connector.py
packages/api/tests/test_kicad_formats.py
packages/api/tests/test_kicad_ingest_e2e.py
packages/api/tests/test_kicad_netlist.py
packages/api/tests/test_kicad_netlist_sexpr.py
packages/api/tests/test_kicad_pcb.py
packages/api/tests/test_kicad_reconcile.py
packages/api/tests/test_kicad_sexpr.py
packages/api/tests/test_knowledge.py
packages/api/tests/test_library.py
packages/api/tests/test_library_router.py
packages/api/tests/test_limits.py
packages/api/tests/test_linker.py
packages/api/tests/test_links.py
packages/api/tests/test_live_access.py
packages/api/tests/test_live_connection.py
packages/api/tests/test_live_events.py
packages/api/tests/test_live_hub_channels.py
packages/api/tests/test_live_kicad_write.py
packages/api/tests/test_live_onshape_write.py
packages/api/tests/test_live_publisher.py
packages/api/tests/test_live_smoke.py
packages/api/tests/test_live_streams.py
packages/api/tests/test_local_acquire.py
packages/api/tests/test_local_folder.py
packages/api/tests/test_local_folder_routes.py
packages/api/tests/test_local_links.py
packages/api/tests/test_local_tools.py
packages/api/tests/test_logging.py
packages/api/tests/test_machine_path_redaction.py
packages/api/tests/test_machine_writes.py
packages/api/tests/test_main.py
packages/api/tests/test_make_diagram.py
packages/api/tests/test_matcher.py
packages/api/tests/test_mcp_acquire_artifact.py
packages/api/tests/test_mcp_acquire.py
packages/api/tests/test_mcp_license.py
packages/api/tests/test_mcp_servers.py
packages/api/tests/test_mcp_tool.py
packages/api/tests/test_mcu_connection.py
packages/api/tests/test_mechanical.py
packages/api/tests/test_members.py
packages/api/tests/test_meta.py
packages/api/tests/test_models.py
packages/api/tests/test_modes.py
packages/api/tests/test_neighborhood.py
packages/api/tests/test_never_raises_groups.py
packages/api/tests/test_no_hardcoded_models.py
packages/api/tests/test_normalize.py
packages/api/tests/test_notifications.py
packages/api/tests/test_oauth_refresh.py
packages/api/tests/test_onshape_account_usage.py
packages/api/tests/test_onshape_application_quota.py
packages/api/tests/test_onshape_assembly_geometry.py
packages/api/tests/test_onshape_assembly_read.py
packages/api/tests/test_onshape_authoring.py
packages/api/tests/test_onshape_call_budget.py
packages/api/tests/test_onshape_circle_connector.py
packages/api/tests/test_onshape_confirmation.py
packages/api/tests/test_onshape_connector.py
packages/api/tests/test_onshape_cut.py
packages/api/tests/test_onshape_empty_elements.py
packages/api/tests/test_onshape_export_keys.py
packages/api/tests/test_onshape_fastened_geometry.py
packages/api/tests/test_onshape_fastened_repair.py
packages/api/tests/test_onshape_feature_parameter_specs.py
packages/api/tests/test_onshape_feature_spec_cache.py
packages/api/tests/test_onshape_freshness.py
packages/api/tests/test_onshape_geometry.py
packages/api/tests/test_onshape_guards.py
packages/api/tests/test_onshape_mate_offsets.py
packages/api/tests/test_onshape_mates.py
packages/api/tests/test_onshape_nested_inspection.py
packages/api/tests/test_onshape_nested_mates.py
packages/api/tests/test_onshape_occurrence_names.py
packages/api/tests/test_onshape_ops.py
packages/api/tests/test_onshape_pool.py
packages/api/tests/test_onshape_quiet.py
... [truncated: 222 more lines]
```

### J2 — git log --oneline -40 origin/main
```
da9204ff SOLUSDEV-313: ADR-023 clarification — staff limits_override merged per key over plan defaults
5360f2a5 SOLUSDEV-312: ADR-037 live channels (project, team, user change hints)
5a6ae0bc SOLUSDEV-311: accept client.error data events (closed, typed payload)
6b7faa19 Solusdev 262 livebench robo sol initial
7aadbb4f SOLUSDEV-400: add product showcase motion piece (orb morph, 12 bars @ 118 BPM)
52844231 SOLUSDEV-260: fix blank desktop window — rename deviceCard.ts to deviceCardRules.ts
09353979 add design stuff
2ffbf8b8 Solusdev 261 integration check
fb56b607 SOLUSDEV-300: rebuild the landing page from the Claude Design waitlist mock
de1eddd8 SOLUSDEV-260: 250-252, robot onboarding + graph + sol initial
1fa93715 SOLUSDEV-252: amend metadata-extraction contract — S-expression netlist...
3a90ab6f SOLUSDEV-249: INTEGRATIONS I2 — local folders as a graph source
02590af8 SOLUSDEV-244: ADR-034 amendment — root engineering preferences in ~/.solus/preferences.json
4fa1ce86 SOLUSDEV-248: physical robot node initial
d0737491 SOLUSDEV-242: Home as the cross-project surface — active-team project grid,...
3003d518 SOLUSDEV-242-test
22ca1688 SOLUSDEV-240: graph workspace w1
43e8a06e SOLUSDEV-241: CORPUS C1 — corpus scope, licensing policy, chunk schema
12d33aea SOLUSDEV-234: stop the desktop 429ing itself against the API
6c507dbb SOLUSDEV-235: EXT-05 bundle installer + developer mode
54179866 SOLUSDEV-167: featurescript mcp
37cc91ef SOLUSDEV-233: add filter-scoped total to activity feed meta
215b0f5c SOLUSDEV-167: governance gate — change-signal spine architecture + tier-1 doc amendments
72a96d15 SOLUSDEV-165: emit machine-readable connect stages; add cancel + result-returning connect hooks
c4430b2e SOLUSDEV-165: emit machine-readable connect stages; add cancel + result-returning connect hooks
0ddce887 SOLUSDEV-72: local source catalog + packet tap on the stream pump
2a0b9389 SOLUSDEV-165: emit machine-readable connect stages; add cancel + result-returning connect hooks
f9bf9b8e SOLUSDEV-64: retry Onshape 429s with bounded Retry-After backoff
c02bee00 SOLUSDEV-69: seed every env-sourced SecretStore ref via make seed-secrets
00d967ca SOLUSDEV-70: wire the graph screen — entity list, focus-driven inspector
ae8fe02c SOLUSDEV-69-orgy
a79aea83 SOLUSDEV-102: split project folder Open into VSCode and file-manager options
a9f3bca4 SOLUSDEV-114: fix Sources page crash on structured last_error
9506ac5e SOLUSDEV-136: CTR-08 extend Modality with hardware-recognition members...
af613d09 SOLUSDEV-222: worktree protocol, CODEOWNERS and the lane-ownership CI check
41cd8a35 SOLUSDEV-89: foundation-path E2E gate (signup→team→project→credited op)
4cc7a122 SOLUSDEV-100: restore the human-owned solus-contracts Python package
2bf34779 SOLUSDEV-83: add stripe-setup operator CLI (put-key/check/bootstrap)
875c016a SOLUSDEV-153+154
197b3ec5 SOLUSDEV-164: project hub landing + per-project Sources page
```

### J2 — alembic heads / alembic history | head -25 (run from packages/api via uv; scripts only, no DB)
```
a31300000001 (head)
---
a38000000001 -> a31300000001 (head), SOLUSDEV-313: subscription staff override/comp columns + Stripe cancel tombstones.
a26200000001 -> a38000000001, ADR-038 §1: durable CAD purge requests (delete-on-revocation that cannot be lost).
a26100000001 -> a26200000001, SOLUSDEV-262: additive physical connectivity from accepted CONFIG evidence.
a26000000005 -> a26100000001, SOLUSDEV-261 approved Code/Isaac terminal execution knowledge categories.
a26000000004 -> a26000000005, Index revision references for bounded cascade cleanup.
a26000000003 -> a26000000004, Personal source revision snapshots and per-user selections.
a26000000002 -> a26000000003, SOLUSDEV-260: enforce hardware subject invariants after validated backfill.
a25100000001 -> a26000000002, SOLUSDEV-260: backfill independent hardware subjects before constraints.
c7d8e9f0a1b2 -> a25100000001, SOLUSDEV-251: additive config subject/version and reviewed operation storage.
b4c5d6e7f8a9 -> c7d8e9f0a1b2, solusdev-249 add local source type
7e290e665c1f, f0a1b2c3d4e5 -> b4c5d6e7f8a9 (mergepoint), solusdev_244 merge hardware config (7e290e665c1f) and sourcing (f0a1b2c3d4e5) heads
8f1c2a7d4e90, f7a8b9c0d1e2 -> 7e290e665c1f (mergepoint), solusdev_248 merge onboarding and main
c7f242e9a842 -> 8f1c2a7d4e90, solusdev-248 R5: structured Hardware-configs entries and link suggestions.
a9c0d1e2f3b4 -> f0a1b2c3d4e5, SOLUSDEV-246 (STORE ST5): sourcing requests — one engine for two doors.
e1f2a3b4c5d6 -> a9c0d1e2f3b4, solusdev-241 CORPUS C2: corpus_chunk, corpus_citation, corpus_release (ADR-036)
f7a8b9c0d1e2 -> e1f2a3b4c5d6, SOLUSDEV-246 (STORE ST3): per-user extension pins — "Pin for all projects".
e6f7a8b9c0d1, c7f242e9a842 -> f7a8b9c0d1e2 (branchpoint) (mergepoint), Merge point: SOLUSDEV-246 (e6f7a8b9c0d1) and SOLUSDEV-242's workspace/solus-graph
chain (c7f242e9a842).
2cd33377eeb0, d5e6f7a8b9c0 -> e6f7a8b9c0d1 (mergepoint), Merge SOLUSDEV-240 (`project` domain) and SOLUSDEV-246 (`workspace` domain).
b6f242d8e731 -> c7f242e9a842 (branchpoint), solusdev-242 wrap existing Onshape graphs in stable document roots.
a3f242b9c610 -> b6f242d8e731, solusdev-242 backfill real .solus section and entry graph identities.
2cd33377eeb0 -> a3f242b9c610, solusdev-242 project-shared workspace coordinates
9a1c4e7d2b30, b7e2d4a9c1f0 -> 2cd33377eeb0 (branchpoint) (mergepoint), solusdev-240 merge connections + solus heads
c4d5e6f7a8b9 -> d5e6f7a8b9c0, SOLUSDEV-246 (STORE ST2, security review MEDIUM-2): singletons are unique.
b3f1c2d4e5a6 -> c4d5e6f7a8b9, SOLUSDEV-246 (STORE ST2 real-run fix): store v1 manifests as authored.
```


### J3 — dumps

Enums and models are verbatim in Q9 (graph_entity, Domain), Q10 (graph_edge), Q19 (SolusSection), Q20 (SolusEntryKind, SolusEntry), Q59 (session config field lists) and Q61 (connector contract). The edge-type grep is the Q10 table, the registered-tool table is in Q40, and the SSE frame types are in Q18. The per-section dumps follow.

### J3 — from section B
- Edge-type constants: CONFIGURES store.py:45; RELATION_SAME_AS linker.py:69, bom/rows.py:37; EVIDENCE_RELATION/RELATION/MEMBERSHIP topology.py:23-25; BINDING_RELATION bindings.py:16; CONTAINS local_folder.py:52, graph_nodes.py:40; REQUIRES local_folder.py:141; CONNECTED_TO eda.py:79; PART_OF mechanical.py:64; CLONE_OF local_links.py:32; DRIVES/READS_FROM/POWERS/CONNECTED_TO checkers/attributes.py:57-60. Full writer/reader sites in the Q10 table.
- SSE frame grep: graph/live.py:165 `graph.changed`, :188 `hardware.devices_changed`; routers/live.py:82,106,114,129,213; typed constructors live_publisher.py L139–388 (JobUpdated L242).
- wc -l (beyond Where fields): runtime.py 838, connectors/contracts.py 250, solus_contracts/connector.py 187, impact/engine.py 227, hardware/links.py 342, bindings.py 187, topology.py 406, topology_acceptance.py 199, store.py 699, ownership.py 152, hardware/runtime.py 149, presence.py 387, presence_topology.py 362, cad_suggestions.py 306, companion_deployment.py 330, solus_graph.py 227, physical_robots.py 294, local_links.py 144, simulation_models.py 159, neighborhood.py 288, read_scope.py 164, entities.py 339, events.py 250, attributes.py 112, rail_current.py 138, diagram/build.py 171, local_folder.py 658, code_host.py 147, github.py 459, gitlab.py 442, eda.py 417, mechanical.py 298, WorkspaceScreen.tsx 728, useGroupPositions.ts 77, liveStream.ts 79, workspace.ts 54.


### J3 — from section D

PLUGIN_MODULES roster (verbatim): see Q31 code block.

```
   294 packages/api/src/solus_api/services/physical_robots.py
   406 packages/api/src/solus_api/hardware/topology.py
   408 packages/api/src/solus_api/hardware/host_topology.py
   280 packages/api/src/solus_api/hardware/topology_proposals.py
   273 packages/api/src/solus_api/hardware/topology_observations.py
   165 packages/api/src/solus_api/hardware/topology_evidence.py
   199 packages/api/src/solus_api/hardware/topology_acceptance.py
   342 packages/api/src/solus_api/hardware/library.py
   322 packages/api/src/solus_api/hardware/library_router.py
    63 packages/api/src/solus_api/hardware/library_import.py
   902 packages/api/src/solus_api/hardware/detect.py
   382 packages/api/src/solus_api/hardware/config.py
   387 packages/api/src/solus_api/hardware/presence.py
   330 packages/api/src/solus_api/hardware/companion_deployment.py
   187 packages/api/src/solus_api/hardware/bindings.py
    99 packages/api/src/solus_api/graph/resolver.py
   507 packages/api/src/solus_api/agent/tools/read_document.py
    52 packages/api/src/solus_api/agent/tools/firmware_presence.py
    39 livebench/src/livebench/hardware/registries.py
   118 livebench/src/livebench/hardware/channel.py
    89 livebench/src/livebench/hardware/driver.py
   103 livebench/src/livebench/hardware/interrogator.py
   499 livebench/src/livebench/hardware/repo_config.py
   176 livebench/src/livebench/hardware/topology_extractors.py
   113 livebench/src/livebench/hardware/usb_serial.py
   143 livebench/src/livebench/hardware/usb_can.py
   142 livebench/src/livebench/hardware/network.py
   304 livebench/src/livebench/hardware/bluetooth.py
   414 livebench/src/livebench/hardware/detection.py
    60 livebench/src/livebench/plugins/__init__.py
   408 livebench/src/livebench/recognition/firmware.py
   156 livebench/src/livebench/recognition/active.py
   146 livebench/src/livebench/deploy/flash.py
   384 livebench/src/livebench/deploy/companion.py
   167 livebench/src/livebench/deploy/companion_remote.py
   507 livebench/src/livebench/local.py
   117 livebench/src/livebench/telemetry/reconnect.py
    99 apps/desktop/src/renderer/src/features/graph/hardware/HardwareAddPanel.tsx
   243 apps/desktop/src/renderer/src/features/graph/robots/RobotTopologyGraph.tsx
   101 libs/solus-telemetry/arduino/src/SolusTelemetry.cpp
   149 libs/solus-telemetry/micropython/solus_telemetry.py
   198 libs/solus-telemetry/python/src/solus_telemetry/http.py
   143 libs/solus-telemetry/python/src/solus_telemetry/__init__.py
   215 libs/solus-telemetry/python/src/solus_telemetry/mirror.py
  livebench total: 10620 lines across livebench/src/livebench
  hardware/ (API) total: 9027 lines
```


### J3 — from section E1

### Registered-tool table
See Q40 (it is the J3 table).

### Bridge allowlist roster (`integrations/mcp/*/allowlist.yaml`)
```
altium (11): GATED=['proj_set_parameter','sch_set_components_parameters'] UNGATED=['app_get_status','proj_get_path','proj_list_documents','proj_get_stats','proj_get_bom','proj_get_nets','proj_get_component_info','list_nets','export_netlist']
autocad (155): ALL GATED
brave (4): UNGATED=['brave_web_search','brave_llm_context','brave_news_search','brave_summarizer']
code (15): GATED=['create_environment','install','run','test','git_commit','git_push','arduino_prepare','arduino_compile','arduino_upload'] UNGATED=['probe_environment','plan','git_status','git_log','git_diff','arduino_probe']
fusion (0)
isaac (8): GATED=['start','stop','load_model','set_joint_limits','set_sensor_pose','run_routine'] UNGATED=['probe','status']
kicad (15): GATED=['create_schematic','add_symbol','add_wire','add_net_label','mark_no_connect','set_symbol_property'] UNGATED=['get_symbol_definition','get_schematic_geometry','check_erc','list_projects','get_project_structure','extract_project_netlist','analyze_schematic_connections','analyze_bom','export_netlist']
local (3): GATED=['open_in_tool'] UNGATED=['scan_folder','folder_digest']
machine (3): GATED=['read_file','write_file'] UNGATED=['read_code_file']
solidworks (62): ALL GATED
```

### wc -l of files named in E1 (paths under packages/api/src/solus_api unless noted)
```
orchestration: models.yaml 430, providers.py 901, gateway.py 530, config.py 357, embeddings.py 311, gates.py 226,
  cost.py 213, retry.py 204, resolution.py 177, __init__.py 162, type_estimator.py 108, complexity.py 100,
  router.py 67, enums.py 41, choice.py 32; routers/orchestration.py 133; routers/sol.py 1259
agent: runtime.py 1312, confirmations.py 730, context.py 577, prompt.py 481, research.py 354, connect_integration.py 314,
  screen.py 292, feeds.py 251, interfaces.py 242, errors_filing.py 235, stream.py 179, perf.py 175,
  execution_policy.py 174, conversation.py 173, reason.py 153, layers.py 128, command_output.py 118,
  onshape_turn_sync.py 115, history_evidence.py 110, modes.py 98, preferences.py 74, turn_limits.py 22
agent/tools: mcp_tool.py 712, hosted_tools.py 632, onshape_tools.py 619, solus_tools.py 546, read_document.py 507,
  isaac_tools.py 416, read_code_file.py 365, untrusted.py 259, builtin.py 250, remote_mcp.py 246, isaac_models.py 246,
  knowledge.py 221, mcp_servers.py 196, research_tool.py 192, make_diagram.py 189, registry.py 163, exec.py 151,
  machine_writes.py 149, shapes.py 147, bench_scene.py 136, get_entity.py 105, environment.py 92, solus_entry.py 86,
  tool.py 84, rail_current.py 71, companion_deployment.py 55, firmware_presence.py 52
agent/documents: extract.py 212, pdf.py 130, fetch.py 124
bridge/allowlist.py 265; connectors/onshape_ops.py 1247; fingerprint/visual.py 229
toolkb: schema 327, guard 317, router 263, sharing 230, guides 186, review 125, staleness 107, feedback 97, catalog 96, storage 71
apps/desktop/src/main: index.ts 804, sol-window/solWindow.ts 378, hotkeys/index.ts 243, capture/screenCapture.ts 201,
  sol-window/orbOverlayWire.ts 182, solSettings.ts 173, overlay/overlayWindow.ts 162, hotkeys/keyHook.ts 131,
  hotkeys/ctrlStateMachine.ts 114, gesture/circleDetector.ts 110, platform/capabilities.ts 110, hotkeys/globalHotkeys.ts 93,
  sol-window/nativeGuideTarget.ts 76, capture/activeWindow.ts 68, gesture/cursorSampler.ts 44
apps/desktop renderer guide/overlay: GuidePanel 218, GuideTasks 159, overlaySession 147, useNativeGuideHandoff 124,
  guideApi 98, overlayDecision 82, GuideOverlay 71, OverlayWindow 64, useGuide 44
integrations/mcp allowlists: autocad 473, solidworks 338, code 80, altium 63, kicad 63, fusion 40, isaac 38, machine 31, brave 29, local 20
packages/api/tests/test_sol_runtime.py 622
```

### models.yaml (verbatim, `packages/api/src/solus_api/orchestration/models.yaml`)
```yaml
# ============================================================================
# Model-orchestration config (ADR-026 / ADR-024). Validated by
# solus_api.orchestration.config.OrchestrationConfig.
#
# PROVISIONAL — calibrate `credits_per_dollar` / `margin_multiplier` from pilot
# data (ADR-024). Model identity lives ONLY here — never hardcoded in code.
# Swapping which model serves a role is a config edit.
#
# Model IDs & prices VERIFIED 2026-09-07 (SOLUSDEV-252) against provider docs:
#   - platform.claude.com/docs/en/about-claude/pricing + models overview (Anthropic)
#   - developers.openai.com/api/docs/pricing + /models/gpt-6-astra (OpenAI)
#   - ai.google.dev/gemini-api/docs/pricing (Google — last verified 2026-07-11)
# Exceptions are marked UNVERIFIED inline. Re-verify before production.
#
# Roles are named `<strength>_<tier>`. A role must be filled by exactly ONE
# catalog entry (enforced) so routing is deterministic. The matrix (SOLUSDEV-252,
# human-decided): hard general+code -> gpt-6-astra; standard code -> Claude Fable
# 5.1; standard general -> gpt-5.6-sol; trivial general -> gpt-5.6-luna; trivial
# code -> Claude Haiku 4.5; visual_log/long_context rows stay Gemini (ADR-029).
# Unreferenced catalog entries (claude-sonnet-5 as default_role fallback,
# claude-opus-4-8, gpt-5.6-terra) are BENCH roles: pointing any cell at them is
# a one-line edit here.
#
# Long-context (breakpoint) pricing: models whose provider charges more above
# an input-token threshold carry `long_context_threshold_tokens` +
# `price_in_long`/`price_out_long` (all three or none). Flat-priced models
# simply omit them. `cost.compute_call_credits` bills the long rates when
# tokens_in exceeds the threshold.
#
# `price_cached_in`: USD per 1M prompt-cache-READ tokens (must be <= price_in).
# Billed for `Usage.tokens_cached_in` below the breakpoint only — above it the
# whole call bills the long rates (no cached-long rate is modeled; over-bills,
# never under). `reasoning_effort`: the provider effort knob for that entry
# (OpenAI only today; Anthropic/Gemini adapters carry no thinking mapping yet).
#
# `accepts_images` (default true): every entry below is vision-capable, so none
# sets it. A text-only model MUST set `accepts_images: false` and may then fill
# only long_context roles — a GENERAL, CODE or VISUAL_LOG cell (any tier) or
# default_role pointing at it fails at config load (SOLUSDEV-252 S3 review M2).
# ============================================================================
version: 1

# --- Model catalog: concrete models + the role(s) each fills -----------------
# prices are USD per 1,000,000 tokens (price_unit below).
# Anthropic cache reads: 0.1x input (0.025x on Fable 5.1) — verified 2026-09-07.
catalog:
  - provider: anthropic
    name: claude-haiku-4-5
    price_in: 1.0
    price_out: 5.0
    price_cached_in: 0.1
    context_window: 200000
    roles: [general_trivial] # trivial.code: cheap, with a code-quality floor

  - provider: anthropic
    name: claude-sonnet-5
    # $2/$10 was introductory through 2026-08-31; Anthropic made it the standard
    # price (the 2026-09-01 increase to $3/$15 was cancelled — verified 2026-09-07).
    price_in: 2.0
    price_out: 10.0
    price_cached_in: 0.2
    context_window: 1000000 # full 1M window at standard pricing (verified)
    roles: [general_standard] # default_role fallback only — no matrix cell points here

  - provider: anthropic
    name: claude-fable-5-1
    price_in: 10.0
    price_out: 50.0
    price_cached_in: 0.25 # 0.025x input on Fable 5.1 (verified 2026-09-07)
    context_window: 1000000 # 1M window, 128K max output (verified 2026-09-07)
    roles: [code_standard] # standard.code: strongest CODE reasoning

  - provider: anthropic
    name: claude-opus-4-8
    price_in: 5.0
    price_out: 25.0
    price_cached_in: 0.5
    context_window: 1000000 # full 1M window at standard pricing (verified)
    roles: [anthropic_hard] # bench role — unreferenced since SOLUSDEV-252

  - provider: google
    name: gemini-3.1-flash-lite
    price_in: 0.25 # cheapest model in the catalog, ~1M window: the trivial
    price_out: 1.5 # visual/long-context workhorse
    context_window: 1048576
    roles: [visual_trivial, longctx_trivial]

  - provider: google
    name: gemini-3.5-flash
    price_in: 1.5
    price_out: 9.0
    context_window: 1048576
    roles: [visual_standard, longctx_standard]

  - provider: google
    # GA rename to `gemini-3.1-pro` expected; `-preview` is the live ID today.
    name: gemini-3.1-pro-preview
    price_in: 2.0
    price_out: 12.0
    context_window: 1048576
    long_context_threshold_tokens: 200000 # input above this bills the long rates
    price_in_long: 4.0
    price_out_long: 18.0
    roles: [visual_hard, longctx_hard]

  # --- OpenAI (Responses API). Prices verified 2026-09-07 at
  # developers.openai.com/api/docs/pricing. Family rule: >272K input tokens ->
  # long tier for the full request (long_* below; the long cached rate is 2x
  # price_cached_in and is NOT modeled — see header). `gpt-5.6` is an alias for
  # -sol; explicit IDs preferred. Windows for sol/terra/luna are family-assumed
  # — UNVERIFIED per-variant.
  - provider: openai
    name: gpt-6-astra
    price_in: 10.0
    price_out: 50.0
    price_cached_in: 1.0
    context_window: 922000 # max input tokens, 128K max output (verified 2026-09-07)
    long_context_threshold_tokens: 272000
    price_in_long: 20.0
    price_out_long: 75.0
    reasoning_effort: medium # supports low..max ONLY — never "none"
    roles: [general_hard, code_hard] # one entry, both hard cells

  - provider: openai
    name: gpt-5.6-sol
    price_in: 4.0
    price_out: 20.0
    price_cached_in: 0.4
    context_window: 1050000 # UNVERIFIED — family-assumed
    long_context_threshold_tokens: 272000
    price_in_long: 8.0
    price_out_long: 30.0
    reasoning_effort: medium
    roles: [openai_standard] # standard.general

  - provider: openai
    name: gpt-5.6-terra
    price_in: 2.0
    price_out: 12.0
    price_cached_in: 0.2
    context_window: 1050000 # UNVERIFIED — family-assumed
    long_context_threshold_tokens: 272000
    price_in_long: 4.0
    price_out_long: 18.0
    reasoning_effort: low
    roles: [openai_mid] # bench role — unreferenced

  - provider: openai
    name: gpt-5.6-luna
    price_in: 0.2
    price_out: 1.2
    price_cached_in: 0.02
    context_window: 1050000 # UNVERIFIED — family-assumed
    long_context_threshold_tokens: 272000
    price_in_long: 0.4
    price_out_long: 1.8
    reasoning_effort: low
    roles: [openai_trivial] # trivial.general

# --- Provider stanzas (SOLUSDEV-252): connection shape for providers WITHOUT a
# dedicated adapter. Config only — routing a catalog entry at `azure` raises
# UnknownProviderError until an adapter is registered under that key
# (providers.build_adapter_registry). Production wiring = fill this stanza +
# add one adapter. `api_key_ref` is a SecretStore ref NAME, never a value.
providers:
  azure:
    kind: openai_compatible
    endpoint: "" # https://<resource>.openai.azure.com/openai/v1/ — fill at deploy
    api_version: v1 # Azure OpenAI v1 GA API: no dated api-version (verified 2026-09-07)
    api_key_ref: azure_openai_api_key
    deployments: {} # catalog model name -> Azure deployment name

# --- Embeddings (SYS-02, human-approved model choice 2026-08-07) --------------
# The single embedding model behind orchestration.embeddings.embed() — feeds the
# FP-02 EmbedFn seam and RAG retrieval. `dimensions` must match the pgvector
# column width (EMBEDDING_DIM = 1536). Embeddings bill input tokens only.
embeddings:
  provider: openai
  name: text-embedding-3-small
  dimensions: 1536
  price_in: 0.02 # USD per 1M tokens — VERIFIED 2026-08-07 (developers.openai.com pricing)

# --- (complexity × type) → role matrix ---------------------------------------
# May be partial; a missing cell falls back to `default_role`.
matrix:
  trivial:
    general: openai_trivial # gpt-5.6-luna: cheapest text model in the catalog
    code: general_trivial # claude-haiku-4-5: cheap fast model with a code-quality floor
    visual_log: visual_trivial # Flash-Lite: cheaper than Haiku AND ~1M window
    long_context: longctx_trivial # MUST be a large-window model — a long-but-simple input still needs to FIT
  standard:
    general: openai_standard # gpt-5.6-sol
    code: code_standard # claude-fable-5-1: strongest CODE reasoning
    visual_log: visual_standard # Gemini-class: strong for logs/telemetry/images
    long_context: longctx_standard # Gemini-class: large context window
  hard:
    general: general_hard # gpt-6-astra
    code: code_hard # gpt-6-astra (same entry, both hard cells)
    visual_log: visual_hard
    long_context: longctx_hard

default_role: general_standard

# --- Query-based complexity estimator (MO-02, patterns MO-02b) ----------------
# Fallback tier estimation when the caller supplies neither an explicit
# complexity nor an InteractionContext. Deterministic text heuristics — NO
# model call. Algorithm in orchestration/complexity.py; the FROZEN labeled spec
# it is tuned against lives in packages/api/tests/fixtures/complexity_labels.py.
# Every knob here is tunable WITHOUT a code change.
#
# Keyword entries are EXPLICIT REGEX PATTERNS (case-insensitive, validated at
# config load — a bad regex fails fast). The pattern spells out its own anchors
# and morphology: '\bdrift(s|ing|ed)?\b' hits "drifting" but never "adrift";
# "currently"/"framework"/"wireless"/"escape"/"ARM64" cannot fire the
# current/frame/wire/esc/arm markers.
#
# score = long_query·[words >= hard_min_words]
#       + tool_signal·(distinct tool pattern hits)
#       + reasoning_signal·(distinct reasoning pattern hits)
#       + extra_domain·(domain groups matched - 1)
# score >= hard_threshold -> hard; >= standard_threshold -> standard;
# else trivial if words <= trivial_max_words, otherwise standard.
# Empty/blank queries -> standard (the safe default — never a crash, never
# expensive-by-default).
#
# NOTE (deliberate): "how do i"/"how to" are NOT signals — phrasing is not
# complexity; plain lookups must reach the trivial tier. Two diagnostic hits
# (e.g. "why" + a malfunction phrase) reach HARD by design: diagnosis is the
# product's core value, even for short queries.
estimator:
  trivial_max_words: 12 # <= this many words + zero signals -> trivial
  hard_min_words: 35 # >= this many words adds the long_query weight
  standard_threshold: 1 # score >= this -> at least standard
  hard_threshold: 4 # score >= this -> hard
  weights:
    long_query: 2 # one-shot bump for very long queries
    tool_signal: 1 # per distinct work-implying pattern (compare/calculate/...)
    reasoning_signal: 2 # per distinct diagnostic pattern (debugging trends hard)
    extra_domain: 2 # per matched domain beyond the first (cross-domain = harder)
  tool_keywords: # work-implying actions (NOT bare question phrasing)
    - '\bcompar(e|es|ed|ing|ison|isons)\b'
    - '\bset(ting)?\s+up\b'
    - '\blook(ing)?\s+up\b'
    - '\bcheck(s|ed|ing)?\b'
    - '\bcalculat(e|es|ed|ing|ion|ions)\b'
    - '\bcalibrat(e|es|ed|ing|ion)\b'
    - '\bconvert(s|ed|ing)?\b'
    - '\bchoos(e|es|ing)\b'
    - '\bpick(s|ed|ing)?\b'
    - '\brecommend(s|ed|ing|ation|ations)?\b'
    - '\bconfigur(e|es|ed|ing|ation)\b'
    - '\btun(e|es|ed|ing)\b'
    - '\bwire\s+(a|an|the|up|it|this)\b' # wiring-as-task ("wire a limit switch"), not the noun
    - '\bmount(ing)?\s+(a|an|the|it|this)\b' # mounting-as-task ("mount this lidar")
  reasoning_keywords: # diagnosis / anomaly language -> real reasoning needed
    - '\bwhy\b'
    - '\bdebug(s|ged|ging|ger)?\b'
    - '\btrac(e|es|ed|ing)\b'
    - '\bdiagnos(e|es|ed|ing|is|tic|tics)\b'
    - '\broot\s+cause(s)?\b'
    - '\bwrong\b'
    - '\bconflict(s|ed|ing)?\b'
    - '\bintermittent(ly)?\b'
    - '\bdrift(s|ed|ing)?\b'
    - '\bveer(s|ed|ing)?\b'
    - '\bjitter(s|y|ing)?\b'
    - '\bstall(s|ed|ing)?\b'
    - '\bbrownout(s)?\b'
    - '\boverheat(s|ed|ing)?\b'
    - '\boscillat(e|es|ed|ing|ion|ions)\b'
    - '\bovershoot(s|ing)?\b'
    - '\bovershot\b'
    - '\breset(s|ting)\b' # deliberately NOT bare "reset" (the command, not a symptom)
    - '\bcrash(es|ed|ing)?\b'
    # Malfunction/negation family: "not working", "doesn't work", "won't turn",
    # "isn't responding", "fails to boot", "stopped moving" — one pattern so
    # equivalent phrasings tier identically.
    - '\b(not|isn[''’]?t|is\s+not|doesn[''’]?t|does\s+not|won[''’]?t|will\s+not|can[''’]?t|cannot|never|fail(s|ing)?\s+to|stopped|stops)\s+(\w+\s+){0,2}(work(s|ing)?|match(es|ing)?|respond(s|ing)?|mov(e|es|ing)|turn(s|ing)?|spin(s|ning)?|boot(s|ing)?|start(s|ing)?|connect(s|ing)?|read(s|ing)?|detect(s|ing)?|initializ\w*)\b'
  domain_keywords: # breadth signal: >= 2 groups matched = cross-domain query
    code:
      - '\bfirmware\b'
      - '\bcode(base|bases)?\b'
      - '\bros2?\b'
      - '\bnode(s)?\b'
      - '\bfunction(s)?\b'
      - '\bcompil(e|es|ed|ing|er|ation)\b'
      - '\bscript(s|ed|ing)?\b'
      - '\bpython\b'
      - '\blibrar(y|ies)\b'
      - '\bsketch(es)?\b'
      - '\bprogram(s|med|ming)?\b'
      - '\bsoftware\b'
      - '\bslam\b'
      - '\bpid\b'
      - '\balgorithm(s)?\b'
      - '\burdf\b'
    electrical:
      - '\bpcb(s)?\b'
      - '\bschematic(s)?\b'
      - '\bwir(e|es|ed|ing)\b' # not "wireless"
      - '\bsolder(ed|ing)?\b'
      - '\bi2c\b'
      - '\bspi\b'
      - '\buart\b'
      - '\bcan\s+bus\b'
      - '\bvolt(s|age|ages)?\b'
      - '\bresistor(s)?\b'
      - '\bcapacitor(s)?\b'
      - '\bregulator(s)?\b'
      - '\bservo(s)?\b'
      - '\bmotor(s)?\b'
      - '\besc(s)?\b' # not "escape"
      - '\bcurrent(s)?\b' # not "currently" (the bare adjective "current version" can still hit — review)
      - '\bamp(s|erage)?\b'
      - '\bpower(ed)?\b' # not "powerful"
      - '\bbatter(y|ies)\b'
      - '\bsensor(s)?\b'
      - '\bimu(s)?\b'
      - '\bencoder(s)?\b'
      - '\badc\b'
      - '\bpwm\b'
      - '\bgpio\b'
      - '\bpin(s|out|outs)?\b'
    mechanical:
      - '\bcad\b'
      - '\bonshape\b'
      - '\bmount(s|ed|ing)?\b'
      - '\bcasing(s)?\b'
      - '\benclosure(s)?\b'
      - '\bchassis\b'
      - '\btorque(s)?\b'
      - '\bjoint(s)?\b'
      # robot arms yes; ARM the CPU architecture no ("arm64" has no word
      # boundary so it never matches; "ARM <cpu-word>" is killed by lookahead)
      - '\barm(s)?\b(?!\s+(processor|cpu|core|cortex|architecture|chip|soc|board|build|binar\w*|instruction\w*|v\d))'
      - '\bbracket(s)?\b'
      - '\bgear(s|box|boxes)?\b'
      - '\blinkage(s)?\b'
      - '\bframe(s)?\b' # not "framework"
      - '\b3d[\s-]?print(s|ed|ing|er|ers)?\b'
      - '\bbearing(s)?\b'
      - '\bbacklash\b'
      - '\bclearance(s)?\b'
      - '\btolerance(s)?\b'

# --- Query-TYPE estimator (MO-04) ---------------------------------------------
# Fallback RouteType inference when the caller supplies neither an explicit
# type nor an InteractionContext (chain: explicit -> derive_type(context) ->
# estimate_type -> GENERAL — deliberately symmetric with the complexity chain).
# Deterministic, NO model call. Patterns are explicit regexes (IGNORECASE,
# validated at load) like the estimator: section. The labeled spec lives in
# packages/api/tests/fixtures/type_labels.py — REVIEW ME.
#
# PRECEDENCE (hard constraints beat soft preferences):
#   LONG_CONTEXT (measured tokens >= long_context_min_tokens — it must FIT)
#   > VISUAL_LOG (attached image/log, or plainly about logs/telemetry — the
#     model must be able to SEE it)
#   > CODE (a strength preference)
#   > GENERAL.
# Token measurement is len(text)/chars_per_token + attachment token hints — a
# deliberate heuristic (no tokenizer dependency); calibrate the divisor if it
# drifts.
type_estimator:
  chars_per_token: 4
  long_context_min_tokens: 100000 # ~half a 200K window: forces 1M-window routing
  code_min_hits: 1
  visual_min_hits: 1
  visual_attachment_kinds: [image, screenshot, plot, log, telemetry, video]
  code_patterns:
    - "```"
    - '\.(py|cpp|cc|c|h|hpp|ino|rs|go|ts|js|json|ya?ml|xml|launch|urdf|xacro|srdf|sh)\b'
    - '\btraceback\b'
    - '\bsegfault(s|ed)?\b'
    - '\bsegmentation\s+fault\b'
    - '\bundefined\s+reference\b'
    - '\bcompil(e|er|ation)\s+(error|fail\w*|warning)s?\b'
    - '\blinker\s+error(s)?\b'
    - '\bstack\s+trace(s)?\b'
    - '\bnullptr\b'
    - '\bnull\s+pointer\b'
    - '\bcolcon\b'
    - '\bcatkin\b'
    - '\broslaunch\b'
    - '\b(def|fn|func|void|int|bool)\s+\w+\s*\(' # function definitions
    # bare call syntax like init_pwm(). Lookbehind, NOT '\w+\(\)': the greedy
    # form is O(n²) on paren-less word runs (security C1 — 15min on a 1MB
    # query); this is linear and semantically identical.
    - '(?<=\w)\(\)'
    - '\bwrite\s+(a\s+|the\s+)?(function|script|driver|node|code|firmware)\b'
    - '\bunit\s+test(s)?\b'
    - '\bimport\s*error\b'
  visual_log_patterns:
    - '\blogs\b' # plural only — "log IMU data" (the verb) is a code task
    - '\blog\s?file(s)?\b'
    - '\btelemetry\b'
    - '\bplot(s|ted|ting)?\b'
    - '\bgraph\s+of\b'
    - '\bwaveform(s)?\b'
    - '\bscreenshot(s)?\b'
    - '\bdmesg\b'
    - '\bserial\s+(monitor|output|console)\b'
    - '\boscilloscope\b'
    - '\btrace\s+file(s)?\b'

# --- Pre-flight limits + provider retry (MO-03, all tunable) ------------------
# trial_credit_cap: PROVISIONAL single trial allowance in CREDITS (~$5 of
#   provider spend at the current cost knobs). Pre-flight check only — a call
#   that pushes spend slightly past the cap is accepted by design (Q9: block
#   when already at/over, bill the actual after; no cost pre-authorization).
# max_calls_per_minute: FLAT per-user frequency cap (abuse insurance, same for
#   every plan; Redis-backed sliding window). Exceeding it is a transient
#   "try again shortly", NOT the trial cap's "upgrade to continue".
# retry_*: OUR exponential backoff for provider 429/overload (SDK retries are
#   pinned to 0 in the adapters). retry_max_attempts counts total tries.
limits:
  trial_credit_cap: 1000 # PROVISIONAL — calibrate with pricing
  max_calls_per_minute: 20
  frequency_window_seconds: 60
  retry_max_attempts: 3
  # Base delay, doubling per retry: 1s + 2s = 3s of waiting across 3 attempts.
  # Raised from 0.5 (SOLUSDEV-252, observed live): a token-per-minute limit
  # asks for ~2.7s, which the old 0.5+1.0=1.5s budget could never clear, so
  # every retry hit the same closed window and the turn died as 'exhausted'.
  retry_backoff_seconds: 1.0

# --- Cost / credit conversion (ADR-024, all calibratable) --------------------
cost:
  margin_multiplier: 2.0 # infra + failed calls + trial grants + profit (not pure profit)
  credits_per_dollar: 100.0 # PROVISIONAL — calibrate from pilot data
  price_unit: usd_per_million_tokens
```


### J3 — from section FG
Line counts inline above. Connectors: 61 files, 18,221 lines.


### J3 — from section H
wc -l: WorkspaceShell 803, shellStore 66, TitleBar 36, MenuBar 250, menuBar.constants 75, ShellChrome 287, AppRoutes 107, App 49, HomeScreen 327, ProjectGrid 124, TeamStrip 234, MembersPanel 540, TeamActivityPanel 99, ConnectedAccountsCard 512, AccountRows 478, connectedAccounts 143, SolusCard 312, ProjectFolderCard 398, HomeTeamModals 188, modals 307, useHomeData 291, useHomeTeam 537, extensionRail 156, useExtensionRail 192, widget.contract 91, focusStore 194, WorkspaceScreen 728, RobotTopologyGraph 243, GraphNavigator 270, GraphCard 327, GraphLinks 173, graphIndex 132, layout 96, useGraphNavigation 386, GraphSuggestions 144, NodeSidebar 190, WorkspaceAdd 119, useWorkspaceGraph 159, useWorkspaceLayout 326, useSolusNodes 199, AlertScreen 63, navigation.css 733, BenchScreen 226, DeviceBenchView 570, BenchCanvasHost 164, BenchRealtime 213, ConnectDeviceModal 122, bench.css 386, SolScreen 115, SolChat 665, ChatsSidebar 362, ContextPanel 238, UsagePanel 184, useSolChat 118, SolWindow 143, StoreScreen 259, ExtensionCard 171, ExtensionDetail 279, extensionLogic 410, useExtensions 191, BomScreen 246, BomTable 151, BillingScreen 490, SettingsScreen 90, OverlayWindow 64, Onboarding 202, LandingPage 166, main.css 658, tokens.constants 138, applyTheme 51, settingsStore 38, icons.constants 169, ContextMenu 113, Button 61, Card 46, `lib/api/resources.ts` 1696. Renderer: 481 non-test `.ts/.tsx` files.



---

## Not determined — for the human to answer
- ~~Q5~~: answered by the user, API suite green on main.
- **Q8**: whether `openapi.json` matches the running app. It was not regenerated.
- **Q10**: who reads `clone_of` and `deployment_for_target` edges.
- **Q27**: retention of `conversations`/`conversation_turns` and `data_events`.
- **Q42**: hotkey and gesture runtime behaviour on this aarch64 box. The uiohook prebuild is likely x64, so the app probably falls back to keyboard-only summon.
- **Q62**: the `change-signal-spine.md` lease and probe rules other than the 90 s quiet period.
- **Q63**: the Onshape double-click-to-allow issue: cause and fix state.
- **Q74**: "unassigned notes". Only unassigned *parts* exist.
- **Q75**: whether the built bundle launches. It was not launched. `npm run build` was not run because it rewrites the tracked `schema.ts`. The packager was not run.
