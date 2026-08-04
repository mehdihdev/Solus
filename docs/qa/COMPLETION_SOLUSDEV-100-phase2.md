# Completion Report — SOLUSDEV-100 phase 2: KiCad MCP fork, live export acquisition, artifacts

**Ticket:** SOLUSDEV-100 (phase 2) · **Branch:** `SOLUSDEV-100-kicad-mcp` (37 commits over
main at handoff, through `0785fa8`) · **Date:** 2026-08-03 · **Status:** integrated,
suites green, awaiting the human gates in §8.

Phase 1 (the committed-netlist KiCad connector + UI connect flow) shipped earlier on this
ticket and is reported in its own artifacts; this report covers phase 2: the vendored
KiCad MCP server fork, the schematic write proof, the live export acquisition path, and
the project artifact surface.

---

## 1. What was built, per acceptance criterion

| Criterion                                                                         | Status           | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --------------------------------------------------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fork** — a vendored, hardened, launchable KiCad MCP server per ADR-031          | ✓                | `integrations/mcp/kicad/`: `upstream/` = `lamaalrajih/kicad-mcp` @ `98c9ea41` (MIT, verbatim single import, F6 exclusions logged); `vendor/` = `circuit-synth/kicad-sch-api` @ `505bca23` (two-tree layout, F7); `solus/` overlay (trimmed 6-tool roster + `set_symbol_property`, stdout/ctx/env hardening, headless degrade); `bin/launch` (fixed argv, `env -i` allowlist, private venv, zero network I/O); `allowlist.yaml`, `PROVENANCE.md` (both tree hashes, recomputed on every test run), `SECURITY_REVIEW.md` drafts; `requirements.lock.txt` hash-pinned.                                                  |
| **Write proof** — a mutating schematic edit that cannot corrupt a design file     | ✓                | `solus/write/`: owned byte-offset S-expr tokenizer (`sexpr.py`), top-level-instance property locator, strict KiCad string escaping, workspace path confinement, **splice + byte-stability guard** (F10, `guard.py`: diff confined to the located span AND token streams identical except exactly one STRING token), atomic write (temp-in-same-dir + fsync + `os.replace`). Registered as `kicad.set_symbol_property` through the trimming registrar; allowlisted `requires_confirmation: true`. Design forced by the T2a measured finding that library round-trips are NOT byte-stable (strict xfail pins it — §5). |
| **E2E ingest** — the real fixture landing in the graph through the real HTTP flow | ✓                | `packages/api/tests/test_kicad_ingest_e2e.py`: T3 committed fixture (`solus_sample`, 9-component roster with pinned MPNs; 1001-component large variant) through connect/sync HTTP; re-sync idempotency; **invariant-2 equality across all three acquisition paths** (inline config, live inline content, live ArtifactRef); one-shot artifact consumption with the six-condition anti-forgery match.                                                                                                                                                                                                                 |
| **Adapter mirrored**                                                              | ✓ (pre-existing) | The fork plugs into SOL through the untouched W0-04 `ToolRegistry`/`MCPTool` adapter (SOLUSDEV-153 MCP-01) — phase 2 added no adapter code; the companion mirrors (never imports) the cloud `ArtifactRef` schema per its standalone-bundle rule.                                                                                                                                                                                                                                                                                                                                                                     |

Supporting surfaces built for the criteria:

- **Artifact upload/fetch** (`docs/api/artifacts.md`, T4c0 route-plan amendment + T4c):
  `POST/GET /api/v1/projects/{id}/artifacts[...]` behind `ProjectCtx`, `ArtifactStore`
  protocol (`local` dev / `s3` prod-shaped), 8 MiB hard cap enforced pre-read AND while
  streaming, per-user/per-team upload budgets, TTL sweep + one-shot consumption,
  `tool_call_id` column (new migration).
- **Acquisition chain** (T4a/T4b): `ExportAcquirer` protocol seam in
  `EdaExportConnector` (try live, fall back to committed on ANY failure) +
  `BridgeExportAcquirer` (scope-bound dispatch, §4.3 anti-forgery conditions 3–5
  enforced acquirer-side, every decline a stable logged reason).
- **Companion bulk-output path** (T4d): `artifact_path` → resolve/confine/size-cap →
  HTTPS upload to the artifacts route (host-allowlisted, token never logged) → rewrite
  to `ArtifactRef` in the `tool_result`.
- **T6 handoff docs**: `docs/contracts/metadata-extraction.md` §2.1 dated addendum (F1
  transport), `integrations/mcp/README.md` two-tree layout + allowlist-example fix,
  `.claude/skills/kicad-parsing/SKILL.md`, `docs/qa/COWORK_QA_kicad-mcp.md`, phase-2
  pointer in `COWORK_QA_kicad-connector.md`, this report.

## 2. Governing docs consulted

- **DECISIONS.md**: ADR-030 (committed-export v1, revisit clause exercised), ADR-031
  (fork–harden–own MCP hosting), ADR-021 (git workflow), ADR-032 (two-tier governance —
  every contract/route change below rode its tier), ADR-027 (graph enums/domains).
- **Contracts**: `docs/contracts/metadata-extraction.md` §2.1 + §5.2 (amended here,
  tier-1), `docs/contracts/agent-tool.md` (W0-04 `ArtifactRef`, `artifacts` table,
  confirmation flag), `docs/contracts/bridge-protocol.md` (frame caps, §10 hole closed),
  `docs/contracts/connector-interface.md` (W0-05).
- **Route plans**: `docs/api/artifacts.md` (authored T4c0 as the tier-1 amendment, then
  implemented exactly), `docs/api/API-implementation.md` conventions.
- **Directory law**: `integrations/mcp/README.md` + `integrations/mcp/CLAUDE.md` +
  the PROVENANCE/SECURITY_REVIEW templates; root CLAUDE.md §5–§9.
- **Skills**: `tdd-workflow`, `security-review`, `python-testing`, `api-design`;
  captured the new domain procedure as `.claude/skills/kicad-parsing/` per root
  CLAUDE.md ("capture KiCad parsing as a skill as it stabilizes").

## 3. Human decisions recorded (all approved in-session, 2026-08-03)

| #               | Decision                                                                                                                                                                                                                                                                                                                           |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fork choice     | Vendor `lamaalrajih/kicad-mcp` @ `98c9ea41` (MIT; upstream merge of PR #33 null-ctx workaround) as the KiCad fork's upstream.                                                                                                                                                                                                      |
| BSD-2 exception | `sexpdata` (BSD-2-Clause) ships as the vendored library's sole runtime dep — **ACCEPTED LICENSE EXCEPTION** to ADR-031's MIT/Apache-2.0 fork boundary; recorded in PROVENANCE; an ADR-031 wording clarification (permissive non-copyleft deps of a fork vs. the fork itself) is proposed separately.                               |
| F1              | Build the ArtifactRef path now: live exports ≤ 512 KiB ride inline in the tool result; larger exports are workspace files the companion uploads via `POST /projects/{id}/artifacts` and rewrites to an `ArtifactRef`; one-shot consumption behind the six-condition anti-forgery match. (Contract addendum §2.1; route plan T4c0.) |
| F2              | Live acquisition is **API-process-only** for now — the in-process `BridgeSessionRegistry` is the session source; ARQ-worker-triggered syncs use the committed path until a cross-process seam exists.                                                                                                                              |
| F3              | Acting user for a live-acquiring sync = the manual sync **requester, else `source.created_by`** ("requester-else-creator"); unresolvable → live path declines cleanly.                                                                                                                                                             |
| F6              | Vendor exclusion pattern for verbatim imports: `CLAUDE.md`, `.claude/`, `agents/`, `.mcp.json`, `.github/` (one PROVENANCE row per exclusion that existed upstream).                                                                                                                                                               |
| F7              | Two-tree fork shape ratified: `vendor/` (support library) beside `upstream/`, ONE `PROVENANCE.md` with a section per tree, each tree its own recomputed hash. (Now codified in `integrations/mcp/README.md`.)                                                                                                                      |
| F12             | Artifact `scope = PROJECT` default + **1 h TTL** — proceeding on the agent's recommendation; explicitly flagged for ratification at MR review (also called out in `docs/api/artifacts.md` §4.1).                                                                                                                                   |

## 4. Delegated-judgment decisions (agent calls, flagged for review)

- **T2b write design**: after T2a measured that `kicad_sch_api` round-trips are not
  byte-stable (§5), the write tool was built as locate→splice→guard→atomic-replace over
  raw bytes with an owned offset-carrying tokenizer — NOT library load→modify→save. The
  guard refuses any write whose effect is not provably "exactly one string token
  changed".
- **Rate-limit numbers are provisional**: `artifact_uploads_per_minute_per_user` /
  `artifact_upload_bytes_per_hour_per_team` setting NAMES are the contract; values await
  the F13 security pass (documented in `artifacts.md` §4.5).
- **`ArtifactRef.uri` = the API content route** (relative), never a storage-internal
  locator — keeps every read on the single authz path; presigned S3 documented as the
  revisit, not v1.
- **Vendored-tree lint/type law mechanics**: a Solus-marked `[tool.ruff]`
  force-exclude block appended to `upstream/pyproject.toml` (logged PROVENANCE row —
  ruff resolves the nearest config, so hooks stop linting third-party code); the
  shadowed duplicate `vendor/kicad_sch_api/cli.py` dropped (mypy duplicate-module
  blocker, logged); repo-root conftest collision fix so whole-repo pytest/mypy runs
  survive the fork tree.
- **T4b additive `project_path` config key** on EDA sources (no
  `EdaExportConnector`/`KicadConnector` signature change); the corresponding
  `config_fields` catalog omission is filed in §7.

## 5. The load-bearing measured finding (T2a)

`kicad_sch_api.Schematic.load(...).save_as(..., preserve_format=True)` on the committed
Solus fixture re-emits canonical multi-line KiCad style (43,513 B / 655 lines →
65,603 B / 4,003 lines), reorders top-level elements, injects format-version fields, and
replaces embedded `lib_symbols` from the machine's local KiCad libraries when installed.
Pinned as a **strict xfail**
(`integrations/mcp/kicad/tests/test_vendor_sch_api.py::test_roundtrip_is_byte_identical_on_the_solus_fixture`)
so the design assumption is re-checked on every run; the structural round-trip
(populations of symbols/wires/labels/no_connects preserved) is the green floor. This is
why the write tool splices bytes instead of saving through the library.

## 6. Deviations & limitations (documented, not silent)

1. **The write tool is not end-to-end dispatchable**: the user-confirmation flow does
   not exist yet, so `agent/runtime.py::confirmation_refusal` structurally refuses every
   `requires_confirmation` tool. Expected posture until the confirmation-flow ticket;
   QA Flow 5 verifies the refusal.
2. **Live acquisition is API-process-only** (F2): ARQ-worker syncs take the committed
   path; a cross-process bridge seam is future work.
3. **Property CREATION unsupported**: `set_symbol_property` edits an existing property's
   value only (splice semantics); creating a new property node is out of scope.
4. **Fork-venv tests skip in CI** (3 skips) until the companion install-time
   materialization of `integrations/mcp/kicad/.venv` lands (BRG follow-up) — the skips
   carry the materialization hint.
5. **S3 artifact backend not deployable** until infra F11 provisions the bucket; dev
   runs `local`. The `ArtifactStore` seam is the swap point.

## 7. Found defects filed for follow-up

1. **Acquirer ↔ fork result-envelope mismatch — FIXED before handoff (commit
   `23503ef`), found independently by the Phase 4 code review and T6 fact-checking.**
   `connectors/mcp_acquire.py::_ExportToolValue` accepts ONLY `content`/`artifact_ref`
   (`extra="forbid"`), but the fork's plan-locked `export_netlist` envelope
   (`solus/netlist_export.py`) also carries `format`, `filename`, `bytes`, `degraded`,
   `reason` — and on the inline branch an explicit `artifact_path: None` — all of which
   survive the companion's rewrite (`dispatch.py` strips only `artifact_path` when
   non-null). Against the REAL fork, validation therefore fails, the acquirer declines
   "tool result value has an unexpected shape", and every live sync silently falls back
   to the committed export (invariant 3 masks the defect; all T4b/T5 tests used
   bare `{"content": …}`/`{"artifact_ref": …}` fakes, so suites stayed green). Fix landed
   in `23503ef`: `_ExportToolValue` now carries the full plan-locked envelope (advisory
   metadata keys are never authority), a NON-NULL `artifact_path` is a hard decline
   (an unrewritten companion path must never be consumed cloud-side), and regression
   tests feed the acquirer the fork's literal envelope (inline, degraded, and
   unrewritten-path variants). The QA plan's flows now target the real live-path
   results.
2. **`serialize_entity` omits `modality_hints`** (T5 finding): the public `/entities`
   read surfaces `properties`/`attrs` but not `modality_hints`, so fingerprint identity
   channels are invisible to API consumers; T5's graph assertions read the DB directly.
   Needs a product decision (expose vs. keep fingerprint-internal).
3. **README ↔ `ServerAllowlist` mismatch — FIXED here (T6)**: the sample
   `allowlist.yaml` showed an `upstream_tool_count` field the `extra="forbid"` model
   rejects; the example now notes the exposed/total ratio lives in PROVENANCE (T1b
   finding).
4. **Upstream netlist parser lacks an input-size cap** (residual, recorded in
   `SECURITY_REVIEW.md`): `kicad_mcp.utils.netlist_parser.extract_netlist` reads the
   schematic unbounded; mitigations today are the workspace confinement + the cloud-side
   caps. A `solus/` shim cap is the natural hardening follow-up.
5. **`KicadConnector.config_fields` omits `project_path`** (T4b note): the catalog does
   not advertise the live-acquisition key; belongs to the owner of `connectors/kicad.py`.
6. **Composed tool-name bound not re-validated in `discover_mcp_tools`** (carried
   MCP-03 follow-on): the ≤128-char `{server}.{tool}` bound is enforced by layout law
   and review only.

## 8. Human gates left open (nothing ships past these without a human)

- **`allowlist.yaml` ratification**: the WHOLE file is human-ratified at the MR
  (integrations/mcp/CLAUDE.md rule 2), including the drafted
  `set_symbol_property: requires_confirmation: true` row.
- **Security review signatures**: `SECURITY_REVIEW.md` checklists (T1b + T2b addendum)
  need BOTH dev sign-offs, and `PROVENANCE.md`'s sign-off lines must pin BOTH current
  tree hashes (upstream `56f30452…`, vendor `844e1a11…`). Sign-off lines are blank by
  design — agents never write them.
- **F12 ratification** (artifact scope default + TTL) at MR review.
- **The MR itself**: push, open, review, merge are human actions (ADR-021). The branch
  is integrated and green; no agent pushed anything.

## 9. Test coverage summary (all run at handoff, this worktree, 2026-08-03)

| Suite                                                                                                                  | Result                                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `uv run pytest integrations/mcp -q`                                                                                    | **209 passed, 3 skipped** (fork-venv `sexpdata` tests skip until `.venv` materialization; strict xfail included) |
| `uv run pytest packages/companion -q`                                                                                  | **108 passed**                                                                                                   |
| `cd packages/api && uv run pytest -q` (full suite)                                                                     | **1292 passed, 3 skipped**                                                                                       |
| Phase-2 API files alone (`test_artifacts`, `test_mcp_acquire*`, `test_sync_live_acquisition`, `test_kicad_ingest_e2e`) | 38 passed                                                                                                        |

Coverage character: TDD throughout (each task's tests landed before/with its
implementation — see the per-task commit pairs in `git log main..HEAD`); contract-shaped
suites (fork layout/provenance/lockfile law, allowlist shape, launcher pinning), security
cases (DTD refusal, path confinement, anti-forgery §4.3 conditions incl. cross-project /
cross-user / replay, host allowlist, token-absence-in-logs), degradation cases (headless,
bridge offline, malformed shapes), and isolation cases per CLAUDE.md §7.

## 10. Harness observations (for the humans who own `.claude/`)

Flagged per CLAUDE.md §5 ("an agent that believes a hook is misfiring flags it in its
completion report") — none were bypassed:

- **H9 TDD-name heuristics**: the tests-first check keys on file-name patterns and
  intermittently flagged legitimately-paired work (e.g. overlay modules whose tests live
  under the fork's `tests/` tree rather than a sibling `test_*.py`); workers appeased it
  with commit ordering rather than restructuring.
- **H8 dmypy `solus.*` resolution**: the fork's `solus/` overlay package (deliberately
  not a uv-workspace member) confuses dmypy's module resolution on explicit-path runs;
  the vendored-tree lint-law mechanics (§4) contain it, but dmypy occasionally needed a
  restart.
- **mypy internal-error flakes**: sporadic mypy internal errors on the large vendored
  tree; re-runs were clean — worth pinning/upgrading mypy when convenient.
- **Worktree base-commit variance**: parallel worktrees were cut at different base
  commits as the feature branch advanced, so early sub-branches merged against stale
  bases; integration merges resolved it but it cost churn — future plans should re-cut
  or fast-forward worktrees after each integration.
- **Watchdog stalls**: long fork test runs (subprocess probes) occasionally tripped
  session watchdog timeouts; harmless but noisy.

---

**T6 (this handoff) deliverables**: `docs/contracts/metadata-extraction.md` §2.1 addendum ·
`integrations/mcp/README.md` two-tree layout + allowlist-example fix ·
`.claude/skills/kicad-parsing/SKILL.md` · `docs/qa/COWORK_QA_kicad-mcp.md` ·
phase-2 pointer in `docs/qa/COWORK_QA_kicad-connector.md` · this report.

## 9. Phase 4 verification outcomes (appended post-review)

**Code review:** WARNING → resolved. HIGH (acquirer rejected the real fork envelope,
live path inert) fixed in `23503ef`; MEDIUM (stale write-tool status in the security
paper trail) fixed via append-only SECURITY_REVIEW reconciliation + the allowlist
`reason` accuracy correction (comment-level only; entries and `requires_confirmation`
values untouched — the file remains human-ratified at the MR).

**Security review:** FAIL → all findings remediated on-branch:
C1 dispatch timeout (setting `bridge_tool_timeout_seconds`, decline+fallback, silent-
companion test) · H1+M3 content GET now member-only and non-destructive; one-shot
consumption moved to `consume_tool_artifact` (all six anti-forgery conditions, the
only consumption path) · H2 input-path confinement for every fork tool (one wrapper
in the trimming registrar) · H3 fail-closed workspace end-to-end (workspace_root
refuses when unset; launcher passes the var through empty; companion
`SOLUS_COMPANION_WORKSPACE` seam wired through `__main__`) · H4 `discover_mcp_tools`
consumes allowlist.yaml (requires_confirmation only from the allowlist) + ALL catalog
stdio launchers pinned absolute · H5 residual: real companion-rewritten envelope
tested end-to-end · M1 411 on missing Content-Length before body buffering · M2
limiter eviction + documented per-instance multiplier (Redis backing = named
follow-up) · M4 real project-access re-check at consumption · M5 parser token/depth
caps, iterative parse, RecursionError/OSError mapped to stable refusals · M6 hostile-
instruction fixture ingests verbatim-inert (fork + cloud e2e) · L1 concurrency-safe
stdout diversion · L2 stale docs corrected · L3 64 KiB property-value cap · L4
change-detection probe timeout · L6 hygiene (0700 store root, `bytes` alias).

Verified clean by the reviewer (no findings): secrets handling, SQL, subprocess
discipline, storage-key traversal, companion path confinement + token hygiene,
splice-guard bypass attempts, requires_confirmation provenance, tenant isolation on
all new endpoints, one-shot race, invariant-2 identity, log hygiene, and — key —
no reachable production path spawns the fork outside the allowlist-gated companion.

**Follow-ups accepted (not blocking):** Redis-backed upload budgets (M2 mechanism);
dedicated limiter-eviction unit test; worker probe-timeout test coverage (L4);
live acquisition remains API-process-only (F2/L5 — prod ARQ path uses committed
exports until a cross-process dispatch seam lands); presigned-S3 revisit (F11).

**Final validation:** packages/api 1316 passed / 3 skipped · integrations/mcp 289
passed / 3 skipped · packages/companion 116 passed · ruff repo-wide clean.

## 10. Pipeline remediation (appended after MR !32's first run)

`test:python` failed in CI while every suite passed locally. Root-caused by
reproducing the pipeline exactly — the CI images (`ghcr.io/astral-sh/uv:python3.12-
bookworm-slim`, `pgvector/pgvector:pg16`) against a clean clone with no `.env`:

1. **No `git` binary in the CI python image.** Four ADR-031 vendored-tree-hash
   guards shelled out to `git` and died with `FileNotFoundError: 'git'`. Skipping
   them in CI would have disabled a security control exactly where it matters, so
   the recompute is now pure Python (`integrations/mcp/kicad/tests/tree_hash.py`),
   cross-checked against real `git rev-parse` wherever git exists — including on
   the real vendored tree — across exec bits, symlinks, nested trees, empty
   directories and git's directory-sorts-as-`name/` rule. Reading the working tree
   also subsumes the old `git status --porcelain` checks, and gitignored litter is
   skipped by name (the bug that voided this guard once before).
2. **`os.access(X_OK)` lies for root.** The first pure-Python cut used it for mode
   detection; as root — i.e. in every CI container — it reports success for files
   with no execute bits, so all 121 vendored files hashed as `100755` and the guard
   failed in CI while passing locally. Now `lstat().st_mode & S_IXUSR`, which is
   git's actual rule and root-independent. Two regression tests pin it, one
   patching `os.access` always-true.
3. **`security:gitleaks` would have failed next.** `generic-api-key` fired on a
   test constant NAME (`SOME_KEY`) holding an opaque storage-key UUID — an
   artifact id, never a credential. Renamed to `STORAGE_REF`; the already-pushed
   commit is pinned by fingerprint in `.gitleaksignore` (pushed history is never
   rewritten).
4. A 5 s wall-clock assertion in the tokenizer test was relaxed to 30 s (measured
   0.12 s locally): a tight bound on a loaded shared runner is a false failure,
   not a finding.

**All six pipeline jobs verified green in their real CI images before handoff:**
lint:python · typecheck:python (124 files) · test:python (1727 passed, 13 skipped
— the git cross-checks skip without a git binary while the four production hash
guards run and pass) · lint:node · typecheck:node · test:node · security:gitleaks
(no leaks, single-branch clone as CI clones).

## 11. Sync with main (appended before handoff)

`origin/main` had advanced to `2bf3477` (the squash-merged SOLUSDEV-83 stripe-setup
CLI). Synced by **merging main INTO this branch** (`ccfdfb1`), not rebasing: the
branch is pushed as MR !32, so rewriting its history would need a force-push —
forbidden by ADR-021 and hook-blocked.

One conflict, agent-resolved and disclosed here: `.gitleaksignore`, where both
branches appended a fingerprint suppression. Resolution keeps BOTH entries (the
SOLUSDEV-83 stripe fixture hit and this branch's `SOME_KEY` storage-UUID hit) — no
suppression was dropped or widened. Two other overlaps merged without conflict:
`packages/api/pyproject.toml` (main's `[project.scripts]` alongside this branch's
`solus-contracts` dev dependency) and `packages/api/tests/test_plans.py`, where
both branches had made the byte-identical `_env_file=None` hermeticity fix.

`origin/main` is now fully contained in this branch, so the MR merges cleanly.
Post-merge verification, all in the real CI images: lint:python ✅ ·
typecheck:python ✅ (126 files) · test:python ✅ **1759 passed, 13 skipped** ·
security:gitleaks ✅ no leaks · lint:node / typecheck:node / test:node ✅ (exit 0).
Locally at the merge commit: 1766 passed, 6 skipped.

## 12. security:gitleaks fix — value-based, not fingerprint-based (pipeline #2730474888)

`test:python` went green after §10, and the pipeline advanced to `security:gitleaks`,
which failed with 2 leaks on the SAME fake UUID §10 had already suppressed by
fingerprint. Cause, from the job log: CI fetches with **`git depth 20`**. In a
shallow clone the graft-boundary commit has no parent, so its entire tree reads as
newly added and the finding is attributed to THAT commit — not the commit the
fingerprint pins (CI scanned 240 commits / 72 MB; a full local clone scans ~12 MB).
Both reported findings were the same literal under two different boundary SHAs.

The important part: **that boundary moves with every push**, so any
`.gitleaksignore` fingerprint for a literal in committed history passes one
pipeline and fails the next. The fix is therefore value-based — the fake UUID is
allowlisted by regex in `.gitleaks.toml`, the pattern that file already used for
`sk_live_abc123` — and `.gitleaksignore` keeps a pointer explaining why a
fingerprint is the wrong tool here. The literal is an opaque artifact storage id,
never a credential; the constant was already renamed `SOME_KEY` → `STORAGE_REF`.

Verified with real gitleaks in three clone shapes: **depth 20** (CI's exact shape),
**full clone**, and **depth 5** — the last one proving resilience to a future push
shifting the graft boundary. All three: no leaks. Local suite re-run after the
config change: 1766 passed, 6 skipped; ruff clean.
