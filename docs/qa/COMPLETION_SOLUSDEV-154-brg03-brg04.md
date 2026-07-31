# Completion Report — SOLUS-BRG-03 + SOLUS-BRG-04 (SOLUSDEV-162/163 on SOLUSDEV-154)

## BRG-03 — detect / surface / degrade / reconnect

- **Status frames** (schema now in `docs/contracts/bridge-protocol.md` Addendum B; closes the contract's BRG-03 hole):
  snapshot-not-delta, per-SERVER busy from real in-flight counters, coalesced ≥1 s + one snapshot
  after every `hello_ack`, ≤512-char §6-hygienic details. Cloud validates strictly, filters
  unknown server names against the allowlist roster, caches on the session (dies with it);
  dispatch never gates on the cache — advisory, UI-facing.
- **`GET /api/v1/projects/{project_id}/bridge`** (ProjectCtx; per-user semantics — you see YOUR
  companion; non-member 404). The three AC states surface as: no session → `connected:false`
  ("bridge offline"); session + `not_launched/launching/error` → "tool not launched"; `busy` →
  "tool busy". `ToolErrorCode.UNAVAILABLE` added (pre-sanctioned contract extension; W0-04 enum
  lock-test updated; **ratification = humans**, see paste files) — BridgeTool's offline fail-fast
  now machine-readable.
- **UI**: TopBar `BridgePill` (offline/ready/busy/attention + per-server popover) fed by
  `useBridgeStatus` (10 s poll, offline-gated); typed via `resources.ts` + regenerated schema.
- **No-dupe resync gate** (`tests/test_bridge_resync.py`): same-sync-twice idempotent (ids +
  versions stable, 0 created/updated), modified resync updates in place + tombstones (ADR-027),
  reappearing entity keeps exactly one live row (partial-unique end-to-end). Combined with §5's
  "companion never buffers across reconnects", reconnect+resync cannot duplicate entities.
- **Deferred (flagged, per plan)**: the live-MCP-acquisition → committed-export fallback flow and
  per-source "degraded" badges belong to the per-tool connector tickets (MCP-04 amendment
  governs); auto-TRIGGERED resync on tool return is v1-deferred (availability restoration + the
  idempotency gate satisfy the AC).

## BRG-04 — bundle into Electron (unsigned)

- **Runtime**: `main/companion.ts` — single-flight detached spawn, equal-jitter backoff
  (1 s→30 s, reset after 60 s stable), pidfile orphan-tree reap on start, SIGTERM→3 s→SIGKILL
  group stop on `before-quit`; `requestSingleInstanceLock` (two apps can't duel companions);
  stdin token relay `preload bridge.setToken ← authStore.setSession` — access tokens ride
  IPC+stdin only, never argv/log; **refresh tokens never leave the renderer** (more conservative
  than contract §2 — recorded as a contract note). Companion side: env token now OPTIONAL when a
  stdin relay is attached (empty TokenBox idles the channel; first token line starts dialing).
- **Packaging**: `scripts/build-companion.sh` + `make companion-bin` — PyInstaller onefile
  **verified on this Linux ARM box** (47 MB `dist/companion/solus-companion` builds and boots to
  config validation, proving websockets/mcp/pydantic bundle) + vendored `integrations/mcp/`
  rsync; `electron-builder.yml` `extraResources: dist/companion → companion`; signing = build-time
  env (CSC_LINK / notarize) — the final swappable step, external blocker (certs/entity).
  Auto-update honest v1: companion + vendored servers ship inside app releases; protocol `4400`
  close = "update required"; electron-updater stays unwired (no feed — SOLUSDEV-148/149).
  Clean-uninstall + per-OS notes: `apps/desktop/docs/companion-packaging.md`.
- **electron-builder × pnpm blocker RESOLVED (2026-07-30)**: root causes were (a) a stray
  `apps/desktop/pnpm-workspace.yaml` shadowing the root workspace (broke every pnpm call from
  the app dir — "packages field missing or empty"; its build-script allowances moved to the root
  file) and (b) electron-builder 26.0.12's pnpm dependency collector failing on the symlinked
  store (upgraded to 26.15.3); plus `linux.executableName: solus` (the package name is not a
  valid binary name). `solus-1.0.0.AppImage` (170 MB) now builds with the companion + vendored
  MCP tree in `resources/companion/`. Runtime steps 3–6 of the checklist need a display —
  human-run. Win/mac: config + docs only this cycle (per ticket).
- **⚠ Pre-existing package-wide `lint` failures** in six renderer data hooks (react-hooks v7
  rules) — untouched by this work; all files touched here are lint-clean. Flagged for a human.

## Verification (epic close)

`solus_test_brg`: **1120 passed, 3 skipped** (api + companion; +8 status/resync/UNAVAILABLE since
iteration 1). Desktop: **552 vitest passed**, typecheck green. `ruff` clean repo-wide;
`mypy --strict` clean (226 files). Commits `96b85e9`, `9cff0b0`, `2eb4e61` (+ iteration-1 set).

## Human actions (adds to the iteration-1 list)

1. ~~Paste + ratify~~ DONE 2026-07-30 under ADR-032: `docs/contracts/bridge-protocol.md` landed
   (contract + hello-inventory + status-frame addendums), `UNAVAILABLE` ratified in
   `docs/contracts/agent-tool.md`, ADR-031 → Accepted, temp files deleted.
2. ~~electron-builder × pnpm~~ FIXED 2026-07-30 (commit 5b3a2b7; see the RESOLVED bullet above).
3. Linux AppImage RUNTIME checklist steps 3–6 (companion-packaging.md) — needs a display; win/mac
   builds on their native runners.

## Phase-4 review outcome (post-close addendum)

Fresh-context security-reviewer (verdict FAIL: 1 HIGH/4 MED/3 LOW) and code-reviewer (WARN:
1 HIGH/2 MED) ran on `ad89a23..HEAD`; every finding was FIXED, not noted:

- **SEC-H1** requires_confirmation was enforced nowhere → central gate `confirmation_refusal`
  in `agent/runtime.py`, consulted by ScaffoldRunner before every dispatch — destructive tools
  are structurally un-dispatchable until a real confirmation UX ships. **Any new runner
  (SOL-01/02) MUST consult this gate — merge-blocker.** Tests added.
- **CR-H1** concurrent MCP-server revive raced in the companion supervisor (orphaned child +
  state stomp) → per-handle asyncio.Lock serializing start/stop/restart + concurrent-crash test.
- **SEC-M1** pre-auth per-IP connect throttle before any signature verification (4429) + test.
- **SEC-M2** companion refuses to send the bearer to non-allowlisted hosts
  (`SOLUS_COMPANION_ALLOWED_HOSTS`; default localhost-only; packaged pinning → SOLUSDEV-148/149).
- **SEC-M3** `ToolError.message` now redacted at ingress (`redact_text`) + test.
- **SEC-M4** duplicate advertised tools deduped (first-wins) — no more registry crash + test.
- **CR-M1** team-cap TOCTOU closed (synchronous re-check at bind).
- **CR-M2** pidfile reap verifies the PID looks like a companion (/proc cmdline; win32 skips).
- **SEC-L1** RecursionError from nested JSON → dropped violation + test. **SEC-L2** launch guard
  now executes the RESOLVED path. **SEC-L3** (context-size budget for tool output) deferred to
  the ADR-019 budget seam — flagged, not fixed here.

Post-fix gates: 1127 pytest (api) + 76 (companion) on solus_test_brg, 555 vitest, ruff +
mypy --strict clean.
