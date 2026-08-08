# Completion Report — SOLUSDEV-102 (SOLUS-EDA-03: Altium MCP fork)

**Branch:** `SOLUSDEV-102-altium-mcp` · **Date:** 2026-08-08 · **Status:** implementation
complete, Phase 4 verified (security verdict PASS after fixes), awaiting the human gates below.

## What was built

Fork + harden of the 290-tool-class Apache-2.0 Altium MCP server
[`salitronic/eda-agent`](https://github.com/salitronic/eda-agent) @ `77966059` (~396 tools at
the pinned SHA), per ADR-031 and the MCP-03 playbook:

- **Vendor + provenance**: verbatim single import commit (`.github/`-only exclusion,
  human-approved), one logged `upstream/` deviation (ruff block), `PROVENANCE.md` pinned to
  vendored tree hash `7e08fbb7450cf0603c24bfe2facbd56a3ffcbe32`, 524-hash universal
  `requirements.lock.txt` (upstream ships none), hygiene-gate enrollment
  (`test_vendor_hygiene.py` now covers the fork), shared `vendored_tree_hash` helper extracted
  to `integrations/mcp/tests/_lib/` (kicad shimmed, sign-offs unaffected).
- **Confined launch**: `bin/launch` (POSIX: fixed argv, `env -i` + 10-name declared allowlist,
  zero network) and `bin/launch.cmd` (Windows twin; companion `_child_env` is the authoritative
  scrub there — honestly documented incl. the MCP SDK's inherited-env floor). The
  machine-global IPC pointer (`C:\ProgramData\eda-agent\`) is unreachable: launcher-set
  `EDA_AGENT_WORKSPACE`/`EDA_AGENT_POINTER_FILE`/`EDA_AGENT_BACKEND` pins are byte-verified by
  `solus/server.py` before serving; unconfigured workspace and symlink escapes fail closed.
- **Tool surface — 11 of ~396** (`allowlist.yaml`, DRAFT pending ratification): 8 read-only
  upstream tools + Solus-authored `export_netlist` + 2 confirmation-gated writes. In-process
  trimming makes everything else dead — upstream's meta-dispatch pair
  (`tool_catalog`/`tool_invoke`, a full allowlist bypass) is never even created, proven against
  upstream's real dispatch mechanism. Hardening is data-driven: `PINNED_PARAMETERS`
  (`force_recompile` hidden-write neutralized; `backend` pinned; `timeout` stripped),
  `NUMERIC_BOUNDS` (limit caps), `WRITE_GUARDS` (name shape-lock vs IPC metacharacters, value
  4 KiB, batch 500/32-key/1 MiB caps), result sanitation (upstream's model-directed
  "datasheet" imperatives stripped; hostile schematic fields stay as inert leaf data),
  ctx-strip, stdout diversion, pre-body path confinement.
- **`export_netlist`** synthesizes Protel netlist text from two read-only bridge reads
  (`get_nets`/`get_bom`), neutralizes the full line-boundary set against the real cloud parser
  (round-trip tested incl. a hostile fixture), 512 KiB inline / workspace-confined artifact
  branch, degraded-never-raises with stable reasons; a degraded envelope fails cloud
  validation on purpose so acquisition declines and the connector falls back to the committed
  export (ADR-030 invariant 3 intact).
- **Connector**: `AltiumConnector.config_fields` gains `project_path` (the `mcp_acquire.py`
  handoff); inline-export fallback and conformance suite green.
- **BYO-license capture (MCP-05 companion side)**: stdin credential control line → validated
  → single `credential_submit` frame (Addendum C exact; 16 KiB cap; secret values never in any
  log/store/crash path — sentinel-asserted at every hop); desktop `bridge:license` IPC
  (sender-gated) + BridgePopover "Add license" modal (masked inputs by key name, three
  `license_state` renderings, cleared on close); companion Windows launcher resolution
  (`launch.cmd` sibling, per-platform executability, fail-closed); wireflow recorded at
  `docs/wireflows/license-capture.md`.
- **Docs**: fork `README.md` (surface table, re-vendor procedure), `SECURITY_REVIEW.md`
  (drafted evidence + Phase 4 audit addendum), `docs/qa/COWORK_QA_altium-mcp.md` (split:
  in-house flows vs customer-machine flows), `docs/qa/RUNBOOK_altium-customer-validation.md`
  (the acceptance item "customer-side validation documented").

## Governing docs followed

ADR-031 (fork model), ADR-030 (parse-export fallback preserved), ADR-021/§5 branch
discipline, `integrations/mcp/README.md` + `CLAUDE.md` + both templates, bridge-protocol.md
Addenda B/C, connector-interface.md, metadata-extraction.md §2.1/§5.4. `docs/architecture/`
and `docs/wireflows/` were empty; the license-capture wireflow gap was resolved by in-chat
human decision (BridgePopover modal) and the flow is now documented.

## Verification (final, serial, isolated DB `solus_test_altium102`)

- Full repo suite: **2272 passed, 6 skipped** (2:10). Fork suite: 220. `integrations/mcp`:
  524 incl. kicad. Companion: 158. Desktop vitest: **715 passed / 103 files**; `pnpm
typecheck` clean. `ruff check .` clean; branch-diff mypy (445 files) exit 0.
  Lane-ownership check: "not a lane branch — skipped" (ticket branches exempt, verified).
  Vendored tree hash unchanged end-to-end.
- **Phase 4**: fresh-context code review (1 MEDIUM found → fixed: `EDA_AGENT_BACKEND`
  fail-open) and fresh-context security audit (4 HIGH + 4 MEDIUM found → all fixed test-first
  in per-finding commits → independently re-verified by the original reviewer: **PASS**).
  Full table in the `SECURITY_REVIEW.md` addendum.
- **Not proven in-house (byo_paid QA scope)**: anything requiring live Altium/Windows — the
  DelphiScript round trip, real payload shapes, write-tool effects, pointer handshake. These
  are the customer-machine half of the QA file + runbook.

## Human gates outstanding (in order)

1. **Allowlist ratification** — the whole `allowlist.yaml`, incl. whether to keep both write
   tools or cut `sch_set_components_parameters` (drafted for exactly this decision).
2. **Security-review sign-off** — both devs, `SECURITY_REVIEW.md` dated pass +
   `PROVENANCE.md` sign-off lines pinned to tree hash `7e08fbb7…`.
3. **Push / MR / merge** — human-only per ADR-021.
4. **Cowork QA pass** (in-house half) + **customer-side validation** (runbook) when a
   customer machine is available.

## Decisions made under delegated judgment

Upstream = `salitronic/eda-agent` (only match for the ticket's description; human-confirmed);
`.github/`-only vendor exclusion (human-confirmed); read-only + 2 gated writes allowlist
posture (human-confirmed); BridgePopover license UI (human-confirmed); Windows launch fixed
minimally in this ticket (human-confirmed); tree-hash helper shared via `_lib` Option A
(human-confirmed); refuse-not-clamp for numeric bounds; degraded-envelope-fails-cloud-validation
as the honest offline behavior; `sch_set_components_parameters` extracted via an inert closure
harvester rather than invoking `generic.py`'s registration wholesale.

## Deviations, incidents, and flags

- **Shared-branch interleaving (by your arrangement, flagging for MR shaping)**: this branch
  also carries the other session's billing/pricing/cancellation commits (`1cbb6cd`, `1330343`,
  `aa89e6c` — incl. a DECISIONS.md ADR-023/024 amendment), its earlier fixes (`d8f0547`,
  `5f7b9d0`, `94cf1c5`), and a landing-page commit (`4743e7c`). That session confirms its
  commits are self-contained and cherry-pickable if you want to split the MR.
- **Incident — file lost**: a review subagent wrongly deleted the untracked
  `docs/superpowers/specs/2026-08-08-solus-landing-starter-design.md` while trying to clear an
  ownership-hook block. It was never committed, so it is unrecoverable from git; neither this
  session nor `solus-9b` authored it. Whoever wrote it (a third session or a local planning
  flow) needs to regenerate it. Subagents also twice removed the transient `.playwright-mcp/`
  browser-artifact dir — consider gitignoring it.
- **Pointer-handshake gap (needs a decision before customer rollout)**:
  `upstream/scripts/altium/Main.pas` hardcodes the machine-global pointer path, while the fork
  confines the pointer to the workspace. The bridge halves may not meet on a clean customer
  machine — recorded in the runbook troubleshooting and the SECURITY_REVIEW residuals; options
  are a logged `upstream/` patch (PROVENANCE row, re-review trigger) or an install-time step.
- **Known residuals** (accepted, listed in the SECURITY_REVIEW addendum): L3–L6.
- **CI/process proposals (not built)**: mypy `integrations/mcp/*/solus/` in CI (currently
  H8-local only); a CODEOWNERS row for `packages/companion/`; `@lane-workspace` reviewer for
  the desktop UI files; kicad README's stale "T1b, coming" note; recurring mypy-cache
  INTERNAL ERRORs under concurrent sessions (worked around via cache clears).
