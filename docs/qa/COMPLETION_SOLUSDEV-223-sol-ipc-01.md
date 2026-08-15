# Completion report — SOLUSDEV-223 (SOL-IPC-01): main↔renderer IPC push channel

**Lane:** C (SOLUSDEV-68, branch `SOLUSDEV-68-SOL-Reasoning`) · **Date:** 2026-08-08
**Scope:** the wire only. No orb behaviour, no overlay window (those are SOLX-02 / LANE D).

## What was built

The app's first push-shaped IPC, typed end to end over the CTR-06 contract:

- `apps/desktop/src/main/sol-window/orbOverlayWire.ts` — `attachOrbOverlayWire(win, ipc)`: validated pushes to one window (`pushToOrb` / `pushToOverlay`), validated subscriptions from that window only (`onOrbToOverlay` / `onOverlayToOrb`, sender-filtered by `webContents.id`), and teardown bound to the window's `closed` event. Electron is injected as structural slices (`WireWindow`, `WireIpc`) — the companion.ts pattern — so every behaviour is unit-testable without a BrowserWindow; a compile-time assertion in the test proves `BrowserWindow`/`ipcMain` satisfy the slices.
- `apps/desktop/src/preload/orbOverlayBridge.ts` — `createOrbOverlayBridge(ipcRenderer)`: the renderer surface, both sides of the conversation (orb: `publishToOverlay`/`onOverlayToOrb`; overlay, for LANE D: `publishToOrb`/`onOrbToOverlay`). Subscriptions return unsubscribe functions for component-lifecycle cleanup.
- `apps/desktop/src/preload/index.ts` — exposes the bridge as `window.solus.orbOverlay`. **`window.api` was frozen, not extended**: `api` (the legacy shape) and `solus` (`api` + `orbOverlay`) are now separate objects, since both globals previously aliased one object and adding to it would have grown the vestigial surface. `SolusBridge` now derives from `solus`.

## Acceptance → evidence

| Acceptance                                                  | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Push received and validated in the renderer, and vice versa | `orbOverlayWire.test.ts` (outbound/inbound suites), `orbOverlayBridge.test.ts` (publish/subscribe suites); both assert the delivered object is the parser's fresh rebuild, never the sender's reference. Live round-trip under `contextIsolation`: Cowork QA (see below) — deliberately deferred to when a consumer attaches the wire, matching repo precedent (companion supervision is checklist-verified, not vitest). |
| Malformed message rejected at the boundary, with a test     | Both test files: malformed inbound → handler never runs, rejection observable via injected `onMalformed`; malformed **outbound** throws (a bug in our own process is loud, not dropped).                                                                                                                                                                                                                                  |
| Listeners removed on window close                           | `orbOverlayWire.test.ts` teardown suite: `closed` → every `ipcMain` listener removed, pushes return `false`, late subscribe throws; `detach()` idempotent.                                                                                                                                                                                                                                                                |
| Channel names from constants, no repeated literals          | Both modules import `ORB_OVERLAY_CHANNELS`; a **ratchet test** (`orbOverlayWire.test.ts`, "channel-literal ratchet") scans `src/main/` + `src/preload/` sources and fails on any `orb-overlay:` string literal.                                                                                                                                                                                                           |
| Loopback stubs remain the unit-test path                    | `packages/shared-types/**` untouched (tier-2; no change was needed).                                                                                                                                                                                                                                                                                                                                                      |
| Surface on `window.solus`, typed; nothing on `window.api`   | `preload/index.ts`: `orbOverlay` exists only on the `solus` object; `api` frozen at the legacy shape.                                                                                                                                                                                                                                                                                                                     |

## Verification

- Desktop suite: **102 files / 659 tests, all passing** (includes the 20 new tests). `typecheck:node`, `typecheck:web`, eslint: clean.
- Phase-4 code review + security review subagent passes run on the staged diff; findings addressed before commit (see the commit for the final state).

## Decisions under delegated judgment

1. **Attach-on-demand, no eager wiring in `main/index.ts`.** Nothing attaches the wire today because nothing produces or consumes handoff messages yet — SOLX-02 attaches it to the orb's window, LANE D to the overlay's. Wiring it to the main window now would be dead code with no observable behaviour.
2. **The bridge carries both sides** (orb and overlay directions) so LANE D's overlay window uses the same preload surface without touching preload again.
3. **`window.api`/`window.solus` de-aliased** (see above) — the letter of "do not add to window.api" required splitting the two exposures. `window.api` consumers: zero (audited), so no behaviour change.
4. **Sender filtering by `webContents.id`** — a wire speaks for exactly one window; messages from any other renderer are ignored (and a hostile renderer cannot inject into another window's wire).

## Phase-4 review findings and their resolutions

Code review: APPROVE (0 critical/high). Security review: initial FAIL — resolved as follows, final suite 666/666 green.

**Fixed in this diff** (all in-lane):

- **H1 (memory amplification):** the contract's unknown-type error interpolates the sender's `type` field before any cap; a megabyte `type` produced a megabyte Error in main (empirically confirmed by the reviewer). Fixed wire-side: a `screenType` guard refuses `type` fields over 64 chars before the parser ever sees them, in both wire and bridge, with tests asserting the resulting error stays under 256 chars. **Proposed LANE 0 follow-up:** the one-line root fix in `orb-overlay.ts` (`String(m.type).slice(0, 64)` in both `default:` branches) — tier-2, needs human approval, benefits every future consumer.
- **M1 (log injection) + M6 (log flooding):** the default malformed-message logger now strips control characters (a hostile payload cannot forge log lines like "user confirmed flash") and throttles to 5 reports per channel per wire. Tested.
- **M2 (destroyed-webContents crash):** the inbound filter captures `webContents.id` at attach and never touches `win.webContents` afterwards — after a renderer crash the old code would have thrown inside a process-global ipcMain listener. Tested with a fake whose `webContents` getter throws.
- **Code-review MEDIUM + L1 (lifecycle):** attaching to an already-destroyed window now yields an inert wire (no listener can ever leak), and `detach()` removes the `closed` hook so re-attachment does not accumulate window listeners. One-wire-per-window documented. Tested.
- **L2:** prototype-pollution fixture added (`__proto__`-smuggling payload delivered clean, `Object.prototype` untouched).

**Explicitly NOT fixed here — recorded obligations on the consumers** (the security reviewer's sanctioned alternative; the wire cannot know a handoff or tenant):

- **H2:** the wire authenticates the _window_, not the handoff or tenant. Binding inbound messages to the active `handoffId`/`projectId` — and the cross-handoff isolation test — is the SOLX-02 orb router's obligation (and LANE D's on their side). Stated in the `orbOverlayWire.ts` header docstring; carried into the SOLX-02 task spec.
- **M3:** sender filtering is per-webContents, sound while the CSP stays `default-src 'self'`; the code comment binds the assumption so a CSP/frame change trips review.
- **M4:** both bridge roles are exposed to every renderer; role-gating the preload surface belongs to the ticket that creates the second window (LANE D / SOLX-02).
- **M7:** GuideStep text and `failed.reason` are untrusted content end-to-end: render as text only, wrap as data before prompt assembly, red-team fixtures at those sites — obligations stated in the wire docstring, owed by SOLX-02/LANE D.

## Deviations / flags for humans

- **Preload files are outside LANE C's CODEOWNERS paths** (`src/preload/` is not in the lane's six entries). The ticket text explicitly directs the preload change ("The renderer surface goes on `window.solus`, typed"), so I treated the ticket as the sanction. Flagging per the lane charter's cross-lane rule.
- **H9 hook noise**: `vitest run --silent <file>` is incompatible with vitest 3's CLI parsing (documented in `apps/desktop/CLAUDE.md` as a known harness gap). Verified with `npx vitest related --run` (what the H10 gate uses) instead. Do not edit hooks; a human should fix H9's flag.
- **This worktree had no `node_modules`** — ran `pnpm install --frozen-lockfile` (lockfile unchanged).
- The pre-existing H10 full-suite failures (companion supervisor / bridge e2e / MCP vendor hygiene, 15 tests) are unrelated to this diff and pre-date it; the session-level `VIRTUAL_ENV` export from `/home/beeboss/Solus/.venv` hijacks Python runs in this worktree (see Phase 0 report §2.10).

## Governing docs consulted

`docs/contracts/orb-overlay.md` (normative wire rules) · `packages/shared-types/src/orb-overlay.ts` (frozen contract) · SOLUSDEV-223 ticket text · `apps/desktop/CLAUDE.md` · root CLAUDE.md §7 (untrusted IPC input) · DECISIONS.md ADR-032 (tier boundaries).
