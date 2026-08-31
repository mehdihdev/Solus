# Completion Report — SOLUSDEV-166: the `.solus` two-layer local state (Ticket A)

**Branch:** `SOLUSDEV-166-solus-folder-design` (ready for human review; not pushed).
**Status:** Ticket A complete and verified. Tickets B–E remain planned (design doc lists them).

## What was built

The machine-local layer of the `.solus` design (ADR-034): a `~/.solus/projects.json` project→folder
registry the Electron **main process** owns and reads, which finally writes `SOLUS_COMPANION_WORKSPACE`
at companion spawn — closing the long-standing Altium fail-closed gap (the link previously lived only
in renderer localStorage, unreadable from main).

- **ADR-034** added to DECISIONS.md (tier-2, ratified in-session, dedicated commit).
- **Contract**: `ProjectRegistry`/`ProjectFolderLink` in `packages/shared-types` (TS) and
  `solus_contracts` (Python), cross-validated against shared fixtures with an alias-based
  `_fields.json` drift manifest. `docs/contracts/local-state.md` documents the schema and rules.
- **Registry library** (`apps/desktop/src/main/localState.ts`): read/link/unlink/workspace, atomic
  temp+rename writes, 0700 dir / 0600 file, "newer schema_version ⇒ read-only", corrupt-degrades-to-empty.
- **IPC** `folder:link` / `folder:unlink` / `folder:links` (sender-gated like billing/bridge; inputs
  validated). `projectFolderStore` became a write-through display cache with startup hydration.
- **Companion spawn** derives `SOLUS_COMPANION_WORKSPACE` from the registry and respawns when the
  active project's link changes (only when the resolved workspace actually changed).
- **Companion 0700**: `~/.solus` is tightened on every load (scoped to the Solus home only).

## Governing docs consulted

DECISIONS.md (ADR-021/027/030/032, new ADR-034), `docs/architecture/solus-folder.md` (the design,
authored under this ticket and updated to "Ticket A implemented"), `docs/contracts/*`, `apps/desktop/CLAUDE.md`,
`docs/CAPABILITIES.md` (the gap this fixes).

## Tests & verification

- Desktop: **1417** vitest pass; `pnpm typecheck` clean.
- Python: **222** pass (companion + contracts); ruff + mypy clean (added `py.typed` to `solus_contracts`).
- shared-types: **176** pass; `tsc` clean.
- Two Phase-4 reviewers (code + security) run on the diff; findings fixed and re-verified across two
  rounds (see below).

## Security review outcome

Two mandatory reviewers ran; the security reviewer initially returned FAIL, then FAIL again on the
first fix round. Both rounds' blocking findings were fixed and re-verified:

- **C1 (path → `SOLUS_MCP_WORKSPACE` injection / over-broad fork confinement)**: workspace paths are
  canonicalized (realpath) and rejected if they carry control chars, resolve to root/home/`~/.solus`,
  or (on Windows only) contain the cmd.exe metacharacter class; validated at BOTH the write boundary
  and the read boundary (the registry file is fork-writable, so the sink is the real trust boundary).
- **H2 (clone-URL credentials on a fork-readable file)**: `repoUrl` userinfo is stripped on write and
  on read (legacy files cleaned); ssh `git@` preserved.
- **L7 (`__proto__`/`constructor`/`prototype` ids)**: rejected at every write and read boundary in
  both languages; null-prototype maps; shared reserved-id fixture asserted by both suites.
- **Companion 0700 gap, M4/M5/M6, size cap**: all addressed.

## Decisions made under delegated judgment

- **Tier-2 approvals obtained in-chat**: ADR-034 text, the local-state contract shapes, and the
  `solus_contracts/py.typed` marker. The Python reserved-id validator and the `emptyProjectRegistry`
  null-prototype change are security hardening of the same in-session-approved contract code, flagged
  here for the MR reviewer.
- **Ticket A scope**: shipped the full doc scope (TS + Python libs + contracts) per the answered
  design-review question. The Python `~/.solus` _file-writing_ library is not built — the companion
  only reads the shape today; writing stays desktop-main-owned per ADR-034.
- **M4/M5 (companion supervision)**: fixed in code but not unit-tested in vitest, matching the
  documented policy in `companion.test.ts` (process supervision is validated on the packaging
  checklist, not vitest). Flagged for awareness.

## Known follow-ups (non-blocking, noted for a human)

- On Windows, a folder whose name contains a cmd metacharacter (`C:\R&D\rover`) is refused as a
  workspace and the failure is currently silent (`{ ok: false }` with no reason surfaced). A
  discriminated result + a renderer toast would improve the UX; deferred to avoid renderer-plumbing
  scope creep in this ticket.
- `integrations/mcp/altium/bin/launch.cmd` interpolates `SOLUS_MCP_WORKSPACE` unquoted; the desktop
  now sanitizes the value at the boundary, but hardening `launch.cmd` itself (delayed expansion) is a
  provenance-touching change for a human to make.
- `companionEnv.ts` lets an explicit inherited `SOLUS_COMPANION_WORKSPACE` override the validated
  registry value (a deliberate operator escape hatch); it is not re-validated. Operator-set env is
  trusted input, but noted.

## Handoff artifacts

- Integrated feature branch, full validation green.
- `docs/qa/COWORK_QA_solus-folder-registry.md` — self-sufficient user-flow test plan.
- This report.
